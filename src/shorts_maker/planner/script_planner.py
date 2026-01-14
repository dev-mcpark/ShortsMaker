import os
import json
import random
import feedparser
from datetime import datetime, timedelta
import time
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Dict
import trafilatura

class VideoScene(BaseModel):
    scene_number: int
    visual_description: str
    motion_instruction: str # New: Specific motion for Veo (Stage 2)
    script_text: str
    duration_seconds: float = 5.0

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
        
        # Expanded Moods for diverse storytelling
        self.allowed_moods = [
            'suspense',   # For shocking news, warnings, mysteries
            'sci-fi',     # For AI, space, future tech
            'corporate',  # For business, money, success stories
            'emotional',  # For human stories, healing, sadness
            'energetic',  # For sports, gaming, excitement
            'calm',       # For nature, tips, meditation
            'luxury'      # For fashion, expensive cars, design
        ]
        self.story_styles = ["The Insight Curator", "The Trend Reporter"]

        # [NEW] Character Persona for Consistency
        # You can change this description to whatever character you want to appear IN the video.
        self.character_profile = "A futuristic cute robot with glowing blue eyes and a white sleek body"

        self.rss_sources = {
            "Tech_IT": [
                "https://news.hada.io/rss/news",
                "http://www.theverge.com/rss/full.xml",
                "https://techcrunch.com/feed/",
                "https://feeds.feedburner.com/TechCrunch/",
                "http://news.mit.edu/rss/feed"
            ],
            "Business": [
                "https://www.cnbc.com/id/10001147/device/rss/rss.html", # CNBC Business
                "https://feeds.contenthub.gerben.nl/economist/business", # The Economist
                "http://feeds.marketwatch.com/marketwatch/topstories/",
                "https://www.investing.com/rss/news.rss"
            ],
            "Entertainment": [
                "https://variety.com/feed/",
                "https://deadline.com/feed/",
                "https://www.hollywoodreporter.com/feed/",
                "https://www.cinema-life.net/feed/"
            ],
            "Finance_Economy": [
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
        # Save URL history (simple list for dedup)
        url_history = self._load_url_history()
        url_history.append(url)
        with open(self.url_history_file, 'w') as f: json.dump(url_history[-100:], f, indent=2)
        
        # Save Topic history (detailed for variety check)
        topic_history = []
        if os.path.exists(self.history_file):
            try: topic_history = json.load(open(self.history_file, 'r'))
            except: pass
        
        topic_history.append({
            "title": title,
            "url": url,
            "date": datetime.now().isoformat()
        })
        with open(self.history_file, 'w') as f: json.dump(topic_history[-20:], f, indent=2)

    def _is_recent(self, entry) -> bool:
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                if (datetime.now() - published_dt).days <= 14: return True
                else: return False
            return True 
        except: return True

    def _fetch_rss_feeds(self) -> List[Dict]:
        posts = []
        url_history = self._load_url_history()
        # Use ALL available sources to maximize candidate pool
        selected_sources = []
        for category, urls in self.rss_sources.items():
            for url in urls:
                selected_sources.append((category, url))
        
        # Shuffle to mix categories during fetch
        random.shuffle(selected_sources)
        
        print(f"📡 Fetching feeds from {len(selected_sources)} sources...")
        for category, url in selected_sources:
            try:
                feed = feedparser.parse(url)
                
                # Shuffle entries to avoid only picking the latest "Breaking News"
                entries = list(feed.entries)
                random.shuffle(entries)
                
                for entry in entries:
                    if entry.link in url_history: continue
                    if not self._is_recent(entry): continue
                    content = ""
                    if hasattr(entry, 'summary'): content = entry.summary
                    elif hasattr(entry, 'description'): content = entry.description
                    else: content = entry.title
                    
                    # Filter out short/empty content to ensure quality
                    if len(content) < 200: continue

                    posts.append({
                        'category': category,
                        'source': feed.feed.get('title', 'Unknown Source'),
                        'title': entry.title,
                        'content': content[:3000], 
                        'url': entry.link
                    })
                    # Increased limit: Collect up to 5 items per category
                    if len([p for p in posts if p['category'] == category]) >= 5: break
            except Exception as e:
                print(f"Failed to fetch {url}: {e}")
                continue
        print(f"✅ Found {len(posts)} recent candidates.")
        return posts

    async def _select_best_topic(self, candidates: List[Dict]) -> Dict:
        candidates_text = ""
        for i, item in enumerate(candidates):
            candidates_text += f"{i+1}. [{item['category']}] {item['title']}\n"
            
        # Load recent history to avoid repetition
        recent_topics = []
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    history = json.load(f)
                    # Assuming history is list of dicts, take last 5 titles
                    recent_topics = [h.get('title', '') for h in history[-5:]]
        except: pass
        
        recent_context = ""
        if recent_topics:
            recent_context = "**AVOID these recently covered topics (Find something different):**\n" + "\n".join([f"- {t}" for t in recent_topics])

        prompt = f"""
        You are a **Trend Hunter** looking for **'Blue Ocean' content** across various fields.
        
        **Selection Criteria (Balance is Key):**
        1. **Unexpected Insight:** Something counter-intuitive or surprising. ("Did you know?" factor)
        2. **Specific Value:**
           - **Tech/Science:** New mechanism, hidden discovery.
           - **Biz/Finance:** Money-making opportunity, market shift.
           - **Culture/Life:** Psychological hack, hidden trend, emotional resonance.
        3. **Niche over Generic:** Avoid broad headlines like "Market is up" or "New Movie Released". Look for the *specific reason* or *untold story*.
        
        {recent_context}
        
        **Candidates:**
        {candidates_text}
        
        Select the ONE article that is most interesting, regardless of category.
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
        
        # 🚀 Fetch Full Content from URL
        print(f"🕵️ Fetching full article from: {selection['url']}")
        full_content = self._fetch_full_article(selection['url'])
        if full_content:
            print(f"✅ Successfully extracted {len(full_content)} chars.")
            selection['content'] = full_content[:8000] # Limit to avoid context overflow
        else:
            print("⚠️ Failed to extract content. Using summary.")

        self._save_history(selection['title'], selection['url'])

        script = await self._write_script(selection)
        
        try:
            import re
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[^\w\s-]', '', script.title).strip().replace(' ', '_')[:30]
            os.makedirs(self.script_output_dir, exist_ok=True)
            filepath = os.path.join(self.script_output_dir, f"script_{timestamp}_{safe_title}.json")
            with open(filepath, 'w', encoding='utf-8') as f: f.write(script.model_dump_json(indent=2))
        except: pass
        
        return script

    def _fetch_full_article(self, url: str) -> str:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded)
                return text
            return None
        except Exception as e:
            print(f"Error fetching article: {e}")
            return None

    async def _write_script(self, item: Dict) -> ShortsScript:
        print(f"Writing script for: {item['title']} (Mode: {self.generation_mode})")
        
        mood_list_str = ', '.join(self.allowed_moods)
        style = "The Info Curator"
        
        # Dynamic Prompt based on Generation Mode
        if self.generation_mode == "video":
            visual_instruction = f"""
            **Visuals (VIDEO MODE - HIGH QUALITY VEO 3.0 OPTIMIZED):**
            - **OBJECTIVE:** Create **Cinematic Background Visuals** that represent the news concept. 
            - **ROLE:** These videos will be the background for a news report. They should be atmospheric, metaphorical, and visually stunning.
            - **NO TEXT:** Do not generate any text inside the video.
            
            **STRUCTURE:** `[Camera Movement] + [Subject/Object] + [Environment] + [Lighting] + [4k, photorealistic]`
            
            **MANDATORY RULES:**
            1.  **Subject:** Focus on the **Subject Matter** of the news (e.g., Robots, Money, Servers, Nature). Do NOT focus on a generic human presenter (we have an overlay for that).
            2.  **Camera Movement (Use one):** "Slow pan right", "Drone establishing shot", "Tracking shot", "Macro close-up".
            3.  **Lighting (Use one):** "Cinematic lighting", "Cyberpunk neon", "Golden hour", "Volumetric fog", "Studio lighting".
            4.  **Motion:** The scene MUST have movement (e.g., "Clouds moving", "Gears turning", "Lights flashing").
            
            **Example Output:**
            "Drone shot of a futuristic city skyline at night with neon lights reflecting on wet pavement. Cyberpunk atmosphere. 4k resolution, photorealistic, high fidelity."
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
        Create a **comprehensive and engaging** YouTube Shorts script (approx. 55-60s) based on this news.
        
        **SOURCE MATERIAL:**
        Category: {item['category']}
        Title: {item['title']}
        Content: {item['content']}
        
        **INSTRUCTION:**
        - **Language:** **KOREAN ONLY** (For Script, Title, and Description).
        - **Title:** Create a **Viral/Clickbait Korean Title** (Max 40 chars). Do NOT use the English source title directly.
        - **Anti-Cliché Rule:** Do NOT start with "Did you know?" or generic intros. Dive straight into the specific fact or problem.
        - **Depth:** Explain the **Specific Mechanism** or **Hidden Logic** behind the news. Avoid vague statements like "It is good." -> Say "It improves efficiency by 15% using X technology."
        - **Length:** Target roughly **140-160 Korean characters** (approx. 120 spoken words).
        - **TIMING:** The total spoken duration MUST be under **50 seconds**. This is a HARD LIMIT.
        - **Structure:**
          1. **Hook (0-5s):** A surprising fact or counter-intuitive statement.
          2. **The 'Secret' (5-15s):** What is the specific hidden detail/tech?
          3. **Deep Analysis (15-35s):** How does it work? Why is it different?
          4. **Impact (35-50s):** A sharp, non-obvious conclusion.
        - **Scenes:** Generate **6 to 10 scenes** to ensure fast pacing and retention.
        - **Duration:** Each scene should be **5 to 8 seconds** (We will trim the start, so make it longer).
        
        {visual_instruction}
        
        **Mood:** Choose best from [{mood_list_str}].
        
        Output JSON:
        {{
            "title": "호기심을 자극하는 한글 제목 (이모지 포함 가능)",
            "description": "영상 내용에 대한 자세한 한글 설명...",
            "tags": ["category_name", "shorts", "trend"],
            "mood": "upbeat",
            "style": "The Info Curator",
            "source_url": "https://example.com",
            "generation_mode": "{self.generation_mode}",
            "scenes": [
                {{
                    "scene_number": 1,
                    "visual_description": "A futuristic city background with neon lights.",
                    "motion_instruction": "The character talks while looking at the camera, gesturing with hands occasionally. Background lights flicker.",
                    "script_text": "...",
                    "duration_seconds": 5.0
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