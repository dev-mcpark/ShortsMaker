"""Exercise the installed SDK and parsed planning contracts without provider calls."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import AsyncOpenAI

from shorts_maker.planner.content_analyzer import ContentAnalyzer
from shorts_maker.planner.models import ShortsScript
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.services import openai_models
from shorts_maker.utils.config import settings
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter


class TerraPlanningTests(unittest.TestCase):
    def test_export_preserves_narrated_people_and_detail_instructions(self):
        script = ShortsScript(
            title='버스', description='개념도', tags=[], mood='calm', style='miniature',
            source_name='Source', source_url='https://example.com/bus', generation_mode='video',
            scenes=[dict(scene_number=1, script_text='승객 여덟 명이 탑니다.',
                         visual_description='Same blue capsule bus with eight seated passengers.',
                         motion_instruction='Camera moves toward the seats, keeping all eight visible.')],
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, 'clips_dir', Path(directory)):
            scene = json.loads(VeoPromptExporter().export_json(script, 'review'))['scenes'][0]
        self.assertIn(script.scenes[0].visual_description, scene['veo_prompt'])
        self.assertIn(script.scenes[0].motion_instruction, scene['veo_prompt'])
        self.assertNotIn('no people', scene['style_notes'])
        self.assertNotIn('4K', scene['style_notes'])
        self.assertIn('recurring identities', scene['style_notes'])

    def test_analysis_writer_and_validator_use_bounded_terra_json_requests(self):
        source = 'The completed depot has a water tank beneath its bus parking floor.'
        script = ShortsScript(
            title='차고지 아래에는 무엇이 있을까요?', description='출처에 근거한 개념 모형',
            tags=['도시'], mood='sci-fi', style='concept model',
            source_name='Source', source_url='https://example.com/depot', generation_mode='video',
            scenes=[dict(scene_number=n, script_text='차고지 아래에 저류조가 있습니다.',
                         visual_description='Same blue bus above a cutaway water tank.',
                         motion_instruction='Camera holds both levels in frame.', duration_seconds=6)
                    for n in range(1, 6)],
        )
        replies = [
            dict(core_message='Tank beneath parking', hook='What is beneath the depot?',
                 secret_mechanism='Tank', context_background='Completed depot',
                 future_impact='No measured benefit claimed', story_fit=True,
                 story_fit_evidence=source),
            script.model_dump(),
            dict(is_valid=True, score=80, reason='valid', feedback=''),
        ]
        requests = []

        def respond(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, '/v1/chat/completions')
            self.assertEqual(body['model'], 'gpt-6.1-terra')
            self.assertEqual(body['reasoning_effort'], 'low')
            self.assertEqual(body['service_tier'], 'default')
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertNotIn('temperature', body)
            self.assertNotIn('tools', body)
            content = replies[len(requests)]
            requests.append(body)
            return httpx.Response(200, json={
                'id': 'offline', 'object': 'chat.completion', 'created': 0,
                'model': body['model'], 'choices': [dict(index=0, finish_reason='stop',
                    message=dict(role='assistant', content=json.dumps(content)))],
            })

        async def exercise():
            async with AsyncOpenAI(api_key='offline-key', max_retries=0,
                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
                analyzer = object.__new__(ContentAnalyzer)
                analyzer.client, analyzer.logger, analyzer.model = client, Mock(), openai_models.PRIMARY_CHAT_MODEL
                article = SimpleNamespace(url=script.source_url, title=script.title,
                                          main_text=source, quotes=[], captions=[], headings=[])
                self.assertTrue((await analyzer.analyze_content(article)).story_fit)
                planner = object.__new__(ScriptPlanner)
                planner.client, planner.logger = client, Mock()
                planner.generation_mode, planner.allowed_moods = 'video', ['sci-fi']
                result = await planner._write_script(dict(title=script.title, content=source,
                                                         url=script.source_url, source='Source', category='City_Life'))
                self.assertEqual(result.model_dump(), script.model_dump())
                validator = object.__new__(ScriptValidator)
                validator.client, validator.logger = client, Mock()
                self.assertTrue((await validator.validate_script(result, source_text=source)).is_valid)

        with patch.object(settings, 'paid_production_enabled', True), \
                patch.object(settings, 'openai_monthly_budget_usd', None):
            asyncio.run(exercise())
        self.assertEqual([r['max_completion_tokens'] for r in requests], [1500, 4000, 1500])
        writer_prompt = requests[1]['messages'][0]['content']
        self.assertIn('Visible proof', writer_prompt)
        self.assertIn('Continuity anchors', writer_prompt)
        self.assertIn('Do not list cabin, capacity, route and fare', writer_prompt)
        self.assertIn('visual_discontinuity', requests[2]['messages'][0]['content'])

