"""The free RSS review displays only escaped leads and skips paid planning."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.preview_rss_candidates import main, preview, render_html
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.config import settings


class RSSCandidatePreviewTests(unittest.TestCase):
    def test_render_escapes_untrusted_feed_text_and_rejects_bad_link(self):
        page = render_html([
            {"category": "City", "source": "News", "title": "<script>alert(1)</script>",
             "content": "<p>One <b>result</b></p>", "published": "<img src=x>",
             "url": "https://example.com/story?a=1&b=2"},
            {"category": "City", "source": "News", "title": "Unsafe",
             "content": "Text", "url": "javascript:alert(1)"},
            {"category": "City", "source": "News", "title": "Undated",
             "content": "Text", "url": "https://example.com/undated"},
        ], ["City"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("story?a=1&amp;b=2", page)
        self.assertIn("One result", page)
        self.assertIn("&lt;img src=x&gt;", page)
        self.assertIn("발행일 미표기", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("javascript:", page)

    def test_preview_uses_rss_discovery_without_topic_scoring(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.preview_rss_candidates.ScriptPlanner"
        ) as planner_type:
            planner = planner_type.for_rss_discovery.return_value
            planner.rss_sources = {"City": ["https://example.com/feed"]}
            planner._fetch_rss_feeds.return_value = [
                {"category": "City", "source": "News", "title": "A story",
                 "content": "Source summary", "url": "https://example.com/story"}
            ]
            output = Path(directory) / "preview.html"
            self.assertEqual(preview(["City"], output), output)
            self.assertIn("A story", output.read_text(encoding="utf-8"))
            planner._fetch_rss_feeds.assert_called_once_with()
            planner._score_topics.assert_not_called()
            with self.assertRaisesRegex(ValueError, "등록되지 않은"):
                preview(["Unknown"], output)
            self.assertEqual(planner._fetch_rss_feeds.call_count, 1)
            prior_page = output.read_text(encoding="utf-8")
            planner._fetch_rss_feeds.side_effect = RuntimeError("RSS_SOURCE_UNVERIFIED")
            with self.assertRaisesRegex(RuntimeError, "RSS_SOURCE_UNVERIFIED"):
                preview(["City"], output)
            self.assertEqual(output.read_text(encoding="utf-8"), prior_page)

    def test_expanded_preview_marks_difference_from_paid_pool(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.preview_rss_candidates.ScriptPlanner"
        ) as planner_type:
            planner = planner_type.for_rss_discovery.return_value
            planner.rss_sources = {"Life_Tips": ["https://example.com/feed"]}
            planner._fetch_rss_feeds.return_value = [
                {"category": "Life_Tips", "source": "Official", "title": "Completed change",
                 "content": "Observed outcome", "published": "2026-10-21",
                 "url": "https://example.com/story"}
            ]
            output = Path(directory) / "inventory.html"
            preview(["Life_Tips"], output, all_recent=True)

            page = output.read_text(encoding="utf-8")
            self.assertIn("읽힌 피드에서 수집 규칙을 통과한 최근 후보 전체", page)
            self.assertIn("2026-10-21", page)
            planner._fetch_rss_feeds.assert_called_once_with(limit_per_category=None)
            planner._score_topics.assert_not_called()

    def test_preview_runs_without_openai_key_or_paid_clients(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(settings, "openai_api_key", ""), \
                patch.object(settings, "rss_sources_file", Path(directory) / "sources.json"), \
                patch.object(settings, "url_history_file", Path(directory) / "history.json"), \
                patch.object(ScriptPlanner, "_fetch_rss_feeds", return_value=[]) as fetch, \
                patch("shorts_maker.planner.script_planner.AsyncOpenAI") as openai:
            output = Path(directory) / "preview.html"
            preview(["City_Life"], output)

            self.assertTrue(output.exists())
            fetch.assert_called_once_with()
            openai.assert_not_called()

    def test_command_preserves_previous_review_page(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(settings, "output_dir", Path(directory)), \
                patch("scripts.preview_rss_candidates.ScriptPlanner") as planner_type, \
                patch("sys.argv", ["preview_rss_candidates.py", "--category", "City"]), \
                patch("builtins.print"):
            planner = planner_type.for_rss_discovery.return_value
            planner.rss_sources = {"City": ["https://example.com/feed"]}
            planner._fetch_rss_feeds.side_effect = [
                [{"category": "City", "source": "News", "title": "First",
                  "content": "First lead", "url": "https://example.com/first"}],
                [{"category": "City", "source": "News", "title": "Second",
                  "content": "Second lead", "url": "https://example.com/second"}],
            ]
            main()
            main()

            pages = list((Path(directory) / "evaluation").glob("rss_candidate_preview_*.html"))
            self.assertEqual(len(pages), 2)
            contents = [page.read_text(encoding="utf-8") for page in pages]
            self.assertTrue(any("First lead" in page for page in contents))
            self.assertTrue(any("Second lead" in page for page in contents))


if __name__ == "__main__":
    unittest.main()
