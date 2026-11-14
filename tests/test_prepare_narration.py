"""Narration spending is bounded across interrupted runs and completed scenes survive."""

import asyncio
import hashlib
import json
import tempfile
import os
import subprocess
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from shorts_maker.services.narration_preparation import prepare, _narration_lock
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services import openai_budget
from shorts_maker.services import openai_models
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
                before_manifest=(output/'narration.json').read_bytes()
                with patch.object(VideoEditor, '_generate_tts') as tts:
                    for cap in (prior_reserve, .02):
                        with self.assertRaisesRegex(ValueError, 'NARRATION_REQUEST_UNVERIFIED'):
                            asyncio.run(prepare(script, output, 'nova', cap, 15))
                    tts.assert_not_called()
                self.assertEqual((output/'narration.json').read_bytes(),before_manifest)
                # Simulate an already returned file whose final manifest update was interrupted.
                (output/'scene_2.mp3').write_bytes(b'reconciled existing audio')
                with patch.object(settings,'paid_production_enabled',False), patch.object(settings,'openai_api_key',''), \
                        patch.object(VideoEditor,'_generate_tts') as tts, \
                        patch('shorts_maker.services.narration_preparation.check_openai_speech_budget') as budget:
                    result=asyncio.run(prepare(script,output,'nova',.02,15))
                    tts.assert_not_called();budget.assert_not_called()
                self.assertEqual(calls,[1,2])
                self.assertEqual(first_file.read_bytes(),b'scene one audio')
                self.assertEqual(len(result['audio_paths']),2)
                self.assertEqual(json.loads((output/'narration.json').read_text())['reserved_usd_total'],prior_reserve)

                script.write_text(script.read_text() + " ", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "different script"):
                    asyncio.run(prepare(script, output, "nova", 0.02, 15, plan_only=True))

    def test_unknown_pending_request_is_never_replayed_with_more_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=self._script(root);output=root/'narration';output.mkdir()
            story=ShortsScript.model_validate_json(script.read_text())
            manifest={'schema_version':1,'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                'model':VideoEditor.TTS_MODEL,'voice':'nova','usd_per_million_characters':15,
                'reserved_usd_total':.001,'scenes':{'1':{'status':'pending',
                    'text_sha256':hashlib.sha256(story.scenes[0].script_text.encode()).hexdigest()}}}
            path=output/'narration.json';path.write_text(json.dumps(manifest));before=path.read_bytes()
            with patch.object(settings,'output_dir',root),patch.object(settings,'paid_production_enabled',True), \
                    patch.object(settings,'openai_api_key','test'),patch.object(VideoEditor,'_generate_tts',side_effect=RuntimeError('unexpected paid boundary')) as tts:
                with self.assertRaisesRegex(ValueError,'NARRATION_REQUEST_UNVERIFIED'):
                    asyncio.run(prepare(script,output,'nova',1.0,15))
                tts.assert_not_called()
            self.assertEqual(path.read_bytes(),before)

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

    def test_retirement_blocks_missing_voice_but_allows_completed_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self._script(root)
            output = root / 'narration'
            with patch.object(settings, 'output_dir', root), patch.object(
                openai_models, 'datetime', **{
                    'now.return_value': datetime(2027, 1, 6, tzinfo=timezone.utc),
                },
            ), patch.object(VideoEditor, '_generate_tts') as tts:
                with self.assertRaises(openai_models.ModelMigrationRequired):
                    asyncio.run(prepare(script, output, 'nova', .02, 15, plan_only=True))
                self.assertFalse(output.exists())
                # Only the cache-routing contract is mocked, not media quality.
                with patch('shorts_maker.services.narration_preparation._scene_state', return_value='complete'):
                    plan = asyncio.run(prepare(script, output, 'nova', .02, 15, plan_only=True))
                self.assertEqual(plan['missing_scenes'], [])
                self.assertEqual(plan['additional_request_reserve_usd'], 0)
                tts.assert_not_called()

    def test_process_lock_blocks_duplicate_work_and_releases_after_child_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'narration';output.mkdir()
            child=subprocess.Popen([sys.executable,'-c',
                'import sys; from pathlib import Path; from shorts_maker.services.narration_preparation import _narration_lock\n'
                'with _narration_lock(Path(sys.argv[1])):\n print("locked",flush=True);sys.stdin.read()\n',
                str(output)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                env={**os.environ,'OUTPUT_DIR':str(root/'child-output')})
            try:
                self.assertEqual(child.stdout.readline().strip(),'locked')
                script=self._script(root)
                with patch.object(settings,'output_dir',root), patch.object(settings,'paid_production_enabled',True), \
                        patch.object(settings,'openai_api_key','test'),patch.object(VideoEditor,'_generate_tts') as tts:
                    with self.assertRaisesRegex(ValueError,'NARRATION_IN_PROGRESS'):
                        asyncio.run(prepare(script,output,'nova',.02,15))
                    tts.assert_not_called()
                self.assertFalse((output/'narration.json').exists())
                child.terminate();child.wait(timeout=5)
                with _narration_lock(output):pass
                self.assertEqual((output/'.narration.lock.sqlite3').stat().st_mode & 0o777,0o600)
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                for stream in (child.stdin,child.stdout,child.stderr):stream.close()

    def test_pending_or_changed_state_during_preflight_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=self._script(root);output=root/'narration'
            def changed(*args):
                output.mkdir()
                (output/'narration.json').write_text('{}')
            with patch.object(settings,'output_dir',root),patch.object(settings,'paid_production_enabled',True), \
                    patch.object(settings,'openai_api_key','test'),patch.object(VideoEditor,'_generate_tts') as tts, \
                    patch('shorts_maker.services.narration_preparation.check_openai_speech_budget',side_effect=changed):
                with self.assertRaises(ValueError):asyncio.run(prepare(script,output,'nova',.02,15))
                tts.assert_not_called()
            self.assertEqual((output/'narration.json').read_text(),'{}')

    def test_bad_pending_output_or_manifest_stops_before_other_missing_scene_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=self._script(root);output=root/'narration';output.mkdir()
            story=ShortsScript.model_validate_json(script.read_bytes())
            entry={'status':'pending','text_sha256':hashlib.sha256(story.scenes[1].script_text.encode()).hexdigest()}
            base={'schema_version':1,'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                  'model':VideoEditor.TTS_MODEL,'voice':'nova','usd_per_million_characters':15,
                  'reserved_usd_total':.001,'scenes':{'2':entry}}
            (output/'scene_2.mp3').write_bytes(b'corrupt existing output')
            path=output/'narration.json'
            for change in ({}, {'scenes':{'2':[]}}, {'reserved_usd_total':False}):
                path.write_text(json.dumps({**base,**change}));before=path.read_bytes()
                with patch.object(settings,'output_dir',root),patch.object(VideoEditor,'_generate_tts') as tts, \
                        patch('shorts_maker.services.narration_preparation.check_openai_speech_budget') as budget:
                    with self.assertRaises(ValueError):asyncio.run(prepare(script,output,'nova',.02,15))
                    tts.assert_not_called();budget.assert_not_called()
                self.assertEqual(path.read_bytes(),before)

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
