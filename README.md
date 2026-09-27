# 敵情報検索ツール

アークナイツ（日本版）の敵を、登場コンテンツ・種族・ランク・攻撃属性などで絞り込んで探せるツールです。
データの読み込み以外はブラウザ内で完結し、GitHub Pages でそのままホスティングできます。

## ファイル構成

```
index.html                         画面
style.css                          デザイン
script.js                          検索・絞り込み
data/enemies.json                  敵データ（scripts/build_data.py で生成。手で編集しない）
data/regions.json                  勢力/地域の手動対応表
scripts/build_data.py              ゲームデータ → enemies.json の変換スクリプト
.github/workflows/update-data.yml  週1回データを自動更新する GitHub Actions
```

## データについて

- 元データは [ArknightsAssets/ArknightsGamedata](https://github.com/ArknightsAssets/ArknightsGamedata) の `jp/gamedata` です。
- 敵図鑑に載っている敵（非表示のものを除く）を対象に、名前・ランク・種族・能力・説明とレベルごとのステータスを取り込みます。
- 登場コンテンツは各ステージの敵編成（`levels/`）から自動で集計しています。
  - メインテーマ: 章ごと
  - イベント: サイドストーリー・オムニバス（常設化されたものを含む。復刻は初回開催と同じイベントとして扱う）
  - 統合戦略: テーマごと
  - 特殊モード: 保全駐在・殲滅作戦・危機契約・生息演算、および導灯の試練・協心競技・鋒矢突破・堅守協定などのイベント内モード
  - その他: 資源収集・物資調達、オペレーター密録
- 勢力/地域はゲームデータに存在しないため `data/regions.json` の手動対応表から付与します（空の間は画面に表示されません）。
  - `byEnemy`: 敵ID → 地域の配列（最優先）
  - `byContent`: イベント名やメインテーマの章名 → 地域の配列。個別指定のない敵は、初登場したメインテーマ/イベントの地域を引き継ぎます。

## データの更新

GitHub Actions が毎週月曜の朝に最新データで `data/enemies.json` を作り直し、変更があればコミットします。
リポジトリの Actions タブから「Update enemy data」を手動実行することもできます。

手元で作る場合:

```bash
git clone --filter=blob:none --no-checkout --depth 1 https://github.com/ArknightsAssets/ArknightsGamedata src
cd src && git sparse-checkout set --no-cone /jp/gamedata/excel/ /jp/gamedata/levels/ && git checkout && cd ..
python3 scripts/build_data.py src/jp/gamedata data/enemies.json
```

## ローカルで確認する

`fetch` を使うため、ファイルを直接開くのではなく簡易サーバー経由で開いてください。

```bash
python3 -m http.server 8000
# http://localhost:8000 を開く
```

## GitHub Pages

Settings → Pages で Source を「Deploy from a branch」、Branch を `main` / `/ (root)` にすると公開されます。
