"""Source-bound first-frame review before new paid Veo scene output."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
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
