"""Checks for resuming paid work and rejecting unfit output."""

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy as np
from openai import APIConnectionError, BadRequestError, RateLimitError
from PIL import Image
from moviepy import AudioClip, AudioFileClip, ColorClip, TextClip, VideoFileClip, concatenate_videoclips

from scripts.paired_review import estimate_pair, render_pair
from shorts_maker.editor.quality_check import check_video_quality
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.planner.content_enricher import ContentEnricher
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionService
from shorts_maker.uploader.youtube_uploader import YouTubeUploader
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.character_video_generator import CharacterVideoGenerator
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
    def setUp(self):
        paid = patch.object(settings, "paid_production_enabled", True)
        paid.start()
        self.addCleanup(paid.stop)

    def test_prepared_narration_manifest_rejects_wrong_script_or_file(self):
        script = sample_script()
        script.scenes = script.scenes[:1]
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "scene_1.wav"
            audio.write_bytes(b"recorded")
            manifest = {"schema_version": 1, "scenes": {"1": {
                "status": "complete",
                "text_sha256": hashlib.sha256(b"First").hexdigest(),
                "file_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
            }}}
            (Path(directory) / "narration.json").write_text(json.dumps(manifest))
            with patch("shorts_maker.editor.video_editor.AudioFileClip",
                       return_value=SimpleNamespace(duration=1.0, close=Mock())):
                VideoEditor.validate_narration([str(audio)], script)
                script.scenes[0].script_text = "Different claim"
                with self.assertRaisesRegex(ValueError, "대본"):
                    VideoEditor.validate_narration([str(audio)], script)
                script.scenes[0].script_text = "First"
                audio.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "준비 기록"):
                    VideoEditor.validate_narration([str(audio)], script)

    def test_direct_provider_helpers_respect_paid_switch(self):
        video_client = SimpleNamespace(models=SimpleNamespace(generate_videos=Mock()))
        image_client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock()))
        video = object.__new__(VideoGenerator)
        video.client = video_client
        video.image_client = image_client
        voice = object.__new__(VideoEditor)
        voice.client = SimpleNamespace(audio=SimpleNamespace(
            speech=SimpleNamespace(create=AsyncMock())))
        character = object.__new__(CharacterVideoGenerator)
        character.client = video_client
        enricher = object.__new__(ContentEnricher)
        enricher.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock())))
        enricher.search_api_key = "test-key"
        enricher.logger = Mock()

        with patch.object(settings, "paid_production_enabled", False):
            with self.assertRaisesRegex(RuntimeError, "PAID_PRODUCTION_ENABLED"):
                video._run_image_generation("image-model", SimpleNamespace(
                    visual_description="scene"), "unused.png")
            with self.assertRaisesRegex(RuntimeError, "PAID_PRODUCTION_ENABLED"):
                video._retry_veo_call("video-model", "prompt", "unused.mp4", "fallback")
            with self.assertRaisesRegex(RuntimeError, "PAID_PRODUCTION_ENABLED"):
                character._run_veo_generation("video-model", "prompt", object(), "unused.mp4", 6)
            with self.assertRaisesRegex(RuntimeError, "PAID_PRODUCTION_ENABLED"):
                asyncio.run(voice._generate_tts("문장", 0, "nova"))
            with self.assertRaisesRegex(RuntimeError, "PAID_PRODUCTION_ENABLED"):
                asyncio.run(enricher._generate_search_query("topic", "message", []))
            with patch("shorts_maker.planner.content_enricher.requests.get") as search:
                self.assertEqual(asyncio.run(enricher._search_web_brave("query")), [])
                search.assert_not_called()

        image_client.models.generate_content.assert_not_called()
        video_client.models.generate_videos.assert_not_called()
        voice.client.audio.speech.create.assert_not_awaited()
        enricher.client.chat.completions.create.assert_not_awaited()

        character.logger = Mock()
        video_client.models.generate_videos.side_effect = RuntimeError("500 provider error")
        self.assertFalse(character._run_veo_generation(
            "video-model", "prompt", object(), "unused.mp4", 6))
        video_client.models.generate_videos.assert_called_once()

    def test_local_editor_needs_no_openai_key_until_tts(self):
        with patch.object(settings, "openai_api_key", ""), patch(
            "shorts_maker.editor.video_editor.AsyncOpenAI"
        ) as client_class:
            editor = VideoEditor(bgm_volume=0)
            self.assertIsNone(editor.preflight_music(sample_script()))
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is required"):
                asyncio.run(editor._generate_tts("확인", 0, "nova"))
            client_class.assert_not_called()

    def test_tts_retries_only_transient_failure_and_keeps_voice(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/audio/speech")
        with patch.object(settings, "openai_api_key", "test-key"), patch(
            "shorts_maker.editor.video_editor.AsyncOpenAI"
        ) as client_class:
            editor = VideoEditor(bgm_volume=0)
            client_class.assert_not_called()
            client_class.return_value = SimpleNamespace(
                audio=SimpleNamespace(speech=SimpleNamespace(create=AsyncMock(
                    return_value=SimpleNamespace(stream_to_file=Mock())
                )))
            )
            with tempfile.TemporaryDirectory() as directory, patch.object(settings, "temp_dir", Path(directory)):
                asyncio.run(editor._generate_tts("확인", 0, "nova"))
            client_class.assert_called_once_with(api_key="test-key", max_retries=0)

        editor = object.__new__(VideoEditor)
        editor.logger = Mock()
        editor._temp_files = []
        response = SimpleNamespace(stream_to_file=Mock())
        create = AsyncMock(side_effect=[APIConnectionError(request=request), response])
        editor.client = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "temp_dir", Path(directory)):
            with patch("shorts_maker.editor.video_editor.asyncio.sleep", new_callable=AsyncMock) as sleep:
                asyncio.run(editor._generate_tts("확인", 0, "nova"))
            self.assertEqual(create.await_count, 2)
            sleep.assert_awaited_once_with(2)
            self.assertEqual(create.await_args.kwargs["voice"], "nova")

            for error in (
                BadRequestError("bad request", response=httpx.Response(400, request=request), body=None),
                RateLimitError("quota", response=httpx.Response(429, request=request), body=None),
            ):
                create.reset_mock()
                create.side_effect = error
                with patch("shorts_maker.editor.video_editor.asyncio.sleep", new_callable=AsyncMock) as sleep:
                    with self.assertRaises(type(error)):
                        asyncio.run(editor._generate_tts("확인", 1, "nova"))
                create.assert_awaited_once()
                sleep.assert_not_awaited()

            create.reset_mock()
            create.side_effect = APIConnectionError(request=request)
            with patch("shorts_maker.editor.video_editor.asyncio.sleep", new_callable=AsyncMock) as sleep:
                with self.assertRaises(APIConnectionError):
                    asyncio.run(editor._generate_tts("확인", 2, "nova"))
            self.assertEqual(create.await_count, 2)
            sleep.assert_awaited_once_with(2)

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
            self.assertEqual(manager.get_track_path("calm_review.mp3"), str(track))
            self.assertEqual(manager.list_documented_tracks(), {
                "calm_review.mp3": "Review track — Example artist",
            })
            self.assertIsNone(manager.get_track_path("../calm_review.mp3"))
            self.assertIsNone(manager.get_track_path("other.mp3"))
            editor = object.__new__(VideoEditor)
            editor.bgm_manager = manager
            editor.bgm_mood = "auto"
            editor.bgm_volume = 0.4
            self.assertEqual(editor.preflight_music(sample_script()), str(track))
            editor.bgm_mood = "calm"
            track.write_bytes(b"replaced music")
            self.assertIsNone(manager.get_bgm_path("calm"))
            self.assertIsNone(manager.get_track_path("calm_review.mp3"))
            self.assertEqual(manager.list_documented_tracks(), {})
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

        exact_track = ProductionService(editor_options={"bgm_track": "missing.mp3"})
        exact_track._editor = SimpleNamespace(preflight_music=Mock(side_effect=ValueError("exact music missing")))
        exact_track._planner = SimpleNamespace(plan_content=AsyncMock())
        self.assertEqual(asyncio.run(exact_track.generate_script()), (None, None))
        exact_track._planner.plan_content.assert_not_awaited()

        with patch.object(BGMManager, "has_documented_track", return_value=False):
            automatic_mood = ProductionService(editor_options={"bgm_mood": "auto"})
            automatic_mood._planner = SimpleNamespace(plan_content=AsyncMock())
            self.assertEqual(asyncio.run(automatic_mood.generate_script()), (None, None))
            automatic_mood._planner.plan_content.assert_not_awaited()
        with patch.object(BGMManager, "has_documented_track", return_value=True):
            automatic_mood = ProductionService(editor_options={"bgm_mood": "auto"})
            automatic_mood._editor = SimpleNamespace(preflight_music=Mock())
            automatic_mood._planner = SimpleNamespace(
                plan_content=AsyncMock(return_value=(sample_script(), None)))
            self.assertEqual(asyncio.run(automatic_mood.generate_script())[0].mood, "calm")
            automatic_mood._editor.preflight_music.assert_not_called()

    def test_sci_fi_music_prefers_documented_futuristic_track(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "bgm_dir", Path(directory)):
            for mood in ("mysterious", "futuristic"):
                track = Path(directory) / f"{mood}_sample.mp3"
                track.write_bytes(mood.encode())
                Path(f"{track}.license.json").write_text(json.dumps({
                    "title": mood, "artist": "Test artist",
                    "source_url": "https://example.com/music",
                    "license": "No attribution required", "attribution_required": False,
                    "sha256": hashlib.sha256(track.read_bytes()).hexdigest(),
                }), encoding="utf-8")
            self.assertEqual(
                BGMManager().get_bgm_path("sci-fi"),
                str(Path(directory) / "futuristic_sample.mp3"),
            )

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

    def test_youtube_upload_sends_private_synthetic_disclosure(self):
        uploader = object.__new__(YouTubeUploader)
        uploader.logger = Mock()
        youtube = Mock()
        youtube.videos.return_value.insert.return_value.next_chunk.return_value = (None, {"id": "video-id"})
        uploader.get_authenticated_service = Mock(return_value=youtube)
        with patch("shorts_maker.uploader.youtube_uploader.MediaFileUpload"):
            for metadata, expected in (
                ({"title": "Generated"}, True),
                ({"title": "Documentary", "contains_synthetic_media": False}, False),
            ):
                self.assertEqual(uploader._upload_sync("review.mp4", metadata), "video-id")
                body = youtube.videos.return_value.insert.call_args.kwargs["body"]
                self.assertEqual(body["status"]["privacyStatus"], "private")
                self.assertIs(body["status"]["containsSyntheticMedia"], expected)
            uploader.get_authenticated_service.reset_mock()
            self.assertIsNone(uploader._upload_sync("review.mp4", {"contains_synthetic_media": "no"}))
            uploader.get_authenticated_service.assert_not_called()

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

    def test_quiet_narration_is_normalized_before_music_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "temp_dir", Path(directory)):
            source = Path(directory) / "quiet.wav"
            audio = AudioClip(lambda t: 0.01 * np.sin(2 * np.pi * 220 * t), duration=2, fps=8000)
            try:
                audio.write_audiofile(str(source), fps=8000, logger=None)
            finally:
                audio.close()
            original = source.read_bytes()
            editor = VideoEditor(bgm_volume=0)
            normalized_path = editor._normalize_narration_audio(str(source))
            with AudioFileClip(str(source)) as before, AudioFileClip(normalized_path) as after:
                self.assertGreater(after.max_volume(), before.max_volume() * 4)
                self.assertAlmostEqual(after.duration, before.duration, delta=0.05)
            self.assertEqual(source.read_bytes(), original)
            editor.cleanup_temp_files()
            self.assertFalse(Path(normalized_path).exists())

    def test_short_video_holds_final_frame_without_retiming_reveal(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.mp4"
            first = ColorClip((8, 16), color=(255, 0, 0), duration=0.5)
            second = ColorClip((8, 16), color=(0, 0, 255), duration=0.5)
            clip = concatenate_videoclips([first, second])
            try:
                clip.write_videofile(str(source), fps=12, codec="libx264", audio=False, logger=None)
            finally:
                clip.close()
                first.close()
                second.close()
            extended = VideoEditor(bgm_volume=0)._create_visual_clip(str(source), 1.5)
            try:
                self.assertAlmostEqual(extended.duration, 1.5, delta=0.02)
                self.assertGreater(extended.get_frame(0.65)[900, 500, 2], 200)
                self.assertGreater(extended.get_frame(1.1)[900, 500, 2], 200)
            finally:
                extended.close()

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
    def test_zero_paid_round_blocks_api_work_but_allows_complete_local_edit(self, _check):
        with patch.object(settings, "paid_production_enabled", False):
            planning = ProductionService(editor_options={"bgm_volume": 0})
            planning._planner = SimpleNamespace(plan_content=AsyncMock())
            self.assertEqual(asyncio.run(planning.generate_script()), (None, None))
            planning._planner.plan_content.assert_not_awaited()
            full = asyncio.run(planning.full_pipeline())
            self.assertFalse(full.success)
            self.assertIn("PAID_PRODUCTION_ENABLED", full.error)
            planning._planner.plan_content.assert_not_awaited()

            context = SimpleNamespace(attempt_count=0, max_attempts=2, source_item={})
            planning._planner.regenerate = AsyncMock()
            self.assertIsNone(asyncio.run(planning.regenerate_script(context, "revise")))
            self.assertEqual(context.attempt_count, 0)
            planning._planner.regenerate.assert_not_awaited()

            paid_video = ProductionService(mode="image", editor_options={"bgm_volume": 0})
            paid_video._editor = fake_editor("unused.mp4")
            paid_video._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
            result = asyncio.run(paid_video.produce_video(sample_script()))
            self.assertFalse(result.success)
            self.assertIn("PAID_PRODUCTION_ENABLED", result.error)
            paid_video._editor.prepare_narration.assert_not_awaited()
            paid_video._generator.generate_scene_clip.assert_not_awaited()

            with tempfile.TemporaryDirectory() as directory:
                clip = Path(directory) / "scene.mp4"
                output = Path(directory) / "review.mp4"
                clip.touch()
                output.touch()
                script = sample_script()
                script.scenes = script.scenes[:1]
                local = ProductionService(mode="video", editor_options={"bgm_volume": 0})
                local._editor = fake_editor(output)
                local._editor.validate_narration = Mock()
                result = asyncio.run(local.produce_video(
                    script, manual_clip_paths={1: str(clip)},
                    prepared_audio_paths=["prepared.wav"],
                ))
                self.assertTrue(result.success)
                local._editor.prepare_narration.assert_not_awaited()

            with patch("scripts.paired_review.VideoEditor") as narrator:
                with self.assertRaisesRegex(ValueError, "PAID_PRODUCTION_ENABLED"):
                    asyncio.run(render_pair(sample_script(), budget_usd=2.0))
            narrator.assert_not_called()

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

    def test_veo_retry_reserve_blocks_before_paid_work(self):
        self.assertEqual(ProductionService(mode="hybrid").max_veo_attempts, 1)
        with self.assertRaisesRegex(ValueError, "max_veo_attempts"):
            ProductionService(mode="hybrid", max_veo_attempts=0)
        service = ProductionService(mode="hybrid", max_veo_attempts=2)
        service._editor = fake_editor("unused.mp4")
        service._generator = SimpleNamespace(generate_scene_clip=AsyncMock())
        with patch.object(settings, "max_visual_cost_usd", 0.90):
            result = asyncio.run(service.produce_video(sample_script()))
        self.assertFalse(result.success)
        self.assertIn("$0.994", result.error)
        service._editor.prepare_narration.assert_not_awaited()
        service._generator.generate_scene_clip.assert_not_awaited()

    @patch("shorts_maker.services.production_service.check_video_quality")
    @patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock)
    def test_hybrid_generates_video_hook_and_image_remainder(self, _sleep, _check):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            output = Path(directory) / "output.mp4"
            output.touch()
            script = sample_script()
            script.music_direction = "조용한 호기심, 강한 드럼은 피함"
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
            self.assertEqual(report["music_direction"], script.music_direction)
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
            self.assertIs(report["contains_synthetic_media"], True)
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

            script = sample_script()
            result = asyncio.run(service.produce_video(
                script, prepared_audio_paths=[str(audio), str(audio)],
            ))

            self.assertTrue(result.success)
            service._editor.prepare_narration.assert_not_awaited()
            service._editor.validate_narration.assert_called_once_with([str(audio)] * 2, script)
            self.assertEqual(service._editor.compose_video.await_args.kwargs["audio_paths"], [str(audio)] * 2)
            service._editor.cleanup_temp_files.assert_not_called()
            self.assertTrue(audio.exists())

            editor = object.__new__(VideoEditor)
            editor._temp_files = []
            editor.logger = Mock()
            editor.cleanup_old_temp_files = Mock()
            editor._get_voice_for_mood = Mock(return_value="alloy")
            editor._normalize_narration_audio = Mock(return_value=str(audio))
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

    def test_card_subtitle_is_a_local_style_option(self):
        with self.assertRaisesRegex(ValueError, "subtitle_style"):
            VideoEditor(bgm_volume=0, subtitle_style="unknown")
        soft = VideoEditor(bgm_volume=0)._create_subtitle_clips(
            "드론은 잠깐 멈춰 새 지점을 검토했습니다.", 3,
        )
        with patch("shorts_maker.editor.video_editor.TextClip", wraps=TextClip) as text_clip:
            card = VideoEditor(bgm_volume=0, subtitle_style="card")._create_subtitle_clips(
                "드론은 잠깐 멈춰 새 지점을 검토했습니다.", 3,
            )
        self.assertEqual(text_clip.call_args.kwargs["horizontal_align"], "left")
        try:
            self.assertEqual(card[0].w, 940)
            self.assertGreater(card[0].h, soft[0].h)
            self.assertEqual(card[0].get_frame(0.1).shape[1], 940)
        finally:
            for clip in soft + card:
                clip.close()

    def test_caption_segments_reveal_without_early_payoff(self):
        text = "드론이 새 지점을 찾았습니다. 하던 임무는 멈춰야 할까요?"
        segments = VideoEditor._caption_segments(text, 4.0)
        self.assertEqual([part for part, _, _ in segments], [
            "드론이 새 지점을 찾았습니다.", "하던 임무는 멈춰야 할까요?",
        ])
        self.assertEqual(segments[0][1], 0)
        self.assertGreater(segments[1][1], 0)
        self.assertAlmostEqual(segments[-1][1] + segments[-1][2], 4.0)
        self.assertTrue(all(length > 0 for _, _, length in segments))

        widow = "AI가 사람의 우선순위에 맞춰 팀을 재배치한 겁니다. 아직은 지구 시험이죠."
        phrases = [part for part, _, _ in VideoEditor._caption_segments(widow, 5.38)]
        self.assertEqual(phrases[0:2], ["AI가 사람의 우선순위에 맞춰 팀을", "재배치한 겁니다."])
        self.assertNotIn("겁니다.", phrases)
        short_previous = "가나다라마바사아자차카타파하 가나다라마바사 겁니다."
        phrases = [part for part, _, _ in VideoEditor._caption_segments(short_previous, 3.0)]
        self.assertEqual(phrases, [short_previous])

    def test_korean_subtitle_keeps_punctuation_with_word(self):
        text = "올여름 NASA 팀은 드론 한 대와 로버 두 대의 협업을 시험했습니다."
        wrapped = VideoEditor._wrap_subtitle(text, "AppleGothic", 60)
        self.assertGreater(len(wrapped.splitlines()), 1)
        self.assertEqual(wrapped.replace("\n", " "), text)
        self.assertNotIn("\n.", wrapped)
        self.assertEqual(
            VideoEditor._wrap_subtitle("AI가 사람의 우선순위에 맞춰 팀을", "AppleGothic", 60),
            "AI가 사람의 우선순위에\n맞춰 팀을",
        )
        self.assertEqual(
            VideoEditor._wrap_subtitle("2026년 버지니아에서 NASA는 드론 한 대와",
                                        "/System/Library/Fonts/AppleSDGothicNeo.ttc", 54),
            "2026년 버지니아에서 NASA는\n드론 한 대와",
        )

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
