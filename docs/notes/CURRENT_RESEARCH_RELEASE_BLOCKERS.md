# Current research release blockers

Status date: 2026-07-30
Code status: slot-indexed Stage 1 energy recourse, multi-candidate Stage 2
evaluation, explicit same-service-date PV controls, and an HTTP-only frontend
pair runner are implemented. A final-slot return-boundary defect exposed by
the fourth HTTP attempt is corrected, and candidate selection now requires an
independent physical check in addition to Stage 2 feasibility. The fifth HTTP
attempt exposed and the current tree corrects a result-claim message that
conflated integrated-optimality scope with certified-gap status. The corrected
completion audit also rejects a contradiction between solver settings,
persisted claim classification, and terminal response. The corrected focused
regression passes (`89 passed`) and the complete suite passes
(`1066 passed`); compileall and `git diff --check` are required before freeze.

Teacher release status is fail-closed: **BLOCKED** unless
`output/formal_pair_20260730/completion_audit.json` records `status=READY`,
zero failed checks, the exact frozen Git SHA at start and end, and a completed
ZIP. When that artifact exists for the current frozen SHA, this blocker is
discharged without modifying the repository during the experiment.

The first frozen attempt at
`d95e0e049a254bb3f3e560aa86e986ec4a773b7f` is retained at
`output/formal_pair_20260730` and is diagnostic only. The full-scope synchronous
Prepare exceeded the HTTP client's former 120-second default in both cases, so
no optimization job ran. The runner now uses the declared formal job timeout
for Prepare and submit; a new clean commit and untouched output directory are
required for the next attempt.

The second frozen attempt at
`3ee1c2f46a7d3bbbfa1244baf61fd7b5319188f5` is retained at the same
requested experiment name until archival before retry. It failed before the
solver because an empty route selection expanded to 56 routes/974 trips and
the Prepare payload omitted the explicit ICE initial-fuel controls required by
the selected-depot fleet contract. The instructed scope is the same 16 route
IDs in both diagnostic prepared inputs and materializes 264 trips; 264 is not a
code constant. The runner now sends those 16 IDs plus the shared explicit
SOC/terminal/ICE-fuel and cost-component controls and rejects route-count drift
immediately.

The third frozen attempt at
`92c4f36e934ac10a4b12dd7b45aae6068ac6483f` is retained under
`output/formal_pair_20260730_diagnostic_attempt3`. Both fresh 264-trip cases
completed 24/24 Rolling, physical validation, terminal SOC, executed-day
accounting, final reconciliation, and 229/229 artifact checks. It is still
diagnostic and blocked because only one assignment candidate was evaluated,
the run gate mishandled a valid zero-unserved counter, Phase 4 contained an
unaccounted vehicle-discharge sink, the rain certified gap was 10.666%, and an
unchanged assignment had no twenty-alternative cost audit.

The fourth frozen attempt at
`19644e4449ec4a6fc7314d067cfba9dad944da03` is retained under
`output/formal_pair_20260730_diagnostic_attempt4`. Sunny completed 264/264
trips, 21/21 feasible candidates, 24/24 Rolling, physical validation,
accounting reconciliation, and 229/229 artifacts with raw/certified Stage 1
gaps of 9.5801%/3.4503%. Rain evaluated 21/21 Stage 2-feasible candidates but
failed before Rolling because the independent SOC replay checked a 23:14
trip's pre-return final-slot SOC instead of the state after its four-minute
terminal return. The 1.5792 kWh discrepancy equals that return movement
exactly. The replay now advances through the return-completion boundary without
borrowing next-day charging, and candidate selection independently rejects any
physically invalid Stage 2 incumbent. This fix still requires a fresh clean
commit and complete two-case HTTP rerun; attempt 4 remains diagnostic.

The fifth frozen attempt at
`448d52a0e876335a3df63776039a393db6ab4029` is retained under
`output/formal_pair_20260730_diagnostic_attempt5`. Sunny job
`7ba14751-51d5-4f7b-9108-e15f8285783a` and rain job
`a6acab0c-630d-4b9f-ae3b-f5c190991b88` both passed 264/264 trips, 21/21
candidate Stage 2 and independent physical checks, 24/24 Rolling, terminal
SOC, accounting reconciliation, and 229/229 artifact checks. The pair matched
all non-PV controls, used 614.709375/101.1143 kWh PV, and changed 37 trip
powertrain assignments. Its raw/certified Stage 1 gaps were
9.5801%/3.4503% (sunny) and 100%/3.2840% (rain). It is diagnostic because the
terminal BFF responses incorrectly said the requested gap was unestablished
despite `mip_gap_target_met=true`. Claim classification and job messaging now
report the passed certified-gap gate separately from the still-unestablished
integrated global-optimality claim. A fresh same-SHA HTTP pair is required to
validate the corrected response artifacts.

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

