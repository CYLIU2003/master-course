# Thesis External Review Brief

## 1. Motivation

This review asks whether the current thesis evidence is being described at its
actual strength. The project must not turn a feasible 264-trip candidate, a
bounded small-instance oracle, or a diagnostic root-LP observation into an
unjustified global-optimality, speedup, economic-response, or deployment claim.

The release remains `BLOCKED` until this independent review and the separate
264-trip Stage-1 1% gap gate are both resolved. This file is a review request,
not a reviewer approval.

## 2. Scope

Review the frozen evidence and the claim boundary only:

- Baseline review SHA: `a145cf3a8b9cba0e4d97c48f800fba9ff07a1e69`.
- Latest root-LP subset diagnostic source: `f10525f4255be72bde81d19778b5af5ceeac8949`
  (`thesis-activation-start-top5-diagnostic-f10525f`); its one-row predecessor
  is `08af4829b3491269698f0faf67162af9d8d52861`.
- Latest exhaustive no-path-clique diagnostic source:
  `f71bc51a48c743e86c4150bb53bbb5e281caa4cb`
  (`thesis-exact-no-path-clique-f71bc51`).
- Rejected exact-clone rank-tie-breaker source: `1aaaa272c48aa4d4673833719d13af5be191ddd1`
  (`thesis-stage1-clone-rank-symmetry-1aaaa27`); the current source reverts
  this candidate after its controlled negative diagnostic.
- Latest long-cap diagnostic source: `96982abe376422a630543bc35426d201c0a998ac`
  (`thesis-long-stage1-single-96982ab`).
- Full 264-trip discrete/pure-aggregate A/B evidence, small 8/12/24/40-trip
  Phase-4 oracle, small M0--M3 study, one-factor sensitivity matrix,
  fixed-decision stress evaluation, and the root-LP candidate diagnostics.

Do not approve or reject a new PV curve, calendar date, V2G design, column
generation, UI work, or large refactor; those are outside this review.

## 3. Technical changes and evidence

| Area | Evidence | Review question |
| --- | --- | --- |
| Reproducible 264-trip A/B | `output/diagnostics/pure_ice_aggregation_phase3_ab_25ec2f1_20260824/repeated_comparison.json` | Are the five AB/BA isolated-process pairs sufficient to support `PASS_STRUCTURAL_ONLY`, but not a speedup claim? |
| Long-cap aggregate reachability | `output/diagnostics/pure_ice_aggregation_single_long_stage1_96982ab_20260824/diagnostic_result.json` | Does the explicit 870/30/120-second wall-clock contract and the 3.041301684% result remain correctly labelled as one diagnostic, not a performance, cost, or acceptance comparison? |
| Small integrated oracle | `output/verification/small_integrated_oracle_scale/93e31b0_20260824/scale_certificate.json` | Are 8/12/24/40-trip zero-gap Phase-4 references appropriately limited to bounded formulation evidence? |
| Small M0--M3 | `output/verification/small_m0_m3/93e31b0_20260824/audit.json` | Is the M2--M3 same-input comparison clearly separated from fleet/PV/BESS-changing M0/M1 ablations? |
| Economic response | `output/thesis_remaining_sensitivities_27ec8ce_20260824/sensitivity_execution_manifest.json`, `output/thesis_economic_electricity_93e31b0_20260824/sensitivity_execution_manifest.json`, `output/thesis_economic_diesel_93e31b0_20260824/sensitivity_execution_manifest.json`, and `output/thesis_economic_vehicle_day_9650ed9_20260824/sensitivity_execution_manifest.json` | Do the 21 documented gap failures, despite effective varied inputs and valid physical/accounting artifacts within each frozen family, correctly prevent economic-response conclusions and cross-family comparison claims? |
| Fixed-plan stress | `output/diagnostics/fixed_solution_stress_0ddcd22_20260824/fixed_solution_stress.json` | Is fixed-decision fragility correctly kept distinct from reoptimized robustness? |
| Root-LP strengthening | `output/diagnostics/stage1_activation_start_dual_root_a51b1f3_20260824/diagnostic_assessment.json`, `output/diagnostics/stage1_activation_start_subset_root_08af482_20260824/diagnostic_assessment.json`, and `output/diagnostics/stage1_activation_start_top5_root_f10525f_20260824/diagnostic_result.json` | Do the all-row no-solution plus quality-qualified one-row and five-row no-bound-improvement results justify rejecting the tested high-deficit subsets without a MIP ON/OFF run, while avoiding an unsupported claim about every other subset? |
| Exact no-path cliques | `output/diagnostics/stage1_assignment_path_exact_clique_root_f71bc51_20260824/diagnostic_result.json` | Does the optimal, quality-qualified root LP plus 59/59 optimal auxiliary clique MIPs justify rejecting this complete no-path clique family at that root point, without implying a general integrality or gap result? |
| Stage-1 clone rank tie-breaker | `output/diagnostics/stage1_clone_rank_root_1aaaa27_20260824/diagnostic_result.json` | Does the no-improvement root LP and worse primary-MIP certified gap justify rejecting and reverting this exact label-symmetry candidate without calling it a comparative performance result? |

