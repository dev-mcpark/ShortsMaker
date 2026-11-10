"""Inspect a scheduled review and attach an existing verified private upload from Studio."""

import json
from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.services.operating_budget import load_episode
from shorts_maker.services.operating_status import operator_status


def render_operator_panel(state, manager, schedule, on_attached):
    keys = ('id', 'review_operator', 'run_count', 'last_episode_id', 'last_result', 'enabled', 'last_script',
            'last_video_path', 'last_youtube_id')
    def identity(current):
        return json.dumps({key: current.get(key) for key in keys}, sort_keys=True, ensure_ascii=False)
    expected = identity(schedule)
    readout, loading = {}, {'value': False}

    @ui.refreshable
    def details():
        if not readout:
            ui.label('펼치거나 새로고침하면 현재 회차 기록을 조회합니다.').classes('text-xs text-slate-400')
            return
        if 'error' in readout:
            ui.label(readout['error']).classes('text-xs text-amber-200 break-all')
            return
        data = readout['data']
        phase = {'operator_pending': '제작 인계 대기',
                 'script_review_pending': '완성본 검토 대기' if data.get('last_youtube_id') else '각본·장면 검토 대기',
                 'run_in_progress': '실행 중 또는 결과 확인 필요', 'planning_failed': '기획 중단',
                 'private_review_accepted': '완성본 채택 완료', 'script_rejected': '각본 제외'}.get(
                     data['last_result'], '운영 상태 확인 필요' if data['last_result'] else '아직 실행 전')
        ui.label(f'회차 {data["run_count"] or 0} · {phase}').classes('text-sm text-slate-200')
        ui.label(f'마지막 조회 {readout["checked_at"]}').classes('text-xs text-slate-400')
        if schedule.get('review_operator') != 'agent':
            ui.label('Studio 직접 실행 일정입니다. 월 장부·비주얼 상한을 사용하며 에이전트 회차 한도를 새로 만들지 않습니다.').classes('text-xs text-slate-400')
        elif not data.get('last_episode_id'):
            ui.label('아직 회차 장부가 없습니다. 실제 예약 대기 항목에서만 회차를 시작합니다.').classes('text-xs text-slate-400')
        if data.get('operation_pending_unverified'):
            ui.label('실행 결과 대조 필요 · 요청 기록을 확인하기 전 재실행·연결을 중단합니다.').classes('text-xs text-amber-200')
        if 'budget_error' in data:
            ui.label(f'회차 비용 확인 필요: {data["budget_error"]}').classes('text-xs text-amber-200 break-all')
        if budget := data.get('budget'):
            ui.label(f'Google 회차 누적 예약 ₩{budget["google_new_reserved_krw"]:,} · 전체 상한까지 여유 ₩{budget["google_remaining_krw"]:,}').classes('text-xs text-teal-200')
            ui.label(f'OpenAI 회차 누적 예약 ${budget["openai_new_reserved_usd"]:.6f} · 전체 상한까지 여유 ${budget["openai_remaining_usd"]:.6f}').classes('text-xs text-teal-200')
        ui.label('전체 회차 여유는 새 지출 허가가 아닙니다. 월 잔액과 별도 비교·검증 범위 중 더 작은 한도 및 소진된 호출 횟수를 함께 적용합니다.').classes('text-xs text-slate-400')
        ui.label('이 화면은 회차를 앞당기거나 기획·제작을 실행하지 않습니다.').classes('text-xs text-slate-400')

    async def refresh():
        if loading['value']:
            return
        loading['value'] = True
        try:
            def read():
                current = manager.get_schedule(schedule['id'])
                if not current:
                    raise ValueError('일정이 없습니다. 목록을 새로고침하세요.')
                return operator_status(current)
            data = await run.io_bound(read)
            readout.clear()
            readout['data'] = data
            readout['checked_at'] = datetime.now().astimezone().strftime('%m-%d %H:%M:%S %Z')
        except (ValueError, OSError, RuntimeError) as error:
            readout.clear()
            readout['error'] = str(error)
        finally:
            loading['value'] = False
            safe_refresh(details)

    async def opened(event):
        if event.value:
            await refresh()

    def attach_preview():
        def current():
            current_schedule = manager.get_schedule(schedule['id'])
            if (state.is_busy or not current_schedule or identity(current_schedule) != expected
                    or current_schedule.get('enabled') or current_schedule.get('last_result') != 'script_review_pending'
                    or current_schedule.get('last_youtube_id')):
                raise ValueError('작업 중이거나 회차 상태가 바뀌었습니다. 현재 회차를 다시 확인하세요.')
            if current_schedule.get('review_operator') == 'agent':
                load_episode(current_schedule.get('last_episode_id'), current_schedule)

        try:
            current()
            selected = state.final_video_path
            info = manager.pending_video_info(schedule['id'], selected)
        except (ValueError, RuntimeError, OSError) as error:
            safe_notify(f'완성본을 연결할 수 없습니다: {error}', type='warning')
            return
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
            ui.label(f'{schedule["name"]} · 비공개 완성본 연결').classes('text-lg font-bold')
            ui.label(Path(info['video_path']).name).classes('text-sm break-all')
            ui.link(f'YouTube {info["youtube_id"]}', f'https://www.youtube.com/shorts/{info["youtube_id"]}', new_tab=True)
            ui.label('파일·대본·출처·비공개 업로드 기록을 대조했습니다. 연결 후에도 검토 대기이며, 채택과 공개는 별도로 결정합니다.').classes('text-sm text-slate-300')

            def confirm():
                if dialog.is_deleted or not dialog.value:
                    return
                try:
                    current()
                    if (state.final_video_path != selected
                            or manager.pending_video_info(schedule['id'], selected) != info):
                        raise ValueError('선택한 영상 또는 업로드 기록이 바뀌었습니다. 다시 확인하세요.')
                    manager.record_private_review_copy(schedule['id'], selected)
                    dialog.close()
                    on_attached()
                    safe_notify('비공개 완성본을 회차에 연결했습니다. 채택·일정 재개는 아직 하지 않았습니다.', type='positive')
                except (ValueError, RuntimeError, OSError) as error:
                    safe_notify(f'연결을 중단했습니다: {error}', type='warning')

            with ui.row().classes('w-full flex-wrap'):
                ui.button('취소', on_click=dialog.close).props('flat')
                ui.button('이 비공개 완성본 연결', on_click=confirm).props('color=teal').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
        dialog.open()

    with ui.expansion('현재 회차 상태·연결', on_value_change=opened).classes('w-full'):
        details()
        ui.button('회차 상태 새로고침', on_click=refresh).props('flat icon=refresh').bind_enabled_from(loading, 'value', lambda value: not value)
        if schedule.get('last_result') == 'script_review_pending' and not schedule.get('last_youtube_id') and not schedule.get('enabled'):
            ui.label('완성본·업로드에서 확인된 비공개 영상을 불러온 뒤 연결하세요. 이 버튼은 업로드하거나 새 영상을 만들지 않습니다.').classes('text-xs text-slate-300')
            ui.button('선택 완성본을 이 회차에 연결', on_click=attach_preview).props('outline color=teal').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy and bool(state.final_video_path))
        elif schedule.get('last_youtube_id'):
            ui.label('이미 연결된 검토본을 유지합니다. 다른 영상으로의 교체는 별도 검토가 필요합니다.').classes('text-xs text-slate-400')
    return refresh
