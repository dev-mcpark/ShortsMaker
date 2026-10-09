"""Music auditions compare one picture edit with different audio streams."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.music_review import build_music_review


class MusicReviewTests(unittest.TestCase):
    def test_requires_same_video_distinct_audio_and_escapes_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cuts = [("무음 <기준>", root / "silent.mp4"),
                    ("곡 & 음성", root / "music.mp4")]
            for _, path in cuts:
                path.touch()
            output = root / "review.html"
            with patch("scripts.music_review.stream_hashes", side_effect=[
                {"v": "same", "a": "silent"}, {"v": "same", "a": "music"}
            ]):
                build_music_review(cuts, output, "잔잔한 <리듬>")
            page = output.read_text(encoding="utf-8")
            self.assertIn("무음 &lt;기준&gt;", page)
            self.assertIn("곡 &amp; 음성", page)
            self.assertIn("잔잔한 &lt;리듬&gt;", page)
            self.assertIn('src="music.mp4"', page)

            output.unlink()
            with patch("scripts.music_review.stream_hashes", side_effect=[
                {"v": "same", "a": "silent"}, {"v": "different", "a": "music"}
            ]):
                with self.assertRaisesRegex(ValueError, "identical video"):
                    build_music_review(cuts, output)
            self.assertFalse(output.exists())

            with patch("scripts.music_review.stream_hashes", side_effect=[
                {"v": "same", "a": "same"}, {"v": "same", "a": "same"}
            ]):
                with self.assertRaisesRegex(ValueError, "distinct audio"):
                    build_music_review(cuts, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
