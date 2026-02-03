import json
import os
from typing import Dict, List

RSS_FILE = "rss_sources.json"

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
        "https://rss.hankyung.com/feed/market.xml"
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

class SourceManager:
    def __init__(self):
        self.filepath = RSS_FILE
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.filepath):
            self.save_sources(DEFAULT_SOURCES)

    def load_sources(self) -> Dict[str, List[str]]:
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return DEFAULT_SOURCES

    def save_sources(self, sources: Dict[str, List[str]]):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(sources, f, indent=4, ensure_ascii=False)

    def add_source(self, category: str, url: str):
        sources = self.load_sources()
        if category not in sources:
            sources[category] = []
        if url not in sources[category]:
            sources[category].append(url)
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
