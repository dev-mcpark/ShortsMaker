"""Real local MP4s and delayed imports; never generate provider media or upload to YouTube."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from moviepy import ColorClip
from nicegui import core, ui
from nicegui.client import Client
from nicegui.elements.video import Video
from nicegui.page import page

from shorts_maker.gui.components import generation_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.config import settings
from shorts_maker.utils.media_validation import is_playable_video
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from test_gui_creation_flows import callback, script


class ManualClipImportTests(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = []
        with TemporaryDirectory() as folder:
            for index, color in enumerate(((30, 70, 110), (180, 60, 30))):
                path = Path(folder) / f'{index}.mp4'
                with ColorClip((32, 48), color, duration=.4) as clip:
                    clip.write_videofile(str(path), fps=5, codec='libx264', audio=False, logger=None)
                cls.encoded.append(path.read_bytes())

    async def asyncSetUp(self):
        directory = TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in ('clips_dir', 'output_dir'):
            self.enterContext(patch.object(settings, name, self.root / name))
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        self.exporter = VeoPromptExporter()
        self.state = AppState(script=script(), manual_video_mode=True, final_video_path='keep-final.mp4', generated_clips=['kept.mp4'])
        self.state.confirm_script_review()
        self.state.manual_script_id = self.exporter.create_workspace(self.state.script)
        self.path = self.exporter.get_clip_path(self.state.manual_script_id, 1)
        self.path.write_bytes(self.encoded[0])
        self.manifest = self.path.parent / 'workspace.json'
        self.manifest_before = self.manifest.read_bytes()
        self.notify = Mock()
        self.redraw = Mock()

    def handler(self, exporter=None, redraw=None, container=None):
        return callback('generation_tab.py', 'make_upload_handler', {
            'state': self.state, 'scene_num': 1, 'exporter': exporter or self.exporter,
            'safe_notify': self.notify, 'logger': Mock(), 'render_manual_panel': redraw or self.redraw,
            'start_edit_btn': Mock(), 'scene_cards_container': container})()

    @staticmethod
    def upload(content):
        return SimpleNamespace(file=SimpleNamespace(read=AsyncMock(return_value=content)))

    async def test_corrupt_and_empty_replacements_keep_valid_clip_results_review_and_workspace(self):
        before = self.state.reviewed_script_sha256
        for content in (b'', b'not a video'):
            event = self.upload(content);event.sender = Mock(is_deleted=False)
            await self.handler()(event)
            event.sender.reset.assert_called_once()
            self.assertIn(f'{self.state.manual_script_id}:1', self.state.manual_clip_errors)
            self.assertEqual(self.path.read_bytes(), self.encoded[0])
            self.assertTrue(is_playable_video(self.path))
            self.assertEqual(self.state.final_video_path, 'keep-final.mp4')
            self.assertEqual(self.state.generated_clips, ['kept.mp4'])
            self.assertEqual(self.state.reviewed_script_sha256, before)
            self.assertFalse(self.state.is_busy)
            self.assertFalse(list(self.path.parent.glob('.*.tmp.mp4')))
            self.assertEqual(self.manifest_before, self.manifest.read_bytes())
        self.redraw.assert_not_called()
        self.assertTrue(all(call.kwargs['type'] == 'negative' for call in self.notify.call_args_list))

    async def test_invalid_first_upload_does_not_create_a_false_ready_scene(self):
        self.path.unlink()
        await self.handler()(self.upload(b'broken first upload'))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.exporter.all_clips_ready(self.state.script, self.state.manual_script_id))
        self.assertEqual(self.state.final_video_path, 'keep-final.mp4')

    async def test_valid_replacement_is_decoded_before_atomic_replace_and_clears_only_selected_result(self):
        receipt = self.state.reviewed_script_sha256
        self.state.manual_clip_errors = {f'{self.state.manual_script_id}:1': 'earlier invalid file', 'other:1': 'keep other error'}
        self.redraw.side_effect = RuntimeError('old view deleted')
        await self.handler()(self.upload(self.encoded[1]))
        self.assertEqual(self.state.manual_clip_errors, {'other:1': 'keep other error'})
        self.assertEqual(self.path.read_bytes(), self.encoded[1])
        self.assertTrue(ProductionService._valid_clip(self.path, 'video'))
        self.assertEqual(self.manifest_before, self.manifest.read_bytes())
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertFalse(self.state.is_busy)
        self.redraw.assert_called_once()
        self.assertFalse(list(self.path.parent.glob('.*.tmp.mp4')))

    async def test_decoder_and_replace_failures_preserve_previous_clip_and_clean_pending_file(self):
        with patch('shorts_maker.utils.media_validation.VideoFileClip', side_effect=OSError('decode failure')) as decode:
            with self.assertRaises(ValueError):
                self.exporter.save_uploaded_clip(self.encoded[1], self.state.manual_script_id, 1)
            decode.assert_called_once()
        with patch('shorts_maker.utils.veo_prompt_exporter.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.exporter.save_uploaded_clip(self.encoded[1], self.state.manual_script_id, 1)
        self.assertEqual(self.path.read_bytes(), self.encoded[0])
        self.assertFalse(list(self.path.parent.glob('.*.tmp.mp4')))

    async def test_failed_thread_submission_releases_only_its_own_busy_state(self):
        with patch('asyncio.to_thread', side_effect=RuntimeError('thread submission failed')):
            await self.handler()(self.upload(self.encoded[1]))
        self.assertFalse(self.state.is_busy)
        self.assertFalse(self.state.media_import_in_progress)
        self.assertEqual(self.state.final_video_path, 'keep-final.mp4')
        self.assertEqual(self.path.read_bytes(), self.encoded[0])

    async def test_delayed_import_is_nonblocking_exclusive_and_cancellation_waits_for_actual_save(self):
        entered, release = Event(), Event()
        original = self.exporter.save_uploaded_clip
        def delayed(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('fixture release timeout')
            return original(*args)
        exporter = SimpleNamespace(save_uploaded_clip=Mock(side_effect=delayed), all_clips_ready=Mock(return_value=True))
        task = asyncio.create_task(self.handler(exporter)(self.upload(self.encoded[1])))
        try:
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3))
            self.assertTrue(self.state.is_busy)
            self.assertTrue(self.state.media_import_in_progress)
            self.assertEqual(self.path.read_bytes(), self.encoded[0])
            with self.assertRaises(ValueError):
                self.state.load_saved_script(script('should not load'))
            duplicate = self.upload(self.encoded[0])
            await self.handler(exporter)(duplicate)
            duplicate.file.read.assert_not_awaited()
            task.cancel();await asyncio.sleep(.01);task.cancel();await asyncio.sleep(.01)
            self.assertFalse(task.done())
            self.assertTrue(self.state.is_busy)
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        exporter.save_uploaded_clip.assert_called_once()
        self.assertFalse(self.state.is_busy)
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual(self.path.read_bytes(), self.encoded[1])

    async def test_old_read_completion_after_source_or_scope_change_does_not_save(self):
        for change in (lambda: setattr(self.state, 'manual_video_mode', False), self.state.detach_operating_scope):
            self.state.manual_video_mode = True
            handler = self.handler()
            entered, release = asyncio.Event(), asyncio.Event()
            async def read():
                entered.set();await release.wait();return self.encoded[1]
            task = asyncio.create_task(handler(SimpleNamespace(file=SimpleNamespace(read=read))))
            await entered.wait();change();release.set();await task
            self.assertEqual(self.path.read_bytes(), self.encoded[0])
            self.assertEqual(self.state.final_video_path, 'keep-final.mp4')
            self.assertFalse(self.state.is_busy)

    async def test_new_view_opened_during_import_refreshes_once_after_idle_without_spending(self):
        self.path.unlink()
        self.state.media_import_in_progress = True
        client = Client(page('/manual-import'));self.addCleanup(client.delete)
        timers = []
        def timer(interval, handler):
            item = SimpleNamespace(callback=handler, cancel=Mock());timers.append(item);return item
        with client, patch.object(generation_tab.ui, 'timer', side_effect=timer):
            root = ui.column();button = ui.button()
            self.state.manual_clip_errors = {f'{self.state.manual_script_id}:1': 'earlier import failed'}
            generation_tab.render_manual_panel(self.state, self.exporter, button, root)
            self.assertTrue(any(getattr(e, 'text', '') == 'earlier import failed' for e in root.descendants()))
            self.assertFalse(any(isinstance(e, Video) for e in root.descendants()))
            timers[0].callback();timers[0].cancel.assert_not_called()
            self.exporter.save_uploaded_clip(self.encoded[1], self.state.manual_script_id, 1)
            self.state.media_import_in_progress = False
            timers[0].callback()
            timers[0].cancel.assert_called_once()
            self.assertTrue(any(isinstance(e, Video) for e in root.descendants()))
            self.assertEqual(len(timers), 1)
