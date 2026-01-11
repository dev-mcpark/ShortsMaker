import os
import asyncio
import time
import requests
import json
import base64
from typing import List
from google.oauth2 import service_account
from google.auth.transport.requests import Request

class VideoGenerator:
    def __init__(self):
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.location = os.getenv("GCP_LOCATION", "us-central1")
        self.service_account_file = "service_account.json"
        
        # Use Imagen 3 for image generation
        self.api_endpoint = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/imagen-3.0-generate-001:predict"
        
        if not os.path.exists(self.service_account_file):
            print(f"Warning: {self.service_account_file} not found. Generation will fail.")
            self.credentials = None
        else:
            self.credentials = service_account.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

    def _get_access_token(self):
        if not self.credentials:
            return None
        self.credentials.refresh(Request())
        return self.credentials.token

    async def generate_clips(self, script) -> List[str]:
        video_paths = []
        for scene in script.scenes:
            path = await self._generate_single_image(scene)
            video_paths.append(path)
            # Add a small delay between successful requests to be polite to the API
            time.sleep(5) 
        return video_paths

    async def _generate_single_image(self, scene) -> str:
        image_path = f"temp/scene_{scene.scene_number}.png"
        
        if os.path.exists(image_path) and os.path.getsize(image_path) > 1000:
            print(f"Image for scene {scene.scene_number} already exists. Skipping.")
            return image_path

        print(f"Requesting Imagen 3 to generate image for scene {scene.scene_number}...")
        
        max_retries = 3
        retry_delay = 10 # seconds

        for attempt in range(max_retries):
            try:
                token = self._get_access_token()
                if not token:
                    raise Exception("No valid credentials found.")
                    
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                data = {
                    "instances": [
                        {
                            "prompt": scene.visual_description
                        }
                    ],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": "9:16"
                    }
                }
                
                response = requests.post(self.api_endpoint, headers=headers, json=data)
                
                if response.status_code == 200:
                    result = response.json()
                    predictions = result.get('predictions', [])
                    
                    if predictions:
                        bytes_base64 = predictions[0].get('bytesBase64Encoded')
                        if bytes_base64:
                            image_data = base64.b64decode(bytes_base64)
                            with open(image_path, "wb") as f:
                                f.write(image_data)
                            print(f"Imagen 3 generated image for scene {scene.scene_number}")
                            return image_path
                    print(f"No image data found: {result}")
                    break # Don't retry if response is 200 but empty (logic error)

                elif response.status_code == 429:
                    print(f"Rate limit hit (429). Waiting {retry_delay}s before retry {attempt + 1}/{max_retries}...")
                    time.sleep(retry_delay)
                    retry_delay *= 2 # Exponential backoff (10s -> 20s -> 40s)
                else:
                    print(f"Imagen API Error: {response.status_code} - {response.text}")
                    break # Don't retry for other errors (400, 401, etc.)
                    
            except Exception as e:
                print(f"Error generating image for scene {scene.scene_number}: {e}")
                break

        # If we exhausted retries or failed, create placeholder
        if not os.path.exists(image_path):
             self._create_mock_image(image_path)
             
        return image_path

    def _create_mock_image(self, path):
        """Creates a placeholder image using PIL."""
        print(f"Creating placeholder image for: {path}")
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1080, 1920), color = (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10,10), "Placeholder", fill=(255,255,255))
        img.save(path)
