"""Rejected validator drafts reopen through the existing safe script-copy path."""

import asyncio
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import script_review_panel
from shorts_maker.gui.components.planning_tab import _saved_script_options
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.script_reviews import read_review_script, read_script_reviews
from shorts_maker.services.work_drafts import read_work_draft, saved_work_drafts, script_draft_key
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script
from test_script_review_panel import ReviewFixture


class ReviewRecoveryTests(ReviewFixture, unittest.TestCase):
    def test_rejected_and_interrupted_drafts_missing_from_saved_scripts_are_discoverable(self):
        self.write('rejected');self.write('unknown', verdict=None)
        self.write('passed', self.script.model_copy(update={'title': 'Another candidate'}), verdict=True)
        self.assertEqual(_saved_script_options(), {})  # Validation rejection never creates an accepted script file.
        before = {p.name: p.read_bytes() for p in self.reviews.iterdir()}
        records = read_script_reviews()['records']
        self.assertEqual(len(records), 3)
        for row in records:
            reopened = read_review_script(row['name'], row['request_sha256'])
            self.assertEqual(reopened.model_dump(), row['script'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.reviews.iterdir()})

    def test_exact_file_snapshot_and_path_source_schema_are_rechecked_before_opening(self):
        path = self.write('review')
        row = read_script_reviews()['records'][0]
        path.write_text(path.read_text() + '\n')
        with self.assertRaises(ValueError):
            read_review_script(row['name'], row['request_sha256'])
        for name in ('../review.request.json', '/review.request.json', '..\\review.request.json', 'other.json'):
            with self.assertRaises(ValueError):
                read_review_script(name, row['request_sha256'])
        data = json.loads(path.read_text());data['source_excerpt'] = 'Changed source'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            read_review_script(path.name, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(read_script_reviews()['unreadable'], [path.name])


class ReviewRecoveryPanelTests(ReviewFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for field, value in [('output_dir', self.root), ('rss_sources_file', self.root/'rss.json')]:
            override = patch.object(settings, field, value);override.start();self.addCleanup(override.stop)
        settings.rss_sources_file.write_text('{}')
        loop = patch.object(core, 'loop', asyncio.get_running_loop());loop.start();self.addCleanup(loop.stop)
        self.client = Client(page('/review-recovery'));self.addCleanup(self.client.delete)
        self.state = AppState(script=script('Current'), final_video_path='kept.mp4', operating_scope={'preserved': 'scope'})
        self.state.confirm_script_review()
        self.opened = Mock()

    async def render(self):
        with self.client, ui.column() as self.panel:
            refresh = script_review_panel.render_review_recovery(self.state, self.opened)
            await refresh()
        await asyncio.sleep(0);binding._refresh_step()
        return refresh

    def select(self, name):
        choice = next(e for e in self.panel.descendants() if e._props.get('label') == '모델 검토 대본 검색')
        choice.value = f'{name}.request.json'

    def click(self, text):
        button = [e for e in self.client.elements.values() if getattr(e, 'text', '') == text][-1]
        handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
        handler(None)
        return handler

    def text(self):
        return '\n'.join(str(getattr(e, 'text', '')) for e in self.panel.descendants())

    async def test_explicit_open_backs_up_current_and_target_input_and_keeps_original_failure_scope(self):
        self.write('rejected')
        current = self.state.script
        self.state.remember_script_draft(self.state.script_editor_key(), '{unfinished current')
        self.state.first_frame_drafts[self.state.script_editor_key()] = {1: {'reviewer_note': 'current note'}}
        target = script_draft_key(self.script)
        self.state.script_editor_drafts[target] = '{unfinished target'
        before = {p.name: p.read_bytes() for p in self.reviews.iterdir()}
        await self.render();self.select('rejected')
        with self.client:
            self.click('선택 검토 대본 확인')
            self.assertEqual(self.state.script, current)
            self.click('취소');self.click('미확인 사본 열기')
            self.assertEqual(self.state.script, current)
            self.click('선택 검토 대본 확인');self.click('미확인 사본 열기')
        self.assertEqual(self.state.script, self.script)
        self.assertFalse(self.state.is_script_reviewed())
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual(self.state.operating_scope, {'preserved': 'scope'})
        self.assertNotIn(target, self.state.script_editor_drafts)
        self.assertIsNone(self.state.production_service)
        records, warnings = saved_work_drafts();self.assertEqual(warnings, [])
        snapshots = [read_work_draft(name)[0] for name in records]
        self.assertEqual({s.editor_text for s in snapshots}, {'{unfinished current', '{unfinished target'})
        self.assertTrue(any(s.first_frames.get('1', {}).get('reviewer_note') == 'current note' for s in snapshots))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.reviews.iterdir()})
        self.assertFalse(read_script_reviews(self.state.script)['records'][0]['verdict']['is_valid'])
        self.opened.assert_called_once()

    async def test_changed_busy_deleted_and_cancelled_dialogs_preserve_current_work(self):
        self.write('rejected');await self.render();self.select('rejected')
        original = self.state.script
        with self.client, patch.object(script_review_panel, 'safe_notify'):
            self.click('선택 검토 대본 확인')
            self.state.remember_script_draft(self.state.script_editor_key(), 'Changed while dialog open')
            self.click('미확인 사본 열기');self.assertEqual(self.state.script, original)
            self.click('선택 검토 대본 확인');self.state.pipeline_running = True
            self.click('미확인 사본 열기');self.assertEqual(self.state.script, original)
            self.state.pipeline_running = False
            self.click('선택 검토 대본 확인')
            button = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '미확인 사본 열기'][-1]
            late = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            self.panel.clear();late(None)
        self.assertEqual(self.state.script, original)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.opened.assert_not_called()

    async def test_record_change_and_backup_failure_stop_before_current_state_is_replaced(self):
        path = self.write('rejected');await self.render();self.select('rejected')
        original = self.state.script
        with self.client, patch.object(script_review_panel, 'safe_notify'):
            self.click('선택 검토 대본 확인');path.write_text(path.read_text() + '\n')
            self.click('미확인 사본 열기');self.assertEqual(self.state.script, original)
        await self.render();self.select('rejected')
        with self.client, patch.object(script_review_panel, 'safe_notify'), patch.object(self.state, 'save_work_draft', side_effect=OSError('disk full')):
            self.click('선택 검토 대본 확인');self.click('미확인 사본 열기')
        self.assertEqual(self.state.script, original)
        self.assertTrue(self.state.is_script_reviewed())
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.opened.assert_not_called()

    async def test_failed_or_late_inventory_never_exposes_old_candidates(self):
        self.write('rejected');refresh = await self.render()
        self.assertIn('선택 검토 대본 확인', self.text())
        with patch.object(script_review_panel, 'read_script_reviews', side_effect=OSError('denied')), self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('목록을 읽을 수 없습니다', self.text())
        self.assertNotIn('선택 검토 대본 확인', self.text())
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            entered.set();await release.wait();return {'records': [], 'unreadable': ['late.request.json']}
        with patch.object(script_review_panel.asyncio, 'to_thread', side_effect=delayed) as reader, self.client:
            task = asyncio.create_task(refresh());await entered.wait();await refresh()
            self.assertEqual(reader.call_count, 1)
            self.panel.clear();release.set();await task
        self.assertNotIn('late.request.json', self.text())

    async def test_completed_open_is_not_reported_as_failed_when_old_preview_cannot_update(self):
        self.write('rejected');await self.render();self.select('rejected')
        self.opened.side_effect = RuntimeError('old preview deleted')
        with self.client, patch.object(script_review_panel, 'safe_notify') as notify:
            self.click('선택 검토 대본 확인');self.click('미확인 사본 열기')
        self.assertEqual(self.state.script, self.script)
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertEqual(notify.call_args.kwargs['type'], 'positive')
