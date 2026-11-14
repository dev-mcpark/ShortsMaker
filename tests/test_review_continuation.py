"""Review deferral keeps cadence, outputs and budgets without inventing adoption."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
from zoneinfo import ZoneInfo
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components.review_continuation import render_review_continuation
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

    def test_due_new_slot_archives_unaccepted_copy_once_and_does_not_inherit_spend_scope(self):
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
        for key in ('last_episode_id','last_youtube_id','last_video_path','last_script','review_continuation','accepted_at'):
            self.assertNotIn(key,current)
        history=current['run_history'][-1]
        self.assertEqual(history['last_youtube_id'],resumed['last_youtube_id'])
        self.assertEqual(history['review_continuation'],resumed['review_continuation'])
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
