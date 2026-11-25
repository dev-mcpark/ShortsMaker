"""Explicit local inspection, separate from the user's script confirmation."""

import asyncio
import json

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh, safe_notify
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.services.openai_budget import chat_reservation_usd
from shorts_maker.services.openai_models import PRIMARY_CHAT_MODEL
from shorts_maker.services.revision_validation import read_applied_reassessment
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.services.script_reviews import read_script_reviews, read_review_script


def _verdict_label(record):
    label = {'missing': '결과 없음 · 확인 필요', 'unreadable': '결과 파일 확인 필요',
             'error': '검증 오류 · 확인 필요'}.get(record['state'])
    if label is None:
        verdict = record['verdict']
        label = f"모델 {'통과' if verdict['is_valid'] else '미통과'} · {verdict['score']}점"
    return label


def render_script_review_panel(state):
    script = state.script
    key = state.script_editor_key()
    execution = state.execution_key()
    scope = dict(state.operating_scope) if state.operating_scope else None
    loading = {'value': False}
    result = {'value': None, 'error': False}

    def current():
        return not panel.is_deleted and state.script_editor_key() == key and state.execution_key() == execution

    @ui.refreshable
    def body():
        if loading['value']:
            ui.label('저장된 검토 기록을 읽는 중…').classes('text-sm text-slate-300')
            return
        if result['error']:
            ui.label('검토 기록을 읽을 수 없습니다. 보관 폴더를 확인한 뒤 다시 조회하세요.').classes('text-sm text-amber-200')
            return
        value = result['value']
        if value is None:
            return
        if value.get('reassessment_error'):
            ui.label('사용자 재평가의 원문 기록을 확인할 수 없습니다. 회차와 저장된 요청을 확인하세요.').classes(
                'text-sm text-amber-200')
        if reassessment := value.get('reassessment'):
            with ui.expansion('사용자 재평가에서 대조한 원문', icon='article').classes('w-full min-w-0'):
                ui.label('현재 대본을 사용자가 재평가해 채택할 때 대조한 발췌입니다.').classes('text-sm')
                ui.label('채택 사유 · ' + reassessment['note']).classes('text-sm whitespace-pre-wrap break-words')
                ui.label(f'이전 대본의 모델 미통과 · {reassessment["rejected_score"]}점').classes('text-xs text-slate-300')
                ui.label(reassessment['excerpt']).classes('text-sm whitespace-pre-wrap break-words')
        if not value['records']:
            ui.label('현재 적용 대본과 정확히 일치하는 모델 검토 기록이 없습니다. 수정 전의 판정을 이어받지 않습니다.').classes(
                'text-sm text-amber-200')
        for record in value['records']:
            verdict = record['verdict']
            with ui.expansion(_verdict_label(record), icon='fact_check').classes('w-full min-w-0'):
                ui.label(f"모델: {record['model']}").classes('text-xs text-slate-300 break-all')
                ui.label(f"기록: {record['name']}").classes('text-xs text-slate-400 break-all')
                if verdict:
                    ui.label(f"판정 코드: {verdict['reason'] or '(없음)'}").classes('text-sm text-amber-200 break-all')
                    ui.label(verdict['feedback'] or '저장된 상세 피드백이 없습니다.').classes('text-sm text-slate-200 whitespace-pre-wrap break-words')
                if record['state'] != 'completed':
                    ui.label('통과 여부를 판단할 수 없습니다. 원본·요청 결과를 대조하기 전 재요청하지 마세요.').classes('text-sm text-amber-200')
                with ui.expansion('검토에 제공된 원문 발췌 보기').classes('w-full min-w-0'):
                    ui.label('당시 제공된 최대 5,000자 발췌입니다. 기사 전체·최신 내용·사실 확인 완료를 뜻하지 않습니다.').classes('text-xs text-slate-400')
                    ui.label(record['source_excerpt']).classes('text-sm text-slate-300 whitespace-pre-wrap break-words')
        if value['unreadable']:
            ui.label(f"요청·해시 확인이 필요한 기록 {len(value['unreadable'])}개 · 현재 대본과의 일치 여부를 판단할 수 없습니다.").classes(
                'text-sm text-amber-200')
            for name in value['unreadable']:
                ui.label(name).classes('text-xs text-slate-400 break-all')

    async def refresh():
        if loading['value'] or not current():
            return
        loading['value'] = True
        result.update(value=None, error=False)
        safe_refresh(body)
        try:
            value = await asyncio.to_thread(read_script_reviews, script)
            if scope and current():
                try:
                    value['reassessment'] = await asyncio.to_thread(read_applied_reassessment, scope, script)
                except (OSError, ValueError, RuntimeError, KeyError, TypeError, RecursionError):
                    value['reassessment_error'] = True
            if current():
                result['value'] = value
        except (OSError, ValueError):
            if current():
                result['error'] = True
        finally:
            loading['value'] = False
            if current():
                safe_refresh(body)

    def preview():
        if (comparison.is_deleted or state.is_busy or state.script_editor_key() != key
                or state.has_unapplied_script_draft()):
            safe_notify('수정 내용을 적용한 뒤 현재 대본에서 다시 여세요.', type='warning')
            return
        try:
            messages = ScriptValidator.review_messages(script, article.value or '')
            amount = chat_reservation_usd(PRIMARY_CHAT_MODEL, messages, ScriptValidator.MAX_COMPLETION_TOKENS)
        except (ValueError, RuntimeError) as error:
            safe_notify(str(error), type='warning')
            return
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label(script.title).classes('text-lg font-bold break-words')
            ui.label(f'{PRIMARY_CHAT_MODEL} 검증 1회 예상 예약액 ${amount:.6f}').classes('text-sm')
            ui.label('입력한 본문의 앞 5,000자까지 반영한 미리보기입니다.').classes('text-xs')
            ui.label(json.loads(messages[1]['content'])['source_excerpt']).classes('whitespace-pre-wrap break-words')
            ui.label(script.description).classes('text-sm whitespace-pre-wrap break-words')
            for scene in script.scenes:
                with ui.expansion(f'장면 {scene.scene_number} · {scene.script_text}').classes('w-full min-w-0'):
                    ui.label(scene.visual_description).classes('whitespace-pre-wrap break-words')
                    ui.label(scene.motion_instruction).classes('whitespace-pre-wrap break-words')
            ui.button('닫기', on_click=dialog.close).props('flat')
        dialog.open()

    with ui.expansion('수정 대본·원문 대조', icon='compare').classes('w-full mb-4 min-w-0') as comparison:
        comparison.bind_visibility_from(state, 'script', backward=lambda _: state.script_editor_key() == key)
        if SourceManager.is_allowed_url(script.source_url):
            ui.link('현재 대본의 출처 기사 열기', script.source_url, new_tab=True).props('rel="noopener noreferrer"')
        ui.label('기사 본문을 붙여 넣으면 장면별 내레이션·화면과 검증 예약 예상액을 무료로 확인합니다. '
                 '입력은 이 화면에서만 사용합니다.').classes('text-xs text-slate-300')
        article = ui.textarea('지금 대조할 기사 본문').props('outlined dark rows=4').classes('w-full')
        ui.button('원문과 장면 대조하기', on_click=preview).props('outline').classes('min-h-[44px]').bind_enabled_from(
            state, 'is_busy', lambda busy: not busy and state.script_editor_key() == key
            and not state.has_unapplied_script_draft() and bool((article.value or '').strip()))

    with ui.expansion('현재 대본의 모델 검토 기록', icon='fact_check').classes('w-full mb-4 min-w-0') as panel:
        panel.bind_visibility_from(state, 'script', backward=lambda _: state.script_editor_key() == key)
        ui.label('현재 적용 대본의 모델 기록과 해당 회차의 사용자 재평가 원문을 조회합니다. '
                 '미적용 수정은 포함하지 않습니다.').classes('text-xs text-slate-400')
        ui.label('모델 판정은 사용자 각본 확인·제외 해제·완성본 채택과 별개입니다. 조회는 무료이며 새 검증을 실행하지 않습니다.').classes('text-xs text-amber-200')
        ui.button('저장된 모델 검토 기록 조회', on_click=refresh).props('flat icon=refresh').classes('min-h-[44px]').bind_enabled_from(
            loading, 'value', backward=lambda value: not value)
        body()
    return refresh


