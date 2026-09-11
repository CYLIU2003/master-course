# 契約電力の有料超過と検証の整合

## 確認した停止原因

`43fe848f4b962cb2efc91d686af7818683521af7` の新規Prepareによる渋21/22/23キャンペーンで、冬・春・夏はそれぞれ168/168時間、独立物理検証、最終会計を通過した。秋（2025-11-03開始、祝日を含む1,621便）は159時間を通過後に停止した。旧成果物は次の場所に保持する。

`C:/master-course-worktrees/shibu21-23-pv-reserve-20260912/output/shibu21_23_exact_pv_reserve_campaign_20260912_run2`

秋のhour159の予測窓では、slot669の購入67.32609273735918 kWhに対し、契約200 kW・15分の購入枠は50 kWhだった。ソルバーは明示された有料超過policyに従い、17.326092737359165 kWhの超過を出力していた。共通検証がpolicyを参照せず超過を拒否した。これは丸め差ではなく約69.30437 kWの超過であり、hard cap条件での実行可能性を示すものではない。slot669はhour159の実行対象slot636〜639より先の予測部分であり、その時点の実行費用へ先取り計上してはならない。

旧秋の週間費用は未成立。停止した結果を後からacceptedへ書き換えない。

## 数式と変更範囲

営業所d・slot tの購入エネルギーを `G = grid_to_bus + grid_to_bess` [kWh]、正の契約値を `P` [kW]、時間幅を `dt` [h] とすると、観測超過量は `E = max(G - P * dt, 0)` [kWh]。

- 明示 `enable_contract_overage_penalty is True`: `E` と計上超過量が1e-6 kWh以内で一致することを必須にする。欠損、不足、過大、非有限、負値を不合格とする。負値には数値許容差を適用しない。
- False・欠損・不正なpolicy: 従来のhard検証を維持し、1e-6 kWhを超える購入超過を拒否する。正式prepared inputは正規化された明示boolを持つ。
- 非正の契約値が有限上限を表さない既存の共通検証仕様は保持する。
- `contract_power_violation_count` はhard違反件数、`contract_overage_accounting_violation_count` は計上不整合件数。両方とも必須の0件ゲート。
- 観測値は `contract_power_exceedance_count`、`contract_power_excess_kwh`、`contract_overage_reported_kwh` として保存する。softで合格しても超過を隠さない。

既存費用は `contract_overage_cost = reported_overage_kwh * penalty_yen_per_kwh`。当該ケースは500 JPY/kWhであり、上記slotの予測超過費用は約8,663.046369円。電気量・燃料・SOC・単価・ソルバー制約を変更せず、明示policyに対する検証の不一致を修正する。受入集合はsoft設定と計上が整合する解についてのみ広がる。hard上限、将来PVの非参照、hourly execution prefix、出帰庫、終端SOC、60台のfleet、全接続は保持する。

2026-09-10の[季節拡張の既存実行契約](SEVEN_DAY_SEASONAL_EXTENSION_20260910.md)は、hard設定を失敗、soft設定を超過kWhと費用の記録として区別している。2026-07-29由来のnative回帰は「softでも共通検証が拒否する」旧挙動を固定していたため、その期待を既存実行契約へ更新する。同一native解がsoftで超過計上とともに受理され、hardへ変えると拒否されることを検証する。

## 検証と研究上の境界

関連41テストが通過し、独立コードレビューの微小負値P1を修正、残るP0/P1は0件。最終全体回帰は2,228 passed / 既存PowerPoint証拠2 failed（98.36秒）。JUnitは `output/exact_depot_factor_validation/pytest-contract-overage-policy-final.xml`。初回全体回帰の旧soft拒否期待1件は、前節のnative soft/hard検証へ更新して通過した。

修正後の秋の保持状態159〜167時は全9回の求解・履歴推定PV実行を通過した。証拠は `output/rolling_autumn_contract_policy_final_diagnostic`。各回の契約・計上違反は0件で、初回の超過量17.326092737359176 kWhと計上17.326092737359165 kWhは一致した。最終BESSは1199.9999999999998 kWhで、既存物理許容差内の下限1200 kWhを保持する。新しいclean SHAで全四季を再Prepare・再求解する。保持入力の再現は診断であり、新規計算の代替証拠にはしない。最終週間費用は accepted rolling chain の `executed_day_accounting.json` のみを採用する。

新clean SHAによる四季完走は本記録作成時点で未完了。既存PowerPoint証拠2件、宣言10%のギャップ未達、正式fleet-contractの未宣言、2026時刻表・2025評価日、2024年だけの学習という制限は残る。PVは履歴推定PVであり実測発電量と称さない。結果は引き続き **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**、研究リリースは **BLOCKED**。
