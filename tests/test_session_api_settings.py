"""Shared Studio connections must not move another active job to a new account."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.gui.state.session_manager import SessionManager
from shorts_maker.utils.config import settings


class SessionAPISettingsTests(unittest.TestCase):
    def setUp(self):
        self.first = AppState(openai_key='first-key', gcp_project='first-project')
        self.second = AppState(openai_key='second-key', gcp_project='second-project')
        for target, name, value in (
            (settings, 'openai_api_key', 'first-key'),
            (settings, 'gcp_project_id', 'first-project'),
            (SessionManager, '_sessions', {'first': self.first, 'second': self.second}),
        ):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_implicit_service_creation_cannot_change_another_active_job(self):
        active = self.first.new_production_service()
        self.first.pipeline_running = True
        with self.assertRaisesRegex(ValueError, '다른 Studio'):
            self.second.new_production_service()
        self.assertIs(self.first.production_service, active)
        self.assertIsNone(self.second.production_service)
        self.assertEqual(settings.openai_api_key, 'first-key')
        self.assertEqual(settings.gcp_project_id, 'first-project')
        with patch('shorts_maker.services.production_service.VideoEditor',
                   side_effect=lambda **_: settings.openai_api_key):
            self.assertEqual(active._get_editor(), 'first-key')

    def test_explicit_change_blocks_all_busy_operations_without_invalidating(self):
        cached = self.second.new_production_service()
        for flag in ('pipeline_running', 'youtube_upload_in_progress',
                     'scheduled_planning_in_progress', 'media_import_in_progress', 'auth'):
            with self.subTest(flag=flag):
                if flag == 'auth':
                    self.first._youtube_connection = SimpleNamespace(running=True)
                else:
                    setattr(self.first, flag, True)
                self.second.openai_key = 'third-key'
                with self.assertRaisesRegex(ValueError, '다른 Studio'):
                    self.second.apply_api_settings()
                self.assertIs(self.second.production_service, cached)
                self.assertEqual(settings.openai_api_key, 'second-key')
                if flag == 'auth':
                    self.first._youtube_connection = None
                else:
                    setattr(self.first, flag, False)

    def test_same_connections_allow_concurrent_work_and_preserve_services(self):
        active = self.first.new_production_service()
        self.first.pipeline_running = True
        self.second.openai_key, self.second.gcp_project = 'first-key', 'first-project'
        self.assertIsNotNone(self.second.new_production_service())
        self.assertIs(self.first.production_service, active)

    def test_idle_change_invalidates_lazy_clients_in_every_session(self):
        first_service = self.first.new_production_service()
        self.first.openai_key = self.first.gcp_project = ''
        self.second.apply_api_settings()
        self.assertIsNone(self.first.production_service)
        self.assertIsNone(self.second.production_service)
        refreshed = self.first.get_or_create_service()
        self.assertIsNot(refreshed, first_service)
        self.assertEqual(settings.openai_api_key, 'second-key')
        self.assertEqual(settings.gcp_project_id, 'second-project')

    def test_current_job_and_failed_settings_write_keep_services(self):
        cached = self.first.new_production_service()
        self.first.pipeline_running = True
        with self.assertRaisesRegex(ValueError, '진행 중'):
            self.first.apply_api_settings()
        self.first.pipeline_running = False
        with patch.object(settings, 'update_api_keys', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.second.apply_api_settings()
        self.assertIs(self.first.production_service, cached)
        self.assertEqual(settings.openai_api_key, 'first-key')


class SessionAPISettingsUITests(unittest.IsolatedAsyncioTestCase):
    async def test_sidebar_rejects_other_busy_session_then_applies_when_idle(self):
        from contextlib import ExitStack
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from shorts_maker.gui.pages import main_page

        state = AppState(openai_key='second-key', gcp_project='second-project')
        other = AppState(pipeline_running=True)
        client = Client(page('/shared-settings-test'))
        try:
            with ExitStack() as stack:
                for target, name, value in (
                    (main_page, 'get_session_state', lambda: state),
                    (SessionManager, '_sessions', {'current': state, 'other': other}),
                    (settings, 'openai_api_key', 'first-key'),
                    (settings, 'gcp_project_id', 'first-project'),
                    (main_page, 'render_planning_tab', lambda *a, **k: None),
                    (main_page, 'render_episode_workspace', lambda *a, **k: None),
                    (main_page, 'render_budget_panel', lambda: None),
                ):
                    stack.enter_context(patch.object(target, name, value))
                notify = stack.enter_context(patch.object(ui, 'notify'))
                with client:
                    main_page.render_main_page()
                    button = next(e for e in client.elements.values()
                                  if getattr(e, 'text', '') == '연결 설정 적용')
                    click = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                    click(None)
                    self.assertIn('다른 Studio', notify.call_args.args[0])
                    self.assertEqual(settings.openai_api_key, 'first-key')
                    other.pipeline_running = False
                    click(None)
                    self.assertEqual(settings.openai_api_key, 'second-key')
                    self.assertEqual(settings.gcp_project_id, 'second-project')
                    button.delete()
                    client.elements[next(e.id for e in client.elements.values()
                                         if e._props.get('label') == 'OpenAI Key')].delete()
                    state.openai_key = 'stale-key'
                    click(None)
                    self.assertEqual(settings.openai_api_key, 'second-key')
        finally:
            client.delete()

    async def test_edit_rejects_changed_connection_before_clearing_previous_output(self):
        import ast
        from pathlib import Path
        from unittest.mock import Mock
        from shorts_maker.gui.components import generation_tab
        from test_gui_creation_flows import script

        state = AppState(script=script(), final_video_path='previous.mp4',
                         openai_key='other-key', gcp_project='other-project')
        state.confirm_script_review()
        core = next(n for n in ast.walk(ast.parse(Path(generation_tab.__file__).read_text()))
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_production_core')
        wrapper = ast.parse('def factory():\n video_player = None\n placeholder_content = None\n return _run_production_core\n')
        wrapper.body[0].body.insert(-1, core)
        environment = {'state': state, 'settings': settings,
                       'rendered_script': state.script.model_dump_json(), 'safe_notify': Mock()}
        exec(compile(ast.fix_missing_locations(wrapper), 'edit-core', 'exec'), environment)
        with patch.object(SessionManager, '_sessions', {'active': AppState(pipeline_running=True)}), \
                patch.object(settings, 'paid_production_enabled', True), \
                patch.object(settings, 'openai_api_key', 'first-key'):
            await environment['factory']()()
        self.assertEqual(state.final_video_path, 'previous.mp4')
        self.assertIsNone(state.production_service)
        self.assertFalse(state.is_busy)
        self.assertIn('다른 Studio', environment['safe_notify'].call_args.args[0])