def render_review_recovery(state, on_opened):
    loading = {'value': False}
    result = {'value': None, 'error': False}

    @ui.refreshable
    def body():
        with ui.column().classes('w-full gap-2') as view:
            if loading['value']:
                ui.label('검토 대본 목록을 읽는 중…').classes('text-xs text-slate-300')
                return
            if result['error']:
                ui.label('목록을 읽을 수 없습니다. 검토 보관 폴더를 확인하세요.').classes('text-xs text-amber-200')
                return
            if result['value'] is None:
                return
            records = {row['name']: row for row in result['value']['records']}
            for name in result['value']['unreadable']:
                ui.label(f'{name} · 파일·해시 확인 필요').classes('text-xs text-amber-200 break-all')
            if not records:
                ui.label('열 수 있는 검토 대본이 없습니다.').classes('text-xs text-slate-400')
                return
            choice = ui.select({name: f"{row['script']['title']} · {_verdict_label(row)} · {name}" for name, row in records.items()},
                               label='모델 검토 대본 검색', with_input=True).props('outlined dark clearable').classes('w-full')

            def preview():
                if view.is_deleted or state.is_busy or choice.value not in records:
                    return
                row = records[choice.value]
                def work_identity():
                    return json.dumps([state.script_editor_key(), state.script_editor_text(), state.first_frame_drafts,
                                       state.execution_key(), state.reviewed_script_sha256, state.final_video_path,
                                       state.prepared_narration_manifest, state.prepared_narration_sha256,
                                       state._editor_options(), state.manual_video_mode, state.manual_script_id], sort_keys=True)
                expected = work_identity()
                with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl bg-slate-900 text-white'):
                    ui.label(row['script']['title']).classes('text-lg font-bold break-words')
                    ui.label(f"{_verdict_label(row)} · {row['model']}").classes('text-sm text-amber-200 break-all')
                    if row['verdict']:
                        ui.label(row['verdict']['feedback'] or '저장된 피드백이 없습니다.').classes('text-sm whitespace-pre-wrap break-words')
                    ui.label('현재 대본·미적용 입력을 작업 초안으로 보관한 뒤 사본을 엽니다. 현재 완성본·음성 선택과 각본 확인은 해제됩니다. '
                             '원본·미통과 판정·파일·회차 권한은 유지되며 API를 호출하거나 검증 통과로 바꾸지 않습니다.').classes('text-sm text-slate-300')

                    def open_copy():
                        if dialog.is_deleted or not dialog.value:
                            return
                        try:
                            if view.is_deleted or state.is_busy or work_identity() != expected or choice.value != row['name']:
                                raise ValueError('현재 작업이나 선택이 바뀌었습니다. 검토 창을 다시 여세요.')
                            candidate = read_review_script(row['name'], row['request_sha256'])
                            backups = state.open_historical_script(candidate)
                        except (ValueError, OSError, RuntimeError) as error:
                            safe_notify(f'검토 대본 열기 중단: {error}', type='warning')
                            return
                        try:
                            dialog.close()
                            on_opened()
                        except RuntimeError:
                            pass  # The copy is already loaded; a deleted display cannot undo that result.
                        safe_notify(f'미확인 대본 사본 열기 완료 · 기존 입력 {len(backups)}개 초안 보관. 모델 판정은 유지됩니다.', type='positive')

                    with ui.row().classes('w-full flex-wrap'):
                        ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                        ui.button('미확인 사본 열기', on_click=open_copy).props('color=teal').classes('min-h-[44px]').bind_enabled_from(
                            state, 'is_busy', backward=lambda value: not value)
                dialog.open()

            ui.button('선택 검토 대본 확인', on_click=preview).props('flat icon=preview').classes('min-h-[44px]').bind_enabled_from(
                state, 'is_busy', backward=lambda value: not value)

    async def refresh():
        if loading['value'] or panel.is_deleted:
            return
        loading['value'] = True
        result.update(value=None, error=False)
        safe_refresh(body)
        try:
            value = await asyncio.to_thread(read_script_reviews)
            if not panel.is_deleted:
                result['value'] = value
        except (OSError, ValueError):
            if not panel.is_deleted:
                result['error'] = True
        finally:
            loading['value'] = False
            if not panel.is_deleted:
                safe_refresh(body)

    with ui.expansion('모델 검토 대본 다시 열기', icon='history').classes('w-full') as panel:
        ui.label('미통과·결과 미확인 대본도 재구매 없이 다시 검토할 수 있습니다. 사본 열기는 승인·재요청이 아닙니다.').classes('text-xs text-slate-300')
        ui.button('검토 대본 목록 조회', on_click=refresh).props('flat icon=refresh').classes('min-h-[44px]').bind_enabled_from(
            loading, 'value', backward=lambda value: not value)
        body()
    return refresh
