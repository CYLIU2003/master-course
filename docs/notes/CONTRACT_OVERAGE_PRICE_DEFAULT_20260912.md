# 契約超過単価の未設定値と確定会計の修正

## 確認した問題と旧結果の訂正

凍結 `a812aeb2380c3482dfbfa63935b8217b8b4d4b77` の新規Prepareによる冬・春は、それぞれ168時間と独立物理検証を通過した。しかし春の実行超過量31.04537962105529 kWhに対し、確定会計の超過料金が0円だった。独立の費用再計算で15,522.689810527645円の過少計上を確認し、2026-09-12 05:33 JSTに夏のPrepare中のキャンペーンを停止した。旧春の「会計成立」は撤回する。旧SHAの物理検証と費用採用は区別する。

旧成果物は `C:/master-course-worktrees/shibu21-23-contract-policy-20260912/output/shibu21_23_exact_contract_policy_campaign_20260912` に保持する。`operator_stop_accounting_mismatch.json` が停止理由を記録する。保存結果は書き換えない。冬の超過料金差は1e-6円未満だったが、修正後の証拠として再利用しない。さらに古いSHAの「会計通過」記録も当時の検査結果であり、今回判明した単価不一致を検査した証拠ではない。

## 到達経路と原因

`run_exact_seasonal_campaign.py` から季節診断、`run_hourly_charging_reoptimization.py` の実行prefix結合、`CostEvaluator.evaluate` へ到達する。Builderは未指定単価をmetadataに `None` として保存していた。native Stage 1/2はこれを500 JPY/kWhと解釈したが、Evaluatorの `float(metadata.get(key, 500) or 0)` は0と解釈した。春の予測窓では超過がなく、履歴推定PVによる実行時だけ超過したため、最終会計で表面化した。最終会計の再評価自体が欠落していたわけではない。

## 数式・比較可能性への影響

実行slotの契約超過量を `E_dt = max(grid_to_bus_dt + grid_to_bess_dt - contract_kw_d * timestep_hours, 0)` [kWh]、単価を `r` [JPY/kWh] とすると、料金は `C = r * sum(E_dt)` [JPY]。明示soft policyと費用componentが有効な場合に計上する。

- 未指定または `None` の単価を、native solverと共通の定数500 JPY/kWhへ統一する。明示0および明示単価を保持し、無効componentの費用は0とする。
- Builderのcanonical metadataへ有効数値を保存し、直接生成・旧metadataの `None` もEvaluatorで同じ意味にする。
- 実行prefixを結合した最終会計で、実行超過量と報告超過量の差を1e-6 kWh、期待料金と報告料金の差を1e-6円以内とする。欠損・非有限・負の値、不一致では `eligible=false` と理由を保存する。
- 予測だけの将来slotは料金へ含めない。費用component無効・明示0は正当な0料金として区別する。

native solverの既定単価と制約は変わらない。変更はcanonical単価の正規化と会計・受入検査であり、時刻表、operator、距離、fleet、燃料、SOC、PV、充放電指令、全接続は変えない。ただし過少計上していた最終料金と評価値は増えるため、旧結果を修正後の研究証拠へ付け替えず、全四季を新しいclean SHAで再実行する。

## 保持春状態による原因確認

`output/spring_contract_price_repricing_diagnostic/repricing_report.json` は **DIAGNOSTIC_REPRICING_NOT_FRESH_WEEKLY_EVIDENCE**。保存済み実行計画を再集計した結果は以下。

| 指標 | 値 |
|---|---:|
| 旧合計 [JPY] | 4241099.626143190 |
| 再集計合計 [JPY] | 4256622.315953718 |
| 追加超過料金 [JPY] | 15522.689810528 |
| 実行超過量 [kWh] | 31.04537962105529 |
| 日別合計との差 [JPY] | 0 |

実行エネルギーflow hashは不変。電力量・燃料量・CO2・車両使用費等は不変で、超過料金とそれを含む集計値だけが変わった。この診断は新規週間求解の代替ではない。

## 検証と残る条件

新規回帰12件と関連97件が通過した。未指定・None・明示0・独自単価・無効flag、予測超過0からPV不足で実行超過が発生するprefix、将来slot除外、日別会計照合、正の超過を0円に改変した場合の受入拒否を確認した。Lunaによる独立コードレビューの残P0/P1は0件。

全体回帰は **2,240 passed / 既存PowerPoint証拠2 failed、102.56秒**。JUnitは `output/exact_depot_factor_validation/pytest-contract-price-release.xml`。残る2件は `test_original_and_all_bound_sources_unchanged` と `test_unrelated_presentation_parts_remain_byte_identical` であり、資料のhash・部品集合の既存不一致を保持する。`git diff --check` も対象変更で通過した。

新clean SHA `e09fb550` で全四季の新規Prepare・各168時間・最終物理会計が通過し、独立監査も完了した。春の新規実行では超過料金15,522.689810527645円、総費用4,256,622.315953718円が正しく保存され、日別差0円。夏・秋の正の超過料金も独立grid再計算と一致した。[四季完走と丸め前の証拠](SHIBU21_23_FOUR_SEASON_COMPLETION_20260912.md)。既存PowerPoint証拠2件、宣言10%の最適性ギャップ未達、正式fleet-contractの未宣言、2026時刻表と2025評価日、2024年だけの予測学習という制限は残る。結果は **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**、研究リリースは **BLOCKED**。
