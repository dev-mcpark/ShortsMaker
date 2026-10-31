"""
CharacterVideoGenerator - 캐릭터 이미지로부터 말하는 듯한 무음 영상 생성

캐릭터 이미지를 Veo에 입력하여 말하는 동작의 무음 영상을 생성합니다.
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
import mimetypes
from typing import Optional
from pathlib import Path

from google import genai
from google.genai import types
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.utils.paid_gate import require_paid_production_enabled
from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.services.google_budget import mark_google_result, reserve_google_output


class CharacterVideoGenerator:
    """
    캐릭터 이미지를 말하는 동작의 무음 영상으로 변환하는 생성기
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
                location=self.location,
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
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
        캐릭터 이미지로부터 말하는 동작의 무음 영상 생성

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
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 프롬프트 선택
        prompt = custom_prompt or self.SPEAKING_PROMPTS.get(style, self.SPEAKING_PROMPTS["news_anchor"])

        self.logger.info(f"🎬 Generating speaking video from: {character_image_path}")
        self.logger.info(f"   Style: {style}")
        self.logger.info(f"   Output: {output_path}")

        try:
            mime_type = mimetypes.guess_type(character_image_path)[0]
            if mime_type not in {"image/png", "image/jpeg"}:
                raise ValueError("캐릭터 이미지는 PNG 또는 JPEG여야 합니다.")
            # 이미지 로드
            with open(character_image_path, "rb") as f:
                image_bytes = f.read()

            image_input = types.Image(
                image_bytes=image_bytes,
                mime_type=mime_type
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
                output_path,
                duration_seconds,
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

    def _run_veo_generation(self, model_id: str, prompt: str, image_input,
                            output_path: str, duration_seconds: int) -> bool:
        """Make one explicit Veo attempt; a new paid attempt needs a new call."""
        require_paid_production_enabled()
        if duration_seconds not in {4, 6, 8}:
            raise ValueError("Veo 생성 길이는 4, 6, 8초 중 하나여야 합니다.")
        reserve = estimated_scene_cost("video", model_id, duration_seconds)
        if reserve > settings.max_visual_cost_usd:
            raise ValueError(
                f"예상 비주얼 비용 ${reserve:.3f}가 설정 상한 "
                f"${settings.max_visual_cost_usd:.2f}를 초과합니다."
            )
        budget_request_id = reserve_google_output("video", model_id, duration_seconds)
        status = "unknown"
        try:
            operation = self.client.models.generate_videos(
                model=model_id,
                prompt=prompt,
                image=image_input,
                config={"aspect_ratio": "9:16", "duration_seconds": duration_seconds,
                        "resolution": "720p", "generate_audio": False}
            )

            for _ in range(90):  # 최대 15분 대기
                if operation.done:
                    break
                time.sleep(10)
                operation = self.client.operations.get(operation)
                self.logger.debug("   Waiting...")
            if not operation.done:
                raise TimeoutError("Veo generation did not finish within 15 minutes")

            response = operation.result
            if response and response.generated_videos:
                response.generated_videos[0].video.save(output_path)
                status = "saved"
                return True
            error_info = getattr(operation, "error", "Unknown Error")
            raise RuntimeError(f"No video generated. Error: {error_info}")
        except Exception as error:
            self.logger.error(f"   ❌ Veo generation failed: {error}")
            return False
        finally:
            if not mark_google_result(budget_request_id, status):
                self.logger.error("Google 예산 장부 상태 갱신 실패: 예약액은 유지됩니다.")


async def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(
        description="캐릭터 이미지로부터 말하는 동작의 무음 영상 생성"
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
