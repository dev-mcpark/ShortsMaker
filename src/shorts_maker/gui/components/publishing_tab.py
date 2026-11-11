"""YouTube Publishing 탭 컴포넌트"""

import hashlib
import json
import re
from pathlib import Path

from nicegui import ui
from typing import TYPE_CHECKING

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.common.card_header import card_with_header
from shorts_maker.gui.components.common.media_preview import media_sources
from shorts_maker.gui.components.youtube_connection_panel import render_youtube_connection_panel
from shorts_maker.services.production_service import source_credited_description, script_sha256
from shorts_maker.services.publishing_drafts import (
    publishing_key as _publishing_key, save_publishing_draft, saved_publishing_drafts,
    restore_publishing_draft,
)
from shorts_maker.utils.config import settings
from shorts_maker.utils.logger import get_logger

if TYPE_CHECKING:
    from shorts_maker.gui.state.app_state import AppState

logger = get_logger(__name__)


def _completed_outputs() -> dict[str, str]:
    outputs = []
    for path in settings.output_dir.glob('*.production.json'):
        try:
            if not path.resolve().is_relative_to(settings.output_dir.resolve()):
                continue
            report = json.loads(path.read_text(encoding='utf-8'))
            video = Path(report['video_path']).resolve()
            if (report.get('schema_version') == 1 and report.get('quality_passed') is True
                    and re.fullmatch(r'[0-9a-f]{64}', str(report.get('video_sha256', '')))
                    and report.get('video_path') == str(video)
                    and path.resolve() == video.with_suffix('.production.json') and video.is_file()
                    and video.suffix.lower() == '.mp4'
                    and video.is_relative_to(settings.output_dir.resolve())):
                outputs.append((video.stat().st_mtime, str(video), f"{report.get('title') or video.stem} · {video.name}"))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return {path: label for _, path, label in sorted(outputs, reverse=True)}


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


def _recorded_metadata(report: dict) -> dict:
    request = report.get('youtube_upload_request') or {}
    snippet = request.get('snippet', {}) if isinstance(request, dict) else {}
    snippet = snippet if isinstance(snippet, dict) else {}
    title = snippet.get('title') or report.get('title')
    description, source = snippet.get('description'), report.get('source_url')
    tags, disclosure = snippet.get('tags', []), report.get('contains_synthetic_media')
    return {
        'title': title if isinstance(title, str) else Path(report['video_path']).stem,
        'description': description if isinstance(description, str) else ('출처: ' + source if isinstance(source, str) else ''),
        'tags': ','.join(tag for tag in tags if isinstance(tag, str)) if isinstance(tags, list) else '',
        'disclosure': ('yes' if disclosure else 'no') if isinstance(disclosure, bool) else None,
    }


