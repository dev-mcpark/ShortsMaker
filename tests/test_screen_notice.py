"""Studio notices reuse rendered overlays and fail before a paid narration request."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.gui.components.screen_notice import render_screen_notice
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class ScreenNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for key, value in [('output_dir', self.root), ('paid_production_enabled', True)]:
            override = patch.object(settings, key, value);override.start();self.addCleanup(override.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop());loop.start();self.addCleanup(loop.stop)
        self.client = Client(page('/screen-notice'));self.addCleanup(self.client.delete)
        self.content = script()
        self.content.scenes.append(self.content.scenes[0].model_copy(update={'scene_number': 7}))

    def test_notice_maps_every_stable_scene_id_and_empty_remains_compatible(self):
        state = AppState(script=self.content)
        self.assertNotIn('text_overlays', state._editor_options())
        state.screen_notice = ' 설명용 개념 모형 '
        overlays = state._editor_options()['text_overlays']
        self.assertEqual(set(overlays), {'1', '7'})
        self.assertEqual(overlays['7'], [{'text': '설명용 개념 모형', 'start': 0, 'x': 60, 'y': 70}])
        self.content.scenes.reverse()
        self.assertEqual(state._editor_options()['text_overlays'], overlays)
        for value in ('x' * 21, '줄\n바꿈', '줄\r바꿈', None):
            state.screen_notice = value
            with self.assertRaises(ValueError):
                state._editor_options()

    def test_preflight_uses_real_renderer_bounds_and_releases_created_clips(self):
        state = AppState(script=self.content, screen_notice='설명용 개념 모형')
        editor = VideoEditor(**state._editor_options())
        with patch.object(editor, '_cleanup_clips', wraps=editor._cleanup_clips) as cleanup:
            editor.preflight_text_overlays(self.content)
        self.assertEqual(cleanup.call_count, 2)
        clips = editor._create_text_overlay_clips(7, 2.5)
        try:
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0].start, 0)
            self.assertEqual(clips[0].duration, 2.5)
            self.assertTrue(20 < clips[0].w < settings.video_width - 60)
        finally:
            editor._cleanup_clips(clips)
        editor.text_overlays['7'][0]['x'] = settings.video_width
        with self.assertRaisesRegex(ValueError, '화면 밖'):
            editor.preflight_text_overlays(self.content)

    async def test_invalid_notice_fails_before_speech_or_generator_submission(self):
        editor = VideoEditor(bgm_volume=0, text_overlays={'1': [{'text': '줄\n바꿈', 'start': 0, 'x': 60, 'y': 70}]})
        service = ProductionService(mode='video')
        with patch.object(service, '_valid_clip', return_value=True), patch.object(service, '_get_editor', return_value=editor), \
                patch.object(editor, 'prepare_narration', new_callable=AsyncMock) as speech, \
                patch.object(service, '_get_generator', side_effect=AssertionError('no provider')) as generator:
            result = await service.produce_video(self.content, manual_clip_paths={1: 'one.mp4', 7: 'seven.mp4'})
        self.assertFalse(result.success)
        self.assertIn('화면 표기 문안', result.error)
        speech.assert_not_awaited();generator.assert_not_called()

    async def test_editor_preparation_also_checks_labels_before_a_speech_quote(self):
        editor = VideoEditor(bgm_volume=0, text_overlays={'1': [{'text': 'bad\nlabel', 'start': 0, 'x': 60, 'y': 70}]})
        with patch('shorts_maker.services.narration_preparation.plan_narration') as quote:
            with self.assertRaisesRegex(ValueError, '화면 표기 문안'):
                await editor.prepare_narration(self.content)
        quote.assert_not_called()

    def test_native_change_clear_busy_and_deleted_field_preserve_state(self):
        state = AppState(script=self.content, final_video_path='retained.mp4')
        state.confirm_script_review()
        with self.client, ui.column() as root:
            render_screen_notice(state)
        field = next(e for e in root.descendants() if e._props.get('label') == '전체 장면 안내 문구')
        changed = field._change_handlers[-1]
        changed(SimpleNamespace(value='설명용 개념 모형'))
        self.assertEqual(state.screen_notice, '설명용 개념 모형')
        self.assertTrue(state.is_script_reviewed());self.assertEqual(state.final_video_path, 'retained.mp4')
        state.pipeline_running = True;changed(SimpleNamespace(value='stale'))
        self.assertEqual(state.screen_notice, '설명용 개념 모형')
        state.pipeline_running = False;changed(SimpleNamespace(value=None))
        self.assertEqual(state.screen_notice, '')
        root.clear();changed(SimpleNamespace(value='deleted'))
        self.assertEqual(state.screen_notice, '')
