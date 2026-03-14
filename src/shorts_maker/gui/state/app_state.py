"""애플리케이션 상태 관리"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


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
    pipeline_phase: Any = None  # ProductionPhase enum
    pipeline_progress: float = 0.0
    pipeline_message: str = ""

    # Scene Progress
    scene_progresses: Dict[int, float] = field(default_factory=dict)
    total_scenes: int = 0
    completed_scenes: int = 0
    current_scene: int = 0

    # Timing
    elapsed_seconds: float = 0.0
    estimated_seconds: float = 0.0
    phase_times: Dict[str, float] = field(default_factory=dict)

    # Results
    script: Any = None
    scene_clips: List[str] = field(default_factory=list)
    generated_clips: List[str] = field(default_factory=list)
    final_video_path: Optional[str] = None

    # Service Reference
    production_service: Any = None

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
    manual_script_id: str = ""                                    # 현재 스크립트 ID (clips 폴더명)
    manual_clip_paths: Dict[int, str] = field(default_factory=dict)  # {scene_number: file_path}

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
        self.manual_clip_paths.clear()

    def add_to_history(self, title: str, success: bool) -> None:
        """실행 이력에 추가"""
        self.pipeline_history.append({
            'title': title,
            'success': success,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        })

    def get_recent_history(self, limit: int = 5) -> List[Dict]:
        """최근 실행 이력 조회"""
        return list(reversed(self.pipeline_history[-limit:]))


# 싱글톤 인스턴스
state = AppState()
