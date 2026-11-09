# NISA 判断支援ダッシュボード

PayPay NISA の保有・積立・市場ニュースをもとに、**売買の判断支援**と**資金スケジュール**を静的サイト（GitHub Pages）で可視化します。注文は自動では行いません。

## GitHub Pages URL

| ページ | URL |
|--------|-----|
| ダッシュボード（トップ） | https://kuimac.github.io/kabu/ |
| 同上（index.html） | https://kuimac.github.io/kabu/index.html |
| スタイルシート | https://kuimac.github.io/kabu/assets/app.css |
| チャート用JS | https://kuimac.github.io/kabu/assets/charts.js |

リポジトリ: https://github.com/kuimac/kabu

## できること

- 保有銘柄の評価額・損益・構成比
- 先頭の**トピック（話題）**: 緊急シグナル＋JPX等のニュース上位
- 透明なルールに基づくシグナル（保有継続 / 要監視 / 買い検討 / 売り検討 / 入金推奨）
- 積立と売却着金（PayPay +2〜3営業日、銀行引出さらに +2〜3営業日）のカレンダー
- 日本市場の**開場前（08:00 JST）**と**閉場後（15:30 JST）**に自動更新（平日・GitHub Actions）＋手動更新

## 個人情報について

リポジトリに置いてよいもの: 銘柄名・口数・評価額・損益（公開前提）

置かないもの: 口座番号、銀行情報、氏名、ログイン情報、API秘密鍵（`.env` は gitignore）

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/update_all.py
```

生成物: `docs/index.html`（ローカルなら `docs/` をブラウザで開く）

### 手で直すCSV

| ファイル | 用途 |
|---------|------|
| `data/holdings.csv` | 保有口数・取得額 |
| `data/trades.csv` | 売買履歴。約定が無い保有は初期記録 |
| `data/signal_ranks.csv` | 買い・売りの強さ上位（自動計算） |
| `data/accumulations.csv` | 積立設定 |
| `data/cash_balance.csv` | PayPay残高（手入力） |
| `data/watchlist.csv` | 監視・おすすめ銘柄 |

投信の協会コードは `association_code` 列。eMAXIS Slim は三菱UFJ公式APIで基準価額を取得します。

PayPay証券の投信口数は **千口表示** として `unit_multiplier=1000` で評価額を計算しています（S&P500・オルカンで公式NAVと一致を確認）。表示口数や取得額がアプリと違う場合は `holdings.csv` を直して再実行してください。

ニッセイAI・ダイワインドは公式JSON APIがないため、当面は `holdings.csv` の評価額を手更新（または implied NAV）します。

`data/trades.csv` は売買履歴です。いまの保有に約定データはないため、2026-11-09 14:28 JST の値段・損益額・率を区分「初期記録」として保存しています。購入日は空欄で、画面では未記録です。実際の買付・売却は行を追加します。初期記録は約定ではありません。

## スマホから更新する

データ取得、分析、Pages への反映は GitHub Actions が行います。PC は不要です。

1. GitHub アプリでこのリポジトリの Issue「スマホから更新」を開く
2. コメントに `/update` と書いて送信する
3. 1〜2 分後、同じ Issue に結果（市場・評価額・シグナル）が返信される
4. 返信のリンクから公開ページを開く。反映が遅いときは少し待って再読み込みする

同じ更新は、Actions タブの **Update NISA dashboard** → **Run workflow** からでも実行できます。平日の開場前・閉場後の自動更新はそのまま動きます。

`/update` はリポジトリの所有者のコメントだけが起動します。

### スマホで保有を直してから更新する

次のファイルを GitHub アプリで編集して保存してから、`/update` を送ります。

| ファイル | 用途 |
|---------|------|
| `data/holdings.csv` | 保有口数・取得額 |
| `data/trades.csv` | 売買履歴（初期記録と、以降の約定） |
| `data/signal_ranks.csv` | 買い・売りの強さ上位（自動計算） |
| `data/accumulations.csv` | 積立設定 |
| `data/cash_balance.csv` | PayPay残高 |
| `data/watchlist.csv` | 監視銘柄 |

## GitHub Pages 公開手順

1. このリポジトリを GitHub に push
2. Settings → Pages → Build and deployment → Source を **Deploy from a branch**
3. Branch: `main`（または `master`）、Folder: **/docs** を選択して Save
4. Actions の書き込み権限: Settings → Actions → General → Workflow permissions で **Read and write** を許可
5. 初回は Actions の **Update NISA dashboard** を手動実行（workflow_dispatch）

公開URLは上記「GitHub Pages URL」を参照。

## データ源

- 投信（eMAXIS Slim）: [三菱UFJアセットマネジメント 投信情報API](https://www.am.mufg.jp/tool/webapi/)
- 投信（ニッセイAI・ダイワインド等）: Yahoo!ファイナンス HTML（APIが無い場合の補完）
- 株・指数: yfinance（IHI=`7013.T`, NVDA, TOPIX連動=`1306.T`）
- ニュース: [JPX RSS](https://www.jpx.co.jp/rss/) ＋ 株探・みんかぶ（先頭ページのみ）
- 営業日: `jpholiday`

### スクレイピングの負荷対策

個人利用の範囲で、サーバーに負担をかけないよう次を実装しています。

- **ホスト単位で最低約8秒＋ジッター**空けてから次リクエスト（`SCRAPE_INTERVAL_SEC` / `SCRAPE_JITTER_SEC` で変更可）
- 並列クロールなし・必要ページのみ（投信は協会コード単位、ニュースは各サイト1ページ）
- `robots.txt` を確認して不許可パスはスキップ
- HTTP 429/503 時はバックオフして1回だけ再試行
- 公式APIがあるものはスクレイピングより API を優先

```bash
# 例: 間隔をさらに広げる
export SCRAPE_INTERVAL_SEC=12
export SCRAPE_JITTER_SEC=3
python scripts/update_all.py
```

## Cursor Skill

`.cursor/skills/nisa-refresh/SKILL.md`  
「NISA更新」「データ取得」「分析して」などでエージェントが `update_all.py` を実行します。

## 注意

本ツールは投資助言ではありません。最終判断はご自身で行ってください。
