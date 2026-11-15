"""Manual script edits preserve explicit speech selection, without new TTS or approval."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from moviepy import AudioClip

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ShortsScript
from shorts_maker.services import audio_choices
from shorts_maker.services.prepared_narration import retain_narration_set, speech_identity
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script, callback


class ScriptAudioEditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        override = patch.object(settings,'output_dir',self.root);override.start();self.addCleanup(override.stop)
        self.original = script('Original selection')
        self.original.scenes.append(self.original.scenes[0].model_copy(update={
            'scene_number':2,'script_text':'두 번째 설명입니다.'}))
        tone = self.root/'tone.mp3'
        with AudioClip(lambda t:.2*np.sin(2*np.pi*440*t),duration=.8,fps=16000) as clip:
            clip.write_audiofile(str(tone),fps=16000,logger=None)
        self.manifest = retain_narration_set(self.original,[str(tone)]*2,'nova')
        self.state = self.bound_state()

    def bound_state(self):
        state = AppState(script=self.original,tts_voice='alloy',bgm_mood='auto',bgm_volume=.37)
        state.select_prepared_narration(self.manifest)
        state.confirm_script_review();state.final_video_path='kept-final.mp4'
        return state

    def apply(self, target):
        text = target.model_dump_json()
        key = self.state.script_editor_key();self.state.remember_script_draft(key,text)
        self.notify = Mock()
        apply = callback('planning_tab.py','save_script',{'state':self.state,'json':json,'ShortsScript':ShortsScript,
            'speech_identity':speech_identity,'editor_source':{'key':key},'editor_area':SimpleNamespace(value=text),
            'restore_editor':Mock(),'form_panel':None,'safe_refresh':Mock(),'safe_notify':self.notify,
            'update_script_preview':Mock(),'update_candidates_panel':Mock(),'feedback_section':SimpleNamespace(visible=True)})
        apply()

    def visual_edit(self):
        target = self.original.model_copy(deep=True);target.title='Visual edit'
        target.scenes[0].visual_description='A clearer wide view of the same bus'
        target.scenes.reverse()
        return target

    def test_visual_edit_keeps_explicit_voice_binding_and_preferences_but_requires_new_review_edit(self):
        selected = self.state.prepared_narration_manifest,self.state.prepared_narration_sha256
        before = Path(self.manifest).read_bytes()
        target = self.visual_edit();self.apply(target)
        self.assertEqual(self.state.script,target)
        self.assertEqual((self.state.prepared_narration_manifest,self.state.prepared_narration_sha256),selected)
        self.assertEqual(self.state.tts_voice,'alloy')  # The explicitly selected Nova set overrides this for editing.
        self.assertEqual(self.state.bgm_volume,.37)
        self.assertEqual(Path(self.manifest).read_bytes(),before)
        self.assertEqual([Path(p).name for p in self.state.prepared_audio_paths()],['scene_2.mp3','scene_1.mp3'])
        self.assertIsNone(self.state.reviewed_script_sha256);self.assertIsNone(self.state.final_video_path)
        self.assertIsNone(self.state.production_service)
        self.assertIsNone(audio_choices.load_audio_choices(target))  # Applying is not saving audio settings.

    def test_changed_manifest_stays_selected_and_invalid_instead_of_falling_back_to_new_tts(self):
        selected = self.state.prepared_narration_manifest,self.state.prepared_narration_sha256
        Path(self.manifest).write_text(Path(self.manifest).read_text()+' ')
        self.apply(self.visual_edit())
        self.assertEqual((self.state.prepared_narration_manifest,self.state.prepared_narration_sha256),selected)
        with self.assertRaisesRegex(ValueError,'변경'):
            self.state.prepared_audio_paths()
        self.assertIsNone(self.state.production_service)

    def test_narration_source_or_scene_id_change_does_not_carry_old_selection(self):
        variants = []
        text = self.visual_edit();text.scenes[0].script_text='New narration';variants.append(text)
        variants.append(self.visual_edit().model_copy(update={'source_url':'https://example.com/new'}))
        number = self.visual_edit();number.scenes[0].scene_number=8;variants.append(number)
        for target in variants:
            with self.subTest(target=target.model_dump_json()):
                self.state=self.bound_state();self.apply(target)
                self.assertEqual(self.state.script,target)
                self.assertIsNone(self.state.prepared_narration_manifest)
                self.assertIsNone(self.state.prepared_narration_sha256)

    def test_corrupt_target_audio_record_blocks_edit_without_replacing_current_selection(self):
        target=self.visual_edit();path=audio_choices._path(target);path.parent.mkdir(parents=True)
        path.write_text('{broken');before=path.read_bytes()
        selected=self.state.prepared_narration_manifest,self.state.prepared_narration_sha256
        receipt=self.state.reviewed_script_sha256
        self.apply(target)
        self.assertEqual(self.state.script,self.original)
        self.assertEqual((self.state.prepared_narration_manifest,self.state.prepared_narration_sha256),selected)
        self.assertEqual(self.state.reviewed_script_sha256,receipt)
        self.assertEqual(self.state.final_video_path,'kept-final.mp4')
        self.assertEqual(path.read_bytes(),before)
        self.assertIn('적용할 수 없습니다',self.notify.call_args.args[0])

    def test_file_load_restores_saved_target_choices_and_new_planning_does_not_inherit_media(self):
        target=self.visual_edit()
        audio_choices.save_audio_choices(target,dict(tts_voice='shimmer',bgm_mood='auto',bgm_track='',bgm_volume=0.))
        self.state.load_saved_script(target,backup_current=True)
        self.assertEqual(self.state.tts_voice,'shimmer')
        self.assertIsNone(self.state.prepared_narration_manifest)
        self.state=self.bound_state()
        other=script('New planned story')
        callback('planning_tab.py','apply_script',{'state':self.state})(other)
        self.assertEqual(self.state.script,other)
        self.assertIsNone(self.state.prepared_narration_manifest)

    def test_manual_edit_does_not_overwrite_previously_saved_target_audio_settings(self):
        target=self.visual_edit()
        path=audio_choices.save_audio_choices(target,dict(tts_voice='shimmer',bgm_mood='auto',bgm_track='',bgm_volume=0.))
        before=path.read_bytes()
        selected=self.state.prepared_narration_manifest,self.state.prepared_narration_sha256
        self.apply(target)
        self.assertEqual((self.state.prepared_narration_manifest,self.state.prepared_narration_sha256),selected)
        self.assertEqual(self.state.tts_voice,'alloy')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(audio_choices.load_audio_choices(target)['tts_voice'],'shimmer')
