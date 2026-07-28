# Current research release blockers

Status date: 2026-07-28
Code status: local regression passed; no post-change 264-trip formal run yet
Teacher release status: **BLOCKED**

This file is the single current blocker register. Older rolling remediation
documents are historical specifications and are marked resolved/superseded.
Numbers from runs created before the next frozen commit are diagnostic only and
must not be reused as evidence for the current model.

## Verified implemented path

The reachable frontend path is:

```text
Tk frontend
  -> POST /api/scenarios/{scenario_id}/run-optimization
  -> bff.routers.optimization._run_optimization
  -> ProblemBuilder.build_from_scenario
  -> OptimizationEngine.solve
  -> Phase 3 Stage 1 full-network vehicle assignment
  -> Phase 3 Stage 2 fixed-assignment charging/PV/BESS MILP
  -> run_rolling_chain (60 minutes x full 24-hour horizon)
  -> rolling acceptance audit
  -> physical schedule validation
  -> executed-day canonical accounting
  -> final JSON/Markdown/Excel/report reconciliation
```

Rolling orchestration itself is no longer a blocker. Physical feasibility,
research acceptance, accounting eligibility, comparison validity, and
optimality remain separate decisions.

## Closed in the current working tree, pending clean-run confirmation

1. Physical-schedule validation is separated from research acceptance. A
   fleet, exactness, provenance, or optimality rejection no longer turns a
   physically validated schedule into `INVALID`.
2. After accepted rolling,
   `rolling_hourly_chain/executed_day_accounting.json` is the unique final cost
   source. Total and every enabled canonical component must agree across ledger,
   summary, JSON, Markdown, Excel, and optimization result within `1e-6 JPY`;
   disabled components must be explicit `SKIPPED` zeroes. Missing component
   evidence fails the job.
3. Formal frontend runs fail before solving unless Git is clean and has a SHA.
   A source-state change during the run is also fatal.
4. Formal frontend runs derive and hard-check the exact active vehicle set
   from the materialized prepared scenario and selected depot/scope. Counts,
   IDs, initial state, vehicle parameters, and the fleet-contract hash must
   match. Unavailable persisted records are excluded with reasons; contradictory
   or malformed availability, duplicate/empty IDs, unknown types, implicit
   initial state, missing catalog/physical parameters, or hash drift fail.
5. Formal Phase 3 frontend runs force the complete successor network and
   prohibit fallback/post-solve repair.
6. Stage 1 now shares charge reachability across physical charger definitions,
   compatibility, ports, power, depot location, charging windows, and an
   optimistic site supply cap when a finite import contract is configured. A
   non-positive contract means no finite cap, consistently with Stage 2. This
   remains a necessary relaxation; Stage 2 is the exact charging/SOC check.
7. If and only if Stage 2 returns a Gurobi `INFEASIBLE` certificate, the full
   failed vehicle-trip assignment is returned to Stage 1 as a no-good cut and
   re-solved (maximum two feedback iterations in a formal frontend run).
   `TIME_LIMIT` without a feasible incumbent does not justify a cut. All
   feedback iterations share one global wall-clock deadline.
8. Each run emits a counterfactual-case manifest. A separate pair builder
   verifies the fixed-control hash, PV hashes/difference, physical validation,
   rolling cost source, and comparison table.
9. An explicit policy-sensitivity checkbox can require every available BEV to
   serve at least one trip. It is not the unconstrained baseline.
10. Results that pass physical gates but miss the predeclared gap are labelled
    `FEASIBLE_CANDIDATE`, not an optimal solution.

## Open blockers

### B1 — Fresh formal execution evidence is absent

The model and accounting changes invalidate all older KPI claims. A frozen
clean commit must be executed through the normal frontend for high-PV,
low-PV, and no-PV cases. All three require 24/24 rolling and the run acceptance
table below.

### B2 — Full-scale Stage 1 performance and gap are unmeasured

The shared-charger relaxation and Stage 2 feedback cuts change Stage 1 size and
mathematical strength. No 264-trip runtime, raw Gurobi gap, certified gap,
node count, numeric-scaling diagnostic, or feedback-iteration count has yet
been measured. Until a run reaches the predeclared gap, it is a feasible
candidate only.

### B3 — Stage 1/Stage 2 decomposition is not an integrated global optimum

