"""保有・価格・積立からシグナルと資金スケジュールを生成。"""
from __future__ import annotations

import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    DATA,
    add_business_days,
    ensure_data_dir,
    is_business_day,
    now_jst,
    read_csv,
    to_float,
    today_jst,
    write_csv,
)

# 閾値（透明なルール）
WATCH_LOSS_PCT = -10.0
SELL_REVIEW_LOSS_PCT = -20.0
BUY_DIP_PCT = -5.0  # 監視銘柄の短期下落で検討

# 表示用シグナル／アクション（日本語）
SIGNAL_BUY = "買い検討"
SIGNAL_SELL = "売り検討"
SIGNAL_HOLD = "保有継続"
SIGNAL_WATCH = "要監視"
SIGNAL_CASH = "入金推奨"
SIGNAL_WAIT = "見送り"
SIGNAL_REF = "参考監視"
SURGE_PCT = 5.0
RSI_LOW = 30.0
RSI_HIGH = 70.0

# 判定の優先順。先に一致した種類が売り・買い・見送りを決める。
REPRESENTATIVE = [
    ("loss_sell", "含み損売り", "sell"),
    ("dead", "デッドクロス", "sell"),
    ("rsi_high", "RSI買われすぎ", "sell"),
    ("rsi_low", "RSI売られすぎ", "buy"),
    ("golden", "ゴールデンクロス", "buy"),
    ("dip", "押し目", "buy"),
    ("loss_watch", "含み損監視", "watch"),
    ("surge", "急騰", "wait"),
]
KIND_ACTION = {
    "sell": SIGNAL_SELL,
    "buy": SIGNAL_BUY,
    "watch": SIGNAL_WATCH,
    "wait": SIGNAL_WAIT,
}

# 監視銘柄のおすすめスコア用カテゴリ
WATCH_META = {
    "1306": {"kind": "japan_etf", "paypay_tradable": True, "diversify": "japan"},
    "2558": {"kind": "global_etf", "paypay_tradable": True, "diversify": "global"},
    "1540": {"kind": "gold_etf", "paypay_tradable": True, "diversify": "gold"},
    "spy": {"kind": "us_etf_ref", "paypay_tradable": False, "diversify": "us_ref"},
    "qqq": {"kind": "us_etf_ref", "paypay_tradable": False, "diversify": "us_ref"},
}


def pnl_pct(cost: float, market: float) -> float:
    if cost <= 0:
        return 0.0
    return (market - cost) / cost * 100


