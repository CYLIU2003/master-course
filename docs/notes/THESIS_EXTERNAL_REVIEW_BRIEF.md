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
- Latest root-LP subset diagnostic source: `08af4829b3491269698f0faf67162af9d8d52861`
  (`thesis-activation-start-subset-08af482`).
- Current documentation head when this brief was written: `e56d08f`.
- Full 264-trip discrete/pure-aggregate A/B evidence, small 8/12/24/40-trip
  Phase-4 oracle, small M0--M3 study, one-factor sensitivity matrix,
  fixed-decision stress evaluation, and the root-LP candidate diagnostics.

Do not approve or reject a new PV curve, calendar date, V2G design, column
generation, UI work, or large refactor; those are outside this review.

## 3. Technical changes and evidence

| Area | Evidence | Review question |
| --- | --- | --- |
| Reproducible 264-trip A/B | `output/diagnostics/pure_ice_aggregation_phase3_ab_25ec2f1_20260824/repeated_comparison.json` | Are the five AB/BA isolated-process pairs sufficient to support `PASS_STRUCTURAL_ONLY`, but not a speedup claim? |
| Small integrated oracle | `output/verification/small_integrated_oracle_scale/93e31b0_20260824/scale_certificate.json` | Are 8/12/24/40-trip zero-gap Phase-4 references appropriately limited to bounded formulation evidence? |
| Small M0--M3 | `output/verification/small_m0_m3/93e31b0_20260824/audit.json` | Is the M2--M3 same-input comparison clearly separated from fleet/PV/BESS-changing M0/M1 ablations? |
| Economic response | `output/thesis_remaining_sensitivities_27ec8ce_20260824/sensitivity_execution_manifest.json` | Do the documented gap failures prevent economic-response conclusions? |
| Fixed-plan stress | `output/diagnostics/fixed_solution_stress_0ddcd22_20260824/fixed_solution_stress.json` | Is fixed-decision fragility correctly kept distinct from reoptimized robustness? |
| Root-LP strengthening | `output/diagnostics/stage1_activation_start_dual_root_a51b1f3_20260824/diagnostic_assessment.json` and `output/diagnostics/stage1_activation_start_subset_root_08af482_20260824/diagnostic_assessment.json` | Do the all-row no-solution and one-row no-bound-improvement results justify rejecting this candidate without a MIP ON/OFF run? |

The implementation adds only diagnostic controls:

- `stage1_root_lp_diagnostic_method` selects barrier or dual simplex for a
  separate continuous clone, never the production Stage-1 MIP.
- `stage1_activation_start_strengthening_vehicle_ids` can select an explicit
  subset of independently certified activation-to-path-start inequalities. It
  rejects empty, duplicate, unknown, clone-domain, and start-domain-ineligible
  IDs.
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
# 1567 passed in 79.69s at source SHA 08af482

.\.venv\Scripts\python.exe scripts\verify_run_input_provenance.py `
  --run-dir output\2026-08-24\run_20260824_1139

.\.venv\Scripts\python.exe scripts\verify_run_input_provenance.py `
  --run-dir output\2026-08-24\run_20260824_1156
```

Both provenance checks are valid. The selected-one-row root LP is optimal with
maximum unscaled primal violation `5.820766091346741e-11`, but its objective
differs from the unstrengthened root LP by `-4.3655745685100555e-11` JPY, well
inside the predeclared `1e-5`-JPY comparison tolerance.

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
