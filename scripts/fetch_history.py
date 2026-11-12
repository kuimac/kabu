#!/usr/bin/env python3
"""保存済みの足の続きだけを足す。

日次は data/history/ の最後の日付の翌日から今日まで。
時間足と5分足は data/bars/1h と data/bars/5m。未保存の銘柄は直近セッションだけ。
それより古い分足は取らない。保存済みの足はダウンロードし直さない。
"""
from __future__ import annotations

import csv
import io
import math
import signal
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from common import DATA, append_csv, now_jst, read_csv, today_jst, write_csv
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
BARS_INDEX_FIELDS = ["symbol", "interval", "start", "end", "bars"]
DAILY_FIELDS = ["date", "price"]
BAR_FIELDS = ["datetime", "open", "high", "low", "close", "volume"]
HISTORY_DIR = DATA / "history"
BARS_DIR = DATA / "bars"
UTC = timezone.utc
CHUNK = 40
PAUSE_SEC = 0.5


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


def plan_daily(last: str | None, today: date) -> tuple[str, str] | None:
    """日次の取得範囲。戻り値は (period|start, 値)。保存済みの翌日が今日より後なら何も取らない。"""
    if not last:
        return ("period", "5y")
    try:
        last_day = date.fromisoformat(last[:10])
    except ValueError:
        return ("period", "5y")
    if last_day > today:
        return None
    if last_day == today:
        return ("start", today.isoformat())
    return ("start", (last_day + timedelta(days=1)).isoformat())


def plan_intraday(last: str | None, now: datetime, step: timedelta) -> tuple[str, str] | None:
    """分足・時間足の取得範囲。未保存なら直近1日。保存済みなら最後の足の日付から、ただし足1本分より新しければスキップ。"""
    if not last:
        return ("period", "1d")
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return ("period", "1d")
    if now.astimezone(UTC) - last_dt < step:
        return None
    return ("start", last_dt.strftime("%Y-%m-%d"))


def latest_session(rows: list[dict], day_key: str = "local_day") -> list[dict]:
    """未保存の分足を、返ってきたうち最新のセッション日だけに限る。"""
    if not rows:
        return []
    day = max(row.get(day_key) or row.get("datetime", "")[:10] for row in rows)
    return [row for row in rows if (row.get(day_key) or row.get("datetime", "")[:10]) == day]


def _check_plans() -> None:
    assert plan_daily(None, date(2026, 11, 12)) == ("period", "5y")
    assert plan_daily("2026-11-10", date(2026, 11, 12)) == ("start", "2026-11-11")
    assert plan_daily("2026-11-12", date(2026, 11, 12)) == ("start", "2026-11-12")
    now = datetime(2026, 11, 12, 2, 10, tzinfo=UTC)
    assert plan_intraday(None, now, timedelta(minutes=5)) == ("period", "1d")
    assert plan_intraday("2026-11-12T02:00:00Z", now, timedelta(minutes=5)) == ("start", "2026-11-12")
    assert plan_intraday("2026-11-12T02:08:00Z", now, timedelta(minutes=5)) is None
    kept = latest_session(
        [
            {"local_day": "2026-11-11", "datetime": "2026-11-11T06:00:00Z"},
            {"local_day": "2026-11-12", "datetime": "2026-11-12T00:00:00Z"},
        ]
    )
    assert [row["local_day"] for row in kept] == ["2026-11-12"]
    spiked = drop_return_spikes([("2026-11-10", 100.0), ("2026-11-11", 10.0), ("2026-11-12", 101.0)])
    assert [day for day, _ in spiked] == ["2026-11-10", "2026-11-12"]


def _finite(raw: object) -> float | None:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _price(value: float) -> str:
    return f"{value:.4f}"


def _volume(raw: object) -> str:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value) or value < 0:
        return ""
    return str(int(value))


