import asyncio
import json
import unittest
from unittest.mock import patch
from shorts_maker.planner.content_extractor import ContentExtractor
from shorts_maker.utils.logger import get_logger


class ContentExtractionTests(unittest.TestCase):
    def test_navigation_does_not_make_short_article_pass_body_length_gate(self):
        navigation = ''.join(
            f'<li><a href="/menu/{i}">정책 금융 연구 경제 통계 자주 찾는 메뉴 {i}</a></li>'
            for i in range(40)
        )

        def page(body):
            return (
                '<html><head><title>경제 통계 자료</title></head><body>'
                f'<header><nav><ul>{navigation}</ul></nav></header>'
                f'<main><article><h1>경제 통계 자료</h1><p>{body}</p></article></main>'
                f'<footer>{navigation}</footer></body></html>'
            )

        with patch('shorts_maker.planner.content_extractor.trafilatura.fetch_url',
                   side_effect=[page('주요 내용은 첨부 문서를 참고하세요.'),
                                page('서울의 소비자 물가는 전월보다 안정되었습니다. ' * 25)]):
            short = ContentExtractor().fetch_enhanced_article('https://example.com/short')
            full = ContentExtractor().fetch_enhanced_article('https://example.com/full')

        self.assertLess(short.word_count, 100)
        self.assertNotIn('자주 찾는 메뉴', short.main_text)
        self.assertGreaterEqual(full.word_count, 100)
        self.assertNotIn('자주 찾는 메뉴', full.main_text)

    def test_generic_press_release_heading_uses_specific_page_title(self):
        html = '<html><head><title>서류 1,658개 간소화 | 행정안전부 &gt; 보도자료</title></head><body><h2>보도자료</h2><p>본문</p></body></html>'
        with patch('shorts_maker.planner.content_extractor.trafilatura.fetch_url', return_value=html), patch(
            'shorts_maker.planner.content_extractor.trafilatura.extract',
            return_value=json.dumps({'title': '보도자료', 'text': '확인된 본문입니다.'}),
        ):
            article = ContentExtractor().fetch_enhanced_article('https://example.com/press/1')

        self.assertIsNotNone(article)
        self.assertEqual(article.title, '서류 1,658개 간소화')


async def test_extraction():
    logger = get_logger("test_extractor")
    extractor = ContentExtractor()
    
    # 테스트 URL - 차단이 적은 Arxiv 추상화 페이지 등 사용
    test_url = "https://arxiv.org/abs/2310.11511"
    # 참고: 실제 동작 여부는 인터넷 연결 상태에 따라 다를 수 있음
    
    print(f"\n--- Testing Extraction from: {test_url} ---")
    content = extractor.fetch_enhanced_article(test_url)
    
    if content:
        print(f"Title: {content.title}")
        print(f"Author: {content.author}")
        print(f"Words: {content.word_count}")
        print(f"\n--- Quotes ({len(content.quotes)}) ---")
        for q in content.quotes:
            print(f"- {q[:100]}...")
            
        print(f"\n--- Headings ({len(content.headings)}) ---")
        for h in content.headings:
            print(f"- {h}")
            
        print(f"\n--- Captions ({len(content.captions)}) ---")
        for c in content.captions:
            print(f"- {c}")
            
        print(f"\n--- Links ({len(content.links)}) ---")
        for l in content.links:
            print(f"- {l}")
    else:
        print("Failed to extract content.")

if __name__ == "__main__":
    asyncio.run(test_extraction())
