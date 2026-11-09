#!/usr/bin/env python3
"""取扱銘柄のファンダメンタルを、今回の Yahoo クォートから取得する。

返ってこなかった項目は空のままにする。数値を補完したり、評価を作ったりしない。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from yfinance.const import _QUERY1_URL_
from yfinance.data import YfData

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, now_jst, read_csv, write_csv

FIELDS = [
    "symbol",
    "as_of",
    "price",
    "change_pct",
    "currency",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "eps",
    "eps_forward",
    "market_cap",
    "div_yield",
    "book_value",
    "week52_high",
    "week52_low",
    "quote_type",
]
BATCH = 40
QUOTE_KEYS = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_book": "priceToBook",
    "eps": "epsTrailingTwelveMonths",
    "eps_forward": "epsForward",
    "market_cap": "marketCap",
    "book_value": "bookValue",
    "week52_high": "fiftyTwoWeekHigh",
    "week52_low": "fiftyTwoWeekLow",
}


def _text(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _symbols() -> list[str]:
    rows = read_csv(DATA / "quote_universe.csv")
    symbols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        symbol = (row.get("symbol") or "").strip()
        ticker = (row.get("yahoo_ticker") or "").strip()
        if not symbol or not ticker or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _ticker_of(symbol: str, universe: dict[str, dict]) -> str:
    ticker = (universe.get(symbol, {}).get("yahoo_ticker") or "").strip()
    return ticker or f"{symbol}.T"


def _fetch_batch(data: YfData, tickers: list[str]) -> list[dict]:
    params = {"symbols": ",".join(tickers), "formatted": "false"}
    result = data.get_raw_json(f"{_QUERY1_URL_}/v7/finance/quote?", params=params)
    payload = (result or {}).get("quoteResponse") or {}
    return list(payload.get("result") or [])


def _row_from_quote(symbol: str, quote: dict, as_of: str) -> dict:
    row = {key: "" for key in FIELDS}
    row["symbol"] = symbol
    row["as_of"] = as_of
    row["price"] = _text(quote.get("regularMarketPrice"))
    row["change_pct"] = _text(quote.get("regularMarketChangePercent"))
    row["currency"] = _text(quote.get("currency"))
    row["quote_type"] = _text(quote.get("quoteType"))
    for field, key in QUOTE_KEYS.items():
        if key in quote:
            row[field] = _text(quote.get(key))
    # 配当利回りは小数で返る trailingAnnualDividendYield だけを使う。
    # dividendYield は倍率の表記が混ざるため、欠測の穴埋めには使わない。
    if "trailingAnnualDividendYield" in quote:
        row["div_yield"] = _text(quote.get("trailingAnnualDividendYield"))
    return row


def refresh_fundamentals() -> int:
    universe = {row["symbol"]: row for row in read_csv(DATA / "quote_universe.csv") if row.get("symbol")}
    symbols = _symbols()
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    data = YfData()
    by_ticker: dict[str, dict] = {}
    print(f"fundamental symbols={len(symbols)}", flush=True)
    for start in range(0, len(symbols), BATCH):
        chunk = symbols[start : start + BATCH]
        tickers = [_ticker_of(symbol, universe) for symbol in chunk]
        quotes: list[dict] = []
        for attempt in range(3):
            try:
                quotes = _fetch_batch(data, tickers)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"WARN {tickers[0]}.. attempt {attempt + 1}: {exc}", flush=True)
                time.sleep(1.5 * (attempt + 1))
        for quote in quotes:
            ticker = str(quote.get("symbol") or "")
            if ticker:
                by_ticker[ticker] = quote
        print(f"  {start + len(chunk)}/{len(symbols)} quotes={len(by_ticker)}", flush=True)
        time.sleep(0.35)
    rows: list[dict] = []
    for symbol in symbols:
        ticker = _ticker_of(symbol, universe)
        quote = by_ticker.get(ticker)
        if quote:
            rows.append(_row_from_quote(symbol, quote, as_of))
        else:
            empty = {key: "" for key in FIELDS}
            empty["symbol"] = symbol
            empty["as_of"] = as_of
            rows.append(empty)
    rows.sort(key=lambda row: row["symbol"])
    write_csv(DATA / "fundamentals.csv", rows, FIELDS)
    with_pe = sum(1 for row in rows if row["trailing_pe"])
    with_pbr = sum(1 for row in rows if row["price_to_book"])
    with_eps = sum(1 for row in rows if row["eps"])
    with_price = sum(1 for row in rows if row["price"])
    print(
        f"OK fundamentals rows={len(rows)} price={with_price} pe={with_pe} "
        f"pbr={with_pbr} eps={with_eps}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(refresh_fundamentals())
