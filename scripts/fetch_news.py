"""JPX RSS と株探・みんかぶ（丁寧スクレイピング）からニュースを取得。"""
from __future__ import annotations

import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, JPX_RSS_FEEDS, ensure_data_dir, write_csv
from polite_http import shared_session
from scrape_web import fetch_kabutan_news, fetch_minkabu_news


def normalize_published(entry) -> str:
    if getattr(entry, "published", None):
        try:
            dt = parsedate_to_datetime(entry.published)
            return dt.isoformat()
        except Exception:  # noqa: BLE001
            return entry.published
    if getattr(entry, "updated", None):
        return entry.updated
    return ""


def fetch_jpx_rss() -> list[dict]:
    rows: list[dict] = []
    for source_name, url in JPX_RSS_FEEDS:
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"WARN RSS failed: {url} ({feed.bozo_exception})")
            continue
        for entry in feed.entries:
            rows.append(
                {
                    "published": normalize_published(entry),
                    "source": source_name,
                    "title": getattr(entry, "title", "").strip(),
                    "link": getattr(entry, "link", "").strip(),
                    "category": getattr(feed.feed, "category", source_name),
                }
            )
        print(f"OK {source_name}: {len(feed.entries)} items")
    return rows


def main() -> int:
    ensure_data_dir()
    rows: list[dict] = []
    rows.extend(fetch_jpx_rss())

    # HTMLスクレイピングは間隔を十分にあける（PoliteSession共有）
    session = shared_session()
    rows.extend(fetch_kabutan_news(session=session))
    rows.extend(fetch_minkabu_news(session=session))

    seen = set()
    unique = []
    for row in sorted(rows, key=lambda r: (r.get("published") or "", r.get("title") or ""), reverse=True):
        key = (row["title"], row["link"])
        if key in seen or not row["title"]:
            continue
        seen.add(key)
        unique.append(row)

    write_csv(
        DATA / "news.csv",
        unique,
        ["published", "source", "title", "link", "category"],
    )
    print(f"news total={len(unique)}")
    return 0 if unique else 1


if __name__ == "__main__":
    raise SystemExit(main())
