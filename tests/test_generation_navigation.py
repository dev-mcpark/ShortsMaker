"""Offline completion recovery after navigation; no provider or media generation."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from nicegui import binding, ui
from nicegui.client import Client
from nicegui.elements.video import Video
from nicegui.page import page

from shorts_maker.gui.components import generation_tab
from shorts_maker.gui.components.common.progress_utils import update_scene_grid
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.production_service import ProductionPhase
from test_gui_creation_flows import callback, script


class GenerationNavigationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Client(page('/test-generation-navigation'))

    async def asyncTearDown(self):
        self.client.delete()

    async def test_progress_cards_identify_reordered_scenes_and_actual_states(self):
        from shorts_maker.services.production_service import SceneProgress
        with self.client, ui.column() as grid:
            update_scene_grid(
                [SceneProgress(7, 'processing'), SceneProgress(3, 'failed')], grid)
        labels = [item.text for item in grid.descendants() if isinstance(item, ui.label)]
        self.assertEqual(labels, ['장면 7', '처리 중', '장면 3', '실패'])

    def render_view(self, state):
        source = lambda path: f'/offline-media/{Path(path).name}' if path else ''
        with self.client, ui.element('div') as container, patch.object(
                generation_tab, 'media_sources', return_value=source), patch.object(
                generation_tab, 'render_first_frame_reviews', Mock()), patch.object(
                generation_tab, 'render_raw_clip_reviews', Mock()), patch.object(
                generation_tab, 'render_narration_panel', Mock()), patch.object(
                generation_tab, 'render_manual_panel', Mock()), patch.object(
                generation_tab, 'VeoPromptExporter', Mock()):
            generation_tab.render_generation_tab(state)
        self.view_root = container
        players = [element for element in container.descendants() if isinstance(element, Video)]
        self.assertEqual(len(players), 2)
        return players

    async def test_reopened_view_tracks_running_scenes_through_failure_and_reset(self):
        from shorts_maker.services.production_service import ProductionProgress, SceneProgress

        state = AppState(script=script(), pipeline_running=True)
        progress = ProductionProgress(phase=ProductionPhase.EDITING,
                                      scene_progresses=[SceneProgress(7, 'completed'), SceneProgress(3, 'processing')])
        state.sync_from_progress(progress)

        def visible_text():
            binding._refresh_step()
            return ' '.join(el.text for el in self.view_root.descendants()
                            if isinstance(el, ui.label) and all(p.visible for p in el.ancestors(include_self=True)))

        for manual in (False, True):
            state.manual_video_mode = manual
            self.render_view(state)
            self.assertIn('편집 중', visible_text())
            self.assertIn('장면 3 · 처리 중', visible_text())
            self.view_root.delete()
        self.render_view(state)
        progress.scene_progresses[1].status = 'failed'
        progress.phase = ProductionPhase.FAILED
        state.sync_from_progress(progress)
        state.pipeline_running = False
        self.assertIn('장면 7 · 완료', visible_text())
        self.assertIn('장면 3 · 실패', visible_text())
        self.assertIn('작업 중단', visible_text())
        state.reset_pipeline()
        self.assertNotIn('장면 3 · 실패', visible_text())

    async def complete_after_navigation(self, *, success=True, manual=False, prepared=False, retained=False):
        state = AppState(script=script(), manual_video_mode=manual)
        state.confirm_script_review()
        if prepared:
            state.prepared_narration_manifest = '/tmp/narration.json'
            state.prepared_audio_paths = Mock(return_value=['/tmp/retained-voice.mp3'])
        state.failed_video_preview_path = '/tmp/previous-partial.mp4'
        started, release = asyncio.Event(), asyncio.Event()
        progress = SimpleNamespace(phase=ProductionPhase.EDITING, scene_progresses=[], progress_percent=50)

        async def produce(*args, **kwargs):
            if prepared:
                self.assertEqual(kwargs['prepared_audio_paths'], ['/tmp/retained-voice.mp3'])
            started.set()
            await release.wait()
            progress.phase = ProductionPhase.COMPLETED if success else ProductionPhase.FAILED
            return SimpleNamespace(success=success,
                                   video_path='/tmp/new-final.mp4' if success else '/tmp/new-partial.mp4',
                                   clips=['scene.mp4'], estimated_visual_cost_usd=0, reused_scenes=1,
                                   narration_manifest_path='/tmp/retained/narration.json' if retained else None,
                                   error=None if success else 'quality check failed')

        service = SimpleNamespace(produce_video=produce, set_progress_callback=Mock(), progress=progress)
        state.new_production_service = lambda: service
        old_player = SimpleNamespace(visible=True, set_source=Mock(side_effect=RuntimeError('deleted player')))
        old_manual_player = SimpleNamespace(set_source=Mock(side_effect=RuntimeError('deleted manual player')))
        notifications = Mock()
        environment = {
            'state': state, 'safe_notify': notifications, 'logger': Mock(), 'asyncio': asyncio,
            'ProductionPhase': ProductionPhase, 'ProductionProgress': object,
            'manual_preview': SimpleNamespace(visible=False, is_deleted=False), 'manual_video_player': old_manual_player,
            'injected_video_player': old_player, 'injected_placeholder': SimpleNamespace(visible=False),
            'safe_refresh': Mock(), 'narration_panel': Mock(),
            'rendered_script': state.script.model_dump_json(),
            'settings': SimpleNamespace(paid_production_enabled=not prepared),
        }
        tree = ast.parse(Path(generation_tab.__file__).read_text())
        core = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == '_run_production_core')
        wrapper = ast.parse('def factory():\n video_player = injected_video_player\n placeholder_content = injected_placeholder\n return _run_production_core\n')
        wrapper.body[0].body.insert(-1, core)
        exec(compile(ast.fix_missing_locations(wrapper), 'generation_tab.py', 'exec'), environment)
        task = asyncio.create_task(environment['factory']()({1: 'scene.mp4'} if manual else None))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertIsNone(state.final_video_path)
            self.assertIsNone(state.failed_video_preview_path)
            players = self.render_view(state)
            self.assertEqual(players[0].source, '')
            self.assertFalse(players[0].visible)
            release.set()
            await asyncio.wait_for(task, timeout=2)
            binding._refresh_step()
            old_player.set_source.assert_not_called()
            old_manual_player.set_source.assert_not_called()
            self.assertFalse(state.is_busy)
            self.assertFalse(any('실행 도중 오류' in call.args[0] for call in notifications.call_args_list))
            return state, players
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_new_automatic_view_receives_successful_completion_without_reopening_again(self):
        state, players = await self.complete_after_navigation()
        self.assertEqual(state.final_video_path, '/tmp/new-final.mp4')
        self.assertIsNone(state.failed_video_preview_path)
        self.assertEqual(players[0].source, '/offline-media/new-final.mp4')
        self.assertTrue(players[0].visible)

    async def test_read_only_ui_passes_retained_narration_to_the_normal_editor(self):
        state, _ = await self.complete_after_navigation(manual=True, prepared=True)
        self.assertEqual(state.final_video_path, '/tmp/new-final.mp4')

    async def test_completed_edit_retains_voice_selection_after_navigation(self):
        state, _ = await self.complete_after_navigation(manual=True, retained=True)
        self.assertEqual(state.prepared_narration_manifest, '/tmp/retained/narration.json')

    async def test_failed_edit_retains_voice_without_promoting_a_failed_video(self):
        state, _ = await self.complete_after_navigation(manual=True, retained=True, success=False)
        self.assertEqual(state.prepared_narration_manifest, '/tmp/retained/narration.json')
        self.assertIsNone(state.final_video_path)

    async def test_new_manual_view_receives_success_without_false_deleted_widget_error(self):
        state, players = await self.complete_after_navigation(manual=True)
        self.assertEqual(players[1].source, '/offline-media/new-final.mp4')
        self.assertTrue(players[1].parent_slot.parent.visible)
        self.assertEqual(state.final_video_path, '/tmp/new-final.mp4')

    async def test_partial_failure_remains_previewable_but_cannot_be_uploaded(self):
        state, players = await self.complete_after_navigation(success=False)
        self.assertIsNone(state.final_video_path)
        self.assertEqual(state.failed_video_preview_path, '/tmp/new-partial.mp4')
        self.assertEqual(players[0].source, '/offline-media/new-partial.mp4')
        self.assertTrue(players[0].visible)
        state.get_or_create_service = Mock()
        notify = Mock()
        await callback('publishing_tab.py', 'upload_video', {'state': state, 'safe_notify': notify})()
        state.get_or_create_service.assert_not_called()
        notify.assert_called_once()

    async def test_manual_edit_failure_can_be_inspected_after_navigation(self):
        state, players = await self.complete_after_navigation(manual=True, success=False)
        state.pipeline_message = '편집 품질 검사 실패'
        for player, view in [(players[1], self.view_root), (self.render_view(state)[1], self.view_root)]:
            binding._refresh_step()
            preview = player.parent_slot.parent
            manual_area = preview.parent_slot.parent
            self.assertTrue(manual_area.visible)
            self.assertTrue(preview.visible)
            self.assertEqual(player.source, '/offline-media/new-partial.mp4')
            self.assertTrue(any(isinstance(item, ui.label) and item.visible
                                and '품질 검사' in item.text for item in preview.descendants()))
            self.assertTrue(any(isinstance(item, ui.label) and item.visible
                                and item.text == state.pipeline_message for item in view.descendants()))
        self.assertIsNone(state.final_video_path)
        state.invalidate_video_result()
        binding._refresh_step()
        self.assertFalse(players[1].parent_slot.parent.visible)

    async def test_loading_another_script_and_invalidating_results_clear_failed_preview(self):
        state = AppState(script=script())
        state.failed_video_preview_path = '/tmp/partial.mp4'
        state.load_saved_script(script('B'))
        self.assertIsNone(state.failed_video_preview_path)
        self.assertIsNone(state.preview_video_path)
        state.failed_video_preview_path = '/tmp/another-partial.mp4'
        state.invalidate_video_result()
        self.assertIsNone(state.failed_video_preview_path)
        self.assertIsNone(state.preview_video_path)
