"""Repeat-pass state transitions and recoverable configuration failures; no providers."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import generation_tab, planning_tab, pipeline_tab, scheduling_tab, sources_tab
from shorts_maker.gui.components.common import source_access
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ScriptGenerationContext
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from test_gui_creation_flows import callback, planning_environment, script
from test_gui_operation_flows import _UI


class SourceRecoveryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'feeds.json'
        self.source.write_text('{broken')
        for name, value in [('rss_sources_file', self.source), ('scripts_dir', self.root / 'scripts')]:
            change = patch.object(settings, name, value)
            change.start()
            self.addCleanup(change.stop)

    def render(self, module, render):
        recorder = _UI()
        with patch.object(module, 'ui', recorder), patch.object(source_access, 'ui', recorder), \
                patch.object(scheduling_tab, 'schedule_manager', ScheduleManager(str(self.root / 'schedules.json'))):
            render(AppState())
        return recorder

    def test_corrupt_feeds_do_not_break_any_view_or_overwrite_original(self):
        for module, render in [(planning_tab, planning_tab.render_planning_tab),
                               (pipeline_tab, pipeline_tab.render_pipeline_tab),
                               (scheduling_tab, scheduling_tab.render_scheduling_tab),
                               (sources_tab, sources_tab.render_sources_tab)]:
            with self.subTest(module=module.__name__):
                recorder = self.render(module, render)
                self.assertTrue(any(e.kind == 'label' and e.text == 'RSS 소스 설정을 읽지 못했습니다.'
                                    for e in recorder.elements))
                self.assertEqual(self.source.read_text(), '{broken')
        with patch.object(settings, 'paid_production_enabled', True):
            recorder = self.render(planning_tab, planning_tab.render_planning_tab)
        self.assertFalse(recorder.find('button', '각본 생성하기').enabled)
        self.assertTrue(any(e.kind == 'button' and e.args == ('현재 대본 새 파일로 저장',)
                            for e in recorder.elements))

    def test_unreadable_catalog_is_reported_and_repaired_file_is_read_normally(self):
        recorder = _UI()
        with patch.object(source_access, 'ui', recorder):
            manager, sources = source_access.load_source_catalog(Mock(side_effect=OSError('unreadable')))
        self.assertIsNone(manager)
        self.assertEqual(sources, {})
        self.source.write_text(json.dumps({'City_Life': ['https://example.com/rss']}))
        recorder = self.render(planning_tab, planning_tab.render_planning_tab)
        categories = next(e for e in recorder.elements if e.kind == 'select' and e.kwargs.get('label') == 'RSS 분야')
        self.assertIn('City_Life', categories.args[0])

    def test_corrupt_sources_render_in_native_widgets_across_all_four_views(self):
        for module, render in [(planning_tab, planning_tab.render_planning_tab),
                               (pipeline_tab, pipeline_tab.render_pipeline_tab),
                               (scheduling_tab, scheduling_tab.render_scheduling_tab),
                               (sources_tab, sources_tab.render_sources_tab)]:
            with self.subTest(module=module.__name__):
                client = Client(page('/source-recovery-test'))
                try:
                    with client, patch.object(scheduling_tab, 'schedule_manager',
                                              ScheduleManager(str(self.root / 'native-schedule.json'))):
                        render(AppState())
                    self.assertTrue(any(getattr(e, 'text', '') == 'RSS 소스 설정을 읽지 못했습니다.'
                                        for e in client.elements.values()))
                    self.assertEqual(self.source.read_text(), '{broken')
                finally:
                    client.delete()

    def test_source_writes_stay_blocked_until_explicit_reload_after_repair(self):
        recorder = _UI()
        with patch.object(sources_tab, 'ui', recorder), patch.object(source_access, 'ui', recorder), \
                patch.object(sources_tab, 'safe_notify'):
            sources_tab.render_sources_tab(AppState())
            add = recorder.find('button', 'RSS 소스 추가')
            self.assertFalse(add.enabled)
            recorder.find('input', '카테고리').value = 'New'
            recorder.find('input', 'RSS 피드 URL').value = 'https://example.com/new'
            add.callback()
            self.assertEqual(self.source.read_text(), '{broken')
            self.source.write_text(json.dumps({'Kept': ['https://example.com/kept']}))
            reload_button = next(e for e in recorder.elements if e.kind == 'button'
                                 and 'RSS 목록 새로고침' in e.props_text)
            reload_button.callback()
            add.callback()
        self.assertEqual(json.loads(self.source.read_text()), {
            'Kept': ['https://example.com/kept'], 'New': ['https://example.com/new']})

    def test_native_source_controls_reenable_after_repair_and_reload(self):
        client = Client(page('/source-repair-controls'))
        native_button = ui.button
        created = []

        def button(*args, **kwargs):
            element = native_button(*args, **kwargs)
            created.append((element, args, kwargs))
            return element

        try:
            with client, patch.object(ui, 'button', side_effect=button):
                sources_tab.render_sources_tab(AppState())
            add = next(e for e, args, _ in created if args == ('RSS 소스 추가',))
            binding._refresh_step()
            self.assertFalse(add.enabled)
            self.source.write_text(json.dumps({'Restored': ['https://example.com/rss']}))
            reload = next(kwargs['on_click'] for _, _, kwargs in created if kwargs.get('icon') == 'refresh')
            async def refresh():
                with patch.object(core, 'loop', asyncio.get_running_loop()), client:
                    reload()
                    await asyncio.sleep(0)
                    binding._refresh_step()

            asyncio.run(refresh())
            self.assertTrue(add.enabled)
            self.assertEqual(json.loads(self.source.read_text()), {'Restored': ['https://example.com/rss']})
        finally:
            client.delete()

    def test_bad_rss_blocks_submission_before_creating_a_paid_service(self):
        state = AppState()
        state.get_or_create_service = Mock()
        env = planning_environment(state, None)
        env['catalog_manager'] = None
        asyncio.run(callback('planning_tab.py', 'generate_script', env)())
        state.get_or_create_service.assert_not_called()


class RepeatNavigationTests(TestCase):
    def setUp(self):
        self.client = Client(page('/repeat-workflows'))
        self.addCleanup(self.client.delete)

    def test_feedback_context_and_attempts_survive_return_to_planning(self):
        context = ScriptGenerationContext(source_item={'url': 'https://example.com'},
                                          attempt_count=1, max_attempts=3)
        state = AppState(script=script(), script_context=context)
        with self.client, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {})):
            planning_tab.render_planning_tab(state)
        binding._refresh_step()
        counter = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '재생성: 1/3회')
        panel = counter.parent_slot.parent.parent_slot.parent
        self.assertTrue(panel.visible)
        context.attempt_count = 2
        binding._refresh_step()
        self.assertEqual(counter.text, '재생성: 2/3회')

    def test_planning_view_opened_during_operation_recovers_result_once_idle(self):
        state = AppState(script=script('before'), pipeline_running=True)
        recovery = Mock()
        callbacks = []
        with self.client, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {})), \
                patch.object(ui, 'timer', side_effect=lambda _, cb: callbacks.append(cb) or recovery):
            planning_tab.render_planning_tab(state)
        self.assertEqual(len(callbacks), 1)
        state.pipeline_running = False
        state.load_saved_script(script('returned while away'))
        binding._refresh_step()
        editor = next(e for e in self.client.elements.values() if e._props.get('label') == '각본 JSON')
        self.assertFalse(editor.enabled)
        async def recover():
            with patch.object(core, 'loop', asyncio.get_running_loop()), self.client:
                callbacks[0]()
                await asyncio.sleep(0)
        asyncio.run(recover())
        binding._refresh_step()
        self.assertTrue(editor.enabled)
        self.assertTrue(any(getattr(e, 'text', '') == 'returned while away' for e in self.client.elements.values()))
        self.assertTrue(any('returned while away' in (getattr(e, 'value', '') or '')
                            for e in self.client.elements.values() if isinstance(getattr(e, 'value', None), str)))
        recovery.cancel.assert_called_once()

    def test_manual_edit_button_tracks_busy_completion_without_reopening(self):
        with TemporaryDirectory() as folder, patch.object(settings, 'clips_dir', Path(folder)), \
                patch.object(settings, 'paid_production_enabled', True):
            state = AppState(script=script(), manual_video_mode=True, pipeline_running=True)
            state.confirm_script_review()
            exporter = VeoPromptExporter()
            state.manual_script_id = exporter.create_workspace(state.script)
            for scene in state.script.scenes:
                exporter.save_uploaded_clip(b'fixture', state.manual_script_id, scene.scene_number)
            with self.client:
                generation_tab.render_generation_tab(state)
            button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '편집 및 자막 믹싱 시작')
            binding._refresh_step()
            self.assertFalse(button.enabled)
            state.pipeline_running = False
            binding._refresh_step()
            self.assertTrue(button.enabled)
            state.youtube_upload_in_progress = True
            binding._refresh_step()
            self.assertFalse(button.enabled)

    def test_closed_raw_view_does_not_turn_recorded_success_into_failure(self):
        state = AppState(script=script())
        state.confirm_script_review()
        service = SimpleNamespace(generate_review_clip=AsyncMock(return_value='retained.mp4'))
        state.get_or_create_service = Mock(return_value=service)
        env = {'state': state, 'rendered_script': state.script.model_dump_json(), 'index': 0,
               'refresh': Mock(side_effect=RuntimeError('deleted view')), 'reserve': .15,
               'displayed_frame': {'sha256': 'a' * 64}, 'safe_notify': Mock(), 'logger': Mock()}
        asyncio.run(callback('generation_tab.py', 'generate', env)())
        service.generate_review_clip.assert_awaited_once()
        self.assertFalse(state.is_busy)
        self.assertEqual(env['safe_notify'].call_args.kwargs['type'], 'positive')

    def test_closed_raw_view_preserves_original_pending_request_error(self):
        state = AppState(script=script())
        state.confirm_script_review()
        service = SimpleNamespace(generate_review_clip=AsyncMock(side_effect=ValueError('RAW_REQUEST_PENDING')))
        state.get_or_create_service = Mock(return_value=service)
        env = {'state': state, 'rendered_script': state.script.model_dump_json(), 'index': 0,
               'refresh': Mock(side_effect=RuntimeError('deleted view')), 'reserve': .15,
               'displayed_frame': {'sha256': 'a' * 64}, 'safe_notify': Mock(), 'logger': Mock()}
        asyncio.run(callback('generation_tab.py', 'generate', env)())
        service.generate_review_clip.assert_awaited_once()
        self.assertFalse(state.is_busy)
        self.assertIn('RAW_REQUEST_PENDING', env['safe_notify'].call_args.args[0])
        self.assertEqual(env['safe_notify'].call_args.kwargs['type'], 'negative')

    def test_closed_regeneration_counter_cannot_discard_new_script(self):
        state = AppState(script=script())
        context = ScriptGenerationContext(source_item={'url': 'https://example.com'}, attempt_count=1)
        state.script_context = context
        result = script('returned new draft')
        service = SimpleNamespace(regenerate_script=AsyncMock(return_value=result))
        state.get_or_create_service = Mock(return_value=service)
        env = planning_environment(state, service)
        env.update(feedback_input=SimpleNamespace(value='clarify'),
                   apply_script=lambda new, context: setattr(state, 'script', new))
        env['update_script_preview'].side_effect = RuntimeError('deleted view')
        asyncio.run(callback('planning_tab.py', 'regenerate_with_feedback', env)())
        self.assertIs(state.script, result)
        self.assertFalse(state.is_busy)
        self.assertTrue(any(c.kwargs.get('type') == 'positive' for c in env['safe_notify'].call_args_list))

    def test_pipeline_preserves_planning_context_without_starting_media(self):
        context = ScriptGenerationContext(source_item={'url': 'https://example.com'})
        service = ProductionService(mode='image', editor_options={'bgm_volume': 0})
        service.generate_script = AsyncMock(return_value=(script(), context))
        service.produce_video = AsyncMock()
        with patch.object(settings, 'paid_production_enabled', False):
            result = asyncio.run(service.full_pipeline())
        self.assertTrue(result.review_pending)
        self.assertIs(result.script_context, context)
        service.produce_video.assert_not_awaited()
