"""Offline checks for the paths that select paid or manual generation."""

import asyncio
import importlib
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.gui.components.planning_tab import estimate_new_visual_cost
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ScriptGenerationContext, TopicCandidate
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services.production_service import ProductionPhase, ProductionResult, ProductionService
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        paid = patch.object(settings, "paid_production_enabled", True)
        paid.start()
        self.addCleanup(paid.stop)
        budget = patch.object(settings, "google_monthly_budget_krw", None)
        budget.start()
        self.addCleanup(budget.stop)

    def test_script_preview_uses_selected_visual_mode_and_model_duration(self):
        script = SimpleNamespace(scenes=[
            SimpleNamespace(visual_mode='video'),
            SimpleNamespace(visual_mode='image'),
        ])
        with patch.object(settings, 'veo_model_id', 'veo-3.1-lite-generate-001'), \
                patch.object(settings, 'veo_duration_seconds', 8), \
                patch.object(settings, 'hybrid_veo_duration_seconds', 6):
            self.assertAlmostEqual(estimate_new_visual_cost(script, 'image'), 0.068)
            self.assertAlmostEqual(estimate_new_visual_cost(script, 'hybrid'), 0.214)
            self.assertAlmostEqual(estimate_new_visual_cost(script, 'video'), 0.48)

    def test_topic_scoring_asks_for_stakes_and_source_supported_payoff(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.history_file = "/nonexistent/shorts-maker-history.json"
        create = AsyncMock(return_value=SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=(
                '{"candidates":[{"index":0,"score":7,"reason":"검증 필요","selected":true}]}'
            )))
        ]))
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

        result = asyncio.run(planner._score_topics([
            {"title": "Article title", "category": "Tech", "url": "https://example.com",
             "content": "<p>차고지 아래 저류조가 폭우 때 물을 모읍니다.</p>" + "x" * 250 + "END"}
        ]))

        self.assertTrue(result[0].selected)
        self.assertEqual(create.await_args.kwargs["max_completion_tokens"], 2000)
        prompt = create.await_args.kwargs["messages"][0]["content"]
        self.assertIn("Concrete stakes", prompt)
        self.assertIn("Source-backed turn", prompt)
        self.assertIn("Visual proof", prompt)
        self.assertIn("Event guides, discounts, openings, and promotional visits", prompt)
        self.assertIn("Do not turn an intended economic benefit into a measured outcome", prompt)
        self.assertIn("A niche mechanism alone", prompt)
        self.assertIn("차고지 아래 저류조가 폭우 때 물을 모읍니다.", prompt)
        self.assertNotIn("<p>", prompt)
        self.assertNotIn("END", prompt)
        self.assertIn("do not treat a feed teaser as proof", prompt)
        self.assertNotIn('"score": 9', prompt)

    def test_topic_scoring_rejects_ambiguous_or_malformed_selection(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.history_file = "/nonexistent/shorts-maker-history.json"
        create = AsyncMock()
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))
        candidates = [
            {"title": f"Story {i}", "category": "City_Life", "url": f"https://example.com/{i}"}
            for i in range(2)
        ]
        valid = [
            {"index": i, "score": 7, "reason": "본문 검증 필요", "selected": i == 0}
            for i in range(2)
        ]
        bad_responses = [
            {"candidates": [valid[0]]},
            {"candidates": [valid[0], valid[0]]},
            {"candidates": [dict(valid[0], selected=True), dict(valid[1], selected=True)]},
            {"candidates": [dict(valid[0], selected="false"), valid[1]]},
            {"candidates": [dict(valid[0], score=11), valid[1]]},
        ]
        for response in bad_responses:
            with self.subTest(response=response):
                create.return_value = SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(response)))])
                with self.assertRaisesRegex(RuntimeError, "TOPIC_SCORING_UNVERIFIED"):
                    asyncio.run(planner._score_topics(candidates))

        create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="length", message=SimpleNamespace(content=json.dumps({"candidates": valid})))])
        with self.assertRaisesRegex(RuntimeError, "TOPIC_SCORING_UNVERIFIED"):
            asyncio.run(planner._score_topics(candidates))

        create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"candidates": valid})))])
        result = asyncio.run(planner._score_topics(candidates))
        self.assertEqual([candidate.selected for candidate in result], [True, False])

    def test_topic_scoring_can_decline_the_whole_pool(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.history_file = "/nonexistent/shorts-maker-history.json"
        create = AsyncMock(return_value=SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=(
                '{"candidates":[{"index":0,"score":4,"reason":"근거 부족","selected":false}]}'
            )))
        ]))
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))
        candidate = {"title": "Unclear topic", "category": "Tech", "url": "https://example.com"}

        result = asyncio.run(planner._score_topics([candidate]))

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].selected)
        self.assertIn("mark all selected=false", create.await_args.kwargs["messages"][0]["content"])

    def test_unselected_topics_stop_before_article_and_writer(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidate = {"title": "Unclear topic", "category": "Tech", "url": "https://example.com"}
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=4, reason="not enough evidence", selected=False)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock())
        planner._write_script = AsyncMock()

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_awaited_once()
        planner.content_extractor.fetch_enhanced_article.assert_not_called()
        planner._write_script.assert_not_awaited()

    def test_bad_topic_score_response_does_not_randomly_select(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.history_file = "/nonexistent/shorts-maker-history.json"
        planner.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content="not JSON"))
            ])))))

        with self.assertRaisesRegex(RuntimeError, "TOPIC_SCORING_UNVERIFIED"):
            asyncio.run(planner._score_topics([
                {"title": "Unclear topic", "category": "Tech", "url": "https://example.com"}
            ]))

    def test_direct_generator_checks_batch_and_retry_reserve_before_generation(self):
        generator = object.__new__(VideoGenerator)
        generator.mode = "image"
        generator.max_veo_attempts = 1
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=i) for i in (1, 2)])
        with patch.object(settings, "max_visual_cost_usd", 0.05), patch.object(
            generator, "_generate_clips_sequential", new_callable=AsyncMock,
        ) as generate:
            with self.assertRaisesRegex(ValueError, "설정 상한"):
                asyncio.run(generator.generate_clips(script))
            generate.assert_not_awaited()

        generator.mode = "video"
        generator.max_veo_attempts = 3
        with patch.object(settings, "max_visual_cost_usd", 1.0), patch.object(
            generator, "_generate_background_video", new_callable=AsyncMock,
        ) as generate:
            with self.assertRaisesRegex(ValueError, "설정 상한"):
                asyncio.run(generator.generate_scene_clip(script.scenes[0]))
            generate.assert_not_awaited()

    def test_empty_manual_clips_do_not_start_paid_generation(self):
        service = ProductionService(mode="video")
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=1)])

        result = asyncio.run(service.produce_video(script, manual_clip_paths={}))

        self.assertFalse(result.success)
        self.assertIn("씬 1", result.error)
        self.assertIsNone(service._generator)

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_manual_clips_reach_editor_without_generator(self, _check):
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

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_session_options_reach_editor_and_parallel_generator(self, _check):
        state = AppState(mode="image", tts_voice="nova", bgm_mood="cinematic",
                         bgm_track="chosen.mp3")
        with patch.object(settings, "update_api_keys"):
            service = state.new_production_service(parallel_clips=True)
        self.assertIs(state.production_service, service)
        self.assertTrue(service.parallel_clips)
        with patch("shorts_maker.services.production_service.VideoEditor") as editor_class:
            service._get_editor()
        self.assertEqual(editor_class.call_args.kwargs["tts_voice"], "nova")
        self.assertEqual(editor_class.call_args.kwargs["bgm_mood"], "cinematic")
        self.assertEqual(editor_class.call_args.kwargs["bgm_track"], "chosen.mp3")

        state.bgm_track = "other.mp3"
        with patch.object(settings, "update_api_keys"):
            refreshed = state.get_or_create_service()
        self.assertIsNot(refreshed, service)
        self.assertEqual(refreshed.editor_options["bgm_track"], "other.mp3")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp4"
            output.touch()
            clips = [str(Path(directory) / f"{i}.png") for i in (1, 2)]
            for clip in clips:
                Path(clip).touch()
            generator = SimpleNamespace(generate_scene_clip=AsyncMock(side_effect=clips))
            service._generator = generator
            service._editor = SimpleNamespace(compose_video=AsyncMock(return_value=str(output)))
            script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=i) for i in (1, 2)])
            result = asyncio.run(service.produce_video(script))

        self.assertTrue(result.success)
        self.assertEqual(generator.generate_scene_clip.await_count, 2)
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
            success=True, video_path="video.mp4", clips=["scene.png"], ready_for_upload=True,
        ))
        service.upload_to_youtube = AsyncMock(return_value=ProductionResult(
            success=False, error="upload failed"
        ))

        result = asyncio.run(service.full_pipeline(auto_upload=True))

        self.assertFalse(result.success)
        self.assertIs(result.script, script)
        self.assertEqual(result.video_path, "video.mp4")
        self.assertEqual(result.clips, ["scene.png"])
        self.assertTrue(result.ready_for_upload)

    def test_full_pipeline_reuses_approved_script_and_assets_for_private_upload(self):
        service = ProductionService(mode="video")
        script = SimpleNamespace(title="Approved", description="Source", tags=["Shorts"])
        clips = {1: "scene.mp4"}
        audio = ["scene.mp3"]
        service.generate_script = AsyncMock()
        service.produce_video = AsyncMock(return_value=ProductionResult(
            success=True, video_path="render.mp4", ready_for_upload=True,
        ))
        service.upload_to_youtube = AsyncMock(return_value=ProductionResult(
            success=True, video_path="render.mp4", youtube_id="private-id",
        ))
        metadata = {"title": "Approved", "description": "Source", "contains_synthetic_media": True}

        result = asyncio.run(service.full_pipeline(
            approved_script=script, manual_clip_paths=clips,
            prepared_audio_paths=audio, auto_upload=True, upload_metadata=metadata,
        ))

        self.assertTrue(result.success)
        self.assertEqual(result.youtube_id, "private-id")
        self.assertIs(result.script, script)
        service.generate_script.assert_not_awaited()
        service.produce_video.assert_awaited_once_with(
            script, finish_phase=False, manual_clip_paths=clips, prepared_audio_paths=audio,
        )
        service.upload_to_youtube.assert_awaited_once_with("render.mp4", metadata)

    def test_approved_script_upload_requires_explicit_reviewed_metadata_before_render(self):
        complete = {"title": "Approved", "description": "Source credit", "contains_synthetic_media": True}
        for metadata in (None, {}, {"description": "Source credit", "contains_synthetic_media": True},
                         {"title": "Approved", "contains_synthetic_media": True},
                         {"title": "Approved", "description": "Source credit"},
                         {**complete, "title": "  "}, {**complete, "description": "  "},
                         {**complete, "contains_synthetic_media": "yes"}):
            with self.subTest(metadata=metadata):
                service = ProductionService()
                service.generate_script = AsyncMock()
                service.produce_video = AsyncMock()
                service.upload_to_youtube = AsyncMock()
                result = asyncio.run(service.full_pipeline(
                    approved_script=SimpleNamespace(title="Approved", description="old draft"),
                    auto_upload=True, upload_metadata=metadata,
                ))
                self.assertFalse(result.success)
                self.assertIn("검토한 제목·설명·AI 공개 선택", result.error)
                service.generate_script.assert_not_awaited()
                service.produce_video.assert_not_awaited()
                service.upload_to_youtube.assert_not_awaited()

    def test_full_pipeline_rejects_conflicting_approved_inputs(self):
        service = ProductionService()
        service.generate_script = AsyncMock()
        service.produce_video = AsyncMock()

        result = asyncio.run(service.full_pipeline(
            topic="new topic", approved_script=SimpleNamespace(), auto_upload=True,
        ))

        self.assertFalse(result.success)
        service.generate_script.assert_not_awaited()
        service.produce_video.assert_not_awaited()

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_full_pipeline_completes_only_after_upload(self, _check):
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
        self.assertIs(service._uploader.upload.await_args.args[1]["contains_synthetic_media"], True)

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_upload_failure_sets_failed_phase(self, _check):
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

    @patch("shorts_maker.services.production_service.check_video_quality")
    def test_editor_progress_is_reported_when_work_occurs(self, _check):
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
        generator.max_veo_attempts = 1
        generator.character_overlay = None
        generator._generate_background_video = AsyncMock(return_value="background.mp4")
        generator._generate_image_gemini = AsyncMock(return_value="image.png")
        scene = SimpleNamespace(scene_number=1)

        self.assertEqual(asyncio.run(generator.generate_scene_clip(scene)), "background.mp4")
        generator.mode = "image"
        self.assertEqual(asyncio.run(generator.generate_scene_clip(scene)), "image.png")
        generator._generate_background_video.assert_awaited_once_with(scene)
        generator._generate_image_gemini.assert_awaited_once_with(scene)

    def test_sequential_generation_waits_only_between_scenes(self):
        generator = object.__new__(VideoGenerator)
        generator.mode = "image"
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
        evidence = "The source describes the choice and its concrete mechanism."
        article = SimpleNamespace(word_count=120, title="Topic", main_text=evidence,
                                  quotes=[], headings=[], captions=[])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=article))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=
            SimpleNamespace(story_fit=True, story_fit_evidence=evidence,
                            core_message="Choice", visual_keywords=[])))
        planner.content_enricher = SimpleNamespace(enrich_content=AsyncMock(return_value=[]))
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
        evidence = "The source describes the choice and its concrete mechanism."
        article = SimpleNamespace(word_count=120, title="Topic", main_text=evidence,
                                  quotes=[], headings=[], captions=[])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=article))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=
            SimpleNamespace(story_fit=True, story_fit_evidence=evidence,
                            core_message="Choice", visual_keywords=[])))
        planner.content_enricher = SimpleNamespace(enrich_content=AsyncMock(return_value=[]))
        planner._write_script = AsyncMock(return_value=object())
        validated = object()
        planner._validate_and_save = AsyncMock(return_value=validated)
        planner._save_history = Mock()

        result, _ = asyncio.run(planner.plan_content())

        self.assertIs(result, validated)
        planner._save_history.assert_called_once_with("Topic", "https://example.com")

    def test_rss_skips_missing_and_short_articles_before_paid_writer(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidates = [
            {"title": name, "category": "Tech", "url": f"https://example.com/{name}"}
            for name in ("missing", "short", "usable")
        ]
        planner._fetch_rss_feeds = Mock(return_value=candidates)
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(side_effect=lambda remaining: [
            TopicCandidate(item=remaining[0], score=8, reason="test", selected=True)
        ])
        short = SimpleNamespace(word_count=99)
        evidence = "The source describes the choice and its concrete mechanism."
        usable = SimpleNamespace(word_count=100, title="Usable", main_text=evidence,
                                 quotes=[], headings=[], captions=[])
        planner.content_extractor = SimpleNamespace(
            fetch_enhanced_article=Mock(side_effect=[None, short, usable])
        )
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=
            SimpleNamespace(story_fit=True, story_fit_evidence=evidence,
                            core_message="Choice", visual_keywords=[])))
        planner.content_enricher = SimpleNamespace(enrich_content=AsyncMock(return_value=[]))
        script = object()
        planner._write_script = AsyncMock(return_value=script)
        planner._validate_and_save = AsyncMock(return_value=script)
        planner._save_history = Mock()

        with patch.object(settings, "max_topic_retries", 3):
            result, _ = asyncio.run(planner.plan_content())

        self.assertIs(result, script)
        self.assertEqual(planner.content_extractor.fetch_enhanced_article.call_count, 3)
        planner._write_script.assert_awaited_once()
        self.assertEqual(planner._write_script.await_args.args[0]["url"],
                         "https://example.com/usable")
        planner._save_history.assert_called_once_with("usable", "https://example.com/usable")

    def test_rss_rejects_announcement_or_unmatched_evidence_before_enrichment(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidate = {"title": "Launch announcement", "category": "City_Life",
                     "url": "https://example.com/launch"}
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=8, reason="promising lead", selected=True)
        ])
        article = SimpleNamespace(word_count=120, title="Launch announcement",
                                  main_text="The new service is scheduled to start next week.",
                                  quotes=[], headings=[], captions=[])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=article))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock())
        planner.content_enricher = SimpleNamespace(enrich_content=AsyncMock())
        planner._write_script = AsyncMock()

        for verdict, evidence in ((False, ""), (True, "An observed result not found in the article."),
                                  (True, "scheduled")):
            with self.subTest(verdict=verdict, evidence=evidence), patch.object(settings, "max_topic_retries", 1):
                planner.content_analyzer.analyze_content.return_value = SimpleNamespace(
                    story_fit=verdict, story_fit_evidence=evidence)
                self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner.content_enricher.enrich_content.assert_not_awaited()
        planner._write_script.assert_not_awaited()

    def test_rss_analysis_failure_stops_before_another_paid_selection(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidates = [
            {"title": name, "category": "City_Life", "url": f"https://example.com/{name}"}
            for name in ("first", "second")
        ]
        planner._fetch_rss_feeds = Mock(return_value=candidates)
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidates[0], score=8, reason="lead", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=
            SimpleNamespace(word_count=120, title="First", main_text="Article body")))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=None))
        planner._write_script = AsyncMock()

        with patch.object(settings, "max_topic_retries", 2):
            with self.assertRaisesRegex(RuntimeError, "ARTICLE_ANALYSIS_UNVERIFIED"):
                asyncio.run(planner.plan_content())
        planner._score_topics.assert_awaited_once()
        planner._write_script.assert_not_awaited()

    def test_empty_feed_does_not_invent_a_topic(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner._fetch_rss_feeds = Mock(return_value=[])
        planner._score_topics = AsyncMock()

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_not_awaited()

    def test_rss_category_limit_skips_extra_feed_before_fetch(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"City_Life": ["https://example.com/one", "https://example.com/two"]}
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        entries = [
            {"title": f"Story {i}", "link": f"https://example.com/story-{i}",
             "summary": "Source summary " * 20, "published_parsed": None}
            for i in range(5)
        ]
        planner.rss_cache = SimpleNamespace(get=Mock(return_value=entries), set=Mock())

        with patch("shorts_maker.planner.script_planner.random.shuffle"):
            posts = planner._fetch_rss_feeds()

        self.assertEqual(len(posts), 5)
        planner.rss_cache.get.assert_called_once_with("https://example.com/one")

    def test_rss_discovery_deduplicates_and_rejects_disallowed_article_urls(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {
            "City_Life": ["https://example.com/city"],
            "Finance_Economy": ["https://example.com/economy"],
        }
        planner._load_url_history = Mock(return_value=[])
        planner._is_recent = Mock(return_value=True)
        shared = {"title": "Shared", "link": "https://example.com/shared",
                  "summary": "Source summary " * 20, "published_parsed": None}
        blocked = dict(shared, title="Blocked", link="http://127.0.0.1/private")
        planner.rss_cache = SimpleNamespace(get=Mock(return_value=[shared, blocked]), set=Mock())

        with patch("shorts_maker.planner.script_planner.random.shuffle"):
            posts = planner._fetch_rss_feeds()

        self.assertEqual([post["url"] for post in posts], ["https://example.com/shared"])

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
        self.assertFalse(run_server.call_args.kwargs["reload"])
        self.assertNotEqual(
            run_server.call_args.kwargs["storage_secret"],
            "shortsmaker_secret_key_change_in_production",
        )


if __name__ == "__main__":
    unittest.main()
