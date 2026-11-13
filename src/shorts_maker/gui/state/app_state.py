"""애플리케이션 상태 관리"""

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from shorts_maker.utils.character_overlay import CharacterOverlayConfig
    from shorts_maker.planner.models import ShortsScript, ScriptGenerationContext, TopicCandidate
    from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress, SceneProgress
    from shorts_maker.services.youtube_connection import YouTubeConnection


@dataclass
class AppState:
    """브라우저 세션의 UI 상태."""

    current_view: str = "workspace"
    workspace_sub_tab: str = "editor"
    planning_source_mode: str = 'RSS 자동 발견'
    planning_url: str = ''
    planning_category: str = '전체 분야'
    rss_preview: Dict[str, Any] = field(default_factory=dict)

    # API Keys (사용자 입력)
    openai_key: str = ""
    gcp_project: str = ""

    # Production Mode
    mode: str = "hybrid"  # "hybrid", "video" or "image"

    # Pipeline State
    pipeline_running: bool = False
    pipeline_phase: Optional["ProductionPhase"] = None
    pipeline_progress: float = 0.0
    pipeline_message: str = ""

    # Scene Progress
    scene_progresses: List["SceneProgress"] = field(default_factory=list)
    total_scenes: int = 0
    completed_scenes: int = 0
    current_scene: int = 0

    # Timing
    elapsed_seconds: float = 0.0
    estimated_seconds: float = 0.0
    phase_times: Dict[str, float] = field(default_factory=dict)

    # Results
    script: Optional["ShortsScript"] = None
    reviewed_script_sha256: Optional[str] = None
    script_editor_drafts: Dict[str, str] = field(default_factory=dict, repr=False)
    first_frame_drafts: Dict[str, Dict[int, Dict[str, str]]] = field(default_factory=dict, repr=False)
    publishing_drafts: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)
    script_context: Optional["ScriptGenerationContext"] = None
    prepared_narration_manifest: Optional[str] = None
    prepared_narration_sha256: Optional[str] = None
    topic_candidates: List["TopicCandidate"] = field(default_factory=list)
    scene_clips: List[str] = field(default_factory=list)
    generated_clips: List[str] = field(default_factory=list)
    final_video_path: Optional[str] = None
    failed_video_preview_path: Optional[str] = None
    youtube_upload_in_progress: bool = False
    scheduled_planning_in_progress: bool = False
    media_import_in_progress: bool = False
    manual_clip_errors: Dict[str, str] = field(default_factory=dict, repr=False)
    operating_scope: Optional[Dict[str, str]] = None
    _execution_version: int = 0

    # Service Reference (lazy init via property)
    _production_service: Optional["ProductionService"] = field(default=None, repr=False)
    _youtube_connection: Optional['YouTubeConnection'] = field(default=None, repr=False)

    # Error State
    last_error: Optional[str] = None

    # History
    pipeline_history: List[Dict] = field(default_factory=list)

    # Editing Options - TTS
    tts_voice: str = "alloy"

    # Editing Options - BGM
    bgm_mood: str = "auto"
    bgm_track: str = ""
    bgm_volume: float = 0.2

    # Editing Options - Subtitles
    subtitle_color: str = "#F6F8FA"
    subtitle_size: int = 54
    subtitle_y_position: int = 1350

    # Character Overlay Options
    character_overlay_enabled: bool = False
    character_image_path: str = "assets/character_ref.png"
    character_video_path: Optional[str] = None
    character_position: str = "bottom_right"
    character_size_ratio: float = 0.25
    character_border_color: str = "#00FFFF"

    # Chroma Key Options
    chroma_key_enabled: bool = False
    chroma_key_color: str = "green"
    chroma_key_threshold: float = 0.3

    # 수동 생성 모드
    manual_video_mode: bool = False
    manual_script_id: str = ""

    # ── Service accessor ──────────────────────────────────────────────────────

    @property
    def is_busy(self) -> bool:
        return (self.pipeline_running or self.youtube_upload_in_progress or self.scheduled_planning_in_progress or self.media_import_in_progress
                or bool(self._youtube_connection and self._youtube_connection.running))

    def get_youtube_connection(self) -> 'YouTubeConnection':
        from shorts_maker.services.youtube_connection import YouTubeConnection
        if self._youtube_connection is None:
            self._youtube_connection = YouTubeConnection()
        return self._youtube_connection

    @property
    def production_service(self) -> Optional["ProductionService"]:
        return self._production_service

    @production_service.setter
    def production_service(self, value: Optional["ProductionService"]) -> None:
        self._production_service = value

    def get_or_create_service(self) -> "ProductionService":
        """Reuse the current planning service while its credentials and mode are current."""
        from shorts_maker.utils.config import settings

        # Keep cancellation and progress attached to the active task until it finishes.
        if self.is_busy and self._production_service is not None:
            return self._production_service
        overlay = self.build_character_overlay_config()
        if (self._production_service is None
                or getattr(self._production_service, 'scope', None) != self.operating_scope
                or (self.operating_scope and self._production_service.review_receipt != self.reviewed_script_sha256)
                or self._production_service.mode != self.mode
                or self._production_service.editor_options != self._editor_options()
                or (self._production_service.character_overlay_config.to_dict()
                    if self._production_service.character_overlay_config else None) != (
                        overlay.to_dict() if overlay else None)
                or self._production_service.is_cancelled()
                or (self.openai_key and self.openai_key != settings.openai_api_key)
                or (self.gcp_project and self.gcp_project != settings.gcp_project_id)):
            return self.new_production_service()
        return self._production_service

    def _editor_options(self) -> Dict[str, Any]:
        return {
            "tts_voice": self.tts_voice,
            "bgm_mood": self.bgm_mood,
            "bgm_track": self.bgm_track or None,
            "bgm_volume": self.bgm_volume,
            "subtitle_color": self.subtitle_color,
            "subtitle_size": self.subtitle_size,
            "subtitle_y_position": self.subtitle_y_position,
        }

    def new_production_service(self, parallel_clips: bool = False) -> "ProductionService":
        """Create one configured service for a new production run."""
        from shorts_maker.services.production_service import ProductionService
        from shorts_maker.utils.config import settings

        if self.operating_scope:
            from shorts_maker.services.scoped_production import ScopedProductionService
            factory = lambda **options: ScopedProductionService(self.operating_scope, self.reviewed_script_sha256, **options)
        else:
            settings.update_api_keys(openai_key=self.openai_key, gcp_project=self.gcp_project)
            factory = ProductionService
        self._production_service = factory(
            mode=self.mode,
            parallel_clips=parallel_clips,
            character_overlay_config=self.build_character_overlay_config(),
            editor_options=self._editor_options(),
        )
        return self._production_service

    def execution_key(self) -> tuple:
        return self._execution_version, json.dumps(self.operating_scope, sort_keys=True)

    @property
    def video_model_label(self) -> str:
        from shorts_maker.services.operating_budget import episode_video_spec
        from shorts_maker.utils.config import settings
        model = episode_video_spec(self.mode)[0] if self.operating_scope else settings.veo_model_id
        return f'영상 모델 · {model}' + (' · 회차 고정' if self.operating_scope else '')

    def require_execution_context(self, expected: tuple) -> None:
        if self.execution_key() != expected:
            raise ValueError('제작 회차 연결이 바뀌었습니다. 현재 화면을 다시 열어 주세요.')
        if self.operating_scope:
            from shorts_maker.utils.paid_gate import require_paid_production_enabled
            from shorts_maker.services.studio_episode_action import EpisodeScope, scope_status
            require_paid_production_enabled()
            scope_status(EpisodeScope.model_validate(self.operating_scope), self.script)

    def load_scheduled_script(self, manager, schedule_id: str) -> None:
        from shorts_maker.planner.models import ShortsScript
        from shorts_maker.services.studio_episode_action import EpisodeScope, scope_status
        current = manager.get_schedule(schedule_id)
        if not current or current.get('review_operator') != 'agent':
            raise ValueError('에이전트 회차를 선택하세요.')
        scope = EpisodeScope(schedules_file=str(manager.filename.resolve()), schedule_id=schedule_id,
                             episode_id=current.get('last_episode_id'))
        current, _ = scope_status(scope)
        script = ShortsScript.model_validate(current['last_script'])
        self.load_saved_script(script)
        self.operating_scope = scope.model_dump()
        self._execution_version += 1

    def detach_operating_scope(self) -> None:
        if self.is_busy:
            raise ValueError('진행 중인 회차 작업이 끝난 뒤 전환하세요.')
        self.operating_scope = None
        self._execution_version += 1
        self._production_service = None

    # ── State mutators ────────────────────────────────────────────────────────

    def save_script_copy(self):
        from shorts_maker.services.script_store import save_script_copy
        from shorts_maker.utils.config import settings

        if self.is_busy or self.script is None:
            raise ValueError('작업이 끝난 뒤 저장할 대본을 확인하세요.')
        return save_script_copy(self.script, settings.scripts_dir)

    def planning_input(self) -> dict:
        return {'mode': self.planning_source_mode, 'url': self.planning_url, 'category': self.planning_category}

    def has_planning_input(self) -> bool:
        return self.planning_input() != {'mode': 'RSS 자동 발견', 'url': '', 'category': '전체 분야'}

    def save_work_draft(self):
        from shorts_maker.services.work_drafts import save_work_draft

        if self.is_busy:
            raise ValueError('제작·업로드가 끝난 뒤 작업 초안을 저장하세요.')
        return save_work_draft(self.script, self.script_editor_text(),
                               self.first_frame_drafts.get(self.script_editor_key(), {}),
                               planning_input=self.planning_input())

    def open_historical_script(self, script):
        """Keep current text work before opening a review-only historical copy."""
        if self.is_busy:
            raise ValueError('진행 중인 작업이 끝난 뒤 과거 대본을 여세요.')
        backups = self._backup_text_work(script, save_applied=True)
        self.load_saved_script(script)
        self.script_editor_drafts.pop(self.script_editor_key(), None)
        self.first_frame_drafts.pop(self.script_editor_key(), None)
        return backups

    def restore_work_draft(self, name: str, expected_sha256: str):
        from shorts_maker.services.work_drafts import read_work_draft

        if self.is_busy:
            raise ValueError('제작·업로드가 끝난 뒤 작업 초안을 복원하세요.')
        record, digest = read_work_draft(name)
        if digest != expected_sha256:
            raise ValueError('목록을 읽은 뒤 초안 파일이 바뀌었습니다. 목록을 새로고침하세요.')
        source_changed = record.planning_input is not None and record.planning_input != self.planning_input()
        if source_changed and self.rss_preview.get('loading'):
            raise ValueError('RSS 후보 조회가 끝난 뒤 기획 입력을 복원하세요.')
        source_only = (record.planning_input is not None and record.applied_script is None
                       and not record.editor_text.strip() and not record.first_frames)
        if source_only:
            backups = [self.save_work_draft()] if source_changed and self.has_planning_input() else []
        else:
            backups = self._backup_text_work(
                record.applied_script, save_applied=(record.script_sha256 != self.script_editor_key()
                                                    or source_changed and self.has_planning_input()))
            self.load_saved_script(record.applied_script)
            self.script_editor_drafts[record.script_sha256] = record.editor_text
            self.first_frame_drafts[record.script_sha256] = {int(number): values for number, values in record.first_frames.items()}
        if source_changed:
            self.planning_source_mode = record.planning_input['mode']
            self.planning_url = record.planning_input['url']
            self.planning_category = record.planning_input['category']
            self.rss_preview = {}
        return backups

    def _backup_text_work(self, target_script, *, save_applied=False):
        from shorts_maker.services.work_drafts import save_work_draft, script_draft_key
        current_key, target_key = self.script_editor_key(), script_draft_key(target_script)
        backups = []
        applied_text = self.script.model_dump_json(indent=2) if self.script else ''
        if ((save_applied and (self.script is not None or self.script_editor_text() or self.has_planning_input()))
                or self.script_editor_text() != applied_text or self.first_frame_drafts.get(current_key)):
            backups.append(self.save_work_draft())
        target_text = target_script.model_dump_json(indent=2) if target_script else ''
        text = self.script_editor_drafts.get(target_key, target_text)
        if target_key != current_key and (text != target_text or self.first_frame_drafts.get(target_key)):
            backups.append(save_work_draft(target_script, text, self.first_frame_drafts.get(target_key, {})))
        return backups

    def invalidate_video_result(self):
        if self.is_busy:
            raise ValueError('작업 중에는 제작 결과를 변경할 수 없습니다.')
        self.reset_pipeline()
        self.final_video_path = None
        self.failed_video_preview_path = None
        self.scene_clips = []
        self.generated_clips = []
        self._production_service = None

    def restore_manual_workspace(self, script_id: str):
        from shorts_maker.utils.veo_prompt_exporter import VeoPromptExporter

        if self.is_busy or self.script is None or not self.manual_video_mode:
            raise ValueError('작업이 끝난 뒤 현재 대본의 보유 영상 연결 화면에서 복원하세요.')
        VeoPromptExporter().validate_workspace(self.script, script_id)
        self.invalidate_video_result()
        self.manual_script_id = script_id

    def save_audio_choices(self):
        from shorts_maker.services.audio_choices import save_audio_choices

        if self.is_busy or self.script is None:
            raise ValueError('작업이 끝난 뒤 설정을 저장할 각본을 확인하세요.')
        choices = {
            key: getattr(self, key) for key in ('tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume',
                                               'prepared_narration_manifest', 'prepared_narration_sha256')
        }
        if self.prepared_narration_manifest and self.prepared_narration_sha256 is None:
            self.prepared_audio_paths()
            choices['prepared_narration_sha256'] = hashlib.sha256(Path(self.prepared_narration_manifest).read_bytes()).hexdigest()
        return save_audio_choices(self.script, choices)

    def prepared_audio_paths(self) -> Optional[List[str]]:
        from shorts_maker.services.prepared_narration import narration_paths

        if self.prepared_narration_manifest is None:
            return None
        if self.script is None:
            raise ValueError('내레이션을 사용할 대본이 없습니다.')
        return narration_paths(self.script, self.prepared_narration_manifest, self.prepared_narration_sha256)

    def select_prepared_narration(self, manifest_path: Optional[str]) -> None:
        from shorts_maker.services.prepared_narration import narration_paths
        from shorts_maker.editor.video_editor import VideoEditor

        if self.is_busy or self.script is None:
            raise ValueError('작업이 끝난 뒤 현재 대본의 음성을 선택하세요.')
        digest = None
        if manifest_path:
            paths = narration_paths(self.script, manifest_path)
            VideoEditor.validate_narration(paths, self.script)
            manifest_path = str(Path(manifest_path).resolve())
            digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        if (manifest_path or None) == self.prepared_narration_manifest and digest == self.prepared_narration_sha256:
            return
        self.invalidate_video_result()
        self.prepared_narration_manifest = manifest_path or None
        self.prepared_narration_sha256 = digest

    def load_saved_script(self, script) -> None:
        from shorts_maker.services.audio_choices import load_audio_choices

        if self.is_busy:
            raise ValueError('제작 또는 업로드가 진행 중에는 각본을 바꿀 수 없습니다.')
        if script is not None and script.generation_mode not in {'image', 'hybrid', 'video'}:
            raise ValueError('각본의 제작 모드를 확인하세요.')
        choices = load_audio_choices(script) if script is not None else None
        if choices is None:
            defaults = AppState()
            choices = {key: getattr(defaults, key)
                       for key in ('tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume',
                                   'prepared_narration_manifest', 'prepared_narration_sha256')}
        for key, value in choices.items():
            setattr(self, key, value)
        self.reset_pipeline()
        self.reset_manual_mode()
        self.script = script
        self.mode = script.generation_mode if script is not None else defaults.mode
        self.script_context = None
        self.topic_candidates = []
        self.reviewed_script_sha256 = None
        self.final_video_path = None
        self.failed_video_preview_path = None
        self.scene_clips = []
        self.generated_clips = []
        self._production_service = None

    @property
    def preview_video_path(self) -> Optional[str]:
        return self.final_video_path or self.failed_video_preview_path

    def confirm_script_review(self) -> None:
        if self.script is None:
            raise ValueError("검토할 각본이 없습니다.")
        self.reviewed_script_sha256 = hashlib.sha256(
            self.script.model_dump_json().encode("utf-8")
        ).hexdigest()

    def script_editor_key(self) -> str:
        from shorts_maker.services.work_drafts import script_draft_key
        return script_draft_key(self.script)

    def script_editor_text(self) -> str:
        return self.script_editor_drafts.get(
            self.script_editor_key(), self.script.model_dump_json(indent=2) if self.script else '')

    def remember_script_draft(self, key: str, text: str) -> None:
        if not self.is_busy and key == self.script_editor_key():
            self.script_editor_drafts[key] = text

    def script_form_data(self) -> dict:
        """Read the shared draft without rejecting temporary empty text/number fields."""
        data = json.loads(self.script_editor_text())
        if not isinstance(data, dict) or not isinstance(data.get('scenes'), list) or not data['scenes']:
            raise ValueError('고급 JSON의 대본·장면 구조를 수정하거나 미적용 수정을 되돌리세요.')
        numbers = []
        for scene in data['scenes']:
            if (not isinstance(scene, dict) or type(scene.get('scene_number')) is not int
                    or scene['scene_number'] < 1
                    or any(not isinstance(scene.get(field, ''), str)
                           for field in ('script_text', 'visual_description', 'motion_instruction'))):
                raise ValueError('고급 JSON의 장면 번호·텍스트 구조를 확인하세요.')
            numbers.append(scene['scene_number'])
            duration = scene.get('duration_seconds', 5.0)
            if duration is not None and (type(duration) not in {int, float} or not math.isfinite(duration)):
                raise ValueError('고급 JSON의 장면 예상 길이는 숫자여야 합니다.')
            if not isinstance(scene.get('visual_mode'), (str, type(None))):
                raise ValueError('고급 JSON의 장면 화면 구성을 확인하세요.')
        if len(set(numbers)) != len(numbers) or any(not isinstance(data.get(field, ''), str)
                                                    for field in ('title', 'description', 'generation_mode')):
            raise ValueError('고급 JSON의 제목·설명·중복 장면 번호를 확인하세요.')
        if not isinstance(data.get('mood'), (str, type(None))):
            raise ValueError('고급 JSON의 음악 분위기는 문자열 또는 미선택이어야 합니다.')
        return data

    def update_script_form_field(self, key: str, expected_text: str, field: str, value,
                                 scene_number: Optional[int] = None) -> bool:
        if self.is_busy or key != self.script_editor_key():
            raise ValueError('작업 중이거나 대본이 바뀌었습니다. 현재 편집 화면을 다시 여세요.')
        if expected_text != self.script_editor_text():
            raise ValueError('다른 편집 화면에서 초안이 바뀌었습니다. 편집 화면을 새로고침하세요.')
        data = self.script_form_data()
        if scene_number is None:
            if field not in {'title', 'description', 'generation_mode', 'mood'} or not isinstance(value, str):
                raise ValueError('수정할 대본 항목을 확인하세요.')
            if field == 'mood':
                from shorts_maker.planner.script_planner import ScriptPlanner
                if value not in ScriptPlanner.SUPPORTED_MOODS:
                    raise ValueError('대본 음악 분위기를 목록에서 선택하세요.')
            if field == 'generation_mode' and value not in {'hybrid', 'image', 'video'}:
                raise ValueError('대본의 기본 화면 구성을 선택하세요.')
            target = data
        else:
            if field not in {'script_text', 'visual_description', 'motion_instruction', 'duration_seconds', 'visual_mode'}:
                raise ValueError('수정할 장면 항목을 확인하세요.')
            if field in {'script_text', 'visual_description', 'motion_instruction'} and not isinstance(value, str):
                raise ValueError('장면 내용은 텍스트로 입력하세요.')
            if field == 'visual_mode' and value not in {None, 'image', 'video'}:
                raise ValueError('장면의 화면 구성을 선택하세요.')
            if field == 'duration_seconds' and value is not None and (
                    type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError('장면 예상 길이는 유한한 숫자로 입력하세요.')
            target = next((scene for scene in data['scenes'] if scene['scene_number'] == scene_number), None)
            if target is None:
                raise ValueError('장면이 바뀌었습니다. 현재 편집 화면을 다시 여세요.')
        if target.get(field) == value:
            return False
        target[field] = value
        self.script_editor_drafts[key] = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        return True

    def change_script_scene(self, key: str, expected_text: str, action: str, scene_number: int) -> int:
        """Change draft order only; scene IDs and applied media/reviews stay untouched."""
        if self.is_busy or key != self.script_editor_key():
            raise ValueError('작업 중이거나 대본이 바뀌었습니다. 현재 편집 화면을 다시 여세요.')
        if expected_text != self.script_editor_text():
            raise ValueError('다른 편집 화면에서 초안이 바뀌었습니다. 편집 화면을 새로고침하세요.')
        data = self.script_form_data()
        scenes = data['scenes']
        index = next((i for i, scene in enumerate(scenes)
                      if type(scene_number) is int and scene['scene_number'] == scene_number), None)
        if index is None or action not in {'add', 'remove', 'earlier', 'later'}:
            raise ValueError('변경할 장면과 작업을 확인하세요.')
        if action == 'add':
            scene_number = max([s['scene_number'] for s in scenes]
                               + ([s.scene_number for s in self.script.scenes] if self.script else [])) + 1
            scenes.insert(index + 1, {'scene_number': scene_number, 'script_text': '', 'visual_description': '',
                                      'motion_instruction': '', 'duration_seconds': 5.0, 'visual_mode': None})
        elif action == 'remove':
            if len(scenes) == 1:
                raise ValueError('대본에는 장면이 하나 이상 있어야 합니다.')
            scenes.pop(index)
            scene_number = scenes[min(index, len(scenes) - 1)]['scene_number']
        else:
            other = index + (-1 if action == 'earlier' else 1)
            if other < 0 or other >= len(scenes):
                return scene_number
            scenes[index], scenes[other] = scenes[other], scenes[index]
        self.script_editor_drafts[key] = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        return scene_number

    def has_unapplied_first_frame_draft(self, scene_number: int) -> bool:
        return bool(self.first_frame_drafts.get(self.script_editor_key(), {}).get(scene_number))

    def has_unapplied_first_frame_drafts(self) -> bool:
        from shorts_maker.services.visual_cost import scene_mode
        return bool(self.script and not self.manual_video_mode and any(
            self.has_unapplied_first_frame_draft(scene.scene_number)
            for index, scene in enumerate(self.script.scenes) if scene_mode(self.mode, scene, index) == 'video'))

    def has_unapplied_script_draft(self) -> bool:
        from shorts_maker.planner.models import ShortsScript

        draft = self.script_editor_drafts.get(self.script_editor_key())
        if draft is None or (self.script is None and not draft.strip()):
            return False
        try:
            parsed = ShortsScript.model_validate_json(draft)
            return self.script is None or parsed.model_dump_json() != self.script.model_dump_json()
        except ValueError:
            return True

    def is_script_reviewed(self) -> bool:
        return bool(self.script and self.reviewed_script_sha256 == hashlib.sha256(
            self.script.model_dump_json().encode("utf-8")
        ).hexdigest())

    def reset_pipeline(self) -> None:
        """파이프라인 상태 초기화"""
        self.pipeline_running = False
        self.pipeline_phase = None
        self.pipeline_progress = 0.0
        self.pipeline_message = ""
        self.scene_progresses = []
        self.total_scenes = 0
        self.completed_scenes = 0
        self.current_scene = 0
        self.elapsed_seconds = 0.0
        self.estimated_seconds = 0.0
        self.phase_times = {}
        self.last_error = None

    def reset_manual_mode(self) -> None:
        """수동 모드 상태 초기화 (스크립트 변경 시 호출)"""
        self.manual_script_id = ""

    def add_to_history(self, title: str, success: bool) -> None:
        """실행 이력에 추가"""
        self.pipeline_history.append({
            'title': title,
            'success': success,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        })

    def get_recent_history(self, limit: int = 5) -> List[Dict]:
        """최근 실행 이력 조회"""
        return list(reversed(self.pipeline_history[-limit:]))

    def sync_from_progress(self, progress: "ProductionProgress") -> None:
        """ProductionProgress 데이터를 state 필드에 동기화"""
        self.pipeline_phase = progress.phase
        self.pipeline_progress = progress.progress_percent
        self.pipeline_message = progress.message
        self.scene_progresses = progress.scene_progresses
        self.total_scenes = progress.total_scenes
        self.completed_scenes = progress.completed_scenes
        self.current_scene = getattr(progress, 'current_scene', self.current_scene)
        self.elapsed_seconds = progress.elapsed_seconds
        self.estimated_seconds = progress.remaining_seconds

    def build_character_overlay_config(self) -> Optional["CharacterOverlayConfig"]:
        """state의 캐릭터 설정으로 CharacterOverlayConfig 생성. 비활성화 시 None 반환."""
        if not self.character_overlay_enabled:
            return None

        from shorts_maker.utils.character_overlay import CharacterOverlayConfig
        config = CharacterOverlayConfig()
        config.enabled = True
        config.character_image = self.character_image_path
        config.character_video = self.character_video_path if self.character_video_path else None
        config.position = self.character_position
        config.size_ratio = self.character_size_ratio
        try:
            hex_color = self.character_border_color.lstrip('#')
            config.border_color = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        except (ValueError, IndexError):
            config.border_color = (255, 255, 255)
        config.chroma_key_enabled = self.chroma_key_enabled
        config.chroma_key_color = self.chroma_key_color
        config.chroma_key_threshold = self.chroma_key_threshold
        return config
