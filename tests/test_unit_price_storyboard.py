"""The unit-price scratch diagrams reveal the arithmetic after the question."""

import unittest

from PIL import Image, ImageChops

from scripts.render_unit_price_storyboard import BG, frame


class UnitPriceStoryboardTests(unittest.TestCase):
    def test_hypothetical_result_and_real_dispatch_price_reveal_later(self):
        for scene, box, before, after in (
            (2, (275, 255, 510, 455), 0.5, 3.0),
            (2, (80, 510, 460, 660), 0.5, 5.0),
            (3, (40, 370, 500, 550), 0.5, 3.0),
            (4, (35, 395, 505, 535), 3.0, 5.0),
        ):
            early = frame(scene, before, 7).crop(box)
            late = frame(scene, after, 7).crop(box)
            self.assertIsNotNone(ImageChops.difference(early, late).getbbox())

    def test_caption_region_stays_clear(self):
        for scene in range(1, 6):
            region = frame(scene, 5, 7).crop((0, 700, 540, 960))
            self.assertIsNone(ImageChops.difference(region, Image.new("RGB", region.size, BG)).getbbox())


if __name__ == "__main__":
    unittest.main()
