import os
import asyncio
import logging
from dotenv import load_dotenv
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.uploader.youtube_uploader import YouTubeUploader

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

async def main():
    try:
        # Get generation mode from env (default to 'image')
        mode = os.getenv("GENERATION_MODE", "image").lower()
        logger.info(f"🚀 Starting ShortsMaker in [{mode.upper()}] mode")

        # 1. 주제 선정 및 스크립트 작성
        planner = ScriptPlanner(generation_mode=mode)
        logger.info("Step 1: Planning content...")
        script = await planner.plan_content()
        logger.info(f"Planned script: {script.title}")
        
        # 2. 영상 생성 (Veo or Imagen)
        generator = VideoGenerator(mode=mode)
        logger.info(f"Step 2: Generating clips using {mode.title()} Generator...")
        video_paths = await generator.generate_clips(script)

        # 3. 편집 및 자막 합성
        editor = VideoEditor()
        logger.info("Step 3: Editing and composing final video...")
        final_video_path = await editor.compose_video(video_paths, script)

        if final_video_path:
            logger.info(f"Final video created at: {final_video_path}")

            # 4. 유튜브 업로드
            uploader = YouTubeUploader()
            logger.info("Step 4: Uploading to YouTube...")

            description = script.description
            if hasattr(script, 'source_url') and script.source_url:
                description += f"\n\n출처: {script.source_url}"

            await uploader.upload(final_video_path, {
                "title": script.title,
                "description": description,
                "tags": script.tags
            })
        else:
            logger.error("Video composition failed.")

    except Exception as e:
        logger.error(f"An error occurred in the pipeline: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
