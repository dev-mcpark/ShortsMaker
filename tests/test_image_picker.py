"""Native Studio controls choose existing media without implicit review or providers."""

import asyncio
import ast
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import asset_library_tab, generation_tab, image_picker
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.gui.state.session_manager import SessionManager
from shorts_maker.services.asset_library import AssetLibrary
from shorts_maker.services.visual_review import approve_first_frame, inspect_frame
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class ImagePickerTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        for name, value in [('output_dir', self.root / 'outputs'), ('clips_dir', self.root / 'outputs/clips')]:
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start()
        self.addCleanup(loop.stop)
        self.client = Client(page('/image-picker'))
        self.addCleanup(self.client.delete)
        self.library = AssetLibrary(roots={'outputs': settings.output_dir}, project_root=self.root)
        settings.output_dir.mkdir()
        self.frame = settings.output_dir / 'first_frame.png'
        Image.new('RGB', (540, 960), '#557799').save(self.frame)
        self.state = AppState(script=script(), mode='video', final_video_path='kept.mp4')
        self.state.confirm_script_review()

    def control(self, label):
        return next(e for e in self.client.elements.values() if e._props.get('label') == label)

    def click(self, label):
        button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == label)
        return next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    async def flush(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        binding._refresh_step()

    async def test_imported_image_is_only_a_scene_draft_and_keeps_prior_result(self):
        from types import SimpleNamespace
        from shorts_maker.services.visual_review import review_path
        receipt = self.state.reviewed_script_sha256
        with self.client:
            generation_tab.render_first_frame_reviews(self.state)
            with patch.object(image_picker, 'AssetLibrary', return_value=self.library):
                await self.click_and_wait('이미지 선택·가져오기')
            uploader = next(e for e in self.client.elements.values() if e.__class__.__name__ == 'Upload')
            await uploader._upload_handlers[0](SimpleNamespace(
                file=SimpleNamespace(read=AsyncMock(return_value=self.frame.read_bytes())), sender=uploader))
        selected = self.control('첫 프레임 PNG/JPEG 경로').value
        self.assertNotEqual(selected, str(self.frame))
        self.assertTrue(Path(selected).is_file())
        self.assertTrue(self.state.has_unapplied_first_frame_drafts())
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertFalse(review_path(self.state.script, self.state.script.scenes[0]).exists())

    async def click_and_wait(self, label, task_name='pick_image'):
        before = asyncio.all_tasks()
        self.click(label)
        tasks = [task for task in asyncio.all_tasks() - before if task_name in task.get_name()]
        self.assertTrue(tasks)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)

    async def test_first_frame_picker_previews_without_approval_and_draft_survives_view_reentry(self):
        receipt = self.state.reviewed_script_sha256
        with self.client, ui.column() as root:
            generation_tab.render_first_frame_reviews(self.state)
        with self.client:
            self.control('반드시 보여야 할 내용 (한 줄에 하나)').set_value('버스 공간 전체')
            self.control('피해야 할 묘사 (한 줄에 하나)').set_value('실제 장소로 오인')
            self.control('검토 의견').set_value('현재 장면 후보')
            with patch.object(image_picker, 'AssetLibrary', return_value=self.library):
                await self.click_and_wait('이미지 선택·가져오기')
            self.control('이미지 파일 검색').set_value('outputs/first_frame.png')
            self.click('선택 이미지 미리보기')
        self.assertEqual(self.control('첫 프레임 PNG/JPEG 경로').value, str(self.frame))
        self.assertFalse((settings.output_dir / 'evaluation/visual_reviews').exists())
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        with self.client, root:
            root.clear()
            generation_tab.render_first_frame_reviews(self.state)
        await self.flush()
        self.assertEqual(self.control('첫 프레임 PNG/JPEG 경로').value, str(self.frame))
        self.assertEqual(self.control('검토 의견').value, '현재 장면 후보')
        self.assertEqual(self.control('반드시 보여야 할 내용 (한 줄에 하나)').value, '버스 공간 전체')
        self.assertEqual(self.control('피해야 할 묘사 (한 줄에 하나)').value, '실제 장소로 오인')
        old_note = self.control('검토 의견')
        self.state.load_saved_script(script('another'))
        with self.client:
            old_note.set_value('오래된 입력')
        self.assertNotIn(self.state.script_editor_key(), self.state.first_frame_drafts)
        with self.client, root:
            root.clear()
            generation_tab.render_first_frame_reviews(self.state)
        await self.flush()
        self.assertEqual(self.control('검토 의견').value, '')

    async def test_picker_rechecks_media_path_and_stale_or_cancelled_dialog_cannot_select(self):
        selected = Mock()
        current = Mock(return_value=True)
        (settings.output_dir / 'link.png').symlink_to(self.frame)
        with self.client, patch.object(image_picker, 'AssetLibrary', return_value=self.library):
            await image_picker.open_image_picker(selected, current)
            choice = self.control('이미지 파일 검색')
            self.assertIn('outputs/first_frame.png', choice.options)
            self.assertNotIn('outputs/link.png', choice.options)
            choice.set_value('outputs/first_frame.png')
            self.frame.unlink()
            self.click('선택 이미지 미리보기')
            selected.assert_not_called()
            Image.new('RGB', (540, 960)).save(self.frame)
            current.return_value = False
            self.click('선택 이미지 미리보기')
            selected.assert_not_called()
            current.return_value = True
            self.click('취소')
            self.click('선택 이미지 미리보기')
            selected.assert_not_called()

    async def test_invalid_frame_and_late_scan_leave_existing_selection_unchanged(self):
        with self.client:
            generation_tab.render_first_frame_reviews(self.state)
            self.control('첫 프레임 PNG/JPEG 경로').set_value(str(self.frame))
            self.click('이미지 미리보기')
            invalid = settings.output_dir / 'landscape.png'
            Image.new('RGB', (960, 540)).save(invalid)
            with patch.object(image_picker, 'AssetLibrary', return_value=self.library):
                await self.click_and_wait('이미지 선택·가져오기')
            self.control('이미지 파일 검색').set_value('outputs/landscape.png')
            self.click('선택 이미지 미리보기')
            self.assertEqual(self.control('첫 프레임 PNG/JPEG 경로').value, str(self.frame))
        selected = Mock()
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            entered.set()
            await release.wait()
            return {'rows': [], 'warnings': []}

        current = Mock(return_value=True)
        async def open_later():
            with self.client:
                await image_picker.open_image_picker(selected, current)
        with self.client, patch.object(image_picker.run, 'io_bound', side_effect=delayed):
            task = asyncio.create_task(open_later())
            await asyncio.wait_for(entered.wait(), timeout=2)
            current.return_value = False
            release.set()
            await task
        selected.assert_not_called()

    async def test_unapproved_frame_draft_protects_an_old_temporary_image_from_cleanup(self):
        old = self.root / 'temp/old.png'
        old.parent.mkdir()
        Image.new('RGB', (540, 960)).save(old)
        os.utime(old, (time.time() - 90000,) * 2)
        self.state.first_frame_drafts[self.state.script_editor_key()] = {1: {'frame_path': str(old)}}
        library = AssetLibrary(roots={'temp': old.parent}, project_root=self.root)
        self.assertTrue(library.scan()['rows'][0]['cleanable'])

        def connected_library(**kwargs):
            library.active_references = kwargs['active_references']
            library.busy = kwargs['busy']
            return library

        with self.client, patch.object(SessionManager, '_sessions', {'fixture': self.state}), patch.object(
                asset_library_tab, 'AssetLibrary', side_effect=connected_library):
            asset_library_tab.render_asset_library_tab(self.state)
            row = library.scan()['rows'][0]
        self.assertFalse(row['cleanable'])
        self.assertIn('현재 브라우저 작업', row['reason'])

    async def test_unapplied_frame_inputs_block_old_paid_events_until_approval_or_discard(self):
        frame_hash = inspect_frame(str(self.frame))
        review = approve_first_frame(self.state.script, self.state.script.scenes[0], str(self.frame),
                                     ['전체 공간'], ['가짜 글자'], '원본 검토', frame_hash)
        original = review.read_bytes()
        service = Mock()
        service.max_veo_attempts = 1
        service.video_spec.return_value = ('veo-3.1-fast-generate-001', 6)
        service.review_clip_path.return_value = (None, frame_hash)
        service.generate_review_clip = AsyncMock()
        self.state.get_or_create_service = Mock(return_value=service)
        self.state.new_production_service = Mock()
        with self.client, patch.object(settings, 'paid_production_enabled', True):
            generation_tab.render_first_frame_reviews(self.state)
            generation_tab.render_raw_clip_reviews(self.state)
            self.assertTrue(generation_tab._auto_edit_ready(self.state, {0: 'approved'}))
            self.control('검토 의견').set_value('새 검토 기준')
            await self.flush()
            self.assertFalse(generation_tab._auto_edit_ready(self.state, {0: 'approved'}))
            self.assertIn('미적용 첫 프레임', generation_tab._next_edit_step(self.state, {0: 'approved'}))
            self.state.mode = 'image'
            self.assertFalse(self.state.has_unapplied_first_frame_drafts())
            self.state.mode = 'video'
            self.state.manual_video_mode = True
            self.assertFalse(self.state.has_unapplied_first_frame_drafts())
            self.state.manual_video_mode = False
            await self.click_and_wait('이 장면 Veo 원본 생성', 'generate')
            service.generate_review_clip.assert_not_awaited()
            node = next(n for n in ast.walk(ast.parse(Path(generation_tab.__file__).read_text()))
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_production_core')
            wrapper = ast.parse('def factory():\n video_player = None\n placeholder_content = None\n return _run_production_core\n')
            wrapper.body[0].body.insert(-1, node)
            env = {'state': self.state, 'rendered_script': self.state.script.model_dump_json(), 'safe_notify': Mock()}
            exec(compile(ast.fix_missing_locations(wrapper), 'frame-draft-edit', 'exec'), env)
            await env['factory']()()
            self.state.new_production_service.assert_not_called()
            self.assertEqual(self.state.final_video_path, 'kept.mp4')
            self.assertEqual(review.read_bytes(), original)
            self.click('첫 프레임 검토 입력 되돌리기')
            self.assertFalse(self.state.has_unapplied_first_frame_drafts())
            self.assertTrue(generation_tab._auto_edit_ready(self.state, {0: 'approved'}))
            self.control('검토 의견').set_value('명시적으로 다시 검토')
            self.click('이미지 미리보기')
            self.click('이 첫 프레임 승인')
            self.assertFalse(self.state.has_unapplied_first_frame_drafts())
            self.assertNotEqual(review.read_bytes(), original)

    async def test_empty_or_failed_inventory_has_recovery_text_without_selection(self):
        selected = Mock()
        library = Mock()
        library.scan.return_value = {'rows': [], 'warnings': ['Unreadable fixture record']}
        with self.client, patch.object(image_picker, 'AssetLibrary', return_value=library):
            await image_picker.open_image_picker(selected, lambda: True)
            text = '\n'.join(getattr(e, 'text', '') for e in self.client.elements.values())
            self.assertIn('보관함에 PNG/JPEG 이미지가 없습니다', text)
            self.assertIn('일부 보관함 기록을 읽지 못했습니다', text)
            library.scan.side_effect = OSError('fixture read failure')
            await image_picker.open_image_picker(selected, lambda: True)
            text = '\n'.join(getattr(e, 'text', '') for e in self.client.elements.values())
            self.assertIn('목록을 불러올 수 없습니다', text)
        selected.assert_not_called()
