# 2026年11月向け追加実験の事前登録

## 判定

`P0_ADAPTERS_READY_FOR_HUMAN_APPROVAL`

本ディレクトリは、計画commit `132302a736f72e04aa1fbe07b8d4945fe56c5531` から作成した **ADAPTER_ONLY_NO_EXECUTION** の成果である。Prepare、Gurobi、Phase 3、Phase 4、Rolling、実HTTPは一度も実行していない。正本artifact、`docs/thesis/authoring_v1/`、main、PR #7、PR #8は変更していない。

## 結論

- P3-SCALARは既存config/metadataでは実現不能で、`P3_SCALAR_UNSUPPORTED`である。P3-DEPLOYEDとP4-SCALARの差は純粋な分解gapではなく、`deployed_phase3_to_scalar_integrated_reference_distance`と呼ぶ。
- 小規模oracleへplan-only、全費用内訳、1e-6円会計再計算、使用BEV全保存slot（初期slot含む）の最低SOC、配車hash、exact gateを追加した。
- RAINは候補範囲×計算予算の2×2（BASE/RANGE_ONLY/BUDGET_ONLY/FULL_EXPANDED）へ修正し、plan-only runner、allowlist、requested/effective分離、候補集合分析器、事前登録schemaを追加した。
- PV LOW/MEDIUM/HIGHのうちLOW/HIGHの正本曲線は存在する。MEDIUMの合成、provenance、hash、同一非PV制御をfail-closedで扱う既存runnerはないため、P1のまま保留する。

## 実験を開始できる条件

1. 指導教員がRAIN安定性の許容値（候補内費用改善率）とStage 1 gapの採用線を事前決定する。
2. `03_small_oracle_feasibility.md` と `04_rain_candidate_sensitivity_plan.md` に記した非core adapterを別Goalで実装・レビューし、solverなしのfocused testsを通す。
3. adapter実装後にexact command、出力schema、run-count定義を再確認し、人間がPhase 2を明示承認する。

## 実験family別の必須報告

| family | 研究上の目的 | 実行可能性 | exact command | run数 | solver時間 | 成功条件 | 失敗条件 | 得られる主張 | 得られない主張 |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| 小規模oracle | deployed policyとscalar referenceの距離 | adapter実装済・実行未承認 | `07_exact_commands.md` | 3 jobs / 6 phase solves | 最大1,800 s | Phase 4 exact gate、同一入力、全便・物理・会計PASS | time limit、入力不一致、会計不一致 | 8/12/24便subset内の距離 | 純粋な分解gap・264便誤差上限 |
| RAIN感度 | 候補集合と計算予算への選択安定性 | plan-only実装済・実行未承認 | `07_exact_commands.md` | 4 jobs | 最大11,910 s | 4 profileの全gateと事前閾値 | 制御drift、正当性失敗、閾値未承認 | テスト済み2×2内の連続指標 | 閾値なしの二値安定判定・全候補空間 |
| PV三水準 | 固定運行に対するPV量感度 | P1・`REQUIRES_SMALL_ADAPTER` | `NOT AVAILABLE` | 承認時3 jobs | 最大5,445 s | 非PV hash一致、3水準全gate | provenance/非PV drift/正当性失敗 | 固定3曲線の記述的応答 | 天候因果・季節一般化 |

## 読む順序

1. `01_conference_claim_candidates.md`
2. `02_experiment_preregistration.md`
3. `03_small_oracle_feasibility.md`
4. `04_rain_candidate_sensitivity_plan.md`
5. `05_pv_availability_sensitivity_plan.md`
6. `06_experiment_matrix.csv`
7. `07_exact_commands.md`
8. `08_time_and_compute_budget.md`
9. `09_risk_and_stop_rules.md`
10. `10_midterm_storyboard.md`
11. `11_ieej_two_page_storyboard.md`
12. `12_advisor_questions.md`
13. `13_adapter_acceptance_report.md`

## 研究境界

追加実験が成功しても、264便統合大域最適、一般的な雨天効果、年間費用、LCC、設備容量最適化は主張しない。中心表現は「同一平日運行・固定設備条件における有限候補二段階法の内的妥当性と選択安定性」である。
