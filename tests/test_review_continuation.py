"""Review deferral keeps cadence, outputs and budgets without inventing adoption."""
import asyncio
import hashlib
import json
import tempfile
import subprocess
import sqlite3
import sys
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
from zoneinfo import ZoneInfo
from nicegui import core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.review_continuation import render_review_acceptance, render_review_continuation
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.services import google_budget,openai_budget
from shorts_maker.services.operating_budget import begin_episode,episode_path
from shorts_maker.services.operating_status import schedule_sha256
from shorts_maker.services.production_service import script_sha256
from shorts_maker.utils.config import settings
from shorts_maker.utils.scheduler import ScheduleManager
from test_gui_creation_flows import script


class ReviewContinuationTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        for key,value in [('output_dir',self.root),('paid_production_enabled',False),
            ('google_monthly_budget_krw',10000),('google_budget_opening_krw',0),('google_budget_month',google_budget._period()),
            ('openai_monthly_budget_usd',1.),('openai_budget_opening_usd',0.),('openai_budget_month',openai_budget._period())]:
            self.enterContext(patch.object(settings,key,value))
        google_budget.initialize_google_budget();openai_budget.initialize_openai_budget()
        self.manager=ScheduleManager(str(self.root/'schedules.json'),queue_only=True)
        self.first=datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None,microsecond=0)-timedelta(days=1)
        s=self.manager.create_schedule('정기 제작','10:06',frequency='Every 2 Weeks')
        self.manager.update_schedule(s['id'],{'first_run_at':self.first.isoformat(),'review_operator':'agent'})
        asyncio.run(self.manager.queue_overdue())
        current=self.manager.get_schedule(s['id'])
        episode=begin_episode(s['id'],current['run_count'])
        model=script().model_dump(mode='json')
        self.video=self.root/'review.mp4';self.video.write_bytes(b'fixture video')
        self.report=self.video.with_suffix('.production.json')
        self.report.write_text(json.dumps({'video_path':str(self.video),'source_url':model['source_url'],
            'script_sha256':script_sha256(model),'quality_passed':True,
            'video_sha256':hashlib.sha256(self.video.read_bytes()).hexdigest(),'youtube_id':'fixture_private',
            'youtube_upload_request':{'status':{'privacyStatus':'private'}},'uploaded_at_utc':'2026-11-01T00:00:00Z'}))
        self.manager.update_schedule(s['id'],{'last_script':model,'last_result':'script_review_pending','last_episode_id':episode['id']})
        self.schedule=self.manager.record_private_review_copy(s['id'],str(self.video))
        self.episode=episode_path(episode['id'])

    def resume(self,**kw):
        return self.manager.resume_after_video_review(self.schedule['id'],str(self.video),
            expected_schedule_sha256=kw.get('expected',schedule_sha256(self.schedule)),note=kw.get('note','완성본 미채택 유지, 다음 회차 개선 진행'))

    def test_resume_preserves_attachment_episode_budget_anchor_and_restart_trigger(self):
        paths=[self.video,self.report,self.episode,google_budget._database_path(),openai_budget._database_path()]
        before=[p.read_bytes() for p in paths]
        resumed=self.resume()
        self.assertTrue(resumed['enabled'])
        self.assertEqual(resumed['last_result'],'private_review_deferred')
        self.assertNotIn('accepted_at',resumed)
        for key in ('last_script','last_video_path','last_video_sha256','last_youtube_id','scheduled_for','first_run_at','run_count','last_episode_id'):
            self.assertEqual(resumed[key],self.schedule[key])
        self.assertEqual([p.read_bytes() for p in paths],before)
        async def clock():
            for _ in range(2):
                manager=ScheduleManager(str(self.manager.filename),queue_only=True)
                manager.start_scheduler()
                jobs=manager.get_next_run_times()
                self.assertEqual(len(jobs),1)
                self.assertEqual(datetime.fromisoformat(jobs[0]['next_run']).replace(tzinfo=None),self.first+timedelta(days=14))
                await manager.queue_overdue()
                self.assertEqual(manager.get_schedule(resumed['id'])['run_count'],1)
                manager.stop_scheduler();await asyncio.sleep(0)
        with patch('shorts_maker.services.production_service.ProductionService.full_pipeline',new_callable=AsyncMock) as paid:
            asyncio.run(clock());paid.assert_not_awaited()

    def test_weekly_transition_starts_at_new_anchor_and_keeps_previous_review(self):
        first = self.first + timedelta(days=14)
        existing = self.schedule
        staged = self.manager.update_schedule(existing['id'], {
            'frequency': 'Every Week', 'first_run_at': first.isoformat(),
        })
        resumed = self.resume(expected=schedule_sha256(staged))
        self.assertEqual(resumed['scheduled_for'], existing['scheduled_for'])
        self.assertEqual(resumed['last_youtube_id'], existing['last_youtube_id'])
        self.assertEqual(resumed['last_episode_id'], existing['last_episode_id'])
        self.assertEqual(resumed['last_result'], 'private_review_deferred')

        async def check_clock():
            host = ScheduleManager(str(self.manager.filename), queue_only=True)
            host.start_scheduler()
            try:
                job, = host.get_next_run_times()
                self.assertEqual(datetime.fromisoformat(job['next_run']).replace(tzinfo=None), first)
                self.assertEqual(host._scheduler.get_job(existing['id']).trigger.interval, timedelta(weeks=1))
                await host.queue_overdue()
                self.assertEqual(host.get_schedule(existing['id']), resumed)
            finally:
                host.stop_scheduler()
                await asyncio.sleep(0)

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return first.replace(tzinfo=tz)

        with patch('shorts_maker.services.production_service.ProductionService.full_pipeline', new_callable=AsyncMock) as paid:
            asyncio.run(check_clock())
            with patch('shorts_maker.utils.scheduler.datetime', Frozen):
                asyncio.run(self.manager.queue_overdue())
                asyncio.run(self.manager.queue_overdue())
            paid.assert_not_awaited()
        queued = self.manager.get_schedule(existing['id'])
        self.assertEqual(queued['scheduled_for'], first.isoformat())
        self.assertEqual(queued['skipped_slots'], [])
        self.assertEqual(queued['run_count'], existing['run_count'] + 1)
        self.assertEqual(queued['run_history'][-1]['last_youtube_id'], existing['last_youtube_id'])

    def test_due_new_slot_archives_unaccepted_copy_once_and_does_not_inherit_spend_scope(self):
        self.manager.update_schedule(self.schedule['id'], {'planning_auth_required': False})
        self.schedule = self.manager.get_schedule(self.schedule['id'])
        resumed=self.resume()
        future=self.first+timedelta(days=14,seconds=1)
        class Frozen(datetime):
            @classmethod
            def now(cls,tz=None):return future.replace(tzinfo=ZoneInfo('Asia/Seoul')) if tz else future
        with patch('shorts_maker.utils.scheduler.datetime',Frozen),patch('shorts_maker.services.production_service.ProductionService.full_pipeline',new_callable=AsyncMock) as paid:
            asyncio.run(self.manager.queue_overdue());asyncio.run(self.manager.queue_overdue());paid.assert_not_awaited()
        current=self.manager.get_schedule(resumed['id'])
        self.assertEqual(current['run_count'],2)
        self.assertEqual(current['last_result'],'operator_pending')
        self.assertFalse(current['enabled'])
        for key in ('last_episode_id','last_youtube_id','last_video_path','last_script','review_continuation','accepted_at','planning_auth_required'):
            self.assertNotIn(key,current)
        history=current['run_history'][-1]
        self.assertEqual(history['last_youtube_id'],resumed['last_youtube_id'])
        self.assertEqual(history['review_continuation'],resumed['review_continuation'])
        self.assertIs(history['planning_auth_required'], False)
        self.assertNotIn('accepted_at',history)
        self.assertEqual(self.video.read_bytes(),b'fixture video')

    def test_owner_can_later_adopt_current_deferred_copy_without_creating_a_new_slot(self):
        resumed=self.resume()
        accepted=self.manager.accept_pending_video(resumed['id'],str(self.video))
        self.assertEqual(accepted['last_result'],'private_review_accepted')
        self.assertIn('accepted_at',accepted)
        self.assertEqual(accepted['run_count'],1)
        self.assertEqual(accepted['scheduled_for'],resumed['scheduled_for'])
        self.assertEqual(accepted['review_continuation'],resumed['review_continuation'])

    def test_accepting_a_deferred_copy_preserves_explicit_schedule_pause(self):
        resumed = self.resume()
        self.manager.toggle_schedule(resumed['id'])
        paused = self.manager.get_schedule(resumed['id'])
        self.assertFalse(paused['enabled'])
        accepted = self.manager.accept_pending_video(resumed['id'], str(self.video))
        self.assertEqual(accepted['last_result'], 'private_review_accepted')
        self.assertFalse(accepted['enabled'])
        self.assertEqual(accepted['last_youtube_id'], paused['last_youtube_id'])

    def test_old_adoption_confirmation_cannot_overwrite_schedule_change_during_media_check(self):
        original = self.manager._verified_pending_video

        def concurrent_change(*args, **kwargs):
            result = original(*args, **kwargs)
            self.manager.update_schedule(self.schedule['id'], {'name': '검토 중 이름 변경'})
            return result

        with patch.object(self.manager, '_verified_pending_video', side_effect=concurrent_change):
            with self.assertRaisesRegex(ValueError, '변경'):
                self.manager.accept_pending_video(
                    self.schedule['id'], str(self.video), expected_schedule_sha256=schedule_sha256(self.schedule),
                )
        current = self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['name'], '검토 중 이름 변경')
        self.assertNotIn('accepted_at', current)

    def test_stale_pending_changed_media_direct_url_and_no_attachment_fail_without_writes(self):
        original=self.manager.filename.read_bytes()
        with self.assertRaises(ValueError):self.resume(expected='0'*64)
        with self.assertRaises(ValueError):self.resume(note='')
        pending=self.episode.with_suffix('.operation.pending.json');pending.write_text('{}')
        with self.assertRaisesRegex(ValueError,'미확인'):self.resume()
        pending.unlink();pending.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(ValueError,'미확인'):self.resume()
        pending.unlink();self.video.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.resume()
        self.assertEqual(self.manager.filename.read_bytes(),original)
        self.video.write_bytes(b'fixture video')
        for change in ({'direct_url':'https://example.com/story'},{'last_youtube_id':None}):
            updated=self.manager.update_schedule(self.schedule['id'],change)
            before=self.manager.filename.read_bytes()
            with self.assertRaises(ValueError):self.resume(expected=schedule_sha256(updated))
            self.assertEqual(before,self.manager.filename.read_bytes())
            self.manager.save_schedules([self.schedule])
        self.resume()
        with self.assertRaises(ValueError):self.resume()

    def test_change_during_video_verification_is_not_overwritten(self):
        original=self.manager._verified_pending_video
        def changed(*args,**kwargs):
            verified=original(*args,**kwargs)
            self.manager.update_schedule(self.schedule['id'],{'name':'다른 작업에서 변경'})
            return verified
        with patch.object(self.manager,'_verified_pending_video',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'변경'):self.resume()
        current=self.manager.get_schedule(self.schedule['id'])
        self.assertEqual(current['name'],'다른 작업에서 변경')
        self.assertFalse(current['enabled'])
        self.assertNotIn('review_continuation',current)

    def test_live_child_lock_blocks_all_review_writes_until_explicit_retry(self):
        lock=self.manager.filename.with_name(self.manager.filename.name+'.lock.sqlite3')
        child=subprocess.Popen([sys.executable,'-c',
            "import sqlite3,sys; db=sqlite3.connect(sys.argv[1],isolation_level=None); "
            "db.execute('BEGIN EXCLUSIVE'); print('locked',flush=True); sys.stdin.read(1); db.close()",str(lock)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            self.assertIsNone(child.poll())
            before=self.manager.filename.read_bytes()
            for method in (self.manager.record_private_review_copy,self.manager.accept_pending_video):
                with self.subTest(method=method.__name__):
                    with self.assertRaisesRegex(ValueError,'다른 회차'):
                        method(self.schedule['id'],str(self.video))
                    self.assertEqual(self.manager.filename.read_bytes(),before)
            with self.assertRaisesRegex(ValueError, '다른 회차'):
                self.manager.toggle_schedule(self.schedule['id'])
            with self.assertRaisesRegex(ValueError,'다른 회차'):self.resume()
        finally:
            child.communicate('x',timeout=5)
        self.assertEqual(child.returncode,0)
        resumed=self.resume()
        self.assertEqual(resumed['last_result'],'private_review_deferred')
        self.assertNotIn('accepted_at',resumed)

    def test_unattached_script_rejection_cannot_race_an_attachment(self):
        self.manager.update_schedule(self.schedule['id'],{'last_youtube_id':None,'last_video_path':None,'last_video_sha256':None})
        before=self.manager.filename.read_bytes()
        db=sqlite3.connect(self.manager.filename.with_name(self.manager.filename.name+'.lock.sqlite3'),isolation_level=None)
        try:
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaisesRegex(ValueError,'다른 회차'):
                self.manager.reject_pending_script(self.schedule['id'])
            self.assertEqual(before,self.manager.filename.read_bytes())
        finally:
            db.close()
        rejected=self.manager.reject_pending_script(self.schedule['id'])
        self.assertEqual(rejected['last_result'],'script_rejected')
        self.assertNotIn('accepted_at',rejected)

    def test_broken_pending_links_block_preview_attachment_acceptance_and_continuation(self):
        markers=[self.episode.with_suffix('.operation.pending.json'),self.video.with_suffix('.upload-pending.json')]
        before=self.manager.filename.read_bytes()
        for marker in markers:
            marker.symlink_to(self.root/'missing-result')
            try:
                for method in (self.manager.pending_video_info,self.manager.record_private_review_copy,self.manager.accept_pending_video):
                    with self.subTest(marker=marker.name,method=method.__name__):
                        with self.assertRaises(ValueError):method(self.schedule['id'],str(self.video))
                        self.assertEqual(self.manager.filename.read_bytes(),before)
                with self.assertRaises(ValueError):self.resume()
            finally:
                marker.unlink()
        self.assertEqual(self.manager.filename.read_bytes(),before)

    def test_native_explicit_confirmation_busy_deleted_view_and_preserved_owner_state(self):
        state=AppState();client=Client(page('/review-continue'));self.addCleanup(client.delete)
        refresh=Mock()
        with client:
            root=ui.column()
            with root:render_review_continuation(state,self.manager,self.schedule,refresh)
            def click(text):
                b=next(e for e in reversed(list(client.elements.values())) if getattr(e,'text','')==text)
                next(e.handler for e in b._event_listeners.values() if e.type=='click')(None)
            click('채택 보류·다음 회차 예약')
            before=self.manager.filename.read_bytes()
            state.pipeline_running=True;click('미채택 유지·다음 회차 예약')
            self.assertEqual(before,self.manager.filename.read_bytes())
            old_button=next(e for e in client.elements.values() if getattr(e,'text','')=='미채택 유지·다음 회차 예약')
            old_confirm=next(e.handler for e in old_button._event_listeners.values() if e.type=='click')
            state.pipeline_running=False;root.clear();old_confirm(None)
            self.assertEqual(before,self.manager.filename.read_bytes())
            with root:render_review_continuation(state,self.manager,self.schedule,refresh)
            click('채택 보류·다음 회차 예약');click('미채택 유지·다음 회차 예약')
        self.assertTrue(self.manager.get_schedule(self.schedule['id'])['enabled'])
        self.assertNotIn('accepted_at',self.manager.get_schedule(self.schedule['id']))
        refresh.assert_called_once()

    def test_weekly_review_confirmation_shows_the_saved_frequency(self):
        schedule = self.manager.update_schedule(self.schedule['id'], {'frequency': 'Every Week'})
        client = Client(page('/weekly-review'));self.addCleanup(client.delete)
        with client:
            render_review_continuation(AppState(), self.manager, schedule, Mock())
            button = next(e for e in client.elements.values() if getattr(e, 'text', '') == '채택 보류·다음 회차 예약')
            next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)
            labels = [getattr(e, 'text', '') for e in client.elements.values()]
        self.assertTrue(any('7일마다' in label for label in labels))
        self.assertFalse(any('14일/28일' in label for label in labels))

    def test_native_adoption_shows_bound_video_and_requires_a_current_explicit_decision(self):
        async def exercise():
            refresh = Mock()
            state = AppState(final_video_path='/not-the-attached-video.mp4')
            with patch.object(core, 'loop', asyncio.get_running_loop()):
                client = Client(page('/review-adopt'))
                with client, ui.column() as root:
                    try:
                        render_review_acceptance(state, self.manager, self.schedule, refresh)

                        async def click(label):
                            button = next(e for e in client.elements.values() if getattr(e, 'text', '') == label)
                            handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                            before = asyncio.all_tasks()
                            handler(None)
                            await asyncio.sleep(0)
                            await asyncio.gather(*(asyncio.all_tasks() - before))

                        await click('완성본 채택')
                        self.assertIn('YouTube ID · fixture_private',
                                      [getattr(e, 'text', '') for e in client.elements.values()])
                        self.assertFalse(any(isinstance(e, ui.input) for e in client.elements.values()))
                        await click('취소')
                        await click('이 완성본 채택')
                        self.assertEqual(self.manager.get_schedule(self.schedule['id']), self.schedule)
                        await click('완성본 채택')
                        current = self.manager.update_schedule(self.schedule['id'], {'name': '변경된 일정'})
                        await click('이 완성본 채택')
                        self.assertTrue(any('일정이 변경됐습니다' in getattr(e, 'text', '')
                                            for e in client.elements.values()))
                        self.assertEqual(self.manager.get_schedule(self.schedule['id']), current)
                        root.clear()
                        render_review_acceptance(state, self.manager, current, refresh)
                        await click('완성본 채택')
                        await click('이 완성본 채택')
                    finally:
                        client.delete()
            accepted = self.manager.get_schedule(self.schedule['id'])
            self.assertEqual(accepted['last_result'], 'private_review_accepted')
            self.assertEqual(accepted['last_video_path'], str(self.video))
            self.assertEqual(state.final_video_path, '/not-the-attached-video.mp4')
            refresh.assert_called_once()

        asyncio.run(exercise())
