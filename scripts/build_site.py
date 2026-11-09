"""CSVから GitHub Pages 用の静的サイトを生成。"""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze
from common import DATA, DOCS, ensure_data_dir, now_jst, read_csv, to_float

PREVIEW_LIMIT = 5
ATTR_ORDER = ["国内投信", "国内株", "米国株", "国内ETF", "米国ETF"]
BUY_KINDS = {"買付", "買い", "buy"}
SUBPAGES = [
    ("instruments.html", "銘柄一覧", "instruments"),
    ("holdings.html", "保有", "holdings"),
    ("trades.html", "売買履歴", "trades"),
]


def esc(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
    )


def yen(n: float) -> str:
    return f"{n:,.0f}"


def signed_yen(n: float) -> str:
    return f"{n:+,.0f}"


def pnl_class(n: float) -> str:
    if n < 0:
        return "neg"
    if n > 0:
        return "pos"
    return ""


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def format_stored_pct(raw: str) -> str:
    try:
        return format_pct(float(raw))
    except (TypeError, ValueError):
        return "—"


def menubar(label: str, links: list[tuple[str, str]], current: str | None = None) -> str:
    parts = []
    for href, text in links:
        current_attr = ' aria-current="page"' if current and href == current else ""
        parts.append(f'<a href="{esc(href)}"{current_attr}>{esc(text)}</a>')
    return f'<nav class="section-menu" aria-label="{esc(label)}">{"".join(parts)}</nav>'


def sidemenu(current: str) -> str:
    def link(href: str, text: str, key: str) -> str:
        current_attr = ' aria-current="page"' if key == current else ""
        return f'<a href="{esc(href)}"{current_attr}>{esc(text)}</a>'

    children = "".join(link(href, text, key) for href, text, key in SUBPAGES)
    sections = [
        ("index.html#market", "市場", "market"),
        ("index.html#signals", "売買シグナル", "signals"),
        ("index.html#accum", "積立", "accum"),
        ("index.html#cashflow", "資金スケジュール", "cashflow"),
        ("index.html#watch", "監視銘柄", "watch"),
    ]
    rest = "".join(link(href, text, key) for href, text, key in sections)
    return (
        '<aside id="sidemenu" class="sidemenu" aria-label="ページ">'
        '<p class="sidemenu-label">メニュー</p>'
        + link("index.html#top", "トップ", "home")
        + '<div class="sidemenu-group"><p class="sidemenu-sublabel">下層ページ</p>'
        + children
        + "</div>"
        + rest
        + "</aside>"
    )


def layout(title: str, current: str, body: str, updated: str, chart_json: str | None) -> str:
    chart_tag = ""
    chart_scripts = ""
    if chart_json is not None:
        safe_json = chart_json.replace("<", "\\u003c")
        chart_tag = f'<script id="chart-data" type="application/json">{safe_json}</script>'
        chart_scripts = (
            '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js" defer></script>'
            '<script src="assets/charts.js" defer></script>'
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n'
        "<head>\n"
        '  <meta charset="UTF-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"  <title>{esc(title)}</title>\n"
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
        '  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+JP:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet" />\n'
        '  <link rel="stylesheet" href="assets/app.css" />\n'
        "</head>\n"
        "<body>\n"
        '<button class="sidemenu-backdrop" type="button" data-menu-close aria-label="メニューを閉じる"></button>\n'
        '<div class="shell">\n'
        + sidemenu(current)
        + '\n<div class="page">\n'
        '  <header class="site-header">\n'
        '    <div class="wrap header-bar">\n'
        '      <button class="menu-toggle" type="button" data-menu-toggle aria-expanded="false" aria-controls="sidemenu">メニュー</button>\n'
        "      <div>\n"
        '        <p class="brand">NISA Desk</p>\n'
        f"        <h1>{esc(title)}</h1>\n"
        f'        <p class="sub">PayPay証券の注文は手動。最終更新 {esc(updated)}</p>\n'
        "      </div>\n"
        "    </div>\n"
        "  </header>\n"
        '  <main class="wrap" id="content">\n'
        + body
        + "\n  </main>\n"
        '  <footer class="site-footer">\n'
        '    <div class="wrap">\n'
        "      <p>本ページは投資助言ではありません。最終判断はご自身で行ってください。</p>\n"
        "      <p>口座番号・銀行情報などの個人識別情報は含みません。データはCSVで管理しています。</p>\n"
        f"      <p>更新: {esc(updated)}</p>\n"
        "    </div>\n"
        "  </footer>\n"
        "</div>\n"
        "</div>\n"
        + chart_tag
        + "\n"
        + chart_scripts
        + '<script src="assets/desk.js" defer></script>\n'
        "</body>\n"
        "</html>\n"
    )


