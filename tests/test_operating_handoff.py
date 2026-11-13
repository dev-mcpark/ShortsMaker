"""Real local clocks/ledgers; provider planning and uploads remain offline."""

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from scripts.operate_schedule import run_scoped
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services import scheduled_planning
from shorts_maker.services.operating_status import operator_status, schedule_sha256
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.services.operating_budget import begin_episode, episode_environment, episode_path, load_episode
from shorts_maker.services.production_service import ProductionResult, script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager


class OperatingHandoffTests(unittest.TestCase):
    def revision_fixture(self):
        from test_gui_creation_flows import script
        record = self.queued_episode()
        original = script()
        current = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'script_review_pending', 'last_script': original.model_dump(mode='json')})
        modified = original.model_copy(update={'title': '수정 대본'})
        return record, current, original, modified

    def revise(self, current, modified, **options):
        return self.manager.revise_pending_script(current['id'], modified.model_dump(mode='json'),
            expected_schedule_sha256=options.get('expected', schedule_sha256(current)),
            reviewed_script_sha256=options.get('receipt', script_draft_key(modified)))

    def test_reviewed_revision_preserves_episode_costs_and_enables_exact_video_attachment(self):
        record, current, original, modified = self.revision_fixture()
        reservation = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        google_budget.mark_google_result(reservation, 'failed')
        original_file = episode_path(record['id']).with_suffix('.script.json')
        original_file.write_text(original.model_dump_json(indent=2))
        paths = [episode_path(record['id']), google_budget._database_path(), openai_budget._database_path(), original_file]
        before = [p.read_bytes() for p in paths]
        video = settings.output_dir / 'revision.mp4';video.write_bytes(b'local fixture')
        report = {'schema_version': 1, 'video_path': str(video), 'source_url': modified.source_url,
                  'script_sha256': script_sha256(modified.model_dump(mode='json')), 'quality_passed': True,
                  'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'youtube_id': 'fixture_private',
                  'youtube_upload_request': {'status': {'privacyStatus': 'private'}}, 'uploaded_at_utc': '2026-11-11T00:00:00Z'}
        video.with_suffix('.production.json').write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(current['id'], str(video))
        revised = self.revise(current, modified)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertEqual(revised['last_episode_id'], current['last_episode_id'])
        self.assertEqual(revised['run_count'], current['run_count'])
        self.assertEqual(revised['last_result'], 'script_review_pending')
        self.assertFalse(revised['enabled'])
        self.assertNotIn('last_youtube_id', revised)
        self.assertEqual(revised['script_revisions'][0]['script'], original.model_dump(mode='json'))
        self.assertEqual(revised['script_revisions'][0]['script_path'], str(original_file))
        replacement = Path(revised['last_script_path'])
        self.assertNotEqual(replacement, original_file)
        self.assertEqual(json.loads(replacement.read_text()), modified.model_dump(mode='json'))
        self.assertEqual(operator_status(revised)['planned_script_path'], str(replacement))
        self.assertEqual(self.manager.pending_video_info(current['id'], str(video))['youtube_id'], 'fixture_private')
        report['script_sha256'] = script_sha256(original.model_dump(mode='json'))
        video.with_suffix('.production.json').write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(current['id'], str(video))
        replacement.write_text('{}')
        status = operator_status(revised)
        self.assertIsNone(status['planned_script_path'])
        self.assertIn('planned_script_error', status)
        for pointer in ('', None, str(self.root / 'outside.json')):
            status = operator_status({**revised, 'last_script_path': pointer})
            self.assertIsNone(status['planned_script_path'])
            self.assertIn('planned_script_error', status)

    def test_revision_file_failure_preserves_current_schedule_and_history(self):
        _, current, _, modified = self.revision_fixture()
        before = self.manager.filename.read_bytes()
        with patch('shorts_maker.services.script_store.os.fsync', side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):
                self.revise(current, modified)
        self.assertEqual(self.manager.filename.read_bytes(), before)
        self.assertEqual(list((settings.output_dir / 'evaluation/scheduled_script_revisions').glob('*.tmp')), [])

    def test_revision_rejects_stale_review_and_changed_source_without_mutating_schedule(self):
        _, current, _, modified = self.revision_fixture()
        before = self.manager.filename.read_bytes()
        for script, options in ((modified, {'expected': 'stale'}), (modified, {'receipt': 'unreviewed'}),
                                (modified.model_copy(update={'source_url': 'https://example.com/other'}), {})):
            with self.assertRaises(ValueError):
                self.revise(current, script, **options)
            self.assertEqual(self.manager.filename.read_bytes(), before)

    def test_attached_enabled_rejected_and_uncertain_operation_cannot_be_revised(self):
        record, current, _, modified = self.revision_fixture()
        for changes in ({'last_youtube_id': 'existing_video'}, {'last_video_path': '/kept.mp4'},
                        {'enabled': True}, {'last_result': 'script_rejected'}):
            self.manager.save_schedules([{**current, **changes}])
            changed = self.manager.get_schedule(current['id']);before = self.manager.filename.read_bytes()
            with self.assertRaises(ValueError):
                self.revise(changed, modified)
            self.assertEqual(self.manager.filename.read_bytes(), before)
        self.manager.save_schedules([current])
        marker = episode_path(record['id']).with_suffix('.operation.pending.json')
        marker.write_text('unknown request')
        with self.assertRaises(ValueError):
            self.revise(current, modified)
        self.assertEqual(marker.read_text(), 'unknown request')

    def test_paid_execution_lock_blocks_revision_until_the_other_child_finishes(self):
        _, current, _, modified = self.revision_fixture()
        lock = self.manager.filename.with_name(self.manager.filename.name + '.lock.sqlite3')
        with closing(sqlite3.connect(lock, isolation_level=None)) as db:
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaisesRegex(ValueError, '실행'):
                self.revise(current, modified)
        self.assertEqual(self.revise(current, modified)['last_script']['title'], modified.title)

    def test_revision_history_is_append_only_noop_safe_and_moves_with_its_original_run(self):
        _, current, original, modified = self.revision_fixture()
        revised = self.revise(current, modified)
        before = self.manager.filename.read_bytes()
        self.assertEqual(self.revise(revised, modified), revised)
        self.assertEqual(before, self.manager.filename.read_bytes())
        newest = modified.model_copy(update={'title': '세 번째 대본'})
        second = self.revise(revised, newest)
        self.assertEqual(len(second['script_revisions']), 2)
        self.assertEqual(second['script_revisions'][0]['script'], original.model_dump(mode='json'))
        damaged = {**second, 'script_revisions': [*second['script_revisions'], {}]}
        self.manager.save_schedules([damaged]);before = self.manager.filename.read_bytes()
        with self.assertRaises(ValueError):
            self.revise(damaged, newest.model_copy(update={'title': '아직 저장하면 안됨'}))
        self.assertEqual(self.manager.filename.read_bytes(), before)
        self.manager.save_schedules([second])
        next_run = self.manager.update_schedule(current['id'], {
            'run_count': current['run_count'] + 1, 'last_run': datetime.now().isoformat(), 'last_result': 'operator_pending'})
        self.assertNotIn('script_revisions', next_run)
        self.assertEqual(next_run['run_history'][-1]['script_revisions'], second['script_revisions'])

    def test_uncertain_upload_blocks_replacing_the_draft_and_preserves_both_files(self):
        _, current, original, modified = self.revision_fixture()
        marker = settings.output_dir / 'unknown.upload-pending.json';marker.write_text('unverified')
        report = settings.output_dir / 'unknown.production.json'
        report.write_text(json.dumps({'script_sha256': script_sha256(original.model_dump(mode='json'))}))
        before = [p.read_bytes() for p in (self.manager.filename, marker, report)]
        with self.assertRaisesRegex(ValueError, '업로드'):
            self.revise(current, modified)
        self.assertEqual(before, [p.read_bytes() for p in (self.manager.filename, marker, report)])

    def pending_schedule(self):
        return self.manager.update_schedule(self.schedule['id'], {
            'enabled': False, 'last_result': 'operator_pending', 'run_count': 1})

    def test_concurrent_first_planning_creates_one_baseline_and_one_child(self):
        self.pending_schedule()
        entered, release = Event(), Event()
        records = []
        def begin(*args):
            record = begin_episode(*args)
            records.append(record['id'])
            entered.set()
            self.assertTrue(release.wait(5))
            return record
        def invoke():
            return run_scoped(self.manager, self.schedule['id'], [sys.executable, '-c', 'pass'], planning=True)
        with patch('scripts.operate_schedule.begin_episode', side_effect=begin), \
                patch('scripts.operate_schedule.subprocess.run', return_value=SimpleNamespace(returncode=0)) as child:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(invoke)
                try:
                    self.assertTrue(entered.wait(5))
                    with self.assertRaises(sqlite3.OperationalError):
                        pool.submit(invoke).result(timeout=5)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5), 0)
            child.assert_called_once()
        self.assertEqual(len(records), 1)
        self.assertEqual(self.manager.get_schedule(self.schedule['id'])['last_episode_id'], records[0])

    def test_planning_snapshot_recheck_happens_before_baseline_or_child(self):
        expected = self.pending_schedule()
        before = self.manager.filename.read_bytes()
        with patch('scripts.operate_schedule.begin_episode') as begin, patch('scripts.operate_schedule.subprocess.run') as child:
            with self.assertRaises(ValueError):
                run_scoped(self.manager, expected['id'], [sys.executable, '-c', 'pass'],
                           planning=True, expected_schedule_sha256='old dialog')
            begin.assert_not_called()
            child.assert_not_called()
        self.assertEqual(before, self.manager.filename.read_bytes())

    def test_studio_planning_preflight_reads_current_room_without_creating_episode(self):
        expected = self.pending_schedule()
        before = self.manager.filename.read_bytes()
        with patch.object(settings, 'paid_production_enabled', True):
            room = scheduled_planning.planning_preflight(self.manager, expected)
            self.assertEqual(room, {'google_remaining_krw': 3000, 'openai_remaining_usd': .30})
            self.assertNotIn('last_episode_id', self.manager.get_schedule(expected['id']))
            self.manager.update_schedule(expected['id'], {'name': 'changed since preview'})
            with self.assertRaises(ValueError):
                scheduled_planning.planning_preflight(self.manager, expected)
        self.assertNotEqual(before, self.manager.filename.read_bytes())

    def test_studio_planning_runs_only_fixed_existing_scoped_command(self):
        from test_gui_creation_flows import script
        expected = self.pending_schedule()
        def child(command, **kwargs):
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[-4:], ['plan', expected['id'], '--expected-schedule-sha256', schedule_sha256(expected)])
            self.assertNotIn('shell', kwargs)
            self.manager.update_schedule(expected['id'], {'last_result': 'script_review_pending',
                                                          'last_script': script().model_dump(mode='json')})
            return SimpleNamespace(returncode=0, stderr='', stdout='')
        with patch.object(settings, 'paid_production_enabled', True), \
                patch.object(scheduled_planning.subprocess, 'run', side_effect=child) as process:
            result = asyncio.run(scheduled_planning.plan_pending_schedule(self.manager, expected))
            self.assertEqual(result['last_result'], 'script_review_pending')
            process.assert_called_once()
        self.assertNotIn('last_youtube_id', result)

    def test_studio_planning_gate_and_unknown_result_do_not_launch_or_retry(self):
        record = self.queued_episode()
        expected = self.manager.get_schedule(self.schedule['id'])
        with patch.object(scheduled_planning.subprocess, 'run') as child:
            with patch.object(settings, 'paid_production_enabled', False):
                with self.assertRaises(RuntimeError):
                    asyncio.run(scheduled_planning.plan_pending_schedule(self.manager, expected))
            pending = episode_path(record['id']).with_suffix('.operation.pending.json')
            pending.write_text('unreconciled')
            with patch.object(settings, 'paid_production_enabled', True):
                with self.assertRaises(ValueError):
                    asyncio.run(scheduled_planning.plan_pending_schedule(self.manager, expected))
            child.assert_not_called()
        self.assertEqual(pending.read_text(), 'unreconciled')

    def test_studio_planning_auth_failure_is_actionable_and_not_retried(self):
        expected = self.pending_schedule()
        result = SimpleNamespace(returncode=1, stderr='YOUTUBE_AUTH_REQUIRED: fixture', stdout='')
        with patch.object(settings, 'paid_production_enabled', True), \
                patch.object(scheduled_planning.subprocess, 'run', return_value=result) as child:
            with self.assertRaisesRegex(RuntimeError, 'YOUTUBE_AUTH_REQUIRED'):
                asyncio.run(scheduled_planning.plan_pending_schedule(self.manager, expected))
            child.assert_called_once()
        self.assertEqual(self.manager.get_schedule(expected['id']), expected)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for target, value in (
            ('output_dir', self.root / 'outputs'), ('google_monthly_budget_krw', 10000),
            ('google_budget_month', '2026-10'), ('google_budget_opening_krw', 3000),
            ('google_usd_krw_rate', 2000), ('openai_monthly_budget_usd', 1.0),
            ('openai_budget_month', '2026-10'), ('openai_budget_opening_usd', .2),
            ('paid_production_enabled', False),
        ):
            p = patch.object(settings, target, value)
            p.start()
            self.addCleanup(p.stop)
        for module in (google_budget, openai_budget):
            p = patch.object(module, '_period', return_value='2026-10')
            p.start()
            self.addCleanup(p.stop)
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        self.manager = ScheduleManager(str(self.root / 'schedules.json'), queue_only=True)
        self.schedule = self.manager.create_schedule('Bounded operator', '19:00', frequency='Every 4 Weeks')
        self.manager.update_schedule(self.schedule['id'], {'review_operator': 'agent'})

    def queued_episode(self):
        first = datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None) - timedelta(seconds=1)
        self.manager.update_schedule(self.schedule['id'], {'first_run_at': first.isoformat()})
        asyncio.run(self.manager._execute_pipeline(self.schedule))
        queued = self.manager.get_schedule(self.schedule['id'])
        record = begin_episode(queued['id'], queued['run_count'])
        self.manager.update_schedule(queued['id'], {'last_episode_id': record['id']})
        return record

    def test_child_ceilings_stop_real_ledger_reservations(self):
        record = self.queued_episode()
        env, _ = episode_environment(record)
        with patch.object(settings, 'google_monthly_budget_krw', int(env['GOOGLE_MONTHLY_BUDGET_KRW'])):
            for _ in range(6):
                google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
            with self.assertRaisesRegex(RuntimeError, 'GOOGLE_BUDGET_EXCEEDED'):
                google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
        with patch.object(settings, 'openai_monthly_budget_usd', float(env['OPENAI_MONTHLY_BUDGET_USD'])):
            for _ in range(20):
                openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
            with self.assertRaises(openai_budget.OpenAIBudgetExceeded):
                openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
        _, current = episode_environment(record)
        self.assertEqual(current['google_remaining_krw'], 120)
        self.assertEqual(current['openai_remaining_usd'], 0)

    def test_month_rollover_preserves_episode_spend_and_old_rows(self):
        old = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
        record = self.queued_episode()
        google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
        openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
        with patch.object(google_budget, '_period', return_value='2026-11'), patch.object(
            openai_budget, '_period', return_value='2026-11',
        ):
            with self.assertRaisesRegex(RuntimeError, 'Google'):
                episode_environment(record)
            with patch.object(settings, 'google_budget_month', '2026-11'), patch.object(
                settings, 'openai_budget_month', '2026-11',
            ), patch.object(settings, 'google_budget_opening_krw', 0), patch.object(
                settings, 'openai_budget_opening_usd', 0,
            ):
                env, current = episode_environment(record)
                self.assertEqual(env['GOOGLE_MONTHLY_BUDGET_KRW'], '2520')
                self.assertAlmostEqual(float(env['OPENAI_MONTHLY_BUDGET_USD']), .285)
                self.assertEqual(current['google_new_reserved_krw'], 480)
        with closing(sqlite3.connect(google_budget._database_path())) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests WHERE id=?', (old,)).fetchone()[0], 1)
            db.execute('DELETE FROM requests WHERE id=?', (old,))
        with self.assertRaisesRegex(ValueError, '사라졌습니다'):
            episode_environment(record)

    def test_explicit_cap_extension_preserves_spend_and_future_default(self):
        record = self.queued_episode()
        self.assertEqual(record['openai_cap_micro_usd'], 300000)
        openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
        path = episode_path(record['id'])
        extended = {**record, 'openai_cap_micro_usd': 350000}
        path.write_text(json.dumps(extended))
        schedule = self.manager.get_schedule(self.schedule['id'])
        with self.assertRaisesRegex(ValueError, '사용자 승인'):
            load_episode(record['id'], schedule)
        extended['openai_cap_extension'] = {
            'previous_cap_micro_usd': 300000, 'approved_cap_micro_usd': 350000,
            'owner_approval': 'This episode only, $0.35 approved.',
        }
        path.write_text(json.dumps(extended))
        loaded = load_episode(record['id'], schedule)
        self.assertEqual(loaded['baseline'], record['baseline'])
        _, current = episode_environment(loaded)
        self.assertEqual(current['openai_new_reserved_usd'], .015)
        self.assertEqual(current['openai_remaining_usd'], .335)
        future = begin_episode('future-schedule', 1)
        self.assertEqual(future['openai_cap_micro_usd'], 300000)
        for changes in ({'openai_cap_micro_usd': 350001},
                        {'openai_cap_extension': {**extended['openai_cap_extension'], 'owner_approval': ''}},
                        {'openai_cap_extension': {**extended['openai_cap_extension'], 'approved_cap_micro_usd': 340000}}):
            path.write_text(json.dumps({**extended, **changes}))
            with self.assertRaises(ValueError):
                load_episode(record['id'], schedule)

    def test_followup_openai_extension_requires_both_approvals_and_keeps_history(self):
        record = self.queued_episode()
        openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
        previous = {'previous_cap_micro_usd': 300000, 'approved_cap_micro_usd': 350000,
                    'owner_approval': 'Previous one-episode approval'}
        followup = {'previous_cap_micro_usd': 350000, 'approved_cap_micro_usd': 450000,
                    'owner_approval': 'This episode only, $0.45 for text validation'}
        extended = {**record, 'openai_cap_micro_usd': 450000,
                    'openai_cap_extension': previous, 'openai_cap_extension_followup': followup}
        path = episode_path(record['id'])
        path.write_text(json.dumps(extended))
        loaded = load_episode(record['id'], self.manager.get_schedule(self.schedule['id']))
        self.assertEqual(loaded['baseline'], record['baseline'])
        self.assertEqual(loaded['openai_cap_extension'], previous)
        self.assertAlmostEqual(episode_environment(loaded)[1]['openai_remaining_usd'], .435)
        with patch.object(settings, 'openai_monthly_budget_usd', .22):
            env, _ = episode_environment(loaded)
            self.assertEqual(env['OPENAI_MONTHLY_BUDGET_USD'], '0.22')
        self.assertEqual(begin_episode(record['schedule_id'], 2)['openai_cap_micro_usd'], 300000)
        for changes in (
            {'openai_cap_extension': None}, {'openai_cap_extension_followup': None},
            {'openai_cap_micro_usd': 450001},
            {'openai_cap_extension_followup': {**followup, 'owner_approval': ''}},
            {'openai_cap_extension_followup': {**followup, 'previous_cap_micro_usd': 300000}},
        ):
            path.write_text(json.dumps({**extended, **changes}))
            with self.assertRaises(ValueError):
                load_episode(record['id'], self.manager.get_schedule(self.schedule['id']))

    def test_video_comparison_extension_retains_all_previous_approvals(self):
        record = self.queued_episode()
        google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
        openai_budget.reserve_openai_speech('tts-1', 'a' * 1000)
        old_google = {'previous_cap_krw': 3000, 'approved_cap_krw': 3300, 'owner_approval': 'Earlier media'}
        old_openai = {'previous_cap_micro_usd': 300000, 'approved_cap_micro_usd': 350000,
                      'owner_approval': 'Earlier validation'}
        followup = {'previous_cap_micro_usd': 350000, 'approved_cap_micro_usd': 450000,
                    'owner_approval': 'Earlier text comparison'}
        approval = {'previous_google_cap_krw': 3300, 'approved_google_cap_krw': 6300,
                    'previous_openai_cap_micro_usd': 450000, 'approved_openai_cap_micro_usd': 500000,
                    'owner_approval': 'New video comparison approved'}
        extended = {**record, 'google_cap_krw': 6300, 'openai_cap_micro_usd': 500000,
                    'google_cap_extension': old_google, 'openai_cap_extension': old_openai,
                    'openai_cap_extension_followup': followup, 'video_comparison_extension': approval}
        path = episode_path(record['id'])
        path.write_text(json.dumps(extended))
        schedule = self.manager.get_schedule(self.schedule['id'])
        loaded = load_episode(record['id'], schedule)
        self.assertEqual(loaded['baseline'], record['baseline'])
        self.assertEqual(loaded['openai_cap_extension_followup'], followup)
        self.assertEqual(loaded['google_cap_extension'], old_google)
        _, status = episode_environment(loaded)
        self.assertEqual(status['google_new_reserved_krw'], 480)
        self.assertAlmostEqual(status['openai_remaining_usd'], .485)
        with patch.object(settings, 'google_monthly_budget_krw', 2000), patch.object(
                settings, 'openai_monthly_budget_usd', .2):
            env, _ = episode_environment(loaded)
            self.assertEqual(env['GOOGLE_MONTHLY_BUDGET_KRW'], '2000')
            self.assertEqual(env['OPENAI_MONTHLY_BUDGET_USD'], '0.2')
        future = begin_episode(record['schedule_id'], 2)
        self.assertEqual((future['google_cap_krw'], future['openai_cap_micro_usd']), (3000, 300000))
        for changes in (
            {'google_cap_extension': None}, {'openai_cap_extension_followup': None},
            {'video_comparison_extension': None}, {'google_cap_krw': 6301},
            {'openai_cap_micro_usd': 500001},
            {'video_comparison_extension': {**approval, 'owner_approval': ''}},
            {'video_comparison_extension': {**approval, 'previous_google_cap_krw': 3000}},
            {'video_comparison_extension': {**approval, 'approved_openai_cap_micro_usd': 450000}},
            {'openai_cap_micro_usd': 350000, 'openai_cap_extension_followup': None,
             'video_comparison_extension': {**approval, 'approved_openai_cap_micro_usd': 350000}},
        ):
            path.write_text(json.dumps({**extended, **changes}))
            with self.assertRaises(ValueError):
                load_episode(record['id'], schedule)

    def test_paid_planning_extension_requires_new_and_all_previous_approvals(self):
        record = self.queued_episode()
        previous = {
            **record, 'google_cap_krw': 6300, 'openai_cap_micro_usd': 500000,
            'google_cap_extension': {'previous_cap_krw': 3000, 'approved_cap_krw': 3300,
                                     'owner_approval': 'Earlier media'},
            'openai_cap_extension': {'previous_cap_micro_usd': 300000,
                'approved_cap_micro_usd': 350000, 'owner_approval': 'Earlier validation'},
            'openai_cap_extension_followup': {'previous_cap_micro_usd': 350000,
                'approved_cap_micro_usd': 450000, 'owner_approval': 'Earlier text'},
            'video_comparison_extension': {'previous_google_cap_krw': 3300,
                'approved_google_cap_krw': 6300, 'previous_openai_cap_micro_usd': 450000,
                'approved_openai_cap_micro_usd': 500000, 'owner_approval': 'Earlier comparison'},
        }
        approval = {'previous_cap_micro_usd': 500000, 'approved_cap_micro_usd': 650000,
                    'owner_approval': 'New $0.15 planning validation'}
        extended = {**previous, 'planning_validation_extension': approval}
        path = episode_path(record['id'])
        schedule = self.manager.get_schedule(self.schedule['id'])
        path.write_text(json.dumps(extended))
        loaded = load_episode(record['id'], schedule)
        self.assertEqual(loaded['baseline'], record['baseline'])
        self.assertEqual(loaded['openai_cap_micro_usd'], previous['openai_cap_micro_usd'])
        self.assertEqual(loaded['video_comparison_extension'], previous['video_comparison_extension'])
        _, status = episode_environment(loaded)
        self.assertEqual(status['openai_remaining_usd'], .65)
        self.assertEqual(begin_episode(record['schedule_id'], 2)['openai_cap_micro_usd'], 300000)
        for changes in ({'planning_validation_extension': None},
                {'planning_validation_extension': {**approval, 'owner_approval': ''}},
                {'planning_validation_extension': {**approval, 'previous_cap_micro_usd': 450000}},
                {'planning_validation_extension': {**approval, 'approved_cap_micro_usd': 660000}},
                {'openai_cap_micro_usd': 650001}, {'openai_cap_micro_usd': 640000},
                {'video_comparison_extension': None}, {'openai_cap_extension_followup': None},
                {'openai_cap_extension': None}, {'google_cap_extension': None}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**extended, **changes}))
                with self.assertRaises(ValueError):
                    load_episode(record['id'], schedule)

    def test_google_extension_keeps_old_reserves_and_monthly_ceiling(self):
        record = self.queued_episode()
        google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 8)
        path = episode_path(record['id'])
        extended = {**record, 'google_cap_krw': 3300, 'google_cap_extension': {
            'previous_cap_krw': 3000, 'approved_cap_krw': 3300,
            'owner_approval': 'This episode only, KRW3300 and frame v3 approved.',
        }}
        path.write_text(json.dumps(extended))
        loaded = load_episode(record['id'], self.manager.get_schedule(self.schedule['id']))
        self.assertEqual(loaded['baseline'], record['baseline'])
        env, current = episode_environment(loaded)
        self.assertEqual(current['google_new_reserved_krw'], 480)
        self.assertEqual(current['google_remaining_krw'], 2820)
        self.assertEqual(env['GOOGLE_MONTHLY_BUDGET_KRW'], '6300')
        with patch.object(settings, 'google_monthly_budget_krw', 4000):
            self.assertEqual(episode_environment(loaded)[0]['GOOGLE_MONTHLY_BUDGET_KRW'], '4000')
        self.assertEqual(begin_episode('future-schedule', 1)['google_cap_krw'], 3000)
        for changes in ({'google_cap_krw': 3301}, {'google_cap_extension': None},
                        {'google_cap_extension': {**extended['google_cap_extension'], 'owner_approval': ''}},
                        {'google_cap_extension': {**extended['google_cap_extension'], 'previous_cap_krw': 0}},
                        {'google_cap_extension': {**extended['google_cap_extension'], 'approved_cap_krw': 3200}}):
            path.write_text(json.dumps({**extended, **changes}))
            with self.assertRaises(ValueError):
                load_episode(record['id'], self.manager.get_schedule(self.schedule['id']))

    def test_scope_identity_corruption_and_operation_marker_fail_closed(self):
        record = self.queued_episode()
        schedule = self.manager.get_schedule(self.schedule['id'])
        self.manager.update_schedule(schedule['id'], {'last_result': 'script_review_pending'})
        path = episode_path(record['id'])
        invalid = {**record, 'google_cap_krw': 3001}
        path.write_text(json.dumps(invalid))
        with self.assertRaises(ValueError):
            load_episode(record['id'], schedule)
        path.write_text(json.dumps(record))
        pending = path.with_suffix('.operation.pending.json')
        pending.write_text('unverified prior child')
        with patch('scripts.operate_schedule.subprocess.run') as child:
            with self.assertRaises(FileExistsError):
                run_scoped(self.manager, schedule['id'], [sys.executable, '-c', 'pass'])
            child.assert_not_called()
        self.assertEqual(pending.read_text(), 'unverified prior child')

    def test_scope_process_environment_and_audit_do_not_enable_the_parent(self):
        record = self.queued_episode()
        seen = []

        def child(command, *, cwd, env):
            self.assertTrue(episode_path(record['id']).with_suffix('.operation.pending.json').is_file())
            seen.append(env)
            return SimpleNamespace(returncode=2)

        with patch('scripts.operate_schedule.subprocess.run', side_effect=child):
            self.assertEqual(run_scoped(self.manager, self.schedule['id'], [sys.executable, '-c', 'pass']), 2)
        self.assertFalse(settings.paid_production_enabled)
        self.assertEqual(settings.google_monthly_budget_krw, 10000)
        self.assertEqual(seen[0]['SHORTSMAKER_EPISODE_ID'], record['id'])
        self.assertEqual(seen[0]['GOOGLE_MONTHLY_BUDGET_KRW'], '6000')
        self.assertEqual(seen[0]['OPENAI_MONTHLY_BUDGET_USD'], '0.5')
        self.assertFalse(episode_path(record['id']).with_suffix('.operation.pending.json').exists())
        audit = next(episode_path(record['id']).parent.glob('*.operation.*.json'))
        self.assertEqual(json.loads(audit.read_text())['returncode'], 2)

    def test_real_child_loads_reduced_settings_without_provider_calls(self):
        record = self.queued_episode()
        command = [sys.executable, '-c',
                   'from shorts_maker.utils.config import settings; '
                   'assert settings.google_monthly_budget_krw == 6000; '
                   'assert settings.openai_monthly_budget_usd == .5; '
                   'assert settings.google_usd_krw_rate == 2000; '
                   'assert settings.paid_production_enabled; '
                   'assert settings.veo_model_id == "veo-3.1-lite-generate-001"']
        with patch.dict(os.environ, {'GOOGLE_USD_KRW_RESERVE_RATE': '1000'}):
            self.assertEqual(run_scoped(self.manager, self.schedule['id'], command), 0)
        self.assertFalse(settings.paid_production_enabled)
        self.assertEqual(episode_environment(record)[1]['google_new_reserved_krw'], 0)

    def test_queue_only_host_does_not_run_a_legacy_paid_job(self):
        legacy = self.manager.create_schedule('Legacy daily', '19:00', enabled=True)
        with patch.object(settings, 'paid_production_enabled', True), patch(
            'shorts_maker.services.production_service.ProductionService.full_pipeline', new_callable=AsyncMock,
        ) as pipeline:
            asyncio.run(self.manager._execute_pipeline(legacy))
            pipeline.assert_not_awaited()
        self.assertEqual(self.manager.get_schedule(legacy['id'])['run_count'], 0)

    def test_real_clock_queues_once_and_recovers_without_provider_calls(self):
        first = datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None) + timedelta(seconds=.15)
        self.manager.update_schedule(self.schedule['id'], {'first_run_at': first.isoformat()})

        async def run_clock():
            self.manager.start_scheduler()
            deadline = asyncio.get_running_loop().time() + 3
            while asyncio.get_running_loop().time() < deadline:
                if self.manager.get_schedule(self.schedule['id']).get('last_result') == 'operator_pending':
                    break
                await asyncio.sleep(.02)
            self.manager.stop_scheduler()
            await asyncio.sleep(0)

        with patch('shorts_maker.services.production_service.ProductionService.full_pipeline',
                   new_callable=AsyncMock) as pipeline, patch(
            'shorts_maker.uploader.youtube_uploader.YouTubeUploader.get_authenticated_service',
        ) as auth:
            asyncio.run(run_clock())
            asyncio.run(self.manager._execute_pipeline(self.schedule))
            pipeline.assert_not_awaited()
            auth.assert_not_called()
        restarted = ScheduleManager(str(self.manager.filename), queue_only=True)
        queued = restarted.get_schedule(self.schedule['id'])
        self.assertEqual(queued['last_result'], 'operator_pending')
        self.assertEqual(queued['run_count'], 1)
        self.assertFalse(queued['enabled'])
        with self.assertRaises(ValueError):
            restarted.toggle_schedule(queued['id'])

    def test_operator_planning_keeps_one_attempt_and_unknown_result_blocks_replay(self):
        record = self.queued_episode()
        script = ShortsScript(title='Source story', description='Facts', tags=[], mood='calm',
                              style='documentary', generation_mode='video', source_name='Source', source_url='https://example.com/story',
                              scenes=[VideoScene(scene_number=1, visual_description='Model', script_text='사실')])
        with patch.dict(os.environ, {'SHORTSMAKER_EPISODE_ID': record['id']}), patch.object(
            settings, 'paid_production_enabled', True,
        ), patch('shorts_maker.utils.bgm_manager.BGMManager.has_documented_track', return_value=True), patch(
            'shorts_maker.services.production_service.ProductionService.full_pipeline', new_callable=AsyncMock,
            return_value=ProductionResult(success=True, review_pending=True, script=script),
        ) as pipeline:
            with patch('shorts_maker.uploader.youtube_uploader.YouTubeUploader.get_authenticated_service',
                       return_value=object()):
                asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
            pipeline.assert_awaited_once()
            with self.assertRaises(ValueError):
                asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['run_count'], 1)
        self.assertEqual(current['last_result'], 'script_review_pending')
        self.assertEqual(current['last_episode_id'], record['id'])
        self.assertFalse(current.get('run_history'))

    def test_host_sync_retains_anchor_and_tracks_external_pause_resume(self):
        first = datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None) + timedelta(minutes=10)
        self.manager.update_schedule(self.schedule['id'], {'first_run_at': first.isoformat(), 'frequency': 'Every 2 Weeks'})

        async def check():
            self.manager.start_scheduler()
            job = self.manager._scheduler.get_job(self.schedule['id'])
            initial = job.next_run_time
            self.manager.sync_jobs()
            self.assertIs(self.manager._scheduler.get_job(job.id), job)
            external = ScheduleManager(str(self.manager.filename))
            external.update_schedule(job.id, {'enabled': False})
            self.manager.sync_jobs()
            self.assertIsNone(self.manager._scheduler.get_job(job.id))
            external.update_schedule(job.id, {'enabled': True})
            self.manager.sync_jobs()
            restored = self.manager._scheduler.get_job(job.id)
            self.assertEqual(restored.next_run_time, initial)
            self.assertEqual(restored.trigger.interval, timedelta(weeks=2))
            self.manager.stop_scheduler()
            await asyncio.sleep(0)

        asyncio.run(check())

    def test_operator_auth_failure_preserves_episode_before_planning(self):
        record = self.queued_episode()
        before = self.manager.get_schedule(self.schedule['id'])
        episode_before = episode_path(record['id']).read_bytes()
        budget_before = episode_environment(record)[1]
        script = ShortsScript(title='Source story', description='Facts', tags=[], mood='calm',
                              style='documentary', generation_mode='video', source_name='Source',
                              source_url='https://example.com/story',
                              scenes=[VideoScene(scene_number=1, visual_description='Model', script_text='사실')])
        with patch.dict(os.environ, {'SHORTSMAKER_EPISODE_ID': record['id']}), patch.object(
            settings, 'paid_production_enabled', True,
        ), patch('shorts_maker.utils.bgm_manager.BGMManager.has_documented_track', return_value=True), patch(
            'shorts_maker.services.production_service.ProductionService.full_pipeline', new_callable=AsyncMock,
            return_value=ProductionResult(success=True, review_pending=True, script=script),
        ) as pipeline, patch(
            'shorts_maker.uploader.youtube_uploader.YouTubeUploader.get_authenticated_service',
            side_effect=RuntimeError('expired consent'),
        ) as auth:
            with self.assertRaisesRegex(RuntimeError, 'YOUTUBE_AUTH_REQUIRED'):
                asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
            auth.assert_called_once_with(interactive=False)
            pipeline.assert_not_awaited()
            self.assertEqual(self.manager.get_schedule(self.schedule['id']), before)
            self.assertEqual(episode_path(record['id']).read_bytes(), episode_before)
            self.assertEqual(episode_environment(record)[1], budget_before)
            auth.side_effect = None
            auth.return_value = object()
            asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
        pipeline.assert_awaited_once()
        after = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(after['last_episode_id'], record['id'])
        self.assertEqual(after['run_count'], 1)
        self.assertEqual(after['last_result'], 'script_review_pending')
        self.assertFalse(after['enabled'])

    def test_interrupted_planning_remains_unverified_and_cannot_be_submitted_again(self):
        record = self.queued_episode()
        with patch.dict(os.environ, {'SHORTSMAKER_EPISODE_ID': record['id']}), patch.object(
            settings, 'paid_production_enabled', True,
        ), patch('shorts_maker.utils.bgm_manager.BGMManager.has_documented_track', return_value=True), patch(
            'shorts_maker.services.production_service.ProductionService.full_pipeline',
            new_callable=AsyncMock, side_effect=asyncio.CancelledError,
        ) as pipeline:
            with patch('shorts_maker.uploader.youtube_uploader.YouTubeUploader.get_authenticated_service',
                       return_value=object()), self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
            current = self.manager.get_schedule(self.schedule['id'])
            self.assertEqual(current['last_result'], 'run_in_progress')
            self.assertFalse(current['enabled'])
            with self.assertRaises(ValueError):
                asyncio.run(self.manager._execute_pipeline(self.schedule, operator=True))
            pipeline.assert_awaited_once()

    def test_overdue_recovery_queues_latest_slot_once_and_records_missed_dates(self):
        first = datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None) - timedelta(weeks=4, minutes=10)
        self.manager.update_schedule(self.schedule['id'], {'first_run_at': first.isoformat(), 'frequency': 'Every 2 Weeks'})
        with patch('shorts_maker.services.production_service.ProductionService.full_pipeline',
                   new_callable=AsyncMock) as pipeline:
            asyncio.run(self.manager.queue_overdue())
            asyncio.run(self.manager.queue_overdue())
            pipeline.assert_not_awaited()
        queued = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(queued['run_count'], 1)
        self.assertEqual(queued['scheduled_for'], (first + timedelta(weeks=4)).isoformat())
        self.assertEqual(queued['skipped_slots'], [first.isoformat(), (first + timedelta(weeks=2)).isoformat()])
        self.assertGreater(queued['late_by_seconds'], 599)

    def test_attaching_private_copy_does_not_accept_or_reenable_it(self):
        self.queued_episode()
        script = {'title': 'Reviewed story', 'source_url': 'https://example.com/story'}
        self.manager.update_schedule(self.schedule['id'], {'last_result': 'script_review_pending', 'last_script': script})
        video = settings.output_dir / 'review.mp4'
        video.write_bytes(b'local fixture, not a real render')
        report = {'video_path': str(video), 'source_url': script['source_url'],
                  'script_sha256': script_sha256(script), 'quality_passed': True,
                  'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'youtube_id': 'private_12345',
                  'youtube_upload_request': {'status': {'privacyStatus': 'private'}},
                  'uploaded_at_utc': '2026-11-01T00:00:00Z'}
        video.with_suffix('.production.json').write_text(json.dumps(report))
        attached = self.manager.record_private_review_copy(self.schedule['id'], str(video))
        self.assertEqual(attached['last_result'], 'script_review_pending')
        self.assertFalse(attached['enabled'])
        self.assertNotIn('accepted_at', attached)
        episode = episode_path(attached['last_episode_id'])
        baseline = episode.read_bytes()
        budget = episode_environment(load_episode(attached['last_episode_id'], attached))[1]
        with patch('scripts.operate_schedule.subprocess.run', return_value=SimpleNamespace(returncode=0)) as child:
            with self.assertRaisesRegex(ValueError, '완성본'):
                run_scoped(self.manager, self.schedule['id'], [sys.executable, '-c', 'pass'])
            child.assert_not_called()
        self.assertEqual(list(episode.parent.glob('*.operation.*.json')), [])
        self.assertEqual(episode.read_bytes(), baseline)
        self.assertEqual(episode_environment(load_episode(attached['last_episode_id'], attached))[1], budget)
        with self.assertRaisesRegex(ValueError, '비공개'):
            self.manager.reject_pending_script(self.schedule['id'])
        self.assertEqual(self.manager.get_schedule(self.schedule['id']), attached)
        self.assertEqual(self.manager.record_private_review_copy(self.schedule['id'], str(video)), attached)
        original_bytes = video.read_bytes()
        for label, candidate, content, upload_id in (
            ('different_path', settings.output_dir / 'other.mp4', original_bytes, report['youtube_id']),
            ('changed_content', video, b'another cut of the same script', report['youtube_id']),
            ('changed_upload', video, original_bytes, 'another_12345'),
        ):
            with self.subTest(label=label):
                candidate.write_bytes(content)
                candidate.with_suffix('.production.json').write_text(json.dumps({
                    **report, 'video_path': str(candidate), 'youtube_id': upload_id,
                    'video_sha256': hashlib.sha256(content).hexdigest(),
                }))
                for action in (self.manager.record_private_review_copy, self.manager.accept_pending_video):
                    with self.assertRaisesRegex(ValueError, '연결된'):
                        action(self.schedule['id'], str(candidate))
                    self.assertEqual(self.manager.get_schedule(self.schedule['id']), attached)
                video.write_bytes(original_bytes)
                video.with_suffix('.production.json').write_text(json.dumps(report))
        accepted = self.manager.accept_pending_video(self.schedule['id'], str(video))
        self.assertTrue(accepted['enabled'])
        self.assertEqual(accepted['last_result'], 'private_review_accepted')
