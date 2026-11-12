"""Read-only Studio startup identity; never infer loaded code from a later Git HEAD."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess

from nicegui import run, ui


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_startup = None


def code_digest(root=PACKAGE_ROOT):
    digest = hashlib.sha256()
    files = sorted(root.rglob('*.py'))
    if not files:
        raise ValueError('코드 파일이 없습니다.')
    for path in files:
        if path.is_symlink():
            raise ValueError('코드 링크는 실행 지문으로 확인할 수 없습니다.')
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def initialize_runtime():
    global _startup
    if _startup is not None:
        return
    commit, dirty, digest = None, None, None
    try:
        result = subprocess.run(['git', '-C', str(PACKAGE_ROOT), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, check=True, timeout=2)
        value = result.stdout.strip()
        if len(value) == 40 and all(c in '0123456789abcdef' for c in value):
            commit = value
        result = subprocess.run(['git', '-C', str(PACKAGE_ROOT), 'status', '--porcelain', '--untracked-files=normal', '--', '.'],
                                capture_output=True, text=True, check=True, timeout=2)
        dirty = bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        digest = code_digest()
    except (OSError, ValueError):
        pass
    _startup = {'pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
                'commit': commit, 'dirty': dirty, 'code_sha256': digest}


def runtime_label():
    commit = _startup.get('commit') if _startup else None
    return f'시작 커밋 · {commit[:7]}' if commit else '시작 커밋 · 확인 불가'


def render_runtime_info():
    with ui.expansion('실행 정보 · 배포 확인', icon='info').classes('w-full max-w-3xl').props('dark') as view:
        if _startup is None:
            ui.label('이 실행은 시작 정보를 기록하지 않았습니다. 현재 Git 버전을 실행 버전으로 판단하지 마세요.').classes('text-xs text-amber-200')
            return
        for label, value in [('Studio 프로세스', _startup['pid']), ('앱 시작 기록 (UTC)', _startup['started_at']),
                             ('시작 기준 커밋', _startup['commit'] or '확인 불가'),
                             ('시작 시 패키지 수정', {True: '수정 포함', False: '없음', None: '확인 불가'}[_startup['dirty']]),
                             ('시작 Python 코드 지문', _startup['code_sha256'] or '확인 불가')]:
            ui.label(f'{label} · {value}').classes('text-xs text-slate-300 break-all')
        ui.label('시작 시점 기록이며 전체 모듈·설정·의존성·영상 품질의 검증은 아닙니다. 저장소 코드가 바뀌어도 실행 정보는 바뀌지 않습니다.').classes('text-xs text-slate-400')
        result = ui.label('아래 버튼은 패키지의 Python 코드만 읽어 비교합니다.').classes('text-xs text-amber-200 break-all')
        loading = {'value': False}

        async def compare():
            if view.is_deleted or loading['value']:
                return
            loading['value'] = True
            try:
                current = await run.io_bound(code_digest)
                if not _startup['code_sha256']:
                    message = '시작 지문을 확인할 수 없어 비교하지 못했습니다.'
                elif current == _startup['code_sha256']:
                    message = '현재 저장 코드와 시작 지문이 같습니다.'
                else:
                    message = '현재 저장 코드가 시작 지문과 다릅니다. 재시작 전 초안을 저장하고 진행 중 작업을 확인하세요.'
            except (OSError, ValueError, RuntimeError):
                message = '현재 코드 읽기에 실패했습니다. 실행 코드가 최신이라고 판단하지 마세요.'
            finally:
                loading['value'] = False
            if not view.is_deleted:
                result.text = message

        ui.button('현재 저장 코드와 비교', on_click=compare).props('outline').classes('min-h-[44px]').bind_enabled_from(
            loading, 'value', lambda value: not value)
    return compare
