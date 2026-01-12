import os
import json
import random
import feedparser
from datetime import datetime, timedelta
import time
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Dict

class VideoScene(BaseModel):
    scene_number: int
    visual_description: str
    script_text: str
    duration_seconds: float

class ShortsScript(BaseModel):
    title: str
    description: str
    tags: List[str]
    mood: str
    style: str
    source_url: str
    generation_mode: str # New: Tracks whether this script is for 'image' or 'video'
    scenes: List[VideoScene]

class ScriptPlanner:
    def __init__(self, generation_mode: str = "image"):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.history_file = "topic_history.json"
        self.url_history_file = "url_history.json"
        self.script_output_dir = "outputs/scripts"
        self.generation_mode = generation_mode # 'image' or 'video'
        
        self.allowed_moods = ['upbeat', 'inspiring', 'cinematic', 'energetic', 'calm', 'mysterious']
        self.story_styles = ["The Insight Curator", "The Trend Reporter"]

        self.rss_sources = {
            "Tech_IT": [
                "https://news.hada.io/rss/news",
                "http://www.theverge.com/rss/full.xml",
                "https://techcrunch.com/feed/"
            ],
            "Finance_Economy": [
                "https://www.investing.com/rss/news.rss",
                "https://www.cnbc.com/id/10000664/device/rss/rss.html",
                "https://rss.hankyung.com/feed/market.xml"
            ],
            "Gaming_Esports": [
                "http://feeds.ign.com/ign/games-all",
                "https://www.polygon.com/rss/index.xml",
                "https://kotaku.com/rss/index.xml"
            ],
            "Life_Tips": [
                "https://lifehacker.com/rss",
                "https://www.psychologytoday.com/us/feed/index.rss"
            ],
            "Design_Culture": [
                "https://www.designboom.com/feed/",
                "https://hypebeast.kr/feed"
            ]
        }

    # ... (Existing helper methods: _load_url_history, _save_history, _is_recent, _fetch_rss_feeds, _select_best_topic need to be preserved) ...
    # Re-implementing them briefly to ensure file integrity
    def _load_url_history(self) -> List[str]:
        if os.path.exists(self.url_history_file):
            try: return json.load(open(self.url_history_file, 'r'))
            except: return []
        return []

    def _save_history(self, title: str, url: str):
        url_history = self._load_url_history()
        url_history.append(url)
        with open(self.url_history_file, 'w') as f: json.dump(url_history[-100:], f, indent=2)

    def _is_recent(self, entry) -> bool:
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if (datetime.now() - published_dt).days <= 7: return True
                else: return False
            return True 
        except: return True

    def _fetch_rss_feeds(self) -> List[Dict]:
        posts = []
        url_history = self._load_url_history()
        selected_sources = []
        for category, urls in self.rss_sources.items():
            selected_sources.append((category, random.choice(urls)))
        
        print(f"📡 Fetching feeds from: {[s[1] for s in selected_sources]}")
        for category, url in selected_sources:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    if entry.link in url_history: continue
                    if not self._is_recent(entry): continue
                    content = ""
                    if hasattr(entry, 'summary'): content = entry.summary
                    elif hasattr(entry, 'description'): content = entry.description
                    else: content = entry.title
                    if len(content) < 50: continue
                    posts.append({
                        'category': category,
                        'source': feed.feed.get('title', 'Unknown Source'),
                        'title': entry.title,
                        'content': content[:1500],
                        'url': entry.link
                    })
                    if len([p for p in posts if p['category'] == category]) >= 2: break
            except Exception as e:
                print(f"Failed to fetch {url}: {e}")
                continue
        print(f"✅ Found {len(posts)} recent candidates.")
        return posts

    async def _select_best_topic(self, candidates: List[Dict]) -> Dict:
        candidates_text = ""
        for i, item in enumerate(candidates):
            candidates_text += f"{i+1}. [{item['category']}] {item['title']}\n"
        prompt = f"""
        You are an **Editor-in-Chief**. Select the ONE article that is most **Viral, Useful, or Entertaining**.
        **Candidates:**
        {candidates_text}
        Output ONLY the index number (e.g., '1').
        """
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10
            )
            import re
            match = re.search(r'\d+', response.choices[0].message.content)
            idx = int(match.group()) - 1 if match else 0
            return candidates[idx] if 0 <= idx < len(candidates) else candidates[0]
        except: return random.choice(candidates)

    async def plan_content(self, topic: str = None) -> ShortsScript:
        candidates = self._fetch_rss_feeds()
        if not candidates:
            candidates = [{'category': 'General', 'source': 'Fallback', 'title': 'AI Future', 'content': 'AI impact.', 'url': 'google.com'}]

        selection = await self._select_best_topic(candidates)
        print(f"🔥 Selected Topic: {selection['title']} ({selection['category']})")
        self._save_history(selection['title'], selection['url'])

        script = await self._write_script(selection)
        
        try:
            import re
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[^\w\s-]', '', script.title).strip().replace(' ', '_')[:30]
            filepath = os.path.join(self.script_output_dir, f"script_{timestamp}_{safe_title}.json")
            with open(filepath, 'w', encoding='utf-8') as f: f.write(script.model_dump_json(indent=2))
        except: pass
        
        return script

    async def _write_script(self, item: Dict) -> ShortsScript:
        print(f"Writing script for: {item['title']} (Mode: {self.generation_mode})")
        
        mood_list_str = ', '.join(self.allowed_moods)
        style = "The Info Curator"
        
        # Dynamic Prompt based on Generation Mode
        if self.generation_mode == "video":
            visual_instruction = """
            **Visuals (VIDEO MODE - HIGH QUALITY VEO 3.1):**
            - You MUST STRICTLY follow the **'5-Step Formula'** to maximize Veo 3.1's physics and cinematic capabilities.
            
            **Structure:**
            `[Camera Angle/Movement] + [Main Subject] + [Action/Physics] + [Environment/Texture] + [Lighting/Cinematic Style]`

            **Detailed Guidelines:**
            1. **Camera:** Use dynamic terms (e.g., "FPV drone dive", "Fast dolly zoom", "Low-angle tracking").
            2. **Subject:** Define materials (e.g., "Golden metallic robot", "Fur-covered creature").
            3. **Action (CRITICAL):** NO STATIC verbs (like "floating", "standing"). Use **high-energy physics** verbs (e.g., "shattering into glass shards", "sprinting with dust trails", "liquid morphing", "exploding in slow motion").
            4. **Environment:** Describe textures (e.g., "Wet rainy asphalt", "Crumbling stone ruins").
            5. **Style:** Lighting & Mood (e.g., "Volumetric god rays", "Cyberpunk neon reflection", "Film grain", "4k realistic").

            **Good Example:**
            "Fast tracking shot of a futuristic sports car drifting around a sharp corner, tires smoking and kicking up debris, on a wet neon-lit Tokyo highway, cinematic lens flare, hyper-realistic 8k."

            **Bad Example:**
            "Medium shot of a car driving on a road." (Too static, no texture, no lighting detail)
            """
        else: # image mode
            visual_instruction = """
            **Visuals (IMAGE MODE):**
            - Describe **STATIC DETAILS, LIGHTING, and COMPOSITION**.
            - Use terms like: "8k resolution", "Photorealistic", "Dramatic lighting", "Detailed texture", "Macro shot".
            - NO verbs implying complex motion (e.g., "explode" is bad for static, "explosion frozen in time" is good).
            """

        prompt = f"""
        Act as a professional **Content Creator**.
        Create a YouTube Shorts script (50-60s) summarizing this news.
        
        **SOURCE MATERIAL:**
        Category: {item['category']}
        Title: {item['title']}
        Content: {item['content']}
        
        **INSTRUCTION:**
        - **Language:** Korean (Natural, Engaging).
        - **Tone:** Match the category.
        - **Structure:** Hook -> Main Info -> Takeaway.
        
        {visual_instruction}
        
        **Mood:** Choose best from [{mood_list_str}].
        
        Output JSON:
        {{
            "title": "{item['title']}",
            "description": "Summary",
            "tags": ["{item['category']}", "shorts"],
            "mood": "upbeat",
            "style": "{style}",
            "source_url": "{item['url']}",
            "generation_mode": "{self.generation_mode}",
            "scenes": [
                {{
                    "scene_number": 1,
                    "visual_description": "Detailed English prompt...",
                    "script_text": "Korean narration",
                    "duration_seconds": 3.0
                }}
            ]
        }}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            if data.get('mood') not in self.allowed_moods: data['mood'] = 'upbeat'
            # Ensure generation_mode is consistent
            data['generation_mode'] = self.generation_mode
            return ShortsScript(**data)
        except Exception as e: raise e
