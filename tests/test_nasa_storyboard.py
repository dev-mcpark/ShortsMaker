"""Check the authored NASA review cue stays aligned as narration length changes."""

import unittest

from PIL import Image, ImageColor

from scripts import render_nasa_storyboard as storyboard


class NasaStoryboardTests(unittest.TestCase):
    def test_rover_cue_stays_at_second_phrase_and_progress_continues(self):
        original_photo = storyboard.PHOTO
        storyboard.PHOTO = Image.new("RGB", (2000, 1400), "#334455")
        try:
            before = storyboard.frame(5, 2.4, 6.16)
            after = storyboard.frame(5, 2.5, 6.16)
            late = storyboard.frame(5, 6.0, 6.16)
            mint = ImageColor.getrgb(storyboard.MINT)
            gold = ImageColor.getrgb(storyboard.GOLD)
            self.assertEqual(before.getpixel((32, 360)), mint)
            self.assertEqual(after.getpixel((282, 360)), mint)
            self.assertNotEqual(after.getpixel((450, 828)), gold)
            self.assertEqual(late.getpixel((450, 828)), gold)
        finally:
            storyboard.PHOTO = original_photo


if __name__ == "__main__":
    unittest.main()
