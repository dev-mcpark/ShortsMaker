"""Inspect a scheduled review and attach an existing verified private upload from Studio."""

from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from shorts_maker.gui.components.common.safe_ui import safe_notify, safe_refresh
from shorts_maker.gui.components.episode_reservation_panel import render_episode_reservation_panel
from shorts_maker.gui.components.episode_review_recovery_panel import (
    render_episode_review_recovery, render_pending_upload_recovery,
)
from shorts_maker.gui.components.scheduled_run_view import STOP_GUIDANCE
from shorts_maker.gui.components.work_drafts_panel import render_episode_writer_draft
from shorts_maker.services.operating_budget import episode_path, load_episode
from shorts_maker.services.operating_status import episode_source_url, operator_status, schedule_sha256
from shorts_maker.services.scheduled_script_history import restore_missing_revision_copy
from shorts_maker.services.scheduled_planning import planning_preflight, plan_pending_schedule
from shorts_maker.services.revision_validation import (
    prepare_recovery, preview_reassessment, preview_recovery, save_reassessment,
)


def render_operator_panel(state, manager, schedule, on_attached):
    readout, loading = {}, {'value': False}
    planning_preview = {'checking': False}
    planning_dialog = None
    attachment_checking = False
    attachment_dialog = None
    restoring_revision = False

    def choose_episode_source():
        if panel.is_deleted or state.is_busy:
            return
        prefill = state.planning_url if state.planning_source_mode == '직접 URL 입력' else ''
        initial = episode_source_url(schedule) or prefill
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label('이번 회차 기사 지정').classes('text-lg font-bold')
            ui.label('원문을 읽고 확인한 공개 기사 주소를 입력하세요. 빈칸으로 저장하면 이번 회차에서 RSS로 소재를 찾습니다.').classes('text-sm')
            ui.label('이 선택은 이번 회차에 저장됩니다. 기획은 별도의 비용 확인을 거쳐 시작합니다.').classes('text-sm')
            url = ui.input('이번 회차 기사 URL', value=initial).props('maxlength=4096').classes('w-full')
            notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

            def save():
                if panel.is_deleted or dialog.is_deleted or state.is_busy or not dialog.value:
                    return
                try:
                    manager.set_pending_episode_source(schedule['id'], url.value,
                                                       expected_schedule_sha256=schedule_sha256(schedule))
                except (OSError, ValueError, RuntimeError) as error:
                    notice.set_text(f'출처 저장 중단: {error}')
                    return
                dialog.close()
                on_attached()
                safe_notify('이번 회차의 소재 선택을 저장했습니다.', type='positive')

            with ui.row().classes('w-full flex-wrap'):
                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                ui.button('이번 회차 출처 저장', on_click=save).props('color=teal').classes('min-h-[44px]')
        dialog.open()

    def revision_preview():
        def current():
            if (state.is_busy or panel.is_deleted or not state.script or not state.is_script_reviewed()
                    or state.has_unapplied_script_draft()
                    or schedule_sha256(manager.get_schedule(schedule['id']) or {}) != schedule_sha256(schedule)):
                raise ValueError('수정 내용을 적용·확인한 뒤 현재 회차에서 다시 저장하세요.')
        try:
            current()
            script_text = state.script.model_dump_json()
            receipt = state.reviewed_script_sha256
            if state.script.source_url != (schedule.get('last_script') or {}).get('source_url'):
                raise ValueError('이 회차와 같은 출처의 수정 각본을 불러오세요.')
        except (ValueError, RuntimeError) as error:
            safe_notify(str(error), type='warning')
            return
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
            ui.label('확인한 수정 대본을 이 회차에 저장').classes('text-lg font-bold')
            ui.label(f'이전: {(schedule.get("last_script") or {}).get("title", "제목 없음")}').classes('text-sm text-slate-300')
            ui.label(f'수정: {state.script.title}').classes('text-sm text-teal-200')
            ui.label('이전 대본은 회차 이력에 남깁니다. 기존 영상·승인·제외·비용 기록은 유지하며, 수정한 장면은 다시 확인해야 합니다.').classes('text-sm text-slate-300')
            ui.label('API 호출·비용 한도 확대·영상 채택·일정 재개를 실행하지 않습니다.').classes('text-xs text-slate-400')

            def confirm():
                if dialog.is_deleted or not dialog.value:
                    return
                try:
                    current()
                    if state.script.model_dump_json() != script_text or state.reviewed_script_sha256 != receipt:
                        raise ValueError('대본 또는 확인 상태가 바뀌었습니다. 수정본을 다시 확인하세요.')
                    manager.revise_pending_script(schedule['id'], state.script.model_dump(mode='json'),
                        expected_schedule_sha256=schedule_sha256(schedule), reviewed_script_sha256=receipt)
                    dialog.close()
                    on_attached()
                    safe_notify('수정 대본을 회차에 저장했습니다. 장면 검토 후 제작을 이어가세요.', type='positive')
                except (ValueError, RuntimeError, OSError) as error:
                    safe_notify(f'회차 대본 저장 중단: {error}', type='warning')

            with ui.row().classes('w-full flex-wrap'):
                ui.button('취소', on_click=dialog.close).props('flat').style('min-height:44px')
                ui.button('이 수정 대본으로 회차 저장', on_click=confirm).props('color=teal').style('min-height:44px')
        dialog.open()

    async def plan_preview():
        nonlocal planning_dialog
        if (panel.is_deleted or planning_preview['checking']
                or (planning_dialog is not None and not planning_dialog.is_deleted and planning_dialog.value)):
            return

        def current():
            if (state.is_busy or getattr(panel, 'is_deleted', False) is True
                    or schedule_sha256(manager.get_schedule(schedule['id']) or {}) != schedule_sha256(schedule)):
                raise ValueError('작업 중이거나 일정이 바뀌었습니다. 현재 회차를 다시 확인하세요.')
        planning_preview['checking'] = True
        try:
            current()
            room = await run.io_bound(planning_preflight, manager, schedule)
            current()
        except (ValueError, RuntimeError, OSError) as error:
            if not panel.is_deleted and not planning_check.is_deleted:
                planning_check.set_text(f'기획을 시작할 수 없습니다: {error}')
                planning_check.set_visibility(True)
            return
        finally:
            planning_preview['checking'] = False

        planning_check.set_visibility(False)
        planning_check.set_text('')
        if planning_dialog is not None and not planning_dialog.is_deleted:
            planning_dialog.delete()
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
            ui.label(f'{schedule["name"]} · 예약 회차 기획').classes('text-lg font-bold')
            source = episode_source_url(schedule) or schedule.get('direct_url')
            ui.label(f'선택 기사 · {source}' if source else '소재 선택 · RSS 자동 발견').classes('text-sm break-all')
            ui.label('소재 분석·각본·검증에 OpenAI 비용이 발생합니다. 음성·이미지·영상 제작과 업로드는 실행하지 않습니다.').classes('text-sm text-slate-300')
            ui.label(f'월·회차 중 작은 잔여 상한: Google ₩{room["google_remaining_krw"]:,} · OpenAI ${room["openai_remaining_usd"]:.6f}').classes('text-sm text-teal-200')
            ui.label(f'최소 {room["minimum_visual_scenes"]}장면 신규 비주얼 예약 추정 · '
                     f'₩{room["minimum_visual_reservation_krw"]:,}').classes('text-sm text-slate-300')
            ui.label('이 화면의 신규 비주얼 추정은 기본 장면 구성에 대한 금액입니다. '
                     '각본에 맞춘 첫 프레임·장면·음성의 예약액은 제작 단계에서 확인합니다.').classes('text-xs text-slate-400')
            ui.label('OpenAI 기획은 실제 기사·응답에 맞춰 각 요청 직전에 예약액을 계산합니다.').classes('text-xs text-slate-400')
            ui.label('업로드 인증이 만료됐다면 기획 비용을 쓰기 전에 멈춥니다. 중단된 실행을 자동으로 다시 제출하지 않습니다.').classes('text-xs text-slate-400')

            async def confirm():
                if dialog.is_deleted or not dialog.value:
                    return
                try:
                    current()
                except (ValueError, RuntimeError, OSError) as error:
                    safe_notify(f'기획을 시작할 수 없습니다: {error}', type='warning')
                    return
                state.scheduled_planning_in_progress = True
                dialog.close()
                try:
                    await plan_pending_schedule(manager, schedule)
                    safe_notify('기획을 저장했습니다. 예약 회차의 각본 불러오기로 검토하세요.', type='positive')
                except (ValueError, RuntimeError, OSError) as error:
                    safe_notify(f'기획 중단: {error}', type='warning')
                finally:
                    state.scheduled_planning_in_progress = False
                    on_attached()

            with ui.row().classes('w-full flex-wrap'):
                ui.button('취소', on_click=dialog.close).props('flat')
                ui.button('이 회차 기획 실행', on_click=confirm).props('color=teal').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
        planning_dialog = dialog
        dialog.open()

    recovery_dialog = None
    recovery_checking = False
    reassessment = schedule.get('last_result') == 'planning_failed'
    can_reassess = False
    if reassessment:
        try:
            can_reassess = episode_path(schedule.get('last_episode_id')).with_suffix('.revision-request.started').is_file()
        except (ValueError, OSError):
            pass

    async def recovery_preview():
        nonlocal recovery_dialog, recovery_checking
        if (panel.is_deleted or recovery_checking
                or (recovery_dialog is not None and not recovery_dialog.is_deleted and recovery_dialog.value)):
            return
        script = state.script
        review_receipt = state.reviewed_script_sha256

        def current():
            if (panel.is_deleted or state.is_busy or not script or state.script is not script
                    or state.reviewed_script_sha256 != review_receipt
                    or not state.is_script_reviewed() or state.has_unapplied_script_draft()
                    or (state.operating_scope and state.operating_scope['episode_id'] != schedule['last_episode_id'])
                    or manager.get_schedule(schedule['id']) != schedule):
                raise ValueError('수정 대본을 적용·확인한 뒤 현재 회차를 다시 확인하세요.')

        recovery_checking = True
        try:
            current()
            preview = await run.io_bound(preview_reassessment if reassessment else preview_recovery,
                                         manager, schedule, script)
            current()
        except (ValueError, RuntimeError, OSError, TypeError, KeyError, ArithmeticError) as error:
            if not panel.is_deleted:
                safe_notify(str(error), type='warning')
            return
        finally:
            recovery_checking = False
        if recovery_dialog is not None and not recovery_dialog.is_deleted:
            recovery_dialog.delete()

        review = preview.get('review')
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label('모델 미통과 대본 재평가' if review else '수정 대본과 작성 원문 확인').classes('text-lg font-bold')
            ui.label(script.title).classes('font-semibold')
            with ui.scroll_area().classes('w-full h-72'):
                ui.label(script.source_url).classes('text-sm break-all')
                if review:
                    verdict = review['verdict']
                    ui.label(f'이전 모델 미통과 · {verdict["score"]}점').classes('font-semibold')
                    ui.label(verdict['feedback'] or verdict['reason']).classes('text-sm whitespace-pre-wrap break-words')
                    ui.label('이전 대본').classes('font-semibold')
                    for scene in review['script']['scenes']:
                        ui.label(scene['script_text']).classes('text-sm break-words')
                ui.label('검증에 사용한 원문 발췌' if review else '작성에 사용한 원문 발췌').classes('font-semibold')
                ui.label(review['source_excerpt'] if review else preview['source_excerpt']).classes(
                    'text-sm whitespace-pre-wrap break-words')
                ui.label('확인한 수정 대본').classes('font-semibold')
                for scene in script.scenes:
                    ui.label(scene.script_text).classes('text-sm break-words')
            if review:
                ui.label('이전 모델 판정은 보존합니다. 수정 대본 채택 후 각본·장면 검토를 이어갑니다.')
                note = ui.textarea('원문을 대조한 뒤 이 수정 대본을 채택하는 이유').props('maxlength=500').classes('w-full')
            else:
                ui.label(f'모델 검증 예상 예약액 ${preview["reservation_estimate_usd"]} · 이 화면에서는 요청만 저장합니다.')

            async def save():
                if dialog.is_deleted or not dialog.value:
                    return
                try:
                    current()
                except ValueError as error:
                    safe_notify(str(error), type='warning')
                    return
                state.scheduled_planning_in_progress = True
                try:
                    if review:
                        await run.io_bound(save_reassessment, manager, schedule, script, preview, note.value)
                    else:
                        await run.io_bound(prepare_recovery, manager, schedule, script, preview)
                except (ValueError, RuntimeError, OSError, TypeError, KeyError, ArithmeticError) as error:
                    safe_notify(str(error), type='warning')
                else:
                    dialog.close()
                    if review:
                        on_attached()
                        safe_notify('수정 대본을 채택했습니다. 검토할 각본 불러오기로 이어가세요.', type='positive')
                    else:
                        safe_notify('요청을 저장했습니다. 준비된 수정 대본 검증에서 비용을 확인하고 실행할 수 있습니다.',
                                    type='positive')
                finally:
                    state.scheduled_planning_in_progress = False

            ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
            ui.button('재평가한 수정 대본 채택' if review else '원문 확인 · 검증 요청 저장',
                      on_click=save).props('color=teal').classes('min-h-[44px]')
        recovery_dialog = dialog
        dialog.open()

    async def revision_validation_preview():
        import subprocess
        import sys
        from shorts_maker.services.revision_validation import prepared_revision
        from shorts_maker.utils.config import PROJECT_ROOT, settings

        def current():
            if (panel.is_deleted or state.is_busy or not settings.paid_production_enabled
                    or manager.get_schedule(schedule['id']) != schedule):
                raise ValueError('현재 회차와 직접 제작 설정을 확인하세요.')
        try:
            current()
            digest, script, amount = await run.io_bound(prepared_revision, manager, schedule)
            current()
        except (ValueError, OSError, RuntimeError, KeyError, TypeError, ArithmeticError) as error:
            safe_notify(str(error), type='warning')
            return
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label(script.title).classes('text-lg font-bold')
            ui.label(f'수정 대본 모델 검증 1회 · 예약액 ${amount}')
            ui.label('준비된 원문으로 검증합니다. 통과하면 같은 회차의 장면 검토로 이어집니다.')
            async def confirm():
                if dialog.is_deleted or not dialog.value:
                    return
                try:
                    current()
                except ValueError as error:
                    safe_notify(str(error), type='warning')
                    return
                state.scheduled_planning_in_progress = True
                dialog.close()
                try:
                    command = [sys.executable, str(PROJECT_ROOT / 'scripts/operate_schedule.py'), '--schedules',
                               str(manager.filename.resolve()), 'run', '--validate-revision', digest, schedule['id']]
                    result = await run.io_bound(subprocess.run, command, cwd=PROJECT_ROOT, capture_output=True)
                    ok = not result.returncode and (manager.get_schedule(schedule['id']) or {}).get('last_result') == 'script_review_pending'
                    safe_notify('수정 대본 검증 통과 · 회차에서 대본을 불러오세요.' if ok else
                                '검증 중단 · 회차 상태와 저장된 검토 기록을 확인하세요.', type='positive' if ok else 'warning')
                finally:
                    state.scheduled_planning_in_progress = False
                    on_attached()
            ui.button('취소', on_click=dialog.close).props('flat')
            ui.button('수정 대본 1회 검증', on_click=confirm).props('color=teal')
        dialog.open()

    async def restore_revision():
        nonlocal restoring_revision
        if panel.is_deleted or state.is_busy or restoring_revision:
            return
        restoring_revision = True
        try:
            await run.io_bound(restore_missing_revision_copy, manager, schedule)
            safe_notify('저장된 수정 대본 파일을 복원했습니다. 검토할 각본을 다시 불러오세요.', type='positive')
        except (OSError, ValueError, RuntimeError) as error:
            safe_notify(f'수정 대본 복원 중단: {error}', type='warning')
        finally:
            restoring_revision = False
            if not panel.is_deleted:
                await refresh()

    @ui.refreshable
    def details():
        if not readout:
            ui.label('펼치거나 새로고침하면 현재 회차 기록을 조회합니다.').classes('text-xs text-slate-400')
            return
        if 'error' in readout:
            ui.label(readout['error']).classes('text-xs text-amber-200 break-all')
            return
        data = readout['data']
        stop = STOP_GUIDANCE.get(data['last_result'])
        phase = {'operator_pending': '제작 인계 대기',
                 'script_review_pending': '완성본 검토 대기' if data.get('last_youtube_id') else '각본·장면 검토 대기',
                 'private_review_deferred': '미채택 검토본 보존 · 다음 회차 예약 가능',
                 'private_review_accepted': '완성본 채택 완료', 'script_rejected': '각본 제외'}.get(
                     data['last_result'], '운영 상태 확인 필요' if data['last_result'] else '아직 실행 전')
        ui.label(f'회차 {data["run_count"] or 0} · {stop[0] if stop else phase}').classes('text-sm text-slate-200')
        ui.label(f'마지막 조회 {readout["checked_at"]}').classes('text-xs text-slate-400')
        if data.get('planning_auth_required'):
            ui.label('지난 기획 시도에서 YouTube 업로드 인증을 확인하지 못해 비용 발생 전에 중단했습니다. '
                     '이미 연결했다면 이 회차의 기획을 재개하세요. 현재 연결 상태는 '
                     '완성본·업로드 → YouTube 업로드 연결 → 저장된 인증 확인에서 확인할 수 있습니다.').classes(
                'text-sm text-amber-200').props('role=alert')
        if schedule.get('review_operator') != 'agent':
            ui.label('Studio 직접 실행 일정입니다. 월 장부·비주얼 상한을 사용하며 에이전트 회차 한도를 새로 만들지 않습니다.').classes('text-xs text-slate-400')
        elif not data.get('last_episode_id'):
            ui.label('아직 회차 장부가 없습니다. 실제 예약 대기 항목에서만 회차를 시작합니다.').classes('text-xs text-slate-400')
        if data.get('operation_pending_unverified'):
            ui.label('실행 결과 대조 필요 · 요청 기록을 확인하기 전 재실행·연결을 중단합니다.').classes('text-xs text-amber-200')
            if (schedule.get('review_operator') == 'agent' and schedule.get('last_result') == 'script_review_pending'
                    and not schedule.get('enabled') and not schedule.get('last_youtube_id') and not schedule.get('last_video_path')):
                render_pending_upload_recovery(state, manager, schedule, refresh)
        elif stop:
            ui.label(stop[1]).classes('text-sm text-slate-300 break-words')
        if 'budget_error' in data:
            ui.label(f'회차 비용 확인 필요: {data["budget_error"]}').classes('text-xs text-amber-200 break-all')
        if data.get('planned_script_error'):
            ui.label(data['planned_script_error']).classes('text-xs text-amber-200')
            if (data.get('planned_script_missing') and data['last_result'] == 'script_review_pending'
                    and not data['enabled'] and not data.get('last_video_path') and not data.get('last_youtube_id')):
                ui.button('누락된 수정 대본 파일 복원', on_click=restore_revision).props('outline icon=restore').classes(
                    'min-h-[44px]').bind_enabled_from(state, 'is_busy',
                        lambda busy: not busy and not restoring_revision)
        if data.get('script_reassessment'):
            ui.label('사용자 재평가로 수정 대본을 채택했습니다. 이전 모델 미통과 기록은 보관되어 있습니다.').classes(
                'text-xs text-slate-300')
        if budget := data.get('budget'):
            ui.label(f'Google 회차 누적 예약 ₩{budget["google_new_reserved_krw"]:,} · 전체 상한까지 여유 ₩{budget["google_remaining_krw"]:,}').classes('text-xs text-teal-200')
            ui.label(f'OpenAI 회차 누적 예약 ${budget["openai_new_reserved_usd"]:.6f} · 전체 상한까지 여유 ${budget["openai_remaining_usd"]:.6f}').classes('text-xs text-teal-200')
        if schedule.get('review_operator') == 'agent' and schedule.get('last_episode_id'):
            render_episode_reservation_panel(manager, schedule)
        ui.label('전체 회차 여유는 새 지출 허가가 아닙니다. 월 잔액과 별도 비교·검증 범위 중 더 작은 한도 및 소진된 호출 횟수를 함께 적용합니다.').classes('text-xs text-slate-400')
        ui.label('기획은 실제 제작 대기 회차에서만 별도로 시작합니다. 회차를 앞당기거나 미디어를 자동 제작하지 않습니다.').classes('text-xs text-slate-400')

    async def refresh():
        if loading['value']:
            return
        loading['value'] = True
        try:
            def read():
                current = manager.get_schedule(schedule['id'])
                if not current:
                    raise ValueError('일정이 없습니다. 목록을 새로고침하세요.')
                return operator_status(current)
            data = await run.io_bound(read)
            readout.clear()
            readout['data'] = data
            readout['checked_at'] = datetime.now().astimezone().strftime('%m-%d %H:%M:%S %Z')
        except (ValueError, OSError, RuntimeError) as error:
            readout.clear()
            readout['error'] = str(error)
        finally:
            loading['value'] = False
            safe_refresh(details)

    async def opened(event):
        if event.value:
            await refresh()

    def check_attachment_schedule():
        if manager.get_schedule(schedule['id']) != schedule:
            raise ValueError('회차 상태가 바뀌었습니다. 현재 회차를 다시 확인하세요.')
        if schedule.get('review_operator') == 'agent':
            load_episode(schedule.get('last_episode_id'), schedule)

    async def attach_preview():
        nonlocal attachment_checking, attachment_dialog
        if (panel.is_deleted or state.is_busy or attachment_checking or not state.final_video_path
                or (attachment_dialog is not None and not attachment_dialog.is_deleted and attachment_dialog.value)):
            return
        selected = state.final_video_path

        def read():
            check_attachment_schedule()
            info = manager.pending_video_info(schedule['id'], selected)
            check_attachment_schedule()
            return info

        attachment_checking = True
        attachment_notice.text = '선택 영상과 비공개 업로드 기록을 확인하는 중…'
        try:
            info = await run.io_bound(read)
        except (ValueError, RuntimeError, OSError) as error:
            if not panel.is_deleted:
                attachment_notice.text = f'{error} 완성본·업로드에서 영상과 예약 회차를 확인하세요.'
            return
        finally:
            attachment_checking = False
        if panel.is_deleted:
            return
        if not info or state.is_busy or state.final_video_path != selected:
            attachment_notice.text = '현재 작업이나 선택한 영상이 바뀌었습니다. 다시 확인하세요.'
            return
        attachment_notice.text = ''
        if attachment_dialog is not None and not attachment_dialog.is_deleted:
            attachment_dialog.delete()
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl bg-slate-900 text-white'):
            ui.label(f'{schedule["name"]} · 비공개 완성본 연결').classes('text-lg font-bold')
            ui.label(Path(info['video_path']).name).classes('text-sm break-all')
            ui.link(f'YouTube {info["youtube_id"]}', f'https://www.youtube.com/shorts/{info["youtube_id"]}', new_tab=True)
            ui.label('파일·대본·출처·비공개 업로드 기록을 대조했습니다. 연결 후에도 검토 대기이며, 채택과 공개는 별도로 결정합니다.').classes('text-sm text-slate-300')
            confirmation_notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')

            def confirm():
                if panel.is_deleted or dialog.is_deleted or not dialog.value:
                    return
                try:
                    if state.is_busy or state.final_video_path != selected:
                        raise ValueError('현재 작업이나 선택한 영상이 바뀌었습니다. 다시 확인하세요.')
                    check_attachment_schedule()
                    manager.record_private_review_copy(schedule['id'], selected,
                        expected_schedule_sha256=schedule_sha256(schedule), expected_video_info=info)
                    dialog.close()
                    on_attached()
                    safe_notify('비공개 완성본을 회차에 연결했습니다. 채택·일정 재개는 아직 하지 않았습니다.', type='positive')
                except (ValueError, RuntimeError, OSError) as error:
                    confirmation_notice.text = f'연결을 중단했습니다: {error}'
                    safe_notify(confirmation_notice.text, type='warning')

            with ui.row().classes('w-full flex-wrap'):
                ui.button('취소', on_click=dialog.close).props('flat').classes('min-h-[44px]')
                ui.button('이 비공개 완성본 연결', on_click=confirm).props('color=teal').classes(
                    'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
        attachment_dialog = dialog
        dialog.open()

    with ui.expansion('현재 회차 상태·연결', on_value_change=opened).classes('w-full') as panel:
        details()
        ui.button('회차 상태 새로고침', on_click=refresh).props('flat icon=refresh').bind_enabled_from(loading, 'value', lambda value: not value)
        if (schedule.get('review_operator') == 'agent' and not schedule.get('enabled')
                and schedule.get('last_result') == 'music_selection_required'):
            render_episode_writer_draft(state, manager, schedule)
        if (schedule.get('review_operator') == 'agent' and not schedule.get('enabled')
                and (schedule.get('last_result') == 'music_selection_required' or can_reassess)):
            ui.button('수정 대본 재평가' if reassessment else '확인한 수정 대본으로 검증 요청 준비',
                      on_click=recovery_preview).props('outline').classes('min-h-[44px]').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and state.is_script_reviewed()
                    and not state.has_unapplied_script_draft())
        if schedule.get('review_operator') == 'agent' and not schedule.get('enabled') and schedule.get('last_result') == 'music_selection_required':
            ui.button('준비된 수정 대본 검증', on_click=revision_validation_preview).props('outline').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy)
        ui.label('예약 회차를 기획 중입니다. 메뉴를 이동해도 실행은 계속되며 저장된 회차에서 결과를 확인합니다.').classes('text-xs text-teal-200').bind_visibility_from(state, 'scheduled_planning_in_progress')
        if (schedule.get('review_operator') == 'agent' and schedule.get('last_result') == 'operator_pending'
                and not schedule.get('enabled') and not schedule.get('last_video_path') and not schedule.get('last_youtube_id')):
            if not schedule.get('direct_url'):
                url = episode_source_url(schedule)
                ui.label(f'이번 회차의 선택 기사 · {url}' if url else '이번 회차 소재 · RSS 자동 발견').classes(
                    'text-sm text-slate-300 break-all')
                ui.button('이번 회차 기사 지정', on_click=choose_episode_source).props('outline').classes(
                    'min-h-[44px]').bind_enabled_from(state, 'is_busy', lambda busy: not busy)
            ui.button('계정 연결 후 기획 재개' if schedule.get('planning_auth_required') else '예약 회차 기획 시작', on_click=plan_preview).props('outline color=teal').bind_enabled_from(
                state, 'is_busy', lambda busy: not busy and not planning_preview['checking'])
            ui.label('예약 기획 예산 확인 중…').classes('text-sm text-slate-300').props('role=status').bind_visibility_from(
                planning_preview, 'checking')
            planning_check = ui.label().classes('text-sm text-amber-200 break-words').props('role=alert')
            planning_check.set_visibility(False)
        if schedule.get('last_result') == 'script_review_pending' and not schedule.get('last_youtube_id') and not schedule.get('enabled'):
            if not schedule.get('last_video_path'):
                if schedule.get('review_operator') == 'agent' and schedule.get('last_episode_id'):
                    render_episode_review_recovery(state, manager, schedule, on_attached, edit=True)
                    render_episode_review_recovery(state, manager, schedule, on_attached)
                ui.label('작업실에서 대본을 수정·적용·확인했다면 이 회차에도 수정본을 저장하세요.').classes('text-xs text-slate-300')
                ui.button('확인한 수정 대본을 회차에 저장', on_click=revision_preview).props('flat icon=save').style('min-height:44px').bind_enabled_from(
                    state, 'is_busy', lambda busy: not busy and state.is_script_reviewed() and not state.has_unapplied_script_draft())
            ui.label('선택한 영상의 비공개 업로드 기록을 확인한 뒤 연결 확인 창을 엽니다.').classes('text-xs text-slate-300')
            ui.button('선택 완성본을 이 회차에 연결', on_click=attach_preview).props('outline color=teal').classes(
                'min-h-[44px]').bind_enabled_from(state, 'is_busy',
                    lambda busy: not busy and not attachment_checking and bool(state.final_video_path))
            attachment_notice = ui.label().classes('text-sm text-amber-200 break-words').props('role=status')
        elif schedule.get('last_youtube_id'):
            ui.label('이미 연결된 검토본을 유지합니다. 다른 영상으로의 교체는 별도 검토가 필요합니다.').classes('text-xs text-slate-400')
    return refresh
