"""The free RSS review displays only escaped leads and skips paid planning."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.preview_rss_candidates import preview, render_html


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
            planner = planner_type.return_value
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
            planner = planner_type.return_value
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


if __name__ == "__main__":
    unittest.main()
