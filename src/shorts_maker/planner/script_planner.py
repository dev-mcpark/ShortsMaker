import os
import json
import random
import re
import ipaddress
import hashlib
import feedparser
from datetime import datetime, timedelta
import time
from urllib.parse import urlparse
from openai import AsyncOpenAI
from typing import List, Dict, Optional, Tuple
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.planner.script_validator import ScriptValidator
from shorts_maker.utils.source_manager import SourceManager
from shorts_maker.planner.models import VideoScene, ShortsScript, ArticleContent, ContentAnalysis
from shorts_maker.planner.content_extractor import ContentExtractor
from shorts_maker.planner.content_analyzer import ContentAnalyzer
from shorts_maker.planner.content_enricher import ContentEnricher


class RSSCache:
    """RSS 피드 캐싱 클래스 (TTL 기반)"""

    def __init__(self, ttl_minutes: int = 30):
        self._cache: Dict[str, Tuple[List[Dict], datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self.logger = get_logger(__name__)

    def _get_key(self, url: str) -> str:
        """URL을 해시 키로 변환 (SHA256 사용)"""
        return hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str) -> Optional[List[Dict]]:
        """캐시에서 데이터 조회"""
        key = self._get_key(url)
        if key in self._cache:
            data, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
                self.logger.debug(f"캐시 히트: {url[:50]}...")
                return data
            else:
                # 만료된 캐시 삭제
                del self._cache[key]
        return None

    def set(self, url: str, data: List[Dict]):
        """캐시에 데이터 저장"""
        key = self._get_key(url)
        self._cache[key] = (data, datetime.now())
        self.logger.debug(f"캐시 저장: {url[:50]}... ({len(data)}개 항목)")

    def clear(self):
        """캐시 전체 삭제"""
        self._cache.clear()

    def clear_expired(self):
        """만료된 캐시 항목만 삭제"""
        now = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if now - timestamp >= self._ttl
        ]
        for key in expired_keys:
            del self._cache[key]

# VideoScene과 ShortsScript는 models.py로 이동

