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


def pnl_pct(cost: float, market: float) -> float:
    if cost <= 0:
        return 0.0
    return (market - cost) / cost * 100


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
                    "signal": "CONSIDER_SELL",
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
                    "signal": "WATCH",
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
                    "signal": "HOLD",
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
                    "signal": "HOLD",
                    "priority": "low",
                    "reason": f"損益 {pct:+.1f}%。特別なアクションなし。",
                    "suggested_action": "積立を継続。",
                }
            )

    # 監視銘柄の短期変化
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
                    "signal": "CONSIDER_BUY",
                    "priority": "medium",
                    "reason": f"監視銘柄が前日比 {change_pct:.1f}%。押し目検討。",
                    "suggested_action": "PayPay残高があれば市場時間中に即時購入可。銀行→PayPay入金は即時。",
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
                "signal": "CASH_TOPUP",
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
                "signal": "HOLD",
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
                "signal": "WATCH",
                "priority": "medium",
                "reason": f"S&P500積立が月 {sp_monthly:,}円とフローの約 {sp_monthly/monthly_need*100:.0f}%を占める。",
                "suggested_action": "オルカン/先進国とのバランスを定期確認。",
            }
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: (priority_rank.get(s["priority"], 9), s["symbol"]))
    return signals


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
        if s["signal"] != "CONSIDER_SELL":
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
    cashflow = build_cashflow(accums, signals, today_jst())

    write_csv(
        DATA / "signals.csv",
        signals,
        ["as_of", "symbol", "name", "signal", "priority", "reason", "suggested_action"],
    )
    write_csv(
        DATA / "cashflow.csv",
        cashflow,
        ["date", "event_type", "symbol", "amount_yen", "direction", "note"],
    )

    print(f"signals={len(signals)} cashflow={len(cashflow)} monthly_need={monthly_need:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
