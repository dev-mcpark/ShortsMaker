"""Session draft recovery must not change applied scripts or quality verdicts."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from shorts_maker.gui.components import planning_tab
from shorts_maker.gui.state.app_state import AppState
from test_gui_creation_flows import callback, script
from test_gui_operation_flows import _UI


class StudioDraftTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_patch = patch.object(planning_tab.settings, 'scripts_dir', Path(self.temp.name))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def render(self, state):
        recorder = _UI()
        with patch.object(planning_tab, 'ui', recorder):
            planning_tab.render_planning_tab(state)
        return recorder

    def test_menu_rerender_retains_invalid_draft_without_applying_or_invalidating_approved_script(self):
        state = AppState(script=script(), final_video_path='retained.mp4')
        state.confirm_script_review()
        original = state.script.model_dump_json()
        first = self.render(state)
        editor = first.find('textarea', '각본 JSON')
        self.assertEqual(editor.value, state.script.model_dump_json(indent=2))
        editor.kwargs['on_change'](SimpleNamespace(value='{ unfinished JSON'))
        second = self.render(state)
        self.assertEqual(second.find('textarea', '각본 JSON').value, '{ unfinished JSON')
        self.assertEqual(state.script.model_dump_json(), original)
        self.assertTrue(state.is_script_reviewed())
        self.assertEqual(state.final_video_path, 'retained.mp4')
        self.assertTrue(state.has_unapplied_script_draft())

    def test_different_scripts_keep_separate_drafts_and_old_editor_events_cannot_write_new_script(self):
        first_script, second_script = script('A'), script('B')
        state = AppState(script=first_script)
        old = self.render(state).find('textarea', '각본 JSON')
        old.kwargs['on_change'](SimpleNamespace(value='draft A'))
        state.load_saved_script(second_script)
        new = self.render(state).find('textarea', '각본 JSON')
        self.assertEqual(new.value, second_script.model_dump_json(indent=2))
        new.kwargs['on_change'](SimpleNamespace(value='draft B'))
        old.kwargs['on_change'](SimpleNamespace(value='late A event'))
        self.assertEqual(state.script_editor_text(), 'draft B')
        state.load_saved_script(first_script)
        self.assertEqual(state.script_editor_text(), 'draft A')

    def test_blank_draft_is_preserved_and_busy_events_cannot_change_it(self):
        state = AppState(script=script())
        key = state.script_editor_key()
        state.remember_script_draft(key, '')
        self.assertEqual(self.render(state).find('textarea', '각본 JSON').value, '')
        self.assertTrue(state.has_unapplied_script_draft())
        state.pipeline_running = True
        state.remember_script_draft(key, 'ignored while busy')
        self.assertEqual(state.script_editor_text(), '')

    def test_unapplied_draft_cannot_be_confirmed_then_explicit_discard_restores_applied_script(self):
        state = AppState(script=script())
        recorder = self.render(state)
        editor = recorder.find('textarea', '각본 JSON')
        editor.kwargs['on_change'](SimpleNamespace(value='{broken'))
        env = {'state': state, 'previewed_script': {'json': state.script.model_dump_json()},
               'safe_notify': Mock(), 'logger': Mock(), 'on_reviewed': Mock()}
        callback('planning_tab.py', 'confirm_script', env)()
        self.assertFalse(state.is_script_reviewed())
        env['on_reviewed'].assert_not_called()
        recorder.find('button', '미적용 수정 되돌리기').callback()
        self.assertFalse(state.has_unapplied_script_draft())
        self.assertEqual(editor.value, state.script.model_dump_json(indent=2))

    def test_applying_draft_changes_only_after_explicit_action_and_requires_review_again(self):
        state = AppState(script=script(), final_video_path='old.mp4')
        state.confirm_script_review()
        recorder = self.render(state)
        editor = recorder.find('textarea', '각본 JSON')
        changed = state.script.model_copy(deep=True)
        changed.title = '편집한 제목'
        editor.value = changed.model_dump_json(indent=2)
        editor.kwargs['on_change'](SimpleNamespace(value=editor.value))
        recorder.find('button', '현재 작업에 적용').callback()
        self.assertEqual(state.script.title, '편집한 제목')
        self.assertIsNone(state.final_video_path)
        self.assertFalse(state.is_script_reviewed())
        self.assertFalse(state.has_unapplied_script_draft())

    def test_format_only_edit_is_not_a_pending_content_change(self):
        state = AppState(script=script())
        state.remember_script_draft(state.script_editor_key(), state.script.model_dump_json(indent=4))
        self.assertFalse(state.has_unapplied_script_draft())

    def test_empty_new_editor_and_discard_are_not_pending_content(self):
        state = AppState()
        recorder = self.render(state)
        editor = recorder.find('textarea', '각본 JSON')
        editor.kwargs['on_change'](SimpleNamespace(value='unapplied import'))
        self.assertTrue(state.has_unapplied_script_draft())
        recorder.find('button', '미적용 수정 되돌리기').callback()
        editor.kwargs['on_change'](SimpleNamespace(value=''))
        self.assertFalse(state.has_unapplied_script_draft())

    def test_empty_workspace_cannot_offer_script_confirmation(self):
        recorder = self.render(AppState())
        self.assertFalse(recorder.find('button', '각본 확인 완료 · 영상 제작으로 →').enabled)
