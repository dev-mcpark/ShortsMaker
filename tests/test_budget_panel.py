"""The Studio reads real isolated ledgers without releasing or resetting reserves."""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import budget_panel
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.monthly_opening import MonthOpeningRequired
from shorts_maker.services.operating_budget import begin_episode, episode_environment
from shorts_maker.utils.config import settings


class BudgetPanelTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in [('output_dir', Path(directory.name)),
                            ('google_monthly_budget_krw', 10000), ('google_budget_opening_krw', 1000),
                            ('google_budget_month', google_budget._period()), ('google_usd_krw_rate', 2000),
                            ('openai_monthly_budget_usd', 1.0), ('openai_budget_opening_usd', .2),
                            ('openai_budget_month', openai_budget._period())]:
            override = patch.object(settings, name, value)
            override.start()
            self.addCleanup(override.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start()
        self.addCleanup(loop.stop)
        self.client = Client(page('/budget-panel'))
        self.addCleanup(self.client.delete)

    def render(self):
        with self.client, ui.column() as root, patch.object(ui, 'timer'):
            refresh = budget_panel.render_budget_panel()
        return root, refresh

    async def refresh(self, refresh):
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        binding._refresh_step()

    def text(self, root):
        return '\n'.join(getattr(e, 'text', '') for e in root.descendants())

    async def test_exact_balances_and_model_holds_are_read_only_and_can_refresh(self):
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        request = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        google_budget.mark_google_result(request, 'failed')
        openai_budget.reserve_openai_speech('tts-1', '가' * 100)
        paths = [google_budget._database_path(), openai_budget._database_path()]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        root, refresh = self.render()
        await self.refresh(refresh)
        text = self.text(root)
        for expected in ['남은 예약 여유 ₩8,760', '남은 예약 여유 $0.798500',
                         '기준 사용액 ₩1,000', '기준 사용액 $0.200000',
                         'veo-3.1-lite-generate-001 · ₩240', 'tts-1 · $0.001500',
                         '미국 태평양 시간', 'UTC', '실제 청구액', '회차 한도', '마지막 조회']:
            self.assertIn(expected, text)
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
        openai_budget.reserve_openai_speech('tts-1', '가' * 100)
        await self.refresh(refresh)
        self.assertIn('남은 예약 여유 $0.797000', self.text(root))
        self.assertEqual(google_budget.budget_status()['requests_by_status']['failed']['requests'], 1)

    async def test_missing_old_and_disabled_ledgers_never_show_an_invented_balance(self):
        root, refresh = self.render()
        await self.refresh(refresh)
        self.assertEqual(self.text(root).count('장부 확인 필요'), 2)
        self.assertIn('기존 장부를 복구하세요', self.text(root))
        self.assertNotIn('남은 예약 여유', self.text(root))
        self.assertFalse((settings.output_dir / 'evaluation').exists())
        with patch.object(settings, 'google_budget_month', '2000-01'), patch.object(settings, 'openai_monthly_budget_usd', None):
            await self.refresh(refresh)
        self.assertIn('기존 장부를 복구하세요', self.text(root))
        self.assertNotIn('Google 이번 달 기준 사용액 확인', self.text(root))
        self.assertIn('월 예산 미설정', self.text(root))
        self.assertNotIn('남은 예약 여유', self.text(root))

    async def test_month_opening_requires_explicit_evidence_and_refreshes_only_the_chosen_provider(self):
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        with patch.object(settings, 'google_budget_month', '2000-01'):
            root, refresh = self.render()
            await self.refresh(refresh)
            before = google_budget._database_path().read_bytes()
            before_openai = openai_budget._database_path().read_bytes()
            with self.client:
                button = next(e for e in root.descendants() if getattr(e, 'text', '') == 'Google 이번 달 기준 사용액 확인')
                next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
                dialog = next(e for e in self.client.elements.values() if isinstance(e, ui.dialog))
                save = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '확인한 기준 사용액 저장')
                confirm = next(e.handler for e in save._event_listeners.values() if e.type == 'click')
                created = asyncio.all_tasks()
                confirm(None)
                await asyncio.gather(*(asyncio.all_tasks() - created))
                self.assertIn('해당 월을 대조한 뒤', self.text(dialog))
                self.assertEqual(google_budget._database_path().read_bytes(), before)
                fields = [e for e in dialog.descendants() if isinstance(e, ui.input)]
                fields[0].value = '825'
                fields[1].value = '테스트 보고서 12:00'
                next(e for e in dialog.descendants() if isinstance(e, ui.checkbox)).value = True
                created = asyncio.all_tasks()
                confirm(None)
                await asyncio.gather(*(asyncio.all_tasks() - created))
            self.assertFalse(dialog.value)
            self.assertIn('기준 사용액 ₩825', self.text(root))
            self.assertIn('남은 예약 여유 ₩9,175', self.text(root))
            self.assertNotIn('Google 이번 달 기준 사용액 확인', self.text(root))
            self.assertEqual(openai_budget._database_path().read_bytes(), before_openai)
            with closing(sqlite3.connect(google_budget._database_path())) as db:
                self.assertEqual(db.execute('SELECT evidence FROM month_openings').fetchone()[0], '테스트 보고서 12:00')

    async def test_month_rollover_preserves_failed_requests_and_episode_spend(self):
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        episode = begin_episode('scheduled', 1)
        request = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        google_budget.mark_google_result(request, 'failed')
        openai_budget._reserve('fixture', Decimal('.03'))
        before_episode = episode_environment(episode)[1]
        with patch.object(google_budget, '_period', return_value='2099-03'), patch.object(
                openai_budget, '_period', return_value='2099-04'):
            for status in (google_budget.budget_status, openai_budget.budget_status):
                with self.assertRaises(MonthOpeningRequired):
                    status()
            with self.assertRaises(ValueError):
                google_budget.record_google_opening('2099-04', 0, 'wrong provider month')
            google_budget.record_google_opening('2099-03', 2750, 'Google test report')
            with self.assertRaises(MonthOpeningRequired):
                episode_environment(episode)
            openai_budget.record_openai_opening('2099-04', Decimal('.08'), 'OpenAI test report')
            with self.assertRaisesRegex(ValueError, '이미 저장'):
                google_budget.record_google_opening('2099-03', 0, 'overwrite')
            _, current_episode = episode_environment(episode)
            self.assertEqual(current_episode['google_new_reserved_krw'], before_episode['google_new_reserved_krw'])
            self.assertEqual(current_episode['openai_new_reserved_usd'], before_episode['openai_new_reserved_usd'])
            self.assertEqual(google_budget.budget_status()['opening_krw'], 2750)
            self.assertEqual(openai_budget.budget_status()['opening_usd'], .08)
        self.assertEqual(google_budget.budget_status()['requests_by_status']['failed']['requests'], 1)
        self.assertEqual(openai_budget.budget_status()['local_reserved_usd'], .03)

    async def test_missing_or_already_used_ledger_refuses_new_opening(self):
        google_budget.initialize_google_budget()
        google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        with patch.object(settings, 'google_budget_month', '2000-01'), patch.object(settings, 'openai_budget_month', '2000-01'):
            with self.assertRaisesRegex(ValueError, '이미 예약 기록'):
                google_budget.record_google_opening(google_budget._period(), 0, 'test report')
            with self.assertRaises(sqlite3.Error):
                openai_budget.record_openai_opening(openai_budget._period(), Decimal(0), 'test report')
        self.assertFalse(openai_budget._database_path().exists())

    async def test_new_process_sees_opening_and_reserves_with_unchanged_prior_month_configuration(self):
        openai_budget.initialize_openai_budget()
        with patch.object(settings, 'openai_budget_month', '2000-01'):
            openai_budget.record_openai_opening(openai_budget._period(), Decimal('.95'), 'test report')
        child = subprocess.run([sys.executable, '-c', """
import json, sys
from pathlib import Path
from decimal import Decimal
from shorts_maker.utils.config import settings
from shorts_maker.services import openai_budget
settings.output_dir = Path(sys.argv[1])
try:
    openai_budget._reserve('fixture', Decimal('.06'))
except openai_budget.OpenAIBudgetExceeded:
    openai_budget._reserve('fixture', Decimal('.03'))
    print(json.dumps(openai_budget.budget_status()))
""", str(settings.output_dir)], env={**os.environ, 'OPENAI_MONTHLY_BUDGET_USD': '1',
                                  'OPENAI_BUDGET_MONTH': '2000-01', 'OPENAI_BUDGET_OPENING_USD': '0'},
                               capture_output=True, text=True, check=True, timeout=5)
        readback = json.loads(child.stdout)
        self.assertEqual(readback['opening_usd'], .95)
        self.assertEqual(readback['local_reserved_usd'], .03)
        self.assertEqual(readback['remaining_usd'], .02)

    async def test_one_provider_failure_preserves_other_provider_and_concurrent_refresh_is_ignored(self):
        google_budget.initialize_google_budget()
        root, refresh = self.render()
        original = budget_panel.run.io_bound
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(function):
            entered.set()
            await release.wait()
            return await original(function)

        with self.client, patch.object(budget_panel.run, 'io_bound', side_effect=delayed) as io:
            task = asyncio.create_task(refresh())
            await entered.wait()
            binding._refresh_step()
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '장부 새로고침')
            self.assertFalse(button.enabled)
            await refresh()
            self.assertEqual(io.call_count, 2)
            release.set()
            await task
        await asyncio.sleep(0)
        binding._refresh_step()
        self.assertTrue(button.enabled)
        self.assertIn('남은 예약 여유 ₩9,000', self.text(root))
        self.assertIn('장부 확인 필요', self.text(root))
