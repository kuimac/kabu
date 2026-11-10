#!/usr/bin/env python3
"""今回取得したテクニカルとファンダメンタルから、売り買い候補を決める。

欠測の項目は使わない。株価や倍率を補完しない。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze
from common import DATA, now_jst, read_csv, to_float, write_csv

PE_CHEAP = 12.0
PE_RICH = 40.0
PBR_CHEAP = 1.0
PBR_RICH = 5.0
TOP_LIMIT = 30
OUTLOOK_GAP = 0.05
OUTLOOK_AGREE = 6.0
MEDIUM_DATE = "2027-06"
LONG_DATE = "2027-12"
_MARKET_NAME = {"n225": "日経平均", "spx": "S&P500", "topix": "TOPIX"}

FIELDS = [
    "as_of",
    "rank",
    "symbol",
    "name",
    "action",
    "score",
    "price",
    "change_pct",
    "tech_signals",
    "fund_signals",
    "decision",
    "sma5",
    "sma25",
    "rsi14",
    "bars",
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
]


def _present(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:
        return None
    return number


def _fund_view(row: dict) -> tuple[float, float, list[str], list[str]]:
    buy_notes: list[str] = []
    sell_notes: list[str] = []
    buy = 0.0
    sell = 0.0
    pe = _present(row.get("trailing_pe"))
    pbr = _present(row.get("price_to_book"))
    eps = _present(row.get("eps"))
    loss = eps is not None and eps < 0
    if loss:
        sell += 10
        sell_notes.append(f"EPS {eps:.2f}（赤字）")
    if pe is not None and pe > 0 and pe <= PE_CHEAP and not loss:
        buy += 8
        buy_notes.append(f"PER {pe:.1f}倍（{PE_CHEAP:.0f}倍以下）")
    if pe is not None and pe >= PE_RICH:
        sell += 8
        sell_notes.append(f"PER {pe:.1f}倍（{PE_RICH:.0f}倍以上）")
    if pbr is not None and pbr > 0 and pbr <= PBR_CHEAP and not loss:
        buy += 8
        buy_notes.append(f"PBR {pbr:.2f}倍（{PBR_CHEAP:.0f}倍以下）")
    if pbr is not None and pbr >= PBR_RICH:
        sell += 8
        sell_notes.append(f"PBR {pbr:.2f}倍（{PBR_RICH:.0f}倍以上）")
    return buy, sell, buy_notes, sell_notes


def _flat_market(tech: dict | None, change: float | None) -> bool:
    """値動きが無いと RSI が 0 や 100 に張り付く。その値は売り買いの決定に使わない。"""
    if not tech:
        return False
    sma5 = _present(tech.get("sma5"))
    sma25 = _present(tech.get("sma25"))
    if sma5 is None or sma25 is None or sma5 <= 0:
        return False
    if abs(sma5 - sma25) / sma5 > 0.002:
        return False
    return change is None or abs(change) < 0.05


def _tech_score(tags: list[tuple[str, str, str]], change: float | None, tech: dict | None) -> float:
    ids = {tag[0] for tag in tags}
    rsi = _present((tech or {}).get("rsi14"))
    score = 0.0
    if "dead" in ids:
        score += 22
    if "rsi_high" in ids and rsi is not None:
        score += 14 + max(0.0, rsi - analyze.RSI_HIGH) * 0.5
    if "rsi_low" in ids and rsi is not None:
        score += 14 + max(0.0, analyze.RSI_LOW - rsi) * 0.5
    if "golden" in ids:
        score += 20
    if "dip" in ids and change is not None:
        score += 12 + min(20.0, max(0.0, -change - 5))
    return score


def _stance(target: float | None, spot: float | None) -> tuple[str, float | None]:
    if target is None or spot is None or spot <= 0:
        return "", None
    gap = target / spot - 1
    if gap >= OUTLOOK_GAP:
        return "強気", gap
    if gap <= -OUTLOOK_GAP:
        return "弱気", gap
    return "中立", gap


def _outlook_rows() -> list[dict]:
    path = DATA / "market_outlook.csv"
    if not path.exists():
        return []
    return read_csv(path)


def _horizon(rows: list[dict], market: str, horizon: str) -> dict | None:
    for row in rows:
        if row.get("market") == market and row.get("horizon_date") == horizon and row.get("target") and row.get("spot"):
            return row
    return None


def _overlay(medium: dict | None, long: dict | None, index_name: str) -> tuple[float, float, str]:
    if medium is None or long is None:
        return 0.0, 0.0, ""
    medium_side, medium_gap = _stance(_present(medium.get("target")), _present(medium.get("spot")))
    long_side, long_gap = _stance(_present(long.get("target")), _present(long.get("spot")))
    if not medium_side or not long_side or medium_gap is None or long_gap is None:
        return 0.0, 0.0, ""
    note = (
        f"{index_name}の中期{medium['horizon_date']}は{float(medium['target']):,.0f}"
        f"（終値比{medium_gap * 100:+.1f}%）、"
        f"長期{long['horizon_date']}は{float(long['target']):,.0f}"
        f"（終値比{long_gap * 100:+.1f}%）"
    )
    if medium_side == long_side and medium_side in {"強気", "弱気"}:
        points = OUTLOOK_AGREE
        text = f"{note}で、どちらも{medium_side}"
        if medium_side == "強気":
            return points, 0.0, text
        return 0.0, points, text
    if medium_side != long_side and "中立" not in {medium_side, long_side}:
        return 0.0, 0.0, note + "で、中期と長期が分かれた"
    one = medium_side if medium_side in {"強気", "弱気"} else long_side
    if one in {"強気", "弱気"}:
        text = f"{note}で、{one}は片方だけ"
        if one == "強気":
            return OUTLOOK_AGREE / 2, 0.0, text
        return 0.0, OUTLOOK_AGREE / 2, text
    return 0.0, 0.0, note + "で、どちらも中立"


def market_overlays() -> dict[str, tuple[float, float, str]]:
    rows = _outlook_rows()
    packs = {
        "jp": _overlay(_horizon(rows, "n225", MEDIUM_DATE), _horizon(rows, "n225", LONG_DATE), "日経平均"),
        "us": _overlay(_horizon(rows, "spx", MEDIUM_DATE), _horizon(rows, "spx", LONG_DATE), "S&P500"),
    }
    return packs


def _region(symbol: str, ticker: str) -> str:
    ticker = (ticker or "").strip()
    if ticker.endswith(".T"):
        return "jp"
    if ticker and "." not in ticker:
        return "us"
    if re.fullmatch(r"[0-9A-Z]{4,5}", symbol or ""):
        return "jp"
    if re.fullmatch(r"[A-Za-z]{1,5}", symbol or ""):
        return "us"
    return ""


def _decision(
    tags: list[tuple[str, str, str]],
    change: float | None,
    tech: dict | None,
    fund_buy: float,
    fund_sell: float,
    buy_notes: list[str],
    sell_notes: list[str],
    market_buy: float = 0.0,
    market_sell: float = 0.0,
    market_note: str = "",
) -> tuple[str, float, str, str]:
    deciding = [tag for tag in tags if tag[2] in {"buy", "sell"}]
    tech_side = analyze.decide_action(deciding) if deciding else ""
    same_side = [tag for tag in deciding if analyze.KIND_ACTION[tag[2]] == tech_side]
    tech_score = _tech_score(same_side, change, tech)
    sentence = ""
    if same_side:
        sentence = analyze.signal_sentence(same_side, change if change is not None else 0.0, None, tech)
    tech_labels = " ".join(tag[1] for tag in same_side)
    def _with_market(parts: list[str], same: float, opposite: float) -> None:
        if not market_note:
            return
        if same > 0:
            parts.append("同じ側の市場予報: " + market_note)
        elif opposite > 0:
            parts.append("逆材料でスコアを下げた: " + market_note)
        else:
            parts.append("市場予報はスコアを動かしていない: " + market_note)

    if tech_side == analyze.SIGNAL_BUY:
        score = max(1.0, tech_score + fund_buy + market_buy - (fund_sell + market_sell) * 0.5)
        parts = [f"テクニカルが買いを決定: {sentence}"]
        if buy_notes:
            parts.append("同じ側の材料: " + "、".join(buy_notes))
        if sell_notes:
            parts.append("逆材料でスコアを下げた: " + "、".join(sell_notes))
        _with_market(parts, market_buy, market_sell)
        return analyze.SIGNAL_BUY, score, tech_labels, "。".join(parts)
    if tech_side == analyze.SIGNAL_SELL:
        score = max(1.0, tech_score + fund_sell + market_sell - (fund_buy + market_buy) * 0.5)
        parts = [f"テクニカルが売りを決定: {sentence}"]
        if sell_notes:
            parts.append("同じ側の材料: " + "、".join(sell_notes))
        if buy_notes:
            parts.append("逆材料でスコアを下げた: " + "、".join(buy_notes))
        _with_market(parts, market_sell, market_buy)
        return analyze.SIGNAL_SELL, score, tech_labels, "。".join(parts)
    if fund_buy >= 8 and fund_sell == 0 and buy_notes:
        score = max(1.0, fund_buy + market_buy - market_sell * 0.5)
        parts = ["ファンダメンタルが買いを決定: " + "、".join(buy_notes)]
        _with_market(parts, market_buy, market_sell)
        return analyze.SIGNAL_BUY, score, "", "。".join(parts)
    if fund_sell >= 8 and fund_buy == 0 and sell_notes:
        score = max(1.0, fund_sell + market_sell - market_buy * 0.5)
        parts = ["ファンダメンタルが売りを決定: " + "、".join(sell_notes)]
        _with_market(parts, market_sell, market_buy)
        return analyze.SIGNAL_SELL, score, "", "。".join(parts)
    watched = [tag for tag in tags if tag[2] not in {"buy", "sell"}]
    looked: list[str] = []
    if watched:
        looked.append(
            analyze.signal_sentence(watched, change if change is not None else 0.0, None, tech)
            + "（売り買いの決定には使っていません）"
        )
    if buy_notes or sell_notes:
        looked.append("材料は分かれたか、基準に届かなかった: " + "、".join(buy_notes + sell_notes))
    if not looked:
        looked.append("買い・売りを決める材料は今回の取得になかった")
    return "", 0.0, tech_labels, "。".join(looked)


def build_symbol_analysis() -> list[dict]:
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    universe = [row for row in read_csv(DATA / "quote_universe.csv") if row.get("symbol")]
    names = {row["symbol"]: row.get("name") or row["symbol"] for row in universe}
    tickers = {row["symbol"]: (row.get("yahoo_ticker") or "").strip() for row in universe}
    for row in read_csv(DATA / "holdings.csv"):
        symbol = (row.get("symbol") or "").strip()
        ticker = (row.get("yahoo_ticker") or "").strip()
        if symbol and ticker:
            tickers.setdefault(symbol, ticker)
    overlays = market_overlays()
    technical = {row["symbol"]: row for row in read_csv(DATA / "technical.csv") if row.get("symbol")}
    fundamentals = {row["symbol"]: row for row in read_csv(DATA / "fundamentals.csv") if row.get("symbol")}
    symbols = sorted(set(names) | set(technical) | set(fundamentals))
    ranked: list[dict] = []
    rest: list[dict] = []
    for symbol in symbols:
        tech = technical.get(symbol)
        fund = fundamentals.get(symbol) or {}
        change = _present(fund.get("change_pct"))
        signal_tech = None if _flat_market(tech, change) else tech
        tags = analyze.representative_tags(0.0 if change is None else change, None, signal_tech)
        # 前日比が無いときに 0% 扱いの押し目・急騰は付けない。representative_tags は
        # 0 をどちらの閾値にも掛けないので、このままで足りる。
        fund_buy, fund_sell, buy_notes, sell_notes = _fund_view(fund)
        region = _region(symbol, tickers.get(symbol, ""))
        market_buy, market_sell, market_note = overlays.get(region, (0.0, 0.0, ""))
        action, score, tech_labels, decision = _decision(
            tags,
            change,
            signal_tech,
            fund_buy,
            fund_sell,
            buy_notes,
            sell_notes,
            market_buy,
            market_sell,
            market_note,
        )
        rsi = _present((tech or {}).get("rsi14"))
        if _flat_market(tech, change) and rsi is not None and (rsi <= analyze.RSI_LOW or rsi >= analyze.RSI_HIGH):
            decision += "。終値が横ばいなので、RSIは判定に使っていません"
        fund_labels = " ".join(buy_notes + sell_notes)
        row = {
            "as_of": as_of,
            "rank": "",
            "symbol": symbol,
            "name": names.get(symbol) or symbol,
            "action": action,
            "score": f"{score:.2f}",
            "price": fund.get("price") or "",
            "change_pct": "" if change is None else f"{change:.2f}",
            "tech_signals": tech_labels,
            "fund_signals": fund_labels,
            "decision": decision,
            "sma5": (tech or {}).get("sma5") or "",
            "sma25": (tech or {}).get("sma25") or "",
            "rsi14": (tech or {}).get("rsi14") or "",
            "bars": (tech or {}).get("bars") or "",
            "trailing_pe": fund.get("trailing_pe") or "",
            "forward_pe": fund.get("forward_pe") or "",
            "price_to_book": fund.get("price_to_book") or "",
            "eps": fund.get("eps") or "",
            "eps_forward": fund.get("eps_forward") or "",
            "market_cap": fund.get("market_cap") or "",
            "div_yield": fund.get("div_yield") or "",
            "book_value": fund.get("book_value") or "",
            "week52_high": fund.get("week52_high") or "",
            "week52_low": fund.get("week52_low") or "",
        }
        if action in {analyze.SIGNAL_BUY, analyze.SIGNAL_SELL} and score > 0:
            ranked.append(row)
        else:
            rest.append(row)
    ranked.sort(key=lambda row: (-to_float(row["score"]), row["name"]))
    for index, row in enumerate(ranked, start=1):
        row["rank"] = str(index) if index <= TOP_LIMIT else ""
    ordered = ranked + rest
    return ordered


def main() -> int:
    rows = build_symbol_analysis()
    write_csv(DATA / "symbol_analysis.csv", rows, FIELDS)
    picked = [row for row in rows if row["rank"]]
    buys = sum(1 for row in picked if row["action"] == analyze.SIGNAL_BUY)
    sells = sum(1 for row in picked if row["action"] == analyze.SIGNAL_SELL)
    tech_rows = sum(1 for row in rows if row["sma5"] or row["rsi14"])
    pe_rows = sum(1 for row in rows if row["trailing_pe"])
    print(
        f"OK analysis rows={len(rows)} technical={tech_rows} pe={pe_rows} "
        f"top={len(picked)} buy={buys} sell={sells}"
    )
    for row in picked:
        print(f"  {row['rank']:>2} {row['action']} {row['score']} {row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
