"""The free Jamsu plan audition distinguishes the old and revised designs."""

import unittest

from PIL import Image, ImageChops, ImageColor

from scripts.render_jamsu_bridge_storyboard import BG, PINK, frame


class JamsuBridgeStoryboardTests(unittest.TestCase):
    def test_plan_revisions_and_caption_space(self):
        self.assertEqual(frame(1, 1, 8).getpixel((100, 328)), ImageColor.getrgb(PINK))
        self.assertEqual(frame(1, 5, 8).getpixel((100, 328)), ImageColor.getrgb(BG))
        old = frame(3, 1, 8)
        revised = frame(3, 5, 8)
        self.assertEqual(old.getpixel((100, 328)), ImageColor.getrgb(PINK))
        self.assertEqual(revised.getpixel((100, 328)), ImageColor.getrgb(BG))
        self.assertIsNotNone(ImageChops.difference(
            frame(4, 0.5, 8).crop((130, 270, 410, 325)),
            frame(4, 2, 8).crop((130, 270, 410, 325))
        ).getbbox())
        for scene in range(1, 6):
            region = frame(scene, 5, 8).crop((0, 640, 540, 960))
            self.assertIsNone(ImageChops.difference(
                region, Image.new("RGB", region.size, BG)
            ).getbbox())


if __name__ == "__main__":
    unittest.main()
