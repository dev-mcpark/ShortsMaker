"""Real local clocks/ledgers; provider planning and uploads remain offline."""

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from scripts.operate_schedule import run_scoped
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.operating_budget import begin_episode, episode_environment, episode_path, load_episode
from shorts_maker.services.production_service import ProductionResult, script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager


class OperatingHandoffTests(unittest.TestCase):
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
        with sqlite3.connect(google_budget._database_path()) as db:
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
                   new_callable=AsyncMock) as pipeline:
            asyncio.run(run_clock())
            asyncio.run(self.manager._execute_pipeline(self.schedule))
            pipeline.assert_not_awaited()
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

    def test_interrupted_planning_remains_unverified_and_cannot_be_submitted_again(self):
        record = self.queued_episode()
        with patch.dict(os.environ, {'SHORTSMAKER_EPISODE_ID': record['id']}), patch.object(
            settings, 'paid_production_enabled', True,
        ), patch('shorts_maker.utils.bgm_manager.BGMManager.has_documented_track', return_value=True), patch(
            'shorts_maker.services.production_service.ProductionService.full_pipeline',
            new_callable=AsyncMock, side_effect=asyncio.CancelledError,
        ) as pipeline:
            with self.assertRaises(asyncio.CancelledError):
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
        accepted = self.manager.accept_pending_video(self.schedule['id'], str(video))
        self.assertTrue(accepted['enabled'])
        self.assertEqual(accepted['last_result'], 'private_review_accepted')
