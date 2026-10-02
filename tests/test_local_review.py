"""The local review command must fail before production when an input is incomplete."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.local_review import collect_local_inputs, render_local
from shorts_maker.planner.models import ShortsScript, VideoScene


class LocalReviewTests(unittest.TestCase):
    def test_complete_local_inputs_required_before_service(self):
        script = ShortsScript(
            title="Review", description="", tags=[], mood="calm", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=n, visual_description="diagram", script_text="line") for n in (1, 2)],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in (1, 2):
                (root / f"scene_{number}.mp4").touch()
                (root / f"scene_{number}.aiff").touch()
            clips, audio = collect_local_inputs(script, root, root)
            self.assertEqual(set(clips), {1, 2})
            self.assertEqual([Path(path).name for path in audio], ["scene_1.aiff", "scene_2.aiff"])

            (root / "scene_2.mp4").unlink()
            with patch("scripts.local_review.ProductionService") as service:
                with self.assertRaisesRegex(FileNotFoundError, "scene_2.mp4"):
                    asyncio.run(render_local(script, root, root, 0.4))
                service.assert_not_called()

            (root / "scene_2.mp4").touch()
            (root / "scene_1.aiff").unlink()
            with patch("scripts.local_review.ProductionService") as service:
                with self.assertRaisesRegex(ValueError, "scene 1, found 0"):
                    asyncio.run(render_local(script, root, root, 0.4))
                service.assert_not_called()

            (root / "scene_1.aiff").touch()
            (root / "scene_2.mp3").touch()
            with self.assertRaisesRegex(ValueError, "scene 2, found 2"):
                collect_local_inputs(script, root, root)


if __name__ == "__main__":
    unittest.main()
