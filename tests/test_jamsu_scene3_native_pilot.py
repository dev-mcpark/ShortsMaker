"""The Jamsu paid pilot must preserve its pinned image, source, and one-shot bound."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import jamsu_scene3_native_pilot as pilot


class JamsuScene3NativePilotTests(unittest.TestCase):
    def test_unreviewed_frame_blocks_paid_submission(self):
        self.assertFalse(pilot.FRAME_APPROVED)
        with self.assertRaisesRegex(RuntimeError, "editorial verdict"):
            pilot.run()

    def test_one_mocked_submission_stays_budgeted_and_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            service_account = output / "service_account.json"
            service_account.write_text("{}")
            with (
                patch.object(pilot, "OUT", output),
                patch.object(pilot, "FRAME_APPROVED", True),
                patch.object(pilot, "budget_status", return_value={"enabled": True}),
                patch.object(pilot, "check_google_budget"),
                patch.object(pilot.settings, "paid_production_enabled", True),
                patch.object(pilot.settings, "max_visual_cost_usd", 1.0),
                patch.object(pilot.settings, "gcp_project_id", "test-project"),
                patch.object(pilot.settings, "gcp_location", "us-central1"),
                patch.object(pilot.settings, "service_account_path", service_account),
            ):
                generator = Mock(client=Mock())
                generator._retry_veo_call.side_effect = lambda *args, **kwargs: (
                    (output / "scene_3.mp4").write_bytes(b"mock clip")
                )
                with patch.object(pilot, "VideoGenerator", return_value=generator):
                    pilot.run()
                record = json.loads((output / "request.json").read_text())
                self.assertEqual(record["status"], "saved_unreviewed")
                self.assertEqual(record["first_frame_sha256"], pilot.FRAME_SHA256)
                self.assertEqual(record["estimated_output_usd"], 0.24)
                kwargs = generator._retry_veo_call.call_args.kwargs
                self.assertEqual(kwargs["max_attempts"], 1)
                self.assertEqual(kwargs["request_budget_usd"], 0.24)
                self.assertEqual(kwargs["source_url"], pilot.SOURCE_URL)
                self.assertEqual(kwargs["first_frame_path"], str(pilot.FRAME))
                with self.assertRaisesRegex(RuntimeError, "already been used"):
                    pilot.preflight()


if __name__ == "__main__":
    unittest.main()
