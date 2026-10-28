"""Offline checks for the paths that select paid or manual generation."""

import asyncio
import importlib
import json
import tempfile
import time
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.gui.components.planning_tab import estimate_new_visual_cost
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ScriptGenerationContext, ShortsScript, TopicCandidate
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services.production_service import (
    ProductionPhase, ProductionResult, ProductionService, source_credited_description,
)
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.rss_cache import RSSCache
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        paid = patch.object(settings, "paid_production_enabled", True)
        paid.start()
        self.addCleanup(paid.stop)
        budget = patch.object(settings, "google_monthly_budget_krw", None)
        budget.start()
        self.addCleanup(budget.stop)
        openai_budget = patch.object(settings, "openai_monthly_budget_usd", None)
        openai_budget.start()
        self.addCleanup(openai_budget.stop)

    def test_rss_recency_requires_a_valid_utc_date_within_fourteen_days(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        now = datetime.now(timezone.utc)

        def entry_at(offset):
            return SimpleNamespace(published_parsed=time.gmtime((now + offset).timestamp()))

        self.assertTrue(planner._is_recent(entry_at(-timedelta(days=13))))
        self.assertFalse(planner._is_recent(entry_at(-timedelta(days=15))))
        self.assertFalse(planner._is_recent(entry_at(timedelta(days=1))))
        self.assertFalse(planner._is_recent(SimpleNamespace(published_parsed=None)))
        self.assertFalse(planner._is_recent(SimpleNamespace(published_parsed=("invalid",))))

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

        with patch('shorts_maker.planner.script_planner.reserve_openai_chat') as reserve:
            result = asyncio.run(planner._score_topics([
                {"title": "Article title", "category": "Tech", "url": "https://example.com",
                 "content": "<p>차고지 아래 저류조가 폭우 때 물을 모읍니다.</p>" + "x" * 250 + "END"}
            ]))

        self.assertTrue(result[0].selected)
        self.assertEqual(reserve.call_args.args[2], 4000)
        self.assertNotIn("source_url", reserve.call_args.kwargs)
        self.assertEqual(create.await_args.kwargs["max_completion_tokens"], 4000)
        prompt = create.await_args.kwargs["messages"][0]["content"]
        self.assertIn("Concrete stakes", prompt)
        self.assertIn("Source-backed turn", prompt)
        self.assertIn("Visual proof", prompt)
        self.assertIn("Event guides, discounts, openings, and promotional visits", prompt)
        self.assertIn("Do not turn an intended economic benefit into a measured outcome", prompt)
        self.assertIn("A niche mechanism alone", prompt)
        self.assertIn("select at most one of those leads", prompt)
        self.assertIn("one concise Korean clause", prompt)
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
            message=SimpleNamespace(content=json.dumps({"candidates": [
                dict(valid[0], selected=True), dict(valid[1], selected=True),
            ]})))])
        with patch.object(settings, "max_topic_retries", 1):
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
        create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"candidates": [
                dict(valid[0], selected=True), dict(valid[1], selected=True),
            ]})))])
        result = asyncio.run(planner._score_topics(candidates))
        self.assertEqual([candidate.selected for candidate in result], [True, True])

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
        planner._remember_rss_urls = Mock()

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_awaited_once()
        planner.content_extractor.fetch_enhanced_article.assert_not_called()
        planner._write_script.assert_not_awaited()
        planner._remember_rss_urls.assert_called_once_with([candidate["url"]])

    def test_declined_rss_lead_is_not_scored_again_on_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "url_history.json"
            planner = object.__new__(ScriptPlanner)
            planner.logger = Mock()
            planner.url_history_file = str(path)
            planner.rss_sources = {"City_Life": ["https://example.com/feed"]}
            planner.rss_cache = SimpleNamespace(get=Mock(return_value=[{
                "title": "Unclear story", "link": "https://example.com/story",
                "summary": "Source summary " * 20, "published_parsed": None,
            }]), set=Mock())
            planner._validate_url = Mock(return_value=True)
            planner._is_recent = Mock(return_value=True)
            planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock())
            planner._score_topics = AsyncMock(side_effect=lambda candidates: [
                TopicCandidate(item=item, score=4, reason="no source-backed turn", selected=False)
                for item in candidates
            ])

            planner._score_topics.side_effect = RuntimeError("TOPIC_SCORING_UNVERIFIED")
            with self.assertRaisesRegex(RuntimeError, "TOPIC_SCORING_UNVERIFIED"):
                asyncio.run(planner.plan_content())
            self.assertFalse(path.exists())
            planner._score_topics.side_effect = lambda candidates: [
                TopicCandidate(item=item, score=4, reason="no source-backed turn", selected=False)
                for item in candidates
            ]
            self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             ["https://example.com/story"])
            self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
            self.assertEqual(planner._score_topics.await_count, 2)
            planner.content_extractor.fetch_enhanced_article.assert_not_called()

            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "URL 히스토리"):
                planner._fetch_rss_feeds()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

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
        service._uploader = SimpleNamespace(get_authenticated_service=Mock(return_value=object()))
        script = SimpleNamespace(title="Title", description="Description", tags=[],
                                 source_url="https://example.com/report",
                                 supporting_source_urls=["https://example.com/context"])
        service.generate_script = AsyncMock(return_value=(script, None))
        service.produce_video = AsyncMock(return_value=ProductionResult(
            success=True, video_path="video.mp4", clips=["scene.png"], ready_for_upload=True,
        ))
        service.upload_to_youtube = AsyncMock(return_value=ProductionResult(
            success=False, error="upload failed"
        ))

        metadata = {
            "title": "Title",
            "description": "Description\n\n출처: https://example.com/report"
                           "\n\n출처: https://example.com/context",
            "contains_synthetic_media": True,
        }
        result = asyncio.run(service.full_pipeline(
            approved_script=script, auto_upload=True, upload_metadata=metadata,
        ))

        self.assertFalse(result.success)
        self.assertIs(result.script, script)
        self.assertEqual(result.video_path, "video.mp4")
        self.assertEqual(result.clips, ["scene.png"])
        self.assertTrue(result.ready_for_upload)
        self.assertEqual(service.upload_to_youtube.await_args.args[1], metadata)

    def test_new_script_stops_before_visuals_and_upload_auth(self):
        service = ProductionService(mode="image", editor_options={"bgm_volume": 0})
        script = ShortsScript(
            title="Reviewed later", description="A source-backed change", tags=[],
            mood="calm", style="documentary", source_name="Source",
            source_url="https://example.com/article", generation_mode="image",
            scenes=[{"scene_number": 1, "visual_description": "Show the relationship",
                     "script_text": "Explain the change"}],
        )
        service.generate_script = AsyncMock(return_value=(script, None))
        service.produce_video = AsyncMock()
        service._uploader = SimpleNamespace(get_authenticated_service=Mock())

        result = asyncio.run(service.full_pipeline(auto_upload=True))

        self.assertTrue(result.success)
        self.assertTrue(result.review_pending)
        self.assertIs(result.script, script)
        self.assertIsNone(result.video_path)
        service.produce_video.assert_not_awaited()
        service._uploader.get_authenticated_service.assert_not_called()

    def test_script_confirmation_is_bound_to_current_content(self):
        state = AppState(script=ShortsScript(
            title="Current", description="Description", tags=[], mood="calm",
            style="documentary", source_name="Source",
            source_url="https://example.com/article", generation_mode="image",
            scenes=[{"scene_number": 1, "visual_description": "A bridge",
                     "script_text": "A decision"}],
        ))
        self.assertFalse(state.is_script_reviewed())
        state.confirm_script_review()
        self.assertTrue(state.is_script_reviewed())
        state.script.scenes[0].visual_description = "A different plan"
        self.assertFalse(state.is_script_reviewed())

    def test_source_credit_does_not_duplicate_existing_link(self):
        description = "설명\n출처: https://example.com/report"
        self.assertEqual(source_credited_description(description, "https://example.com/report"),
                         description)
        self.assertEqual(source_credited_description(
            "설명\n출처: https://example.com/report-extra", "https://example.com/report",
            ["https://example.com/earlier"]),
            "설명\n출처: https://example.com/report-extra\n\n"
            "출처: https://example.com/report\n\n출처: https://example.com/earlier")
        both = "자료: https://example.com/report; 보조: https://example.com/earlier"
        self.assertEqual(source_credited_description(
            both, "https://example.com/report", ["https://example.com/earlier"]), both)

    def test_full_pipeline_reuses_approved_script_and_assets_for_private_upload(self):
        service = ProductionService(mode="video")
        service._uploader = SimpleNamespace(get_authenticated_service=Mock(return_value=object()))
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

    def test_approved_upload_checks_auth_before_render(self):
        service = ProductionService()
        service._uploader = SimpleNamespace(get_authenticated_service=Mock(
            side_effect=RuntimeError("YOUTUBE_AUTH_REQUIRED"),
        ))
        service.generate_script = AsyncMock()
        service.produce_video = AsyncMock()

        result = asyncio.run(service.full_pipeline(
            approved_script=SimpleNamespace(), auto_upload=True,
            upload_metadata={"title": "Approved", "description": "Reviewed",
                             "contains_synthetic_media": True},
        ))

        self.assertFalse(result.success)
        self.assertIn("YOUTUBE_AUTH_REQUIRED", result.error)
        service.generate_script.assert_not_awaited()
        service.produce_video.assert_not_awaited()
        service._uploader.get_authenticated_service.assert_called_once_with(interactive=False)

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

    def test_approved_script_upload_checks_source_credit_before_render(self):
        service = ProductionService()
        service._uploader = SimpleNamespace(get_authenticated_service=Mock(return_value=object()))
        service.produce_video = AsyncMock()
        service.upload_to_youtube = AsyncMock()

        result = asyncio.run(service.full_pipeline(
            approved_script=SimpleNamespace(source_url="https://example.com/article"),
            auto_upload=True,
            upload_metadata={"title": "Reviewed", "description": "출처 없음",
                             "contains_synthetic_media": True},
        ))

        self.assertFalse(result.success)
        self.assertIn("출처 URL", result.error)
        service.produce_video.assert_not_awaited()
        service.upload_to_youtube.assert_not_awaited()

        secondary = asyncio.run(service.full_pipeline(
            approved_script=SimpleNamespace(
                source_url="https://example.com/article",
                supporting_source_urls=["https://example.com/earlier"]),
            auto_upload=True,
            upload_metadata={"title": "Reviewed",
                             "description": "출처: https://example.com/article",
                             "contains_synthetic_media": True},
        ))
        self.assertFalse(secondary.success)
        self.assertIn("모든 출처 URL", secondary.error)
        service.produce_video.assert_not_awaited()

    def test_auto_upload_rejects_invalid_metadata_before_planning(self):
        service = ProductionService()
        service.generate_script = AsyncMock()
        service.produce_video = AsyncMock()

        result = asyncio.run(service.full_pipeline(
            auto_upload=True, upload_metadata={"title": "Ready", "tags": [object()]},
        ))

        self.assertFalse(result.success)
        self.assertIn("메타데이터 확인 실패", result.error)
        service.generate_script.assert_not_awaited()
        service.produce_video.assert_not_awaited()

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
            service._uploader = SimpleNamespace(
                get_authenticated_service=Mock(return_value=object()),
                upload=AsyncMock(return_value="video-id"),
            )
            phases = []
            service.set_progress_callback(lambda progress: phases.append(progress.phase))

            with patch("shorts_maker.services.production_service.asyncio.sleep", new_callable=AsyncMock) as delay:
                result = asyncio.run(service.full_pipeline(
                    approved_script=script, auto_upload=True,
                    upload_metadata={"title": "Title", "description": "Description",
                                     "contains_synthetic_media": True},
                ))
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

        self.assertEqual(asyncio.run(generator.generate_scene_clip(
            scene, first_frame_path="reviewed.png", expected_first_frame_sha256="frame-hash",
        )), "background.mp4")
        generator.mode = "image"
        self.assertEqual(asyncio.run(generator.generate_scene_clip(scene)), "image.png")
        generator._generate_background_video.assert_awaited_once_with(
            scene, source_url=None, first_frame_path="reviewed.png",
            expected_first_frame_sha256="frame-hash",
        )
        generator._generate_image_gemini.assert_awaited_once_with(scene, None)

    def test_sequential_generation_waits_only_between_scenes(self):
        generator = object.__new__(VideoGenerator)
        generator.mode = "image"
        generator.generate_scene_clip = AsyncMock(side_effect=["scene_1.png", "scene_2.png"])
        script = SimpleNamespace(scenes=[SimpleNamespace(scene_number=i) for i in (1, 2)],
                                 source_url="https://example.com/story")

        with patch("shorts_maker.generator.video_generator.asyncio.sleep", new_callable=AsyncMock) as delay:
            result = asyncio.run(generator._generate_clips_sequential(script))

        self.assertEqual(result, ["scene_1.png", "scene_2.png"])
        self.assertEqual([call.kwargs["source_url"] for call in generator.generate_scene_clip.await_args_list],
                         [script.source_url] * 2)
        delay.assert_awaited_once_with(settings.scene_buffer_seconds)

    def test_parallel_failure_does_not_create_publishable_placeholder(self):
        generator = object.__new__(VideoGenerator)
        generator.logger = get_logger(__name__)
        generator.max_concurrent = 2
        generator._create_mock_image = Mock()
        scenes = [SimpleNamespace(scene_number=1), SimpleNamespace(scene_number=2)]

        async def generate(scene, *, source_url):
            self.assertEqual(source_url, "https://example.com/story")
            if scene.scene_number == 1:
                raise RuntimeError("generation failed")
            return "scene_2.png"

        generator.generate_scene_clip = generate
        with patch("shorts_maker.generator.video_generator.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                asyncio.run(generator._generate_clips_parallel(SimpleNamespace(
                    scenes=scenes, source_url="https://example.com/story",
                )))

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
        planner._remember_rss_urls = Mock()
        planner._write_script = AsyncMock(return_value=object())
        planner._validate_and_save = AsyncMock(return_value=None)

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._save_history.assert_not_called()
        planner._remember_rss_urls.assert_called_once_with([candidate["url"]])

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
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidates[2], score=7, reason="test", selected=True),
            TopicCandidate(item=candidates[1], score=8, reason="test", selected=True),
            TopicCandidate(item=candidates[0], score=9, reason="test", selected=True),
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
        planner._remember_rss_urls = Mock()

        with patch.object(settings, "max_topic_retries", 3):
            result, _ = asyncio.run(planner.plan_content())

        self.assertIs(result, script)
        planner._score_topics.assert_awaited_once_with(candidates)
        self.assertEqual(planner.content_extractor.fetch_enhanced_article.call_count, 3)
        planner._write_script.assert_awaited_once()
        self.assertEqual(planner._write_script.await_args.args[0]["url"],
                         "https://example.com/usable")
        self.assertEqual(planner.content_enricher.enrich_content.await_args.kwargs["source_url"],
                         "https://example.com/usable")
        planner._save_history.assert_called_once_with("usable", "https://example.com/usable")
        self.assertEqual([call.args[0] for call in planner._remember_rss_urls.call_args_list],
                         [["https://example.com/missing"], ["https://example.com/short"]])

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
        planner._remember_rss_urls = Mock()

        for verdict, evidence in ((False, ""), (True, "An observed result not found in the article."),
                                  (True, "scheduled")):
            with self.subTest(verdict=verdict, evidence=evidence), patch.object(settings, "max_topic_retries", 1):
                planner.content_analyzer.analyze_content.return_value = SimpleNamespace(
                    story_fit=verdict, story_fit_evidence=evidence)
                self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner.content_enricher.enrich_content.assert_not_awaited()
        planner._write_script.assert_not_awaited()
        self.assertEqual(planner._remember_rss_urls.call_count, 3)

    def test_rss_shares_late_evidence_with_writer_and_validator(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        candidate = {"title": "Long article", "category": "City_Life",
                     "url": "https://example.com/long"}
        evidence = "The completed project has a source-backed explanatory result."
        planner._fetch_rss_feeds = Mock(return_value=[candidate])
        planner._validate_url = Mock(return_value=True)
        planner._score_topics = AsyncMock(return_value=[
            TopicCandidate(item=candidate, score=8, reason="promising lead", selected=True)
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=
            SimpleNamespace(word_count=120, title="Long article",
                            main_text="A" * 5000 + " " + evidence + " " + "B" * 2500,
                            quotes=[evidence], headings=[], captions=[])))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=
            SimpleNamespace(story_fit=True, story_fit_evidence=evidence,
                            core_message="Completed work", visual_keywords=[])))
        planner.content_enricher = SimpleNamespace(enrich_content=AsyncMock(return_value=[]))
        script = object()
        planner._write_script = AsyncMock(return_value=script)
        planner._validate_and_save = AsyncMock(return_value=script)
        planner._save_history = Mock()
        planner._remember_rss_urls = Mock()

        with patch.object(settings, "max_topic_retries", 1):
            result, _ = asyncio.run(planner.plan_content())

        self.assertIs(result, script)
        source_excerpt = planner._write_script.await_args.args[0]["content"]
        self.assertLessEqual(len(source_excerpt), 5000)
        self.assertIn(evidence, source_excerpt)
        self.assertIs(planner._validate_and_save.await_args.args[1],
                      planner._write_script.await_args.args[0])
        planner._remember_rss_urls.assert_not_called()

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
            TopicCandidate(item=candidates[0], score=8, reason="lead", selected=True),
            TopicCandidate(item=candidates[1], score=7, reason="backup", selected=True),
        ])
        planner.content_extractor = SimpleNamespace(fetch_enhanced_article=Mock(return_value=
            SimpleNamespace(word_count=120, title="First", main_text="Article body")))
        planner.content_analyzer = SimpleNamespace(analyze_content=AsyncMock(return_value=None))
        planner._write_script = AsyncMock()

        with patch.object(settings, "max_topic_retries", 2):
            with self.assertRaisesRegex(RuntimeError, "ARTICLE_ANALYSIS_UNVERIFIED"):
                asyncio.run(planner.plan_content())
        planner._score_topics.assert_awaited_once()
        planner.content_extractor.fetch_enhanced_article.assert_called_once_with(candidates[0]["url"])
        planner._write_script.assert_not_awaited()

    def test_empty_feed_does_not_invent_a_topic(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner._fetch_rss_feeds = Mock(return_value=[])
        planner._score_topics = AsyncMock()

        self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_not_awaited()

    def test_zero_rss_attempts_does_not_buy_topic_scoring(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner._fetch_rss_feeds = Mock(return_value=[
            {"title": "Lead", "category": "City_Life", "url": "https://example.com/lead"}
        ])
        planner._score_topics = AsyncMock()

        with patch.object(settings, "max_topic_retries", 0):
            self.assertEqual(asyncio.run(planner.plan_content()), (None, None))
        planner._score_topics.assert_not_awaited()

    def test_rss_category_limit_balances_sources_without_more_paid_candidates(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"City_Life": ["https://example.com/one", "https://example.com/two"]}
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        feeds = {url: [
            {"title": f"Story {i}", "link": f"{url}/story-{i}",
             "summary": "Source summary " * 20, "published_parsed": None}
            for i in range(5)
        ] for url in planner.rss_sources["City_Life"]}
        planner.rss_cache = SimpleNamespace(get=Mock(side_effect=feeds.__getitem__), set=Mock())

        posts = planner._fetch_rss_feeds()

        self.assertEqual(len(posts), 5)
        self.assertEqual(planner.rss_cache.get.call_count, 2)
        self.assertEqual(sorted(sum(post["url"].startswith(url) for post in posts)
                                for url in feeds), [2, 3])
        with self.assertRaises(ValueError):
            planner._fetch_rss_feeds(limit_per_category=0)

    def test_rss_category_choice_filters_sources_before_scoring(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {
            "City_Life": ["https://example.com/city"],
            "Finance_Economy": ["https://example.com/finance"],
        }
        planner._load_url_history = Mock(return_value=[])
        planner._is_recent = Mock(return_value=True)
        planner.rss_cache = SimpleNamespace(get=Mock(side_effect=lambda url: [{
            "title": url, "link": f"{url}/story", "summary": "Source summary " * 20,
            "published_parsed": None,
        }]), set=Mock())

        posts = planner._fetch_rss_feeds(category="Finance_Economy")
        self.assertEqual([post["category"] for post in posts], ["Finance_Economy"])
        planner.rss_cache.get.assert_called_once_with("https://example.com/finance")
        with self.assertRaisesRegex(ValueError, "등록되지 않은 RSS 분야"):
            planner._fetch_rss_feeds(category="Technology")
        planner.rss_cache.get.assert_called_once()

        planner._fetch_rss_feeds = Mock(return_value=[])
        planner._score_topics = AsyncMock()
        self.assertEqual(asyncio.run(planner.plan_content(topic="City_Life")), (None, None))
        planner._fetch_rss_feeds.assert_called_once_with(category="City_Life")
        planner._score_topics.assert_not_awaited()

    def test_rss_length_gate_uses_visible_summary_text(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"City_Life": ["https://example.com/feed"]}
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        entries = [
            {"title": "Markup-only lead", "link": "https://example.com/short",
             "summary": '<p data-noise="' + 'x' * 250 + '">Tiny lead</p>'},
            {"title": "Too little context", "link": "https://example.com/too-short",
             "summary": "Source details " * 9},
            {"title": "Economy lead", "link": "https://example.com/economy",
             "summary": "Source details " * 11},
            {"title": "Readable lead", "link": "https://example.com/readable",
             "summary": "<p>" + "Source details " * 20 + "</p>"},
        ]
        planner.rss_cache = SimpleNamespace(get=Mock(return_value=entries), set=Mock())

        posts = planner._fetch_rss_feeds()

        self.assertEqual({post["url"] for post in posts},
                         {"https://example.com/economy", "https://example.com/readable"})
        self.assertEqual(next(post["content"] for post in posts if post["url"].endswith("/economy")),
                         ("Source details " * 11).strip())

    def test_cached_rss_retains_publisher_name_for_script_source(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"Finance_Economy": ["https://example.com/feed"]}
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        planner.rss_cache = RSSCache()
        response = SimpleNamespace(
            is_redirect=False, raise_for_status=Mock(),
            content=(
                '<rss version="2.0"><channel><title>Official Economy</title><item>'
                '<title>Economic change</title><link>https://example.com/story</link>'
                '<description>' + 'Source details ' * 11 + '</description>'
                '</item></channel></rss>'
            ).encode(),
        )

        with patch('shorts_maker.planner.script_planner.httpx.get', return_value=response) as get:
            first = planner._fetch_rss_feeds()
            cached = planner._fetch_rss_feeds()

        self.assertEqual(first, cached)
        self.assertEqual(first[0]['source'], 'Official Economy')
        get.assert_called_once()

    def test_rss_daily_sample_matches_category_preview_without_mutating_cache(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {
            "City_Life": ["https://example.com/city-one", "https://example.com/city-two"],
            "Finance_Economy": ["https://example.com/economy"],
        }
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        feeds = {
            url: [
                {"title": f"Story {i}", "link": f"{url}/story-{i}",
                 "summary": "Source summary " * 20, "published_parsed": None}
                for i in range(8)
            ]
            for urls in planner.rss_sources.values() for url in urls
        }
        original_order = {url: [item["link"] for item in entries] for url, entries in feeds.items()}
        planner.rss_cache = SimpleNamespace(get=Mock(side_effect=feeds.__getitem__), set=Mock())

        full = planner._fetch_rss_feeds()
        self.assertEqual(full, planner._fetch_rss_feeds())
        planner.rss_sources = {"City_Life": planner.rss_sources["City_Life"]}
        city_preview = planner._fetch_rss_feeds()

        self.assertEqual([item for item in full if item["category"] == "City_Life"], city_preview)
        self.assertEqual(original_order, {
            url: [item["link"] for item in entries] for url, entries in feeds.items()
        })

    def test_rss_free_inventory_reads_past_paid_category_limit(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"City_Life": ["https://example.com/one", "https://example.com/two"]}
        planner._load_url_history = Mock(return_value=[])
        planner._validate_url = Mock(return_value=True)
        planner._is_recent = Mock(return_value=True)
        planner.rss_cache = SimpleNamespace(get=Mock(side_effect=lambda url: [
            {"title": f"Story {url}-{i}", "link": f"{url}/story-{i}",
             "summary": "Source summary " * 20, "published": "2026-10-21",
             "published_parsed": None}
            for i in range(5)
        ]), set=Mock())

        posts = planner._fetch_rss_feeds(limit_per_category=None)

        self.assertEqual(len(posts), 10)
        self.assertEqual(planner.rss_cache.get.call_count, 2)
        self.assertTrue(all(item["published"] == "2026-10-21" for item in posts))

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
                with self.assertRaisesRegex(RuntimeError, "RSS_SOURCE_UNVERIFIED"):
                    planner._fetch_rss_feeds()

        httpx_client.get.assert_called_once()
        parse.assert_not_called()

    def test_rss_failure_is_distinct_from_a_valid_empty_feed(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.rss_sources = {"City": ["https://example.com/feed"]}
        planner._load_url_history = Mock(return_value=[])
        planner.rss_cache = SimpleNamespace(get=Mock(return_value=None), set=Mock())

        with patch("shorts_maker.planner.script_planner.httpx.get", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "RSS_SOURCE_UNVERIFIED"):
                planner._fetch_rss_feeds()

        response = SimpleNamespace(is_redirect=False, raise_for_status=Mock(), content=(
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        ))
        with patch("shorts_maker.planner.script_planner.httpx.get", return_value=response):
            self.assertEqual(planner._fetch_rss_feeds(), [])

        response.content = b"<html>not a feed</html>"
        with patch("shorts_maker.planner.script_planner.httpx.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "RSS_SOURCE_UNVERIFIED"):
                planner._fetch_rss_feeds()

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
