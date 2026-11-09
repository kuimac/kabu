"""CSVから GitHub Pages 用の静的サイトを生成。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DOCS, ensure_data_dir, now_jst, read_csv, to_float


def yen(n: float) -> str:
    return f"{n:,.0f}"


def pct(n: float) -> str:
    return f"{n:+.1f}%"


def build_chart_payload(holdings: list[dict], history: list[dict]) -> dict:
    labels = [h["name"] for h in holdings]
    values = [to_float(h.get("market_value")) for h in holdings]
    pnls = [to_float(h.get("unrealized_pnl")) for h in holdings]
    short_names = [h["name"][:18] for h in holdings]

    # 銘柄ごとの直近履歴
    by_symbol: dict[str, list] = {}
    for row in history:
        by_symbol.setdefault(row["symbol"], []).append(
            {"date": row["date"], "price": to_float(row["price"])}
        )
    for s in by_symbol:
        by_symbol[s].sort(key=lambda x: x["date"])

    return {
        "allocationLabels": short_names,
        "allocationValues": values,
        "pnlLabels": short_names,
        "pnlValues": pnls,
        "history": by_symbol,
        "holdingSymbols": [h["symbol"] for h in holdings],
    }


def render_html(
    holdings: list[dict],
    market: list[dict],
    news: list[dict],
    signals: list[dict],
    cashflow: list[dict],
    accums: list[dict],
    watchlist: list[dict],
    prices: list[dict],
    cash_rows: list[dict],
    chart_payload: dict,
) -> str:
    updated = now_jst().strftime("%Y-%m-%d %H:%M JST")
    total_market = sum(to_float(h.get("market_value")) for h in holdings)
    total_pnl = sum(to_float(h.get("unrealized_pnl")) for h in holdings)
    total_cost = sum(to_float(h.get("cost_value")) for h in holdings)
    monthly = sum(to_float(a.get("monthly_estimate_yen")) for a in accums)
    cash = to_float(cash_rows[0].get("paypay_balance_yen")) if cash_rows else 0

    urgent = [s for s in signals if s.get("priority") == "high"]
    medium = [s for s in signals if s.get("priority") == "medium"]
    # トピック用ニュース: JPXを優先し、足りなければ他ソース
    jpx_news = [n for n in news if "JPX" in n.get("source", "")]
    other_news = [n for n in news if "JPX" not in n.get("source", "")]
    topic_news = (jpx_news + other_news)[:8]

    holding_rows = []
    for h in holdings:
        market_v = to_float(h.get("market_value"))
        pnl = to_float(h.get("unrealized_pnl"))
        cost = to_float(h.get("cost_value"))
        ratio = market_v / total_market * 100 if total_market else 0
        pnl_p = pnl / cost * 100 if cost else 0
        cls = "neg" if pnl < 0 else "pos" if pnl > 0 else ""
        holding_rows.append(
            f"<tr><td>{h['name']}</td><td>{h.get('nisa_type','')}</td>"
            f"<td class='num'>{h.get('units','')}</td>"
            f"<td class='num'>{yen(market_v)}</td>"
            f"<td class='num {cls}'>{yen(pnl)} ({pct(pnl_p)})</td>"
            f"<td class='num'>{ratio:.1f}%</td></tr>"
        )

    signal_rows = []
    for s in signals:
        signal_rows.append(
            f"<tr class='prio-{s.get('priority','')}'><td><span class='badge'>{s['signal']}</span></td>"
            f"<td>{s['name']}</td><td>{s['reason']}</td><td>{s['suggested_action']}</td></tr>"
        )

    topic_cards: list[str] = []
    for u in urgent:
        topic_cards.append(
            "<article class='topic-card topic-urgent'>"
            f"<p class='topic-tag'>緊急 · {u['signal']}</p>"
            f"<h3>{u['name']}</h3>"
            f"<p>{u['reason']}</p>"
            f"<p class='topic-action'>{u.get('suggested_action','')}</p>"
            "</article>"
        )
    for m in medium[:3]:
        topic_cards.append(
            "<article class='topic-card topic-watch'>"
            f"<p class='topic-tag'>注目 · {m['signal']}</p>"
            f"<h3>{m['name']}</h3>"
            f"<p>{m['reason']}</p>"
            "</article>"
        )
    for n in topic_news[:6]:
        published = (n.get("published") or "")[:16]
        meta = " · ".join(x for x in [n.get("source", ""), published] if x)
        topic_cards.append(
            "<article class='topic-card topic-news'>"
            f"<p class='topic-tag'>ニュース · {n.get('source','')}</p>"
            f"<h3><a href='{n['link']}' target='_blank' rel='noopener'>{n['title']}</a></h3>"
            f"<p class='meta'>{meta}</p>"
            "</article>"
        )
    if not topic_cards:
        topic_cards.append("<p class='muted'>表示できるトピックがありません。</p>")
    topics_html = "".join(topic_cards)

    cashflow_rows = []
    for c in cashflow[:40]:
        cashflow_rows.append(
            f"<tr><td>{c['date']}</td><td>{c['event_type']}</td><td>{c.get('symbol','')}</td>"
            f"<td class='num'>{c.get('amount_yen','')}</td><td>{c.get('note','')}</td></tr>"
        )

    accum_rows = []
    for a in accums:
        accum_rows.append(
            f"<tr><td>{a['name']}</td><td>{a['schedule']}</td>"
            f"<td class='num'>{yen(to_float(a['amount_yen']))}</td>"
            f"<td>{a.get('nisa_type','')}</td>"
            f"<td class='num'>{yen(to_float(a.get('monthly_estimate_yen')))}</td></tr>"
        )

    watch_rows = []
    price_map = {p["symbol"]: p for p in prices}
    for w in watchlist:
        p = price_map.get(w["symbol"], {})
        ch = to_float(p.get("change_pct"))
        cls = "neg" if ch < 0 else "pos" if ch > 0 else ""
        watch_rows.append(
            f"<tr><td>{w['name']}</td><td class='num'>{p.get('price','—')}</td>"
            f"<td class='num {cls}'>{p.get('change_pct','—')}</td><td>{w.get('reason','')}</td></tr>"
        )

    market_cards = []
    for m in market:
        ch = to_float(m.get("change_pct"))
        cls = "neg" if ch < 0 else "pos" if ch > 0 else ""
        market_cards.append(
            f"<article class='metric'><h3>{m['name']}</h3>"
            f"<p class='big'>{m['price']}</p>"
            f"<p class='{cls}'>{m.get('change','')} ({m.get('change_pct','')}%)</p>"
            f"<p class='spark'>{m.get('sparkline','')}</p></article>"
        )

    chart_json = json.dumps(chart_payload, ensure_ascii=False)
    urgent_count = len(urgent)
    news_count = min(6, len(topic_news))

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NISA 判断支援ダッシュボード</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+JP:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="assets/app.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js" defer></script>
  <script src="assets/charts.js" defer></script>
</head>
<body>
  <header class="site-header">
    <div class="wrap">
      <p class="brand">NISA Desk</p>
      <h1>判断支援ダッシュボード</h1>
      <p class="sub">PayPay証券の注文は手動。最終更新 {updated}</p>
    </div>
  </header>

  <main class="wrap">
    <section class="hero-topics" id="top">
      <div class="topics-header">
        <p class="eyebrow">Topics</p>
        <h2>本日のトピック</h2>
        <p class="sub">緊急シグナル {urgent_count}件 · ニュース話題 {news_count}件</p>
      </div>
      <div class="topics-grid">
        {topics_html}
      </div>
    </section>

    <section class="metrics-row">
      <h2 class="sr-only">市場・残高サマリー</h2>
      {''.join(market_cards)}
      <article class="metric">
        <h3>保有合計</h3>
        <p class="big">{yen(total_market)}</p>
        <p class="{'neg' if total_pnl < 0 else 'pos'}">{yen(total_pnl)} / 取得 {yen(total_cost)}</p>
      </article>
      <article class="metric">
        <h3>PayPay残高（手入力）</h3>
        <p class="big">{yen(cash)}</p>
        <p class="muted">月次積立目安 {yen(monthly)}</p>
      </article>
    </section>

    <section>
      <h2>保有銘柄</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>銘柄</th><th>NISA</th><th>口数</th><th>評価額</th><th>損益</th><th>比率</th></tr></thead>
          <tbody>{''.join(holding_rows)}</tbody>
        </table>
      </div>
      <div class="charts-grid">
        <div class="chart-card"><h3>構成比</h3><canvas id="allocChart"></canvas></div>
        <div class="chart-card"><h3>銘柄別損益</h3><canvas id="pnlChart"></canvas></div>
      </div>
    </section>

    <section>
      <h2>売買シグナル</h2>
      <p class="muted">自動発注はしません。PayPay証券で手動執行してください。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>シグナル</th><th>対象</th><th>理由</th><th>推奨アクション</th></tr></thead>
          <tbody>{''.join(signal_rows)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>積立設定</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>銘柄</th><th>頻度</th><th>金額</th><th>枠</th><th>月次目安</th></tr></thead>
          <tbody>{''.join(accum_rows)}</tbody>
        </table>
      </div>
      <p class="muted">月次合計目安 {yen(monthly)} 円（毎日積立は営業日〜暦日換算の概算）</p>
    </section>

    <section>
      <h2>資金スケジュール</h2>
      <p class="muted">売却→PayPay着金（+2〜3営業日）→銀行引出（さらに+2〜3営業日）。買い直しはPayPay残高があれば市場時間中に即時。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>日付</th><th>種別</th><th>銘柄</th><th>金額</th><th>メモ</th></tr></thead>
          <tbody>{''.join(cashflow_rows)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>監視・おすすめ銘柄</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>銘柄</th><th>価格</th><th>変化%</th><th>理由</th></tr></thead>
          <tbody>{''.join(watch_rows)}</tbody>
        </table>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <p>本ページは投資助言ではありません。最終判断はご自身で行ってください。</p>
      <p>口座番号・銀行情報などの個人識別情報は含みません。データはCSVで管理しています。</p>
      <p>更新: {updated}</p>
    </div>
  </footer>

  <script id="chart-data" type="application/json">{chart_json}</script>
</body>
</html>
"""


def main() -> int:
    ensure_data_dir()
    holdings = read_csv(DATA / "holdings.csv")
    market = read_csv(DATA / "market.csv")
    news = read_csv(DATA / "news.csv")
    signals = read_csv(DATA / "signals.csv")
    cashflow = read_csv(DATA / "cashflow.csv")
    accums = read_csv(DATA / "accumulations.csv")
    watchlist = read_csv(DATA / "watchlist.csv")
    prices = read_csv(DATA / "prices_latest.csv")
    cash_rows = read_csv(DATA / "cash_balance.csv")
    history = read_csv(DATA / "prices_history.csv")
    chart_payload = build_chart_payload(holdings, history)

    html = render_html(
        holdings,
        market,
        news,
        signals,
        cashflow,
        accums,
        watchlist,
        prices,
        cash_rows,
        chart_payload,
    )
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {DOCS / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
