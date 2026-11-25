"""Native auth-panel navigation/cancellation never authenticates or uploads to Google."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.youtube_connection_panel import render_youtube_connection_panel
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services.youtube_connection import local_upload_token_status
from shorts_maker.uploader.youtube_uploader import YOUTUBE_UPLOAD_SCOPE
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script
from test_youtube_connection import FakeProcess, URL


class ConnectionUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start(); self.addCleanup(loop.stop)
        self.client = Client(page('/youtube-connection'))
        self.addCleanup(self.client.delete)
        self.state = AppState(script=script(), final_video_path='keep.mp4')
        self.state.remember_script_draft(self.state.script_editor_key(), '{작성 중인 입력')

    def render(self):
        with self.client, ui.column() as root:
            render_youtube_connection_panel(self.state)
        return root

    def click(self, root, text):
        button = next(e for e in root.descendants() if getattr(e, 'text', '') == text)
        before = asyncio.all_tasks()
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
        return asyncio.all_tasks() - before

    async def flush(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        binding._refresh_step()

    async def test_render_is_passive_and_explicit_check_preserves_work(self):
        process = FakeProcess([{'event': 'ready'}], code=0)
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as create:
            root = self.render()
            create.assert_not_awaited()
            with self.client:
                tasks = self.click(root, '저장된 인증 확인')
                await asyncio.wait_for(asyncio.gather(*tasks), 2)
                await self.flush()
            create.assert_awaited_once()
        self.assertTrue(self.state.get_youtube_connection().checked_at)
        self.assertFalse(self.state.is_busy)
        self.assertIsNone(self.state.production_service)
        self.assertEqual(self.state.final_video_path, 'keep.mp4')
        self.assertEqual(self.state.script_editor_text(), '{작성 중인 입력')

    async def test_expanded_panel_reads_expired_token_without_dispatch_or_sensitive_output(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'token.json'
            data = {'expiry': '2000-01-01T00:00:00Z', 'scopes': [YOUTUBE_UPLOAD_SCOPE],
                    'token': 'access-fixture-private', 'refresh_token': 'refresh-fixture-private'}
            path.write_text(json.dumps(data))
            before = path.read_bytes()
            with patch.object(settings, 'token_file_path', path), patch(
                    'shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec',
                    new_callable=AsyncMock) as create:
                root = self.render()
                expander = next(e for e in root.descendants() if isinstance(e, ui.expansion))
                with self.client:
                    before_tasks = asyncio.all_tasks()
                    expander.value = True
                    await asyncio.wait_for(asyncio.gather(*(asyncio.all_tasks() - before_tasks)), 3)
                visible = '\n'.join(getattr(e, 'text', '') for e in root.descendants())
                self.assertIn('저장된 접근 토큰이 만료됐습니다. 갱신이 가능한지는', visible)
                self.assertNotIn(data['token'], visible)
                self.assertNotIn(data['refresh_token'], visible)
                create.assert_not_awaited()
                self.assertEqual(path.read_bytes(), before)

    async def test_local_token_hint_distinguishes_current_metadata_without_inventing_grants(self):
        now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'token.json'
            self.assertEqual(local_upload_token_status(path, now=now), 'missing')
            fields = {'scopes': [YOUTUBE_UPLOAD_SCOPE], 'token': 'synthetic'}
            for update, expected in (
                ({'expiry': '2026-12-01T00:00:00Z'}, 'unexpired'),
                ({'expiry': '2026-11-24T00:00:00Z'}, 'connection_required'),
                ({'expiry': '2026-11-24T00:00:00Z', 'refresh_token': 'synthetic'}, 'refresh_unverified'),
                ({'expiry': '2026-11-24T00:00:00Z', 'scopes': []}, 'scope_unconfirmed'),
                ({'expiry': '2026-12-01T00:00:00'}, 'unknown'),
            ):
                with self.subTest(expected):
                    path.write_text(json.dumps({**fields, **update}))
                    self.assertEqual(local_upload_token_status(path, now=now), expected)

    async def test_navigation_keeps_waiting_link_and_new_view_can_cancel(self):
        url = URL + '&q="><img src=x>'
        process = FakeProcess([{'event': 'authorization_url', 'url': url}])
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as create:
            root = self.render()
            with self.client:
                tasks = self.click(root, '업로드 계정 연결')
                for _ in range(10):
                    await self.flush()
                    if self.state.get_youtube_connection().authorization_url:
                        break
                self.assertTrue(self.state.is_busy)
                root.clear()
                new_root = self.render()
                await self.flush()
                html = next(e for e in new_root.descendants() if '로그인 창 직접 열기' in getattr(e, 'content', ''))
                self.assertIn('target="_blank"', html.content)
                self.assertIn('noopener noreferrer', html.content)
                self.assertNotIn('<img', html.content)
                self.assertIn('&quot;', html.content)
                self.click(new_root, '인증 대기 취소')
                await asyncio.wait_for(asyncio.gather(*tasks), 2)
                await self.flush()
            create.assert_awaited_once()
        self.assertFalse(self.state.is_busy)
        self.assertEqual(self.state.get_youtube_connection().authorization_url, '')
        self.assertEqual(process.terminated, 1)

    async def test_busy_and_deleted_views_do_not_start_or_reset_authentication(self):
        root = self.render()
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock) as create, self.client:
            self.state.pipeline_running = True
            await asyncio.wait_for(asyncio.gather(*self.click(root, '업로드 계정 연결')), 2)
            self.assertTrue(self.state.pipeline_running)
            self.state.pipeline_running = False
            button = next(e for e in root.descendants() if getattr(e, 'text', '') == '업로드 계정 연결')
            callback = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            root.clear()
            before = asyncio.all_tasks();callback(None)
            await asyncio.wait_for(asyncio.gather(*(asyncio.all_tasks() - before)), 2)
            create.assert_not_awaited()
        self.assertFalse(self.state.is_busy)

    async def test_failed_check_replaces_ready_state_without_starting_login(self):
        connection = self.state.get_youtube_connection()
        connection.checked_at = 'old check'
        connection.message = 'old success'
        process = FakeProcess([{'event': 'error', 'code': 'auth_required'}], code=1)
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as create:
            root = self.render()
            with self.client:
                await asyncio.wait_for(asyncio.gather(*self.click(root, '저장된 인증 확인')), 2)
                await self.flush()
        self.assertIn('--auth-check', create.call_args.args)
        self.assertFalse(connection.checked_at)
        self.assertNotIn('old success', connection.message)
        self.assertEqual(connection.authorization_url, '')
