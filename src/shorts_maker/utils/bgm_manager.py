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
        Includes a mapping to group similar moods.
        """
        mood = mood.lower()
        
        # Mood Groups: Map AI-generated moods to actual file categories
        mood_map = {
            'luxury': 'corporate',
            'corporate': 'corporate',
            'sci-fi': 'mysterious',
            'suspense': 'mysterious',
            'emotional': 'calm',
            'energetic': 'upbeat',
            'calm': 'calm'
        }
        
        # Use mapped category if exists, otherwise use the mood name directly
        category = mood_map.get(mood, mood)
        
        # 1. Try to find files for the specific category
        pattern = os.path.join(self.bgm_dir, f"{category}*.mp3")
        files = glob.glob(pattern)
        
        # 2. If not found, try the raw mood name
        if not files and category != mood:
            pattern = os.path.join(self.bgm_dir, f"{mood}*.mp3")
            files = glob.glob(pattern)

        if not files:
            # Fallback: Look for ANY mp3 file
            all_files = glob.glob(os.path.join(self.bgm_dir, "*.mp3"))
            if all_files:
                return random.choice(all_files)
            return None
        
        selected_file = random.choice(files)
        print(f"Selected BGM Category: {category} ({selected_file})")
        return selected_file
