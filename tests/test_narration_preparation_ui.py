"""Standalone app speech uses checkpointed existing services and explicit consent."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from moviepy import AudioClip
from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.gui.components import narration_prepare
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import narration_preparation as preparation
from shorts_maker.services.prepared_narration import narration_paths, retain_narration_set
from shorts_maker.services.production_service import ProductionService
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class NarrationPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in [('output_dir', self.root), ('paid_production_enabled', True),
                            ('openai_api_key', 'offline-fixture'), ('openai_monthly_budget_usd', None)]:
            self.enterContext(patch.object(settings, name, value))
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        self.script = script()
        self.script.scenes.append(self.script.scenes[0].model_copy(update={'scene_number': 2, 'script_text': '두 번째 설명입니다.'}))
        self.audio = self.root / 'tone.mp3'
        clip = AudioClip(lambda t: .2 * np.sin(2 * np.pi * 440 * t), duration=.8, fps=16000)
        try:
            clip.write_audiofile(str(self.audio), fps=16000, logger=None)
        finally:
            clip.close()
        self.tts = self.enterContext(patch.object(VideoEditor, '_generate_tts', new_callable=AsyncMock, return_value=str(self.audio)))

    async def test_quote_readonly_then_service_prepares_real_decodable_audio_without_visuals_or_music(self):
        before = set(self.root.rglob('*'))
        quote = preparation.plan_narration(self.script, 'nova')
        self.assertEqual(before, set(self.root.rglob('*')))
        self.assertEqual(quote['missing_scenes'], [1, 2])
        service = ProductionService(editor_options={'tts_voice': 'nova', 'bgm_track': 'does-not-exist.mp3'})
        with patch.object(service, '_get_generator', side_effect=AssertionError('no visuals')), \
                patch.object(service, '_get_editor', side_effect=AssertionError('no edit')):
            manifest = await service.prepare_narration(self.script, request_budget_usd=quote['additional_request_reserve_usd'])
        paths = narration_paths(self.script, manifest)
        VideoEditor.validate_narration(paths)
        self.assertEqual(self.tts.await_count, 2)
        saved = Path(manifest).read_bytes()
        with patch.object(settings, 'paid_production_enabled', False), patch.object(settings, 'openai_api_key', ''):
            self.assertEqual(await service.prepare_narration(self.script, request_budget_usd=0), manifest)
        self.assertEqual(Path(manifest).read_bytes(), saved)
        self.assertEqual(self.tts.await_count, 2)

    async def test_cancel_retains_current_scene_and_resume_only_buys_unstarted_scene(self):
        service = ProductionService(editor_options={'tts_voice': 'nova'})
        entered, release = asyncio.Event(), asyncio.Event()
        async def speech(*args, **kwargs):
            entered.set(); await release.wait()
            return str(self.audio)
        self.tts.side_effect = speech
        quote = preparation.plan_narration(self.script, 'nova')
        task = asyncio.create_task(service.prepare_narration(self.script, request_budget_usd=quote['additional_request_reserve_usd']))
        await asyncio.wait_for(entered.wait(), 5); service.cancel(); release.set()
        with self.assertRaisesRegex(ValueError, '중지'):
            await task
        manifest = Path(quote['manifest_path'])
        record = json.loads(manifest.read_text())
        self.assertEqual(list(record['scenes']), ['1'])
        self.assertEqual(record['scenes']['1']['status'], 'complete')
        first = manifest.parent.joinpath('scene_1.mp3').read_bytes()
        next_quote = preparation.plan_narration(self.script, 'nova')
        self.assertEqual(next_quote['missing_scenes'], [2])
        self.tts.side_effect = None
        await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(
            self.script, request_budget_usd=next_quote['additional_request_reserve_usd'])
        self.assertEqual(self.tts.await_count, 2)
        self.assertEqual(manifest.parent.joinpath('scene_1.mp3').read_bytes(), first)

    async def test_unknown_provider_failure_cannot_be_replayed_and_zero_quote_never_buys(self):
        self.tts.side_effect = RuntimeError('unknown request result')
        service = ProductionService(editor_options={'tts_voice':'nova'})
        with self.assertRaisesRegex(ValueError, '상한'):
            await service.prepare_narration(self.script, request_budget_usd=0)
        self.tts.assert_not_awaited()
        with self.assertRaisesRegex(RuntimeError, 'unknown'):
            await service.prepare_narration(self.script, request_budget_usd=.02)
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await service.prepare_narration(self.script, request_budget_usd=1)
        self.tts.assert_awaited_once()

    async def test_existing_matching_voice_reused_and_changed_quote_zero_fails_closed(self):
        retained = retain_narration_set(self.script, [str(self.audio)]*2, 'nova')
        quote = preparation.plan_narration(self.script, 'nova')
        self.assertEqual(quote['manifest_path'], retained)
        self.assertEqual(quote['additional_request_reserve_usd'], 0)
        Path(retained).unlink()
        with self.assertRaisesRegex(ValueError, '상한'):
            await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(self.script, request_budget_usd=0)
        self.tts.assert_not_awaited()

    async def test_known_pending_file_reconciles_locally_without_becoming_new_speech(self):
        service = ProductionService(editor_options={'tts_voice':'nova'})
        manifest = Path(await service.prepare_narration(self.script, request_budget_usd=.02))
        record = json.loads(manifest.read_text())
        reserve = record['reserved_usd_total']
        record['scenes']['2']['status'] = 'pending'
        manifest.write_text(json.dumps(record))
        self.tts.reset_mock()
        with patch.object(settings, 'paid_production_enabled', False), patch.object(settings, 'openai_api_key', ''):
            await service.prepare_narration(self.script, request_budget_usd=0)
        record = json.loads(manifest.read_text())
        self.assertEqual(record['scenes']['2']['status'], 'complete')
        self.assertEqual(record['reserved_usd_total'], reserve)
        self.tts.assert_not_awaited()

    def render(self):
        self.state = AppState(script=self.script, final_video_path='existing.mp4', tts_voice='nova')
        self.state.confirm_script_review()
        self.client = Client(page('/narration-only-test')); self.addCleanup(self.client.delete)
        with self.client:
            narration_prepare.render_narration_prepare(self.state, Mock())

    async def click(self, text):
        button = next(e for e in reversed(list(self.client.elements.values())) if getattr(e, 'text', '') == text)
        handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
        with self.client:
            before = asyncio.all_tasks()
            result = handler(None)
            if asyncio.iscoroutine(result):
                await result
            tasks = asyncio.all_tasks() - before
            if tasks:
                await asyncio.gather(*tasks)

    async def test_native_confirmation_connects_without_clearing_result_before_completion(self):
        self.render()
        service = ProductionService(editor_options={'tts_voice':'nova'})
        with patch.object(self.state, 'new_production_service', return_value=service):
            await self.click('음성만 준비 · 비용 확인')
            self.tts.assert_not_awaited()
            self.assertEqual(self.state.final_video_path, 'existing.mp4')
            await self.click('확인 후 음성만 준비')
        self.assertFalse(self.state.is_busy)
        self.assertTrue(self.state.prepared_narration_manifest)
        self.assertIsNone(self.state.final_video_path)
        VideoEditor.validate_narration(self.state.prepared_audio_paths())

    async def test_native_stale_confirmation_busy_unreviewed_draft_and_selected_voice_do_not_submit(self):
        self.render()
        with patch.object(self.state, 'new_production_service', side_effect=AssertionError('must not submit')):
            await self.click('음성만 준비 · 비용 확인')
            self.state.tts_voice = 'alloy'
            await self.click('확인 후 음성만 준비')
            for change in ({'pipeline_running':True}, {'reviewed_script_sha256':None}, {'prepared_narration_manifest':'invalid'}):
                for key,value in change.items(): setattr(self.state,key,value)
                await self.click('음성만 준비 · 비용 확인')
                self.state.pipeline_running=False
                self.state.confirm_script_review()
        self.tts.assert_not_awaited()
        self.assertEqual(self.state.final_video_path, 'existing.mp4')

    async def test_native_task_cancellation_awaits_saved_request_and_preserves_result(self):
        self.render()
        service = ProductionService(editor_options={'tts_voice':'nova'})
        entered, release = asyncio.Event(), asyncio.Event()
        async def speech(*args, **kwargs):
            entered.set(); await release.wait(); return str(self.audio)
        self.tts.side_effect = speech
        with patch.object(self.state, 'new_production_service', return_value=service):
            await self.click('음성만 준비 · 비용 확인')
            task = asyncio.create_task(self.click('확인 후 음성만 준비'))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel(); await asyncio.sleep(0)
            self.assertTrue(self.state.is_busy)
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(self.state.is_busy)
        self.assertEqual(self.state.final_video_path, 'existing.mp4')
        self.assertIsNone(self.state.prepared_narration_manifest)
        quote = preparation.plan_narration(self.script, 'nova')
        self.assertEqual(quote['missing_scenes'], [2])

    async def test_native_lower_budget_and_deleted_quote_view_cannot_submit(self):
        self.render()
        with patch.object(narration_prepare, 'budget_status', return_value={'enabled': True, 'remaining_usd': 0}), \
                patch.object(self.state, 'new_production_service', side_effect=AssertionError('no submit')):
            await self.click('음성만 준비 · 비용 확인')
        self.assertIn('초과', self.state.narration_preparation_message)
        self.assertFalse(any(getattr(e, 'text', '') == '확인 후 음성만 준비' for e in self.client.elements.values()))
        import threading
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        original = narration_prepare.plan_narration
        def held(*args):
            import time
            loop.call_soon_threadsafe(entered.set)
            while not release.is_set(): time.sleep(.01)
            return original(*args)
        with patch.object(narration_prepare, 'plan_narration', side_effect=held):
            task = asyncio.create_task(self.click('음성만 준비 · 비용 확인'))
            await asyncio.wait_for(entered.wait(), 5)
            self.client.content.clear()
            release.set()
            await task
        self.tts.assert_not_awaited()
