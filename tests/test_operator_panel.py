"""Native episode inspection/attachment uses isolated records, never provider calls."""

import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.operator_panel import render_operator_panel
from shorts_maker.gui.components import scheduling_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.operating_budget import begin_episode, episode_path
from shorts_maker.services.operating_status import operator_status
from shorts_maker.services.production_service import script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from test_gui_creation_flows import script


class OperatorPanelTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        for name, value in [('output_dir', self.root / 'outputs'),
                            ('google_monthly_budget_krw', 10000), ('google_budget_opening_krw', 0),
                            ('google_budget_month', google_budget._period()), ('google_usd_krw_rate', 2000),
                            ('openai_monthly_budget_usd', 1.0), ('openai_budget_opening_usd', 0),
                            ('openai_budget_month', openai_budget._period()), ('paid_production_enabled', False)]:
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start()
        self.addCleanup(loop.stop)
        self.client = Client(page('/operator-panel'))
        self.addCleanup(self.client.delete)
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        self.manager = ScheduleManager(str(self.root / 'schedules.json'), queue_only=True)
        scheduled = self.manager.create_schedule('UI 회차', '19:00', frequency='Every 2 Weeks')
        self.schedule = self.manager.update_schedule(scheduled['id'], {
            'review_operator': 'agent', 'enabled': False, 'run_count': 1,
            'last_result': 'script_review_pending', 'last_script': script().model_dump(mode='json')})
        self.episode = begin_episode(self.schedule['id'], 1)
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_episode_id': self.episode['id']})
        self.video = settings.output_dir / 'review.mp4'
        self.video.write_bytes(b'isolated metadata fixture, not an encoded video')
        self.report = self.video.with_suffix('.production.json')
        self.report.write_text(json.dumps({
            'schema_version': 1, 'video_path': str(self.video), 'source_url': script().source_url,
            'script_sha256': script_sha256(self.schedule['last_script']), 'quality_passed': True,
            'video_sha256': hashlib.sha256(self.video.read_bytes()).hexdigest(),
            'youtube_id': 'private_test_12', 'youtube_upload_request': {'status': {'privacyStatus': 'private'}},
            'uploaded_at_utc': '2026-11-10T00:00:00Z'}))
        self.state = AppState(script=script(), final_video_path=str(self.video))
        self.attached = Mock()

    def render(self):
        with self.client, ui.column() as root:
            refresh = render_operator_panel(self.state, self.manager, self.schedule, self.attached)
        return root, refresh

    def click(self, text):
        button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == text)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    def text(self, root):
        return '\n'.join(getattr(e, 'text', '') for e in root.descendants())

    async def test_read_only_status_uses_existing_reserves_and_does_not_start_or_reset_episode(self):
        request = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        google_budget.mark_google_result(request, 'failed')
        paths = [self.manager.filename, episode_path(self.episode['id']),
                 google_budget._database_path(), openai_budget._database_path()]
        before = [p.read_bytes() for p in paths]
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('Google 회차 누적 예약 ₩240', self.text(root))
        self.assertIn('전체 상한까지 여유 ₩2,760', self.text(root))
        self.assertIn('새 지출 허가가 아닙니다', self.text(root))
        self.assertEqual(operator_status(self.schedule)['budget']['google_new_reserved_krw'], 240)
        self.assertEqual(before, [p.read_bytes() for p in paths])

    async def test_preview_then_attach_is_explicit_and_keeps_owner_acceptance_pending(self):
        self.render()
        before = self.manager.filename.read_bytes()
        with self.client:
            self.click('선택 완성본을 이 회차에 연결')
            self.assertEqual(self.manager.filename.read_bytes(), before)
            self.click('이 비공개 완성본 연결')
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertEqual(current['last_video_path'], str(self.video))
        self.assertEqual(current['last_result'], 'script_review_pending')
        self.assertFalse(current['enabled'])
        self.assertNotIn('accepted_at', current)
        self.attached.assert_called_once()

    async def test_cancelled_or_stale_selection_and_episode_cannot_attach(self):
        self.render()
        before = self.manager.filename.read_bytes()
        with self.client:
            self.click('선택 완성본을 이 회차에 연결')
            self.click('취소')
            self.click('이 비공개 완성본 연결')
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.click('선택 완성본을 이 회차에 연결')
            # Target the new dialog; closed prior dialogs retain widgets until client cleanup.
            confirms = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 비공개 완성본 연결']
            confirm = next(e.handler for e in confirms[-1]._event_listeners.values() if e.type == 'click')
            self.state.final_video_path = 'different.mp4'
            confirm(None)
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.state.final_video_path = str(self.video)
            report = json.loads(self.report.read_text())
            report['youtube_id'] = 'changed_test_12'
            self.report.write_text(json.dumps(report))
            confirm(None)
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.manager.update_schedule(self.schedule['id'], {'last_result': 'script_rejected'})
            changed = self.manager.filename.read_bytes()
            confirm(None)
            self.assertEqual(changed, self.manager.filename.read_bytes())
        self.attached.assert_not_called()

    async def test_pending_operations_uploads_and_external_reports_block_preview_attach_and_acceptance(self):
        operation = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        upload = self.video.with_suffix('.upload-pending.json')
        for marker in (operation, upload):
            marker.write_text('{}')
            before = self.manager.filename.read_bytes()
            for action in (self.manager.pending_video_info, self.manager.record_private_review_copy,
                           self.manager.accept_pending_video):
                with self.assertRaises(ValueError):
                    action(self.schedule['id'], str(self.video))
            self.assertEqual(before, self.manager.filename.read_bytes())
            marker.unlink()
        operation.write_text('{}')
        changed_actor = self.manager.update_schedule(self.schedule['id'], {'review_operator': None})
        self.assertTrue(operator_status(changed_actor)['operation_pending_unverified'])
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))
        operation.unlink()
        external = self.root / 'outside-output.json'
        self.report.rename(external)
        self.report.symlink_to(external)
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))

    async def test_failed_status_does_not_invent_budget_and_attached_episode_has_no_replace_control(self):
        operation = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        operation.write_text('{}')
        episode_path(self.episode['id']).write_text('{invalid')
        status = operator_status(self.schedule)
        self.assertTrue(status['operation_pending_unverified'])
        self.assertIn('budget_error', status)
        self.assertNotIn('budget', status)
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_youtube_id': 'already_set_12'})
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('회차 비용 확인 필요', self.text(root))
        self.assertNotIn('선택 완성본을 이 회차에 연결', self.text(root))

    async def test_unchanged_schedule_poll_preserves_live_panel_and_dialog_but_changed_records_refresh(self):
        with self.client, ui.column() as root, patch.object(scheduling_tab, 'schedule_manager', self.manager), patch.object(
                scheduling_tab, 'load_source_catalog', return_value=(object(), {})), patch.object(ui, 'timer') as timers:
            scheduling_tab.render_scheduling_tab(self.state)
            poll = next(call.args[1] for call in timers.call_args_list if call.args[0] == 30.0)
            self.click('선택 완성본을 이 회차에 연결')
            dialog = next(e for e in self.client.elements.values() if isinstance(e, ui.dialog))
            attach_button = next(e for e in root.descendants() if getattr(e, 'text', '') == '선택 완성본을 이 회차에 연결')
            poll()
            await asyncio.sleep(0)
            self.assertTrue(dialog.value)
            self.assertFalse(dialog.is_deleted)
            self.assertFalse(attach_button.is_deleted)
            self.manager.update_schedule(self.schedule['id'], {'last_result': 'script_rejected'})
            poll()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertTrue(attach_button.is_deleted)

    async def test_direct_studio_schedule_can_attach_without_creating_an_agent_budget(self):
        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'review_operator': None, 'last_episode_id': None})
        before = set((settings.output_dir / 'evaluation/operating_episodes').iterdir())
        root, refresh = self.render()
        with self.client:
            await refresh()
            await asyncio.sleep(0)
            self.click('선택 완성본을 이 회차에 연결')
            self.click('이 비공개 완성본 연결')
        self.assertIn('Studio 직접 실행 일정', self.text(root))
        self.assertEqual(before, set((settings.output_dir / 'evaluation/operating_episodes').iterdir()))
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertFalse(current['enabled'])
