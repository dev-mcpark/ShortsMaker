"""The Studio reads real isolated ledgers without releasing or resetting reserves."""

import asyncio
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import budget_panel
from shorts_maker.services import google_budget, openai_budget
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
        self.assertIn('이번 달 Google 사용액 기준을 다시 설정', self.text(root))
        self.assertIn('월 예산 미설정', self.text(root))
        self.assertNotIn('남은 예약 여유', self.text(root))

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
