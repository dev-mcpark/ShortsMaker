"""Read retained script versions; their hashes grant no review or spending authority."""

from shorts_maker.planner.models import ShortsScript
from shorts_maker.services.production_service import script_sha256


def validated_revisions(current: dict, history: list) -> list[dict]:
    if not isinstance(current, dict) or not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
        raise ValueError('기존 각본 수정 이력을 확인하세요. 덮어쓰지 않습니다.')
    previous = script_sha256(current)
    for row in reversed(history):
        if (not isinstance(row.get('script'), dict) or row.get('replacement_sha256') != previous
                or row.get('script_sha256') != script_sha256(row['script'])):
            raise ValueError('각본 수정 이력의 해시가 일치하지 않습니다. 원래 기록은 유지됩니다.')
        previous = row['script_sha256']
    return history


def script_versions(run: dict) -> list[dict]:
    current = run.get('last_script')
    history = run.get('script_revisions', [])
    if current is None and history == []:
        return []
    history = validated_revisions(current, history)
    versions = [{'label': '이 회차의 마지막 저장본', 'script': current}, *[
        {'label': f'수정 전 대본 {index + 1} · {row.get("replaced_at") or "변경 시각 기록 없음"}', 'script': row['script']}
        for index, row in reversed(list(enumerate(history)))]]
    for version in versions:
        try:
            version['script'] = ShortsScript.model_validate(version['script'])
        except ValueError as error:
            raise ValueError('보관된 전체 대본 형식을 확인하세요. 일부 기록을 추측해 복구하지 않습니다.') from error
    return versions
