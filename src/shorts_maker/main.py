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
        # 1. 주제 선정 및 스크립트 작성
        planner = ScriptPlanner()
        logger.info("Step 1: Planning content...")
        # plan_content() call updated to match new signature if needed, but defaults are fine
        script = await planner.plan_content()
        logger.info(f"Planned script: {script.title}")
        
        # 2. Veo3 (Imagen 3) 기반 영상 생성
        generator = VideoGenerator()
        logger.info("Step 2: Generating video clips using Veo3...")
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
            
            # Append source to description if available
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