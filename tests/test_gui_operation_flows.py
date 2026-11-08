"""Offline operation-flow regressions; no API, scheduler, or browser is started."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from shorts_maker.gui.components import generation_tab, pipeline_tab, planning_tab, publishing_tab, sources_tab
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ShortsScript, VideoScene
from shorts_maker.services.production_service import ProductionProgress, ProductionResult
from shorts_maker.utils.scheduler import ScheduleManager


class _Element:
    def __init__(self, kind, args, kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
        self.value = kwargs.get('value')
        self.callback = kwargs.get('on_click')
        self.props_text = ''
        self.visible = True
        self.text = args[0] if args and isinstance(args[0], str) else ''
        self.enabled = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def props(self, text='', **kwargs):
        self.props_text += text
        return self

    def on_click(self, callback):
        self.callback = callback
        return self

    def bind_enabled_from(self, target, name, backward=None):
        value = getattr(target, name)
        self.enabled = backward(value) if backward else bool(value)
        return self

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def __getattr__(self, name):
        return lambda *args, **kwargs: self


class _UI:
    """Record rendered handlers while keeping NiceGUI and socket state untouched."""

    def __init__(self):
        self.elements = []

    def refreshable(self, function):
        function.refresh = Mock()
        return function

    def __getattr__(self, kind):
        def create(*args, **kwargs):
            element = _Element(kind, args, kwargs)
            self.elements.append(element)
            return element
        return create

    def find(self, kind, label):
        return next(element for element in self.elements
                    if element.kind == kind and element.args and element.args[0] == label)


class CompletedOutputTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'outputs'
        self.output.mkdir()
        self.settings = patch.object(publishing_tab, 'settings', Mock(output_dir=self.output))
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def write_output(self, path=None, **overrides):
        video = path or self.output / 'completed.mp4'
        video.write_bytes(b'fixture video bytes')
        report = {
            'schema_version': 1, 'video_path': str(video), 'title': '검토 완료 영상',
            'quality_passed': True, 'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
        }
        report.update(overrides)
        video.with_suffix('.production.json').write_text(json.dumps(report), encoding='utf-8')
        return video, report

    def test_reopen_saved_completed_output_without_replacing_script(self):
        video, report = self.write_output()
        state = AppState(final_video_path='previous.mp4')
        previous_script = object()
        state.script = previous_script
        self.assertEqual(publishing_tab._load_completed_video(state, str(video)), report)
        self.assertEqual(state.final_video_path, str(video))
        self.assertIs(state.script, previous_script)
        self.assertIn('검토 완료 영상 · completed.mp4', publishing_tab._completed_outputs().values())

    def test_invalid_quality_or_changed_hash_preserves_selected_output(self):
        for overrides in ({'quality_passed': False}, {'video_sha256': 'wrong'}):
            with self.subTest(overrides=overrides):
                video, _ = self.write_output(**overrides)
                state = AppState(final_video_path='previous.mp4')
                with self.assertRaises(ValueError):
                    publishing_tab._load_completed_video(state, str(video))
                self.assertEqual(state.final_video_path, 'previous.mp4')

    def test_busy_replacement_is_rejected_for_both_operations(self):
        video, _ = self.write_output()
        for busy_field in ('pipeline_running', 'youtube_upload_in_progress'):
            state = AppState(final_video_path='previous.mp4')
            setattr(state, busy_field, True)
            with self.subTest(busy_field=busy_field), self.assertRaises(ValueError):
                publishing_tab._load_completed_video(state, str(video))
            self.assertEqual(state.final_video_path, 'previous.mp4')

    def test_outside_video_and_symlinked_report_are_rejected(self):
        outside, _ = self.write_output(self.root / 'outside.mp4')
        with self.assertRaises(ValueError):
            publishing_tab._completed_video(str(outside))
        video, _ = self.write_output()
        sidecar = video.with_suffix('.production.json')
        sidecar.unlink()
        sidecar.symlink_to(outside.with_suffix('.production.json'))
        with self.assertRaises(ValueError):
            publishing_tab._completed_video(str(video))
        self.assertEqual(publishing_tab._completed_outputs(), {})

    def test_corrupt_reports_do_not_break_output_list(self):
        video, _ = self.write_output()
        (self.output / 'bad.production.json').write_text('{')
        (self.output / 'list.production.json').write_text('[]')
        self.assertEqual(list(publishing_tab._completed_outputs()), [str(video)])

    def test_completed_outputs_use_file_time_instead_of_filename_order(self):
        old, _ = self.write_output(self.output / 'zzz_older.mp4')
        new, _ = self.write_output(self.output / 'aaa_latest.mp4')
        os.utime(old, (100, 100))
        os.utime(new, (200, 200))
        self.assertEqual(list(publishing_tab._completed_outputs()), [str(new), str(old)])

    def render(self, state):
        recorder = _UI()
        with patch.object(publishing_tab, 'ui', recorder), \
                patch.object(publishing_tab, 'card_with_header', lambda *args: recorder.card()):
            publishing_tab.render_publishing_tab(state)
        return recorder

    def test_failed_saved_output_load_preserves_path_and_form(self):
        video, _ = self.write_output(video_sha256='wrong')
        state = AppState(final_video_path='previous.mp4')
        recorder = self.render(state)
        saved = next(element for element in recorder.elements
                     if element.kind == 'select' and element.kwargs.get('label') == '저장된 완성본')
        saved.value = str(video)
        title = recorder.find('input', '영상 제목')
        title.value = '기존 제목'
        with patch.object(publishing_tab, 'safe_notify'):
            recorder.find('button', '완성본 불러오기').callback()
        self.assertEqual(state.final_video_path, 'previous.mp4')
        self.assertEqual(title.value, '기존 제목')

    def test_other_scripts_metadata_cannot_replace_selected_video_metadata(self):
        video, _ = self.write_output(script_sha256='different script')
        state = AppState(final_video_path=str(video))
        state.script = Mock()
        state.script.model_dump.return_value = {'title': '다른 각본'}
        recorder = self.render(state)
        title = recorder.find('input', '영상 제목')
        title.value = '선택한 영상 제목'
        with patch.object(publishing_tab, 'safe_notify') as notify:
            recorder.find('button', '각본에서 게시 정보 가져오기').callback()
        self.assertEqual(title.value, '선택한 영상 제목')
        self.assertEqual(notify.call_args.kwargs['type'], 'warning')

    def test_upload_uses_configured_service_before_busy_state(self):
        video, _ = self.write_output()
        state = AppState(final_video_path=str(video))
        service = Mock()
        service.upload_to_youtube = AsyncMock(return_value=ProductionResult(True, youtube_id='ABC123def45'))

        def get_service():
            self.assertFalse(state.is_busy)
            return service

        state.get_or_create_service = Mock(side_effect=get_service)
        recorder = self.render(state)
        recorder.find('input', '영상 제목').value = '검토 제목'
        next(element for element in recorder.elements if element.kind == 'radio').value = 'yes'
        with patch.object(publishing_tab, 'safe_notify'):
            asyncio.run(recorder.find('button', 'YouTube에 비공개 업로드').callback())
        service.upload_to_youtube.assert_awaited_once()
        self.assertFalse(state.youtube_upload_in_progress)

    def test_active_planning_blocks_upload_before_service_creation(self):
        state = AppState(pipeline_running=True, final_video_path='previous.mp4')
        state.get_or_create_service = Mock()
        recorder = self.render(state)
        asyncio.run(recorder.find('button', 'YouTube에 비공개 업로드').callback())
        state.get_or_create_service.assert_not_called()


class ScheduleDeletionTests(TestCase):
    def test_pending_or_active_round_cannot_be_deleted_and_history_survives(self):
        with TemporaryDirectory() as temp:
            manager = ScheduleManager(str(Path(temp) / 'schedules.json'))
            for status in ('operator_pending', 'run_in_progress', 'script_review_pending'):
                with self.subTest(status=status):
                    record = manager.create_schedule('작업', '09:00', 'Every 2 Weeks', enabled=False)
                    manager.update_schedule(record['id'], {
                        'last_result': status, 'review_operator': 'agent',
                        'last_run': '2026-11-04T10:06:00', 'run_count': 1,
                    })
                    before = manager.filename.read_bytes()
                    with self.assertRaises(ValueError):
                        manager.delete_schedule(record['id'])
                    self.assertEqual(manager.filename.read_bytes(), before)
                    self.assertIsNotNone(manager.get_schedule(record['id']))
                    self.assertTrue(any(row['schedule_id'] == record['id']
                                        for row in manager.get_execution_history()))

    def test_unused_inactive_schedule_can_still_be_deleted(self):
        with TemporaryDirectory() as temp:
            manager = ScheduleManager(str(Path(temp) / 'schedules.json'))
            record = manager.create_schedule('미사용', '09:00', enabled=False)
            self.assertTrue(manager.delete_schedule(record['id']))
            self.assertIsNone(manager.get_schedule(record['id']))


class PlanningCallbackTests(TestCase):
    def render(self, state, *, paid):
        recorder = _UI()
        source = Mock()
        source.get_categories.return_value = []
        with patch.object(pipeline_tab, 'ui', recorder), \
                patch.object(pipeline_tab, 'SourceManager', Mock(return_value=source)), \
                patch.object(pipeline_tab, 'safe_notify'), \
                patch.object(pipeline_tab, 'settings', Mock(paid_production_enabled=paid)):
            pipeline_tab.render_pipeline_tab(state)
        return recorder, recorder.find('button', '각본 기획 시작').callback

    def test_disabled_paid_actions_do_not_clear_previous_result(self):
        state = AppState(final_video_path='existing.mp4', generated_clips=['scene.mp4'])
        state.script = object()
        previous = state.script
        state.new_production_service = Mock()
        _, callback = self.render(state, paid=False)
        with patch.object(pipeline_tab, 'settings', Mock(paid_production_enabled=False)), \
                patch.object(pipeline_tab, 'safe_notify'):
            asyncio.run(callback())
        state.new_production_service.assert_not_called()
        self.assertIs(state.script, previous)
        self.assertEqual(state.final_video_path, 'existing.mp4')
        self.assertEqual(state.generated_clips, ['scene.mp4'])

    def test_active_upload_blocks_planning_before_service_creation(self):
        state = AppState(youtube_upload_in_progress=True, final_video_path='existing.mp4')
        state.new_production_service = Mock()
        _, callback = self.render(state, paid=True)
        with patch.object(pipeline_tab, 'safe_notify'):
            asyncio.run(callback())
        state.new_production_service.assert_not_called()
        self.assertEqual(state.final_video_path, 'existing.mp4')

    def test_failed_planning_keeps_previous_assets_and_stops_monitor(self):
        state = AppState(final_video_path='existing.mp4', generated_clips=['scene.mp4'])
        state.script = object()
        previous = state.script
        service = Mock(progress=ProductionProgress())
        service.full_pipeline = AsyncMock(return_value=ProductionResult(False, error='fixture failure'))
        state.new_production_service = Mock(return_value=service)
        recorder, callback = self.render(state, paid=True)
        with patch.object(pipeline_tab, 'ui', recorder), \
                patch.object(pipeline_tab, 'settings', Mock(paid_production_enabled=True)), \
                patch.object(pipeline_tab, 'safe_notify'), patch.object(pipeline_tab, 'safe_refresh'), \
                patch.object(pipeline_tab, 'safe_set_visibility'):
            asyncio.run(callback())
        service.full_pipeline.assert_awaited_once()
        self.assertFalse(state.pipeline_running)
        self.assertIs(state.script, previous)
        self.assertEqual(state.final_video_path, 'existing.mp4')
        self.assertEqual(state.generated_clips, ['scene.mp4'])
        self.assertEqual(state.pipeline_history[-1]['title'], '각본 기획 실패')


class SourceCallbackTests(TestCase):
    def render(self, manager):
        recorder = _UI()
        manager.load_sources.return_value = {}
        with patch.object(sources_tab, 'ui', recorder), \
                patch.object(sources_tab, 'SourceManager', Mock(return_value=manager)):
            sources_tab.render_sources_tab(AppState())
        return recorder

    def test_whitespace_category_is_rejected_before_persistence(self):
        manager = Mock()
        recorder = self.render(manager)
        recorder.find('input', '카테고리').value = '   '
        recorder.find('input', 'RSS 피드 URL').value = 'https://example.com/rss'
        with patch.object(sources_tab, 'safe_notify'):
            recorder.find('button', 'RSS 소스 추가').callback()
        manager.add_source.assert_not_called()

    def test_recommended_feed_write_failure_is_reported(self):
        manager = Mock()
        manager.add_source.side_effect = OSError('fixture disk failure')
        recorder = self.render(manager)
        button = next(element for element in recorder.elements
                      if element.kind == 'button' and 'TechCrunch 피드 추가' in element.props_text)
        with patch.object(sources_tab, 'safe_notify') as notify, \
                patch.object(sources_tab, 'safe_refresh') as refresh:
            button.callback()
        self.assertEqual(notify.call_args.kwargs['type'], 'negative')
        refresh.assert_not_called()


class LocalReviewInterfaceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = ShortsScript(title='파일명이 아닌 실제 이야기 제목', description='Source', tags=[], mood='calm', style='explainer',
            source_url='https://example.com/article', source_name='Source', generation_mode='video',
            scenes=[VideoScene(scene_number=n, script_text=f'Scene {n}', visual_description='One bus')
                    for n in range(1, 4)])
        self.state = AppState(script=self.script, mode='video')
        self.state.confirm_script_review()
        self.record = self.root / 'review.json'
        self.record.write_text(json.dumps({'frame_path': 'approved.png', 'must_show': ['one bus'],
            'must_avoid': ['extra bus'], 'reviewer_note': 'Reviewed'}))

    def test_script_search_keeps_older_titles_and_skips_invalid_or_outside_files(self):
        for n in range(7):
            path = self.root / f'script_{9-n}.json'
            path.write_text(self.script.model_copy(update={'title': f'Full title {n}'}).model_dump_json())
            os.utime(path, (100+n, 100+n))
        (self.root / 'broken.json').write_text('{')
        (self.root / 'list.json').write_text('[]')
        outside = self.root / 'outside'
        outside.mkdir()
        secret = outside / 'script.json'
        secret.write_text(self.script.model_dump_json())
        # A separate script root must not follow a link to another workspace location.
        script_dir = self.root / 'scripts'
        script_dir.mkdir()
        (script_dir / 'outside.json').symlink_to(secret)
        with patch.object(planning_tab.settings, 'scripts_dir', script_dir):
            self.assertEqual(planning_tab._saved_script_options(), {})
        with patch.object(planning_tab.settings, 'scripts_dir', self.root):
            options = planning_tab._saved_script_options()
        self.assertEqual(len(options), 7)
        self.assertEqual(next(iter(options)), 'script_3.json')
        self.assertIn('Full title 0 · script_9.json', options.values())

    def test_frame_summary_folds_approved_scenes_and_updates_after_explicit_review(self):
        recorder = _UI()
        changed = Mock()
        def verified(script, scene):
            if scene.scene_number == 3:
                raise ValueError('unreviewed')
            return 'approved.png', 'hash'
        with patch.object(generation_tab, 'ui', recorder), patch.object(
                generation_tab, 'verified_first_frame', side_effect=verified), patch.object(
                generation_tab, 'review_path', return_value=self.record), patch.object(
                generation_tab, 'inspect_frame', return_value='hash'), patch.object(
                generation_tab, 'approve_first_frame') as approve, patch.object(generation_tab, 'safe_notify'):
            generation_tab.render_first_frame_reviews(self.state, on_review_change=changed)
            panels = [e for e in recorder.elements if e.kind == 'expansion']
            self.assertIn('승인 2/3', panels[0].text)
            self.assertEqual([e.value for e in panels[1:]], [False, False, True])
            approve.assert_not_called()
            inputs = [e for e in recorder.elements if e.kind == 'input' and e.text == '첫 프레임 PNG/JPEG 경로']
            notes = [e for e in recorder.elements if e.kind == 'input' and e.text == '검토 의견']
            criteria = [e for e in recorder.elements if e.kind == 'textarea']
            inputs[-1].value, notes[-1].value = 'candidate.png', 'Source and image checked'
            criteria[-2].value, criteria[-1].value = 'one bus', 'extra bus'
            [e for e in recorder.elements if e.kind == 'button' and e.text == '이미지 미리보기'][-1].callback()
            [e for e in recorder.elements if e.kind == 'button' and e.text == '이 첫 프레임 승인'][-1].callback()
            approve.assert_called_once()
            changed.assert_called_once()
            self.assertIn('승인 3/3', panels[0].text)
            self.assertIn('승인됨', panels[-1].text)

    def test_raw_summary_keeps_rejected_and_unknown_results_open_without_paid_calls(self):
        recorder = _UI()
        verdicts = {1: 'approved', 2: 'rejected', 3: 'stale'}
        service = Mock(max_veo_attempts=1)
        service.review_clip_path.side_effect = lambda script, index: ('cached.mp4', 'hash')
        self.state.get_or_create_service = lambda: service
        with patch.object(generation_tab, 'ui', recorder), patch.object(
                generation_tab, 'review_path', return_value=self.record), patch.object(
                generation_tab, 'raw_review_status', side_effect=lambda script, scene, *args: verdicts[scene.scene_number]), patch.object(
                generation_tab, 'load_raw_verdict', return_value={'reviewer_note': 'Stored note'}), patch.object(
                generation_tab, 'save_raw_verdict') as save, patch.object(generation_tab, 'safe_notify'), patch.object(
                generation_tab.settings, 'paid_production_enabled', False):
            generation_tab.render_raw_clip_reviews(self.state)
            panels = [e for e in recorder.elements if e.kind == 'expansion']
            self.assertIn('승인 1/3', panels[0].text)
            self.assertEqual([e.value for e in panels[1:]], [False, True, True])
            self.assertIn('원본 제외', panels[2].text)
            self.assertIn('판정 무효', panels[3].text)
            self.assertEqual(len([e for e in recorder.elements if e.kind == 'button' and e.text == '저장된 원본 다시 확인']), 3)
            verdicts[2] = 'approved'
            [e for e in recorder.elements if e.kind == 'button' and e.text == '원본 승인'][1].callback()
            save.assert_called_once()
            self.assertIn('승인 2/3', panels[0].text)
            self.assertFalse(panels[2].value)
            service.generate_review_clip.assert_not_called()

    def test_missing_raw_cannot_be_generated_in_review_mode(self):
        recorder = _UI()
        service = Mock(max_veo_attempts=1)
        service.review_clip_path.side_effect = [
            (None, 'hash'), ValueError('uncertain request'), (None, 'hash')]
        self.state.get_or_create_service = lambda: service
        with patch.object(generation_tab, 'ui', recorder), patch.object(
                generation_tab, 'review_path', return_value=self.record), patch.object(
                generation_tab.settings, 'paid_production_enabled', False):
            generation_tab.render_raw_clip_reviews(self.state)
        buttons = [e for e in recorder.elements if e.kind == 'button' and e.text == '이 장면 Veo 원본 생성']
        self.assertTrue(all(not e.enabled for e in buttons))
        group = next(e for e in recorder.elements if e.kind == 'expansion')
        self.assertIn('승인 0/3', group.text)
        service.generate_review_clip.assert_not_called()
