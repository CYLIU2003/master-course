# 修論執筆ベースライン v1

## 状態

`THESIS_AUTHORING_BASELINE_COMPLETE_WITH_OPEN_EXPERIMENTS`

本ディレクトリは、正本実験 `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` の結果を、研究課題、数理モデル、実験条件、結果、考察、先行研究および口頭審査資料へ変換した読取専用の派生成果物である。Prepare、solver、Rolling、正本artifactおよび既存reporting auditorは変更していない。

## 証拠の優先順位

1. `docs/evidence/weather_dispatch_rerun_bb0c005/**` のGit管理済み正本
2. `docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources/**` のexact-byte入力補助証拠
3. 正本run directoryに残る24個のRolling step結果（SHA-256を本ディレクトリのmanifestへ保存）
4. `docs/thesis/weather_results_bb0c005/**` の検証済み要約
5. 本ディレクトリの再集計・文章・図表

数値が食い違う場合は上位を採用し、派生文書を修正する。Stage 1の近似目的とStage 2のcanonical cost、本モデルの費用定義に基づく24時間Rolling実行日評価額を混同しない。

## 主要な到達点

- RQ1～RQ3と限定付き貢献を固定した。
- 現行Phase 3を統合MILPではなく二段階法として定式化した。
- 22件の固定配車候補をSUNNY/RAINへ相互適用した行列を再分析した。
- ローカル正本runの24個の`hourly_solver_result.json`から各実行prefixを抽出し、96スロット系列を復元した。両ケースとも公開済み`executed_energy_flow_hash`、日合計、Prepared ID、scenario ID、実験SHAと一致したため`FOUND_AND_VERIFIED`である。
- claim-evidence matrix、literature matrix、不足証拠台帳、章草稿、想定問答、指導教員判断メモを作成した。
- 新規solver runは0件である。小規模統合oracle、候補範囲感度および価格・消費電力量感度は未実施であり、主張範囲を広げていない。

## 再生成

```powershell
.\.venv\Scripts\python.exe tools\thesis_authoring\build_authoring_evidence.py
.\.venv\Scripts\python.exe -m pytest -q tests\thesis_authoring
```

ツールは正本run directoryが無い環境ではfail-closedする。欠落時に96スロットを推測生成しない。

## ディレクトリ案内

- `01`～`08`: 研究設計、システム、定式化、実験、結果、考察
- `09`: 修論中の主張と正本証拠の対応
- `10`: アクセス確認済み文献と本研究との差分
- `11`: 不足証拠の優先度台帳
- `12`: 指導教員が決めるべき事項
- `13`: 口頭審査の想定問答
- `14`: 執筆・提出前チェックリスト
- `chapter_drafts`: 章ごとの常体ドラフト
- `tables`: 22候補の再分析表
- `figures`: 候補および96スロット図（PNG/SVG）
- `evidence_supplements`: 96スロットCSVと派生証拠manifest

## 使用禁止の表現

本結果を「統合最適化」「大域最適」「両ケース1%最適」「一般的な晴雨効果」「実支出」「総運用費」「LCC」「導入経済性の証明」「実運用可能性の証明」と呼ばない。使用する中心表現は「評価した有限候補集合から選択された、物理的・会計的に妥当なPhase 3二段階実行可能解」である。
