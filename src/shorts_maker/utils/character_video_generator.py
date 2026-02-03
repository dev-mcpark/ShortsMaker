"""
CharacterVideoGenerator - 캐릭터 이미지로부터 말하는 영상 생성

캐릭터 이미지를 Veo에 입력하여 자연스럽게 말하는 영상을 생성합니다.
한 번 생성한 영상은 assets 폴더에 저장하여 재사용합니다.

사용법:
    python -m shorts_maker.utils.character_video_generator

또는 코드에서:
    from shorts_maker.utils.character_video_generator import CharacterVideoGenerator
    generator = CharacterVideoGenerator()
    video_path = await generator.generate_speaking_video("assets/character_ref.png")
"""
import os
import time
import asyncio
from typing import Optional
from pathlib import Path

from google import genai
from google.genai import types
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings


class CharacterVideoGenerator:
    """
    캐릭터 이미지를 말하는 영상으로 변환하는 생성기
    """

    # 말하는 캐릭터를 위한 프롬프트 템플릿
    SPEAKING_PROMPTS = {
        "news_anchor": (
            "Animate this character as a professional news anchor speaking to camera. "
            "The character speaks naturally with subtle lip movements, occasional head nods, "
            "gentle hand gestures, and natural eye movements. "
            "Professional broadcast lighting, steady camera, smooth motion. "
            "The character maintains a friendly, engaging expression while speaking. "
            "No background change, focus only on the character's speaking animation."
        ),
        "presenter": (
            "Animate this character as a friendly presenter talking to the audience. "
            "Natural speaking movements: lip sync, head tilts, expressive eyes, small gestures. "
            "Warm and engaging personality, professional demeanor. "
            "Smooth, natural motion, broadcast quality."
        ),
        "casual": (
            "Animate this character speaking casually and naturally. "
            "Relaxed speaking movements, natural expressions, subtle gestures. "
            "Friendly and approachable demeanor."
        ),
        "energetic": (
            "Animate this character speaking with energy and enthusiasm. "
            "Dynamic expressions, animated gestures, engaging eye contact. "
            "Upbeat and exciting presentation style."
        ),
    }

    def __init__(self):
        self.logger = get_logger(__name__)
        self.project_id = settings.gcp_project_id
        self.location = settings.gcp_location

        # settings에서 이미 GOOGLE_APPLICATION_CREDENTIALS 환경변수 설정됨

        try:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location
            )
            self.logger.info("✅ CharacterVideoGenerator initialized")
        except Exception as e:
            self.logger.error(f"❌ Failed to init GenAI Client: {e}")
            self.client = None

    async def generate_speaking_video(
        self,
        character_image_path: str,
        output_path: Optional[str] = None,
        duration_seconds: int = 8,
        style: str = "news_anchor",
        custom_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """
        캐릭터 이미지로부터 말하는 영상 생성

        Args:
            character_image_path: 캐릭터 이미지 경로
            output_path: 출력 영상 경로 (None이면 자동 생성)
            duration_seconds: 영상 길이 (초)
            style: 스타일 프리셋 ("news_anchor", "presenter", "casual", "energetic")
            custom_prompt: 커스텀 프롬프트 (None이면 스타일 프리셋 사용)

        Returns:
            생성된 영상 경로 또는 None (실패 시)
        """
        if not self.client:
            self.logger.error("GenAI client not initialized")
            return None

        if not os.path.exists(character_image_path):
            self.logger.error(f"Character image not found: {character_image_path}")
            return None

        # 출력 경로 설정
        if output_path is None:
            input_name = Path(character_image_path).stem
            output_path = str(settings.assets_dir / f"{input_name}_speaking.mp4")

        # 출력 디렉토리 생성
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 프롬프트 선택
        prompt = custom_prompt or self.SPEAKING_PROMPTS.get(style, self.SPEAKING_PROMPTS["news_anchor"])

        self.logger.info(f"🎬 Generating speaking video from: {character_image_path}")
        self.logger.info(f"   Style: {style}")
        self.logger.info(f"   Output: {output_path}")

        try:
            # 이미지 로드
            with open(character_image_path, "rb") as f:
                image_bytes = f.read()

            image_input = types.Image(
                image_bytes=image_bytes,
                mime_type="image/png"
            )

            # Veo 모델로 영상 생성
            model_id = settings.veo_model_id

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                self._run_veo_generation,
                model_id,
                prompt,
                image_input,
                output_path
            )

            if result and os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                self.logger.info(f"✅ Speaking video generated: {output_path} ({file_size:,} bytes)")
                return output_path
            else:
                self.logger.error("❌ Video generation failed")
                return None

        except Exception as e:
            self.logger.error(f"❌ Error generating speaking video: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    def _run_veo_generation(self, model_id: str, prompt: str, image_input, output_path: str) -> bool:
        """Veo API 호출 (동기)"""
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                self.logger.info(f"   Generating (Attempt {attempt + 1}/{max_attempts})...")

                operation = self.client.models.generate_videos(
                    model=model_id,
                    prompt=prompt,
                    image=image_input,
                    config={"aspect_ratio": "9:16"}
                )

                # 완료 대기
                while not operation.done:
                    time.sleep(10)
                    operation = self.client.operations.get(operation)
                    self.logger.debug("   Waiting...")

                self.logger.info("   Done!")

                response = operation.result
                if response and response.generated_videos:
                    response.generated_videos[0].video.save(output_path)
                    return True
                else:
                    error_info = getattr(operation, 'error', 'Unknown Error')
                    raise Exception(f"No video generated. Error: {error_info}")

            except Exception as e:
                err_str = str(e).lower()

                if "internal error" in err_str or "500" in err_str:
                    self.logger.warning(f"   ⚠️ Server error, retrying in 30s...")
                    time.sleep(30)
                    continue

                if "violate" in err_str:
                    self.logger.warning(f"   ⚠️ Safety violation, simplifying prompt...")
                    prompt = (
                        "Animate this character speaking naturally. "
                        "Subtle movements, professional quality."
                    )
                    continue

                self.logger.error(f"   ❌ Error: {e}")
                if attempt == max_attempts - 1:
                    return False
                time.sleep(10)

        return False


async def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(
        description="캐릭터 이미지로부터 말하는 영상 생성"
    )
    parser.add_argument(
        "--input", "-i",
        default=str(settings.assets_dir / "character_ref.png"),
        help=f"캐릭터 이미지 경로 (기본값: {settings.assets_dir}/character_ref.png)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="출력 영상 경로 (기본값: assets/{input_name}_speaking.mp4)"
    )
    parser.add_argument(
        "--style", "-s",
        choices=["news_anchor", "presenter", "casual", "energetic"],
        default="news_anchor",
        help="스타일 프리셋 (기본값: news_anchor)"
    )
    parser.add_argument(
        "--prompt", "-p",
        default=None,
        help="커스텀 프롬프트 (스타일 프리셋 대신 사용)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("🎬 캐릭터 영상 생성기")
    print("=" * 60)
    print(f"입력 이미지: {args.input}")
    print(f"스타일: {args.style}")
    print()

    generator = CharacterVideoGenerator()
    result = await generator.generate_speaking_video(
        character_image_path=args.input,
        output_path=args.output,
        style=args.style,
        custom_prompt=args.prompt
    )

    if result:
        print()
        print("=" * 60)
        print(f"✅ 성공! 생성된 영상: {result}")
        print()
        print("이 영상을 GUI에서 사용하려면:")
        print(f"  Character Overlay → Video: {result}")
        print("=" * 60)
    else:
        print()
        print("❌ 영상 생성에 실패했습니다.")


if __name__ == "__main__":
    asyncio.run(main())
