"""The Jamsu paid pilot must preserve its pinned image, source, and one-shot bound."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import jamsu_scene4_native_pilot as pilot


class JamsuScene4NativePilotTests(unittest.TestCase):
    def test_unreviewed_frame_blocks_paid_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            review = json.loads(pilot.REVIEW.read_text(encoding="utf-8"))
            review.update(decision="pending", reviewer_note="")
            review_path = Path(directory) / "visual_review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            with patch.object(pilot, "REVIEW", review_path), patch.object(pilot, "preflight") as preflight, patch.object(pilot, "VideoGenerator") as generator:
                with self.assertRaisesRegex(RuntimeError, "editorial verdict"):
                    pilot.run()
                preflight.assert_not_called()
                generator.assert_not_called()

    def test_one_mocked_submission_stays_budgeted_and_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            service_account = output / "service_account.json"
            service_account.write_text("{}")
            review = json.loads(pilot.REVIEW.read_text(encoding="utf-8"))
            review.update(decision="approved", reviewer_note="The revised one-level deck and flush transparent panels are readable")
            review_path = output / "visual_review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            with (
                patch.object(pilot, "OUT", output),
                patch.object(pilot, "REVIEW", review_path),
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
                    (output / "scene_4.mp4").write_bytes(b"mock clip")
                )
                with patch.object(pilot, "VideoGenerator", return_value=generator):
                    pilot.run()
                record = json.loads((output / "request.json").read_text())
                self.assertEqual(record["status"], "saved_unreviewed")
                self.assertEqual(record["first_frame_sha256"], pilot.FRAME_SHA256)
                self.assertEqual(record["visual_review_sha256"], pilot.sha256(review_path))
                self.assertEqual(record["estimated_output_usd"], 0.24)
                kwargs = generator._retry_veo_call.call_args.kwargs
                self.assertEqual(kwargs["max_attempts"], 1)
                self.assertEqual(kwargs["request_budget_usd"], 0.24)
                self.assertEqual(kwargs["source_url"], pilot.SOURCE_URL)
                self.assertEqual(kwargs["first_frame_path"], str(pilot.FRAME))
                self.assertEqual(kwargs["expected_first_frame_sha256"], pilot.FRAME_SHA256)
                with self.assertRaisesRegex(RuntimeError, "already been used"):
                    pilot.preflight()

    def test_changed_motion_invalidates_visual_verdict(self):
        with patch.object(pilot, "PROMPT", pilot.PROMPT + " A new camera move."):
            with self.assertRaisesRegex(ValueError, "Visual review is stale"):
                pilot.visual_review_status()


if __name__ == "__main__":
    unittest.main()
