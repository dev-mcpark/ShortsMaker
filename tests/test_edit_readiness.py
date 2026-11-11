"""User-visible preparation state and last-moment draft guards; no providers."""

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from nicegui import binding, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import generation_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script
from test_gui_operation_flows import _UI


class EditReadinessTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = AppState(script=script(), mode='video')
        self.state.confirm_script_review()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for key, value in [('paid_production_enabled', True), ('output_dir', Path(temporary.name))]:
            change = patch.object(settings, key, value)
            change.start()
            self.addCleanup(change.stop)

    def test_veo_requires_every_raw_approval_and_readiness_never_reads_media(self):
        state = self.state
        state.script.scenes.append(state.script.scenes[0].model_copy(update={'scene_number': 2}))
        state.confirm_script_review()
        with patch.object(Path, 'open', side_effect=AssertionError('readiness must not poll files')):
            for verdicts in ({}, {0: 'approved'}, {0: 'approved', 1: 'rejected'}, {0: 'approved', 1: 'stale'}):
                self.assertFalse(generation_tab._auto_edit_ready(state, verdicts))
            self.assertTrue(generation_tab._auto_edit_ready(state, {0: 'approved', 1: 'approved'}))
        self.assertIn('1/2', generation_tab._next_edit_step(state, {0: 'approved'}))

    def test_image_and_hybrid_modes_use_their_actual_video_scene_set(self):
        state = self.state
        state.script.scenes.append(state.script.scenes[0].model_copy(update={'scene_number': 2}))
        state.confirm_script_review()
        state.mode = 'image'
        self.assertTrue(generation_tab._auto_edit_ready(state, {}))
        state.mode = 'hybrid'
        self.assertTrue(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        state.script.scenes[1].visual_mode = 'video'
        state.confirm_script_review()
        self.assertFalse(generation_tab._auto_edit_ready(state, {0: 'approved'}))

    def test_unapplied_draft_blocks_editing_but_preserves_approval_and_previous_video(self):
        state = self.state
        receipt = state.reviewed_script_sha256
        state.final_video_path = 'previous.mp4'
        state.manual_script_id = 'workspace'
        exporter = SimpleNamespace(all_clips_ready=Mock(return_value=True))
        state.remember_script_draft(state.script_editor_key(), '{ unfinished JSON')
        self.assertTrue(state.is_script_reviewed())
        self.assertFalse(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        self.assertFalse(generation_tab._manual_edit_ready(state, exporter))
        self.assertIn('미적용', generation_tab._next_edit_step(state, {0: 'approved'}))
        self.assertEqual(state.final_video_path, 'previous.mp4')
        self.assertEqual(state.reviewed_script_sha256, receipt)
        state.script_editor_drafts.clear()
        self.assertTrue(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        self.assertTrue(generation_tab._manual_edit_ready(state, exporter))

    def test_format_only_draft_stays_ready_and_read_only_requires_a_voice_set(self):
        state = self.state
        state.remember_script_draft(state.script_editor_key(), state.script.model_dump_json(indent=4))
        self.assertTrue(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        with patch.object(settings, 'paid_production_enabled', False):
            self.assertFalse(generation_tab._auto_edit_ready(state, {0: 'approved'}))
            self.assertIn('내레이션', generation_tab._next_edit_step(state, {0: 'approved'}))
            state.prepared_narration_manifest = 'selected/narration.json'
            self.assertTrue(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        state.pipeline_running = True
        self.assertFalse(generation_tab._auto_edit_ready(state, {0: 'approved'}))
        state.pipeline_running = False
        state.manual_video_mode = True
        self.assertFalse(generation_tab._auto_edit_ready(state, {0: 'approved'}))

    def test_native_button_and_next_step_follow_live_verdicts_and_pending_edits(self):
        state, verdicts = self.state, {0: 'pending'}
        client = Client(page('/test-edit-readiness'))
        try:
            with client, ui.column() as container, patch.object(generation_tab, 'render_raw_clip_reviews', return_value=verdicts), \
                    patch.object(generation_tab, 'render_first_frame_reviews'), patch.object(generation_tab, 'render_narration_panel'), \
                    patch.object(generation_tab, 'render_manual_panel'), patch.object(generation_tab, 'VeoPromptExporter'):
                generation_tab.render_generation_tab(state)
            button = next(e for e in container.descendants() if getattr(e, 'text', '') == '영상 제작 시작')
            self.assertFalse(button.enabled)
            verdicts[0] = 'approved'
            binding._refresh_step()
            self.assertTrue(button.enabled)
            state.remember_script_draft(state.script_editor_key(), '{unfinished')
            binding._refresh_step()
            self.assertFalse(button.enabled)
            self.assertTrue(any('미적용' in getattr(e, 'text', '') for e in container.descendants()))
            state.script_editor_drafts.clear()
            binding._refresh_step()
            self.assertTrue(button.enabled)
        finally:
            client.delete()

    async def test_stale_first_frame_and_raw_events_cannot_buy_using_an_unapplied_draft(self):
        state = self.state
        service = SimpleNamespace(max_veo_attempts=1, video_spec=lambda: ('veo-3.1-fast-generate-001', 6), generate_review_clip=AsyncMock(),
                                  review_clip_path=Mock(side_effect=ValueError('FIRST_FRAME_REVIEW_REQUIRED: scene')))
        state.get_or_create_service = Mock(return_value=service)
        state.new_production_service = Mock()
        recorder = _UI()
        with patch.object(generation_tab, 'ui', recorder), patch.object(generation_tab, 'media_sources', return_value=lambda p: p), \
                patch.object(generation_tab, 'safe_notify') as notify:
            generation_tab.render_first_frame_reviews(state)
            generation_tab.render_raw_clip_reviews(state)
            state.remember_script_draft(state.script_editor_key(), '{unfinished')
            await recorder.find('button', '첫 프레임 후보 생성').callback()
            await recorder.find('button', '이 장면 Veo 원본 생성').callback()
        state.new_production_service.assert_not_called()
        service.generate_review_clip.assert_not_awaited()
        self.assertTrue(all('미적용' in call.args[0] for call in notify.call_args_list))

    async def test_stale_edit_event_keeps_previous_result_and_never_starts_service(self):
        state = self.state
        state.final_video_path = 'previous.mp4'
        state.new_production_service = Mock()
        state.remember_script_draft(state.script_editor_key(), '{unfinished')
        core = next(n for n in ast.walk(ast.parse(Path(generation_tab.__file__).read_text()))
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_production_core')
        wrapper = ast.parse('def factory():\n video_player = None\n placeholder_content = None\n return _run_production_core\n')
        wrapper.body[0].body.insert(-1, core)
        environment = {'state': state, 'rendered_script': state.script.model_dump_json(), 'safe_notify': Mock()}
        exec(compile(ast.fix_missing_locations(wrapper), 'edit-core', 'exec'), environment)
        await environment['factory']()()
        state.new_production_service.assert_not_called()
        self.assertEqual(state.final_video_path, 'previous.mp4')
        self.assertFalse(state.is_busy)

    async def test_old_frame_and_raw_events_cannot_spend_after_switching_to_local_clips(self):
        state = self.state
        service = SimpleNamespace(generate_first_frame=AsyncMock(return_value='unused.png'),
                                  is_cancelled=Mock(return_value=False), max_veo_attempts=1, video_spec=lambda: ('veo-3.1-fast-generate-001', 6),
                                  generate_review_clip=AsyncMock(),
                                  review_clip_path=Mock(side_effect=ValueError('FIRST_FRAME_REVIEW_REQUIRED: scene')))
        state.new_production_service = Mock(return_value=service)
        state.get_or_create_service = Mock(return_value=service)
        recorder = _UI()
        with patch.object(generation_tab, 'ui', recorder), patch.object(generation_tab, 'media_sources', return_value=lambda p: p), \
                patch.object(generation_tab, 'safe_notify') as notify:
            generation_tab.render_first_frame_reviews(state)
            generation_tab.render_raw_clip_reviews(state)
            old_event = recorder.find('button', '첫 프레임 후보 생성').callback
            old_raw_event = recorder.find('button', '이 장면 Veo 원본 생성').callback
            state.manual_video_mode = True
            await old_event()
            await old_raw_event()
        state.new_production_service.assert_not_called()
        service.generate_review_clip.assert_not_awaited()
        self.assertTrue(all('제작 방식' in call.args[0] for call in notify.call_args_list))

    async def test_old_edit_event_preserves_result_after_visual_or_source_mode_change(self):
        for key, value in [('mode', 'image'), ('manual_video_mode', True)]:
            with self.subTest(key=key):
                state = AppState(script=script(), mode='video', final_video_path='previous.mp4')
                state.confirm_script_review()
                state.new_production_service = Mock(side_effect=AssertionError('stale work reached service'))
                core = next(n for n in ast.walk(ast.parse(Path(generation_tab.__file__).read_text()))
                            if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_production_core')
                wrapper = ast.parse('def factory():\n video_player = None\n placeholder_content = None\n return _run_production_core\n')
                wrapper.body[0].body.insert(-1, core)
                environment = {'state': state, 'rendered_script': state.script.model_dump_json(), 'safe_notify': Mock(),
                               'settings': SimpleNamespace(paid_production_enabled=True), 'gen_spinner': Mock(),
                               'scene_progress_container': Mock(), 'manual_preview': Mock(), 'logger': Mock()}
                exec(compile(ast.fix_missing_locations(wrapper), 'edit-mode', 'exec'), environment)
                old_event = environment['factory']()
                setattr(state, key, value)
                await old_event()
                state.new_production_service.assert_not_called()
                self.assertEqual(state.final_video_path, 'previous.mp4')
