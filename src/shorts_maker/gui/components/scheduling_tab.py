"""Schedule Management 탭 컴포넌트"""

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.utils.scheduler import ScheduleManager
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

# 전역 스케줄 매니저
schedule_manager = ScheduleManager()


def render_scheduling_tab(state: 'AppState') -> None:
    """Schedule Management 탭 렌더링"""

    with ui.row().classes('w-full h-full gap-6'):
        # === Left Panel: Create & Control ===
        with ui.column().classes('w-96 min-w-[380px] gap-4'):

            # === Scheduler Status Card ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                status_header = ui.element('div').classes('w-full p-4 bg-gradient-to-r from-red-600 to-orange-600')

                with status_header:
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-3'):
                            status_icon = ui.icon('pause_circle', size='md').classes('text-white')
                            with ui.column().classes('gap-0'):
                                ui.label('Scheduler').classes('text-sm text-white/70')
                                status_label = ui.label('Stopped').classes('text-lg font-bold text-white')

                        with ui.row().classes('gap-2'):
                            start_btn = ui.button(icon='play_arrow').props('round color=white text-color=green-600 size=md')
                            stop_btn = ui.button(icon='stop').props('round color=white text-color=red-600 size=md')

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
                    schedule_manager.start_scheduler()
                    update_status()
                    safe_notify('✅ Scheduler started', type='positive')
                    safe_refresh(schedule_list)

                def stop_scheduler():
                    schedule_manager.stop_scheduler()
                    update_status()
                    safe_notify('⏹️ Scheduler stopped', type='warning')

                start_btn.on_click(start_scheduler)
                stop_btn.on_click(stop_scheduler)
                update_status()

            # === Create Schedule Card ===
            with card_with_header('Create New Schedule', 'add_alarm', 'purple'):
                with ui.element('div').classes('p-5'):
                    # Schedule Name
                    with ui.column().classes('w-full gap-1 mb-4'):
                        ui.label('Schedule Name').classes('text-xs text-gray-400 uppercase tracking-wider')
                        schedule_name = ui.input(value='Daily Tech News').props('outlined dense dark').classes('w-full')

                    # Time & Frequency
                    with ui.row().classes('w-full gap-4 mb-4'):
                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('Time').classes('text-xs text-gray-400 uppercase tracking-wider')
                            with ui.row().classes('gap-2'):
                                hour_select = ui.select(
                                    options={str(i).zfill(2): str(i).zfill(2) for i in range(24)},
                                    value='09'
                                ).props('outlined dense dark').classes('w-20')
                                ui.label(':').classes('text-xl text-gray-400 self-center')
                                minute_select = ui.select(
                                    options={str(i).zfill(2): str(i).zfill(2) for i in range(0, 60, 5)},
                                    value='00'
                                ).props('outlined dense dark').classes('w-20')

                        with ui.column().classes('flex-grow gap-1'):
                            ui.label('Frequency').classes('text-xs text-gray-400 uppercase tracking-wider')
                            frequency_select = ui.select(
                                options={
                                    'Daily': '📅 Daily',
                                    'Weekly (Mon)': '📆 Mon',
                                    'Weekly (Tue)': '📆 Tue',
                                    'Weekly (Wed)': '📆 Wed',
                                    'Weekly (Thu)': '📆 Thu',
                                    'Weekly (Fri)': '📆 Fri',
                                    'Weekly (Sat)': '📆 Sat',
                                    'Weekly (Sun)': '📆 Sun',
                                },
                                value='Daily'
                            ).props('outlined dense dark').classes('w-full')

                    ui.separator().classes('bg-slate-600 my-4')

                    # Content Source
                    ui.label('Content Source').classes('text-xs text-gray-400 uppercase tracking-wider mb-2')

                    with ui.element('div').classes('w-full p-3 bg-slate-800/50 rounded-lg mb-3'):
                        source_mode = ui.radio(
                            ['Auto-Discovery (RSS)', 'Direct URL'],
                            value='Auto-Discovery (RSS)'
                        ).props('color=purple dense')

                    topic_input = ui.input(
                        'Topic Keyword',
                        placeholder='e.g., AI, Technology'
                    ).props('outlined dense dark').classes('w-full mb-3')
                    topic_input.bind_visibility_from(source_mode, 'value', value='Auto-Discovery (RSS)')

                    url_input = ui.input(
                        'Article URL',
                        placeholder='https://...'
                    ).props('outlined dense dark').classes('w-full mb-3')
                    url_input.bind_visibility_from(source_mode, 'value', value='Direct URL')

                    ui.separator().classes('bg-slate-600 my-4')

                    # Options
                    ui.label('Options').classes('text-xs text-gray-400 uppercase tracking-wider mb-3')

                    with ui.row().classes('w-full gap-4 mb-4'):
                        with ui.column().classes('gap-1'):
                            ui.label('Mode').classes('text-xs text-gray-500')
                            with ui.button_group().props('rounded'):
                                mode_img_btn = ui.button(
                                    'IMAGE',
                                    on_click=lambda: mode_select.set_value('image')
                                ).props('outline color=purple size=sm')
                                mode_vid_btn = ui.button(
                                    'VIDEO',
                                    on_click=lambda: mode_select.set_value('video')
                                ).props('color=purple size=sm')
                            mode_select = ui.radio(['image', 'video'], value='video').classes('hidden')

                            def update_mode_btns():
                                if mode_select.value == 'video':
                                    mode_vid_btn.props(remove='outline', add='')
                                    mode_img_btn.props(remove='', add='outline')
                                else:
                                    mode_img_btn.props(remove='outline', add='')
                                    mode_vid_btn.props(remove='', add='outline')
                            mode_select.on_value_change(lambda: update_mode_btns())

                        with ui.column().classes('gap-1'):
                            ui.label('YouTube').classes('text-xs text-gray-500')
                            auto_upload_check = ui.switch('Auto-Upload').props('color=red dense')

                    # Create Button
                    def create_schedule():
                        time_str = f"{hour_select.value}:{minute_select.value}"
                        try:
                            schedule = schedule_manager.create_schedule(
                                name=schedule_name.value,
                                time=time_str,
                                frequency=frequency_select.value,
                                topic=topic_input.value if source_mode.value == 'Auto-Discovery (RSS)' else None,
                                direct_url=url_input.value if source_mode.value == 'Direct URL' else None,
                                auto_upload=auto_upload_check.value,
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
                    ).classes('w-full').props('color=purple unelevated icon=add size=lg')

        # === Right Panel: Schedule List & History ===
        with ui.column().classes('flex-grow gap-4'):

            # === Active Schedules Section ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-4 border-b border-slate-700'):
                    with ui.row().classes('items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('event_available', size='sm').classes('text-teal-400')
                            ui.label('Active Schedules').classes('text-lg font-bold text-white')

                        schedule_count_badge = ui.badge('0').classes('bg-teal-600 text-white')

                @ui.refreshable
                def schedule_list():
                    schedules = schedule_manager.load_schedules()
                    try:
                        schedule_count_badge.text = str(len(schedules))
                    except RuntimeError:
                        pass

                    if not schedules:
                        with ui.element('div').classes('p-8'):
                            with ui.column().classes('items-center gap-3'):
                                ui.icon('event_busy', size='xl').classes('text-slate-600')
                                ui.label('No schedules configured').classes('text-gray-500')
                                ui.label('Create your first schedule to automate video production').classes('text-xs text-gray-600')
                        return

                    next_runs = {item['id']: item['next_run'] for item in schedule_manager.get_next_run_times()}

                    with ui.scroll_area().classes('h-[40vh]'):
                        with ui.element('div').classes('p-4 space-y-3'):
                            for schedule in schedules:
                                enabled = schedule.get('enabled', True)
                                next_run = next_runs.get(schedule['id'])

                                card_class = 'w-full p-4 rounded-xl border transition-all duration-300 '
                                if enabled:
                                    card_class += 'bg-gradient-to-r from-slate-700 to-slate-700/50 border-teal-500/30 hover:border-teal-500/60'
                                else:
                                    card_class += 'bg-slate-800/50 border-slate-700 opacity-60'

                                with ui.card().classes(card_class):
                                    with ui.row().classes('w-full items-center justify-between'):
                                        with ui.column().classes('flex-grow gap-2'):
                                            with ui.row().classes('items-center gap-3'):
                                                indicator_class = 'w-3 h-3 rounded-full '
                                                indicator_class += 'bg-green-500 animate-pulse' if enabled else 'bg-gray-600'
                                                ui.element('div').classes(indicator_class)

                                                ui.label(schedule['name']).classes('font-bold text-white text-lg')

                                                mode = schedule.get('mode', 'image')
                                                mode_color = 'bg-purple-600' if mode == 'video' else 'bg-blue-600'
                                                ui.badge(mode.upper()).classes(f'{mode_color} text-white text-xs px-2')

                                                if schedule.get('auto_upload'):
                                                    ui.badge('YouTube').classes('bg-red-600 text-white text-xs px-2')

                                            with ui.row().classes('gap-4'):
                                                with ui.row().classes('items-center gap-1'):
                                                    ui.icon('schedule', size='xs').classes('text-amber-400')
                                                    ui.label(schedule['time']).classes('text-sm text-amber-300 font-medium')

                                                with ui.row().classes('items-center gap-1'):
                                                    ui.icon('date_range', size='xs').classes('text-gray-400')
                                                    ui.label(schedule.get('frequency', 'Daily')).classes('text-sm text-gray-400')

                                            if next_run and enabled:
                                                with ui.element('div').classes('mt-2 p-2 bg-teal-900/30 rounded-lg border border-teal-500/20'):
                                                    with ui.row().classes('items-center gap-2'):
                                                        ui.icon('alarm', size='xs').classes('text-teal-400')
                                                        ui.label('Next run:').classes('text-xs text-teal-400')
                                                        ui.label(next_run[:16].replace('T', ' ')).classes('text-sm text-teal-300 font-medium')

                                        with ui.column().classes('gap-2'):
                                            def toggle_schedule(sid=schedule['id']):
                                                schedule_manager.toggle_schedule(sid)
                                                safe_refresh(schedule_list)
                                                safe_refresh(history_list)

                                            def delete_schedule(sid=schedule['id'], sname=schedule['name']):
                                                schedule_manager.delete_schedule(sid)
                                                safe_notify(f"🗑️ Deleted: {sname}", type='warning')
                                                safe_refresh(schedule_list)
                                                safe_refresh(history_list)

                                            toggle_icon = 'pause' if enabled else 'play_arrow'
                                            toggle_color = 'amber' if enabled else 'green'
                                            toggle_tip = 'Pause' if enabled else 'Resume'
                                            ui.button(
                                                icon=toggle_icon,
                                                on_click=toggle_schedule
                                            ).props(f'round size=md color={toggle_color}').tooltip(toggle_tip)

                                            ui.button(
                                                icon='delete_outline',
                                                on_click=delete_schedule
                                            ).props('round size=md flat color=red').tooltip('Delete')

                schedule_list()

            # === Execution History Section ===
            with ui.card().classes('w-full p-0 bg-slate-800 border border-slate-600 overflow-hidden'):
                with ui.element('div').classes('w-full p-4 border-b border-slate-700'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('history', size='sm').classes('text-amber-400')
                        ui.label('Execution History').classes('text-lg font-bold text-white')

                @ui.refreshable
                def history_list():
                    schedules = schedule_manager.load_schedules()
                    run_schedules = [s for s in schedules if s.get('last_run')]
                    run_schedules.sort(key=lambda x: x.get('last_run', ''), reverse=True)

                    if not run_schedules:
                        with ui.element('div').classes('p-8'):
                            with ui.column().classes('items-center gap-3'):
                                ui.icon('hourglass_empty', size='xl').classes('text-slate-600')
                                ui.label('No execution history yet').classes('text-gray-500')
                                ui.label('History will appear after schedules run').classes('text-xs text-gray-600')
                        return

                    with ui.scroll_area().classes('h-[25vh]'):
                        with ui.element('div').classes('p-4 space-y-2'):
                            for schedule in run_schedules[:10]:
                                last_result = schedule.get('last_result', 'unknown')
                                is_success = last_result == 'success'
                                run_count = schedule.get('run_count', 0)

                                result_class = 'border-l-4 '
                                result_class += 'border-green-500 bg-green-900/10' if is_success else 'border-red-500 bg-red-900/10'

                                with ui.element('div').classes(f'w-full p-3 rounded-r-lg {result_class}'):
                                    with ui.row().classes('w-full items-center justify-between'):
                                        with ui.row().classes('items-center gap-3'):
                                            icon_name = 'check_circle' if is_success else 'error'
                                            icon_class = 'text-green-400' if is_success else 'text-red-400'
                                            ui.icon(icon_name, size='sm').classes(icon_class)

                                            with ui.column().classes('gap-0'):
                                                ui.label(schedule['name']).classes('text-sm font-medium text-white')
                                                ui.label(schedule.get('last_run', '')[:19].replace('T', ' ')).classes('text-xs text-gray-500')

                                        with ui.row().classes('items-center gap-2'):
                                            ui.badge(f'#{run_count}').classes('bg-slate-600 text-gray-300 text-xs')
                                            result_badge_class = 'bg-green-600' if is_success else 'bg-red-600'
                                            ui.badge(last_result[:15]).classes(f'{result_badge_class} text-white text-xs')

                history_list()

            # Auto-refresh every 30 seconds
            ui.timer(30.0, lambda: (safe_refresh(schedule_list), safe_refresh(history_list)))