def round_yen_1000(amount: float) -> int:
    if amount <= 0:
        return 0
    return int(amount // 1000 * 1000)


def portfolio_flags(holdings: list[dict]) -> dict:
    total = sum(to_float(h.get("market_value")) for h in holdings) or 1.0
    by = {h["symbol"]: to_float(h.get("market_value")) for h in holdings}
    sp = by.get("slim_sp500", 0) / total
    acwi = by.get("slim_acwi", 0) / total
    theme = (by.get("nissei_ai", 0) + by.get("daiwa_india", 0) + by.get("ihi", 0) + by.get("nvda", 0)) / total
    return {
        "total": total,
        "sp_heavy": sp >= 0.25,
        "acwi_light": acwi < 0.15,
        "theme_heavy": theme >= 0.35,
        "equity_heavy": True,  # 現状ほぼ株式のみ
    }


def load_technical() -> dict[str, dict]:
    path = DATA / "technical.csv"
    if not path.exists():
        return {}
    return {row["symbol"]: row for row in read_csv(path) if row.get("symbol")}


def _present(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return to_float(text)


def representative_tags(change: float, pnl: float | None, tech: dict | None) -> list[tuple[str, str, str]]:
    """一致した代表的シグナルを、判定優先順で返す。"""
    found: set[str] = set()
    if pnl is not None and pnl <= SELL_REVIEW_LOSS_PCT:
        found.add("loss_sell")
    elif pnl is not None and pnl <= WATCH_LOSS_PCT:
        found.add("loss_watch")
    if tech:
        sma5 = _present(tech.get("sma5"))
        sma25 = _present(tech.get("sma25"))
        prev5 = _present(tech.get("prev_sma5"))
        prev25 = _present(tech.get("prev_sma25"))
        rsi = _present(tech.get("rsi14"))
        if None not in (sma5, sma25, prev5, prev25):
            if prev5 <= prev25 and sma5 > sma25:
                found.add("golden")
            elif prev5 >= prev25 and sma5 < sma25:
                found.add("dead")
        if rsi is not None and rsi <= RSI_LOW:
            found.add("rsi_low")
        elif rsi is not None and rsi >= RSI_HIGH:
            found.add("rsi_high")
    if change <= BUY_DIP_PCT:
        found.add("dip")
    elif change >= SURGE_PCT:
        found.add("surge")
    return [item for item in REPRESENTATIVE if item[0] in found]


def signal_sentence(tags: list[tuple[str, str, str]], change: float, pnl: float | None, tech: dict | None) -> str:
    ids = {tag[0] for tag in tags}
    sma5 = _present((tech or {}).get("sma5"))
    sma25 = _present((tech or {}).get("sma25"))
    rsi = _present((tech or {}).get("rsi14"))
    parts: list[str] = []
    if "golden" in ids and sma5 is not None and sma25 is not None:
        parts.append(f"ゴールデンクロス（5日線 {sma5:.2f} が25日線 {sma25:.2f} を上抜け）")
    if "dead" in ids and sma5 is not None and sma25 is not None:
        parts.append(f"デッドクロス（5日線 {sma5:.2f} が25日線 {sma25:.2f} を下抜け）")
    if "rsi_low" in ids and rsi is not None:
        parts.append(f"RSI(14) {rsi:.1f} で売られすぎ")
    if "rsi_high" in ids and rsi is not None:
        parts.append(f"RSI(14) {rsi:.1f} で買われすぎ")
    if "dip" in ids:
        parts.append(f"前日比 {change:+.1f}% の押し目")
    if "surge" in ids:
        parts.append(f"前日比 {change:+.1f}% の急騰")
    if "loss_sell" in ids and pnl is not None:
        parts.append(f"含み損 {pnl:+.1f}%")
    if "loss_watch" in ids and pnl is not None:
        parts.append(f"含み損 {pnl:+.1f}% で要監視")
    return "。".join(parts)


def decide_action(tags: list[tuple[str, str, str]]) -> str:
    if not tags:
        return ""
    return KIND_ACTION[tags[0][2]]


def trade_candidates(holdings: list[dict], prices: list[dict]) -> list[dict]:
    """代表的シグナルが点灯した銘柄だけを返す。"""
    holding_map = {row["symbol"]: row for row in holdings}
    technical = load_technical()
    candidates: list[dict] = []
    for price in prices:
        symbol = (price.get("symbol") or "").strip()
        if not symbol or symbol in SKIP_SYMBOLS or not str(price.get("price") or "").strip():
            continue
        holding = holding_map.get(symbol)
        change = to_float(price.get("change_pct"))
        name = (holding.get("name") if holding else "") or price.get("name") or symbol
        market = to_float(holding.get("market_value")) if holding else 0.0
        pnl = pnl_pct(to_float(holding.get("cost_value")), market) if holding else None
        tech = technical.get(symbol)
        tags = representative_tags(change, pnl, tech)
        if not tags:
            continue
        kind = tags[0][2]
        candidates.append(
            {
                "symbol": symbol,
                "name": name,
                "side": "sell" if kind == "sell" else "buy" if kind == "buy" else "other",
                "action": decide_action(tags),
                "signals": " ".join(tag[1] for tag in tags),
                "detail": signal_sentence(tags, change, pnl, tech),
                "change": change,
                "pnl": pnl,
                "market": market,
                "price": price.get("price", ""),
                "change_pct": price.get("change_pct", ""),
            }
        )
    return candidates


def build_watch_actions(
    watchlist: list[dict],
    prices: list[dict],
    holdings: list[dict],
    cash: float,
    monthly_need: float,
) -> list[dict]:
    """監視銘柄をスコア順に並べ、売買金額目安を付ける。"""
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    price_map = {p["symbol"]: p for p in prices}
    flags = portfolio_flags(holdings)
    # 積立1ヶ月分を残した余りを買い余力とする
    surplus = max(0.0, cash - monthly_need)
    reserve_note = f"PayPay残高{cash:,.0f}円 − 月次積立目安{monthly_need:,.0f}円 = 余力{surplus:,.0f}円"

    scored: list[dict] = []
    for w in watchlist:
        symbol = w["symbol"]
        meta = WATCH_META.get(symbol, {"kind": "other", "paypay_tradable": True, "diversify": ""})
        p = price_map.get(symbol, {})
        change_pct = to_float(p.get("change_pct"))
        price = to_float(p.get("price"))
        score = 50.0
        # 下落ほど買い優先
        score += max(-change_pct, 0) * 4
        score -= max(change_pct, 0) * 2

        reasons = [w.get("reason", "")]
        if flags["sp_heavy"] and meta["diversify"] == "global":
            score += 18
            reasons.append("保有がS&P寄りのため全世界分散を優先")
        if flags["acwi_light"] and meta["diversify"] == "global":
            score += 10
            reasons.append("オルカン系比率が低め")
        if flags["theme_heavy"] and meta["diversify"] in {"global", "japan"}:
            score += 8
            reasons.append("テーマ・個別比率が高めのため指数へ寄せる候補")
        if flags["equity_heavy"] and meta["diversify"] == "gold":
            score += 6
            reasons.append("株式偏重の分散候補（コモディティ）")
        if meta["diversify"] == "japan":
            score += 4
            reasons.append("日本株エクスポージャの確認用")

        tradable = meta.get("paypay_tradable", True)
        if not tradable:
            score -= 25
            action = SIGNAL_REF
            buy_yen = 0
            sell_yen = 0
            action_detail = "参考監視のみ（米国ETF。PayPay NISAでの直接購入は取扱確認）。相当なら既存のS&P/オルカン積立で代替。"
        elif surplus < 5000:
            action = SIGNAL_HOLD
            buy_yen = 0
            sell_yen = 0
            action_detail = f"買い余力不足。{reserve_note}。必要なら銀行→PayPayへ入金後に再評価。"
        elif change_pct <= BUY_DIP_PCT:
            action = SIGNAL_BUY
            # 余力の25〜40%を目安（下限5,000・上限30,000）
            raw = surplus * (0.40 if change_pct <= -8 else 0.25)
            buy_yen = min(30000, max(5000, round_yen_1000(raw)))
            sell_yen = 0
            action_detail = f"目安 {buy_yen:,}円の買い検討（押し目 {change_pct:+.1f}%）。市場時間中なら即時。"
            score += 12
        elif change_pct >= 3.0:
            action = SIGNAL_WAIT
            buy_yen = 0
            sell_yen = 0
            action_detail = f"短期上昇中（{change_pct:+.1f}%）。追っかけ買いは見送り、押し目待ち。"
            score -= 8
        else:
            action = SIGNAL_BUY
            buy_yen = min(20000, max(5000, round_yen_1000(surplus * 0.15))) if surplus >= 5000 else 0
            if buy_yen == 0:
                action = SIGNAL_HOLD
                action_detail = f"様子見。{reserve_note}"
            else:
                action_detail = f"目安 {buy_yen:,}円の少額買い検討（分散・積立の補完）。急がなくてよい。"
            sell_yen = 0

        scored.append(
            {
                "as_of": as_of,
                "rank": 0,
                "symbol": symbol,
                "name": w["name"],
                "score": f"{score:.1f}",
                "action": action,
                "buy_yen": str(buy_yen),
                "sell_yen": str(sell_yen),
                "price": p.get("price", ""),
                "change_pct": p.get("change_pct", ""),
                "signals": "",
                "action_detail": action_detail,
                "reason": " / ".join(r for r in reasons if r),
                "_score": score,
            }
        )

    technical = load_technical()
    holding_map = {row["symbol"]: row for row in holdings}
    for row in scored:
        holding = holding_map.get(row["symbol"])
        change = to_float(row.get("change_pct"))
        market = to_float(holding.get("market_value")) if holding else 0.0
        pnl = pnl_pct(to_float(holding.get("cost_value")), market) if holding else None
        tech = technical.get(row["symbol"])
        tags = representative_tags(change, pnl, tech)
        if not tags:
            continue
        row["signals"] = " ".join(tag[1] for tag in tags)
        row["action"] = decide_action(tags)
        row["reason"] = "代表的シグナル: " + "、".join(tag[1] for tag in tags)
        row["action_detail"] = signal_sentence(tags, change, pnl, tech)
        if row["action"] == SIGNAL_SELL:
            row["buy_yen"] = "0"
            row["sell_yen"] = str(int(round(market))) if market else "0"
        elif row["action"] != SIGNAL_BUY:
            row["buy_yen"] = "0"
            row["sell_yen"] = "0"

    listed = {row["symbol"] for row in scored}
    for candidate in trade_candidates(holdings, prices):
        if candidate["symbol"] in listed:
            continue
        action = candidate["action"]
        detail = candidate["detail"]
        if action == SIGNAL_SELL:
            loss = -(candidate["pnl"] or 0.0)
            score = 80.0 + min(20.0, loss * 0.3)
            buy_yen = 0
            sell_yen = int(round(candidate["market"])) if candidate["market"] else 0
        elif action == SIGNAL_BUY:
            score = 70.0 + max(-candidate["change"], 0) * 2
            sell_yen = 0
            if surplus < 5000:
                buy_yen = 0
                detail += f"。買い余力不足。{reserve_note}"
            else:
                raw = surplus * (0.40 if candidate["change"] <= -8 else 0.25)
                buy_yen = min(30000, max(5000, round_yen_1000(raw)))
        else:
            score = 40.0
            buy_yen = 0
            sell_yen = 0
        reason = "代表的シグナル: " + candidate["signals"].replace(" ", "、")
        scored.append(
            {
                "as_of": as_of,
                "rank": 0,
                "symbol": candidate["symbol"],
                "name": candidate["name"],
                "score": f"{score:.1f}",
                "action": action,
                "buy_yen": str(buy_yen),
                "sell_yen": str(sell_yen),
                "price": candidate["price"],
                "change_pct": candidate["change_pct"],
                "signals": candidate["signals"],
                "action_detail": detail,
                "reason": reason,
                "_score": score,
            }
        )

    scored.sort(key=lambda r: r["_score"], reverse=True)

    # 買い金額が余力を超えないよう上位から再配分
    remaining = surplus
    for row in scored:
        buy = int(to_float(row["buy_yen"]))
        if row["action"] not in {SIGNAL_BUY} or buy <= 0:
            row["buy_yen"] = "0"
            continue
        if remaining < 5000:
            row["buy_yen"] = "0"
            row["action_detail"] = f"{row.get('action_detail') or ''} 買い余力不足。{reserve_note}".strip()
            continue
        allocated = min(buy, round_yen_1000(remaining))
        if allocated < 5000:
            row["buy_yen"] = "0"
            row["action_detail"] = f"{row.get('action_detail') or ''} 余力残り僅少。{reserve_note}".strip()
            continue
        row["buy_yen"] = str(allocated)
        row["action_detail"] = (
            f"おすすめ順に基づき目安 {allocated:,}円の買い"
            f"（単価 {row.get('price') or '—'}、前日比 {row.get('change_pct') or '—'}%）。"
            " PayPayで手動注文。"
        )
        remaining -= allocated

    for i, row in enumerate(scored, start=1):
        row["rank"] = str(i)
        row.pop("_score", None)
    return scored


def build_signals(holdings: list[dict], prices: list[dict], watchlist: list[dict], cash: float, monthly_need: float) -> list[dict]:
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    price_map = {p["symbol"]: p for p in prices}
    signals: list[dict] = []

    for h in holdings:
        symbol = h["symbol"]
        name = h["name"]
        cost = to_float(h.get("cost_value"))
        market = to_float(h.get("market_value"))
        pct = pnl_pct(cost, market)
        if pct <= SELL_REVIEW_LOSS_PCT:
            signals.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "name": name,
                    "signal": SIGNAL_SELL,
                    "priority": "high",
                    "reason": f"含み損 {pct:.1f}%（閾値 {SELL_REVIEW_LOSS_PCT:.0f}%以下）。方針見直し候補。",
                    "suggested_action": "PayPay証券で一部売却を検討。売却代金は2〜3営業日後にPayPay口座へ。",
                }
            )
        elif pct <= WATCH_LOSS_PCT:
            signals.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "name": name,
                    "signal": SIGNAL_WATCH,
                    "priority": "medium",
                    "reason": f"含み損 {pct:.1f}%。積立継続か配分見直しを確認。",
                    "suggested_action": "積立設定と比率を確認。慌てて売却しない。",
                }
            )
        elif pct >= 15:
            signals.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "name": name,
                    "signal": SIGNAL_HOLD,
                    "priority": "low",
                    "reason": f"含み益 {pct:.1f}%。利確より長期保有が基本方針。",
                    "suggested_action": "現状維持。必要なら一部リバランスのみ検討。",
                }
            )
        else:
            signals.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "name": name,
                    "signal": SIGNAL_HOLD,
                    "priority": "low",
                    "reason": f"損益 {pct:+.1f}%。特別なアクションなし。",
                    "suggested_action": "積立を継続。",
                }
            )

    # 監視銘柄の短期変化（詳細な金額は watch_actions.csv）
    for w in watchlist:
        p = price_map.get(w["symbol"])
        if not p:
            continue
        change_pct = to_float(p.get("change_pct"))
        if change_pct <= BUY_DIP_PCT:
            signals.append(
                {
                    "as_of": as_of,
                    "symbol": w["symbol"],
                    "name": w["name"],
                    "signal": SIGNAL_BUY,
                    "priority": "medium",
                    "reason": f"監視銘柄が前日比 {change_pct:.1f}%。押し目検討。",
                    "suggested_action": "監視おすすめ欄の金額目安を参照。PayPayで手動注文。",
                }
            )

    # 現金余力
    if cash < monthly_need:
        shortage = monthly_need - cash
        signals.append(
            {
                "as_of": as_of,
                "symbol": "CASH",
                "name": "PayPay口座残高",
                "signal": SIGNAL_CASH,
                "priority": "high",
                "reason": f"残高 {cash:,.0f}円 < 月次積立目安 {monthly_need:,.0f}円（不足 {shortage:,.0f}円）。",
                "suggested_action": "積立日前に銀行からPayPay口座へ入金（即時）。",
            }
        )
    else:
        signals.append(
            {
                "as_of": as_of,
                "symbol": "CASH",
                "name": "PayPay口座残高",
                "signal": SIGNAL_HOLD,
                "priority": "low",
                "reason": f"残高 {cash:,.0f}円で月次積立目安 {monthly_need:,.0f}円をカバー。",
                "suggested_action": "追加入金は任意。",
            }
        )

    # S&P集中の注意
    sp_monthly = 50000
    if monthly_need > 0 and sp_monthly / monthly_need >= 0.35:
        signals.append(
            {
                "as_of": as_of,
                "symbol": "slim_sp500",
                "name": "積立フロー集中",
                "signal": SIGNAL_WATCH,
                "priority": "medium",
                "reason": f"S&P500積立が月 {sp_monthly:,}円とフローの約 {sp_monthly/monthly_need*100:.0f}%を占める。",
                "suggested_action": "オルカン/先進国とのバランスを定期確認。",
            }
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: (priority_rank.get(s["priority"], 9), s["symbol"]))
    return signals


