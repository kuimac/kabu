"""負荷配慮付きの Web スクレイピング（投信NAV・ニュース）。"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polite_http import PoliteSession, shared_session


def _parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "").replace("円", "").strip()
    cleaned = re.sub(r"[^\d.\-+]", "", cleaned)
    if not cleaned or cleaned in {"+", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_yahoo_fund_nav(association_code: str, session: PoliteSession | None = None) -> dict | None:
    """Yahoo!ファイナンスの投信ページから基準価額を取得。"""
    if not association_code:
        return None
    sess = session or shared_session()
    url = f"https://finance.yahoo.co.jp/quote/{association_code}"
    try:
        res = sess.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN yahoo fund {association_code}: {exc}")
        return None

    soup = BeautifulSoup(res.text, "lxml")
    price_el = soup.select_one(
        '[class*="CommonPriceBoard__price"] [class*="StyledNumber__value"]'
    )
    if not price_el:
        # フォールバック: 価格ボード全体から大きめの数値
        board = soup.select_one('[class*="CommonPriceBoard"]')
        if not board:
            print(f"WARN yahoo fund {association_code}: price element not found")
            return None
        nums = re.findall(r"\d{1,3}(?:,\d{3})+", board.get_text(" ", strip=True))
        if not nums:
            return None
        price = _parse_number(nums[0])
    else:
        price = _parse_number(price_el.get_text(strip=True))

    if price is None:
        return None

    change = ""
    change_pct = ""
    label = soup.select_one('[class*="PriceChangeLabel"]')
    if label:
        txt = label.get_text(" ", strip=True)
        m = re.search(
            r"([+\-−]?[0-9,]+(?:\.[0-9]+)?)\s*\(\s*([+\-−]?[0-9.]+)\s*%\s*\)",
            txt,
        )
        if m:
            change = m.group(1).replace(",", "").replace("−", "-")
            change_pct = m.group(2).replace("−", "-")

    as_of = ""
    board = soup.select_one('[class*="CommonPriceBoard"]')
    if board:
        m = re.search(r"(\d{1,2})/(\d{1,2})", board.get_text(" ", strip=True))
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = datetime.now().year
            # 年末跨ぎの粗い補正
            if month == 12 and datetime.now().month == 1:
                year -= 1
            as_of = f"{year:04d}-{month:02d}-{day:02d}"

    return {
        "price": price,
        "as_of": as_of,
        "change": change,
        "change_pct": change_pct,
        "source": "yahoo_scrape",
        "name": association_code,
        "url": url,
    }


def fetch_yahoo_stock_quote(code: str, session: PoliteSession | None = None) -> dict | None:
    """Yahoo!ファイナンスの個別株ページ（例: 7013.T）。補助用。"""
    if not code:
        return None
    sess = session or shared_session()
    url = f"https://finance.yahoo.co.jp/quote/{code}"
    try:
        res = sess.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN yahoo stock {code}: {exc}")
        return None
    soup = BeautifulSoup(res.text, "lxml")
    price_el = soup.select_one(
        '[class*="CommonPriceBoard__price"] [class*="StyledNumber__value"]'
    ) or soup.select_one('[class*="PriceBoard"] [class*="StyledNumber__value"]')
    if not price_el:
        return None
    price = _parse_number(price_el.get_text(strip=True))
    if price is None:
        return None
    change = change_pct = ""
    label = soup.select_one('[class*="PriceChangeLabel"]')
    if label:
        txt = label.get_text(" ", strip=True)
        m = re.search(
            r"([+\-−]?[0-9,]+(?:\.[0-9]+)?)\s*\(\s*([+\-−]?[0-9.]+)\s*%\s*\)",
            txt,
        )
        if m:
            change = m.group(1).replace(",", "").replace("−", "-")
            change_pct = m.group(2).replace("−", "-")
    return {
        "price": price,
        "as_of": "",
        "change": change,
        "change_pct": change_pct,
        "source": "yahoo_scrape",
        "name": code,
        "url": url,
    }


def fetch_kabutan_news(limit: int = 15, session: PoliteSession | None = None) -> list[dict]:
    sess = session or shared_session()
    url = "https://kabutan.jp/news/"
    try:
        res = sess.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN kabutan news: {exc}")
        return []
    soup = BeautifulSoup(res.text, "lxml")
    rows: list[dict] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if "/news/marketnews/?b=" not in href or not title or len(title) < 8:
            continue
        if "プレミアム専用" in title:
            continue
        full = urljoin(url, href)
        if full in seen:
            continue
        seen.add(full)
        rows.append(
            {
                "published": "",
                "source": "株探",
                "title": title,
                "link": full,
                "category": "kabutan",
            }
        )
        if len(rows) >= limit:
            break
    print(f"OK 株探ニュース: {len(rows)} items")
    return rows


def fetch_minkabu_news(limit: int = 10, session: PoliteSession | None = None) -> list[dict]:
    sess = session or shared_session()
    url = "https://minkabu.jp/news"
    try:
        res = sess.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN minkabu news: {exc}")
        return []
    soup = BeautifulSoup(res.text, "lxml")
    rows: list[dict] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 12:
            continue
        if "/news/" not in href and "/articles/" not in href:
            continue
        full = urljoin(url, href)
        if full in seen or "minkabu.jp" not in full:
            continue
        # ナビやカテゴリ見出しを除外
        if title in {"ニュース", "トップ", "ホーム"}:
            continue
        seen.add(full)
        rows.append(
            {
                "published": "",
                "source": "みんかぶ",
                "title": title,
                "link": full,
                "category": "minkabu",
            }
        )
        if len(rows) >= limit:
            break
    print(f"OK みんかぶニュース: {len(rows)} items")
    return rows
