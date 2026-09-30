"""Offline checks for the paths that select paid or manual generation."""

import asyncio
import importlib
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ScriptGenerationContext, TopicCandidate
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services.production_service import ProductionPhase, ProductionResult, ProductionService
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter


class WorkflowTests(unittest.TestCase):
    def test_empty_manual_clips_do_not_start_paid_generation(self):
        service = ProductionService(mode="video")
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])

        result = asyncio.run(service.produce_video(script, manual_clip_paths={}))

        self.assertFalse(result.success)
        self.assertIn("씬 1", result.error)
        self.assertIsNone(service._generator)

    def test_manual_clips_reach_editor_without_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.touch()
            clip = Path(directory) / "clip.mp4"
            clip.touch()
            service = ProductionService(mode="video")
            editor = SimpleNamespace(compose_video=AsyncMock(return_value=str(output)))
            service._editor = editor
            script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])

            result = asyncio.run(
                service.produce_video(script, manual_clip_paths={1: str(clip)})
            )

        self.assertTrue(result.success)
        self.assertEqual(result.clips, [str(clip)])
        self.assertIsNone(service._generator)
        editor.compose_video.assert_awaited_once()
        self.assertEqual(editor.compose_video.await_args.args, ([str(clip)], script))
        self.assertTrue(callable(editor.compose_video.await_args.kwargs["progress_callback"]))

    def test_missing_manual_file_is_rejected_before_editing(self):
        service = ProductionService(mode="video")
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])

        result = asyncio.run(service.produce_video(script, manual_clip_paths={1: "/missing/clip.mp4"}))

        self.assertFalse(result.success)
        self.assertIn("클립 파일", result.error)
        self.assertIsNone(service._editor)
        self.assertEqual(service.progress.phase, ProductionPhase.FAILED)

    def test_session_options_reach_editor_and_parallel_generator(self):
        state = AppState(mode="image", tts_voice="nova", bgm_mood="cinematic")
        with patch.object(settings, "update_api_keys"):
            service = state.new_production_service(parallel_clips=True)
        self.assertIs(state.production_service, service)
        self.assertTrue(service.parallel_clips)
        with patch("shorts_maker.services.production_service.VideoEditor") as editor_class:
            service._get_editor()
        self.assertEqual(editor_class.call_args.kwargs["tts_voice"], "nova")
        self.assertEqual(editor_class.call_args.kwargs["bgm_mood"], "cinematic")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.touch()
            clips = [str(Path(directory) / f"{i}.png") for i in (1, 2)]
            for clip in clips:
                Path(clip).touch()
            generator = SimpleNamespace(generate_clips=AsyncMock(return_value=clips))
            service._generator = generator
            service._editor = SimpleNamespace(compose_video=AsyncMock(return_value=str(output)))
            script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=i) for i in (1, 2)])
            result = asyncio.run(service.produce_video(script))

        self.assertTrue(result.success)
        generator.generate_clips.assert_awaited_once_with(script, parallel=True)
        service._editor.compose_video.assert_awaited_once()
        self.assertEqual(service._editor.compose_video.await_args.args, (clips, script))

    def test_editor_rejects_mismatched_clips_before_processing(self):
        editor = object.__new__(VideoEditor)
        script = SimpleNamespace(scenes=[object(), object()])
        with self.assertRaisesRegex(ValueError, "씬 수와 클립 수"):
            asyncio.run(editor.compose_video(["one.png"], script))

    def test_editor_cleans_up_when_tts_fails(self):
        editor = object.__new__(VideoEditor)
        editor._temp_files = []
        editor.logger = Mock()
        editor.cleanup_old_temp_files = Mock()
        editor.cleanup_temp_files = Mock()
        editor._cleanup_clips = Mock()
        editor._get_voice_for_mood = Mock(return_value="alloy")
        editor._generate_tts = AsyncMock(side_effect=RuntimeError("tts failed"))
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1, script_text="Hello")])

        with self.assertRaisesRegex(RuntimeError, "tts failed"):
            asyncio.run(editor.compose_video(["scene.png"], script))

        editor._cleanup_clips.assert_called_once_with([])
        editor.cleanup_temp_files.assert_called_once()

    def test_editor_cancellation_skips_visual_processing(self):
        editor = object.__new__(VideoEditor)
        editor._temp_files = []
        editor.logger = Mock()
        editor.cleanup_old_temp_files = Mock()
        editor.cleanup_temp_files = Mock()
        editor._cleanup_clips = Mock()
        editor._get_voice_for_mood = Mock(return_value="alloy")
        editor._generate_tts = AsyncMock(return_value="audio.mp3")
        editor._create_visual_clip = Mock()
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1, script_text="Hello")])

        with self.assertRaisesRegex(RuntimeError, "취소"):
            asyncio.run(editor.compose_video(["scene.png"], script, is_cancelled=lambda: True))

        editor._create_visual_clip.assert_not_called()
        editor.cleanup_temp_files.assert_called_once()

    def test_full_pipeline_retains_work_after_upload_failure(self):
        service = ProductionService()
        script = SimpleNamespace(title="Title", description="Description", tags=[])
        service.generate_script = AsyncMock(return_value=(script, None))
        service.produce_video = AsyncMock(return_value=ProductionResult(
            success=True, video_path="video.mp4", clips=["scene.png"]
        ))
        service.upload_to_youtube = AsyncMock(return_value=ProductionResult(
            success=False, error="upload failed"
        ))

        result = asyncio.run(service.full_pipeline(auto_upload=True))

        self.assertFalse(result.success)
        self.assertIs(result.script, script)
        self.assertEqual(result.video_path, "video.mp4")
        self.assertEqual(result.clips, ["scene.png"])

    def test_full_pipeline_completes_only_after_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "scene.png"
            clip.touch()
            output = Path(directory) / "output.mp4"
            output.touch()
            service = ProductionService(mode="image")
            script = SimpleNamespace(
                title="Title", description="Description", tags=[],
                scenes=[SimpleNamespace(scene_number=1, visual_description="Visual")],
            )
            service.generate_script = AsyncMock(return_value=(script, None))
            service._generator = SimpleNamespace(generate_scene_clip=AsyncMock(return_value=str(clip)))
            service._editor = SimpleNamespace(compose_video=AsyncMock(return_value=str(output)))
            service._uploader = SimpleNamespace(upload=AsyncMock(return_value="video-id"))
            phases = []
            service.set_progress_callback(lambda progress: phases.append(progress.phase))

            with patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock) as delay:
                result = asyncio.run(service.full_pipeline(auto_upload=True))
            delay.assert_not_awaited()

        self.assertTrue(result.success)
        self.assertIn(ProductionPhase.UPLOADING, phases)
        self.assertEqual(phases[-1], ProductionPhase.COMPLETED)
        self.assertNotIn(ProductionPhase.COMPLETED, phases[:phases.index(ProductionPhase.UPLOADING)])

    def test_upload_failure_sets_failed_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.touch()
            service = ProductionService()
            service._uploader = SimpleNamespace(upload=AsyncMock(return_value=None))

            result = asyncio.run(service.upload_to_youtube(str(output), {"title": "Title"}))

        self.assertFalse(result.success)
        self.assertEqual(service.progress.phase, ProductionPhase.FAILED)

    def test_cancelled_run_does_not_start_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.touch()
            service = ProductionService()
            uploader = SimpleNamespace(upload=AsyncMock(return_value="video-id"))
            service._uploader = uploader
            service.cancel()

            result = asyncio.run(service.upload_to_youtube(str(output), {"title": "Title"}))

        self.assertFalse(result.success)
        self.assertEqual(service.progress.phase, ProductionPhase.FAILED)
        uploader.upload.assert_not_awaited()

    def test_editor_progress_is_reported_when_work_occurs(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "scene.png"
            clip.touch()
            output = Path(directory) / "output.mp4"
            output.touch()
            service = ProductionService()
            async def compose(*args, progress_callback, is_cancelled):
                progress_callback(50, "씬 편집 중")
                return str(output)

            service._editor = SimpleNamespace(compose_video=AsyncMock(side_effect=compose))
            script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])
            seen = []
            service.set_progress_callback(lambda progress: seen.append((progress.phase, progress.progress_percent)))

            result = asyncio.run(service.produce_video(script, manual_clip_paths={1: str(clip)}))

        self.assertTrue(result.success)
        self.assertEqual(next(percent for phase, percent in seen if phase == ProductionPhase.EDITING), 0)
        self.assertIn((ProductionPhase.EDITING, 50), seen)
        self.assertNotIn((ProductionPhase.EDITING, 60), seen)
        self.assertNotIn((ProductionPhase.EDITING, 80), seen)

    def test_uploaded_clips_are_recovered_from_disk(self):
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])
        exporter = VeoPromptExporter()
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "clips_dir", Path(directory)):
            self.assertIsNone(exporter.get_ready_clip_paths(script, "script"))
            path = exporter.save_uploaded_clip(b"video", "script", 1)
            self.assertEqual(
                exporter.get_ready_clip_paths(script, "script"), {1: str(path)}
            )

    def test_generator_keeps_mode_specific_paths(self):
        generator = object.__new__(VideoGenerator)
        generator.mode = "video"
        generator.character_overlay = None
        generator._generate_background_video = AsyncMock(return_value="background.mp4")
        generator._generate_image_imagen = AsyncMock(return_value="image.png")
        scene = SimpleNamespace(scene_number=1)

        self.assertEqual(asyncio.run(generator.generate_scene_clip(scene)), "background.mp4")
        generator.mode = "image"
        self.assertEqual(asyncio.run(generator.generate_scene_clip(scene)), "image.png")
        generator._generate_background_video.assert_awaited_once_with(scene)
        generator._generate_image_imagen.assert_awaited_once_with(scene)

    def test_sequential_generation_waits_only_between_scenes(self):
        generator = object.__new__(VideoGenerator)
        generator.generate_scene_clip = AsyncMock(side_effect=["scene_1.png", "scene_2.png"])
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=i) for i in (1, 2)])

        with patch("shorts_maker.generator.video_generator.asyncio.sleep", new_callable=AsyncMock) as delay:
            result = asyncio.run(generator._generate_clips_sequential(script))

        self.assertEqual(result, ["scene_1.png", "scene_2.png"])
        delay.assert_awaited_once_with(settings.scene_buffer_seconds)

    def test_parallel_failure_does_not_create_publishable_placeholder(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = get_logger(__name__)
        generator.max_concurrent = 2
        generator._create_mock_image = Mock()
        scenes = [SimpleNamespace(scene_number=1), SimpleNamespace(scene_number=2)]

        async def generate(scene):
            if scene.scene_number == 1:
                raise RuntimeError("generation failed")
            return "scene_2.png"

        generator.generate_scene_clip = generate
        with patch("shorts_maker.generator.video_generator.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                asyncio.run(generator._generate_clips_parallel(SimpleNamespace(scenes=scenes)))

        generator._create_mock_image.assert_not_called()

    def test_rejected_script_is_not_returned(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = get_logger(__name__)
        candidate = {"title": "Topic", "category": "Tech", "url": "https://example.com"}
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=8, reason="test", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=None))
        planner._save_history = Mock()
        planner._write_script = AsyncMock(return_value=object())
        planner._validate_and_save = AsyncMock(return_value=None)

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._save_history.assert_not_called()

    def test_valid_script_is_recorded_after_validation(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidate = {"title": "Topic", "category": "Tech", "url": "https://example.com"}
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=8, reason="test", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=None))
        planner._write_script = AsyncMock(return_value=object())
        validated = object()
        planner._validate_and_save = AsyncMock(return_value=validated)
        planner._save_history = Mock()

        result, _ = asyncio.run(planner.plan_content())

        self.assertIs(result, validated)
        planner._save_history.assert_called_once_with("Topic", "https://example.com")

    def test_empty_feed_does_not_invent_a_topic(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner._fetch_rss_feeds = Mock(return_value=[])
        planner._score_topics = AsyncMock()

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_not_awaited()

    def test_private_rss_article_is_not_downloaded(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        item = {"title": "Internal", "category": "Tech", "url": "http://127.0.0.1/private"}
        planner._fetch_rss_feeds = Mock(return_value=[item])
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=item, score=9, reason="test", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock())

        with patch.object(settings, "max_topic_retries", 1):
            self.assertEqual(asyncio.run(planner.plan_content()), (None, None))

        planner.content_extractor.fetch_enhanced_article.assert_not_called()

    def test_rss_redirect_to_private_address_is_not_followed(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"Tech": ["https://example.com/feed"]}
        planner.rss_cache = SimpleNamespace(get=Mock(return_value=None), set=Mock())
        planner._load_url_history = Mock(return_value=[])
        redirect = SimpleNamespace(
            is_redirect=True, headers={"location": "http://127.0.0.1/private"}
        )

        with patch("shorts_maker.planner.script_planner.httpx", create=True) as httpx_client:
            httpx_client.get.return_value = redirect
            with patch("shorts_maker.planner.script_planner.feedparser.parse") as parse:
                parse.return_value = SimpleNamespace(entries=[], feed={})
                planner._fetch_rss_feeds()

        httpx_client.get.assert_called_once()

    def test_regeneration_limit_counts_failed_attempts(self):
        service = ProductionService()
        planner = SimpleNamespace(regenerate=AsyncMock(return_value=None))
        service._planner = planner
        context = ScriptGenerationContext(source_item={"title": "Topic"}, max_attempts=1)

        self.assertIsNone(asyncio.run(service.regenerate_script(context, "try again")))
        self.assertIsNone(asyncio.run(service.regenerate_script(context, "try again")))
        self.assertEqual(context.attempt_count, 1)
        planner.regenerate.assert_awaited_once()

    def test_installed_command_has_a_server_entrypoint(self):
        project = Path(__file__).resolve().parents[1]
        with (project / "pyproject.toml").open("rb") as file:
            target = tomllib.load(file)["project"]["scripts"]["shorts-maker"]
        module_name, function_name = target.split(":")

        module = importlib.import_module(module_name)
        self.assertEqual(function_name, "run")
        with patch.object(module.ui, "run") as run_server:
            getattr(module, function_name)()
        self.assertEqual(run_server.call_args.kwargs["port"], 8080)
        self.assertEqual(run_server.call_args.kwargs["host"], "127.0.0.1")
        self.assertNotEqual(
            run_server.call_args.kwargs["storage_secret"],
            "shortsmaker_secret_key_change_in_production",
        )


if __name__ == "__main__":
    unittest.main()
