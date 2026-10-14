"""Regression checks for production and local data boundaries."""

import asyncio
import httpx
import importlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from openai import RateLimitError
from PIL import Image
from moviepy import ColorClip, VideoFileClip

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.content_enricher import ContentEnricher
from shorts_maker.planner.content_analyzer import ContentAnalyzer
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
    def setUp(self):
        paid = patch.object(settings, "paid_production_enabled", True)
        paid.start()
        self.addCleanup(paid.stop)
        budget = patch.object(settings, "google_monthly_budget_krw", None)
        budget.start()
        self.addCleanup(budget.stop)

    def test_planning_openai_clients_have_no_hidden_sdk_retries(self):
        with patch.object(settings, "openai_api_key", "test-key"):
            planner = ScriptPlanner()
        clients = [
            planner.client, planner.validator.client,
            planner.content_analyzer.client, planner.content_enricher.client,
        ]
        self.assertEqual([client.max_retries for client in clients], [0, 0, 0, 0])

        async def close_clients():
            await asyncio.gather(*(client.close() for client in clients))

        asyncio.run(close_clients())

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
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failed,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "billing_disabled")

    def test_provider_limit_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            for error in ("429 RESOURCE_EXHAUSTED", "RESOURCE_EXHAUSTED"):
                schedule = manager.create_schedule("Pilot", "09:00")
                failure = ProductionService()._failed_result(error)
                with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                    "shorts_maker.services.production_service.ProductionService.full_pipeline",
                    new_callable=AsyncMock, return_value=failure,
                ):
                    asyncio.run(manager._execute_pipeline(schedule))
                stored = manager.get_schedule(schedule["id"])
                self.assertFalse(stored["enabled"])
                self.assertEqual(stored["last_result"], "provider_limit")
                self.assertEqual(stored["run_count"], 1)

            schedule = manager.create_schedule("Thrown", "10:00")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, side_effect=RuntimeError("429 provider error"),
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "provider_limit")
            self.assertEqual(stored["run_count"], 1)

            schedule = manager.create_schedule("Transient", "11:00")
            failure = ProductionService()._failed_result("503 temporary server error")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failure,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            self.assertTrue(manager.get_schedule(schedule["id"])["enabled"])

    def test_completed_veo_without_video_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Veo pilot", "09:00")
            failure = ProductionService()._failed_result("VEO_RESULT_UNVERIFIED: no verified video")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failure,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "veo_result_unverified")
            self.assertEqual(stored["run_count"], 1)

            raised = manager.create_schedule("Thrown Veo", "10:00")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, side_effect=RuntimeError("VEO_RESULT_UNVERIFIED"),
            ):
                asyncio.run(manager._execute_pipeline(raised))
            self.assertFalse(manager.get_schedule(raised["id"])["enabled"])
            self.assertEqual(manager.get_schedule(raised["id"])["last_result"], "veo_result_unverified")

    def test_google_budget_limit_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Budgeted pilot", "09:00")
            failure = ProductionService()._failed_result("GOOGLE_BUDGET_EXCEEDED: limit reached")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failure,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "google_budget_exceeded")

    def test_impossible_visual_cap_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Too costly", "09:00")
            failure = ProductionService()._failed_result("VISUAL_COST_CAP_EXCEEDED: minimum round")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failure,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "visual_cost_cap_exceeded")

    def test_unsupported_music_mood_pauses_repeating_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Music review", "09:00")
            failure = ProductionService()._failed_result("BGM_SELECTION_REQUIRED: unsupported mood")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failure,
            ):
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "music_selection_required")

    def test_unsupported_music_mood_stops_pipeline_before_media(self):
        service = ProductionService(editor_options={"bgm_volume": 0})
        service._planner = SimpleNamespace(plan_content=AsyncMock(
            side_effect=ValueError("BGM_SELECTION_REQUIRED: unsupported mood"),
        ))
        service.produce_video = AsyncMock()
        result = asyncio.run(service.full_pipeline())
        self.assertFalse(result.success)
        self.assertIn("BGM_SELECTION_REQUIRED", result.error)
        service.produce_video.assert_not_awaited()

    def test_planning_provider_limit_survives_pipeline_without_stale_errors(self):
        service = ProductionService(editor_options={"bgm_volume": 0})
        service._planner = SimpleNamespace(plan_content=AsyncMock(
            side_effect=RateLimitError("quota", response=httpx.Response(
                429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            ), body=None)
        ))
        result = asyncio.run(service.full_pipeline())
        self.assertFalse(result.success)
        self.assertEqual(result.error, "RESOURCE_EXHAUSTED: 공급자 제한으로 스크립트 생성 중단")
        service._planner.plan_content = AsyncMock(return_value=(None, None))
        result = asyncio.run(service.full_pipeline())
        self.assertEqual(result.error, "스크립트 생성 실패")

    def test_openai_limit_stops_optional_planning_stages(self):
        limited = RateLimitError("quota", response=httpx.Response(
            429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        ), body=None)
        completion = AsyncMock(side_effect=limited)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))

        with tempfile.TemporaryDirectory() as directory:
            planner = object.__new__(ScriptPlanner)
            planner.logger = Mock()
            planner.history_file = str(Path(directory) / "history.json")
            planner.client = client
            planner._fetch_rss_feeds = Mock(return_value=[{
                "category": "Tech", "title": "Topic", "url": "https://example.com/article",
            }])
            planner._write_script = AsyncMock()
            with self.assertRaises(RateLimitError):
                asyncio.run(planner.plan_content())
            planner._write_script.assert_not_awaited()

        analyzer = object.__new__(ContentAnalyzer)
        analyzer.logger = Mock()
        analyzer.model = "gpt-4o"
        analyzer.client = client
        article = SimpleNamespace(title="Topic", main_text="Source", quotes=[], headings=[], captions=[])
        with self.assertRaises(RateLimitError):
            asyncio.run(analyzer.analyze_content(article))

        enricher = object.__new__(ContentEnricher)
        enricher.logger = Mock()
        enricher.client = client
        with self.assertRaises(RateLimitError):
            asyncio.run(enricher._summarize_search_results("Topic", [
                {"title": "Result", "description": "Excerpt"},
            ]))

        validator = object.__new__(ScriptValidator)
        validator.logger = Mock()
        validator.client = client
        script = SimpleNamespace(title="Topic", model_dump_json=lambda **_: "{}")
        with self.assertRaises(RateLimitError):
            asyncio.run(validator.validate_script(script, source_text="Primary source"))

    def test_schedule_pauses_before_paid_planning_when_music_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Pilot", "09:00")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=False), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock,
            ) as pipeline:
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "music_missing")
            pipeline.assert_not_awaited()

            another = manager.create_schedule("Other mood", "10:00")
            failed = ProductionService()._failed_result("'sci-fi' 분위기의 사용 권한이 기록된 BGM이 없습니다")
            with patch("shorts_maker.utils.bgm_manager.BGMManager.has_documented_track", return_value=True), patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock, return_value=failed,
            ):
                asyncio.run(manager._execute_pipeline(another))
            self.assertFalse(manager.get_schedule(another["id"])["enabled"])

    def test_schedule_pauses_before_any_pipeline_when_paid_work_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScheduleManager(str(Path(directory) / "schedules.json"))
            schedule = manager.create_schedule("Pilot", "09:00")
            with patch.object(settings, "paid_production_enabled", False), patch(
                "shorts_maker.utils.bgm_manager.BGMManager.has_documented_track"
            ) as music, patch(
                "shorts_maker.services.production_service.ProductionService.full_pipeline",
                new_callable=AsyncMock,
            ) as pipeline:
                asyncio.run(manager._execute_pipeline(schedule))
            stored = manager.get_schedule(schedule["id"])
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["last_result"], "paid_production_disabled")
            music.assert_not_called()
            pipeline.assert_not_awaited()

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
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ), patch("shorts_maker.generator.video_generator.time.sleep"):
            with self.assertRaisesRegex(TimeoutError, "VEO_RESULT_UNVERIFIED"):
                generator._retry_veo_call(
                    "veo-3.1-lite-generate-001", "prompt", "unused.mp4", "fallback",
                    request_budget_usd=0.30,
                )
        generator.client.models.generate_videos.assert_called_once()
        self.assertFalse(generator.client.models.generate_videos.call_args.kwargs["config"]["generate_audio"])
        self.assertEqual(generator.client.models.generate_videos.call_args.kwargs["config"]["number_of_videos"], 1)

        character_generator = object.__new__(CharacterVideoGenerator)
        character_generator.client = SimpleNamespace(
            models=SimpleNamespace(generate_videos=Mock(return_value=operation)),
            operations=SimpleNamespace(get=Mock(return_value=operation)),
        )
        character_generator.logger = Mock()
        with patch("shorts_maker.utils.character_video_generator.time.sleep"):
            self.assertFalse(character_generator._run_veo_generation(
                settings.veo_model_id, "prompt", object(), "unused.mp4", 6,
            ))
        character_generator.client.models.generate_videos.assert_called_once()

    def test_veo_limit_stops_without_using_reserved_retries(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        request = Mock()
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        status_only = RuntimeError("quota")
        status_only.status_code = 429

        for error in (RuntimeError("RESOURCE_EXHAUSTED"), status_only):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory, patch.object(
                settings, "output_dir", Path(directory),
            ), patch(
                "shorts_maker.generator.video_generator.time.sleep"
            ) as sleep, patch.object(settings, "max_visual_cost_usd", 10):
                request.reset_mock(side_effect=True)
                request.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "RESOURCE_EXHAUSTED"):
                    generator._retry_veo_call(
                        settings.veo_model_id, "prompt", "unused.mp4", "fallback",
                        max_attempts=3, request_budget_usd=10,
                    )
                request.assert_called_once()
                sleep.assert_not_called()

    def test_completed_veo_code_8_stops_without_retry(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        operation = SimpleNamespace(
            done=True, result=None,
            error={"code": 8, "message": "The service is experiencing high load"},
            name="projects/example/operations/operation-id",
        )
        request = Mock(return_value=operation)
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ), patch("shorts_maker.generator.video_generator.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "RESOURCE_EXHAUSTED"):
                generator._retry_veo_call(
                    "veo-3.1-lite-generate-001", "prompt", "unused.mp4", "fallback",
                    duration_seconds=8, max_attempts=2, request_budget_usd=0.6,
                )
            path = next((Path(directory) / "evaluation/visual_attempts").glob("*.json"))
            record = json.loads(path.read_text(encoding="utf-8"))
        request.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(record["status"], "provider_limited")
        self.assertEqual(record["provider_error_code"], "8")

    def test_veo_keeps_explicit_retry_for_server_error(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        saved_video = Mock()
        operation = SimpleNamespace(
            done=True, result=SimpleNamespace(
                generated_videos=[SimpleNamespace(video=saved_video)]),
        )
        request = Mock(side_effect=[RuntimeError("503"), operation])
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        saved_video.save.side_effect = lambda path: Path(path).write_bytes(b"fake clip")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ), patch("shorts_maker.generator.video_generator.time.sleep") as sleep, patch.object(
            settings, "max_visual_cost_usd", 2,
        ):
            output = str(Path(directory) / "saved.mp4")
            generator._retry_veo_call(
                settings.veo_model_id, "prompt", output, "fallback",
                max_attempts=2, request_budget_usd=2,
            )
            records = [json.loads(path.read_text(encoding="utf-8")) for path in
                       (Path(directory) / "evaluation/visual_attempts").glob("*.json")]
            self.assertEqual(sorted(record["status"] for record in records),
                             ["failed_or_unknown", "saved"])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(30)
        saved_video.save.assert_called_once_with(output)

    def test_veo_internal_error_records_one_unbilled_attempt(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        operation = SimpleNamespace(
            done=True, result=None, error={"code": 13, "message": "Internal error"},
            name="projects/example/operations/operation-id",
        )
        request = Mock(return_value=operation)
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))

        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ):
            with self.assertRaisesRegex(RuntimeError, "VEO_RESULT_UNVERIFIED"):
                generator._retry_veo_call(
                    "veo-3.1-lite-generate-001", "private prompt", "unused.mp4", "fallback",
                    duration_seconds=8, scene_number=1, request_budget_usd=0.30,
                )
            paths = list((Path(directory) / "evaluation/visual_attempts").glob("*.json"))
            self.assertEqual(len(paths), 1)
            record = json.loads(paths[0].read_text(encoding="utf-8"))
        request.assert_called_once()
        self.assertEqual(record["status"], "failed_or_unknown")
        self.assertEqual(record["provider_error_code"], "13")
        self.assertEqual(record["operation_id"], "operation-id")
        self.assertEqual(record["estimated_output_usd"], 0.24)
        self.assertIsNone(record["actual_billed_usd"])
        self.assertNotIn("private prompt", json.dumps(record))

    def test_veo_first_frame_is_validated_and_audited_before_one_request(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        saved_video = Mock()
        saved_video.save.side_effect = lambda path: Path(path).write_bytes(b"clip")
        operation = SimpleNamespace(done=True, result=SimpleNamespace(
            generated_videos=[SimpleNamespace(video=saved_video)]),
        )
        request = Mock(return_value=operation)
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ), patch.object(settings, "max_visual_cost_usd", 0.30):
            frame = Path(directory) / "frame.png"
            Image.new("RGB", (720, 1280), "white").save(frame)
            output = str(Path(directory) / "clip.mp4")
            generator._retry_veo_call(
                "veo-3.1-lite-generate-001", "motion only", output, "fallback",
                duration_seconds=8, scene_number=1, first_frame_path=str(frame),
                request_budget_usd=0.30,
            )
            record = json.loads(next((Path(directory) / "evaluation/visual_attempts").glob(
                "*.json")).read_text(encoding="utf-8"))
            kwargs = request.call_args.kwargs
            self.assertEqual(kwargs["image"].image_bytes, frame.read_bytes())
            self.assertEqual(kwargs["image"].mime_type, "image/png")
            self.assertEqual(kwargs["config"]["number_of_videos"], 1)
            self.assertFalse(kwargs["config"]["generate_audio"])
            self.assertEqual(record["input_type"], "image_first_frame")
            self.assertEqual(record["estimated_output_usd"], 0.24)
            self.assertEqual(record["request_budget_usd"], 0.30)
            self.assertEqual(record["status"], "saved")
            self.assertEqual(len(record["input_image_sha256"]), 64)
            self.assertNotIn("motion only", json.dumps(record))

    def test_direct_veo_preflight_blocks_overspend_and_invalid_frame(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        request = Mock()
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "output_dir", Path(directory),
        ):
            frame = Path(directory) / "wrong.png"
            Image.new("RGB", (1280, 720), "white").save(frame)
            oversized = Path(directory) / "oversized.png"
            with oversized.open("wb") as file:
                file.seek(20_000_000)
                file.write(b"x")
            with patch.object(settings, "max_visual_cost_usd", 1):
                with self.assertRaisesRegex(ValueError, "요청 상한"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, request_budget_usd=0.20,
                    )
            with patch.object(settings, "max_visual_cost_usd", 0.20):
                with self.assertRaisesRegex(ValueError, "상한"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, first_frame_path=str(frame),
                        request_budget_usd=0.30,
                    )
            with patch.object(settings, "max_visual_cost_usd", 0.30):
                with self.assertRaisesRegex(ValueError, "예산 상한"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, first_frame_path=str(frame),
                    )
                with self.assertRaisesRegex(ValueError, "예산 상한"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, request_budget_usd=float("nan"),
                    )
                with self.assertRaisesRegex(ValueError, "20 MB"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, first_frame_path=str(oversized),
                        request_budget_usd=0.30,
                    )
                with self.assertRaisesRegex(ValueError, "상한"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, max_attempts=2, request_budget_usd=0.30,
                    )
                with self.assertRaisesRegex(ValueError, "세로 9:16"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=8, first_frame_path=str(frame),
                        request_budget_usd=0.30,
                    )
                with self.assertRaisesRegex(ValueError, "시도 횟수"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        max_attempts=0, request_budget_usd=0.30,
                    )
                with self.assertRaisesRegex(ValueError, "생성 길이"):
                    generator._retry_veo_call(
                        "veo-3.1-lite-generate-001", "motion", "unused.mp4", "fallback",
                        duration_seconds=5, request_budget_usd=0.30,
                    )
            self.assertFalse(list((Path(directory) / "evaluation").glob("**/*.json")))
            request.assert_not_called()

    def test_veo_does_not_call_provider_when_attempt_record_cannot_be_written(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        request = Mock()
        generator.client = SimpleNamespace(models=SimpleNamespace(generate_videos=request))
        with tempfile.TemporaryDirectory() as directory:
            occupied = Path(directory) / "occupied"
            occupied.write_text("not a directory", encoding="utf-8")
            with patch.object(settings, "output_dir", occupied):
                with self.assertRaises(OSError):
                    generator._retry_veo_call(
                        settings.veo_model_id, "prompt", "unused.mp4", "fallback",
                        request_budget_usd=1,
                    )
        request.assert_not_called()

    def test_veo_prompt_keeps_one_silent_shot_without_fake_quality_claims(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = Mock()
        generator.max_veo_attempts = 1
        generator._retry_veo_call = Mock()
        scene = SimpleNamespace(
            scene_number=1,
            visual_description="One drone above two rovers on a Virginia lawn",
            motion_instruction="The camera slowly pushes toward the fleet",
        )

        generator._run_veo_background_only("model", scene, "clip.mp4", 6)

        prompt = generator._retry_veo_call.call_args.args[1]
        self.assertIn("One continuous vertical shot", prompt)
        self.assertNotIn("9:16", prompt)
        self.assertIn(scene.visual_description, prompt)
        self.assertIn(scene.motion_instruction, prompt)
        self.assertIn("Silent background footage", prompt)
        self.assertNotIn("4K", prompt)
        self.assertNotIn("no people", prompt)

    def test_planner_visual_brief_requires_source_matched_setting(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.allowed_moods = ["calm"]
        planner.generation_mode = "hybrid"
        script = {
            "title": "드론 현장 시험", "description": "출처 NASA", "tags": [],
            "mood": "calm", "style": "The Info Curator", "source_name": "NASA",
            "music_direction": "조용한 호기심, 강한 드럼은 피함",
            "source_url": "https://example.com", "generation_mode": "hybrid",
            "scenes": [{"scene_number": 1, "visual_mode": "image",
                        "visual_description": "Illustrative robot diagram",
                        "script_text": "로봇 세 대가 함께 시험했습니다.",
                        "duration_seconds": 6}],
        }
        completion = AsyncMock(return_value=SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(script))),
        ]))
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=completion),
        ))

        source_text = "  Three robots were tested in Virginia. " + "A" * 5000 + "UNVERIFIED_TAIL"
        result = asyncio.run(planner._write_script({
            "category": "Tech", "title": "ASTRA field test",
            "content": source_text,
            "source": "NASA", "url": "https://example.com/source",
            "analysis": SimpleNamespace(
                core_message="Mars landing", hook="Mars landing", secret_mechanism="unverified",
                context_background="unverified", numbers_data=["unverified estimate"], expert_insights=[],
                future_impact="unverified", visual_keywords=[],
                story_structure={"opening": "Mars", "mystery": "Mars", "secret": "Mars", "impact": "Mars"},
            ),
            "enriched_info": ["Unverified search claim"],
        }))

        self.assertEqual(result.scenes[0].visual_mode, "image")
        self.assertEqual(result.music_direction, "조용한 호기심, 강한 드럼은 피함")
        prompt = completion.await_args.kwargs["messages"][0]["content"]
        self.assertIn("Music direction", prompt)
        self.assertIn("primary article's real location", prompt)
        self.assertIn("clearly illustrative diagram", prompt)
        self.assertIn("show its parts and their connection", prompt)
        self.assertIn("A mood shot, labels naming the parts", prompt)
        self.assertIn("a diagram promised for later editing do not supply this proof", prompt)
        self.assertIn("one coherent shot", prompt)
        self.assertIn("keep its before and resulting state visible", prompt)
        self.assertIn("source-supported dilemma, decision, and result", prompt)
        self.assertIn("Separate measured results from model projections", prompt)
        self.assertIn("STORY IDEAS FROM AN EARLIER MODEL PASS (NOT EVIDENCE)", prompt)
        self.assertIn("Include factual claims only when the primary source text above supports them", prompt)
        self.assertIn("Use these snippets as leads only", prompt)
        self.assertIn("Three robots were tested in Virginia.", prompt)
        self.assertNotIn("UNVERIFIED_TAIL", prompt)
        self.assertIn("Reveal what actually happened", prompt)
        self.assertNotIn("4k resolution", prompt.lower())
        self.assertNotIn("15%", prompt)

        legacy = script.copy()
        legacy.pop("music_direction")
        self.assertEqual(ShortsScript.model_validate(legacy).music_direction, "")

        script["mood"] = "curious"
        completion.return_value.choices[0].message.content = json.dumps(script)
        with self.assertRaisesRegex(ValueError, "BGM_SELECTION_REQUIRED"):
            asyncio.run(planner._write_script({
                "category": "Tech", "title": "ASTRA field test",
                "content": "Three robots were tested in Virginia.",
            }))

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
            self.assertFalse(asyncio.run(validator.validate_script(script, source_text="Test source.")).is_valid)
        response.choices[0].message.content = '{"is_valid": true, "score": 90, "reason": "advertising_content"}'
        script.scenes[0].duration_seconds = 5
        self.assertFalse(asyncio.run(validator.validate_script(script, source_text="Test source.")).is_valid)

    def test_empty_source_stops_script_and_validation_requests(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.generation_mode = "image"
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock()),
        ))
        self.assertIsNone(asyncio.run(planner._write_script({"title": "Draft", "content": "  "})))
        planner.client.chat.completions.create.assert_not_awaited()

        validator = object.__new__(ScriptValidator)
        validator.logger = Mock()
        validator.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock()),
        ))
        script = SimpleNamespace(title="Draft")
        result = asyncio.run(validator.validate_script(script, source_text="  "))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.reason, "insufficient_source")
        validator.client.chat.completions.create.assert_not_awaited()

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
        self.assertIn("Distinguish measured results from simulations", request[0]["content"])
        self.assertIn("The factory expanded.", request[1]["content"])
        self.assertIn("30% increase", request[1]["content"])

    def test_validator_rejects_visual_failure_reasons(self):
        validator = object.__new__(ScriptValidator)
        validator.logger = Mock()
        completion = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({
                "is_valid": True, "score": 90, "reason": "unsupported_visual",
                "feedback": "Scene 1 depicts a desert instead of Virginia",
            })),
        )]))
        validator.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=completion),
        ))
        script = ShortsScript(
            title="실험", description="", tags=[], mood="calm", style="news",
            source_name="NASA", source_url="https://example.com", generation_mode="image",
            scenes=[VideoScene(scene_number=1, visual_description="desert", script_text="지상 시험")],
        )

        for reason in ("unsupported_visual", "missing_visual_proof"):
            with self.subTest(reason=reason):
                source = "The field test took place in Virginia."
                if reason == "missing_visual_proof":
                    script.scenes[0].visual_description = "Decorative exterior of a bus depot"
                    script.scenes[0].script_text = "지상과 지하 1층은 차고지, 지하 2층은 빗물저류조입니다."
                    source = "The depot occupies the ground and basement 1; the reservoir is in basement 2."
                completion.return_value.choices[0].message.content = json.dumps({
                    "is_valid": True, "score": 90, "reason": reason,
                    "feedback": "Scene 1's visual fails the explanation",
                })
                result = asyncio.run(validator.validate_script(
                    script, source_text=source,
                ))
                self.assertFalse(result.is_valid)
                self.assertEqual(result.reason, reason)
                self.assertIn(script.scenes[0].visual_description,
                              completion.await_args.kwargs["messages"][1]["content"])
        prompt = completion.await_args.kwargs["messages"][0]["content"]
        self.assertIn("parts and connection", prompt)
        self.assertIn("diagram to be added in editing", prompt)
        self.assertIn("visible before, change, and resulting state", prompt)

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
