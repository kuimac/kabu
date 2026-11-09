"""更新結果を Markdown で標準出力する。GitHub Actions の要約と Issue 返信に使う。"""
from __future__ import annotations

import csv
import os
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def read_csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def yen(value: float) -> str:
    return f"{int(round(value)):,}円"


def signed_yen(value: float) -> str:
    return f"{int(round(value)):+,}円"


def pages_url() -> str:
    explicit = os.environ.get("PAGES_URL", "").strip()
    if explicit:
        return explicit
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    name = repository.split("/", 1)[1] if "/" in repository else ""
    if not owner or not name:
        return ""
    if name == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{name}/"


def main() -> None:
    market = read_csv("market.csv")
    signals = read_csv("signals.csv")
    holdings = read_csv("holdings.csv")
    lines = ["## NISAダッシュボードを更新しました", ""]

    if market:
        lines.append(f"取得時刻: {market[0].get('as_of', '')}")
        lines.append("")
        lines.append("### 市場")
        for row in market:
            raw = (row.get("change_pct") or "").strip()
            try:
                pct = f"{float(raw):+.2f}%"
            except ValueError:
                pct = raw or "-"
            lines.append(f"- {row.get('name')}: {row.get('price')}（{pct}）")
        lines.append("")

    total_value = 0.0
    total_pnl = 0.0
    for row in holdings:
        try:
            total_value += float(row.get("market_value") or 0)
            total_pnl += float(row.get("unrealized_pnl") or 0)
        except ValueError:
            continue
    lines.append("### 保有")
    lines.append(f"- 合計評価額: {yen(total_value)}")
    lines.append(f"- 合計損益: {signed_yen(total_pnl)}")
    lines.append("")

    hot = [row for row in signals if row.get("priority") in {"high", "medium"}]
    priority_ja = {"high": "高", "medium": "中", "low": "低"}
    lines.append("### シグナル（高 / 中）")
    if not hot:
        lines.append("- なし")
    else:
        for row in hot:
            prio = priority_ja.get(row.get("priority", ""), row.get("priority"))
            lines.append(
                f"- [{prio}] {row.get('name')}: {row.get('signal')} — {row.get('reason')}"
            )
    lines.append("")

    url = pages_url()
    if url:
        lines.append(f"公開ページ: {url}")
        lines.append("反映まで 1〜2 分かかることがあります。")
    else:
        lines.append("GitHub Pages へ反映されます（1〜2 分）。")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
