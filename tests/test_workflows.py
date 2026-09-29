"""Offline checks for the paths that select paid or manual generation."""

import asyncio
import importlib
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.planner.models import ScriptGenerationContext, TopicCandidate
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services.production_service import ProductionService
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
            service = ProductionService(mode="video")
            editor = SimpleNamespace(compose_video=AsyncMock(return_value=str(output)))
            service._editor = editor
            script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])

            result = asyncio.run(
                service.produce_video(script, manual_clip_paths={1: "clip.mp4"})
            )

        self.assertTrue(result.success)
        self.assertEqual(result.clips, ["clip.mp4"])
        self.assertIsNone(service._generator)
        editor.compose_video.assert_awaited_once_with(["clip.mp4"], script)

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

    def test_parallel_failure_keeps_scene_order(self):
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
            paths = asyncio.run(generator._generate_clips_parallel(SimpleNamespace(scenes=scenes)))

        self.assertEqual(paths, ["temp/error_scene_1.png", "scene_2.png"])
        generator._create_mock_image.assert_called_once_with("temp/error_scene_1.png")

    def test_rejected_script_is_not_returned(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = get_logger(__name__)
        candidate = {"title": "Topic", "category": "Tech", "url": "https://example.com"}
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=8, reason="test", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=None))
        planner._save_history = Mock()
        planner._write_script = AsyncMock(return_value=object())
        planner._validate_and_save = AsyncMock(return_value=None)

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))

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


if __name__ == "__main__":
    unittest.main()