## P0 weather/dispatch coupling correction, pending full validation and runs

The previous Stage 1 assignment objective used a whole-day PV-energy credit.
It did not match PV generation slots to assignment-derived depot-presence
windows, charger capacity, BEV SOC, BESS operation, TOU grid prices, or demand
peaks. Because Stage 2 fixed that assignment, the old sunny/rain assignment
hash equality could not be treated as evidence that weather had no dispatch
effect.

The current working tree replaces that decision term with slot-indexed
continuous energy recourse tied to assignment, physical charging windows,
compatible charger ports and power, BEV SOC, per-slot PV/grid/BESS balance,
BESS terminal SOC, import limits and overage, peak demand, and enabled
accounting terms. The aggregate whole-day proxy is diagnostic only. Formal
requests evaluate multiple distinct Stage 1 assignments in exact Stage 2 and
select the minimum-canonical-cost candidate only when exact Stage 2,
canonical-cost evaluation, and the independent physical validator all pass.
Candidate JSON/CSV records the physical result and error hash. Explicit
trip-level powertrain-pattern no-good cuts prevent candidate collection from
degenerating into same-type vehicle-label symmetries. Opposite-powertrain
whole-duty swaps are partial MIP starts only: the unchanged Stage 1 model must
accept them, and they add no weather bias, cost term, or physical exemption.
A 264-trip diagnostic found seven such alternatives in a 36-second reserve and
all eight total candidates passed exact Stage 2, but the archived prepared
input and dirty diagnostic context make that mechanics evidence only. This
remains a bounded two-stage method and does not establish an integrated global
optimum.

The follow-up also separates Gurobi's raw bound from a weather-sensitive
analytical floor combining strict path-cover vehicle usage and an optimistic
direct service-energy/fuel floor. It changes no model coefficient and fails
closed if omitted objective costs are not known nonnegative. Integrated Phase
4 now forbids unaccounted vehicle discharge and uses the same `1e-9` physical
numeric contract as Stage 2. Sunny and rain small integrated-oracle reruns are
now physically valid and accounting matched; they do not replace the required
fresh full-scope HTTP runs.

Prepare now records the common 2025-08-05 service date separately from each PV
source date. The new HTTP-only runner must use fresh prepared inputs and the
ordinary BFF endpoints, preserve exact payloads, run cases sequentially, and
fail closed on every run, pair, oracle, gap, physical, accounting, provenance,
or artifact gate. These changes are verified code facts only until the fresh
frozen-commit high/low-PV pair completes successfully. Passing
unit/regression tests does not substitute for the full prepared-scope physical
run or formal pair acceptance.

## P0 physical-validation provenance correction, pending fresh evidence

The archived 18:35 and 18:41 runs are diagnostic only. They completed 24/24
Rolling steps with `chain_accepted=true` and eligible executed accounting, but
the finalizer passed the lossy BFF reporting wrapper to the independent event
validator. That wrapper had no top-level `vehicle_paths`; the validator therefore
reconstructed charging without the 264 service/deadhead events and produced
false unassigned-trip and terminal-SOC findings.

The current fix uses only the SHA-matched persisted canonical result for
assignment/refueling, overlays only executed Rolling charging, and persists
`physical_validation_input_manifest.json`. It fails closed when canonical SHA,
vehicle paths, served trips, canonical problem trips, or zero-unserved status
do not agree. The independent validator and every physical metric remain
mandatory. Its terminal-SOC comparison now shares the solver's explicit
scientific tolerance plus numerical margin; this does not widen the scientific
tolerance or excuse material energy imbalance.

This code is not accepted evidence until the new frozen clean commit completes
the normal 264-trip frontend execution and all physical, accounting, artifact,
and provenance gates are measured from its new run directory.

The first clean diagnostic run of this correction,
`run_20260728_1938`, confirmed that the intended P0 boundary is now exercised:
it accepted 24/24 Rolling steps, has eligible executed-day accounting, and
reports physical validation `VALID` with 264 assigned/served trips and zero
required physical violations. It then failed during `results.xlsx` generation
because `cost_component_flags` is structured metadata and the previous writer
passed the mapping directly to an Excel cell. No final cost reconciliation or
artifact-completeness status exists for that failed job, so it is diagnostic
only. The writer now serializes mapping/list/tuple metadata deterministically
as JSON text while retaining numeric cost values for reconciliation and
rejecting unknown object types; another frozen clean-commit normal frontend
run remains mandatory.

