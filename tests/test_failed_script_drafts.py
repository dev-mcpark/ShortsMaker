"""Failed writer responses remain editable without another request or approval."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services import work_drafts
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class FailedScriptDraftTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(settings, 'output_dir', Path(directory.name)))
        self.enterContext(patch.object(settings, 'paid_production_enabled', True))
        self.enterContext(patch('shorts_maker.planner.script_planner.reserve_openai_chat'))
        self.planner = object.__new__(ScriptPlanner)
        self.planner.logger = Mock()
        self.planner.allowed_moods = ['calm']
        self.planner.generation_mode = 'video'
        self.reply = SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=''))
        self.create = AsyncMock(return_value=SimpleNamespace(choices=[self.reply]))
        self.planner.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))
        self.item = dict(title='Failed response', category='City_Life', content='One bus appears in the source.',
                         url='https://example.com/source', source='Known source')

    def write(self, content):
        self.reply.message.content = content
        return asyncio.run(self.planner._write_script(self.item))

    def test_invalid_mood_is_saved_without_forcing_music_or_returning_an_approved_script(self):
        data = script().model_dump(); data['mood'] = None
        data['source_url'] = 'https://example.com/model-invented-source'
        with self.assertRaisesRegex(ValueError, 'BGM_SELECTION_REQUIRED') as stopped:
            self.write(json.dumps(data))
        choices, warnings = work_drafts.saved_work_drafts()
        self.assertEqual(len(choices), 1)
        self.assertEqual(warnings, [])
        name = next(iter(choices)); record, _ = work_drafts.read_work_draft(name)
        saved = json.loads(record.editor_text)
        self.assertIsNone(record.applied_script)
        self.assertIsNone(saved['mood'])
        self.assertEqual(saved['source_url'], self.item['url'])
        self.assertEqual(saved['source_name'], self.item['source'])
        self.assertEqual(saved['generation_mode'], 'video')
        self.assertIn('저장된 작업 초안', str(stopped.exception))
        self.assertIn(Path(name).stem[-8:], str(stopped.exception))
        self.assertEqual(self.create.await_count, 1)

    def test_malformed_truncated_and_schema_invalid_outputs_are_retained_as_unapplied_text(self):
        data = script().model_dump(); data['scenes'][0]['duration_seconds'] = -1
        for text, finish in (('{incomplete', 'length'), ('not JSON', 'stop'), ('[]', 'stop'),
                             (json.dumps(data), 'stop')):
            with self.subTest(finish=finish, text=text):
                before = set(work_drafts.saved_work_drafts()[0])
                self.reply.finish_reason = finish
                with self.assertRaises(ValueError):
                    self.write(text)
                after = set(work_drafts.saved_work_drafts()[0])
                self.assertEqual(len(after - before), 1)
                record, _ = work_drafts.read_work_draft((after - before).pop())
                self.assertIsNone(record.applied_script)
                self.assertIn(text if not text.startswith('{"') else 'duration_seconds', record.editor_text)
        self.assertEqual(self.create.await_count, 4)

    def test_storage_failure_keeps_existing_snapshot_and_reports_no_saved_copy(self):
        existing = work_drafts.save_work_draft(None, 'keep this unfinished text', {})
        old = existing.read_bytes()
        data = script().model_dump(); data['mood'] = None
        with patch('shorts_maker.services.work_drafts.save_work_draft', side_effect=OSError('Disk full')):
            with self.assertRaisesRegex(ValueError, '초안 보관 실패') as stopped:
                self.write(json.dumps(data))
        self.assertNotIn('저장된 작업 초안에서', str(stopped.exception))
        self.assertEqual(existing.read_bytes(), old)
        self.assertEqual(self.create.await_count, 1)

    def test_valid_response_has_no_failure_snapshot_and_empty_response_does_not_claim_recovery(self):
        data = script().model_dump()
        data['scenes'] = [{**data['scenes'][0], 'scene_number': n} for n in range(1, 6)]
        self.assertIsNotNone(self.write(json.dumps(data)))
        self.assertEqual(work_drafts.saved_work_drafts(), ({}, []))
        with self.assertRaises(ValueError) as stopped:
            self.write('')
        self.assertNotIn('저장된 작업 초안', str(stopped.exception))
        self.assertEqual(work_drafts.saved_work_drafts(), ({}, []))
