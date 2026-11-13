"""Structured fields and advanced JSON share one explicit-apply draft; no providers."""

import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from nicegui import binding, core, ui
from nicegui.client import Client
from nicegui.page import page

from shorts_maker.gui.components import planning_tab, script_form
from shorts_maker.gui.state.app_state import AppState
from shorts_maker.planner.models import ShortsScript
from shorts_maker.utils.config import settings
from test_gui_creation_flows import script
from test_gui_operation_flows import _UI


class ScriptFormStateTests(TestCase):
    def setUp(self):
        self.script = script()
        self.script.scenes = [self.script.scenes[0].model_copy(update={'scene_number': 2}),
                              self.script.scenes[0].model_copy(update={'scene_number': 5})]
        self.state = AppState(script=self.script, mode='video', final_video_path='kept.mp4')
        self.state.confirm_script_review()

    def update(self, field, value, number=None):
        return self.state.update_script_form_field(self.state.script_editor_key(), self.state.script_editor_text(), field, value, number)

    def test_unapplied_recovery_can_edit_mood_content_and_structure_without_authority(self):
        data = self.script.model_dump()
        data['mood'] = None
        self.state = AppState()
        scope = {'episode_id': 'unchanged scope'}
        self.state.operating_scope = scope
        self.state.remember_script_draft(self.state.script_editor_key(), json.dumps(data))
        self.update('mood', 'calm')
        self.update('script_text', '복구한 내레이션', 5)
        key = self.state.script_editor_key()
        number = self.state.change_script_scene(key, self.state.script_editor_text(), 'add', 2)
        self.assertGreater(number, 5)
        self.assertEqual(self.state.script_form_data()['mood'], 'calm')
        self.assertEqual(self.state.script_form_data()['source_url'], self.script.source_url)
        self.assertIsNone(self.state.script)
        self.assertIsNone(self.state.reviewed_script_sha256)
        self.assertIsNone(self.state.final_video_path)
        self.assertIs(self.state.operating_scope, scope)
        before = self.state.script_editor_text()
        with self.assertRaises(ValueError):
            self.update('mood', 'unrecognized-new-mood')
        self.assertEqual(self.state.script_editor_text(), before)

    def test_plain_fields_merge_by_scene_number_and_preserve_applied_source_and_approval(self):
        original = self.script.model_dump_json()
        receipt = self.state.reviewed_script_sha256
        self.update('title', '새 제목')
        self.update('script_text', '다섯 번째 장면 내레이션', 5)
        self.update('visual_description', '구체적인 모형의 배치', 2)
        self.update('motion_instruction', '옆으로 천천히 이동', 5)
        self.update('generation_mode', 'hybrid')
        self.update('visual_mode', 'image', 5)
        draft = self.state.script_form_data()
        self.assertEqual(draft['scenes'][0]['visual_description'], '구체적인 모형의 배치')
        self.assertEqual(draft['scenes'][1]['script_text'], '다섯 번째 장면 내레이션')
        self.assertEqual(draft['scenes'][1]['visual_mode'], 'image')
        self.assertEqual(draft['source_url'], self.script.source_url)
        self.assertEqual(draft['style'], self.script.style)
        self.assertEqual(self.script.model_dump_json(), original)
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertTrue(self.state.has_unapplied_script_draft())

    def test_partial_empty_values_survive_and_can_be_repaired_before_schema_apply(self):
        self.update('script_text', '', 2)
        self.update('duration_seconds', None, 5)
        self.assertEqual(self.state.script_form_data()['scenes'][0]['script_text'], '')
        with self.assertRaises(ValueError):
            ShortsScript.model_validate_json(self.state.script_editor_text())
        self.update('script_text', '복원한 문장', 2)
        self.update('duration_seconds', 6.5, 5)
        parsed = ShortsScript.model_validate_json(self.state.script_editor_text())
        self.assertEqual(parsed.scenes[1].duration_seconds, 6.5)

    def test_stale_view_busy_and_stale_advanced_draft_never_replace_newer_text(self):
        key, before = self.state.script_editor_key(), self.state.script_editor_text()
        self.update('description', '고급 편집과 공유할 수정')
        changed = self.state.script_editor_text()
        with self.assertRaisesRegex(ValueError, '초안'):
            self.state.update_script_form_field(key, before, 'title', 'late')
        self.assertEqual(self.state.script_editor_text(), changed)
        self.state.pipeline_running = True
        with self.assertRaises(ValueError):
            self.update('title', 'busy')
        self.state.pipeline_running = False
        self.state.load_saved_script(script('another'))
        with self.assertRaises(ValueError):
            self.state.update_script_form_field(key, changed, 'title', 'old source')

    def test_broken_advanced_structure_is_preserved_instead_of_replaced(self):
        for text in ('{unfinished', '[]', '{"scenes":[]}', '{"scenes":[{"scene_number":true}]}'):
            self.state.remember_script_draft(self.state.script_editor_key(), text)
            with self.assertRaises(ValueError):
                self.update('title', 'must not overwrite')
            self.assertEqual(self.state.script_editor_text(), text)

    def test_unsupported_fields_and_invalid_numbers_do_not_mutate_the_draft(self):
        before = self.state.script_editor_text()
        for field, value, number in [('source_url', 'https://changed.example', None),
                                     ('scene_number', 8, 2), ('visual_mode', 'unknown', 5),
                                     ('duration_seconds', float('nan'), 2), ('duration_seconds', False, 2)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.update(field, value, number)
            self.assertEqual(self.state.script_editor_text(), before)
        self.assertFalse(self.update('title', self.script.title))

    def structure(self, action, number):
        return self.state.change_script_scene(self.state.script_editor_key(), self.state.script_editor_text(), action, number)

    def test_reorder_preserves_scene_ids_metadata_and_applied_work_until_explicit_apply(self):
        original, receipt = self.script.model_dump_json(), self.state.reviewed_script_sha256
        self.update('script_text', '새로운 결말', 5)
        scope = self.state.operating_scope = {'schedule_id': 'retained-scope'}
        self.assertEqual(self.structure('earlier', 5), 5)
        draft = self.state.script_form_data()
        self.assertEqual([s['scene_number'] for s in draft['scenes']], [5, 2])
        self.assertEqual(draft['scenes'][0]['script_text'], '새로운 결말')
        self.assertEqual({k: v for k, v in draft.items() if k != 'scenes'},
                         {k: v for k, v in self.script.model_dump().items() if k != 'scenes'})
        self.assertEqual(self.script.model_dump_json(), original)
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertIs(self.state.operating_scope, scope)
        text = self.state.script_editor_text()
        self.structure('earlier', 5)  # Already at the start.
        self.assertEqual(self.state.script_editor_text(), text)
        self.structure('later', 5)
        self.assertEqual([s['scene_number'] for s in self.state.script_form_data()['scenes']], [2, 5])

    def test_add_remove_blank_scene_and_keep_original_scene_ids_distinct(self):
        self.structure('remove', 5)
        number = self.structure('add', 2)
        self.assertEqual(number, 6)  # Do not reuse an ID from the applied source.
        scenes = self.state.script_form_data()['scenes']
        self.assertEqual([s['scene_number'] for s in scenes], [2, 6])
        self.assertEqual(scenes[1]['script_text'], '')
        self.assertEqual(scenes[1]['visual_description'], '')
        with self.assertRaises(ValueError):
            ShortsScript.model_validate_json(self.state.script_editor_text())
        self.update('script_text', '출처와 대조한 새 장면', number)
        self.update('visual_description', '그 문장을 설명하는 구체적인 배치', number)
        self.assertEqual(ShortsScript.model_validate_json(self.state.script_editor_text()).scenes[1].scene_number, 6)
        self.assertEqual(self.structure('remove', 6), 2)
        before = self.state.script_editor_text()
        with self.assertRaisesRegex(ValueError, '하나 이상'):
            self.structure('remove', 2)
        self.assertEqual(self.state.script_editor_text(), before)

    def test_structure_rejects_stale_busy_invalid_and_broken_drafts_without_mutation(self):
        key, text = self.state.script_editor_key(), self.state.script_editor_text()
        self.update('title', '다른 화면에서 입력')
        changed = self.state.script_editor_text()
        with self.assertRaises(ValueError):
            self.state.change_script_scene(key, text, 'remove', 2)
        for action, number in [('invalid', 2), ('add', True), ('remove', 100)]:
            with self.assertRaises(ValueError):
                self.structure(action, number)
            self.assertEqual(self.state.script_editor_text(), changed)
        self.state.pipeline_running = True
        with self.assertRaises(ValueError):
            self.structure('add', 2)
        self.state.pipeline_running = False
        self.state.load_saved_script(script('new script'))
        with self.assertRaises(ValueError):
            self.state.change_script_scene(key, changed, 'add', 2)
        self.state.remember_script_draft(self.state.script_editor_key(), '{unfinished')
        with self.assertRaises(ValueError):
            self.structure('add', 1)
        self.assertEqual(self.state.script_editor_text(), '{unfinished')


class ScriptFormUiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.loop_patch = patch.object(core, 'loop', asyncio.get_running_loop())
        self.loop_patch.start()
        self.addCleanup(self.loop_patch.stop)
        setting = patch.object(settings, 'scripts_dir', Path(temporary.name))
        setting.start()
        self.addCleanup(setting.stop)
        output = patch.object(settings, 'output_dir', Path(temporary.name) / 'outputs')
        output.start()
        self.addCleanup(output.stop)
        self.client = Client(page('/script-form'))
        self.addCleanup(self.client.delete)
        self.state = AppState(script=script(), mode='video', final_video_path='kept.mp4')
        self.state.confirm_script_review()

    def render(self):
        with self.client, ui.column() as root, patch.object(planning_tab, 'load_source_catalog', return_value=(object(), {})):
            planning_tab.render_planning_tab(self.state)
        return root

    def field(self, root, label):
        return next(e for e in root.descendants() if e._props.get('label') == label)

    def click(self, root, text):
        button = next(e for e in root.descendants() if getattr(e, 'text', '') == text)
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    async def flush(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        binding._refresh_step()

    async def test_recovered_null_mood_can_be_repaired_in_plain_form_without_auto_apply(self):
        data = script().model_dump()
        data['mood'] = None
        self.state = AppState()
        self.state.remember_script_draft(self.state.script_editor_key(), json.dumps(data))
        root = self.render()
        mood = self.field(root, '대본 음악 분위기')
        source_link = next(e for e in root.descendants() if getattr(e, 'text', '') == '초안 출처 원문 열기')
        self.assertEqual(source_link._props['href'], data['source_url'])
        self.assertEqual(source_link._props['rel'], 'noopener noreferrer')
        self.assertIsNone(mood.value)
        self.assertIsNone(json.loads(self.state.script_editor_text())['mood'])
        with self.client:
            mood.set_value('calm')
            self.field(root, '장면 1 · 내레이션').set_value('일반 폼에서 고친 문장')
        await self.flush()
        self.assertIsNone(self.state.script)
        self.assertIsNone(self.state.reviewed_script_sha256)
        with self.client:
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.script.mood, 'calm')
        self.assertEqual(self.state.script.scenes[0].script_text, '일반 폼에서 고친 문장')
        self.assertEqual(self.state.script.source_url, data['source_url'])
        self.assertFalse(self.state.is_script_reviewed())
        self.assertIsNone(self.state.final_video_path)

    async def test_malformed_recovery_stays_in_editor_and_does_not_guess_a_form(self):
        self.state = AppState()
        self.state.remember_script_draft(self.state.script_editor_key(), '{broken response')
        root = self.render()
        text = '\n'.join(getattr(e, 'text', '') for e in root.descendants())
        self.assertIn('일반 편집을 열 수 없습니다', text)
        self.assertEqual(self.field(root, '각본 JSON').value, '{broken response')
        self.assertIsNone(self.state.script)
        self.assertFalse(self.state.is_script_reviewed())

    async def test_typing_shares_json_without_replacing_focused_form_and_apply_uses_existing_gates(self):
        root = self.render()
        field = self.field(root, '장면 1 · 내레이션')
        with self.client:
            field.set_value('JSON을 몰라도 문장을 수정합니다.')
        await self.flush()
        self.assertIn(field, self.client.elements.values())
        self.assertEqual(json.loads(self.field(root, '각본 JSON').value)['scenes'][0]['script_text'], 'JSON을 몰라도 문장을 수정합니다.')
        self.assertEqual(self.state.script.scenes[0].script_text, 'A bus.')
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        with self.client:
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.script.scenes[0].script_text, 'JSON을 몰라도 문장을 수정합니다.')
        self.assertIsNone(self.state.final_video_path)
        self.assertFalse(self.state.is_script_reviewed())
        self.assertFalse(self.state.has_unapplied_script_draft())

    async def test_duration_field_accepts_saved_integer_and_fractional_seconds_without_step_mismatch(self):
        root = self.render()
        duration = self.field(root, '장면 예상 길이 (초)')
        self.assertEqual(duration._props['step'], 'any')
        with self.client:
            duration.set_value(5.25)
        await self.flush()
        self.assertEqual(self.state.script.scenes[0].duration_seconds, 5.0)
        self.assertEqual(json.loads(self.state.script_editor_text())['scenes'][0]['duration_seconds'], 5.25)
        with self.client:
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.script.scenes[0].duration_seconds, 5.25)

    async def test_advanced_changes_refresh_plain_fields_and_empty_narration_can_recover(self):
        root = self.render()
        draft = self.state.script.model_dump()
        draft['scenes'][0]['script_text'] = '고급 편집에서 수정한 문장'
        with self.client:
            self.field(root, '각본 JSON').set_value(json.dumps(draft, ensure_ascii=False))
        await self.flush()
        self.assertEqual(self.field(root, '장면 1 · 내레이션').value, '고급 편집에서 수정한 문장')
        with self.client:
            self.field(root, '장면 1 · 내레이션').set_value('')
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        self.assertEqual(self.state.script.scenes[0].script_text, 'A bus.')
        with self.client:
            self.field(root, '장면 1 · 내레이션').set_value('고친 문장')
            self.click(root, '수정 내용 되돌리기')
        await self.flush()
        self.assertFalse(self.state.has_unapplied_script_draft())
        self.assertEqual(self.field(root, '장면 1 · 내레이션').value, 'A bus.')
        self.assertEqual(self.state.final_video_path, 'kept.mp4')

    async def test_scene_switch_and_stale_field_merge_cannot_overwrite_advanced_changes(self):
        self.state.script.scenes.append(self.state.script.scenes[0].model_copy(update={'scene_number': 5}))
        self.state.confirm_script_review()
        root = self.render()
        old = self.field(root, '장면 1 · 내레이션')
        with self.client:
            self.field(root, '수정할 장면').set_value(5)
        await self.flush()
        with self.client:
            self.field(root, '장면 5 · 화면 설명·이미지 프롬프트').set_value('다섯 번째 장면의 모형 배치')
            self.field(root, '대본에 저장할 기본 화면 구성').set_value('hybrid')
        await self.flush()
        override = self.field(root, '이 장면의 화면 구성 · 혼합 모드에서 적용')
        self.assertTrue(override.enabled)
        with self.client:
            override.set_value('image')
        await self.flush()
        self.assertEqual(json.loads(self.state.script_editor_text())['scenes'][1]['visual_mode'], 'image')
        draft = json.loads(self.state.script_editor_text())
        draft['title'] = '고급 편집에서 바꾼 제목'
        with self.client:
            self.field(root, '각본 JSON').set_value(json.dumps(draft, ensure_ascii=False))
        await self.flush()
        before = self.state.script_editor_text()
        with self.client:
            old.set_value('늦게 도착한 이전 화면 값')
        await self.flush()
        self.assertEqual(self.state.script_editor_text(), before)
        self.assertEqual(json.loads(before)['scenes'][1]['visual_description'], '다섯 번째 장면의 모형 배치')

    def button(self, text):
        return next(e for e in reversed(list(self.client.elements.values())) if getattr(e, 'text', '') == text and not e.is_deleted)

    def invoke(self, button):
        next(e.handler for e in button._event_listeners.values() if e.type == 'click')(None)

    async def test_move_buttons_follow_playback_order_and_apply_invalidates_old_work(self):
        self.state.script.scenes.append(self.state.script.scenes[0].model_copy(update={'scene_number': 5, 'script_text': '결말'}))
        self.state.confirm_script_review()
        root = self.render()
        self.assertFalse(self.button('앞으로 이동').enabled)
        with self.client:
            self.click(root, '뒤로 이동')
        await self.flush()
        self.assertEqual([s['scene_number'] for s in self.state.script_form_data()['scenes']], [5, 1])
        self.assertEqual(self.field(root, '수정할 장면').value, 1)
        self.assertFalse(self.button('뒤로 이동').enabled)
        self.assertEqual([s.scene_number for s in self.state.script.scenes], [1, 5])
        self.assertTrue(self.state.is_script_reviewed())
        with self.client:
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual([s.scene_number for s in self.state.script.scenes], [5, 1])
        self.assertFalse(self.state.is_script_reviewed())
        self.assertIsNone(self.state.final_video_path)

    async def test_add_blank_fill_apply_and_deleted_old_field_cannot_overwrite(self):
        root = self.render()
        old_field = self.field(root, '장면 1 · 내레이션')
        with self.client:
            self.click(root, '이 장면 뒤에 추가')
        await self.flush()
        self.assertEqual(self.field(root, '수정할 장면').value, 2)
        self.assertTrue(old_field.is_deleted)
        before = self.state.script_editor_text()
        with self.client:
            old_field.set_value('늦게 도착한 입력')
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.script_editor_text(), before)
        self.assertEqual(len(self.state.script.scenes), 1)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        with self.client:
            self.field(root, '장면 2 · 내레이션').set_value('출처를 확인한 새로운 결말')
            self.field(root, '장면 2 · 화면 설명·이미지 프롬프트').set_value('명확한 결말의 화면 배치')
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual([s.scene_number for s in self.state.script.scenes], [1, 2])
        self.assertEqual(self.state.script.scenes[1].script_text, '출처를 확인한 새로운 결말')

    async def test_delete_confirmation_cancel_discard_and_last_scene_guard(self):
        self.state.script.scenes.append(self.state.script.scenes[0].model_copy(update={'scene_number': 5}))
        self.state.confirm_script_review()
        root = self.render()
        before = self.state.script_editor_text()
        with self.client:
            self.click(root, '장면 삭제')
            self.invoke(self.button('취소'))
        await self.flush()
        self.assertEqual(self.state.script_editor_text(), before)
        with self.client:
            self.field(root, '장면 1 · 내레이션').set_value('방금 수정한 삭제 대상 문장')
            self.click(root, '장면 삭제')
            self.assertTrue(any(getattr(e, 'text', '') == '방금 수정한 삭제 대상 문장'
                                for e in self.client.elements.values()))
            self.invoke(self.button('선택 장면 삭제'))
        await self.flush()
        self.assertEqual([s['scene_number'] for s in self.state.script_form_data()['scenes']], [5])
        self.assertFalse(self.button('장면 삭제').enabled)
        self.assertEqual(len(self.state.script.scenes), 2)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        with self.client:
            self.click(root, '수정 내용 되돌리기')
        await self.flush()
        self.assertFalse(self.state.has_unapplied_script_draft())
        self.assertEqual([s['scene_number'] for s in self.state.script_form_data()['scenes']], [1, 5])
        self.assertTrue(self.state.is_script_reviewed())

    async def test_old_confirmation_and_scene_buttons_cannot_change_newer_or_busy_view(self):
        self.state.script.scenes.append(self.state.script.scenes[0].model_copy(update={'scene_number': 5}))
        root = self.render()
        with self.client:
            self.click(root, '장면 삭제')
            confirm = self.button('선택 장면 삭제')
            self.field(root, '대본 제목').set_value('확인 창을 연 뒤 수정')
        before = self.state.script_editor_text()
        with self.client:
            self.invoke(confirm)
        await self.flush()
        self.assertEqual(self.state.script_editor_text(), before)
        old_button = self.button('뒤로 이동')
        with self.client:
            self.field(root, '수정할 장면').set_value(5)
        await self.flush()
        with self.client:
            self.invoke(old_button)
        self.assertEqual(self.state.script_editor_text(), before)
        self.state.pipeline_running = True
        with self.client:
            self.invoke(self.button('이 장면 뒤에 추가'))
        self.assertEqual(self.state.script_editor_text(), before)
        self.state.pipeline_running = False
        with self.client:
            self.click(root, '장면 삭제')
            confirm = self.button('선택 장면 삭제')
            root.clear()
            self.invoke(confirm)
        self.assertEqual(self.state.script_editor_text(), before)

    async def test_incomplete_structure_snapshot_reopens_in_fresh_session_without_authority(self):
        from shorts_maker.services.work_drafts import read_work_draft
        root = self.render()
        with self.client:
            self.click(root, '이 장면 뒤에 추가')
        await self.flush()
        path = self.state.save_work_draft()
        record, digest = read_work_draft(path.name)
        restored = AppState()
        restored.restore_work_draft(path.name, digest)
        self.assertEqual(restored.script_editor_text(), self.state.script_editor_text())
        self.assertEqual([s['scene_number'] for s in restored.script_form_data()['scenes']], [1, 2])
        self.assertEqual(restored.script_form_data()['scenes'][1]['script_text'], '')
        self.assertEqual(len(restored.script.scenes), 1)
        self.assertIsNone(restored.reviewed_script_sha256)
        self.assertIsNone(restored.final_video_path)
        self.assertEqual(len(record.applied_script.scenes), 1)

    async def test_noop_apply_preserves_receipt_and_consumed_draft_does_not_delete_other_script_draft(self):
        root = self.render()
        receipt = self.state.reviewed_script_sha256
        with self.client:
            self.click(root, '현재 작업에 적용')
        await self.flush()
        self.assertEqual(self.state.reviewed_script_sha256, receipt)
        self.assertEqual(self.state.final_video_path, 'kept.mp4')
        old_key = self.state.script_editor_key()
        edited = self.state.script.model_copy(update={'title': '적용할 제목'})
        edited_key = hashlib.sha256(edited.model_dump_json().encode()).hexdigest()
        other_draft = edited.model_copy(update={'title': '다른 화면에서 쓰던 별도 초안'}).model_dump_json()
        self.state.script_editor_drafts[edited_key] = other_draft
        with self.client:
            self.field(root, '대본 제목').set_value('적용할 제목')
            self.click(root, '수정 내용 적용')
        await self.flush()
        self.assertEqual(self.state.script.title, '적용할 제목')
        self.assertNotIn(old_key, self.state.script_editor_drafts)
        self.assertEqual(self.state.script_editor_drafts[edited_key], other_draft)
