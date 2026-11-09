"""Local editing/restart boundaries; no provider or uploader is instantiated."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import script_store
from shorts_maker.utils.config import settings
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from tests.test_visual_review import sample_script


class InterventionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, directory in (('scripts_dir', 'scripts'), ('clips_dir', 'clips'), ('output_dir', 'outputs')):
            change = patch.object(settings, name, self.root / directory)
            change.start()
            self.addCleanup(change.stop)
        self.script = sample_script()
        self.exporter = VeoPromptExporter()

    def workspace_with_clip(self):
        workspace = self.exporter.create_workspace(self.script)
        clip = self.exporter.save_uploaded_clip(b'local fixture', workspace, self.script.scenes[0].scene_number)
        return workspace, clip

    def test_saved_copies_preserve_original_and_reopen_without_review_approval(self):
        state = AppState(script=self.script, openai_key='private-key')
        state.confirm_script_review()
        first = state.save_script_copy()
        original = first.read_bytes()
        edited = self.script.model_copy(deep=True)
        edited.scenes[0].script_text = '수정한 내레이션'
        state.load_saved_script(edited)
        second = state.save_script_copy()
        third = state.save_script_copy()
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(len({first, second, third}), 3)
        self.assertNotIn('private-key', second.read_text())
        restored = AppState()
        restored.load_saved_script(type(self.script).model_validate_json(second.read_text()))
        self.assertEqual(restored.script.scenes[0].script_text, '수정한 내레이션')
        self.assertFalse(restored.is_script_reviewed())
        self.assertIsNone(restored.final_video_path)

    def test_script_write_failure_leaves_existing_files_and_session_unchanged(self):
        state = AppState(script=self.script, final_video_path='old-final.mp4')
        first = state.save_script_copy()
        original = first.read_bytes()
        with patch.object(script_store.os, 'replace', side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):
                state.save_script_copy()
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(state.final_video_path, 'old-final.mp4')
        self.assertEqual(list(settings.scripts_dir.glob('*.tmp')), [])
        self.assertEqual(list(settings.scripts_dir.glob('*.json')), [first])

    def test_busy_operations_cannot_save_or_restore_work(self):
        workspace, clip = self.workspace_with_clip()
        for field in ('pipeline_running', 'youtube_upload_in_progress'):
            state = AppState(script=self.script, manual_video_mode=True, manual_script_id='previous',
                             final_video_path='old.mp4', **{field: True})
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    state.save_script_copy()
                with self.assertRaises(ValueError):
                    state.restore_manual_workspace(workspace)
                self.assertEqual((state.manual_script_id, state.final_video_path), ('previous', 'old.mp4'))
                self.assertEqual(clip.read_bytes(), b'local fixture')

    def test_explicit_restore_after_restart_preserves_files_but_invalidates_final(self):
        workspace, clip = self.workspace_with_clip()
        second, _ = self.workspace_with_clip()
        self.assertNotEqual(workspace, second)
        self.assertEqual(set(self.exporter.list_workspaces(self.script)), {workspace, second})
        restarted = AppState(script=self.script, manual_video_mode=True, manual_script_id='new-session',
                             final_video_path='unrelated.mp4', generated_clips=['old.mp4'], openai_key='current')
        restarted.restore_manual_workspace(workspace)
        self.assertEqual(restarted.manual_script_id, workspace)
        self.assertIsNone(restarted.final_video_path)
        self.assertEqual(restarted.generated_clips, [])
        self.assertFalse(restarted.is_script_reviewed())
        self.assertEqual(restarted.openai_key, 'current')
        self.assertEqual(clip.read_bytes(), b'local fixture')
        self.assertIsNone(restarted.production_service)

    def test_changed_script_or_corrupt_record_cannot_restore_old_mapping(self):
        workspace, clip = self.workspace_with_clip()
        for field, value in (('source_url', 'https://example.com/different'), ('title', 'Different title')):
            changed = self.script.model_copy(update={field: value})
            self.assertEqual(self.exporter.list_workspaces(changed), {})
            state = AppState(script=changed, manual_video_mode=True, manual_script_id='current', final_video_path='old.mp4')
            with self.assertRaises(ValueError):
                state.restore_manual_workspace(workspace)
            self.assertEqual((state.manual_script_id, state.final_video_path), ('current', 'old.mp4'))
        changed = self.script.model_copy(deep=True)
        changed.scenes[0].motion_instruction = 'Different motion'
        self.assertEqual(self.exporter.list_workspaces(changed), {})
        (clip.parent / 'workspace.json').write_text('{broken')
        self.assertEqual(self.exporter.list_workspaces(self.script), {})
        with self.assertRaises(ValueError):
            self.exporter.validate_workspace(self.script, workspace)
        self.assertEqual(clip.read_bytes(), b'local fixture')

    def test_unbound_legacy_or_empty_directories_are_not_guessed_as_recovery(self):
        self.exporter.create_workspace(self.script)
        self.exporter.save_uploaded_clip(b'legacy', 'legacy', 1)
        self.assertEqual(self.exporter.list_workspaces(self.script), {})
        with self.assertRaises(ValueError):
            self.exporter.validate_workspace(self.script, 'legacy')

    def test_directory_manifest_and_clip_symlink_escapes_are_rejected(self):
        workspace, clip = self.workspace_with_clip()
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'outside')
        clip.unlink()
        clip.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.exporter.validate_workspace(self.script, workspace)
        self.assertEqual(self.exporter.list_workspaces(self.script), {})
        with self.assertRaises(ValueError):
            self.exporter.get_clips_dir('../outside')
        (settings.clips_dir / 'external').symlink_to(self.root)
        with self.assertRaises(ValueError):
            self.exporter.get_clips_dir('external')

    def test_manual_editor_stays_disabled_until_current_script_is_reviewed(self):
        from shorts_maker.gui.components.generation_tab import render_manual_panel
        from tests.test_gui_operation_flows import _UI
        workspace, _ = self.workspace_with_clip()
        state = AppState(script=self.script, manual_video_mode=True, manual_script_id=workspace)
        recorder = _UI()
        recorder.context = Mock()
        media = Mock()
        media.add_media_file.side_effect = lambda **kwargs: kwargs['url_path']
        button, container = recorder.button('edit'), recorder.column()
        with patch('shorts_maker.gui.components.generation_tab.ui', recorder), patch(
                'shorts_maker.gui.components.common.media_preview.ui', recorder), patch(
                'shorts_maker.gui.components.common.media_preview.app', media), patch.object(
                settings, 'paid_production_enabled', True):
            render_manual_panel(state, self.exporter, button, container)
            self.assertFalse(button.enabled)
            state.confirm_script_review()
            render_manual_panel(state, self.exporter, button, container)
            self.assertTrue(button.enabled)
            self.assertTrue(any(e.kind == 'video' and str(e.args[0]).endswith('scene_01.mp4')
                                for e in recorder.elements))

    def test_restored_preview_route_survives_old_widget_cleanup(self):
        from nicegui import app, ui
        from shorts_maker.gui.components.common.media_preview import media_sources
        _, clip = self.workspace_with_clip()
        cleanup = []
        with patch.object(ui.context.client, 'on_delete', side_effect=cleanup.append):
            first = media_sources()(str(clip))
            old = ui.video(first)
            second = media_sources()(str(clip))
            new = ui.video(second)
        try:
            self.assertNotEqual(first, second)
            old.delete()
            cleanup[0]()
            self.assertTrue(any(getattr(route, 'path', None) == second for route in app.routes))
        finally:
            new.delete()
            for callback in cleanup:
                callback()
        self.assertFalse(any(getattr(route, 'path', None) in {first, second} for route in app.routes))

    def test_invalid_manual_media_stops_before_narration_or_visual_spending(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from shorts_maker.services.production_service import ProductionService
        invalid = self.root / 'broken.mp4'
        invalid.write_bytes(b'not a playable video')
        service = ProductionService(mode='video')
        service._editor = SimpleNamespace(prepare_narration=AsyncMock(), compose_video=AsyncMock())
        with patch.object(settings, 'paid_production_enabled', True):
            result = asyncio.run(service.produce_video(self.script, manual_clip_paths={1: str(invalid)}))
        self.assertFalse(result.success)
        self.assertIn('재생', result.error)
        service._editor.prepare_narration.assert_not_awaited()
        service._editor.compose_video.assert_not_awaited()
        self.assertIsNone(service._generator)

    def test_unknown_manual_scene_is_rejected_before_decoder_or_editor(self):
        import asyncio
        from shorts_maker.services.production_service import ProductionService
        service = ProductionService(mode='video')
        with patch.object(service, '_valid_clip') as decode:
            for number in (True, 999):
                result = asyncio.run(service.produce_video(self.script, manual_clip_paths={number: 'local.mp4'}))
                self.assertFalse(result.success)
                self.assertIn('장면 번호', result.error)
            decode.assert_not_called()
        self.assertIsNone(service._editor)
