#!/usr/bin/env python3
"""
영상 생성 파이프라인 테스트 스크립트

이 스크립트는 저장된 스크립트를 로드하여 Generation 탭에서
실행하는 것과 동일한 파이프라인을 테스트합니다.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from shorts_maker.planner.script_planner import ShortsScript
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.utils.character_overlay import CharacterOverlayConfig
from shorts_maker.utils.logger import setup_logging, get_logger

# 로깅 설정
setup_logging()
logger = get_logger("test_generation")


def load_script(script_path: str) -> ShortsScript:
    """JSON 파일에서 스크립트 로드"""
    with open(script_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return ShortsScript.from_dict(data)


async def test_single_scene_generation(script: ShortsScript, mode: str = "image"):
    """
    단일 씬만 테스트 (API 비용 절감)
    """
    logger.info("=" * 60)
    logger.info(f"🧪 테스트 모드: {mode}")
    logger.info(f"📝 스크립트: {script.title}")
    logger.info(f"🎬 총 {len(script.scenes)}개 씬 중 1개만 테스트")
    logger.info("=" * 60)

    # CharacterOverlay 설정
    char_config = CharacterOverlayConfig()
    char_config.enabled = True
    char_config.character_image = "assets/character_ref.png"
    char_config.character_video = None  # 영상 없이 이미지만 사용
    char_config.position = "bottom_right"
    char_config.size_ratio = 0.25
    char_config.chroma_key_enabled = False  # 이미지이므로 크로마키 불필요

    logger.info(f"✅ Character Overlay 설정:")
    logger.info(f"   - Image: {char_config.character_image}")
    logger.info(f"   - Position: {char_config.position}")
    logger.info(f"   - Size: {char_config.size_ratio * 100}%")

    # VideoGenerator 초기화
    generator = VideoGenerator(
        mode=mode,
        character_overlay_config=char_config
    )

    # 첫 번째 씬만 포함하는 테스트용 스크립트 생성
    test_script = ShortsScript(
        title=script.title,
        description=script.description,
        tags=script.tags,
        scenes=[script.scenes[0]]  # 첫 번째 씬만
    )

    logger.info(f"\n🎬 씬 1 정보:")
    logger.info(f"   - Visual: {test_script.scenes[0].visual_description[:100]}...")
    logger.info(f"   - Duration: {test_script.scenes[0].duration_seconds}초")

    # 생성 실행
    logger.info(f"\n🚀 생성 시작...")
    try:
        clips = await generator.generate_clips(test_script)

        logger.info(f"\n✅ 생성 완료!")
        for i, clip in enumerate(clips):
            if os.path.exists(clip):
                size = os.path.getsize(clip)
                logger.info(f"   - 클립 {i+1}: {clip} ({size:,} bytes)")
            else:
                logger.warning(f"   - 클립 {i+1}: {clip} (파일 없음)")

        return clips

    except Exception as e:
        logger.error(f"❌ 생성 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


async def test_character_overlay_only():
    """
    캐릭터 오버레이만 테스트 (API 호출 없이)
    """
    logger.info("=" * 60)
    logger.info("🧪 캐릭터 오버레이 합성 테스트 (API 호출 없음)")
    logger.info("=" * 60)

    from shorts_maker.utils.character_overlay import CharacterOverlay

    # temp 폴더에 테스트용 배경 이미지 생성
    os.makedirs("temp", exist_ok=True)

    from PIL import Image, ImageDraw

    # 테스트용 배경 이미지 생성 (9:16 비율)
    bg = Image.new('RGB', (1080, 1920), color=(30, 50, 80))
    draw = ImageDraw.Draw(bg)
    draw.text((100, 100), "Test Background", fill=(255, 255, 255))
    draw.text((100, 200), "뉴스 배경 테스트", fill=(200, 200, 200))
    bg_path = "temp/test_background.png"
    bg.save(bg_path)
    logger.info(f"✅ 테스트 배경 이미지 생성: {bg_path}")

    # CharacterOverlay 초기화
    overlay = CharacterOverlay(
        character_source="assets/character_ref.png",
        position="bottom_right",
        size_ratio=0.25,
        corner_radius=20,
        border_width=3,
        border_color=(255, 255, 255)
    )

    # 합성 테스트
    output_path = "temp/test_composite.png"
    result = overlay.composite_on_image(bg_path, output_path)

    if os.path.exists(result):
        size = os.path.getsize(result)
        logger.info(f"✅ 합성 완료: {result} ({size:,} bytes)")
        return result
    else:
        logger.error(f"❌ 합성 실패")
        return None


async def main():
    """메인 테스트 함수"""
    print("\n" + "=" * 60)
    print("ShortsMaker 영상 생성 파이프라인 테스트")
    print("=" * 60)

    # 테스트 옵션 선택
    print("\n테스트 옵션:")
    print("1. 캐릭터 오버레이만 테스트 (API 호출 없음, 빠름)")
    print("2. 이미지 모드로 1개 씬 생성 테스트 (Imagen API)")
    print("3. 비디오 모드로 1개 씬 생성 테스트 (Veo API)")
    print("0. 종료")

    choice = input("\n선택 (0-3): ").strip()

    if choice == "0":
        print("종료합니다.")
        return

    elif choice == "1":
        result = await test_character_overlay_only()
        if result:
            print(f"\n✅ 테스트 성공! 결과 파일: {result}")

    elif choice in ["2", "3"]:
        # 스크립트 목록 표시
        script_dir = Path("outputs/scripts")
        scripts = sorted(script_dir.glob("*.json"), reverse=True)

        if not scripts:
            print("❌ 저장된 스크립트가 없습니다.")
            return

        print("\n저장된 스크립트:")
        for i, sp in enumerate(scripts[:5]):
            print(f"  {i+1}. {sp.name}")

        script_choice = input(f"\n스크립트 선택 (1-{min(5, len(scripts))}): ").strip()
        try:
            script_idx = int(script_choice) - 1
            script_path = scripts[script_idx]
        except:
            script_path = scripts[0]

        script = load_script(str(script_path))
        mode = "image" if choice == "2" else "video"

        print(f"\n📝 선택된 스크립트: {script.title}")
        print(f"🎬 생성 모드: {mode}")
        confirm = input("진행하시겠습니까? (y/n): ").strip().lower()

        if confirm == 'y':
            clips = await test_single_scene_generation(script, mode)
            if clips:
                print(f"\n✅ 테스트 성공! 생성된 클립: {clips}")
        else:
            print("취소되었습니다.")

    else:
        print("잘못된 선택입니다.")


if __name__ == "__main__":
    asyncio.run(main())
