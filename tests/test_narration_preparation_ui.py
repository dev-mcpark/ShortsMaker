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

    async def partial_voice(self):
        service = ProductionService(editor_options={'tts_voice': 'nova'})
        async def first_only(*args, **kwargs):
            service.cancel()
            return str(self.audio)
        self.tts.side_effect = first_only
        quote = preparation.plan_narration(self.script, 'nova')
        with self.assertRaisesRegex(ValueError, '중지'):
            await service.prepare_narration(self.script, request_budget_usd=quote['additional_request_reserve_usd'])
        self.tts.side_effect = None
        return Path(quote['manifest_path'])

    def visual_revision(self):
        revised = self.script.model_copy(deep=True)
        revised.title = 'Changed visual plan'
        revised.scenes[0].visual_description = 'A wider, clearer view of the same bus'
        revised.scenes[0].motion_instruction = 'A small sideways camera move'
        revised.scenes.reverse()
        return revised

    async def test_visual_revision_reuses_partial_voice_profile_and_preserves_original_source(self):
        manifest = await self.partial_voice()
        source = manifest.with_name('script.json');source_bytes = source.read_bytes()
        first = manifest.with_name('scene_1.mp3');first_bytes = first.read_bytes()
        previous_hold = json.loads(manifest.read_text())['reserved_usd_total']
        revised = self.visual_revision()
        quote = preparation.plan_narration(revised, 'nova')
        self.assertEqual(quote['missing_scenes'], [2])
        self.assertEqual(quote['manifest_path'], str(manifest))
        self.assertEqual(quote['prior_request_reserve_usd'], previous_hold)
        result = await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(
            revised, request_budget_usd=quote['additional_request_reserve_usd'])
        self.assertEqual(result, str(manifest))
        self.assertEqual(self.tts.await_count, 2)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual([Path(p).name for p in narration_paths(revised, result)], ['scene_2.mp3', 'scene_1.mp3'])
        self.assertEqual(len(list((self.root/'evaluation/narration_preparation').glob('*/script.json'))), 1)
        self.assertAlmostEqual(json.loads(manifest.read_text())['reserved_usd_total'],
                               previous_hold + quote['additional_request_reserve_usd'])

    async def test_visual_revision_cannot_bypass_compatible_unknown_request_even_with_other_complete_set(self):
        self.tts.side_effect = RuntimeError('unknown provider result')
        with self.assertRaises(RuntimeError):
            await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(self.script, request_budget_usd=.02)
        revised = self.visual_revision()
        content, directory = preparation._profile(revised, 'nova')
        directory.mkdir(parents=True);directory.joinpath('script.json').write_bytes(content)
        retain_narration_set(revised, [str(self.audio)]*2, 'nova')
        before = {p:p.read_bytes() for p in self.root.rglob('*.json')}
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            preparation.plan_narration(revised, 'nova')
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(revised, request_budget_usd=.02)
        self.tts.assert_awaited_once()
        self.assertEqual(before, {p:p.read_bytes() for p in self.root.rglob('*.json')})

    async def test_partial_continuation_requires_same_voice_scene_text_and_source(self):
        await self.partial_voice()
        revised = self.visual_revision()
        changed_text = revised.model_copy(deep=True);changed_text.scenes[0].script_text = '다른 설명'
        changed_source = revised.model_copy(update={'source_url':'https://example.com/other'})
        for candidate, voice in ((changed_text,'nova'),(changed_source,'nova'),(revised,'alloy')):
            with self.subTest(voice=voice,title=candidate.title):
                quote = preparation.plan_narration(candidate, voice)
                self.assertEqual(set(quote['missing_scenes']), {1,2})
        self.tts.assert_awaited_once()

    async def test_same_speech_identity_is_locked_across_visual_revisions_and_processes(self):
        import sys
        manifest = await self.partial_voice()
        root = manifest.parent.parent
        locks = list(root.glob('.claims/*/.narration.lock.sqlite3'))
        self.assertEqual(len(locks), 1)
        code = ('import sqlite3,sys;db=sqlite3.connect(sys.argv[1],timeout=0,isolation_level=None);'
                'db.execute("BEGIN EXCLUSIVE");print("locked",flush=True);sys.stdin.readline();db.close()')
        child = await asyncio.create_subprocess_exec(sys.executable,'-c',code,str(locks[0]),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            self.assertEqual(await asyncio.wait_for(child.stdout.readline(),5), b'locked\n')
            with self.assertRaisesRegex(ValueError, 'NARRATION_IN_PROGRESS'):
                await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(
                    self.visual_revision(), request_budget_usd=.02)
            self.tts.assert_awaited_once()
            # Another narration identity can proceed; this is not a global production lock.
            other = self.script.model_copy(deep=True);other.scenes[0].script_text = 'A different narration'
            await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(other,request_budget_usd=.02)
            self.assertEqual(self.tts.await_count, 3)
        finally:
            if child.returncode is None:
                child.stdin.write(b'release\n');await child.stdin.drain()
                await asyncio.wait_for(child.wait(),5)
        quote = preparation.plan_narration(self.visual_revision(),'nova')
        await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(
            self.visual_revision(),request_budget_usd=quote['additional_request_reserve_usd'])
        self.assertEqual(self.tts.await_count, 4)
        self.assertEqual(json.loads(manifest.read_text())['scenes']['2']['status'], 'complete')

    async def test_candidate_source_is_bounded_and_linked_or_changed_matching_records_are_not_reused(self):
        manifest = await self.partial_voice()
        source = manifest.with_name('script.json');content = source.read_bytes()
        source.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
        self.assertIsNone(preparation._compatible_content(self.visual_revision(),'nova',source.parent))
        source.unlink();outside = self.root/'outside.json';outside.write_bytes(content)
        source.symlink_to(outside)
        self.assertIsNone(preparation._compatible_content(self.visual_revision(),'nova',source.parent))
        source.unlink();source.write_bytes(content)
        manifest.write_text('{invalid')
        with self.assertRaises(ValueError):
            preparation.plan_narration(self.visual_revision(),'nova')
        self.tts.assert_awaited_once()
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(manifest.read_text(), '{invalid')
        claims = manifest.parent.parent/'.claims'
        kept = claims.with_name('kept-claims');claims.rename(kept)
        outside_dir = self.root/'outside-claims';outside_dir.mkdir();claims.symlink_to(outside_dir)
        try:
            with self.assertRaisesRegex(ValueError, '잠금 경로'):
                await ProductionService(editor_options={'tts_voice':'nova'}).prepare_narration(
                    self.visual_revision(),request_budget_usd=.02)
            self.assertEqual(list(outside_dir.iterdir()), [])
            self.tts.assert_awaited_once()
        finally:
            claims.unlink();kept.rename(claims)

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

    def default_service(self):
        (self.root/'clip.mp4').write_bytes(b'local clip fixture')
        service=ProductionService(editor_options={'tts_voice':'nova','bgm_volume':0})
        service._valid_clip=Mock(return_value=True)
        editor=VideoEditor(tts_voice='nova',bgm_volume=0)
        editor.compose_video=AsyncMock(side_effect=RuntimeError('local edit stopped'))
        service._editor=editor
        service._get_generator=Mock(side_effect=AssertionError('manual clips need no provider'))
        return service,{scene.scene_number:str(self.root/'clip.mp4') for scene in self.script.scenes}

    async def test_default_edit_preserves_first_voice_and_does_not_replay_unknown_second_request(self):
        service,clips=self.default_service()
        self.tts.side_effect=[str(self.audio),RuntimeError('provider response unknown')]
        result=await service.produce_video(self.script,clips,retain_narration=True)
        self.assertFalse(result.success)
        self.assertIn('unknown',result.error)
        manifests=list(self.root.glob('evaluation/narration_preparation/*/narration.json'))
        self.assertEqual(len(manifests),1)
        record=json.loads(manifests[0].read_text())
        self.assertEqual(record['scenes']['1']['status'],'complete')
        self.assertEqual(record['scenes']['2']['status'],'pending')
        first=manifests[0].parent/'scene_1.mp3'
        before=first.read_bytes(),manifests[0].read_bytes()
        self.tts.reset_mock();self.tts.side_effect=None
        retry,clips=self.default_service()
        stopped=await retry.produce_video(self.script,clips,retain_narration=True)
        self.assertFalse(stopped.success)
        self.assertIn('UNVERIFIED',stopped.error)
        self.assertEqual(before,(first.read_bytes(),manifests[0].read_bytes()))
        self.tts.assert_not_awaited()
        service._editor.compose_video.assert_not_awaited()
        retry._editor.compose_video.assert_not_awaited()

    async def test_default_edit_cooperative_stop_and_resume_only_unstarted_voice(self):
        service,clips=self.default_service()
        async def speech(*args,**kw):
            service.cancel()
            return str(self.audio)
        self.tts.side_effect=speech
        result=await service.produce_video(self.script,clips,retain_narration=True)
        self.assertFalse(result.success)
        self.assertEqual(self.tts.await_count,1)
        self.assertIn('보존',result.error)
        service._editor.compose_video.assert_not_awaited()
        quote=preparation.plan_narration(self.script,'nova')
        self.assertEqual(quote['missing_scenes'],[2])
        self.tts.reset_mock();self.tts.side_effect=None
        retry,clips=self.default_service()
        stopped=await retry.produce_video(self.script,clips,retain_narration=True)
        self.assertFalse(stopped.success)
        self.assertIn('local edit stopped',stopped.error)
        self.tts.assert_awaited_once()
        quote=preparation.plan_narration(self.script,'nova')
        self.assertEqual(quote['additional_request_reserve_usd'],0)
        self.assertTrue(Path(quote['manifest_path']).is_file())
        VideoEditor.validate_narration(narration_paths(self.script,quote['manifest_path']))

    async def test_default_success_uses_one_manifest_and_stable_scene_order_with_resolved_auto_voice(self):
        self.script.scenes=[self.script.scenes[0].model_copy(update={'scene_number':7}),self.script.scenes[1]]
        service,clips=self.default_service()
        service._editor.tts_voice='auto'
        voice=service._editor._get_voice_for_mood(self.script.mood)
        output=self.root/'fixture-final.mp4';output.write_bytes(b'local mocked editor output')
        service._editor.compose_video.side_effect=None
        service._editor.compose_video.return_value=str(output)
        with patch('shorts_maker.services.production_service.check_video_quality'):
            result=await service.produce_video(self.script,clips,retain_narration=True)
        self.assertTrue(result.success,result.error)
        quote=preparation.plan_narration(self.script,voice)
        self.assertEqual(result.narration_manifest_path,quote['manifest_path'])
        self.assertEqual(service._editor.prepared_narration_manifest,quote['manifest_path'])
        self.assertFalse((self.root/'evaluation/narration_sets').exists())
        paths=narration_paths(self.script,result.narration_manifest_path)
        self.assertEqual([Path(p).stem for p in paths],['scene_7','scene_2'])
        self.assertEqual([call.args[1] for call in self.tts.await_args_list],[7,2])
        self.assertEqual([call.args[2] for call in self.tts.await_args_list],[voice,voice])
        self.assertTrue(all(call.kwargs['source_url']==self.script.source_url for call in self.tts.await_args_list))
        VideoEditor.validate_narration(paths,self.script)

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
