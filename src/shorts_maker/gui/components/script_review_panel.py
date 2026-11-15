"""Explicit local inspection, separate from the user's script confirmation."""

import asyncio

from nicegui import ui

from shorts_maker.gui.components.common.safe_ui import safe_refresh
from shorts_maker.services.script_reviews import read_script_reviews


def render_script_review_panel(state):
    script = state.script
    key = state.script_editor_key()
    loading = {'value': False}
    result = {'value': None, 'error': False}

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
        if not value['records']:
            ui.label('현재 적용 대본과 정확히 일치하는 모델 검토 기록이 없습니다. 수정 전의 판정을 이어받지 않습니다.').classes(
                'text-sm text-amber-200')
        for record in value['records']:
            verdict = record['verdict']
            label = {'missing': '결과 없음 · 확인 필요', 'unreadable': '결과 파일 확인 필요',
                     'error': '검증 오류 · 확인 필요'}.get(record['state'])
            if label is None:
                label = f"모델 {'통과' if verdict['is_valid'] else '미통과'} · {verdict['score']}점"
            with ui.expansion(label, icon='fact_check').classes('w-full min-w-0'):
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
        if loading['value'] or panel.is_deleted or state.script_editor_key() != key:
            return
        loading['value'] = True
        result.update(value=None, error=False)
        safe_refresh(body)
        try:
            value = await asyncio.to_thread(read_script_reviews, script)
            if not panel.is_deleted and state.script_editor_key() == key:
                result['value'] = value
        except (OSError, ValueError):
            if not panel.is_deleted and state.script_editor_key() == key:
                result['error'] = True
        finally:
            loading['value'] = False
            if not panel.is_deleted and state.script_editor_key() == key:
                safe_refresh(body)

    with ui.expansion('현재 대본의 모델 검토 기록', icon='fact_check').classes('w-full mb-4 min-w-0') as panel:
        panel.bind_visibility_from(state, 'script', backward=lambda _: state.script_editor_key() == key)
        ui.label('현재 적용 대본과 해시가 일치하는 저장 기록만 조회합니다. 미적용 수정은 포함하지 않습니다.').classes('text-xs text-slate-400')
        ui.label('모델 판정은 사용자 각본 확인·제외 해제·완성본 채택과 별개입니다. 조회는 무료이며 새 검증을 실행하지 않습니다.').classes('text-xs text-amber-200')
        ui.button('저장된 모델 검토 기록 조회', on_click=refresh).props('flat icon=refresh').classes('min-h-[44px]').bind_enabled_from(
            loading, 'value', backward=lambda value: not value)
        body()
    return refresh
