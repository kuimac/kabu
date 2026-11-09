#!/usr/bin/env python3
"""銘柄ごとの過去5年の日次終値を data/history/ に保存する。"""
from __future__ import annotations

import signal
import time
from datetime import date, timedelta

import yfinance as yf

from common import DATA, read_csv, today_jst, write_csv
from technical import ticker_map

INDEX_FIELDS = [
    "symbol",
    "start",
    "end",
    "bars",
    "first_price",
    "last_price",
    "high",
    "low",
    "change_pct",
]
HISTORY_DIR = DATA / "history"


def drop_return_spikes(points: list[tuple[str, float]], ratio: float = 0.55, max_run: int = 5) -> list[tuple[str, float]]:
    """前後へすぐ戻る極端な終値だけを除く。半分より浅い変動と、続いた水準変化は残す。"""
    if len(points) < 3:
        return points
    kept: list[tuple[str, float]] = []
    index = 0
    while index < len(points):
        if not kept:
            kept.append(points[index])
            index += 1
            continue
        last = kept[-1][1]
        price = points[index][1]
        if last > 0 and ratio <= price / last <= 1 / ratio:
            kept.append(points[index])
            index += 1
            continue
        ahead = index
        while ahead < len(points) and last > 0 and not (ratio <= points[ahead][1] / last <= 1 / ratio):
            ahead += 1
            if ahead - index > max_run:
                break
        if (
            ahead < len(points)
            and ahead - index <= max_run
            and last > 0
            and ratio <= points[ahead][1] / last <= 1 / ratio
        ):
            index = ahead
            continue
        kept.append(points[index])
        index += 1
    return kept


def _dated_closes(frame, ticker: str, multiple: bool) -> list[tuple[str, float]]:
    try:
        series = frame[ticker]["Close"] if multiple else frame["Close"]
    except (KeyError, TypeError, AttributeError):
        return []
    points: list[tuple[str, float]] = []
    for ts, raw in series.items():
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price != price or price <= 0:  # NaN を除く
            continue
        points.append((str(ts)[:10], price))
    points.sort()
    deduped: list[tuple[str, float]] = []
    for day, price in points:
        if deduped and deduped[-1][0] == day:
            deduped[-1] = (day, price)
        else:
            deduped.append((day, price))
    return drop_return_spikes(deduped)


def _fresh(symbol: str) -> bool:
    path = HISTORY_DIR / f"{symbol}.csv"
    rows = read_csv(path)
    if len(rows) < 40:
        return False
    try:
        end = date.fromisoformat(rows[-1]["date"])
    except (KeyError, TypeError, ValueError):
        return False
    return today_jst() - end <= timedelta(days=14)


def write_index() -> int:
    rows: list[dict] = []
    for path in sorted(HISTORY_DIR.glob("*.csv")):
        points = read_csv(path)
        prices: list[float] = []
        for point in points:
            try:
                prices.append(float(point["price"]))
            except (KeyError, TypeError, ValueError):
                continue
        if not prices or not points:
            continue
        first, last = prices[0], prices[-1]
        change = (last - first) / first * 100 if first else 0.0
        rows.append(
            {
                "symbol": path.stem,
                "start": points[0].get("date", ""),
                "end": points[-1].get("date", ""),
                "bars": str(len(prices)),
                "first_price": f"{first:.4f}",
                "last_price": f"{last:.4f}",
                "high": f"{max(prices):.4f}",
                "low": f"{min(prices):.4f}",
                "change_pct": f"{change:.2f}",
            }
        )
    write_csv(DATA / "history_index.csv", rows, INDEX_FIELDS)
    print(f"OK history index={len(rows)}", flush=True)
    return len(rows)


def refresh_history() -> int:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    mapping = ticker_map()
    inverse: dict[str, str] = {}
    for symbol, ticker in mapping.items():
        inverse.setdefault(ticker, symbol)
    pending = {ticker: symbol for ticker, symbol in inverse.items() if not _fresh(symbol)}
    tickers = sorted(pending)
    print(f"history tickers={len(inverse)} pending={len(tickers)}", flush=True)
    written = 0
    for start in range(0, len(tickers), 40):
        chunk = tickers[start : start + 40]

        def _expire(_signum, _frame, label=chunk[0]):
            raise TimeoutError(label)

        try:
            signal.signal(signal.SIGALRM, _expire)
            signal.alarm(180)
            frame = yf.download(
                chunk,
                period="5y",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {chunk[0]}..: {exc}", flush=True)
            time.sleep(1.0)
            continue
        finally:
            signal.alarm(0)
        if frame is None or getattr(frame, "empty", True):
            time.sleep(0.4)
            continue
        multiple = len(chunk) > 1
        for ticker in chunk:
            points = _dated_closes(frame, ticker, multiple)
            if len(points) < 2:
                continue
            symbol = pending[ticker]
            write_csv(
                HISTORY_DIR / f"{symbol}.csv",
                [{"date": day, "price": f"{price:.4f}"} for day, price in points],
                ["date", "price"],
            )
            written += 1
        print(f"  {start + len(chunk)}/{len(tickers)} written={written}", flush=True)
        time.sleep(0.4)
    write_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(refresh_history())
