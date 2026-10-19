"""Small explanatory insets keep the Veo scenes visible."""

import unittest

from PIL import ImageChops

from scripts.sillim_explanatory_composite import CARD_POSITION, REVEALS, proof_card


class SillimExplanatoryCompositeTests(unittest.TestCase):
    def test_insets_leave_most_of_the_footage_visible_and_reveal_the_relationship(self):
        self.assertNotIn(5, REVEALS)
        for scene, early, late in ((2, 1, 4), (3, 1, 4), (4, 1, 5)):
            with self.subTest(scene=scene):
                first, revealed = proof_card(scene, early), proof_card(scene, late)
                self.assertEqual(first.size, revealed.size)
                self.assertLess(first.width * first.height / (720 * 1280), 0.12)
                self.assertLess(CARD_POSITION[1] + first.height, 700)
                self.assertIsNotNone(ImageChops.difference(first, revealed).getbbox())

    def test_scene_four_stops_at_supported_temporary_storage(self):
        self.assertEqual(len(REVEALS[4]), 2)
        self.assertIsNone(ImageChops.difference(proof_card(4, 2.5), proof_card(4, 5)).getbbox())


if __name__ == "__main__":
    unittest.main()
