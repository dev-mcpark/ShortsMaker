"""Regression checks for production and local data boundaries."""

import asyncio
import importlib
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from moviepy import ColorClip, VideoFileClip

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.content_enricher import ContentEnricher
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.character_overlay import CharacterOverlay
from shorts_maker.utils.character_video_generator import CharacterVideoGenerator
from shorts_maker.utils.config import PROJECT_ROOT, _find_project_root, settings
from shorts_maker.utils.scheduler import ScheduleManager
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter


class ReviewRegressions(unittest.TestCase):
    def test_project_root_does_not_depend_on_launch_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("shorts_maker.utils.config.Path.cwd", return_value=Path(directory)):
                self.assertEqual(_find_project_root(), PROJECT_ROOT)

    def test_source_category_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = object.__new__(SourceManager)
            manager.filepath = Path(directory) / "sources.json"
            manager.save_sources({"Tech": ["https://example.com/feed"]})

            manager.remove_category("Tech")

            self.assertEqual(manager.load_sources(), {})

    def test_corrupt_sources_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = object.__new__(SourceManager)
            manager.filepath = Path(directory) / "sources.json"
            manager.filepath.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                manager.add_source("Tech", "https://example.com/feed")
            self.assertEqual(manager.filepath.read_text(encoding="utf-8"), "{broken")

    def test_private_rss_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = object.__new__(SourceManager)
            manager.filepath = Path(directory) / "sources.json"
            with self.assertRaises(ValueError):
                manager.add_source("Tech", "http://127.0.0.1/feed")
            self.assertFalse(manager.filepath.exists())

    def test_failed_source_replace_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = object.__new__(SourceManager)
            manager.filepath = Path(directory) / "sources.json"
            manager.filepath.write_text('{"Tech": []}', encoding="utf-8")
            with patch("shorts_maker.utils.source_manager.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    manager.save_sources({"News": []})
            self.assertEqual(manager.filepath.read_text(encoding="utf-8"), '{"Tech": []}')

    def test_scheduler_can_restart_after_stop(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as directory:
                manager = ScheduleManager(str(Path(directory) / "schedules.json"))
                manager.start_scheduler()
                manager.stop_scheduler()
                manager.start_scheduler()
                self.assertTrue(manager._scheduler_running)
                manager.stop_scheduler()

        asyncio.run(exercise())

    def test_corrupt_schedule_does_not_leave_scheduler_running(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "schedules.json"
                path.write_text("{broken", encoding="utf-8")
                manager = ScheduleManager(str(path))
                with self.assertRaises(ValueError):
                    manager.start_scheduler()
                self.assertFalse(manager._scheduler_running)

        asyncio.run(exercise())

    def test_schedule_save_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(directory)
            with self.assertRaises(OSError):
                manager.save_schedules([])

    def test_corrupt_schedules_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedules.json"
            path.write_text("{broken", encoding="utf-8")
            manager = ScheduleManager(str(path))
            with self.assertRaises(ValueError):
                manager.create_schedule("Daily", "09:00")
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_invalid_schedule_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedules.json"
            manager = ScheduleManager(str(path))
            with self.assertRaises(ValueError):
                manager.create_schedule("Broken", "25:99")
            self.assertFalse(path.exists())

    def test_billing_disabled_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Pilot", "09:00")
            failed = ProductionService()._failed_result("403 BILLING_DISABLED: verbose provider details")
            self.assertNotIn("verbose provider details", failed.error)
            with patch("shorts_maker.services.production_service.ProductionService.full_pipeline",
                       new_callable=AsyncMock, return_value=failed):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "billing_disabled")

    def test_enabled_image_overlay_changes_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            background = Path(directory) / "background.png"
            character = Path(directory) / "character.png"
            output = Path(directory) / "combined.png"
            Image.new("RGB", (40, 40), "white").save(background)
            Image.new("RGBA", (10, 10), "red").save(character)
            overlay = CharacterOverlay(str(character), position="top_left", size_ratio=0.25)

            result = overlay.composite_on_image(str(background), str(output))

            self.assertEqual(result, str(output))
            with Image.open(output) as image:
                self.assertEqual(image.getpixel((5, 5))[:3], (255, 0, 0))

    def test_enabled_video_overlay_changes_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            background = Path(directory) / "background.mp4"
            character = Path(directory) / "character.png"
            output = Path(directory) / "combined.mp4"
            Image.new("RGBA", (10, 10), "red").save(character)
            clip = ColorClip(size=(40, 40), color=(255, 255, 255), duration=0.5)
            clip.write_videofile(str(background), fps=2, codec="libx264", audio=False, logger=None)
            clip.close()

            result = CharacterOverlay(
                str(character), position="top_left", size_ratio=0.25,
                chroma_key_enabled=False,
            ).composite_on_video(str(background), str(output))

            self.assertEqual(result, str(output))
            with VideoFileClip(result) as video:
                red, green, _ = video.get_frame(0.1)[5, 5]
                self.assertGreater(red, 200)
                self.assertLess(green, 50)

    def test_generation_failure_does_not_return_mock_media(self):
        generator = object.__new__(VideoGenerator)
        generator.image_client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(side_effect=RuntimeError("GenAI unavailable")),
        ))
        generator.logger = Mock()
        generator._create_mock_image = Mock(return_value="placeholder.png")

        with self.assertRaisesRegex(RuntimeError, "GenAI"):
            asyncio.run(generator._generate_image_gemini(SimpleNamespace(
                scene_number=1, visual_description="A vertical image",
            )))

        generator._create_mock_image.assert_not_called()

    def test_gemini_image_request_uses_vertical_1k_output(self):
        generator = object.__new__(VideoGenerator)
        image = SimpleNamespace(save=Mock())
        part = SimpleNamespace(as_image=Mock(return_value=image))
        generator.image_client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(return_value=SimpleNamespace(candidates=[
                SimpleNamespace(content=SimpleNamespace(parts=[part])),
            ])),
        ))
        scene = SimpleNamespace(visual_description="A vertical landscape")
        generator._run_image_generation("gemini-3.1-flash-lite-image", scene, "scene.png")

        image.save.assert_called_once_with("scene.png")
        request = generator.image_client.models.generate_content.call_args.kwargs
        self.assertEqual(request["contents"], scene.visual_description)
        self.assertEqual(request["config"].image_config.aspect_ratio, "9:16")
        self.assertEqual(request["config"].image_config.image_size, "1K")

    def test_veo_polling_stops_after_bounded_wait(self):
        generator = object.__new__(VideoGenerator)
        operation = SimpleNamespace(done=False)
        generator.client = SimpleNamespace(
            models=SimpleNamespace(generate_videos=Mock(return_value=operation)),
            operations=SimpleNamespace(get=Mock(return_value=operation)),
        )
        generator.logger = Mock()
        with patch("shorts_maker.generator.video_generator.time.sleep"):
            with self.assertRaises(TimeoutError):
                generator._retry_veo_call("model", "prompt", "unused.mp4", "fallback")
        generator.client.models.generate_videos.assert_called_once()
        self.assertFalse(generator.client.models.generate_videos.call_args.kwargs["config"]["generate_audio"])

        character_generator = object.__new__(CharacterVideoGenerator)
        character_generator.client = SimpleNamespace(
            models=SimpleNamespace(generate_videos=Mock(return_value=operation)),
            operations=SimpleNamespace(get=Mock(return_value=operation)),
        )
        character_generator.logger = Mock()
        with patch("shorts_maker.utils.character_video_generator.time.sleep"):
            self.assertFalse(character_generator._run_veo_generation(
                "model", "prompt", object(), "unused.mp4", 6,
            ))
        character_generator.client.models.generate_videos.assert_called_once()

    def test_scene_error_stops_before_editing(self):
        service = ProductionService(mode="image")
        generator = SimpleNamespace(
            generate_scene_clip=AsyncMock(side_effect=RuntimeError("api unavailable")),
            create_fallback_image=Mock(),
        )
        service._generator = generator
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1, visual_description="scene")])
        with patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(service.produce_video(script))

        self.assertFalse(result.success)
        self.assertIn("api unavailable", result.error)
        generator.create_fallback_image.assert_not_called()
        self.assertIsNone(service._editor)

    def test_invalid_visual_does_not_become_black_video(self):
        editor = object.__new__(VideoEditor)
        editor.logger = Mock()
        with patch("shorts_maker.editor.video_editor.VideoFileClip", side_effect=OSError("bad video")):
            with patch("moviepy.ColorClip"):
                with self.assertRaisesRegex(OSError, "bad video"):
                    editor._create_visual_clip("bad.mp4", 1)
        with self.assertRaises(ValueError):
            editor._create_visual_clip("unknown.txt", 1)

    def test_brave_search_does_not_block_event_loop(self):
        enricher = object.__new__(ContentEnricher)
        enricher.logger = Mock()
        enricher.search_api_key = "test-key"
        request_thread = []

        def fake_get(*args, **kwargs):
            request_thread.append(threading.get_ident())
            return SimpleNamespace(status_code=200, json=lambda: {"web": {"results": []}})

        with patch("shorts_maker.planner.content_enricher.requests.get", side_effect=fake_get):
            asyncio.run(enricher._search_web_brave("topic"))

        self.assertNotEqual(request_thread, [threading.get_ident()])

    def test_malformed_script_cannot_reach_video_workflow(self):
        with self.assertRaises(ValueError):
            VideoScene(scene_number=1, visual_description="visual", script_text="words", duration_seconds=0)
        with self.assertRaises(ValueError):
            VideoScene(scene_number=1, visual_description="  ", script_text="words")
        with self.assertRaises(ValueError):
            ShortsScript(
                title="title", description="desc", tags=[], mood="calm", style="news",
                source_name="source", source_url="https://example.com", generation_mode="image",
                scenes=[],
            )

    def test_script_validator_enforces_objective_limits(self):
        validator = object.__new__(ScriptValidator)
        validator.logger = Mock()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())])
        validator.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=response)
        )))
        script = SimpleNamespace(
            title="title", scenes=[SimpleNamespace(duration_seconds=5)],
            model_dump_json=lambda **_: "{}",
        )
        for score, duration in [(42, 5), (90, 70)]:
            response.choices[0].message.content = f'{{"is_valid": true, "score": {score}}}'
            script.scenes[0].duration_seconds = duration
            self.assertFalse(asyncio.run(validator.validate_script(script)).is_valid)
        response.choices[0].message.content = '{"is_valid": true, "score": 90, "reason": "advertising_content"}'
        script.scenes[0].duration_seconds = 5
        self.assertFalse(asyncio.run(validator.validate_script(script)).is_valid)

    def test_source_excerpt_reaches_validator_as_untrusted_data(self):
        validator = object.__new__(ScriptValidator)
        validator.logger = Mock()
        completion = AsyncMock(return_value=SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=(
                '{"is_valid": true, "score": 90, "reason": "unsupported_claim", '
                '"feedback": "30% increase is absent from source"}'
            ))),
        ]))
        validator.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=completion),
        ))
        script = ShortsScript(
            title="30% increase", description="", tags=[], mood="calm", style="news",
            source_name="source", source_url="https://example.com", generation_mode="image",
            scenes=[VideoScene(scene_number=1, visual_description="factory", script_text="30% increase")],
        )
        result = asyncio.run(validator.validate_script(script, source_text="The factory expanded."))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.reason, "unsupported_claim")
        request = completion.await_args.kwargs["messages"]
        self.assertIn("Source grounding", request[0]["content"])
        self.assertIn("The factory expanded.", request[1]["content"])
        self.assertIn("30% increase", request[1]["content"])

    def test_planner_requires_source_before_approving_script(self):
        script = ShortsScript(
            title="Factory", description="", tags=[], mood="calm", style="news",
            source_name="source", source_url="https://example.com", generation_mode="image",
            scenes=[VideoScene(scene_number=1, visual_description="factory", script_text="The factory expanded")],
        )
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.validator = SimpleNamespace(validate_script=AsyncMock(return_value=SimpleNamespace(is_valid=True)))
        with tempfile.TemporaryDirectory() as directory:
            planner.script_output_dir = directory
            self.assertIsNone(asyncio.run(planner._validate_and_save(script, {"content": "  "})))
            planner.validator.validate_script.assert_not_awaited()
            self.assertIs(asyncio.run(planner._validate_and_save(
                script, {"content": "The factory expanded."},
            )), script)
        planner.validator.validate_script.assert_awaited_once_with(
            script, source_text="The factory expanded.",
        )

    def test_subtitle_failure_is_not_silently_accepted(self):
        editor = object.__new__(VideoEditor)
        editor.logger = Mock()
        editor.subtitle_size = 60
        editor.subtitle_color = "white"
        with patch("shorts_maker.editor.video_editor.TextClip", side_effect=OSError("font unavailable")):
            with self.assertRaisesRegex(OSError, "font unavailable"):
                editor._create_subtitle_clips("caption", 1)

    def test_clip_directory_cannot_escape_storage_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(settings, "clips_dir", Path(directory) / "clips"):
                with self.assertRaises(ValueError):
                    VeoPromptExporter().get_clips_dir("../escape")

    def test_failed_clip_replace_preserves_previous_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(settings, "clips_dir", Path(directory)):
                exporter = VeoPromptExporter()
                path = exporter.get_clip_path("script", 1)
                path.write_bytes(b"old video")
                with patch("shorts_maker.utils.veo_prompt_exporter.os.replace", create=True,
                           side_effect=OSError("disk error")):
                    with self.assertRaises(OSError):
                        exporter.save_uploaded_clip(b"new video", "script", 1)
                self.assertEqual(path.read_bytes(), b"old video")

    def test_manual_script_ids_are_unique(self):
        exporter = VeoPromptExporter()
        script = SimpleNamespace(title="Same title")
        self.assertNotEqual(exporter.get_script_id(script), exporter.get_script_id(script))

    def test_character_video_passes_selected_duration_and_image_type(self):
        with tempfile.TemporaryDirectory() as directory:
            character = Path(directory) / "character.jpg"
            output = Path(directory) / "character.mp4"
            Image.new("RGB", (10, 10), "blue").save(character)
            generator = object.__new__(CharacterVideoGenerator)
            generator.client = object()
            generator.logger = Mock()

            def generate(*args):
                output.write_bytes(b"video")
                return True

            generator._run_veo_generation = Mock(side_effect=generate)
            result = asyncio.run(generator.generate_speaking_video(
                str(character), str(output), duration_seconds=6,
            ))

            self.assertEqual(result, str(output))
            self.assertEqual(generator._run_veo_generation.call_args.args[2].mime_type, "image/jpeg")
            self.assertEqual(generator._run_veo_generation.call_args.args[-1], 6)

    def test_manual_generation_helper_accepts_saved_script(self):
        helper = importlib.import_module("test_generation")
        script = ShortsScript(
            title="title", description="desc", tags=[], mood="calm", style="news",
            source_name="source", source_url="https://example.com", generation_mode="image",
            scenes=[VideoScene(scene_number=1, visual_description="visual", script_text="words")],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.json"
            path.write_text(script.model_dump_json(), encoding="utf-8")
            loaded = helper.load_script(str(path))
            with patch.object(helper, "VideoGenerator") as generator_class:
                generator_class.return_value.generate_clips = AsyncMock(return_value=[])
                asyncio.run(helper.test_single_scene_generation(loaded))

        produced_script = generator_class.return_value.generate_clips.call_args.args[0]
        self.assertIsInstance(produced_script, ShortsScript)
        self.assertEqual(len(produced_script.scenes), 1)


if __name__ == "__main__":
    unittest.main()
