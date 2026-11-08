"""Per-script audio recovery without restoring secrets or approvals."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.audio_choices import load_audio_choices, save_audio_choices
from shorts_maker.utils.config import settings
from tests.test_visual_review import sample_script


CHOICES = {'tts_voice': 'nova', 'bgm_mood': 'auto',
           'bgm_track': 'candidate_serene_view.mp3', 'bgm_volume': 0.15}


class AudioChoicesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = patch.object(settings, 'output_dir', Path(temporary.name))
        output.start()
        self.addCleanup(output.stop)

    def test_new_session_restores_audio_without_secrets_or_approvals(self):
        state = AppState(script=sample_script(), openai_key='secret', **CHOICES)
        path = state.save_audio_choices()
        self.assertNotIn('secret', path.read_text())
        restored = AppState(openai_key='current-key', final_video_path='old.mp4',
                            reviewed_script_sha256='old-review')
        with patch('shorts_maker.services.audio_choices.BGMManager.get_track_path', return_value='licensed.mp3'):
            restored.load_saved_script(sample_script())
        self.assertEqual({key: getattr(restored, key) for key in CHOICES}, CHOICES)
        self.assertEqual(restored.openai_key, 'current-key')
        self.assertIsNone(restored.reviewed_script_sha256)
        self.assertIsNone(restored.final_video_path)

    def test_loading_script_restores_mode_and_clears_prior_production(self):
        script = sample_script()
        script.generation_mode = 'video'
        save_audio_choices(script, CHOICES)
        previous_progress = [object()]
        service = object()
        state = AppState(mode='image', openai_key='current-key', gcp_project='current-project',
                         generated_clips=['old.mp4'], scene_clips=['old.png'],
                         scene_progresses=previous_progress, pipeline_phase='completed',
                         pipeline_progress=100, pipeline_message='Old completed run',
                         total_scenes=5, completed_scenes=5, current_scene=5,
                         elapsed_seconds=30, estimated_seconds=10, phase_times={'old': 30},
                         last_error='Old failure', final_video_path='old-final.mp4',
                         reviewed_script_sha256='old-review', manual_script_id='old-manual',
                         manual_video_mode=True, script_context=object(), topic_candidates=[object()],
                         pipeline_history=[{'title': 'Earlier video'}])
        state.production_service = service
        with patch('shorts_maker.services.audio_choices.BGMManager.get_track_path', return_value='licensed.mp3'):
            state.load_saved_script(script)
        self.assertIs(state.script, script)
        self.assertEqual(state.mode, 'video')
        self.assertEqual({key: getattr(state, key) for key in CHOICES}, CHOICES)
        self.assertEqual((state.openai_key, state.gcp_project), ('current-key', 'current-project'))
        self.assertTrue(state.manual_video_mode)
        self.assertEqual(state.manual_script_id, '')
        self.assertIsNone(state.production_service)
        self.assertIsNone(state.script_context)
        self.assertIsNone(state.final_video_path)
        self.assertIsNone(state.reviewed_script_sha256)
        self.assertEqual((state.generated_clips, state.scene_clips, state.topic_candidates), ([], [], []))
        self.assertIsNone(state.pipeline_phase)
        self.assertEqual((state.pipeline_progress, state.pipeline_message), (0, ''))
        self.assertEqual((state.total_scenes, state.completed_scenes, state.current_scene), (0, 0, 0))
        self.assertEqual((state.elapsed_seconds, state.estimated_seconds, state.phase_times), (0, 0, {}))
        self.assertIsNone(state.last_error)
        self.assertEqual(state.scene_progresses, [])
        self.assertEqual(len(previous_progress), 1)
        self.assertEqual(state.pipeline_history, [{'title': 'Earlier video'}])

    def test_active_production_or_upload_cannot_replace_current_script(self):
        original = sample_script()
        candidate = original.model_copy(deep=True)
        candidate.title = 'Another episode'
        for busy in ('pipeline_running', 'youtube_upload_in_progress'):
            with self.subTest(busy=busy):
                state = AppState(script=original, mode='image', final_video_path='old.mp4',
                                 generated_clips=['old-clip.mp4'], manual_script_id='manual', **{busy: True})
                with patch('shorts_maker.services.audio_choices.load_audio_choices') as load:
                    with self.assertRaisesRegex(ValueError, '진행 중'):
                        state.load_saved_script(candidate)
                    load.assert_not_called()
                self.assertIs(state.script, original)
                self.assertEqual((state.mode, state.final_video_path), ('image', 'old.mp4'))
                self.assertEqual(state.generated_clips, ['old-clip.mp4'])
                self.assertEqual(state.manual_script_id, 'manual')
                self.assertTrue(getattr(state, busy))

    def test_unknown_loaded_mode_preserves_existing_state(self):
        candidate = sample_script()
        candidate.generation_mode = 'unknown'
        original = sample_script()
        state = AppState(script=original, mode='video', final_video_path='current.mp4')
        with self.assertRaisesRegex(ValueError, '모드'):
            state.load_saved_script(candidate)
        self.assertIs(state.script, original)
        self.assertEqual(state.mode, 'video')
        self.assertEqual(state.final_video_path, 'current.mp4')

    def test_changed_script_does_not_inherit_another_scripts_audio(self):
        script = sample_script()
        save_audio_choices(script, CHOICES)
        script.scenes[0].script_text = 'A different story.'
        self.assertIsNone(load_audio_choices(script))
        state = AppState(**CHOICES)
        state.load_saved_script(script)
        self.assertEqual(state.tts_voice, 'alloy')
        self.assertEqual(state.bgm_track, '')
        self.assertEqual(state.bgm_volume, 0.2)

    def test_corrupt_or_wrong_binding_preserves_current_session(self):
        script = sample_script()
        path = save_audio_choices(script, CHOICES)
        record = json.loads(path.read_text())
        current = script.model_copy(deep=True)
        current.title = 'Other episode'
        state = AppState(script=current, bgm_volume=0.4)
        for content in ('{broken', json.dumps({**record, 'script_sha256': 'wrong'})):
            path.write_text(content)
            with self.assertRaisesRegex(ValueError, '저장된 음성'):
                state.load_saved_script(script)
            self.assertIs(state.script, current)
            self.assertEqual(state.bgm_volume, 0.4)

    def test_invalid_choices_cannot_overwrite_saved_record(self):
        script = sample_script()
        path = save_audio_choices(script, CHOICES)
        before = path.read_bytes()
        for bad in ({'bgm_volume': True}, {'bgm_volume': float('nan')},
                    {'bgm_volume': 1.1}, {'openai_key': 'never-save-this'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                save_audio_choices(script, {**CHOICES, **bad})
            self.assertEqual(path.read_bytes(), before)

    def test_missing_selected_track_does_not_silently_fall_back(self):
        script = sample_script()
        save_audio_choices(script, CHOICES)
        with patch('shorts_maker.services.audio_choices.BGMManager.get_track_path', return_value=None):
            with self.assertRaisesRegex(ValueError, '저장된 음성'):
                load_audio_choices(script)
        save_audio_choices(script, {**CHOICES, 'bgm_track': '', 'bgm_mood': 'not-installed'})
        with patch('shorts_maker.services.audio_choices.BGMManager.get_bgm_path', return_value=None):
            with self.assertRaisesRegex(ValueError, '저장된 음성'):
                load_audio_choices(script)

    def test_failed_atomic_save_keeps_previous_choices(self):
        script = sample_script()
        path = save_audio_choices(script, CHOICES)
        before = path.read_bytes()
        with patch('shorts_maker.services.audio_choices.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                save_audio_choices(script, {**CHOICES, 'bgm_volume': 0.3})
        self.assertEqual(path.read_bytes(), before)
