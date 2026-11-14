"""Fixed Studio actions inside the existing episode-scoped operator child."""

import asyncio
import hashlib
import json
import os
import re
import tempfile
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue, TypeAdapter, ValidationError

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.operating_budget import episode_environment, episode_path, load_episode
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import ProductionResult, ProductionService, script_sha256
from shorts_maker.services.work_drafts import script_draft_key
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled
from shorts_maker.utils.scheduler import ScheduleManager


class EpisodeScope(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schedules_file: str
    schedule_id: str
    episode_id: str = Field(pattern=r'^[0-9a-f]{32}$')


class StudioAction(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    scope: EpisodeScope
    operation: Literal['frame', 'raw', 'narration', 'edit', 'upload']
    schedule_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    script_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_receipt: str = Field(pattern=r'^[0-9a-f]{64}$')
    mode: Literal['image', 'hybrid', 'video']
    image_model: str
    scene_index: int | None = Field(default=None, ge=0)
    request_budget_usd: FiniteFloat | None = Field(default=None, gt=0)
    narration_budget_usd: FiniteFloat | None = Field(default=None, ge=0)
    expected_frame_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    manual_clip_paths: dict[int, str] | None = None
    prepared_audio_paths: list[str] | None = None
    finish_phase: bool = True
    video_path: str | None = None
    metadata: dict[str, JsonValue] | None = None
    editor_options: dict[str, JsonValue] = Field(default_factory=dict)
    overlay_options: dict[str, JsonValue] = Field(default_factory=dict)


def action_directory() -> Path:
    directory = settings.output_dir / 'evaluation' / 'studio_episode_actions'
    if directory.is_symlink() or not directory.resolve().is_relative_to(settings.output_dir.resolve()):
        raise ValueError('회차 작업 보관 경로를 확인하세요.')
    return directory


def action_path(path: str | Path) -> Path:
    path = Path(path)
    if (path.is_symlink() or path.parent.resolve() != action_directory().resolve()
            or not re.fullmatch(r'[0-9a-f]{32}\.request\.json', path.name)):
        raise ValueError('유효한 회차 작업 요청 파일이 필요합니다.')
    return path


def write_message(path: Path, payload: dict):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix='.message_', delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, allow_nan=False)
            file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def scope_status(scope: EpisodeScope, script: ShortsScript | None = None, *, child: bool = False) -> tuple[dict, dict]:
    manager = ScheduleManager(scope.schedules_file, queue_only=True)
    schedule = manager.get_schedule(scope.schedule_id)
    if (not schedule or schedule.get('review_operator') != 'agent' or schedule.get('enabled')
            or schedule.get('last_result') != 'script_review_pending'
            or schedule.get('last_episode_id') != scope.episode_id
            or schedule.get('last_video_path') or schedule.get('last_youtube_id')):
        raise ValueError('같은 회차의 미첨부 각본 검토 단계가 필요합니다. 연결된 영상은 유지합니다.')
    record = load_episode(scope.episode_id, schedule)
    pending = episode_path(scope.episode_id).with_suffix('.operation.pending.json')
    if not child and (pending.exists() or pending.is_symlink()):
        raise ValueError('이전 회차 실행 결과를 먼저 대조하세요. 다시 요청하지 않습니다.')
    if child and not pending.is_file():
        raise ValueError('회차 실행 잠금이 없습니다.')
    if script is not None and script_sha256(script.model_dump(mode='json')) != script_sha256(schedule['last_script']):
        raise ValueError('수정한 대본을 먼저 이 회차에 저장하세요.')
    return schedule, record


def validate_receipt(path: str | Path, request_sha256: str) -> dict:
    request = action_path(path)
    action = read_request(request, request_sha256)
    result = request.with_suffix('.result.json')
    if result.is_symlink() or result.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('회차 결과 파일을 확인하세요.')
    data = json.loads(result.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('request_sha256') != request_sha256
            or data.get('status') != 'returned' or data.get('kind') not in {'path', 'production', 'error'}):
        raise ValueError('회차 결과 영수증이 요청과 일치하지 않습니다.')
    if data['kind'] == 'production':
        TypeAdapter(ProductionResult).validate_json(json.dumps(data.get('value')), strict=True)
    elif not isinstance(data.get('error' if data['kind'] == 'error' else 'value'), str) or not data.get('error' if data['kind'] == 'error' else 'value'):
        raise ValueError('회차 결과 내용이 올바르지 않습니다.')
    if type(data.get('cancelled', False)) is not bool:
        raise ValueError('회차 중지 결과를 확인하세요.')
    if data['kind'] != 'error' and data['kind'] != ('path' if action.operation in {'frame', 'raw', 'narration'} else 'production'):
        raise ValueError('요청한 단계와 회차 결과가 다릅니다.')
    return data


def read_request(path: str | Path, digest: str) -> StudioAction:
    path = action_path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('회차 요청 크기를 확인하세요.')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('회차 요청 파일이 변경됐습니다.')
    return StudioAction.model_validate_json(content)


def worker_command(path: str | Path, digest: str) -> list[str]:
    return [sys.executable, '-m', 'shorts_maker.services.studio_episode_action', str(path), digest]


async def execute_action(request: StudioAction, path: Path, digest: str):
    schedule, record = scope_status(request.scope, child=True)
    pending = episode_path(record['id']).with_suffix('.operation.pending.json')
    audit = json.loads(pending.read_text())
    if audit.get('command_sha256') != hashlib.sha256(json.dumps(worker_command(path, digest)).encode()).hexdigest():
        raise ValueError('다른 회차 요청이 실행 중입니다. 기존 실행 결과를 먼저 대조하세요.')
    env, _ = episode_environment(record)
    if (os.getenv('SHORTSMAKER_EPISODE_ID') != record['id']
            or not 0 < settings.google_monthly_budget_krw <= int(env['GOOGLE_MONTHLY_BUDGET_KRW'])
            or not 0 < settings.openai_monthly_budget_usd <= float(env['OPENAI_MONTHLY_BUDGET_USD'])
            or settings.veo_model_id != env['VEO_MODEL_ID']
            or settings.veo_duration_seconds != int(env['VEO_DURATION_SECONDS'])
            or settings.hybrid_veo_duration_seconds != int(env['HYBRID_VEO_DURATION_SECONDS'])
            or settings.google_usd_krw_rate < float(env['GOOGLE_USD_KRW_RESERVE_RATE'])
            or not 0 <= settings.max_visual_cost_usd <= float(env['MAX_VISUAL_COST_USD'])
            or settings.image_model_id != request.image_model
            or schedule_sha256(schedule) != request.schedule_sha256):
        raise ValueError('회차 상한·모델·일정이 고정된 별도 실행 경로가 필요합니다.')
    require_paid_production_enabled()
    script = ShortsScript.model_validate(schedule['last_script'])
    if (script_sha256(script.model_dump(mode='json')) != request.script_sha256
            or script_draft_key(script) != request.review_receipt):
        raise ValueError('현재 대본과 검토 확인이 일치하지 않습니다.')
    if request.operation in {'frame', 'raw'} and (request.scene_index is None or request.scene_index >= len(script.scenes)):
        raise ValueError('현재 대본의 장면 번호를 선택하세요.')
    allowed_editor = {'tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume', 'subtitle_color', 'subtitle_size', 'subtitle_y_position'}
    if request.editor_options.keys() - allowed_editor or request.overlay_options.keys() - CharacterOverlayConfig().to_dict().keys():
        raise ValueError('지원하는 편집 설정만 사용할 수 있습니다.')
    service = ProductionService(mode=request.mode, max_veo_attempts=1, parallel_clips=False,
        editor_options=request.editor_options,
        character_overlay_config=CharacterOverlayConfig.from_dict(request.overlay_options))
    def progress(value):
        data = asdict(value);data['phase'] = value.phase.value
        write_message(path.with_suffix('.progress.json'), data)
    service.set_progress_callback(progress)
    async def cancellation():
        marker = path.with_suffix('.cancel')
        while True:
            if marker.is_file() and not marker.is_symlink() and marker.stat().st_size == 64:
                if marker.read_text() == digest:
                    service.cancel()
                return
            await asyncio.sleep(.1)
    watcher = asyncio.create_task(cancellation())
    try:
        if request.operation == 'frame':
            if request.request_budget_usd is None:
                raise ValueError('첫 프레임의 요청 상한이 필요합니다.')
            result = await service.generate_first_frame(script, request.scene_index, request_budget_usd=request.request_budget_usd)
        elif request.operation == 'raw':
            result = await service.generate_review_clip(script, request.scene_index,
                request_budget_usd=request.request_budget_usd, expected_frame_sha256=request.expected_frame_sha256,
                manual_clip_paths=request.manual_clip_paths)
        elif request.operation == 'narration':
            if request.narration_budget_usd is None:
                raise ValueError('내레이션의 요청 상한이 필요합니다.')
            result = await service.prepare_narration(script, request_budget_usd=request.narration_budget_usd)
        elif request.operation == 'edit':
            result = await service.produce_video(script, manual_clip_paths=request.manual_clip_paths,
                prepared_audio_paths=request.prepared_audio_paths, retain_narration=True, finish_phase=request.finish_phase)
        else:
            if not request.video_path or request.metadata is None:
                raise ValueError('검토한 완성본과 게시 정보가 필요합니다.')
            video = Path(request.video_path)
            report_path = video.with_suffix('.production.json')
            if (video.is_symlink() or video.suffix.lower() != '.mp4'
                    or not video.resolve().is_relative_to(settings.output_dir.resolve())
                    or report_path.is_symlink() or not report_path.resolve().is_relative_to(settings.output_dir.resolve())):
                raise ValueError('출력 폴더의 검토한 완성본이 필요합니다.')
            report = json.loads(report_path.read_text())
            if report.get('script_sha256') != request.script_sha256:
                raise ValueError('완성본이 현재 회차 대본과 다릅니다.')
            result = await service.upload_to_youtube(request.video_path, request.metadata)
        if isinstance(result, str):
            payload = {'kind': 'path', 'value': result}
        else:
            payload = {'kind': 'production', 'value': asdict(result)}
            payload['value']['script'] = result.script.model_dump(mode='json') if result.script else None
            payload['value']['script_context'] = None
        return {**payload, 'cancelled': service.is_cancelled()}
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def main(arguments):
    if len(arguments) != 2:
        raise ValueError('회차 요청 경로와 해시가 필요합니다.')
    path = action_path(arguments[0]);digest = arguments[1]
    try:
        request = read_request(path, digest)
        result = asyncio.run(execute_action(request, path, digest))
    except ValidationError:
        result = {'kind': 'error', 'error': '회차 요청 형식을 확인하세요.'}
    except Exception as error:
        result = {'kind': 'error', 'error': str(error)}
    write_message(path.with_suffix('.result.json'), {'request_sha256': digest, 'status': 'returned', **result})
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))
