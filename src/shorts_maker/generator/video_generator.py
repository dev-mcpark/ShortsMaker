import os
import time
import asyncio
from typing import List, Optional
from google import genai
from google.genai import types
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.utils.character_overlay import CharacterOverlay, CharacterOverlayConfig


class VideoGenerator:
    def __init__(self, mode: str = "image", max_concurrent: int = 3, character_overlay_config: Optional[CharacterOverlayConfig] = None):
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
        self.character_overlay = self.character_overlay_config.create_overlay() if self.character_overlay_config.enabled else None

        # settings에서 이미 GOOGLE_APPLICATION_CREDENTIALS 환경변수 설정됨

        try:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location
            )
            self.logger.info(f"✅ Google GenAI Client initialized (Mode: {mode})")
            if self.character_overlay:
                self.logger.info(f"✅ Character Overlay enabled (position: {self.character_overlay_config.position})")
        except Exception as e:
            self.logger.error(f"❌ Failed to init GenAI Client: {e}")
            self.client = None

    async def generate_clips(self, script, parallel: bool = False) -> List[str]:
        """
        스크립트의 모든 씬에 대해 클립 생성

        Args:
            script: ShortsScript 객체
            parallel: True면 이미지 모드에서 병렬 처리 (비디오 모드는 순차 처리)

        Returns:
            생성된 클립 파일 경로 목록
        """
        # 이미지 모드에서만 병렬 처리 지원 (비디오 모드는 API 제한으로 순차)
        if parallel and self.mode == "image":
            return await self._generate_clips_parallel(script)
        else:
            return await self._generate_clips_sequential(script)

    async def _generate_clips_sequential(self, script) -> List[str]:
        """순차적 클립 생성 (개선된 3단계 파이프라인)"""
        clips_paths = []
        for scene in script.scenes:
            if self.mode == "video":
                # [Three-Stage Generation Pipeline - Character Consistency Guaranteed]
                self.logger.info(f"\n🎥 === Processing Scene {scene.scene_number} (Three-Stage Pipeline) ===")

                # Stage 1: Generate Background-Only Video with Veo
                self.logger.info(f"    📍 Stage 1: Generating background video (no character)")
                bg_video_path = await self._generate_background_video(scene)

                # Stage 2: Composite Character Overlay
                if self.character_overlay:
                    self.logger.info(f"    📍 Stage 2: Compositing character overlay")
                    final_video_path = await self._composite_character_on_video(bg_video_path, scene)
                    clips_paths.append(final_video_path)
                else:
                    self.logger.info(f"    ⚠️ Character overlay disabled, using background only")
                    clips_paths.append(bg_video_path)
            else:
                # Image Mode (Legacy/Simple)
                path = await self._generate_image_imagen(scene)

                # 이미지 모드에서도 캐릭터 합성 적용
                if self.character_overlay:
                    path = self.character_overlay.composite_on_image(path, path.replace(".png", "_final.png"))

                clips_paths.append(path)

            await asyncio.sleep(10)  # Non-blocking buffer

        return clips_paths

    async def _generate_clips_parallel(self, script) -> List[str]:
        """병렬 클립 생성 (이미지 모드 전용)"""
        self.logger.info(f"⚡ 병렬 처리 모드 (최대 {self.max_concurrent}개 동시)")

        semaphore = asyncio.Semaphore(self.max_concurrent)
        scenes = list(script.scenes)

        async def generate_with_semaphore(scene):
            async with semaphore:
                self.logger.info(f"🎨 Processing Scene {scene.scene_number}...")
                path = await self._generate_image_imagen(scene)
                await asyncio.sleep(2)  # 짧은 버퍼
                return (scene.scene_number, path)

        # 모든 씬 병렬 처리
        results = await asyncio.gather(
            *[generate_with_semaphore(scene) for scene in scenes],
            return_exceptions=True
        )

        # 결과 정렬 (씬 순서 유지)
        clips_paths = []
        for result in sorted(results, key=lambda x: x[0] if isinstance(x, tuple) else float('inf')):
            if isinstance(result, tuple):
                clips_paths.append(result[1])
            else:
                # 예외 발생 시 mock 이미지 생성
                self.logger.error(f"병렬 처리 중 오류: {result}")
                mock_path = f"temp/error_scene.png"
                self._create_mock_image(mock_path)
                clips_paths.append(mock_path)

        self.logger.info(f"✅ 병렬 처리 완료: {len(clips_paths)}개 클립 생성")
        return clips_paths

    async def _generate_background_video(self, scene) -> str:
        """
        Stage 1 (New): 배경 영상만 생성 (캐릭터 없이)

        캐릭터를 AI로 생성하지 않고, 순수하게 배경/뉴스 컨텐츠만 생성합니다.
        이후 Stage 2에서 준비된 캐릭터 이미지/영상을 합성합니다.
        """
        output_path = f"temp/bg_scene_{scene.scene_number}.mp4"

        if not self.client:
            return self._create_mock_video(output_path, scene.duration_seconds)

        model_id = settings.veo_model_id
        self.logger.info(f"🎬 Generating background video with Veo ({model_id})...")

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._run_veo_background_only,
                model_id,
                scene,
                output_path
            )

            if os.path.exists(output_path):
                self.logger.info(f"    ✅ Background video generated: {output_path}")
                return output_path
        except Exception as e:
            self.logger.error(f"    ❌ Veo Background Generation Error: {e}")

        return self._create_mock_video(output_path, scene.duration_seconds)

    async def _composite_character_on_video(self, bg_video_path: str, scene) -> str:
        """
        Stage 2 (New): 배경 영상에 캐릭터 합성

        CharacterOverlay를 사용하여 준비된 캐릭터를 배경 영상 위에 합성합니다.
        이 방식으로 100% 캐릭터 일관성을 보장합니다.
        """
        output_path = f"temp/scene_{scene.scene_number}.mp4"

        if not self.character_overlay:
            self.logger.warning("Character overlay not configured, returning background video")
            return bg_video_path

        try:
            loop = asyncio.get_running_loop()

            # 캐릭터 영상이 있으면 사용, 없으면 이미지 사용
            char_video_path = self.character_overlay_config.character_video

            result_path = await loop.run_in_executor(
                None,
                self.character_overlay.composite_on_video,
                bg_video_path,
                output_path,
                char_video_path
            )

            if os.path.exists(result_path):
                self.logger.info(f"    ✅ Character composited: {result_path}")
                return result_path

        except Exception as e:
            self.logger.error(f"    ❌ Character compositing error: {e}")

        return bg_video_path

    def _run_veo_background_only(self, model_id, scene, output_path):
        """
        Veo로 배경 영상만 생성 (캐릭터 언급 없음)

        캐릭터 관련 프롬프트를 완전히 제거하여:
        1. Safety 필터 회피
        2. 더 풍부한 배경 애니메이션 생성
        3. 후처리로 캐릭터 합성 예정
        """
        self.logger.info(f"--> Generating background-only video for Scene {scene.scene_number}")

        original_prompt = scene.visual_description
        motion_desc = getattr(scene, 'motion_instruction', "Smooth cinematic movement")

        # 배경 전용 프롬프트 (캐릭터 언급 완전 제거)
        background_prompt = (
            f"Cinematic news broadcast background scene: {original_prompt}. "
            f"Motion style: {motion_desc}. "
            f"Full-screen background footage with dynamic camera movement. "
            f"Atmospheric lighting, detailed environment, immersive depth. "
            f"Professional broadcast quality, 4K resolution, smooth motion. "
            f"This is a B-roll background shot - no people, no presenter, just the scene itself. "
            f"Focus on environmental storytelling and visual atmosphere."
        )

        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                self.logger.info(f"    Generating background (Attempt {attempt+1}/{max_attempts})...")

                operation = self.client.models.generate_videos(
                    model=model_id,
                    prompt=background_prompt,
                    config={"aspect_ratio": "9:16"}
                )

                while not operation.done:
                    time.sleep(10)
                    operation = self.client.operations.get(operation)

                self.logger.info("    Done!")

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    return
                else:
                    error_info = getattr(operation, 'error', 'Unknown Error')
                    raise Exception(f"No video generated. Error: {error_info}")

            except Exception as e:
                err_str = str(e).lower()

                if "internal error" in err_str or "500" in err_str:
                    self.logger.warning(f"    ⚠️ Server error, retrying in 30s...")
                    time.sleep(30)
                    continue

                if "violate" in err_str:
                    self.logger.warning(f"    ⚠️ Safety violation, simplifying prompt...")
                    # 더 단순한 프롬프트로 재시도
                    background_prompt = (
                        f"A cinematic establishing shot: {original_prompt}. "
                        f"Beautiful atmospheric scene, professional quality, no people."
                    )
                    continue

                self.logger.error(f"    ❌ Error: {e}")
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(10)

    # ============================================================
    # Legacy Methods (하위 호환성 유지)
    # ============================================================

    async def _generate_base_image(self, scene) -> str:
        """
        [Legacy] Stage 1: Generates a high-quality static image merging the character and the news background.
        NOTE: 새 파이프라인에서는 _generate_background_video + _composite_character_on_video 사용 권장
        """
        output_path = f"temp/base_scene_{scene.scene_number}.png"
        ref_path = str(settings.assets_dir / "character_ref.png")

        self.logger.info(f"🎨 [Legacy Stage 1] Generating Base Image with Imagen 3 for Scene {scene.scene_number}...")

        if not self.client:
            self.logger.warning(f"    ⚠️ No GenAI client, creating mock image")
            self._create_mock_image(output_path)
            return output_path

        # Check if reference image exists
        if not os.path.exists(ref_path):
            self.logger.warning(f"    ⚠️ Reference image not found at {ref_path}, creating mock")
            self._create_mock_image(output_path)
            return output_path

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._run_imagen_with_reference,
                scene,
                ref_path,
                output_path
            )

            if os.path.exists(output_path):
                self.logger.info(f"    ✅ Base image generated: {output_path}")
                return output_path
        except Exception as e:
            self.logger.error(f"    ❌ Imagen Error: {e}")

        # Fallback to mock if generation fails
        self._create_mock_image(output_path)
        return output_path

    async def _animate_with_veo(self, scene, base_image_path: str) -> str:
        """
        [Legacy] Stage 2: Animates the provided base image using Veo.
        NOTE: 새 파이프라인에서는 _generate_background_video + _composite_character_on_video 사용 권장
        """
        output_path = f"temp/scene_{scene.scene_number}.mp4"

        if not self.client:
            return self._create_mock_video(output_path, scene.duration_seconds)

        model_id = settings.veo_model_id
        self.logger.info(f"🎬 [Legacy Stage 2] Animating with Veo ({model_id})...")

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_veo_generation_logic, model_id, scene, output_path, base_image_path)

            if os.path.exists(output_path):
                self.logger.info(f"    ✅ Video generation complete: {output_path}")
                return output_path
        except Exception as e:
            self.logger.error(f"    ❌ Veo Animation Error: {e}")

        return self._create_mock_video(output_path, scene.duration_seconds)

    def _run_veo_generation_logic(self, model_id, scene, output_path, image_input_path):
        self.logger.info(f"--> Entered _run_veo_generation_logic for Scene {scene.scene_number}")

        has_ref = os.path.exists(image_input_path)
        self.logger.info(f"    Input Image: {image_input_path}, Exists? {has_ref}")

        original_prompt = scene.visual_description
        motion_desc = getattr(scene, 'motion_instruction', "The character speaks and moves naturally.")

        # Veo prompt optimized for BACKGROUND-FOCUSED news broadcast
        # The main animation is the background scene, presenter is secondary in corner
        current_prompt = (
            f"Animate this news broadcast scene where the MAIN FOCUS is the background: {original_prompt}. "
            f"Motion in the scene: {motion_desc}. "
            f"The large background scene is animated with cinematic camera movement and atmospheric effects. "
            f"In the small corner window (bottom-right, 15-20% of frame), the character speaks to camera with subtle gestures. "
            f"the character's motion is minimal and natural - slight head movements, small hand gestures, facial expressions. "
            f"the character stays within their small corner frame throughout the video. "
            f"The background scene animation is the PRIMARY focus - detailed, dynamic, and cinematic. "
            f"Professional news broadcast quality, 4k resolution, smooth motion, broadcast-style composition."
        )
        image_input = None
        
        if has_ref:
            try:
                from google.genai import types
                with open(image_input_path, "rb") as f:
                    image_bytes = f.read()
                if image_bytes:
                    image_input = types.Image(image_bytes=image_bytes, mime_type='image/png')
                    self.logger.info("    ✅ Image object loaded for animation.")
            except Exception as e:
                self.logger.warning(f"    ⚠️ Failed to load image input: {e}")

        # Retry Logic for Safety and Internal Errors
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                self.logger.info(f"    Generating (Attempt {attempt+1}/{max_attempts})...")
                
                kwargs = {
                    "model": model_id,
                    "prompt": current_prompt,
                    "config": {"aspect_ratio": "9:16"}
                }
                
                if image_input:
                    kwargs['image'] = image_input

                operation = self.client.models.generate_videos(**kwargs)
                
                while not operation.done:
                    time.sleep(10)
                    operation = self.client.operations.get(operation)
                    self.logger.debug(".", extra={"end": ""})
                self.logger.info(" Done!")

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    return
                else:
                    error_info = getattr(operation, 'error', 'Unknown Error')
                    raise Exception(f"No video. Error: {error_info}")

            except Exception as e:
                err_str = str(e).lower()
                
                # Case 1: Internal Error (Transient)
                if "internal error" in err_str or "500" in err_str or "try again later" in err_str:
                    self.logger.warning(f"    ⚠️ Server Error. Waiting 30s before retry...")
                    time.sleep(30)
                    continue 
                
                # Case 2: Safety Violation
                if "violate" in err_str or "code': 3" in err_str:
                    self.logger.warning(f"    ⚠️ Safety Violation.")
                    if attempt < max_attempts - 1:
                        self.logger.info("    ♻️ Retrying safely (background scene only, no person)...")
                        # Remove person/character references to avoid safety filters
                        # Focus 100% on the background scene animation
                        current_prompt = (
                            f"Cinematic news broadcast background scene: {original_prompt}. "
                            f"Motion: {motion_desc}. "
                            f"Dynamic camera movement, atmospheric lighting, detailed environment, 4k quality, professional broadcast style."
                        )
                        image_input = None
                        continue

                self.logger.error(f"    ❌ Error: {e}")
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(10)

    async def _generate_image_imagen(self, scene) -> str:
        # Legacy/Single stage image generator
        output_path = f"temp/scene_{scene.scene_number}.png"
        
        if not self.client:
            return self._create_mock_image(output_path)

        self.logger.info(f"🎨 Requesting Imagen 3 for scene {scene.scene_number}...")
        try:
            model_id = "imagen-3.0-generate-001"
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_imagen_generation, model_id, scene, output_path)
            return output_path
        except Exception as e:
            self.logger.error(f"❌ Imagen Generation Error: {e}")
        return self._create_mock_image(output_path)

    def _run_imagen_generation(self, model_id, scene, output_path):
        try:
            response = self.client.models.generate_images(
                model=model_id,
                prompt=scene.visual_description,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    safety_filter_level="block_some"
                )
            )
            if response and response.generated_images:
                response.generated_images[0].image.save(output_path)
            else:
                raise Exception("No image returned")
        except Exception as e:
            raise e

    def _run_imagen_with_reference(self, scene, ref_image_path, output_path):
        """
        Stage 1: Compose character + background using edit_image with reference.

        This preserves character consistency by:
        1. Loading character_ref.png as RawReferenceImage
        2. Using MASK_MODE_BACKGROUND to replace only the background
        3. Keeping the character consistent across all scenes
        """
        self.logger.info(f"    📸 Reference image: {ref_image_path}")

        try:
            from google.genai.types import RawReferenceImage, MaskReferenceImage

            # Background-focused prompt (80-85% background, 15-20% presenter in corner)
            composition_prompt = (
                f"A cinematic news broadcast background scene: {scene.visual_description}. "
                f"The main subject is the large, detailed background (80-85% of frame). "
                f"In the bottom-right corner, position the presenter in a small rounded window (15-20% of frame). "
                f"Professional news broadcast style, 9:16 aspect ratio, photorealistic, cinematic lighting, 4k quality."
            )

            self.logger.info(f"    🎨 Composing with character reference: {composition_prompt[:100]}...")

            # 1. Load character reference image
            with open(ref_image_path, "rb") as f:
                image_bytes = f.read()

            raw_ref_image = RawReferenceImage(
                reference_id=1,
                reference_image=types.Image(image_bytes=image_bytes, mime_type='image/png'),
            )

            # 2. Mask the background (keep character, replace background)
            mask_ref_image = MaskReferenceImage(
                reference_id=2,
                config=types.MaskReferenceConfig(
                    mask_mode="MASK_MODE_BACKGROUND",  # Only replace background
                    mask_dilation=0.0,
                ),
            )

            # 3. Edit image: keep character, replace background
            response = self.client.models.edit_image(
                model="imagen-3.0-capability-001",  # Must use capability model for reference images
                prompt=composition_prompt,
                reference_images=[raw_ref_image, mask_ref_image],
                config=types.EditImageConfig(
                    edit_mode="EDIT_MODE_INPAINT_INSERTION",
                    number_of_images=1,
                    include_rai_reason=True,
                    output_mime_type='image/png',
                )
            )

            if response and response.generated_images:
                response.generated_images[0].image.save(output_path)
                self.logger.info(f"    ✅ Character + background composed successfully")
            else:
                raise Exception("No image returned from edit_image")

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"    ❌ Character composition failed: {error_msg}")

            # Fallback 1: Try without reference image (text-only generation)
            self.logger.info(f"    ⚙️ Fallback: Generating with text prompt only (no character reference)")
            try:
                fallback_prompt = (
                    f"A cinematic news broadcast scene: {scene.visual_description}. "
                    f"In the bottom-right corner, a small news presenter in a rounded window (15-20% of frame). "
                    f"Professional broadcast style, 9:16 aspect ratio, photorealistic, 4k quality."
                )

                response = self.client.models.generate_images(
                    model="imagen-3.0-generate-001",
                    prompt=fallback_prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="9:16"
                    )
                )

                if response and response.generated_images:
                    response.generated_images[0].image.save(output_path)
                    self.logger.warning(f"    ⚠️ Generated without character reference (consistency may vary)")
                    return
            except Exception as fallback_error:
                self.logger.error(f"    ❌ Fallback generation also failed: {fallback_error}")

            raise e

    def _create_mock_video(self, path, duration):
        self.logger.warning(f"⚠️ Creating mock video for: {path}")
        from moviepy import ColorClip

        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        clip = ColorClip(size=(1080, 1920), color=(0, 0, 50), duration=duration)
        clip.write_videofile(path, fps=24, codec="libx264", logger=None)
        return path

    def _create_mock_image(self, path):
        self.logger.warning(f"⚠️ Creating mock image for: {path}")
        from PIL import Image, ImageDraw

        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        img = Image.new('RGB', (1080, 1920), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10,10), "Placeholder", fill=(255,255,255))
        img.save(path)
        return path