class ScriptPlanner:
    def __init__(self, generation_mode: str = "image"):
        self.logger = get_logger(__name__)

        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                "Please set it in .env file or config/.env"
            )

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
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
        
        # Validator
        self.validator = ScriptValidator()

        # RSS Cache (30분 TTL)
        self.rss_cache = RSSCache(ttl_minutes=30)

        # Load RSS Sources from JSON config
        self.source_manager = SourceManager()
        self.rss_sources = self.source_manager.load_sources()
        
        # ContentExtractor for enhanced article extraction
        self.content_extractor = ContentExtractor()

        # ContentAnalyzer for deep semantic analysis
        self.content_analyzer = ContentAnalyzer()
        
        # ContentEnricher for multi-source supplementary information
        self.content_enricher = ContentEnricher()

    def _validate_url(self, url: str) -> bool:
        """
        URL 유효성 검증 (SSRF 방지)

        Args:
            url: 검증할 URL

        Returns:
            bool: URL이 안전하면 True, 아니면 False
        """
        try:
            parsed = urlparse(url)

            # 허용된 스킴만 허용
            if parsed.scheme not in ('http', 'https'):
                self.logger.warning(f"허용되지 않은 URL 스킴: {parsed.scheme}")
                return False

            # 호스트명이 없으면 거부
            if not parsed.hostname:
                self.logger.warning("호스트명이 없는 URL")
                return False

            # 내부 호스트 차단
            hostname = parsed.hostname.lower()
            blocked_hosts = ('localhost', '127.0.0.1', '0.0.0.0', '::1')
            if hostname in blocked_hosts:
                self.logger.warning(f"내부 호스트 URL 차단: {hostname}")
                return False

            # 프라이빗 IP 대역 차단
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_reserved:
                    self.logger.warning(f"프라이빗 IP URL 차단: {hostname}")
                    return False
            except ValueError:
                # IP 주소가 아닌 경우 (도메인명) - 통과
                pass

            return True

        except Exception as e:
            self.logger.error(f"URL 검증 오류: {e}")
            return False

    def _load_url_history(self) -> List[str]:
        if os.path.exists(self.url_history_file):
            try:
                with open(self.url_history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"URL 히스토리 로드 실패: {e}")
                return []
        return []

    def _save_history(self, title: str, url: str):
        # Save URL history (simple list for dedup)
        url_history = self._load_url_history()
        url_history.append(url)
        try:
            with open(self.url_history_file, 'w', encoding='utf-8') as f:
                json.dump(url_history[-100:], f, indent=2, ensure_ascii=False)
        except IOError as e:
            self.logger.warning(f"URL 히스토리 저장 실패: {e}")

        # Save Topic history (detailed for variety check)
        topic_history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    topic_history = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"토픽 히스토리 로드 실패: {e}")

        topic_history.append({
            "title": title,
            "url": url,
            "date": datetime.now().isoformat()
        })
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(topic_history[-20:], f, indent=2, ensure_ascii=False)
        except IOError as e:
            self.logger.warning(f"토픽 히스토리 저장 실패: {e}")

    def _is_recent(self, entry) -> bool:
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                return (datetime.now() - published_dt).days <= 14
            return True
        except (TypeError, ValueError, OverflowError) as e:
            self.logger.debug(f"날짜 파싱 오류 (기본값 사용): {e}")
            return True

    def _fetch_rss_feeds(self, use_cache: bool = True) -> List[Dict]:
        """
        RSS 피드에서 후보 기사 수집

        Args:
            use_cache: True면 캐시 사용 (기본값)
        """
        posts = []
        url_history = self._load_url_history()
        cache_hits = 0
        cache_misses = 0

        # Use ALL available sources to maximize candidate pool
        selected_sources = []
        for category, urls in self.rss_sources.items():
            for url in urls:
                selected_sources.append((category, url))

        # Shuffle to mix categories during fetch
        random.shuffle(selected_sources)

        self.logger.info(f"📡 Fetching feeds from {len(selected_sources)} sources...")
        for category, url in selected_sources:
            try:
                # 캐시 확인
                cached_entries = self.rss_cache.get(url) if use_cache else None

                if cached_entries is not None:
                    cache_hits += 1
                    feed_entries = cached_entries
                    source_name = "Cached Source"
                else:
                    cache_misses += 1
                    feed = feedparser.parse(url)
                    feed_entries = [
                        {
                            'title': e.title,
                            'link': e.link,
                            'summary': getattr(e, 'summary', ''),
                            'description': getattr(e, 'description', ''),
                            'published_parsed': getattr(e, 'published_parsed', None)
                        }
                        for e in feed.entries
                    ]
                    source_name = feed.feed.get('title', 'Unknown Source')

                    # 캐시에 저장
                    if use_cache:
                        self.rss_cache.set(url, feed_entries)

                # Shuffle entries to avoid only picking the latest "Breaking News"
                random.shuffle(feed_entries)

                for entry in feed_entries:
                    if entry['link'] in url_history:
                        continue

                    # _is_recent 호환을 위한 간단한 객체 생성
                    class SimpleEntry:
                        def __init__(self, data):
                            self.published_parsed = data.get('published_parsed')

                    if not self._is_recent(SimpleEntry(entry)):
                        continue

                    content = entry.get('summary') or entry.get('description') or entry.get('title', '')

                    # Filter out short/empty content to ensure quality
                    if len(content) < 200:
                        continue

                    posts.append({
                        'category': category,
                        'source': source_name,
                        'title': entry['title'],
                        'content': content[:3000],
                        'url': entry['link']
                    })
                    # Increased limit: Collect up to 5 items per category
                    if len([p for p in posts if p['category'] == category]) >= 5:
                        break

            except Exception as e:
                self.logger.warning(f"Failed to fetch {url}: {e}")
                continue

        self.logger.info(f"✅ Found {len(posts)} recent candidates (캐시: {cache_hits}히트/{cache_misses}미스)")
        return posts

    async def _select_best_topic(self, candidates: List[Dict]) -> Dict:
        candidates_text = ""
        for i, item in enumerate(candidates):
            candidates_text += f"{i+1}. [{item['category']}] {item['title']}\n"
            
        # Load recent history to avoid repetition
        recent_topics = []
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    # Assuming history is list of dicts, take last 5 titles
                    recent_topics = [h.get('title', '') for h in history[-5:]]
        except (json.JSONDecodeError, IOError) as e:
            self.logger.debug(f"최근 토픽 로드 실패: {e}")
        
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
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10
            )
            match = re.search(r'\d+', response.choices[0].message.content)
            idx = int(match.group()) - 1 if match else 0
            return candidates[idx] if 0 <= idx < len(candidates) else candidates[0]
        except Exception as e:
            self.logger.warning(f"토픽 선택 실패, 랜덤 선택: {e}")
            return random.choice(candidates)

    async def plan_content(self, topic: str = None, direct_url: str = None) -> ShortsScript:
        # [Mode 1: Direct URL]
        if direct_url:
            # URL 검증 (SSRF 방지)
            if not self._validate_url(direct_url):
                error_msg = "유효하지 않거나 허용되지 않은 URL입니다. http/https URL만 허용됩니다."
                self.logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)

            self.logger.info(f"🔗 Planning content from Direct URL: {direct_url}")
            article_content = self.content_extractor.fetch_enhanced_article(direct_url)
            
            if not article_content or article_content.word_count < 100:
                error_msg = "추출된 본문 내용이 너무 적거나 URL에서 내용을 가져올 수 없습니다. 다른 URL을 시도해주세요."
                self.logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            # 2. Analyze Content Depth [PHASE 2]
            self.logger.info("🔍 Analyzing content depth...")
            analysis = await self.content_analyzer.analyze_content(article_content)
            
            if not analysis:
                self.logger.warning("⚠️ Deep analysis failed. Falling back to basic content.")
            
            # 3. Enrich Content [PHASE 3]
            enriched_info = []
            if analysis:
                self.logger.info("🌐 Searching for supplementary info...")
                enriched_info = await self.content_enricher.enrich_content(
                    topic=article_content.title,
                    core_message=analysis.core_message,
                    visual_keywords=analysis.visual_keywords
                )
            
            # Create a synthetic candidate item with enhanced info & analysis & enrichment
            selection = {
                'category': 'Custom',
                'source': 'Direct URL',
                'title': topic if topic else article_content.title, 
                'content': article_content.main_text[:8000],
                'url': direct_url,
                'quotes': article_content.quotes,
                'headings': article_content.headings,
                'captions': article_content.captions,
                'analysis': analysis,
                'enriched_info': enriched_info  # [NEW] 외부 보강 정보 포함
            }
            # Skip loop for direct URL (Single attempt, or could loop if we want re-generation)
            script = await self._write_script(selection)
            return await self._validate_and_save(script, selection)

        # [Mode 2: RSS Discovery]
        candidates = self._fetch_rss_feeds()
        if not candidates:
            candidates = [{'category': 'General', 'source': 'Fallback', 'title': 'AI Future', 'content': 'AI impact.', 'url': 'google.com'}]

        max_topic_retries = 5
        script = None

        for attempt in range(max_topic_retries):
            if not candidates:
                self.logger.warning("No more candidates available for selection.")
                break

            # 1. Select Topic
            # If a manual topic is provided in RSS mode, filter candidates or use it as a keyword?
            # For now, let's keep the trend hunter logic but maybe prioritize the topic if feasible.
            # (Simple version: Trend hunter just runs as is)
            selection = await self._select_best_topic(candidates)
            self.logger.info(f"🔥 Selected Topic (Attempt {attempt+1}): {selection['title']} ({selection['category']})")
            
            # 2. Fetch Full Content
            self.logger.info(f"🕵️ Fetching enhanced article from: {selection['url']}")
            article_content = self.content_extractor.fetch_enhanced_article(selection['url'])
            if article_content:
                self.logger.info(f"✅ Successfully extracted {article_content.word_count} words.")
                
                # 심층 분석 수행 [PHASE 2]
                self.logger.info("🔍 Analyzing content depth...")
                analysis = await self.content_analyzer.analyze_content(article_content)
                
                # 콘텐츠 보강 수행 [PHASE 3]
                enriched_info = []
                if analysis:
                    self.logger.info("🌐 Searching for supplementary info...")
                    enriched_info = await self.content_enricher.enrich_content(
                        topic=article_content.title,
                        core_message=analysis.core_message,
                        visual_keywords=analysis.visual_keywords
                    )
                
                selection['content'] = article_content.main_text[:8000]
                selection['quotes'] = article_content.quotes
                selection['headings'] = article_content.headings
                selection['captions'] = article_content.captions
                selection['analysis'] = analysis
                selection['enriched_info'] = enriched_info  # [NEW] 외부 보강 정보 포함
            else:
                self.logger.warning("⚠️ Failed to extract enhanced content. Using summary.")
                selection['analysis'] = None

            self._save_history(selection['title'], selection['url'])

            # 3. Write & Validate
            script = await self._write_script(selection)
            final_script = await self._validate_and_save(script, selection)
            
            if final_script:
                return final_script
            
            # If validation failed (returned None), remove candidate and retry
            self.logger.info("🔄 Discarding this topic and selecting a NEW one...")
            candidates = [c for c in candidates if c['url'] != selection['url']]

        if not script:
            self.logger.error("Failed to generate a valid script after retries.")
            return None
        return script

    async def _validate_and_save(self, script: ShortsScript, selection: Dict) -> Optional[ShortsScript]:
        """Helper to validate script and save to disk if valid."""
        # Validate
        validation = await self.validator.validate_script(script)
        
        # Simple Retry Loop for the SAME topic if validation fails (Optional optimization)
        # For now, if invalid, we return None to trigger topic switch in RSS mode.
        # In Direct URL mode, we might want to retry generation on the same URL?
        # Let's keep it simple: Single validation check.
        
        if not validation.is_valid:
            self.logger.warning(f"❌ Script rejected. Reason: {validation.reason}")
            self.logger.info(f"Validation Feedback: {validation.feedback}")
            return None

        self.logger.info(f"🎉 Script Validated!")
        
        # Save to file
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[^\w\s-]', '', script.title).strip().replace(' ', '_')[:30]
            os.makedirs(self.script_output_dir, exist_ok=True)
            filepath = os.path.join(self.script_output_dir, f"script_{timestamp}_{safe_title}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(script.model_dump_json(indent=2))
            self.logger.info(f"📄 스크립트 저장됨: {filepath}")
        except IOError as e:
            self.logger.warning(f"스크립트 저장 실패: {e}")
        
        return script

    async def _write_script(self, item: Dict, feedback: Optional[str] = None) -> ShortsScript:
        self.logger.info(f"Writing script for: {item['title']} (Mode: {self.generation_mode})")
        if feedback:
            self.logger.info(f"♻️ Rewriting based on feedback: {feedback}")
        
        mood_list_str = ', '.join(self.allowed_moods)
        style = "The Info Curator"
        
        # Enhanced information 및 Deep Analysis를 프롬프트에 포함
        enhanced_context = ""
        analysis = item.get('analysis')
        
        if analysis:
            # Phase 2: Deep Analysis 결과 활용
            enhanced_context += f"""
            ### DEEP ANALYSIS & STORY MATERIAL (PRIORITY):
            - **Core Message:** {analysis.core_message}
            - **Powerful Hook:** {analysis.hook}
            - **Secret Mechanism (The 'How'):** {analysis.secret_mechanism}
            - **Background Context:** {analysis.context_background}
            - **Key Data Points:** {', '.join(analysis.numbers_data)}
            - **Expert Perspective:** {', '.join(analysis.expert_insights)}
            - **Future Outlook:** {analysis.future_impact}
            
            ### SUGGESTED STORY STRUCTURE:
            1. **Opening:** {analysis.story_structure.get('opening')}
            2. **Mystery:** {analysis.story_structure.get('mystery')}
            3. **Secret:** {analysis.story_structure.get('secret')}
            4. **Impact:** {analysis.story_structure.get('impact')}
            
            ### VISUAL THEMES: {', '.join(analysis.visual_keywords)}
            """
            
            # Phase 3: Enriched Info 추가
            enriched_info = item.get('enriched_info')
            if enriched_info:
                enhanced_context += "\n### SUPPLEMENTARY INFORMATION (FROM WEB SEARCH):\n"
                for point in enriched_info:
                    enhanced_context += f"- {point}\n"
                enhanced_context += "\n*Integrate these facts seamlessly into the script to improve depth.*\n"
        else:
            # Fallback: Phase 1 정보만 활용
            if item.get('quotes'):
                enhanced_context += f"\n**Important Quotes:**\n"
                for q in item['quotes'][:3]:
                    enhanced_context += f"- \"{q}\"\n"
            
            if item.get('headings'):
                enhanced_context += f"\n**Article Structure:**\n"
                for h in item['headings'][:5]:
                    enhanced_context += h + "\n"
            
            if item.get('captions'):
                enhanced_context += f"\n**Visual Context:**\n"
                for c in item['captions'][:3]:
                    enhanced_context += c + "\n"

        # Dynamic Prompt based on Generation Mode
        if self.generation_mode == "video":
            visual_instruction = f"""
            **Visuals (VIDEO MODE - BACKGROUND-FOCUSED NEWS BROADCAST STYLE):**

            **CRITICAL COMPOSITION RULE:**
            - The visual_description creates a LARGE BACKGROUND SCENE that occupies 80-85% of the 9:16 frame
            - A small news presenter appears in the bottom-right corner (15-20% of frame) in a rounded window
            - The BACKGROUND SCENE is the MAIN FOCUS and PRIMARY SUBJECT of the description
            - Think of this as a professional news broadcast with a corner presenter overlay

            **VISUAL DESCRIPTION STRUCTURE:**
            `[Camera Movement] + [Main Subject/Scene] + [Detailed Environment] + [Atmospheric Elements] + [Lighting Style] + [Technical Quality]`

            **MANDATORY COMPONENTS:**

            1. **Camera Movement (REQUIRED - Choose ONE):**
               - "Slow drone shot descending from above"
               - "Smooth tracking shot moving forward"
               - "Gentle pan across the scene from left to right"
               - "Gradual zoom in revealing details"
               - "Orbital camera rotating around the subject"
               - "Steady cinematic push-in shot"

            2. **Main Subject/Scene (REQUIRED - BE SPECIFIC):**
               - NOT generic: ❌ "A city"
               - SPECIFIC: ✅ "A towering futuristic metropolis with holographic billboards and flying vehicles"
               - Focus on CONCRETE OBJECTS: Buildings, Nature, Technology, Vehicles, Architecture, etc.
               - Describe SCALE: "Massive", "Towering", "Sprawling", "Intimate", "Vast"

            3. **Detailed Environment (REQUIRED - 2-3 ELEMENTS):**
               - Background layers: "Distant mountains with snow-capped peaks"
               - Mid-ground: "Rows of glass skyscrapers reflecting sunset"
               - Foreground: "Busy street with neon signs and steam vents"
               - Weather/Atmosphere: "Light fog rolling through", "Rain-slicked surfaces"

            4. **Atmospheric Elements (REQUIRED - 1-2 EFFECTS):**
               - "Particles of dust floating in volumetric light beams"
               - "Gentle falling cherry blossoms"
               - "Steam rising from subway grates"
               - "Lens flare from the setting sun"
               - "Ambient mist creating depth"
               - "Subtle motion blur on moving elements"

            5. **Lighting Style (REQUIRED - BE DESCRIPTIVE):**
               - NOT: ❌ "Good lighting"
               - SPECIFIC: ✅ "Warm golden hour sunlight casting long shadows, with cool blue ambient fill from the sky"
               - Options: "Cyberpunk neon (magenta/cyan)", "Soft diffused overcast", "Dramatic rim lighting", "Volumetric god rays"

            6. **Technical Quality (REQUIRED):**
               - ALWAYS include: "Professional broadcast quality, 4k resolution, cinematic color grading, photorealistic rendering"

            **EXAMPLE OUTPUTS (STUDY THESE):**

            Example 1 (Tech News):
            "Smooth tracking shot moving through a massive data center with rows of server racks extending into the distance. Blue LED indicator lights flicker across thousands of machines. Cooling mist rises from floor vents creating atmospheric depth. Holographic data streams float in the air. Cool cyan and white lighting with subtle lens flares. Professional broadcast quality, 4k resolution, cinematic color grading, photorealistic rendering."

            Example 2 (Nature News):
            "Gentle drone shot descending over a pristine mountain valley covered in dense pine forest. Morning mist flows through the valleys like a river. Golden hour sunlight breaks through gaps in the forest canopy creating dramatic god rays. A crystal-clear lake reflects the surrounding peaks in the distance. Warm amber and deep green color palette. Professional broadcast quality, 4k resolution, cinematic color grading, photorealistic rendering."

            Example 3 (Business News):
            "Slow pan across a modern corporate headquarters lobby with floor-to-ceiling glass walls. Sleek marble floors reflect the ambient lighting. Business professionals move in subtle motion blur in the background. Large LED stock ticker displays line the walls showing market data. Cool blue and warm amber accent lighting creating depth. Professional broadcast quality, 4k resolution, cinematic color grading, photorealistic rendering."

            **AVOID:**
            - Generic descriptions: ❌ "A nice city"
            - Person-focused: ❌ "A person talking about technology" (presenter is separate)
            - Static/boring: ❌ "A room with computers"
            - Text/UI elements: ❌ "With Korean subtitles" (added separately)

            **LENGTH:** Each visual_description should be 150-250 characters for optimal detail without excess.

            ---

            **MOTION INSTRUCTION (For Veo Animation):**

            The motion_instruction describes HOW the background scene animates. Focus on BACKGROUND MOTION, not presenter motion.

            **STRUCTURE:** `[Camera Movement] + [Background Elements Animation] + [Atmospheric Effects]`

            **COMPONENTS:**

            1. **Camera Movement:**
               - "Camera slowly tracks forward"
               - "Drone descends smoothly"
               - "Gentle pan from left to right"
               - "Gradual zoom revealing details"

            2. **Background Elements:**
               - "Clouds drift across the sky"
               - "LED lights flicker and pulse rhythmically"
               - "Water ripples gently"
               - "Leaves sway in the breeze"
               - "Traffic moves in the distance"
               - "Holographic displays animate with data"

            3. **Atmospheric Effects:**
               - "Mist swirls around objects"
               - "Dust particles float in light beams"
               - "Steam rises gently"
               - "Lens flares shift subtly"

            **EXAMPLES:**
            - "Camera pushes forward through the corridor. LED indicators pulse. Cooling mist rises and swirls around equipment."
            - "Drone descends revealing the landscape. Wind ripples through grass fields. Clouds cast moving shadows."
            - "Slow pan across the cityscape. Neon signs flicker. Steam vents release periodic bursts. Traffic flows in the distance."

            **IMPORTANT:** Motion should be SUBTLE and CINEMATIC, not chaotic. The presenter in the corner has separate minimal motion.
            """
        else: # image mode
            visual_instruction = """
            **Visuals (IMAGE MODE):**
            - Describe **STATIC DETAILS, LIGHTING, and COMPOSITION**.
            - Use terms like: "8k resolution", "Photorealistic", "Dramatic lighting", "Detailed texture", "Macro shot".
            - NO verbs implying complex motion (e.g., "explode" is bad for static, "explosion frozen in time" is good).
            """

        feedback_instruction = ""
        if feedback:
            feedback_instruction = f"""
            **⚠️ CRITICAL CORRECTION REQUIRED:**
            The previous script was rejected by the editor. You MUST fix the following issues:
            "{feedback}"
            """

        prompt = f"""
        Act as a professional **Content Creator**.
        Create a **comprehensive and engaging** YouTube Shorts script (approx. 55-60s) based on this news.
        
        {feedback_instruction}

        **SOURCE MATERIAL:**
        Category: {item['category']}
        Title: {item['title']}
        Content: {item['content']}
        
        {enhanced_context}
        
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
            "source_name": "Source Name",
            "source_url": "https://example.com",
            "generation_mode": "{self.generation_mode}",
            "scenes": [
                {{
                    "scene_number": 1,
                    "visual_description": "Smooth tracking shot moving through a massive server room with towering racks of blinking equipment extending into the distance. Cool blue LED lights pulse rhythmically across thousands of machines. Transparent holographic displays float showing data streams. Cooling mist rises from floor vents creating atmospheric depth and volumetric lighting effects. Cyberpunk aesthetic with cyan and magenta accent lighting. Professional broadcast quality, 4k resolution, cinematic color grading.",
                    "motion_instruction": "Camera slowly pushes forward through the server corridor. LED lights flicker and pulse. Holographic displays animate with flowing data. Mist swirls gently around the equipment.",
                    "script_text": "요즘 AI 데이터센터가 엄청난 전기를 소비하고 있다는 사실, 알고 계셨나요?",
                    "duration_seconds": 6.0
                }},
                {{
                    "scene_number": 2,
                    "visual_description": "Aerial drone shot descending over a vast solar panel farm stretching to the horizon under golden hour sunlight. Thousands of panels glisten with reflections creating a sea of geometric patterns. Gentle wind causes subtle ripples across the installation. Distant mountains frame the background. Warm amber and orange tones dominate the color palette. Professional broadcast quality, 4k resolution, cinematic color grading.",
                    "motion_instruction": "Drone descends smoothly revealing the scale of the solar farm. Panels subtly shift tracking the sun. Camera rotates slightly showing the mountain backdrop.",
                    "script_text": "하지만 동시에 재생에너지 투자도 역대 최고치를 기록했습니다.",
                    "duration_seconds": 6.0
                }}
            ]
        }}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            if data.get('mood') not in self.allowed_moods: data['mood'] = 'upbeat'
            # Ensure generation_mode is consistent
            data['generation_mode'] = self.generation_mode
            # Inject source info from the item to ensure accuracy
            data['source_name'] = item.get('source', 'Unknown Source')
            data['source_url'] = item.get('url', '')
            return ShortsScript(**data)
        except Exception as e: raise e