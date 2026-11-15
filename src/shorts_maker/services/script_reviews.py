"""Read retained validator evidence for an exact applied script; never run or approve it."""

import hashlib
import json

from shorts_maker.planner.script_validator import ValidationResult
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
    return value


def read_script_reviews(script) -> dict:
    root = settings.scripts_dir / 'reviews'
    if root.is_symlink() or settings.scripts_dir.is_symlink():
        raise ValueError('검토 보관 폴더의 링크를 확인하세요.')
    try:
        paths = sorted(root.iterdir())
    except FileNotFoundError:
        return {'records': [], 'unreadable': []}
    expected = hashlib.sha256(json.dumps(script.model_dump(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    records, unreadable = [], []
    for path in paths:
        if not path.name.endswith('.request.json'):
            continue
        try:
            request = _read(path)
            recorded = hashlib.sha256(json.dumps(request['script'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            source = request['source_excerpt']
            if (not isinstance(request['script'], dict) or recorded != request['script_json_sha256']
                    or not isinstance(source, str) or not source.strip() or len(source) > 5000
                    or hashlib.sha256(source.encode()).hexdigest() != request['source_sha256']
                    or not isinstance(request['validator_model'], str) or not request['validator_model'].strip()):
                raise ValueError('invalid review binding')
            if recorded != expected:
                continue
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            unreadable.append(path.name)
            continue
        record = {'name': path.name, 'model': request['validator_model'], 'source_excerpt': source,
                  'state': 'missing', 'verdict': None}
        verdict_path = path.with_name(path.name.removesuffix('.request.json') + '.verdict.json')
        try:
            verdict = ValidationResult.model_validate(_read(verdict_path), strict=True)
            record['verdict'] = verdict.model_dump()
            record['state'] = 'error' if verdict.reason == 'validation_error' else 'completed'
        except FileNotFoundError:
            pass  # A retained request alone never proves a completed validation.
        except (OSError, ValueError, TypeError, RecursionError):
            record['state'] = 'unreadable'
        records.append(record)
    return {'records': records, 'unreadable': unreadable}
