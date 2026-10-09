"""The Sillim diagram reveals its hidden facility and caveat with narration."""

import unittest
from PIL import Image, ImageChops

from scripts.render_sillim_depot_storyboard import BG, frame


class SillimDepotStoryboardTests(unittest.TestCase):
    def test_tank_and_attribution_appear_later(self):
        early_tank = frame(3, 1, 7).crop((58, 438, 482, 566))
        late_tank = frame(3, 4, 7).crop((58, 438, 482, 566))
        self.assertIsNotNone(ImageChops.difference(early_tank, late_tank).getbbox())

        early_caveat = frame(5, 2, 8).crop((75, 490, 470, 590))
        late_caveat = frame(5, 6, 8).crop((75, 490, 470, 590))
        self.assertIsNotNone(ImageChops.difference(early_caveat, late_caveat).getbbox())

    def test_caption_region_is_clear_in_every_scene(self):
        blank = Image.new("RGB", (540, 200), BG)
        for scene in range(1, 6):
            with self.subTest(scene=scene):
                bottom = frame(scene, 6, 8).crop((0, 700, 540, 900))
                self.assertIsNone(ImageChops.difference(bottom, blank).getbbox())


if __name__ == "__main__":
    unittest.main()
