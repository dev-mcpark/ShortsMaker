import os
import time
import asyncio
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
from PIL import Image

from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.services.visual_cost import estimated_scene_cost, scene_mode
from shorts_maker.services.google_budget import (
    check_google_budget, mark_google_result, reserve_google_output,
)

VIDEO_PROMPT_VERSION = 2


class VideoGenerator:
    def __init__(
        self,
        mode: str = "image",
        max_concurrent: int = 3,
        character_overlay_config: Optional[CharacterOverlayConfig] = None,
        max_veo_attempts: int = 1,
    ):
        """
        VideoGenerator 초기화

        Args:
            mode: 'image', 'video' 또는 'hybrid'
            max_concurrent: 병렬 처리 시 최대 동시 요청 수 (기본값: 3)
            character_overlay_config: 캐릭터 오버레이 설정 (None이면 기본값 사용)
        """
        self.logger = get_logger(__name__)
        self.mode = mode
        self.max_concurrent = max_concurrent
        if max_veo_attempts < 1:
            raise ValueError("max_veo_attempts는 1 이상이어야 합니다.")
        self.max_veo_attempts = max_veo_attempts
        self.project_id = settings.gcp_project_id
        self.location = settings.gcp_location
        self.image_client = None

        # 캐릭터 오버레이 설정
        self.character_overlay_config = character_overlay_config or CharacterOverlayConfig()
        self.character_overlay = (
            self.character_overlay_config.create_overlay()
            if self.character_overlay_config.enabled
            else None
        )

        # settings에서 이미 GOOGLE_APPLICATION_CREDENTIALS 환경변수 설정됨

        try:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            self.logger.info(f"✅ Google GenAI Client initialized (Mode: {mode})")
            if self.character_overlay:
                self.logger.info(
                    f"✅ Character Overlay enabled (position: {self.character_overlay_config.position})"
                )
        except Exception as e:
            self.logger.error(f"❌ Failed to init GenAI Client: {e}")
            self.client = None

    # ── Public API ────────────────────────────────────────────────────────

    async def generate_clips(self, script, parallel: bool = False) -> List[str]:
        """스크립트의 모든 씬에 대해 클립 생성.

        Args:
            script: ShortsScript 객체
            parallel: True면 이미지 모드에서 병렬 처리 (비디오 모드는 순차 처리)
        """
        reserve = sum(
            self._scene_output_reserve(scene_mode(self.mode, scene, index))
            for index, scene in enumerate(script.scenes)
        )
        self._check_visual_cap(reserve)
        request_count = sum(
            self.max_veo_attempts if scene_mode(self.mode, scene, index) == "video" else 1
            for index, scene in enumerate(script.scenes)
        )
        if reserve:
            check_google_budget(reserve, request_count)
        if parallel and self.mode == "image":
            return await self._generate_clips_parallel(script)
        return await self._generate_clips_sequential(script)

    def _scene_output_reserve(self, mode: str) -> float:
        model = settings.veo_model_id if mode == "video" else settings.image_model_id
        duration = (settings.hybrid_veo_duration_seconds if self.mode == "hybrid"
                    else settings.veo_duration_seconds)
        attempts = self.max_veo_attempts if mode == "video" else 1
        return attempts * estimated_scene_cost(mode, model, duration)

    @staticmethod
    def _check_visual_cap(reserve: float) -> None:
        if reserve > settings.max_visual_cost_usd:
            raise ValueError(
                f"예상 비주얼 비용 ${reserve:.3f}가 설정 상한 "
                f"${settings.max_visual_cost_usd:.2f}를 초과합니다."
            )

    async def generate_scene_clip(self, scene, mode_override: Optional[str] = None,
                                  *, source_url: str | None = None,
                                  first_frame_path: str | None = None,
                                  expected_first_frame_sha256: str | None = None,
                                  request_budget_usd: float | None = None) -> str:
        """현재 생성 모드에 맞는 단일 씬 클립을 만듭니다."""
        mode = mode_override or self.mode
        reserve = self._scene_output_reserve(mode)
        self._check_visual_cap(reserve)
        check_google_budget(reserve, self.max_veo_attempts if mode == "video" else 1)
        if mode == "video":
            if not first_frame_path:
                raise ValueError("FIRST_FRAME_REVIEW_REQUIRED: Veo 첫 프레임 검토가 필요합니다.")
            cap = reserve if request_budget_usd is None else request_budget_usd
            path = (await self._generate_background_video(
                scene, settings.hybrid_veo_duration_seconds, source_url,
                first_frame_path, expected_first_frame_sha256, cap,
            ) if self.mode == "hybrid" else await self._generate_background_video(
                scene, source_url=source_url, first_frame_path=first_frame_path,
                expected_first_frame_sha256=expected_first_frame_sha256,
                request_budget_usd=cap,
            ))
            if self.character_overlay:
                return await self._composite_character_on_video(path, scene)
            return path
        if mode != "image":
            raise ValueError(f"지원하지 않는 생성 모드: {mode}")

        path = await self._generate_image_gemini(scene, source_url)
        if self.character_overlay:
            return await asyncio.to_thread(
                self.character_overlay.composite_on_image,
                path, path.replace(".png", "_final.png")
            )
        return path

    # ── Clip Generation Orchestration ────────────────────────────────────

    async def _generate_clips_sequential(self, script) -> List[str]:
        """순차적 클립 생성."""
        clips_paths = []
        for index, scene in enumerate(script.scenes):
            mode = scene_mode(self.mode, scene, index)
            kwargs = {'source_url': getattr(script, 'source_url', None)}
            if mode == 'video':
                from shorts_maker.services.visual_review import verified_first_frame
                kwargs['first_frame_path'], kwargs['expected_first_frame_sha256'] = verified_first_frame(
                    script, scene,
                )
            path = await self.generate_scene_clip(
                scene, mode_override=mode, **kwargs,
            ) if self.mode == "hybrid" else await self.generate_scene_clip(
                scene, **kwargs,
            )
            clips_paths.append(path)
            if index < len(script.scenes) - 1:
                await asyncio.sleep(settings.scene_buffer_seconds)
        return clips_paths

    async def _generate_clips_parallel(self, script) -> List[str]:
        """병렬 클립 생성 (이미지 모드 전용)."""
        self.logger.info(f"⚡ 병렬 처리 모드 (최대 {self.max_concurrent}개 동시)")

        semaphore = asyncio.Semaphore(self.max_concurrent)
        scenes = list(script.scenes)

        async def generate_with_semaphore(scene):
            async with semaphore:
                self.logger.info(f"🎨 Processing Scene {scene.scene_number}...")
                path = await self.generate_scene_clip(scene, source_url=getattr(script, "source_url", None))
                await asyncio.sleep(2)
                return path

        results = await asyncio.gather(
            *[generate_with_semaphore(scene) for scene in scenes],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, BaseException):
                self.logger.error(f"병렬 처리 중 오류: {result}")
                raise result

        self.logger.info(f"✅ 병렬 처리 완료: {len(results)}개 클립 생성")
        return results

    # ── Current Pipeline: Background Video + Character Composite ─────────

    async def _generate_background_video(self, scene, duration_seconds: Optional[int] = None,
                                         source_url: str | None = None,
                                         first_frame_path: str | None = None,
                                         expected_first_frame_sha256: str | None = None,
                                         request_budget_usd: float | None = None) -> str:
        """Stage 1: 배경 영상만 생성 (캐릭터 없이)."""
        output_path = str(settings.temp_dir / f"bg_scene_{scene.scene_number}_{uuid.uuid4().hex}.mp4")

        if not self.client:
            raise RuntimeError("GenAI client is unavailable")

        model_id = settings.veo_model_id
        self.logger.info(
            f"🎬 Generating background video with Veo ({model_id})...\n"
            f"    📍 Stage 1: Generating background video (no character)"
        )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._run_veo_background_only, model_id, scene, output_path, duration_seconds,
                source_url, first_frame_path, expected_first_frame_sha256, request_budget_usd,
            )
            if os.path.exists(output_path):
                self.logger.info(f"    ✅ Background video generated: {output_path}")
                return output_path
            raise RuntimeError("Veo returned no video file")
        except Exception as e:
            self.logger.error(f"    ❌ Veo Background Generation Error: {e}")
            raise

    async def _composite_character_on_video(self, bg_video_path: str, scene) -> str:
        """Stage 2: 배경 영상에 캐릭터 합성."""
        output_path = str(settings.temp_dir / f"scene_{scene.scene_number}_{uuid.uuid4().hex}.mp4")

        if not self.character_overlay:
            self.logger.warning("Character overlay not configured, returning background video")
            return bg_video_path

        try:
            loop = asyncio.get_running_loop()
            char_video_path = self.character_overlay_config.character_video
            result_path = await loop.run_in_executor(
                None,
                self.character_overlay.composite_on_video,
                bg_video_path,
                output_path,
                char_video_path,
            )
            if os.path.exists(result_path):
                self.logger.info(f"    ✅ Character composited: {result_path}")
                return result_path
        except Exception as e:
            self.logger.error(f"    ❌ Character compositing error: {e}")
            raise

    # ── Veo Helpers ───────────────────────────────────────────────────────

    def _retry_veo_call(
        self,
        model_id: str,
        initial_prompt: str,
        output_path: str,
        fallback_prompt: str,
        max_attempts: int = 1,
        duration_seconds: Optional[int] = None,
        scene_number: Optional[int] = None,
        first_frame_path: Optional[str] = None,
        request_budget_usd: Optional[float] = None,
        source_url: str | None = None,
        expected_first_frame_sha256: str | None = None,
    ) -> None:
        """Veo API 호출을 재시도 로직과 함께 실행.

        max_attempts가 2 이상이면 서버 오류를 대기 후 재시도하고,
        안전 위반 시 fallback_prompt로 전환합니다.
        """
        require_paid_production_enabled()
        if (not isinstance(request_budget_usd, (int, float))
                or isinstance(request_budget_usd, bool)
                or not math.isfinite(request_budget_usd) or request_budget_usd < 0):
            raise ValueError("Veo 요청 예산 상한을 명시해야 합니다.")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError("Veo 시도 횟수는 1 이상이어야 합니다.")
        requested_seconds = settings.veo_duration_seconds if duration_seconds is None else duration_seconds
        if requested_seconds not in {4, 6, 8} or isinstance(requested_seconds, bool):
            raise ValueError("Veo 생성 길이는 4, 6, 8초 중 하나여야 합니다.")
        estimated_output = estimated_scene_cost("video", model_id, requested_seconds)
        reserve = estimated_output * max_attempts
        self._check_visual_cap(reserve)
        if reserve > request_budget_usd:
            raise ValueError(
                f"Veo 예약액 ${reserve:.3f}가 요청 상한 ${request_budget_usd:.2f}를 초과합니다."
            )

        first_frame = None
        image_sha256 = None
        if first_frame_path is not None:
            frame_path = Path(first_frame_path)
            if frame_path.stat().st_size > 20_000_000:
                raise ValueError("Veo 첫 프레임 이미지는 20 MB 이하여야 합니다.")
            image_bytes = frame_path.read_bytes()
            with Image.open(BytesIO(image_bytes)) as image:
                width, height = image.size
                mime_type = Image.MIME.get(image.format)
                image.verify()
            if mime_type not in {"image/png", "image/jpeg"} or abs(width / height - 9 / 16) > 0.02:
                raise ValueError("Veo 첫 프레임은 세로 9:16 PNG 또는 JPEG여야 합니다.")
            first_frame = types.Image(image_bytes=image_bytes, mime_type=mime_type)
            image_sha256 = hashlib.sha256(image_bytes).hexdigest()
            if (expected_first_frame_sha256 is not None
                    and image_sha256 != expected_first_frame_sha256):
                raise ValueError("승인된 Veo 첫 프레임이 변경됐습니다.")

        current_prompt = initial_prompt

        for attempt in range(max_attempts):
            require_paid_production_enabled()
            audit_dir = settings.output_dir / "evaluation" / "visual_attempts"
            audit_dir.mkdir(parents=True, exist_ok=True)
            audit_path = audit_dir / f"{uuid.uuid4().hex}.json"
            record = {
                "schema_version": 1,
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "model": model_id,
                "scene_number": scene_number,
                "duration_seconds": requested_seconds,
                "resolution": "720p",
                "generate_audio": False,
                "number_of_videos": 1,
                "estimated_output_usd": round(estimated_output, 4),
                "request_budget_usd": request_budget_usd,
                "input_type": "image_first_frame" if first_frame is not None else "text",
                "input_image_sha256": image_sha256,
                "source_url": source_url,
                "actual_billed_usd": None,
                "status": "submitted_or_pending",
            }
            audit_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            operation = None
            budget_request_id = None
            try:
                budget_request_id = reserve_google_output(
                    "video", model_id, requested_seconds, source_url=source_url,
                )
                record["budget_request_id"] = budget_request_id
                self.logger.info(f"    Generating (Attempt {attempt + 1}/{max_attempts})...")

                request = {
                    "model": model_id,
                    "prompt": current_prompt,
                    "config": {
                        "aspect_ratio": "9:16",
                        "duration_seconds": requested_seconds,
                        "resolution": "720p",
                        "generate_audio": False,
                        "number_of_videos": 1,
                    },
                }
                if first_frame is not None:
                    request["image"] = first_frame
                operation = self.client.models.generate_videos(**request)
                for _ in range(90):  # 최대 15분 대기
                    if operation.done:
                        break
                    time.sleep(10)
                    operation = self.client.operations.get(operation)
                if not operation.done:
                    raise TimeoutError("Veo generation did not finish within 15 minutes")

                self.logger.info("    Done!")

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    if not os.path.isfile(output_path):
                        raise RuntimeError("Veo returned no video file")
                    record["status"] = "saved"
                    return

                error_info = getattr(operation, "error", "Unknown Error")
                raise Exception(f"No video generated. Error: {error_info}")

            except TimeoutError as e:
                record["status"] = "timed_out_unknown"
                raise TimeoutError("VEO_RESULT_UNVERIFIED: Veo 작업의 완료 여부를 확인할 수 없습니다") from e
            except Exception as e:
                record.update(
                    status="budget_blocked" if "GOOGLE_BUDGET_EXCEEDED" in str(e)
                    else "failed_or_unknown",
                    error_type=type(e).__name__,
                )
                if record["status"] == "budget_blocked":
                    raise
                provider_error = getattr(operation, "error", None)
                provider_code = (provider_error.get("code") if isinstance(provider_error, dict)
                                 else getattr(provider_error, "code", None))
                if provider_code is not None:
                    record["provider_error_code"] = str(provider_code)
                err_str = str(e).lower()
                if str(provider_code) == "8" or getattr(e, "status_code", None) == 429 or any(
                    term in err_str for term in ("429", "resource_exhausted", "resource exhausted")
                ):
                    record["status"] = "provider_limited"
                    raise RuntimeError("RESOURCE_EXHAUSTED: 공급자 제한으로 Veo 생성 중단") from e

                if any(term in err_str for term in (
                    "internal error", "500", "502", "503", "504", "try again later",
                )) and attempt < max_attempts - 1:
                    self.logger.warning("    ⚠️ Server error, retrying in 30s...")
                    time.sleep(30)
                    continue

                if ("violate" in err_str or "code': 3" in err_str) and current_prompt != fallback_prompt and attempt < max_attempts - 1:
                    self.logger.warning("    ⚠️ Safety violation, simplifying prompt...")
                    current_prompt = fallback_prompt
                    continue

                if operation is not None:
                    raise RuntimeError("VEO_RESULT_UNVERIFIED: 제출된 작업에서 영상 파일을 확인할 수 없습니다") from e

                self.logger.error(f"    ❌ Error: {e}")
                raise
            finally:
                operation_name = getattr(operation, "name", None)
                if isinstance(operation_name, str):
                    record["operation_id"] = operation_name.rsplit("/", 1)[-1]
                record["finished_utc"] = datetime.now(timezone.utc).isoformat()
                audit_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                if not mark_google_result(budget_request_id, record["status"]):
                    self.logger.error("Google 예산 장부 상태 갱신 실패: 예약액은 유지됩니다.")

    def _run_veo_background_only(
        self, model_id: str, scene, output_path: str, duration_seconds: Optional[int] = None,
        source_url: str | None = None,
        first_frame_path: str | None = None,
        expected_first_frame_sha256: str | None = None,
        request_budget_usd: float | None = None,
    ) -> None:
        """Veo로 배경 영상만 생성 (캐릭터 언급 없음)."""
        self.logger.info(
            f"--> Generating background-only video for Scene {scene.scene_number}"
        )

        original_prompt = scene.visual_description.strip().rstrip(".")
        motion_desc = (getattr(scene, "motion_instruction", "") or "").strip().rstrip(".")
        motion_clause = motion_desc + "." if motion_desc else "Steady camera."

        initial_prompt = (
            f"One continuous vertical shot. {original_prompt}. "
            f"Motion: {motion_clause} "
            "Plain unlettered surfaces and an uncluttered lower third for captions added in editing. "
            "Silent background footage."
        )
        fallback_prompt = (
            f"One simple vertical shot. {original_prompt}. "
            f"Motion: {motion_clause} "
            "Plain unlettered surfaces, uncluttered lower third."
        )

        self._retry_veo_call(
            model_id, initial_prompt, output_path, fallback_prompt,
            max_attempts=self.max_veo_attempts,
            duration_seconds=duration_seconds,
            scene_number=scene.scene_number,
            request_budget_usd=settings.max_visual_cost_usd if request_budget_usd is None else request_budget_usd,
            source_url=source_url,
            first_frame_path=first_frame_path,
            expected_first_frame_sha256=expected_first_frame_sha256,
        )

    # ── Image Helper ──────────────────────────────────────────────────────

    async def _generate_image_gemini(self, scene, source_url: str | None = None) -> str:
        """Generate a vertical still with the supported Gemini image model."""
        output_path = str(settings.temp_dir / f"scene_{scene.scene_number}_{uuid.uuid4().hex}.png")

        self.logger.info(f"🎨 Requesting Gemini image for scene {scene.scene_number}...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._run_image_generation,
                settings.image_model_id,
                scene,
                output_path,
                source_url,
            )
            if not os.path.isfile(output_path):
                raise RuntimeError("Gemini returned no image file")
            return output_path
        except Exception as e:
            self.logger.error(f"❌ Gemini Image Generation Error: {e}")
            raise

    def _run_image_generation(self, model_id: str, scene, output_path: str,
                              source_url: str | None = None) -> None:
        require_paid_production_enabled()
        budget_request_id = reserve_google_output("image", model_id, source_url=source_url)
        if self.image_client is None:
            self.image_client = genai.Client(
                vertexai=True, project=self.project_id, location="global",
            )
        status = "unknown"
        try:
            response = self.image_client.models.generate_content(
                model=model_id,
                contents=scene.visual_description,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="9:16", image_size="1K"),
                ),
            )
            for candidate in response.candidates or []:
                for part in (candidate.content.parts or []) if candidate.content else []:
                    image = part.as_image()
                    if image:
                        image.save(output_path)
                        status = "saved"
                        return
            raise RuntimeError("No image returned")
        finally:
            if not mark_google_result(budget_request_id, status):
                self.logger.error("Google 예산 장부 상태 갱신 실패: 예약액은 유지됩니다.")
