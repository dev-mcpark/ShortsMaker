"""Exercise the real Google SDK over an in-memory transport, without credentials or network."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from google import genai
from google.genai import errors, types
from google.oauth2.credentials import Credentials

from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.utils.character_video_generator import CharacterVideoGenerator
from shorts_maker.utils.config import settings


_REAL_CLIENT = genai.Client


class GoogleSDKRetryTests(unittest.TestCase):
    @contextmanager
    def offline_clients(self, status):
        clients, calls = [], []

        def client_factory(**kwargs):
            options = kwargs.pop('http_options', types.HttpOptions())
            location = kwargs['location']

            def respond(request):
                calls.append((location, request.method))
                return httpx.Response(status, json={
                    'error': {'code': status, 'message': 'offline fixture',
                              'status': 'RESOURCE_EXHAUSTED' if status == 429 else 'UNAVAILABLE'},
                })

            options.httpx_client = httpx.Client(transport=httpx.MockTransport(respond))
            client = _REAL_CLIENT(**{**kwargs, 'project': 'offline-test'},
                                  credentials=Credentials(token='offline-token'), http_options=options)
            clients.append(client)
            return client

        try:
            with patch('google.genai.Client', side_effect=client_factory):
                yield calls
        finally:
            for client in clients:
                client.close()
                asyncio.run(client.aio.aclose())

    def test_veo_sdk_sends_one_http_attempt_for_rate_limit_and_server_error(self):
        for status in (429, 503):
            with self.subTest(status=status), self.offline_clients(status) as calls:
                generator = VideoGenerator(mode='video')
                with self.assertRaises(errors.APIError):
                    generator.client.models.generate_videos(
                        model='veo-3.1-lite-generate-001', prompt='Offline miniature fixture',
                    )
                self.assertEqual(calls, [(settings.gcp_location, 'POST')])

    def test_global_image_sdk_sends_one_http_attempt_for_rate_limit_and_server_error(self):
        for status in (429, 503):
            with self.subTest(status=status), self.offline_clients(status) as calls, \
                    tempfile.TemporaryDirectory() as directory, patch.object(
                        settings, 'paid_production_enabled', True,
                    ), patch.object(settings, 'google_monthly_budget_krw', None):
                generator = VideoGenerator(mode='image')
                with self.assertRaises(errors.APIError):
                    generator._run_image_generation(
                        settings.image_model_id, SimpleNamespace(visual_description='Offline miniature'),
                        str(Path(directory) / 'unused.png'),
                    )
                self.assertEqual(calls, [('global', 'POST')])

    def test_character_sdk_sends_one_http_attempt_for_rate_limit_and_server_error(self):
        for status in (429, 503):
            with self.subTest(status=status), self.offline_clients(status) as calls:
                generator = CharacterVideoGenerator()
                with self.assertRaises(errors.APIError):
                    generator.client.models.generate_videos(
                        model='veo-3.1-lite-generate-001', prompt='Offline character fixture',
                    )
                self.assertEqual(calls, [(settings.gcp_location, 'POST')])