def render_publishing_tab(state: 'AppState') -> None:
    """YouTube Publishing 탭 렌더링"""

    binding = {'path': state.final_video_path, 'key': None, 'loading': False}
    snapshots_open = {'value': False}
    media_source = media_sources(ui.context.client)
    with ui.column().classes('w-full max-w-2xl mx-auto mt-10'):
        with card_with_header('YouTube 비공개 업로드', 'cloud_upload', 'danger'):
            with ui.element('div').classes('w-full p-6'):
                render_youtube_connection_panel(state)
                outputs = _completed_outputs()
                saved_video = ui.select(
                    outputs, label='저장된 완성본', with_input=True,
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
                    restore_form(report)
                    safe_refresh(publishing_snapshots)
                    uploaded_review.refresh()
                    safe_notify('완성본을 불러왔습니다. 영상과 게시 정보를 확인하세요.', type='positive')

                with ui.row().classes('w-full gap-2 mb-4'):
                    ui.button('완성본 불러오기', on_click=load_saved_video).props('flat icon=folder_open').bind_enabled_from(
                        state, 'is_busy', backward=lambda busy: not busy)
                    ui.button('목록 새로고침', on_click=refresh_outputs).props('flat icon=refresh')
                ui.label('제목·파일명으로 검색 · 파일 최근 수정순. 재제작 없이 열며 품질 기록과 파일 해시를 확인합니다.').classes(
                    'text-xs text-gray-400 mb-4')
                ui.label('품질 기록·저장 해시가 없는 이전 파일은 이 목록에서 제외됩니다. 재료 보관함에서 확인하세요.').classes('text-xs text-amber-200 mb-4')

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

                def remember_form(_=None):
                    if (not binding['loading'] and not state.is_busy and binding['key'] is not None
                            and binding['path'] == state.final_video_path):
                        state.publishing_drafts[binding['key']] = {
                            'title': title_input.value or '', 'description': desc_input.value or '',
                            'tags': tags_input.value or '', 'disclosure': synthetic_input.value,
                        }

                def restore_form(report=None):
                    binding.update(path=state.final_video_path, key=None, loading=True)
                    try:
                        if state.final_video_path:
                            report = report or _completed_video(state.final_video_path)
                            binding['key'] = _publishing_key(report)
                            defaults = _recorded_metadata(report)
                        else:
                            binding['key'] = ''
                            defaults = {'title': '', 'description': '', 'tags': '', 'disclosure': None}
                        values = state.publishing_drafts.get(binding['key'], defaults)
                        for key, control in (('title', title_input), ('description', desc_input),
                                             ('tags', tags_input), ('disclosure', synthetic_input)):
                            control.value = values[key]
                    except (OSError, ValueError, TypeError):
                        ui.label('선택된 영상의 품질 기록을 확인할 수 없습니다. 완성본을 다시 선택해 불러오세요.').classes('text-sm text-amber-200')
                    finally:
                        binding['loading'] = False

                for control in (title_input, desc_input, tags_input, synthetic_input):
                    control.on_value_change(remember_form)
                restore_form()
                ui.label('메뉴 이동 시 입력을 유지합니다. 재시작 전에는 게시 초안을 사본 저장하세요. 같은 영상에만 다시 불러올 수 있습니다.').classes('text-xs text-slate-400 mb-3')

                @ui.refreshable
                def publishing_snapshots():
                    expected_key = binding['key']

                    def current_report():
                        if (state.is_busy or binding['path'] != state.final_video_path or binding['key'] != expected_key
                                or getattr(snapshot_view, 'is_deleted', False) is True):
                            raise ValueError('작업이 끝난 뒤 현재 완성본을 다시 불러오세요.')
                        report = _completed_video(state.final_video_path)
                        if _publishing_key(report) != expected_key:
                            raise ValueError('영상이 바뀌었습니다. 완성본을 다시 불러오세요.')
                        return report

                    with ui.expansion('게시 초안 저장·복원', icon='save', value=snapshots_open['value'],
                                      on_value_change=lambda event: snapshots_open.update(value=event.value)).classes('w-full mb-4') as snapshot_view:
                        ui.label('빈 입력·미선택 상태도 저장합니다. 복원은 업로드나 기존 게시 정보 변경을 실행하지 않습니다.').classes('text-xs text-slate-400')
                        if not state.final_video_path or not expected_key:
                            ui.label('먼저 저장된 완성본을 불러오세요.').classes('text-sm text-slate-400')
                            return
                        try:
                            choices, digests, warnings = saved_publishing_drafts(current_report())
                        except (OSError, ValueError, TypeError):
                            ui.label('초안 목록을 읽을 수 없습니다. 영상·보관 폴더를 확인한 뒤 새로고침하세요.').classes('text-sm text-amber-200')
                            choices, digests, warnings = {}, {}, []
                        for warning in warnings[:3]:
                            ui.label(warning).classes('text-xs text-amber-200')

                        def save_snapshot():
                            try:
                                report = current_report()
                                remember_form()
                                save_publishing_draft(report, state.publishing_drafts[expected_key])
                            except (OSError, ValueError, TypeError, KeyError) as error:
                                safe_notify(f'게시 초안 저장 실패: {error}', type='negative')
                                return
                            safe_refresh(publishing_snapshots)
                            safe_notify('게시 초안을 사본으로 저장했습니다.', type='positive')

                        with ui.row().classes('w-full gap-2'):
                            ui.button('게시 초안 사본 저장', on_click=save_snapshot).props('flat icon=save').bind_enabled_from(
                                state, 'is_busy', backward=lambda busy: not busy)
                            ui.button('게시 초안 목록 새로고침', on_click=lambda: safe_refresh(publishing_snapshots)).props('flat icon=refresh')
                        saved = ui.select(choices, label='이 영상의 저장된 게시 초안', with_input=True).props('outlined dark').classes('w-full')
                        saved.bind_enabled_from(state, 'is_busy', backward=lambda busy: not busy)
                        if not choices:
                            ui.label('이 영상의 저장된 게시 초안이 없습니다.').classes('text-xs text-slate-400')

                        def load_snapshot():
                            try:
                                report = current_report()
                                if saved.value not in digests:
                                    raise ValueError('저장된 게시 초안을 선택하세요.')
                                remember_form()
                                fields, backup = restore_publishing_draft(
                                    report, saved.value, digests[saved.value],
                                    state.publishing_drafts[expected_key], _recorded_metadata(report))
                            except (OSError, ValueError, TypeError, KeyError) as error:
                                safe_notify(f'게시 초안 복원 실패: {error}', type='negative')
                                return
                            state.publishing_drafts[expected_key] = fields
                            restore_form(report)
                            safe_refresh(publishing_snapshots)
                            safe_notify('게시 초안을 불러왔습니다.' + (' 이전 편집도 사본으로 보관했습니다.' if backup else ''), type='positive')

                        ui.button('게시 초안 불러오기', on_click=load_snapshot).props('flat icon=folder_open').bind_enabled_from(
                            state, 'is_busy', backward=lambda busy: not busy and bool(choices))

                publishing_snapshots()

                def reset_form():
                    if state.is_busy or binding['path'] != state.final_video_path:
                        safe_notify('현재 완성본을 다시 불러온 뒤 게시 입력을 확인하세요.', type='warning')
                        return
                    try:
                        report = _completed_video(state.final_video_path) if state.final_video_path else None
                        if report and binding['key'] != _publishing_key(report):
                            raise ValueError('영상이 바뀌었습니다. 완성본을 다시 불러오세요.')
                    except (OSError, ValueError, TypeError) as error:
                        safe_notify(str(error), type='warning')
                        return
                    state.publishing_drafts.pop(binding['key'], None)
                    restore_form(report)

                ui.button('게시 입력 되돌리기', on_click=reset_form).props('flat color=grey-4').bind_enabled_from(
                    state, 'is_busy', backward=lambda busy: not busy)

                def load_metadata():
                    """스크립트에서 메타데이터 로드"""
                    if state.is_busy:
                        safe_notify('진행 중인 제작·업로드가 끝난 뒤 게시 정보를 바꾸세요.', type='warning')
                        return
                    if binding['path'] != state.final_video_path:
                        safe_notify('선택된 영상이 바뀌었습니다. 완성본을 다시 불러오세요.', type='warning')
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
                        remember_form()
                    else:
                        safe_notify('불러온 각본이 없습니다.', type='warning')

                ui.button(
                    '각본에서 게시 정보 가져오기',
                    on_click=load_metadata
                ).props('flat color=white icon=download').classes('mb-4')

                async def upload_video(expected_execution=state.execution_key()):
                    """YouTube에 비디오 업로드"""
                    if state.is_busy:
                        return
                    if not state.final_video_path:
                        safe_notify('업로드할 완성본을 먼저 불러오세요.', type='warning')
                        return
                    try:
                        if (binding['path'] != state.final_video_path
                                or binding['key'] != _publishing_key(_completed_video(state.final_video_path))):
                            raise ValueError('선택된 영상이 바뀌었습니다. 완성본과 게시 정보를 다시 확인하세요.')
                    except (OSError, ValueError, TypeError) as error:
                        safe_notify(str(error), type='warning')
                        return
                    if not (title_input.value or '').strip():
                        safe_notify('영상 제목을 입력하세요', type='warning')
                        return
                    if synthetic_input.value not in ('yes', 'no'):
                        safe_notify('AI 사용 공개 여부를 선택하세요', type='warning')
                        return

                    try:
                        state.require_execution_context(expected_execution)
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

                preview = ui.video('').classes('w-full max-w-[270px] max-h-[480px] mb-4 bg-black')
                preview.bind_source_from(state, 'final_video_path', backward=media_source)
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
