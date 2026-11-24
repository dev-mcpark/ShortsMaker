"""Real local clock evidence and native status UI; no provider or schedule execution."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.queue_host_panel import render_queue_host_panel
from scripts.operate_schedule import serve
from shorts_maker.services.budget_calendar import budget_month_starts
from shorts_maker.services.queue_host_status import read_host_status, status_path, write_host_status
from shorts_maker.utils.scheduler import ScheduleManager, TRIGGER_FIELDS


class QueueHostStatusTests(unittest.TestCase):
    def test_slot_budget_months_follow_each_ledger_even_on_different_dates_in_seoul(self):
        seoul = ZoneInfo('Asia/Seoul')
        split = budget_month_starts(datetime.fromisoformat('2026-12-01T10:06:00+09:00'))
        self.assertEqual({name: start.strftime('%Y-%m') for name, start in split.items()},
                         {'Google': '2026-11', 'OpenAI': '2026-12'})
        winter = budget_month_starts(datetime.fromisoformat('2026-12-02T10:06:00+09:00'))
        self.assertEqual(winter['Google'].astimezone(seoul).isoformat(), '2026-12-01T17:00:00+09:00')
        self.assertEqual(winter['OpenAI'].astimezone(seoul).isoformat(), '2026-12-01T09:00:00+09:00')
        summer = budget_month_starts(datetime.fromisoformat('2026-07-02T10:06:00+09:00'))
        self.assertEqual(summer['Google'].astimezone(seoul).isoformat(), '2026-07-01T16:00:00+09:00')
        with self.assertRaises(ValueError):
            budget_month_starts(datetime(2026, 12, 2, 10, 6))

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = ScheduleManager(str(Path(self.temp.name) / 'schedules.json'), queue_only=True)
        self.schedule = {'id': 'future-slot', 'name': '예약 검증', 'enabled': True,
                         'review_operator': 'agent', 'mode': 'video', 'time': '10:06', 'frequency': 'Every 2 Weeks',
                         'first_run_at': '2099-01-01T10:06:00', 'created_at': '2026-11-15T09:00:00'}
        self.manager.save_schedules([self.schedule])
        self.path = status_path(self.manager)

    def snapshot(self, **changes):
        value = {'schema_version': 1, 'pid': os.getpid(), 'state': 'running',
                 'updated_at': datetime.now(timezone.utc).isoformat(),
                 'schedules_file': str(self.manager.filename.resolve()),
                 'jobs': [{'id': self.schedule['id'], 'next_run': '2099-01-01T10:06:00+09:00',
                           'registration': {key: self.schedule.get(key) for key in TRIGGER_FIELDS}}]}
        value.update(changes)
        self.path.write_text(json.dumps(value))
        return value

    def test_requires_fresh_matching_registered_jobs_and_live_process(self):
        before = self.manager.filename.read_bytes()
        self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        value = self.snapshot()
        self.assertEqual(read_host_status(self.manager)['state'], 'healthy')
        with patch('shorts_maker.services.queue_host_status.os.kill', side_effect=ProcessLookupError):
            self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        for age in (91, -20):
            self.snapshot(updated_at=(datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat())
            self.assertEqual(read_host_status(self.manager)['state'], 'stale')
        for state in ('stopped', 'error'):
            self.snapshot(state=state)
            self.assertEqual(read_host_status(self.manager)['state'], state)
        self.snapshot()
        self.manager.update_schedule(self.schedule['id'], {'time': '12:30'})
        self.assertEqual(read_host_status(self.manager)['state'], 'out_of_sync')
        self.manager.save_schedules([self.schedule])
        self.snapshot(jobs=[])
        self.assertEqual(read_host_status(self.manager)['state'], 'out_of_sync')
        self.snapshot(schedules_file='/different/schedules.json')
        self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        self.assertEqual(self.manager.filename.read_bytes(), before)

    def test_corrupt_oversized_linked_and_bad_registration_cannot_look_healthy(self):
        for content in ('{bad', 'null', '[]', ' ' * (1024 * 1024 + 1)):
            self.path.write_text(content)
            self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        value = self.snapshot()
        for jobs in (None, [None], [value['jobs'][0]] * 2,
                     [{**value['jobs'][0], 'next_run': '2099-01-01T00:00:00'}],
                     [{**value['jobs'][0], 'next_run': '2020-01-01T00:00:00+00:00'}]):
            self.snapshot(jobs=jobs)
            self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        self.path.unlink()
        other = Path(self.temp.name) / 'other';other.write_text('preserve')
        self.path.symlink_to(other)
        self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
        with self.assertRaises(ValueError):
            write_host_status(self.manager)
        self.assertEqual(other.read_text(), 'preserve')

    def test_windows_never_uses_kill_zero_as_a_probe(self):
        self.snapshot()
        with patch('shorts_maker.services.queue_host_status.sys.platform', 'win32'), patch(
            'shorts_maker.services.queue_host_status.os.kill') as kill:
            self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
            kill.assert_not_called()

    def test_real_serve_reports_registration_sync_stop_and_dead_process(self):
        env = {**os.environ, 'PAID_PRODUCTION_ENABLED': 'false', 'OPENAI_API_KEY': 'offline-test-key'}
        with (Path(self.temp.name) / 'host.log').open('wb') as log:
            child = subprocess.Popen([sys.executable, 'scripts/operate_schedule.py', '--schedules',
                                      str(self.manager.filename), 'serve'], stdout=log, stderr=log, env=env)
            try:
                deadline = time.monotonic() + 12
                while read_host_status(self.manager)['state'] != 'healthy' and time.monotonic() < deadline:
                    if child.poll() is not None:
                        self.fail((Path(self.temp.name) / 'host.log').read_text())
                    time.sleep(.02)
                snapshot = read_host_status(self.manager)
                self.assertEqual(snapshot['state'], 'healthy')
                self.assertEqual(snapshot['pid'], child.pid)
                self.assertEqual(snapshot['jobs'][0]['next_run'], '2099-01-01T10:06:00+09:00')
                self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
                self.manager.update_schedule(self.schedule['id'], {'enabled': False})
                self.assertEqual(read_host_status(self.manager)['state'], 'out_of_sync')
                child.send_signal(signal.SIGTERM)
                child.wait(timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(read_host_status(self.manager)['state'], 'stopped')
                self.snapshot(pid=child.pid)
                self.assertEqual(read_host_status(self.manager)['state'], 'unavailable')
            finally:
                if child.poll() is None:
                    child.kill();child.wait(timeout=5)


class QueueHostPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        previous = core.loop
        core.loop = asyncio.get_running_loop()
        self.addCleanup(setattr, core, 'loop', previous)

    async def test_clock_loop_syncs_external_changes_and_status_io_failure_does_not_stop_clock(self):
        with TemporaryDirectory() as folder:
            manager = ScheduleManager(str(Path(folder) / 'schedules.json'), queue_only=True)
            manager.save_schedules([{'id': 'future', 'name': 'future', 'enabled': True, 'mode': 'video',
                                     'review_operator': 'agent', 'time': '10:06', 'frequency': 'Every 2 Weeks',
                                     'first_run_at': '2099-01-01T10:06:00', 'created_at': '2026-11-15T00:00:00'}])
            original_wait = asyncio.wait_for
            async def accelerated(awaitable, timeout):
                return await original_wait(awaitable, timeout=.01)
            with patch.object(asyncio.get_running_loop(), 'add_signal_handler') as handlers, patch(
                'scripts.operate_schedule.asyncio.wait_for', side_effect=accelerated):
                task = asyncio.create_task(serve(manager))
                try:
                    for _ in range(100):
                        await asyncio.sleep(.01)
                        if read_host_status(manager)['state'] == 'healthy':
                            break
                    self.assertEqual(len(read_host_status(manager)['jobs']), 1)
                    manager.update_schedule('future', {'enabled': False})
                    for _ in range(100):
                        await asyncio.sleep(.01)
                        if read_host_status(manager).get('jobs') == []:
                            break
                    self.assertEqual(read_host_status(manager)['jobs'], [])
                    with patch('scripts.operate_schedule.write_host_status', side_effect=OSError('read only')):
                        await asyncio.sleep(.04)
                        self.assertFalse(task.done())
                        self.assertTrue(manager._scheduler_running)
                    next(call.args[1] for call in handlers.call_args_list if call.args[0] == signal.SIGTERM)()
                    await original_wait(task, 2)
                    self.assertEqual(read_host_status(manager)['state'], 'stopped')
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_refresh_failure_clears_old_success_and_deleted_view_ignores_late_result(self):
        client = Client(page('/queue-host-native'), request=None)
        healthy = {'state': 'healthy', 'pid': 123, 'updated_at': '2026-11-24T01:10:00+00:00',
                   'jobs': [{'id': 'one', 'next_run': '2026-12-02T10:06:00+09:00'}]}
        with client:
            root = ui.column()
            with root:
                refresh = render_queue_host_panel(Mock())
        def text():
            return '\n'.join(getattr(e, 'text', '') for e in client.elements.values())
        async def io(function, *args):
            return function(*args)
        with (client,
              patch('shorts_maker.gui.components.queue_host_panel.run.io_bound', side_effect=io),
              patch('shorts_maker.gui.components.queue_host_panel.read_host_status', return_value=healthy) as read,
              patch('shorts_maker.gui.components.queue_host_panel.datetime', wraps=datetime) as clock):
            clock.now.return_value = datetime.fromisoformat(healthy['updated_at'])
            await refresh()
            await asyncio.sleep(0)
            self.assertIn('2026-12-02 10:06 KST', text())
            self.assertIn('등록 1건', text())
            self.assertIn('Google 2026-12 · OpenAI 2026-12', text())
            self.assertIn('OpenAI 새 장부 월 시작 · 2026-12-01 09:00 KST', text())
            self.assertIn('Google 새 장부 월 시작 · 2026-12-01 17:00 KST', text())
            clock.now.return_value = datetime.fromisoformat('2026-12-01T10:00:00+09:00')
            await refresh()
            await asyncio.sleep(0)
            self.assertNotIn('OpenAI 새 장부 월 시작', text())
            self.assertIn('Google 새 장부 월 시작', text())
            read.return_value = {'state': 'stale'}
            await refresh()
            await asyncio.sleep(0)
            self.assertNotIn('등록 1건', text())
            self.assertNotIn('예약 시각 기준 장부 월', text())
            self.assertIn('응답 지연', text())
            with patch('shorts_maker.gui.components.queue_host_panel.run.io_bound', side_effect=RuntimeError('read failed')):
                await refresh()
                await asyncio.sleep(0)
                self.assertIn('호스트 확인 필요', text())
            entered, release = asyncio.Event(), asyncio.Event()
            async def delayed(*args):
                entered.set();await release.wait();return healthy
            with patch('shorts_maker.gui.components.queue_host_panel.run.io_bound', side_effect=delayed):
                task = asyncio.create_task(refresh())
                await entered.wait()
                await refresh()  # An in-flight read must not launch another.
                root.clear();release.set();await task
            self.assertNotIn('등록 1건', text())
        client.delete()
