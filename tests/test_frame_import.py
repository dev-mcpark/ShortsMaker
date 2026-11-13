"""Local first-frame imports are immutable material copies, never approvals."""
import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page
from shorts_maker.gui.components import image_picker
from shorts_maker.services.visual_review import import_frame, inspect_frame, MAX_FRAME_BYTES
from shorts_maker.utils.config import settings


def image_bytes(fmt='PNG', size=(360, 640)):
    output = io.BytesIO()
    Image.new('RGB', size, '#426688').save(output, format=fmt)
    return output.getvalue()


class FrameImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        setting = patch.object(settings, 'output_dir', self.root)
        setting.start(); self.addCleanup(setting.stop)

    def test_png_and_jpeg_are_validated_private_copies_with_no_review_records(self):
        for fmt, suffix in [('PNG', '.png'), ('JPEG', '.jpg')]:
            content = image_bytes(fmt)
            first, second = import_frame(content), import_frame(content)
            self.assertNotEqual(first, second)
            self.assertEqual(first.suffix, suffix)
            self.assertEqual(first.read_bytes(), content)
            self.assertEqual(inspect_frame(str(first)), inspect_frame(str(second)))
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.rglob('*.json')))
        self.assertFalse(list(self.root.rglob('.frame_*')))

    def test_invalid_format_ratio_size_and_io_leave_existing_images_unchanged(self):
        saved = import_frame(image_bytes())
        previous = saved.read_bytes()
        for content in (b'', b'not an image', image_bytes(size=(640, 360)),
                        image_bytes('GIF'), b'x' * (MAX_FRAME_BYTES + 1)):
            with self.subTest(length=len(content)), self.assertRaises((OSError, ValueError)):
                import_frame(content)
        with patch('shorts_maker.services.visual_review.os.link', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                import_frame(image_bytes())
        self.assertEqual(saved.read_bytes(), previous)
        self.assertEqual(list(saved.parent.iterdir()), [saved])

    def test_linked_import_directory_is_rejected(self):
        outside = self.root / 'other';outside.mkdir()
        (self.root / 'evaluation').mkdir()
        (self.root / 'evaluation' / 'imported_frames').symlink_to(outside)
        with self.assertRaises(ValueError):
            import_frame(image_bytes())
        self.assertEqual(list(outside.iterdir()), [])


class FrameImportUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for target, name, value in ((settings, 'output_dir', self.root),
                                    (core, 'loop', asyncio.get_running_loop())):
            p = patch.object(target, name, value);p.start();self.addCleanup(p.stop)
        self.client = Client(page('/frame-import'))
        self.addCleanup(self.client.delete)
        self.selected = Mock()
        self.current = Mock(return_value=True)
        with self.client, patch.object(image_picker.AssetLibrary, 'scan', return_value={'rows': [], 'warnings': []}):
            await image_picker.open_image_picker(self.selected, self.current)
        self.uploader = next(e for e in self.client.elements.values() if e.__class__.__name__ == 'Upload')

    async def send(self, content):
        event = SimpleNamespace(file=SimpleNamespace(read=AsyncMock(return_value=content)), sender=self.uploader)
        with self.client:
            handler = self.uploader._upload_handlers[0]
            await handler(event)

    async def test_success_selects_only_candidate_invalid_import_preserves_selection(self):
        with patch.object(image_picker, 'safe_notify'):
            await self.send(b'invalid')
            self.selected.assert_not_called()
            self.assertTrue(any('이미지 가져오기 실패' in getattr(e, 'text', '') for e in self.client.elements.values()))
            await self.send(image_bytes())
        path = Path(self.selected.call_args.args[0])
        self.assertTrue(path.is_file())
        self.assertFalse(list(self.root.rglob('*.json')))
        self.assertEqual(self.uploader._props.get('files'), None)

    async def test_late_import_keeps_material_but_never_attaches_to_changed_or_closed_view(self):
        started, release = asyncio.Event(), asyncio.Event()
        real_import = image_picker.import_frame
        # Control the async handoff while retaining the real atomic importer.
        async def held(function, *args):
            started.set();await release.wait();return real_import(*args)
        with patch.object(image_picker.asyncio, 'to_thread', side_effect=held), patch.object(image_picker, 'safe_notify'):
            task = asyncio.create_task(self.send(image_bytes()))
            await asyncio.wait_for(started.wait(), timeout=2)
            await self.send(image_bytes())
            await self.send(image_bytes())
            self.assertEqual(image_picker.asyncio.to_thread.call_count, 1)
            self.current.return_value = False
            release.set();await task
        self.selected.assert_not_called()
        self.assertEqual(len(list(self.root.rglob('*.png'))), 1)

    async def test_closed_dialog_and_changed_context_do_not_read_or_import(self):
        for close in (False, True):
            with self.subTest(close=close):
                self.current.return_value = not close
                if close:
                    next(e for e in self.client.elements.values() if e.__class__.__name__ == 'Dialog').close()
                else:
                    self.current.return_value = False
                with patch.object(image_picker, 'import_frame') as save, patch.object(self.uploader, 'reset') as reset:
                    await self.send(image_bytes())
                save.assert_not_called()
                reset.assert_called_once()
                self.selected.assert_not_called()

    async def test_cancellation_waits_for_owned_import_and_prevents_attachment(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def held(function, content):
            started.set();await release.wait();return import_frame(content)
        with patch.object(image_picker.asyncio, 'to_thread', side_effect=held):
            task = asyncio.create_task(self.send(image_bytes()))
            await asyncio.wait_for(started.wait(), timeout=2);task.cancel();await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.selected.assert_not_called()
        self.assertEqual(len(list(self.root.rglob('*.png'))), 1)
