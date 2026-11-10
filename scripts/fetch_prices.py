"""保有・監視銘柄の価格取得。"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    DATA,
    MUFG_NAV_URL,
    ensure_data_dir,
    fund_market_value,
    implied_nav,
    now_jst,
    read_csv,
    to_float,
    write_csv,
)
from polite_http import shared_session
from quote_universe import refresh_quote_universe
from scrape_web import fetch_yahoo_fund_nav


def fetch_mufg_nav(association_code: str) -> dict | None:
    if not association_code:
        return None
    url = MUFG_NAV_URL.format(code=association_code)
    try:
        # APIもホスト単位で間隔を空ける
        res = shared_session().get(url, timeout=20)
        payload = res.json()
        datasets = payload.get("datasets") or []
        if not datasets:
            return None
        item = datasets[0]
        as_of = item.get("base_date", "")
        if as_of and len(as_of) == 8 and as_of.isdigit():
            as_of = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"
        return {
            "price": float(item["nav"]),
            "as_of": as_of,
            "change": item.get("cmp_prev_day", ""),
            "change_pct": item.get("percentage_change", ""),
            "source": "mufg_api",
            "name": item.get("fund_name", ""),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"WARN MUFG {association_code}: {exc}")
        return None


def price_currency(ticker: str) -> str:
    ticker = ticker or ""
    if ticker.endswith(".T") or ticker.startswith("^"):
        return "JPY"
    return "USD"


def fetch_yahoo_price(ticker: str) -> dict | None:
    if not ticker:
        return None
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist.empty:
            return None
        finite: list[tuple[object, float]] = []
        for ts, raw in zip(hist.index, hist["Close"].tolist()):
            try:
                price = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(price) and price > 0:
                finite.append((ts, price))
        if not finite:
            return None
        as_of_raw, price = finite[-1]
        prev = finite[-2][1] if len(finite) > 1 else price
        change = price - prev
        change_pct = change / prev * 100 if prev else 0.0
        as_of = as_of_raw.to_pydatetime().strftime("%Y-%m-%d")
        return {
            "price": price,
            "as_of": as_of,
            "change": f"{change:.4f}",
            "change_pct": f"{change_pct:.2f}",
            "source": "yfinance",
            "name": ticker,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"WARN yfinance {ticker}: {exc}")
        return None


def fetch_usdjpy() -> float | None:
    try:
        hist = yf.Ticker("USDJPY=X").history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        print(f"WARN USDJPY: {exc}")
        return None


def update_holding_valuations(
    holdings: list[dict], prices: dict[str, dict], usdjpy: float | None
) -> list[dict]:
    updated = []
    for h in holdings:
        symbol = h["symbol"]
        units = to_float(h.get("units"))
        cost = to_float(h.get("cost_value"))
        asset_type = h.get("asset_type", "")
        mult = to_float(h.get("unit_multiplier"), 1000 if asset_type == "fund" else 1)
        denom = to_float(h.get("nav_denominator"), 10000 if asset_type == "fund" else 1)
        px = prices.get(symbol)
        if px and px.get("price") is not None:
            price = float(px["price"])
            if asset_type == "fund":
                # implied_from_holdings のときは評価額をいじらない（循環更新防止）
                if px.get("source") == "implied_from_holdings":
                    updated.append(h)
                    continue
                market = fund_market_value(units, price, mult, denom)
            elif h.get("yahoo_ticker") == "NVDA":
                if usdjpy and usdjpy > 0:
                    market = units * price * usdjpy
                else:
                    market = to_float(h.get("market_value"))
            else:
                market = units * price
            h = dict(h)
            h["market_value"] = f"{market:.0f}"
            h["unrealized_pnl"] = f"{market - cost:.0f}"
        updated.append(h)
    return updated


def main() -> int:
    ensure_data_dir()
    holdings = read_csv(DATA / "holdings.csv")
    watchlist = read_csv(DATA / "watchlist.csv")
    latest: list[dict] = []
    price_map: dict[str, dict] = {}
    today = now_jst().strftime("%Y-%m-%d")

    targets = []
    for h in holdings:
        targets.append(
            {
                "symbol": h["symbol"],
                "name": h["name"],
                "asset_type": h.get("asset_type", ""),
                "association_code": h.get("association_code", ""),
                "yahoo_ticker": h.get("yahoo_ticker", ""),
                "units": h.get("units", ""),
                "market_value": h.get("market_value", ""),
                "unit_multiplier": h.get("unit_multiplier", ""),
                "nav_denominator": h.get("nav_denominator", ""),
            }
        )
    for w in watchlist:
        targets.append(
            {
                "symbol": w["symbol"],
                "name": w["name"],
                "asset_type": w.get("asset_type", ""),
                "association_code": w.get("association_code", ""),
                "yahoo_ticker": w.get("yahoo_ticker", ""),
            }
        )
    seen = {row["symbol"] for row in targets}
    for extra in read_csv(DATA / "universe.csv"):
        if extra.get("symbol") in seen:
            continue
        seen.add(extra.get("symbol"))
        targets.append(
            {
                "symbol": extra["symbol"],
                "name": extra["name"],
                "asset_type": extra.get("asset_type", ""),
                "association_code": extra.get("association_code", ""),
                "yahoo_ticker": extra.get("yahoo_ticker", ""),
            }
        )
    # 保有・監視・比較はそのまま。スクリーナーが列挙できる東証銘柄を足す。
    preset_prices: dict[str, dict] = {}
    for attempt in range(3):
        try:
            preset_prices = refresh_quote_universe()
            break
        except Exception as exc:  # noqa: BLE001
            print(f"WARN quote universe attempt {attempt + 1}: {exc}", flush=True)
            time.sleep(5)
    if not preset_prices:
        from quote_universe import _history_prices

        stored = [row for row in read_csv(DATA / "quote_universe.csv") if row.get("symbol") and row.get("yahoo_ticker")]
        print(f"WARN quote universe: batching stored prices n={len(stored)}", flush=True)
        found = _history_prices([row["yahoo_ticker"] for row in stored])
        for row in stored:
            got = found.get(row["yahoo_ticker"])
            if got:
                preset_prices[row["symbol"]] = got
        print(f"OK stored batch prices={len(preset_prices)}", flush=True)
    for extra in read_csv(DATA / "quote_universe.csv"):
        symbol = (extra.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        targets.append(
            {
                "symbol": symbol,
                "name": extra.get("name", ""),
                "asset_type": extra.get("asset_type", ""),
                "association_code": extra.get("association_code", ""),
                "yahoo_ticker": extra.get("yahoo_ticker", ""),
            }
        )

    history_rows = []
    previous_by_symbol = {row["symbol"]: row for row in read_csv(DATA / "prices_latest.csv") if row.get("symbol")}

    def _finite_price(value: object) -> float | None:
        try:
            price = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if math.isfinite(price) and price > 0:
            return price
        return None

    for t in targets:
        symbol = t["symbol"]
        got = preset_prices.get(symbol)
        # 1) MUFG公式API（eMAXIS等）
        if t.get("association_code") and t.get("asset_type") == "fund":
            got = fetch_mufg_nav(t["association_code"])
        # 2) 投信は Yahoo スクレイピング（間隔制御あり）で補完
        if got is None and t.get("association_code") and t.get("asset_type") == "fund":
            got = fetch_yahoo_fund_nav(t["association_code"], shared_session())
        # 3) 個別株・ETFは yfinance
        if got is None and t.get("yahoo_ticker"):
            got = fetch_yahoo_price(t["yahoo_ticker"])
        # 4) 最終手段: 保有評価から暗黙NAV
        if got is None and t.get("asset_type") == "fund":
            units = to_float(t.get("units"))
            market = to_float(t.get("market_value"))
            mult = to_float(t.get("unit_multiplier"), 1000)
            denom = to_float(t.get("nav_denominator"), 10000)
            if units > 0 and market > 0:
                nav = implied_nav(units, market, mult, denom)
                got = {
                    "price": nav,
                    "as_of": today,
                    "change": "",
                    "change_pct": "",
                    "source": "implied_from_holdings",
                    "name": t["name"],
                }
                print(f"INFO {symbol}: implied NAV {nav:.2f}")
        if got is not None and _finite_price(got.get("price")) is None:
            print(f"WARN {symbol}: non-finite price")
            got = None
        prev = previous_by_symbol.get(symbol)
        if got is not None and prev and (prev.get("as_of") or "")[:10] > (got.get("as_of") or "")[:10]:
            print(f"WARN {symbol}: new bar {got.get('as_of')} is older than {prev.get('as_of')}")
            got = None
        if got is None and prev and _finite_price(prev.get("price")) is not None:
            print(f"WARN {symbol}: keep previous price {prev['price']}")
            latest.append(prev)
            price_map[symbol] = {"price": float(prev["price"]), "source": prev.get("source", ""), "as_of": prev.get("as_of", "")}
            continue
        if got is None:
            print(f"WARN no price for {symbol}")
            continue

        currency = price_currency(t.get("yahoo_ticker") or "")
        row = {
            "symbol": symbol,
            "name": t["name"],
            "price": f"{float(got['price']):.4f}".rstrip("0").rstrip(".")
            if isinstance(got["price"], float)
            else got["price"],
            "currency": currency,
            "as_of": got.get("as_of") or today,
            "source": got.get("source", ""),
            "change": got.get("change", ""),
            "change_pct": got.get("change_pct", ""),
        }
        # normalize price string
        row["price"] = f"{float(got['price']):.4f}"
        latest.append(row)
        price_map[symbol] = {"price": float(got["price"]), **got}
        history_rows.append(
            {
                "date": today,
                "symbol": symbol,
                "price": row["price"],
                "currency": currency,
                "source": row["source"],
            }
        )
        print(f"OK {symbol}: {row['price']} ({row['source']})")

    write_csv(
        DATA / "prices_latest.csv",
        latest,
        ["symbol", "name", "price", "currency", "as_of", "source", "change", "change_pct"],
    )

    # 同日・同銘柄は再取得した価格で置き、新しい銘柄は追加する
    existing = read_csv(DATA / "prices_history.csv")
    fresh_keys = {(r["date"], r["symbol"]) for r in history_rows}
    merged = [r for r in existing if (r.get("date"), r.get("symbol")) not in fresh_keys]
    merged.extend(history_rows)
    merged.sort(key=lambda r: (r.get("date", ""), r.get("symbol", "")))
    write_csv(
        DATA / "prices_history.csv",
        merged,
        ["date", "symbol", "price", "currency", "source"],
    )

    # 保有評価の再計算
    if holdings:
        usdjpy = fetch_usdjpy()
        if usdjpy:
            print(f"OK USDJPY: {usdjpy:.3f}")
            price_map["USDJPY"] = {"price": usdjpy, "source": "yfinance"}
            latest.append(
                {
                    "symbol": "USDJPY",
                    "name": "米ドル円",
                    "price": f"{usdjpy:.4f}",
                    "currency": "JPY",
                    "as_of": today,
                    "source": "yfinance",
                    "change": "",
                    "change_pct": "",
                }
            )
            write_csv(
                DATA / "prices_latest.csv",
                latest,
                ["symbol", "name", "price", "currency", "as_of", "source", "change", "change_pct"],
            )
        updated = update_holding_valuations(holdings, price_map, usdjpy)
        write_csv(
            DATA / "holdings.csv",
            updated,
            list(holdings[0].keys()),
        )

    return 0 if latest else 1


if __name__ == "__main__":
    raise SystemExit(main())
