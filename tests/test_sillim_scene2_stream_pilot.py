"""The stream pilot spends at most one bounded request per approval."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import sillim_scene2_stream_pilot as pilot


class SillimScene2StreamPilotTests(unittest.TestCase):
    def test_one_mocked_submission_then_repeat_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            service_account = output / "service_account.json"
            service_account.write_text("{}")
            with (
                patch.object(pilot, "OUT", output),
                patch.object(pilot, "budget_status", return_value={"enabled": True}),
                patch.object(pilot, "check_google_budget") as budget,
                patch.object(pilot.settings, "paid_production_enabled", True),
                patch.object(pilot.settings, "max_visual_cost_usd", 1.0),
                patch.object(pilot.settings, "gcp_project_id", "test-project"),
                patch.object(pilot.settings, "gcp_location", "us-central1"),
                patch.object(pilot.settings, "service_account_path", service_account),
            ):
                generator = Mock(client=Mock())
                generator._retry_veo_call.side_effect = lambda *args, **kwargs: (
                    (output / "scene_2_stream.mp4").write_bytes(b"mock clip")
                )
                with patch.object(pilot, "VideoGenerator", return_value=generator):
                    pilot.run()
                record = json.loads((output / "request.json").read_text())
                self.assertEqual(record["status"], "saved_unreviewed")
                self.assertEqual(record["shot"], "stream")
                self.assertEqual(record["estimated_output_usd"], 0.12)
                self.assertIn("water stays below the banks", record["prompt"])
                budget.assert_called_once_with(0.12)
                kwargs = generator._retry_veo_call.call_args.kwargs
                self.assertEqual(kwargs["max_attempts"], 1)
                self.assertEqual(kwargs["request_budget_usd"], 0.15)
                self.assertEqual(kwargs["duration_seconds"], 4)
                self.assertEqual(kwargs["scene_number"], 2)
                self.assertEqual(kwargs["first_frame_path"], str(pilot.FRAME))
                with self.assertRaisesRegex(RuntimeError, "already been used"):
                    pilot.preflight()

    def test_provider_failure_consumes_attempt_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            service_account = output / "service_account.json"
            service_account.write_text("{}")
            with (
                patch.object(pilot, "OUT", output),
                patch.object(pilot, "budget_status", return_value={"enabled": True}),
                patch.object(pilot, "check_google_budget"),
                patch.object(pilot.settings, "paid_production_enabled", True),
                patch.object(pilot.settings, "max_visual_cost_usd", 1.0),
                patch.object(pilot.settings, "gcp_project_id", "test-project"),
                patch.object(pilot.settings, "gcp_location", "us-central1"),
                patch.object(pilot.settings, "service_account_path", service_account),
            ):
                generator = Mock(client=Mock())
                generator._retry_veo_call.side_effect = RuntimeError("RESOURCE_EXHAUSTED")
                with patch.object(pilot, "VideoGenerator", return_value=generator):
                    with self.assertRaisesRegex(RuntimeError, "RESOURCE_EXHAUSTED"):
                        pilot.run()
                record = json.loads((output / "request.json").read_text())
                self.assertEqual(record["status"], "provider_limited")
                generator._retry_veo_call.assert_called_once()
                with self.assertRaisesRegex(RuntimeError, "already been used"):
                    pilot.preflight()


if __name__ == "__main__":
    unittest.main()
