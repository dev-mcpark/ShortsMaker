"""Checks for resuming paid work and rejecting unfit output."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from PIL import Image
from moviepy import AudioClip, ColorClip

from shorts_maker.editor.quality_check import check_video_quality
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.config import settings


def sample_script():
    return ShortsScript(
        title="Example", description="", tags=[], mood="calm", style="plain",
        source_name="test", source_url="https://example.com", generation_mode="image",
        scenes=[
            VideoScene(scene_number=1, visual_description="First", script_text="First"),
            VideoScene(scene_number=2, visual_description="Second", script_text="Second"),
        ],
    )


def fake_editor(output):
    return SimpleNamespace(
        prepare_narration=AsyncMock(return_value=["one.mp3", "two.mp3"]),
        compose_video=AsyncMock(return_value=str(output)),
        cleanup_temp_files=Mock(),
    )


class ProductionGateTests(unittest.TestCase):
    @patch("shorts_maker.services.production_service.check_video_quality")
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_retry_only_generates_missing_scene(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            source1, source2, output = (Path(directory) / name for name in ("one.png", "two.png", "out.mp4"))
            Image.new("RGB", (4, 8), "red").save(source1)
            Image.new("RGB", (4, 8), "blue").save(source2)
            output.touch()
            script = sample_script()
            first = ProductionService()
            first._editor = fake_editor(output)
            first._generator = SimpleNamespace(generate_scene_clip=AsyncMock(
                side_effect=[str(source1), RuntimeError("API failed")]
            ))

            failed = asyncio.run(first.produce_video(script))
            self.assertFalse(failed.success)
            self.assertEqual(len(failed.clips), 1)
            self.assertTrue(Path(failed.clips[0]).is_file())

            retry = ProductionService()
            retry._editor = fake_editor(output)
            retry._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(source2)))
            result = asyncio.run(retry.produce_video(script))

            self.assertTrue(result.success)
            self.assertTrue(result.ready_for_upload)
            retry._generator.generate_scene_clip.assert_awaited_once_with(script.scenes[1])
            self.assertEqual(Path(result.clips[0]).read_bytes(), source1.read_bytes())
            self.assertEqual(Path(result.clips[1]).read_bytes(), source2.read_bytes())
            self.assertEqual(retry._editor.compose_video.await_args.kwargs["audio_paths"], ["one.mp3", "two.mp3"])

    def test_corrupt_cached_scene_is_regenerated(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            cached = cache / "scene_01.png"
            cached.write_bytes(b"corrupt")
            self.assertIsNone(ProductionService._cached_clip(cache, 1, "image"))

    @patch("shorts_maker.services.production_service.check_video_quality")
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_parallel_retry_keeps_successful_scene(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            source = Path(directory) / "first.png"
            output = Path(directory) / "output.mp4"
            Image.new("RGB", (4, 8), "red").save(source)
            output.touch()
            script = sample_script()

            async def generate(scene):
                if scene.scene_number == 2:
                    raise RuntimeError("API failed")
                return str(source)

            first = ProductionService(parallel_clips=True)
            first._editor = fake_editor(output)
            first._generator = SimpleNamespace(generate_scene_clip=AsyncMock(side_effect=generate))
            failed = asyncio.run(first.produce_video(script))
            self.assertFalse(failed.success)
            self.assertEqual(len(failed.clips), 1)

            second = ProductionService(parallel_clips=True)
            second._editor = fake_editor(output)
            second._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(source)))
            result = asyncio.run(second.produce_video(script))
            self.assertTrue(result.success)
            second._generator.generate_scene_clip.assert_awaited_once_with(script.scenes[1])

    def test_narration_failure_stops_before_paid_visual_generation(self):
        service = ProductionService()
        service._editor = fake_editor("unused.mp4")
        service._editor.prepare_narration.side_effect = ValueError("내레이션이 너무 깁니다")
        service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())

        result = asyncio.run(service.produce_video(sample_script()))

        self.assertFalse(result.success)
        self.assertIn("내레이션", result.error)
        service._generator.generate_scene_clip.assert_not_awaited()

    @patch("shorts_maker.services.production_service.check_video_quality", side_effect=ValueError("무음"))
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_failed_quality_keeps_preview_without_upload_readiness(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            source = Path(directory) / "scene.png"
            output = Path(directory) / "output.mp4"
            Image.new("RGB", (4, 8), "red").save(source)
            output.touch()
            service = ProductionService()
            service._editor = fake_editor(output)
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(source)))

            result = asyncio.run(service.produce_video(sample_script()))

            self.assertFalse(result.success)
            self.assertFalse(result.ready_for_upload)
            self.assertEqual(result.video_path, str(output))

    def test_narration_duration_limit_and_audio_reuse(self):
        editor = object.__new__(VideoEditor)
        editor._temp_files = []
        editor.logger = Mock()
        editor._get_voice_for_mood = Mock(return_value="alloy")
        editor._generate_tts = AsyncMock(side_effect=["one.mp3", "two.mp3"])
        editor.cleanup_temp_files = Mock()
        audio = SimpleNamespace(duration=40, close=Mock())
        with patch("shorts_maker.editor.video_editor.AudioFileClip", return_value=audio):
            with self.assertRaisesRegex(ValueError, "내레이션"):
                asyncio.run(editor.prepare_narration(sample_script()))
        editor.cleanup_temp_files.assert_called_once()

        editor._generate_tts.reset_mock()
        editor.cleanup_old_temp_files = Mock()
        editor._cleanup_clips = Mock()
        editor._track_temp_file = Mock()
        with patch("shorts_maker.editor.video_editor.AudioFileClip", return_value=audio):
            with self.assertRaisesRegex(RuntimeError, "취소"):
                asyncio.run(editor.compose_video(
                    ["one.png", "two.png"], sample_script(),
                    audio_paths=["one.mp3", "two.mp3"], is_cancelled=lambda: True,
                ))
        editor._generate_tts.assert_not_awaited()

    def test_subtitle_is_placed_inside_frame(self):
        editor = object.__new__(VideoEditor)
        editor.logger = Mock()
        editor.subtitle_size = 60
        editor.subtitle_color = "white"
        editor.subtitle_y_position = 1900
        clip = Mock(h=500)
        with patch("shorts_maker.editor.video_editor.TextClip", return_value=clip):
            editor._create_subtitle_clips("Caption", 3)
        clip.with_position.assert_called_once_with(("center", settings.video_height - 500 - 80))

    @patch("shorts_maker.editor.quality_check.VideoFileClip")
    def test_quality_check_rejects_silent_video(self, open_video):
        clip = SimpleNamespace(
            duration=30, w=1080, h=1920,
            get_frame=Mock(return_value=np.full((2, 2, 3), 50)),
            audio=SimpleNamespace(get_frame=Mock(return_value=np.zeros(2))),
            close=Mock(),
        )
        open_video.return_value = clip
        with self.assertRaisesRegex(ValueError, "무음"):
            check_video_quality("output.mp4")
        clip.close.assert_called_once()
        clip.audio.get_frame.return_value = np.full(2, 0.1)
        clip.get_frame.return_value = np.zeros((2, 2, 3))
        with self.assertRaisesRegex(ValueError, "검은 화면"):
            check_video_quality("output.mp4")
        clip.duration = 70
        with self.assertRaisesRegex(ValueError, "영상 길이"):
            check_video_quality("output.mp4")

    def test_quality_check_reads_rendered_media(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.mp4"
            audio = AudioClip(lambda t: 0.2 * np.sin(2 * np.pi * 123 * t), duration=1, fps=8000)
            video = ColorClip((108, 192), color=(60, 90, 120), duration=1).with_audio(audio)
            try:
                video.write_videofile(str(output), fps=4, codec="libx264", audio_codec="aac", logger=None)
            finally:
                video.close()
                audio.close()
            check_video_quality(str(output))

    @patch("shorts_maker.services.production_service.check_video_quality", side_effect=ValueError("무음"))
    def test_quality_failure_blocks_upload(self, _check):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp4"
            output.touch()
            service = ProductionService()
            service._uploader = SimpleNamespace(upload=AsyncMock(return_value="video-id"))
            result = asyncio.run(service.upload_to_youtube(str(output), {"title": "Example"}))
        self.assertFalse(result.success)
        self.assertEqual(result.video_path, str(output))
        service._uploader.upload.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
