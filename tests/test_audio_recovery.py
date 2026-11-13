"""Explicit audio recovery never overwrites unknown bytes or silently buys new speech."""

import asyncio
from contextlib import ExitStack
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page
from shorts_maker.gui.components.audio_recovery import render_audio_recovery
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import audio_choices as audio
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class AudioRecoveryFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        p = patch.object(settings, 'output_dir', self.root);p.start();self.addCleanup(p.stop)
        self.target = script('Recovery target')
        self.path = audio.save_audio_choices(self.target, {'tts_voice':'nova','bgm_mood':'auto','bgm_track':'','bgm_volume':.2})
        self.path.write_bytes(b'{corrupt audio record')
        self.before = self.path.read_bytes()
        self.state = AppState(script=script('Previous work'), final_video_path='kept.mp4')
        self.state.confirm_script_review()
        self.state.remember_script_draft(self.state.script_editor_key(), '{unfinished')
        with self.assertRaises(ValueError):
            self.state.load_saved_script(self.target)
        self.expected = copy.deepcopy(self.state.audio_recovery)

class AudioRecoveryTests(AudioRecoveryFixture, unittest.TestCase):
    def test_failure_preserves_current_work_then_confirmed_reset_backs_up_both(self):
        self.assertEqual(self.state.final_video_path,'kept.mp4')
        self.assertEqual(self.state.script.title,'Previous work')
        self.assertEqual(self.path.read_bytes(),self.before)
        self.state.operating_scope={'fixture':'kept'}
        backup = self.state.recover_audio_choices(self.expected)
        self.assertEqual(backup.read_bytes(),self.before)
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.state.script,self.target)
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual(self.state.operating_scope,{'fixture':'kept'})
        self.assertIsNone(self.state.prepared_narration_manifest)
        self.assertEqual(self.state.tts_voice,'alloy')
        self.assertEqual(self.state.bgm_volume,0)
        self.assertTrue(list(self.root.rglob('draft_*.json')))
        self.assertIsNone(self.state.audio_recovery)

    def test_changed_record_stale_or_busy_state_is_rejected_before_backup(self):
        for flag in ('record','busy','target'):
            with self.subTest(flag=flag):
                self.path.write_bytes(self.before)
                self.state.pipeline_running=False;self.state.audio_recovery=copy.deepcopy(self.expected)
                if flag=='record':self.path.write_bytes(b'changed record')
                elif flag=='busy':self.state.pipeline_running=True
                else:self.state.audio_recovery=None
                before=self.path.read_bytes()
                with self.assertRaises(ValueError):self.state.recover_audio_choices(self.expected)
                self.assertEqual(self.path.read_bytes(),before)
                self.assertEqual(self.state.final_video_path,'kept.mp4')
                self.assertFalse(list(self.root.rglob('*.backup_*.json')))

    def test_backup_and_replace_failures_preserve_original_and_current_state(self):
        for operation in ('work','backup','replace'):
            with self.subTest(operation=operation):
                target=(patch.object(self.state,'_backup_text_work',side_effect=OSError('fixture')) if operation=='work'
                        else patch.object(audio.os,'link' if operation=='backup' else 'replace',side_effect=OSError('fixture')))
                with ExitStack() as stack:
                    if operation != 'work':
                        stack.enter_context(patch.object(self.state, '_backup_text_work', return_value=[]))
                    stack.enter_context(target)
                    with self.assertRaises(OSError):self.state.recover_audio_choices(self.expected)
                if operation == 'replace':
                    self.assertTrue(list(self.path.parent.glob('*.backup_*.json')))
                self.assertEqual(self.path.read_bytes(),self.before)
                self.assertEqual(self.state.final_video_path,'kept.mp4')
                self.assertFalse(list(self.path.parent.glob('.audio_backup_*')))

    def test_missing_track_record_and_strict_loader_remain_explicit(self):
        self.path.write_text(json.dumps({'script_sha256':audio.script_sha256(self.target.model_dump()),
            'choices':{'tts_voice':'nova','bgm_mood':'auto','bgm_track':'gone.mp3','bgm_volume':.2}}))
        with self.assertRaises(ValueError):self.state.load_saved_script(self.target)
        self.assertIsNotNone(self.state.audio_recovery)
        self.assertEqual(self.state.final_video_path,'kept.mp4')
        self.state.recover_audio_choices(copy.deepcopy(self.state.audio_recovery))
        self.assertEqual(self.state.bgm_track,'')

    def test_unsafe_or_oversized_original_cannot_be_reset(self):
        digest=audio.audio_choice_fingerprint(self.target)
        self.path.write_bytes(b'x'*(2*1024*1024+1))
        with self.assertRaises(ValueError):audio.load_audio_choices(self.target)
        with self.assertRaises(ValueError):audio.reset_audio_choices(self.target,digest)

        self.path.unlink();self.path.symlink_to(self.root/'missing')
        with self.assertRaises(ValueError):audio.reset_audio_choices(self.target,digest)

    def test_repaired_dependencies_require_reload_instead_of_resetting_working_choices(self):
        self.path.write_text(json.dumps({'script_sha256':audio.script_sha256(self.target.model_dump()),
            'choices':{'tts_voice':'nova','bgm_mood':'auto','bgm_track':'restored.mp3','bgm_volume':.2}}))
        raw=self.path.read_bytes()
        with patch.object(audio.BGMManager,'get_track_path',return_value=None):
            with self.assertRaises(ValueError):self.state.load_saved_script(self.target)
        expected=copy.deepcopy(self.state.audio_recovery)
        with patch.object(audio.BGMManager,'get_track_path',return_value='restored.mp3'):
            with self.assertRaisesRegex(ValueError,'다시 읽을 수'):
                self.state.recover_audio_choices(expected)
        self.assertEqual(self.path.read_bytes(),raw)
        self.assertEqual(self.state.final_video_path,'kept.mp4')
        self.assertFalse(list(self.path.parent.glob('*.backup_*.json')))


class AudioRecoveryUITests(AudioRecoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        p=patch.object(core,'loop',asyncio.get_running_loop());p.start();self.addCleanup(p.stop)
        self.client=Client(page('/audio-recovery'));self.addCleanup(self.client.delete)
        self.refresh=Mock()
        with self.client:render_audio_recovery(self.state,self.refresh)

    def click(self,label):
        button=next(e for e in reversed(list(self.client.elements.values())) if getattr(e,'text','')==label)
        with self.client:next(e.handler for e in button._event_listeners.values() if e.type=='click')(None)

    async def test_cancel_and_stale_dialog_preserve_work_then_explicit_recovery_refreshes(self):
        self.click('음성·음악 설정 복구 방법');self.click('취소')
        self.assertEqual(self.path.read_bytes(),self.before)
        self.click('음성·음악 설정 복구 방법')
        self.state.remember_script_draft(self.state.script_editor_key(),'{changed')
        with patch('shorts_maker.gui.components.audio_recovery.safe_notify') as notify:
            self.click('사본 보관 후 설정 복구·대본 열기')
            self.assertIn('바뀌었습니다',notify.call_args.args[0])
        self.assertEqual(self.path.read_bytes(),self.before)
        self.click('취소');self.click('음성·음악 설정 복구 방법')
        self.click('사본 보관 후 설정 복구·대본 열기')
        self.refresh.assert_called_once()
        self.assertEqual(self.state.script,self.target)