def attribute_of(asset_type: str, ticker: str) -> str:
    ticker = ticker or ""
    if asset_type == "fund":
        return "国内投信"
    if asset_type == "etf":
        return "国内ETF" if ticker.endswith(".T") else "米国ETF"
    if asset_type == "stock":
        return "国内株" if ticker.endswith(".T") else "米国株"
    return "その他"


def instrument_code(row: dict) -> str:
    code = (row.get("association_code") or "").strip()
    if code:
        return code
    ticker = (row.get("yahoo_ticker") or "").strip()
    if ticker:
        return ticker
    return (row.get("symbol") or "").strip()


def ordered_attrs(rows: list[dict]) -> list[str]:
    present = {row.get("attribute") or "" for row in rows}
    present.discard("")
    ordered = [name for name in ATTR_ORDER if name in present]
    ordered.extend(sorted(present - set(ATTR_ORDER)))
    return ordered


def build_catalog(holdings: list[dict], watchlist: list[dict], prices: list[dict]) -> list[dict]:
    names = {row["symbol"]: row.get("name", "") for row in prices}
    seen: set[str] = set()
    rows: list[dict] = []

    def add(src: dict, kind: str) -> None:
        symbol = (src.get("symbol") or "").strip()
        if not symbol or symbol == "USDJPY" or symbol in seen:
            return
        seen.add(symbol)
        ticker = (src.get("yahoo_ticker") or "").strip()
        rows.append(
            {
                "symbol": symbol,
                "name": src.get("name") or names.get(symbol) or symbol,
                "code": instrument_code(src),
                "attribute": attribute_of(src.get("asset_type") or "", ticker),
                "kind": kind,
            }
        )

    for row in holdings:
        add(row, "保有")
    for row in watchlist:
        add(row, "監視")
    for row in prices:
        add(row, "価格のみ")
    return rows


def purchase_date_for(symbol: str, trades: list[dict]) -> str:
    found: list[str] = []
    for trade in trades:
        if trade.get("symbol") != symbol:
            continue
        explicit = (trade.get("purchase_date") or "").strip()
        if explicit:
            found.append(explicit)
        elif trade.get("kind") in BUY_KINDS and (trade.get("as_of") or "").strip():
            found.append(trade["as_of"].strip())
    return min(found) if found else ""


def price_unit(holding: dict) -> str:
    if holding.get("asset_type") == "fund":
        denom = to_float(holding.get("nav_denominator"), 10000)
        if denom == 10000:
            return "円/1万口"
        return f"円/{int(denom)}口"
    return "円/株"


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def unit_prices(holding: dict) -> tuple[float, float]:
    asset_type = holding.get("asset_type") or ""
    units = Decimal(str(holding.get("units") or "0"))
    multiplier = Decimal(str(holding.get("unit_multiplier") or ("1000" if asset_type == "fund" else "1")))
    denominator = Decimal(str(holding.get("nav_denominator") or ("10000" if asset_type == "fund" else "1")))
    if units <= 0 or multiplier <= 0:
        return 0.0, 0.0
    quantity = units * multiplier
    cost = Decimal(str(holding.get("cost_value") or "0")) * denominator / quantity
    current = Decimal(str(holding.get("market_value") or "0")) * denominator / quantity
    return _money(cost), _money(current)


def holding_quantity(holding: dict) -> str:
    units = to_float(holding.get("units"))
    if holding.get("asset_type") == "fund":
        multiplier = to_float(holding.get("unit_multiplier"), 1000)
        quantity = units * multiplier
        if abs(quantity - round(quantity)) < 1e-4:
            return f"{int(round(quantity)):,}口"
        return f"{quantity:,.4f}口"
    text = f"{units:.10f}".rstrip("0").rstrip(".")
    return f"{text}株"


def rate_label(holding: dict, trades: list[dict], pnl: float, cost: float) -> str:
    for trade in trades:
        if trade.get("symbol") != holding.get("symbol") or trade.get("kind") != "初期記録":
            continue
        try:
            if int(round(float(trade.get("pnl_yen") or 0))) == int(round(pnl)):
                return format_stored_pct(trade.get("pnl_pct") or "")
        except ValueError:
            break
    if not cost:
        return "—"
    return format_pct(pnl / cost * 100)


