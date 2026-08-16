# EMA Screener

JPX400の現在構成銘柄を対象に、EMA9/21押し目戦略のBUY候補を毎営業日自動更新する独立スクリーナーです。

## 表示内容

- 日足CのBUYシグナルが確定した銘柄
- 63日モメンタム順位
- 週足フィルターのOK / NG（参考情報）
- 終値、日足・週足EMA
- TradingViewチャートへのリンク
- ランキングCSVのダウンロード
- データ・CSS・JavaScriptを内蔵した単一HTML（`EMA_Screener.html`）

## 売買ルール

BUY条件は次のすべてを満たした確定日足です。

1. 前日終値が前日EMA9より上
2. 当日の値幅がEMA9〜EMA21帯に入る
3. 当日終値がEMA21より上
4. 陽線かつ当日終値が前日高値を上回る

シグナル日の翌営業日始値をエントリー想定とします。週足OK / NGは表示しますが、バックテスト1位戦略には週足の買いフィルターがないため、NGも候補から除外しません。出口は確定週足のEMA9がEMA21を下回った後の翌営業日始値です。

## GitHub Pagesを有効にする

1. リポジトリの `Settings` → `Pages` を開く
2. `Build and deployment` のSourceで `GitHub Actions` を選ぶ
3. `Actions` → `Update EMA signals` → `Run workflow` を一度実行する

以後は平日16:45（日本時間）に自動更新します。取引所休業日は直近取引日の結果を表示します。GitHub Actionsの混雑やYahoo Finance側の状態により、開始遅延・取得失敗が起こることがあります。その場合は手動で再実行してください。

生成される`index.html`と`EMA_Screener.html`にはランキングデータを直接埋め込んでいます。そのため、`data.json`への通信ができない環境や、ダウンロードしたHTMLを単体で開いた場合でも閲覧・検索・CSV保存ができます。

## ローカル実行

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
cp -R site _site
python -m src.screener --output _site
python -m http.server 8000 --directory _site
```

## 注意

価格データはYahoo Financeの調整後OHLCを使用します。構成銘柄リストは定期的な更新が必要です。本ツールは投資助言ではなく、将来の利益を保証しません。
