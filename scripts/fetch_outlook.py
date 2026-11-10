"""公表されている市場の中長期見通しを保存する。

数値は資料から読めたものだけを書く。終値と比べられない行は判定に使わない。
"""
from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path

import requests
import yfinance as yf
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, ensure_data_dir, now_jst, read_csv, write_csv

SOURCE = "野村證券"
SOURCE_URL = "https://www.nomura.co.jp/market/research/pdf/indices.pdf"
HORIZONS = ("2026-12", "2027-03", "2027-06", "2027-12")
FIELDS = [
    "as_of",
    "source",
    "source_url",
    "published",
    "document_id",
    "market",
    "horizon_date",
    "target",
    "spot",
    "spot_date",
    "spot_source",
    "note",
]
_MARKETS = (
    ("日経平均株価", "n225"),
    ("TOPIX", "topix"),
    ("S&P500", "spx"),
)
_SPOTS = {
    "n225": "^N225",
    "spx": "^GSPC",
    "topix": "^TOPX",
}


def _numbers(chunk: str) -> list[float]:
    found = []
    for raw in re.findall(r"\d{1,3}(?:,\d{3})+", chunk):
        found.append(float(raw.replace(",", "")))
        if len(found) == 4:
            break
    return found


def parse_nomura(text: str) -> tuple[str, str, dict[str, list[float]]]:
    published = ""
    dated = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if dated:
        published = f"{int(dated.group(1)):04d}-{int(dated.group(2)):02d}-{int(dated.group(3)):02d}"
    document = ""
    coded = re.search(r"MZ\d+", text)
    if coded:
        document = coded.group(0)
    targets: dict[str, list[float]] = {}
    for label, key in _MARKETS:
        start = text.find(label)
        if start < 0:
            continue
        values = _numbers(text[start : start + 180])
        if len(values) == 4:
            targets[key] = values
    if "n225" not in targets:
        raise ValueError("日経平均の4本の見通しが読めなかった")
    return published, document, targets


def _yfinance_spot(ticker: str) -> tuple[str, str]:
    hist = yf.Ticker(ticker).history(period="5d")
    if hist.empty or "Close" not in hist:
        return "", ""
    closes = hist["Close"].dropna()
    if closes.empty:
        return "", ""
    return f"{float(closes.iloc[-1]):.2f}", str(closes.index[-1])[:10]


def _stored_n225() -> tuple[str, str]:
    for row in read_csv(DATA / "market.csv"):
        if row.get("symbol") == "^N225" and row.get("price"):
            return row["price"], (row.get("as_of") or "")[:10]
    return "", ""


def main() -> int:
    ensure_data_dir()
    try:
        res = requests.get(SOURCE_URL, timeout=30)
        res.raise_for_status()
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(res.content)).pages)
        published, document, targets = parse_nomura(text)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN outlook: {exc}")
        return 1
    spots: dict[str, tuple[str, str, str]] = {}
    for market, ticker in _SPOTS.items():
        try:
            price, day = _yfinance_spot(ticker)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN spot {ticker}: {exc}")
            price, day = "", ""
        source = "yfinance" if price else ""
        if not price and market == "n225":
            price, day = _stored_n225()
            source = "market.csv" if price else ""
        spots[market] = (price, day, source)
        if not price:
            print(f"SKIP {market}: 終値がない")
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    rows = []
    for market, values in targets.items():
        spot, day, source = spots.get(market, ("", "", ""))
        note = "" if spot else "終値が取れなかったので判定に使わない"
        for horizon, target in zip(HORIZONS, values):
            rows.append(
                {
                    "as_of": as_of,
                    "source": SOURCE,
                    "source_url": SOURCE_URL,
                    "published": published,
                    "document_id": document,
                    "market": market,
                    "horizon_date": horizon,
                    "target": f"{target:.2f}".rstrip("0").rstrip("."),
                    "spot": spot,
                    "spot_date": day,
                    "spot_source": source,
                    "note": note,
                }
            )
    rows.append(
        {
            "as_of": as_of,
            "source": "Yahoo Finance",
            "source_url": "",
            "published": "",
            "document_id": "",
            "market": "",
            "horizon_date": "",
            "target": "",
            "spot": "",
            "spot_date": "",
            "spot_source": "yfinance",
            "note": "指数の目標値がなかったので使わない",
        }
    )
    write_csv(DATA / "market_outlook.csv", rows, FIELDS)
    print(f"OK outlook rows={len(rows)} published={published} id={document}")
    for row in rows:
        if row["note"] and not row["target"]:
            print(f"  skip {row['source']}: {row['note']}")
            continue
        print(
            f"  {row['market']} {row['horizon_date']} target={row['target']} "
            f"spot={row['spot'] or '-'} {row['note']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
