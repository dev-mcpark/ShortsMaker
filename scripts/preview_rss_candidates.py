"""Write a no-provider-call preview of the planner's current RSS candidate pool."""

import argparse
from datetime import datetime
from html import escape
from pathlib import Path
from uuid import uuid4

from bs4 import BeautifulSoup

from shorts_maker.planner.script_planner import ScriptPlanner
from shorts_maker.utils.config import settings
from shorts_maker.utils.source_manager import SourceManager


def render_html(candidates: list[dict], categories: list[str], all_recent: bool = False) -> str:
    cards = []
    for item in candidates:
        url = item["url"]
        if not SourceManager.is_allowed_url(url):
            continue
        excerpt = BeautifulSoup(item.get("content") or "", "html.parser").get_text(" ", strip=True)
        cards.append(
            '<article><p class="category">' + escape(item["category"]) + ' · ' +
            escape(item["source"]) + ' · ' + escape((item.get("published") or "발행일 미표기")[:80]) +
            '</p><h2><a href="' + escape(url, quote=True) +
            '" target="_blank" rel="noopener noreferrer">' + escape(item["title"]) +
            '</a></h2><p>' + escape(" ".join(excerpt.split())[:300]) + '</p></article>'
        )
    content = ("\n".join(cards) if cards else
               "<p>표시할 후보가 없습니다. 일부 피드가 실패했을 수 있으므로 수집 로그도 확인하세요.</p>")
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>RSS 소재 미리보기</title><style>"
            "body{max-width:820px;margin:24px auto;padding:0 16px;background:#f4f0e9;color:#203746;font:16px/1.6 system-ui,sans-serif}"
            "article{background:white;border:1px solid #c7d3d1;border-radius:12px;padding:14px 18px;margin:14px 0}"
            "h2{font-size:19px;margin:4px 0}a{color:#176e80}.category{font-size:13px;color:#657b84;margin:0}"
            "</style></head><body><h1>RSS 소재 미리보기</h1><p>" +
            escape(", ".join(categories)) + " · " + datetime.now().strftime("%Y-%m-%d %H:%M") +
            " 수집 · 후보 " + str(len(cards)) + "건. " +
            ("읽힌 피드에서 수집 규칙을 통과한 최근 후보 전체입니다. 자동 유료 평가는 매일 바뀌는 순서에서 카테고리별 최대 5건만 고릅니다. "
             if all_recent else "실제 자동 유료 평가의 카테고리별 최대 5건 후보입니다. ") +
            "같은 날 피드 내용과 검토 이력이 같으면 후보 순서도 같습니다. " +
            "비용이 드는 모델 평가·본문 검증은 실행하지 않았습니다. "
            "일부 피드는 실패했을 수 있으니 수집 로그를 확인하세요. 제목과 RSS 요약은 단서일 뿐입니다. 흥미로운 후보를 골라도 원문과 시점·주장을 확인하세요.</p>" +
            content + "</body></html>")


def preview(categories: list[str], output: Path, all_recent: bool = False) -> Path:
    planner = ScriptPlanner.for_rss_discovery()
    unknown = set(categories) - set(planner.rss_sources)
    if unknown:
        raise ValueError(f"등록되지 않은 카테고리: {', '.join(sorted(unknown))}")
    planner.rss_sources = {name: planner.rss_sources[name] for name in categories}
    candidates = planner._fetch_rss_feeds(limit_per_category=None) if all_recent else planner._fetch_rss_feeds()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(candidates, categories, all_recent), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", action="append", required=True, help="Registered RSS category; repeat to combine")
    parser.add_argument("--all-recent", action="store_true", help="Show all recent leads passing collection filters for free editorial review")
    args = parser.parse_args()
    kind = "inventory" if args.all_recent else "preview"
    filename = f"rss_candidate_{kind}_{datetime.now():%Y%m%d}_{uuid4().hex}.html"
    output = settings.output_dir / "evaluation" / filename
    print(preview(args.category, output, all_recent=args.all_recent))


if __name__ == "__main__":
    main()