The next diagnostic run, `run_20260728_1949`, also passed the corrected P0
physical gate and accepted Rolling/accounting, but stopped during final cost
reconciliation when the report carried `demand_charge_jpy=null`. Its earlier
finalization path also demonstrated that a failed job could leave torn `READY`
labels in some human-facing artifacts. Both conditions are now fail-closed:
missing/invalid/non-finite monetary evidence persists as `null` rather than a
fabricated zero and causes reconciliation `ERROR`; the outer failure path
scrubs every release surface to `BLOCKED` / `DIAGNOSTIC`. The canonical summary
continues to define `energy_cost_jpy` as electricity only, with the distinct
`propulsion_energy_cost_jpy` aggregate when needed. This repair does not
weaken physical validation, SOC limits, Rolling acceptance, or accounting.
`run_20260728_1949` remains diagnostic; it has no successful final
reconciliation or artifact-completeness result.

The first fresh run from the subsequent reporting commit,
`run_20260728_2028`, confirmed the corrected P0 path again: 24/24 accepted
Rolling, eligible executed accounting, and `physical_schedule_validation`
`VALID` all passed. It then failed before artifact acceptance because the
Markdown total marker was compared byte-for-byte against a separately parsed
floating-point representation (`707808.6603727042` versus
`707808.660372704`). The values differ by less than `1e-6 JPY` and represent
the same canonical accounting total. The comparison is now a finite numeric
check under the existing `1e-6 JPY` contract; missing, ambiguous, non-finite,
or materially different markers remain `ERROR`. This run is diagnostic only;
a further new clean-commit normal frontend run remains required.

The subsequent fresh run, `run_20260728_2036`, passed 24/24 accepted Rolling,
eligible executed accounting, independent physical validation, and final cost
reconciliation. It correctly failed artifact completeness because the valid
zero-ICE-refuel schedule had produced a zero-byte declared graph export,
`graph/refuel_events.csv`. The graph exporter now writes the CSV schema header
for zero-event refueling. The completeness audit now compares both
`refuel_events.csv` and `graph/refuel_events.csv` against the canonical
`refueling_schedule` with exact schemas and event multisets; header-only is
allowed only when the canonical schedule is empty. Missing, zero-byte,
schema-invalid, or row-mismatched exports fail. `run_20260728_2036` is
diagnostic only, and another clean-commit normal frontend run remains
required.

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
   initial state, missing catalog/physical parameters, or hash drift fail. The
   full validated v2 contract is preserved in canonical problem metadata and
   handed unchanged to Rolling; a count-only validation summary is not accepted.
5. Formal Phase 3 frontend runs force the complete successor network and
   prohibit fallback/post-solve repair.
6. Stage 1 now couples assignment to slot-level charge reachability, compatible
   charger ports and power, depot-presence windows, BEV SOC, per-slot PV/grid/
   BESS balance, BESS terminal SOC, contract overage, peak demand, and enabled
   accounting costs. Contract-overage feasibility and penalty match Stage 2;
   the previous hard optimistic site cap is not used. Stage 2 remains the exact
   binary charger and charging/SOC check.
7. If and only if Stage 2 returns a Gurobi `INFEASIBLE` certificate, the full
   failed vehicle-trip assignment is returned to Stage 1 as a no-good cut and
   re-solved (maximum two feedback iterations in a formal frontend run).
   `TIME_LIMIT` without a feasible incumbent does not justify a cut. All
   feedback iterations share one global wall-clock deadline.
8. Each run emits a counterfactual-case manifest. A separate pair builder
   verifies the fixed-control hash, PV hashes/difference, physical validation,
   rolling cost source, final artifact-completeness acceptance, terminal
   `manifest.json` state, and comparison table. The builder can discharge only
   `controlled_counterfactual_pair_not_verified`; any other case-level release
   failure rejects the pair.
9. An explicit policy-sensitivity checkbox can require every available BEV to
   serve at least one trip. It is not the unconstrained baseline.
10. Results that pass physical gates but miss the predeclared gap are labelled
    `FEASIBLE_CANDIDATE`, not an optimal solution.
11. Ordinary frontend completion is fail-closed on
    `artifact_completeness.json`. The required root/raw/graph/provenance,
    24-step Rolling, physical-validation, accounting, Markdown, JSON, and
    Excel bundle must be present and readable. Missing artifacts preserve the
    diagnostic run directory but fail the job.
