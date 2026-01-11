import os
import json
import random
from datetime import datetime
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Tuple
from googlesearch import search

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
        
        # Define Specific Niches (removed as per request for broad trends, but structure kept clean)
        # We are using broad trend search now.
        
        self.allowed_moods = [
            'happy', 'upbeat', 'energetic', 'playful', 'inspiring',
            'mysterious', 'cinematic', 'calm', 'ambient', 'romantic',
            'dramatic', 'epic', 'suspense', 'dark', 'aggressive'
        ]
        
        self.story_styles = [
            "The Mystery Gap (Keep the answer until the end)",
            "The Myth Buster (Challenge common beliefs)",
            "The Shocking Listicle (Rapid fire facts)"
        ]

    def _load_history(self) -> List[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_history(self, topic: str):
        history = self._load_history()
        history.append(topic)
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)

    def _get_trend_search_query(self) -> str:
        """Generates a broad, trend-focused search query."""
        now = datetime.now()
        year = now.year
        month = now.strftime("%B")
        
        # Broad queries to catch anything interesting
        queries = [
            f"most interesting news {month} {year}",
            f"viral stories {month} {year}",
            f"weirdest facts discovered recently {year}",
            f"trending science mysteries {year}",
            f"internet sensation topics {year}",
            f"mind blowing discoveries {month} {year}",
            f"unbelievable true stories {year}",
            f"what people are talking about today {year}"
        ]
        
        return random.choice(queries)

    async def plan_content(self, topic: str = None) -> ShortsScript:
        selected_topic = topic
        context = ""
        
        if not selected_topic:
            selected_topic, context = await self._generate_topic_from_search()
        
        print(f"🔥 Selected Topic: {selected_topic}")
        self._save_history(selected_topic)

        script = await self._write_script(selected_topic, context)
        return script

    async def _generate_topic_from_search(self) -> Tuple[str, str]:
        history = self._load_history()
        recent_history = history[-20:] if history else []
        
        query = self._get_trend_search_query()
        print(f"🔎 Searching Global Trends for: '{query}'...")
        
        search_results = []
        try:
            results = search(query, num_results=10, advanced=True)
            for r in results:
                if "youtube.com" not in r.url:
                    search_results.append(f"Title: {r.title}\nSnippet: {r.description}\nSource: {r.url}")
                
        except Exception as e:
            print(f"Search failed: {e}. Falling back.")
            search_results = ["Fallback context."]

        search_context = "\n---\n".join(search_results)
        
        prompt = f"""
        You are a 'Viral Trend Hunter'.
        Scan the search results below and pick the SINGLE most fascinating, click-worthy topic for a general audience.
        
        **Search Results (Context):**
        {search_context}
        
        **Constraints:**
        1. **Broad Appeal:** Must be interesting to ANYONE (not just experts).
        2. **Format:** Question ("~까?") or Statement ("~다").
        3. **Trigger:** Curiosity, Shock, Fun, or Awe.
        4. **Length:** Under 25 chars (Korean).
        5. **No Repeats:** Avoid: {', '.join(recent_history)}.
        
        Output ONLY the topic sentence.
        """
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            topic = response.choices[0].message.content.strip().replace('"', '')
            return topic, search_context
        except Exception as e:
            print(f"Topic generation failed: {e}")
            return "오늘 인터넷에서 가장 핫한 이야기", ""

    async def _write_script(self, topic: str, context: str) -> ShortsScript:
        selected_style = random.choice(self.story_styles)
        print(f"Writing script for: {topic} (Style: {selected_style})")
        
        mood_list_str = ', '.join(self.allowed_moods)
        
        prompt = f"""
        Act as a professional YouTube Shorts scriptwriter.
        Create a 40-50 second viral script based on the topic: "{topic}".
        
        **CORE MATERIAL (SEARCH DATA):**
        {context}
        
        **INSTRUCTION:** 
        - Use the CORE MATERIAL to ensure the script is based on real, recent info.
        - **Identify the specific Source URL** from the context.
        - **ALL OUTPUT (Title, Script, Description) MUST BE IN KOREAN.**
        
        **STORYTELLING STYLE: {selected_style}**
        
        Output JSON:
        {{
            "title": "{topic}",
            "description": "Short description",
            "tags": ["tag1", "tag2"],
            "mood": "mysterious",
            "style": "{selected_style}",
            "source_url": "The specific URL from CORE MATERIAL",
            "scenes": [
                {{
                    "scene_number": 1,
                    "visual_description": "Cinematic shot description in ENGLISH",
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
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            if data.get('mood') not in self.allowed_moods:
                data['mood'] = 'cinematic'
                
            return ShortsScript(**data)
            
        except Exception as e:
            print(f"Script writing failed: {e}")
            raise e
