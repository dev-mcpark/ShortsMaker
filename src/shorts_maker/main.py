import os
import asyncio
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.uploader.youtube_uploader import YouTubeUploader

# Load environment variables
load_dotenv()

@task(name="1. 주제 기획 및 스크립트 작성", retries=2, retry_delay_seconds=2)
async def task_plan_content(mode: str):
    logger = get_run_logger()
    logger.info(f"Step 1: Planning content in [{mode}] mode...")
    
    planner = ScriptPlanner(generation_mode=mode)
    script = await planner.plan_content()
    
    logger.info(f"Planned Script Title: {script.title}")
    return script

@task(name="2. 영상 소스 생성", retries=3, retry_delay_seconds=5)
async def task_generate_video(script, mode: str):
    logger = get_run_logger()
    logger.info(f"Step 2: Generating clips using {mode.title()} Generator...")
    
    generator = VideoGenerator(mode=mode)
    video_paths = await generator.generate_clips(script)
    
    logger.info(f"Generated {len(video_paths)} clips.")
    return video_paths

@task(name="3. 영상 편집 및 합성", log_prints=True)
async def task_edit_video(video_paths, script):
    logger = get_run_logger()
    logger.info("Step 3: Editing and composing final video...")
    
    editor = VideoEditor()
    final_video_path = await editor.compose_video(video_paths, script)
    
    if final_video_path:
        logger.info(f"Final video created at: {final_video_path}")
        return final_video_path
    else:
        raise RuntimeError("Video composition failed: No output path returned.")

@task(name="4. 유튜브 업로드", retries=3, retry_delay_seconds=10)
async def task_upload_youtube(final_video_path, script):
    logger = get_run_logger()
    logger.info("Step 4: Uploading to YouTube...")
    
    uploader = YouTubeUploader()
    
    description = script.description
    if hasattr(script, 'source_url') and script.source_url:
        description += f"\n\n출처: {script.source_url}"

    await uploader.upload(final_video_path, {
        "title": script.title,
        "description": description,
        "tags": script.tags
    })
    logger.info("Upload completed successfully.")

@flow(name="Shorts Maker Pipeline", log_prints=True)
async def shorts_maker_flow():
    logger = get_run_logger()
    
    # Get generation mode from env (default to 'image')
    mode = os.getenv("GENERATION_MODE", "image").lower()
    logger.info(f"🚀 Starting ShortsMaker Pipeline in [{mode.upper()}] mode")

    try:
        # 1. Plan
        script = await task_plan_content(mode)
        
        # 2. Generate
        video_paths = await task_generate_video(script, mode)
        
        # 3. Edit
        final_video_path = await task_edit_video(video_paths, script)
        
        # 4. Upload
        await task_upload_youtube(final_video_path, script)
        
        logger.info("✅ All steps completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}")
        raise

if __name__ == "__main__":
    # Work Pool 기반의 배포(Deployment) 정의
    # 이 스크립트를 한 번 실행하면, Prefect 서버에 "이런 작업이 있다"고 등록만 하고 종료됩니다.
    # 실제 실행은 'prefect worker start --pool local-process-pool' 명령어로 켜둔 워커가 담당합니다.
    
    deployment = shorts_maker_flow.to_deployment(
        name="daily-shorts-maker",
        version="1.0",
        tags=["production"],
        # 'local-process-pool'이라는 이름의 Work Pool에 작업을 던집니다.
        work_pool_name="local-process-pool", 
        parameters={}
    )
    
    # 서버에 배포 적용
    deployment.apply()
    
    print("✅ Deployment 'daily-shorts-maker' has been applied to work pool 'local-process-pool'.")
    print("👉 Now run this command in a terminal to start the worker:")
    print("   prefect worker start --pool local-process-pool")