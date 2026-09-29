"""Video Generation 탭 컴포넌트 - Google AI Studio 스타일 중앙 융합 개편"""
import asyncio
from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress
from shorts_maker.gui.components.common.progress_utils import update_scene_grid
from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)

SCENE_ACCENT = [
    ('from-violet-600', 'to-indigo-600', 'border-violet-500/30', 'bg-violet-950/20', 'text-violet-300'),
    ('from-indigo-600', 'to-blue-600', 'border-indigo-500/30', 'bg-indigo-950/20', 'text-indigo-300'),
    ('from-purple-600', 'to-pink-600', 'border-purple-500/30', 'bg-purple-950/20', 'text-purple-300'),
    ('from-teal-600', 'to-emerald-600', 'border-teal-500/30', 'bg-teal-950/20', 'text-teal-300'),
    ('from-fuchsia-600', 'to-rose-600', 'border-fuchsia-500/30', 'bg-fuchsia-950/20', 'text-fuchsia-300'),
]


def render_manual_panel(state: 'AppState', exporter: VeoPromptExporter,
                        start_edit_btn: ui.button,
                        scene_cards_container: ui.element) -> None:
    """수동 모드 격자 그리드 씬 업로드 패널 렌더링"""
    try:
        scene_cards_container.clear()
    except RuntimeError:
        return

    # 스크립트 없을 때 처리
    if not state.script:
        start_edit_btn.disable()
        with scene_cards_container:
            with ui.element('div').classes('w-full h-96 flex items-center justify-center col-span-full'):
                with ui.column().classes('items-center gap-4'):
                    ui.icon('description', size='xl').classes('text-slate-600')
                    ui.label('각본을 먼저 로드해주세요').classes('text-lg font-bold text-slate-400')
                    ui.label('왼쪽 메뉴의 Studio -> 1. Script & Prompt Editor 에서 각본을 생성해주세요.').classes('text-xs text-slate-500')
        return

    if not state.manual_script_id:
        state.manual_script_id = exporter.get_script_id(state.script)

    scenes_status = exporter.get_scenes_status(state.script, state.manual_script_id)
    ready_count = sum(1 for s in scenes_status if s["exists"])
    total = len(scenes_status)
    if total and ready_count == total:
        start_edit_btn.enable()
    else:
        start_edit_btn.disable()

    with scene_cards_container:
        # ── 상단 진행 정보 (Grid의 가로 한 줄 전체 차지) ──
        with ui.element('div').classes('col-span-full w-full rounded-xl bg-slate-900 border border-slate-800 p-5 mb-2'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('video_library', size='sm').classes('text-violet-400')
                    ui.label('수동 소스 매핑 및 영상 수집').classes('text-base font-bold text-white')

                # 진행도 표시 뱃지
                progress_badge_cls = 'bg-violet-600 text-white font-bold px-3 py-1 rounded-full text-xs' \
                    if ready_count == total else 'bg-slate-800 text-slate-400 font-bold px-3 py-1 rounded-full text-xs border border-slate-700'
                ui.badge(f'{ready_count} / {total} 씬 업로드 완료').classes(progress_badge_cls)

            # 전체 진행 바
            with ui.element('div').classes('w-full h-2 rounded-full bg-slate-800 overflow-hidden mb-4'):
                pct = int(ready_count / max(total, 1) * 100)
                bar_color = 'bg-gradient-to-r from-violet-600 to-indigo-600' if ready_count == total else 'bg-violet-600'
                ui.element('div').classes(f'h-full rounded-full {bar_color} transition-all').style(f'width: {pct}%')

            # 안내 가이드 및 일괄 다운로드/복사 도구
            with ui.row().classes('w-full items-stretch gap-4'):
                with ui.element('div').classes('flex-grow rounded-lg bg-violet-950/20 border border-violet-500/20 p-3 flex items-start gap-2'):
                    ui.icon('info', size='xs').classes('text-violet-400 mt-0.5 shrink-0')
                    ui.label('각 씬의 프롬프트를 복사하여 Veo 3.1이나 외부 AI Studio에서 생성한 후, 씬 카드 내에 업로드해주십시오. 모든 씬 영상이 로드되면 인코딩 및 자막 믹싱을 시작할 수 있습니다.').classes('text-xs text-slate-300 leading-relaxed')

                with ui.column().classes('justify-center gap-2 min-w-[240px] border-l border-slate-800 pl-4'):
                    def copy_all_json():
                        json_str = exporter.export_json(state.script, state.manual_script_id)
                        ui.run_javascript(f'navigator.clipboard.writeText({repr(json_str)})')
                        safe_notify('전체 프롬프트 JSON이 클립보드에 복사되었습니다.', type='positive')

                    ui.button(
                        '전체 프롬프트 JSON 복사',
                        icon='content_copy',
                        on_click=copy_all_json
                    ).classes('w-full py-1 text-xs').props('outline color=violet dense size=sm')

        # ── 씬별 카드 (Grid 구조로 각 씬이 격자 배치됨) ──
        for idx, scene_info in enumerate(scenes_status):
            scene_num = scene_info["scene_number"]
            exists = scene_info["exists"]
            prompt = scene_info["prompt"]
            script_text = scene_info["script_text"]

            from_c, to_c, border_c, bg_c, label_c = SCENE_ACCENT[idx % len(SCENE_ACCENT)]
            card_border = 'border-violet-500/50' if exists else 'border-slate-800 hover:border-slate-700'
            card_bg = 'bg-slate-900/80 shadow-md' if exists else 'bg-slate-900/40 hover:bg-slate-900/60'

            with ui.element('div').classes(f'rounded-xl border {card_border} {card_bg} overflow-hidden flex flex-col justify-between transition-all duration-300'):

                # 씬 헤더
                with ui.element('div').classes(f'w-full px-4 py-2.5 bg-gradient-to-r {from_c} {to_c} opacity-90 flex items-center justify-between shrink-0'):
                    with ui.row().classes('items-center gap-2'):
                        with ui.element('div').classes('w-6 h-6 rounded bg-white/20 flex items-center justify-center'):
                            ui.label(str(scene_num)).classes('text-xs font-bold text-white')
                        ui.label(f'씬 {scene_num}').classes('text-xs font-bold text-white')

                    if exists:
                        with ui.row().classes('items-center gap-1 bg-white/20 rounded-full px-2 py-0.5'):
                            ui.icon('check', size='xs').classes('text-white')
                            ui.label('완료').classes('text-[10px] text-white font-semibold')
                    else:
                        ui.label('대기').classes('text-[10px] text-white/70 font-semibold bg-white/10 px-2 py-0.5 rounded-full')

                # 카드 바디
                with ui.column().classes('p-4 gap-3 flex-grow'):
                    # 1. 오디오 자막 (내레이션)
                    with ui.column().classes('w-full gap-1'):
                        ui.label('나레이션').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')
                        with ui.element('div').classes('w-full rounded-lg bg-slate-950/60 border border-slate-800/80 px-3 py-2 min-h-[50px]'):
                            ui.label(script_text).classes('text-xs text-slate-300 leading-relaxed italic')

                    # 2. 비주얼 프롬프트 복사
                    with ui.column().classes('w-full gap-1'):
                        ui.label('비주얼 프롬프트').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')
                        with ui.element('div').classes('w-full rounded-lg bg-slate-950/80 border border-slate-800 p-2.5 min-h-[60px] max-h-[100px] overflow-y-auto font-mono'):
                            ui.label(prompt).classes('text-[11px] text-slate-400 leading-normal')

                        def make_copy_fn(p=prompt, sn=scene_num):
                            def copy_prompt():
                                ui.run_javascript(f'navigator.clipboard.writeText({repr(p)})')
                                safe_notify(f'씬 {sn} 프롬프트 복사 완료!', type='info')
                            return copy_prompt

                        ui.button(
                            '프롬프트 복사',
                            icon='content_copy',
                            on_click=make_copy_fn()
                        ).classes('w-full py-0.5 text-xs mt-1').props('flat dense color=violet size=xs')

                    # 3. 비디오 클립 업로드
                    with ui.column().classes('w-full gap-1 mt-1'):
                        ui.label('비디오 파일 매핑').classes('text-[10px] text-slate-500 font-bold uppercase tracking-wider')

                        # 업로드 완료된 클립명 표시
                        if exists:
                            clip_name = scene_info["clip_path"].split('/')[-1]
                            with ui.element('div').classes('w-full rounded-lg bg-violet-950/20 border border-violet-500/20 px-2 py-1.5 flex items-center justify-between mb-1.5'):
                                with ui.row().classes('items-center gap-1.5 overflow-hidden'):
                                    ui.icon('video_file', size='xs').classes('text-violet-400 shrink-0')
                                    ui.label(clip_name).classes('text-[11px] text-violet-300 truncate max-w-[180px]')
                                ui.icon('check_circle', size='xs').classes('text-violet-400')

                        # 업로드 컴포넌트
                        def make_upload_handler(sn=scene_num):
                            async def handle_upload(e):
                                try:
                                    file_bytes = await e.file.read()
                                    exporter.save_uploaded_clip(
                                        file_bytes, state.manual_script_id, sn
                                    )

                                    safe_notify(f'씬 {sn} 비디오 클립 업로드 완료!', type='positive')

                                    # 전체 패널 다시 그리기
                                    render_manual_panel(state, exporter, start_edit_btn, scene_cards_container)
                                    if exporter.all_clips_ready(state.script, state.manual_script_id):
                                        safe_notify('🎉 모든 씬의 영상 매핑 완료! 상단의 [편집 및 자막 믹싱 시작]을 실행하십시오.', type='positive')
                                except Exception as err:
                                    safe_notify(f'업로드 실패: {err}', type='negative')
                                    logger.error(f'씬 {sn} 수동 로드 오류: {err}')
                            return handle_upload

                        ui.upload(
                            on_upload=make_upload_handler(),
                            auto_upload=True,
                            max_file_size=500_000_000,
                        ).props('accept=".mp4,.mov,.webm" flat color=violet dense label="비디오 선택 (mp4, mov)"').classes('w-full border border-dashed border-slate-700 rounded-lg hover:border-violet-500/50 bg-slate-950/20 py-1')


def render_generation_tab(state: 'AppState') -> None:
    """Google AI Studio 스타일의 리팩토링된 Generation 탭 렌더링"""
    exporter = VeoPromptExporter()

    # 세션 뷰에 필요한 헬퍼
    phase_labels = {}
    phases = ['ready', 'visuals', 'editing', 'complete']

    def update_progress_ui(phase: str, progress: float, message: str = ""):
        try:
            for p, label in phase_labels.items():
                if p == phase:
                    label.classes(replace='text-violet-400 font-bold')
                elif phases.index(p) < phases.index(phase):
                    label.classes(replace='text-emerald-400')
                else:
                    label.classes(replace='text-slate-600')
        except (ValueError, RuntimeError) as e:
            logger.debug(f"Progress UI sync skipped: {e}")

    # 전체를 아우르는 반응형 컬럼 구조
    with ui.column().classes('w-full h-full gap-0 overflow-hidden bg-slate-950'):

        # ── 1. TOP PIPELINE ACTION BAR ──
        with ui.element('div').classes('w-full px-6 py-4 bg-slate-900 border-b border-slate-800 flex items-center justify-between shrink-0 gap-4'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('smart_display', size='sm').classes('text-violet-400')
                with ui.column().classes('gap-0'):
                    ui.label('영상 프로덕션 모니터').classes('text-sm font-bold text-white')
                    source_label = '수동 업로드 모드' if state.manual_video_mode else 'Vertex AI API 자동 생성 모드'
                    ui.label(f'Status: {source_label}').classes('text-[11px] text-slate-400 mt-0.5')

            # 파이프라인 진행 상태 (자동 / 수동 겸용 액션 바)
            with ui.row().classes('items-center gap-4'):

                # 수동 모드 전용 편집 시작 버튼
                async def run_manual_production():
                    clip_paths = (
                        exporter.get_ready_clip_paths(state.script, state.manual_script_id)
                        if state.script else None
                    )
                    if not clip_paths:
                        safe_notify('먼저 아래 격자 패널에서 모든 씬의 영상을 업로드해주십시오.', type='warning')
                        return
                    await run_production_with_clips(clip_paths)

                manual_btn = ui.button(
                    '편집 및 자막 믹싱 시작',
                    on_click=run_manual_production
                ).classes('px-4 py-1.5 font-bold text-xs').props('color=violet unelevated size=sm icon=movie_edit')
                manual_btn.visible = state.manual_video_mode

                # 자동 모드 전용 Start Production 버튼
                async def run_production_with_notification():
                    if not state.script:
                        safe_notify('로드된 각본이 없습니다. 스크립트 작성 후 실행해주십시오.', type='warning')
                        return
                    ui.notify('🎬 비디오 자동 생성을 구동합니다. Vertex AI 비용 모니터링을 진행하십시오...', type='info')
                    await run_production()

                auto_btn = ui.button(
                    'Start Production',
                    on_click=run_production_with_notification
                ).classes('px-4 py-1.5 font-bold text-xs bg-gradient-to-r from-violet-600 to-indigo-600').props('color=violet unelevated size=sm icon=rocket_launch')
                auto_btn.visible = not state.manual_video_mode

                # 상태 인디케이터 스피너
                gen_spinner = ui.spinner(size='sm').props('color=violet').classes('my-1')
                gen_spinner.visible = False

        # ── 2. MAIN PRODUCTION WORKSPACE ──
        with ui.row().classes('w-full flex-grow overflow-hidden no-wrap gap-0'):

            # --- 2A. LEFT SIDE: WIDE PREVIEW MONITOR (자동 모드 시 메인, 수동 모드 시 숨김/작게) ---
            # 자동 모드와 수동 모드 모두의 통합 뷰어
            with ui.column().classes('flex-grow h-full p-6 overflow-y-auto gap-5') as main_workspace_area:

                # ── 대형 프리뷰 모니터 카드 (자동 생성 시 혹은 수동 편집 완료 시 띄움) ──
                with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 overflow-hidden flex flex-col shadow-xl') as preview_monitor_card:
                    # 모니터 타이틀 바
                    with ui.element('div').classes('w-full bg-slate-900/90 border-b border-slate-800 px-4 py-2.5 flex items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.element('div').classes('w-2 h-2 rounded-full bg-rose-500 animate-pulse')
                            ui.label('Premium Preview Monitor').classes('text-xs font-bold text-slate-300 font-mono')

                        # 해상도 정보 등 뱃지
                        ui.badge('9:16 Vertical Shorts').classes('bg-slate-800 text-slate-400 text-[10px] px-2 py-0.5 border border-slate-700')

                    # 모니터 콘텐츠 본체
                    with ui.element('div').classes('w-full h-[360px] flex items-center justify-center bg-black/80 relative overflow-hidden'):
                        video_player = None
                        placeholder_content = None

                        # Gemini 풍의 유려한 그라데이션 광채 플레이스홀더
                        with ui.column().classes('items-center gap-3 z-10 p-6 text-center') as placeholder_content:
                            ui.icon('smart_display', size='lg').classes('text-violet-500/70')
                            ui.label('Shorts Preview Area').classes('text-sm font-bold text-slate-300')
                            ui.label('우측 패널에서 Veo 3.1 / Imagen 3 설정을 조정한 뒤, 상단의 생성을 구동하면 여기에 프리뷰가 재생됩니다.').classes('text-xs text-slate-500 max-w-md leading-relaxed')

                            # 만약 API 요금 절감을 원할 시 수동 모드로 돌릴 것을 추천하는 뱃지
                            with ui.row().classes('items-center gap-1.5 mt-2 bg-violet-950/30 rounded-lg border border-violet-500/20 px-3 py-1.5'):
                                ui.icon('offline_bolt', size='xs').classes('text-violet-400')
                            ui.label('API 비용 없이 제작하려면 Local File로 전환하고 씬별 영상을 업로드하세요.').classes('text-[10px] text-violet-300')

                        # 실제 비디오 컴포넌트 (종횡비 9:16 대응)
                        video_player = ui.video('').classes('max-h-full max-w-[200px] h-full shadow-lg border border-slate-800 rounded bg-slate-950')
                        video_player.visible = False

                        if state.final_video_path:
                            video_player.set_source(state.final_video_path)
                            video_player.visible = True
                            placeholder_content.visible = False

                # ── 파이프라인 진행 상태 모니터 ──
                with ui.element('div').classes('w-full rounded-xl bg-slate-900 border border-slate-800 p-5') as pipeline_status_card:
                    with ui.row().classes('w-full items-center justify-between mb-4'):
                        ui.label('파이프라인 진행 이력').classes('text-xs font-bold text-slate-400 uppercase tracking-widest')
                        ui.label().bind_text_from(state, 'pipeline_message').classes('text-xs text-violet-400 font-semibold')

                    # 파이프라인 단계 로드바
                    with ui.row().classes('w-full justify-between items-center bg-slate-950/60 rounded-xl border border-slate-800/80 p-4 mb-4'):
                        step_configs = [
                            ('ready', 'hourglass_empty', 'Ready'),
                            ('visuals', 'auto_awesome', 'Veo Visuals'),
                            ('editing', 'movie_edit', 'FFmpeg Editing'),
                            ('complete', 'check_circle', 'Finished')
                        ]
                        for i, (phase_id, icon, label_text) in enumerate(step_configs):
                            with ui.column().classes('items-center gap-1.5 flex-grow'):
                                icon_class = 'text-violet-400' if i == 0 else 'text-slate-600'
                                with ui.element('div').classes('w-9 h-9 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center transition-all duration-300'):
                                    ui.icon(icon, size='xs').classes(icon_class)
                                phase_labels[phase_id] = ui.label(label_text).classes('text-[10px] text-slate-500 font-semibold uppercase tracking-wider')

                            if i < len(step_configs) - 1:
                                ui.element('div').classes('h-px bg-slate-800 flex-grow max-w-[60px] mb-5')

                    # 실시간 생성 씬 격자 모니터 (비디오 생성 상태 확인)
                    scene_progress_container = ui.column().classes('w-full gap-2 mt-2')
                    scene_progress_container.visible = False

            # --- 2B. RIGHT SIDE: SCENE MANUAL GRID UPLOADER (수동 모드 시 화면 가득 활성화) ---
            with ui.scroll_area().classes('flex-grow h-full bg-slate-950') as manual_uploader_area:
                scene_cards_container = ui.grid(columns='repeat(auto-fill, minmax(320px, 1fr))').classes('w-full gap-4 p-6')

        # ── 3. VISIBILITY SWITCHING LOGIC ──
        def sync_layout_visibility():
            """수동/자동 모드 설정값에 따른 가시성 조율"""
            try:
                # 자동 모드는 프리뷰, 수동 모드는 업로더를 표시
                main_workspace_area.visible = not state.manual_video_mode
                manual_uploader_area.visible = state.manual_video_mode

                auto_btn.visible = not state.manual_video_mode
                manual_btn.visible = state.manual_video_mode

                if state.manual_video_mode:
                    render_manual_panel(state, exporter, manual_btn, scene_cards_container)
            except RuntimeError:
                pass

        # 초기 동기화
        sync_layout_visibility()

        # ── 4. EVENT HANDLERS CORE (동적 렌더러 연동) ──
        async def _run_production_core(manual_clip_paths=None):
            nonlocal video_player, placeholder_content
            production_running = True

            try:
                gen_spinner.visible = True
                scene_progress_container.visible = True
                scene_progress_container.clear()
            except RuntimeError:
                return

            try:
                # 상태 초기화
                state.reset_pipeline()

                char_config = state.build_character_overlay_config()
                service = ProductionService(
                    mode=state.mode,
                    character_overlay_config=char_config
                )

                def on_progress(progress: ProductionProgress):
                    state.sync_from_progress(progress)

                service.set_progress_callback(on_progress)

                async def monitor_progress():
                    while production_running:
                        progress = service.progress
                        try:
                            update_scene_grid(progress.scene_progresses, scene_progress_container)
                        except RuntimeError:
                            pass
                        try:
                            phase_map = {
                                ProductionPhase.GENERATING: 'visuals',
                                ProductionPhase.EDITING: 'editing',
                                ProductionPhase.COMPLETED: 'complete'
                            }
                            if progress.phase in phase_map:
                                update_progress_ui(phase_map[progress.phase], progress.progress_percent)
                        except (RuntimeError, KeyError):
                            pass
                        if progress.phase in [ProductionPhase.COMPLETED, ProductionPhase.FAILED]:
                            break
                        await asyncio.sleep(0.3)

                monitor_task = asyncio.create_task(monitor_progress())

                logger.info("=== Production Pipeline Execution Triggered ===")
                result = await service.produce_video(
                    state.script,
                    manual_clip_paths=manual_clip_paths
                )

                production_running = False
                await monitor_task

                if result.success:
                    state.final_video_path = result.video_path
                    state.generated_clips = result.clips
                    update_progress_ui('complete', 100)
                    safe_notify("🎉 영상 편집 및 프로덕션 완료!", type='positive')

                    if video_player and state.final_video_path:
                        try:
                            # 믹싱 성공 시 항상 프리뷰 모니터 영역으로 유도하여 재생
                            state.manual_video_mode = False
                            sync_layout_visibility()

                            video_player.set_source(state.final_video_path)
                            video_player.visible = True
                            if placeholder_content:
                                placeholder_content.visible = False
                        except RuntimeError:
                            pass
                    logger.info(f"Final output video available at: {state.final_video_path}")
                else:
                    safe_notify(f"프로덕션 실패: {result.error}", type='negative')
                    logger.error(f"Production Failed: {result.error}")

            except Exception as e:
                safe_notify(f"실행 도중 오류 발생: {e}", type='negative')
                logger.error(f"Production Error Event: {e}")
            finally:
                production_running = False
                try:
                    gen_spinner.visible = False
                except RuntimeError:
                    pass

        async def run_production():
            if not state.script:
                safe_notify("각본을 먼저 생성/로드해주십시오.", type='warning')
                return
            await _run_production_core(manual_clip_paths=None)

        async def run_production_with_clips(clips: dict):
            if not state.script:
                safe_notify("각본을 먼저 로드해주십시오.", type='warning')
                return
            await _run_production_core(manual_clip_paths=clips)

        # 우측 설정 패널에서 모드가 바뀌면 현재 탭의 레이아웃을 갱신합니다.
        def check_mode_and_sync():
            """글로벌 State의 manual_video_mode와 본 탭 레이아웃 상태를 유기적으로 감지 및 매핑"""
            try:
                # 상태가 불일치 시 UI 토글 동기화
                is_manual = state.manual_video_mode
                if is_manual != manual_uploader_area.visible:
                    sync_layout_visibility()
            except RuntimeError:
                pass

        # 1초 주기로 글로벌 모드 변경 감지 및 반응형 레이아웃 갱신
        ui.timer(1.0, check_mode_and_sync)
