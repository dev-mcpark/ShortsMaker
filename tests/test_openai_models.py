"""Shutdown boundaries must stop new spending while retained edits remain usable."""

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.services import openai_budget, openai_models
from shorts_maker.services.production_service import ProductionResult, ProductionService
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager


class OpenAIModelTests(unittest.TestCase):
    def at(self, day):
        return patch.object(openai_models, 'datetime', **{
            'now.return_value': datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
        })

    def test_shutdown_utc_boundary_for_each_pinned_role(self):
        for model, before, after in (
            ('tts-1', '2027-01-05T23:59:59', '2027-01-06T00:00:00'),
            ('gpt-4o', '2027-01-13T23:59:59', '2027-01-14T00:00:00'),
            ('gpt-4o-mini', '2027-01-13T23:59:59', '2027-01-14T00:00:00'),
        ):
            with self.subTest(model=model), self.at(before):
                openai_models.require_model_active(model)
            with self.subTest(model=model), self.at(after):
                with self.assertRaisesRegex(openai_models.ModelMigrationRequired, model):
                    openai_models.require_model_active(model)

    def test_retired_requests_fail_before_budget_initialization_even_if_budget_disabled(self):
        with self.at('2027-01-14'), patch.object(openai_budget, '_configured_period') as period:
            for request in (
                lambda: openai_budget.reserve_openai_chat('gpt-4o', [], 100),
                lambda: openai_budget.reserve_openai_speech('tts-1', '대본'),
                lambda: openai_budget.check_openai_speech_budget('tts-1', ['대본'], 2),
            ):
                with self.assertRaises(openai_models.ModelMigrationRequired):
                    request()
            period.assert_not_called()

    def test_fresh_cycle_stops_before_planning_but_retained_edit_can_continue(self):
        service = ProductionService(mode='video')
        service.generate_script = AsyncMock()
        service.produce_video = AsyncMock(return_value=ProductionResult(
            success=True, video_path='retained-edit.mp4'))
        with self.at('2027-01-06'), patch.object(settings, 'paid_production_enabled', True):
            result = asyncio.run(service.full_pipeline())
            self.assertFalse(result.success)
            self.assertIn('OPENAI_MODEL_RETIRED: tts-1', result.error)
            service.generate_script.assert_not_awaited()
            service.produce_video.assert_not_awaited()
            script = SimpleNamespace()
            result = asyncio.run(service.full_pipeline(
                approved_script=script, manual_clip_paths={1: 'clip.mp4'},
                prepared_audio_paths=['voice.mp3']))
        self.assertTrue(result.success)
        service.generate_script.assert_not_awaited()
        service.produce_video.assert_awaited_once_with(
            script, finish_phase=True, manual_clip_paths={1: 'clip.mp4'},
            prepared_audio_paths=['voice.mp3'])

    def test_topic_scorer_propagates_retirement_without_submitting_or_retrying(self):
        planner = object.__new__(ScriptPlanner)
        planner.logger = Mock()
        create = AsyncMock()
        planner.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as directory, self.at('2027-01-14'), patch.object(
            settings, 'paid_production_enabled', True,
        ):
            planner.history_file = str(Path(directory) / 'history.json')
            with self.assertRaises(openai_models.ModelMigrationRequired):
                asyncio.run(planner._score_topics([
                    {'category': 'City_Life', 'title': '기사', 'content': '출처 요약'},
                ]))
        create.assert_not_awaited()

    def test_schedule_pauses_on_returned_and_raised_retirement(self):
        error = openai_models.ModelMigrationRequired('OPENAI_MODEL_RETIRED: tts-1')
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, 'paid_production_enabled', True,
        ), patch('shorts_maker.services.google_budget.budget_status', return_value={
            'enabled': True, 'remaining_krw': 1000,
        }), patch('shorts_maker.services.openai_budget.budget_status', return_value={
            'enabled': True, 'remaining_usd': .1,
        }), patch('shorts_maker.utils.bgm_manager.BGMManager.has_documented_track', return_value=True):
            manager = ScheduleManager(str(Path(directory) / 'schedules.json'))
            for raises in (False, True):
                schedule = manager.create_schedule(f'Pause {raises}', '19:00')
                pipeline = AsyncMock(side_effect=error) if raises else AsyncMock(
                    return_value=ProductionResult(success=False, error=str(error)))
                with patch.object(ProductionService, 'full_pipeline', pipeline):
                    asyncio.run(manager._execute_pipeline(schedule))
                    asyncio.run(manager._execute_pipeline(schedule))
                stored = manager.get_schedule(schedule['id'])
                self.assertEqual(stored['last_result'], 'model_migration_required')
                self.assertFalse(stored['enabled'])
                self.assertEqual(stored['run_count'], 1)
                pipeline.assert_awaited_once()
