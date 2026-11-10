"""Feedback regeneration observes cancellation without losing paid-result evidence."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.services.production_service import ProductionPhase, ProductionService
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script


class RegenerationCancellationTests(IsolatedAsyncioTestCase):
    async def test_new_regeneration_clears_error_from_previous_attempt(self):
        service = ProductionService()
        service._progress.error = 'old failed request'
        output = script('new response')
        service._get_planner = Mock(return_value=SimpleNamespace(regenerate=AsyncMock(return_value=output)))
        with patch.object(settings, 'paid_production_enabled', True):
            result = await service.regenerate_script(self.context(), '수정 요청')
        self.assertIs(result, output)
        self.assertIsNone(service.progress.error)

    def context(self):
        return SimpleNamespace(attempt_count=0, max_attempts=3, source_item={'url': 'https://example.com/source'})

    async def test_preexisting_cancellation_submits_nothing_and_does_not_consume_attempt(self):
        service = ProductionService()
        service.cancel()
        service._get_planner = Mock()
        context = self.context()
        with patch.object(settings, 'paid_production_enabled', True):
            result = await service.regenerate_script(context, '수정 요청')
        self.assertIsNone(result)
        self.assertEqual(context.attempt_count, 0)
        service._get_planner.assert_not_called()
        self.assertEqual(service.progress.phase, ProductionPhase.FAILED)
        self.assertIn('취소', service.progress.message)

    async def test_cancellation_from_pre_submit_progress_does_not_buy_an_attempt(self):
        service = ProductionService()
        service._get_planner = Mock()
        context = self.context()

        def cancel_at_submission(progress):
            if progress.phase == ProductionPhase.PLANNING and progress.progress_percent == 20:
                service.cancel()

        service.set_progress_callback(cancel_at_submission)
        with patch.object(settings, 'paid_production_enabled', True):
            result = await service.regenerate_script(context, '수정 요청')
        self.assertIsNone(result)
        self.assertEqual(context.attempt_count, 0)
        service._get_planner.assert_not_called()

    async def test_cancellation_after_submission_retains_result_and_consumed_attempt_without_success(self):
        service = ProductionService()
        context = self.context()
        started, release = asyncio.Event(), asyncio.Event()
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / 'generated_script.json'
            output = script('별도 보관된 응답')

            async def generate(*args, **kwargs):
                started.set()
                await release.wait()
                artifact.write_text(output.model_dump_json(), encoding='utf-8')
                return output

            planner = SimpleNamespace(regenerate=AsyncMock(side_effect=generate))
            service._get_planner = Mock(return_value=planner)
            with patch.object(settings, 'paid_production_enabled', True):
                task = asyncio.create_task(service.regenerate_script(context, '수정 요청'))
                await started.wait()
                service.cancel()
                release.set()
                result = await task
            self.assertIsNone(result)
            self.assertEqual(artifact.read_text(encoding='utf-8'), output.model_dump_json())
        self.assertEqual(context.attempt_count, 1)
        planner.regenerate.assert_awaited_once_with(context.source_item, feedback='수정 요청')
        self.assertEqual(service.progress.phase, ProductionPhase.FAILED)
        self.assertIn('취소', service.progress.message)

    async def test_readonly_gate_still_prevents_submission_and_attempt(self):
        service = ProductionService()
        service._get_planner = Mock()
        context = self.context()
        with patch.object(settings, 'paid_production_enabled', False):
            result = await service.regenerate_script(context, '수정 요청')
        self.assertIsNone(result)
        self.assertEqual(context.attempt_count, 0)
        service._get_planner.assert_not_called()
        self.assertEqual(service.progress.error, service.PAID_WORK_DISABLED)
