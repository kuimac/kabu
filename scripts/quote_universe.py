"""yfinance が列挙できる東証銘柄を、相場ユニバースとして保存する。

価格ソースは既存と同じ yfinance。銘柄の母集団は yfinance スクリーナーが
知っている東証（JPX）の株式と、地域 jp の ETF。日本語名と市場区分は
JPX が公開している東証上場銘柄一覧（月次の xlsx）で補う。
投信の全件一覧や、東証以外の市場はここでは作らない。
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, JST, now_jst, read_csv, write_csv

PAGE_SIZE = 250
FIELDS = ["symbol", "name", "asset_type", "association_code", "yahoo_ticker", "reason"]
# 東証の通常ティッカー。9942@F.T のような札幌・福岡の別名は含めない。
CANONICAL_TICKER = re.compile(r"^[0-9A-Z]{4,5}\.T$")
JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_XLSX = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
)
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
USER_AGENT = (
    "Mozilla/5.0 (compatible; nisa-dashboard/1.0; +https://kuimac.github.io/kabu/)"
)


def _screen_once(query, offset: int) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return yf.screen(
                query,
                offset=offset,
                size=PAGE_SIZE,
                sortField="ticker",
                sortAsc=False,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"screener failed at offset {offset}: {last_error}")


def _screen_query(query, label: str) -> tuple[list[dict], int]:
    offset = 0
    total = 0
    rows: list[dict] = []
    while True:
        payload = _screen_once(query, offset)
        total = int(payload.get("total") or 0)
        quotes = payload.get("quotes") or []
        print(f"OK screener {label}: offset={offset} page={len(quotes)} total={total}")
        if not quotes:
            break
        rows.extend(quotes)
        offset += PAGE_SIZE if len(quotes) == PAGE_SIZE else len(quotes)
        if offset >= total:
            break
        time.sleep(0.4)
    return rows, total


def screen_tokyo() -> tuple[list[dict], dict]:
    """東証株式と日本の ETF を、スクリーナーが返す範囲で集める。"""
    equity_query = yf.EquityQuery(
        "and",
        [
            yf.EquityQuery("eq", ["region", "jp"]),
            yf.EquityQuery("eq", ["exchange", "JPX"]),
        ],
    )
    etf_query = yf.ETFQuery("eq", ["region", "jp"])
    equities, equity_total = _screen_query(equity_query, "JPX equity")
    time.sleep(0.4)
    etfs, etf_total = _screen_query(etf_query, "JP ETF")
    merged: dict[str, dict] = {}
    for quote in equities + etfs:
        symbol = (quote.get("symbol") or "").strip()
        if symbol and symbol not in merged:
            merged[symbol] = quote
    stats = {
        "screener_equity_total": equity_total,
        "screener_equity_rows": len(equities),
        "screener_etf_total": etf_total,
        "screener_etf_rows": len(etfs),
        "screener_unique": len(merged),
    }
    return list(merged.values()), stats


def _xlsx_strings(book: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for node in root.findall("m:si", NS):
        parts = [
            text.text or ""
            for text in node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        strings.append("".join(parts))
    return strings


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        parts = [
            text.text or ""
            for text in cell.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        return "".join(parts).strip()
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    raw = value.text
    if kind == "s":
        return strings[int(raw)].strip()
    return raw.strip()


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - 64)
    return index


def parse_jpx_xlsx(payload: bytes) -> tuple[list[dict], str]:
    with ZipFile(BytesIO(payload)) as book:
        strings = _xlsx_strings(book)
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows: list[dict] = []
    as_of = ""
    for row in sheet.findall("m:sheetData/m:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("m:c", NS):
            ref = cell.get("r") or ""
            values[_column_index(ref)] = _cell_text(cell, strings)
        code = _normalize_code(values.get(2, ""))
        name = values.get(3, "").strip()
        market = values.get(4, "").strip()
        if not code or code == "コード" or not name:
            continue
        if not as_of:
            as_of = _normalize_date(values.get(1, ""))
        rows.append({"code": code, "name": name, "market": market})
    return rows, as_of


def _normalize_code(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if text.isdigit() and len(text) < 4:
        return text.zfill(4)
    return text


def _normalize_date(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def download_jpx_list() -> tuple[list[dict], str]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    response = session.get(JPX_XLSX, timeout=60)
    if response.status_code == 404:
        page = session.get(JPX_PAGE, timeout=60)
        page.raise_for_status()
        match = re.search(r'href="([^"]*data_j\.xlsx)"', page.text)
        if not match:
            raise RuntimeError("JPX page has no data_j.xlsx link")
        href = match.group(1)
        url = href if href.startswith("http") else "https://www.jpx.co.jp" + href
        response = session.get(url, timeout=60)
    response.raise_for_status()
    return parse_jpx_xlsx(response.content)


def _asset_type(market: str, quote_type: str) -> str:
    if "外国" in market:
        return "foreign_stock"
    if market.startswith("ETF") or quote_type == "ETF":
        return "etf"
    if any(token in market for token in ("REIT", "インフラファンド", "ベンチャーファンド", "カントリーファンド")):
        return "reit"
    return "stock"


def _price_from_quote(quote: dict) -> dict | None:
    raw = quote.get("regularMarketPrice")
    if raw in (None, ""):
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    previous = quote.get("regularMarketPreviousClose")
    change = quote.get("regularMarketChange")
    change_pct = quote.get("regularMarketChangePercent")
    try:
        if change in (None, "") and previous not in (None, ""):
            change = price - float(previous)
        change_text = "" if change in (None, "") else f"{float(change):.4f}"
    except (TypeError, ValueError):
        change_text = ""
    try:
        pct_text = "" if change_pct in (None, "") else f"{float(change_pct):.2f}"
    except (TypeError, ValueError):
        pct_text = ""
    as_of = ""
    stamp = quote.get("regularMarketTime")
    if stamp:
        try:
            as_of = datetime.fromtimestamp(int(stamp), JST).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            as_of = ""
    if not as_of:
        as_of = now_jst().strftime("%Y-%m-%d")
    name = (quote.get("longName") or quote.get("shortName") or quote.get("symbol") or "").strip()
    return {
        "price": price,
        "as_of": as_of,
        "change": change_text,
        "change_pct": pct_text,
        "source": "yfinance",
        "name": name,
        "quote_type": (quote.get("quoteType") or "").upper(),
    }


def _history_prices(tickers: list[str]) -> dict[str, dict]:
    """スクリーナーに無いコードだけ、既存と同じ日次終値で埋める。"""
    found: dict[str, dict] = {}
    if not tickers:
        return found
    for start in range(0, len(tickers), 40):
        chunk = tickers[start : start + 40]
        try:
            frame = yf.download(
                chunk,
                period="5d",
                group_by="ticker",
                threads=False,
                progress=False,
                auto_adjust=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"WARN yfinance batch {chunk[0]}..: {exc}")
            time.sleep(1.0)
            continue
        if frame is None or frame.empty:
            continue
        for ticker in chunk:
            try:
                closes = frame[ticker]["Close"].dropna() if len(chunk) > 1 else frame["Close"].dropna()
            except (KeyError, TypeError, AttributeError):
                continue
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else price
            change = price - prev
            change_pct = change / prev * 100 if prev else 0.0
            as_of = closes.index[-1]
            as_of_text = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)[:10]
            found[ticker] = {
                "price": price,
                "as_of": as_of_text,
                "change": f"{change:.4f}",
                "change_pct": f"{change_pct:.2f}",
                "source": "yfinance",
                "name": ticker,
                "quote_type": "",
            }
        time.sleep(0.8)
    return found


def _core_tickers_and_symbols() -> tuple[set[str], set[str]]:
    tickers: set[str] = set()
    symbols: set[str] = set()
    for name in ("holdings.csv", "watchlist.csv", "universe.csv"):
        for row in read_csv(DATA / name):
            symbol = (row.get("symbol") or "").strip()
            ticker = (row.get("yahoo_ticker") or "").strip()
            if symbol:
                symbols.add(symbol)
            if ticker:
                tickers.add(ticker)
    return tickers, symbols


def refresh_quote_universe() -> dict[str, dict]:
    """quote_universe.csv を更新し、銘柄コードから価格を返す。"""
    screened, stats = screen_tokyo()
    try:
        listed, listed_as_of = download_jpx_list()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN JPX list: {exc}")
        listed, listed_as_of = [], ""
    by_code = {row["code"]: row for row in listed}
    markets: dict[str, int] = {}
    for row in listed:
        markets[row["market"]] = markets.get(row["market"], 0) + 1

    core_tickers, core_symbols = _core_tickers_and_symbols()
    universe: list[dict] = []
    presets: dict[str, dict] = {}
    seen_codes: set[str] = set()
    no_price = 0
    screener_only = 0
    skipped_alias = 0

    for quote in screened:
        ticker = (quote.get("symbol") or "").strip()
        if not ticker:
            continue
        if not CANONICAL_TICKER.match(ticker):
            skipped_alias += 1
            continue
        code = ticker[:-2]
        got = _price_from_quote(quote)
        if got is None:
            no_price += 1
            continue
        seen_codes.add(code)
        listed_row = by_code.get(code)
        if listed_row:
            name = listed_row["name"]
            market = listed_row["market"]
        else:
            name = got["name"]
            market = ""
            if not name or name in {ticker, code}:
                skipped_alias += 1
                continue
            screener_only += 1
        if ticker in core_tickers or code in core_symbols:
            continue
        asset_type = _asset_type(market, got["quote_type"])
        reason = market or "yfinanceが列挙した東証銘柄"
        universe.append(
            {
                "symbol": code,
                "name": name,
                "asset_type": asset_type,
                "association_code": "",
                "yahoo_ticker": ticker,
                "reason": reason,
            }
        )
        presets[code] = got

    missing = [row for row in listed if row["code"] not in seen_codes and f"{row['code']}.T" not in core_tickers and row["code"] not in core_symbols]
    backfill = _history_prices([f"{row['code']}.T" for row in missing])
    unpriced: list[str] = []
    backfill_priced = 0
    for row in missing:
        ticker = f"{row['code']}.T"
        got = backfill.get(ticker)
        if got is None:
            unpriced.append(f"{row['code']} {row['name']} ({row['market']})")
            continue
        backfill_priced += 1
        got["name"] = row["name"]
        universe.append(
            {
                "symbol": row["code"],
                "name": row["name"],
                "asset_type": _asset_type(row["market"], got.get("quote_type") or ""),
                "association_code": "",
                "yahoo_ticker": ticker,
                "reason": row["market"] or "JPX上場銘柄",
            }
        )
        presets[row["code"]] = got

    universe.sort(key=lambda row: row["symbol"])
    write_csv(DATA / "quote_universe.csv", universe, FIELDS)
    print(
        "OK quote universe: "
        f"written={len(universe)} presets={len(presets)} "
        f"screener_unique={stats['screener_unique']} "
        f"equity={stats['screener_equity_rows']}/{stats['screener_equity_total']} "
        f"etf={stats['screener_etf_rows']}/{stats['screener_etf_total']} "
        f"jpx={len(listed)} jpx_as_of={listed_as_of or '-'} "
        f"screener_only={screener_only} skipped_alias={skipped_alias} no_price={no_price} "
        f"backfill={backfill_priced} unpriced_jpx={len(unpriced)}"
    )
    for market, count in sorted(markets.items(), key=lambda item: (-item[1], item[0])):
        print(f"  JPX {market}: {count}")
    if unpriced:
        preview = "; ".join(unpriced[:12])
        print(f"  unpriced sample: {preview}")
    stats.update(
        {
            "jpx_rows": len(listed),
            "jpx_as_of": listed_as_of,
            "jpx_markets": markets,
            "written": len(universe),
            "screener_only": screener_only,
            "no_price": no_price,
            "backfill_priced": backfill_priced,
            "unpriced_jpx": unpriced,
        }
    )
    refresh_quote_universe.last_stats = stats  # type: ignore[attr-defined]
    return presets


if __name__ == "__main__":
    refresh_quote_universe()
