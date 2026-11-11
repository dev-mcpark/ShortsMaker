"""Auth-only process and credential recovery use local fixtures, never Google."""

import asyncio
import contextlib
import io
import json
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.services.youtube_connection import YouTubeConnection
from shorts_maker.uploader import youtube_uploader as youtube


URL = 'https://accounts.google.com/o/oauth2/auth?client_id=fixture&state=temporary'


class TokenSafetyTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.token = self.root / 'token.json'
        self.token.write_text('{"kept":"fixture"}')
        self.uploader = youtube.YouTubeUploader()
        self.uploader.token_file = str(self.token)
        self.uploader.client_secrets_file = str(self.root / 'client.json')
        Path(self.uploader.client_secrets_file).write_text('{}')

    def refreshing_credentials(self):
        creds = SimpleNamespace(valid=False, expired=True, refresh_token='fixture',
                                to_json=lambda: '{"new":"fixture"}')
        creds.refresh = Mock(side_effect=lambda _: setattr(creds, 'valid', True))
        return creds

    def test_atomic_token_save_is_private_and_failure_keeps_previous_bytes(self):
        creds = self.refreshing_credentials()
        before = self.token.read_bytes()
        with patch.object(youtube.Credentials, 'from_authorized_user_info', return_value=creds), \
                patch.object(youtube, 'build') as build, patch.object(youtube.os, 'replace', side_effect=OSError('fixture full')):
            with self.assertRaises(OSError):
                self.uploader.get_authenticated_service(interactive=False)
            build.assert_not_called()
        self.assertEqual(self.token.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.token_*')), [])
        creds.valid = False
        with patch.object(youtube.Credentials, 'from_authorized_user_info', return_value=creds), patch.object(youtube, 'build'):
            self.uploader.get_authenticated_service(interactive=False)
        self.assertEqual(self.token.read_text(), '{"new":"fixture"}')
        self.assertEqual(stat.S_IMODE(self.token.stat().st_mode), 0o600)

    def test_fsync_failure_and_symlink_do_not_change_existing_credentials(self):
        before = self.token.read_bytes()
        with patch.object(youtube.Credentials, 'from_authorized_user_info', return_value=self.refreshing_credentials()), \
                patch.object(youtube.os, 'fsync', side_effect=OSError('fixture full')):
            with self.assertRaises(OSError):
                self.uploader.get_authenticated_service(interactive=False)
        self.assertEqual(self.token.read_bytes(), before)
        linked = self.root / 'linked.json'
        linked.symlink_to(self.token)
        self.uploader.token_file = str(linked)
        with self.assertRaises(ValueError):
            self.uploader.get_authenticated_service(interactive=False)
        self.assertEqual(self.token.read_bytes(), before)

    def test_cross_connection_lock_rejects_another_authentication_before_reading_token(self):
        with youtube._authentication_lock(self.token), patch.object(youtube.Credentials, 'from_authorized_user_info') as parse:
            with self.assertRaisesRegex(youtube.YouTubeAuthRequired, 'YOUTUBE_AUTH_BUSY'):
                self.uploader.get_authenticated_service(interactive=False)
            parse.assert_not_called()
        with youtube._authentication_lock(self.token):
            pass

    def test_callback_preserves_scope_and_sdk_flow_without_logging_url_or_invalid_token(self):
        old = self.token.read_bytes()
        self.token.unlink()
        flow = Mock()
        flow.authorization_url.return_value = (URL, 'original-state')
        creds = SimpleNamespace(valid=True, to_json=lambda: '{"saved":"fixture"}')
        def local_server(**options):
            self.assertEqual(options, {'port': 0, 'timeout_seconds': 300, 'authorization_prompt_message': None})
            self.assertEqual(flow.authorization_url(), (URL, 'original-state'))
            return creds
        flow.run_local_server.side_effect = local_server
        seen = Mock()
        with patch.object(youtube.InstalledAppFlow, 'from_client_secrets_file', return_value=flow) as factory, \
                patch.object(youtube, 'build'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.uploader.get_authenticated_service(on_authorization_url=seen)
        factory.assert_called_once_with(self.uploader.client_secrets_file, ['https://www.googleapis.com/auth/youtube.upload'])
        seen.assert_called_once_with(URL)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(self.token.read_text(), '{"saved":"fixture"}')
        self.token.write_bytes(old)
        flow = Mock(); flow.run_local_server.return_value = None
        with patch.object(youtube.Credentials, 'from_authorized_user_info', return_value=None), \
                patch.object(youtube.InstalledAppFlow, 'from_client_secrets_file', return_value=flow):
            with self.assertRaises(youtube.YouTubeAuthRequired):
                self.uploader.get_authenticated_service()
        self.assertEqual(self.token.read_bytes(), old)

    def test_auth_command_emits_only_safe_events_and_never_uploads(self):
        with patch.object(youtube.YouTubeUploader, 'get_authenticated_service') as authenticate, \
                patch.object(youtube.YouTubeUploader, 'upload') as upload, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(youtube.auth_command(['--auth-check', '--json-progress']), 0)
            self.assertFalse(authenticate.call_args.kwargs['interactive'])
            upload.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {'event': 'ready'})
        with patch.object(youtube.YouTubeUploader, 'get_authenticated_service', side_effect=OSError('DO_NOT_ECHO_SECRET')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(youtube.auth_command(['--auth-only', '--json-progress']), 1)
        self.assertNotIn('DO_NOT_ECHO', output.getvalue())
        for url in ('javascript:alert(1)', 'https://accounts.google.com.evil/login',
                    'https://user@accounts.google.com/login', 'http://accounts.google.com/login'):
            with self.assertRaises(ValueError):
                youtube.validate_authorization_url(url)

    def test_valid_json_with_wrong_structure_can_reconnect_without_losing_it_on_failure(self):
        for text in ('[]', 'null', '"fixture"'):
            self.token.write_text(text)
            with patch.object(youtube.Credentials, 'from_authorized_user_info') as parse, \
                    patch.object(youtube.InstalledAppFlow, 'from_client_secrets_file') as flow:
                flow.return_value.run_local_server.side_effect = OSError('fixture cancelled')
                with self.assertRaises(OSError):
                    self.uploader.get_authenticated_service()
                parse.assert_not_called()
            self.assertEqual(self.token.read_text(), text)


class FakeProcess:
    def __init__(self, events=(), code=None):
        self.stdout = asyncio.StreamReader()
        self.returncode = code
        self.stopped = asyncio.Event()
        self.terminated = 0
        for event in events:
            self.stdout.feed_data(json.dumps(event).encode() + b'\n')
        if code is not None:
            self.stdout.feed_eof(); self.stopped.set()

    async def wait(self):
        await self.stopped.wait()
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = -15
        self.stdout.feed_eof(); self.stopped.set()


class ConnectionProcessTests(IsolatedAsyncioTestCase):
    async def test_fixed_check_command_requires_ready_and_never_exposes_credentials(self):
        connection = YouTubeConnection()
        process = FakeProcess([{'event': 'ready'}], code=0)
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as create:
            await connection.run(interactive=False)
        self.assertEqual(create.call_args.args, (sys.executable, '-m', 'shorts_maker.uploader.youtube_uploader', '--auth-check', '--json-progress'))
        self.assertNotIn('shell', create.call_args.kwargs)
        self.assertTrue(connection.checked_at)
        self.assertFalse(connection.running)
        self.assertEqual(connection.authorization_url, '')
        for events, code in (([], 0), ([{'event': 'error', 'code': 'busy'}], 1), ([{'event': 'error', 'code': 'auth_required'}], 1)):
            with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock,
                       return_value=FakeProcess(events, code=code)):
                await connection.run(interactive=False)
            self.assertFalse(connection.checked_at)
            self.assertFalse(connection.running)

    async def test_cancel_stops_owned_child_clears_link_and_rejects_overlap(self):
        connection = YouTubeConnection()
        process = FakeProcess([{'event': 'authorization_url', 'url': URL}])
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as create:
            task = asyncio.create_task(connection.run(interactive=True))
            for _ in range(10):
                await asyncio.sleep(0)
                if connection.authorization_url:
                    break
            self.assertEqual(connection.authorization_url, URL)
            with self.assertRaises(ValueError):
                await connection.run(interactive=False)
            connection.cancel()
            await asyncio.wait_for(task, 2)
            create.assert_awaited_once()
        self.assertEqual(process.terminated, 1)
        self.assertFalse(connection.running)
        self.assertEqual(connection.authorization_url, '')
        self.assertFalse(connection.checked_at)

    async def test_bad_login_url_stops_child_and_does_not_leak_error_values(self):
        connection = YouTubeConnection()
        process = FakeProcess([{'event': 'authorization_url', 'url': 'javascript:DO_NOT_ECHO'}])
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process):
            await connection.run(interactive=True)
        self.assertEqual(process.terminated, 1)
        self.assertFalse(connection.running)
        self.assertNotIn('DO_NOT_ECHO', connection.message)
        self.assertEqual(connection.authorization_url, '')

    async def test_authentication_deadline_stops_owned_child_and_retains_unknown_state(self):
        connection = YouTubeConnection()
        process = FakeProcess([{'event': 'authorization_url', 'url': URL}])
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process), \
                patch('shorts_maker.services.youtube_connection.AUTH_TIMEOUT_SECONDS', 0):
            await connection.run(interactive=True)
        self.assertEqual(process.terminated, 1)
        self.assertIn('시간이 끝났습니다', connection.message)
        self.assertFalse(connection.running)
        self.assertFalse(connection.checked_at)
        self.assertEqual(connection.authorization_url, '')

    async def test_cancelled_ui_task_cleans_up_owned_process_before_releasing_busy(self):
        connection = YouTubeConnection()
        process = FakeProcess([{'event': 'authorization_url', 'url': URL}])
        with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process):
            task = asyncio.create_task(connection.run(interactive=True))
            for _ in range(10):
                await asyncio.sleep(0)
                if connection.authorization_url:
                    break
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(process.terminated, 1)
        self.assertFalse(connection.running)
        self.assertEqual(connection.authorization_url, '')

    async def test_cancellation_terminates_a_real_fixture_process_without_google(self):
        connection = YouTubeConnection()
        actual_create = asyncio.create_subprocess_exec
        children = []
        with TemporaryDirectory() as directory:
            program = Path(directory) / 'auth_fixture.py'
            token = Path(directory) / 'fixture-token.json'
            token.write_text('{"kept":"fixture"}')
            program.write_text('import json,time\nfrom pathlib import Path\nfrom shorts_maker.uploader.youtube_uploader import _authentication_lock\n'
                               + 'with _authentication_lock(Path(' + repr(str(token)) + ')):\n'
                               + ' print(json.dumps(' + repr({'event': 'authorization_url', 'url': URL}) + '),flush=True)\n time.sleep(60)\n')
            async def fixture(*args, **kwargs):
                child = await actual_create(sys.executable, str(program), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                children.append(child)
                return child
            with patch('shorts_maker.services.youtube_connection.asyncio.create_subprocess_exec', side_effect=fixture):
                task = asyncio.create_task(connection.run(interactive=True))
                try:
                    async with asyncio.timeout(3):
                        while not connection.authorization_url:
                            await asyncio.sleep(.01)
                    self.assertIsNone(children[0].returncode)
                finally:
                    connection.cancel()
                    await asyncio.wait_for(task, 3)
            self.assertNotEqual(children[0].returncode, 0)
            self.assertFalse(connection.running)
            self.assertEqual(token.read_text(), '{"kept":"fixture"}')
            with youtube._authentication_lock(token):
                pass
