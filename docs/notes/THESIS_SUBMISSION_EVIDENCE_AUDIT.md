# Thesis submission evidence audit

**Audit date:** 2026-08-24  
**Latest 264-trip A/B evidence:** clean frozen tag `thesis-freeze-25ec2f1` at `25ec2f170949b7108c5dd98ac1dc5b5b03845525`
**Requested comparison baseline:** `a145cf3a8b9cba0e4d97c48f800fba9ff07a1e69`

## Scope and disposition

This is an evidence audit, not a change to the mathematical model, acceptance
gates, or claimed results. The requested baseline is an ancestor of the
frozen `25ec2f1` evidence checkout, with no divergent baseline-side commits.
The changes add
reproducibility capture, isolated-process A/B evidence, bounded integrated
oracles, sensitivity/stress harnesses, and gap diagnostics. They do not make
the 264-trip Phase-3 result an integrated global total-cost optimum.

The research release is **BLOCKED**. This document records which thesis-facing
claims are supported and which remain forbidden. The authoritative live
release status is [CURRENT_RESEARCH_RELEASE_BLOCKERS.md](CURRENT_RESEARCH_RELEASE_BLOCKERS.md).

## Reproducibility snapshot

The current environment observed during this audit is Windows 11
`10.0.26200`, CPython `3.14.6`, Gurobi/gurobipy `13.0.1`, an Intel Core
i7-12700 (20 logical CPUs), and 34,033,328,128 bytes of RAM. The individual
run artifacts persist their own pre/post Git SHA and clean state, prepared
input hash, scenario/prepared-input IDs, runtime environment, solver controls,
threads, seed, time limits, and requested MIP gap. Current machine information
is a verification observation; it is not substituted for frozen evidence.

The historical five-pair A/B bundle correctly retains a null presolve value.
The new frozen-`25ec2f1` five-pair bundle records the final Stage-1 Gurobi
`PRESOLVE` callback timestamp for every child and labels it as elapsed time
from `optimize` start, not as a dedicated internal presolve-duration attribute.
Its artifact hashes verify and its clean pre/post run SHA, prepared input,
runtime environment, seed, threads, time limits, and solver controls are
persisted. This read-only telemetry change does not alter the release gate.

## Requirement-by-requirement evidence

| Requirement | Evidence | Status and allowed conclusion |
| --- | --- | --- |
| Reproducible run identity | Each fresh 264-trip A/B child records clean pre/post `25ec2f1`, prepared-input SHA-256, seed 42, four threads, 435/30-second stage limits, runtime environment, and Gurobi controls. The 40-trip oracle audit records clean pre/post `93e31b0`, its prepared-input hash, runtime environment, and controls. | **Verified for the cited artifacts.** A later documentation-only HEAD does not relabel those runs as current-HEAD formal evidence. |
| 264-trip pure-ICE aggregation A/B | [Repeated comparison](../../output/diagnostics/pure_ice_aggregation_phase3_ab_25ec2f1_20260824/repeated_comparison.json): ten isolated children, five AB/BA pairs, all 264/264 served, physical validation, Rolling 24/24, accounting, no fallback/repair, verified artifact hashes, and final `PRESOLVE` callback timestamps. | **PASS_STRUCTURAL_ONLY.** Median variables/binaries/constraints/RSS decrease 31.82%/32.01%/24.09%/17.27%; the callback timestamp falls 12.74%, but median solver time increases from 465.761 to 480.487 seconds. Do not claim speedup, equal full-scale objective, or optimality. |
| Small integrated oracle | [Scale certificate](../../output/verification/small_integrated_oracle_scale/93e31b0_20260824/scale_certificate.json): 8/12/24/40-trip Phase-4 references are optimal at zero gap; Phase-3 pairs complete. | **Verified, bounded only.** 24/40-trip identifiable ApproxGap is 0.0 within numerical tolerance; 8/12 relative gaps are correctly not identifiable because the reference cost is zero. This does not certify 264-trip global optimality or a full-scale Phase-3 cost bound. |
| Economic one-factor response | [13-case matrix](../../output/thesis_remaining_sensitivities_27ec8ce_20260824/sensitivity_execution_manifest.json) and its no-HTTP re-audit record fresh Prepare, complete successors, physical validation, Rolling, accounting, provenance, and stable non-varied controls. | **Executed but not accepted.** Every selected case fails only `mip_gap_target_met` (2.404055%--26.849287% versus 1%). Candidate differences are provenance diagnostics, not economic-response results. |
| Fixed-plan stress | [Stress result](../../output/diagnostics/fixed_solution_stress_0ddcd22_20260824/fixed_solution_stress.json) fixes the exact source decision and forbids reoptimization. | **Limited robustness evidence.** Only initial SOC -5 percentage points remains physically accepted (0 JPY fixed-decision delta); the other six predeclared stresses fail physically and have no invented cost. This is not recourse robustness. |
| M0--M3 comparison | [40-trip audit](../../output/verification/small_m0_m3/93e31b0_20260824/audit.json) has M0--M3 present and feasible; M0/M3 are exact small references and M2/M3 have the same declared problem-input hash. | **PASS_SMALL_SCOPE_ONLY.** M2--M3 differs by `2.546585164964199e-11` JPY. M0/M1 differ in fleet and/or PV/BESS treatment, so their deltas are descriptive ablations, not a full-network method comparison. |
| Independent review | Internal artifact and regression audit is complete. No separate external reviewer approval is stored in this repository. | **Open gate.** Do not report `LGTM`, `READY`, or “model complete.” |

