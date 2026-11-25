"""Native episode inspection/attachment uses isolated records, never provider calls."""

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.operator_panel import render_operator_panel
from shorts_maker.gui.components import operator_panel, scheduling_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import google_budget, openai_budget
from shorts_maker.services.operating_budget import begin_episode, episode_path
from shorts_maker.services.operating_status import operator_status
from shorts_maker.services.production_service import script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from test_gui_creation_flows import script


class OperatorPanelTests(IsolatedAsyncioTestCase):
    async def test_auth_block_reason_survives_reopen_without_a_new_auth_or_plan_request(self):
        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'operator_pending', 'last_video_path': None, 'last_youtube_id': None,
            'planning_auth_required': True})
        self.assertTrue(operator_status(self.schedule)['planning_auth_required'])
        before = self.manager.filename.read_bytes()
        with patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as planning:
            for _ in range(2):
                root, refresh = self.render()
                with self.client:
                    await refresh()
                await asyncio.sleep(0)
                self.assertIn('지난 기획 시도', self.text(root))
                self.assertIn('저장된 인증 확인', self.text(root))
                self.assertIn('계정 연결 후 기획 재개', self.text(root))
                root.clear()
            planning.assert_not_awaited()
        self.assertEqual(before, self.manager.filename.read_bytes())

    async def test_music_selection_stop_shows_its_own_reason(self):
        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'planning_auth_required': False})
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('배경음악 선택 필요', self.text(root))
        self.assertNotIn('지난 기획 시도', self.text(root))

    async def test_saved_stop_reason_and_matching_next_action_survive_reopening(self):
        for reason, title, next_step in (
            ('source_unavailable', 'RSS 피드를 읽지 못함', '무료 RSS 기사 조회'),
            ('openai_budget_exceeded', 'OpenAI 예산 확인 필요', '이번 달 기준과 잔여액'),
            ('analysis_failed', '기사 본문 분석 결과 확인 필요', '보관된 분석 응답'),
            ('veo_result_unverified', 'Veo 원본 결과 확인 필요', '공급자 결과와 저장된 장면 파일'),
        ):
            with self.subTest(reason=reason):
                self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_result': reason})
                before = self.manager.filename.read_bytes()
                root, refresh = self.render()
                with self.client:
                    await refresh()
                await asyncio.sleep(0)
                self.assertIn(title, self.text(root))
                self.assertIn(next_step, self.text(root))
                self.assertEqual(before, self.manager.filename.read_bytes())
                root.clear()

    async def test_bound_music_draft_opens_existing_text_after_explicit_confirmation(self):
        from shorts_maker.services.work_drafts import WriterSource, read_work_draft, saved_work_drafts, save_work_draft

        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'last_script': None})
        original_script = script('같은 회차의 편집 전 작성 초안')
        original_text = original_script.model_copy(update={'mood': None}).model_dump_json()
        excerpt = '이 예약 회차에서 작성 모델에 넘긴 발췌입니다.'
        original = save_work_draft(None, original_text, {}, writer_source=WriterSource(
            source_url=original_script.source_url, excerpt=excerpt, episode_id=self.episode['id']))
        save_work_draft(None, original_text, {}, writer_source=WriterSource(
            source_url=original_script.source_url, excerpt='다른 회차', episode_id='1' * 32))
        self.state.load_saved_script(script('기존 작업'))
        key = self.state.script_editor_key()
        self.state.remember_script_draft(key, '{아직 고치는 입력')
        self.state.final_video_path = '/current.mp4'
        protected = [self.manager.filename, original, episode_path(self.episode['id']),
                     google_budget._database_path(), openai_budget._database_path()]
        before = [path.read_bytes() for path in protected]
        self.render()
        with self.client, patch('subprocess.run') as child:
            await self.click_and_wait('이 회차의 작성 초안 확인', 'preview_writer_draft')
            self.assertIn(excerpt, [getattr(e, 'text', '') for e in self.client.elements.values()])
            self.assertEqual(self.state.final_video_path, '/current.mp4')
            self.click('닫기')
            self.click('작성 초안을 작업실에서 열기')
            self.assertEqual(self.state.script.title, '기존 작업')
            await self.click_and_wait('이 회차의 작성 초안 확인', 'preview_writer_draft')
            self.state.remember_script_draft(key, '{그 사이 추가로 고친 입력')
            self.click('작성 초안을 작업실에서 열기')
            self.assertEqual(self.state.script.title, '기존 작업')
            self.click('닫기')
            await self.click_and_wait('이 회차의 작성 초안 확인', 'preview_writer_draft')
            self.click('작성 초안을 작업실에서 열기')
            self.assertIsNone(self.state.script)
            self.assertEqual(self.state.script_editor_text(), original_text)
            self.assertIsNone(self.state.reviewed_script_sha256)
            self.assertIsNone(self.state.operating_scope)
            child.assert_not_called()
        self.assertEqual([path.read_bytes() for path in protected], before)
        self.assertTrue(any(read_work_draft(name)[0].editor_text == '{그 사이 추가로 고친 입력'
                            for name in saved_work_drafts()[0]))

    async def test_music_draft_lookup_rejects_duplicate_exact_episode_sources(self):
        from shorts_maker.services.work_drafts import WriterSource, save_work_draft

        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'last_script': None})
        model = script()
        for text in ('발췌 판본 1', '발췌 판본 2'):
            save_work_draft(None, model.model_dump_json(), {}, writer_source=WriterSource(
                source_url=model.source_url, excerpt=text, episode_id=self.episode['id']))
        root, _ = self.render()
        with self.client:
            await self.click_and_wait('이 회차의 작성 초안 확인', 'preview_writer_draft')
        self.assertIn('정확히 연결된 작성 원문 사본 하나가 필요합니다', self.text(root))
        self.assertFalse(any(getattr(e, 'text', '') == '작성 초안을 작업실에서 열기'
                             for e in self.client.elements.values()))

    async def test_history_distinguishes_due_slot_handoff_and_later_music_stop(self):
        self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'last_script': None,
            'scheduled_for': '2026-11-18T10:06:00', 'queued_at': '2026-11-18T10:06:02.189937',
            'last_run': '2026-11-20T17:20:56.970515',
        })
        before = self.manager.filename.read_bytes()
        with self.client, ui.column() as root, patch.object(scheduling_tab, 'schedule_manager', self.manager), patch.object(
                scheduling_tab, 'load_source_catalog', return_value=(object(), {})), patch.object(ui, 'timer'):
            scheduling_tab.render_scheduling_tab(self.state)
        text = self.text(root)
        for label in ('예약 시각 · 2026-11-18 10:06:00', '제작 대기 생성 · 2026-11-18 10:06:02',
                      '최근 처리 · 2026-11-20 17:20:56', '배경음악 선택 필요'):
            self.assertIn(label, text)
        self.assertEqual(self.manager.filename.read_bytes(), before)

    def prepare_revision(self):
        self.state.load_saved_script(script().model_copy(update={'title': '직접 다듬은 대본'}))
        self.state.confirm_script_review()

    async def test_revision_preview_cancel_and_confirm_are_explicit_and_preserve_review_authority(self):
        self.prepare_revision()
        self.render()
        before = self.manager.filename.read_bytes()
        receipt = self.state.reviewed_script_sha256
        with self.client:
            self.click('확인한 수정 대본을 회차에 저장')
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.click('취소')
            self.click('이 수정 대본으로 회차 저장')
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.click('확인한 수정 대본을 회차에 저장')
            confirms = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 수정 대본으로 회차 저장']
            next(e.handler for e in confirms[-1]._event_listeners.values() if e.type == 'click')(None)
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_script']['title'], '직접 다듬은 대본')
        self.assertEqual(len(current['script_revisions']), 1)
        self.assertEqual(current['last_episode_id'], self.episode['id'])
        self.assertFalse(current['enabled'])
        self.assertEqual(current['last_result'], 'script_review_pending')
        self.assertIsNone(current.get('last_youtube_id'))
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertIsNone(self.state.production_service)
        self.attached.assert_called_once()

    async def test_unapplied_changed_or_busy_revision_dialog_cannot_save(self):
        self.prepare_revision()
        self.render()
        with self.client:
            self.click('확인한 수정 대본을 회차에 저장')
            before = self.manager.filename.read_bytes()
            self.state.remember_script_draft(self.state.script_editor_key(), '{not yet applied')
            self.click('이 수정 대본으로 회차 저장')
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.state.script_editor_drafts.clear()
            self.state.pipeline_running = True
            self.click('이 수정 대본으로 회차 저장')
            self.assertTrue(self.state.pipeline_running)
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.state.pipeline_running = False
            self.state.load_saved_script(script().model_copy(update={'title': '확인 창 이후 수정'}))
            self.state.confirm_script_review()
            self.click('이 수정 대본으로 회차 저장')
            self.assertEqual(before, self.manager.filename.read_bytes())

    async def test_attached_round_has_no_revision_action_and_deleted_view_cannot_save(self):
        self.prepare_revision()
        root, _ = self.render()
        with self.client:
            self.click('확인한 수정 대본을 회차에 저장')
            button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 수정 대본으로 회차 저장')
            confirm = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            before = self.manager.filename.read_bytes()
            root.clear();confirm(None)
            self.assertEqual(before, self.manager.filename.read_bytes())
        self.schedule = self.manager.record_private_review_copy(self.schedule['id'], str(self.video))
        root, _ = self.render()
        self.assertNotIn('확인한 수정 대본을 회차에 저장', self.text(root))

    def pending(self):
        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'operator_pending', 'last_script': None,
            'last_video_path': None, 'last_youtube_id': None})
        settings.paid_production_enabled = True

    async def click_and_wait(self, label, task_name):
        before = asyncio.all_tasks()
        self.click(label)
        tasks = [task for task in asyncio.all_tasks() - before if task_name in task.get_name()]
        self.assertTrue(tasks)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    async def test_planning_preview_is_read_only_and_cancel_does_not_dispatch(self):
        self.pending()
        before = self.manager.filename.read_bytes()
        self.render()
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as plan:
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertEqual(self.manager.filename.read_bytes(), before)
            self.assertIn('OpenAI $0.300000', '\n'.join(getattr(e, 'text', '') for e in self.client.elements.values()))
            self.assertIn('최소 5장면 신규 비주얼 예약 추정', '\n'.join(
                getattr(e, 'text', '') for e in self.client.elements.values()))
            self.click('취소')
            await self.click_and_wait('이 회차 기획 실행', 'confirm')
            plan.assert_not_awaited()
        self.assertFalse(self.state.is_busy)

    async def test_selecting_a_workroom_url_for_this_episode_is_explicit_and_shown_before_paid_dispatch(self):
        self.pending()
        before = self.manager.filename.read_bytes()
        ledgers = [google_budget._database_path(), openai_budget._database_path()]
        ledger_bytes = [path.read_bytes() for path in ledgers]
        self.state.planning_source_mode = '직접 URL 입력'
        self.state.planning_url = 'https://example.com/read-in-workroom'
        self.render()
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as plan:
            self.click('이번 회차 기사 지정')
            field = next(e for e in self.client.elements.values() if e._props.get('label') == '이번 회차 기사 URL')
            self.assertEqual(field.value, self.state.planning_url)
            self.click('취소')
            self.assertEqual(self.manager.filename.read_bytes(), before)
            self.click('이번 회차 기사 지정')
            confirm = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '이번 회차 출처 저장'][-1]
            next(e.handler for e in confirm._event_listeners.values() if e.type == 'click')(None)
            plan.assert_not_awaited()
            self.schedule = self.manager.get_schedule(self.schedule['id'])
            self.assertEqual(self.schedule['episode_source_url'], self.state.planning_url)
            self.assertEqual(self.schedule['last_result'], 'operator_pending')
            self.assertIsNone(self.schedule.get('direct_url'))
            self.client.content.clear()
            self.render()
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertIn('선택 기사 · ' + self.state.planning_url,
                          [getattr(element, 'text', '') for element in self.client.elements.values()])
            plan.assert_not_awaited()
            await self.click_and_wait('이 회차 기획 실행', 'confirm')
            plan.assert_awaited_once_with(self.manager, self.schedule)
        self.assertEqual(ledger_bytes, [path.read_bytes() for path in ledgers])

    async def test_rapid_planning_clicks_open_one_confirmation_and_allow_new_check_after_cancel(self):
        self.pending()
        self.render()
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_check(*args):
            entered.set()
            await release.wait()
            return {'google_remaining_krw': 3000, 'openai_remaining_usd': .3,
                    'minimum_visual_scenes': 5, 'minimum_visual_reservation_krw': 636}

        with self.client, patch.object(operator_panel.run, 'io_bound', side_effect=delayed_check) as check:
            before = asyncio.all_tasks()
            self.click('예약 회차 기획 시작')
            await asyncio.wait_for(entered.wait(), 3)
            self.click('예약 회차 기획 시작')
            await asyncio.sleep(0)
            release.set()
            await asyncio.wait_for(asyncio.gather(*(
                task for task in asyncio.all_tasks() - before if 'plan_preview' in task.get_name()
            )), 3)
            self.assertEqual(check.await_count, 1)
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertEqual(check.await_count, 1)
            self.click('취소')
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertEqual(check.await_count, 2)
            buttons = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 회차 기획 실행']
            self.assertEqual(len(buttons), 1)

    async def test_stale_month_explains_provider_at_planning_button_and_clears_on_recheck(self):
        self.pending()
        root, _ = self.render()
        before = self.manager.filename.read_bytes()
        ledgers = [google_budget._database_path(), openai_budget._database_path()]
        ledger_bytes = [path.read_bytes() for path in ledgers]
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as plan:
            with patch.object(settings, 'google_budget_month', '2020-01'):
                await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
                self.assertIn('이번 달 Google 사용액 기준을 다시 설정하세요', self.text(root))
                self.assertFalse(any(getattr(e, 'text', '') == '이 회차 기획 실행'
                                     for e in self.client.elements.values()))
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertNotIn('이번 달 Google 사용액 기준을 다시 설정하세요', self.text(root))
            self.click('취소')
            plan.assert_not_awaited()
        self.assertEqual(before, self.manager.filename.read_bytes())
        self.assertEqual(ledger_bytes, [path.read_bytes() for path in ledgers])

    async def test_planning_dialog_explains_minimum_visual_shortfall_and_recovers_on_recheck(self):
        self.pending()
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'mode': 'video'})
        root, _ = self.render()
        before = self.manager.filename.read_bytes()
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as plan:
            with patch.object(settings, 'google_budget_opening_krw', 8000):
                await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
                self.assertIn('₩2,404가 필요합니다', self.text(root))
                self.assertIn('₩2,000', self.text(root))
                self.assertFalse(any(getattr(e, 'text', '') == '이 회차 기획 실행'
                                     for e in self.client.elements.values()))
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.assertNotIn('₩2,404가 필요합니다', self.text(root))
            self.assertIn('₩2,404', self.text(root))
            self.click('취소')
            plan.assert_not_awaited()
        self.assertEqual(self.manager.filename.read_bytes(), before)

    async def test_music_stop_can_prepare_its_saved_source_in_studio_without_a_paid_request(self):
        from shorts_maker.services.audio_choices import save_audio_choices
        from shorts_maker.services.revision_validation import prepared_revision
        from shorts_maker.services.work_drafts import WriterSource, save_work_draft

        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'last_script': None})
        candidate = script('음악 설정을 수정한 대본')
        candidate.scenes = [candidate.scenes[0].model_copy(update={'scene_number': n})
                            for n in range(1, 6)]
        exact_excerpt = '이 회차의 작성기에 넘긴 원문입니다.'
        original = save_work_draft(None, candidate.model_copy(
            update={'title': '원래 대본', 'mood': None}).model_dump_json(), {},
            writer_source=WriterSource(source_url=candidate.source_url, excerpt=exact_excerpt,
                                       episode_id=self.episode['id']))
        save_audio_choices(candidate, {'tts_voice': 'nova', 'bgm_mood': 'auto',
                                       'bgm_track': '', 'bgm_volume': 0})
        self.state.load_saved_script(candidate)
        self.state.confirm_script_review()
        self.render()
        request = episode_path(self.episode['id']).with_suffix('.revision-request.json')
        protected = [original, self.manager.filename, google_budget._database_path(), openai_budget._database_path()]
        before = [path.read_bytes() for path in protected]
        with self.client, patch.object(settings, 'paid_production_enabled', True), \
                patch('subprocess.run') as child:
            await self.click_and_wait('확인한 수정 대본으로 검증 요청 준비', 'recovery_preview')
            self.assertIn(exact_excerpt, [getattr(e, 'text', '') for e in self.client.elements.values()])
            self.assertFalse(request.exists())
            changed = json.loads(before[0])
            changed['writer_source']['excerpt'] = '다른 원문'
            original.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')
            with patch.object(operator_panel, 'safe_notify') as notify:
                await self.click_and_wait('원문 확인 · 검증 요청 저장', 'save')
                self.assertIn('원문이나 검증 견적이 바뀌었습니다', notify.call_args.args[0])
            self.assertFalse(request.exists())
            original.write_bytes(before[0])
            await self.click_and_wait('원문 확인 · 검증 요청 저장', 'save')
            saved = request.read_bytes()
            digest, draft, amount = prepared_revision(self.manager, self.schedule)
            self.assertEqual(hashlib.sha256(saved).hexdigest(), digest)
            self.assertEqual(draft, candidate)
            self.assertGreater(float(amount), 0)
            await self.click_and_wait('준비된 수정 대본 검증', 'revision_validation_preview')
            self.assertIn('수정 대본 1회 검증', [getattr(e, 'text', '') for e in self.client.elements.values()])
            child.assert_not_called()
        self.assertEqual(before, [path.read_bytes() for path in protected])
        self.assertEqual(request.read_bytes(), saved)
        self.assertFalse(request.with_suffix('.started').exists())

    async def test_studio_reassessment_blocks_unknown_results_and_requires_explicit_confirmation(self):
        from shorts_maker.services.audio_choices import save_audio_choices
        from shorts_maker.services import revision_validation as recovery
        from shorts_maker.services.work_drafts import WriterSource, save_work_draft
        from shorts_maker.services.scheduled_script_history import validated_revisions
        self.enterContext(patch.object(settings, 'scripts_dir', self.root / 'scripts'))

        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'last_result': 'music_selection_required', 'last_script': None})
        rejected = script('처음 검증한 대본')
        rejected.scenes = [rejected.scenes[0].model_copy(update={'scene_number': n})
                           for n in range(1, 6)]
        excerpt = '원문에서는 손님이 지붕 아래에서 식사했다고 설명했습니다.'
        save_work_draft(None, rejected.model_dump_json(), {},
                        writer_source=WriterSource(source_url=rejected.source_url, excerpt=excerpt,
                                                   episode_id=self.episode['id']))
        choices = {'tts_voice': 'nova', 'bgm_mood': 'auto', 'bgm_track': '', 'bgm_volume': 0}
        save_audio_choices(rejected, choices)
        recovery.prepare_recovery(self.manager, self.schedule, rejected,
                                  recovery.preview_recovery(self.manager, self.schedule, rejected))
        base = episode_path(self.episode['id'])
        request = base.with_suffix('.revision-request.json')
        request.with_suffix('.started').write_text(hashlib.sha256(request.read_bytes()).hexdigest())
        reviews = settings.scripts_dir / 'reviews'
        reviews.mkdir(parents=True)
        model_request, verdict = reviews / 'review_fixture.request.json', reviews / 'review_fixture.verdict.json'
        model_request.write_text(json.dumps({'script': rejected.model_dump(),
            'script_json_sha256': script_sha256(rejected.model_dump()), 'source_excerpt': excerpt,
            'source_sha256': hashlib.sha256(excerpt.encode()).hexdigest(),
            'validator_model': recovery.PRIMARY_CHAT_MODEL}))
        verdict.write_text(json.dumps({'is_valid': False, 'reason': 'unsupported_claim', 'score': 62,
                                       'feedback': '원문 표현을 확인하세요.'}))
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_result': 'planning_failed'})
        corrected = rejected.model_copy(update={'title': '원문에 맞게 고친 대본'})
        save_audio_choices(corrected, choices)
        self.state.load_saved_script(corrected)
        self.state.confirm_script_review()
        self.render()
        protected = [base, request, model_request, verdict,
                     google_budget._database_path(), openai_budget._database_path()]
        before = [path.read_bytes() for path in protected]
        with self.client, patch('subprocess.run') as child, patch.object(operator_panel, 'safe_notify') as notify:
            await self.click_and_wait('수정 대본 재평가', 'recovery_preview')
            visible = [getattr(e, 'text', '') for e in self.client.elements.values()]
            self.assertIn('이전 모델 미통과 · 62점', visible)
            self.assertIn(excerpt, visible)
            note = next(e for e in self.client.elements.values() if
                        getattr(e, 'label', '') == '원문을 대조한 뒤 이 수정 대본을 채택하는 이유')
            await self.click_and_wait('재평가한 수정 대본 채택', 'save')
            self.assertIn('채택하는 이유', notify.call_args.args[0])
            note.set_value('기사 내용과 수정 대본을 대조했습니다.')
            pending = base.with_suffix('.operation.pending.json')
            pending.symlink_to(self.root / 'missing.json')
            await self.click_and_wait('재평가한 수정 대본 채택', 'save')
            self.assertIn('대조', notify.call_args.args[0])
            self.assertEqual(self.manager.get_schedule(self.schedule['id']), self.schedule)
            pending.unlink()
            await self.click_and_wait('재평가한 수정 대본 채택', 'save')
            child.assert_not_called()
        result = self.manager.get_schedule(self.schedule['id'])
        self.assertFalse(result['enabled'])
        self.assertEqual(result['last_result'], 'script_review_pending')
        self.assertEqual(result['last_episode_id'], self.episode['id'])
        self.assertIsNone(result.get('last_youtube_id'))
        self.assertTrue(operator_status(result)['script_reassessment'])
        self.assertEqual(result['script_revisions'][0]['reassessment']['model_verdict']['score'], 62)
        validated_revisions(result['last_script'], result['script_revisions'])
        self.state.load_scheduled_script(self.manager, self.schedule['id'])
        self.assertEqual(self.state.script, corrected)
        self.assertEqual(before, [path.read_bytes() for path in protected])

    async def test_planning_runs_once_through_navigation_without_replacing_user_work(self):
        self.pending()
        original_script = self.state.script.model_dump_json()
        self.state.remember_script_draft(self.state.script_editor_key(), '미적용 입력 유지')
        root, _ = self.render()
        entered, release = asyncio.Event(), asyncio.Event()
        async def complete(*args):
            entered.set()
            await release.wait()
            return self.manager.update_schedule(self.schedule['id'], {
                'last_result': 'script_review_pending', 'last_script': script().model_dump(mode='json')})
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', side_effect=complete) as plan:
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            before = asyncio.all_tasks()
            self.click('이 회차 기획 실행')
            tasks = [task for task in asyncio.all_tasks() - before if 'confirm' in task.get_name()]
            await asyncio.wait_for(entered.wait(), 3)
            self.assertTrue(self.state.is_busy)
            root.clear()
            self.render()
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            plan.assert_awaited_once()
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 3)
        self.assertFalse(self.state.is_busy)
        self.assertEqual(self.state.script.model_dump_json(), original_script)
        self.assertEqual(self.state.script_editor_text(), '미적용 입력 유지')
        self.assertEqual(self.manager.get_schedule(self.schedule['id'])['last_result'], 'script_review_pending')
        self.attached.assert_called_once()

    async def test_stale_or_busy_planning_dialog_does_not_clear_another_running_operation(self):
        self.pending()
        self.render()
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock) as plan:
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            self.state.scheduled_planning_in_progress = True
            await self.click_and_wait('이 회차 기획 실행', 'confirm')
            self.assertTrue(self.state.scheduled_planning_in_progress)
            plan.assert_not_awaited()
            self.state.scheduled_planning_in_progress = False
            self.manager.update_schedule(self.schedule['id'], {'name': '다른 설정으로 수정됨'})
            await self.click_and_wait('이 회차 기획 실행', 'confirm')
            plan.assert_not_awaited()

    async def test_failed_planning_releases_ui_busy_without_accepting_or_retrying(self):
        self.pending()
        before = self.manager.filename.read_bytes()
        self.render()
        with self.client, patch.object(operator_panel, 'plan_pending_schedule', new_callable=AsyncMock,
                                       side_effect=RuntimeError('YOUTUBE_AUTH_REQUIRED')) as plan:
            await self.click_and_wait('예약 회차 기획 시작', 'plan_preview')
            await self.click_and_wait('이 회차 기획 실행', 'confirm')
            plan.assert_awaited_once()
        self.assertFalse(self.state.is_busy)
        self.assertEqual(before, self.manager.filename.read_bytes())
        self.assertIsNone(self.manager.get_schedule(self.schedule['id']).get('last_youtube_id'))

    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        for name, value in [('output_dir', self.root / 'outputs'),
                            ('google_monthly_budget_krw', 10000), ('google_budget_opening_krw', 0),
                            ('google_budget_month', google_budget._period()), ('google_usd_krw_rate', 2000),
                            ('openai_monthly_budget_usd', 1.0), ('openai_budget_opening_usd', 0),
                            ('openai_budget_month', openai_budget._period()), ('paid_production_enabled', False)]:
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        loop = patch.object(core, 'loop', asyncio.get_running_loop())
        loop.start()
        self.addCleanup(loop.stop)
        self.client = Client(page('/operator-panel'))
        self.addCleanup(self.client.delete)
        google_budget.initialize_google_budget()
        openai_budget.initialize_openai_budget()
        self.manager = ScheduleManager(str(self.root / 'schedules.json'), queue_only=True)
        scheduled = self.manager.create_schedule('UI 회차', '19:00', frequency='Every 2 Weeks')
        self.schedule = self.manager.update_schedule(scheduled['id'], {
            'review_operator': 'agent', 'enabled': False, 'run_count': 1,
            'last_result': 'script_review_pending', 'last_script': script().model_dump(mode='json')})
        self.episode = begin_episode(self.schedule['id'], 1)
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_episode_id': self.episode['id']})
        self.video = settings.output_dir / 'review.mp4'
        self.video.write_bytes(b'isolated metadata fixture, not an encoded video')
        self.report = self.video.with_suffix('.production.json')
        self.report.write_text(json.dumps({
            'schema_version': 1, 'video_path': str(self.video), 'source_url': script().source_url,
            'script_sha256': script_sha256(self.schedule['last_script']), 'quality_passed': True,
            'video_sha256': hashlib.sha256(self.video.read_bytes()).hexdigest(),
            'youtube_id': 'private_test_12', 'youtube_upload_request': {'status': {'privacyStatus': 'private'}},
            'uploaded_at_utc': '2026-11-10T00:00:00Z'}))
        self.state = AppState(script=script(), final_video_path=str(self.video))
        self.attached = Mock()

    def render(self):
        with self.client, ui.column() as root:
            refresh = render_operator_panel(self.state, self.manager, self.schedule, self.attached)
        return root, refresh

    def saved_upload(self, *, scope_episode=None, id_in_receipt='private_test_12', operation='upload'):
        from shorts_maker.services import studio_episode_action as action
        from shorts_maker.services.operating_status import schedule_sha256
        from shorts_maker.services.production_service import ProductionResult
        from shorts_maker.services.work_drafts import script_draft_key

        saved_script = script()
        request = action.StudioAction(
            scope=action.EpisodeScope(schedules_file=str(self.manager.filename.resolve()),
                schedule_id=self.schedule['id'], episode_id=scope_episode or self.episode['id']),
            operation=operation, schedule_sha256=schedule_sha256(self.schedule),
            script_sha256=script_sha256(self.schedule['last_script']), review_receipt=script_draft_key(saved_script),
            mode=self.schedule['mode'], image_model=settings.image_model_id,
            video_path=str(self.video) if operation == 'upload' else None,
        )
        directory = action.action_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{uuid4().hex}.request.json'
        raw = request.model_dump_json().encode('utf-8')
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        result_path = path.with_suffix('.result.json')
        result_path.write_text(json.dumps({'request_sha256': digest, 'status': 'returned', 'kind': 'production',
            'value': asdict(ProductionResult(success=True, video_path=str(self.video),
                                            youtube_id=id_in_receipt, ready_for_upload=True,
                                            report_path=str(self.report)))}))
        base = episode_path(self.episode['id'])
        audit = base.with_suffix(f'.operation.{uuid4().hex}.json')
        command_sha256 = hashlib.sha256(json.dumps(action.worker_command(path, digest)).encode()).hexdigest()
        audit.write_text(json.dumps({'command_sha256': command_sha256, 'returncode': 0}))
        return result_path, audit

    def saved_edit(self):
        report = json.loads(self.report.read_text())
        for key in ('youtube_id', 'youtube_upload_request', 'uploaded_at_utc'):
            report.pop(key)
        self.report.write_text(json.dumps(report))
        return self.saved_upload(operation='edit', id_in_receipt=None)

    async def test_edit_lookup_excludes_upload_evidence_pending_files_and_changed_bytes(self):
        from shorts_maker.services.episode_review_recovery import recovered_episode_edits

        self.saved_upload()
        self.assertEqual(recovered_episode_edits(self.manager, self.schedule), {})
        _, audit = self.saved_edit()
        self.assertEqual(list(recovered_episode_edits(self.manager, self.schedule)), [str(self.video)])
        original_report = self.report.read_text()
        report = json.loads(original_report)
        report['uploaded_at_utc'] = '2026-11-10T00:00:00Z'
        self.report.write_text(json.dumps(report))
        self.assertEqual(recovered_episode_edits(self.manager, self.schedule), {})
        self.report.write_text(original_report)
        pending = self.video.with_suffix('.upload-pending.json')
        pending.symlink_to(pending.with_name('missing'))
        self.assertEqual(recovered_episode_edits(self.manager, self.schedule), {})
        pending.unlink()
        original_video = self.video.read_bytes()
        self.video.write_bytes(b'different bytes')
        self.assertEqual(recovered_episode_edits(self.manager, self.schedule), {})
        self.video.write_bytes(original_video)
        audit.write_text('{}')
        self.assertEqual(recovered_episode_edits(self.manager, self.schedule), {})

    async def test_edit_recovery_explicitly_opens_same_episode_without_writes_or_dispatch(self):
        self.state = AppState()
        self.saved_edit()
        protected = [self.manager.filename, self.video, self.report, episode_path(self.episode['id']),
                     google_budget._database_path(), openai_budget._database_path()]
        before = [path.read_bytes() for path in protected]
        self.render()
        with self.client, patch('subprocess.run') as process:
            await self.click_and_wait('이 회차의 편집한 완성본 찾기', 'find_copies')
            chooser = next(e for e in self.client.elements.values() if e._props.get('label') == '편집한 완성본')
            self.assertIsNone(chooser.value)
            chooser.value = str(self.video)
            self.click('닫기')
            self.assertIsNone(self.state.final_video_path)
            self.assertIsNone(self.state.operating_scope)
            await self.click_and_wait('이 회차의 편집한 완성본 찾기', 'find_copies')
            chooser = next(e for e in self.client.elements.values() if e._props.get('label') == '편집한 완성본')
            chooser.value = str(self.video)
            await self.click_and_wait('선택한 완성본 열기', 'attach')
            process.assert_not_called()
        self.assertEqual(self.state.final_video_path, str(self.video))
        self.assertEqual(self.state.operating_scope['episode_id'], self.episode['id'])
        self.assertEqual(self.state.script, script())
        self.assertFalse(self.state.is_script_reviewed())
        self.state.confirm_script_review()
        self.assertEqual(self.state.final_video_path, str(self.video))
        self.assertEqual([path.read_bytes() for path in protected], before)

    async def test_edit_recovery_rejects_changed_schedule_before_switching_workspace(self):
        self.saved_edit()
        self.state.final_video_path = None
        root, _ = self.render()
        with self.client:
            await self.click_and_wait('이 회차의 편집한 완성본 찾기', 'find_copies')
            chooser = next(e for e in self.client.elements.values() if e._props.get('label') == '편집한 완성본')
            chooser.value = str(self.video)
            self.manager.update_schedule(self.schedule['id'], {'name': '다른 회차 상태'})
            await self.click_and_wait('선택한 완성본 열기', 'attach')
        self.assertIn('회차 상태가 변경', self.text(root))
        self.assertIsNone(self.state.operating_scope)
        self.assertIsNone(self.state.final_video_path)

    async def test_recovered_upload_checks_same_episode_audit_receipt_report_and_pending_state(self):
        from shorts_maker.services.episode_review_recovery import recovered_review_copies, attach_recovered_review_copy

        self.saved_upload(scope_episode='1' * 32)
        self.saved_upload(id_in_receipt='different_id')
        self.assertEqual(recovered_review_copies(self.manager, self.schedule), {})
        result, audit = self.saved_upload()
        valid = audit.read_bytes()
        audit.write_text('{}')
        self.assertEqual(recovered_review_copies(self.manager, self.schedule), {})
        audit.write_bytes(valid)
        copies = recovered_review_copies(self.manager, self.schedule)
        self.assertEqual(list(copies), [str(self.video)])
        before = self.manager.filename.read_bytes()
        valid = result.read_bytes()
        result.write_text('{}')
        with self.assertRaisesRegex(ValueError, '업로드 기록이 변경'):
            attach_recovered_review_copy(self.manager, self.schedule, copies[str(self.video)])
        result.write_bytes(valid)
        pending = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        pending.symlink_to(pending.with_name('missing'))
        with self.assertRaisesRegex(ValueError, '실행 결과'):
            recovered_review_copies(self.manager, self.schedule)
        pending.unlink()
        pending = self.video.with_suffix('.upload-pending.json')
        pending.symlink_to(pending.with_name('missing'))
        self.assertEqual(recovered_review_copies(self.manager, self.schedule), {})
        self.assertEqual(self.manager.filename.read_bytes(), before)

    async def test_recovered_upload_can_attach_explicitly_with_no_current_video_selection(self):
        self.state.final_video_path = None
        self.saved_upload()
        protected = [self.video, self.report, episode_path(self.episode['id']),
                     google_budget._database_path(), openai_budget._database_path()]
        before = [path.read_bytes() for path in protected]
        self.render()
        schedule_bytes = self.manager.filename.read_bytes()
        with self.client, patch('subprocess.run') as process:
            await self.click_and_wait('이 회차의 업로드한 검토본 찾기', 'find_copies')
            chooser = next(e for e in self.client.elements.values() if e._props.get('label') == '완료된 검토본')
            self.assertIsNone(chooser.value)
            chooser.value = str(self.video)
            self.click('닫기')
            self.assertEqual(self.manager.filename.read_bytes(), schedule_bytes)
            await self.click_and_wait('이 회차의 업로드한 검토본 찾기', 'find_copies')
            chooser = next(e for e in self.client.elements.values() if e._props.get('label') == '완료된 검토본')
            chooser.value = str(self.video)
            await self.click_and_wait('선택한 저장 검토본 연결', 'attach')
            process.assert_not_called()
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertFalse(current['enabled'])
        self.assertEqual(current['last_result'], 'script_review_pending')
        self.assertNotIn('accepted_at', current)
        self.assertIsNone(self.state.final_video_path)
        self.assertEqual([path.read_bytes() for path in protected], before)

    def click(self, text):
        button = next(e for e in self.client.elements.values() if getattr(e, 'text', '') == text)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    def text(self, root):
        return '\n'.join(getattr(e, 'text', '') for e in root.descendants())

    async def test_read_only_status_uses_existing_reserves_and_does_not_start_or_reset_episode(self):
        request = google_budget.reserve_google_output('video', 'veo-3.1-lite-generate-001', 4)
        google_budget.mark_google_result(request, 'failed')
        paths = [self.manager.filename, episode_path(self.episode['id']),
                 google_budget._database_path(), openai_budget._database_path()]
        before = [p.read_bytes() for p in paths]
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('Google 회차 누적 예약 ₩240', self.text(root))
        self.assertIn('전체 상한까지 여유 ₩2,760', self.text(root))
        self.assertIn('새 지출 허가가 아닙니다', self.text(root))
        self.assertEqual(operator_status(self.schedule)['budget']['google_new_reserved_krw'], 240)
        self.assertEqual(before, [p.read_bytes() for p in paths])

    async def test_preview_then_attach_is_explicit_and_keeps_owner_acceptance_pending(self):
        self.render()
        before = self.manager.filename.read_bytes()
        with self.client:
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            self.assertEqual(self.manager.filename.read_bytes(), before)
            self.click('이 비공개 완성본 연결')
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertEqual(current['last_video_path'], str(self.video))
        self.assertEqual(current['last_result'], 'script_review_pending')
        self.assertFalse(current['enabled'])
        self.assertNotIn('accepted_at', current)
        self.attached.assert_called_once()

    async def test_external_lock_keeps_confirmation_selection_and_schedule_for_explicit_retry(self):
        self.render()
        before=self.manager.filename.read_bytes()
        with self.client, patch.object(operator_panel,'safe_notify') as notify:
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            dialog=next(e for e in self.client.elements.values() if type(e).__name__=='Dialog')
            db=sqlite3.connect(self.manager.filename.with_name(self.manager.filename.name+'.lock.sqlite3'),isolation_level=None)
            try:
                db.execute('BEGIN EXCLUSIVE')
                self.click('이 비공개 완성본 연결')
                self.assertEqual(before,self.manager.filename.read_bytes())
                self.assertEqual(self.state.final_video_path,str(self.video))
                self.assertTrue(dialog.value)
                self.attached.assert_not_called()
                self.assertIn('다른 회차',notify.call_args.args[0])
            finally:
                db.close()
            self.click('이 비공개 완성본 연결')
            self.assertFalse(dialog.value)
        current=self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'],'private_test_12')
        self.assertNotIn('accepted_at',current)
        self.attached.assert_called_once()

    async def test_attachment_does_not_commit_a_new_upload_seen_only_inside_the_lock(self):
        self.render()
        before = self.manager.filename.read_bytes()
        real_attach = self.manager.record_private_review_copy

        def replace_upload_before_write(*args, **kwargs):
            report = json.loads(self.report.read_text())
            report['youtube_id'] = 'replacement_12'
            self.report.write_text(json.dumps(report))
            return real_attach(*args, **kwargs)

        with self.client, patch.object(self.manager, 'record_private_review_copy',
                                       side_effect=replace_upload_before_write):
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            self.click('이 비공개 완성본 연결')
        self.assertEqual(self.manager.filename.read_bytes(), before)
        self.attached.assert_not_called()

    async def test_completed_upload_with_retained_claim_can_be_attached_without_removing_claim(self):
        from shorts_maker.services.episode_review_recovery import recovered_review_copies
        from shorts_maker.services.production_service import ProductionService
        from shorts_maker.uploader.youtube_uploader import YouTubeUploader

        upload = YouTubeUploader.build_upload_body({
            'title': '검토본', 'description': '출처: https://example.com/news', 'contains_synthetic_media': False})
        cut = json.loads(self.report.read_text())
        cut.update(youtube_id=None, youtube_upload_request=None, uploaded_at_utc=None)
        self.report.write_text(json.dumps(cut))
        marker = ProductionService._claim_upload(str(self.video), cut['video_sha256'], upload)
        original = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, '업로드 결과를 먼저 대조'):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))
        self.assertIsNotNone(ProductionService()._record_upload(str(self.video), 'private_test_12', upload))
        self.saved_upload()
        self.assertEqual(list(recovered_review_copies(self.manager, self.schedule)), [str(self.video)])
        self.render()
        with self.client:
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            self.click('이 비공개 완성본 연결')
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertFalse(current['enabled'])
        self.assertNotIn('accepted_at', current)
        self.assertEqual(marker.read_bytes(), original)

    async def test_unuploaded_selection_explains_next_step_in_the_episode_panel(self):
        self.saved_edit()
        root, _ = self.render()
        before = self.manager.filename.read_bytes()
        with self.client:
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
        self.assertIn('완성본·업로드에서 영상과 예약 회차를 확인하세요.', self.text(root))
        self.assertIn('확인된 YouTube 비공개 업로드 기록이 필요합니다.', self.text(root))
        self.assertEqual(self.manager.filename.read_bytes(), before)

    async def test_deleted_panel_drops_a_late_attachment_preview(self):
        root, _ = self.render()
        entered, release = asyncio.Event(), asyncio.Event()
        before = self.manager.filename.read_bytes()
        preview = self.manager.pending_video_info(self.schedule['id'], str(self.video))

        async def delayed_read(_):
            entered.set()
            await release.wait()
            return preview

        with self.client, patch.object(operator_panel.run, 'io_bound', side_effect=delayed_read):
            task = asyncio.create_task(self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview'))
            await asyncio.wait_for(entered.wait(), timeout=3)
            root.clear()
            release.set()
            await task
        self.assertFalse(any(isinstance(e, ui.dialog) for e in self.client.elements.values()))
        self.assertEqual(self.manager.filename.read_bytes(), before)

    async def test_cancelled_or_stale_selection_and_episode_cannot_attach(self):
        self.render()
        before = self.manager.filename.read_bytes()
        with self.client:
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            self.click('취소')
            self.click('이 비공개 완성본 연결')
            self.assertEqual(before, self.manager.filename.read_bytes())
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            # Target the new dialog; closed prior dialogs retain widgets until client cleanup.
            confirms = [e for e in self.client.elements.values() if getattr(e, 'text', '') == '이 비공개 완성본 연결']
            confirm = next(e.handler for e in confirms[-1]._event_listeners.values() if e.type == 'click')
            self.state.final_video_path = 'different.mp4'
            confirm(None)
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.state.final_video_path = str(self.video)
            report = json.loads(self.report.read_text())
            report['youtube_id'] = 'changed_test_12'
            self.report.write_text(json.dumps(report))
            confirm(None)
            self.assertEqual(before, self.manager.filename.read_bytes())
            self.manager.update_schedule(self.schedule['id'], {'last_result': 'script_rejected'})
            changed = self.manager.filename.read_bytes()
            confirm(None)
            self.assertEqual(changed, self.manager.filename.read_bytes())
        self.attached.assert_not_called()

    async def test_pending_operations_uploads_and_external_reports_block_preview_attach_and_acceptance(self):
        operation = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        upload = self.video.with_suffix('.upload-pending.json')
        for marker in (operation, upload):
            marker.write_text('{}')
            before = self.manager.filename.read_bytes()
            for action in (self.manager.pending_video_info, self.manager.record_private_review_copy,
                           self.manager.accept_pending_video):
                with self.assertRaises(ValueError):
                    action(self.schedule['id'], str(self.video))
            self.assertEqual(before, self.manager.filename.read_bytes())
            marker.unlink()
        operation.write_text('{}')
        changed_actor = self.manager.update_schedule(self.schedule['id'], {'review_operator': None})
        self.assertTrue(operator_status(changed_actor)['operation_pending_unverified'])
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))
        operation.unlink()
        external = self.root / 'outside-output.json'
        self.report.rename(external)
        self.report.symlink_to(external)
        with self.assertRaises(ValueError):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))

    async def test_broken_operation_marker_is_reported_and_blocks_attachment(self):
        marker = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        marker.symlink_to(self.root / 'unavailable-operation-record.json')
        before = self.manager.filename.read_bytes()
        self.assertTrue(operator_status(self.schedule)['operation_pending_unverified'])
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('실행 결과 대조 필요', self.text(root))
        with self.assertRaisesRegex(ValueError, '미확인 실행'):
            self.manager.pending_video_info(self.schedule['id'], str(self.video))
        self.assertTrue(marker.is_symlink())
        self.assertEqual(before, self.manager.filename.read_bytes())

    async def test_failed_status_does_not_invent_budget_and_attached_episode_has_no_replace_control(self):
        operation = episode_path(self.episode['id']).with_suffix('.operation.pending.json')
        operation.write_text('{}')
        episode_path(self.episode['id']).write_text('{invalid')
        status = operator_status(self.schedule)
        self.assertTrue(status['operation_pending_unverified'])
        self.assertIn('budget_error', status)
        self.assertNotIn('budget', status)
        self.schedule = self.manager.update_schedule(self.schedule['id'], {'last_youtube_id': 'already_set_12'})
        root, refresh = self.render()
        with self.client:
            await refresh()
        await asyncio.sleep(0)
        self.assertIn('회차 비용 확인 필요', self.text(root))
        self.assertNotIn('선택 완성본을 이 회차에 연결', self.text(root))

    async def test_unchanged_schedule_poll_preserves_live_panel_and_dialog_but_changed_records_refresh(self):
        with self.client, ui.column() as root, patch.object(scheduling_tab, 'schedule_manager', self.manager), patch.object(
                scheduling_tab, 'load_source_catalog', return_value=(object(), {})), patch.object(ui, 'timer') as timers:
            scheduling_tab.render_scheduling_tab(self.state)
            poll = next(call.args[1] for call in timers.call_args_list
                        if call.args[1].__name__ == 'refresh_changed_records')
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            dialog = next(e for e in self.client.elements.values() if isinstance(e, ui.dialog))
            attach_button = next(e for e in root.descendants() if getattr(e, 'text', '') == '선택 완성본을 이 회차에 연결')
            poll()
            await asyncio.sleep(0)
            self.assertTrue(dialog.value)
            self.assertFalse(dialog.is_deleted)
            self.assertFalse(attach_button.is_deleted)
            self.manager.update_schedule(self.schedule['id'], {'last_result': 'script_rejected'})
            poll()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertTrue(attach_button.is_deleted)

    async def test_direct_studio_schedule_can_attach_without_creating_an_agent_budget(self):
        self.schedule = self.manager.update_schedule(self.schedule['id'], {
            'review_operator': None, 'last_episode_id': None})
        before = set((settings.output_dir / 'evaluation/operating_episodes').iterdir())
        root, refresh = self.render()
        with self.client:
            await refresh()
            await asyncio.sleep(0)
            await self.click_and_wait('선택 완성본을 이 회차에 연결', 'attach_preview')
            self.click('이 비공개 완성본 연결')
        self.assertIn('Studio 직접 실행 일정', self.text(root))
        self.assertEqual(before, set((settings.output_dir / 'evaluation/operating_episodes').iterdir()))
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['last_youtube_id'], 'private_test_12')
        self.assertFalse(current['enabled'])
