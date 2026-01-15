import os
import time
import asyncio
from typing import List
from google import genai
from google.genai import types
from shorts_maker.utils.logger import get_logger

class VideoGenerator:
    def __init__(self, mode: str = "image"):
        self.logger = get_logger(__name__)
        self.mode = mode
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.location = os.getenv("GCP_LOCATION", "us-central1")

        # Ensure service account is set for auth
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"

        try:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location
            )
            self.logger.info(f"✅ Google GenAI Client initialized (Mode: {mode})")
        except Exception as e:
            self.logger.error(f"❌ Failed to init GenAI Client: {e}")
            self.client = None

    async def generate_clips(self, script) -> List[str]:
        clips_paths = []
        for scene in script.scenes:
            if self.mode == "video":
                # [Two-Stage Generation Pipeline]
                self.logger.info(f"\n🎥 === Processing Scene {scene.scene_number} (Two-Stage) ===")
                
                # Stage 1: Generate Base Image (Character + Background)
                base_image_path = await self._generate_base_image(scene)
                
                # Stage 2: Animate with Veo
                video_path = await self._animate_with_veo(scene, base_image_path)
                clips_paths.append(video_path)
            else:
                # Image Mode (Legacy/Simple)
                path = await self._generate_image_imagen(scene)
                clips_paths.append(path)
            
            time.sleep(2) # Buffer
            
        return clips_paths

    async def _generate_base_image(self, scene) -> str:
        """
        Stage 1: Generates a high-quality static image merging the character and the news background using Imagen 3.
        Uses reference image (character_ref.png) + scene description to create a composed image.
        """
        output_path = f"temp/base_scene_{scene.scene_number}.png"
        ref_path = "assets/character_ref.png"

        self.logger.info(f"🎨 [Stage 1] Generating Base Image with Imagen 3 for Scene {scene.scene_number}...")

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
        Stage 2: Animates the provided base image using Veo.
        """
        output_path = f"temp/scene_{scene.scene_number}.mp4"
        
        if not self.client:
            return self._create_mock_video(output_path, scene.duration_seconds)

        model_id = os.getenv("VEO_MODEL_ID", "veo-2.0-generate-001")
        self.logger.info(f"🎬 [Stage 2] Animating with Veo ({model_id})...")
        
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
            f"In the small corner window (bottom-right, 15-20% of frame), a news presenter speaks to camera with subtle gestures. "
            f"The presenter's motion is minimal and natural - slight head movements, small hand gestures, facial expressions. "
            f"The presenter stays within their small corner frame throughout the video. "
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
        Generates a background-focused image with the character positioned small in the corner.
        The main focus is the news scene (background), with the presenter as a secondary element.
        """
        self.logger.info(f"    📸 Reference image: {ref_image_path}")

        try:
            # Background-focused composition prompt
            # The key is to make the SCENE the main subject, not the person
            composition_prompt = (
                f"A cinematic news broadcast scene showing: {scene.visual_description}. "
                f"In the bottom-right corner, there is a small news presenter/reporter (taking up only 15-20% of the frame). "
                f"The presenter is positioned in a circular or rounded-rectangle frame/window in the corner. "
                f"The main focus of the image is the background scene, not the person. "
                f"The background scene is large, detailed, and occupies 80-85% of the frame. "
                f"9:16 aspect ratio, photorealistic, professional news broadcast style, cinematic lighting, 4k quality."
            )

            self.logger.info(f"    🎨 Generating background-focused composition: {composition_prompt[:120]}...")

            # Use generate_images (not edit_image) to have full control over composition
            response = self.client.models.generate_images(
                model="imagen-3.0-generate-001",
                prompt=composition_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    include_rai_reason=True
                )
            )

            if response and response.generated_images:
                response.generated_images[0].image.save(output_path)
                self.logger.info(f"    ✅ Background-focused image generated successfully")
            else:
                raise Exception("No image returned from generate_images")

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"    ❌ Imagen generation failed: {error_msg}")

            # Fallback: Generate without person reference
            self.logger.info(f"    ⚙️ Falling back to background-only generation")
            try:
                fallback_prompt = (
                    f"A cinematic broadcast scene showing: {scene.visual_description}. "
                    f"Professional news broadcast style, 9:16 aspect ratio, photorealistic, 4k quality."
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
                    self.logger.warning(f"    ⚠️ Generated background-only (no presenter in frame)")
                    return
            except Exception as fallback_error:
                self.logger.error(f"    ❌ Fallback also failed: {fallback_error}")

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
