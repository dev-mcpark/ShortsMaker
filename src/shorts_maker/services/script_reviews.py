"""Read retained validator evidence for an exact applied script; never run or approve it."""

import hashlib
import json

from shorts_maker.planner.script_validator import ValidationResult
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings

MAX_BYTES = 2 * 1024 * 1024


def _read(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('invalid review path')
    with path.open('rb') as file:
        content = file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('oversized review')
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError('invalid review')
    return value, hashlib.sha256(content).hexdigest()


def _root():
    root = settings.scripts_dir / 'reviews'
    if root.is_symlink() or settings.scripts_dir.is_symlink():
        raise ValueError('검토 보관 폴더의 링크를 확인하세요.')
    return root


def _request(path):
    request, digest = _read(path)
    recorded = hashlib.sha256(json.dumps(request['script'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    source = request['source_excerpt']
    if (not isinstance(request['script'], dict) or recorded != request['script_json_sha256']
            or not isinstance(source, str) or not source.strip() or len(source) > 5000
            or hashlib.sha256(source.encode()).hexdigest() != request['source_sha256']
            or not isinstance(request['validator_model'], str) or not request['validator_model'].strip()):
        raise ValueError('invalid review binding')
    ShortsScript.model_validate(request['script'])
    return request, digest


def _review_path(name: str):
    if not isinstance(name, str) or '/' in name or '\\' in name or not name.endswith('.request.json'):
        raise ValueError('보관된 검토 대본을 목록에서 선택하세요.')
    return _root() / name


def read_review_script(name: str, expected_sha256: str) -> ShortsScript:
    try:
        request, digest = _request(_review_path(name))
        if digest != expected_sha256:
            raise ValueError('목록 조회 후 검토 기록이 바뀌었습니다.')
        return ShortsScript.model_validate(request['script'])
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as error:
        raise ValueError('검토 대본의 파일·해시를 확인한 뒤 목록을 다시 조회하세요.') from error


def _review_record(path, request, digest):
    record = {'name': path.name, 'request_sha256': digest, 'script': request['script'],
              'model': request['validator_model'], 'source_excerpt': request['source_excerpt'],
              'state': 'missing', 'verdict': None}
    verdict_path = path.with_name(path.name.removesuffix('.request.json') + '.verdict.json')
    try:
        verdict = ValidationResult.model_validate(_read(verdict_path)[0], strict=True)
        record['verdict'] = verdict.model_dump()
        record['state'] = 'error' if verdict.reason == 'validation_error' else 'completed'
    except FileNotFoundError:
        pass  # A retained request alone never proves a completed validation.
    except (OSError, ValueError, TypeError, RecursionError):
        record['state'] = 'unreadable'
    return record


def read_exact_review(name: str, expected_sha256: str) -> dict:
    path = _review_path(name)
    request, digest = _request(path)
    if digest != expected_sha256:
        raise ValueError('저장된 모델 검토 요청이 변경됐습니다.')
    return _review_record(path, request, digest)


def read_script_reviews(script=None) -> dict:
    """None lists retained drafts; a script limits results to its exact applied contents."""
    root = _root()
    try:
        paths = sorted(root.iterdir())
    except FileNotFoundError:
        return {'records': [], 'unreadable': []}
    expected = hashlib.sha256(json.dumps(script.model_dump(), ensure_ascii=False, sort_keys=True).encode()).hexdigest() if script else None
    records, unreadable = [], []
    for path in paths:
        if not path.name.endswith('.request.json'):
            continue
        try:
            request, digest = _request(path)
            if expected and request['script_json_sha256'] != expected:
                continue
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            unreadable.append(path.name)
            continue
        records.append(_review_record(path, request, digest))
    return {'records': records, 'unreadable': unreadable}
