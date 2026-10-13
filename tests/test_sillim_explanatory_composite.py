"""Explanatory cards add the relationships missing from the raw Veo shots."""

import unittest

from PIL import Image, ImageChops

from scripts.render_sillim_depot_storyboard import frame
from scripts.sillim_explanatory_composite import proof_card


class SillimExplanatoryCompositeTests(unittest.TestCase):
    def test_missing_relationships_are_drawn_in_the_card(self):
        for scene, time, region in (
            (2, 4, (100, 400, 380, 455)),
            (3, 4, (150, 435, 340, 475)),
            (4, 5, (100, 400, 380, 475)),
        ):
            with self.subTest(scene=scene):
                original = frame(scene, time, 8).crop((0, 100, 540, 650))
                original = original.resize((480, 489), Image.Resampling.LANCZOS)
                revised = proof_card(scene, time).convert("RGB")
                self.assertIsNotNone(ImageChops.difference(
                    original.crop(region), revised.crop(region)
                ).getbbox())


if __name__ == "__main__":
    unittest.main()
