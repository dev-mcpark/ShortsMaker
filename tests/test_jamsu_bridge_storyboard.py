"""The free Jamsu plan audition distinguishes the old and revised designs."""

import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageColor

from scripts.render_jamsu_bridge_storyboard import BG, PINK, frame, pilot_seed


class JamsuBridgeStoryboardTests(unittest.TestCase):
    def test_unlettered_pilot_states_keep_lower_bridge_fixed(self):
        proposed, revised = pilot_seed(True), pilot_seed(False)
        assets = Path(__file__).resolve().parents[1] / "assets"
        for image, filename in ((proposed, "jamsu_scene3_seed_v1.png"),
                                (revised, "jamsu_scene3_target_v1.png")):
            with Image.open(assets / filename) as saved:
                self.assertIsNone(ImageChops.difference(image, saved.convert("RGB")).getbbox())
        self.assertEqual(proposed.size, (720, 1280))
        self.assertEqual(proposed.getpixel((300, 415)), ImageColor.getrgb(PINK))
        self.assertNotEqual(revised.getpixel((300, 415)), ImageColor.getrgb(PINK))
        self.assertIsNone(ImageChops.difference(
            proposed.crop((100, 525, 620, 740)), revised.crop((100, 525, 620, 740))
        ).getbbox())
        self.assertIsNone(ImageChops.difference(
            proposed.crop((0, 960, 720, 1280)), revised.crop((0, 960, 720, 1280))
        ).getbbox())

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
