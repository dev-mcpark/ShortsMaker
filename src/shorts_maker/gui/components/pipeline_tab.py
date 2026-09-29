"""Full Pipeline 실행 탭 컴포넌트 - Google AI Studio 스타일 개편"""
from nicegui import ui
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Callable

from shorts_maker.gui.components.common.safe_ui import (
    safe_notify, safe_refresh, safe_update, safe_set_visibility
)
from shorts_maker.services.production_service import ProductionPhase, ProductionProgress
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger
from shorts_maker.gui.components.common.progress_utils import format_time, update_scene_grid

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_pipeline_tab(
    state: 'AppState',
    step_indicators: List = None,
    update_step_indicators_fn: Callable = None
) -> None:
    """Full Pipeline 실행 탭 렌더링 - 2단 슬림 레이아웃"""

    # Progress bar references
    progress_bars: Dict[str, ui.linear_progress] = {}
    phase_labels: Dict[str, ui.label] = {}
    phase_time_labels: Dict[str, ui.label] = {}

    # UI element references
    start_btn = None
    stop_btn = None
    error_panel = None
    error_message_label = None
    error_details_label = None
    video_preview = None
    preview_placeholder = None
    scene_grid = None
    elapsed_label = None
    scenes_label = None
    current_task_label = None
    history_count_badge = None

    # History 초기화
    if not hasattr(state, 'pipeline_history'):
        state.pipeline_history = []

    def show_error_panel(message: str):
        """에러 패널 표시"""
        try:
            error_panel.visible = True
            error_message_label.text = '파이프라인 실행 실패 (Error)'
            short_msg = message[:200] + '...' if len(message) > 200 else message
            error_details_label.text = short_msg
        except RuntimeError:
            pass

    def hide_error_panel():
        """에러 패널 숨기기"""
        try:
            error_panel.visible = False
        except RuntimeError:
            pass

    # 중앙 가변 영역에 최적화된 2단 레이아웃
    with ui.row().classes('w-full h-full gap-5 overflow-hidden no-wrap bg-slate-950'):

        # =====================================================================
        # === 1. LEFT PANEL: CONTROLS & STATUS (320px 고정폭) ===
        # =====================================================================
        with ui.column().classes('w-80 min-w-[320px] bg-slate-900 border-r border-slate-800 p-5 gap-4 overflow-y-auto shrink-0'):

            # --- Pipeline Control ---
            with ui.column().classes('w-full gap-2.5'):
                ui.label('콘텐츠 소스 입력').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')

                source_mode = ui.radio(
                    ['Auto (RSS)', 'Direct URL'],
                    value='Auto (RSS)'
                ).props('color=violet dense').classes('text-xs text-slate-300 gap-4 mb-1')

                topic_input = ui.input(
                    'RSS 토픽 키워드',
                    placeholder='예: AI, 과학, 테크 뉴스'
                ).props('outlined dense dark').classes('w-full text-xs')
                topic_input.bind_visibility_from(source_mode, 'value', value='Auto (RSS)')

                url_input = ui.input(
                    '개별 기사 URL 주소',
                    placeholder='https://...'
                ).props('outlined dense dark').classes('w-full text-xs')
                url_input.bind_visibility_from(source_mode, 'value', value='Direct URL')

            ui.separator().classes('bg-slate-800 my-1')

            # --- Options ---
            with ui.column().classes('w-full gap-2'):
                ui.label('퍼블리싱 & 하이퍼파라미터').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')

                auto_upload = ui.switch('유튜브 자동 업로드').props('color=red dense').classes('text-xs text-slate-400')
                parallel_clips = ui.switch('미디어 병렬 고속 생성').props('color=violet dense').classes('text-xs text-slate-400')

                character_overlay = ui.switch('캐릭터 아바타 오버레이').props('color=violet dense').classes('text-xs text-slate-400')
                character_overlay.bind_value(state, 'character_overlay_enabled')

            ui.separator().classes('bg-slate-800 my-1')

            # --- Execution Actions ---
            async def run_full_pipeline():
                nonlocal start_btn, stop_btn

                if state.pipeline_running:
                    safe_notify('이미 파이프라인이 구동 중입니다!', type='warning')
                    return

                if source_mode.value == 'Direct URL' and not url_input.value:
                    safe_notify('직접 크롤링할 URL을 입력해주십시오.', type='negative')
                    return

                # 파이프라인 상태 초기화
                state.pipeline_running = True
                state.pipeline_phase = ProductionPhase.IDLE
                state.last_error = None

                try:
                    start_btn.disable()
                    stop_btn.enable()
                except RuntimeError:
                    pass

                # UI 요소 초기화
                for bar in progress_bars.values():
                    try:
                        bar.set_value(0)
                    except RuntimeError:
                        pass

                for label in phase_labels.values():
                    try:
                        label.text = '대기 중'
                        label.classes(remove='text-violet-400 text-teal-400 text-rose-400', add='text-slate-500')
                    except RuntimeError:
                        pass

                for label in phase_time_labels.values():
                    try:
                        label.text = ''
                    except RuntimeError:
                        pass

                try:
                    scene_grid.clear()
                    with scene_grid:
                        with ui.column().classes('w-full items-center justify-center py-8'):
                            ui.icon('burst_mode', size='md').classes('text-slate-700')
                            ui.label('생성된 씬 클립들이 여기에 실시간 표시됩니다').classes('text-xs text-slate-500')
                except RuntimeError:
                    pass

                hide_error_panel()
                safe_set_visibility(video_preview, False)
                safe_set_visibility(preview_placeholder, True)

                try:
                    # API Key 및 GCP 프로젝트 동적 매핑
                    if state.openai_key or state.gcp_project:
                        settings.update_api_keys(
                            openai_key=state.openai_key,
                            gcp_project=state.gcp_project
                        )

                    # 캐릭터 설정 바인딩
                    char_config = state.build_character_overlay_config()

                    from shorts_maker.services.production_service import ProductionService
                    service = ProductionService(
                        mode=state.mode,
                        parallel_clips=parallel_clips.value,
                        character_overlay_config=char_config
                    )
                    state.production_service = service

                    # 콜백 연결
                    def on_progress(progress: ProductionProgress):
                        state.sync_from_progress(progress)

                    service.set_progress_callback(on_progress)

                    # 백그라운드 스레드 모니터
                    async def monitor_progress():
                        while state.pipeline_running:
                            progress = service.progress
                            phase_key = progress.phase.value

                            # 진행률 바 갱신
                            if phase_key in progress_bars:
                                try:
                                    progress_bars[phase_key].set_value(progress.progress_percent / 100)
                                except RuntimeError:
                                    pass

                            # 진행 메시지 라벨 갱신
                            if phase_key in phase_labels:
                                try:
                                    if 0 < progress.progress_percent < 100:
                                        phase_labels[phase_key].text = f'{progress.progress_percent:.0f}% 진행'
                                        phase_labels[phase_key].classes(remove='text-slate-500 text-violet-400', add='text-teal-400')
                                    elif progress.progress_percent >= 100:
                                        phase_labels[phase_key].text = '✓ 완료'
                                        phase_labels[phase_key].classes(remove='text-slate-500 text-teal-400', add='text-violet-400 font-bold')
                                except RuntimeError:
                                    pass

                            # 소요 시간 갱신
                            if phase_key in phase_time_labels:
                                try:
                                    elapsed = format_time(progress.elapsed_seconds)
                                    if progress.remaining_seconds > 0:
                                        remaining = format_time(progress.remaining_seconds)
                                        phase_time_labels[phase_key].text = f'{elapsed} / 약 {remaining} 남음'
                                    else:
                                        phase_time_labels[phase_key].text = elapsed
                                except RuntimeError:
                                    pass

                            # 씬 미디어 격자 상황판 업데이트
                            update_scene_grid(progress.scene_progresses, scene_grid)

                            # 글로벌 진행 수치 갱신
                            try:
                                elapsed_label.text = f'⏱️ {format_time(progress.elapsed_seconds)}'
                                if progress.total_scenes > 0:
                                    scenes_label.text = f'📹 {progress.completed_scenes}/{progress.total_scenes} 씬'
                                current_task_label.text = progress.message
                            except RuntimeError:
                                pass

                            # 상단 헤더 이정표와 연계 갱신
                            if update_step_indicators_fn and step_indicators:
                                update_step_indicators_fn(progress.phase, step_indicators)

                            if progress.phase in [ProductionPhase.COMPLETED, ProductionPhase.FAILED]:
                                break

                            await asyncio.sleep(0.3)

                    monitor_task = asyncio.create_task(monitor_progress())

                    logger.info("=== Production Full Pipeline Triggered ===")

                    result = await service.full_pipeline(
                        topic=topic_input.value if source_mode.value == 'Auto (RSS)' else None,
                        direct_url=url_input.value if source_mode.value == 'Direct URL' else None,
                        auto_upload=auto_upload.value
                    )

                    state.pipeline_running = False
                    await monitor_task

                    if result.success:
                        state.final_video_path = result.video_path
                        state.pipeline_phase = ProductionPhase.COMPLETED
                        state.pipeline_message = "파이프라인 전체 완료!"
                        safe_notify('🎉 전 프로세스가 성공적으로 조율되었습니다!', type='positive')

                        if result.video_path:
                            try:
                                video_preview.set_source(result.video_path)
                                video_preview.visible = True
                                preview_placeholder.visible = False
                            except Exception as e:
                                logger.warning(f"Video set source failed: {e}")

                        if result.youtube_id:
                            safe_notify(f'📺 유튜브 자동 업로드 성공! ID: {result.youtube_id}', type='positive')

                        for bar in progress_bars.values():
                            try:
                                bar.set_value(1.0)
                            except RuntimeError:
                                pass

                        if update_step_indicators_fn and step_indicators:
                            update_step_indicators_fn(ProductionPhase.COMPLETED, step_indicators)

                        # 이력에 추가
                        state.pipeline_history.append({
                            'title': state.script.title if state.script else '자동 완성 쇼츠',
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
                            'success': True,
                            'video_path': result.video_path,
                            'youtube_id': result.youtube_id
                        })
                        safe_refresh(history_list)

                    else:
                        state.pipeline_phase = ProductionPhase.FAILED
                        state.pipeline_message = f"오류: {result.error}"
                        state.last_error = result.error
                        show_error_panel(result.error)
                        safe_notify('❌ 파이프라인 구동 중 에러가 발생했습니다.', type='negative')

                        state.pipeline_history.append({
                            'title': state.script.title if state.script else '작업 실패',
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
                            'success': False,
                            'error': result.error
                        })
                        safe_refresh(history_list)

                except Exception as e:
                    state.pipeline_phase = ProductionPhase.FAILED
                    state.pipeline_message = f"치명적 오류: {str(e)}"
                    state.last_error = str(e)
                    show_error_panel(str(e))
                    safe_notify(f'❌ 실행 실패: {e}', type='negative')
                    logger.error(f"Pipeline running crash: {e}")

                finally:
                    state.pipeline_running = False
                    try:
                        start_btn.enable()
                        stop_btn.disable()
                    except RuntimeError:
                        pass

            async def stop_pipeline():
                """파이프라인 실행 긴급 중단"""
                if state.production_service:
                    state.production_service.cancel()
                state.pipeline_running = False
                state.pipeline_phase = ProductionPhase.FAILED
                state.pipeline_message = "사용자에 의해 취소됨"
                safe_notify('⚠️ 파이프라인 중단 요청 전송 완료', type='warning')

            with ui.row().classes('w-full gap-2 mt-2'):
                start_btn = ui.button(
                    '실행 시작',
                    on_click=run_full_pipeline
                ).classes('flex-grow font-bold text-xs py-1.5 bg-gradient-to-r from-violet-600 to-indigo-600').props('unelevated icon=play_arrow')

                stop_btn = ui.button(on_click=stop_pipeline).props('flat round color=red icon=stop').classes('bg-slate-800/80')
                stop_btn.disable()

            ui.separator().classes('bg-slate-800 my-1')

            # --- Live Progress Monitor ---
            with ui.column().classes('w-full gap-2 p-3 bg-slate-950/60 border border-slate-800/80 rounded-xl'):
                ui.label('콘솔 모니터').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')

                with ui.row().classes('w-full justify-between items-center px-1'):
                    with ui.column().classes('items-start gap-0.5'):
                        elapsed_label = ui.label('00:00').classes('text-lg font-bold text-white font-mono')
                        ui.label('경과 시간').classes('text-[10px] text-slate-500 font-semibold')
                    with ui.column().classes('items-end gap-0.5'):
                        scenes_label = ui.label('0/0 씬').classes('text-lg font-bold text-violet-400')
                        ui.label('완료 진행도').classes('text-[10px] text-slate-500 font-semibold')

                current_task_label = ui.label('대기 중...').classes(
                    'text-[10px] text-slate-400 font-mono truncate w-full text-center py-2 px-1 bg-slate-900 border border-slate-800/80 rounded'
                )

            # --- Recent Runs (Execution History) ---
            with ui.column().classes('w-full gap-2 mt-1'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('최근 실행 이력').classes('text-[10px] text-slate-500 font-bold uppercase tracking-widest')
                    history_count_badge = ui.badge('0').classes('bg-slate-800 text-slate-400 text-[10px] border border-slate-700 px-1.5')

                @ui.refreshable
                def history_list():
                    history = getattr(state, 'pipeline_history', [])
                    try:
                        history_count_badge.text = str(len(history))
                    except RuntimeError:
                        pass

                    if not history:
                        with ui.element('div').classes('w-full py-4 text-center border border-dashed border-slate-800 rounded-lg'):
                            ui.label('기록 없음').classes('text-[11px] text-slate-600')
                        return

                    with ui.scroll_area().classes('h-36 w-full'):
                        with ui.column().classes('w-full gap-2 pr-1'):
                            for run in reversed(history[-5:]):
                                is_success = run.get('success', False)
                                border_color = 'border-violet-500/80' if is_success else 'border-rose-500/80'
                                border_bg = 'bg-violet-950/10' if is_success else 'bg-rose-950/10'

                                with ui.element('div').classes(f'w-full p-2.5 rounded-lg border border-slate-800/80 border-l-4 {border_color} {border_bg}'):
                                    with ui.row().classes('w-full items-center justify-between no-wrap'):
                                        with ui.column().classes('gap-0 overflow-hidden'):
                                            title = run.get('title', '자동 완성 쇼츠')[:14]
                                            ui.label(title).classes('text-xs text-white font-medium truncate')
                                            ui.label(run.get('timestamp', '')).classes('text-[9px] text-slate-500 font-mono')

                                        if is_success:
                                            ui.icon('check_circle', size='xs').classes('text-violet-400')
                                        else:
                                            ui.icon('error', size='xs').classes('text-rose-400')

                                    if run.get('video_path'):
                                        def play_history_video(path=run['video_path']):
                                            try:
                                                video_preview.set_source(path)
                                                video_preview.visible = True
                                                preview_placeholder.visible = False
                                            except Exception as err:
                                                logger.warning(f"Video set source failed: {err}")

                                        ui.button('재생하기', on_click=play_history_video).props('flat dense size=xs color=violet').classes('mt-1 text-[10px]')

                history_list()

        # =====================================================================
        # === 2. RIGHT PANEL: PROGRESS GRID & PREVIEW (가변폭) ===
        # =====================================================================
        with ui.column().classes('flex-grow h-full p-6 overflow-y-auto gap-5'):

            # --- 2A. Pipeline Milestone Progress Bar (진행 이정표) ---
            with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 p-5'):
                ui.label('실시간 단계별 진행도').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')

                # 4단계 밀착 리스트
                with ui.row().classes('w-full justify-between items-center bg-slate-950/40 rounded-xl border border-slate-800 p-4 gap-2'):
                    phases_info = [
                        ('planning', '기획 & 대본 작성', 'edit_note', 'violet', '대본 분석 및 씬 플래닝'),
                        ('generating', '미디어 클립 매핑', 'auto_fix_high', 'purple', 'Veo/Imagen 이미지 생성'),
                        ('editing', '인코딩 & 믹싱', 'movie_edit', 'indigo', '오디오 자막 및 BGM 병합'),
                        ('uploading', '최종 퍼블리싱', 'cloud_upload', 'rose', '유튜브 쇼츠 자동 업로드'),
                    ]

                    for idx, (phase_key, phase_name, phase_icon, phase_color, phase_desc) in enumerate(phases_info):
                        with ui.column().classes('items-start gap-1 flex-grow max-w-[200px]'):
                            with ui.row().classes('items-center gap-1.5'):
                                with ui.element('div').classes(f'w-6 h-6 rounded-full bg-{phase_color}-950/30 border border-{phase_color}-500/20 flex items-center justify-center'):
                                    ui.icon(phase_icon, size='xs').classes(f'text-{phase_color}-400')
                                ui.label(phase_name).classes('text-xs font-bold text-slate-300')

                            progress_bars[phase_key] = ui.linear_progress(value=0, show_value=False).props(f'color={phase_color} rounded size=4px').classes('w-full mt-1.5')

                            with ui.row().classes('w-full items-center justify-between text-[10px] text-slate-500 mt-1'):
                                phase_labels[phase_key] = ui.label('대기 중').classes('font-semibold')
                                phase_time_labels[phase_key] = ui.label('')

                        if idx < len(phases_info) - 1:
                            ui.element('div').classes('h-6 w-px bg-slate-800 shrink-0 self-center mx-2')

            # --- 2B. 격자 씬 미디어 상황판 (Scene Progress Grid) ---
            with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 p-5'):
                ui.label('각 씬별 미디어 생성 진행상황').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')

                scene_grid = ui.grid(columns='repeat(auto-fill, minmax(130px, 1fr))').classes('w-full gap-4')
                with scene_grid:
                    with ui.column().classes('w-full items-center justify-center col-span-full py-12'):
                        ui.icon('burst_mode', size='lg').classes('text-slate-800')
                        ui.label('대기 중').classes('text-sm font-bold text-slate-500')
                        ui.label('파이프라인이 기획 씬 분석을 통과하면 상황판이 격자 배열됩니다').classes('text-xs text-slate-600 mt-1')

            # --- 2C. 에러 알림 박스 (실패 시에만 보임) ---
            error_panel = ui.element('div').classes('w-full rounded-xl p-4 bg-rose-950/20 border border-rose-500/30 flex items-start gap-3 shadow-lg')
            error_panel.visible = False
            with error_panel:
                ui.icon('error_outline', size='sm').classes('text-rose-400 shrink-0 mt-0.5')
                with ui.column().classes('flex-grow gap-1'):
                    error_message_label = ui.label('실행 실패').classes('font-bold text-rose-300 text-xs')
                    error_details_label = ui.label('').classes('text-xs text-rose-200/80 leading-relaxed font-mono')

            # --- 2D. 최종 비디오 프리뷰어 모니터 ---
            with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 p-5'):
                ui.label('퍼블리싱 비디오 프리뷰어').classes('text-xs font-bold text-slate-400 uppercase tracking-widest mb-4')

                with ui.element('div').classes('w-full aspect-[16/9] md:aspect-[21/9] bg-black/80 rounded-xl overflow-hidden flex items-center justify-center relative border border-slate-950'):
                    # Placeholder
                    with ui.column().classes('items-center gap-2 z-10') as preview_placeholder:
                        ui.icon('videocam_off', size='lg').classes('text-slate-700')
                        ui.label('미리보기 없음').classes('text-xs font-bold text-slate-500')
                        ui.label('생성 프로세스 완료 시 여기에 믹싱된 영상이 노출됩니다').classes('text-[10px] text-slate-600')

                    # Video Player
                    video_preview = ui.video('').classes('max-h-full max-w-[200px] h-full shadow-2xl rounded bg-black')
                    video_preview.visible = False

                    if state.final_video_path:
                        try:
                            video_preview.set_source(state.final_video_path)
                            video_preview.visible = True
                            preview_placeholder.visible = False
                        except Exception:
                            pass
