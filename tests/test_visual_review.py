"""Source-bound first-frame review before new paid Veo scene output."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from PIL import Image

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
from shorts_maker.services.raw_review import raw_review_status, save_raw_verdict, verified_raw_clip
from shorts_maker.services.visual_review import (
    approve_first_frame, inspect_frame, verified_first_frame,
)
from shorts_maker.utils.config import settings


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

    def test_generate_review_clip_requests_one_scene_without_narration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'clips_dir', Path(directory) / 'clips',
        ), patch.object(settings, 'paid_production_enabled', True), patch.object(
            settings, 'max_visual_cost_usd', 1.0,
        ), patch('shorts_maker.services.production_service.verified_first_frame',
                 return_value=('reviewed.png', 'frame-hash')), patch.object(
            ProductionService, '_save_clip', return_value='cached.mp4',
        ), patch('shorts_maker.services.production_service.check_google_budget') as budget:
            service = ProductionService(mode='video')
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value='raw.mp4'))
            self.assertEqual(asyncio.run(service.generate_review_clip(sample_script(), 0)), 'cached.mp4')
            service._generator.generate_scene_clip.assert_awaited_once()
            self.assertEqual(service._generator.generate_scene_clip.await_args.kwargs['first_frame_path'],
                             'reviewed.png')
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
