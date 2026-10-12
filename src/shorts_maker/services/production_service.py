"""
ProductionService - 비디오 프로덕션 워크플로우를 추상화하는 서비스 레이어.

GUI와 비즈니스 로직을 분리하여 유지보수성과 테스트 용이성을 높입니다.
"""
import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from PIL import Image
from moviepy import VideoFileClip

from shorts_maker.planner.script_planner import ScriptPlanner, ShortsScript
from shorts_maker.planner.models import ScriptGenerationContext
from shorts_maker.generator.video_generator import VIDEO_PROMPT_VERSION, VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.uploader.youtube_uploader import YouTubeUploader
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.bgm_manager import BGMManager
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.utils.config import settings
from shorts_maker.editor.quality_check import check_video_quality
from shorts_maker.services.visual_cost import estimated_scene_cost, scene_mode
from shorts_maker.services.google_budget import check_google_budget


class ProductionPhase(Enum):
    """프로덕션 단계 열거형"""
    IDLE = "idle"
    PLANNING = "planning"
    GENERATING = "generating"
    EDITING = "editing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SceneProgress:
    """개별 씬의 진행 상황"""
    scene_number: int
    status: str = "pending"  # pending, processing, completed, failed
    thumbnail_path: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time


@dataclass
class ProductionProgress:
    """프로덕션 진행 상황을 추적하는 데이터 클래스"""
    phase: ProductionPhase = ProductionPhase.IDLE
    progress_percent: float = 0.0
    message: str = ""
    error: Optional[str] = None

    # 세부 진행 정보
    total_scenes: int = 0
    completed_scenes: int = 0
    current_scene: int = 0
    scene_progresses: List[SceneProgress] = field(default_factory=list)

    # 시간 추적
    phase_start_time: Optional[float] = None
    estimated_total_seconds: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        if self.phase_start_time is None:
            return 0.0
        return time.time() - self.phase_start_time

    @property
    def remaining_seconds(self) -> float:
        if self.estimated_total_seconds <= 0 or self.progress_percent <= 0:
            return 0.0
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return self.estimated_total_seconds
        # 현재 진행률 기반 예상
        estimated_total = elapsed / (self.progress_percent / 100)
        return max(0, estimated_total - elapsed)


@dataclass
class ProductionResult:
    """프로덕션 결과를 담는 데이터 클래스"""
    success: bool
    video_path: Optional[str] = None
    youtube_id: Optional[str] = None
    error: Optional[str] = None
    clips: List[str] = field(default_factory=list)
    script: Optional[ShortsScript] = None
    ready_for_upload: bool = False
    estimated_visual_cost_usd: float = 0.0
    generated_scenes: int = 0
    reused_scenes: int = 0
    report_path: Optional[str] = None


