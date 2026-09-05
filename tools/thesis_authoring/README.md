# 修論・進捗資料の作成ツール

リポジトリルートから実行します。既存の入力ハッシュに含まれるスクリプトは移動しません。
出力の正本は [Outcome](../../outcome/README.md)、描画の作業領域は `output/` です。

| 用途 | スクリプト | 注意 |
|---|---|---|
| 凍結結果から執筆用根拠を作成 | [build_authoring_evidence.py](build_authoring_evidence.py) | 既存の入力・承認条件を維持 |
| 執筆bundle検証 | [validate_authoring_bundle.py](validate_authoring_bundle.py) | 検証PASSは実験承認と別 |
| 本人向け説明分析 | [build_progress_explanation.py](build_progress_explanation.py) | 既存manifestのハッシュ対象 |
| 研究進捗スライド | [build_progress_presentation.mjs](build_progress_presentation.mjs) | 9月の説明資料用 |
| 8月資料の改訂 | [build_august_progress_revision.mjs](build_august_progress_revision.mjs) | 正本を上書きせず別出力先で再生成 |
| 8月資料の最終梱包 | [maintenance/package_august_20260905.mjs](maintenance/package_august_20260905.mjs) | 下記の限定用途 |

`maintenance/package_august_20260905.mjs` は作業領域に散在していた一回限りの
梱包処理を保管したものです。2026-09-05の固定パス・PPTXハッシュに限定され、
実行すると既存のreceiptとinventoryを更新します。汎用ツールではなく、通常は再実行しません。
今回の整理では移動のみで実行していません。

再生成の条件・コマンドは [8月改訂版README](../../outcome/2026-09-05_august_progress_revision/README.md)
を参照してください。公開済みPPTXとmanifestは整理目的で書き換えません。
