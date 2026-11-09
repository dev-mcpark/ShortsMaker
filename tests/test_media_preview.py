"""Installed NiceGUI media lifecycle checks; no browser or provider is used."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import PropertyMock, patch
from urllib.parse import unquote

from nicegui import app, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.common.media_preview import media_sources


class MediaPreviewTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.clip = self.root / 'clip.mp4'
        self.clip.write_bytes(b'local route fixture')
        self.client = Client(page('/media-preview-test'))
        self.client.__enter__()
        self.addCleanup(self.client.delete)
        self.addCleanup(lambda: self.client.__exit__(None, None, None))

    @staticmethod
    def route_exists(source):
        return any(getattr(route, 'path', None) == unquote(source) for route in app.routes)

    def sources(self):
        cleanup = []
        with patch.object(ui.context.client, 'on_delete', side_effect=cleanup.append) as register:
            source = media_sources()
        register.assert_called_once()
        self.assertEqual(len(cleanup), 1)
        self.addCleanup(cleanup[0])
        return source, cleanup[0]

    def test_same_file_widgets_keep_live_route_when_old_widget_is_deleted(self):
        source, cleanup = self.sources()
        url = source(self.clip)
        old = ui.video(url)
        live = ui.video(source(str(self.clip)))
        try:
            self.assertEqual(live._props['src'], url)
            self.assertTrue(self.route_exists(url))
            old.delete()
            self.assertTrue(self.route_exists(live._props['src']))
        finally:
            live.delete()
        self.assertTrue(self.route_exists(url))
        cleanup()
        self.assertFalse(self.route_exists(url))

    def test_bound_conversion_is_stable_without_a_slot_context(self):
        source, cleanup = self.sources()
        with patch.object(type(ui.context), 'slot_stack', new_callable=PropertyMock, return_value=[]):
            with self.assertRaises(RuntimeError):
                _ = ui.context.client
            first = source(self.clip)
            for _ in range(10):
                self.assertEqual(source(str(self.clip)), first)
        self.assertTrue(self.route_exists(first))
        cleanup()
        self.assertFalse(self.route_exists(first))

    def test_view_factories_have_separate_routes_and_cleanup_ownership(self):
        first, close_first = self.sources()
        second, close_second = self.sources()
        first_url, second_url = first(self.clip), second(self.clip)
        self.assertNotEqual(first_url, second_url)
        close_first()
        self.assertFalse(self.route_exists(first_url))
        self.assertTrue(self.route_exists(second_url))
        self.assertEqual(second(self.clip), second_url)
        close_second()
        self.assertFalse(self.route_exists(second_url))

    def test_file_replacement_changes_url_for_mtime_or_size_and_cleanup_covers_all_versions(self):
        source, cleanup = self.sources()
        original = source(self.clip)
        stat = self.clip.stat()
        self.clip.write_bytes(b'replaced fixture!!!')
        self.assertEqual(self.clip.stat().st_size, stat.st_size)
        os.utime(self.clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        replacement = source(self.clip)
        self.assertNotEqual(replacement, original)
        self.clip.write_bytes(b'a different size')
        os.utime(self.clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        resized = source(self.clip)
        self.assertNotEqual(resized, replacement)
        for url in (original, replacement, resized):
            self.assertTrue(self.route_exists(url))
        cleanup()
        for url in (original, replacement, resized):
            self.assertFalse(self.route_exists(url))

    def test_image_with_korean_filename_survives_widget_deletion_and_cleans_its_route(self):
        from PIL import Image

        frame = self.root / '첫 프레임.png'
        Image.new('RGB', (2, 2)).save(frame)
        source, cleanup = self.sources()
        url = source(frame)
        self.addCleanup(lambda: app.remove_route(unquote(url)))
        old, live = ui.image(url), ui.image(source(frame))
        try:
            old.delete()
            self.assertTrue(self.route_exists(live._props['src']))
        finally:
            live.delete()
        cleanup()
        self.assertFalse(self.route_exists(url))

    def test_empty_or_missing_sources_do_not_register_routes(self):
        source, cleanup = self.sources()
        before = len(app.routes)
        self.assertEqual(source(None), '')
        self.assertEqual(source(''), '')
        self.assertEqual(source(self.root / 'missing.mp4'), '')
        self.assertEqual(len(app.routes), before)
        cleanup()
