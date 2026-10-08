"""Keep the measured result and modeled forecast in their spoken order."""

import unittest

from PIL import ImageColor

from scripts import render_wind_tunnel_storyboard as storyboard


class WindTunnelStoryboardTests(unittest.TestCase):
    def test_result_and_modeled_farm_reveal_after_setup(self):
        before_result = storyboard.frame(2, 3.2, 5.39)
        after_result = storyboard.frame(2, 3.6, 5.39)
        before_forecast = storyboard.frame(5, 2.6, 6.76)
        after_forecast = storyboard.frame(5, 3.0, 6.76)
        self.assertNotEqual(before_result.getpixel((64, 550)), ImageColor.getrgb(storyboard.MINT))
        self.assertEqual(after_result.getpixel((64, 550)), ImageColor.getrgb(storyboard.MINT))
        self.assertNotEqual(before_forecast.getpixel((47, 560)), ImageColor.getrgb(storyboard.GOLD))
        self.assertEqual(after_forecast.getpixel((47, 560)), ImageColor.getrgb(storyboard.GOLD))


if __name__ == "__main__":
    unittest.main()
