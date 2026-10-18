"""Local scratch speech must remain script-bound and resumable."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_scratch_narration as scratch


class ScratchNarrationTests(unittest.TestCase):
    @staticmethod
    def script(path: Path) -> None:
        path.write_text(json.dumps({
            "title": "Test", "description": "Draft", "tags": [], "mood": "curious",
            "style": "test", "source_name": "Source", "source_url": "https://example.com",
            "generation_mode": "image", "scenes": [{
                "scene_number": 1, "visual_description": "Diagram",
                "script_text": "첫 번째 문장입니다.", "duration_seconds": 3,
            }],
        }, ensure_ascii=False), encoding="utf-8")

    def test_valid_output_is_recorded_reused_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "script.json"
            output = root / "outputs" / "scratch"
            self.script(script)

            def synthesize(command, check):
                Path(command[4]).write_bytes(b"valid local audio")

            with (patch.object(scratch.settings, "output_dir", root / "outputs"),
                  patch.object(scratch.subprocess, "run", side_effect=synthesize) as run,
                  patch.object(scratch, "_check_audio"),
                  patch.object(scratch.VideoEditor, "validate_narration")):
                paths = scratch.prepare(script, output)
                self.assertEqual(paths, [str((output / "scene_1.aiff").resolve())])
                self.assertEqual(scratch.prepare(script, output), paths)
                run.assert_called_once()
                record = json.loads((output / "narration.json").read_text())
                self.assertEqual(record["model"], "macos-say")
                self.assertEqual(record["scenes"]["1"]["status"], "complete")
                (output / "scene_1.aiff").write_bytes(b"changed audio")
                with self.assertRaisesRegex(ValueError, "file changed"):
                    scratch.prepare(script, output)

    def test_unplayable_output_stays_pending_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "script.json"
            output = root / "outputs" / "scratch"
            self.script(script)

            def synthesize(command, check):
                Path(command[4]).write_bytes(b"invalid")

            with (patch.object(scratch.settings, "output_dir", root / "outputs"),
                  patch.object(scratch.subprocess, "run", side_effect=synthesize) as run,
                  patch.object(scratch, "_check_audio", side_effect=ValueError("unplayable"))):
                with self.assertRaisesRegex(ValueError, "unplayable"):
                    scratch.prepare(script, output)
                self.assertFalse((output / "scene_1.aiff").exists())
                self.assertFalse((output / "scene_1.part.aiff").exists())
                record = json.loads((output / "narration.json").read_text())
                self.assertEqual(record["scenes"]["1"]["status"], "pending")
                with self.assertRaisesRegex(ValueError, "unplayable"):
                    scratch.prepare(script, output)
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
