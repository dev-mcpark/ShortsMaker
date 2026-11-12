"""Reuse exact-scene sources through existing import; no provider requests."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from moviepy import ColorClip
from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import existing_scene_picker, generation_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.existing_scene_clips import ExistingSceneClips
from shorts_maker.utils.config import settings
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from test_gui_creation_flows import script, callback as creation_callback


class ExistingSceneClipsTests(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'test.mp4'
            with ColorClip((32, 48), (70, 110, 150), duration=.4) as clip:
                clip.write_videofile(str(path), fps=5, codec='libx264', audio=False, logger=None)
            cls.video = path.read_bytes()

    async def asyncSetUp(self):
        directory = TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.enterContext(patch.object(settings, 'clips_dir', self.root / 'clips'))
        self.enterContext(patch.object(settings, 'output_dir', self.root / 'outputs'))
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        self.script = script()
        self.exporter = VeoPromptExporter()
        self.current = self.exporter.create_workspace(self.script)
        self.saved = self.exporter.create_workspace(self.script)
        self.source = self.exporter.save_uploaded_clip(self.video, self.saved, 1)
        self.service = SimpleNamespace(review_clip_path=Mock(side_effect=ValueError('no approved native')))
        self.reader = ExistingSceneClips(self.script, 1, self.service, self.current)
        self.client = Client(page('/existing-scenes'));self.addCleanup(self.client.delete)

    async def test_only_matching_scene_workspaces_are_listed_and_original_is_preserved(self):
        wrong = self.exporter.create_workspace(script('different script'))
        self.exporter.save_uploaded_clip(self.video, wrong, 1)
        self.exporter.save_uploaded_clip(self.video, self.current, 1)
        record = self.source.parent / 'workspace.json';before = record.read_bytes(), self.source.read_bytes()
        choices = self.reader.candidates()
        self.assertEqual(len(choices), 1)
        key, candidate = next(iter(choices.items()))
        path, identity = self.reader.preview(key, candidate)
        self.assertEqual(path, str(self.source))
        self.assertEqual(self.reader.read(key, candidate, identity), self.video)
        self.assertEqual(before, (record.read_bytes(), self.source.read_bytes()))

    async def test_pending_rejected_or_stale_native_sources_are_not_reusable(self):
        native = settings.clips_dir / 'native' / 'clip.mp4';native.parent.mkdir();native.write_bytes(self.video)
        self.service.review_clip_path.side_effect = None
        self.service.review_clip_path.return_value = (str(native), 'frame-hash')
        for verdict in ('pending', 'rejected', 'stale'):
            with patch('shorts_maker.services.existing_scene_clips.raw_review_status', return_value=verdict):
                self.assertTrue(all(row['workspace'] is not None for row in self.reader.candidates().values()))
        with patch('shorts_maker.services.existing_scene_clips.raw_review_status', return_value='approved'):
            choices = self.reader.candidates()
            key = next(key for key, row in choices.items() if row['workspace'] is None)
            candidate = choices[key]
            _, identity = self.reader.preview(key, candidate)
        with patch('shorts_maker.services.existing_scene_clips.raw_review_status', return_value='rejected'):
            with self.assertRaises(ValueError):
                self.reader.read(key, candidate, identity)
        self.assertEqual(native.read_bytes(), self.video)

    async def test_changed_file_workspace_symlink_or_oversized_input_cannot_be_imported(self):
        key, candidate = next(iter(self.reader.candidates().items()))
        _, identity = self.reader.preview(key, candidate)
        self.source.write_bytes(self.video + b'changed')
        with self.assertRaises(ValueError):
            self.reader.read(key, candidate, identity)
        self.source.write_bytes(self.video)
        self.source.write_bytes(b'not a video')
        with self.assertRaises(ValueError):
            self.reader.preview(key, candidate)
        self.source.write_bytes(self.video)
        record = self.source.parent / 'workspace.json';before = record.read_bytes()
        altered = json.loads(before);altered['script']['title'] = 'different story'
        record.write_text(json.dumps(altered))
        with self.assertRaises(ValueError):
            self.reader.read(key, candidate, identity)
        record.write_bytes(before)
        with patch('shorts_maker.services.existing_scene_clips.MAX_MANUAL_CLIP_BYTES', 1):
            with self.assertRaises(ValueError):
                self.reader.preview(key, candidate)
        original = self.source.read_bytes()
        with patch('shorts_maker.utils.veo_prompt_exporter.MAX_MANUAL_CLIP_BYTES', 1):
            with self.assertRaises(ValueError):
                self.exporter.save_uploaded_clip(self.video, self.saved, 1)
        self.assertEqual(self.source.read_bytes(), original)
        self.source.unlink();self.source.symlink_to(self.root / 'outside.mp4')
        with self.assertRaises(ValueError):
            self.reader.preview(key, candidate)

    async def test_preview_connect_feeds_original_callback_and_copy_preserves_source_and_authority(self):
        state = AppState(script=self.script, manual_video_mode=True, manual_script_id=self.current, final_video_path='old.mp4')
        state.confirm_script_review();receipt = state.reviewed_script_sha256
        async def direct(function, *args):
            return function(*args)
        connect = creation_callback('generation_tab.py', 'make_upload_handler', {
            'state': state, 'scene_num': 1, 'exporter': self.exporter, 'safe_notify': Mock(), 'logger': Mock(),
            'render_manual_panel': Mock(), 'start_edit_btn': Mock(), 'scene_cards_container': None})()
        with self.client, patch.object(existing_scene_picker.run, 'io_bound', side_effect=direct):
            await existing_scene_picker.open_existing_scene_picker(self.script, 1, self.service, self.current, connect, lambda: True)
            choice = next(e for e in self.client.elements.values() if e._props.get('label') == '기존 장면 영상 검색')
            choice.value = next(iter(choice.options))
            async def click(label):
                button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == label)
                before = asyncio.all_tasks()
                next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
                await asyncio.sleep(0)
                await asyncio.gather(*(asyncio.all_tasks() - before))
            await click('선택 영상 미리보기')
            binding._refresh_step()
            await click('이 장면에 영상 연결')
        self.assertEqual(self.source.read_bytes(), self.video)
        self.assertEqual(self.exporter.get_clip_path(self.current, 1).read_bytes(), self.video)
        self.assertEqual(state.reviewed_script_sha256, receipt)
        self.assertIsNone(state.final_video_path)

    async def test_stale_or_cancelled_picker_cannot_import(self):
        async def direct(function, *args):
            return function(*args)
        allowed = {'value': True}
        callback = AsyncMock()
        with self.client, patch.object(existing_scene_picker.run, 'io_bound', side_effect=direct):
            await existing_scene_picker.open_existing_scene_picker(self.script, 1, self.service, self.current, callback, lambda: allowed['value'])
            choice = next(e for e in self.client.elements.values() if e._props.get('label') == '기존 장면 영상 검색')
            choice.value = next(iter(choice.options))
            button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '선택 영상 미리보기')
            before = asyncio.all_tasks()
            next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
            await asyncio.sleep(0)
            await asyncio.gather(*(asyncio.all_tasks() - before))
            allowed['value'] = False
            connect = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 장면에 영상 연결')
            before = asyncio.all_tasks()
            next(e.handler for e in connect._event_listeners.values() if e.type == 'click')(None)
            await asyncio.sleep(0)
            await asyncio.gather(*(asyncio.all_tasks() - before))
        callback.assert_not_awaited()

    async def test_cancelled_delayed_listing_and_deleted_view_do_not_apply_material(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(function, *args):
            entered.set();await release.wait();return function(*args)
        imported = AsyncMock()
        with self.client, patch.object(existing_scene_picker.run, 'io_bound', side_effect=delayed):
            async def open_picker():
                with self.client:
                    await existing_scene_picker.open_existing_scene_picker(
                        self.script, 1, self.service, self.current, imported, lambda: True)
            task = asyncio.create_task(open_picker())
            try:
                await asyncio.wait_for(entered.wait(), 2)
            except asyncio.TimeoutError:
                release.set()
                await task
                self.fail('The picker did not reach its delayed read')
            dialog = next(e for e in self.client.elements.values() if isinstance(e, ui.dialog))
            dialog.close();release.set();await task
        imported.assert_not_awaited()
        self.assertFalse(self.exporter.get_clip_path(self.current, 1).exists())

    async def test_old_scene_button_cannot_open_picker_after_source_scope_or_script_change(self):
        state = AppState(script=self.script, manual_video_mode=True, manual_script_id=self.current)
        with self.client, ui.column() as root, patch.object(generation_tab, 'open_existing_scene_picker', new_callable=AsyncMock) as picker:
            generation_tab.render_manual_panel(state, self.exporter, ui.button(), root)
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '기존 장면 영상 찾기')
            handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            for change in (lambda: setattr(state, 'manual_video_mode', False), state.detach_operating_scope,
                           lambda: setattr(state, 'script', script('changed'))):
                change();before = asyncio.all_tasks();handler(None);await asyncio.sleep(0)
                await asyncio.gather(*(asyncio.all_tasks() - before))
                state.manual_video_mode = True
            picker.assert_not_awaited()
