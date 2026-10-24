"""YouTube Publishing 탭 컴포넌트"""

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.services.production_service import source_credited_description
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_publishing_tab(state: 'AppState') -> None:
    """YouTube Publishing 탭 렌더링"""

    with ui.column().classes('w-full max-w-2xl mx-auto mt-10'):
        with card_with_header('YouTube 비공개 업로드', 'cloud_upload', 'danger'):
            with ui.element('div').classes('w-full p-6'):
                # 입력 필드들
                title_input = ui.input('Video Title').props('outlined dark').classes('w-full mb-4')
                desc_input = ui.textarea('Description').props('outlined dark').classes('w-full h-32 mb-4')
                tags_input = ui.input('Tags (comma separated)').props('outlined dark').classes('w-full mb-6')
                ui.label('YouTube AI 사용 공개 선택 (필수)').classes('text-sm text-gray-300')
                synthetic_input = ui.radio({
                    'yes': '예: 실제처럼 보이는 AI 생성·변형 장면이 있음',
                    'no': '아니요: 그런 장면이 없음',
                }).props('color=red').classes('w-full mb-4')

                def load_metadata():
                    """스크립트에서 메타데이터 로드"""
                    if state.script:
                        title_input.value = state.script.title
                        desc_input.value = source_credited_description(
                            state.script.description, state.script.source_url)
                        tags_input.value = ",".join(state.script.tags)
                    else:
                        safe_notify("No script loaded", type='warning')

                ui.button(
                    'Load Metadata from Script',
                    on_click=load_metadata
                ).props('flat color=white icon=download').classes('mb-4')

                async def upload_video():
                    """YouTube에 비디오 업로드"""
                    if state.youtube_upload_in_progress:
                        return
                    if not state.final_video_path:
                        safe_notify("No video to upload", type='warning')
                        return
                    if not (title_input.value or '').strip():
                        safe_notify('영상 제목을 입력하세요', type='warning')
                        return
                    if synthetic_input.value not in ('yes', 'no'):
                        safe_notify('AI 사용 공개 여부를 선택하세요', type='warning')
                        return

                    state.youtube_upload_in_progress = True
                    upload_btn.disable()
                    safe_notify("Uploading...", type='info')

                    try:
                        meta = {
                            "title": title_input.value.strip(),
                            "description": desc_input.value or '',
                            "tags": [t.strip() for t in (tags_input.value or '').split(',') if t.strip()],
                            "contains_synthetic_media": synthetic_input.value == 'yes',
                        }

                        service = state.get_or_create_service()
                        result = await service.upload_to_youtube(state.final_video_path, meta)
                        vid_id = result.youtube_id

                        if vid_id:
                            safe_notify(f"{service.progress.message} (ID: {vid_id})", type='positive')
                            logger.info(f"Upload success: https://youtube.com/shorts/{vid_id}")
                        else:
                            safe_notify(f"Upload failed: {result.error or 'unknown error'}", type='negative')

                    except Exception as e:
                        safe_notify(f"Error: {e}", type='negative')
                        logger.error(f"Upload error: {e}")
                    finally:
                        state.youtube_upload_in_progress = False
                        if state.final_video_path:
                            try:
                                upload_btn.enable()
                            except RuntimeError:
                                pass

                # 영상 경로 표시
                with ui.row().classes('w-full items-center gap-2 mb-4 p-3 rounded-lg bg-slate-900/60 border border-slate-700'):
                    ui.icon('movie', size='xs').classes('text-gray-500')
                    video_path_label = ui.label(
                        state.final_video_path or '영상 없음 — Pipeline 또는 Generation 탭에서 먼저 생성하세요'
                    ).classes('text-xs text-gray-400 truncate flex-grow')
                    video_path_label.bind_text_from(
                        state, 'final_video_path',
                        backward=lambda p: p if p else '영상 없음 — Pipeline 또는 Generation 탭에서 먼저 생성하세요'
                    )

                preview = ui.video(state.final_video_path or '').classes('w-full max-w-[270px] max-h-[480px] mb-4 bg-black')
                preview.bind_source_from(state, 'final_video_path', backward=lambda p: p or '')
                preview.bind_visibility_from(state, 'final_video_path', backward=bool)
                ui.label('완성본을 확인한 뒤 업로드하세요. YouTube에는 비공개로 저장됩니다.').classes('text-sm text-gray-300 mb-4')

                upload_btn = ui.button(
                    'YouTube에 비공개 업로드',
                    on_click=upload_video
                ).classes('w-full').props('color=red unelevated size=lg icon=cloud_upload')
                upload_btn.bind_enabled_from(state, 'final_video_path', backward=lambda p: bool(p) and not state.youtube_upload_in_progress)

        # 업로드 상태 정보
        with ui.card().classes('w-full p-4 bg-slate-800 border border-slate-700 mt-4'):
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('info', size='xs').classes('text-blue-400')
                ui.label('Upload Requirements').classes('text-sm font-bold text-blue-300')

            with ui.column().classes('gap-2'):
                ui.label('• YouTube OAuth credentials required (client_secrets.json)').classes('text-xs text-gray-400')
                ui.label('• Video must be generated first in Pipeline or Generation tab').classes('text-xs text-gray-400')
                ui.label('• Current ShortsMaker production limit: 59 seconds').classes('text-xs text-gray-400')
