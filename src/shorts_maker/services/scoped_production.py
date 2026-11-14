"""ProductionService UI contract with paid work delegated to the existing scoped CLI."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.operating_budget import episode_video_spec
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import ProductionPhase, ProductionProgress, ProductionResult, ProductionService, SceneProgress, script_sha256
from shorts_maker.services.studio_episode_action import EpisodeScope, StudioAction, action_directory, scope_status, validate_receipt, worker_command
from shorts_maker.utils.config import PROJECT_ROOT, settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled


class ScopedProductionService(ProductionService):
    def __init__(self, scope: dict, review_receipt: str | None, **options):
        super().__init__(max_veo_attempts=1, **options)
        self.scope = dict(scope)
        self.review_receipt = review_receipt
        self._request_path = None
        self._request_digest = None

    def video_spec(self):
        return episode_video_spec(self.mode)

    def cancel(self):
        super().cancel()
        if self._request_path and self._request_digest:
            marker = self._request_path.with_suffix('.cancel')
            if not marker.exists():
                with marker.open('x', encoding='utf-8') as file:
                    file.write(self._request_digest)

    async def _dispatch(self, operation, script=None, **parameters):
        require_paid_production_enabled()
        scope = EpisodeScope.model_validate(self.scope)
        current, _ = await asyncio.to_thread(scope_status, scope, script)
        current_script = ShortsScript.model_validate(current['last_script'])
        from shorts_maker.services.work_drafts import script_draft_key
        if self.review_receipt != script_draft_key(current_script):
            raise ValueError('회차의 현재 대본을 먼저 확인하세요.')
        request = StudioAction(scope=scope, operation=operation,
            schedule_sha256=schedule_sha256(current), script_sha256=script_sha256(current_script.model_dump(mode='json')),
            review_receipt=self.review_receipt, mode=self.mode, image_model=settings.image_model_id,
            editor_options=self.editor_options,
            overlay_options=self.character_overlay_config.to_dict() if self.character_overlay_config else {}, **parameters)
        directory = action_directory();directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f'{uuid4().hex}.request.json'
        content = request.model_dump_json().encode('utf-8')
        if len(content) > 2 * 1024 * 1024:
            raise ValueError('회차 요청 크기를 확인하세요.')
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
            file.write(content);file.flush();os.fsync(file.fileno())
        digest = hashlib.sha256(content).hexdigest()
        self._request_path, self._request_digest = path, digest
        if self.is_cancelled():
            raise ValueError('회차 작업이 취소됐습니다. 요청하지 않습니다.')
        command = [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'), '--schedules', scope.schedules_file,
            'run', '--studio-request', str(path), '--request-sha256', digest, scope.schedule_id, '--',
            *worker_command(path, digest)]
        self._update_progress(ProductionPhase.UPLOADING if operation == 'upload' else ProductionPhase.GENERATING, 0, '회차 상한 안에서 실행 중')
        try:
            process = await asyncio.create_subprocess_exec(*command, cwd=PROJECT_ROOT,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            self._request_path = self._request_digest = None
            self._update_progress(ProductionPhase.FAILED, 0, '회차 실행 프로세스를 시작하지 못했습니다.')
            raise
        waiter = asyncio.create_task(process.wait())
        try:
            while not waiter.done():
                try:
                    await asyncio.wait_for(asyncio.shield(waiter), .3)
                except asyncio.TimeoutError:
                    self._read_progress(path)
            self._read_progress(path)
            if waiter.result() != 0:
                raise ValueError('회차 실행이 중단됐습니다. 현재 상태·결과 기록을 먼저 대조하세요. 자동 재시도하지 않습니다.')
            receipt = await asyncio.to_thread(validate_receipt, path, digest)
            self._cancelled = self._cancelled or receipt.get('cancelled', False)
            if receipt['kind'] == 'error':
                raise ValueError(receipt['error'])
            if receipt['kind'] == 'path':
                return receipt['value']
            data = receipt['value']
            if data.get('script'):
                data['script'] = ShortsScript.model_validate(data['script'])
            result = ProductionResult(**data)
            self._update_progress(ProductionPhase.COMPLETED if result.success else ProductionPhase.FAILED,
                                  100 if result.success else 0, '회차 작업 완료' if result.success else result.error or '회차 작업 중단')
            return result
        except asyncio.CancelledError:
            self.cancel()
            # Wait for cooperative cancellation; never kill/retry an uncertain paid request.
            await asyncio.shield(waiter)
            raise
        except Exception as error:
            self._update_progress(ProductionPhase.FAILED, 0, str(error))
            raise
        finally:
            if waiter.done():
                self._request_path = self._request_digest = None

    def _read_progress(self, path):
        try:
            progress = path.with_suffix('.progress.json')
            if progress.is_symlink() or progress.stat().st_size > 2 * 1024 * 1024:
                return
            data = json.loads(progress.read_text())
            data['phase'] = ProductionPhase(data['phase'])
            data['scene_progresses'] = [SceneProgress(**row) for row in data['scene_progresses']]
            self._progress = ProductionProgress(**data)
            self._notify_progress()
        except (OSError, ValueError, TypeError, KeyError):
            pass

    async def prepare_narration(self, script, *, request_budget_usd):
        return await self._dispatch('narration', script, narration_budget_usd=request_budget_usd)

    async def generate_first_frame(self, script, scene_index, *, request_budget_usd):
        return await self._dispatch('frame', script, scene_index=scene_index, request_budget_usd=request_budget_usd)

    async def generate_review_clip(self, script, scene_index, *, request_budget_usd=None, expected_frame_sha256=None, manual_clip_paths=None):
        return await self._dispatch('raw', script, scene_index=scene_index, request_budget_usd=request_budget_usd,
                                    expected_frame_sha256=expected_frame_sha256, manual_clip_paths=manual_clip_paths)

    async def produce_video(self, script, manual_clip_paths=None, finish_phase=True, prepared_audio_paths=None, retain_narration=False):
        return await self._dispatch('edit', script, manual_clip_paths=manual_clip_paths,
                                    prepared_audio_paths=prepared_audio_paths, finish_phase=finish_phase)

    async def upload_to_youtube(self, video_path, metadata):
        return await self._dispatch('upload', video_path=video_path, metadata=metadata)

    async def generate_script(self, *args, **kwargs):
        raise ValueError('회차 기획은 예약 운영에서 진행하세요. 다른 소재는 수동 작업으로 전환하세요.')

    regenerate_script = generate_script
    full_pipeline = generate_script
