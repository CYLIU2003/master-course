# P0 execution-gate acceptance report

## Scope

基準`87c837b83228502622cf0f39cdb67e51ef533842`からexecution-gateを強化した。`src/**`、`bff/**`、frozen evidence、authoring、`.github/**`、requirementsは変更していない。Prepare、solver、Rolling、実HTTPは実行していない。

## Method verdicts

- P3 scalar: `P3_SCALAR_UNSUPPORTED`
- small oracle Phase 3: bb0c005の契約一致時だけ`P3_DEPLOYED`、それ以外は`P3_ALIGNED_REFERENCE`
- pure decomposition gap: unavailable
- permitted comparison: `deployed_phase3_to_scalar_integrated_reference_distance`
- RAIN design: BASE/RANGE_ONLY/BUDGET_ONLY/FULL_EXPANDED 2×2
- generic sensitivity matrix: P0/P1で使用禁止
- PV MEDIUM: `BLOCKED_PV_MEDIUM_INTERFACE_NOT_IMPLEMENTED`

## Adapter inventory

- small oracle output/plan-only adapterとv2 schema
- Fresh Prepare一回・同一Prepared共有を宣言するoracle matrix plan
- RAIN profile allowlist・plan-only・validation・advisor-null execute gate
- `assignment_hash`を研究上の物理配車identityとする比較tool（`candidate_hash`はprovenanceのみ）
- production同一tiebreak、正式selectable gate、4 profileの`profile_result_v1.json`正規化
- 2×2直交性、preregistration型・日付・SHA・単位、同一Prepared/固定入力hash、Git SHA driftのfail-closed検証
- `INTERRUPTED` progress manifestとartifact inventory
- 12会計成分、会計reconciliation、使用BEV SOC traceが欠けるsmall oracle比較の遮断

## Verification

- `.venv/Scripts/python.exe -m compileall -q tools/november_2026 scripts/audit_small_integrated_weather_milp.py tests`: PASS
- focused execution-gate/oracle tests: 48 PASS
- full regression: 1,754 PASS
- `git diff --check`: PASS（改行変換warningのみ）
- changed files: 24 / 25上限
- solver / Prepare / Rolling / 実HTTP: 0 / 0 / 0 / 0

全回帰とdiff監査を通過したため、実装判定は`P0_EXECUTION_PACKAGE_READY_FOR_ADVISOR_SIGNOFF`である。これは実験開始の承認ではない。Phase 2 executionは引き続き、完全なpreregistration manifest、clean commit SHA、指導教員の別承認が必要である。
