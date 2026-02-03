"""
ShortsMaker 중앙 설정 관리 모듈.
환경변수와 기본값을 통합 관리합니다.

설정 파일 우선순위:
1. config/.env (권장)
2. 프로젝트 루트 .env (하위 호환)

인증 파일 우선순위:
1. config/credentials/ 폴더
2. 프로젝트 루트 (하위 호환)
"""
import os
import sys
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# 프로젝트 루트 경로 탐지
def _find_project_root() -> Path:
    """pyproject.toml 또는 .git이 있는 프로젝트 루트 탐색"""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return current

PROJECT_ROOT = _find_project_root()

# .env 파일 로드 (우선순위: config/.env > 루트/.env)
_config_env = PROJECT_ROOT / "config" / ".env"
_root_env = PROJECT_ROOT / ".env"

if _config_env.exists():
    load_dotenv(_config_env)
elif _root_env.exists():
    load_dotenv(_root_env)


def _find_credential_file(filename: str) -> Path:
    """인증 파일 경로 탐색 (config/credentials/ 우선, 루트 폴백)"""
    config_path = PROJECT_ROOT / "config" / "credentials" / filename
    root_path = PROJECT_ROOT / filename

    if config_path.exists():
        return config_path
    elif root_path.exists():
        return root_path
    # 기본값: config/credentials/ 경로 반환 (파일 생성 위치 안내용)
    return config_path


