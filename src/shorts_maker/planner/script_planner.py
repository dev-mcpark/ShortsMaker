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
    scenes: List[VideoScene]

class ScriptPlanner:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.history_file = "topic_history.json"
        self.url_history_file = "url_history.json"
        self.script_output_dir = "outputs/scripts"
        
        self.allowed_moods = [
            'upbeat', 'inspiring', 'cinematic', 'energetic', 'calm', 
            'mysterious', 'playful', 'dramatic'
        ]
        self.story_styles = ["The Insight Curator", "The Trend Reporter", "The Deep Dive"]

        # 🚀 Mega Expansion of RSS Sources
        self.rss_sources = {
            "Tech_IT": [
                "https://news.hada.io/rss/news", # GeekNews
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
                "https://lifehacker.com/rss", # Life hacks
                "https://www.psychologytoday.com/us/feed/index.rss" # Mental Health
            ],
            "Design_Culture": [
                "https://www.designboom.com/feed/",
                "https://hypebeast.kr/feed"
            ]
        }

    def _load_url_history(self) -> List[str]:
        if os.path.exists(self.url_history_file):
            try:
                with open(self.url_history_file, 'r') as f:
                    return json.load(f)
            except: return []
        return []

    def _save_history(self, title: str, url: str):
        url_history = self._load_url_history()
        url_history.append(url)
        with open(self.url_history_file, 'w') as f:
            json.dump(url_history[-100:], f, indent=2)

    def _is_recent(self, entry) -> bool:
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if (datetime.now() - published_dt).days <= 7:
                    return True
                else:
                    return False
            return True 
        except:
            return True

    def _fetch_rss_feeds(self) -> List[Dict]:
        posts = []
        url_history = self._load_url_history()
        
        # Pick 1 source from EACH category for maximum variety
        selected_sources = []
        for category, urls in self.rss_sources.items():
            source_url = random.choice(urls)
            selected_sources.append((category, source_url))
            
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
                    
                    if len([p for p in posts if p['category'] == category]) >= 2:
                        break
            except Exception as e:
                print(f"Failed to fetch {url}: {e}")
                continue
                
        print(f"✅ Found {len(posts)} recent candidates.")
        return posts

    async def plan_content(self, topic: str = None) -> ShortsScript:
        candidates = self._fetch_rss_feeds()
        
        if not candidates:
            print("⚠️ No recent items found. Using fallback.")
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
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(script.model_dump_json(indent=2))
        except: pass
        
        return script

    async def _select_best_topic(self, candidates: List[Dict]) -> Dict:
        candidates_text = ""
        for i, item in enumerate(candidates):
            candidates_text += f"{i+1}. [{item['category']}] {item['title']}\n"

        prompt = f"""
        You are an **Editor-in-Chief** for a viral YouTube Shorts channel covering Tech, Finance, Gaming, and Life Hacks.
        
        Select the ONE article from the list that is most **Viral, Useful, or Entertaining**.
        
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
        style = "The Info Curator"
        
        prompt = f"""
        Act as a professional **Content Creator**.
        Create a YouTube Shorts script (50-60s) summarizing this news.
        
        **SOURCE MATERIAL:**
        Category: {item['category']}
        Title: {item['title']}
        Content: {item['content']}
        
        **INSTRUCTION:**
        - **Language:** Korean (Natural, Engaging).
        - **Tone:** Match the category (e.g., Gaming -> Energetic, Finance -> Professional, Life -> Friendly).
        - **Structure:** Hook -> Main Info -> Takeaway.
        
        **Visuals (CRITICAL):** 
        - Write **High-Quality Image Prompts** for Imagen 3 in **ENGLISH**.
        - [Subject] + [Environment] + [Lighting] + [Style].
        - Match visual style to category (e.g., Gaming -> 3D Render/Character, Finance -> Wall Street/Chart).
        
        **Mood:** Choose best from [{mood_list_str}].
        
        Output JSON:
        {{
            "title": "{item['title']}",
            "description": "Summary",
            "tags": ["{item['category']}", "shorts"],
            "mood": "upbeat",
            "style": "{style}",
            "source_url": "{item['url']}",
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
            return ShortsScript(**data)
        except Exception as e: raise e