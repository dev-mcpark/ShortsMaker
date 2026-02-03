"""Pydantic models for script planning"""

from pydantic import BaseModel
from typing import List, Optional, Dict


class VideoScene(BaseModel):
    """개별 비디오 씬 정보"""
    scene_number: int
    visual_description: str
    motion_instruction: str = ""  # Optional: Veo 모드에서만 사용 (image 모드에서는 빈 문자열)
    script_text: str
    duration_seconds: float = 5.0


class ShortsScript(BaseModel):
    """완성된 쇼츠 스크립트"""
    title: str
    description: str
    tags: List[str]
    mood: str
    style: str
    source_name: str
    source_url: str
    generation_mode: str  # 'image' or 'video'
    scenes: List[VideoScene]


class ArticleContent(BaseModel):
    """추출된 기사 콘텐츠 (Enhanced)"""
    url: str
    title: str
    main_text: str
    author: Optional[str] = None
    published_date: Optional[str] = None
    
    # Enhanced fields - 추가 정보
    captions: List[str] = []  # 이미지 캡션
    quotes: List[str] = []  # 인용문
    headings: List[str] = []  # 서브헤딩
    links: List[str] = []  # 관련 링크
    
    # 메타 정보
    word_count: int = 0
    estimated_read_time_seconds: int = 0


class ContentAnalysis(BaseModel):
    """LLM 기반 콘텐츠 심층 분석 결과"""
    core_message: str          # 핵심 메시지 (1-2문장)
    hook: str                  # 시청자를 멈추게 할 강력한 후크
    secret_mechanism: str      # 사람들이 잘 모르는 '어떻게?' 또는 '왜?'
    context_background: str    # 이해를 돕기 위한 배경 지식
    numbers_data: List[str] = []    # 신뢰도를 높여주는 구체적인 수치/데이터
    expert_insights: List[str] = [] # 전문가의 견해나 인용구 강조점
    future_impact: str         # 미래에 미칠 영향이나 결론
    visual_keywords: List[str] = [] # 시각적 묘사를 위한 키워드 (오브젝트, 환경 등)
    
    # 쇼츠 기획을 위한 세부 구성 (필수 4단계)
    story_structure: Dict[str, str] = {
        "opening": "",
        "mystery": "",
        "secret": "",
        "impact": ""
    }
