"""Narration spending is bounded across interrupted runs and completed scenes survive."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_narration import prepare
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services import openai_budget
from shorts_maker.utils.config import settings


class PrepareNarrationTests(unittest.TestCase):
    def setUp(self):
        disabled = patch.object(settings, "openai_monthly_budget_usd", None)
        disabled.start()
        self.addCleanup(disabled.stop)

    def test_plan_requires_no_paid_access_and_refuses_oversized_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self._script(root)
            output = root / "narration"
            with patch.object(settings, "output_dir", root), patch.object(
                settings, "paid_production_enabled", False
            ), patch.object(VideoEditor, "_generate_tts") as tts:
                plan = asyncio.run(prepare(script, output, "nova", 0.02, 15, plan_only=True))
                self.assertEqual(plan["missing_scenes"], [1, 2])
                self.assertGreater(plan["cumulative_request_reserve_usd"], 0)
                self.assertFalse(output.exists())
                with self.assertRaisesRegex(ValueError, "exceeds ceiling"):
                    asyncio.run(prepare(script, output, "nova", 0.000001, 15))
                tts.assert_not_called()

    def test_interrupted_run_reuses_finished_scene_and_counts_prior_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self._script(root)
            output = root / "narration"
            calls = []

            async def first_attempt(_editor, text, scene_number, _voice, *, source_url):
                self.assertEqual(source_url, "https://example.com")
                calls.append(scene_number)
                if scene_number == 2:
                    raise RuntimeError("provider stopped")
                source = root / f"source_{scene_number}.mp3"
                source.write_bytes(b"scene one audio")
                return str(source)

            async def resumed_attempt(_editor, text, scene_number, _voice, *, source_url):
                self.assertEqual(source_url, "https://example.com")
                calls.append(scene_number)
                source = root / f"source_{scene_number}.mp3"
                source.write_bytes(b"scene two audio")
                return str(source)

            with patch.object(settings, "output_dir", root), patch.object(
                settings, "paid_production_enabled", True
            ), patch.object(settings, "openai_api_key", "test"), patch.object(
                VideoEditor, "validate_narration", return_value=None
            ):
                with patch.object(VideoEditor, "_generate_tts", first_attempt):
                    with self.assertRaisesRegex(RuntimeError, "provider stopped"):
                        asyncio.run(prepare(script, output, "nova", 0.02, 15))
                first_file = output / "scene_1.mp3"
                self.assertTrue(first_file.is_file())
                manifest = json.loads((output / "narration.json").read_text())
                self.assertEqual(manifest["scenes"]["1"]["status"], "complete")
                self.assertEqual(manifest["scenes"]["2"]["status"], "pending")
                prior_reserve = manifest["reserved_usd_total"]
                with patch.object(VideoEditor, "_generate_tts") as tts:
                    with self.assertRaisesRegex(ValueError, "Cumulative TTS"):
                        asyncio.run(prepare(script, output, "nova", prior_reserve, 15))
                    tts.assert_not_called()
                with patch.object(VideoEditor, "_generate_tts", resumed_attempt):
                    result = asyncio.run(prepare(script, output, "nova", 0.02, 15))
                self.assertEqual(calls, [1, 2, 2])
                self.assertEqual(first_file.read_bytes(), b"scene one audio")
                self.assertEqual(len(result["audio_paths"]), 2)
                self.assertTrue((output / "scene_2.mp3").is_file())

                script.write_text(script.read_text() + " ", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "different script"):
                    asyncio.run(prepare(script, output, "nova", 0.02, 15, plan_only=True))

    def test_monthly_budget_blocks_standalone_narration_before_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self._script(root)
            output = root / "narration"
            with patch.object(settings, "output_dir", root), patch.object(
                settings, "openai_monthly_budget_usd", 0.0051,
            ), patch.object(settings, "openai_budget_opening_usd", 0.005), patch.object(
                settings, "openai_budget_month", openai_budget._period(),
            ), patch.object(VideoEditor, "_generate_tts") as tts:
                openai_budget.initialize_openai_budget()
                with self.assertRaisesRegex(openai_budget.OpenAIBudgetExceeded, "내레이션 최대 예약액"):
                    asyncio.run(prepare(script, output, "nova", 0.02, 15))
                tts.assert_not_called()
                self.assertFalse(output.exists())
                self.assertEqual(openai_budget.budget_status()["local_reserved_usd"], 0)

    @staticmethod
    def _script(root: Path) -> Path:
        script = ShortsScript(
            title="Review", description="", tags=[], mood="sci-fi", style="plain",
            source_name="test", source_url="https://example.com", generation_mode="video",
            scenes=[VideoScene(scene_number=n, visual_description="diagram",
                               script_text=f"Scene {n} narration text") for n in (1, 2)],
        )
        path = root / "script.json"
        path.write_text(script.model_dump_json(), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
