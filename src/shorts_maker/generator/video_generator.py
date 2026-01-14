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
                path = await self._generate_video_veo(scene)
            else:
                path = await self._generate_image_imagen(scene)
            
            clips_paths.append(path)
            time.sleep(5) # Rate limit buffer
            
        return clips_paths

    async def _generate_video_veo(self, scene) -> str:
        output_path = f"temp/scene_{scene.scene_number}.mp4"
        
        # [DEBUG] Force regeneration even if file exists
        # if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        #     print(f"Video for scene {scene.scene_number} already exists.")
        #     return output_path

        if not self.client:
            return self._create_mock_video(output_path, scene.duration_seconds)

        # Veo Model ID: Try the stable one first
        model_id = os.getenv("VEO_MODEL_ID", "veo-2.0-generate-001")
        print(f"🎥 Requesting Veo ({model_id}) for scene {scene.scene_number}...")
        
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_veo_generation, model_id, scene, output_path)
            
            if os.path.exists(output_path):
                print(f"✅ Veo generation complete: {output_path}")
                return output_path
                
        except Exception as e:
            print(f"❌ Veo Generation Error: {e}")
            
        return self._create_mock_video(output_path, scene.duration_seconds)

    def _get_or_upload_character_file(self, path: str) -> str:
        # [FIX] Use Absolute Path for Cache
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_file_dir, "../../../"))
        
        cache_dir = os.path.join(project_root, ".cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "character_file_id.txt")
        
        # 1. Try to load from cache
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cached_id = f.read().strip()
                
                # Verify validity
                print(f"🔍 Checking cached file ID: {cached_id}...")
                file_obj = self.client.files.get(name=cached_id)
                if file_obj.state.name == "ACTIVE":
                    print("✅ Cached file is valid and ACTIVE.")
                    return cached_id
                else:
                    print(f"⚠️ Cached file is not ACTIVE ({file_obj.state.name}). Re-uploading...")
            except Exception as e:
                print(f"⚠️ Cache check failed ({e}). Re-uploading...")

        # 2. Upload new file
        print(f"📤 Uploading reference image: {path}...")
        uploaded_file = self.client.files.upload(path=path)
        
        print(f"⏳ Waiting for file {uploaded_file.name} to be processed...")
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = self.client.files.get(name=uploaded_file.name)
            
        if uploaded_file.state.name != "ACTIVE":
             raise Exception(f"File upload failed with state: {uploaded_file.state.name}")
        
        # 3. Save to cache
        with open(cache_file, "w") as f:
            f.write(uploaded_file.name)
            
        print(f"✅ File uploaded and cached: {uploaded_file.name}")
        return uploaded_file.name

    def _run_veo_generation(self, model_id, scene, output_path):
        print(f"--> Entered _run_veo_generation for Scene {scene.scene_number}", flush=True)
        
        # [FIX] Use Absolute Path derived from this file's location
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_file_dir, "../../../"))
        
        ref_path = os.path.join(project_root, "assets", "character_ref.png")
        has_ref = os.path.exists(ref_path)
        print(f"    Target Ref Path: {ref_path}", flush=True)
        print(f"    Exists? {has_ref}", flush=True)

        # Prepare Prompt & Image
        current_prompt = scene.visual_description
        image_input = None
        
        # [NEW] Simple Image-to-Video Logic using types.Image
        if has_ref:
            try:
                from google.genai import types
                print(f"    Loading reference image from: {ref_path}", flush=True)
                
                # [FIX] Manually read bytes to ensure data is loaded
                with open(ref_path, "rb") as f:
                    image_bytes = f.read()
                
                if image_bytes:
                    print(f"    Read {len(image_bytes)} bytes from file.", flush=True)
                    # Explicitly create Image object with bytes and mime_type
                    image_input = types.Image(image_bytes=image_bytes, mime_type='image/png')
                    
                    # [FIX] Refined Prompt for Layout-based Generation
                    # Since the user provides a pre-composed 9:16 image, we instruct Veo to animate it.
                    current_prompt = (
                        f"The provided image sets the scene layout. "
                        f"Keep the character in the bottom right exactly as is, but make them move their mouth and head naturally to narrate. "
                        f"Preserve the exact features of the character (antenna ears, spring tail, LED eyes). Zero tolerance for appearance changes during the motion. "
                        f"CRITICAL: Replace the empty/black background with a dynamic cinematic video showing: '{current_prompt}' "
                        f"The background video should be behind the character. "
                        f"4k resolution, photorealistic, high quality composite."
                    )
                    print("    ✅ Image object created and prompt refined for layout.", flush=True)
                else:
                    print("    ⚠️ Image file is empty.", flush=True)
                    
            except Exception as e:
                print(f"⚠️ Failed to load image: {e}", flush=True)

        # Retry Logic for Safety Violations and Internal Errors
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                print(f"🎬 Generating scene {scene.scene_number} (Attempt {attempt+1}/{max_attempts})...", flush=True)
                
                kwargs = {
                    "model": model_id,
                    "prompt": current_prompt,
                    "config": {"aspect_ratio": "9:16"}
                }
                
                # Pass image object directly if available and it's the first attempt or if we haven't stripped it yet
                if image_input:
                    kwargs['image'] = image_input

                operation = self.client.models.generate_videos(**kwargs)
                
                # Polling
                while not operation.done:
                    time.sleep(5)
                    operation = self.client.operations.get(operation)
                    print(".", end="", flush=True)
                print(" Done!", flush=True)

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    return # Success!
                else:
                    # Check for explicit error in operation result if not raised by SDK
                    error_info = getattr(operation, 'error', 'Unknown Error')
                    raise Exception(f"No video returned. Operation Error: {error_info}")

            except Exception as e:
                err_str = str(e).lower()
                
                # Case 1: Internal Error (Transient)
                if "internal error" in err_str or "try again later" in err_str or "500" in err_str:
                    print(f"⚠️ Internal Server Error detected. Waiting 30s before retry...", flush=True)
                    time.sleep(30)
                    continue # Retry with same settings
                
                # Case 2: Safety Violation (Prompt Issue)
                if "violate" in err_str or "code': 3" in err_str:
                    print(f"⚠️ Safety Violation detected!", flush=True)
                    if attempt < max_attempts - 1:
                        print("♻️ Retrying with SAFE PROMPT (No image)...", flush=True)
                        current_prompt = "Cinematic slow motion background, atmospheric lighting, 4k resolution, photorealistic."
                        image_input = None # Remove image input
                        continue
                
                # Case 3: Other Errors
                print(f"❌ Veo Error details: {e}", flush=True)
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(10) # Generic wait for other errors

    async def _generate_image_imagen(self, scene) -> str:
        output_path = f"temp/scene_{scene.scene_number}.png"
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"Image for scene {scene.scene_number} already exists.")
            return output_path

        if not self.client:
            return self._create_mock_image(output_path)

        print(f"🎨 Requesting Imagen 3 for scene {scene.scene_number}...")
        
        try:
            model_id = "imagen-3.0-generate-001"
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._run_imagen_generation, model_id, scene, output_path)
            
            if os.path.exists(output_path):
                print(f"✅ Imagen generation complete: {output_path}")
                return output_path
                
        except Exception as e:
            print(f"❌ Imagen Generation Error: {e}")
            
        return self._create_mock_image(output_path)

    def _run_imagen_generation(self, model_id, scene, output_path):
        try:
            # CORRECTED METHOD: generate_images (plural)
            response = self.client.models.generate_images(
                model=model_id,
                prompt=scene.visual_description,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    safety_filter_level="block_some",
                    person_generation="allow_adult"
                )
            )
            
            if response and response.generated_images:
                image = response.generated_images[0]
                image.image.save(output_path)
            else:
                raise Exception("No image returned")
        except Exception as e:
            if "429" in str(e):
                print("Rate limit hit. Waiting 10s...")
                time.sleep(10)
            raise e

    def _create_mock_video(self, path, duration):
        print(f"⚠️ Creating mock video for: {path}")
        from moviepy import ColorClip
        clip = ColorClip(size=(1080, 1920), color=(0, 0, 50), duration=duration)
        clip.write_videofile(path, fps=24, codec="libx264", logger=None)
        return path

    def _create_mock_image(self, path):
        print(f"⚠️ Creating mock image for: {path}")
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1080, 1920), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10,10), "Placeholder", fill=(255,255,255))
        img.save(path)
        return path
