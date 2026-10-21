import json
import os
import ipaddress
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List
from shorts_maker.utils.config import settings

DEFAULT_SOURCES = {
    "Tech_IT": [
        "https://news.hada.io/rss/news",
        "https://seoulz.com/feed/",
        "https://kedglobal.com/newsRss",
        "http://www.theverge.com/rss/full.xml",
        "https://techcrunch.com/feed/",
        "https://feeds.feedburner.com/TechCrunch/",
        "http://news.mit.edu/rss/feed"
    ],
    "Business": [
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://www.economist.com/business/rss.xml",
        "http://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.investing.com/rss/news.rss",
        "https://businesskorea.co.kr/rss/allEnglish.xml"
    ],
    "Finance_Economy": [
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "https://rss.hankyung.com/feed/market.xml",
        "https://mediahub.seoul.go.kr/news/rss/04"
    ],
    "City_Life": [
        "https://mediahub.seoul.go.kr/news/rss/03",
        "https://mediahub.seoul.go.kr/news/rss/01"
    ],
    "Life_Tips": [
        "https://lifehacker.com/rss",
        "https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012"
    ],
    "Design_Culture": [
        "https://www.designboom.com/feed/",
        "https://hypebeast.kr/feed"
    ]
}

class SourceManager:
    @staticmethod
    def is_allowed_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or '').lower().rstrip('.')
            if parsed.scheme not in {'http', 'https'} or not host or parsed.username or parsed.password:
                return False
            if host == 'localhost' or host.endswith('.localhost'):
                return False
            try:
                return ipaddress.ip_address(host).is_global
            except ValueError:
                return True
        except (TypeError, ValueError):
            return False

    def __init__(self):
        self.filepath = settings.rss_sources_file
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.filepath):
            self.save_sources(DEFAULT_SOURCES)

    def load_sources(self) -> Dict[str, List[str]]:
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                sources = json.load(f)
        except FileNotFoundError:
            return {category: urls.copy() for category, urls in DEFAULT_SOURCES.items()}
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"RSS 소스 파일을 읽을 수 없습니다: {self.filepath}") from e
        if not isinstance(sources, dict) or any(
            not isinstance(category, str) or not isinstance(urls, list)
            or not all(isinstance(url, str) for url in urls)
            for category, urls in sources.items()
        ):
            raise ValueError(f"RSS 소스 파일 형식이 잘못되었습니다: {self.filepath}")
        return sources

    def save_sources(self, sources: Dict[str, List[str]]):
        path = Path(self.filepath)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent,
                prefix=f'.{path.name}.', delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(sources, file, indent=4, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def add_source(self, category: str, url: str):
        if not self.is_allowed_url(url):
            raise ValueError("RSS 주소는 공개된 http 또는 https URL이어야 합니다.")
        sources = self.load_sources()
        if category not in sources:
            sources[category] = []
        if url not in sources[category]:
            sources[category].append(url)
            self.save_sources(sources)

    def remove_category(self, category: str):
        sources = self.load_sources()
        if category in sources:
            del sources[category]
            self.save_sources(sources)

    def remove_source(self, category: str, url: str):
        sources = self.load_sources()
        if category in sources and url in sources[category]:
            sources[category].remove(url)
            if not sources[category]:  # 카테고리가 비면 삭제
                del sources[category]
            self.save_sources(sources)

    def get_categories(self) -> List[str]:
        return list(self.load_sources().keys())
