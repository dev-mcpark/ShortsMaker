import os
import json
import random
import feedparser
from datetime import datetime
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
    scenes: List[VideoScene]

class ScriptPlanner:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.history_file = "topic_history.json"
        self.url_history_file = "url_history.json"
        self.script_output_dir = "outputs/scripts"
        
        # Tech/News focused moods
        self.allowed_moods = ['upbeat', 'inspiring', 'cinematic', 'energetic', 'calm']
        self.story_styles = ["The Tech Reporter", "The Insight Curator"]

    def _load_url_history(self) -> List[str]:
        if os.path.exists(self.url_history_file):
            try:
                with open(self.url_history_file, 'r') as f:
                    return json.load(f)
            except: return []
        return []

    def _save_history(self, title: str, url: str):
        # Save URL history
        url_history = self._load_url_history()
        url_history.append(url)
        with open(self.url_history_file, 'w') as f:
            json.dump(url_history[-100:], f, indent=2)

    def _fetch_geeknews_rss(self, limit=10) -> List[Dict]:
        """Fetches latest news from GeekNews RSS."""
        print("Fetching trends from GeekNews (news.hada.io)...")
        url = "https://news.hada.io/rss/news"
        try:
            feed = feedparser.parse(url)
            posts = []
            url_history = self._load_url_history()
            
            for entry in feed.entries:
                if entry.link in url_history: continue
                
                # GeekNews often puts summary in description
                content = entry.description if hasattr(entry, 'description') else entry.title
                
                posts.append({
                    'source': 'GeekNews',
                    'title': entry.title,
                    'content': content,
                    'url': entry.link
                })
                if len(posts) >= limit: break
            return posts
        except Exception as e:
            print(f"RSS fetch failed: {e}")
            return []

    async def plan_content(self, topic: str = None) -> ShortsScript:
        candidates = self._fetch_geeknews_rss()
        
        if not candidates:
            print("⚠️ No new GeekNews items found. Using fallback.")
            candidates = [{'source': 'Fallback', 'title': 'AI is changing the world', 'content': 'AI impact.', 'url': 'google.com'}]

        selection = await self._select_best_topic(candidates)
        
        print(f"🔥 Selected Topic: {selection['title']}")
        self._save_history(selection['title'], selection['url'])

        script = await self._write_script(selection)
        
        # Save script file
        try:
            import re
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[^\w\s-]', '', script.title).strip().replace(' ', '_')[:30]
            filepath = os.path.join(self.script_output_dir, f"script_{timestamp}_{safe_title}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(script.model_dump_json(indent=2))
        except: pass
        
        return script

    async def _select_best_topic(self, candidates: List[Dict]) -> Dict:
        candidates_text = ""
        for i, item in enumerate(candidates):
            candidates_text += f"{i+1}. {item['title']}\n"

        prompt = f"""
        You are a 'Tech News Editor'.
        Select the ONE most interesting/impactful news item for a general audience.
        
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
        except:
            return random.choice(candidates)

    async def _write_script(self, item: Dict) -> ShortsScript:
        print(f"Writing script for: {item['title']}")
        
        mood_list_str = ', '.join(self.allowed_moods)
        style = "The Tech Reporter"
        
        prompt = f"""
        Act as a professional **Tech News Anchor**.
        Create a 45-second YouTube Shorts script summarizing this news.
        
        **NEWS SOURCE:**
        Title: {item['title']}
        Summary: {item['content']}
        
        **INSTRUCTION:**
        - **Language:** Korean (Natural, Professional yet Engaging).
        - **Structure:**
          1. **Hook:** "Did you hear about [Title]?"
          2. **Body:** Summarize key points clearly.
          3. **Takeaway:** Why is this important?
        - **Visuals:** Describe relevant Tech/Abstract imagery in **ENGLISH** (Cyberpunk, Futuristic, Clean Minimalist).
        - **Mood:** Choose best from [{mood_list_str}].
        
        Output JSON:
        {{
            "title": "{item['title']}",
            "description": "Tech news summary",
            "tags": ["tech", "news", "geeknews"],
            "mood": "upbeat",
            "style": "{style}",
            "source_url": "{item['url']}",
            "scenes": [
                {{
                    "scene_number": 1,
                    "visual_description": "Futuristic AI dashboard in 8k...",
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
            return ShortsScript(**data)
        except Exception as e: raise e
