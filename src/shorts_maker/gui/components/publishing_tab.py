"""YouTube Publishing 탭 컴포넌트"""

import hashlib
import json
import re
from pathlib import Path

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.services.production_service import source_credited_description, script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def _completed_outputs() -> dict[str, str]:
    outputs = {}
    for path in sorted(settings.output_dir.glob('*.production.json'), reverse=True):
        try:
            if not path.resolve().is_relative_to(settings.output_dir.resolve()):
                continue
            report = json.loads(path.read_text(encoding='utf-8'))
            video = Path(report['video_path']).resolve()
            if (report.get('quality_passed') is True and video.is_file()
                    and video.suffix.lower() == '.mp4'
                    and video.is_relative_to(settings.output_dir.resolve())):
                outputs[str(video)] = f"{report.get('title') or video.stem} · {video.name}"
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return outputs


def _completed_video(path: str) -> dict:
    video = Path(path).resolve()
    root = settings.output_dir.resolve()
    report_path = video.with_suffix('.production.json').resolve()
    if (not video.is_file() or video.suffix.lower() != '.mp4'
            or not video.is_relative_to(root) or not report_path.is_relative_to(root)):
        raise ValueError('출력 폴더 안의 완성 MP4를 선택하세요.')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    with video.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    if (not isinstance(report, dict) or report.get('schema_version') != 1
            or report.get('video_path') != str(video)
            or report.get('quality_passed') is not True or report.get('video_sha256') != digest):
        raise ValueError('영상과 일치하는 품질 통과 기록·파일 해시가 필요합니다.')
    return report


def _load_completed_video(state: 'AppState', path: str) -> dict:
    if state.is_busy:
        raise ValueError('진행 중인 제작·업로드가 끝난 뒤 완성본을 바꾸세요.')
    report = _completed_video(path)
    state.final_video_path = report['video_path']
    return report


