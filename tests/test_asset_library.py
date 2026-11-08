"""Disposable storage fixtures only; never delete real production assets."""

import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from shorts_maker.services.asset_library import AssetLibrary, file_hash


class AssetLibraryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.roots = {key: self.root / key for key in ('outputs', 'temp', 'assets', 'bgm', 'logs')}
        for root in self.roots.values():
            root.mkdir()
        (self.root / 'docs').mkdir()
        self.busy = Mock(return_value=False)
        self.active = Mock(return_value=[])
        self.library = AssetLibrary(roots=self.roots, project_root=self.root,
                                    busy=self.busy, active_references=self.active)

    def media(self, key='temp/old.mp4'):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'disposable fixture only')
        os.utime(path, (time.time() - 90000,) * 2)
        return path

    def final(self, name='unused.mp4', **overrides):
        path = self.media('outputs/' + name)
        report = {'schema_version': 1, 'video_path': str(path), 'quality_passed': True,
                  'video_sha256': file_hash(path), **overrides}
        path.with_suffix('.production.json').write_text(json.dumps(report))
        return path

    def row(self, key):
        return next(r for r in self.library.scan()['rows'] if r['id'] == key)

    def test_lists_sizes_media_and_protected_records(self):
        path = self.media()
        self.media('outputs/clips/scenes/source/clip.mp4')
        self.media('assets/frame.png')
        self.media('bgm/music.mp3')
        self.media('logs/private.log')
        self.media('outputs/evaluation/google_budget.sqlite3')
        result = self.library.scan()
        self.assertEqual(len(result['rows']), 6)
        self.assertEqual(result['bytes'], path.stat().st_size * 6)
        self.assertEqual(result['cleanable_bytes'], path.stat().st_size)
        self.assertEqual(sum(r['cleanable'] for r in result['rows']), 1)
        for key in ('logs/private.log', 'outputs/evaluation/google_budget.sqlite3', '../config/key.json'):
            with self.assertRaises(ValueError):
                self.library.preview(key)

    def test_recent_temp_and_unbound_final_are_not_candidates(self):
        path = self.media()
        os.utime(path, None)
        self.media('outputs/no_report.mp4')
        self.assertFalse(self.row('temp/old.mp4')['cleanable'])
        self.assertFalse(self.row('outputs/no_report.mp4')['cleanable'])

    def test_own_sidecar_is_not_external_reference_and_legacy_hash_is_optional_for_deletion_only(self):
        for name, overrides in [('new.mp4', {}), ('legacy.mp4', {'video_sha256': None})]:
            self.final(name, **overrides)
            plan = self.library.prepare_delete(['outputs/' + name])
            self.assertEqual(len(plan['files']), 1)
            self.assertEqual(len(plan['files'][0]['sha256']), 64)

    def test_each_upload_signal_protects_edited_video(self):
        for signal in ({'youtube_id': 'private-id'}, {'youtube_upload_request': {'status': {}}}, {'youtube_upload_request': {}},
                       {'uploaded_at_utc': '2026-11-08'}):
            self.final(**signal)
            self.assertFalse(self.row('outputs/unused.mp4')['cleanable'])
        path = self.final()
        path.with_suffix('.upload-pending.json').write_text('{}')
        self.assertFalse(self.row('outputs/unused.mp4')['cleanable'])

    def test_source_record_html_encoded_link_and_schedule_each_protect(self):
        path = self.final('한 글.mp4')
        for reference, content in (
            (self.root / 'docs' / 'review.md', path.name),
            (self.root / 'outputs' / 'review.html', '한%20글.mp4'),
            (self.root / 'schedules.json', json.dumps({'last_video_path': str(path)})),
        ):
            reference.write_text(content)
            self.assertFalse(self.row('outputs/한 글.mp4')['cleanable'])
            self.assertIn(str(reference.relative_to(self.root)), self.row('outputs/한 글.mp4')['reason'])
            reference.unlink()
        self.assertTrue(self.row('outputs/한 글.mp4')['cleanable'])

    def test_session_and_unverified_operation_guard(self):
        self.media()
        self.active.return_value = ['old.mp4']
        self.assertFalse(self.row('temp/old.mp4')['cleanable'])
        self.active.return_value = []
        self.busy.return_value = True
        with self.assertRaises(ValueError):
            self.library.prepare_delete(['temp/old.mp4'])
        self.busy.return_value = False
        marker = self.root / 'outputs' / 'episode.operation.pending.json'
        marker.write_text('{}')
        with self.assertRaises(ValueError):
            self.library.prepare_delete(['temp/old.mp4'])

    def test_directory_reference_and_temp_production_record_preserve_materials(self):
        path = self.media('temp/retained_voice_set/narration.wav')
        record = self.root / 'outputs' / 'audio.json'
        record.write_text(json.dumps({'narration_dir': str(path.parent)}))
        self.assertFalse(self.row('temp/retained_voice_set/narration.wav')['cleanable'])
        path = self.media('temp/scratch.mp4')
        path.with_suffix('.production.json').write_text(json.dumps({'video_path': str(path)}))
        self.assertFalse(self.row('temp/scratch.mp4')['cleanable'])

    def test_corrupt_record_and_late_unreadable_file_block_all_deletion(self):
        self.media()
        (self.root / 'outputs' / 'damaged.json').write_text('{')
        result = self.library.scan()
        self.assertTrue(result['warnings'])
        self.assertFalse(self.row('temp/old.mp4')['cleanable'])
        with self.assertRaises(ValueError):
            self.library.prepare_delete(['temp/old.mp4'])

    def test_links_cannot_escape_or_hide_media_usage(self):
        target = self.final()
        link = self.root / 'outputs' / 'review-copy.mp4'
        link.symlink_to(target)
        self.assertFalse(self.row('outputs/unused.mp4')['cleanable'])
        self.assertFalse(self.row('outputs/review-copy.mp4')['cleanable'])
        for key in ('outputs/review-copy.mp4', 'outputs/../temp/old.mp4', '/etc/passwd'):
            with self.assertRaises(ValueError):
                self.library.preview(key)
        outside = self.root / 'config'
        outside.mkdir()
        (outside / 'private.png').write_bytes(b'private')
        (self.root / 'temp' / 'escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.library.preview('temp/escape/private.png')

    def test_changed_file_or_new_reference_invalidates_confirmation_before_any_delete(self):
        first = self.media()
        second = self.media('temp/second.mp4')
        keys = ['temp/old.mp4', 'temp/second.mp4']
        plan = self.library.prepare_delete(keys)
        second.write_bytes(b'changed')
        os.utime(second, (time.time() - 90000,) * 2)
        with self.assertRaises(ValueError):
            self.library.delete(plan)
        self.assertTrue(first.exists())
        plan = self.library.prepare_delete(keys)
        (self.root / 'docs' / 'new.md').write_text(first.name)
        with self.assertRaises(ValueError):
            self.library.delete(plan)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_hash_mismatch_blocks_cleanup_without_modifying_video(self):
        path = self.final(video_sha256='0' * 64)
        with self.assertRaises(ValueError):
            self.library.prepare_delete(['outputs/unused.mp4'])
        self.assertTrue(path.exists())

    def test_explicit_delete_preserves_sidecar_and_audit_receipt(self):
        path = self.final()
        sidecar = path.with_suffix('.production.json')
        before = sidecar.read_bytes()
        result = self.library.delete(self.library.prepare_delete(['outputs/unused.mp4']))
        self.assertFalse(path.exists())
        self.assertEqual(sidecar.read_bytes(), before)
        self.assertEqual(result['state'], 'deleted')
        self.assertEqual(result['deleted_bytes'], len(b'disposable fixture only'))
        receipts = list((self.root / 'outputs/evaluation/storage_cleanup').glob('*.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text()), result)

    def test_receipt_write_failure_stops_before_unlink(self):
        path = self.media()
        plan = self.library.prepare_delete(['temp/old.mp4'])
        with patch.object(self.library, '_write_receipt', side_effect=OSError('full disk')):
            with self.assertRaises(OSError):
                self.library.delete(plan)
        self.assertTrue(path.exists())

    def test_partial_failure_reports_actual_deleted_bytes_and_keeps_remaining_file(self):
        first = self.media()
        second = self.media('temp/second.mp4')
        plan = self.library.prepare_delete(['temp/old.mp4', 'temp/second.mp4'])
        unlink = Path.unlink

        def fail_second(path, *args, **kwargs):
            if path == second:
                raise PermissionError('fixture refusal')
            return unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_second):
            result = self.library.delete(plan)
        self.assertEqual(result['state'], 'partial_failure')
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(result['deleted_bytes'], len(b'disposable fixture only'))

    def test_ui_requires_concrete_plan_and_confirmation_before_deleting_fixture(self):
        from test_gui_operation_flows import _UI
        from shorts_maker.gui.components import asset_library_tab as tab

        path = self.media()
        ui = _UI()
        create_table = ui.table

        def table(**kwargs):
            element = create_table(**kwargs)
            element.rows, element.selected, element.pagination = [], [], {'page': 1}
            return element

        ui.table = table
        ui.context = SimpleNamespace(client=SimpleNamespace(on_delete=Mock()))
        with patch.object(tab, 'ui', ui), patch.object(tab, 'AssetLibrary', return_value=self.library):
            tab.render_asset_library_tab(SimpleNamespace(is_busy=False))
            listing = next(e for e in ui.elements if e.kind == 'table')
            listing.selected = [self.row('temp/old.mp4')]
            ui.find('button', '선택 파일 정리 검토').callback()
            deletion = ui.find('button', '선택 파일 영구 삭제')
            confirmation = ui.find('checkbox', '선택한 파일의 영구 삭제를 확인했습니다')
            deletion.callback()
            self.assertTrue(path.exists())
            confirmation.value = True
            deletion.callback()
            self.assertFalse(path.exists())
