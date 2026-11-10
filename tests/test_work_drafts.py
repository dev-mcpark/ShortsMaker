"""Explicit unfinished-work recovery uses private, isolated files and no providers."""

import asyncio
import json
import os
import stat
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from PIL import Image
from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import generation_tab, planning_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import draft_store, work_drafts
from shorts_maker.services.asset_library import AssetLibrary
from shorts_maker.services.visual_review import approve_first_frame, inspect_frame
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class WorkDraftTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        setting = patch.object(settings, 'output_dir', self.root / 'outputs')
        setting.start()
        self.addCleanup(setting.stop)
        self.state = AppState(script=script(), final_video_path='kept.mp4', openai_key='DO_NOT_SAVE_KEY', gcp_project='DO_NOT_SAVE_PROJECT')
        self.state.confirm_script_review()

    def test_invalid_editor_and_frame_notes_survive_new_session_without_restoring_authority(self):
        original = self.state.script.model_dump_json()
        receipt = self.state.reviewed_script_sha256
        key = self.state.script_editor_key()
        self.state.remember_script_draft(key, '{미완성 JSON\n')
        self.state.first_frame_drafts[key] = {1: {'frame_path': '/missing/candidate.png', 'reviewer_note': '검토 중'}}
        path = self.state.save_work_draft()
        self.assertEqual(self.state.script.model_dump_json(), original)
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertNotIn('DO_NOT_SAVE', path.read_text())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        record, digest = work_drafts.read_work_draft(path.name)
        restored = AppState()
        restored.restore_work_draft(path.name, digest)
        self.assertEqual(restored.script.model_dump_json(), original)
        self.assertEqual(restored.script_editor_text(), '{미완성 JSON\n')
        self.assertEqual(restored.first_frame_drafts[key][1]['reviewer_note'], '검토 중')
        self.assertTrue(restored.has_unapplied_script_draft())
        self.assertIsNone(restored.reviewed_script_sha256)
        self.assertIsNone(restored.final_video_path)
        self.assertIsNone(restored.production_service)
        self.assertEqual(record.editor_text, restored.script_editor_text())

    def test_empty_workspace_partial_json_can_be_saved_and_restored(self):
        empty = AppState()
        empty.remember_script_draft(empty.script_editor_key(), '{새 대본을 쓰는 중')
        path = empty.save_work_draft()
        _, digest = work_drafts.read_work_draft(path.name)
        self.state.restore_work_draft(path.name, digest)
        self.assertIsNone(self.state.script)
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual(self.state.script_editor_text(), '{새 대본을 쓰는 중')

    def test_restore_backs_up_current_and_target_unapplied_work_before_replacing_it(self):
        target = AppState(script=script('target'))
        target.remember_script_draft(target.script_editor_key(), 'saved target text')
        path = target.save_work_draft()
        _, digest = work_drafts.read_work_draft(path.name)
        self.state.remember_script_draft(self.state.script_editor_key(), 'current unfinished text')
        self.state.script_editor_drafts[target.script_editor_key()] = 'target unfinished text'
        self.state.first_frame_drafts[target.script_editor_key()] = {1: {'must_show': '현재 편집 중인 조건'}}
        backups = self.state.restore_work_draft(path.name, digest)
        self.assertEqual(len(backups), 2)
        records = [work_drafts.read_work_draft(p.name)[0] for p in backups]
        self.assertEqual({r.editor_text for r in records}, {'current unfinished text', 'target unfinished text'})
        target_backup = next(r for r in records if r.editor_text.startswith('target'))
        self.assertEqual(target_backup.first_frames['1']['must_show'], '현재 편집 중인 조건')
        self.assertEqual(self.state.script_editor_text(), 'saved target text')
        self.assertEqual(work_drafts.read_work_draft(path.name)[1], digest)

    def test_changed_or_malformed_snapshot_preserves_live_work_and_bad_file(self):
        path = self.state.save_work_draft()
        _, digest = work_drafts.read_work_draft(path.name)
        record = json.loads(path.read_text())
        record['editor_text'] = 'changed after listing'
        path.write_text(json.dumps(record))
        self.state.remember_script_draft(self.state.script_editor_key(), 'keep this input')
        before = self.state.script.model_dump_json()
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.state.restore_work_draft(path.name, digest)
        for change in ({'script_sha256': 'wrong'}, {'schema_version': True},
                       {'first_frames': {'99': {'reviewer_note': 'wrong scene'}}},
                       {'first_frames': {'1': {'openai_key': 'DO_NOT_ECHO'}}}):
            path.write_text(json.dumps({**record, **change}))
            with self.assertRaises(ValueError) as error:
                self.state.restore_work_draft(path.name, digest)
            self.assertNotIn('DO_NOT_ECHO', str(error.exception))
            self.assertTrue(path.exists())
        choices, warnings = work_drafts.saved_work_drafts()
        self.assertEqual(choices, {})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(self.state.script.model_dump_json(), before)
        self.assertEqual(self.state.script_editor_text(), 'keep this input')
        self.assertEqual(self.state.final_video_path, 'kept.mp4')

    def test_paths_links_size_and_busy_rejections_do_not_replace_or_initialize_work(self):
        self.assertEqual(work_drafts.saved_work_drafts(), ({}, []))
        self.assertFalse(settings.output_dir.exists())
        with patch.object(Path, 'iterdir', side_effect=PermissionError('fixture folder access denied')):
            with self.assertRaises(PermissionError):
                work_drafts.saved_work_drafts()
        path = self.state.save_work_draft()
        _, digest = work_drafts.read_work_draft(path.name)
        for name in ('../secret.json', str(path)):
            with self.assertRaises(ValueError):
                work_drafts.read_work_draft(name)
        linked = path.with_name('draft_20261111T010101Z_' + 'a' * 32 + '.json')
        linked.symlink_to(path)
        with self.assertRaises(ValueError):
            work_drafts.read_work_draft(linked.name)
        self.state.pipeline_running = True
        with self.assertRaises(ValueError):
            self.state.restore_work_draft(path.name, digest)
        with self.assertRaises(ValueError):
            self.state.save_work_draft()
        self.state.pipeline_running = False
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            work_drafts.save_work_draft(self.state.script, '가' * draft_store.MAX_BYTES, {})
        self.assertEqual(self.state.final_video_path, 'kept.mp4')

    def test_unique_atomic_snapshots_and_backup_failure_preserve_prior_work(self):
        first = self.state.save_work_draft()
        second = self.state.save_work_draft()
        self.assertNotEqual(first, second)
        original = first.read_bytes()
        self.state.remember_script_draft(self.state.script_editor_key(), 'unsaved input')
        _, digest = work_drafts.read_work_draft(first.name)
        with patch.object(draft_store.os, 'fsync', side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):
                self.state.restore_work_draft(first.name, digest)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(self.state.script_editor_text(), 'unsaved input')
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertEqual(list(first.parent.glob('*.tmp')), [])

    def test_format_only_input_is_backed_up_and_linked_snapshot_directory_is_rejected(self):
        saved = self.state.save_work_draft()
        _, digest = work_drafts.read_work_draft(saved.name)
        formatted = self.state.script.model_dump_json(indent=4)
        self.state.remember_script_draft(self.state.script_editor_key(), formatted)
        self.assertFalse(self.state.has_unapplied_script_draft())
        backups = self.state.restore_work_draft(saved.name, digest)
        self.assertEqual(len(backups), 1)
        self.assertEqual(work_drafts.read_work_draft(backups[0].name)[0].editor_text, formatted)
        moved = self.root / 'moved-drafts'
        saved.parent.rename(moved)
        saved.parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.state.save_work_draft()

    def test_saved_snapshot_reference_protects_old_temporary_image_after_session_is_gone(self):
        image = self.root / 'temp/old.png'
        image.parent.mkdir()
        image.write_bytes(b'fixture media reference')
        os.utime(image, (time.time() - 90000,) * 2)
        library = AssetLibrary(roots={'outputs': settings.output_dir, 'temp': image.parent}, project_root=self.root)
        self.assertTrue(next(r for r in library.scan()['rows'] if r['id'] == 'temp/old.png')['cleanable'])
        self.state.first_frame_drafts[self.state.script_editor_key()] = {1: {'frame_path': str(image)}}
        self.state.save_work_draft()
        self.state = AppState()
        row = next(r for r in library.scan()['rows'] if r['id'] == 'temp/old.png')
        self.assertFalse(row['cleanable'])
        self.assertIn('사용처 기록', row['reason'])


class WorkDraftUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in [('output_dir', Path(directory.name)), ('scripts_dir', Path(directory.name) / 'scripts')]:
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start()
        self.addCleanup(loop.stop)
        self.client = Client(page('/work-draft'))
        self.addCleanup(self.client.delete)
        self.state = AppState()

    def render(self):
        with self.client, ui.column() as root, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {})):
            planning_tab.render_planning_tab(self.state)
        return root

    def field(self, root, label):
        return next(e for e in root.descendants() if e._props.get('label') == label)

    def click(self, root, text):
        button = next(e for e in root.descendants() if getattr(e, 'text', '') == text)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    async def flush(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_save_then_new_session_reopen_keeps_incomplete_text_without_auto_apply(self):
        self.state.remember_script_draft(self.state.script_editor_key(), '{아직 작성 중')
        root = self.render()
        with self.client:
            self.field(root, '저장된 작업 초안').set_value(True)
            self.click(root, '작업 초안 새 사본 저장')
        await self.flush()
        self.assertTrue(self.field(root, '저장된 작업 초안').value)
        self.assertEqual(len(work_drafts.saved_work_drafts()[0]), 1)
        self.state = AppState()
        with self.client, root, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {})):
            root.clear()
            planning_tab.render_planning_tab(self.state)
        choice = self.field(root, '저장된 작업 초안 검색')
        with self.client:
            choice.set_value(next(iter(choice.options)))
            self.click(root, '선택한 작업 초안 열기')
        await self.flush()
        self.assertEqual(self.field(root, '각본 JSON').value, '{아직 작성 중')
        self.assertIsNone(self.state.script)
        self.assertIsNone(self.state.reviewed_script_sha256)

    async def test_first_frame_inputs_save_explicitly_without_approval(self):
        self.state = AppState(script=script(), mode='video')
        with self.client, ui.column() as root:
            generation_tab.render_first_frame_reviews(self.state)
            self.field(root, '검토 의견').set_value('미승인 검토 중')
            self.click(root, '검토 입력 초안 저장')
        records, _ = work_drafts.saved_work_drafts()
        record, _ = work_drafts.read_work_draft(next(iter(records)))
        self.assertEqual(record.first_frames['1']['reviewer_note'], '미승인 검토 중')
        self.assertFalse((settings.output_dir / 'evaluation/visual_reviews').exists())

    async def test_changed_snapshot_and_stale_view_cannot_restore_over_newer_work(self):
        self.state = AppState(script=script(), final_video_path='kept.mp4')
        path = self.state.save_work_draft()
        root = self.render()
        with self.client:
            choice = self.field(root, '저장된 작업 초안 검색')
            choice.set_value(path.name)
            self.field(root, '각본 JSON').set_value('current input')
            record = json.loads(path.read_text())
            record['editor_text'] = 'external change'
            path.write_text(json.dumps(record))
            self.click(root, '선택한 작업 초안 열기')
        self.assertEqual(self.state.script_editor_text(), 'current input')
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.state.load_saved_script(script('another'))
        with self.client:
            self.click(root, '선택한 작업 초안 열기')
        self.assertEqual(self.state.script.title, 'another')

    async def test_old_snapshot_inputs_equal_to_current_approval_do_not_force_another_review(self):
        self.state = AppState(script=script(), mode='video')
        key = self.state.script_editor_key()
        self.state.first_frame_drafts[key] = {1: {'reviewer_note': '계속 검토'}}
        saved = self.state.save_work_draft()
        _, digest = work_drafts.read_work_draft(saved.name)
        frame = settings.output_dir / 'frame.png'
        Image.new('RGB', (540, 960)).save(frame)
        review = approve_first_frame(self.state.script, self.state.script.scenes[0], str(frame),
                                     ['전체 공간'], ['가짜 글자'], '계속 검토', inspect_frame(str(frame)))
        approved = review.read_bytes()
        self.state = AppState()
        self.state.restore_work_draft(saved.name, digest)
        self.assertTrue(self.state.has_unapplied_first_frame_drafts())
        with self.client, ui.column() as root:
            generation_tab.render_first_frame_reviews(self.state)
        self.assertFalse(self.state.has_unapplied_first_frame_drafts())
        self.state.first_frame_drafts[key] = {1: {'reviewer_note': '계속 검토'}}
        with self.client:
            self.click(root, '첫 프레임 검토 입력 되돌리기')
        self.assertFalse(self.state.has_unapplied_first_frame_drafts())
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertEqual(review.read_bytes(), approved)

    async def test_corrupt_saved_file_is_reported_as_unreadable_instead_of_empty_inventory(self):
        self.state = AppState(script=script())
        saved = self.state.save_work_draft()
        saved.write_text('{broken snapshot')
        root = self.render()
        text = '\n'.join(getattr(e, 'text', '') for e in root.descendants())
        self.assertIn('기록 확인 필요', text)
        self.assertIn('사용 가능한 초안을 불러오지 못했습니다', text)
        self.assertNotIn('저장된 작업 초안이 없습니다', text)
        self.assertTrue(saved.exists())
