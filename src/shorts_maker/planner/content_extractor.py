"""콘텐츠 추출 전담 모듈 - Enhanced Content Extraction"""

import json
import trafilatura
from bs4 import BeautifulSoup
from typing import Optional, List
from shorts_maker.utils.logger import get_logger
from shorts_maker.planner.models import ArticleContent


class ContentExtractor:
    """웹 기사에서 풍부한 정보를 추출하는 클래스
    
    trafilatura와 BeautifulSoup을 조합하여:
    - 본문 텍스트
    - 인용문 (전문가 의견)
    - 이미지 캡션 (비주얼 힌트)
    - 서브헤딩 (구조)
    - 관련 링크
    를 추출합니다.
    """
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.timeout = 10  # HTTP 요청 타임아웃
    
    def fetch_enhanced_article(self, url: str) -> Optional[ArticleContent]:
        """향상된 기사 추출 - 더 많은 정보 수집
        
        Args:
            url: 추출할 웹 페이지 URL
            
        Returns:
            ArticleContent 객체 또는 실패 시 None
        """
        try:
            # 1. Download HTML
            self.logger.info(f"📥 Downloading article from: {url}")
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                self.logger.warning(f"Failed to download URL: {url}")
                return None
            
            # 2. Extract with trafilatura (enhanced options)
            text = trafilatura.extract(
                downloaded,
                include_comments=False,  # 댓글은 제외
                include_tables=True,  # 표 포함
                include_links=False,  # 링크는 별도로 추출
                with_metadata=True,  # 메타데이터 포함
                output_format='json',  # JSON 포맷으로 더 많은 정보
                favor_recall=True  # 정밀도보다 재현율 우선 (더 많은 콘텐츠)
            )
            
            if not text:
                self.logger.warning(f"No text extracted from: {url}")
                return None
            
            trafilatura_data = json.loads(text)
            
            # 3. BeautifulSoup으로 trafilatura가 놓친 정보 수집
            soup = BeautifulSoup(downloaded, 'html.parser')
            
            # 이미지 캡션 추출
            captions = self._extract_captions(soup)
            
            # 인용문 추출
            quotes = self._extract_quotes(soup)
            
            # 서브헤딩 추출
            headings = self._extract_headings(soup)
            
            # 관련 링크 추출
            links = self._extract_links(soup)
            
            # 4. ArticleContent 객체 생성
            main_text = trafilatura_data.get('text', '')
            word_count = len(main_text.split())
            
            content = ArticleContent(
                url=url,
                title=trafilatura_data.get('title', ''),
                main_text=main_text,
                author=trafilatura_data.get('author'),
                published_date=trafilatura_data.get('date'),
                captions=captions,
                quotes=quotes,
                headings=headings,
                links=links,
                word_count=word_count,
                estimated_read_time_seconds=int(word_count * 0.5)  # ~120 wpm
            )
            
            self.logger.info(
                f"✅ Enhanced extraction complete: {word_count} words, "
                f"{len(quotes)} quotes, {len(captions)} captions, "
                f"{len(headings)} headings"
            )
            
            return content
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing error: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error extracting article from {url}: {e}")
            return None
    
    def _extract_captions(self, soup: BeautifulSoup) -> List[str]:
        """이미지 캡션 추출
        
        <figcaption> 태그와 <img alt="..."> 속성에서 추출
        """
        captions = []
        
        # <figcaption> 태그
        for fig in soup.find_all('figcaption'):
            caption_text = fig.get_text(strip=True)
            if caption_text and len(caption_text) > 10:  # 너무 짧은 건 제외
                captions.append(caption_text)
        
        # <img alt="..."> 속성
        for img in soup.find_all('img'):
            alt_text = img.get('alt', '').strip()
            if alt_text and len(alt_text) > 10:
                captions.append(f"Image: {alt_text}")
        
        # 중복 제거 및 최대 10개
        unique_captions = list(dict.fromkeys(captions))  # 순서 유지하며 중복 제거
        return unique_captions[:10]
    
    def _extract_quotes(self, soup: BeautifulSoup) -> List[str]:
        """인용문 추출
        
        <blockquote>와 <q> 태그에서 추출
        전문가 의견이나 중요한 발언이 포함됨
        """
        quotes = []
        
        for quote_tag in soup.find_all(['blockquote', 'q']):
            quote_text = quote_tag.get_text(strip=True)
            # 의미 있는 길이의 인용문만
            if quote_text and 20 < len(quote_text) < 500:
                quotes.append(quote_text)
        
        return quotes[:5]  # 최대 5개
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[str]:
        """서브헤딩 추출
        
        기사의 구조를 파악하는 데 유용
        """
        headings = []
        
        for h_tag in soup.find_all(['h2', 'h3', 'h4']):
            heading_text = h_tag.get_text(strip=True)
            if heading_text and len(heading_text) > 5:
                headings.append(heading_text)
        
        return headings[:10]  # 최대 10개
    
    def _extract_links(self, soup: BeautifulSoup) -> List[str]:
        """본문 내 관련 링크 추출
        
        추가 정보를 찾는 데 활용 가능 (Phase 3용)
        """
        links = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # 외부 링크만 수집 (상대 경로 제외)
            if href.startswith('http'):
                links.append(href)
        
        # 중복 제거 및 최대 5개
        unique_links = list(set(links))
        return unique_links[:5]
