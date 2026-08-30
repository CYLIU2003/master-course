# Current research handoff

## Scope

This handoff covers the thesis-facing SUNNY/RAIN reporting branch only. The
canonical optimization execution remains
`bb0c0050883a91dd86a9e8813ae88d4b6d8c361d`; no Prepare, solver, Rolling,
scenario, objective, or canonical result was changed while hardening the
reporting package.

`scripts/build_thesis_weather_result_package.py` is a frozen, `bb0c005`-specific
evidence auditor. It must not be presented or extended as a general model
validator. Future model-contract changes belong in the production validators;
this package should remain fixed unless a defect in the frozen report is
demonstrated.

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
The final engineering code fixes are commits `8169803` and `151fff4`; the
reviewed code head `256f7fc304fbcece869d55c16e4feac7ad607c9e` and both fixes
are pushed to PR #8. The documentation-only freeze commit containing this
handoff is identified by annotated tag `thesis-pause-20260830`.

Remote state frozen for the pause:

- `main`: `abf149d3dbc3909e40361ada3c9a8542c1cf1dd5`, unchanged;
- PR #7: `8543e95eb6cf98e24e919762c2edb543cb5c1de8`, open and based on `main`;
- PR #8 validated code head: `256f7fc304fbcece869d55c16e4feac7ad607c9e`,
  open and stacked on PR #7;
- PR #8 unresolved review threads: zero before the documentation-only freeze;
- GitHub Actions: disabled on all 31 repositories owned by the account;
- automatic Copilot review, AI training, and all user-switchable Copilot
  features: disabled; additional AI usage: disabled with a USD 0 hard budget;
- final-head remote CI and final-head AI review: not executed under the account
  owner's policy.

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
The account-setting changes, PR #8 push, and review-thread closure are already
complete. The next operation is a human decision about whether local-only
evidence is sufficient or whether the remote-CI/independent-review policy will
be changed. Until that decision, leave PR #7 and PR #8 open, do not merge to
`main`, and retain `BLOCKED_WITH_EXACT_REASON`.

## Restart priorities

When research resumes, begin with these three research tasks rather than adding
more reporting-auditor features:

1. evaluate Stage 1 gap and finite-candidate-range sensitivity;
2. preserve and visualize the canonical 96-slot executed power-flow series;
3. ask the advisor to decide whether the bounded SUNNY/RAIN results belong in
   the thesis results chapter.
