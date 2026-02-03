"""콘텐츠 심층 분석 모듈 - Deep Content Analysis"""

import json
from openai import AsyncOpenAI
from typing import Optional, Dict, List
from shorts_maker.utils.logger import get_logger
from shorts_maker.utils.config import settings
from shorts_maker.planner.models import ArticleContent, ContentAnalysis


class ContentAnalyzer:
    """추출된 기사 콘텐츠를 LLM을 통해 심층 분석하는 클래스"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
        # API 키 검증
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
            
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o"  # 분석을 위해 강력한 모델 사용

    async def analyze_content(self, content: ArticleContent) -> Optional[ContentAnalysis]:
        """기사 내용을 바탕으로 심층 분석 수행
        
        Args:
            content: 추출된 ArticleContent 객체
            
        Returns:
            ContentAnalysis 객체 또는 실패 시 None
        """
        self.logger.info(f"🔍 Analyzing content depth for: {content.title}")
        
        prompt = f"""
        You are an expert content analyst and viral storyteller for YouTube Shorts.
        Analyze the following article and extract key materials to create a compelling 60-second video script.
        
        **Article Title:** {content.title}
        **Main Content (Snipped):** {content.main_text[:5000]}
        **Key Quotes:** {content.quotes}
        **Sub-headings:** {content.headings}
        **Visual Context (Captions):** {content.captions}
        
        **Your Task:**
        1. Identify the single most important **Core Message**.
        2. Create a powerful **Hook** that makes viewers stop scrolling.
        3. Explain the **Secret Mechanism** (How or Why) behind the news in detail.
        4. Provide necessary **Context/Background**.
        5. Extract specific **Numbers or Data points**.
        6. Highlight **Expert Insights**.
        7. Predict the **Future Impact**.
        8. Suggest **Visual Keywords** for AI video generation.
        9. Organize the content into a 4-step **Story Structure** (Opening, Mystery, Secret, Impact).
        
        Output MUST be in JSON format.
        
        JSON Structure:
        {{
            "core_message": "string",
            "hook": "string",
            "secret_mechanism": "string",
            "context_background": "string",
            "numbers_data": ["string", ...],
            "expert_insights": ["string", ...],
            "future_impact": "string",
            "visual_keywords": ["string", ...],
            "story_structure": {{
                "opening": "3-5s Hook point",
                "mystery": "Intriguing problem/mystery",
                "secret": "Detailed explanation of mechanism (20-30s)",
                "impact": "Powerful conclusion/moral"
            }}
        }}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            
            analysis_data = json.loads(response.choices[0].message.content)
            analysis = ContentAnalysis(**analysis_data)
            
            self.logger.info("✅ Content analysis complete.")
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error during content analysis: {e}")
            return None
