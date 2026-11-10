"""データ取得→分析→サイト生成を一括実行。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "fetch_market.py",
    "fetch_prices.py",
    "fetch_news.py",
    "fetch_fundamentals.py",
    "technical.py",
    "analyze.py",
    "fetch_outlook.py",
    "rank_ideas.py",
    "fetch_idea_news.py",
    "build_site.py",
]


def run(script: str) -> int:
    path = Path(__file__).resolve().parent / script
    print(f"\n=== {script} ===")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
    return proc.returncode


def main() -> int:
    failures = []
    for script in SCRIPTS:
        code = run(script)
        if code != 0:
            failures.append((script, code))
            # fetch系は部分失敗でも後続を続行、buildは最後に必須
            if script == "build_site.py":
                return code
    if failures:
        print("\nCompleted with warnings:")
        for name, code in failures:
            print(f"  {name} exit={code}")
        # サイトが生成できていれば0
        if (ROOT / "docs" / "index.html").exists():
            return 0
        return 1
    print("\nAll steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