def format_fetched_at(raw: str) -> tuple[str, str]:
    """取得日時の表示文と time 要素用の値。時刻が無いデータには時刻を足さない。"""
    text = (raw or "").strip()
    if not text:
        return "取得日時 未記録", ""
    matched = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})([+-]\d{2})(\d{2})", text)
    if matched and matched.group(3) == "+09":
        visible = f"取得 {matched.group(1)} {matched.group(2)} JST"
        stamp = f"{matched.group(1)}T{matched.group(2)}+09:00"
        return visible, stamp
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"取得 {text}", text
    return f"取得 {text}", ""


def show_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return '<span class="muted">未記録</span>'
    return esc(text)


def item_class(index: int, fold: int) -> str:
    if fold > 0 and index >= fold:
        return "fold-item is-clipped"
    return "fold-item"


def filter_bar(attrs: list[str]) -> str:
    buttons = [
        '<button type="button" class="filter-btn is-on" data-filter-value="all" aria-pressed="true">すべて</button>'
    ]
    for name in attrs:
        buttons.append(
            '<button type="button" class="filter-btn" data-filter-value="'
            + esc(name)
            + '" aria-pressed="false">'
            + esc(name)
            + "</button>"
        )
    return '<div class="filter-bar" role="group" aria-label="属性で絞り込み">' + "".join(buttons) + "</div>"


def panel(
    panel_id: str,
    title: str,
    more_href: str,
    intro_html: str,
    inner_html: str,
    count: int,
    fold: int,
    attrs: list[str] | None = None,
) -> str:
    more = f'<a class="text-link" href="{esc(more_href)}">下層ページ</a>' if more_href else ""
    head = f'<div class="block-head"><h3>{esc(title)}</h3>{more}</div>' if title else ""
    filters = filter_bar(attrs) if attrs else ""
    empty = '<p class="filter-empty" hidden>該当する銘柄はありません。</p>' if attrs else ""
    button = ""
    if fold > 0 and count > fold:
        button = (
            '<button type="button" class="fold-toggle" data-fold-toggle aria-expanded="false">残り'
            + str(count - fold)
            + "件を表示</button>"
        )
    ident = f' id="{esc(panel_id)}"' if panel_id else ""
    return (
        f'<div class="top-block panel"{ident} data-panel data-fold="{fold}" data-filter="all">'
        + head
        + intro_html
        + filters
        + empty
        + inner_html
        + button
        + "</div>"
    )


