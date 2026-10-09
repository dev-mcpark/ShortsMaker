"""The local story diagram must keep its causal reveals behind the narration."""

import unittest
from PIL import ImageChops

from scripts.render_door_plug_storyboard import frame


class DoorPlugStoryboardTests(unittest.TestCase):
    def test_missing_inspection_and_accident_reveal_later(self):
        early_process = frame(4, 0.5, 6).crop((40, 420, 500, 600))
        late_process = frame(4, 3, 6).crop((40, 420, 500, 600))
        self.assertIsNotNone(ImageChops.difference(early_process, late_process).getbbox())

        early_accident = frame(5, 2.5, 6).crop((60, 510, 480, 610))
        late_accident = frame(5, 4, 6).crop((60, 510, 480, 610))
        self.assertIsNotNone(ImageChops.difference(early_accident, late_accident).getbbox())


if __name__ == "__main__":
    unittest.main()