class ProductionService:
    """
    비디오 프로덕션 워크플로우를 관리하는 서비스 클래스.

    이 클래스는 스크립트 생성, 비주얼 생성, 비디오 편집, YouTube 업로드의
    전체 프로덕션 파이프라인을 조율합니다.
    """

    # 단계별 예상 소요 시간 (초) - 모드에 따라 다름
    ESTIMATED_TIMES = {
        "image": {
            "planning": 30,
            "generating_per_scene": 15,
            "editing_per_scene": 20,
            "uploading": 60
        },
        "hybrid": {
            "planning": 30,
            "generating_per_scene": 35,
            "editing_per_scene": 20,
            "uploading": 60,
        },
        "video": {
            "planning": 30,
            "generating_per_scene": 120,  # Veo는 훨씬 오래 걸림
            "editing_per_scene": 25,
            "uploading": 60
        }
    }

    PAID_WORK_DISABLED = (
        "유료 제작 호출이 꺼져 있습니다. 이번 라운드 예산과 제공자 사용량을 "
        "확인한 뒤 PAID_PRODUCTION_ENABLED=true로 설정하세요."
    )

    def __init__(self, mode: str = "image", parallel_clips: bool = False,
                 character_overlay_config: Optional[CharacterOverlayConfig] = None,
                 editor_options: Optional[Dict[str, Any]] = None,
                 max_veo_attempts: int = 1):
        """
        ProductionService 초기화

        Args:
            mode: 'hybrid', 'image' 또는 'video'
            parallel_clips: True면 이미지 모드에서 병렬 처리
            character_overlay_config: 캐릭터 오버레이 설정 (None이면 기본값 사용)
        """
        self.logger = get_logger(__name__)
        self.mode = mode
        self.parallel_clips = parallel_clips
        self.character_overlay_config = character_overlay_config
        self.editor_options = editor_options or {}
        if max_veo_attempts < 1:
            raise ValueError("max_veo_attempts는 1 이상이어야 합니다.")
        self.max_veo_attempts = max_veo_attempts
        self._progress = ProductionProgress()
        self._cancelled = False

        # 서비스 인스턴스 (지연 초기화)
        self._planner: Optional[ScriptPlanner] = None
        self._generator: Optional[VideoGenerator] = None
        self._editor: Optional[VideoEditor] = None
        self._uploader: Optional[YouTubeUploader] = None

        # 진행 콜백 (GUI 업데이트용)
        self._progress_callback: Optional[Callable[[ProductionProgress], None]] = None

    def set_progress_callback(self, callback: Callable[[ProductionProgress], None]):
        """진행 상황 콜백 설정"""
        self._progress_callback = callback

    def cancel(self):
        """파이프라인 취소 요청"""
        self._cancelled = True
        self.logger.warning("⚠️ Pipeline cancellation requested")

    def is_cancelled(self) -> bool:
        """취소 여부 확인"""
        return self._cancelled

    @property
    def progress(self) -> ProductionProgress:
        """현재 진행 상황 반환"""
        return self._progress

    def _notify_progress(self):
        """진행 콜백 호출"""
        if self._progress_callback:
            try:
                self._progress_callback(self._progress)
            except Exception as e:
                self.logger.warning(f"Progress callback error: {e}")

    def _update_progress(self, phase: ProductionPhase, percent: float, message: str):
        """진행 상황 업데이트"""
        self._progress.phase = phase
        self._progress.progress_percent = percent
        self._progress.message = message
        self.logger.info(f"[{phase.value}] {percent:.0f}% - {message}")
        self._notify_progress()

    def _init_scene_progresses(self, num_scenes: int):
        """씬별 진행 상황 초기화"""
        self._progress.total_scenes = num_scenes
        self._progress.completed_scenes = 0
        self._progress.current_scene = 0
        self._progress.scene_progresses = [
            SceneProgress(scene_number=i + 1) for i in range(num_scenes)
        ]

    def _update_scene_progress(self, scene_idx: int, status: str,
                                thumbnail_path: Optional[str] = None,
                                error: Optional[str] = None):
        """특정 씬의 진행 상황 업데이트"""
        if 0 <= scene_idx < len(self._progress.scene_progresses):
            sp = self._progress.scene_progresses[scene_idx]
            sp.status = status

            if status == "processing" and sp.start_time is None:
                sp.start_time = time.time()
            elif status in ["completed", "failed"]:
                sp.end_time = time.time()

            if thumbnail_path:
                sp.thumbnail_path = thumbnail_path
            if error:
                sp.error = error

            if status == "completed":
                self._progress.completed_scenes += 1

            self._progress.current_scene = scene_idx + 1
            self._notify_progress()

    def _start_phase(self, phase: ProductionPhase, num_scenes: int = 5):
        """단계 시작 - 시간 추적 및 예상 시간 계산"""
        self._progress.phase = phase
        self._progress.progress_percent = 0
        self._progress.phase_start_time = time.time()

        times = self.ESTIMATED_TIMES.get(self.mode, self.ESTIMATED_TIMES["image"])

        if phase == ProductionPhase.PLANNING:
            self._progress.estimated_total_seconds = times["planning"]
        elif phase == ProductionPhase.GENERATING:
            per_scene = times["generating_per_scene"]
            if self.parallel_clips and self.mode == "image":
                # 병렬 처리 시 약 1/3 시간
                self._progress.estimated_total_seconds = per_scene * num_scenes / 3
            else:
                self._progress.estimated_total_seconds = per_scene * num_scenes
        elif phase == ProductionPhase.EDITING:
            self._progress.estimated_total_seconds = times["editing_per_scene"] * num_scenes
        elif phase == ProductionPhase.UPLOADING:
            self._progress.estimated_total_seconds = times["uploading"]

        self._notify_progress()

    def _get_planner(self) -> ScriptPlanner:
        """ScriptPlanner 인스턴스 반환 (지연 초기화)"""
        if self._planner is None:
            self._planner = ScriptPlanner(generation_mode=self.mode)
        return self._planner

    def _get_generator(self) -> VideoGenerator:
        """VideoGenerator 인스턴스 반환 (지연 초기화)"""
        if self._generator is None:
            self._generator = VideoGenerator(
                mode=self.mode,
                character_overlay_config=self.character_overlay_config,
                max_veo_attempts=self.max_veo_attempts,
            )
        return self._generator

    def _get_editor(self) -> VideoEditor:
        """VideoEditor 인스턴스 반환 (지연 초기화)"""
        if self._editor is None:
            self._editor = VideoEditor(**self.editor_options)
        return self._editor

    def _get_uploader(self) -> YouTubeUploader:
        """YouTubeUploader 인스턴스 반환 (지연 초기화)"""
        if self._uploader is None:
            self._uploader = YouTubeUploader()
        return self._uploader

    def _failed_result(
        self, error: str, clips: Optional[List[str]] = None,
        video_path: Optional[str] = None,
    ) -> ProductionResult:
        if "BILLING_DISABLED" in error:
            error = "BILLING_DISABLED: Google Cloud 프로젝트의 결제 계정을 활성화하고 예산을 확인하세요."
        self._progress.error = error
        self._update_progress(ProductionPhase.FAILED, 0, f"오류: {error}")
        return ProductionResult(success=False, video_path=video_path, clips=clips or [], error=error)

    def _scene_cache_dir(self, scene, mode: str) -> Path:
        overlay = (self.character_overlay_config or CharacterOverlayConfig()).to_dict()
        for key in ("character_image", "character_video"):
            path = overlay.get(key)
            if path and Path(path).is_file():
                stat = Path(path).stat()
                overlay[f"{key}_version"] = (stat.st_size, stat.st_mtime_ns)
        identity_data = {
            "visual_description": scene.visual_description,
            "motion_instruction": scene.motion_instruction if mode == "video" else None,
            "mode": mode,
            "model": settings.veo_model_id if mode == "video" else settings.image_model_id,
            "format": "720p-silent" if mode == "video" else "1K-vertical",
            "duration": (settings.hybrid_veo_duration_seconds if self.mode == "hybrid"
                         else settings.veo_duration_seconds) if mode == "video" else None,
            "overlay": overlay,
        }
        if mode == "video":
            identity_data["prompt_version"] = VIDEO_PROMPT_VERSION
        identity = json.dumps(identity_data, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return settings.clips_dir / "scenes" / digest

    @staticmethod
    def _cached_clip(directory: Path, mode: str) -> Optional[str]:
        suffix = ".mp4" if mode == "video" else ".png"
        path = directory / f"clip{suffix}"
        return str(path) if ProductionService._valid_clip(path, mode) else None

    @staticmethod
    def _valid_clip(path: Path, mode: str) -> bool:
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return False
            if mode == "video":
                with VideoFileClip(str(path)) as clip:
                    return clip.duration > 0 and clip.get_frame(0) is not None
            with Image.open(path) as image:
                image.verify()
            return True
        except Exception:
            return False

    @staticmethod
    def _save_clip(directory: Path, mode: str, source: str) -> str:
        suffix = ".mp4" if mode == "video" else ".png"
        destination = directory / f"clip{suffix}"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{destination.stem}.{uuid.uuid4().hex}{suffix}"
        try:
            shutil.copyfile(source, temporary)
            if not ProductionService._valid_clip(temporary, mode):
                raise ValueError("생성 결과 파일을 읽을 수 없습니다.")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return str(destination)

    def _write_report(self, video_path: str, report: Dict[str, Any]) -> Optional[str]:
        path = Path(video_path).with_suffix(".production.json")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
            return str(path)
        except (OSError, TypeError, ValueError) as error:
            self.logger.warning(f"제작 기록 저장 실패: {error}")
            return None
        finally:
            temporary.unlink(missing_ok=True)

    def _record_upload(self, video_path: str, video_id: str, contains_synthetic_media: bool) -> Optional[str]:
        path = Path(video_path).with_suffix(".production.json")
        if not path.is_file():
            return None
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict) or report.get("video_path") != video_path:
                raise ValueError("영상 경로가 일치하지 않는 제작 기록")
        except (OSError, ValueError, TypeError) as error:
            self.logger.warning(f"제작 기록을 갱신할 수 없습니다: {error}")
            return None
        report["youtube_id"] = video_id
        report["contains_synthetic_media"] = contains_synthetic_media
        report["uploaded_at_utc"] = datetime.now(timezone.utc).isoformat()
        return self._write_report(video_path, report)

    async def generate_script(
        self,
        topic: Optional[str] = None,
        direct_url: Optional[str] = None
    ) -> Tuple[Optional[ShortsScript], Optional[ScriptGenerationContext]]:
        """
        스크립트 생성

        Args:
            topic: RSS에서 찾을 토픽 키워드 (선택)
            direct_url: 직접 URL 입력 (선택)

        Returns:
            (ShortsScript, ScriptGenerationContext) 튜플. 실패 시 (None, None)
        """
        try:
            self._progress.error = None
            self._start_phase(ProductionPhase.PLANNING)
            if not settings.paid_production_enabled:
                raise ValueError(self.PAID_WORK_DISABLED)
            self._update_progress(ProductionPhase.PLANNING, 10, "콘텐츠 소스 분석 중...")

            if self.is_cancelled():
                self._update_progress(ProductionPhase.FAILED, 0, "사용자에 의해 취소됨")
                return None, None

            if self.editor_options.get("bgm_volume", 0.2) > 0:
                if (not self.editor_options.get("bgm_track")
                        and self.editor_options.get("bgm_mood") in (None, "", "auto")):
                    if not BGMManager().has_documented_track():
                        raise ValueError("사용 권한이 기록된 BGM이 없습니다")
                else:
                    self._get_editor().preflight_music(None)

            planner = self._get_planner()

            self._update_progress(ProductionPhase.PLANNING, 30, "RSS 피드 스캔 중...")

            if self.is_cancelled():
                self._update_progress(ProductionPhase.FAILED, 0, "사용자에 의해 취소됨")
                return None, None

            self._update_progress(ProductionPhase.PLANNING, 50, "GPT-4o로 스크립트 생성 중...")

            script, context = await planner.plan_content(topic=topic, direct_url=direct_url)

            if self.is_cancelled():
                self._update_progress(ProductionPhase.FAILED, 0, "사용자에 의해 취소됨")
                return None, None

            if script:
                num_scenes = len(script.scenes) if script.scenes else 5
                self._init_scene_progresses(num_scenes)
                self._update_progress(ProductionPhase.PLANNING, 100,
                                       f"✓ 스크립트 완료: {script.title} ({num_scenes}개 씬)")
                return script, context
            else:
                self._update_progress(ProductionPhase.FAILED, 0, "스크립트 생성 실패")
                return None, None

        except Exception as e:
            self._progress.error = ("RESOURCE_EXHAUSTED: 공급자 제한으로 스크립트 생성 중단"
                                    if getattr(e, "status_code", None) == 429 else str(e))
            self.logger.error(f"스크립트 생성 오류: {self._progress.error}")
            self._update_progress(ProductionPhase.FAILED, 0, f"오류: {self._progress.error}")
            return None, None

    async def regenerate_script(
        self,
        context: ScriptGenerationContext,
        feedback: str
    ) -> Optional[ShortsScript]:
        """
        피드백을 반영하여 동일 주제로 스크립트 재생성.

        Args:
            context: 이전 생성 컨텍스트 (소스 데이터 재사용)
            feedback: 사용자 피드백 텍스트

        Returns:
            재생성된 ShortsScript 또는 실패 시 None
        """
        if context.attempt_count >= context.max_attempts:
            self.logger.warning("스크립트 재생성 최대 횟수에 도달했습니다")
            return None

        try:
            self._start_phase(ProductionPhase.PLANNING)
            if not settings.paid_production_enabled:
                raise ValueError(self.PAID_WORK_DISABLED)
            context.attempt_count += 1
            self._update_progress(ProductionPhase.PLANNING, 20, "피드백 반영 재생성 중...")

            planner = self._get_planner()
            final_script = await planner.regenerate(context.source_item, feedback=feedback)

            if final_script:
                num_scenes = len(final_script.scenes) if final_script.scenes else 5
                self._init_scene_progresses(num_scenes)
                self._update_progress(ProductionPhase.PLANNING, 100,
                                       f"✓ 재생성 완료 (시도 {context.attempt_count}/{context.max_attempts})")
                return final_script
            else:
                self._update_progress(ProductionPhase.FAILED, 0, "재생성 검증 실패")
                return None

        except Exception as e:
            self.logger.error(f"스크립트 재생성 오류: {e}")
            self._progress.error = str(e)
            self._update_progress(ProductionPhase.FAILED, 0, f"오류: {e}")
            return None

    async def produce_video(
        self,
        script: ShortsScript,
        manual_clip_paths: Optional[Dict[int, str]] = None,
        finish_phase: bool = True,
        prepared_audio_paths: Optional[List[str]] = None,
    ) -> ProductionResult:
        """
        스크립트에서 비디오 생성

        Args:
            script: 비디오를 생성할 ShortsScript
            manual_clip_paths: 수동 모드 시 {scene_number: file_path} 딕셔너리.
                               None이면 VEO API를 통한 자동 생성.
            prepared_audio_paths: 재사용할 씬별 내레이션 파일. 호출자가 보관/삭제합니다.

        Returns:
            ProductionResult 객체
        """
        num_scenes = len(script.scenes)
        clips = []
        editor = None
        audio_paths = None
        estimated_cost = 0.0
        generated_scenes = 0
        reused_scenes = 0

        try:
            # Phase 1: Visual Generation
            self._start_phase(ProductionPhase.GENERATING, num_scenes)
            self._init_scene_progresses(num_scenes)

            if manual_clip_paths is not None and not manual_clip_paths:
                return self._failed_result("씬 1의 클립 파일이 없습니다.", clips)
            manual_paths = manual_clip_paths or {}
            for scene_number, path in manual_paths.items():
                if not path or not os.path.isfile(path):
                    return self._failed_result(
                        f"씬 {scene_number}의 클립 파일이 없거나 접근할 수 없습니다.", clips,
                    )
            if self.is_cancelled():
                return self._failed_result("사용자에 의해 취소됨", clips)

            # Estimate only new API requests; manual clips and valid cache entries cost nothing.
            visual_modes = [scene_mode(self.mode, scene, i) for i, scene in enumerate(script.scenes)]
            cache_dirs = [
                self._scene_cache_dir(scene, mode) if isinstance(script, ShortsScript) else None
                for scene, mode in zip(script.scenes, visual_modes)
            ]
            cached_paths = []
            visual_request_count = 0
            for scene, mode, directory in zip(script.scenes, visual_modes, cache_dirs):
                cached = (
                    await asyncio.to_thread(self._cached_clip, directory, mode)
                    if directory and scene.scene_number not in manual_paths else None
                )
                cached_paths.append(cached)
                if scene.scene_number not in manual_paths and not cached:
                    model = settings.veo_model_id if mode == "video" else settings.image_model_id
                    duration = (settings.hybrid_veo_duration_seconds if self.mode == "hybrid"
                                else settings.veo_duration_seconds)
                    attempts = self.max_veo_attempts if mode == "video" else 1
                    estimated_cost += attempts * estimated_scene_cost(mode, model, duration)
                    visual_request_count += attempts
            if estimated_cost > settings.max_visual_cost_usd:
                return self._failed_result(
                    f"예상 비주얼 비용 ${estimated_cost:.3f}가 설정 상한 "
                    f"${settings.max_visual_cost_usd:.2f}를 초과합니다. "
                    "이미지 모드 또는 MAX_VISUAL_COST_USD 설정을 확인하세요.", clips,
                )
            if visual_request_count:
                check_google_budget(estimated_cost, visual_request_count)
            if not settings.paid_production_enabled and (
                estimated_cost > 0 or prepared_audio_paths is None
            ):
                return self._failed_result(self.PAID_WORK_DISABLED, clips)
            self.logger.info(f"Visual API estimate: ${estimated_cost:.3f} (cap ${settings.max_visual_cost_usd:.2f})")
            if isinstance(script, ShortsScript):
                self._update_progress(ProductionPhase.GENERATING, 0, "내레이션 길이 확인 중...")
                editor = self._get_editor()
                if hasattr(editor, "preflight_music"):
                    editor.preflight_music(script)
                if prepared_audio_paths is None:
                    audio_paths = await editor.prepare_narration(script)
                else:
                    if len(prepared_audio_paths) != num_scenes:
                        raise ValueError("씬 수와 내레이션 수가 일치하지 않습니다.")
                    await asyncio.to_thread(editor.validate_narration, prepared_audio_paths, script)
                    audio_paths = prepared_audio_paths
                if self.is_cancelled():
                    return self._failed_result("사용자에 의해 취소됨", clips)

            self._update_progress(ProductionPhase.GENERATING, 0,
                                   f"비주얼 준비 시작 (예상 API 비용 ${estimated_cost:.3f})")

            async def generate_one(index, scene):
                if self.is_cancelled():
                    raise RuntimeError("사용자에 의해 취소됨")
                self._update_scene_progress(index, "processing")
                cached = cached_paths[index]
                manual = manual_paths.get(scene.scene_number)
                self._update_progress(
                    ProductionPhase.GENERATING,
                    self._progress.completed_scenes / num_scenes * 100,
                    f"씬 {index + 1}/{num_scenes} "
                    f"{'수동 클립 사용' if manual else '저장된 결과 사용' if cached else '생성 중'}",
                )
                try:
                    if manual or cached:
                        path = manual or cached
                    else:
                        generator = self._get_generator()
                        path = await generator.generate_scene_clip(
                            scene, mode_override=visual_modes[index],
                        ) if self.mode == "hybrid" else await generator.generate_scene_clip(scene)
                        if cache_dirs[index]:
                            path = await asyncio.to_thread(
                                self._save_clip, cache_dirs[index], visual_modes[index], path,
                            )
                    self._update_scene_progress(index, "completed", thumbnail_path=path)
                    return path, bool(manual or cached)
                except Exception as scene_error:
                    self._update_scene_progress(index, "failed", error=str(scene_error))
                    raise

            if self.parallel_clips and self.mode == "image":
                semaphore = asyncio.Semaphore(getattr(self._generator, "max_concurrent", 3))

                async def bounded(index, scene):
                    async with semaphore:
                        path, reused = await generate_one(index, scene)
                        if not reused:
                            await asyncio.sleep(2)
                        return path, reused

                results = await asyncio.gather(
                    *(bounded(i, scene) for i, scene in enumerate(script.scenes)),
                    return_exceptions=True,
                )
                clips = [result[0] for result in results if isinstance(result, tuple)]
                errors = [error for error in results if isinstance(error, BaseException)]
                if errors:
                    raise errors[0]
                generated_scenes = sum(not result[1] for result in results)
                reused_scenes = num_scenes - generated_scenes
            else:
                for i, scene in enumerate(script.scenes):
                    path, reused = await generate_one(i, scene)
                    clips.append(path)
                    generated_scenes += not reused
                    reused_scenes += reused
                    if i < num_scenes - 1 and not reused and not self.is_cancelled():
                        await asyncio.sleep(2)

            if len(clips) != num_scenes or not clips:
                return self._failed_result("씬 수와 클립 수가 일치하지 않습니다.", clips)
            if any(not path or not os.path.isfile(path) for path in clips):
                return self._failed_result("생성된 클립 파일이 없습니다.", clips)

            self._update_progress(ProductionPhase.GENERATING, 100,
                                   f"✓ {len(clips)}개 클립 생성 완료")

            # Phase 2: Video Editing (씬별 상세 진행)
            if self.is_cancelled():
                return self._failed_result("사용자에 의해 취소됨", clips)

            self._start_phase(ProductionPhase.EDITING, num_scenes)
            self._update_progress(ProductionPhase.EDITING, 0, "비디오 편집 시작...")

            editor = editor or self._get_editor()

            if self.is_cancelled():
                return self._failed_result("사용자에 의해 취소됨", clips)
            video_path = await editor.compose_video(
                clips, script,
                progress_callback=lambda percent, message: self._update_progress(
                    ProductionPhase.EDITING, percent, message,
                ),
                is_cancelled=self.is_cancelled,
                **({"audio_paths": audio_paths} if audio_paths is not None else {}),
            )

            if self.is_cancelled():
                return self._failed_result("사용자에 의해 취소됨", clips, video_path)

            if not video_path or not os.path.exists(video_path):
                return self._failed_result("비디오 편집 실패", clips)

            quality_error = None
            try:
                await asyncio.to_thread(check_video_quality, video_path)
            except Exception as error:
                quality_error = str(error)

            script_key = hashlib.sha256(json.dumps({
                "source_url": getattr(script, "source_url", None),
                "title": getattr(script, "title", None),
                "narration": [getattr(scene, "script_text", None) for scene in script.scenes],
            }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
            music_path = getattr(editor, "selected_bgm_path", None)
            report_path = await asyncio.to_thread(self._write_report, video_path, {
                "schema_version": 1,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "video_path": video_path,
                "title": getattr(script, "title", None),
                "source_url": getattr(script, "source_url", None),
                "script_key": script_key,
                "production_mode": self.mode,
                "paired_comparison_eligible": not bool(manual_paths),
                "scenes": [
                    {
                        "number": scene.scene_number,
                        "visual_mode": mode,
                        "model_id": None if scene.scene_number in manual_paths else (
                            settings.veo_model_id if mode == "video" else settings.image_model_id
                        ),
                        "source": "manual" if scene.scene_number in manual_paths else (
                            "cache" if cached_paths[index] else "generated"
                        ),
                    }
                    for index, (scene, mode) in enumerate(zip(script.scenes, visual_modes))
                ],
                "estimated_visual_output_cost_usd": round(estimated_cost, 4),
                "music_direction": getattr(script, "music_direction", ""),
                "bgm_track": Path(music_path).name if music_path else None,
                "bgm_volume": (getattr(editor, "bgm_volume", self.editor_options.get("bgm_volume", 0.2))
                               if music_path else 0.0),
                "bgm_source_target_lufs": VideoEditor.BGM_TARGET_LUFS if music_path else None,
                "subtitle_style": getattr(editor, "subtitle_style", "soft"),
                "subtitle_color": getattr(editor, "subtitle_color", "#F6F8FA"),
                "text_overlays": getattr(editor, "text_overlays", {}),
                "generated_scenes": generated_scenes,
                "reused_or_manual_scenes": reused_scenes,
                "quality_passed": quality_error is None,
                "quality_error": quality_error,
                "youtube_id": None,
            })
            if quality_error:
                result = self._failed_result(f"영상 품질 검사 실패: {quality_error}", clips, video_path)
                result.report_path = report_path
                result.estimated_visual_cost_usd = round(estimated_cost, 4)
                result.generated_scenes = generated_scenes
                result.reused_scenes = reused_scenes
                return result

            self._update_progress(ProductionPhase.EDITING, 100, "✓ 편집 완료")
            if finish_phase:
                self._update_progress(ProductionPhase.COMPLETED, 100,
                                       f"🎬 프로덕션 완료: {video_path}")

            return ProductionResult(
                success=True,
                video_path=video_path,
                clips=clips,
                ready_for_upload=True,
                estimated_visual_cost_usd=round(estimated_cost, 4),
                generated_scenes=generated_scenes,
                reused_scenes=reused_scenes,
                report_path=report_path,
            )

        except Exception as e:
            self.logger.error(f"비디오 프로덕션 오류: {e}")
            return self._failed_result(str(e), clips)
        finally:
            if audio_paths and editor and prepared_audio_paths is None:
                editor.cleanup_temp_files()

    async def upload_to_youtube(
        self,
        video_path: str,
        metadata: Dict[str, Any]
    ) -> ProductionResult:
        """
        YouTube에 비디오 업로드

        Args:
            video_path: 업로드할 비디오 파일 경로
            metadata: 제목, 설명, 태그 등 메타데이터

        Returns:
            ProductionResult 객체
        """
        try:
            self._start_phase(ProductionPhase.UPLOADING)
            self._update_progress(ProductionPhase.UPLOADING, 0, "YouTube 업로드 시작...")

            if not os.path.exists(video_path):
                return self._failed_result("비디오 파일이 존재하지 않습니다")
            if self.is_cancelled():
                return self._failed_result("사용자에 의해 취소됨", video_path=video_path)

            await asyncio.to_thread(check_video_quality, video_path)

            uploader = self._get_uploader()
            video_id = await uploader.upload(video_path, metadata)

            if video_id:
                report_path = await asyncio.to_thread(
                    self._record_upload, video_path, video_id,
                    metadata.get("contains_synthetic_media", True),
                )
                self._update_progress(ProductionPhase.COMPLETED, 100, f"업로드 완료: {video_id}")
                return ProductionResult(
                    success=True,
                    video_path=video_path,
                    youtube_id=video_id,
                    ready_for_upload=True,
                    report_path=report_path,
                )
            else:
                return self._failed_result("업로드 실패", video_path=video_path)

        except Exception as e:
            self.logger.error(f"YouTube 업로드 오류: {e}")
            return self._failed_result(str(e), video_path=video_path)

    async def full_pipeline(
        self,
        topic: Optional[str] = None,
        direct_url: Optional[str] = None,
        auto_upload: bool = False,
        upload_metadata: Optional[Dict[str, Any]] = None
    ) -> ProductionResult:
        """
        전체 프로덕션 파이프라인 실행

        Args:
            topic: RSS에서 찾을 토픽 키워드 (선택)
            direct_url: 직접 URL 입력 (선택)
            auto_upload: True면 자동으로 YouTube 업로드
            upload_metadata: 업로드 메타데이터 (auto_upload가 True일 때 필요)

        Returns:
            ProductionResult 객체
        """
        # Step 1: Script Generation
        script, _context = await self.generate_script(topic=topic, direct_url=direct_url)
        if not script:
            if self.is_cancelled():
                reason = "사용자에 의해 취소됨"
            elif not settings.paid_production_enabled:
                reason = self.PAID_WORK_DISABLED
            elif self._progress.error and (
                "429" in self._progress.error or "RESOURCE_EXHAUSTED" in self._progress.error.upper()
            ):
                reason = "RESOURCE_EXHAUSTED: 공급자 제한으로 스크립트 생성 중단"
            else:
                reason = "스크립트 생성 실패"
            return self._failed_result(reason)

        # Step 2: Video Production
        result = await self.produce_video(script, finish_phase=not auto_upload)
        result.script = script
        if not result.success:
            return result

        # Step 3: Upload (optional)
        if auto_upload and result.video_path:
            metadata = upload_metadata or {
                "title": script.title,
                "description": script.description,
                "tags": script.tags,
                "contains_synthetic_media": True,
            }
            upload_result = await self.upload_to_youtube(result.video_path, metadata)
            result.success = upload_result.success
            result.youtube_id = upload_result.youtube_id
            result.error = upload_result.error

        return result

    def reset(self):
        """서비스 상태 초기화"""
        self._progress = ProductionProgress()
        self._planner = None
        self._generator = None
        self._editor = None
        self._uploader = None
        self._cancelled = False
        self.logger.info("ProductionService 상태 초기화됨")