RANK_LIMIT = 10
SKIP_SYMBOLS = {"USDJPY", "CASH"}


def rank_trade_signals(
    holdings: list[dict],
    prices: list[dict],
    watchlist: list[dict],
    limit: int = RANK_LIMIT,
) -> list[dict]:
    """保有・未保有を混ぜ、買いと売りの強さ上位を返す。"""
    as_of = now_jst().strftime("%Y-%m-%d %H:%M:%S%z")
    universe: dict[str, dict] = {}

    def ensure(symbol: str, name: str) -> dict | None:
        if not symbol or symbol in SKIP_SYMBOLS:
            return None
        row = universe.setdefault(
            symbol,
            {"symbol": symbol, "name": name or symbol, "held": False, "pnl": None, "change": None},
        )
        if name and row["name"] == symbol:
            row["name"] = name
        return row

    for holding in holdings:
        row = ensure(holding.get("symbol", ""), holding.get("name", ""))
        if row is None:
            continue
        row["held"] = True
        row["name"] = holding.get("name") or row["name"]
        row["pnl"] = pnl_pct(to_float(holding.get("cost_value")), to_float(holding.get("market_value")))
    for item in watchlist:
        row = ensure(item.get("symbol", ""), item.get("name", ""))
        if row is not None and item.get("name"):
            if not row["held"]:
                row["name"] = item["name"]
    for price in prices:
        row = ensure(price.get("symbol", ""), price.get("name", ""))
        if row is None:
            continue
        if price.get("name") and row["name"] == row["symbol"]:
            row["name"] = price["name"]
        row["change"] = to_float(price.get("change_pct"))

    def sell_score(row: dict) -> float:
        if row["held"] and row["pnl"] is not None:
            return max(0.0, -row["pnl"])
        change = row["change"] if row["change"] is not None else 0.0
        return max(0.0, change)

    def buy_score(row: dict) -> float:
        if row["held"] and row["pnl"] is not None and row["pnl"] <= SELL_REVIEW_LOSS_PCT:
            return 0.0
        change = row["change"] if row["change"] is not None else 0.0
        return max(0.0, -change)

    def reason(side: str, row: dict) -> str:
        change = row["change"]
        change_text = "前日比なし" if change is None else f"前日比 {change:+.1f}%"
        if side == "buy":
            return f"{change_text}。短期の下落幅を買いの強さにしている。"
        if row["held"] and row["pnl"] is not None:
            return f"含み損 {row['pnl']:+.1f}%。保有の損失幅を売りの強さにしている。"
        return f"{change_text}。未保有の上昇幅を売り・見送りの強さにしている。"

    ranked: list[dict] = []
    for side, score_of in (("buy", buy_score), ("sell", sell_score)):
        scored = []
        for row in universe.values():
            score = score_of(row)
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        for index, (score, row) in enumerate(scored[:limit], start=1):
            ranked.append(
                {
                    "as_of": as_of,
                    "side": side,
                    "rank": str(index),
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "held": "保有" if row["held"] else "未保有",
                    "score": f"{score:.1f}",
                    "change_pct": "" if row["change"] is None else f"{row['change']:.2f}",
                    "pnl_pct": "" if row["pnl"] is None else f"{row['pnl']:.2f}",
                    "reason": reason(side, row),
                }
            )
    return ranked


