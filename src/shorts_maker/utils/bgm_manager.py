import os
import random
import glob

class BGMManager:
    def __init__(self):
        self.bgm_dir = "bgm"
        os.makedirs(self.bgm_dir, exist_ok=True)

    def get_bgm_path(self, mood: str) -> str:
        """
        Finds a local BGM file that matches the mood.
        Example: if mood is 'happy', it looks for 'bgm/happy*.mp3'
        """
        mood = mood.lower()
        
        # Look for files starting with the mood name (e.g., happy_1.mp3, happy_song.mp3)
        pattern = os.path.join(self.bgm_dir, f"{mood}*.mp3")
        files = glob.glob(pattern)
        
        if not files:
            # Fallback: Look for ANY mp3 file if specific mood not found
            all_files = glob.glob(os.path.join(self.bgm_dir, "*.mp3"))
            if all_files:
                print(f"No BGM found for '{mood}', using random fallback.")
                return random.choice(all_files)
            else:
                print(f"No BGM files found in '{self.bgm_dir}' folder.")
                print(f"Please put MP3 files in '{self.bgm_dir}' named like 'happy_1.mp3', 'mysterious.mp3', etc.")
                return None
        
        selected_file = random.choice(files)
        print(f"Selected BGM: {selected_file}")
        return selected_file
