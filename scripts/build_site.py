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
    ("quotes.html", "取得銘柄", "quotes"),
    ("instruments.html", "銘柄一覧", "instruments"),
    ("holdings.html", "保有", "holdings"),
    ("trades.html", "売買履歴", "trades"),
]
INDEX_SECTIONS = [
    ("#top-instruments", "銘柄一覧"),
    ("#top-holdings", "保有"),
    ("#watch", "監視銘柄"),
    ("#top-trades", "売買履歴"),
    ("#top-topics", "トピック"),
    ("#top-signal-rank", "強い売買"),
    ("#market", "市場と残高"),
    ("#holdings", "保有の内訳"),
    ("#signals", "売買シグナル"),
    ("#accum", "積立"),
    ("#cashflow", "資金スケジュール"),
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


def sidemenu(current: str, asset_prefix: str = "") -> str:
    def link(href: str, text: str, key: str) -> str:
        current_attr = ' aria-current="page"' if key == current else ""
        return f'<a href="{esc(asset_prefix + href)}"{current_attr}>{esc(text)}</a>'

    children = "".join(link(href, text, key) for href, text, key in SUBPAGES)
    return (
        '<aside id="sidemenu" class="sidemenu" aria-label="下層ページ">'
        '<p class="sidemenu-label">メニュー</p>'
        + link("index.html#top", "トップ", "home")
        + '<div class="sidemenu-group"><p class="sidemenu-sublabel">下層ページ</p>'
        + children
        + "</div></aside>"
    )


def layout(
    title: str,
    current: str,
    body: str,
    updated: str,
    chart_json: str | None,
    asset_prefix: str = "",
) -> str:
    chart_tag = ""
    chart_scripts = ""
    if chart_json is not None:
        safe_json = chart_json.replace("<", "\\u003c")
        chart_tag = f'<script id="chart-data" type="application/json">{safe_json}</script>'
        chart_scripts = (
            '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js" defer></script>'
            f'<script src="{esc(asset_prefix)}assets/charts.js" defer></script>'
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
        f'  <link rel="stylesheet" href="{esc(asset_prefix)}assets/app.css" />\n'
        "</head>\n"
        "<body>\n"
        '<button class="sidemenu-backdrop" type="button" data-menu-close aria-label="メニューを閉じる"></button>\n'
        '<div class="shell">\n'
        + sidemenu(current, asset_prefix)
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
        + f'<script src="{esc(asset_prefix)}assets/desk.js" defer></script>\n'
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


def symbol_href(symbol: str, prefix: str = "") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", symbol or "")
    return f"{prefix}symbols/{safe}.html"


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
            + '"><td><a href="'
            + esc(symbol_href(row["symbol"]))
            + '">'
            + esc(row["name"])
            + '</a></td><td class="code">'
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


def market_quote_cards(market: list[dict]) -> str:
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
    if not cards:
        return ""
    return '<div class="metrics-row topic-markets">' + "".join(cards) + "</div>"


def topics_block(signals: list[dict], news: list[dict], market: list[dict], fold: int) -> str:
    cards = topic_cards(signals, news)
    quotes = market_quote_cards(market)
    if not cards:
        topics = '<p class="muted">表示できるトピックがありません。</p>'
        count = 0
    else:
        wrapped = []
        for index, card in enumerate(cards):
            wrapped.append(card.replace('class="topic-card', 'class="' + item_class(index, fold) + " topic-card", 1))
        topics = '<div class="topics-grid">' + "".join(wrapped) + "</div>"
        count = len(cards)
    urgent_count = len([row for row in signals if row.get("priority") == "high"])
    intro = '<p class="muted">緊急シグナル ' + str(urgent_count) + "件</p>"
    return panel("top-topics", "本日のトピック", "", intro, quotes + topics, count, fold, None)


def signal_rank_table(rows: list[dict], side: str, fold: int) -> str:
    picked = [row for row in rows if row.get("side") == side]
    title = "買いが強い" if side == "buy" else "売りが強い"
    if not picked:
        return "<h4>" + title + '</h4><p class="muted">強さが付いた銘柄はありません。</p>'
    body = []
    for index, row in enumerate(picked):
        score = to_float(row.get("score"))
        cls = "neg" if side == "sell" else "pos"
        body.append(
            '<tr class="'
            + item_class(index, fold)
            + '"><td class="num">'
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
    button = ""
    if fold > 0 and len(picked) > fold:
        button = (
            '<button type="button" class="fold-toggle" data-fold-toggle aria-expanded="false">残り'
            + str(len(picked) - fold)
            + "件を表示</button>"
        )
    return (
        f'<div data-panel data-fold="{fold}" data-filter="all"><h4>'
        + title
        + '</h4><div class="table-wrap"><table><thead><tr>'
        "<th>順</th><th>銘柄</th><th>区分</th><th>強さ</th><th>根拠</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + button
        + "</div>"
    )


def signal_rank_block(rows: list[dict], fold: int) -> str:
    buy_count = sum(1 for row in rows if row.get("side") == "buy")
    sell_count = sum(1 for row in rows if row.get("side") == "sell")
    intro = (
        '<p class="muted">保有・未保有を分けず、価格がある銘柄を強さ順に最大10件ずつ並べます。'
        "はじめの5件を表示し、残りは開けます。"
        "買いの強さは前日比の下落幅です。含み損が-20%以下の保有は売り見直し側なので買いからは外します。"
        "売りの強さは、保有なら含み損の大きさ、未保有なら前日比の上昇幅です。"
        f"いま買い {buy_count}件、売り {sell_count}件です。</p>"
    )
    tables = (
        '<div class="rank-grid">'
        + signal_rank_table(rows, "buy", fold)
        + signal_rank_table(rows, "sell", fold)
        + "</div>"
    )
    return (
        '<div class="top-block" id="top-signal-rank">'
        '<div class="block-head"><h3>売買シグナルの強い銘柄</h3></div>'
        + intro
        + tables
        + "</div>"
    )


def charts_html() -> str:
    return (
        '<div class="charts-grid">'
        '<div class="chart-card"><h3>構成比</h3><canvas id="allocChart"></canvas></div>'
        '<div class="chart-card"><h3>銘柄別損益</h3><canvas id="pnlChart"></canvas></div>'
        "</div>"
    )


def market_section(_market: list[dict], holdings: list[dict], accums: list[dict], cash_rows: list[dict]) -> str:
    total_market = sum(to_float(row.get("market_value")) for row in holdings)
    total_pnl = sum(to_float(row.get("unrealized_pnl")) for row in holdings)
    total_cost = sum(to_float(row.get("cost_value")) for row in holdings)
    monthly = sum(to_float(row.get("monthly_estimate_yen")) for row in accums)
    cash = to_float(cash_rows[0].get("paypay_balance_yen")) if cash_rows else 0
    cards = []
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
    nav = menubar("市場のメニュー", [("#market", "残高"), ("#top-topics", "日経・TOPIX")])
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


def action_kind(action: str) -> str:
    if "売" in action:
        return "sell"
    if "買" in action:
        return "buy"
    return "other"


def watch_block(watch_actions: list[dict], fold: int) -> str:
    rows = []
    for index, row in enumerate(watch_actions):
        change = to_float(row.get("change_pct"))
        buy = to_float(row.get("buy_yen"))
        sell = to_float(row.get("sell_yen"))
        action = row.get("action") or ""
        rows.append(
            '<tr class="'
            + item_class(index, fold)
            + '" data-rank="'
            + esc(row.get("rank") or str(index + 1))
            + '" data-action="'
            + action_kind(action)
            + '"><td class="num">'
            + esc(row.get("rank"))
            + "</td><td>"
            + esc(row.get("name"))
            + '</td><td><span class="badge">'
            + esc(action)
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
    table = (
        '<div class="table-wrap"><table><thead><tr><th>順</th><th>銘柄</th><th>アクション</th><th>買付目安</th><th>売却目安</th><th>価格</th><th>変化%</th><th>内容</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )
    intro = (
        '<p class="muted">価格を取得できた全銘柄から、買い候補と売り見直しを追加しています。'
        "はじめはおすすめ順です。売り優先は売り検討を上に、買い優先は買い検討を上に並べます。"
        "買付目安は PayPay残高 − 月次積立目安の余力から配分。売却目安は売り見直し対象の評価額です。"
        "投資助言ではありません。</p>"
        '<div class="filter-bar" role="group" aria-label="アクションで並べ替え">'
        '<button type="button" class="filter-btn is-on" data-sort-value="score" aria-pressed="true">おすすめ順</button>'
        '<button type="button" class="filter-btn" data-sort-value="sell" aria-pressed="false">売り優先</button>'
        '<button type="button" class="filter-btn" data-sort-value="buy" aria-pressed="false">買い優先</button>'
        "</div>"
    )
    return panel("watch", "監視・おすすめ銘柄", "", intro, table, len(watch_actions), fold, None)


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
    page_nav = menubar("トップのセクション", INDEX_SECTIONS)
    top = (
        '<section class="hero-topics" id="top">'
        '<div class="topics-header"><p class="eyebrow">Top</p><h2>銘柄・保有・売買</h2>'
        '<p class="sub">はじめの5件を表示します。残りはこのセクションで開けます。</p></div>'
        + catalog_block(catalog, PREVIEW_LIMIT, "top-instruments", "instruments.html")
        + holdings_block(holdings, trades, PREVIEW_LIMIT, "top-holdings", "holdings.html")
        + watch_block(watch_actions, PREVIEW_LIMIT)
        + trades_block(trades, PREVIEW_LIMIT, "top-trades", "trades.html")
        + topics_block(signals, news, market, PREVIEW_LIMIT)
        + signal_rank_block(analyze.rank_trade_signals(holdings, prices, watchlist), PREVIEW_LIMIT)
        + "</section>"
    )
    chart_nav = menubar("保有チャートのメニュー", [("#holdings", "チャート"), ("#top-holdings", "保有の数値")])
    charts = '<section id="holdings"><h2>保有の内訳</h2>' + chart_nav + charts_html() + "</section>"
    return (
        page_nav
        + top
        + market_section(market, holdings, accums, cash_rows)
        + charts
        + signal_section(signals)
        + accum_section(accums)
        + cashflow_section(cashflow)
    )


def fetched_quotes(catalog: list[dict], prices: list[dict]) -> list[dict]:
    by_symbol = {
        row["symbol"]: row
        for row in prices
        if row.get("symbol") and row.get("symbol") != "USDJPY" and str(row.get("price") or "").strip()
    }
    rows: list[dict] = []
    seen: set[str] = set()
    for item in catalog:
        price = by_symbol.get(item["symbol"])
        if not price:
            continue
        seen.add(item["symbol"])
        rows.append({**item, "quote": price})
    for symbol, price in by_symbol.items():
        if symbol in seen:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": price.get("name") or symbol,
                "code": symbol,
                "attribute": "その他",
                "kind": "価格のみ",
                "quote": price,
            }
        )
    return rows


def history_points(symbol: str, history: list[dict], quote: dict) -> list[dict]:
    points = [row for row in history if row.get("symbol") == symbol and str(row.get("price") or "").strip()]
    points.sort(key=lambda row: row.get("date") or "")
    if points:
        return points
    if str(quote.get("price") or "").strip():
        return [
            {
                "date": quote.get("as_of") or "",
                "symbol": symbol,
                "price": quote.get("price") or "",
                "currency": quote.get("currency") or "",
                "source": quote.get("source") or "",
            }
        ]
    return []


def quotes_block(rows: list[dict]) -> str:
    body = []
    for row in rows:
        quote = row["quote"]
        change = to_float(quote.get("change_pct"))
        fetched, stamp = format_fetched_at(quote.get("as_of") or "")
        time_attr = f' datetime="{esc(stamp)}"' if stamp else ""
        body.append(
            "<tr><td><a href=\""
            + esc(symbol_href(row["symbol"]))
            + '">'
            + esc(row["name"])
            + '</a></td><td class="code">'
            + esc(row["code"])
            + "</td><td>"
            + esc(row["attribute"])
            + '</td><td class="num">'
            + esc(quote.get("price") or "—")
            + '</td><td class="num '
            + pnl_class(change)
            + '">'
            + esc(quote.get("change_pct") or "—")
            + '</td><td class="as-of"><time'
            + time_attr
            + ">"
            + esc(fetched)
            + "</time></td></tr>"
        )
    table = (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>名前</th><th>番号</th><th>属性</th><th>価格</th><th>前日比%</th><th>取得時点</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )
    intro = (
        '<p class="muted">価格を取得できた銘柄です。取得時点はデータに記録された日付で、'
        "時刻まで入っているものだけ時刻を表示します。名前から個別ページのチャートを開けます。</p>"
    )
    return panel("", "取得できた銘柄", "", intro, table, len(rows), 0, None)


def symbol_page(row: dict, history: list[dict], prefix: str) -> tuple[str, str]:
    quote = row["quote"]
    points = history_points(row["symbol"], history, quote)
    fetched, stamp = format_fetched_at(quote.get("as_of") or "")
    time_attr = f' datetime="{esc(stamp)}"' if stamp else ""
    change = to_float(quote.get("change_pct"))
    point_rows = []
    for point in points:
        when, point_stamp = format_fetched_at(point.get("date") or "")
        point_time = f' datetime="{esc(point_stamp)}"' if point_stamp else ""
        point_rows.append(
            "<tr><td><time"
            + point_time
            + ">"
            + esc(when.removeprefix("取得 "))
            + '</time></td><td class="num">'
            + esc(point.get("price") or "—")
            + "</td><td>"
            + esc(point.get("currency") or quote.get("currency") or "")
            + "</td><td>"
            + esc(point.get("source") or "")
            + "</td></tr>"
        )
    chart = {
        "priceLabels": [point.get("date") or "" for point in points],
        "priceValues": [to_float(point.get("price")) for point in points],
    }
    nav = menubar(
        "銘柄のメニュー",
        [(f"{prefix}quotes.html", "取得銘柄"), (f"{prefix}index.html#top", "トップ")],
    )
    body = (
        "<section>"
        + nav
        + "<p>"
        + esc(row["code"])
        + " · "
        + esc(row["attribute"])
        + " · "
        + esc(row["kind"])
        + '</p><p class="big">'
        + esc(quote.get("price") or "—")
        + " "
        + esc(quote.get("currency") or "")
        + '</p><p class="'
        + pnl_class(change)
        + '">前日比 '
        + esc(quote.get("change_pct") or "—")
        + '%</p><p class="as-of">価格の取得時点 <time'
        + time_attr
        + ">"
        + esc(fetched)
        + "</time></p>"
        + '<div class="chart-card"><h3>記録した価格</h3>'
        '<canvas id="priceChart"></canvas>'
        '<p class="muted">横軸は記録日です。時刻が記録されていない点は日付だけを表示します。</p></div>'
        + '<div class="table-wrap"><table><thead><tr><th>記録</th><th>価格</th><th>通貨</th><th>取得元</th></tr></thead><tbody>'
        + "".join(point_rows)
        + "</tbody></table></div></section>"
    )
    return body, json.dumps(chart, ensure_ascii=False)


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
    quote_rows = fetched_quotes(catalog, prices)
    pages["quotes.html"] = layout(
        "取得銘柄",
        "quotes",
        "<section>" + subpage_nav("quotes.html") + quotes_block(quote_rows) + "</section>",
        updated,
        None,
    )
    symbol_dir = DOCS / "symbols"
    symbol_dir.mkdir(exist_ok=True)
    written: set[str] = set()
    for row in quote_rows:
        body, chart_json = symbol_page(row, history, "../")
        safe = symbol_href(row["symbol"]).rsplit("/", 1)[-1]
        path = symbol_dir / safe
        path.write_text(
            layout(row["name"], "quotes", body, updated, chart_json, asset_prefix="../"),
            encoding="utf-8",
        )
        written.add(safe)
        print(f"wrote {path}")
    for old in symbol_dir.glob("*.html"):
        if old.name not in written:
            old.unlink()
    for name, html in pages.items():
        path = DOCS / name
        path.write_text(html, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