def monthly_accumulation_total(accums: list[dict]) -> float:
    total = 0.0
    for a in accums:
        est = to_float(a.get("monthly_estimate_yen"))
        if est > 0:
            total += est
        elif a.get("schedule") == "daily":
            total += to_float(a.get("amount_yen")) * 22
        else:
            total += to_float(a.get("amount_yen"))
    return total


def build_cashflow(accums: list[dict], signals: list[dict], start: date) -> list[dict]:
    rows: list[dict] = []
    # 向こう45日の積立予定
    for offset in range(0, 46):
        d = start + timedelta(days=offset)
        for a in accums:
            amount = to_float(a.get("amount_yen"))
            schedule = a.get("schedule")
            if schedule == "daily" and is_business_day(d):
                rows.append(
                    {
                        "date": d.isoformat(),
                        "event_type": "accumulation",
                        "symbol": a["symbol"],
                        "amount_yen": f"{amount:.0f}",
                        "direction": "out",
                        "note": f"積立 {a['name']}（{a.get('nisa_type','')}）PayPay即時引き落とし想定",
                    }
                )
            elif schedule == "monthly":
                day = int(to_float(a.get("day_of_month"), 28))
                last = calendar.monthrange(d.year, d.month)[1]
                target = min(day, last)
                if d.day == target:
                    # 休日なら翌営業日にずらす表示
                    exec_day = d
                    if not is_business_day(exec_day):
                        exec_day = add_business_days(exec_day, 1)
                        if exec_day.month != d.month:
                            # 月末跨ぎは前営業日へ
                            exec_day = d
                            while not is_business_day(exec_day) and exec_day.day > 1:
                                exec_day -= timedelta(days=1)
                    rows.append(
                        {
                            "date": exec_day.isoformat(),
                            "event_type": "accumulation",
                            "symbol": a["symbol"],
                            "amount_yen": f"{amount:.0f}",
                            "direction": "out",
                            "note": f"月次積立 {a['name']}（指定日{day}日）",
                        }
                    )

    # 売却検討がある場合の着金シミュレーション（仮想・今日売却想定）
    for s in signals:
        if s["signal"] != SIGNAL_SELL:
            continue
        sell_day = start if is_business_day(start) else add_business_days(start, 1)
        paypay_credit = add_business_days(sell_day, 3)  # 2〜3営業日の保守側
        bank_credit = add_business_days(paypay_credit, 3)
        rows.append(
            {
                "date": sell_day.isoformat(),
                "event_type": "sell_sim",
                "symbol": s["symbol"],
                "amount_yen": "",
                "direction": "info",
                "note": f"仮に今日売却した場合の起点（{s['name']}）",
            }
        )
        rows.append(
            {
                "date": paypay_credit.isoformat(),
                "event_type": "paypay_credit",
                "symbol": s["symbol"],
                "amount_yen": "",
                "direction": "in",
                "note": "売却代金のPayPay口座着金目安（+3営業日・保守）",
            }
        )
        rows.append(
            {
                "date": bank_credit.isoformat(),
                "event_type": "bank_withdraw",
                "symbol": s["symbol"],
                "amount_yen": "",
                "direction": "in",
                "note": "PayPay→銀行引出の着金目安（さらに+3営業日）。買い直しならPayPay内で即時利用可",
            }
        )

    rows.sort(key=lambda r: (r["date"], r["event_type"], r["symbol"]))
    return rows


