"""強い30件について、株探の銘柄別ニュースから最新1件を取る。

売り買いの判定には使わない。返ってこなかった銘柄は行を作らない。
"""
from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, ensure_data_dir, now_jst, read_csv, write_csv
from polite_http import shared_session

FIELDS = ["as_of", "symbol", "published", "source", "title", "link", "category"]
PAGE = "https://kabutan.jp/stock/news?code={code}"
_SUFFIXES = ("ホールディングス", "ホールディング", "グループ", "証券", "株式会社")
_GENERIC = {
    "ホールディングス",
    "ホールディング",
    "グループ",
    "証券",
    "株式会社",
    "テクノ",
    "テクノロジー",
    "テクノロジーズ",
    "工業",
    "産業",
    "システム",
    "サービス",
}


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s・]+", "", folded)


def name_keys(name: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", name or "")
    compact = _norm(folded)
    keys = [compact]
    for suffix in _SUFFIXES:
        if compact.endswith(suffix) and len(compact) - len(suffix) >= 3:
            keys.append(compact[: -len(suffix)])
    for part in re.split(r"[\s・]+", folded.strip()):
        if len(part) >= 3 and part not in _GENERIC:
            keys.append(part)
    unique = sorted({key for key in keys if len(key) >= 3}, key=len, reverse=True)
    return unique


def title_names_company(title: str, keys: list[str]) -> bool:
    folded = _norm(title)
    return any(key in folded for key in keys)


_ROUNDUP_HINTS = (
    "動いた銘柄",
    "銘柄リスト",
    "銘柄ダイジェスト",
    "ダイジェスト",
    "サプライズ決算",
    "株式相場",
    "日経平均",
    "青天井",
    "ボリンジャー",
    "成長株特集",
    "銘柄特集",
)


def is_roundup(title: str, category: str, named: bool) -> bool:
    if named:
        return False
    head = title.lstrip("★☆■□ ")
    if category == "テク" or head.startswith("本日の") or "本日の【" in title:
        return True
    if any(hint in title for hint in _ROUNDUP_HINTS):
        return True
    return "銘柄" in title and any(word in title for word in ("上抜け", "下抜け", "本日", "リスト"))


def _when(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        return datetime.min
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


def choose_article(items: list[dict], keys: list[str]) -> dict | None:
    kept: list[dict] = []
    for item in items:
        named = title_names_company(item["title"], keys)
        if is_roundup(item["title"], item.get("category") or "", named):
            continue
        kept.append({**item, "named": named})
    if not kept:
        return None
    newest = max(_when(item["published"]) for item in kept)
    same = [item for item in kept if _when(item["published"]) == newest]
    named = [item for item in same if item["named"]]
    pool = named or same

    def rank(item: dict) -> tuple[int, int]:
        title = item["title"]
        useful = 0 if any(word in title for word in ("決算", "業績", "増益", "減益", "配当", "上方", "下方")) else 1
        return (0 if item["named"] else 1, useful)

    pool.sort(key=rank)
    chosen = pool[0]
    return {key: chosen[key] for key in ("published", "title", "link", "category")}


def parse_news_html(html: str, code: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.s_news_list")
    if table is None:
        return []
    base = PAGE.format(code=code)
    items: list[dict] = []
    for row in table.select("tr"):
        link = row.select_one("a[href]")
        if link is None:
            continue
        title = link.get_text(" ", strip=True)
        if not title or "プレミアム専用" in title:
            continue
        stamp = row.select_one("time")
        published = (stamp.get("datetime") or "").strip() if stamp else ""
        category_el = row.select_one(".newslist_ctg")
        category = category_el.get_text(" ", strip=True) if category_el else ""
        items.append(
            {
                "published": published,
                "title": title,
                "link": urljoin(base, link["href"]),
                "category": category,
            }
        )
    return items


def fetch_article(session, symbol: str, keys: list[str]) -> dict | None:
    urls = [
        PAGE.format(code=symbol),
        f"https://kabutan.jp/stock/news?code={symbol}&nmode=0&page=2",
        f"https://kabutan.jp/stock/?code={symbol}",
    ]
    collected: list[dict] = []
    for index, url in enumerate(urls):
        try:
            res = session.get(url)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {symbol}: {exc}")
            if collected:
                break
            continue
        found = parse_news_html(res.text, symbol)
        if not found:
            if collected:
                break
            continue
        collected.extend(found)
        article = choose_article(collected, keys)
        if article is not None or index == len(urls) - 1:
            return article
    return choose_article(collected, keys)


def ranked_symbols() -> list[dict]:
    rows = [row for row in read_csv(DATA / "symbol_analysis.csv") if str(row.get("rank") or "").strip()]
    rows.sort(key=lambda row: int(row["rank"]))
    return rows


def main() -> int:
    ensure_data_dir()
    picked = ranked_symbols()
    if not picked:
        print("WARN idea news: ranked symbols are empty")
        return 1
    session = shared_session()
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    saved: list[dict] = []
    failures = 0
    for row in picked:
        symbol = row["symbol"]
        keys = name_keys(row.get("name") or "")
        article = fetch_article(session, symbol, keys)
        if article is None:
            failures += 1
            print(f"WARN {symbol}: no company news")
            continue
        saved.append(
            {
                "as_of": as_of,
                "symbol": symbol,
                "published": article["published"],
                "source": "株探",
                "title": article["title"],
                "link": article["link"],
                "category": article["category"],
            }
        )
        print(f"OK {symbol}: {article['title']}")
    if not saved:
        print("WARN idea news: kept the previous file")
        return 1
    write_csv(DATA / "idea_news.csv", saved, FIELDS)
    print(f"idea news={len(saved)} missed={len(picked) - len(saved)} failed={failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
