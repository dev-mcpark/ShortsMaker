"""Episode UI/process boundary: only temporary ledgers and mocked provider services."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from scripts.operate_schedule import run_scoped
from shorts_maker.gui.components.episode_workspace import render_episode_workspace
from shorts_maker.gui.components import generation_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import google_budget, openai_budget, scoped_production, studio_episode_action as action
from shorts_maker.services.operating_budget import begin_episode, episode_environment, episode_path
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import ProductionResult, ProductionService, script_sha256
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from test_gui_creation_flows import script


class EpisodeWorkspaceTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in [('output_dir', self.root / 'outputs'),
                            ('google_monthly_budget_krw', 10000), ('google_budget_opening_krw', 0),
                            ('google_budget_month', google_budget._period()), ('google_usd_krw_rate', 2000),
                            ('openai_monthly_budget_usd', 1.), ('openai_budget_opening_usd', 0),
                            ('openai_budget_month', openai_budget._period()), ('paid_production_enabled', True)]:
            p = patch.object(settings, name, value);p.start();self.addCleanup(p.stop)
        google_budget.initialize_google_budget();openai_budget.initialize_openai_budget()
        self.manager = ScheduleManager(str(self.root / 'schedules.json'), queue_only=True)
        scheduled = self.manager.create_schedule('임시 회차', '19:00', frequency='Every 2 Weeks')
        self.script = script().model_copy(update={'generation_mode': 'video'})
        self.schedule = self.manager.update_schedule(scheduled['id'], {'review_operator': 'agent',
            'enabled': False, 'run_count': 1, 'last_result': 'script_review_pending',
            'last_script': self.script.model_dump(mode='json')})
        self.record = begin_episode(scheduled['id'], 1)
        self.schedule = self.manager.update_schedule(scheduled['id'], {'last_episode_id': self.record['id']})
        self.state = AppState()
        self.state.load_scheduled_script(self.manager, scheduled['id'])
        self.scope = action.EpisodeScope.model_validate(self.state.operating_scope)
        self.pending = episode_path(self.record['id']).with_suffix('.operation.pending.json')

    def request(self, operation='raw', **kw):
        fields = dict(scope=self.scope, operation=operation, schedule_sha256=schedule_sha256(self.schedule),
            script_sha256=script_sha256(self.script.model_dump(mode='json')), review_receipt=script_draft_key(self.script),
            mode='video', image_model=settings.image_model_id, scene_index=0, request_budget_usd=.24)
        fields.update(kw)
        request = action.StudioAction(**fields)
        directory = action.action_directory();directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{uuid4().hex}.request.json'
        path.write_text(request.model_dump_json())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.pending.exists():
            self.pending.write_text(json.dumps({'command_sha256': hashlib.sha256(json.dumps(action.worker_command(path, digest)).encode()).hexdigest()}))
        return request, path, digest

    def scoped_env(self):
        env, _ = episode_environment(self.record)
        self.enterContext(patch.dict(os.environ, env))
        for key, value in env.items():
            if key == 'SHORTSMAKER_EPISODE_ID':
                continue
            name = {'GOOGLE_USD_KRW_RESERVE_RATE': 'google_usd_krw_rate'}.get(key, key.lower())
            old = getattr(settings, name)
            self.enterContext(patch.object(settings, name, type(old)(value) if type(old) is not bool else value == 'true'))
        self.pending.write_text('{}')

    async def test_binding_pins_lite_without_changing_global_settings_and_survives_free_edits(self):
        old = settings.veo_model_id, settings.veo_duration_seconds, settings.openai_api_key
        self.state.confirm_script_review()
        service = self.state.new_production_service()
        self.assertIsInstance(service, scoped_production.ScopedProductionService)
        self.assertEqual(service.video_spec(), ('veo-3.1-lite-generate-001', 8))
        self.assertIn('lite', self.state.video_model_label)
        self.assertIs(service, self.state.get_or_create_service())
        before = self.state.execution_key()
        with patch.object(settings, 'paid_production_enabled', False):
            with self.assertRaises(RuntimeError):
                self.state.require_execution_context(before)
            self.assertFalse(generation_tab._auto_edit_ready(self.state, {}))
        self.state.load_saved_script(self.script.model_copy(update={'title': '무료 수정'}))
        self.assertEqual(before, self.state.execution_key())
        with self.assertRaisesRegex(ValueError, '회차에 저장'):
            self.state.require_execution_context(before)
        self.state.detach_operating_scope()
        self.assertNotIn('회차 고정', self.state.video_model_label)
        with self.assertRaisesRegex(ValueError, '연결이 바뀌'):
            self.state.require_execution_context(before)
        self.assertIs(type(self.state.new_production_service()), ProductionService)
        self.assertEqual(old, (settings.veo_model_id, settings.veo_duration_seconds, settings.openai_api_key))

    async def test_pending_attached_wrong_episode_and_stale_review_cannot_dispatch(self):
        for change in ({'enabled': True}, {'last_youtube_id': 'already_uploaded'}, {'last_video_path': 'existing.mp4'},
                       {'last_episode_id': 'f' * 32}):
            self.manager.update_schedule(self.schedule['id'], change)
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.state.load_scheduled_script(self.manager, self.schedule['id'])
            self.manager.save_schedules([self.schedule])
        self.pending.write_text('{}')
        with self.assertRaisesRegex(ValueError, '먼저 대조'):
            action.scope_status(self.scope)
        self.pending.unlink()
        with patch.object(scoped_production.asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as start:
            with self.assertRaisesRegex(ValueError, '먼저 확인'):
                await self.state.new_production_service().generate_first_frame(self.script, 0, request_budget_usd=.034)
            start.assert_not_awaited()

    async def test_worker_uses_existing_four_services_and_typed_local_inputs(self):
        self.scoped_env()
        clips = {0: str(self.root / 'clip.mp4')}
        for operation, method, result in [('frame', 'generate_first_frame', 'frame.png'),
                ('raw', 'generate_review_clip', 'raw.mp4'), ('edit', 'produce_video', ProductionResult(True)),
                ('upload', 'upload_to_youtube', ProductionResult(True, youtube_id='private_test'))]:
            video = settings.output_dir / 'test.mp4'
            video.write_bytes(b'fixture')
            video.with_suffix('.production.json').write_text(json.dumps({'script_sha256': script_sha256(self.script.model_dump(mode='json'))}))
            request, path, digest = self.request(operation, manual_clip_paths=clips,
                prepared_audio_paths=['scene.mp3'], video_path=str(video), metadata={'title': '한글'})
            parsed = action.read_request(path, digest)
            self.assertEqual(parsed.manual_clip_paths, clips)
            mock = AsyncMock(return_value=result)
            with patch.object(ProductionService, method, mock):
                response = await action.execute_action(parsed, path, digest)
            mock.assert_awaited_once()
            self.assertEqual(response['kind'], 'path' if operation in {'frame', 'raw'} else 'production')
            if operation == 'edit':
                self.assertTrue(mock.await_args.kwargs['retain_narration'])
                self.assertEqual(mock.await_args.kwargs['prepared_audio_paths'], ['scene.mp3'])

    async def test_worker_rejects_wrong_profile_caps_hash_and_unreviewed_before_paid_work(self):
        self.scoped_env()
        request, path, digest = self.request()
        with patch.object(ProductionService, 'generate_review_clip', new_callable=AsyncMock) as paid:
            for change in ({'schedule_sha256': 'a' * 64}, {'script_sha256': 'a' * 64},
                           {'review_receipt': 'a' * 64}, {'image_model': 'unexpected'}, {'scene_index': 99}):
                with self.assertRaises(ValueError):
                    await action.execute_action(request.model_copy(update=change), path, digest)
            for name, value in [('veo_model_id', 'expensive-model'), ('veo_duration_seconds', 4),
                                ('google_monthly_budget_krw', 10001), ('openai_monthly_budget_usd', 2.)]:
                with patch.object(settings, name, value), self.assertRaises(ValueError):
                    await action.execute_action(request, path, digest)
            paid.assert_not_awaited()
            self.pending.write_text('{}')
            with self.assertRaisesRegex(ValueError, '다른 회차 요청'):
                await action.execute_action(request, path, digest)
            paid.assert_not_awaited()

    async def test_old_frame_and_edit_buttons_cannot_spend_after_explicit_scope_switch(self):
        import ast
        from test_gui_operation_flows import _UI
        self.state.confirm_script_review()
        self.state.new_production_service = Mock()
        recorder = _UI()
        with patch.object(generation_tab, 'ui', recorder), patch.object(generation_tab, 'media_sources', return_value=lambda p: p), \
             patch.object(generation_tab, 'safe_notify') as notify:
            generation_tab.render_first_frame_reviews(self.state)
            core = next(n for n in ast.walk(ast.parse(Path(generation_tab.__file__).read_text()))
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_production_core')
            wrapper = ast.parse('def factory():\n video_player = None\n placeholder_content = None\n return _run_production_core\n')
            wrapper.body[0].body.insert(-1, core)
            namespace = {'state': self.state, 'rendered_script': self.script.model_dump_json(),
                         'safe_notify': notify, 'settings': settings}
            exec(compile(ast.fix_missing_locations(wrapper), 'scope-edit', 'exec'), namespace)
            edit = namespace['factory']()
            self.state.final_video_path = 'keep-existing.mp4'
            self.state.detach_operating_scope()
            await recorder.find('button', '첫 프레임 후보 생성').callback()
            await edit()
        self.state.new_production_service.assert_not_called()
        self.assertEqual(self.state.final_video_path, 'keep-existing.mp4')
        self.assertTrue(all('연결이 바뀌' in call.args[0] for call in notify.call_args_list))

    async def test_root_requires_fixed_worker_and_preserves_unknown_receipt_pending_gate(self):
        request, path, digest = self.request()
        command = [sys.executable, '-m', 'shorts_maker.services.studio_episode_action', str(path), digest]
        before = self.manager.filename.read_bytes(), episode_path(self.record['id']).read_bytes()
        with patch('scripts.operate_schedule.subprocess.run', return_value=SimpleNamespace(returncode=0)) as child:
            with self.assertRaises(ValueError):
                run_scoped(self.manager, self.schedule['id'], [sys.executable, '-c', 'pass'], studio_request=path, request_sha256=digest)
            self.assertFalse(self.pending.exists());child.assert_not_called()
            with self.assertRaises(FileNotFoundError):
                run_scoped(self.manager, self.schedule['id'], command, studio_request=path, request_sha256=digest)
            self.assertTrue(self.pending.exists())
        self.assertEqual(before, (self.manager.filename.read_bytes(), episode_path(self.record['id']).read_bytes()))
        self.pending.unlink()  # Only this isolated, zero-provider fixture.
        result_path = path.with_suffix('.result.json')
        def child(*args, **kwargs):
            action.write_message(result_path, {'request_sha256': digest, 'status': 'returned', 'kind': 'path', 'value': 'raw.mp4'})
            return SimpleNamespace(returncode=0)
        with patch('scripts.operate_schedule.subprocess.run', side_effect=child):
            self.assertEqual(run_scoped(self.manager, self.schedule['id'], command, studio_request=path, request_sha256=digest), 0)
            self.assertFalse(self.pending.exists())
            with self.assertRaisesRegex(ValueError, '이미 실행'):
                run_scoped(self.manager, self.schedule['id'], command, studio_request=path, request_sha256=digest)

    async def test_proxy_fixed_argv_progress_and_production_receipt_roundtrip(self):
        self.state.confirm_script_review()
        service = self.state.new_production_service()
        async def start(*argv, **kw):
            self.assertEqual(argv[4:6], ('run', '--studio-request'))
            path, digest = Path(argv[-2]), argv[-1]
            request = action.read_request(path, digest)
            self.assertEqual(request.scope, self.scope)
            self.assertLessEqual(path.stat().st_mode & 0o777, 0o600)
            async def wait():
                action.write_message(path.with_suffix('.result.json'), {'status': 'returned', 'request_sha256': digest,
                    'kind': 'production', 'value': asdict(ProductionResult(True, video_path='fixture.mp4'))})
                return 0
            return SimpleNamespace(wait=wait)
        with patch.object(scoped_production.asyncio, 'create_subprocess_exec', side_effect=start):
            result = await service.produce_video(self.script)
        self.assertTrue(result.success)
        self.assertEqual(result.video_path, 'fixture.mp4')
        self.assertIsNone(service._request_path)

    async def test_malformed_or_changed_receipt_keeps_episode_pending_and_cannot_resubmit(self):
        for payload in ({'kind': 'path', 'value': ''}, {'kind': 'production', 'value': {'success': 'yes'}},
                        {'kind': 'path', 'value': 'raw.mp4', 'cancelled': 'false'}):
            _, path, digest = self.request()
            command = [sys.executable, '-m', 'shorts_maker.services.studio_episode_action', str(path), digest]
            def child(*args, **kwargs):
                action.write_message(path.with_suffix('.result.json'), {'status': 'returned', 'request_sha256': digest, **payload})
                return SimpleNamespace(returncode=0)
            with patch('scripts.operate_schedule.subprocess.run', side_effect=child) as run:
                with self.assertRaises(ValueError):
                    run_scoped(self.manager, self.schedule['id'], command, studio_request=path, request_sha256=digest)
                self.assertTrue(self.pending.exists())
                with self.assertRaises(ValueError):
                    run_scoped(self.manager, self.schedule['id'], command, studio_request=path, request_sha256=digest)
                run.assert_called_once()
            self.pending.unlink()  # Only isolated mocked executions; real unknown work remains locked.

    async def test_proxy_cancellation_waits_for_child_receipt_without_killing_or_retrying(self):
        self.state.confirm_script_review()
        service = self.state.new_production_service()
        started = asyncio.Event()
        async def start(*argv, **kw):
            path, digest = Path(argv[-2]), argv[-1]
            async def wait():
                started.set()
                for _ in range(100):
                    if path.with_suffix('.cancel').exists():
                        self.assertEqual(path.with_suffix('.cancel').read_text(), digest)
                        action.write_message(path.with_suffix('.result.json'), {'status': 'returned', 'request_sha256': digest,
                            'kind': 'production', 'cancelled': True, 'value': asdict(ProductionResult(False, error='cancelled'))})
                        return 0
                    await asyncio.sleep(.001)
                self.fail('Cancellation marker missing')
            return SimpleNamespace(wait=wait)
        with patch.object(scoped_production.asyncio, 'create_subprocess_exec', side_effect=start) as child:
            task = asyncio.create_task(service.produce_video(self.script))
            await started.wait();service.cancel()
            result = await task
            self.assertFalse(result.success);self.assertTrue(service.is_cancelled())
            child.assert_awaited_once()
        self.assertFalse(self.pending.exists())

    async def test_proxy_process_failure_does_not_fall_back_to_unscoped_paid_service(self):
        self.state.confirm_script_review()
        service = self.state.new_production_service()
        with patch.object(scoped_production.asyncio, 'create_subprocess_exec', side_effect=OSError('fixture start error')) as child, \
             patch.object(ProductionService, 'produce_video', new_callable=AsyncMock) as unsafe:
            with self.assertRaises(OSError):
                await service.produce_video(self.script)
            child.assert_awaited_once();unsafe.assert_not_awaited()
        self.assertIsNone(service._request_path)
        self.assertFalse(self.pending.exists())

    async def test_real_cli_child_transports_scoped_action_with_offline_provider_only(self):
        _, path, digest = self.request('frame')
        hooks = self.root / 'hooks';hooks.mkdir()
        (hooks / 'sitecustomize.py').write_text('''import os
from pathlib import Path
from shorts_maker.utils.config import settings
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.production_service import ProductionService
settings.output_dir=Path(os.environ['STUDIO_TEST_OUTPUT'])
settings.google_budget_month=google_budget._period();settings.google_budget_opening_krw=0
settings.openai_budget_month=openai_budget._period();settings.openai_budget_opening_usd=0
settings.google_monthly_budget_krw=int(os.getenv('GOOGLE_MONTHLY_BUDGET_KRW','10000'))
settings.openai_monthly_budget_usd=float(os.getenv('OPENAI_MONTHLY_BUDGET_USD','1'))
settings.openai_api_key='';settings.gcp_project_id='offline-fixture'
async def blocked(*args,**kwargs):
 raise AssertionError('All real provider actions are blocked in the transport fixture')
for method in ('produce_video','generate_script','regenerate_script','generate_review_clip','upload_to_youtube'):
 setattr(ProductionService,method,blocked)
async def frame(self,script,scene_index,**kwargs):
 assert os.environ['SHORTSMAKER_EPISODE_ID']
 assert settings.veo_model_id=='veo-3.1-lite-generate-001'
 assert settings.google_monthly_budget_krw<=3000 and settings.openai_monthly_budget_usd<=.3
 output=settings.output_dir/'offline-transport.png';output.write_bytes(b'mocked image, not paid media')
 return str(output)
ProductionService.generate_first_frame=frame
''')
        command = [sys.executable, str(Path('scripts/operate_schedule.py').resolve()), '--schedules',
            str(self.manager.filename), 'run', '--studio-request', str(path), '--request-sha256', digest,
            self.schedule['id'], '--', sys.executable, '-m', 'shorts_maker.services.studio_episode_action', str(path), digest]
        before = google_budget._database_path().read_bytes(), openai_budget._database_path().read_bytes()
        env = {**os.environ, 'PYTHONPATH': str(hooks), 'STUDIO_TEST_OUTPUT': str(settings.output_dir),
               'GOOGLE_MONTHLY_BUDGET_KRW': '10000', 'OPENAI_MONTHLY_BUDGET_USD': '1'}
        result = await asyncio.to_thread(subprocess.run, command, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = action.validate_receipt(path, digest)
        self.assertEqual(receipt['kind'], 'path', receipt)
        self.assertTrue(Path(receipt['value']).is_file())
        self.assertFalse(self.pending.exists())
        self.assertEqual(before, (google_budget._database_path().read_bytes(), openai_budget._database_path().read_bytes()))

    async def test_explicit_scope_detach_dialog_preserves_inputs_and_stale_events(self):
        self.enterContext(patch.object(core, 'loop', asyncio.get_running_loop()))
        client = Client(page('/scope-fixture'));self.addCleanup(client.delete)
        refresh = Mock()
        before = self.manager.filename.read_bytes()
        with client:
            render_episode_workspace(self.state, refresh)
            def click(text):
                button = next(e for e in client.elements.values() if getattr(e, 'text', '') == text)
                next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
            click('회차 연결 해제');click('취소')
            self.assertIsNotNone(self.state.operating_scope)
            click('회차 연결 해제');click('수동 제작으로 전환')
        self.assertIsNone(self.state.operating_scope)
        self.assertEqual(self.state.script, self.script)
        self.assertEqual(before, self.manager.filename.read_bytes())
        refresh.assert_called_once()
