# 2026年11月向け追加実験の事前登録

## 判定

`PARTIAL_WITH_EXACT_BLOCKERS`

本ディレクトリは、基準HEAD `5a6fd2cb36e5c2495ef98606924f7f1c69c1f550` で行った **PLANNING_ONLY** の調査結果である。Prepare、Gurobi、Phase 3、Phase 4、Rollingは一度も実行していない。正本artifact、`docs/thesis/authoring_v1/`、main、PR #7、PR #8は変更していない。

## 結論

- 小規模統合oracleの数理経路は既に存在し、8/12/24便を決定論的に抽出して `phase3_two_stage` と `phase4_integrated` を同一入力・同一費用境界で比較できる。ただし現行JSONには費用内訳と明示的な最低SOCがないため `REQUIRES_SMALL_ADAPTER` とした。
- RAINの候補制御6項目はpublic BFF request schemaに存在する。正式research runでは候補数22、radius 4、frontier ONが下限として強制される。全制御をprofileとして渡し、Fresh Prepareからartifactを封印する既存のRAIN専用runnerがないため `REQUIRES_SMALL_ADAPTER` とした。
- PV LOW/MEDIUM/HIGHのうちLOW/HIGHの正本曲線は存在する。MEDIUMの合成、provenance、hash、同一非PV制御をfail-closedで扱う既存runnerはないため、P1のまま保留する。

## 実験を開始できる条件

1. 指導教員がRAIN安定性の許容値（候補内費用改善率）とStage 1 gapの採用線を事前決定する。
2. `03_small_oracle_feasibility.md` と `04_rain_candidate_sensitivity_plan.md` に記した非core adapterを別Goalで実装・レビューし、solverなしのfocused testsを通す。
3. adapter実装後にexact command、出力schema、run-count定義を再確認し、人間がPhase 2を明示承認する。

## 実験family別の必須報告

| family | 研究上の目的 | 実行可能性 | exact command | run数 | solver時間 | 成功条件 | 失敗条件 | 得られる主張 | 得られない主張 |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| 小規模oracle | 二段階法の内的妥当性 | `REQUIRES_SMALL_ADAPTER` | `07_exact_commands.md`（adapter後） | 3 jobs / 6 phase solves | 最大1,800 s | Phase 4 exact gate、同一入力、全便・物理・会計PASS | time limit、入力不一致、会計不一致 | 8/12/24便subset内の近似差 | 264便誤差上限・大域最適性 |
| RAIN感度 | 候補選択安定性 | `REQUIRES_SMALL_ADAPTER` | 未確定予定interfaceを明示 | 3 jobs | 最大9,735 s | 3 profileの全gateと事前安定条件 | 制御drift、正当性失敗、事前条件外の変動 | テスト済みprofile内の安定/不安定 | 全候補空間の安定性・低PV一般則 |
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

## 研究境界

追加実験が成功しても、264便統合大域最適、一般的な雨天効果、年間費用、LCC、設備容量最適化は主張しない。中心表現は「同一平日運行・固定設備条件における有限候補二段階法の内的妥当性と選択安定性」である。
