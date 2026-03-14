"""
ProductionService - 비디오 프로덕션 워크플로우를 추상화하는 서비스 레이어.

GUI와 비즈니스 로직을 분리하여 유지보수성과 테스트 용이성을 높입니다.
"""
import os
import time
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from shorts_maker.planner.script_planner import ScriptPlanner, ShortsScript
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.uploader.youtube_uploader import YouTubeUploader
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.character_overlay import CharacterOverlayConfig


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
        "video": {
            "planning": 30,
            "generating_per_scene": 120,  # Veo는 훨씬 오래 걸림
            "editing_per_scene": 25,
            "uploading": 60
        }
    }

    def __init__(self, mode: str = "image", parallel_clips: bool = False,
                 character_overlay_config: Optional[CharacterOverlayConfig] = None):
        """
        ProductionService 초기화

        Args:
            mode: 'image' (Imagen) 또는 'video' (Veo)
            parallel_clips: True면 이미지 모드에서 병렬 처리
            character_overlay_config: 캐릭터 오버레이 설정 (None이면 기본값 사용)
        """
        self.logger = get_logger(__name__)
        self.mode = mode
        self.parallel_clips = parallel_clips
        self.character_overlay_config = character_overlay_config
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
                character_overlay_config=self.character_overlay_config
            )
        return self._generator

    def _get_editor(self) -> VideoEditor:
        """VideoEditor 인스턴스 반환 (지연 초기화)"""
        if self._editor is None:
            self._editor = VideoEditor()
        return self._editor

    def _get_uploader(self) -> YouTubeUploader:
        """YouTubeUploader 인스턴스 반환 (지연 초기화)"""
        if self._uploader is None:
            self._uploader = YouTubeUploader()
        return self._uploader

    async def generate_script(
        self,
        topic: Optional[str] = None,
        direct_url: Optional[str] = None
    ) -> Optional[ShortsScript]:
        """
        스크립트 생성

        Args:
            topic: RSS에서 찾을 토픽 키워드 (선택)
            direct_url: 직접 URL 입력 (선택)

        Returns:
            생성된 ShortsScript 또는 실패 시 None
        """
        try:
            self._start_phase(ProductionPhase.PLANNING)
            self._update_progress(ProductionPhase.PLANNING, 10, "콘텐츠 소스 분석 중...")

            if self.is_cancelled():
                return None

            planner = self._get_planner()

            self._update_progress(ProductionPhase.PLANNING, 30, "RSS 피드 스캔 중...")

            if self.is_cancelled():
                return None

            self._update_progress(ProductionPhase.PLANNING, 50, "GPT-4o로 스크립트 생성 중...")

            script = await planner.plan_content(topic=topic, direct_url=direct_url)

            if self.is_cancelled():
                return None

            if script:
                # 씬 수로 초기화
                num_scenes = len(script.scenes) if script.scenes else 5
                self._init_scene_progresses(num_scenes)
                self._update_progress(ProductionPhase.PLANNING, 100,
                                       f"✓ 스크립트 완료: {script.title} ({num_scenes}개 씬)")
                return script
            else:
                self._update_progress(ProductionPhase.FAILED, 0, "스크립트 생성 실패")
                return None

        except Exception as e:
            self.logger.error(f"스크립트 생성 오류: {e}")
            self._progress.error = str(e)
            self._update_progress(ProductionPhase.FAILED, 0, f"오류: {e}")
            return None

    async def produce_video(
        self,
        script: ShortsScript,
        manual_clip_paths: Optional[Dict[int, str]] = None,
    ) -> ProductionResult:
        """
        스크립트에서 비디오 생성

        Args:
            script: 비디오를 생성할 ShortsScript
            manual_clip_paths: 수동 모드 시 {scene_number: file_path} 딕셔너리.
                               None이면 VEO API를 통한 자동 생성.

        Returns:
            ProductionResult 객체
        """
        num_scenes = len(script.scenes)
        clips = []

        try:
            # Phase 1: Visual Generation
            self._start_phase(ProductionPhase.GENERATING, num_scenes)
            generator = self._get_generator()

            if manual_clip_paths:
                # ── 수동 모드: VEO API 호출 없이 업로드된 파일 사용 ──
                self._update_progress(
                    ProductionPhase.GENERATING, 0,
                    f"수동 클립 로드 중 (0/{num_scenes})"
                )
                self._init_scene_progresses(num_scenes)

                for i, scene in enumerate(script.scenes):
                    self._update_scene_progress(i, "processing")
                    clip_path = manual_clip_paths.get(scene.scene_number)
                    if not clip_path:
                        return ProductionResult(
                            success=False,
                            error=f"씬 {scene.scene_number}의 클립 파일이 없습니다."
                        )
                    clips.append(clip_path)
                    self._update_scene_progress(i, "completed", thumbnail_path=clip_path)
                    self._update_progress(
                        ProductionPhase.GENERATING,
                        (i + 1) / num_scenes * 100,
                        f"씬 {i + 1}/{num_scenes} 클립 확인 완료"
                    )

            else:
                # ── 자동 모드: VEO/Imagen API 호출 ──
                self._update_progress(ProductionPhase.GENERATING, 0,
                                       f"비주얼 생성 시작 (0/{num_scenes})")

                for i, scene in enumerate(script.scenes):
                    if self.is_cancelled():
                        return ProductionResult(success=False, clips=clips, error="사용자에 의해 취소됨")

                    self._update_scene_progress(i, "processing")
                    progress_pct = (i / num_scenes) * 100
                    self._update_progress(
                        ProductionPhase.GENERATING,
                        progress_pct,
                        f"씬 {i + 1}/{num_scenes} 생성 중: {scene.visual_description[:30]}..."
                    )

                    try:
                        if self.mode == "video":
                            self._update_progress(
                                ProductionPhase.GENERATING,
                                progress_pct + (0.5 / num_scenes) * 100,
                                f"씬 {i + 1}/{num_scenes}: 배경 영상 생성 중..."
                            )
                            bg_video_path = await generator._generate_background_video(scene)

                            if generator.character_overlay:
                                self._update_progress(
                                    ProductionPhase.GENERATING,
                                    progress_pct + (0.8 / num_scenes) * 100,
                                    f"씬 {i + 1}/{num_scenes}: 캐릭터 합성 중..."
                                )
                                clip_path = await generator._composite_character_on_video(bg_video_path, scene)
                            else:
                                clip_path = bg_video_path
                        else:
                            clip_path = await generator._generate_image_imagen(scene)
                            if generator.character_overlay:
                                clip_path = generator.character_overlay.composite_on_image(
                                    clip_path,
                                    clip_path.replace(".png", "_final.png")
                                )

                        clips.append(clip_path)
                        self._update_scene_progress(i, "completed", thumbnail_path=clip_path)

                    except Exception as scene_error:
                        self.logger.error(f"씬 {i + 1} 생성 실패: {scene_error}")
                        self._update_scene_progress(i, "failed", error=str(scene_error))
                        mock_path = f"temp/error_scene_{i}.png"
                        generator._create_mock_image(mock_path)
                        clips.append(mock_path)

                    import asyncio
                    await asyncio.sleep(2)

            if not clips:
                return ProductionResult(success=False, error="클립 생성 실패")

            self._update_progress(ProductionPhase.GENERATING, 100,
                                   f"✓ {len(clips)}개 클립 생성 완료")

            # Phase 2: Video Editing (씬별 상세 진행)
            if self.is_cancelled():
                return ProductionResult(success=False, clips=clips, error="사용자에 의해 취소됨")

            self._start_phase(ProductionPhase.EDITING, num_scenes)
            self._update_progress(ProductionPhase.EDITING, 0, "비디오 편집 시작...")

            editor = self._get_editor()

            # 편집 단계별 진행률 (TTS, 자막, BGM, 렌더링)
            self._update_progress(ProductionPhase.EDITING, 20, "TTS 음성 생성 중...")

            if self.is_cancelled():
                return ProductionResult(success=False, clips=clips, error="사용자에 의해 취소됨")

            self._update_progress(ProductionPhase.EDITING, 40, "자막 오버레이 중...")

            if self.is_cancelled():
                return ProductionResult(success=False, clips=clips, error="사용자에 의해 취소됨")

            self._update_progress(ProductionPhase.EDITING, 60, "BGM 합성 중...")

            video_path = await editor.compose_video(clips, script)

            if self.is_cancelled():
                return ProductionResult(success=False, clips=clips, error="사용자에 의해 취소됨")

            self._update_progress(ProductionPhase.EDITING, 80, "최종 렌더링 중...")

            if not video_path or not os.path.exists(video_path):
                return ProductionResult(success=False, clips=clips, error="비디오 편집 실패")

            self._update_progress(ProductionPhase.EDITING, 100, "✓ 편집 완료")
            self._update_progress(ProductionPhase.COMPLETED, 100,
                                   f"🎬 프로덕션 완료: {video_path}")

            return ProductionResult(
                success=True,
                video_path=video_path,
                clips=clips
            )

        except Exception as e:
            self.logger.error(f"비디오 프로덕션 오류: {e}")
            self._progress.error = str(e)
            self._update_progress(ProductionPhase.FAILED, 0, f"오류: {e}")
            return ProductionResult(success=False, clips=clips, error=str(e))

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
            self._update_progress(ProductionPhase.UPLOADING, 0, "YouTube 업로드 시작...")

            if not os.path.exists(video_path):
                return ProductionResult(success=False, error="비디오 파일이 존재하지 않습니다")

            uploader = self._get_uploader()
            video_id = await uploader.upload(video_path, metadata)

            if video_id:
                self._update_progress(ProductionPhase.COMPLETED, 100, f"업로드 완료: {video_id}")
                return ProductionResult(
                    success=True,
                    video_path=video_path,
                    youtube_id=video_id
                )
            else:
                return ProductionResult(success=False, video_path=video_path, error="업로드 실패")

        except Exception as e:
            self.logger.error(f"YouTube 업로드 오류: {e}")
            self._progress.error = str(e)
            self._update_progress(ProductionPhase.FAILED, 0, f"오류: {e}")
            return ProductionResult(success=False, video_path=video_path, error=str(e))

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
        script = await self.generate_script(topic=topic, direct_url=direct_url)
        if not script:
            return ProductionResult(success=False, error="스크립트 생성 실패")

        # Step 2: Video Production
        result = await self.produce_video(script)
        if not result.success:
            return result

        # Step 3: Upload (optional)
        if auto_upload and result.video_path:
            metadata = upload_metadata or {
                "title": script.title,
                "description": script.description,
                "tags": script.tags
            }
            upload_result = await self.upload_to_youtube(result.video_path, metadata)
            return upload_result

        return result

    def reset(self):
        """서비스 상태 초기화"""
        self._progress = ProductionProgress()
        self._planner = None
        self._generator = None
        self._editor = None
        self._uploader = None
        self.logger.info("ProductionService 상태 초기화됨")
