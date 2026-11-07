import asyncio
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.services import openai_budget
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.config import Settings, settings


class OpenAIBudgetTests(unittest.TestCase):
    def test_enabled_budget_requires_valid_amount_opening_and_month(self):
        with self.assertRaisesRegex(ValueError, "OpenAI 월 예산"):
            Settings(openai_monthly_budget_usd=1.0, openai_budget_opening_usd=None,
                     openai_budget_month="")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for name, value in (
            ("output_dir", Path(self.directory.name)),
            ("openai_monthly_budget_usd", 0.015),
            ("openai_budget_opening_usd", 0.005),
            ("openai_budget_month", openai_budget._period()),
        ):
            context = patch.object(settings, name, value)
            context.start()
            self.addCleanup(context.stop)

    def test_missing_ledger_fails_closed_and_initialization_is_one_time(self):
        with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "OPENAI_BUDGET_EXCEEDED"):
            openai_budget.reserve_openai_speech("tts-1", "안녕하세요")
        self.assertEqual(openai_budget.initialize_openai_budget()["opening_usd"], 0.005)
        with self.assertRaises(FileExistsError):
            openai_budget.initialize_openai_budget()

    def test_chat_and_each_speech_attempt_reserve_before_limit(self):
        openai_budget.initialize_openai_budget()
        messages = [{"role": "user", "content": "한국어 설명"}]
        openai_budget.reserve_openai_chat("gpt-4o-mini", messages, 1000)
        openai_budget.reserve_openai_speech("tts-1", "가" * 400)
        status = openai_budget.budget_status()
        self.assertGreater(status["reserved_by_model_usd"]["gpt-4o-mini"], 0)
        self.assertEqual(status["reserved_by_model_usd"]["tts-1"], 0.006)
        with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "OPENAI_BUDGET_EXCEEDED"):
            openai_budget.reserve_openai_speech("tts-1", "가" * 400)
        self.assertEqual(openai_budget.budget_status()["reserved_by_model_usd"]["tts-1"], 0.006)

    def test_old_ledger_keeps_shared_cost_when_source_column_is_added(self):
        openai_budget.initialize_openai_budget()
        ledger = openai_budget._database_path()
        with sqlite3.connect(ledger) as db:
            db.execute("DROP TABLE requests")
            db.execute("""CREATE TABLE requests (
                id TEXT PRIMARY KEY, period TEXT NOT NULL, model TEXT NOT NULL,
                reserved_micro_usd INTEGER NOT NULL, created_utc TEXT NOT NULL
            )""")
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                       ("old", openai_budget._period(), "gpt-4o-mini", 200,
                        "2026-10-01T00:00:00+00:00"))
        self.assertEqual(openai_budget.budget_status()["unattributed_reserved_usd"], 0.0002)

        source = "https://example.com/story"
        request_id = openai_budget.reserve_openai_speech("tts-1", "가" * 100,
                                                         source_url=source)
        with sqlite3.connect(ledger) as db:
            rows = db.execute("SELECT id, source_url FROM requests ORDER BY created_utc").fetchall()
        self.assertEqual(rows, [("old", None), (request_id, source)])
        status = openai_budget.budget_status()
        self.assertEqual(status["reserved_by_source_usd"], {source: 0.0015})
        self.assertEqual(status["unattributed_reserved_usd"], 0.0002)
        self.assertEqual(status["local_reserved_usd"], 0.0017)

    def test_narration_preflight_blocks_partial_set_without_reserving(self):
        openai_budget.initialize_openai_budget()
        with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "내레이션 최대 예약액"):
            openai_budget.check_openai_speech_budget("tts-1", ["가" * 100, "나" * 300], 2)
        self.assertEqual(openai_budget.budget_status()["local_reserved_usd"], 0)

        editor = VideoEditor(bgm_volume=0)
        editor._generate_tts = AsyncMock()
        script = SimpleNamespace(
            scenes=[SimpleNamespace(script_text="가" * 100),
                    SimpleNamespace(script_text="나" * 300)],
            mood="sci-fi", source_url="https://example.com/story",
        )
        with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "내레이션 최대 예약액"):
            asyncio.run(editor.prepare_narration(script))
        editor._generate_tts.assert_not_awaited()
        self.assertEqual(openai_budget.budget_status()["local_reserved_usd"], 0)

    def test_unknown_model_and_stale_month_block(self):
        openai_budget.initialize_openai_budget()
        with self.assertRaises(openai_budget.OpenAIBudgetExceeded):
            openai_budget.reserve_openai_chat("unpriced-model", [], 100)
        with patch.object(settings, "openai_budget_month", "2020-01"):
            with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "이번 달"):
                openai_budget.reserve_openai_speech("tts-1", "안녕하세요")

    def test_terra_reserves_full_completion_ceiling_and_preserves_failed_hold(self):
        openai_budget.initialize_openai_budget()
        messages = [{"role": "user", "content": "각본과 장면 검토"}]
        expected = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 1024 + 1500 * 5
        openai_budget.reserve_openai_chat('gpt-6.1-terra', messages, 1500)
        status = openai_budget.budget_status()
        self.assertAlmostEqual(status['reserved_by_model_usd']['gpt-6.1-terra'], expected / 1000000)
        with self.assertRaises(openai_budget.OpenAIBudgetExceeded):
            openai_budget.reserve_openai_chat('gpt-6.1-terra', messages, 1500)
        self.assertEqual(openai_budget.budget_status(), status)

    def test_parallel_scene_requests_cannot_both_spend_the_last_room(self):
        with patch.object(settings, "openai_monthly_budget_usd", 0.012):
            openai_budget.initialize_openai_budget()
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(self._try_speech, range(2)))
            self.assertEqual(sorted(outcomes), ["blocked", "reserved"])
            self.assertEqual(openai_budget.budget_status()["local_reserved_usd"], 0.006)

    @staticmethod
    def _try_speech(_):
        try:
            openai_budget.reserve_openai_speech("tts-1", "가" * 400)
            return "reserved"
        except openai_budget.OpenAIBudgetExceeded:
            return "blocked"

    def test_disabled_budget_never_creates_a_ledger(self):
        with patch.object(settings, "openai_monthly_budget_usd", None):
            self.assertIsNone(openai_budget.reserve_openai_chat("gpt-4o", [], 100))
            self.assertEqual(openai_budget.budget_status(), {"enabled": False})
        self.assertFalse(openai_budget._database_path().exists())

    def test_paid_call_sites_stop_before_submission_when_ledger_is_missing(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        planner.history_file = str(Path(self.directory.name) / "topic_history.json")
        chat_create = AsyncMock()
        planner.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=chat_create)))
        candidate = {"category": "City_Life", "title": "기사", "content": "출처 요약"}
        with patch("shorts_maker.planner.script_planner.require_paid_production_enabled"):
            with self.assertRaises(openai_budget.OpenAIBudgetExceeded):
                asyncio.run(planner._score_topics([candidate]))
        chat_create.assert_not_awaited()

        editor = VideoEditor(bgm_volume=0)
        speech_create = AsyncMock()
        editor.client = SimpleNamespace(audio=SimpleNamespace(
            speech=SimpleNamespace(create=speech_create)))
        with patch("shorts_maker.editor.video_editor.require_paid_production_enabled"), \
                patch.object(settings, "temp_dir", Path(self.directory.name)):
            with self.assertRaises(openai_budget.OpenAIBudgetExceeded):
                asyncio.run(editor._generate_tts("안녕하세요", 1, "nova"))
        speech_create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