def instrument_table(rows: list[dict], fold: int) -> str:
    body = []
    for index, row in enumerate(rows):
        badge = "badge" if row["kind"] == "保有" else "badge badge-muted"
        body.append(
            '<tr class="'
            + item_class(index, fold)
            + '" data-attr="'
            + esc(row["attribute"])
            + '"><td>'
            + esc(row["name"])
            + '</td><td class="code">'
            + esc(row["code"])
            + "</td><td>"
            + esc(row["attribute"])
            + '</td><td><span class="'
            + badge
            + '">'
            + esc(row["kind"])
            + "</span></td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>名前</th><th>番号</th><th>属性</th><th>区分</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def holdings_table(holdings: list[dict], trades: list[dict], fold: int) -> str:
    total_market = sum(to_float(row.get("market_value")) for row in holdings)
    total = total_market or 1.0
    body = []
    for index, holding in enumerate(holdings):
        market = to_float(holding.get("market_value"))
        pnl = to_float(holding.get("unrealized_pnl"))
        cost = to_float(holding.get("cost_value"))
        acquired, current = unit_prices(holding)
        unit = price_unit(holding)
        attribute = attribute_of(holding.get("asset_type") or "", holding.get("yahoo_ticker") or "")
        ratio = market / total * 100
        body.append(
            '<tr class="'
            + item_class(index, fold)
            + '" data-attr="'
            + esc(attribute)
            + '"><td>'
            + esc(holding.get("name"))
            + '</td><td class="code">'
            + esc(instrument_code(holding))
            + "</td><td>"
            + esc(attribute)
            + '</td><td class="num">'
            + esc(holding_quantity(holding))
            + '</td><td class="num">'
            + esc(f"{acquired:,.2f} {unit}")
            + '</td><td class="num">'
            + esc(f"{current:,.2f} {unit}")
            + '</td><td class="num">'
            + esc(yen(market))
            + '</td><td class="num '
            + pnl_class(pnl)
            + '">'
            + esc(signed_yen(pnl))
            + '</td><td class="num '
            + pnl_class(pnl)
            + '">'
            + esc(rate_label(holding, trades, pnl, cost))
            + "</td><td>"
            + show_date(purchase_date_for(holding.get("symbol") or "", trades))
            + '</td><td class="num">'
            + f"{ratio:.1f}%"
            + "</td></tr>"
        )
    total_pnl = sum(to_float(row.get("unrealized_pnl")) for row in holdings)
    total_cost = sum(to_float(row.get("cost_value")) for row in holdings)
    total_rate = format_pct(total_pnl / total_cost * 100) if total_cost else "—"
    footer = (
        '<tfoot><tr class="holding-total-row"><td>合計</td><td></td><td></td><td></td><td></td><td></td>'
        '<td class="num">'
        + esc(yen(total_market))
        + '</td><td class="num '
        + pnl_class(total_pnl)
        + '">'
        + esc(signed_yen(total_pnl))
        + '</td><td class="num '
        + pnl_class(total_pnl)
        + '">'
        + esc(total_rate)
        + '</td><td></td><td class="num">100.0%</td></tr></tfoot>'
    )
    return (
        '<div class="table-wrap"><table class="wide"><thead><tr>'
        "<th>銘柄</th><th>番号</th><th>属性</th><th>数量</th><th>取得単価</th>"
        "<th>現在価格</th><th>評価額</th><th>騰落額</th><th>騰落率</th><th>購入日</th><th>比率</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody>"
        + footer
        + "</table></div>"
    )


def trade_quantity(trade: dict) -> str:
    raw = trade.get("quantity") or ""
    unit = trade.get("quantity_unit") or ""
    try:
        number = float(raw)
    except ValueError:
        return f"{raw}{unit}"
    if unit == "口" and abs(number - round(number)) < 1e-4:
        return f"{int(round(number)):,}{unit}"
    if unit == "株":
        return f"{number:.10f}".rstrip("0").rstrip(".") + unit
    return f"{number:,.2f}{unit}"


def trades_table(trades: list[dict], fold: int) -> str:
    body = []
    for index, trade in enumerate(trades):
        try:
            pnl = float(trade.get("pnl_yen") or 0)
        except ValueError:
            pnl = 0.0
        try:
            price = float(trade.get("unit_price") or 0)
        except ValueError:
            price = 0.0
        try:
            market = float(trade.get("market_value_yen") or 0)
        except ValueError:
            market = 0.0
        unit = trade.get("price_unit") or ""
        body.append(
            '<tr class="'
            + item_class(index, fold)
            + '" data-attr="'
            + esc(trade.get("attribute"))
            + '"><td>'
            + esc(trade.get("as_of"))
            + "</td><td>"
            + esc(trade.get("name"))
            + '</td><td class="code">'
            + esc(trade.get("code"))
            + "</td><td>"
            + esc(trade.get("attribute"))
            + "</td><td>"
            + esc(trade.get("kind"))
            + '</td><td class="num">'
            + esc(trade_quantity(trade))
            + '</td><td class="num">'
            + esc(f"{price:,.2f} {unit}")
            + '</td><td class="num">'
            + esc(yen(market))
            + '</td><td class="num '
            + pnl_class(pnl)
            + '">'
            + esc(signed_yen(pnl))
            + '</td><td class="num '
            + pnl_class(pnl)
            + '">'
            + esc(format_stored_pct(trade.get("pnl_pct") or ""))
            + "</td><td>"
            + show_date(trade.get("purchase_date") or "")
            + "</td><td>"
            + esc(trade.get("note"))
            + "</td></tr>"
        )
    if not body:
        body.append('<tr><td colspan="12">売買履歴はまだありません。</td></tr>')
    return (
        '<div class="table-wrap"><table class="wide"><thead><tr>'
        "<th>記録日</th><th>銘柄</th><th>番号</th><th>属性</th><th>区分</th><th>数量</th>"
        "<th>値段</th><th>評価額</th><th>増減額</th><th>増減率</th><th>購入日</th><th>メモ</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def build_chart_payload(holdings: list[dict], history: list[dict]) -> dict:
    short_names = [row["name"][:18] for row in holdings]
    by_symbol: dict[str, list] = {}
    for row in history:
        by_symbol.setdefault(row["symbol"], []).append(
            {"date": row["date"], "price": to_float(row["price"])}
        )
    for symbol in by_symbol:
        by_symbol[symbol].sort(key=lambda item: item["date"])
    return {
        "allocationLabels": short_names,
        "allocationValues": [to_float(row.get("market_value")) for row in holdings],
        "pnlLabels": short_names,
        "pnlValues": [to_float(row.get("unrealized_pnl")) for row in holdings],
        "history": by_symbol,
        "holdingSymbols": [row["symbol"] for row in holdings],
    }


HOLDING_NOTE = (
    '<p class="muted">取得単価は評価額と評価損益から求めた単価です。'
    "投信は1万口あたり、株式は1株あたりです。購入日の記録はないため未記録と表示します。</p>"
)
TRADE_NOTE = (
    '<p class="muted">いまの保有に約定データはないため、2026-11-09 14:28 JST の値段・増減額・率を'
    "初期記録として保存しています。この行は売買の約定ではありません。</p>"
)
CATALOG_NOTE = (
    '<p class="muted">価格を取得できた銘柄です。番号は投信の協会コード、株式・ETFのティッカーです。</p>'
)


def catalog_block(catalog: list[dict], fold: int, panel_id: str, more_href: str) -> str:
    return panel(
        panel_id,
        "取得できた銘柄",
        more_href,
        CATALOG_NOTE,
        instrument_table(catalog, fold),
        len(catalog),
        fold,
        ordered_attrs(catalog),
    )


def holdings_total_line(holdings: list[dict]) -> str:
    total_pnl = sum(to_float(row.get("unrealized_pnl")) for row in holdings)
    total_cost = sum(to_float(row.get("cost_value")) for row in holdings)
    total_market = sum(to_float(row.get("market_value")) for row in holdings)
    rate = format_pct(total_pnl / total_cost * 100) if total_cost else "—"
    return (
        '<p class="holding-total" data-holding-total>損益合計 '
        '<span class="num '
        + pnl_class(total_pnl)
        + '">'
        + esc(signed_yen(total_pnl))
        + "円</span> "
        '<span class="'
        + pnl_class(total_pnl)
        + '">('
        + esc(rate)
        + ")</span>"
        '<span class="muted"> · 評価額合計 '
        + esc(yen(total_market))
        + "円</span></p>"
    )


def holdings_block(holdings: list[dict], trades: list[dict], fold: int, panel_id: str, more_href: str) -> str:
    attrs = ordered_attrs(
        [
            {"attribute": attribute_of(row.get("asset_type") or "", row.get("yahoo_ticker") or "")}
            for row in holdings
        ]
    )
    return panel(
        panel_id,
        "保有銘柄",
        more_href,
        HOLDING_NOTE + holdings_total_line(holdings),
        holdings_table(holdings, trades, fold),
        len(holdings),
        fold,
        attrs,
    )


def trades_block(trades: list[dict], fold: int, panel_id: str, more_href: str) -> str:
    return panel(
        panel_id,
        "売買履歴",
        more_href,
        TRADE_NOTE,
        trades_table(trades, fold),
        len(trades),
        fold,
        ordered_attrs(trades),
    )


def topic_cards(signals: list[dict], news: list[dict]) -> list[str]:
    urgent = [row for row in signals if row.get("priority") == "high"]
    medium = [row for row in signals if row.get("priority") == "medium"]
    jpx_news = [row for row in news if "JPX" in row.get("source", "")]
    other_news = [row for row in news if "JPX" not in row.get("source", "")]
    cards: list[str] = []
    for row in urgent:
        cards.append(
            '<article class="topic-card topic-urgent">'
            '<p class="topic-tag">緊急 · '
            + esc(row.get("signal"))
            + "</p><h3>"
            + esc(row.get("name"))
            + "</h3><p>"
            + esc(row.get("reason"))
            + '</p><p class="topic-action">'
            + esc(row.get("suggested_action"))
            + "</p></article>"
        )
    for row in medium[:3]:
        cards.append(
            '<article class="topic-card topic-watch">'
            '<p class="topic-tag">注目 · '
            + esc(row.get("signal"))
            + "</p><h3>"
            + esc(row.get("name"))
            + "</h3><p>"
            + esc(row.get("reason"))
            + "</p></article>"
        )
    for row in (jpx_news + other_news)[:6]:
        published = (row.get("published") or "")[:16]
        meta = " · ".join(part for part in [row.get("source", ""), published] if part)
        cards.append(
            '<article class="topic-card topic-news">'
            '<p class="topic-tag">ニュース · '
            + esc(row.get("source"))
            + '</p><h3><a href="'
            + esc(row.get("link"))
            + '" target="_blank" rel="noopener">'
            + esc(row.get("title"))
            + '</a></h3><p class="meta">'
            + esc(meta)
            + "</p></article>"
        )
    return cards


def topics_block(signals: list[dict], news: list[dict], fold: int) -> str:
    cards = topic_cards(signals, news)
    if not cards:
        inner = '<p class="muted">表示できるトピックがありません。</p>'
        count = 0
    else:
        wrapped = []
        for index, card in enumerate(cards):
            wrapped.append(card.replace('class="topic-card', 'class="' + item_class(index, fold) + " topic-card", 1))
        inner = '<div class="topics-grid">' + "".join(wrapped) + "</div>"
        count = len(cards)
    urgent_count = len([row for row in signals if row.get("priority") == "high"])
    intro = '<p class="muted">緊急シグナル ' + str(urgent_count) + "件</p>"
    return panel("top-topics", "本日のトピック", "", intro, inner, count, fold, None)


def signal_rank_table(rows: list[dict], side: str) -> str:
    picked = [row for row in rows if row.get("side") == side]
    if not picked:
        return '<p class="muted">強さが付いた銘柄はありません。</p>'
    body = []
    for row in picked:
        score = to_float(row.get("score"))
        cls = "neg" if side == "sell" else "pos"
        body.append(
            '<tr><td class="num">'
            + esc(row.get("rank"))
            + "</td><td>"
            + esc(row.get("name"))
            + "</td><td>"
            + esc(row.get("held"))
            + '</td><td class="num '
            + cls
            + '">'
            + esc(f"{score:.1f}")
            + "</td><td>"
            + esc(row.get("reason"))
            + "</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>順</th><th>銘柄</th><th>区分</th><th>強さ</th><th>根拠</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def signal_rank_block(rows: list[dict]) -> str:
    buy_count = sum(1 for row in rows if row.get("side") == "buy")
    sell_count = sum(1 for row in rows if row.get("side") == "sell")
    intro = (
        '<p class="muted">保有・未保有を分けず、価格がある銘柄を強さ順に最大10件ずつ並べます。'
        "買いの強さは前日比の下落幅です。含み損が-20%以下の保有は売り見直し側なので買いからは外します。"
        "売りの強さは、保有なら含み損の大きさ、未保有なら前日比の上昇幅です。"
        f"いま買い {buy_count}件、売り {sell_count}件です。</p>"
    )
    tables = (
        '<div class="rank-grid">'
        '<div><h4>買いが強い</h4>'
        + signal_rank_table(rows, "buy")
        + '</div><div><h4>売りが強い</h4>'
        + signal_rank_table(rows, "sell")
        + "</div></div>"
    )
    return panel("top-signal-rank", "売買シグナルの強い銘柄", "", intro, tables, 0, 0, None)


def charts_html() -> str:
    return (
        '<div class="charts-grid">'
        '<div class="chart-card"><h3>構成比</h3><canvas id="allocChart"></canvas></div>'
        '<div class="chart-card"><h3>銘柄別損益</h3><canvas id="pnlChart"></canvas></div>'
        "</div>"
    )


def market_section(market: list[dict], holdings: list[dict], accums: list[dict], cash_rows: list[dict]) -> str:
    total_market = sum(to_float(row.get("market_value")) for row in holdings)
    total_pnl = sum(to_float(row.get("unrealized_pnl")) for row in holdings)
    total_cost = sum(to_float(row.get("cost_value")) for row in holdings)
    monthly = sum(to_float(row.get("monthly_estimate_yen")) for row in accums)
    cash = to_float(cash_rows[0].get("paypay_balance_yen")) if cash_rows else 0
    cards = []
    for row in market:
        change = to_float(row.get("change_pct"))
        fetched, stamp = format_fetched_at(row.get("as_of") or "")
        time_attr = f' datetime="{esc(stamp)}"' if stamp else ""
        cards.append(
            '<article class="metric"><h3>'
            + esc(row.get("name"))
            + '</h3><p class="big">'
            + esc(row.get("price"))
            + '</p><p class="'
            + pnl_class(change)
            + '">'
            + esc(row.get("change"))
            + " ("
            + esc(row.get("change_pct"))
            + '%)</p><p class="as-of"><time'
            + time_attr
            + ">"
            + esc(fetched)
            + '</time></p><p class="spark">'
            + esc(row.get("sparkline"))
            + "</p></article>"
        )
    cards.append(
        '<article class="metric"><h3>保有合計</h3><p class="big">'
        + yen(total_market)
        + '</p><p class="'
        + pnl_class(total_pnl)
        + '">'
        + signed_yen(total_pnl)
        + " / 取得 "
        + yen(total_cost)
        + "</p></article>"
    )
    cards.append(
        '<article class="metric"><h3>PayPay残高（手入力）</h3><p class="big">'
        + yen(cash)
        + '</p><p class="muted">月次積立目安 '
        + yen(monthly)
        + "</p></article>"
    )
    nav = menubar("市場のメニュー", [("#market", "市場"), ("#top", "トップの銘柄")])
    return (
        '<section id="market"><h2>市場と残高</h2>'
        + nav
        + '<div class="metrics-row">'
        + "".join(cards)
        + "</div></section>"
    )


def signal_section(signals: list[dict]) -> str:
    rows = []
    for row in signals:
        rows.append(
            '<tr class="prio-'
            + esc(row.get("priority"))
            + '"><td><span class="badge">'
            + esc(row.get("signal"))
            + "</span></td><td>"
            + esc(row.get("name"))
            + "</td><td>"
            + esc(row.get("reason"))
            + "</td><td>"
            + esc(row.get("suggested_action"))
            + "</td></tr>"
        )
    nav = menubar("シグナルのメニュー", [("#signals", "シグナル"), ("#top-holdings", "保有")])
    return (
        '<section id="signals"><h2>売買シグナル</h2>'
        + nav
        + '<p class="muted">自動発注はしません。PayPay証券で手動執行してください。</p>'
        + '<div class="table-wrap"><table><thead><tr><th>シグナル</th><th>対象</th><th>理由</th><th>推奨アクション</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def accum_section(accums: list[dict]) -> str:
    monthly = sum(to_float(row.get("monthly_estimate_yen")) for row in accums)
    rows = []
    for row in accums:
        rows.append(
            "<tr><td>"
            + esc(row.get("name"))
            + "</td><td>"
            + esc(row.get("schedule"))
            + '</td><td class="num">'
            + yen(to_float(row.get("amount_yen")))
            + "</td><td>"
            + esc(row.get("nisa_type"))
            + '</td><td class="num">'
            + yen(to_float(row.get("monthly_estimate_yen")))
            + "</td></tr>"
        )
    nav = menubar("積立のメニュー", [("#accum", "積立"), ("#cashflow", "資金スケジュール")])
    return (
        '<section id="accum"><h2>積立設定</h2>'
        + nav
        + '<div class="table-wrap"><table><thead><tr><th>銘柄</th><th>頻度</th><th>金額</th><th>枠</th><th>月次目安</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        + '<p class="muted">月次合計目安 '
        + yen(monthly)
        + " 円（毎日積立は営業日〜暦日換算の概算）</p></section>"
    )


def cashflow_section(cashflow: list[dict]) -> str:
    rows = []
    for row in cashflow[:40]:
        rows.append(
            "<tr><td>"
            + esc(row.get("date"))
            + "</td><td>"
            + esc(row.get("event_type"))
            + "</td><td>"
            + esc(row.get("symbol"))
            + '</td><td class="num">'
            + esc(row.get("amount_yen"))
            + "</td><td>"
            + esc(row.get("note"))
            + "</td></tr>"
        )
    nav = menubar("資金のメニュー", [("#cashflow", "資金スケジュール"), ("#accum", "積立")])
    return (
        '<section id="cashflow"><h2>資金スケジュール</h2>'
        + nav
        + '<p class="muted">売却→PayPay着金（+2〜3営業日）→銀行引出（さらに+2〜3営業日）。買い直しはPayPay残高があれば市場時間中に即時。</p>'
        + '<div class="table-wrap"><table><thead><tr><th>日付</th><th>種別</th><th>銘柄</th><th>金額</th><th>メモ</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def watch_section(watch_actions: list[dict]) -> str:
    rows = []
    for row in watch_actions:
        change = to_float(row.get("change_pct"))
        buy = to_float(row.get("buy_yen"))
        sell = to_float(row.get("sell_yen"))
        rows.append(
            '<tr><td class="num">'
            + esc(row.get("rank"))
            + "</td><td>"
            + esc(row.get("name"))
            + '</td><td><span class="badge">'
            + esc(row.get("action"))
            + '</span></td><td class="num">'
            + (yen(buy) if buy > 0 else "—")
            + '</td><td class="num">'
            + (yen(sell) if sell > 0 else "—")
            + '</td><td class="num">'
            + esc(row.get("price") or "—")
            + '</td><td class="num '
            + pnl_class(change)
            + '">'
            + esc(row.get("change_pct") or "—")
            + "</td><td>"
            + esc(row.get("action_detail") or row.get("reason"))
            + "</td></tr>"
        )
    nav = menubar(
        "監視のメニュー",
        [("#watch", "監視"), ("instruments.html", "銘柄一覧"), ("index.html#top-instruments", "トップの銘柄")],
    )
    return (
        '<section id="watch"><h2>監視・おすすめ銘柄</h2>'
        + nav
        + '<p class="muted">おすすめ順（スコア高い順）。買付目安は PayPay残高 − 月次積立目安の余力から配分。売却目安は未保有の監視銘柄では原則なし。投資助言ではありません。</p>'
        + '<div class="table-wrap"><table><thead><tr><th>順</th><th>銘柄</th><th>アクション</th><th>買付目安</th><th>売却目安</th><th>価格</th><th>変化%</th><th>内容</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def subpage_nav(current_href: str) -> str:
    links = [(href, text) for href, text, _key in SUBPAGES]
    links.append(("index.html#top", "トップ"))
    return menubar("下層ページのメニュー", links, current_href)


def index_body(
    catalog: list[dict],
    holdings: list[dict],
    trades: list[dict],
    market: list[dict],
    news: list[dict],
    signals: list[dict],
    cashflow: list[dict],
    accums: list[dict],
    cash_rows: list[dict],
    watch_actions: list[dict],
    prices: list[dict],
    watchlist: list[dict],
) -> str:
    top_nav = menubar(
        "トップのメニュー",
        [
            ("#top-instruments", "銘柄一覧"),
            ("#top-holdings", "保有"),
            ("#top-trades", "売買履歴"),
            ("#top-topics", "トピック"),
            ("#top-signal-rank", "強い売買"),
            ("instruments.html", "銘柄ページ"),
            ("holdings.html", "保有ページ"),
            ("trades.html", "履歴ページ"),
        ],
    )
    top = (
        '<section class="hero-topics" id="top">'
        '<div class="topics-header"><p class="eyebrow">Top</p><h2>銘柄・保有・売買</h2>'
        '<p class="sub">はじめの5件を表示します。残りはこのセクションで開けます。</p></div>'
        + top_nav
        + catalog_block(catalog, PREVIEW_LIMIT, "top-instruments", "instruments.html")
        + holdings_block(holdings, trades, PREVIEW_LIMIT, "top-holdings", "holdings.html")
        + trades_block(trades, PREVIEW_LIMIT, "top-trades", "trades.html")
        + topics_block(signals, news, PREVIEW_LIMIT)
        + signal_rank_block(analyze.rank_trade_signals(holdings, prices, watchlist))
        + "</section>"
    )
    chart_nav = menubar(
        "保有チャートのメニュー",
        [("#holdings", "チャート"), ("#top-holdings", "保有の数値"), ("holdings.html", "保有ページ")],
    )
    charts = '<section id="holdings"><h2>保有の内訳</h2>' + chart_nav + charts_html() + "</section>"
    return (
        top
        + market_section(market, holdings, accums, cash_rows)
        + charts
        + signal_section(signals)
        + accum_section(accums)
        + cashflow_section(cashflow)
        + watch_section(watch_actions)
    )


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
    trades = read_csv(DATA / "trades.csv")
    watch_actions = read_csv(DATA / "watch_actions.csv")
    catalog = build_catalog(holdings, watchlist, prices)
    chart_json = json.dumps(build_chart_payload(holdings, history), ensure_ascii=False)
    updated = now_jst().strftime("%Y-%m-%d %H:%M JST")
    pages = {
        "index.html": layout(
            "判断支援ダッシュボード",
            "home",
            index_body(
                catalog,
                holdings,
                trades,
                market,
                news,
                signals,
                cashflow,
                accums,
                cash_rows,
                watch_actions,
                prices,
                watchlist,
            ),
            updated,
            chart_json,
        ),
        "instruments.html": layout(
            "銘柄一覧",
            "instruments",
            "<section>" + subpage_nav("instruments.html") + catalog_block(catalog, 0, "", "") + "</section>",
            updated,
            None,
        ),
        "holdings.html": layout(
            "保有銘柄",
            "holdings",
            "<section>"
            + subpage_nav("holdings.html")
            + holdings_block(holdings, trades, 0, "", "")
            + charts_html()
            + "</section>",
            updated,
            chart_json,
        ),
        "trades.html": layout(
            "売買履歴",
            "trades",
            "<section>" + subpage_nav("trades.html") + trades_block(trades, 0, "", "") + "</section>",
            updated,
            None,
        ),
    }
    for name, html in pages.items():
        path = DOCS / name
        path.write_text(html, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
