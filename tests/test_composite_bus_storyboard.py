"""The scratch storyboard reveals only the source-backed claim at the right beat."""

import unittest
from pathlib import Path

from PIL import Image, ImageChops

from scripts.render_composite_bus_storyboard import BG, frame
from shorts_maker.planner.models import ShortsScript


class CompositeBusStoryboardTests(unittest.TestCase):
    def test_five_scene_draft_and_delayed_proof(self):
        draft = Path(__file__).resolve().parents[1] / "docs/composite_bus_review_draft.json"
        script = ShortsScript.model_validate_json(draft.read_text(encoding="utf-8"))
        self.assertEqual(len(script.scenes), 5)
        early = frame(4, 3.9, 7).crop((40, 480, 500, 600))
        late = frame(4, 4.3, 7).crop((40, 480, 500, 600))
        self.assertIsNotNone(ImageChops.difference(early, late).getbbox())

    def test_caption_region_stays_clear(self):
        blank = Image.new("RGB", (540, 200), BG)
        for scene in range(1, 6):
            with self.subTest(scene=scene):
                actual = frame(scene, 6, 8).crop((0, 700, 540, 900))
                self.assertIsNone(ImageChops.difference(actual, blank).getbbox())


if __name__ == "__main__":
    unittest.main()
