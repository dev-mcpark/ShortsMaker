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
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"Video for scene {scene.scene_number} already exists.")
            return output_path

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

    def _run_veo_generation(self, model_id, scene, output_path):
        try:
            # CORRECTED METHOD: generate_videos (plural) with dictionary config
            operation = self.client.models.generate_videos(
                model=model_id,
                prompt=scene.visual_description,
                config={
                    "aspect_ratio": "9:16"
                }
            )
            
            # Polling Loop for LRO
            print(f"⏳ Veo job started: {operation.name}. Waiting for completion...")
            while not operation.done:
                time.sleep(10) # Poll every 10 seconds
                try:
                    # Refresh operation status
                    # Note: Using get_operation or similar based on SDK structure. 
                    # Assuming client.operations.get works for google-genai and expects the object
                    operation = self.client.operations.get(operation)
                    print(".", end="", flush=True)
                except Exception as poll_err:
                    print(f"⚠️ Polling warning: {poll_err}")
                    # If polling fails, maybe wait longer and try again, or break if critical
                    # For now, continue waiting
            
            print(" Done!")
            
            # Access result property (not method)
            response = operation.result
            
            if response and response.generated_videos:
                video = response.generated_videos[0]
                video.video.save(output_path)
            else:
                # Avoid accessing 'status' directly if it doesn't exist
                raise Exception(f"No video returned. Operation details: {operation}")
                
        except Exception as e:
            print(f"SDK Error details: {e}")
            raise e

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
