"""The approved one-shot runner must stay bounded and single-use."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import sillim_scene3_native_pilot as pilot


class SillimScene3NativePilotTests(unittest.TestCase):
    def test_one_mocked_submission_uses_approved_bounds_then_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            service_account = Path(directory) / "service_account.json"
            service_account.write_text("{}")
            self._check_submission(Path(directory), service_account)

    def _check_submission(self, output: Path, service_account: Path):
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
            client = Mock()
            generator = Mock(client=client)
            generator._retry_veo_call.side_effect = lambda *args, **kwargs: (
                (output / "scene_3.mp4").write_bytes(b"mock clip")
            )
            with patch.object(pilot, "VideoGenerator", return_value=generator):
                pilot.run()
            record = json.loads((output / "request.json").read_text())
            self.assertEqual(record["status"], "saved_unreviewed")
            self.assertEqual(record["estimated_output_usd"], 0.18)
            kwargs = generator._retry_veo_call.call_args.kwargs
            self.assertEqual(kwargs["max_attempts"], 1)
            self.assertEqual(kwargs["request_budget_usd"], 0.25)
            self.assertEqual(kwargs["first_frame_path"], str(pilot.FRAME))
            with self.assertRaisesRegex(RuntimeError, "already been used"):
                pilot.preflight()

    def test_provider_limit_is_recorded_without_retry(self):
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
