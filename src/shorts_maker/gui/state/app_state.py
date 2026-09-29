"""애플리케이션 상태 관리"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from shorts_maker.utils.character_overlay import CharacterOverlayConfig
    from shorts_maker.planner.models import ShortsScript, ScriptGenerationContext, TopicCandidate
    from shorts_maker.services.production_service import ProductionService, ProductionPhase, ProductionProgress, SceneProgress


@dataclass
class AppState:
    """전역 애플리케이션 상태"""

    # API Keys (사용자 입력)
    openai_key: str = ""
    gcp_project: str = ""

    # Production Mode
    mode: str = "video"  # "video" or "image"

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
    script_context: Optional["ScriptGenerationContext"] = None
    topic_candidates: List["TopicCandidate"] = field(default_factory=list)
    scene_clips: List[str] = field(default_factory=list)
    generated_clips: List[str] = field(default_factory=list)
    final_video_path: Optional[str] = None

    # Service Reference (lazy init via property)
    _production_service: Optional["ProductionService"] = field(default=None, repr=False)

    # Error State
    last_error: Optional[str] = None

    # History
    pipeline_history: List[Dict] = field(default_factory=list)

    # Editing Options - TTS
    tts_voice: str = "alloy"

    # Editing Options - BGM
    bgm_mood: str = "calm"
    bgm_volume: float = 0.15

    # Editing Options - Subtitles
    subtitle_color: str = "#FFFF00"
    subtitle_size: int = 60
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
    def production_service(self) -> Optional["ProductionService"]:
        return self._production_service

    @production_service.setter
    def production_service(self, value: Optional["ProductionService"]) -> None:
        self._production_service = value

    def get_or_create_service(self) -> "ProductionService":
        """현재 mode에 맞는 ProductionService를 반환. mode가 바뀌면 재생성."""
        from shorts_maker.services.production_service import ProductionService

        if self._production_service is None or self._production_service.mode != self.mode:
            char_config = self.build_character_overlay_config()
            self._production_service = ProductionService(
                mode=self.mode,
                character_overlay_config=char_config,
            )
        return self._production_service

    # ── State mutators ────────────────────────────────────────────────────────

    def reset_pipeline(self) -> None:
        """파이프라인 상태 초기화"""
        self.pipeline_running = False
        self.pipeline_phase = None
        self.pipeline_progress = 0.0
        self.pipeline_message = ""
        self.scene_progresses.clear()
        self.total_scenes = 0
        self.completed_scenes = 0
        self.current_scene = 0
        self.elapsed_seconds = 0.0
        self.estimated_seconds = 0.0
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
