"""Checks for resuming paid work and rejecting unfit output."""

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from PIL import Image
from moviepy import AudioClip, ColorClip, VideoFileClip

from scripts.paired_review import estimate_pair, render_pair
from shorts_maker.editor.quality_check import check_video_quality
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
from shorts_maker.uploader.youtube_uploader import YouTubeUploader
from shorts_maker.utils.bgm_manager import BGMManager
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
    def test_music_requires_matching_documented_track_before_paid_work(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "bgm_dir", Path(directory)):
            track = Path(directory) / "calm_review.mp3"
            track.write_bytes(b"local music sample")
            manager = BGMManager()
            self.assertIsNone(manager.get_bgm_path("calm"))
            record = Path(f"{track}.license.json")
            record.write_text(json.dumps({
                "title": "Review track", "artist": "Example artist",
                "source_url": "https://example.com/music", "license": "No attribution required",
                "attribution_required": False,
                "sha256": hashlib.sha256(track.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            self.assertEqual(manager.get_bgm_path("calm"), str(track))
            track.write_bytes(b"replaced music")
            self.assertIsNone(manager.get_bgm_path("calm"))
            editor = object.__new__(VideoEditor)
            editor.bgm_manager = manager
            editor.bgm_mood = "calm"
            editor.bgm_volume = 0.15
            with self.assertRaisesRegex(ValueError, "사용 권한이 기록된 BGM"):
                editor.preflight_music(sample_script())
            editor.bgm_volume = 0
            self.assertIsNone(editor.preflight_music(sample_script()))

        service = ProductionService()
        service._editor = fake_editor("unused.mp4")
        service._editor.preflight_music = Mock(side_effect=ValueError("documented BGM missing"))
        service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
        result = asyncio.run(service.produce_video(sample_script()))
        self.assertFalse(result.success)
        self.assertIn("documented BGM missing", result.error)
        service._editor.prepare_narration.assert_not_awaited()
        service._generator.generate_scene_clip.assert_not_awaited()

        planning = ProductionService(editor_options={"bgm_mood": "calm"})
        planning._editor = SimpleNamespace(preflight_music=Mock(side_effect=ValueError("music missing")))
        planning._planner = SimpleNamespace(plan_content=AsyncMock())
        self.assertEqual(asyncio.run(planning.generate_script()), (None, None))
        planning._planner.plan_content.assert_not_awaited()

    def test_youtube_refresh_failure_preserves_saved_token(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token.json"
            token.write_text("{}", encoding="utf-8")
            secrets = Path(directory) / "client_secrets.json"
            secrets.write_text("{}", encoding="utf-8")
            uploader = object.__new__(YouTubeUploader)
            uploader.token_file = str(token)
            uploader.client_secrets_file = str(secrets)
            uploader.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
            uploader.logger = Mock()
            credentials = SimpleNamespace(
                valid=False, expired=True, refresh_token="saved",
                refresh=Mock(side_effect=OSError("offline")),
            )
            with patch("shorts_maker.uploader.youtube_uploader.Credentials.from_authorized_user_info", return_value=credentials):
                with patch("shorts_maker.uploader.youtube_uploader.InstalledAppFlow.from_client_secrets_file") as login:
                    login.return_value.run_local_server.side_effect = OSError("offline")
                    with self.assertRaisesRegex(OSError, "offline"):
                        uploader.get_authenticated_service()
            self.assertEqual(token.read_text(encoding="utf-8"), "{}")
            login.assert_called_once()

    def test_rendered_audio_is_normalized_without_reencoding_video(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "quiet.mp4"
            audio = AudioClip(lambda t: 0.02 * np.sin(2 * np.pi * 220 * t), duration=3, fps=8000)
            video = ColorClip((108, 192), color=(60, 90, 120), duration=3).with_audio(audio)
            try:
                video.write_videofile(str(output), fps=4, codec="libx264", audio_codec="aac", logger=None)
            finally:
                video.close()
                audio.close()

            with VideoFileClip(str(output)) as rendered:
                before = np.sqrt(np.mean(rendered.audio.to_soundarray(fps=8000) ** 2))
            VideoEditor._normalize_output_audio(str(output))
            with VideoFileClip(str(output)) as normalized:
                after = np.sqrt(np.mean(normalized.audio.to_soundarray(fps=8000) ** 2))
                self.assertAlmostEqual(normalized.duration, 3, delta=0.1)
                self.assertEqual((normalized.w, normalized.h), (108, 192))
            self.assertGreater(after, before * 5)
            self.assertLess(after, 0.7)
            self.assertFalse((Path(directory) / "quiet.normalized.mp4").exists())

    def test_veo_prompt_version_only_invalidates_video_cache(self):
        service = object.__new__(ProductionService)
        service.character_overlay_config = None
        service.mode = "hybrid"
        scene = sample_script().scenes[0]
        image_key = service._scene_cache_dir(scene, "image")
        video_key = service._scene_cache_dir(scene, "video")

        with patch("shorts_maker.services.production_service.VIDEO_PROMPT_VERSION", 999):
            self.assertEqual(service._scene_cache_dir(scene, "image"), image_key)
            self.assertNotEqual(service._scene_cache_dir(scene, "video"), video_key)

    def test_pair_budget_stops_before_paid_narration(self):
        script = sample_script()
        script.scenes[0].visual_mode = "video"
        script.scenes[1].visual_mode = "image"
        image, hybrid = estimate_pair(script)
        self.assertAlmostEqual(image + hybrid, 0.582)
        with patch("scripts.paired_review.VideoEditor") as editor:
            with self.assertRaisesRegex(ValueError, "비교 실험 상한"):
                asyncio.run(render_pair(script, budget_usd=0.50))
        editor.assert_not_called()

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
            script.scenes[0].script_text = "Narration revised without changing the visual"
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
            cached = cache / "clip.png"
            cached.write_bytes(b"corrupt")
            self.assertIsNone(ProductionService._cached_clip(cache, "image"))

    def test_estimated_cost_cap_blocks_paid_calls_and_tts(self):
        service = ProductionService(mode="hybrid")
        service._editor = fake_editor("unused.mp4")
        service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
        with patch.object(settings, "max_visual_cost_usd", 0.10):
            result = asyncio.run(service.produce_video(sample_script()))
        self.assertFalse(result.success)
        self.assertIn("예상 비주얼 비용", result.error)
        service._editor.prepare_narration.assert_not_awaited()
        service._generator.generate_scene_clip.assert_not_awaited()

    @patch("shorts_maker.services.production_service.check_video_quality")
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_hybrid_generates_video_hook_and_image_remainder(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            output = Path(directory) / "output.mp4"
            output.touch()
            script = sample_script()
            service = ProductionService(mode="hybrid")
            service._editor = fake_editor(output)
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(
                side_effect=[str(output), str(output)],
            ))
            with patch.object(ProductionService, "_save_clip", side_effect=lambda _dir, _mode, path: path):
                result = asyncio.run(service.produce_video(script))
            self.assertTrue(result.success)
            self.assertEqual(result.generated_scenes, 2)
            self.assertAlmostEqual(result.estimated_visual_cost_usd, 0.514)
            calls = service._generator.generate_scene_clip.await_args_list
            self.assertEqual([call.kwargs["mode_override"] for call in calls], ["video", "image"])
            report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
            self.assertTrue(report["quality_passed"])
            self.assertEqual(report["source_url"], script.source_url)
            self.assertEqual(report["production_mode"], "hybrid")
            self.assertTrue(report["paired_comparison_eligible"])
            self.assertEqual([scene["visual_mode"] for scene in report["scenes"]], ["video", "image"])
            self.assertEqual([scene["source"] for scene in report["scenes"]], ["generated", "generated"])
            self.assertAlmostEqual(report["estimated_visual_output_cost_usd"], 0.514)

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
            self.assertAlmostEqual(result.estimated_visual_cost_usd, 0.068)
            report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
            self.assertFalse(report["quality_passed"])
            self.assertEqual(report["quality_error"], "무음")
            self.assertIsNone(report["youtube_id"])

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_upload_records_video_id_in_existing_report(self, _check):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "scene.mp4"
            output = Path(directory) / "output.mp4"
            clip.touch()
            output.touch()
            service = ProductionService(mode="video")
            service._editor = fake_editor(output)
            service._uploader = SimpleNamespace(upload=AsyncMock(return_value="video-id"))
            script = sample_script()
            script.scenes = script.scenes[:1]
            produced = asyncio.run(service.produce_video(script, manual_clip_paths={1: str(clip)}))
            uploaded = asyncio.run(service.upload_to_youtube(str(output), {"title": script.title}))

            self.assertTrue(produced.success)
            self.assertTrue(uploaded.success)
            report = json.loads(Path(produced.report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["scenes"][0]["source"], "manual")
            self.assertFalse(report["paired_comparison_eligible"])
            self.assertEqual(report["estimated_visual_output_cost_usd"], 0)
            self.assertEqual(report["youtube_id"], "video-id")
            self.assertIn("uploaded_at_utc", report)

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

    @patch("shorts_maker.services.production_service.check_video_quality")
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_prepared_narration_skips_tts_and_remains_caller_owned(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            source = Path(directory) / "scene.png"
            output = Path(directory) / "output.mp4"
            audio = Path(directory) / "narration.mp3"
            Image.new("RGB", (4, 8), "red").save(source)
            output.touch()
            audio.write_bytes(b"caller-owned")
            service = ProductionService()
            service._editor = fake_editor(output)
            service._editor.validate_narration = Mock()
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(source)))

            result = asyncio.run(service.produce_video(
                sample_script(), prepared_audio_paths=[str(audio), str(audio)],
            ))

            self.assertTrue(result.success)
            service._editor.prepare_narration.assert_not_awaited()
            service._editor.validate_narration.assert_called_once()
            self.assertEqual(service._editor.compose_video.await_args.kwargs["audio_paths"], [str(audio)] * 2)
            service._editor.cleanup_temp_files.assert_not_called()
            self.assertTrue(audio.exists())

            editor = object.__new__(VideoEditor)
            editor._temp_files = []
            editor.logger = Mock()
            editor.cleanup_old_temp_files = Mock()
            editor._get_voice_for_mood = Mock(return_value="alloy")
            editor._create_visual_clip = Mock(side_effect=RuntimeError("stop before render"))
            one_scene_script = sample_script()
            one_scene_script.scenes = one_scene_script.scenes[:1]
            with patch("shorts_maker.editor.video_editor.AudioFileClip", return_value=SimpleNamespace(duration=1, close=Mock())):
                with self.assertRaisesRegex(RuntimeError, "stop before render"):
                    asyncio.run(editor.compose_video([str(source)], one_scene_script, audio_paths=[str(audio)]))
            self.assertTrue(audio.exists())

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

    def test_korean_subtitle_keeps_punctuation_with_word(self):
        text = "올여름 NASA 팀은 드론 한 대와 로버 두 대의 협업을 시험했습니다."
        wrapped = VideoEditor._wrap_subtitle(text, "AppleGothic", 60)
        self.assertGreater(len(wrapped.splitlines()), 1)
        self.assertEqual(wrapped.replace("\n", " "), text)
        self.assertNotIn("\n.", wrapped)

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
        clip.duration = 30
        clip.w = 1062
        clip.h = 1920
        with self.assertRaisesRegex(ValueError, "9:16"):
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
