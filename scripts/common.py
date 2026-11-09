"""共通ユーティリティ。"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import jpholiday

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"

JST = timezone(timedelta(hours=9))

MUFG_NAV_URL = (
    "https://developer.am.mufg.jp/fund_information_latest/association_fund_cd/{code}"
)

JPX_RSS_FEEDS = [
    ("JPXマーケットニュース", "https://www.jpx.co.jp/rss/markets_news.xml"),
    ("JPXニュース", "https://www.jpx.co.jp/rss/jpx-news.xml"),
    ("JPXアラート", "https://www.jpx.co.jp/rss/alerts.xml"),
]


def now_jst() -> datetime:
    return datetime.now(JST)


def today_jst() -> date:
    return now_jst().date()


def ensure_data_dir() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "assets").mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def append_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return default


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return not jpholiday.is_holiday(d)


def add_business_days(start: date, days: int) -> date:
    """営業日を加算（startの翌営業日からカウント）。days<=0ならstartを返す。"""
    if days <= 0:
        return start
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            remaining -= 1
    return current


def next_business_days(start: date, count: int = 30) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if is_business_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def fund_market_value(units: float, nav: float, unit_multiplier: float = 1000, nav_denominator: float = 10000) -> float:
    """投信評価額 = 表示口数 × unit_multiplier × NAV / nav_denominator。"""
    return units * unit_multiplier * nav / nav_denominator


def implied_nav(units: float, market_value: float, unit_multiplier: float = 1000, nav_denominator: float = 10000) -> float:
    if units <= 0:
        return 0.0
    return market_value * nav_denominator / (units * unit_multiplier)