12. Accepted Rolling output now includes five literature-aligned plots, one
    plot-source CSV each, and sixteen analysis-ready raw CSVs with a data
    catalog and hashes. These expose executed vehicle/SOC/charger/energy/cost/
    CO2 evidence without copying paper graphics or fabricating multi-run
    sensitivity results.
13. The 17:55 frontend run exposed a Stage 2 numeric mismatch at Rolling 11:00:
    `1.9536944368644223e-06 kW` of linked continuous power remained while the
    charger-assignment binary was only `5.458495369859787e-08` and therefore
    treated as zero by Gurobi's default `IntFeasTol=1e-5`. Stage 2 now fixes
    and records `IntFeasTol=1e-9`. The exact failing handoff then passed, the
    remaining 13 steps passed, and a dirty full-chain probe completed 24/24
    with eligible executed-day accounting. Reporting no longer replaces a
    primary Rolling step failure with a secondary incomplete-accounting error.
14. Tk Quick Setup and Prepare now persist the existing
    `fixed_weekday_timetable_pv_counterfactual` declaration for the exact user
    selection of one Sunday date, `WEEKDAY`, and `actual_date_profile`. The
    declaration leaves the date, selected timetable rows, route scope, and PV
    curve unchanged, and `ProblemBuilder` supplies it to Rolling's calendar
    audit. A fresh prepared input and normal run are still required before this
    path becomes execution evidence.

## Open blockers

### B1 — Fresh formal execution evidence is absent

The model, accounting, and artifact-contract changes invalidate all older KPI
claims. A frozen clean commit must be executed through the normal frontend for
the predeclared same-service-date high-PV and low-PV pair. Both require 24/24
Rolling and accepted run contracts. Each completed job must additionally show
`artifact_completeness.status=OK`; otherwise it is an incomplete diagnostic
bundle, irrespective of solver feasibility.
The 2026-07-28 17:37 manual run is diagnostic only: day-ahead completed, but
Rolling preflight stopped before step 1 because the canonical problem omitted
the already-resolved fleet-contract payload. The handoff is corrected in code,
but this does not become execution evidence until a fresh clean-commit run
completes.
The 17:55 run is also diagnostic only. It progressed to Rolling step 11 and
identified the now-corrected Stage 2 integrality-tolerance mismatch. A
post-patch full-chain probe using its exact archived input completed 24/24
steps and eligible accounting, but the working tree was intentionally dirty
during diagnosis. It proves that the reproduced technical failure is closed;
it does not replace a fresh clean-commit ordinary frontend run.
It must also contain a `READY` (generation status only)
`graph/literature_figures/manifest.json` with all declared PNG/SVG/source/raw
CSV files. Its manifest hashes and canonical-source hashes must revalidate
without size or SHA-256 mismatch. The charger evidence must preserve concurrent
port count and aggregate power rather than only the maximum vehicle power.
This figure-bundle status does not override research-release blockers.

### B2 — Corrected full-scale Stage 1 performance and gap are unmeasured

The slot-indexed recourse, analytical certificate, powertrain-pattern
enumeration, and multi-candidate Stage 2 evaluation change lower-bound
strength and total runtime. The archived diagnostic preflight measured only
candidate mechanics. No fresh clean-commit HTTP pair has yet measured the
corrected runtime, raw Gurobi gap, certified gap, node count, first incumbent,
candidate count, numeric scaling, or feedback iterations. Until a formal run
reaches the predeclared gap, it is a feasible candidate only.

### B3 — Stage 1/Stage 2 decomposition is not an integrated global optimum

Phase 3 remains a two-stage method. Stage 1 creates dispatch candidates and
Stage 2 optimizes exact energy operation for each fixed assignment. The
slot-indexed recourse, candidate pool, and IIS-backed cuts reduce decomposition
loss but do not prove a single globally minimum accounting cost. The HTTP pair
runner now invokes the small integrated-MILP oracle and requires feasibility,
cost, vehicle mix, and powertrain-assignment agreement, but that audit has not
yet been executed from the new frozen prepared inputs. It cannot replace the
full-scale run.

### B4 — All-available-BEV policy sensitivity has not been executed

The baseline and “every BEV in the scenario-derived active fleet serves at
least one trip” policy case must be run separately. Report feasibility,
BEV/ICE vehicles and trips, grid energy, PV use, cost, charger requirement,
peak kW, and incremental cost. Do not infer why the baseline uses fewer BEVs
without these outputs.

### B5 — Counterfactual pair is not yet assembled from new runs

High/low-PV runs must share the same service date, trip-content hash, fleet
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
| Validation input | SHA-matched canonical paths/refueling plus executed Rolling charging overlay | `physical_validation_input_manifest.json` | PENDING |
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
