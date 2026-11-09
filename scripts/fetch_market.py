"""TOPIX等の市場指標を取得して data/market.csv に保存。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, ensure_data_dir, now_jst, read_csv, write_csv


def _sparkline(closes: list[float], width: int = 24) -> str:
    if not closes:
        return ""
    series = closes[-width:]
    lo, hi = min(series), max(series)
    if hi == lo:
        return "▁" * len(series)
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for v in series:
        idx = int((v - lo) / (hi - lo) * (len(blocks) - 1))
        out.append(blocks[idx])
    return "".join(out)


def fetch_ticker_snapshot(ticker: str, name: str) -> dict:
    t = yf.Ticker(ticker)
    hist = t.history(period="1mo")
    if hist.empty:
        raise RuntimeError(f"no history for {ticker}")
    finite: list[tuple[str, float]] = []
    for ts, raw in zip(hist.index, hist["Close"].tolist()):
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            finite.append((str(ts)[:10], price))
    if not finite:
        raise RuntimeError(f"no finite close for {ticker}")
    bar_date, price = finite[-1]
    prev = finite[-2][1] if len(finite) > 1 else price
    change = price - prev
    change_pct = (change / prev * 100) if prev else 0.0
    closes = [value for _day, value in finite]
    return {
        "as_of": now_jst().strftime("%Y-%m-%d %H:%M:%S%z"),
        "bar_date": bar_date,
        "symbol": ticker,
        "name": name,
        "price": f"{price:.2f}",
        "change": f"{change:.2f}",
        "change_pct": f"{change_pct:.2f}",
        "source": "yfinance",
        "sparkline": _sparkline(closes),
        "_closes": closes,
    }


def main() -> int:
    ensure_data_dir()
    rows = []
    existing = {row["symbol"]: row for row in read_csv(DATA / "market.csv") if row.get("symbol")}
    # yfinance で ^TOPX は取得できないため、TOPIX連動ETF 1306.T を主指標とする
    candidates = [
        ("1306.T", "TOPIX連動ETF(1306)"),
        ("^N225", "日経平均"),
    ]
    for ticker, name in candidates:
        try:
            snap = fetch_ticker_snapshot(ticker, name)
            previous = existing.get(ticker)
            if previous and (previous.get("as_of") or "")[:10] > snap["bar_date"]:
                rows.append(previous)
                print(f"WARN {ticker}: bar {snap['bar_date']} is older than {previous['as_of']}, keep previous")
                continue
            rows.append({k: v for k, v in snap.items() if not k.startswith("_") and k != "bar_date"})
            print(f"OK {ticker}: {snap['price']} ({snap['change_pct']}%)")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {ticker}: {exc}")
            if ticker in existing:
                rows.append(existing[ticker])
                print(f"WARN {ticker}: keep previous price {existing[ticker].get('price')}")

    if not rows:
        print("ERROR: no market data fetched")
        return 1

    write_csv(
        DATA / "market.csv",
        rows,
        ["as_of", "symbol", "name", "price", "change", "change_pct", "source", "sparkline"],
    )
    # チャート用に直近終値をJSONでも残す
    topix = next((r for r in rows if r["symbol"] in ("1306.T", "^TOPX")), rows[0])
    hist_path = DATA / "market_history.json"
    try:
        # re-fetch closes for chart payload of primary
        primary = fetch_ticker_snapshot(topix["symbol"], topix["name"])
        payload = {
            "symbol": primary["symbol"],
            "name": primary["name"],
            "closes": primary["_closes"][-60:],
            "updated_at": primary["as_of"],
        }
        hist_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN market_history.json: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