def _utc_stamp(ts) -> tuple[str, str]:
    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=UTC)
    local_day = dt.strftime("%Y-%m-%d")
    utc = dt.astimezone(UTC).replace(second=0, microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ"), local_day


def _slice(frame, ticker: str):
    if frame is None or getattr(frame, "empty", True):
        return None
    columns = frame.columns
    if isinstance(columns, pd.MultiIndex):
        if ticker not in set(columns.get_level_values(0)):
            return None
        sub = frame[ticker]
    else:
        sub = frame
    if "Close" not in getattr(sub, "columns", []):
        return None
    return sub


def _daily_points(frame, ticker: str) -> list[tuple[str, float]]:
    sub = _slice(frame, ticker)
    if sub is None:
        return []
    points: list[tuple[str, float]] = []
    for ts, raw in zip(sub.index, sub["Close"].tolist()):
        price = _finite(raw)
        if price is None:
            continue
        points.append((str(ts)[:10], price))
    points.sort()
    deduped: list[tuple[str, float]] = []
    for day, price in points:
        if deduped and deduped[-1][0] == day:
            deduped[-1] = (day, price)
        else:
            deduped.append((day, price))
    return deduped


def _intraday_rows(frame, ticker: str) -> list[dict]:
    sub = _slice(frame, ticker)
    if sub is None:
        return []
    rows: list[dict] = []
    opens = sub["Open"].tolist() if "Open" in sub.columns else [None] * len(sub.index)
    highs = sub["High"].tolist() if "High" in sub.columns else [None] * len(sub.index)
    lows = sub["Low"].tolist() if "Low" in sub.columns else [None] * len(sub.index)
    volumes = sub["Volume"].tolist() if "Volume" in sub.columns else [None] * len(sub.index)
    for ts, raw, opened, high, low, volume in zip(sub.index, sub["Close"].tolist(), opens, highs, lows, volumes):
        close = _finite(raw)
        if close is None:
            continue
        stamp, local_day = _utc_stamp(ts)
        open_px = _finite(opened) or close
        high_px = _finite(high) or close
        low_px = _finite(low) or close
        rows.append(
            {
                "datetime": stamp,
                "local_day": local_day,
                "open": _price(open_px),
                "high": _price(high_px),
                "low": _price(low_px),
                "close": _price(close),
                "volume": _volume(volume),
            }
        )
    rows.sort(key=lambda row: row["datetime"])
    deduped: list[dict] = []
    for row in rows:
        if deduped and deduped[-1]["datetime"] == row["datetime"]:
            deduped[-1] = row
        else:
            deduped.append(row)
    return deduped


def _last_key(path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    last = ""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line
    if not last or last.lower().startswith("date"):
        return None
    return last.split(",", 1)[0].strip()


def _csv_line(row: dict, fields: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="")
    writer.writerow([row.get(field, "") for field in fields])
    return buffer.getvalue()


def _newline(data: bytes) -> bytes:
    if b"\r\n" in data:
        return b"\r\n"
    if data.endswith(b"\n"):
        return b"\n"
    return b"\r\n"


def _replace_last_line(path, line: str) -> None:
    data = path.read_bytes()
    newline = _newline(data)
    body = data[:-2] if data.endswith(b"\r\n") else data[:-1] if data.endswith(b"\n") else data
    head, sep, _old = body.rpartition(b"\n")
    if head.endswith(b"\r"):
        head = head[:-1]
    encoded = line.encode("utf-8")
    if sep:
        updated = head + newline + encoded + newline
    else:
        updated = encoded + newline
    path.write_bytes(updated)


def upsert_rows(path, rows: list[dict], fields: list[str], key: str) -> int:
    """最後の足より新しい行だけを足す。最後の足と同じ時刻は、値が変わったときだけその1行を置き換える。"""
    if not rows:
        return 0
    if not path.exists() or path.stat().st_size == 0:
        write_csv(path, rows, fields)
        return len(rows)
    last = _last_key(path)
    if last is None:
        write_csv(path, rows, fields)
        return len(rows)
    fresh: list[dict] = []
    replacement: dict | None = None
    for row in rows:
        stamp = row[key]
        if stamp < last:
            continue
        if stamp == last:
            replacement = row
            continue
        fresh.append(row)
    changed = 0
    if replacement is not None:
        line = _csv_line(replacement, fields)
        current = _last_line(path)
        if current != line:
            _replace_last_line(path, line)
            changed += 1
    if fresh:
        append_csv(path, fresh, fields)
        changed += len(fresh)
    return changed


def _last_line(path) -> str:
    data = path.read_bytes()
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    line = data.rpartition(b"\n")[2]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line.decode("utf-8")


def _last_daily(path) -> tuple[str, float] | None:
    line = ""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                line = raw.strip()
    if not line or line.lower().startswith("date"):
        return None
    day, price_text, *_rest = line.split(",")
    try:
        return day, float(price_text)
    except ValueError:
        return None


def symbols_for_fetch() -> dict[str, str]:
    mapping = ticker_map()
    code = __import__("re").compile(r"^[0-9A-Z]{4,5}$")
    if HISTORY_DIR.exists():
        for path in HISTORY_DIR.glob("*.csv"):
            symbol = path.stem
            if symbol not in mapping and code.fullmatch(symbol) and _safe(symbol):
                mapping[symbol] = f"{symbol}.T"
    return {symbol: ticker for symbol, ticker in mapping.items() if _safe(symbol) and ticker}


def _safe(symbol: str) -> bool:
    return bool(symbol) and "/" not in symbol and "\\" not in symbol and ".." not in symbol


def _download(tickers: list[str], interval: str, mode: str, value: str):
    kwargs = {
        "interval": interval,
        "group_by": "ticker",
        "threads": False,
        "progress": False,
        "auto_adjust": True,
        "timeout": 30,
    }
    if mode == "period":
        if interval != "1d" and value != "1d":
            raise RuntimeError("分足・時間足の初回は直近セッションだけ")
        kwargs["period"] = value
    else:
        kwargs["start"] = value

    def _expire(_signum, _frame):
        raise TimeoutError(tickers[0])

    try:
        signal.signal(signal.SIGALRM, _expire)
        signal.alarm(120)
        return yf.download(tickers, **kwargs)
    finally:
        signal.alarm(0)


def _fetch_group(pairs: list[tuple[str, str]], interval: str, mode: str, value: str, depth: int = 0) -> int:
    if not pairs:
        return 0
    try:
        frame = _download([ticker for ticker, _symbol in pairs], interval, mode, value)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN {interval} {pairs[0][0]}.. n={len(pairs)}: {exc}", flush=True)
        if len(pairs) == 1 or depth >= 4:
            return 0
        time.sleep(2.0)
        mid = len(pairs) // 2
        return _fetch_group(pairs[:mid], interval, mode, value, depth + 1) + _fetch_group(
            pairs[mid:], interval, mode, value, depth + 1
        )
    if frame is None or getattr(frame, "empty", True):
        return 0
    written = 0
    for ticker, symbol in pairs:
        if interval == "1d":
            points = _daily_points(frame, ticker)
            if mode == "period":
                points = drop_return_spikes(points)
            else:
                last = _last_daily(HISTORY_DIR / f"{symbol}.csv")
                if last is not None:
                    downloaded = {day for day, _price_value in points}
                    points = drop_return_spikes([last] + [point for point in points if point[0] >= last[0]])
                    kept: list[tuple[str, float]] = []
                    for day, price in points:
                        if day < last[0]:
                            continue
                        if day == last[0] and (day not in downloaded or f"{price:.4f}" == f"{last[1]:.4f}"):
                            continue
                        kept.append((day, price))
                    points = kept
            rows = [{"date": day, "price": _price(price)} for day, price in points]
            written += upsert_rows(HISTORY_DIR / f"{symbol}.csv", rows, DAILY_FIELDS, "date")
            continue
        rows = _intraday_rows(frame, ticker)
        if mode == "period":
            rows = latest_session(rows)
        for row in rows:
            row.pop("local_day", None)
        folder = BARS_DIR / interval
        written += upsert_rows(folder / f"{symbol}.csv", rows, BAR_FIELDS, "datetime")
    return written


def _run_interval(interval: str, groups: dict[tuple[str, str], list[tuple[str, str]]]) -> int:
    written = 0
    jobs = sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))
    total = sum(len(pairs) for pairs in groups.values())
    done = 0
    for (mode, value), pairs in jobs:
        print(f"{interval} {mode}={value} symbols={len(pairs)}", flush=True)
        for start in range(0, len(pairs), CHUNK):
            chunk = pairs[start : start + CHUNK]
            written += _fetch_group(chunk, interval, mode, value)
            done += len(chunk)
            print(f"  {interval} {done}/{total} changed={written}", flush=True)
            time.sleep(PAUSE_SEC)
    return written


