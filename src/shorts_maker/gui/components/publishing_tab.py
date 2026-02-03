"""YouTube Publishing 탭 컴포넌트"""

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def render_publishing_tab(state: 'AppState') -> None:
    """YouTube Publishing 탭 렌더링"""

    with ui.column().classes('w-full max-w-2xl mx-auto mt-10'):
        with card_with_header('YouTube Upload', 'cloud_upload', 'danger'):
            with ui.element('div').classes('p-6'):
                # 입력 필드들
                title_input = ui.input('Video Title').props('outlined dark').classes('w-full mb-4')
                desc_input = ui.textarea('Description').props('outlined dark').classes('w-full h-32 mb-4')
                tags_input = ui.input('Tags (comma separated)').props('outlined dark').classes('w-full mb-6')

                def load_metadata():
                    """스크립트에서 메타데이터 로드"""
                    if state.script:
                        title_input.value = state.script.title
                        desc_input.value = state.script.description
                        tags_input.value = ",".join(state.script.tags)
                    else:
                        safe_notify("No script loaded", type='warning')

                ui.button(
                    'Load Metadata from Script',
                    on_click=load_metadata
                ).props('flat color=white icon=download').classes('mb-4')

                async def upload_video():
                    """YouTube에 비디오 업로드"""
                    if not state.final_video_path:
                        safe_notify("No video to upload", type='warning')
                        return

                    safe_notify("Uploading...", type='info')

                    try:
                        from shorts_maker.uploader.youtube_uploader import YouTubeUploader

                        uploader = YouTubeUploader()
                        meta = {
                            "title": title_input.value,
                            "description": desc_input.value,
                            "tags": [t.strip() for t in tags_input.value.split(',')]
                        }

                        vid_id = await uploader.upload(state.final_video_path, meta)

                        if vid_id:
                            safe_notify(f"Uploaded! ID: {vid_id}", type='positive')
                            logger.info(f"Upload success: https://youtube.com/shorts/{vid_id}")
                        else:
                            safe_notify("Upload failed", type='negative')

                    except Exception as e:
                        safe_notify(f"Error: {e}", type='negative')
                        logger.error(f"Upload error: {e}")

                ui.button(
                    'Upload to YouTube',
                    on_click=upload_video
                ).classes('w-full').props('color=red unelevated size=lg icon=cloud_upload')

        # 업로드 상태 정보
        with ui.card().classes('w-full p-4 bg-slate-800 border border-slate-700 mt-4'):
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('info', size='xs').classes('text-blue-400')
                ui.label('Upload Requirements').classes('text-sm font-bold text-blue-300')

            with ui.column().classes('gap-2'):
                ui.label('• YouTube OAuth credentials required (service_account.json)').classes('text-xs text-gray-400')
                ui.label('• Video must be generated first in Pipeline or Generation tab').classes('text-xs text-gray-400')
                ui.label('• Max duration for Shorts: 60 seconds').classes('text-xs text-gray-400')