The implementation adds only diagnostic controls:

- `stage1_root_lp_diagnostic_method` selects barrier or dual simplex for a
  separate continuous clone, never the production Stage-1 MIP.
- `stage1_activation_start_strengthening_vehicle_ids` can select an explicit
  subset of independently certified activation-to-path-start inequalities. It
  rejects empty, duplicate, unknown, clone-domain, and start-domain-ineligible
  IDs.
- `stage1_root_lp_diagnostic_exact_clique_separation_enabled` is default-off
  and solves independent maximum-weight clique MIPs at an optimal,
  quality-qualified root-LP point. It is exhaustive only when every eligible
  vehicle/day auxiliary MIP proves optimal; timeout is inconclusive and no
  discovered row is added to Stage 1.
- The exact inequality is
  `used_vehicle <= sum(path_start)` for a non-aggregate label only when the
  chronological acyclic-flow certificate holds. It does not alter the integer
  feasible set under that certificate.

## 4. Research impact

The evidence currently supports these statements:

- The Phase-3 two-stage method produced physically feasible, 264/264-served,
  audited candidates.
- Exact homogeneous-ICE aggregation reduced model structure/RSS in the frozen
  A/B study, but did not improve median solver time.
- The one long-cap aggregate diagnostic remains physically valid but misses the
  1% gap; it is a reachability observation, not comparative evidence.
- The bounded small oracle agrees with Phase 3 within numerical tolerance for
  the listed subsets; it does not prove a 264-trip integrated optimum.
- The stress results describe a fixed solution's limited robustness, not
  recourse robustness.

The evidence does **not** support these statements:

- 264-trip global total-cost optimality, a 1%-optimal final two-stage cost, or
  a solver speedup from aggregation.
- Accepted full-scale economic sensitivity, causal PV/BESS/charger response,
  or robust real-operation performance.
- V2G optimization, full-depot generalization, or deployment readiness.

## 5. Validation

The code changes for the latest root diagnostics passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 1569 passed in 78.97s at source SHA 96982ab

.\.venv\Scripts\python.exe scripts\verify_run_input_provenance.py `
  --run-dir output\2026-08-24\run_20260824_1239

.\.venv\Scripts\python.exe scripts\verify_run_input_provenance.py `
  --run-dir output\2026-08-24\run_20260824_1139

.\.venv\Scripts\python.exe scripts\verify_run_input_provenance.py `
  --run-dir output\2026-08-24\run_20260824_1156
```

Both provenance checks are valid. The selected-one-row root LP is optimal with
maximum unscaled primal violation `5.820766091346741e-11`, but its objective
differs from the unstrengthened root LP by `-4.3655745685100555e-11` JPY, well
inside the predeclared `1e-5`-JPY comparison tolerance.

The exact no-path-clique source `f71bc51` passes `1570` regressions in
79.56 seconds. Its frozen 264-trip diagnostic verifies top-level hashes and
`verify_run_input_provenance.py`; the root LP is optimal and quality-qualified,
and all 59 eligible auxiliary MIPs prove optimal with no violation. This is a
negative strengthening result only, not reviewer approval or release evidence.

The clean `1aaaa27` rank-tie-breaker candidate passed `1570` regressions in
79.19 seconds before its frozen diagnostic. The artifact verifies hashes and
BFF provenance; its root LP differs from the unstrengthened objective by about
`-8.1e-10` JPY within the `1e-5` tolerance, while its primary-MIP
analytical-floor gap is `19.2651169%` versus `19.2273066%` previously. It is
therefore rejected and the source reverts it; this is a negative diagnostic,
not a MIP comparison, approval, or release evidence.

## 6. Remaining limitations and requested decision

1. **Required reviewer decision:** confirm whether the mathematical validity
   argument and negative root-LP conclusions are correctly scoped, and list
   any P0/P1 claim or reproducibility defect with artifact paths.
2. **Open computational gate:** no tested valid Stage-1 strengthening closes
   the 264-trip 1% MIP-gap target. Do not launch a formal run without a new
   validity proof, focused regression, and quality-qualified root-bound
   evidence.
3. **No approval yet:** this repository contains no external reviewer identity,
   review timestamp, or approval record. A reviewer must add those separately;
   this brief must not be edited to simulate independent review.
