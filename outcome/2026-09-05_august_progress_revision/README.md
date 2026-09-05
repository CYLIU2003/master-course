# 8月進捗資料のブラッシュアップ版

元の8月資料を土台に、研究課題・先行研究との比較・方法の説明・結果の解釈を改訂しました。**本編18枚＋補足4枚**です。新しいsolver実験、制約変更、承認の代行はしていません。

- [改訂版PowerPoint](august_progress_revised_20260905.pptx)
- [最初の15分：自分の言葉で説明する](understanding_and_next_step.md)
- [旧版から何を変えたか](revision_log.md)
- [全22枚の発表者ノート](speaker_notes.md)
- [出典と入力ハッシュ](source_manifest.json)
- [成果物のSHA-256一覧](artifact_inventory.json) ／ [構造・図表の検証記録](validation_receipt.json)

## 今回強くしたところ

1. 「何を作ったか」だけでなく、**何を確かめたい研究か**を3つの問いに分けました。
2. 混成配車自体の新規性は主張せず、近い文献の強み・適用範囲・取り入れる方法を比較しました。
3. Stage 1緩和、候補ごとのStage 2、前日費用による選択、固定配車のRollingを分けて説明しました。
4. 元の配車・費用・電源フローに、営業距離比、108便の担当変更、96区間の電力時系列、BESS残量を接続しました。
5. 次点差・raw/certified gap・要求時間上限・実測runtimeの意味を修正し、未識別の原因を断定しない考察にしました。

元の表紙・背景・実験条件図・電源フロー図、16:9サイズ、濃紺・青・緑の配色、日本語フォントを継承しています。数値表とグラフは編集可能です。原版の18枚は上書きしていません。

## 研究の到達点

凍結実験SHAは `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d`、資料作成時HEADは `c0b82ae30e874f65fabcfec94599982023bc3ca6`。dirty worktree上の資料作成を、cleanな新規実験と呼びません。

示せるのは、固定非PV入力に対する二つのPV条件で、全264便・物理・24/24 Rolling・会計が成立する選択計画を得たことです。二段階法の統合大域最適性、単純方式への優位性、一般天候効果、研究releaseの承認は未達です。元の `teacher_release_status=BLOCKED` を維持します。

## 確認したこと

- 原版SHA-256：`15de444f1407faa24ffb83a86dc2c60999edeb087fea144400dda8248f365b27`。変更なし。
- 改訂PPTX SHA-256：`377ba861be7872e96dbd5f0197bd8ee03e23dfc7a934ef2863d1bd05cd1339ae`。
- 原版18枚・改訂版22枚を描画して確認。表11点・グラフ7点・発表者ノート22枚。
- OOXML構造・図表データと埋込ワークブック・配置／日本語フォント指定の検証PASS、最終配置警告0。
- 図表と集計のローカルテスト14件PASS。凍結結果の既存strict validatorもPASS。solverは起動していません。
- グラフ用の埋込値だけ小数6桁に丸めました（変換後単位で最大0.0000005）。正本の物理量・会計・CSVは変更していません。
- ネイティブPowerPoint/Google Slidesでの編集・保存・再読込は未確認です。提出前に利用端末で日本語フォントと表示を確認してください。人間による独立レビューは別途必要です。

## 再確認・再生成

リポジトリルートで実行します。以下は資料検証・再生成だけで、最適化実行コマンドではありません。

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_august_progress_revision.py tests/test_progress_explanation.py
& .\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.build_thesis_weather_result_package import load_and_validate_bundle; load_and_validate_bundle(Path('docs/evidence/weather_dispatch_rerun_bb0c005')); print('Frozen evidence validation PASS; no solve')"
& 'C:\Users\RTDS_admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' tools/thesis_authoring/build_august_progress_revision.mjs --help
```

再生成時は既存成果物を上書きしないよう、**まだ存在しない**出力先と作業先を指定します。PPTX内部ID・ZIPメタデータによって生成物全体のハッシュは変わり得ます。上記pytestは本納品の既定フォルダを検証します。別出力先の再生成では、builderの入力照合と指定作業先の `validation.json` に残る検証結果も確認してください。

```powershell
& 'C:\Users\RTDS_admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' tools/thesis_authoring/build_august_progress_revision.mjs --finalize --output-dir outcome/2026-09-05_august_progress_rebuild_01 --build-dir output/august_progress_rebuild_01
```

既存の正式実験は [判断シート](../../docs/research/november_2026/signoff/01_decision_sheet.md) と [個別コマンド集](../../docs/research/november_2026/signoff/exact_execution_commands.ps1) に従い、署名・実行前検証・cleanな凍結SHAを満たしてから行います。PS1全体の一括実行は禁止です。GitHub Actions・Copilot・課金機能は使用／有効化していません。
