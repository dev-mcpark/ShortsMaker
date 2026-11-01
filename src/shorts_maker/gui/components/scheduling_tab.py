"""Schedule Management 탭 컴포넌트"""

from pathlib import Path
import re
from typing import TYPE_CHECKING

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.scheduler import ScheduleManager
from shorts_maker.utils.config import settings
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

# 전역 스케줄 매니저
schedule_manager = ScheduleManager()


def _reviewable_video_path(path: object) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    try:
        candidate = Path(path).resolve()
        if (candidate.suffix.lower() == '.mp4' and candidate.is_file()
                and candidate.is_relative_to(settings.output_dir.resolve())):
            return str(candidate)
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _reviewable_youtube_url(video_id: object) -> str | None:
    if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{6,64}', video_id):
        return f'https://www.youtube.com/shorts/{video_id}'
    return None


def _schedule_readiness_messages() -> list[str]:
    from shorts_maker.services.google_budget import budget_status as google_budget_status
    from shorts_maker.services.openai_budget import budget_status as openai_budget_status

    messages = []
    if not settings.paid_production_enabled:
        messages.append('유료 제작 스위치 꺼짐')
    for status, remaining, label in (
        (google_budget_status, 'remaining_krw', 'Google 월 장부 확인 필요'),
        (openai_budget_status, 'remaining_usd', 'OpenAI 월 장부 확인 필요'),
    ):
        try:
            snapshot = status()
            if snapshot.get('enabled') and snapshot.get(remaining, 0) > 0:
                continue
        except (RuntimeError, ValueError, OSError):
            pass
        messages.append(label)
    return messages


