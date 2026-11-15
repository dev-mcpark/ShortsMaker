"""Reject non-finite duration before app apply or irreversible JSON serialization."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.script_store import save_script_copy
from shorts_maker.services.work_drafts import saved_work_drafts, read_work_draft
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script, callback


class SceneDurationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in [('output_dir', self.root), ('scripts_dir', self.root / 'scripts')]:
            override = patch.object(settings, name, value);override.start();self.addCleanup(override.stop)

    def test_shared_script_schema_rejects_nonfinite_python_and_json_durations(self):
        for duration in (float('inf'), float('-inf'), float('nan'), 'Infinity', 'inf', '1e309'):
            with self.subTest(duration=duration):
                data = script().model_dump();data['scenes'][0]['duration_seconds'] = duration
                with self.assertRaises(ValidationError):
                    ShortsScript.model_validate(data)
        for literal in ('Infinity', '-Infinity', 'NaN', '1e309'):
            with self.subTest(json_literal=literal):
                data = script().model_dump();data['scenes'][0]['duration_seconds'] = '__duration__'
                text = json.dumps(data).replace('"__duration__"', literal)
                with self.assertRaises(ValidationError):
                    ShortsScript.model_validate_json(text)

    def test_invalid_advanced_editor_apply_preserves_previous_work_and_recoverable_input(self):
        state = AppState(script=script('Original'), final_video_path='kept-final.mp4')
        state.confirm_script_review()
        before = (state.script.model_dump_json(), state.reviewed_script_sha256, state.final_video_path)
        key = state.script_editor_key()
        data = script('Invalid edit').model_dump();data['scenes'][0]['duration_seconds'] = float('inf')
        text = json.dumps(data)
        state.remember_script_draft(key, text)
        notify = Mock()
        apply = callback('planning_tab.py', 'save_script', {
            'state': state, 'editor_source': {'key': key}, 'editor_area': SimpleNamespace(value=text),
            'ShortsScript': ShortsScript, 'json': json, 'restore_editor': Mock(), 'form_panel': None,
            'safe_refresh': Mock(), 'update_script_preview': Mock(), 'update_candidates_panel': Mock(),
            'feedback_section': SimpleNamespace(visible=True), 'safe_notify': notify})
        apply()
        self.assertEqual((state.script.model_dump_json(), state.reviewed_script_sha256, state.final_video_path), before)
        self.assertEqual(state.script_editor_text(), text)
        self.assertIn('적용할 수 없습니다', notify.call_args.args[0])
        self.assertIsNone(state.production_service)
        state.save_work_draft()
        names, warnings = saved_work_drafts();self.assertFalse(warnings)
        record, digest = read_work_draft(next(iter(names)))
        fresh = AppState();fresh.restore_work_draft(next(iter(names)), digest)
        self.assertEqual(fresh.script, state.script)
        self.assertEqual(fresh.script_editor_text(), text)
        self.assertIsNone(fresh.reviewed_script_sha256)
        self.assertIsNone(fresh.final_video_path)

    def test_positive_fractional_duration_and_nonsequential_scene_ids_roundtrip_unchanged(self):
        original = script()
        original.scenes = [original.scenes[0].model_copy(update={'scene_number': 7, 'duration_seconds': .1}),
                           original.scenes[0].model_copy(update={'scene_number': 2, 'duration_seconds': 5.25})]
        validated = ShortsScript.model_validate(original.model_dump())
        path = save_script_copy(validated, settings.scripts_dir)
        restored = ShortsScript.model_validate_json(path.read_text())
        self.assertEqual(restored, original)
        self.assertEqual([scene.scene_number for scene in restored.scenes], [7, 2])
        self.assertEqual([scene.duration_seconds for scene in restored.scenes], [.1, 5.25])