def render_publishing_tab(state: 'AppState') -> None:
    """YouTube Publishing 탭 렌더링"""

    with ui.column().classes('w-full max-w-2xl mx-auto mt-10'):
        with card_with_header('YouTube 비공개 업로드', 'cloud_upload', 'danger'):
            with ui.element('div').classes('w-full p-6'):
                outputs = _completed_outputs()
                saved_video = ui.select(
                    outputs, label='저장된 완성본',
                    value=state.final_video_path if state.final_video_path in outputs else None,
                ).props('outlined dark').classes('w-full mb-2')
                saved_video.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                def refresh_outputs():
                    saved_video.options = _completed_outputs()
                    if saved_video.value not in saved_video.options:
                        saved_video.value = None
                    saved_video.update()

                def load_saved_video():
                    if not saved_video.value:
                        safe_notify('불러올 완성본을 선택하세요.', type='warning')
                        return
                    try:
                        report = _load_completed_video(state, saved_video.value)
                    except (OSError, ValueError, TypeError) as error:
                        safe_notify(f'완성본 불러오기 실패: {error}', type='negative')
                        return
                    request = report.get('youtube_upload_request') or {}
                    snippet = request.get('snippet', {}) if isinstance(request, dict) else {}
                    snippet = snippet if isinstance(snippet, dict) else {}
                    title = snippet.get('title') or report.get('title')
                    title_input.value = title if isinstance(title, str) else Path(state.final_video_path).stem
                    description = snippet.get('description')
                    source = report.get('source_url')
                    desc_input.value = description if isinstance(description, str) else ('출처: ' + source if isinstance(source, str) else '')
                    tags = snippet.get('tags', [])
                    tags_input.value = ','.join(tag for tag in tags if isinstance(tag, str)) if isinstance(tags, list) else ''
                    disclosure = report.get('contains_synthetic_media')
                    synthetic_input.value = ('yes' if disclosure else 'no') if isinstance(disclosure, bool) else None
                    uploaded_review.refresh()
                    safe_notify('완성본을 불러왔습니다. 영상과 게시 정보를 확인하세요.', type='positive')

                with ui.row().classes('w-full gap-2 mb-4'):
                    ui.button('완성본 불러오기', on_click=load_saved_video).props('flat icon=folder_open').bind_enabled_from(
                        state, 'is_busy', backward=lambda busy: not busy)
                    ui.button('목록 새로고침', on_click=refresh_outputs).props('flat icon=refresh')
                ui.label('재제작 없이 저장된 영상을 열 수 있습니다. 불러올 때 품질 기록과 파일 해시를 확인합니다.').classes(
                    'text-xs text-gray-400 mb-4')

                # 입력 필드들
                title_input = ui.input('영상 제목').props('outlined dark').classes('w-full mb-4')
                desc_input = ui.textarea('영상 설명·출처').props('outlined dark').classes('w-full h-32 mb-4')
                tags_input = ui.input('태그 (쉼표로 구분)').props('outlined dark').classes('w-full mb-6')
                ui.label('YouTube AI 사용 공개 선택 (필수)').classes('text-sm text-gray-300')
                synthetic_input = ui.radio({
                    'yes': '예: 실제처럼 보이는 AI 생성·변형 장면이 있음',
                    'no': '아니요: 그런 장면이 없음',
                }).props('color=red').classes('w-full mb-4')
                for control in (title_input, desc_input, tags_input, synthetic_input):
                    control.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)

                def load_metadata():
                    """스크립트에서 메타데이터 로드"""
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 게시 정보를 바꾸세요.', type='warning')
                        return
                    if state.script:
                        if state.final_video_path:
                            try:
                                report = _completed_video(state.final_video_path)
                                if report.get('script_sha256') != script_sha256(state.script.model_dump(mode='json')):
                                    raise ValueError('선택한 완성본과 현재 각본이 다릅니다. 완성본의 게시 정보를 사용하세요.')
                            except (OSError, ValueError, TypeError) as error:
                                safe_notify(str(error), type='warning')
                                return
                        title_input.value = state.script.title
                        desc_input.value = source_credited_description(
                            state.script.description, state.script.source_url,
                            getattr(state.script, 'supporting_source_urls', []))
                        tags_input.value = ",".join(state.script.tags)
                    else:
                        safe_notify('불러온 각본이 없습니다.', type='warning')

                ui.button(
                    '각본에서 게시 정보 가져오기',
                    on_click=load_metadata
                ).props('flat color=white icon=download').classes('mb-4')

                async def upload_video():
                    """YouTube에 비디오 업로드"""
                    if state.is_busy:
                        return
                    if not state.final_video_path:
                        safe_notify('업로드할 완성본을 먼저 불러오세요.', type='warning')
                        return
                    if not (title_input.value or '').strip():
                        safe_notify('영상 제목을 입력하세요', type='warning')
                        return
                    if synthetic_input.value not in ('yes', 'no'):
                        safe_notify('AI 사용 공개 여부를 선택하세요', type='warning')
                        return

                    try:
                        service = state.get_or_create_service()
                        state.youtube_upload_in_progress = True
                        safe_notify('YouTube에 비공개로 업로드 중입니다.', type='info')
                        meta = {
                            "title": title_input.value.strip(),
                            "description": desc_input.value or '',
                            "tags": [t.strip() for t in (tags_input.value or '').split(',') if t.strip()],
                            "contains_synthetic_media": synthetic_input.value == 'yes',
                        }

                        result = await service.upload_to_youtube(state.final_video_path, meta)
                        vid_id = result.youtube_id

                        if vid_id:
                            safe_notify(f"{service.progress.message} (ID: {vid_id})", type='positive')
                            logger.info(f"Upload success: https://youtube.com/shorts/{vid_id}")
                            uploaded_review.refresh()
                        else:
                            safe_notify(f"업로드 실패: {result.error or '결과를 확인할 수 없습니다'}", type='negative')

                    except Exception as e:
                        safe_notify(f'업로드 오류: {e}', type='negative')
                        logger.error(f"Upload error: {e}")
                    finally:
                        state.youtube_upload_in_progress = False

                # 영상 경로 표시
                with ui.row().classes('w-full items-center gap-2 mb-4 p-3 rounded-lg bg-slate-900/60 border border-slate-700'):
                    ui.icon('movie', size='xs').classes('text-gray-500')
                    video_path_label = ui.label(
                        state.final_video_path or '영상 없음 — 저장된 완성본을 불러오거나 제작 화면에서 영상을 만드세요'
                    ).classes('text-xs text-gray-400 truncate flex-grow')
                    video_path_label.bind_text_from(
                        state, 'final_video_path',
                        backward=lambda p: p if p else '영상 없음 — 저장된 완성본을 불러오거나 제작 화면에서 영상을 만드세요'
                    )

                preview = ui.video(state.final_video_path or '').classes('w-full max-w-[270px] max-h-[480px] mb-4 bg-black')
                preview.bind_source_from(state, 'final_video_path', backward=lambda p: p or '')
                preview.bind_visibility_from(state, 'final_video_path', backward=bool)
                ui.label('완성본을 확인한 뒤 업로드하세요. YouTube에는 비공개로 저장됩니다.').classes('text-sm text-gray-300 mb-4')

                upload_btn = ui.button(
                    'YouTube에 비공개 업로드',
                    on_click=upload_video
                ).classes('w-full').props('color=red unelevated size=lg icon=cloud_upload')
                upload_btn.bind_enabled_from(state, 'is_busy', backward=lambda busy: bool(state.final_video_path) and not busy)

                @ui.refreshable
                def uploaded_review():
                    if not state.final_video_path:
                        return
                    try:
                        report = _completed_video(state.final_video_path)
                    except (OSError, ValueError, TypeError):
                        return
                    video_id = report.get('youtube_id')
                    if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{6,64}', video_id):
                        ui.label('이미 업로드된 완성본입니다. 다시 누르면 기존 업로드를 재사용합니다.').classes('text-xs text-teal-300 mt-3')
                        ui.label('기존 업로드의 제목·설명 변경은 YouTube Studio에서 진행하세요.').classes('text-xs text-gray-400')
                        ui.link('YouTube 검토본 열기', f'https://www.youtube.com/shorts/{video_id}', new_tab=True)

                uploaded_review()

        # 업로드 상태 정보
        with ui.card().classes('w-full p-4 bg-slate-800 border border-slate-700 mt-4'):
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('info', size='xs').classes('text-blue-400')
                ui.label('업로드 확인 사항').classes('text-sm font-bold text-blue-300')

            with ui.column().classes('gap-2'):
                ui.label('• YouTube 계정 연결이 필요합니다.').classes('text-xs text-gray-400')
                ui.label('• 완성본과 제목·설명·출처·AI 사용 공개 선택을 확인하세요.').classes('text-xs text-gray-400')
                ui.label('• 업로드는 비공개입니다. 공개 전환은 YouTube Studio에서 직접 결정하세요.').classes('text-xs text-gray-400')
