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
             "content": "<p>One <b>result</b></p>", "url": "https://example.com/story?a=1&b=2"},
            {"category": "City", "source": "News", "title": "Unsafe",
             "content": "Text", "url": "javascript:alert(1)"},
        ], ["City"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("story?a=1&amp;b=2", page)
        self.assertIn("One result", page)
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


if __name__ == "__main__":
    unittest.main()
