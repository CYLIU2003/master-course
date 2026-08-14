# Formal-pair timing against the local literature (2026-08-15)

## Scope

This note records what can and cannot be inferred from the PDFs under
`先行文献/` after the clean `79e61ae` controlled pair. Reported wall times are
not treated as interchangeable unless the optimization scope, algorithm,
hardware, stopping rule and evidence level match.

## Source-level literature observations

| Local source | Reported problem and time | Interpretation for this repository |
|---|---:|---|
| `No06.pdf`, Table 5 | Exact Gurobi: 20 trips 1.78 s; 50 trips 617.6 s; no feasible solution for 200 or 418 trips within 6 h. ALNS-SA: 418 trips 202.3 s | Closest individual-trip integrated comparison. The hundreds-second large result is heuristic, not an exact-gap certificate. |
| `No16.pdf` | 49 buses and 275 trips; MILP 1.5 s; nonlinear solver 466.28 s | Vehicle assignments/charge windows are fixed, so this is mainly energy dispatch rather than the present joint assignment problem. |
| `No61.pdf` | Fixed operations; 34--147 s | Charging/PV/ESS scheduling with a prescribed operation plan. |
| `No63.pdf` | Fixed operations; Gurobi 44.5--1058.9 s; decomposition 7.5--93.4 s | The short results use decomposition; vehicle operation is not jointly selected. |
| `No64.pdf` | Up to 98,784 variables; 52.41--3002.07 s on 80 Xeon cores and 314 GB RAM | Larger energy/V2G model, but still substantially smaller than the current individual-trip formulation and run on much greater parallel hardware. |
| `No55.pdf` | About 5 h | A counterexample to the claim that all related integrated studies end in hundreds of seconds. |
| `No03.pdf` | About 30 min | Another reported result outside the hundreds-second range. |

The detailed page mapping remains in
`LITERATURE_SOLVE_TIME_COMPARISON_20260814.md`. The key conclusion is that
hundreds of seconds are common, but mainly for fixed-assignment models,
decomposition or heuristics. They are a useful engineering target, not proof
that the current complete Phase 4 MILP must certify every case in that time.

## Fresh formal timing evidence

Both cases used fresh frontend Prepare, 264 trips, 60 active vehicles, the
complete 11,310-arc successor network, four Gurobi threads, seed 42, a
3,600-second shared Phase 4 wall budget and a predeclared 1% gap.

| Case | Phase 4 wall time | Certified gap | Used fleet | Trip split | Status |
|---|---:|---:|---:|---:|---|
| High PV | 3606.884 s | 2.987214% | 28 BEV / 4 ICE | 202 BEV / 62 ICE | Physical/accounting/Rolling valid; 1% certificate failed |
| Low PV | 794.542 s | 0.420907% | 15 BEV / 17 ICE | 75 BEV / 189 ICE | Physical/accounting/Rolling valid; 1% certificate passed |

The low-PV result demonstrates that the current full pipeline can reach a 1%
certificate in hundreds of seconds. The high-PV result demonstrates a
case-dependent proof bottleneck: a feasible 32-vehicle incumbent exists, but
the independent lower bound remains 640,000 JPY while the incumbent is
659,706.858 JPY. Additional time alone did not close that gap.

## Required reporting semantics

Performance tables must keep these clocks separate:

1. first feasible incumbent time;
2. best validated incumbent time;
3. declared-gap certification time;
4. solver/model wall time; and
5. frontend submit-to-terminal time including Rolling and reporting.

A heuristic or decomposed result may be labelled `FEASIBLE` or
`CERTIFIED_NEAR_OPTIMAL` only with its actual certificate. It must not be
relabeled as the exact global optimum. Conversely, a time-limit incumbent that
passes physical and accounting checks remains useful progress evidence even
when the optimality claim is blocked.

## Current engineering implication

The next performance work should target the high-PV proof bound or a certified
decomposition/column-generation formulation. Further weather-specific seed
bias or BEV lower bounds are prohibited: they can improve an incumbent while
invalidating the causal comparison. The `79e61ae` pair remains progress-only
because high PV missed 1% and a later reporting-contract fix changed the code
SHA; no existing artifact is retroactively upgraded.
