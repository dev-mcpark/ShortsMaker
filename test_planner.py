import asyncio
import os
from dotenv import load_dotenv
from shorts_maker.planner.script_planner import ScriptPlanner

load_dotenv()

async def test_planner():
    planner = ScriptPlanner()
    print("Testing ScriptPlanner...")
    try:
        script = await planner.plan_content(topic="The speed of light")
        print("\n--- Planned Script ---")
        print(f"Title: {script.title}")
        print(f"Description: {script.description}")
        print(f"Tags: {', '.join(script.tags)}")
        for scene in script.scenes:
            print(f"\nScene {scene.scene_number}:")
            print(f"  Visual: {scene.visual_description}")
            print(f"  Script: {scene.script_text}")
            print(f"  Duration: {scene.duration_seconds}s")
    except Exception as e:
        print(f"Error during planning: {e}")

if __name__ == "__main__":
    asyncio.run(test_planner())
