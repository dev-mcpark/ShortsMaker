"""Run the reviewed operator handoff; ordinary status/serve commands make no provider calls."""

import argparse
import asyncio
import hashlib
import json
import os
import plistlib
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from shorts_maker.services.operating_budget import begin_episode, episode_environment, episode_path, load_episode
from shorts_maker.services.operating_status import operator_status
from shorts_maker.utils.config import PROJECT_ROOT, settings
from shorts_maker.utils.scheduler import ScheduleManager


def active_episode(manager, schedule_id):
    schedule = manager.get_schedule(schedule_id)
    if (not schedule or schedule.get('review_operator') != 'agent' or schedule.get('enabled')
            or schedule.get('last_result') not in {'operator_pending', 'script_review_pending'}):
        raise ValueError('에이전트 제작 대기 또는 각본 검토 중인 일정이 필요합니다.')
    return schedule, load_episode(schedule.get('last_episode_id'), schedule)


def run_scoped(manager, schedule_id, command):
    schedule, record = active_episode(manager, schedule_id)
    if schedule.get('last_youtube_id'):
        raise ValueError('비공개 완성본이 연결된 회차는 제작을 다시 실행할 수 없습니다. 완성본을 검토하세요.')
    env, status = episode_environment(record)
    path = episode_path(record['id']).with_suffix('.operation.pending.json')
    audit = {'command_sha256': hashlib.sha256(json.dumps(command).encode()).hexdigest(), 'status': status}
    with path.open('x') as file:
        json.dump(audit, file)
        file.flush()
        os.fsync(file.fileno())
    # A killed parent retains the marker. Inspect its child and provider records before recovery.
    result = subprocess.run(command, cwd=PROJECT_ROOT, env={**os.environ, **env})
    audit['returncode'] = result.returncode
    with path.open('w') as file:
        json.dump(audit, file)
        file.flush()
        os.fsync(file.fileno())
    path.replace(path.with_name(f'{record["id"]}.operation.{uuid.uuid4().hex}.json'))
    return result.returncode


async def serve(manager):
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    manager.start_scheduler()
    await manager.queue_overdue()
    print(json.dumps({'state': 'queue_only_host_running', 'pid': os.getpid(),
                      'schedules': manager.get_next_run_times()}), flush=True)
    try:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=30)
            except asyncio.TimeoutError:
                manager.sync_jobs()
                await manager.queue_overdue()
    finally:
        manager.stop_scheduler()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schedules', default='schedules.json')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('serve')
    sub.add_parser('install-host')
    for action in ('plan', '_plan', 'run', 'attach'):
        command = sub.add_parser(action)
        command.add_argument('schedule_id')
        if action == 'run':
            command.add_argument('command', nargs=argparse.REMAINDER)
        elif action == 'attach':
            command.add_argument('video_path')
    args = parser.parse_args()
    manager = ScheduleManager(args.schedules, queue_only=True)
    if args.action == 'install-host':
        if sys.platform != 'darwin':
            raise ValueError('이 호스트 설치 명령은 macOS 사용자 LaunchAgent용입니다.')
        label = 'com.shortsmaker.scheduler'
        path = Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist'
        definition = {
            'Label': label,
            'ProgramArguments': [str(PROJECT_ROOT / '.venv/bin/python'), str(Path(__file__).resolve()),
                                 '--schedules', str(manager.filename.resolve()), 'serve'],
            'WorkingDirectory': str(PROJECT_ROOT), 'RunAtLoad': True,
            'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 30,
            'EnvironmentVariables': {'PAID_PRODUCTION_ENABLED': 'false', 'PYTHONUNBUFFERED': '1'},
            'StandardOutPath': str(settings.logs_dir / 'scheduler_host.out.log'),
            'StandardErrorPath': str(settings.logs_dir / 'scheduler_host.err.log'),
        }
        if path.exists() and plistlib.loads(path.read_bytes()) != definition:
            raise ValueError('다른 호스트 설정이 이미 있습니다. 기존 설정부터 검토하세요.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open('xb') as file:
                plistlib.dump(definition, file)
        existing = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{label}'], capture_output=True)
        if existing.returncode == 0:
            print('Queue-only host already loaded:', path)
            return
        subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
        print('Installed queue-only host:', path)
    elif args.action == 'serve':
        asyncio.run(serve(manager))
    elif args.action == 'status':
        for schedule in manager.load_schedules():
            if schedule.get('review_operator') == 'agent':
                print(json.dumps(operator_status(schedule), ensure_ascii=False))
    elif args.action == 'plan':
        schedule = manager.get_schedule(args.schedule_id)
        if (not schedule or schedule.get('review_operator') != 'agent' or schedule.get('enabled')
                or schedule.get('last_result') != 'operator_pending'):
            raise ValueError('실제 일정이 남긴 제작 대기 항목이 필요합니다.')
        if not schedule.get('last_episode_id'):
            episode = begin_episode(schedule['id'], schedule['run_count'])
            manager.update_schedule(schedule['id'], {'last_episode_id': episode['id']})
        raise SystemExit(run_scoped(manager, args.schedule_id, [
            sys.executable, str(Path(__file__).resolve()), '--schedules', str(manager.filename.resolve()),
            '_plan', args.schedule_id,
        ]))
    elif args.action == '_plan':
        schedule, record = active_episode(manager, args.schedule_id)
        expected, _ = episode_environment(record)
        if (settings.google_monthly_budget_krw > int(expected['GOOGLE_MONTHLY_BUDGET_KRW'])
                or settings.openai_monthly_budget_usd > float(expected['OPENAI_MONTHLY_BUDGET_USD'])
                or settings.veo_model_id != expected['VEO_MODEL_ID']):
            raise ValueError('회차 상한이 적용된 별도 프로세스로 기획해야 합니다.')
        asyncio.run(manager._execute_pipeline(schedule, operator=True))
        current = manager.get_schedule(args.schedule_id)
        if current['last_result'] != 'script_review_pending':
            raise RuntimeError('각본 제작 중단: ' + current['last_result'])
        script_path = episode_path(record['id']).with_suffix('.script.json')
        with script_path.open('x', encoding='utf-8') as file:
            json.dump(current['last_script'], file, ensure_ascii=False, indent=2)
        print('Script awaiting editorial review:', script_path)
    elif args.action == 'run':
        schedule, _ = active_episode(manager, args.schedule_id)
        if schedule['last_result'] != 'script_review_pending':
            raise ValueError('회차의 기획을 완료하고 각본부터 검토하세요.')
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command or Path(command[0]).resolve() != Path(sys.executable).resolve():
            raise ValueError('프로젝트 Python으로 기존 제작 경로를 실행하세요.')
        raise SystemExit(run_scoped(manager, args.schedule_id, command))
    elif args.action == 'attach':
        active_episode(manager, args.schedule_id)
        result = manager.record_private_review_copy(args.schedule_id, args.video_path)
        print(json.dumps({'state': 'owner_acceptance_pending',
                          'youtube_id': result['last_youtube_id']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
