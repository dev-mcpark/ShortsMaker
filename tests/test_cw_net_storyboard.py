"""Keep the CW-Net cause and safety system reveals in the spoken order."""

import unittest

from PIL import ImageColor

from scripts import render_cw_net_storyboard as storyboard


class CwNetStoryboardTests(unittest.TestCase):
    def test_stop_is_shown_before_its_safety_cause(self):
        early = storyboard.frame(1, 0.5, 5.23)
        stopped = storyboard.frame(1, 3.4, 5.23)
        before_cause = storyboard.frame(4, 1.5, 6.37)
        after_cause = storyboard.frame(4, 4.0, 6.37)

        self.assertNotEqual(early.getpixel((180, 408)), ImageColor.getrgb(storyboard.RED))
        self.assertEqual(stopped.getpixel((180, 408)), ImageColor.getrgb(storyboard.RED))
        self.assertNotEqual(before_cause.getpixel((65, 195)), ImageColor.getrgb(storyboard.MINT))
        self.assertEqual(after_cause.getpixel((65, 195)), ImageColor.getrgb(storyboard.MINT))
        before_limit = storyboard.frame(6, 3.3, 6.69)
        after_limit = storyboard.frame(6, 4.0, 6.69)
        self.assertNotEqual(before_limit.getpixel((65, 480)), ImageColor.getrgb(storyboard.MUTED))
        self.assertEqual(after_limit.getpixel((65, 480)), ImageColor.getrgb(storyboard.MUTED))


if __name__ == "__main__":
    unittest.main()
