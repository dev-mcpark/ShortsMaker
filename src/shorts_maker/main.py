import os
import asyncio
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.generator.video_generator import VideoGenerator
from shorts_maker.editor.video_editor import VideoEditor
from shorts_maker.uploader.youtube_uploader import YouTubeUploader
from shorts_maker.utils.logger import setup_file_logging

# Load environment variables
load_dotenv()

# Set up file logging with rotation
setup_file_logging(
    log_dir="logs",
    log_file="shorts_maker.log",
    max_bytes=10 * 1024 * 1024,  # 10MB per file
    backup_count=5  # Keep 5 backup files
)

@task(name="1. 주제 기획 및 스크립트 작성", retries=2, retry_delay_seconds=2)
async def task_plan_content(mode: str):
    logger = get_run_logger()
    logger.info(f"Step 1: Planning content in [{mode}] mode...")
    
    planner = ScriptPlanner(generation_mode=mode)
    script = await planner.plan_content()
    
    if not script:
        raise RuntimeError("Failed to generate a valid script after multiple attempts.")
    
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

@task(name="5. 임시 파일 정리")
def task_cleanup_temp():
    logger = get_run_logger()
    temp_dir = "temp"
    if not os.path.exists(temp_dir):
        return

    files = os.listdir(temp_dir)
    count = 0
    for f in files:
        file_path = os.path.join(temp_dir, f)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                count += 1
        except Exception as e:
            logger.warning(f"Failed to delete {file_path}: {e}")
    
    logger.info(f"Cleaned up {count} temporary files from '{temp_dir}'.")

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
        
        # 5. Cleanup
        task_cleanup_temp()
        
        logger.info("✅ All steps completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}")
        # 실패하더라도 임시 파일은 정리하도록 시도 (선택 사항)
        task_cleanup_temp()
        raise

if __name__ == "__main__":
    # [중요] 소스 코드의 위치를 '현재 프로젝트 폴더'로 명시합니다.
    # 이렇게 하면 Prefect가 임시 폴더로 복사하지 않고, 이 경로를 그대로 참조합니다.
    project_path = os.getcwd()
    
    deployment = shorts_maker_flow.from_source(
        source=project_path,
        entrypoint="src/shorts_maker/main.py:shorts_maker_flow"
    ).to_deployment(
        name="daily-shorts-maker",
        version="1.0",
        tags=["production"],
        work_pool_name="local-process-pool",
        job_variables={
            "cwd": project_path,
            "env": {
                "PYTHONPATH": project_path
            }
        },
        parameters={}
    )
    
    deployment.apply()
    
    print(f"✅ Deployment applied with source: {project_path}")
    print("👉 Restart your worker if needed, then trigger a run from UI.")