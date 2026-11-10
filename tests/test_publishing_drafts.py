"""Publishing-text recovery never sends providers or edits production records."""

import asyncio
import hashlib
import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import publishing_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import draft_store, publishing_drafts as drafts
from shorts_maker.utils.config import settings


def completed_output(root, name='video'):
    video = root / f'{name}.mp4'
    video.write_bytes(b'local fixture ' + name.encode())
    report = dict(schema_version=1, video_path=str(video), title='기록 제목', quality_passed=True,
                  video_sha256=hashlib.sha256(video.read_bytes()).hexdigest())
    video.with_suffix('.production.json').write_text(json.dumps(report))
    return report


FIELDS = dict(title='미완성 제목 ', description='출처 확인 중\n', tags='일상, ,건축,', disclosure=None)


class PublishingDraftTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        setting = patch.object(settings, 'output_dir', self.root)
        setting.start()
        self.addCleanup(setting.stop)
        self.report = completed_output(self.root)

    def test_partial_fields_roundtrip_in_private_immutable_files(self):
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        first = drafts.save_publishing_draft(self.report, FIELDS)
        second = drafts.save_publishing_draft(self.report, FIELDS)
        self.assertNotEqual(first, second)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        record, digest = drafts.read_publishing_draft(first.name)
        self.assertEqual(record.fields.model_dump(), FIELDS)
        choices, digests, warnings = drafts.saved_publishing_drafts(self.report)
        self.assertEqual(set(choices), {first.name, second.name})
        self.assertEqual(digests[first.name], digest)
        self.assertEqual(warnings, [])
        empty = dict(title='', description='', tags='', disclosure=None)
        self.assertEqual(drafts.read_publishing_draft(drafts.save_publishing_draft(self.report, empty).name)[0].fields.model_dump(), empty)
        for name, content in original.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertNotIn('youtube_upload_request', first.read_text())

    def test_restore_backs_up_current_edit_but_not_unchanged_recorded_fields(self):
        path = drafts.save_publishing_draft(self.report, FIELDS)
        _, digest = drafts.read_publishing_draft(path.name)
        current = {**FIELDS, 'title': '지금 쓰던 제목', 'disclosure': 'yes'}
        restored, backup = drafts.restore_publishing_draft(self.report, path.name, digest, current, {})
        self.assertEqual(restored, FIELDS)
        self.assertEqual(drafts.read_publishing_draft(backup.name)[0].fields.model_dump(), current)
        self.assertIsNone(drafts.restore_publishing_draft(self.report, path.name, digest, current, current)[1])
        self.assertIsNone(drafts.restore_publishing_draft(self.report, path.name, digest, FIELDS, {})[1])

    def test_failed_backup_does_not_restore_or_replace_snapshots(self):
        path = drafts.save_publishing_draft(self.report, FIELDS)
        original = path.read_bytes()
        _, digest = drafts.read_publishing_draft(path.name)
        current = {**FIELDS, 'title': 'keep current'}
        with patch.object(draft_store.os, 'fsync', side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):
                drafts.restore_publishing_draft(self.report, path.name, digest, current, {})
        self.assertEqual(current['title'], 'keep current')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_cross_video_hash_and_changed_snapshot_fail_closed(self):
        path = drafts.save_publishing_draft(self.report, FIELDS)
        _, digest = drafts.read_publishing_draft(path.name)
        other = completed_output(self.root, 'other')
        for report in (other, {**self.report, 'video_sha256': 'a' * 64}):
            self.assertEqual(drafts.saved_publishing_drafts(report)[0], {})
            with self.assertRaises(ValueError):
                drafts.restore_publishing_draft(report, path.name, digest, FIELDS, {})
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            drafts.restore_publishing_draft(self.report, path.name, digest, FIELDS, {})

    def test_invalid_snapshot_path_schema_and_size_keep_files_and_input(self):
        path = drafts.save_publishing_draft(self.report, FIELDS)
        original = json.loads(path.read_text())
        for change in ({'schema_version': True}, {'saved_at': '2026-11-11T10:00:00'},
                       {'video_path': '/tmp/outside.mp4'}, {'video_sha256': 'bad'},
                       {'fields': {**FIELDS, 'metadata_reviewed': True}},
                       {'fields': {**FIELDS, 'disclosure': 'unknown'}}):
            path.write_text(json.dumps({**original, **change}))
            with self.assertRaises(ValueError):
                drafts.read_publishing_draft(path.name)
            choices, _, warnings = drafts.saved_publishing_drafts(self.report)
            self.assertEqual(choices, {})
            self.assertEqual(len(warnings), 1)
            self.assertTrue(path.is_file())
        with self.assertRaises(ValueError):
            drafts.read_publishing_draft('../outside.json')
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            drafts.save_publishing_draft(self.report, {**FIELDS, 'description': '가' * draft_store.MAX_BYTES})
        with patch.object(Path, 'iterdir', side_effect=PermissionError('fixture denied')):
            with self.assertRaises(PermissionError):
                drafts.saved_publishing_drafts(self.report)


class PublishingDraftUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        for target, name, value in ((settings, 'output_dir', self.root), (core, 'loop', asyncio.get_running_loop())):
            setting = patch.object(target, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.client = Client(page('/publishing-draft'))
        self.addCleanup(self.client.delete)
        self.report = completed_output(self.root)
        Path(self.report['video_path']).with_suffix('.upload-pending.json').write_text('{"status":"unknown"}')
        self.state = AppState(final_video_path=self.report['video_path'])
        self.state.get_or_create_service = Mock(side_effect=AssertionError('No upload allowed'))
        self.original = {p: p.read_bytes() for p in self.root.iterdir()}
        notify = patch.object(publishing_tab, 'safe_notify')
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def render(self):
        with self.client, ui.column() as root:
            publishing_tab.render_publishing_tab(self.state)
        return root

    def field(self, root, label):
        return next(e for e in root.descendants() if e._props.get('label') == label)

    def click(self, root, text):
        button = next(e for e in root.descendants() if getattr(e, 'text', '') == text)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    async def flush(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_save_new_session_restore_and_backup_preserve_video_and_upload_records(self):
        root = self.render()
        with self.client:
            self.field(root, '게시 초안 저장·복원').set_value(True)
            self.field(root, '영상 제목').set_value(FIELDS['title'])
            self.field(root, '영상 설명·출처').set_value(FIELDS['description'])
            self.field(root, '태그 (쉼표로 구분)').set_value(FIELDS['tags'])
            self.click(root, '게시 초안 사본 저장')
        await self.flush()
        self.assertTrue(self.field(root, '게시 초안 저장·복원').value)
        choices, _, _ = drafts.saved_publishing_drafts(self.report)
        self.assertEqual(len(choices), 1)
        self.state = AppState(final_video_path=self.report['video_path'])
        root = self.render()
        self.assertEqual(self.field(root, '영상 제목').value, '기록 제목')
        with self.client:
            self.field(root, '영상 제목').set_value('새로 쓰던 제목')
            self.field(root, '이 영상의 저장된 게시 초안').set_value(next(iter(choices)))
            self.click(root, '게시 초안 불러오기')
        await self.flush()
        self.assertEqual(self.field(root, '영상 제목').value, FIELDS['title'])
        self.assertEqual(self.state.publishing_drafts[drafts.publishing_key(self.report)], FIELDS)
        self.assertEqual(len(drafts.saved_publishing_drafts(self.report)[0]), 2)
        self.assertIsNone(self.state.production_service)
        for path, content in self.original.items():
            self.assertEqual(path.read_bytes(), content)

    async def test_busy_stale_and_file_change_callbacks_preserve_current_form(self):
        saved = drafts.save_publishing_draft(self.report, FIELDS)
        root = self.render()
        with self.client:
            self.field(root, '영상 제목').set_value('현재 입력')
            self.field(root, '이 영상의 저장된 게시 초안').set_value(saved.name)
            for change in ('busy', 'selection', 'file'):
                self.state.youtube_upload_in_progress = change == 'busy'
                self.state.final_video_path = 'different.mp4' if change == 'selection' else self.report['video_path']
                if change == 'file':
                    Path(self.report['video_path']).write_bytes(b'changed file')
                self.click(root, '게시 초안 불러오기')
                self.click(root, '게시 초안 사본 저장')
        self.assertEqual(self.field(root, '영상 제목').value, '현재 입력')
        self.assertEqual(len(list((self.root / 'evaluation/publishing_drafts').glob('*.json'))), 1)
        self.state.get_or_create_service.assert_not_called()

    async def test_snapshot_tamper_and_backup_failure_do_not_change_form(self):
        saved = drafts.save_publishing_draft(self.report, FIELDS)
        root = self.render()
        with self.client:
            self.field(root, '영상 제목').set_value('작성 중 보존')
            self.field(root, '이 영상의 저장된 게시 초안').set_value(saved.name)
            with patch.object(draft_store.os, 'fsync', side_effect=OSError('fixture full')):
                self.click(root, '게시 초안 불러오기')
            self.assertEqual(self.field(root, '영상 제목').value, '작성 중 보존')
            saved.write_bytes(saved.read_bytes() + b'\n')
            self.click(root, '게시 초안 불러오기')
        self.assertEqual(self.field(root, '영상 제목').value, '작성 중 보존')
        self.assertIsNone(self.state.production_service)

    async def test_deleted_snapshot_view_cannot_overwrite_newer_input_for_same_video(self):
        saved = drafts.save_publishing_draft(self.report, FIELDS)
        root = self.render()
        with self.client:
            self.field(root, '이 영상의 저장된 게시 초안').set_value(saved.name)
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '게시 초안 불러오기')
            late_handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            root.clear()
        fresh = self.render()
        with self.client:
            self.field(fresh, '영상 제목').set_value('새 화면에서 편집 중')
            late_handler(None)
        self.assertEqual(self.state.publishing_drafts[drafts.publishing_key(self.report)]['title'], '새 화면에서 편집 중')
        self.assertEqual(self.field(fresh, '영상 제목').value, '새 화면에서 편집 중')
        self.assertEqual(len(drafts.saved_publishing_drafts(self.report)[0]), 1)
