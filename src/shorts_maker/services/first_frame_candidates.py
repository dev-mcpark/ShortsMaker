"""Retain one unapproved image request per exact script/scene, including uncertain attempts."""

import asyncio
import hashlib
import json
import math
import os
import shutil
import uuid

from shorts_maker.services.google_budget import check_google_budget
from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.services.visual_review import inspect_frame, review_path
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled
from shorts_maker.utils.source_manager import SourceManager


def candidate_record_path(script, scene):
    return review_path(script, scene).with_suffix('.candidate.json')


def retained_candidate(script, scene) -> str | None:
    path = candidate_record_path(script, scene)
    if not path.exists():
        if path.with_suffix('.png').exists():
            raise ValueError('FIRST_FRAME_REQUEST_UNVERIFIED: 기록 없는 첫 프레임 파일이 있습니다.')
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        frame = path.with_suffix('.png')
        if (not isinstance(record, dict) or path.is_symlink() or frame.is_symlink() or record.get('schema_version') != 1
                or record['status'] != 'saved' or record['scene_number'] != scene.scene_number
                or record['script_sha256'] != hashlib.sha256(script.model_dump_json().encode()).hexdigest()
                or record['frame_sha256'] != inspect_frame(str(frame))):
            raise ValueError('incomplete or changed candidate')
        return str(frame)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('FIRST_FRAME_REQUEST_UNVERIFIED: 이전 이미지 요청·파일을 확인하세요. 자동 재요청하지 않습니다.') from error


async def generate_candidate(service, script, scene_index, request_budget_usd):
    scene = script.scenes[scene_index]
    cached = retained_candidate(script, scene)
    if cached:
        return cached
    if any(not SourceManager.is_allowed_url(url) for url in [script.source_url, *script.supporting_source_urls]):
        raise ValueError('공개 출처 URL이 있는 대본이 필요합니다.')
    estimate = estimated_scene_cost('image', settings.image_model_id)
    if (not isinstance(request_budget_usd, (int, float)) or isinstance(request_budget_usd, bool)
            or not math.isfinite(request_budget_usd) or estimate > request_budget_usd
            or estimate > settings.max_visual_cost_usd):
        raise ValueError('VISUAL_REQUEST_CAP_EXCEEDED: 첫 프레임 요청의 비용 상한을 확인하세요.')
    require_paid_production_enabled()
    check_google_budget(estimate)
    if service.is_cancelled():
        raise ValueError('사용자에 의해 취소됨')
    generator = service._get_generator()
    path = candidate_record_path(script, scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'schema_version': 1, 'status': 'pending', 'scene_number': scene.scene_number,
              'script_sha256': hashlib.sha256(script.model_dump_json().encode()).hexdigest(),
              'source_url': script.source_url, 'model': settings.image_model_id,
              'estimated_output_usd': estimate, 'frame_path': str(path.with_suffix('.png'))}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    # Keep pending even on cancellation/failure: a submitted request is never an automatic retry.
    generated = await generator.generate_scene_clip(scene, mode_override='image', source_url=script.source_url)
    frame = path.with_suffix('.png')
    await asyncio.to_thread(shutil.copyfile, generated, frame)
    record.update(status='saved', frame_sha256=inspect_frame(str(frame)))
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return str(frame)
