"""Source-bound first-frame review before new paid Veo scene output."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from PIL import Image

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
from shorts_maker.services.raw_review import (
    begin_raw_request, complete_raw_request, raw_review_status, retained_raw_request,
    save_raw_verdict, verified_raw_clip,
)
from shorts_maker.services.visual_review import (
    approve_first_frame, inspect_frame, verified_first_frame,
)
from shorts_maker.utils.config import settings
from shorts_maker.utils.character_overlay import CharacterOverlayConfig


def sample_script():
    return ShortsScript(
        title='Reviewed scene', description='A sourced story', tags=[],
        mood='calm', style='documentary', source_name='Source',
        source_url='https://example.com/story', generation_mode='video',
        scenes=[VideoScene(scene_number=1, visual_description='Show the proposed walkway',
                           motion_instruction='Lift only the proposal layer',
                           script_text='The proposal was removed from the plan.')],
    )


class VisualReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        for name, value in (('output_dir', self.directory / 'outputs'),
                            ('clips_dir', self.directory / 'outputs' / 'clips')):
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def saved_scene(self):
        script = sample_script()
        scene = script.scenes[0]
        frame = self.directory / 'frame.png'
        Image.new('RGB', (540, 960), 'pink').save(frame)
        frame_hash = inspect_frame(str(frame))
        approve_first_frame(script, scene, str(frame), ['upper walkway'], ['demolition'],
                            'Reviewed miniature', frame_hash)
        with patch.object(settings, 'veo_model_id', 'veo-3.1-lite-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 8,
        ):
            directory = ProductionService(mode='video')._scene_cache_dir(scene, 'video', frame_hash)
        directory.mkdir(parents=True)
        clip = directory / 'clip.mp4'
        clip.write_bytes(b'retained silent footage')
        begin_raw_request(script, scene, str(clip), frame_hash, 'veo-3.1-lite-generate-001', 8)
        complete_raw_request(script, scene, frame_hash)
        return script, clip, frame_hash

    def test_changed_model_defaults_recover_saved_raw_without_another_paid_call(self):
        script, clip, frame_hash = self.saved_scene()
        with patch.object(settings, 'veo_model_id', 'veo-3.1-fast-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 6,
        ), patch.object(settings, 'paid_production_enabled', False), patch.object(
            ProductionService, '_valid_clip', return_value=True,
        ), patch('shorts_maker.services.production_service.check_google_budget') as budget:
            service = ProductionService(mode='video')
            self.assertEqual(service.review_clip_path(script, 0), (str(clip.resolve()), frame_hash))
            self.assertEqual(asyncio.run(service.generate_review_clip(script, 0)), str(clip.resolve()))
            self.assertEqual(service._remaining_visual_reserve(script), (0.0, 0))
            self.assertIsNone(service._generator)
            budget.assert_not_called()

    def test_staged_preflight_prices_only_missing_outputs_with_local_edit_scenes(self):
        script = sample_script()
        script.scenes.append(script.scenes[0].model_copy(update={'scene_number': 2}))
        local = self.directory / 'edited.mp4'
        local.write_bytes(b'local edit')
        service = ProductionService(mode='video')
        with patch.object(service, '_valid_clip', side_effect=lambda path, mode: path == local), patch.object(
            settings, 'veo_model_id', 'veo-3.1-lite-generate-001',
        ), patch.object(settings, 'veo_duration_seconds', 8):
            self.assertEqual(service._remaining_visual_reserve(script, {2: str(local)}), (.24, 1))
            for invalid in ({3: str(local)}, {True: str(local)}, {2: 'missing.mp4'}):
                with self.assertRaises(ValueError):
                    service._remaining_visual_reserve(script, invalid)
            with self.assertRaisesRegex(ValueError, '로컬 편집 클립'):
                asyncio.run(service.generate_review_clip(script, 1, manual_clip_paths={2: str(local)}))
        self.assertIsNone(service._generator)

    def test_older_prompt_receipt_blocks_resubmission_and_preserves_the_saved_clip(self):
        script, clip, frame_hash = self.saved_scene()
        receipt = next((settings.output_dir / 'evaluation' / 'visual_reviews').glob('*.raw.json'))
        record = json.loads(receipt.read_text())
        record['prompt_version'] -= 1
        receipt.write_text(json.dumps(record))
        original_receipt = receipt.read_bytes()
        with patch('shorts_maker.services.production_service.check_google_budget') as budget:
            service = ProductionService(mode='video')
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
                asyncio.run(service.generate_review_clip(script, 0))
            budget.assert_not_called()
        self.assertIsNone(service._generator)
        self.assertEqual(clip.read_bytes(), b'retained silent footage')
        self.assertEqual(receipt.read_bytes(), original_receipt)

    def test_retained_raw_tampering_stops_instead_of_regenerating(self):
        script, clip, frame_hash = self.saved_scene()
        receipt = next((settings.output_dir / 'evaluation' / 'visual_reviews').glob('*.raw.json'))
        original = receipt.read_text()
        for invalid in ('{broken', original.replace(str(clip), str(self.directory / 'outside.mp4'))):
            receipt.write_text(invalid)
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
                retained_raw_request(script, script.scenes[0], frame_hash)
        receipt.write_text(original)
        clip.write_bytes(b'changed clip')
        with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
            asyncio.run(ProductionService(mode='video').generate_review_clip(script, 0))

    def test_recovery_does_not_silently_ignore_changed_overlay_configuration(self):
        script, clip, frame_hash = self.saved_scene()
        overlay = CharacterOverlayConfig()
        overlay.enabled = True
        service = ProductionService(mode='video', character_overlay_config=overlay)
        with self.assertRaisesRegex(ValueError, 'RAW_CLIP_CONFIG_CHANGED'):
            asyncio.run(service.generate_review_clip(script, 0))
        self.assertIsNone(service._generator)

    def test_changed_model_does_not_bypass_an_uncertain_request(self):
        script, clip, frame_hash = self.saved_scene()
        receipt = next((settings.output_dir / 'evaluation' / 'visual_reviews').glob('*.raw.json'))
        receipt.write_text(receipt.read_text().replace('"state": "saved"', '"state": "pending"'))
        with patch.object(settings, 'veo_model_id', 'veo-3.1-fast-generate-001'), patch(
            'shorts_maker.services.production_service.check_google_budget',
        ) as budget:
            service = ProductionService(mode='video')
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
                asyncio.run(service.generate_review_clip(script, 0))
            budget.assert_not_called()
            self.assertIsNone(service._generator)

    def test_failed_receipt_save_keeps_the_request_pending(self):
        script, clip, frame_hash = self.saved_scene()
        receipt = next((settings.output_dir / 'evaluation' / 'visual_reviews').glob('*.raw.json'))
        pending = receipt.read_text().replace('"state": "saved"', '"state": "pending"')
        receipt.write_text(pending)
        with patch('shorts_maker.services.raw_review.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                complete_raw_request(script, script.scenes[0], frame_hash)
        self.assertEqual(receipt.read_text(), pending)
        with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
            retained_raw_request(script, script.scenes[0], frame_hash)

    def test_new_approved_frame_has_a_separate_raw_request_identity(self):
        script, clip, old_hash = self.saved_scene()
        frame = self.directory / 'frame.png'
        Image.new('RGB', (540, 960), 'blue').save(frame)
        new_hash = inspect_frame(str(frame))
        approve_first_frame(script, script.scenes[0], str(frame), ['walkway'], ['demolition'],
                            'New input reviewed separately', new_hash)
        self.assertNotEqual(old_hash, new_hash)
        self.assertIsNone(retained_raw_request(script, script.scenes[0], new_hash))
        with self.assertRaisesRegex(ValueError, 'FIRST_FRAME_CHANGED'):
            asyncio.run(ProductionService(mode='video').generate_review_clip(
                script, 0, expected_frame_sha256=old_hash,
            ))
        self.assertEqual(clip.read_bytes(), b'retained silent footage')

    def test_full_cut_reuses_reviewed_lite_clip_and_reports_its_actual_model(self):
        script, clip, frame_hash = self.saved_scene()
        fake_video = MagicMock()
        fake_video.__enter__.return_value = SimpleNamespace(duration=8, audio=None, size=(540, 960))
        with patch('shorts_maker.services.raw_review.VideoFileClip', return_value=fake_video):
            save_raw_verdict(script, script.scenes[0], str(clip), frame_hash, 'approved', 'Clear motion')
        video = self.directory / 'finished.mp4'
        video.write_bytes(b'finished cut')
        audio = self.directory / 'narration.mp3'
        audio.write_bytes(b'prepared narration')
        editor = SimpleNamespace(validate_narration=Mock(), preflight_music=Mock(),
                                 prepare_narration=AsyncMock(), compose_video=AsyncMock(return_value=str(video)))
        with patch.object(settings, 'veo_model_id', 'veo-3.1-fast-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 6,
        ), patch.object(settings, 'paid_production_enabled', False), patch.object(
            ProductionService, '_valid_clip', return_value=True,
        ), patch('shorts_maker.services.production_service.check_video_quality'), patch(
            'shorts_maker.services.production_service.check_google_budget',
        ) as budget:
            service = ProductionService(mode='video')
            service._editor = editor
            result = asyncio.run(service.produce_video(script, prepared_audio_paths=[str(audio)]))
            self.assertTrue(result.success, result.error)
            self.assertEqual(editor.compose_video.await_args.args[0], [str(clip.resolve())])
            report = json.loads(video.with_suffix('.production.json').read_text())
            self.assertEqual(report['scenes'][0]['model_id'], 'veo-3.1-lite-generate-001')
            self.assertEqual(report['estimated_visual_output_cost_usd'], 0)
            editor.prepare_narration.assert_not_awaited()
            budget.assert_not_called()
            self.assertIsNone(service._generator)

    def test_review_binds_source_narration_motion_and_frame_bytes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'output_dir', Path(directory) / 'outputs',
        ):
            frame = Path(directory) / 'frame.png'
            Image.new('RGB', (540, 960), 'pink').save(frame)
            script = sample_script()
            scene = script.scenes[0]
            with self.assertRaisesRegex(ValueError, 'FIRST_FRAME_REVIEW_REQUIRED'):
                verified_first_frame(script, scene)
            digest = inspect_frame(str(frame))
            approve_first_frame(script, scene, str(frame), ['separate upper walkway'],
                                ['real demolition'], 'Two levels are legible', digest)
            self.assertEqual(verified_first_frame(script, scene), (str(frame.resolve()), digest))
            scene.motion_instruction = 'Move the entire bridge'
            with self.assertRaisesRegex(ValueError, 'FIRST_FRAME_REVIEW_REQUIRED'):
                verified_first_frame(script, scene)
            scene.motion_instruction = 'Lift only the proposal layer'
            Image.new('RGB', (540, 960), 'blue').save(frame)
            with self.assertRaisesRegex(ValueError, '검토 기록이 변경'):
                verified_first_frame(script, scene)
            with self.assertRaisesRegex(ValueError, '미리보기 이후'):
                approve_first_frame(script, scene, str(frame), ['upper path'], ['collapse'],
                                    'Reviewed', digest)

    def test_production_stops_before_narration_without_first_frame_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'output_dir', Path(directory) / 'outputs',
        ), patch.object(settings, 'clips_dir', Path(directory) / 'clips'), patch.object(
            settings, 'paid_production_enabled', True,
        ):
            service = ProductionService(mode='video')
            result = asyncio.run(service.produce_video(sample_script()))
            self.assertFalse(result.success)
            self.assertIn('FIRST_FRAME_REVIEW_REQUIRED', result.error)
            self.assertIsNone(service._editor)
            self.assertIsNone(service._generator)

    def test_changed_frame_is_rejected_before_provider_reservation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'paid_production_enabled', True,
        ), patch.object(settings, 'max_visual_cost_usd', 1.0), patch(
            'shorts_maker.generator.video_generator.reserve_google_output',
        ) as reserve:
            frame = Path(directory) / 'frame.png'
            Image.new('RGB', (540, 960), 'pink').save(frame)
            generator = object.__new__(VideoGenerator)
            generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=Mock()))
            generator.max_veo_attempts = 1
            with self.assertRaisesRegex(ValueError, '첫 프레임이 변경'):
                generator._retry_veo_call(
                    'veo-3.1-lite-generate-001', 'prompt', str(Path(directory) / 'clip.mp4'),
                    'fallback', max_attempts=1, duration_seconds=4,
                    first_frame_path=str(frame), request_budget_usd=0.12,
                    expected_first_frame_sha256='wrong',
                )
            reserve.assert_not_called()
            generator.client.models.generate_videos.assert_not_called()

    def test_raw_verdict_binds_clip_and_script_before_final_edit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'output_dir', Path(directory) / 'outputs',
        ), patch.object(settings, 'clips_dir', Path(directory) / 'outputs' / 'clips'):
            frame = Path(directory) / 'frame.png'
            Image.new('RGB', (540, 960), 'pink').save(frame)
            script = sample_script()
            scene = script.scenes[0]
            frame_hash = inspect_frame(str(frame))
            approve_first_frame(script, scene, str(frame), ['upper walkway'], ['real demolition'],
                                'Two levels are legible', frame_hash)
            clip = settings.clips_dir / 'scenes' / 'sample' / 'clip.mp4'
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b'silent clip bytes')
            fake_video = MagicMock()
            fake_video.__enter__.return_value = SimpleNamespace(duration=4, audio=None, size=(540, 960))
            with patch('shorts_maker.services.raw_review.VideoFileClip', return_value=fake_video):
                save_raw_verdict(script, scene, str(clip), frame_hash, 'approved', 'Meaning is clear')
            self.assertEqual(raw_review_status(script, scene, str(clip), frame_hash), 'approved')
            self.assertEqual(len(verified_raw_clip(script, scene, str(clip), frame_hash)), 64)
            with patch('shorts_maker.services.raw_review.VideoFileClip', return_value=fake_video):
                save_raw_verdict(script, scene, str(clip), frame_hash, 'rejected', 'Motion implies demolition')
            self.assertEqual(raw_review_status(script, scene, str(clip), frame_hash), 'rejected')
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REVIEW_REQUIRED'):
                verified_raw_clip(script, scene, str(clip), frame_hash)
            clip.write_bytes(b'changed video bytes')
            self.assertEqual(raw_review_status(script, scene, str(clip), frame_hash), 'stale')
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REVIEW_REQUIRED'):
                verified_raw_clip(script, scene, str(clip), frame_hash)

    def test_production_stops_before_tts_when_raw_clip_is_unreviewed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')), patch.object(
            ProductionService, '_cached_clip', return_value=str(Path(directory) / 'clip.mp4'),
        ):
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
            result = asyncio.run(service.produce_video(sample_script()))
            self.assertFalse(result.success)
            self.assertIn('RAW_CLIP_REVIEW_REQUIRED', result.error)
            self.assertIsNone(service._editor)
            service._generator.generate_scene_clip.assert_not_awaited()

    def test_shared_clip_keeps_independent_verdicts_and_does_not_hide_corrupt_review(self):
        script, clip, frame_hash = self.saved_scene()
        revised = script.model_copy(deep=True)
        revised.description = 'Revised publication metadata'
        frame, _ = verified_first_frame(script, script.scenes[0])
        approve_first_frame(revised, revised.scenes[0], frame, ['two levels'], ['demolition'],
                            'Separate source-bound review', frame_hash)
        video = MagicMock()
        video.__enter__.return_value = SimpleNamespace(duration=8, audio=None, size=(540, 960))
        with patch('shorts_maker.services.raw_review.VideoFileClip', return_value=video):
            original = save_raw_verdict(script, script.scenes[0], str(clip), frame_hash,
                                        'approved', 'Owner approval')
            legacy = clip.with_suffix('.review.json')
            original.replace(legacy)
            self.assertEqual(raw_review_status(script, script.scenes[0], str(clip), frame_hash), 'approved')
            new = save_raw_verdict(revised, revised.scenes[0], str(clip), frame_hash,
                                  'rejected', 'Does not fit revised context')
            self.assertEqual(raw_review_status(script, script.scenes[0], str(clip), frame_hash), 'approved')
            self.assertEqual(raw_review_status(revised, revised.scenes[0], str(clip), frame_hash), 'rejected')
            original = save_raw_verdict(script, script.scenes[0], str(clip), frame_hash,
                                        'rejected', 'Later owner exclusion')
        self.assertNotEqual(original, new)
        self.assertEqual(json.loads(legacy.read_text())['decision'], 'approved')
        self.assertEqual(raw_review_status(script, script.scenes[0], str(clip), frame_hash), 'rejected')
        original.write_text('{broken')
        self.assertEqual(raw_review_status(script, script.scenes[0], str(clip), frame_hash), 'pending')
        with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REVIEW_REQUIRED'):
            verified_raw_clip(script, script.scenes[0], str(clip), frame_hash)

    def test_generate_review_clip_requests_one_scene_without_narration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch.object(settings, 'paid_production_enabled', True), patch.object(
            settings, 'max_visual_cost_usd', 1.0,
        ), patch.object(settings, 'veo_model_id', 'veo-3.1-lite-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 8,
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')), patch.object(
            ProductionService, '_save_clip', return_value='cached.mp4',
        ), patch('shorts_maker.services.production_service.complete_raw_request'), patch(
            'shorts_maker.services.production_service.check_google_budget',
        ) as budget:
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value='raw.mp4'))
            self.assertEqual(asyncio.run(service.generate_review_clip(
                sample_script(), 0, request_budget_usd=0.24,
            )), 'cached.mp4')
            service._generator.generate_scene_clip.assert_awaited_once()
            self.assertEqual(service._generator.generate_scene_clip.await_args.kwargs['first_frame_path'],
                             'reviewed.png')
            self.assertEqual(service._generator.generate_scene_clip.await_args.kwargs['request_budget_usd'], 0.24)
            budget.assert_called_once()
            self.assertIsNone(service._editor)
            directory_path = service._scene_cache_dir(sample_script().scenes[0], 'video', 'frame-hash')
            self.assertFalse((directory_path / 'request.pending.json').exists())

    def test_uncertain_raw_request_blocks_another_attempt(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch.object(settings, 'paid_production_enabled', True), patch.object(
            settings, 'max_visual_cost_usd', 1.0,
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')), patch(
            'shorts_maker.services.production_service.check_google_budget',
        ):
            script = sample_script()
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(side_effect=RuntimeError('timeout')))
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                asyncio.run(service.generate_review_clip(script, 0))
            marker = service._scene_cache_dir(script.scenes[0], 'video', 'frame-hash') / 'request.pending.json'
            self.assertTrue(marker.is_file())
            with self.assertRaisesRegex(ValueError, 'RAW_CLIP_REQUEST_UNVERIFIED'):
                asyncio.run(service.generate_review_clip(script, 0))
            service._generator.generate_scene_clip.assert_awaited_once()

    def test_staged_request_cap_rejects_before_creating_attempt_marker(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch.object(settings, 'veo_model_id', 'veo-3.1-lite-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 8,
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')):
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
            for cap in (0.23, -1, True, float('nan'), float('inf')):
                with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, 'VISUAL_REQUEST_CAP'):
                    asyncio.run(service.generate_review_clip(sample_script(), 0, request_budget_usd=cap))
            self.assertFalse(list(Path(directory).rglob('request.pending.json')))
            service._generator.generate_scene_clip.assert_not_awaited()

    def test_scene_cap_reaches_veo_boundary_in_video_and_hybrid_modes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'temp_dir', Path(directory),
        ), patch.object(settings, 'veo_model_id', 'veo-3.1-lite-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 8,
        ), patch.object(settings, 'hybrid_veo_duration_seconds', 8), patch.object(
            settings, 'max_visual_cost_usd', 1.0,
        ), patch('shorts_maker.generator.video_generator.check_google_budget'):
            for mode in ('video', 'hybrid'):
                with self.subTest(mode=mode):
                    generator = object.__new__(VideoGenerator)
                    generator.mode = mode
                    generator.max_veo_attempts = 1
                    generator.character_overlay = None
                    generator.client = Mock()
                    generator.logger = Mock()
                    generator._retry_veo_call = Mock(side_effect=lambda *args, **kwargs:
                                                     Path(args[2]).write_bytes(b'raw clip'))
                    asyncio.run(generator.generate_scene_clip(
                        sample_script().scenes[0], mode_override='video',
                        first_frame_path='reviewed.png', request_budget_usd=0.24,
                    ))
                    self.assertEqual(generator._retry_veo_call.call_args.kwargs['request_budget_usd'], 0.24)
                    self.assertEqual(generator._retry_veo_call.call_args.kwargs['max_attempts'], 1)

    def test_first_staged_request_checks_the_whole_remaining_visual_round(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch.object(settings, 'paid_production_enabled', True), patch.object(
            settings, 'max_visual_cost_usd', 1.0,
        ), patch.object(settings, 'veo_model_id', 'veo-3.1-fast-generate-001'), patch.object(
            settings, 'veo_duration_seconds', 8,
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')), patch(
            'shorts_maker.services.production_service.check_google_budget',
        ) as budget:
            script = sample_script()
            script.scenes.append(VideoScene(scene_number=2, visual_description='Show the lower bridge',
                                            motion_instruction='Hold the lower bridge',
                                            script_text='The original bridge remains.'))
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
            with self.assertRaisesRegex(ValueError, 'VISUAL_COST_CAP_EXCEEDED'):
                asyncio.run(service.generate_review_clip(script, 0))
            budget.assert_not_called()
            service._generator.generate_scene_clip.assert_not_awaited()
