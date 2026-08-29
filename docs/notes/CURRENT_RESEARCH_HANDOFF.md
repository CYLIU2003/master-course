# Current research handoff

## Scope

This handoff covers the thesis-facing SUNNY/RAIN reporting branch only. The
canonical optimization execution remains
`bb0c0050883a91dd86a9e8813ae88d4b6d8c361d`; no Prepare, solver, Rolling,
scenario, objective, or canonical result was changed while hardening the
reporting package.

The two fixed scenarios are SUNNY
`771d115b-75b0-49f7-a7f0-25f259a2cd21` and RAIN
`b23fd26c-1233-4c73-bb9e-bdb8b1584760`. The raw snapshot and run-manifest
bytes are preserved in
`docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources/`.

## Reviewer entry points

- `docs/thesis/weather_results_bb0c005/thesis_summary_table.md`: concise
  thesis-ready comparison.
- `docs/thesis/weather_results_bb0c005/experiment_parameters.md`: full fixed
  experimental conditions, including individual charger-source validation.
- `docs/thesis/weather_results_bb0c005/results_section_ja.md`: bounded Japanese
  results prose.
- `docs/thesis/weather_results_bb0c005/package_manifest.json`: exact output
  inventory and SHA-256 values.
- `scripts/verify_thesis_weather_result_package.py`: isolated regeneration and
  byte-for-byte comparison.

The verifier must be run against the untouched committed package before any
intentional regeneration, then run again after regeneration. Hash maps use
casefold-sorted relative POSIX paths. Rendering is fail-closed on Matplotlib
3.10.8, Pillow 12.1.1, and the pinned Noto Sans JP face actually selected by
Matplotlib. Local final-candidate checks passed 70 focused tests and the full
1,641-test suite; the final manual GitHub run remains the last merge gate.

## Claim boundary

Both scenarios served 264/264 trips and passed physical validation, 24/24
Rolling, and accounting reconciliation. The results are finite-candidate
Phase 3 two-stage feasible comparisons. They are not integrated global optima,
not 1%-optimal in both scenarios, and not evidence of a general weather effect.
The Stage 1 certified gaps remain 9.5213476% for SUNNY and 1.6563581% for RAIN.

## Merge boundary

`ALLOW_MAIN_MERGE=false`. A human may merge the reporting PR only after all
review threads are resolved, fresh Codex and Copilot review is recorded, and
the final manual **Research code validation** run succeeds on the final HEAD.
No commit may be added after that final validation run. This handoff does not
authorize an automated merge to `main`.
