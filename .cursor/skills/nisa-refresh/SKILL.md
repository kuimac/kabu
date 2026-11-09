---
name: nisa-refresh
description: >-
  NISA判断支援ダッシュボードのデータを取得・分析し、GitHub Pages用HTMLを更新する。
  「NISA更新」「データ取得」「分析して」「Pages更新」などで使う。
---

# NISA Refresh

PayPay NISA向け判断支援ダッシュボードを更新する。自動発注はしない。

定期実行（GitHub Actions）は日本市場の開場前 08:00 JST と閉場後 15:30 JST（平日）。手動指示時も同じ `update_all.py` を使う。

## 手順

1. リポジトリルート（`株`）で依存関係を確認する。未インストールなら `pip install -r requirements.txt`。
2. 一括更新を実行する:

```bash
python scripts/update_all.py
```

3. コードまたは `docs/` を変えたら、最後に `main` へ fast-forward push して GitHub Pages（https://kuimac.github.io/kabu/）へ反映する。`origin/main` が今のコミットの祖先のときだけ `git push origin HEAD:main` する。祖先でないときは上書きしない。
4. 結果を要約して伝える:
   - 先頭トピック（緊急シグナルとニュース話題）
   - `data/signals.csv` の high / medium シグナル
   - `data/market.csv` の主要指数（参考）
   - 保有合計評価額と合計損益（`data/holdings.csv`）
   - `docs/index.html` が更新されたこと
5. 保有口数・積立・PayPay残高の変更がある場合は、該当CSVの編集を案内する:
   - `data/holdings.csv`
   - `data/accumulations.csv`
   - `data/cash_balance.csv`

## 個別スクリプト

- `scripts/fetch_market.py` … TOPIX等
- `scripts/fetch_prices.py` … 保有・監視銘柄価格
- `scripts/fetch_news.py` … JPX RSS
- `scripts/analyze.py` … シグナル・資金スケジュール
- `scripts/build_site.py` … `docs/` 生成

## 禁止事項

- PayPay証券への自動発注・ログイン自動化・スクレイピング発注
- 口座番号・銀行情報・個人名・API秘密鍵をリポジトリに書き込むこと
- 間隔を詰めたり並列クロールしたりして外部サイトへ負荷をかけること

## スクレイピング方針

- 公式API（MUFG・yfinance・JPX RSS）を優先し、不足分のみ Yahoo / 株探 / みんかぶを取得
- `polite_http.PoliteSession` 経由でホスト単位に十分な間隔を空ける（既定8秒＋ジッター）
- 間隔を広げる場合: `SCRAPE_INTERVAL_SEC` / `SCRAPE_JITTER_SEC`

## スマホから

リポジトリ所有者の Issue コメント `/update`、または Actions の **Update NISA dashboard**（workflow_dispatch）で、取得から Pages 反映まで GitHub Actions が実行する。ローカルで同じ処理をするときは下の手順を使う。

## 補足

- 売却着金は PayPay まで2〜3営業日、銀行引出はさらに2〜3営業日。買い直しは PayPay 残高があれば市場時間中に即時。
- 銀行→PayPay入金は即時前提。
