# P0 adapter acceptance report

## Scope

基準`132302a736f72e04aa1fbe07b8d4945fe56c5531`からadapter-onlyで準備した。`src/**`、`bff/**`、frozen evidence、authoring、`.github/**`、requirementsは変更していない。Prepare、solver、Rolling、実HTTPは実行していない。

## Method verdicts

- P3 scalar: `P3_SCALAR_UNSUPPORTED`
- pure decomposition gap: unavailable
- permitted comparison: `deployed_phase3_to_scalar_integrated_reference_distance`
- RAIN design: BASE/RANGE_ONLY/BUDGET_ONLY/FULL_EXPANDED 2×2
- generic sensitivity matrix: P0/P1で使用禁止
- PV MEDIUM: `BLOCKED_PV_MEDIUM_INTERFACE_NOT_IMPLEMENTED`

## Adapter inventory

- small oracle output/plan-only adapterとv2 schema
- Fresh Prepare一回・同一Prepared共有を宣言するoracle matrix plan
- RAIN profile allowlist・plan-only・validation・advisor-null execute gate
- candidate hash/Jaccard/retention/winner比較tool
- preregistration manifest schemaとNOT_RUN templates

## Verification

- `python -m compileall -q tools scripts tests`: PASS
- focused: 29 PASS
- full regression: 1,735 PASS
- `git diff --check`: PASS（改行変換warningのみ）
- changed files: 24 / 25上限
- solver / Prepare / Rolling / 実HTTP: 0 / 0 / 0 / 0

判定は`P0_ADAPTERS_READY_FOR_HUMAN_APPROVAL`。Phase 2 executionは別承認が必要である。
