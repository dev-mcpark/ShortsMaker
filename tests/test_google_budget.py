"""Local Google budget reservations must block before provider requests."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.services.google_budget import (
    budget_status, check_google_budget, initialize_google_budget,
    mark_google_result, reserve_google_output,
)
from shorts_maker.utils.character_video_generator import CharacterVideoGenerator
from shorts_maker.utils.config import Settings, settings


class GoogleBudgetTests(unittest.TestCase):
    def test_enabled_budget_requires_opening_month_and_rate(self):
        with self.assertRaisesRegex(ValueError, "Google 월 예산"):
            Settings(google_monthly_budget_krw=10000, google_budget_month="",
                     google_budget_opening_krw=None, google_usd_krw_rate=None)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for name, value in (
            ("output_dir", Path(self.directory.name)),
            ("google_monthly_budget_krw", 1500),
            ("google_budget_month", "2026-10"),
            ("google_budget_opening_krw", 1000),
            ("google_usd_krw_rate", 2000),
            ("paid_production_enabled", True),
        ):
            override = patch.object(settings, name, value)
            override.start()
            self.addCleanup(override.stop)
        period = patch("shorts_maker.services.google_budget._period", return_value="2026-10")
        period.start()
        self.addCleanup(period.stop)
        initialize_google_budget()

    def test_deleted_ledger_blocks_instead_of_resetting_spend(self):
        request_id = reserve_google_output("image", settings.image_model_id)
        ledger = Path(self.directory.name) / "evaluation" / "google_budget.sqlite3"
        ledger.unlink()
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            reserve_google_output("image", settings.image_model_id)
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            check_google_budget(0.034)
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            budget_status()
        self.assertFalse(mark_google_result(request_id, "saved"))
        self.assertFalse(ledger.exists())

    def test_initializer_does_not_overwrite_existing_reservations(self):
        reserve_google_output("image", settings.image_model_id)
        with self.assertRaises(FileExistsError):
            initialize_google_budget()
        self.assertEqual(budget_status()["local_reserved_krw"], 68)

    def test_batch_preflight_includes_each_request_rounding(self):
        with patch.object(settings, "google_usd_krw_rate", 1501), patch.object(
            settings, "google_monthly_budget_krw", 1103
        ):
            check_google_budget(0.068)
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                check_google_budget(0.068, 2)

    def test_model_price_reserves_and_failed_request_keeps_budget(self):
        self.assertEqual(budget_status()["remaining_krw"], 500)
        request_id = reserve_google_output("image", settings.image_model_id)
        self.assertEqual(budget_status()["local_reserved_krw"], 68)
        self.assertEqual(budget_status()["reserved_by_model_krw"], {settings.image_model_id: 68})
        self.assertTrue(mark_google_result(request_id, "failed_or_unknown"))
        self.assertEqual(budget_status()["local_reserved_krw"], 68)
        self.assertEqual(budget_status()["requests_by_status"], {
            "failed_or_unknown": {"requests": 1, "reserved_krw": 68},
        })
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            reserve_google_output("video", "veo-3.1-lite-generate-001", 8)
        self.assertEqual(budget_status()["remaining_krw"], 432)
        with self.assertRaisesRegex(ValueError, "비용을 알 수 없는"):
            reserve_google_output("image", "unpriced-model")

    def test_parallel_requests_cannot_exceed_monthly_limit(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(reserve_google_output, "video", "veo-3.1-lite-generate-001", 8)
                     for _ in range(2)]
        self.assertEqual(sum(call.exception() is None for call in calls), 1)
        self.assertEqual(budget_status()["local_reserved_krw"], 480)
        with closing(sqlite3.connect(Path(self.directory.name) / "evaluation" / "google_budget.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)

    def test_month_mismatch_and_preflight_block(self):
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            check_google_budget(0.26)
        with patch.object(settings, "google_budget_month", "2026-09"):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                reserve_google_output("image", settings.image_model_id)

    def test_unreadable_ledger_fails_closed(self):
        ledger = Path(self.directory.name) / "evaluation" / "google_budget.sqlite3"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"not a sqlite database")
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
            reserve_google_output("image", settings.image_model_id)

    def test_video_and_image_stop_before_provider_call(self):
        video = object.__new__(VideoGenerator)
        video.logger = Mock()
        video.client = SimpleNamespace(models=SimpleNamespace(generate_videos=Mock()))
        video.image_client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock()))
        with patch.object(settings, "google_monthly_budget_krw", 1000):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                video._retry_veo_call(
                    "veo-3.1-lite-generate-001", "prompt", "unused.mp4", "fallback",
                    duration_seconds=8, request_budget_usd=0.30,
                )
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                video._run_image_generation(settings.image_model_id,
                                            SimpleNamespace(visual_description="scene"), "unused.png")
        video.client.models.generate_videos.assert_not_called()
        video.image_client.models.generate_content.assert_not_called()

        character = object.__new__(CharacterVideoGenerator)
        character.client = SimpleNamespace(models=SimpleNamespace(generate_videos=Mock()))
        character.logger = Mock()
        with patch.object(settings, "google_monthly_budget_krw", 1000):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                character._run_veo_generation(
                    "veo-3.1-lite-generate-001", "prompt", object(), "unused.mp4", 8,
                )
        character.client.models.generate_videos.assert_not_called()

    def test_budget_block_is_not_classified_as_a_retriable_500(self):
        video = object.__new__(VideoGenerator)
        video.logger = Mock()
        video.client = SimpleNamespace(models=SimpleNamespace(generate_videos=Mock()))
        with patch.object(settings, "google_monthly_budget_krw", 500), patch.object(
            settings, "google_budget_opening_krw", 500
        ), patch("shorts_maker.generator.video_generator.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_BUDGET_EXCEEDED"):
                video._retry_veo_call(
                    "veo-3.1-lite-generate-001", "prompt", "unused.mp4", "fallback",
                    duration_seconds=8, max_attempts=2, request_budget_usd=0.50,
                )
        sleep.assert_not_called()
        video.client.models.generate_videos.assert_not_called()
        self.assertEqual(len(list((Path(self.directory.name) / "evaluation" / "visual_attempts").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
