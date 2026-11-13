"""Explicit Studio script replacement preserves the previous text version locally."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.work_drafts import saved_work_drafts, read_work_draft
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script, callback


class ScriptSwitchBackupTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        p=patch.object(settings,'output_dir',self.root);p.start();self.addCleanup(p.stop)
        self.original=script('Applied but not separately saved')
        self.state=AppState(script=self.original,final_video_path='kept.mp4')
        self.state.confirm_script_review()

    def records(self):
        names,warnings=saved_work_drafts()
        self.assertFalse(warnings)
        return [read_work_draft(name)[0] for name in names]

    def test_app_apply_preserves_previous_applied_script_before_replacing_it(self):
        apply=callback('planning_tab.py','apply_script',{'state':self.state})
        apply(script('Next script'))
        self.assertTrue(any(record.applied_script == self.original for record in self.records()))
        self.assertEqual(self.state.script.title,'Next script')

    def test_app_apply_backup_failure_preserves_script_review_result_and_input(self):
        self.state.remember_script_draft(self.state.script_editor_key(),'{unfinished')
        receipt=self.state.reviewed_script_sha256
        apply=callback('planning_tab.py','apply_script',{'state':self.state})
        with patch.object(self.state,'save_work_draft',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):apply(script('Next script'))
        self.assertIs(self.state.script,self.original)
        self.assertEqual(self.state.reviewed_script_sha256,receipt)
        self.assertEqual(self.state.final_video_path,'kept.mp4')
        self.assertEqual(self.state.script_editor_text(),'{unfinished')

    def test_first_or_identical_load_does_not_make_redundant_backups(self):
        state=AppState()
        with patch.object(state,'save_work_draft') as save:
            state.load_saved_script(self.original,backup_current=True)
            state.load_saved_script(self.original.model_copy(deep=True),backup_current=True)
        save.assert_not_called()
        self.assertEqual(self.records(),[])

    def test_invalid_target_is_rejected_before_backing_up_current_work(self):
        target=script('Target')
        with patch('shorts_maker.services.audio_choices.load_audio_choices',side_effect=ValueError('fixture')), \
                patch.object(self.state,'_backup_text_work') as backup:
            with self.assertRaises(ValueError):self.state.load_saved_script(target,backup_current=True)
        backup.assert_not_called()
        self.assertIs(self.state.script,self.original)
        self.assertEqual(self.state.final_video_path,'kept.mp4')

    def test_unapplied_no_base_text_is_preserved_before_loading_first_script(self):
        state=AppState()
        state.remember_script_draft(state.script_editor_key(),'{unfinished new draft')
        state.load_saved_script(self.original,backup_current=True)
        record=self.records()[0]
        self.assertIsNone(record.applied_script)
        self.assertEqual(record.editor_text,'{unfinished new draft')

    def test_fresh_session_recovers_applied_text_frames_and_source_without_authority(self):
        state=self.state
        scope={'episode_id':'kept'}
        state.operating_scope=scope
        state.openai_key='secret-not-stored'
        state.planning_source_mode='직접 URL 입력';state.planning_url='https://example.com/new-source'
        state.remember_script_draft(state.script_editor_key(),'{unfinished')
        state.first_frame_drafts[state.script_editor_key()]={1:{'reviewer_note':'Keep this note'}}
        state.load_saved_script(script('Next'),backup_current=True)
        self.assertIs(state.operating_scope,scope)
        names,_=saved_work_drafts()
        name=next(iter(names))
        record,digest=read_work_draft(name)
        self.assertNotIn('secret-not-stored',(self.root/'evaluation'/'studio_drafts'/name).read_text())
        fresh=AppState()
        fresh.restore_work_draft(name,digest)
        self.assertEqual(fresh.script,self.original)
        self.assertEqual(fresh.script_editor_text(),'{unfinished')
        self.assertEqual(fresh.first_frame_drafts[fresh.script_editor_key()][1]['reviewer_note'],'Keep this note')
        self.assertEqual(fresh.planning_url,state.planning_url)
        self.assertIsNone(fresh.reviewed_script_sha256)
        self.assertIsNone(fresh.operating_scope)
