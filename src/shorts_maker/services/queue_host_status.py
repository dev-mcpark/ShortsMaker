"""Local queue-clock evidence; never infer registration from an enabled schedule alone."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from shorts_maker.utils.scheduler import TRIGGER_FIELDS

MAX_BYTES = 1024 * 1024
MAX_AGE_SECONDS = 90  # Three missed updates of the existing 30-second clock loop.


def status_path(manager) -> Path:
    return manager.filename.with_name(f'{manager.filename.name}.host.json')


def write_host_status(manager, state='running'):
    if not manager.queue_only:
        raise ValueError('대기 전용 호스트의 상태만 기록할 수 있습니다.')
    if state not in {'running', 'stopped', 'error'} or (state == 'running' and not manager._scheduler_running):
        raise ValueError('실행 중인 시계만 정상 상태를 기록할 수 있습니다.')
    path = status_path(manager)
    if path.is_symlink():
        raise ValueError('호스트 상태 파일의 링크를 확인하세요.')
    jobs = []
    if state == 'running' and manager._scheduler_running:
        for job in manager._scheduler.get_jobs():
            jobs.append({'id': job.id, 'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                         'registration': {key: job.args[0].get(key) for key in TRIGGER_FIELDS}})
    content = json.dumps({'schema_version': 1, 'pid': os.getpid(), 'state': state,
                          'updated_at': datetime.now(timezone.utc).isoformat(),
                          'schedules_file': str(manager.filename.resolve()), 'jobs': jobs}).encode()
    if len(content) > MAX_BYTES:
        raise ValueError('호스트 상태가 너무 큽니다.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix=f'.{path.name}.', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def read_host_status(manager) -> dict:
    try:
        path = status_path(manager)
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or linked status')
        with path.open('rb') as file:
            content = file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('oversized status')
        value = json.loads(content)
        if (value['schema_version'] != 1 or type(value['pid']) is not int or value['pid'] <= 0
                or value['schedules_file'] != str(manager.filename.resolve())
                or value['state'] not in {'running', 'stopped', 'error'}
                or not isinstance(value['jobs'], list)):
            raise ValueError('invalid status')
        updated = datetime.fromisoformat(value['updated_at'])
        if updated.tzinfo is None:
            raise ValueError('missing timezone')
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age < -5 or age > MAX_AGE_SECONDS:
            return {'state': 'stale'}
        if value['state'] != 'running':
            return {'state': value['state']}
        # shortcut: POSIX liveness only; add a non-signalling check before supporting Windows hosts.
        if sys.platform == 'win32':
            return {'state': 'unavailable'}
        os.kill(value['pid'], 0)
        desired = {s['id']: {key: s.get(key) for key in TRIGGER_FIELDS}
                   for s in manager.load_schedules() if s.get('enabled', True) and s.get('review_operator') == 'agent'}
        registered = {}
        for job in value['jobs']:
            when = datetime.fromisoformat(job['next_run'])
            if (not isinstance(job['id'], str) or job['id'] in registered or when.tzinfo is None
                    or not isinstance(job['registration'], dict) or when < updated):
                raise ValueError('invalid registration')
            registered[job['id']] = job['registration']
        if desired != registered:
            return {'state': 'out_of_sync'}
        return {'state': 'healthy', 'pid': value['pid'], 'updated_at': value['updated_at'],
                'jobs': [{'id': job['id'], 'next_run': job['next_run']} for job in value['jobs']]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return {'state': 'unavailable'}
