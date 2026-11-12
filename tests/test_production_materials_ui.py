"""Real local media and mocked provider boundaries for Studio material preparation."""

import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from moviepy import AudioClip
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from PIL import Image

from shorts_maker.gui.components import generation_tab, narration_panel
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.first_frame_candidates import candidate_record_path, retained_candidate
from shorts_maker.services.prepared_narration import list_narration_sets, narration_paths
from shorts_maker.services.production_service import ProductionService
from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.services.visual_review import verified_first_frame
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script
from test_gui_operation_flows import _UI
from test_production_gates import fake_editor


class ProductionMaterialsTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / 'outputs'
        self.output.mkdir()
        for key, value in [('output_dir', self.output), ('paid_production_enabled', True)]:
            change = patch.object(settings, key, value)
            change.start()
            self.addCleanup(change.stop)
        change = patch('shorts_maker.services.first_frame_candidates.check_google_budget')
        self.budget = change.start()
        self.addCleanup(change.stop)
        self.script = script()
        self.image = self.root / 'generated.png'
        Image.new('RGB', (360, 640), 'blue').save(self.image)
        self.service = ProductionService(mode='video')
        self.service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(self.image)))
        self.estimate = estimated_scene_cost('image', settings.image_model_id)

    async def generate(self):
        return await self.service.generate_first_frame(self.script, 0, request_budget_usd=self.estimate)

    async def test_generated_candidate_is_retained_and_never_auto_approved(self):
        result = await self.generate()
        self.assertTrue(Path(result).is_file())
        self.assertEqual(retained_candidate(self.script, self.script.scenes[0]), result)
        with self.assertRaisesRegex(ValueError, 'FIRST_FRAME_REVIEW_REQUIRED'):
            verified_first_frame(self.script, self.script.scenes[0])
        with patch.object(settings, 'paid_production_enabled', False):
            self.assertEqual(await self.generate(), result)
        self.service._generator.generate_scene_clip.assert_awaited_once()
        self.budget.assert_called_once_with(self.estimate)

    async def test_uncertain_image_request_blocks_replay_and_preserves_record(self):
        self.service._generator.generate_scene_clip.side_effect = RuntimeError('provider timeout')
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            await self.generate()
        record = candidate_record_path(self.script, self.script.scenes[0])
        before = record.read_bytes()
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await self.generate()
        self.assertEqual(record.read_bytes(), before)
        self.service._generator.generate_scene_clip.assert_awaited_once()

    async def test_request_cap_cancel_and_paid_switch_stop_before_submission(self):
        with self.assertRaisesRegex(ValueError, 'CAP_EXCEEDED'):
            await self.service.generate_first_frame(self.script, 0, request_budget_usd=0)
        with patch.object(settings, 'paid_production_enabled', False), self.assertRaises(RuntimeError):
            await self.generate()
        self.service.cancel()
        with self.assertRaisesRegex(ValueError, '취소'):
            await self.generate()
        self.service._generator.generate_scene_clip.assert_not_awaited()
        self.assertFalse(candidate_record_path(self.script, self.script.scenes[0]).exists())

    async def test_changed_candidate_and_missing_record_do_not_overwrite_or_buy_again(self):
        result = await self.generate()
        Image.new('RGB', (360, 640), 'red').save(result)
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await self.generate()
        candidate_record_path(self.script, self.script.scenes[0]).unlink()
        before = Path(result).read_bytes()
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await self.generate()
        self.assertEqual(Path(result).read_bytes(), before)
        self.service._generator.generate_scene_clip.assert_awaited_once()

    async def test_concurrent_click_cannot_submit_a_second_image_request(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def generated(*args, **kwargs):
            started.set()
            await release.wait()
            return str(self.image)

        self.service._generator.generate_scene_clip.side_effect = generated
        task = asyncio.create_task(self.generate())
        try:
            await asyncio.wait_for(started.wait(), 2)
            with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
                await self.generate()
        finally:
            release.set()
            await task
        self.service._generator.generate_scene_clip.assert_awaited_once()

    async def test_corrupt_record_stops_without_submission_and_bad_client_leaves_no_attempt(self):
        record = candidate_record_path(self.script, self.script.scenes[0])
        record.parent.mkdir(parents=True)
        record.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await self.generate()
        record.unlink()
        with patch.object(self.service, '_get_generator', side_effect=ValueError('bad project')):
            with self.assertRaisesRegex(ValueError, 'bad project'):
                await self.generate()
        self.assertFalse(record.exists())
        self.service._generator.generate_scene_clip.assert_not_awaited()

    async def test_invalid_generated_frame_is_kept_pending_without_auto_retry(self):
        Image.new('RGB', (640, 360), 'blue').save(self.image)
        with self.assertRaisesRegex(ValueError, '9:16'):
            await self.generate()
        record = candidate_record_path(self.script, self.script.scenes[0])
        self.assertEqual(json.loads(record.read_text())['status'], 'pending')
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await self.generate()
        self.service._generator.generate_scene_clip.assert_awaited_once()

    def narration(self, amplitude=.2):
        directory = self.output / 'voice'
        directory.mkdir()
        audio = directory / 'scene_1.mp3'
        clip = AudioClip(lambda t: amplitude * np.sin(2 * np.pi * 440 * t), duration=.4, fps=8000)
        try:
            clip.write_audiofile(str(audio), fps=8000, logger=None)
        finally:
            clip.close()
        record = {'schema_version': 1, 'voice': 'nova', 'scenes': {
            '1': {'status': 'complete', 'text_sha256': hashlib.sha256(self.script.scenes[0].script_text.encode()).hexdigest(),
                  'file_sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}}}
        manifest = directory / 'narration.json'
        manifest.write_text(json.dumps(record))
        return manifest, audio

    def test_audio_selection_validates_real_media_and_does_not_change_on_invalid_input(self):
        manifest, audio = self.narration()
        state = AppState(script=self.script, final_video_path='old.mp4')
        self.assertIn(str(manifest), list_narration_sets(self.script))
        state.select_prepared_narration(str(manifest))
        self.assertEqual(state.prepared_audio_paths(), [str(audio)])
        self.assertIsNone(state.final_video_path)
        state.final_video_path = 'retained.mp4'
        with self.assertRaises((OSError, ValueError)):
            state.select_prepared_narration(str(self.output / 'missing' / 'narration.json'))
        self.assertEqual(state.final_video_path, 'retained.mp4')
        self.assertEqual(state.prepared_narration_manifest, str(manifest))
        state.load_saved_script(script('Other'))
        self.assertIsNone(state.prepared_narration_manifest)

    def test_silent_audio_is_rejected_before_the_previous_result_is_cleared(self):
        manifest, _ = self.narration(amplitude=0)
        state = AppState(script=self.script, final_video_path='retained.mp4')
        with self.assertRaisesRegex(ValueError, '무음'):
            state.select_prepared_narration(str(manifest))
        self.assertEqual(state.final_video_path, 'retained.mp4')
        self.assertIsNone(state.prepared_narration_manifest)

    def test_explicit_audio_settings_save_restores_selected_narration_without_review_authority(self):
        manifest, audio = self.narration()
        state = AppState(script=self.script)
        state.select_prepared_narration(str(manifest))
        path = state.save_audio_choices()
        before = path.read_bytes(), manifest.read_bytes(), audio.read_bytes()
        restored = AppState(final_video_path='old.mp4', reviewed_script_sha256='old')
        restored.load_saved_script(self.script)
        self.assertEqual(restored.prepared_narration_manifest, str(manifest.resolve()))
        self.assertEqual(restored.prepared_audio_paths(), [str(audio)])
        self.assertIsNone(restored.final_video_path)
        self.assertIsNone(restored.reviewed_script_sha256)
        self.assertEqual(before, (path.read_bytes(), manifest.read_bytes(), audio.read_bytes()))
        restored.select_prepared_narration(None)
        restored.save_audio_choices()
        fresh = AppState()
        fresh.load_saved_script(self.script)
        self.assertIsNone(fresh.prepared_narration_manifest)

    def test_changed_saved_narration_stays_selected_until_explicit_recovery_without_tts(self):
        manifest, audio = self.narration()
        state = AppState(script=self.script)
        state.select_prepared_narration(str(manifest))
        saved = state.save_audio_choices();saved_bytes = saved.read_bytes()
        manifest_bytes, audio_bytes = manifest.read_bytes(), audio.read_bytes()
        other = script('Keep current work')
        current = AppState(script=other, final_video_path='keep.mp4', prepared_narration_manifest='keep-selection')
        for target, content in ((manifest, b'{broken'), (audio, b'changed audio'), (manifest, None), (audio, None),
                                (manifest, json.dumps({**json.loads(manifest_bytes), 'voice': 'different'}).encode())):
            manifest.write_bytes(manifest_bytes);audio.write_bytes(audio_bytes)
            if content is None:
                target.unlink()
            else:
                target.write_bytes(content)
            with self.assertRaises((OSError, ValueError)):
                state.save_audio_choices()
            self.assertEqual(saved.read_bytes(), saved_bytes)
            current.load_saved_script(self.script)
            self.assertEqual(current.prepared_narration_manifest, str(manifest.resolve()))
            with self.assertRaises((OSError, ValueError)):
                current.prepared_audio_paths()
            # The app can open the script and expose explicit repair/new-voice controls.
            current.select_prepared_narration(None)
            self.assertIsNone(current.prepared_audio_paths())

    def test_deleted_narration_panel_cannot_clear_a_selection_or_finished_result(self):
        manifest, _ = self.narration()
        state = AppState(script=self.script)
        state.select_prepared_narration(str(manifest))
        state.final_video_path = 'kept.mp4'
        client = Client(page('/stale-narration-choice'))
        try:
            with client, ui.column() as root:
                narration_panel.render_narration_panel(state)
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '새 음성 생성으로 전환')
            with client:
                root.clear()
                next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
            self.assertEqual(state.prepared_narration_manifest, str(manifest))
            self.assertEqual(state.final_video_path, 'kept.mp4')
        finally:
            client.delete()

    def test_reconnecting_same_voice_or_clearing_an_empty_selection_preserves_the_edit(self):
        manifest, audio = self.narration()
        state = AppState(script=self.script, final_video_path='retained.mp4')
        state.select_prepared_narration(None)
        self.assertEqual(state.final_video_path, 'retained.mp4')
        state.select_prepared_narration(str(manifest))
        state.final_video_path = 'retained.mp4'
        service = state._production_service = Mock()
        state.select_prepared_narration(str(manifest))
        self.assertEqual(state.final_video_path, 'retained.mp4')
        self.assertIs(state._production_service, service)
        audio.write_bytes(b'changed after selecting')
        with self.assertRaises(ValueError):
            state.select_prepared_narration(str(manifest))
        self.assertEqual(state.final_video_path, 'retained.mp4')

    async def test_studio_retains_new_voice_before_editor_cleanup_for_the_next_edit(self):
        _, audio = self.narration()
        clip, output = self.root / 'clip.mp4', self.output / 'final.mp4'
        clip.touch()
        output.touch()
        self.service._valid_clip = Mock(return_value=True)
        self.service._editor = fake_editor(output)
        self.service._editor.tts_voice = 'nova'
        self.service._editor.prepare_narration.return_value = [str(audio)]
        self.service._editor.cleanup_temp_files.side_effect = audio.unlink
        with patch('shorts_maker.services.production_service.check_video_quality'):
            result = await self.service.produce_video(self.script, {1: str(clip)}, retain_narration=True)
        self.assertTrue(result.success, result.error)
        self.assertFalse(audio.exists())
        paths = narration_paths(self.script, result.narration_manifest_path)
        self.assertTrue(Path(paths[0]).is_file())
        self.assertIn(result.narration_manifest_path, list_narration_sets(self.script))
        self.assertEqual(json.loads(Path(result.report_path).read_text())['narration_manifest_path'], result.narration_manifest_path)
        self.service._generator.generate_scene_clip.assert_not_awaited()
        state = AppState(script=self.script, prepared_narration_manifest=result.narration_manifest_path)
        state.save_audio_choices()
        restored = AppState()
        restored.load_saved_script(self.script)
        self.assertEqual(restored.prepared_audio_paths(), paths)
        self.assertIsNotNone(restored.prepared_narration_sha256)

    def test_mismatched_pending_changed_and_external_audio_are_not_offered(self):
        manifest, audio = self.narration()
        changed = self.script.model_copy(deep=True)
        changed.scenes[0].script_text = 'Different words.'
        self.assertEqual(list_narration_sets(changed), {})
        record = json.loads(manifest.read_text())
        record['scenes']['1']['status'] = 'pending'
        manifest.write_text(json.dumps(record))
        self.assertEqual(list_narration_sets(self.script), {})
        record['scenes']['1']['status'] = 'complete'
        manifest.write_text(json.dumps(record))
        audio.write_bytes(b'changed')
        self.assertEqual(list_narration_sets(self.script), {})
        outside = self.root / 'narration.json'
        outside.write_text(manifest.read_text())
        with self.assertRaises(ValueError):
            narration_paths(self.script, str(outside))

    def test_read_only_manual_edit_accepts_retained_audio_but_not_new_speech(self):
        manifest, _ = self.narration()
        state = AppState(script=self.script, manual_script_id='manual')
        state.confirm_script_review()
        exporter = SimpleNamespace(all_clips_ready=Mock(return_value=True))
        with patch.object(settings, 'paid_production_enabled', False):
            self.assertFalse(generation_tab._manual_edit_ready(state, exporter))
            state.select_prepared_narration(str(manifest))
            self.assertTrue(generation_tab._manual_edit_ready(state, exporter))
            state.pipeline_running = True
            self.assertFalse(generation_tab._manual_edit_ready(state, exporter))

    def test_native_narration_controls_preview_and_first_frame_candidate_are_renderable(self):
        manifest, _ = self.narration()
        state = AppState(script=self.script)
        state.confirm_script_review()
        state.select_prepared_narration(str(manifest))
        client = Client(page('/test-material-preparation'))
        try:
            with client, ui.column() as container:
                narration_panel.render_narration_panel(state)
                generation_tab.render_first_frame_reviews(state)
            elements = list(container.descendants())
            self.assertTrue(any(e.tag == 'audio' or type(e).__name__ == 'Audio' for e in elements))
            expansion = next(e for e in elements if type(e).__name__ == 'Expansion'
                             and e.text == '내레이션 · 기존 음성 재사용')
            self.assertTrue(expansion.value)
            self.assertTrue(any(getattr(e, 'text', '') == '첫 프레임 후보 생성' for e in elements))
        finally:
            client.delete()

    async def test_first_frame_ui_keeps_saved_result_when_old_widgets_are_deleted(self):
        state = AppState(script=self.script)
        state.confirm_script_review()
        state.new_production_service = lambda: self.service
        recorder = _UI()
        with patch.object(generation_tab, 'ui', recorder), patch.object(generation_tab, 'media_sources', return_value=lambda p: p), \
                patch.object(generation_tab, 'safe_notify') as notify:
            generation_tab.render_first_frame_reviews(state)
            callback = recorder.find('button', '첫 프레임 후보 생성').callback
            # Deleting the old preview must not turn a recorded provider success into a new attempt.
            preview = next(e for e in recorder.elements if e.kind == 'column')
            preview.clear = Mock(side_effect=RuntimeError('deleted view'))
            await callback()
        self.assertFalse(state.is_busy)
        self.assertTrue(retained_candidate(self.script, self.script.scenes[0]))
        self.assertTrue(any('저장 완료' in call.args[0] for call in notify.call_args_list))
        self.assertFalse(any('생성 중단' in call.args[0] for call in notify.call_args_list))

    def test_raw_review_distinguishes_normal_frame_wait_from_unknown_request_errors(self):
        for message, expected in [('FIRST_FRAME_REVIEW_REQUIRED: scene 1', '위에서 첫 프레임을 승인'),
                                  ('RAW_CLIP_REQUEST_UNVERIFIED: pending', '원본 검토 중단:')]:
            with self.subTest(message=message):
                state = AppState(script=self.script)
                state.get_or_create_service = Mock(return_value=SimpleNamespace(
                    max_veo_attempts=1, video_spec=lambda: ('veo-3.1-fast-generate-001', 6), review_clip_path=Mock(side_effect=ValueError(message))))
                recorder = _UI()
                with patch.object(generation_tab, 'ui', recorder), patch.object(
                        generation_tab, 'media_sources', return_value=lambda p: p):
                    generation_tab.render_raw_clip_reviews(state)
                self.assertTrue(any(expected in e.text for e in recorder.elements if e.kind == 'label'))
