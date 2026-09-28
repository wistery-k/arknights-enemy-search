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
  - 特殊モード: 保全駐在・殲滅作戦・危機契約・導灯の試練など
  - その他: 資源収集・物資調達、オペレーター密録
  - 生息演算・協心競技・堅守協定・鋒矢突破は、それぞれ独立したカテゴリとして各回を並べます。
- 絞り込みの「初登場コンテンツ」は、各敵が初めて登場したコンテンツ1つだけで判定します。
  初登場は登場ステージの開始日がいちばん早いもの（イベントは復刻ではなく初回開催日、危機契約・保全駐在・殲滅作戦のローテーションマップはシーズンごとの開始日）。
  常設の殲滅作戦・資源収集・密録など開始日がわからない登場は、日付のわかる登場が無いときだけ初登場として扱います。
  詳細パネルの登場コンテンツ一覧には、初登場以外も含めてすべて表示します。
- 勢力/地域はゲームデータに存在しないため `data/regions.json` の手動対応表から付与します（空の間は画面に表示されません）。
  - `byEnemy`: 敵ID → 地域の配列（最優先）
  - `byContent`: イベント名やメインテーマの章名・統合戦略のテーマ名 → 地域の配列
  - 個別指定のない敵は、初登場したコンテンツの地域を引き継ぎます。初登場は開始日のいちばん早いコンテンツで、
    そこに地域が無い場合（危機契約など）は次に早いコンテンツを使います。
    メインテーマ第8章までの公開日はゲームデータに正しい日付が無いため、`scripts/build_data.py` の `MAIN_RELEASE_JP` に公式告知の日付を書いています。

## 画面

- 条件を何も指定していないときは、地域ごとのタイル（体数と代表的な敵）を表示します。タイルを押すとその地域で絞り込んだ一覧になります。
- 一覧の並び順は「初登場が新しい順」が既定です（図鑑順・ステータス順にも切り替え可）。

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

Settings → Pages で Source を「GitHub Actions」にしてください。`main` への push とデータ自動更新のたびに
`.github/workflows/deploy-pages.yml` が公開します。

公開時に `build-info.json`（コミット番号と日時）が作られ、画面のタイトル下に「更新 2026-09-28 18:30（abc1234）」の形で表示されます。
開いているページより新しい版が公開されていると、画面上部に再読み込みの案内が出ます。
CSS・JS・データの参照にはコミット番号が付くため、古いファイルがキャッシュに残ることもありません。
