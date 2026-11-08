"""애플리케이션 상태 관리"""

from dataclasses import dataclass, field
import hashlib
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from shorts_maker.utils.character_overlay import CharacterOverlayConfig
    from shorts_maker.planner.models import ShortsScript, ScriptGenerationContext, TopicCandidate
    from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress, SceneProgress


@dataclass
class AppState:
    """브라우저 세션의 UI 상태."""

    current_view: str = "workspace"
    workspace_sub_tab: str = "editor"

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
    script_context: Optional["ScriptGenerationContext"] = None
    topic_candidates: List["TopicCandidate"] = field(default_factory=list)
    scene_clips: List[str] = field(default_factory=list)
    generated_clips: List[str] = field(default_factory=list)
    final_video_path: Optional[str] = None
    youtube_upload_in_progress: bool = False

    # Service Reference (lazy init via property)
    _production_service: Optional["ProductionService"] = field(default=None, repr=False)

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
        return self.pipeline_running or self.youtube_upload_in_progress

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

        settings.update_api_keys(openai_key=self.openai_key, gcp_project=self.gcp_project)
        self._production_service = ProductionService(
            mode=self.mode,
            parallel_clips=parallel_clips,
            character_overlay_config=self.build_character_overlay_config(),
            editor_options=self._editor_options(),
        )
        return self._production_service

    # ── State mutators ────────────────────────────────────────────────────────

    def save_script_copy(self):
        from shorts_maker.services.script_store import save_script_copy
        from shorts_maker.utils.config import settings

        if self.is_busy or self.script is None:
            raise ValueError('작업이 끝난 뒤 저장할 대본을 확인하세요.')
        return save_script_copy(self.script, settings.scripts_dir)

    def invalidate_video_result(self):
        if self.is_busy:
            raise ValueError('작업 중에는 제작 결과를 변경할 수 없습니다.')
        self.reset_pipeline()
        self.final_video_path = None
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

        if self.script is None:
            raise ValueError('설정을 저장할 각본이 없습니다.')
        return save_audio_choices(self.script, {
            key: getattr(self, key) for key in ('tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume')
        })

    def load_saved_script(self, script) -> None:
        from shorts_maker.services.audio_choices import load_audio_choices

        if self.is_busy:
            raise ValueError('제작 또는 업로드가 진행 중에는 각본을 바꿀 수 없습니다.')
        if script.generation_mode not in {'image', 'hybrid', 'video'}:
            raise ValueError('각본의 제작 모드를 확인하세요.')
        choices = load_audio_choices(script)
        if choices is None:
            defaults = AppState()
            choices = {key: getattr(defaults, key)
                       for key in ('tts_voice', 'bgm_mood', 'bgm_track', 'bgm_volume')}
        for key, value in choices.items():
            setattr(self, key, value)
        self.reset_pipeline()
        self.reset_manual_mode()
        self.script = script
        self.mode = script.generation_mode
        self.script_context = None
        self.topic_candidates = []
        self.reviewed_script_sha256 = None
        self.final_video_path = None
        self.scene_clips = []
        self.generated_clips = []
        self._production_service = None

    def confirm_script_review(self) -> None:
        if self.script is None:
            raise ValueError("검토할 각본이 없습니다.")
        self.reviewed_script_sha256 = hashlib.sha256(
            self.script.model_dump_json().encode("utf-8")
        ).hexdigest()

    def script_editor_key(self) -> str:
        source = self.script.model_dump_json() if self.script else ''
        return hashlib.sha256(source.encode('utf-8')).hexdigest()

    def script_editor_text(self) -> str:
        return self.script_editor_drafts.get(
            self.script_editor_key(), self.script.model_dump_json(indent=2) if self.script else '')

    def remember_script_draft(self, key: str, text: str) -> None:
        if not self.is_busy and key == self.script_editor_key():
            self.script_editor_drafts[key] = text

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
