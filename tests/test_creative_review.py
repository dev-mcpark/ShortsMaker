"""Controlled creative comparisons must reject changes to the shared media stream."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.creative_review import build_review


class CreativeReviewTests(unittest.TestCase):
    def test_gallery_requires_exact_shared_stream_and_escapes_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = [root / name for name in ("base.mp4", "music.mp4", "captions.mp4")]
            for video in videos:
                video.touch()
            output = root / "review.html"
            names = ('A <기준>', 'B "음악"', "C 자막")
            hashes = [{"v": "video", "a": "base-audio"},
                      {"v": "video", "a": "new-audio"},
                      {"v": "new-video", "a": "base-audio"}]
            with self.assertRaisesRegex(ValueError, "HTML file"):
                build_review(*videos, videos[0], names)
            self.assertTrue(videos[0].exists())
            with patch("scripts.creative_review.stream_hashes", side_effect=hashes):
                build_review(*videos, output, names, "quiet < curiosity")
            page = output.read_text(encoding="utf-8")
            self.assertIn("A &lt;기준&gt;", page)
            self.assertIn("quiet &lt; curiosity", page)
            self.assertIn('src="base.mp4"', page)

            output.unlink()
            hashes[1] = {"v": "different-video", "a": "new-audio"}
            with patch("scripts.creative_review.stream_hashes", side_effect=hashes):
                with self.assertRaisesRegex(ValueError, "Music comparison"):
                    build_review(*videos, output, names)
            self.assertFalse(output.exists())

            hashes[1] = {"v": "video", "a": "new-audio"}
            hashes[2] = {"v": "new-video", "a": "different-audio"}
            with patch("scripts.creative_review.stream_hashes", side_effect=hashes):
                with self.assertRaisesRegex(ValueError, "Caption comparison"):
                    build_review(*videos, output, names)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
