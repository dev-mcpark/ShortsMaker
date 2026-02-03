"""외부 정보 수집 및 보강 모듈 - Multi-Source Enrichment"""

import os
import json
from openai import AsyncOpenAI
from typing import Optional, List, Dict
import requests
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings


class ContentEnricher:
    """웹 검색을 통해 주제와 관련된 추가 정보를 수집하고 요약하는 클래스"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
            
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        # [TIP] 실제 사용 시 Brave Search API 등의 키를 설정에 추가하는 것을 권장합니다.
        # 현재는 별도의 키가 없을 때를 대비하여 Placeholder로 작동하거나 
        # 제한적인 무료 검색 방식을 시도할 수 있도록 설계했습니다.
        self.search_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "")

    async def enrich_content(self, topic: str, core_message: str, visual_keywords: List[str]) -> List[str]:
        """외부 검색을 통해 관련 정보를 수집하고 요약함
        
        Args:
            topic: 기사 제목 또는 주제
            core_message: 기사의 핵심 메시지
            visual_keywords: 분석된 시각적 키워드
            
        Returns:
            보강된 정보 포인트 리스트 (List[str])
        """
        self.logger.info(f"🌐 Enriching content for topic: {topic}")
        
        # 1. 검색 쿼리 생성
        search_query = await self._generate_search_query(topic, core_message, visual_keywords)
        self.logger.info(f"🔍 Search Query: {search_query}")
        
        # 2. 웹 검색 수행
        search_results = await self._search_web_brave(search_query)
        
        if not search_results:
            self.logger.warning("⚠️ No search results found. Enrichment skipped.")
            return []
            
        # 3. 정보 요약
        enriched_points = await self._summarize_search_results(search_query, search_results)
        
        self.logger.info(f"✅ Enrichment complete: {len(enriched_points)} points added.")
        return enriched_points

    async def _generate_search_query(self, topic: str, core_message: str, keywords: List[str]) -> str:
        """분석된 정보를 바탕으로 보강을 위한 최적의 검색 쿼리 생성"""
        prompt = f"""
        Create a single, highly effective search query to find deep technical details, historical context, or recent data points about this topic.
        
        Topic: {topic}
        Core Message: {core_message}
        Keywords: {', '.join(keywords)}
        
        Just output the search query string. 
        Example: "history of Tesla Autopilot accidents and safety data 2024"
        """
        
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip().strip('"')

    async def _search_web_brave(self, query: str) -> List[Dict]:
        """Brave Search API를 사용한 웹 검색 (API 키 필요)"""
        if not self.search_api_key:
            self.logger.warning("Brave Search API Key missing. Skipping web search.")
            return []
            
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.search_api_key
        }
        
        params = {"q": query, "count": 5}
        
        try:
            # Note: 런타임에 동기 요청을 비동기화하기 위해 run_in_executor 등을 사용하는 것이 좋으나 
            # 여기선 간단히 구현합니다.
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params=params,
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                results = []
                for item in data.get("web", {}).get("results", []):
                    results.append({
                        "title": item.get("title"),
                        "description": item.get("description"),
                        "url": item.get("url")
                    })
                return results
            else:
                self.logger.error(f"Brave Search API failed: {response.status_code}")
                return []
        except Exception as e:
            self.logger.error(f"Error during search: {e}")
            return []

    async def _summarize_search_results(self, query: str, results: List[Dict]) -> List[str]:
        """검색 결과 스니펫을 바탕으로 씬 보강용 포인트 추출"""
        
        results_text = ""
        for i, res in enumerate(results):
            results_text += f"[{i+1}] {res['title']}: {res['description']}\n"
            
        prompt = f"""
        Extract 3-5 high-value insights from these search results about '{query}' to enrich a YouTube Shorts script.
        Focus on:
        - Specific numbers, dates, or data points
        - Historical context or 'Did you know?' type facts
        - Concise explanations of complex terms
        
        Results:
        {results_text}
        
        Output format: JSON List of strings.
        Example: ["Point 1...", "Point 2..."]
        """
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            data = json.loads(response.choices[0].message.content)
            # JSON 구조가 유동적일 수 있으므로 안전하게 추출
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val[:5]
            return []
        except Exception as e:
            self.logger.error(f"Error summarizing search results: {e}")
            return []

import os # Missing import added implicitly in thought