## Root-cause evidence for the active blocker

The quality-qualified Stage-1 continuous relaxation at
`output/2026-08-24/run_20260824_0124/` is optimal at 52,749.163582 JPY with a
maximum primal violation of `5.820766e-11`. It splits every one of the 264
trips over vehicle labels (2,274 fractional assignment variables), while all
60 vehicle activations are integral. Stage 1 already includes the continuous,
time-indexed charger/PV/BESS/grid recourse relaxation. The blocker is therefore
the vehicle-labelled assignment/path relaxation, not an omitted time-indexed
energy balance.

Observed candidates do not justify a new row: the full vehicle-by-overlap
audit found no violated overlap-clique inequality; explicit/lifted fragment
rows and generic cut/scaling diagnostics did not improve the certified bound;
the activation-to-start row remains default-off because its 264-trip diagnostic
did not yield a comparable root-LP result; and the clean-`0bd81bc` BFF root-LP
audit at `output/2026-08-24/run_20260824_1050/` checks 1,404,360 same-day
no-path assignment pairs, finds zero violations (maximum mass `0.8457521`),
and adds no row. Adding a duplicate charger or energy row, reducing the
declared gap, or restricting fragments without a proof would change or weaken
the research contract and is not authorized.

## Thesis claim boundary

The evidence supports these statements:

- A BEV/ICE mixed-depot **two-stage** dispatch and charging method produced
  264-trip physically feasible, 24/24-Rolling, accounting-reconciled
  candidates under the cited frozen conditions.
- The small integrated reference model is exact for the bounded 8/12/24/40
  subsets under its recorded scalar-cost contract.
- Exact same-type ICE aggregation reduces the recorded Phase-3 formulation
  size and peak RSS on the five-pair controlled 264-trip study.

The evidence does not support these statements:

- 264-trip integrated global total-cost optimality, or a 1%-optimal final
  two-stage cost;
- a solver-speed improvement from aggregation;
- accepted full-scale economic sensitivity, PV/BESS/charger causal response,
  or recourse robustness; or
- deployment readiness, generalization to all depots, V2G optimization, or a
  complete independent review.

## Required next gate

No additional 264-trip formal run is authorized until a specific
vehicle-labelled assignment/path strengthening is proved valid for the
original integer feasible set, covered by a focused exact/small-MILP test, and
documented for its cost and comparability effects. Only then may a new clean
commit be tagged and submitted through the normal Prepare -> BFF ->
`/run-optimization` path. Existing output must not be reused as evidence for
that changed commit.

The current no-solver re-audit can be reproduced with the following command;
its expected exit code is `2` because the source matrix correctly remains
`BLOCKED`:

    .\.venv\Scripts\python.exe scripts\run_thesis_sensitivity_matrix.py `
      --rebuild-existing-dir output\thesis_remaining_sensitivities_27ec8ce_20260824 `
      --output-dir output\verification\thesis_remaining_sensitivities_reaudit_27ec8ce_20260824
