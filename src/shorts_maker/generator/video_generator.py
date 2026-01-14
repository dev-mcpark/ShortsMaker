import os
import time
import asyncio
from typing import List
from google import genai
from google.genai import types

class VideoGenerator:
    def __init__(self, mode: str = "image"):
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
            print(f"✅ Google GenAI Client initialized (Mode: {mode})")
        except Exception as e:
            print(f"❌ Failed to init GenAI Client: {e}")
            self.client = None

    async def generate_clips(self, script) -> List[str]:
        clips_paths = []
        for scene in script.scenes:
            if self.mode == "video":
                # [Two-Stage Generation Pipeline]
                print(f"\n🎥 === Processing Scene {scene.scene_number} (Two-Stage) ===")
                
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

        print(f"🎨 [Stage 1] Generating Base Image with Imagen 3 for Scene {scene.scene_number}...", flush=True)

        if not self.client:
            print(f"    ⚠️ No GenAI client, creating mock image", flush=True)
            self._create_mock_image(output_path)
            return output_path

        # Check if reference image exists
        if not os.path.exists(ref_path):
            print(f"    ⚠️ Reference image not found at {ref_path}, creating mock", flush=True)
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
                print(f"    ✅ Base image generated: {output_path}", flush=True)
                return output_path
        except Exception as e:
            print(f"    ❌ Imagen Error: {e}", flush=True)

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
        print(f"🎬 [Stage 2] Animating with Veo ({model_id})...", flush=True)
        
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_veo_generation_logic, model_id, scene, output_path, base_image_path)
            
            if os.path.exists(output_path):
                print(f"    ✅ Video generation complete: {output_path}", flush=True)
                return output_path
        except Exception as e:
            print(f"    ❌ Veo Animation Error: {e}", flush=True)
            
        return self._create_mock_video(output_path, scene.duration_seconds)

    def _run_veo_generation_logic(self, model_id, scene, output_path, image_input_path):
        print(f"--> Entered _run_veo_generation_logic for Scene {scene.scene_number}", flush=True)
        
        has_ref = os.path.exists(image_input_path)
        print(f"    Input Image: {image_input_path}, Exists? {has_ref}", flush=True)

        original_prompt = scene.visual_description
        motion_desc = getattr(scene, 'motion_instruction', "The character speaks and moves naturally.")
        
        current_prompt = (
            f"Animate this scene naturally: {motion_desc}. "
            f"The character from the reference image is the subject. "
            f"The background remains consistent with the scene: {original_prompt}. "
            f"4k resolution, high quality motion."
        )
        image_input = None
        
        if has_ref:
            try:
                from google.genai import types
                with open(image_input_path, "rb") as f:
                    image_bytes = f.read()
                if image_bytes:
                    image_input = types.Image(image_bytes=image_bytes, mime_type='image/png')
                    print("    ✅ Image object loaded for animation.", flush=True)
            except Exception as e:
                print(f"    ⚠️ Failed to load image input: {e}", flush=True)

        # Retry Logic for Safety and Internal Errors
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                print(f"    Generating (Attempt {attempt+1}/{max_attempts})...", flush=True)
                
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
                    print(".", end="", flush=True)
                print(" Done!", flush=True)

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
                    print(f"    ⚠️ Server Error. Waiting 30s before retry...", flush=True)
                    time.sleep(30)
                    continue 
                
                # Case 2: Safety Violation
                if "violate" in err_str or "code': 3" in err_str:
                    print(f"    ⚠️ Safety Violation.", flush=True)
                    if attempt < max_attempts - 1:
                        print("    ♻️ Retrying safely (stripping image & subject)...", flush=True)
                        current_prompt = f"Atmospheric cinematic background showing: {original_prompt}. 4k."
                        image_input = None
                        continue
                
                print(f"    ❌ Error: {e}", flush=True)
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(10)

    async def _generate_image_imagen(self, scene) -> str:
        # Legacy/Single stage image generator
        output_path = f"temp/scene_{scene.scene_number}.png"
        
        if not self.client:
            return self._create_mock_image(output_path)

        print(f"🎨 Requesting Imagen 3 for scene {scene.scene_number}...", flush=True)
        try:
            model_id = "imagen-3.0-generate-001"
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_imagen_generation, model_id, scene, output_path)
            return output_path
        except Exception as e:
            print(f"❌ Imagen Generation Error: {e}", flush=True)
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
        Generates a composed image using Imagen 3 edit_image API with character preservation.
        Uses the character from ref_image_path and changes the background to match scene.visual_description.
        This is achieved through inpainting with background masking.
        """
        print(f"    📸 Loading reference image: {ref_image_path}", flush=True)

        try:
            # Load reference image
            with open(ref_image_path, "rb") as f:
                ref_image_bytes = f.read()

            ref_image = types.Image(image_bytes=ref_image_bytes, mime_type='image/png')

            # Background prompt - what we want the new background to be
            background_prompt = (
                f"{scene.visual_description}. "
                f"9:16 aspect ratio, photorealistic, high quality, cinematic lighting, detailed background."
            )

            print(f"    🎨 Editing background with prompt: {background_prompt[:100]}...", flush=True)

            # Use edit_image API with background masking
            # This preserves the character (foreground) and replaces the background
            raw_ref = types.RawReferenceImage(
                reference_id=1,
                reference_image=ref_image
            )

            # Mask the background - this tells Imagen to change only the background
            mask_ref = types.MaskReferenceImage(
                reference_id=2,
                config=types.MaskReferenceConfig(
                    mask_mode=types.MaskReferenceMode.MASK_MODE_BACKGROUND,  # Only edit background
                    mask_dilation=0
                )
            )

            response = self.client.models.edit_image(
                model='imagen-3.0-capability-001',  # Edit/capability model
                prompt=background_prompt,
                reference_images=[raw_ref, mask_ref],
                config=types.EditImageConfig(
                    edit_mode=types.EditMode.EDIT_MODE_INPAINT_INSERTION,  # Insert new background
                    number_of_images=1,
                    include_rai_reason=True
                )
            )

            if response and response.generated_images:
                response.generated_images[0].image.save(output_path)
                print(f"    ✅ Composed image with preserved character saved successfully", flush=True)
            else:
                raise Exception("No composed image returned from edit_image")

        except Exception as e:
            error_msg = str(e)
            print(f"    ❌ Imagen edit_image failed: {error_msg}", flush=True)

            # Fallback: Generate from scratch without character reference
            print(f"    ⚙️ Falling back to generate_images without character reference", flush=True)
            try:
                fallback_prompt = (
                    f"A person in the following scene: {scene.visual_description}. "
                    f"9:16 aspect ratio, photorealistic, high quality, detailed background."
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
                    print(f"    ⚠️ Generated without character reference (character will not be consistent)", flush=True)
                    return
            except Exception as fallback_error:
                print(f"    ❌ Fallback also failed: {fallback_error}", flush=True)

            raise e

    def _create_mock_video(self, path, duration):
        print(f"⚠️ Creating mock video for: {path}", flush=True)
        from moviepy import ColorClip

        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        clip = ColorClip(size=(1080, 1920), color=(0, 0, 50), duration=duration)
        clip.write_videofile(path, fps=24, codec="libx264", logger=None)
        return path

    def _create_mock_image(self, path):
        print(f"⚠️ Creating mock image for: {path}", flush=True)
        from PIL import Image, ImageDraw

        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        img = Image.new('RGB', (1080, 1920), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10,10), "Placeholder", fill=(255,255,255))
        img.save(path)
        return path
