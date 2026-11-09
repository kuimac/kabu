#!/usr/bin/env python3
"""代表的シグナル用に、5日・25日移動平均とRSI(14)を計算して保存する。"""
from __future__ import annotations

import re
import signal
import time

import yfinance as yf

from common import DATA, read_csv, write_csv

FIELDS = ["symbol", "sma5", "sma25", "prev_sma5", "prev_sma25", "rsi14", "bars"]
CODE = re.compile(r"^[0-9A-Z]{4,5}$")


def ticker_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in ("holdings.csv", "watchlist.csv", "universe.csv", "quote_universe.csv"):
        for row in read_csv(DATA / name):
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                continue
            ticker = (row.get("yahoo_ticker") or "").strip()
            if not ticker and CODE.fullmatch(symbol):
                ticker = f"{symbol}.T"
            if ticker:
                mapping[symbol] = ticker
    return mapping


def _sma(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, price in zip(values, values[1:]):
        diff = price - prev
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _metrics(closes: list[float]) -> dict[str, str]:
    sma5 = _sma(closes, 5)
    sma25 = _sma(closes, 25)
    prev = closes[:-1]
    prev5 = _sma(prev, 5)
    prev25 = _sma(prev, 25)
    rsi = _rsi(closes, 14)

    def text(value: float | None) -> str:
        return "" if value is None else f"{value:.4f}"

    return {
        "sma5": text(sma5),
        "sma25": text(sma25),
        "prev_sma5": text(prev5),
        "prev_sma25": text(prev25),
        "rsi14": text(rsi),
        "bars": str(len(closes)),
    }


def _closes(frame, ticker: str, multiple: bool) -> list[float]:
    try:
        series = frame[ticker]["Close"] if multiple else frame["Close"]
    except (KeyError, TypeError, AttributeError):
        return []
    values: list[float] = []
    for raw in series.tolist():
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price == price and price > 0:  # NaN を除く
            values.append(price)
    return values


def refresh_technical() -> int:
    mapping = ticker_map()
    inverse: dict[str, str] = {}
    for symbol, ticker in mapping.items():
        inverse.setdefault(ticker, symbol)
    tickers = sorted(inverse)
    rows: list[dict] = []
    print(f"technical tickers={len(tickers)}", flush=True)
    for start in range(0, len(tickers), 40):
        chunk = tickers[start : start + 40]
        def _expire(_signum, _frame):
            raise TimeoutError(chunk[0])

        try:
            signal.signal(signal.SIGALRM, _expire)
            signal.alarm(60)
            frame = yf.download(
                chunk,
                period="3mo",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
                timeout=15,
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
            closes = _closes(frame, ticker, multiple)
            if len(closes) < 6:
                continue
            symbol = inverse[ticker]
            row = {"symbol": symbol}
            row.update(_metrics(closes))
            rows.append(row)
        print(f"  {start + len(chunk)}/{len(tickers)} rows={len(rows)}", flush=True)
        time.sleep(0.3)
    rows.sort(key=lambda row: row["symbol"])
    write_csv(DATA / "technical.csv", rows, FIELDS)
    print(f"OK technical rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(refresh_technical())