Phase 3 remains a two-stage method. Stage 1 creates a dispatch candidate and
Stage 2 optimizes energy operation for that fixed assignment. The new
reachability relaxation/cuts reduce infeasible handoffs but do not prove a
single globally minimum accounting cost. The real Gurobi regression covers an
IIS-backed Stage 2 rejection, two full-assignment no-good retries, and a final
independently feasible schedule; it does not prove that the bounded feedback
loop exhausts every full-scale infeasible assignment. Small integrated-MILP
comparison remains required to quantify decomposition loss.

### B4 — All-available-BEV policy sensitivity has not been executed

The baseline and “every BEV in the scenario-derived active fleet serves at
least one trip” policy case must be run separately. Report feasibility,
BEV/ICE vehicles and trips, grid energy, PV use, cost, charger requirement,
peak kW, and incremental cost. Do not infer why the baseline uses fewer BEVs
without these outputs.

### B5 — Counterfactual pair is not yet assembled from new runs

High/low/no-PV runs must share the same service date, trip-content hash, fleet
contract, initial-state hash, charger/BESS/tariff inputs, seed, thread count,
time limits, and solver controls. Only the PV curve hash may differ. The
Tsurumaki experiment spec may separately assert 264 trips. Build and archive
the pair manifest after the new runs; do not call it an actual sunny/rainy
operating-day comparison.

### B6 — Uncertainty evidence remains incomplete

After the deterministic formal cases pass, run predeclared trip-energy and PV
forecast stress tests. Preserve seeds and report failure rates, terminal SOC
margin, peak kW, grid energy, and cost. This is subsequent evidence, not a
substitute for closing B1–B5.

## Per-run formal acceptance table

Copy this table into each run review and fill it from artifacts. Never mark a
row from an assumption.

| Check | Acceptance condition | Evidence field/file | Result |
|---|---|---|---|
| Git | clean; non-empty start/end SHA identical | `code_provenance.json`, `run_manifest.json` | PENDING |
| Fleet | exact active IDs, initial state and parameter hashes match the materialized prepared selected scope; exclusions have reasons | `scenario_fleet_contract.json`, `graph/research_fleet_validation.json` | PENDING |
| Trips | prepared-scope trip count fully served; duplicate=0 (Tsurumaki spec may assert 264) | physical validation, summary | PENDING |
| Operator | `UNKNOWN=0` | operator audit | PENDING |
| Dispatch | transition violations=0 | hard validation | PENDING |
| Deadhead | startup/connection/return counted exactly once | movement event ledger | PENDING |
| Charger occupancy | double use=0 | hard validation | PENDING |
| Charging power | vehicle and charger limit violations=0 | hard validation | PENDING |
| Grid | contract-power violations=0 | hard validation, hourly flow | PENDING |
| BEV SOC | lower/upper violations=0 | physical validation | PENDING |
| BEV terminal | initial-target deviation within declared tolerance | terminal audit | PENDING |
| BESS SOC | lower/upper violations=0 | physical validation | PENDING |
| BESS terminal | initial-target deviation within declared tolerance | terminal audit | PENDING |
| Power balance | per-slot residual within tolerance | energy-flow audit | PENDING |
| Fuel | liters and tank balance agree with service/deadhead distance | physical fuel ledger | PENDING |
| Cost | canonical component and cross-artifact residuals <= `1e-6 JPY` | final reconciliation | PENDING |
| Fallback | none | solver metadata | PENDING |
| Post-solve repair | none | solver metadata | PENDING |
| Arc pruning | zero for a full-network claim | arc pruning summary | PENDING |
| Rolling | 24/24, accepted, assignment hash fixed | rolling chain summary | PENDING |
| Gap | predeclared target met | solver settings/claim classification | PENDING |
| Comparison | all non-PV control hashes equal | pair manifest | PENDING |
| Final | `teacher_release_status=READY` | release status | PENDING |

If any row fails, preserve the numbers but add all three labels:

- `DIAGNOSTIC RESULT`
- `NOT USED FOR RESEARCH CONCLUSIONS`
- `BLOCKED: <complete list of reasons>`

## Release procedure

1. Finish review and tests.
2. Commit the reviewed changes on `main` as requested, then freeze the selected
   full SHA for the experiment.
3. Freeze that commit; do not edit code after the formal experiment starts.
4. Run all formal cases from that clean SHA.
5. Never reuse an older result after a code/model change.
6. Fill the table per run and build the PV pair manifest.
7. Seek independent Claude Code/executive review.
8. Only when every required row is accepted may the release be tagged READY.
