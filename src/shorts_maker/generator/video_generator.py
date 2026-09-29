import os
import time
import asyncio
from typing import List, Optional

from google import genai
from google.genai import types

from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.utils.character_overlay import CharacterOverlayConfig


class VideoGenerator:
    def __init__(
        self,
        mode: str = "image",
        max_concurrent: int = 3,
        character_overlay_config: Optional[CharacterOverlayConfig] = None,
    ):
        """
        VideoGenerator 초기화

        Args:
            mode: 'image' (Imagen) 또는 'video' (Veo)
            max_concurrent: 병렬 처리 시 최대 동시 요청 수 (기본값: 3)
            character_overlay_config: 캐릭터 오버레이 설정 (None이면 기본값 사용)
        """
        self.logger = get_logger(__name__)
        self.mode = mode
        self.max_concurrent = max_concurrent
        self.project_id = settings.gcp_project_id
        self.location = settings.gcp_location

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
        if parallel and self.mode == "image":
            return await self._generate_clips_parallel(script)
        return await self._generate_clips_sequential(script)

    async def generate_scene_clip(self, scene) -> str:
        """현재 생성 모드에 맞는 단일 씬 클립을 만듭니다."""
        if self.mode == "video":
            path = await self._generate_background_video(scene)
            if self.character_overlay:
                return await self._composite_character_on_video(path, scene)
            return path

        path = await self._generate_image_imagen(scene)
        if self.character_overlay:
            return self.character_overlay.composite_on_image(
                path, path.replace(".png", "_final.png")
            )
        return path

    # ── Clip Generation Orchestration ────────────────────────────────────

    async def _generate_clips_sequential(self, script) -> List[str]:
        """순차적 클립 생성."""
        clips_paths = []
        for scene in script.scenes:
            path = await self.generate_scene_clip(scene)
            clips_paths.append(path)
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
                path = await self.generate_scene_clip(scene)
                await asyncio.sleep(2)
                return path

        results = await asyncio.gather(
            *[generate_with_semaphore(scene) for scene in scenes],
            return_exceptions=True,
        )

        clips_paths = []
        for scene, result in zip(scenes, results):
            if isinstance(result, BaseException):
                self.logger.error(f"병렬 처리 중 오류: {result}")
                mock_path = f"temp/error_scene_{scene.scene_number}.png"
                self._create_mock_image(mock_path)
                clips_paths.append(mock_path)
            else:
                clips_paths.append(result)

        self.logger.info(f"✅ 병렬 처리 완료: {len(clips_paths)}개 클립 생성")
        return clips_paths

    # ── Current Pipeline: Background Video + Character Composite ─────────

    async def _generate_background_video(self, scene) -> str:
        """Stage 1: 배경 영상만 생성 (캐릭터 없이)."""
        output_path = f"temp/bg_scene_{scene.scene_number}.mp4"

        if not self.client:
            return self._create_mock_video(output_path, scene.duration_seconds)

        model_id = settings.veo_model_id
        self.logger.info(
            f"🎬 Generating background video with Veo ({model_id})...\n"
            f"    📍 Stage 1: Generating background video (no character)"
        )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._run_veo_background_only, model_id, scene, output_path
            )
            if os.path.exists(output_path):
                self.logger.info(f"    ✅ Background video generated: {output_path}")
                return output_path
        except Exception as e:
            self.logger.error(f"    ❌ Veo Background Generation Error: {e}")

        return self._create_mock_video(output_path, scene.duration_seconds)

    async def _composite_character_on_video(self, bg_video_path: str, scene) -> str:
        """Stage 2: 배경 영상에 캐릭터 합성."""
        output_path = f"temp/scene_{scene.scene_number}.mp4"

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

        return bg_video_path

    # ── Veo Helpers ───────────────────────────────────────────────────────

    def _retry_veo_call(
        self,
        model_id: str,
        initial_prompt: str,
        output_path: str,
        fallback_prompt: str,
        max_attempts: int = 4,
    ) -> None:
        """Veo API 호출을 재시도 로직과 함께 실행.

        서버 에러(500/internal) 시 30초 대기 후 재시도,
        안전 위반(violate) 시 fallback_prompt로 전환 후 재시도합니다.
        """
        current_prompt = initial_prompt

        for attempt in range(max_attempts):
            try:
                self.logger.info(f"    Generating (Attempt {attempt + 1}/{max_attempts})...")

                operation = self.client.models.generate_videos(
                    model=model_id,
                    prompt=current_prompt,
                    config={"aspect_ratio": "9:16"},
                )

                while not operation.done:
                    time.sleep(10)
                    operation = self.client.operations.get(operation)

                self.logger.info("    Done!")

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    return

                error_info = getattr(operation, "error", "Unknown Error")
                raise Exception(f"No video generated. Error: {error_info}")

            except Exception as e:
                err_str = str(e).lower()

                if ("internal error" in err_str or "500" in err_str or "try again later" in err_str) and attempt < max_attempts - 1:
                    self.logger.warning("    ⚠️ Server error, retrying in 30s...")
                    time.sleep(30)
                    continue

                if "violate" in err_str or "code': 3" in err_str:
                    self.logger.warning("    ⚠️ Safety violation, simplifying prompt...")
                    if attempt < max_attempts - 1:
                        current_prompt = fallback_prompt
                        continue

                self.logger.error(f"    ❌ Error: {e}")
                if attempt == max_attempts - 1:
                    raise
                time.sleep(10)

    def _run_veo_background_only(self, model_id: str, scene, output_path: str) -> None:
        """Veo로 배경 영상만 생성 (캐릭터 언급 없음)."""
        self.logger.info(
            f"--> Generating background-only video for Scene {scene.scene_number}"
        )

        original_prompt = scene.visual_description
        motion_desc = getattr(scene, "motion_instruction", "Smooth cinematic movement")

        initial_prompt = (
            f"Cinematic news broadcast background scene: {original_prompt}. "
            f"Motion style: {motion_desc}. "
            f"Full-screen background footage with dynamic camera movement. "
            f"Atmospheric lighting, detailed environment, immersive depth. "
            f"Professional broadcast quality, 4K resolution, smooth motion. "
            f"This is a B-roll background shot - no people, no presenter, just the scene itself. "
            f"Focus on environmental storytelling and visual atmosphere."
        )
        fallback_prompt = (
            f"A cinematic establishing shot: {original_prompt}. "
            f"Beautiful atmospheric scene, professional quality, no people."
        )

        self._retry_veo_call(model_id, initial_prompt, output_path, fallback_prompt)

    # ── Imagen Helper ─────────────────────────────────────────────────────

    async def _generate_image_imagen(self, scene) -> str:
        """Imagen으로 씬 이미지를 생성합니다."""
        output_path = f"temp/scene_{scene.scene_number}.png"

        if not self.client:
            return self._create_mock_image(output_path)

        self.logger.info(f"🎨 Requesting Imagen for scene {scene.scene_number}...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._run_imagen_generation,
                settings.imagen_model_id,
                scene,
                output_path,
            )
            return output_path
        except Exception as e:
            self.logger.error(f"❌ Imagen Generation Error: {e}")
        return self._create_mock_image(output_path)

    def _run_imagen_generation(self, model_id: str, scene, output_path: str) -> None:
        response = self.client.models.generate_images(
            model=model_id,
            prompt=scene.visual_description,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16",
                safety_filter_level="block_some",
            ),
        )
        if response and response.generated_images:
            response.generated_images[0].image.save(output_path)
        else:
            raise Exception("No image returned")

    # ── Fallback / Mock Helpers ───────────────────────────────────────────

    def create_fallback_image(self, path: str) -> str:
        """오류 발생 시 대체 이미지를 생성합니다 (public API)."""
        return self._create_mock_image(path)

    def _create_mock_video(self, path: str, duration: float) -> str:
        self.logger.warning(f"⚠️ Creating mock video for: {path}")
        from moviepy import ColorClip

        os.makedirs(os.path.dirname(path), exist_ok=True)
        clip = ColorClip(size=(1080, 1920), color=(0, 0, 50), duration=duration)
        clip.write_videofile(path, fps=24, codec="libx264", logger=None)
        return path

    def _create_mock_image(self, path: str) -> str:
        self.logger.warning(f"⚠️ Creating mock image for: {path}")
        from PIL import Image, ImageDraw

        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = Image.new("RGB", (1080, 1920), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "Placeholder", fill=(255, 255, 255))
        img.save(path)
        return path
