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
casefold-sorted relative POSIX paths. Rendering is fail-closed on the complete
locked Matplotlib/Pillow dependency set and the pinned Noto Sans JP face
actually selected by Matplotlib. After the final evidence-loader and Rolling
attestation reviews, the reporting suites passed 55 tests, the reporting plus
research-contract focused suite passed 225 tests, and the complete repository
suite passed 1,714 tests in 105.09 seconds. Exact package regeneration,
compilation, three README-navigation tests, and diff hygiene also passed.
These final local fixes are commits `8169803` and `151fff4`; neither commit has
been pushed while account-level GitHub Actions and automatic Copilot review
remain enabled.

## Claim boundary

Both scenarios served 264/264 trips and passed physical validation, 24/24
Rolling, and accounting reconciliation. The results are finite-candidate
Phase 3 two-stage feasible comparisons. They are not integrated global optima,
not 1%-optimal in both scenarios, and not evidence of a general weather effect.
The Stage 1 certified gaps remain 9.5213476% for SUNNY and 1.6563581% for RAIN.

## Merge boundary

`ALLOW_MAIN_MERGE=false`. The account owner currently forbids GitHub Actions
and paid/AI review features, so they must not be invoked as merge evidence.
Consequently, the original fresh-remote-CI and fresh-Codex/Copilot-review gates
remain explicitly unsatisfied rather than being replaced by local evidence.
After the owner confirms the prepared account-setting changes, disable those
features first, verify them read-only, and only then push the two local commits
and resolve review threads with their local test evidence. This handoff does
not authorize a merge to `main` or an unsupported `READY_FOR_HUMAN_MERGE`
claim.
