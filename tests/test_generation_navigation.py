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
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.production_service import ProductionPhase
from test_gui_creation_flows import callback, script


class GenerationNavigationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Client(page('/test-generation-navigation'))

    async def asyncTearDown(self):
        self.client.delete()

    def render_view(self, state):
        source = lambda path: f'/offline-media/{Path(path).name}' if path else ''
        with self.client, ui.element('div') as container, patch.object(
                generation_tab, 'media_sources', return_value=source), patch.object(
                generation_tab, 'render_first_frame_reviews', Mock()), patch.object(
                generation_tab, 'render_raw_clip_reviews', Mock()), patch.object(
                generation_tab, 'render_manual_panel', Mock()), patch.object(
                generation_tab, 'VeoPromptExporter', Mock()):
            generation_tab.render_generation_tab(state)
        players = [element for element in container.descendants() if isinstance(element, Video)]
        self.assertEqual(len(players), 2)
        return players

    async def complete_after_navigation(self, *, success=True, manual=False):
        state = AppState(script=script(), manual_video_mode=manual)
        state.confirm_script_review()
        state.failed_video_preview_path = '/tmp/previous-partial.mp4'
        started, release = asyncio.Event(), asyncio.Event()
        progress = SimpleNamespace(phase=ProductionPhase.EDITING, scene_progresses=[], progress_percent=50)

        async def produce(*args, **kwargs):
            started.set()
            await release.wait()
            progress.phase = ProductionPhase.COMPLETED if success else ProductionPhase.FAILED
            return SimpleNamespace(success=success,
                                   video_path='/tmp/new-final.mp4' if success else '/tmp/new-partial.mp4',
                                   clips=['scene.mp4'], estimated_visual_cost_usd=0, reused_scenes=1,
                                   error=None if success else 'quality check failed')

        service = SimpleNamespace(produce_video=produce, set_progress_callback=Mock(), progress=progress)
        state.new_production_service = lambda: service
        old_player = SimpleNamespace(visible=True, set_source=Mock(side_effect=RuntimeError('deleted player')))
        old_manual_player = SimpleNamespace(set_source=Mock(side_effect=RuntimeError('deleted manual player')))
        notifications = Mock()
        environment = {
            'state': state, 'safe_notify': notifications, 'logger': Mock(), 'asyncio': asyncio,
            'ProductionPhase': ProductionPhase, 'ProductionProgress': object,
            'gen_spinner': SimpleNamespace(visible=False),
            'scene_progress_container': SimpleNamespace(visible=False, clear=Mock()),
            'manual_preview': SimpleNamespace(visible=False), 'manual_video_player': old_manual_player,
            'injected_video_player': old_player, 'injected_placeholder': SimpleNamespace(visible=False),
            'update_scene_grid': Mock(), 'update_progress_ui': Mock(),
            'rendered_script': state.script.model_dump_json(),
            'settings': SimpleNamespace(paid_production_enabled=True),
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
        self.assertEqual(players[1].source, '')
        state.get_or_create_service = Mock()
        notify = Mock()
        await callback('publishing_tab.py', 'upload_video', {'state': state, 'safe_notify': notify})()
        state.get_or_create_service.assert_not_called()
        notify.assert_called_once()

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
