# 渋21〜24 四季診断の資源不足と最終状態（2026-09-11）

**DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS — 研究リリースBLOCKED**

4系統合算の全4週で完全Prepareと入力監査が終了した。冬週のモデル構築でPCの
メモリー残量が逼迫したため処理を停止し、春・夏・秋のsolverは実行していない。
数学的なINFEASIBLE判定や、成立した週間計画は得られていない。

## 入力4週と実行状態

対象のclean frozen SHAは `e8bd9d6caee5b24ff8b68ad031a4a7f8d4e81c93`。
作業場所は `C:/master-course-worktrees/shibu21-24-bess-flex-20260911`。

| 季節・開始日 | 便数 | 完全Prepare所要秒 | 入力監査 | solver最終状態 | Rolling |
|---|---:|---:|---|---|---|
| 冬 2025-02-03 | 3,182 | 924.92 | 通過 | RESOURCE_LIMIT_STOP | 0 / 168 |
| 春 2025-05-12 | 3,182 | 924.52 | 通過 | NOT_EXECUTED_RESOURCE_BLOCK | 未実行 |
| 夏 2025-08-04 | 3,182 | 919.56 | 通過 | NOT_EXECUTED_RESOURCE_BLOCK | 未実行 |
| 秋 2025-11-03 | 3,045 | 846.13 | 通過 | NOT_EXECUTED_RESOURCE_BLOCK | 未実行 |

全週で同じ有効60台（BEV35・ICE25）、22パターン、UNKNOWN operator 0、
非正値距離0。保存前後・canonical入力の路線metadata、親シナリオの不変性、
strict transition、turnaround、vehicle-trip compatibility、coverageの監査を確認した。
各prepared JSONは読取前後のSHA-256が一致する。物理検証・会計適格性・最終週間費用は
全週nullであり、費用0として扱わない。

BESSは容量20〜80%、日末・週末の初期SOC復元なし、途中窓もminimum_only。
容量6,000 kWh、初期3,000 kWh、上下限1,200/4,800 kWh、充放電上限900 kWを
保持した。BEVの終端条件、毎日の弦巻帰庫、接続条件、pruning 0は維持した。

## 停止の観測と範囲

冬週のrunner開始は19:05:55 JST、モデル構築へ入ったことを記録し、19:21:38の
サンプルで当該Pythonのprivate memory 28.43 GiB、OSの空きvirtual memory
0.58 GiBを観測した。実機の物理RAMは約31.7 GiB。19:22:09にコマンドラインと
作成時刻を確認したこの診断のPID 10336だけを停止した。停止処理時にはprivate
26.691 GiB、空きvirtual 3.338 GiBへ戻っていたが、直前の急な逼迫を根拠に停止した。
これらは有限回の観測値であり、連続計測した最大値・最小値とは呼ばない。

他3週も同等規模であるため、同じPC上で自動再試行していない。途中のnative
progressやseasonal_evaluationは書き換えず、停止と未実行を別の観測JSONに記録した。
未完了のネイティブ進捗を、全4週完了の最終報告として使用してはならない。

## 発見・修正した重複処理と残る制約

実行経路は4路線runner → 共有weekly solver → `MILPOptimizer.solve` →
`_lightweight_model_stats` → Phase 3 solver adapterである。統計取得では
`enumerate_arc_pairs` の全tupleリストを件数取得だけのために生成していた。
既存の `arc_pruning_summary` が同じ対象の正確な件数を持つため、MAINでその
`arc_count_after_successor_pruning` を再利用する変更を加えた。値0は保持し、
このmetadataを持たない代替builderにだけ従来の列挙を残す。

数式・目的関数・単位・制約・許容値・選択する弧・pruning・会計は変更していない。
可用車、車種互換性、route-band、baseline successor保持を含むfixtureで、
capなし/1/8の件数一致と、統計経路が全arcリストを生成しないことを検査した。
関連18テストが通過した。GPT-5.6 Lunaの独立レビューでは対象2ファイルのP0/P1は0件。
これは統計処理の修正範囲に限る確認であり、モデル全体の承認ではない。

修正後の全体回帰は **2,127件通過・2件失敗、95.56秒**。失敗は既存PowerPoint原本
hashとspeaker-notes版の部品集合の不一致。JUnitは
`output/desktop_parity_validation/pytest-model-stats-final.xml` に保存した。

実solver adapterは引き続き車両別の全接続リスト、接続キーの複製、Gurobi変数を
生成する。Prepareの接続precheckは冬・春・夏が4,531,083組、秋が4,148,246組で、
これに車両60台を乗じる規模の参考値は約2.72億/2.49億組になる。この参考値を実測の
最終MILP変数数と同一視しない。統計用の一度の重複を除去しても、実solver側の
大規模な表現が解決したとは言えない。画面の100万行ページ取得試験もこの問題を検証しない。

指定12 threadsはPythonの接続列挙を制御しない。solver adapterの32 GB
SoftMemLimitと0.5 GB NodefileStartはPhase 4統合モデルの設定であり、今回の
Phase 3 Stage 1/2に適用されていない。スレッド数変更だけで解決するという説明はしない。

## 残る作業と証拠

次の実行には、候補と物理条件を保つ実モデル表現の省メモリー化、または必要メモリーを
満たす実行環境の検討・検証が必要である。無断のsuccessor削減・ICE集約・制約緩和で
ケースを置き換えない。コード変更後は新しいclean commitから入力・実行を検証する。
今回の停止記録を変更後HEADのsolver証拠へ付け替えない。

時刻表は2026年9月版、気象評価は2025年、予測の学習は2024年のみのproxy。
2025年の実運行再現ではない。秋は11月3日の祝日で137便少ないため、季節差を
PVだけの因果効果として解釈しない。正式provenance、全4週168時間の実行・物理検証・
最終会計、fresh clean-commit正式実行、既存PowerPoint証拠の不整合は未解消である。

検証済みのElectron portable版とUI検証は [Tk対応表](DESKTOP_TK_PARITY_20260911.md)
を参照。今回の修正はworkspace側Pythonのみで、配布EXEのReact/Electronコードは変わらない。

- 全4週の監査・prepared hash・実行状態: `C:/master-course/output/desktop_parity_validation/four_route_terminal_observation.json`
- 親側停止記録・計測: 同フォルダーの `seasonal_resource_stop.json`、`seasonal_resource_samples.jsonl`
- 完全Prepare: 凍結worktree内 `output/shibu21_24_seasonal_inputs_validated_20260911/summary.json`
- native実行出力と独立停止観測: 凍結worktree内 `output/shibu21_24_seasonal_diagnostics_20260911/`、`resource_stop_observation.json`