@dataclass
class Settings:
    """애플리케이션 설정 클래스"""

    # API Keys
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    gcp_project_id: str = field(default_factory=lambda: os.getenv("GCP_PROJECT_ID", ""))
    gcp_location: str = field(default_factory=lambda: os.getenv("GCP_LOCATION", "us-central1"))
    pixabay_api_key: str = field(default_factory=lambda: os.getenv("PIXABAY_API_KEY", ""))

    # Character Assets
    character_image_path: Path = field(
        default_factory=lambda: Path(os.getenv("CHARACTER_IMAGE_PATH", str(PROJECT_ROOT / "assets" / "character_ref.png")))
    )
    character_video_path: Path = field(
        default_factory=lambda: Path(os.getenv("CHARACTER_VIDEO_PATH", str(PROJECT_ROOT / "assets" / "character_video.mp4")))
    )

    # Model IDs
    veo_model_id: str = field(default_factory=lambda: os.getenv("VEO_MODEL_ID", "veo-3.1-fast-generate-001"))
    imagen_model_id: str = "imagen-3.0-generate-001"

    # Generation Mode
    generation_mode: str = field(default_factory=lambda: os.getenv("GENERATION_MODE", "video"))

    # Credential Paths (자동 탐색)
    service_account_path: Path = field(default_factory=lambda: _find_credential_file("service_account.json"))
    client_secrets_path: Path = field(default_factory=lambda: _find_credential_file("client_secrets.json"))
    token_file_path: Path = field(default_factory=lambda: _find_credential_file("token.json"))

    # Directory Paths
    temp_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "temp")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "outputs")
    scripts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "outputs" / "scripts")
    bgm_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "bgm")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    assets_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "assets")
    config_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "config")
    credentials_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "config" / "credentials")

    # History Files
    topic_history_file: Path = field(default_factory=lambda: PROJECT_ROOT / "topic_history.json")
    url_history_file: Path = field(default_factory=lambda: PROJECT_ROOT / "url_history.json")
    rss_sources_file: Path = field(default_factory=lambda: PROJECT_ROOT / "rss_sources.json")

    # Video Settings
    max_shorts_duration: float = 59.0
    target_duration: float = 58.5
    video_fps: int = 24
    video_width: int = 1080
    video_height: int = 1920

    # Performance Settings
    scene_buffer_seconds: int = 10
    max_rss_items_per_category: int = 5
    rss_cache_ttl_minutes: int = 30
    max_topic_retries: int = 5
    max_api_retries: int = 3

    # TTS Settings
    tts_model: str = "tts-1"
    default_voice: str = "alloy"

    def __post_init__(self):
        """디렉토리 자동 생성 및 환경변수 설정"""
        # 디렉토리 생성
        for dir_path in [self.temp_dir, self.output_dir, self.scripts_dir,
                         self.bgm_dir, self.logs_dir, self.config_dir,
                         self.credentials_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Google Cloud 인증 환경변수 자동 설정
        if self.service_account_path.exists():
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS",
                                  str(self.service_account_path.absolute()))

    def update_api_keys(
        self,
        openai_key: Optional[str] = None,
        gcp_project: Optional[str] = None
    ) -> None:
        """
        GUI에서 입력된 API 키로 설정을 동적으로 업데이트합니다.
        환경변수를 직접 수정하는 대신 이 메서드를 사용하세요.

        Args:
            openai_key: OpenAI API 키 (None이면 변경하지 않음)
            gcp_project: GCP 프로젝트 ID (None이면 변경하지 않음)
        """
        if openai_key:
            self.openai_api_key = openai_key
        if gcp_project:
            self.gcp_project_id = gcp_project

    def validate(self) -> list[str]:
        """설정 유효성 검증, 문제 목록 반환"""
        issues = []

        if not self.openai_api_key:
            issues.append("OPENAI_API_KEY가 설정되지 않았습니다.")
        elif not self.openai_api_key.startswith("sk-"):
            issues.append("OPENAI_API_KEY 형식이 올바르지 않습니다 (sk-로 시작해야 함).")

        if not self.gcp_project_id:
            issues.append("GCP_PROJECT_ID가 설정되지 않았습니다.")

        if not self.service_account_path.exists():
            issues.append(f"서비스 계정 파일이 없습니다: {self.service_account_path}")

        return issues

    def get_credential_path(self) -> Optional[str]:
        """Google Cloud 인증 경로 반환"""
        if self.service_account_path.exists():
            return str(self.service_account_path)
        return None

    def print_status(self):
        """설정 상태를 콘솔에 출력"""
        print("=" * 50)
        print("🎬 ShortsMaker Configuration Status")
        print("=" * 50)
        print()

        # API Keys
        print("📌 API Keys:")
        if self.openai_api_key:
            masked = self.openai_api_key[:10] + "..." + self.openai_api_key[-4:]
            print(f"   OpenAI:   ✅ {masked}")
        else:
            print("   OpenAI:   ❌ Not set")

        if self.pixabay_api_key:
            masked = self.pixabay_api_key[:10] + "..." + self.pixabay_api_key[-4:]
            print(f"   Pixabay:  ✅ {masked}")
        else:
            print("   Pixabay:  ⚠️  Not set (optional)")
        print()

        # Google Cloud
        print("☁️  Google Cloud:")
        print(f"   Project:  {self.gcp_project_id or '❌ Not set'}")
        print(f"   Location: {self.gcp_location}")
        print(f"   Veo:      {self.veo_model_id}")
        print()

        # Credentials
        print("🔐 Credentials:")
        sa_status = "✅" if self.service_account_path.exists() else "❌"
        print(f"   Service Account: {sa_status} {self.service_account_path}")

        yt_status = "✅" if self.client_secrets_path.exists() else "⚠️  (optional)"
        print(f"   YouTube OAuth:   {yt_status} {self.client_secrets_path}")
        print()

        # Validation
        issues = self.validate()
        if issues:
            print("⚠️  Issues Found:")
            for issue in issues:
                print(f"   - {issue}")
        else:
            print("✅ All configurations valid!")

        print("=" * 50)


# 싱글톤 인스턴스
settings = Settings()


# CLI 지원
if __name__ == "__main__":
    if "--validate" in sys.argv:
        settings.print_status()
        issues = settings.validate()
        sys.exit(1 if issues else 0)
    else:
        print("Usage: python -m shorts_maker.utils.config --validate")
        print("  Validates all configuration settings and credentials.")
