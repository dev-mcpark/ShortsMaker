"""Read-only queue-clock status, separate from Studio's direct production scheduler."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.services.budget_calendar import budget_month_starts
from shorts_maker.services.queue_host_status import read_host_status


SEOUL = ZoneInfo('Asia/Seoul')


def render_queue_host_panel(manager):
    snapshot = {'state': 'unavailable'}
    loading = {'value': False}
    with ui.card().classes('w-full bg-slate-800 border border-slate-600') as root:
        ui.label('예약 대기 호스트').classes('text-lg font-bold')
        ui.label('앱 창과 별도로 실행됩니다. 예약일에 제작 대기만 만들며 유료 호출은 하지 않습니다.').classes(
            'text-xs text-slate-300')

        @ui.refreshable
        def result():
            state = snapshot['state']
            if state == 'healthy':
                ui.label(f'최근 응답 확인 · 등록 {len(snapshot["jobs"])}건 · PID {snapshot["pid"]}').classes(
                    'text-sm text-teal-300')
                when = datetime.fromisoformat(snapshot['updated_at']).astimezone(SEOUL)
                ui.label(f'호스트 응답 {when:%m-%d %H:%M:%S} KST').classes('text-xs text-slate-400')
                now = datetime.now(timezone.utc)
                for job in snapshot['jobs']:
                    next_run = datetime.fromisoformat(job['next_run']).astimezone(SEOUL)
                    ui.label(f'다음 대기 생성: {next_run:%Y-%m-%d %H:%M} KST').classes('text-sm text-teal-200')
                    starts = budget_month_starts(next_run)
                    period_summary = ' · '.join(f'{provider} {start:%Y-%m}' for provider, start in starts.items())
                    ui.label(f'예약 시각 기준 장부 월 · {period_summary}').classes('text-xs text-slate-300')
                    rollover = sorted((start.astimezone(SEOUL), provider)
                                      for provider, start in starts.items() if start > now)
                    if rollover:
                        ui.label('새 월이 시작된 뒤 실제 사용액과 월 장부 기준을 대조하세요.').classes(
                            'text-xs text-amber-200')
                        for start, provider in rollover:
                            ui.label(f'{provider} 새 장부 월 시작 · {start:%Y-%m-%d %H:%M} KST').classes(
                                'text-xs text-slate-300')
                if not snapshot['jobs']:
                    ui.label('등록된 에이전트 일정이 없습니다. 검토 대기·일시정지 상태를 확인하세요.').classes('text-xs')
            else:
                messages = {
                    'unavailable': '호스트 확인 필요 · 응답 파일이나 실행 프로세스를 확인할 수 없습니다.',
                    'stale': '호스트 응답 지연 · 최근 90초 안의 정상 응답을 확인할 수 없습니다.',
                    'out_of_sync': '일정 변경 반영 대기 · 호스트의 실제 등록과 저장 일정이 다릅니다.',
                    'stopped': '예약 대기 호스트가 중지됐습니다.',
                    'error': '예약 대기 호스트가 오류로 종료됐습니다.',
                }
                ui.label(messages.get(state, messages['unavailable'])).classes('text-sm text-amber-300')
                ui.label('최대 30초 후 다시 확인하세요. 계속 다르면 별도 호스트를 점검하세요.' if state == 'out_of_sync' else
                         '별도 호스트 설치·실행을 확인하세요. Studio 직접 스케줄러 시작은 이 호스트를 복구하지 않습니다.').classes(
                    'text-xs text-slate-300')

        async def refresh():
            if loading['value'] or root.is_deleted:
                return
            loading['value'] = True
            try:
                try:
                    value = await run.io_bound(read_host_status, manager)
                except (OSError, ValueError, RuntimeError):
                    value = {'state': 'unavailable'}
                if not root.is_deleted:
                    snapshot.clear()
                    snapshot.update(value)
                    safe_refresh(result)
            finally:
                loading['value'] = False

        result()
        ui.button('호스트 상태 새로고침', on_click=refresh).props('flat icon=refresh').classes(
            'min-h-[44px]').bind_enabled_from(loading, 'value', lambda value: not value)
        ui.label('30초마다 로컬 상태를 읽습니다. 최근 응답은 향후 실행·인증·제작 성공을 보장하지 않습니다.').classes(
            'text-xs text-slate-400')
        ui.timer(0.1, refresh, once=True)
        async def poll():
            if root.is_deleted:
                timer.deactivate()
                return
            await refresh()
        timer = ui.timer(30, poll)
    return refresh
