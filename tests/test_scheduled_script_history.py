"""Retained run versions are read-only, with private text backup before explicit opening."""

import asyncio
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.scheduled_script_history import render_script_history_browser
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.production_service import script_sha256
from shorts_maker.services.scheduled_script_history import script_versions, validated_revisions
from shorts_maker.services.work_drafts import read_work_draft, script_draft_key, saved_work_drafts
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from test_gui_creation_flows import script


class ScheduledScriptHistoryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.enterContext(patch.object(settings, 'output_dir', self.root / 'outputs'))
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        self.manager = ScheduleManager(str(self.root / 'schedules.json'), queue_only=True)
        first = script().model_copy(update={'title': '처음 대본'})
        second = first.model_copy(update={'title': '중간 대본'})
        latest = first.model_copy(update={'title': '마지막 저장 대본'})
        self.scripts = [first, second, latest]
        history = [{'script': a.model_dump(mode='json'), 'script_sha256': script_sha256(a.model_dump(mode='json')),
                    'replacement_sha256': script_sha256(b.model_dump(mode='json')), 'script_path': '/outside/never_read.json',
                    'review_receipt_sha256': script_draft_key(b), 'replaced_at': f'2026-11-11T1{i}:00:00+09:00'}
                   for i, (a, b) in enumerate(zip(self.scripts, self.scripts[1:]))]
        scheduled = self.manager.create_schedule('과거 회차', '19:00', enabled=False)
        self.schedule = self.manager.update_schedule(scheduled['id'], {'run_count': 1, 'last_run': '2026-11-11T10:00:00',
            'last_result': 'script_review_pending', 'last_script': latest.model_dump(mode='json'),
            'script_revisions': history, 'last_youtube_id': 'existing_private_copy', 'last_video_path': 'kept-original.mp4'})
        self.runs = self.manager.get_execution_history()
        self.state = AppState(script=script('active-work'), final_video_path='keep-selected.mp4',
                              openai_key='SECRET_NOT_IN_BACKUP', gcp_project='SECRET_PROJECT')
        self.state.confirm_script_review()
        self.client = Client(page('/history-fixture'));self.addCleanup(self.client.delete)
        self.notify = self.enterContext(patch('shorts_maker.gui.components.scheduled_script_history.safe_notify'))

    def render(self, runs=None):
        with self.client, ui.column() as root:
            render_script_history_browser(self.state, self.manager, self.runs if runs is None else runs)
        return root

    def field(self, label):
        return next(e for e in self.client.elements.values() if getattr(e, 'label', '') == label)

    def click(self, text):
        button = next(e for e in reversed(list(self.client.elements.values())) if getattr(e, 'text', '') == text and not e.is_deleted)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    def preview(self):
        self.field('회차 대본 검색').value = '0'
        self.click('선택 회차 대본 이력 보기')

    async def test_versions_share_revision_chain_validation_and_do_not_read_old_paths_or_mutate_records(self):
        before = self.manager.filename.read_bytes()
        data = copy.deepcopy(self.runs[0])
        with patch.object(Path, 'read_text', side_effect=AssertionError('Do not follow stored historical paths')):
            versions = script_versions(data)
        self.assertEqual([row['script'].title for row in versions], ['마지막 저장 대본', '중간 대본', '처음 대본'])
        self.assertEqual(self.manager.filename.read_bytes(), before)
        self.assertEqual(data, self.runs[0])
        for corrupt in (None, {}, [{}], [{**data['script_revisions'][0], 'script_sha256': 'wrong'}],
                        list(reversed(data['script_revisions']))):
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                validated_revisions(data['last_script'], corrupt)
        self.assertEqual(script_versions({}), [])
        with self.assertRaises(ValueError):
            script_versions({'script_revisions': None})
        with self.assertRaises(ValueError):
            script_versions({'last_script': {'title': 'summary only'}})

    async def test_preview_and_close_leave_work_schedule_scope_and_drafts_untouched(self):
        before = self.manager.filename.read_bytes()
        selected = self.state.script.model_dump_json(), self.state.final_video_path, self.state.reviewed_script_sha256
        self.render()
        with self.client:
            self.preview();self.field('보관된 대본 버전').value = '2'
            self.click('닫기');self.click('선택 대본을 작업실에서 검토')
        self.assertEqual(before, self.manager.filename.read_bytes())
        self.assertEqual(selected, (self.state.script.model_dump_json(), self.state.final_video_path, self.state.reviewed_script_sha256))
        self.assertEqual(saved_work_drafts(), ({}, []))

    async def test_open_explicit_version_backs_up_current_and_target_and_restores_after_restart_without_authority(self):
        before = self.manager.filename.read_bytes()
        current_key = self.state.script_editor_key()
        self.state.remember_script_draft(current_key, '{미완성 현재 JSON')
        self.state.first_frame_drafts[current_key] = {1: {'frame_path': '/retained/current.png', 'reviewer_note': '검토 입력'}}
        target = self.scripts[0]
        target_key = script_draft_key(target)
        self.state.script_editor_drafts[target_key] = '타깃 대본의 이전 입력'
        self.state.first_frame_drafts[target_key] = {1: {'must_show': '보관할 조건'}}
        bound_scope = {'schedules_file': str(self.manager.filename), 'schedule_id': self.schedule['id'], 'episode_id': 'a' * 32}
        self.state.operating_scope = bound_scope
        self.state.prepared_narration_manifest = 'keep-file-but-clear-selection.json'
        self.render()
        with self.client:
            self.preview();self.field('보관된 대본 버전').value = '2';self.click('선택 대본을 작업실에서 검토')
        self.assertEqual(self.state.script, target)
        self.assertEqual(self.state.script_editor_text(), target.model_dump_json(indent=2))
        self.assertFalse(self.state.has_unapplied_script_draft())
        self.assertNotIn(target_key, self.state.first_frame_drafts)
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertIsNone(self.state.final_video_path)
        self.assertIsNone(self.state.prepared_narration_manifest)
        self.assertEqual(self.state.operating_scope, bound_scope)
        self.assertEqual(before, self.manager.filename.read_bytes())
        choices, warnings = saved_work_drafts();self.assertFalse(warnings);self.assertEqual(len(choices), 2)
        records = [(name, read_work_draft(name)[0]) for name in choices]
        name, record = next(row for row in records if row[1].script_sha256 == current_key)
        restored = AppState()
        restored.restore_work_draft(name, choices[name]['sha256'])
        self.assertEqual(restored.script_editor_text(), '{미완성 현재 JSON')
        self.assertEqual(restored.first_frame_drafts[current_key][1]['reviewer_note'], '검토 입력')
        self.assertIsNone(restored.operating_scope)
        self.assertIsNone(restored.reviewed_script_sha256)
        for name in choices:
            content = (settings.output_dir / 'evaluation/studio_drafts' / name).read_text()
            self.assertNotIn('SECRET', content)
            self.assertNotIn('operating_scope', content)

    async def test_applied_but_unsaved_current_script_is_also_backed_up(self):
        expected = self.state.script.model_dump_json()
        backups = self.state.open_historical_script(self.scripts[0])
        self.assertEqual(len(backups), 1)
        record, _ = read_work_draft(backups[0].name)
        self.assertEqual(record.applied_script.model_dump_json(), expected)

    async def test_backup_failure_keeps_current_and_target_inputs_and_selected_results(self):
        key = script_draft_key(self.scripts[0])
        self.state.script_editor_drafts[key] = 'keep target'
        before = copy.deepcopy(self.state.__dict__)
        with patch('shorts_maker.services.work_drafts.save_work_draft', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.state.open_historical_script(self.scripts[0])
        self.assertEqual(before, self.state.__dict__)
        from shorts_maker.services.work_drafts import save_work_draft
        calls = []
        def fail_second(*args):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('target backup failed')
            return save_work_draft(*args)
        with patch('shorts_maker.services.work_drafts.save_work_draft', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.state.open_historical_script(self.scripts[0])
        self.assertEqual(before, self.state.__dict__)
        self.assertEqual(len(saved_work_drafts()[0]), 1)

    async def test_late_changed_busy_deleted_or_damaged_record_cannot_open(self):
        self.render()
        with self.client:
            self.preview()
            self.state.remember_script_draft(self.state.script_editor_key(), '{changed while preview open')
            self.click('선택 대본을 작업실에서 검토')
            self.assertEqual(self.state.final_video_path, 'keep-selected.mp4')
            self.click('닫기');self.preview()
            self.state.pipeline_running = True
            self.click('선택 대본을 작업실에서 검토')
            self.state.pipeline_running = False
            self.click('닫기');self.preview()
            self.manager.update_schedule(self.schedule['id'], {'last_result': 'changed'})
            self.click('선택 대본을 작업실에서 검토')
        self.assertEqual(saved_work_drafts(), ({}, []))
        self.assertEqual(self.state.final_video_path, 'keep-selected.mp4')

    async def test_all_runs_are_searchable_and_missing_or_corrupt_scripts_do_not_break_other_records(self):
        many = [{**self.runs[0], 'run_count': i, 'last_script': {'title': f'대본 {i}'}} for i in range(20)]
        root = self.render(many)
        self.assertEqual(len(self.field('회차 대본 검색').options), 20)
        with self.client:
            self.field('회차 대본 검색').value = '19';self.click('선택 회차 대본 이력 보기')
        self.assertEqual(saved_work_drafts(), ({}, []))
        self.assertTrue(self.notify.called)
        root.clear()
        self.render([{**self.runs[0], 'last_script': 'broken data'}])

    async def test_older_archived_run_is_reopened_as_a_copy_without_replacing_current_episode(self):
        self.manager.update_schedule(self.schedule['id'], {'run_count': 2, 'last_run': '2026-11-12T10:00:00',
            'last_script': self.scripts[0].model_dump(mode='json'), 'last_result': 'operator_pending'})
        runs = self.manager.get_execution_history()
        self.assertEqual([run['run_count'] for run in runs], [2, 1])
        before = self.manager.filename.read_bytes()
        self.render(runs)
        with self.client:
            self.field('회차 대본 검색').value = '1';self.click('선택 회차 대본 이력 보기')
            self.field('보관된 대본 버전').value = '1';self.click('선택 대본을 작업실에서 검토')
        self.assertEqual(self.state.script.title, '중간 대본')
        self.assertEqual(before, self.manager.filename.read_bytes())
        self.assertEqual(self.manager.get_schedule(self.schedule['id'])['run_count'], 2)

    async def test_deleted_panel_or_changed_edit_settings_cannot_apply_late_copy(self):
        root = self.render()
        with self.client:
            self.preview()
            self.state.bgm_volume = .67
            self.click('선택 대본을 작업실에서 검토')
            self.assertEqual(self.state.final_video_path, 'keep-selected.mp4')
            self.click('닫기');self.preview()
            button = next(e for e in reversed(list(self.client.elements.values())) if getattr(e, 'text', '') == '선택 대본을 작업실에서 검토')
            callback = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            root.clear()
            callback(None)
        self.assertEqual(saved_work_drafts(), ({}, []))
        self.assertEqual(self.state.final_video_path, 'keep-selected.mp4')