def main() -> int:
    ensure_data_dir()
    holdings = read_csv(DATA / "holdings.csv")
    prices = read_csv(DATA / "prices_latest.csv")
    watchlist = read_csv(DATA / "watchlist.csv")
    accums = read_csv(DATA / "accumulations.csv")
    cash_rows = read_csv(DATA / "cash_balance.csv")
    cash = to_float(cash_rows[0].get("paypay_balance_yen")) if cash_rows else 0.0
    monthly_need = monthly_accumulation_total(accums)

    signals = build_signals(holdings, prices, watchlist, cash, monthly_need)
    watch_actions = build_watch_actions(watchlist, prices, holdings, cash, monthly_need)
    cashflow = build_cashflow(accums, signals, today_jst())

    write_csv(
        DATA / "signals.csv",
        signals,
        ["as_of", "symbol", "name", "signal", "priority", "reason", "suggested_action"],
    )
    write_csv(
        DATA / "watch_actions.csv",
        watch_actions,
        [
            "as_of",
            "rank",
            "symbol",
            "name",
            "score",
            "action",
            "buy_yen",
            "sell_yen",
            "price",
            "change_pct",
            "signals",
            "action_detail",
            "reason",
        ],
    )
    write_csv(
        DATA / "cashflow.csv",
        cashflow,
        ["date", "event_type", "symbol", "amount_yen", "direction", "note"],
    )
    ranks = rank_trade_signals(holdings, prices, watchlist)
    write_csv(
        DATA / "signal_ranks.csv",
        ranks,
        ["as_of", "side", "rank", "symbol", "name", "held", "score", "change_pct", "pnl_pct", "reason"],
    )

    print(
        f"signals={len(signals)} watch_actions={len(watch_actions)} "
        f"cashflow={len(cashflow)} ranks={len(ranks)} monthly_need={monthly_need:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