def _group_symbols(mapping: dict[str, str], interval: str, now: datetime) -> dict[tuple[str, str], list[tuple[str, str]]]:
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    step = timedelta(hours=1) if interval == "1h" else timedelta(minutes=5)
    folder = HISTORY_DIR if interval == "1d" else BARS_DIR / interval
    for symbol, ticker in mapping.items():
        last = _last_key(folder / f"{symbol}.csv")
        plan = plan_daily(last, now.date()) if interval == "1d" else plan_intraday(last, now, step)
        if plan is None:
            continue
        groups.setdefault(plan, []).append((ticker, symbol))
    return groups


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


def write_bars_index() -> int:
    rows: list[dict] = []
    for interval in ("1h", "5m"):
        folder = BARS_DIR / interval
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.csv")):
            points = read_csv(path)
            if not points:
                continue
            rows.append(
                {
                    "symbol": path.stem,
                    "interval": interval,
                    "start": points[0].get("datetime", ""),
                    "end": points[-1].get("datetime", ""),
                    "bars": str(len(points)),
                }
            )
    write_csv(DATA / "bars_index.csv", rows, BARS_INDEX_FIELDS)
    print(f"OK bars index={len(rows)}", flush=True)
    return len(rows)


def refresh_history() -> int:
    _check_plans()
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (BARS_DIR / "1h").mkdir(parents=True, exist_ok=True)
    (BARS_DIR / "5m").mkdir(parents=True, exist_ok=True)
    mapping = symbols_for_fetch()
    now = now_jst()
    print(f"history symbols={len(mapping)} as_of={now.isoformat(timespec='minutes')}", flush=True)
    for interval in ("1d", "1h", "5m"):
        groups = _group_symbols(mapping, interval, now)
        pending = sum(len(pairs) for pairs in groups.values())
        print(f"{interval} pending={pending}", flush=True)
        _run_interval(interval, groups)
    write_index()
    write_bars_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(refresh_history())