def render_scheduling_tab(state: 'AppState') -> None:
    """Schedule Management 탭 렌더링"""

    with ui.row().classes('w-full h-auto lg:h-full gap-6 flex flex-col lg:flex-row flex-nowrap'):
        # === Left Panel: Create & Control ===
        with ui.column().classes('w-full lg:w-96 gap-4'):

            # === Scheduler Status Card ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                status_header = ui.element('div').classes('w-full p-4 bg-gradient-to-r from-red-600 to-orange-600')

                with status_header:
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-3'):
                            status_icon = ui.icon('pause_circle', size='md').classes('text-white')
                            with ui.column().classes('gap-0'):
                                ui.label('Studio Scheduler').classes('text-sm text-white/70')
                                status_label = ui.label('Stopped').classes('text-lg font-bold text-white')

                        with ui.row().classes('gap-2'):
                            start_btn = ui.button(icon='play_arrow').props('round color=white text-color=green-600 size=md aria-label="스케줄러 시작"')
                            stop_btn = ui.button(icon='stop').props('round color=white text-color=red-600 size=md aria-label="스케줄러 중지"')

                @ui.refreshable
                def readiness_notice():
                    messages = _schedule_readiness_messages()
                    if messages:
                        ui.label('Studio 직접 제작 준비 필요: ' + ' · '.join(messages)).classes(
                            'px-4 py-3 text-sm text-amber-300')
                    ui.label('상태·등록 수는 이 Studio 기준입니다. 에이전트 인계는 별도 대기 호스트를 사용합니다.').classes(
                        'px-4 pb-3 text-xs text-gray-300')

                readiness_notice()

                def update_status():
                    try:
                        if schedule_manager._scheduler_running:
                            status_header.classes(remove='from-red-600 to-orange-600', add='from-green-600 to-teal-600')
                            status_icon._props['name'] = 'play_circle'
                            status_label.text = 'Running'
                        else:
                            status_header.classes(remove='from-green-600 to-teal-600', add='from-red-600 to-orange-600')
                            status_icon._props['name'] = 'pause_circle'
                            status_label.text = 'Stopped'
                        status_header.update()
                        status_icon.update()
                    except (AttributeError, RuntimeError) as e:
                        logger.debug(f"Status update skipped: {e}")

                def start_scheduler():
                    try:
                        schedule_manager.start_scheduler()
                    except Exception as error:
                        logger.error(f"Scheduler start failed: {error}")
                        update_status()
                        safe_notify(f'❌ Scheduler start failed: {error}', type='negative')
                        return
                    update_status()
                    safe_notify('✅ Scheduler started', type='positive')
                    safe_refresh(schedule_list)

                def stop_scheduler():
                    schedule_manager.stop_scheduler()
                    update_status()
                    safe_notify('⏹️ Scheduler stopped', type='warning')
                    safe_refresh(schedule_list)

                start_btn.on_click(start_scheduler)
                stop_btn.on_click(stop_scheduler)
                update_status()

            # === Create Schedule Card ===
            with card_with_header('Create New Schedule', 'add_alarm', 'purple'):
                with ui.element('div').classes('p-5'):
                    # Schedule Name
                    with ui.column().classes('w-full gap-1 mb-4'):
                        ui.label('Schedule Name').classes('text-xs text-gray-400 uppercase tracking-wider')
                        schedule_name = ui.input('Schedule Name', value='4주 Shorts 기획').props('outlined dense dark').classes('w-full')

                    # Time & Frequency
                    with ui.row().classes('w-full gap-4 mb-4'):
                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('Time').classes('text-xs text-gray-400 uppercase tracking-wider')
                            with ui.row().classes('gap-2'):
                                hour_select = ui.select(
                                    options={str(i).zfill(2): str(i).zfill(2) for i in range(24)},
                                    value='09'
                                ).props('outlined dense dark aria-label="실행 시"').classes('w-20')
                                ui.label(':').classes('text-xl text-gray-400 self-center')
                                minute_select = ui.select(
                                    options={str(i).zfill(2): str(i).zfill(2) for i in range(0, 60, 5)},
                                    value='00'
                                ).props('outlined dense dark aria-label="실행 분"').classes('w-20')

                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('Frequency').classes('text-xs text-gray-400 uppercase tracking-wider')
                            frequency_select = ui.select(
                                options={
                                    'Daily': '📅 Daily',
                                    'Every 4 Weeks': '📅 Every 4 Weeks',
                                    'Weekly (Mon)': '📆 Mon',
                                    'Weekly (Tue)': '📆 Tue',
                                    'Weekly (Wed)': '📆 Wed',
                                    'Weekly (Thu)': '📆 Thu',
                                    'Weekly (Fri)': '📆 Fri',
                                    'Weekly (Sat)': '📆 Sat',
                                    'Weekly (Sun)': '📆 Sun',
                                },
                                value='Every 4 Weeks'
                            ).props('outlined dense dark aria-label="반복 주기"').classes('w-full')

                    ui.separator().classes('bg-slate-600 my-4')

                    # Content Source
                    ui.label('Content Source').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')

                    with ui.element('div').classes('w-full p-3 bg-slate-800/50 rounded-lg mb-3'):
                        source_mode = ui.radio(
                            ['Auto-Discovery (RSS)', 'Direct URL'],
                            value='Auto-Discovery (RSS)'
                        ).props('color=purple size=32px')

                    category_select = ui.select(
                        ['전체 분야', *SourceManager().get_categories()],
                        value='전체 분야', label='RSS Category'
                    ).props('outlined dense dark').classes('w-full mb-3')
                    category_select.bind_visibility_from(source_mode, 'value', value='Auto-Discovery (RSS)')

                    url_input = ui.input(
                        'Article URL',
                        placeholder='https://...'
                    ).props('outlined dense dark').classes('w-full mb-3')
                    url_input.bind_visibility_from(source_mode, 'value', value='Direct URL')
                    url_hint = ui.label(
                        'One article URL makes one episode. After rendering, this schedule pauses; use RSS for recurring topics.'
                    ).classes('text-xs text-gray-400 mb-3')
                    url_hint.bind_visibility_from(source_mode, 'value', value='Direct URL')

                    ui.separator().classes('bg-slate-600 my-4')

                    # Options
                    ui.label('Options').classes('text-xs text-gray-400 uppercase tracking-wider mb-3')

                    with ui.row().classes('w-full gap-4 mb-4'):
                        with ui.column().classes('gap-1'):
                            ui.label('Mode').classes('text-xs text-gray-300')
                            with ui.button_group().props('rounded'):
                                mode_hybrid_btn = ui.button(
                                    'HYBRID',
                                    on_click=lambda: mode_select.set_value('hybrid')
                                ).props('color=purple-9 size=sm')
                                mode_img_btn = ui.button(
                                    'IMAGE',
                                    on_click=lambda: mode_select.set_value('image')
                                ).props('outline color=purple-3 size=sm')
                                mode_vid_btn = ui.button(
                                    'VIDEO',
                                    on_click=lambda: mode_select.set_value('video')
                                ).props('outline color=purple-3 size=sm')
                            mode_select = ui.radio(['hybrid', 'image', 'video'], value='hybrid').classes('hidden')

                            def update_mode_btns():
                                for value, button in (
                                    ('hybrid', mode_hybrid_btn),
                                    ('image', mode_img_btn),
                                    ('video', mode_vid_btn),
                                ):
                                    if mode_select.value == value:
                                        button.props(remove='outline color=purple-3', add='color=purple-9')
                                    else:
                                        button.props(remove='color=purple-9', add='outline color=purple-3')
                            mode_select.on_value_change(lambda: update_mode_btns())

                        ui.label('예약 실행은 각본 검토에서 멈춥니다. 영상 제작과 비공개 업로드는 검토 후 Studio에서 진행합니다.').classes(
                            'text-xs text-amber-300')

                    # Create Button
                    def create_schedule():
                        time_str = f"{hour_select.value}:{minute_select.value}"
                        try:
                            schedule = schedule_manager.create_schedule(
                                name=schedule_name.value,
                                time=time_str,
                                frequency=frequency_select.value,
                                topic=(category_select.value if source_mode.value == 'Auto-Discovery (RSS)'
                                       and category_select.value != '전체 분야' else None),
                                direct_url=url_input.value if source_mode.value == 'Direct URL' else None,
                                auto_upload=False,
                                mode=mode_select.value,
                                enabled=True
                            )
                            safe_notify(f"✅ Schedule created: {schedule['name']}", type='positive')
                            logger.info(f"Created schedule: {schedule['name']} at {time_str}")
                            safe_refresh(schedule_list)
                            safe_refresh(history_list)
                        except Exception as e:
                            safe_notify(f"❌ Failed: {e}", type='negative')
                            logger.error(f"Schedule creation error: {e}")

                    ui.button(
                        'Create Schedule',
                        on_click=create_schedule
                    ).classes('w-full').props('color=purple-9 unelevated icon=add size=lg')

        # === Right Panel: Schedule List & History ===
        with ui.column().classes('w-full lg:w-auto lg:flex-grow min-w-0 gap-4'):

            # === Active Schedules Section ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-4 border-b border-slate-700'):
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('event_available', size='sm').classes('text-teal-400')
                        ui.label('Studio Registered Jobs').classes('text-lg font-bold text-white')

                        schedule_count_badge = ui.badge('0').props('color=teal-9 text-color=white')

                @ui.refreshable
                def schedule_list():
                    schedules = schedule_manager.load_schedules()
                    next_runs = {item['id']: item['next_run'] for item in schedule_manager.get_next_run_times()}
                    try:
                        schedule_count_badge.text = str(sum(run is not None for run in next_runs.values()))
                    except RuntimeError:
                        pass

                    if not schedules:
                        with ui.element('div').classes('p-8'):
                            with ui.column().classes('items-center gap-3'):
                                ui.icon('event_busy', size='xl').classes('text-slate-400')
                                ui.label('No schedules configured').classes('text-gray-300')
                                ui.label('Create your first schedule to automate video production').classes('text-xs text-gray-600')
                        return

                    with ui.scroll_area().classes('h-[40vh]'):
                        with ui.element('div').classes('p-4 space-y-3'):
                            for schedule in schedules:
                                enabled = schedule.get('enabled', True)
                                next_run = next_runs.get(schedule['id'])
                                registered = enabled and next_run is not None

                                card_class = 'w-full p-4 rounded-xl border transition-all duration-300 '
                                if registered:
                                    card_class += 'bg-gradient-to-r from-slate-700 to-slate-700/50 border-teal-500/30 hover:border-teal-500/60'
                                else:
                                    card_class += 'bg-slate-800/50 border-slate-700'

                                with ui.card().classes(card_class):
                                    with ui.row().classes('w-full items-center justify-between'):
                                        with ui.column().classes('flex-grow gap-2'):
                                            with ui.row().classes('items-center gap-3'):
                                                indicator_class = 'w-3 h-3 rounded-full '
                                                indicator_class += 'bg-green-500 animate-pulse' if registered else 'bg-gray-600'
                                                ui.element('div').classes(indicator_class)

                                                ui.label(schedule['name']).classes('font-bold text-white text-lg')
                                                if schedule.get('review_operator') == 'agent':
                                                    ui.badge('에이전트 인계').props('color=amber-9 text-color=white')

                                                mode = schedule.get('mode', 'image')
                                                mode_color = 'purple-9' if mode == 'video' else 'teal-9' if mode == 'hybrid' else 'blue-9'
                                                ui.badge(mode.upper()).props(f'color={mode_color} text-color=white').classes('text-xs px-2')

                                                if ((schedule.get('auto_upload') and schedule.get('last_result') == 'success')
                                                        or schedule.get('last_result') == 'private_review_accepted'):
                                                    ui.badge('YouTube').props('color=red-9 text-color=white').classes('text-xs px-2')

                                            with ui.row().classes('gap-4'):
                                                with ui.row().classes('items-center gap-1'):
                                                    ui.icon('schedule', size='xs').classes('text-amber-400')
                                                    ui.label(schedule['time']).classes('text-sm text-amber-300 font-medium')

                                                with ui.row().classes('items-center gap-1'):
                                                    ui.icon('date_range', size='xs').classes('text-gray-400')
                                                    ui.label(schedule.get('frequency', 'Daily')).classes('text-sm text-gray-400')

                                            ui.label(
                                                '직접 URL' if schedule.get('direct_url')
                                                else f"RSS: {schedule.get('topic') or '전체 분야'}"
                                            ).classes('text-xs text-gray-400')
                                            if schedule.get('first_run_at'):
                                                ui.label('첫 제작 예약: ' + schedule['first_run_at'][:16].replace('T', ' ')).classes(
                                                    'text-xs text-gray-400')

                                            review_path = _reviewable_video_path(schedule.get('last_video_path'))
                                            if not enabled and schedule.get('last_result') == 'success':
                                                message = ('영상 검토 대기 · 확인 후 일정 재개' if review_path else
                                                           '최근 성공 기록 · 영상은 출력 폴더에서 확인')
                                                ui.label(message).classes('text-xs text-amber-300')
                                            elif not enabled and schedule.get('last_result') == 'operator_pending':
                                                ui.label('예약 시각 도달 · 에이전트 제작 인계 대기 · API 호출 없음').classes(
                                                    'text-xs text-amber-300')
                                            elif not enabled and schedule.get('last_result') == 'script_review_pending':
                                                ui.label('비공개 완성본 사용자 채택 대기' if schedule.get('last_youtube_id')
                                                         else '각본·장면 검토 대기 · 영상 API와 업로드는 실행되지 않음').classes(
                                                    'text-xs text-amber-300')

                                                def load_pending_script(data=schedule.get('last_script')):
                                                    try:
                                                        script = ShortsScript.model_validate(data)
                                                        state.load_saved_script(script)
                                                    except (TypeError, ValueError) as error:
                                                        safe_notify(f'저장된 각본 확인 실패: {error}', type='negative')
                                                        return
                                                    safe_notify('각본을 불러왔습니다. Workspace의 Script Editor에서 장면을 검토하고 확인하세요.', type='info')

                                                ui.button('검토할 각본 불러오기', on_click=load_pending_script).props(
                                                    'flat dense color=amber')
                                            elif not enabled and schedule.get('last_result') == 'run_in_progress':
                                                ui.label('제작 완료 미확인 · 출력과 청구 내역 확인 후 일정 재개').classes('text-xs text-amber-300')
                                            elif enabled and schedule.get('last_result') == 'source_unavailable':
                                                ui.label('RSS 피드 읽기 실패 · 다음 예약에 다시 확인').classes('text-xs text-amber-300')
                                            elif schedule.get('last_result') == 'private_review_accepted':
                                                message = ('비공개 영상 검토 완료 · 직접 URL 일정 종료'
                                                           if schedule.get('direct_url') else
                                                           '비공개 영상 검토 완료 · RSS는 다음 예약에서 새 소재 탐색')
                                                ui.label(message).classes(
                                                    'text-xs text-teal-300')
                                            if review_path:
                                                with ui.dialog() as review_dialog, ui.card():
                                                    ui.label('최근 제작 영상').classes('text-lg font-medium')
                                                    ui.video(review_path).classes('w-full max-w-[270px] max-h-[480px] bg-black')
                                                    ui.button('닫기', on_click=review_dialog.close)
                                                ui.button('최근 영상 재생', on_click=review_dialog.open).props('flat dense color=teal')
                                            elif schedule.get('last_video_path'):
                                                ui.label('최근 영상 파일을 찾을 수 없습니다. 출력 폴더를 확인하세요.').classes('text-xs text-amber-300')
                                            youtube_url = _reviewable_youtube_url(schedule.get('last_youtube_id'))
                                            if youtube_url and (
                                                schedule.get('last_result') in {'private_review_accepted', 'script_review_pending'}
                                                or (schedule.get('auto_upload') and schedule.get('last_result') == 'success')
                                            ):
                                                ui.link('YouTube 비공개 검토본 보기', youtube_url, new_tab=True).classes(
                                                    'text-xs text-teal-300')

                                            if registered:
                                                with ui.element('div').classes('mt-2 p-2 bg-teal-900/30 rounded-lg border border-teal-500/20'):
                                                    with ui.row().classes('items-center gap-2'):
                                                        ui.icon('alarm', size='xs').classes('text-teal-400')
                                                        ui.label('Next run:').classes('text-xs text-teal-400')
                                                        ui.label(next_run[:16].replace('T', ' ')).classes('text-sm text-teal-300 font-medium')
                                            elif enabled:
                                                ui.label('별도 대기 호스트 사용 · 운영 상태 별도 확인'
                                                         if schedule.get('review_operator') == 'agent'
                                                         else 'Studio Scheduler stopped or job not registered').classes(
                                                    'text-xs text-amber-300')

                                        with ui.column().classes('gap-2'):
                                            def toggle_schedule(sid=schedule['id']):
                                                try:
                                                    schedule_manager.toggle_schedule(sid)
                                                except Exception as error:
                                                    safe_notify(f'일정 변경 실패: {error}', type='negative')
                                                safe_refresh(schedule_list)
                                                safe_refresh(history_list)

                                            def reject_pending_script(sid=schedule['id']):
                                                with ui.dialog() as dialog, ui.card():
                                                    ui.label('이 각본을 제외하고 다음 소재를 찾을까요?')
                                                    ui.label('RSS 일정은 다음 예약 시 다시 기획합니다. 직접 URL 일정은 중지 상태로 남습니다.').classes(
                                                        'text-xs text-gray-400')
                                                    with ui.row():
                                                        ui.button('취소', on_click=dialog.close)

                                                        def confirm_rejection():
                                                            try:
                                                                schedule_manager.reject_pending_script(sid)
                                                                dialog.close()
                                                                safe_refresh(schedule_list)
                                                                safe_refresh(history_list)
                                                            except Exception as error:
                                                                safe_notify(f'각본 제외 실패: {error}', type='negative')

                                                        ui.button('각본 제외', on_click=confirm_rejection).props('color=amber')
                                                dialog.open()

                                            def accept_pending_video(sid=schedule['id'], name=schedule['name'],
                                                                     video_path=schedule.get('last_video_path')):
                                                with ui.dialog() as dialog, ui.card():
                                                    ui.label('비공개 영상 검토 완료').classes('text-lg font-medium')
                                                    ui.label(f'일정: {name}')
                                                    ui.label('전체 영상과 출처·음악·자막을 확인했다면 완성 MP4 경로를 입력하세요.').classes(
                                                        'text-xs text-gray-400')
                                                    ui.label('유료 제작 스위치와 월 장부가 활성화돼 있으면 다음 예약에서 기획 비용이 발생할 수 있습니다.').classes(
                                                        'text-xs text-amber-300')
                                                    path_input = ui.input('완성 MP4 경로', value=video_path or state.final_video_path or '').classes(
                                                        'w-full min-w-[320px]')
                                                    with ui.row():
                                                        ui.button('취소', on_click=dialog.close)

                                                        def confirm_acceptance():
                                                            try:
                                                                schedule_manager.accept_pending_video(sid, path_input.value)
                                                                dialog.close()
                                                                safe_notify('비공개 영상 검토 완료가 기록됐습니다.', type='positive')
                                                                safe_refresh(schedule_list)
                                                                safe_refresh(history_list)
                                                            except Exception as error:
                                                                safe_notify(f'완료 기록 실패: {error}', type='negative')

                                                        ui.button('검토 완료·다음 소재 예약', on_click=confirm_acceptance).props(
                                                            'color=teal')
                                                dialog.open()

                                            def delete_schedule(sid=schedule['id'], sname=schedule['name']):
                                                with ui.dialog() as dialog, ui.card():
                                                    ui.label(f'{sname} 일정을 삭제할까요?')
                                                    with ui.row():
                                                        ui.button('취소', on_click=dialog.close)

                                                        def confirm():
                                                            try:
                                                                schedule_manager.delete_schedule(sid)
                                                                dialog.close()
                                                                safe_notify(f'일정 삭제됨: {sname}', type='warning')
                                                                safe_refresh(schedule_list)
                                                                safe_refresh(history_list)
                                                            except (OSError, ValueError) as error:
                                                                safe_notify(f'삭제 실패: {error}', type='negative')

                                                        ui.button('삭제', on_click=confirm).props('color=red')
                                                dialog.open()

                                            toggle_icon = 'pause' if enabled else 'play_arrow'
                                            toggle_color = 'amber' if enabled else 'green'
                                            toggle_tip = 'Pause' if enabled else 'Resume'
                                            if not enabled and schedule.get('last_result') == 'script_review_pending':
                                                ui.button('비공개 영상 검토 완료', on_click=accept_pending_video).props(
                                                    'flat dense color=teal')
                                                ui.button('각본 제외', on_click=reject_pending_script).props(
                                                    'flat dense color=amber')
                                            else:
                                                ui.button(
                                                    icon=toggle_icon,
                                                    on_click=toggle_schedule
                                                ).props(f'round size=md color={toggle_color} aria-label="일정 {"일시정지" if enabled else "재개"}"').tooltip(toggle_tip)

                                            ui.button(
                                                icon='delete_outline',
                                                on_click=delete_schedule
                                            ).props('round size=md flat color=red aria-label="일정 삭제"').tooltip('Delete')

                schedule_list()

            # === Execution History Section ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-4 border-b border-slate-700'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('history', size='sm').classes('text-amber-400')
                        ui.label('Execution History').classes('text-lg font-bold text-white')

                @ui.refreshable
                def history_list():
                    run_schedules = schedule_manager.get_execution_history()

                    if not run_schedules:
                        with ui.element('div').classes('p-8'):
                            with ui.column().classes('items-center gap-3'):
                                ui.icon('hourglass_empty', size='xl').classes('text-slate-400')
                                ui.label('No execution history yet').classes('text-gray-300')
                                ui.label('History will appear after schedules run').classes('text-xs text-gray-600')
                        return

                    with ui.scroll_area().classes('h-[25vh]'):
                        with ui.element('div').classes('p-4 space-y-2'):
                            for schedule in run_schedules[:10]:
                                last_result = schedule.get('last_result', 'unknown')
                                is_success = last_result in {'success', 'private_review_accepted'}
                                is_pending = last_result in {'operator_pending', 'script_review_pending', 'run_in_progress'}
                                run_count = schedule.get('run_count', 0)

                                color = 'green' if is_success else 'amber' if is_pending else 'red'
                                result_class = f'border-l-4 border-{color}-500 bg-{color}-900/10'

                                with ui.element('div').classes(f'w-full p-3 rounded-r-lg {result_class}'):
                                    with ui.row().classes('w-full items-center justify-between'):
                                        with ui.row().classes('items-center gap-3'):
                                            icon_name = 'check_circle' if is_success else 'hourglass_empty' if is_pending else 'error'
                                            icon_class = f'text-{color}-400'
                                            ui.icon(icon_name, size='sm').classes(icon_class)

                                            with ui.column().classes('gap-0'):
                                                ui.label(schedule['name']).classes('text-sm font-medium text-white')
                                                ui.label(schedule.get('last_run', '')[:19].replace('T', ' ')).classes('text-xs text-gray-300')
                                                script = schedule.get('last_script')
                                                if isinstance(script, dict) and script.get('title'):
                                                    ui.label(script['title']).classes('text-xs text-gray-300')

                                        with ui.row().classes('items-center gap-2'):
                                            ui.badge(f'#{run_count}').props('color=blue-grey-8 text-color=white').classes('text-xs')
                                            ui.badge(last_result).props(f'color={color}-9 text-color=white').classes('text-xs')

                history_list()

            # Auto-refresh every 30 seconds
            ui.timer(30.0, lambda: (safe_refresh(schedule_list), safe_refresh(history_list),
                                    safe_refresh(readiness_notice)))
