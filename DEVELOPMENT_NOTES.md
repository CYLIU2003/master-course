# Development Notes

## 2026-07-28 P0 physical-validation payload provenance fix

- The clean baseline `1acfdff8095932c848bfe91fd79fd4e09f493ca5` produced
  diagnostic runs `run_20260728_1835` and `run_20260728_1841` that completed
  all 24 Rolling steps, had `chain_accepted=true`, and had eligible
  executed-day accounting, but failed only during independent physical-event
  validation. The BFF wrapper lacked top-level `vehicle_paths`, so the
  validator reconstructed charging without service/deadhead energy and
  falsely reported 264 unassigned trips, 13 terminal-SOC violations, and one
  upper-SOC violation.
- Finalization now constructs a fail-closed validation payload from the
  persisted `canonical_solver_result.json`, whose SHA-256 must match the
  rolling-chain provenance. It verifies non-empty/malformed paths, exact
  equality of flattened paths, `served_trip_ids`, and canonical problem trips,
  zero unserved trips, and preserves canonical refueling. It overlays only
  `rolling_hourly_chain/charging_schedule.csv` and writes the source hashes
  and counts to `physical_validation_input_manifest.json`.
- This is not a validation bypass. The independent event validator remains the
  final physical gate; a real charger/location/SOC violation still rejects the
  run. The artifact-completeness contract verifies the input-manifest schema,
  source paths, hashes, counts, and verified checks.
- The corrected reconstruction exposed one genuine numeric-boundary
  inconsistency: `1.0000000116860974e-06 kWh` was just above the old validator
  comparison of `1e-6 kWh`. The pure terminal-SOC contract now lives in the
  common policy module and is used by both Stage 2 and independent validation:
  scientific tolerance `1e-6 kWh` plus numerical margin `1e-9 kWh` yields an
  acceptance limit of `1.001e-6 kWh`. This does not relax the scientific
  tolerance; deviations beyond that explicit limit still fail.
- Focused P0 regression tests cover the original BFF-wrapper boundary, CSV
  overlay, SHA/path/served-trip negative cases, a genuine charger violation,
  terminal boundary behavior, and tampered provenance. A fresh clean-commit
  264-trip normal frontend run is still required before these changes can be
  treated as operational evidence.
- Independent strict review found and closed one additional P1: a
  self-consistent but false input manifest could previously evade the
  artifact-completeness audit. The audit now binds both hashes to
  `rolling_chain_summary.json` and recomputes vehicle-path, assigned,
  served, unserved, and total-trip counts from `canonical_solver_result.json`.
  Negative regression cases cover count and assignment-hash tampering.
- The first frozen diagnostic run of that correction,
  `run_20260728_1938`, passed the corrected independent physical gate
  (`VALID`, 264 assigned/served trips, zero physical metrics), accepted all
  24 Rolling steps, and produced eligible executed-day accounting. It then
  correctly failed finalization because `cost_component_flags` is a mapping
  and the old workbook writer attempted to place that mapping directly into
  an Excel cell. The run has no final cost-reconciliation or artifact-
  completeness result and remains `DIAGNOSTIC`, not research evidence.
- The workbook writer now preserves mapping/list/tuple report metadata as
  deterministic JSON text while preserving scalar monetary components as
  numeric Excel cells. Unknown object types fail closed. This is a
  report-format repair only: it does not alter the ledger, cost reconciliation
  inputs, SOC, dispatch, charging, or independent physical validation. A new
  frozen clean-commit frontend run is required.
- The next frozen diagnostic run, `run_20260728_1949`, again accepted all 24
  Rolling steps, produced eligible executed-day accounting, and passed the
  corrected independent physical validation (`VALID`, 264 served/assigned,
  zero required physical violations). It then exposed reporting-boundary
  defects: a `null` demand charge caused raw `float()` conversion to abort
  reconciliation, explicit `0.0` components could be mistaken for fallback
  values, and a finalization failure could leave inconsistent release labels.
  That run remains `DIAGNOSTIC` and is not reusable evidence.
- Final reporting now preserves explicit zeros, writes vehicle-use and
  canonical-component fields at the report's top-level schema, and treats a
  missing/invalid/non-finite required component as `null` in the reconciliation
  observation and residual (with an `ERROR` gate), never as a fabricated zero.
  Direct report fields and canonical-component-map observations are persisted
  separately, so a valid map cannot overwrite missing direct evidence.
  `summary.energy_cost_jpy` remains electricity-only; the separately named
  `propulsion_energy_cost_jpy` carries the electricity-plus-fuel aggregate.
- The outer frontend failure path now best-effort scrubs scope, summary,
  result/audit copies, Markdown, Excel, and manifest releases to
  `BLOCKED`/`DIAGNOSTIC` with the failure reasons. In addition, an isolated
  frontend run cannot claim teacher release without the independently verified
  controlled counterfactual pair. The pair builder may discharge only that
  one pending-pair blocker; both cases still require accepted artifact
  completeness and a terminal rolling-manifest state of `complete`. A terminal
  post-finalization error downgrades an already-written completeness audit to
  `ERROR`/`accepted=false` before all release surfaces are scrubbed. These are
  reporting/provenance gates, not relaxations of physical validation, SOC,
  solver, or Rolling acceptance.
- Regression coverage includes canonical payload provenance, report schema and
  explicit-zero handling, `null` accounting diagnostics, disabled-component
  cross-artifact reconciliation, Excel serialization, claim-scope scrubbing,
  and positive/negative controlled-PV pair gates. The local suite passed
  `1025` tests; `compileall` and `git diff --check` also passed before the
  pending clean-commit normal frontend rerun.
- The first fresh run from `bfcfa41`, `run_20260728_2028`, reached 24/24
  accepted Rolling, eligible executed accounting, and `VALID` independent
  physical validation, but correctly stopped before artifact acceptance on a
  report-marker false positive. The Markdown header carried the canonical
  ledger total `707808.6603727042`, while the executed JSON parsed as
  `707808.660372704`; the old byte-for-byte float representation check rejected
  their `2e-10 JPY` difference despite the existing `1e-6 JPY` accounting
  tolerance. The marker is now finite numeric evidence checked at that same
  tolerance; missing, ambiguous, non-finite, or materially different values
  still fail closed. This run remains diagnostic and a new clean-commit rerun
  is required.

## 2026-07-28 Stage 2 charger-assignment numeric consistency fix

- Manual frontend run `output/2026-07-28/run_20260728_1755` passed Prepare,
  canonical problem construction, the day-ahead two-stage MILP, and Rolling
  steps 00:00 through 10:00. At 11:00 it stopped with
  `Positive Stage 2 charging power has no selected physical charger`; the
  later `Executed-day accounting is not eligible` message was secondary and
  obscured that primary error.
- Reproduction with the exact 10:00 handoff state showed
  `charge_kw=1.9536944368644223e-06`, `charge_on=5.458586278950696e-08`,
  and the same `5.458495369859787e-08` assignment residue on
  `depot-fast-tsurumaki-001`. This is approximately `0.00195 W`, not a
  physical charging session. Stage 2 already used
  `FeasibilityTol=1e-9`, but Gurobi's default `IntFeasTol=1e-5` allowed the
  binary assignment residue to count as zero while the linked continuous
  charging-power variable remained above the reporting threshold.
- Stage 2 now sets and records
  `stage2_gurobi_integrality_tol=1e-9`. The fix acts inside the MILP numeric
  contract: it does not invent a charger assignment, rescale energy, relax a
  physical limit, or perform post-solve repair. If positive material charging
  power still has no binary-selected physical charger, extraction continues to
  fail and now includes charge, assignment, physical-power, feasibility, and
  integrality diagnostics.
- The frontend finalizer now runs canonical cost/report reconciliation only
  when Rolling has no technical failure. A failed chain is still persisted
  fail-closed, but the original step failure is raised instead of being
  replaced by the inevitable incomplete-day accounting error. Direct calls to
  the accounting validator now include its recorded rejection reason.
- Exact-data diagnostic verification using the archived 17:55 day-ahead
  artifacts:
  - the formerly failing 11:00 step is feasible, Stage 2 is `optimal`,
    264/264 trips are served, and the assignment hash matches;
  - 11:00 through 23:00 completes 13/13 feasible steps with no runtime error;
  - a complete 00:00 through 23:00 probe completes 24/24 feasible steps,
    preserves the assignment hash, and produces eligible executed-day
    accounting; maximum BEV terminal target shortfall is
    `3.808509063674137e-12 kWh`;
  - the probe is deliberately not research evidence because it ran from a
    dirty working tree and therefore has `chain_accepted=false` solely for
    `rolling_runner_git_clean`.
- Focused numeric/reporting/Rolling regression tests passed (`45 passed`);
  the full suite passed (`997 passed`), together with `compileall` and
  `git diff --check`. A fresh ordinary frontend run must be made from the final
  clean commit; the failed 17:55 run and dirty diagnostic probes remain
  `NOT USED FOR RESEARCH CONCLUSIONS`.

## 2026-07-28 frontend Rolling fleet-contract handoff fix

- Manual frontend run `output/2026-07-28/run_20260728_1737` completed its
  day-ahead solve but correctly failed closed before Rolling with
  `Canonical problem is missing scenario_fleet_contract_v2`.
- Root cause: the prepared scenario contained the complete v2 contract and
  `ProblemBuilder` used it to produce an `OK` research-fleet validation, but
  canonical problem metadata retained only the derived validation summary.
  `persist_frontend_day_ahead_rolling_contract()` requires the original
  contract because counts alone cannot recover active IDs, initial state,
  vehicle parameters, exclusions, or their hashes.
- `ProblemBuilder` now preserves the exact resolved contract and its contract
  hash in canonical problem metadata. Rolling continues to fail closed when
  the v2 contract is genuinely absent; no contract is reconstructed from
  solver output.
- Added a Builder-to-canonical-metadata regression using the real research
  path, including an excluded maintenance vehicle and exact hash equality.
  The regression also calls the same Rolling contract-persistence function
  that failed in the manual run and verifies the emitted contract and hash.
  Focused fleet/frontend/Rolling tests: `44 passed`; full suite:
  `994 passed`; `compileall` and `git diff --check` passed.
- Mathematical effect: none. The dispatch, charging, SOC, energy, and cost
  models are unchanged. This repairs provenance handoff needed to start the
  already-required 24-step Rolling chain. The failed 17:37 run remains a
  diagnostic artifact and must not be resumed or cited as a completed result.

## 2026-07-28 pre-manual-run literature artifact hardening

- Closed the review finding that the literature bundle recorded SHA-256 values
  without checking them. The frontend completeness audit now verifies every
  entry's `artifact_files` against `artifact_records`, recalculates size and
  SHA-256, verifies all canonical `source_artifacts`, and fails closed on a
  missing, unsafe, duplicate, mismatched, or malformed record. Regression tests
  mutate both a generated CSV and a canonical source after manifest creation
  and require `artifact_completeness.status=ERROR`.
- Corrected the multi-port charger visualization. The source CSV and PNG/SVG
  now report occupied-port count and aggregate charging kW per physical
  charger/time slot. Concurrent sessions sharing one multi-port `charger_id`
  are summed instead of being reduced to the maximum individual-bus kW.
- Preserved multi-depot tariff evidence as a depot-keyed mapping and separate
  plot line per depot. Conflicting duplicate depot/time prices and conflicting
  duplicate time-level CO2 factors now fail instead of being silently
  overwritten.
- Local ignored literature PDFs are non-canonical supporting references.
  Permission/hash failures are recorded in `literature_source_mapping.csv` and
  no longer abort an otherwise valid optimization-result finalization.
- Added production-finalizer integration coverage for both accepted Rolling
  (bundle generator must run) and non-accepted Rolling (bundle must remain
  `NOT_GENERATED`). Mathematical effect: none on dispatch, charging, SOC,
  energy, or cost optimization; these changes correct reporting semantics and
  strengthen post-run integrity validation.
- Validation after these changes: focused literature/completeness/physical/
  frontend-finalizer tests `50 passed`; full suite `993 passed`; `compileall`
  and `git diff --check` passed. The revised energy-management and two-panel
  charger-occupancy PNGs were rendered and visually inspected. A fresh
  full-scale frontend solver run remains pending and must be created manually
  from the final clean commit before its numbers are used as research evidence.

## 2026-07-28 literature-aligned plots and analysis-ready CSV evidence

- The ordinary frontend finalizer now generates five newly rendered figures
  after accepted 24-step Rolling, independent physical validation, and
  executed-day cost reconciliation: vehicle operations, BEV SOC profiles,
  PV/BESS/grid energy management, physical charger occupancy, and canonical
  cost/CO2 components.
- Each figure has a source CSV. A separate sixteen-file `raw_data/` bundle contains
  canonical copies and deterministic JSON-to-CSV tables for executed vehicle
  events, SOC transitions, charger sessions, hourly energy, cost, CO2, active
  vehicle parameters, cost/CO2 components, physical validation metrics,
  executed-day accounting, and excluded vehicle records. The data catalog
  states row count, evidence level, canonical source, and semantics.
- The independent physical validator now exports per-BEV event-level SOC and
  actual charger power/limit fields. These are derived from the accepted
  Rolling charging sessions and physical problem definition, not from stale
  day-ahead display data.
- `graph/literature_figures/manifest.json` records all plot/table/CSV hashes,
  cited local PDF pages, claim scope, and limitations. The graph manifest and
  frontend artifact-completeness audit require the bundle; missing PNG, SVG,
  source CSV, SOC timeline, raw-data file, or a recorded hash mismatch fails
  finalization.
- Paired PV comparisons, uncertainty distributions, equipment sensitivities,
  and runtime distributions remain explicit multi-run outputs and are not
  fabricated from one run. Figure generation remains separate from
  `teacher_release_status`.
- Mathematical effect: none on the MILP feasible set or objective. This change
  adds deterministic reporting and a stricter post-run artifact gate.
- Validation: literature/physical/completeness focused tests `22 passed`; full
  suite `986 passed`; `compileall` and `git diff --check` passed. The five
  synthetic PNG/SVG outputs were visually inspected. A fresh full-scale
  frontend solver run is still pending.
- Mapping and evidence contract:
  `docs/model/LITERATURE_FIGURE_MAPPING.md`.

## 2026-07-28 Prepare schema v3: explicit fleet state for formal runs

- The first clean-HEAD formal attempt correctly stopped before MILP because
  the existing v2 Prepare artifacts omitted charger compatibility declarations
  and per-vehicle initial ICE fuel, even though the solver had always derived
  those values from the selected depot charger inventory and the simulation
  fuel-percentage settings.
- Prepare now emits schema
  `v3_trip_stop_polyline_distance_explicit_fleet_state`, so the new
  `prepared_input_id` cannot collide with a v2 artifact. It materializes only
  the effective solver inputs: BEVs receive the selected depot charger IDs
  when no declaration exists, and ICE buses receive
  `fuelTankL * min(initial_ice_fuel_percent, max_ice_fuel_percent)` (or the
  configured initial ratio when no maximum is configured).
- The decision rule and derived record counts are saved in
  `fleet_state_materialization`. No distance, SOC, fuel consumption, or
  energy quantity is modified. The previous v2 run attempt is not reused;
  fresh v3 Prepare artifacts are required before the sunny/rain executions.
- The formal frontend weather runner now explicitly enables the persisted
  weather operation policy before `ProblemBuilder`. For the requested
  2025-08-10 rain case it sets the weather/service date to 2025-08-10 while
  retaining the prepared `WEEKDAY` timetable rows, and records the
  `fixed_weekday_timetable_pv_counterfactual` waiver. This is intentional
  weekday-difference suppression, not a Sunday timetable claim.
- A first v3 sunny solve exposed a day-ahead/Rolling asset-hash definition
  mismatch: day-ahead included `pv_case_id` while Rolling correctly treated it
  as part of the PV-only curve. The day-ahead fixed hash now excludes
  `pv_case_id`, `pv_generation_kwh`, and `pv_generation_hash` together; BESS,
  charger, tariff, and depot-limit fields remain fixed. The failed rolling
  attempt is diagnostic only and will not be reused.

## 2026-07-28 scenario fleet contract v2 and independent release gates

- Replaced the remaining fixed fleet-count authority with the exact active
  vehicle set derived from the materialized prepared scenario and explicitly
  selected depot/scope. `scenario_fleet_contract_v2` persists active IDs,
  exclusions, canonical powertrains, initial-state hash, parameter hash, and
  the complete contract hash. Equal counts no longer imply equal input.
- Raw formal records now fail before Canonical conversion on empty/duplicate
  ID, missing type/powertrain/depot, invalid or contradictory availability,
  implicit initial SOC/fuel, or missing positive BEV/ICE physical parameters.
  `"false"` and `"0"` are correctly unavailable.
  Persisted inactive vehicles are excluded with reasons rather than making
  their mere existence an error.
- Vehicle-type-catalog battery, consumption, charge-power, and compatibility
  values are materialized into the canonical active vehicle record. Formal
  artifacts include both the raw vehicle and catalog source records used by the
  exact parameter hash.
- BFF preflight, ProblemBuilder, formal CLI, policy sensitivity, comparison,
  and energy audit use the shared availability/powertrain/fleet resolver.
  `--assert-bev-count` and `--assert-ice-count` are optional checks with no
  defaults; they never define the fleet. “Use every available BEV” derives the
  policy lower bound from the active set.
- Formal CLI now executes full Rolling by default. Only
  `--day-ahead-only-exploratory` skips it; that path remains teacher-blocked and
  returns a non-completion code. The generic comparison derives trip/slot
  counts from the prepared input, uses immutable content hashes, and reports
  solver outcomes such as feedback-cut count without requiring them to match.
- Added independent event reconstruction for startup deadhead, service,
  connection deadhead, waiting, charging, refueling, and terminal return.
  Missing required metrics, unknown/blank chargers, depot/compatibility/power
  errors, charging away from the vehicle location, overlaps, SOC/fuel failure,
  and trip/operator defects fail closed. Grid/PV/BESS source rows belonging to
  one physical charging session are aggregated before occupancy validation.
- Stage 2 infeasibility feedback iterations now share one monotonic global
  deadline. Each Gurobi invocation receives only the remaining time, and
  feedback telemetry records cumulative time and remaining budget.
- The rolling executed-day ledger now publishes enabled/SKIPPED status for
  every canonical accounting component. Every enabled component must agree
  across executed accounting, ledger, summary, experiment JSON, detailed CSV,
  XLSX, and the optimization result within `1e-6 JPY`.
  Human-facing output now exposes `vehicle_usage_cost_jpy`,
  `vehicle_fixed_cost_jpy`, and `vehicle_acquisition_cost_jpy` separately;
  a daily activation charge is no longer relabelled as a fixed ownership cost.
- The legacy feasibility checker now treats a missing, nonnumeric, nonfinite,
  fractional, or negative required count as an error. Duplicate-trip count is
  part of the clean gate instead of being reported without affecting release
  validity.
- The frontend selector now preserves the common 5/15/30/60-minute time-axis
  values. The formal Phase 3 experiment spec remains 15-minute internal slots
  with 60-minute Rolling updates. `--available-bev-count` is now restricted to
  blocked day-ahead exploratory runs because a formal run may not mutate the
  prepared active fleet.
- Removed tracked `.tmp_*` / `tmp_*` one-off scripts and added
  `.github/workflows/research-validation.yml`. The workflow compiles sources,
  runs focused research-contract tests, and runs the full suite without a
  licensed Gurobi requirement.
- Local validation after these changes: `972 passed`; compileall and
  `git diff --check` pass. A remote CI execution and fresh full-scale formal
  solver run are still absent.
- Mathematical effect: the dispatch feasible set is now parameterized by the
  prepared scenario's exact active vehicles rather than a repository-wide
  count. The independent validator adds a release gate without altering the
  MILP feasible region. The global deadline changes termination only. All
  pre-change outputs are non-comparable and must not be reused.
- Documentation:
  `docs/model/SCENARIO_FLEET_CONTRACT.md`,
  `docs/notes/FORMAL_RUNBOOK_CURRENT.md`, and
  `docs/notes/DYNAMIC_FLEET_REMEDIATION_LOG_20260728.md`.
- Release status remains **BLOCKED** until a clean frozen commit produces fresh
  high-PV, low-PV, and no-PV full Rolling runs and the complete acceptance
  table is filled.

## SUPERSEDED 2026-07-28 selected-depot count declaration

- The interactive formal-run fleet declaration now comes from the available
  BEV/ICE records of the selected scenario depot, not a global `35 BEV / 26
  ICE` constant. For the current `tsurumaki` scenario this declares `35 BEV /
  25 ICE`. The canonical builder still fails closed on a declaration/input
  mismatch, duplicate or empty IDs, unknown types, and any unavailable selected
  vehicle. The contract provenance records both the source and selected depot.
- This changes input-contract scope only. It does not establish research
  acceptance, solver optimality, physical validation, rolling acceptance, or
  accounting eligibility; those gates remain separate.

## 2026-07-28 research release correctness and Stage 1→Stage 2 closure

### Verified call path and defects addressed

- 実経路は通常フロント
  `POST /api/scenarios/{scenario_id}/run-optimization`
  → `_run_optimization`
  → `ProblemBuilder`
  → `OptimizationEngine`
  → Phase 3 Stage 1/Stage 2
  → `run_rolling_chain`
  → rolling acceptance
  → final reportingである。CLIだけの修正ではない。
- 研究受理失敗と物理可行性を分離した。全便、接続、SOC、充電器、
  終端条件、assignment/input hash、24-step rollingを独立検査する
  `physical_schedule_validation.json`を持ち、fleet/exactness/gap等の研究
  gateだけを理由に物理的なscheduleを`INVALID`またはKPI nullへ変えない。
- accepted rolling後の唯一の最終費用源を
  `rolling_hourly_chain/executed_day_accounting.json`とした。総額だけで
  なく、電力、燃料、需要、車両使用、CO2の各費目についてledger、
  summary、experiment JSON/Markdown、Excel、optimization resultの残差を
  `1e-6 JPY`以内で強制する。1項目でも外れればjobを失敗させる。
- Stage 1の既存startup precheck、all-day energy envelope、累積SOC必要条件
  を削除せず強化した。充電可能窓に裏付けられた連続充電変数を導入し、
  車両/充電器互換性、90/50 kW等の物理出力、口数、home depot、時刻、
  有限の系統契約がある場合だけ、楽観的な系統+PV+BESS供給上限を全車両で
  共有する（非正値はStage 2と同じく「有限上限なし」であり0 kWではない）。
  charger assignment
  はStage 1では連続緩和なので必要条件、Stage 2ではbinaryの厳密条件
  であり、Phase 3を統合大域最適解とは扱わない。
- Stage 2がGurobi `INFEASIBLE`を返した場合だけ、失敗した全
  `(vehicle, trip)` assignmentをno-good cutとしてStage 1へ戻す
  logic-based feedbackを追加した。通常フロントは最大1回、formal
  research frontend/runnerは最大2回再試行する。`TIME_LIMIT`、単なる
  incumbent欠如、推測した不足量ではcutを作らない。各attemptのIISと
  candidate hashを別成果物へ保存する。
- formal frontendはclean Git + 非空SHAをsolve前にhard gateし、solve中
  のSHA/dirty変化も拒否する。prepared available fleetは選択営業所の
  scenario inventoryをhard contractとし、重複/空ID、unknown type、
  unavailable record、count mismatchをbuild時に停止する。正式Phase 3はfull successor
  network、fallbackなし、post-solve repairなしを強制する。
- 全BEV使用はbaselineへ混ぜず、既存
  `minimum_used_bev_count`制約を使う明示的な政策感度checkboxとした。
  `sum(used_vehicle[v] for available BEV)>=35`の影響を別runで評価する。
- runごとに固定control hash、PV profile hash、assignment/rolling/cost
  evidenceを保存し、pair builderがPV差分hashと比較表を作る。物理条件を
  通過しても事前gap未達または非統合なら
  `FEASIBLE_CANDIDATE`とし、「最適解」とは表示しない。

### Repository and release management

- 実ファイルの`AGENTS.md`へdispatch、timetable、operator、exactness、
  fallback、物理量、再現性の研究guardrailを復元した。
- 旧`AI_AGENT_FRONTEND_ROLLING_RELEASE_BLOCKER_20260727.md`は
  `RESOLVED AND SUPERSEDED`、rolling-first指示書はhistorical
  specificationと明記した。現在の唯一の残課題とrun単位の正式合格表は
  `docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md`へ集約した。
- 正式実験はこの変更をclean commitへ固定した後だけ実行する。実験開始後
  はコードを変更せず、コード変更後に旧結果を再利用しない。

### Validation and remaining evidence

- 2026-07-28 follow-up: I reproduced the actual Stage 2 feedback path with a
  two-trip, two-BEV, two-charger Gurobi model. The continuous Stage 1 charger
  relaxation accepts two all-BEV candidates that the binary Stage 2 charger
  assignment proves infeasible. The retry branch previously referenced
  `_solve_thesis_two_stage` local variables outside their scope and raised
  `NameError` before adding the next Stage 1 cut. The minimal fix removes those
  invalid arguments. `tests/test_stage2_infeasibility_feedback.py` now requires
  two IIS-backed no-good cuts, an eventual BEV/ICE schedule, and a separate
  `FeasibilityChecker` pass. This proves the feedback control path, not global
  completeness of a bounded two-stage decomposition.
- 2026-07-28 follow-up の全回帰は`906 passed`（`pytest -q -p no:cacheprovider`）を
  確認した。compileall、diff check、clean release commitからの264便高PV/
  低PV/no-PV、24/24 rolling、全BEV政策感度は、まだ未実行の正式証拠である。
- したがって`teacher_release_status=READY`、修論モデル完成、統合総費用
  の大域最適性、正式KPI改善はまだ主張しない。新制約がStage 1の変数数、
  runtime、raw/certified gapへ与える影響もclean full runで測定する。

## 2026-07-27 frontend day-ahead -> hourly rolling production orchestration

### Verified call path and implementation

- The active frontend is the Tk application launched by `run_app.py`; it calls
  `POST /api/scenarios/{scenario_id}/run-optimization` through
  `tools/scenario_backup_tk.py`. The production path is now:
  `Tk -> BFF run_optimization -> _run_optimization -> ProblemBuilder ->
  OptimizationEngine.solve -> RollingChainRequest -> run_rolling_chain ->
  rolling_chain_acceptance_audit -> final reporting/persistence`.
- The normal frontend payload explicitly sets
  `run_profile=day_ahead_and_hourly_rolling`, `research_run=true`,
  `run_hourly_rolling=true`, and `rolling_execution_minutes=60`. The BFF treats
  the normal profile as server-authoritative and forces rolling/60 minutes even
  if an old or hand-written client submits different rolling fields.
  Day-ahead-only diagnostics require the explicit
  `run_profile=day_ahead_exploratory`.
- `bff/services/optimization_run/rolling_chain.py` persists the exact
  day-ahead `CanonicalOptimizationProblem`, serialized result, prepared-input
  SHA-256, effective scenario/PV curves, trip/vehicle/charger/initial-SOC
  hashes, calendar audit, and Git provenance. The in-process rolling service
  receives the same canonical problem object; it does not rebuild
  `timetable_rows`, duties, `operator_id`, or the day-ahead assignment.
- A full chain must cover the complete energy horizon, keep the assignment
  hash fixed, execute every 60-minute prefix exactly once, preserve EV/BESS
  state handoff, produce eligible executed-day accounting, keep the day-ahead
  and rolling Git SHA identical, and pass the shared acceptance audit.
  Infeasible/missing/truncated/handoff-failed chains make the BFF job `failed`
  and preserve `rolling_execution_failure.json` plus available diagnostics.
  This historical 2026-07-27 behavior allowed a dirty worktree but blocked
  release. As of the 2026-07-28 formal-run contract, `research_run=true`
  fails before solving on a dirty or unversioned worktree; only explicitly
  non-research diagnostics may run dirty.
- Weekday timetable use on a Sunday is still fail-closed. It is waived only
  when both exact labels
  `comparison_type=fixed_weekday_timetable_pv_counterfactual` and
  `calendar_policy=fixed_weekday_timetable_pv_counterfactual` are declared.
  The output explicitly says this is not actual Sunday operation.
- Reporting is finalized after rolling. `summary.json`,
  `experiment_report.md`, `results.xlsx`, `research_claim_scope.json`, and
  `run_manifest.json` include the run profile, rolling state/minutes,
  research/teacher release gate, failed checks, requested/raw/certified gaps,
  `mip_gap_target_met`, solver termination, and objective-versus-accounting
  semantics. An individual accepted run is not relabelled as a formal weather
  comparison; a matched pair and comparison audit remain separate gates.
- Runtime comparison remains ineligible for every single frontend run even
  with `BestObjStop=OFF` and one Gurobi thread. Repeated matched cases are
  still required.

### Validation and remaining external evidence

- Focused BFF/rolling/provenance tests are included for server-enforced
  defaults, explicit day-ahead exploratory mode, same-object handoff, dirty
  provenance classification, exact Sunday waiver, and rolling evidence.
- The first clean-commit full-size frontend-path trial
  (`output/2026-07-27/run_20260727_1645`) reached rolling step 06 and exposed a
  numerical boundary handoff bug: Gurobi returned the 120 kWh BESS minimum as
  `119.99999999999999`, which the next step rejected by an exact comparison.
  Rolling BESS measurements now reject values outside the bound by more than
  `1e-6 kWh` and clamp only within-tolerance floating-point residue to the
  physical bound. A `119.99 kWh` measurement still fails. This changes no
  physical SOC constraint and does not waive a material violation.
- The next clean trial (`output/2026-07-27/run_20260727_1703`) completed all 24
  feasible rolling steps and passed chain acceptance, then exposed two final
  reporting blockers. The experiment report adapter expected flattened cost
  keys instead of reading `graph/canonical_cost_ledger.json`, and the workbook
  export silently ignored a missing `openpyxl` dependency. Final experiment
  accounting now comes only from the canonical ledger, `openpyxl` is an
  explicit runtime dependency, and a missing experiment report or workbook is
  a job failure rather than a successful frontend run.
- Clean-commit, frontend-equivalent HTTP jobs were completed from
  `9a517c31c09af2ba1400ef40698a522373a0e761`:
  high PV `output/2026-07-27/run_20260727_1800` and low PV
  `output/2026-07-27/run_20260727_1744`. Both use service date 2025-08-05,
  serve 264/264 trips, execute 24/24 feasible hourly steps, pass rolling-chain
  acceptance and executed-day accounting, preserve BEV/BESS terminal energy,
  and write the mandatory canonical report and workbook. Both manifests record
  the same clean Git SHA. The trip, vehicle, initial-SOC, charger, and
  day-ahead assignment hashes match across the pair; only the declared PV
  profile differs (614.709375 versus 101.114300 kWh).
- Before the accepted low-PV rerun, the stored low-PV scenario still combined
  2025-08-10 (Sunday) with `WEEKDAY`; the frontend job correctly failed closed
  in `output/2026-07-27/run_20260727_1740`. The scenario was then prepared as
  an explicit same-service-date PV counterfactual: the service/timetable date
  is 2025-08-05, while the low-PV curve source remains identified as
  2025-08-10. Weather-operation policy is disabled in both final cases so that
  future information from the proxy curve cannot alter operational controls.
  These prepared choices are persisted in each run's `effective_scenario.json`
  and input provenance.
- This closes the frontend orchestration requirement, not the research release
  gates. Both final runs deliberately remain
  `teacher_release_status=BLOCKED` and
  `research_submission_ready=false`. The recorded blockers are
  `research_vehicle_inventory_contract`, `exact_milp_backend`,
  `day_ahead_research_acceptance_failed`, and
  `physical_schedule_not_validated`. In particular, the inventory gate has not
  been weakened or removed, and the two-stage/pruned model is not relabelled as
  an integrated global optimum. The pair is valid evidence that the normal
  frontend path completes day-ahead plus hourly rolling; it is not yet a
  teacher-ready formal weather comparison.
- Validation for the implementation commit completed with
  `python -m pytest -q -p no:cacheprovider` (**896 passed**),
  `python -m compileall -q src bff scripts tools`, and `git diff --check`.

## 2026-07-26 remediation implementation: physical movement, provenance, and comparison gates

### Implemented in the current working tree

- The verified interactive call path remains
  `BFF _run_optimization -> ProblemBuilder -> OptimizationEngine ->
  _persist_canonical_graph_exports -> build_accounting_artifacts`.
  Canonical export now emits exactly one `startup`, `connection`, or
  `terminal_return` row per modeled non-service movement in
  `graph/movement_event_ledger.(csv|json)`. A connection is owned only by the
  following trip; `trip_assignment.deadhead_after_km` no longer duplicates the
  next leg's `deadhead_from_prev_min`.
- ICE service fuel/CO2 and movement fuel/CO2 are calculated from physical
  distance and canonical vehicle/type rates. The accounting layer aggregates
  these quantities without scaling them to a monetary total. The BFF
  regression with 12 km service plus 18 km of startup/connection/return travel
  obtains 6.0 L total fuel, of which 3.6 L is movement fuel, and checks the
  solver fuel/CO2 reconciliation rows.
- Service date and timetable day type are validated before canonical problem
  construction. Counterfactual PV input keeps the operating service date
  separate from `weather_observation_date` and `weather_profile_source`.
  `graph/calendar_weather_validation.json` and
  `graph/research_fleet_validation.json` preserve both contracts. A declared
  research inventory mismatch (including 35 BEV + 26 ICE versus 35 + 25)
  hard-fails instead of silently changing vehicle counts.
- Self-review found and fixed an acceptance-order bug: calendar/fleet checks
  were initially appended after `failed_checks` and `accepted` had already
  been calculated. They now participate in the decision itself. The formal
  weather runner binds its CLI `--expected-bev-count` /
  `--expected-ice-count` declaration into the canonical problem before build,
  and an undeclared research fleet is not accepted.
- Input provenance now includes complete canonical trip/vehicle/PV hashes,
  runtime Python/Gurobi details, tracked-patch and untracked-file hashes. A
  research run requires clean Git at start and rejects a SHA/dirty-state change
  during the solve. Missing or modified manifest artifacts remain
  non-research.
- `return_to_initial` BEV failure or BESS terminal deviation beyond the
  recorded tolerance blocks `validated_feasible` and research KPI eligibility.
  Reporting rebuild `updated_files` is now derived from before/after content
  hashes; an unchanged `results.xlsx` is not claimed as regenerated.
- Existing hourly rolling remains a separate, explicit chain:
  `scripts/run_hourly_charging_reoptimization.py` writes every step and
  `rolling_chain_summary.json`. A day-ahead frontend run remains
  `rolling_execution=not_executed` until that chain is actually completed and
  accepted; no status is inferred from code availability.
- Validation on 2026-07-26 completed with Gurobi enabled:
  `python -m pytest -q -p no:cacheprovider` returned **858 passed**,
  `python -m compileall -q src bff` passed, and `git diff --check` reported no
  whitespace errors.

### Comparability and unfinished external gates

- This changes the physical fuel/CO2 and deadhead accounting definition.
  `run_20260726_1502` and `run_20260726_1518` must not be repaired in place or
  reused as research evidence. A new clean-commit paired run is required.
- No new 264-trip high/low-PV optimization or hourly chain has been executed by
  this code-editing task. Therefore the four final reporting checks, full-run
  terminal balances, ≤10% predeclared gap gate, and weather-comparison
  acceptance are not yet empirically closed.
- Independent Claude Code and executive reviews required by
  `docs/AI_AGENT_REMEDIATION_20260726.md` have not yet been performed. P0/P1
  closure and teacher-facing completion must not be claimed until those
  reviews and the clean rerun are complete. The current Codex self-review is
  recorded separately in
  `docs/reviews/ai_agent_remediation_self_review_20260726.md`.

## 2026-07-26 AI agent remediation specification for the reviewed runs

- Added docs/AI_AGENT_REMEDIATION_20260726.md. It turns the strict review of
  the 2026-07-26 high-PV and low-PV outputs into an implementation order,
  non-negotiable research guardrails, regression requirements, clean-rerun
  acceptance gates, and independent-review checklist.
- This documentation change does not alter the solver, model inputs, or any
  historical result artifact. The reviewed ZIP remains non-research evidence
  until a new run meets the documented provenance, physical-ledger, calendar,
  terminal-SOC, and rolling-horizon gates.

## 2026-07-26 Review correction: physical fuel ledger and objective semantics

### Problems raised and closed in code

- **P1 - reporting changed physical fuel quantities to match a cost total:**
  the `fuel_factor` / `co2_factor` allocation introduced in `e2e54f1` was
  invalid. A monetary discrepancy must never rewrite liters, tank start/end,
  refueling, balance error, or physical ICE emissions. The allocation function
  has been removed. Fuel liters and ICE CO2 now remain derived from distance
  and vehicle parameters. `fuel_cost_jpy` alone follows the
  `cost_component_flags.fuel_cost` switch. If the physical ledger and
  solver-canonical cost or CO2 total disagree, the new
  `solver_fuel_cost_matches_physical_fuel_ledger` /
  `solver_ice_co2_matches_physical_fuel_ledger` checks remain `NG`; reporting
  does not repair the evidence.
- **P1 - non-cost objectives were incorrectly required to equal accounting
  cost:** `graph/canonical_cost_ledger.json` now records
  `objective_accounting_equality_required` as a semantic contract. The
  objective-versus-accounting ERROR check runs only when that contract is
  true. For CO2, balanced, utilization, and two-stage proxy objectives where
  it is false, the check is `SKIPPED`; cost correctness is still enforced by
  `canonical_cost_ledger_accounting_residual`. A coincidental numerical match
  does not relabel a non-cost objective as actual cost. Non-cost objectives
  are emitted with unit `solver_objective_score`, not JPY.
- **P2 - global `FeasibilityTol=1e-9` could burden the runtime-dominant Stage
  1 MILP:** tolerances are now explicit `OptimizationConfig` fields. Stage 1
  defaults to Gurobi's `1e-6`; Stage 2 retains `1e-9` because terminal SOC is
  audited at `1e-6 kWh`. Both effective values, maximum constraint/bound/
  integrality violations, coefficient range, and a scaling-warning flag are
  written to solver metadata and `solver_settings.json`.
- **P2 - the startup-deadhead regression did not traverse the real solver:**
  a Gurobi two-stage integration test now executes
  `GurobiMILPAdapter -> AssignmentPlan -> FeasibilityChecker` with a 30-minute
  non-zero startup deadhead and `return_to_initial`, and requires a feasible
  Stage 2 result plus independent `VALID` feasibility.

### Research validity and remaining measurement

- This correction does not modify timetable rows, `operator_id`, or
  `arrival + turnaround + deadhead <= next departure`.
- It changes reporting semantics introduced only by `e2e54f1`; no result
  produced with the fuel-allocation code may be used as a physical fuel or CO2
  ledger. A fresh optimization run is required.
- A five-repeat tiny paired smoke test at Stage 1 `FeasibilityTol=1e-6` and
  `1e-9` produced feasible solutions, zero reported maximum constraint
  violation, and zero Stage 1 gap in both cases. The model solved in roughly
  one millisecond, so this is a correctness smoke test, **not** evidence about
  full 264-trip runtime. Full-scale paired runtime, gap, and scaling comparison
  remains a required manual experiment.
- Focused accounting/reporting/SOC tests passed, including the real Gurobi
  round trip. Full local regression completed with **844 passed**
  (`python -m pytest -q`, 2026-07-26); `compileall` also passed.

## 2026-07-25 P0 closure: startup-deadhead SOC and canonical cost ledger

### Problems raised and closed in code

- **P0 — the independent SOC checker omitted the first depot deadhead:** the
  Phase 3 solver deducted depot-to-first-trip energy, while
  `FeasibilityChecker` deducted only inter-trip deadheads. Startup,
  connection, and return deadhead energy now use shared functions in
  `soc_helpers.py`. The checker deducts the departure-posted deadhead before
  evaluating departure readiness. Rolling validation now follows the solver's
  all-or-nothing posted-event convention instead of prorating a transition
  across a rolling boundary.
- **P0 — reporting removed demand and grid-CO2 costs:** frontend/BFF runs now
  write `graph/canonical_cost_ledger.json` directly from the solver-evaluated
  `CostBreakdown`. The reporting finalizer consumes that immutable ledger and
  no longer reads an empty `demand_charge` alias or infers a carbon price from
  a previously zeroed CO2 cost. Demand, CO2, fuel, vehicle-use, and the
  accounting residual are therefore emitted from one definition.
- **Superseded on 2026-07-26:** the attempted vehicle-level fuel/ICE-CO2
  allocation was physically invalid and has been removed. See the review
  correction above.
- **P0 — BESS fixed-target tolerance could fail the stricter validator:** fixed
  BESS terminal targets are mathematical equalities in both stages. As of
  2026-07-26, Stage 1 uses `FeasibilityTol=1e-6` and Stage 2 uses `1e-9`;
  independent acceptance remains `1e-6 kWh`.

### Research validity and comparability

- This patch does not change timetable rows, operator identity, or the hard
  dispatch condition
  `arrival + turnaround + deadhead <= next departure`.
- It changes SOC validation and the BESS terminal-target constraint. Results
  generated before this patch must be rerun before claiming physical
  feasibility or daily energy neutrality.
- It changes which cost artifact is authoritative. Old reports whose demand or
  CO2 rows were zeroed must not be quoted; new runs must have
  `canonical_cost_ledger_accounting_residual=OK`. The objective/accounting
  equality check is required only when
  `objective_accounting_equality_required=true`; otherwise it is `SKIPPED`.
- This does **not** close the separate weather-study, ICE 26-vehicle, EV
  35-vehicle-use, hourly rolling, or global integrated-optimality requirements.

### Validation

- Added a non-zero startup-deadhead + return-to-initial regression: startup
  9 kWh, service 10 kWh, return 18 kWh, and 37 kWh restored charging.
- Added canonical cost-ledger regressions that preserve demand charge and grid
  CO2 cost, plus accounting-ledger tests for peak-kW demand charging and
  grid-plus-ICE CO2.
- Focused regression suite completed with **115 passed**. Full local
  regression completed with **840 passed** (`python -m pytest -q`,
  2026-07-25).

## 2026-07-25 Frontend operation-time-window control: explicit full-day canonical horizon

### Problems raised and closed in code

- **P1 — `start_time` / `end_time` had no explicit enable state:** the Tk
  screen formerly sent `05:00–23:00` as an implicit default.  The paired
  fields now have the checkbox **「開始・終了時刻を時間帯制約として使う」**.
  It is off by default; when off, the fields are disabled and the interactive
  Prepare path sends `operation_time_window_enabled=false` with a 24-hour
  planning horizon.  New UI defaults are `00:00–23:59`.
- **P1 — `23:59` could accidentally mean a 1,439-minute horizon:** when the
  checkbox is off, `ProblemBuilder` constructs exactly `24*60` minutes and an
  integral number of timestep slots.  `23:59` remains the user-facing
  inclusive end label; the canonical energy horizon ends at `00:00` on the
  next clock cycle.
- **P1 — a reviewer could not distinguish a saved pair from the solved
  horizon:** Quick Setup, Prepare, BFF, and the canonical builder now carry
  `operation_time_window_enabled`.  The requested pair is retained so it can
  be re-enabled later, while `operation_time_window_effective_*` and
  `interactive_operation_time_window_controls` record the actual solver
  horizon in `effective_scenario.json`, input provenance, solver metadata,
  and summary.  Weather-only comparison alignment also treats this boolean as
  a time-axis control.

### Scope and comparability

- This control changes the **energy/SOC optimization horizon**; it does not
  filter, rewrite, or invent timetable rows.  Dispatch feasibility remains
  `arrival + turnaround + deadhead <= next departure`.
- With the checkbox on, the stored pair is the requested scoped horizon.
  Existing BEV/BESS terminal-SOC requirements may still extend the internal
  energy horizon to a full day; reviewers must read
  `operation_time_window_*` and `energy_horizon_*` separately.
- A run made under the old implicit `05:00–23:00` condition is not directly
  comparable to a new full-day run unless the control, timestep, terminal-SOC
  policy, and all other input hashes match.

### Validation

- `C:\master-course\.venv\Scripts\python.exe -m py_compile` completed for the
  Tk frontend, BFF control path, and canonical builder modules changed here.
- `C:\master-course\.venv\Scripts\python.exe -m pytest -q` completed with
  **835 passed** (2026-07-25).  The regression coverage includes Tk payload
  generation, Quick Setup persistence, Prepare defaults, canonical full-day
  slot construction, BFF provenance, and weather-comparison alignment.

## 2026-07-25 Major revision: manual-run terminal-SOC neutrality and evidence-table truthfulness

### Problems raised and closed in code

- **P1 — the human report conflated three different MIP-gap concepts:**
  `experiment_report.md` previously put the achieved/certified Stage 1 gap in
  both the `MIP Gap 目標` and `MIP Gap 実績` rows. New reports now state the
  requested Gurobi gap, Stage 1 Gurobi native gap, certified/analytical gap,
  certified-gap semantics, and Stage 1 termination reason separately. For the
  2026-07-24 high/low-PV reruns this means `10%` requested, `100%` native gap,
  and the separate certified value (for example `9.205%`), not a claim that
  Gurobi reached 9.205%.
- **P1 — BEV terminal inventory made a day-cost comparison non-neutral:** the
  interactive BFF path now applies `bev_terminal_soc_policy=return_to_initial`
  after weather/scenario overlays and before `ProblemBuilder` runs. It clears
  the legacy fixed-target percentage and tolerance in the effective in-memory
  scenario, adds the matching upper equality constraint already implemented by
  the MILP, and writes both requested and effective states to
  `interactive_terminal_soc_controls`. This is a mathematical model change:
  all earlier fixed-target manual runs must be treated as a separate legacy
  condition and must not be compared as daily operating-cost evidence.
- **P1 — condition CSVs did not describe the model actually solved:**
  `simulation_conditions_tou_prices.csv` and
  `simulation_conditions_contract_limits.csv` formerly read optional UI values
  and could emit `depot_A`/zero values even when the canonical problem used a
  real tariff and a 1,000 kW limit. Interactive output now derives TOU,
  sell-back price, CO₂ factor, depot ID, import limit, and the distinct
  `demand_charge_weight` from `CanonicalOptimizationProblem`. A physical base
  load is left blank unless it is explicitly represented by the canonical
  problem rather than being inferred from that weight. A separate
  `simulation_conditions_provenance.json` records the exact source. A distinct
  transformer limit is left blank rather than invented when it is not modeled.

### Preserved and intentionally unresolved scope

- Dispatch feasibility (`arrival + turnaround + deadhead <= next departure`),
  timetable rows, operator IDs, PV/BESS physical constraints, and the formal
  CLI-runner settings are unchanged.
- This does **not** make the 2026-07-24 runs formal weather studies, global
  total-cost optima, or hourly rolling results. They remain exploratory
  high-PV/low-PV sensitivity runs until the strict same-service-date runner and
  actual rolling chain are executed.

### Required manual verification after the next frontend run

1. In `experiment_report.md`, confirm the four distinct rows: requested gap,
   Gurobi native gap, certified gap, and Stage 1 termination reason.
2. Confirm `summary.json` says `bev_terminal_soc_policy=return_to_initial` and
   `bev_terminal_soc_balance_satisfied=true`; the report should show zero BEV
   terminal-SOC net drawdown within numerical tolerance.
3. Confirm `simulation_conditions_provenance.json.source=canonical_problem`,
   `simulation_conditions_tou_prices.csv` uses the actual depot ID and tariff,
   and the contract CSV uses the canonical depot import limit.

### Validation

- Focused regression suite: report-gap semantics, terminal-policy enforcement,
  canonical condition-table export, accounting-report payload, and graph-output
  parity.
- Full local regression after the change: `830 passed` (`python -m pytest -q`).
- MIT-style code review found no remaining P0/P1 defect in this patch. The
  review specifically rejected inferring a physical base load from
  `demand_charge_weight`; the final export keeps those fields separate.

## 2026-07-24 Major revision: stop-rule transparency and canonical research reporting

### Problems raised and closed in code

- **P1 — front-end runs required users to remember runtime controls:** the Tk
  payload now supplies `stage1_best_obj_stop_enabled=false` and
  `gurobi_threads=1`, and the BFF worker enforces the same values immediately
  before `OptimizationConfig` is built. A stale or manually edited frontend
  request cannot re-enable the early stop or change the thread count. The raw
  request and the enforced effective values are both persisted under
  `interactive_runtime_controls`; the formal CLI runner remains explicitly
  configurable.
- **P1 — apparent sunny/low-PV runtime differences could be caused by a hidden
  stopping rule:** Stage 1 previously always set Gurobi `BestObjStop` whenever
  its analytical vehicle-day lower bound existed. A high-PV case could therefore
  stop as soon as its first incumbent crossed the threshold while another case
  ran to its time limit. `OptimizationConfig.stage1_best_obj_stop_enabled` now
  makes that rule explicit (default `true` preserves operational planning
  behavior). The BFF and formal runner record whether it was enabled, actually
  applied, its threshold, whether it triggered, and the Stage 1 termination
  reason. Runtime experiments must use `--no-stage1-best-obj-stop` and an
  explicit, common `--gurobi-threads` value for every repetition.
- **P1 — a displayed Stage 1 gap could be mistaken for Gurobi's native gap:**
  artifacts now expose `stage1_gurobi_raw_mip_gap_ratio` separately from
  `stage1_certified_mip_gap_ratio`. The latter may use the maximum of Gurobi's
  `ObjBound` and the analytical path-cover lower bound; it is not the same
  object as the raw Gurobi MIP gap. The legacy `stage1_mip_gap_ratio` remains
  for compatibility and denotes the certified/composite value.
- **P1 — experiment reports were generated before the reporting finalizer:**
  this could omit final demand-charge and CO₂-cost terms even when
  `summary.json` and `kpi_summary.json` reconciled. The report is now generated
  only after finalization, from those canonical sidecars, and rejects a report
  when total cost differs from grid electricity + demand allocation + fuel +
  CO₂ cost + vehicle-use cost. The report records the run Git SHA supplied by
  the pre-solve provenance capture rather than relying on a best-effort shell
  lookup.
- **P1 — manual PV-only runs could be relabelled after the fact:** every manual
  frontend artifact now writes `research_claim_scope.json`. A PV-only,
  unaccepted day-ahead run is labelled
  `exploratory_pv_supply_sensitivity_not_weather_adaptive_dispatch`; it
  explicitly disallows claims of weather-adaptive dispatch, formal weather
  comparison, integrated global optimum, monthly demand-bill savings, PV/BESS
  investment economics, or any standalone wall-clock comparison. Disabling
  `BestObjStop` is necessary but still requires matched controls and repeated
  paired measurements.

### Current interpretation of the 2026-07-24 pair

`run_20260724_1345` and `run_20260724_1348` remain useful physical-feasibility
and high-PV/low-PV energy-flow sensitivity artifacts. They are not formal
sunny/rainy evidence: their service dates differ, the low-PV date is a Sunday
while using the weekday timetable, the runs are not accepted research runs, and
no hourly rolling chain was executed. They must not be presented as proof that
sunny cases solve faster, that weather adapted the assignment, or that the
integrated total cost was optimized globally.

### Required follow-up experiments

1. Create the strict same-service-date PV-counterfactual pair with ICE26 real
   inventory, identical timetable/fleet/initial SOC, and `return_to_initial`
   BEV terminal SOC.
2. Run the actual 24-step hourly rolling chain for both cases; do not infer it
   from a day-ahead result.
3. Benchmark time only with `--no-stage1-best-obj-stop`, fixed seed, explicit
   fixed Gurobi threads, identical time limits, and multiple repetitions. Report
   the raw Gurobi gap, certified gap, and termination reason for every run.

## 2026-07-24 Research evidence contract: counterfactual weather comparison and run provenance

### Problems raised and closed in code

- **P1 — code provenance could be blank:** frontend runs previously relied on a
  bare `git` invocation, so `git_sha` and `git_dirty` could be absent. The run
  now captures a structured pre-solve `code_provenance.json` using the configured
  Git executable or standard Windows/Codex locations. The same state is copied
  into the input manifest, solver metadata, and top-level run manifest. Formal
  acceptance rejects unavailable, missing, or dirty Git provenance.
- **P1 — exactness was overstated:** depot/time-step PV/grid/BESS flows are solver
  variables, whereas vehicle-source rows can be proportional allocations. The
  emitted `charging_source_provenance.json` now records both scopes separately:
  `depot_source_provenance_exact` and
  `vehicle_source_provenance_exact`, plus the allocation method. Root KPI and
  graph metadata no longer promote an exact site total into an exact vehicle claim.
- **P1 — weather-only comparison was not identifiable:** the formal Phase 3
  runner and comparator now require a `same_service_date_pv_counterfactual`
  contract. The baseline and counterfactual share prepared input, service date,
  timetable, fleet, initial SOC, and all operational controls. The
  counterfactual applies only an explicitly hashed PV curve. Old weekday-versus-
  Sunday pairs are rejected rather than labelled as weather-only evidence. The
  comparator also requires the substituted curve to change at least one depot's
  PV-generation hash or total, preventing a relabelled duplicate run.
- **P2 — neutral PV-only policy was easy to misread:** the runner now writes a
  `weather_decision_policy` audit. When the policy changes only the PV curve, it
  explicitly says that no weather dispatch or SOC policy was active; a cost or
  assignment difference may not be claimed without a separately specified,
  numerically auditable operating policy.

### Preserved model meaning

- The dispatch feasibility condition
  `arrival + turnaround + deadhead <= next departure` is unchanged.
- Neither a 26th ICE vehicle nor 35 used BEVs is fabricated. ICE26 and a
  minimum-used-BEV condition remain explicit scenario/policy inputs that must be
  prepared and solved with real vehicle records.
- A frontend output records rolling execution as `not_executed` unless a real
  hourly rolling chain and its logs are present. The changes do not claim that a
  rolling result has been run.

### Required next manual experiments

1. Prepare a clean ICE26 scenario with an actual vehicle ID and run the formal
   baseline and PV-counterfactual pair from the same service date and prepared
   artifact.
2. Run the actual hourly rolling chain and attach its state transitions,
   re-solve times, feasibility checks, and plan-delta metrics.
3. If EV35 use is a policy requirement rather than an investment decision, run it
   as an explicit `minimum_used_bev_count=35` sensitivity alongside the
   unconstrained cost-minimization case.

### Validation

- Focused regression tests cover provenance capture/validation, counterfactual PV
  substitution, strict weather comparison contracts, and root/graph source-
  provenance parity. The commands and acceptance interpretation are documented
  in `docs/notes/phase3_manual_validation_runbook_20260716.md`.

## 2026-07-23 フロント手動runの入力provenance出力（本番最適化未実行）

### 結論
- フロントの手動実行経路`run-optimization -> _run_optimization() -> prepared input materialize -> runtime/weather override -> ProblemBuilder -> OptimizationEngine`について、solver開始前にscenario・Prepare・要求パラメータ・canonical実効値を`output/<date>/run_*`へ固定する。
- 従来の`optimization_audit.json`や`solver_settings.json`には個別情報があったが、元scenario、Prepare scope/profile、実行時override、実効モデル値、prepared artifactそのものの同一性が一つの検証契約になっていなかった。新しいbundleはこれらを相互参照し、後付け改変をSHA-256で検出する。

### 新しいrun直下成果物
- `scenario_input_snapshot.json`: 保存scenarioの軽量snapshot、実効`simulation_config`/`scenario_overlay`/dispatch scope、実際にPrepareされた車両・充電器・営業所・路線inventoryと各hash。
- `prepare_input_audit.json`: prepared input ID/schema、作成時刻、dataset、service date、選択営業所・路線・曜日、Prepare profile、scope/count、距離監査、scenario/scope hash、元prepared JSONの絶対/相対path・byte size・完全SHA-256。
- `optimization_parameters.json`: Pydanticで受理したフロントrequest body、BFF正規化後の要求値、`OptimizationConfig`実効値、canonical horizon/timestep/coverage、model metadata、入力件数とtrip/vehicle/charger ID hash、値の上書き優先順位。
- `run_input_summary.md`: 上記の人間向け索引。JSONを正本とし、Markdownは説明用とする。
- `run_input_manifest.json`: compact成果物のbyte sizeとSHA-256。
- `run_input_validation.json`: run生成時のschema、hash、scenario ID、prepared input ID相互整合結果。
- 既存`run_manifest.json`にも`run_input_provenance.status=OK`、schema、prepared ID/source SHA、artifact一覧を載せる。

### 実装上の判断
- 現行prepared inputは1件約249.7MBであるため、各runへ全量複製しない。row-level trips/stop sequences等は元artifactへ残し、run側は完全SHA-256、size、path、scope/count/auditとcompact inventoryを保存する。これによりoutput肥大化を避けつつ、元prepared artifactが残る場合はbyte単位の一致を再検証できる。
- `scripts/verify_run_input_provenance.py --run-dir <RUN_DIR>`はcompact bundleと元prepared sourceを再hashし、不一致時は終了コード2を返す。`--skip-prepared-source`ではrun内bundleだけを検査する。
- provenanceの保存・内部検証に失敗した場合はsolverを開始しない。研究runで入力監査だけ欠落した成功成果物を新たに作らない。
- `timetable_rows`、`operator_id`、数理制約、費用式、SOC/PV/BESS式は変更していない。今回の変更は入力provenanceの保存契約だけであり、既存実験の数理的意味は変えない。

### 検証
- 実prepared input`prepared-9bdbed865edc013c-e6406a7fd75ec751-0ec9cc15`（249,714,439 bytes）を用いた軽量preflightで、source再hashを含め`valid=true`を確認した。
- 追加されたrun内6ファイルは合計約0.4MB（scenario snapshot約273KB、Prepare audit約116KB、parameters約13KB、その他約4KB）だった。
- compact artifact改変、元prepared source改変、scenario/prepared ID不一致、manifest hash不一致の回帰を追加した。Python全回帰は`810 passed`、compileallと`git diff --check`も通過した。
- 本番最適化はユーザーが手動実行するため未実行。既存runにはこのbundleがないため、新しい正確な成果物を過去runへ推測でbackfillしない。

## 2026-07-23 13:50/13:55成果物の厳格監査と入力ゲート修正（本番再計算前）

### 結論
- `output/2026-07-23/run_20260723_1350`（晴天）と`run_20260723_1355`（雨天）は、説明用の非研究runであり、正式な晴雨比較には使用しない。両runは`research_run=false`、`research_run_accepted=false`、`research_cost_kpi_eligible=false`で、雨天runはtime limit、さらに2025-08-10（日曜）を`WEEKDAY`として構築している。
- 検証済みの実行経路は、フロント/BFFの非研究実行 → `ProblemBuilder` → `OptimizationEngine` → `GurobiMILPAdapter._solve_thesis_two_stage()` → graph export → reporting finalizerである。既存成果物のサイト電力収支とBESS終端SOCは整合するが、車両別電源内訳は数理モデルで直接決定した値ではなかった。
- 「1時間rollingが未実装」という評価は正確ではない。`scripts/run_hourly_charging_reoptimization.py`に24時間連鎖と受入判定は実装済みだが、対象2runでは実行されていない。したがって現状の正しい表現は「実装済み・当該成果物では未実行」である。

### 根本原因と修正
- Stage 2 MILPは営業所×時刻の系統/PV/BESS供給量と車両別充電量を決定するが、車両×電源の直積変数は持たない。それにもかかわらず`vehicle_source_provenance_exact=true`を出していたため、BFFが物理充電器IDを電源IDとして解釈し、車両別646.15 kWhを全量系統扱いした。metadataを`false`へ修正し、車両別表示は営業所×時刻の確定比率による按分であることを`proportional_by_depot_timestep`として明示した。サイト台帳は確定値、車両別電源は推計値であり、大域的に一意な車両別由来とは主張しない。
- 晴雨のproxy forecast JSONが旧schemaのままで`capacity_factor_by_slot`を欠き、`missing_capacity_factor_by_slot`としてPV予測曲線が適用されていなかった。既存の生成器から24点の時刻別係数を再生成し、formal runnerは`weather_pv_forecast_applied=true`でないrunをbuild-only段階から拒否する。
- 現在の`solcast_pv_proxy_v1`は対象日実PV形状を読む検証用・Oracle寄りのproxyであり、実運用の予報精度を証明するものではない。まず制御された晴雨可行性比較に用い、予報頑健性はrollingのPV予測誤差ケースで別評価する。
- formal runnerに暦日と`service_id`の整合ゲートを追加した。`WEEKDAY`は月曜～金曜、`SAT`は土曜、`SUN_HOL`は日曜を要求する。監査側のproblem再構築も`input_audit.json`に記録した`service_id`を用い、`WEEKDAY`へ固定しない。
- BEV35台全数使用は費用最小化の基準ケースへ暗黙に混ぜず、`--minimum-used-bev-count 35`を明示した政策感度として実装した。基準ケースは0台下限のまま、車両日費用は`--vehicle-usage-cost-jpy-per-used-bus`で永続scenarioを変更せず感度比較できる。これは数理的に`sum(used_vehicle[BEV]) >= N`を追加するため、過去結果との直接比較には政策制約の有無を必ず併記する。
- 指導教員向け監査に、formal research acceptance、暦日整合、PV予測曲線適用、明示したBEV最低使用台数、任意の`--require-rolling`を追加した。rollingを要求する最終監査では、晴雨双方の`rolling_chain_summary.json.chain_accepted=true`と60分実行間隔に加え、scenario、prepared input、service date、trip/vehicle hash、Git SHA、日次`solver_result.json` SHA-256が監査対象の日次runと一致することを必要とする。

### 軽量検証と残作業
- 2025-08-05晴天・ICE25台のbuild-onlyは、264便、15分×96 slot、BEV35/ICE25、`calendar_service_contract.matches=true`、`weather_pv_forecast_applied=true`まで確認した。ICE26台を要求したbuild-onlyは在庫不一致で停止し、2025-08-10を`WEEKDAY`としたbuild-onlyは日曜不一致で停止した。これは意図したfail-closed動作である。
- 政策感度のbuild-onlyで`minimum_used_bev_count=35`と`vehicle_usage_cost_jpy_per_used_bus=10000.0`がcanonical problem、input audit、experiment hashへ伝播することを確認した。Python全回帰は`808 passed`、compileallと`git diff --check`も通過した。
- 現行prepared inputは晴雨ともICE25台である。実在する26台目を登録して再Prepareするか、当日利用可能25台である根拠をデータ化し、25台ケースを明示的な在庫感度として扱うまで正式計算を開始しない。車両IDや諸元は捏造しない。
- 2025-08-05（火）と2025-08-10（日）の結果を「PVだけが異なる晴雨比較」とは呼べない。推奨する正式比較は、同一service date・同一`service_id`・同一prepared trip scopeへ晴天/雨天の予測曲線だけを与える反実仮想ケースである。日曜実績を使う場合は`SUN_HOL`の別ダイヤ分析として分離する。
- 本番の晴雨最適化と24時間rollingはユーザーが手動実行するため未実行。再実行後も、Stage 1 gapは代理目的のgapであり、最終会計総費用の大域最適性とは表現しない。
- `timetable_rows`、`operator_id`、道路距離、`arrival + turnaround + deadhead <= next departure`は変更していない。道路距離は今回も明示的な保留範囲である。

## 2026-07-23 指導教員受入条件のfail-closed化（未実行）

### Slack原文から確定した受入観点
- 2026-06-11: 系統購入、bus/BESS充放電、PVの行き先、PV抑制を時系列で帳尻確認し、ICE燃料を運行と照合する。
- 2026-06-17: 充電量を瞬時に計上せず、車両・充電器のkW上限と所要時間を反映し、時間帯ピークを説明できるようにする。
- 2026-06-18: 一日終了時のBESS SOC差分0、BEV35台・ICE26台の入力、全グラフでの晴雨比較を確認する。BEV35台全数使用は質問事項であり、最適化へ強制する要件とは解釈しない。
- 2026-07-16: 修正内容と用語を具体化し、計算時間を短縮し、日次計画後に毎時再最適化する二段階運用を示す。

### 今回塞いだ穴
- `run_hourly_charging_reoptimization.py` の24時間連鎖は、従来は各stepが可行なら終了コード0になり、実行prefixをつないだ一日会計が不完全、BEV終端不均衡、BESS終端SOCが初期/指定値と不一致、又はGit provenance不明でも成功扱いになり得た。`chain_accepted`を追加し、全step可行、実行slotの重複・欠落なし、一日会計受理、BEV終端均衡、BESS終端偏差`1e-6 kWh`以下、日次・rolling双方のGit cleanを全て満たす場合だけ終了コード0にした。
- rolling開始前に日次runの`manifest.json`を検証し、`summary.json`、`solver_result.json`、`input_audit.json`、`effective_scenario.json`等の改ざん・欠損を拒否する。PATHにGitがないCodex/Windows環境でも同梱runtimeを探索し、Git不明をcleanと誤認しない。
- `audit_phase3_weather_energy_balance.py` は、変更可能な現在のscenario storeを読み直す方式をやめ、run内の`effective_scenario.json`をSHA-256照合してcanonical problemを再構築する。晴雨manifestと非天候条件一致も監査前に必須化した。
- 同監査へ`advisor_acceptance`を追加した。BEV35/ICE26、宣言在庫一致、全便担当、全hard validation、PV/bus/BESS需給残差、BEV/BESS終端、物理充電器割当、燃料費残差、Git cleanを満たす場合だけ終了コード0になる。これは代表日可行性・会計の受入であり、統合総費用の大域最適性を意味しない。
- `start_time`/`end_time`は配車対象便を32本等へ固定する条件ではない。formal runnerはprepared scopeの`timetable_rows`全264便を対象にし、時間値は24時間の電力・SOC slot基準として使う。rolling手順では`05:00`を再ハードコードせず、日次`solver_result.json`の`metadata.horizon_start`を使用する。`timetable_rows`、`operator_id`、`arrival + turnaround + deadhead <= next departure`は変更していない。

### 検証と残作業
- 対象回帰は`35 passed`、compileallと`git diff --check`を通過した。本番の晴雨・24時間rollingはユーザーが手動実行するため未実行。
- 現行保存scenarioはICE25台なので、正式監査は意図どおり不合格になる。実在する26台目を登録し、晴雨を同条件でPrepareし直すまで正式計算を開始しない。
- 手動実行後は`weather_energy_balance_audit.json.advisor_acceptance.all_cases_accepted=true`、各`rolling_chain_summary.json.chain_accepted=true`を確認する。失敗時は`failed_checks`又は`rejection_reasons`を次の修正対象とし、結果を成功扱いしない。

## 2026-07-22 充電器種類・終端SOC・正式実験契約の修正（未実行）

### 結論
- 正式経路 `run_research_phase3_frontend_weather.py -> OptimizationEngine -> GurobiMILPAdapter._solve_thesis_two_stage()` の Stage 2 と統合MILPについて、90 kW×5口・50 kW×5口を合計10口・700 kWとして扱う集約制約を廃止し、車両×物理充電器×時刻の割当制約へ置換した。各充電中車両は同一時刻に1基だけを使い、充電器ごとの口数・出力、車両固有の最大受電電力、明示された互換充電器IDを同時に守る。
- `ChargingSlot.charger_id` は物理充電器IDとし、系統・PV・BESSの別は新設した `energy_source` に保存する。旧成果物の `grid:<depot>` 等は読取互換を維持する。
- BEV終端方針 `return_to_initial` は従来の `SOC_end >= SOC_initial` から、数値許容差 `1e-6 kWh` 内の上下限制約へ変更した。終端不足だけでなく超過量・最大絶対偏差も成果物に出す。
- 正式weather runnerは既定でBEV 35台・ICE 26台を要求する。現行シナリオのICE 25台では解く前に停止する。26台目の実在ID・諸元は捏造せず、シナリオ側で確定させる。旧25台条件は `--expected-ice-count 25` を明示した感度ケースとしてのみ実行できる。
- `summary.json`、`solver_result.json`、`input_audit.json`、`effective_scenario.json`、`vehicle_schedule.csv` のSHA-256とサイズを `manifest.json` に保存する。晴雨比較器はコード埋込みのgap 10%・ICE 25台・1500秒を要求せず、各runのmanifest宣言との一致と晴雨間の非天候条件一致を検査する。
- GitがPATHにないWindows環境でも標準的なGitインストール先を探索し、commit SHA・dirty状態を記録する。
- `timetable_rows`、`operator_id`、道路距離、ならびに `arrival + turnaround + deadhead <= next departure` は変更していない。道路距離は今回の明示的な保留範囲である。

### 検証
- 本番の晴雨最適化はユーザーが手動実行するため未実行。
- 物理充電器回帰では、90 kW充電6台を90 kW充電器5口へ割り当てるケースが infeasible、90 kW×5台＋50 kW×2台が feasible になることをGurobiで確認した。
- 終端SOC、Stage 2、成果物serializer、晴雨比較、manifest改ざん検出を含む対象テストは `111 passed`。追加の集中テストは `23 passed`、全回帰は `797 passed`。
- 2026-07-21の既存晴雨成果物は事後監査上、充電器種類別包絡と終端SOC等値を満たしていた。ただし旧モデルがそれを保証していたわけではないため、新モデルの正式結果として流用しない。

### 手動実行前に残る必須作業
1. 指導教員条件のICE 26台目について、実在する車両ID・燃費・燃料タンク・利用可否を晴雨両シナリオへ同条件で登録する。整備中等で当日25台のみなら、保有26・当日利用可能25と不可理由をデータ上で分ける。
2. cleanなmain commitから晴雨を同じgap・seed・時間上限で実行する。新しい物理充電器変数がStage 2時間へ与える影響は実測していないため、`stage2_runtime_seconds` と変数数を旧runと比較する。
3. 各runの `manifest.json`、`summary.json`、`solver_result.json` と `vehicle_schedule.csv` を保存し、比較器でmanifest検証後に晴雨差を作成する。
4. 新結果について、物理充電器ID別の同時使用、車両別終端SOC不足・超過、全264便、fallback/repairなし、Git cleanを確認する。
5. この後の研究上の穴は、全規模の複数seed・計算時間感度・電費±10%・PV予測誤差、最新割当を固定した24時間rollingである。総費用の大域最適性は引き続き主張しない。

## 2026-07-21 Stage 1 探索時間差の実測分解（晴天・雨天、gap 2.5%）

### 結論

- 現在の実行経路は `scripts/run_research_phase3_frontend_weather.py` → `OptimizationEngine.solve()` → `MILPOptimizer.solve()` → `GurobiMILPAdapter._solve_thesis_two_stage()` → `stage1.optimize(callback)` である。今回の変更は Gurobi callback による読取り専用テレメトリ追加だけで、目的関数、変数、制約、solver parameter は変更していない。
- 晴天と雨天の時間差は「実行可能解の発見速度」ではない。最初の incumbent は晴天 0.854 秒、雨天 0.893 秒で、両方とも約 0.9 秒だった。
- 雨天は root node の下界 `697,846.853334円` が 60.966 秒で得られ、最初の incumbent `715,275.268466円` との gap が `2.436603%` となり、設定した `2.5%` をその場で満たした。
- 晴天は root node の下界 `689,291.366319円` が 87.962 秒で得られたが、最初の incumbent `707,349.173370円` との gap は `2.552884%` で、目標をわずか `0.052884 percentage point` 超えた。2.5%を満たす incumbent 閾値 `706,965.503917円` より `383.669452円` 高かったため終了できず、その後 214.003 秒に incumbent を `703,718.306415円` へ改善して終了した。
- したがって、晴天の長時間化は二つに分解できる。(1) root relaxation / bound 構築が雨天より約27秒遅い、(2) 最初の incumbent が gap 閾値を僅差で外し、root node 内の追加探索に約126秒必要だった。最終 node count は両ケースとも1で、深い分枝探索ではない。
- 最終反復数は晴天が simplex `301,789`、barrier `41`、雨天が simplex `0`、barrier `24` だった。晴天では weather/PV により Stage 1 energy proxy の目的係数と近接代替解の構造が変わり、root node 内処理が重くなったことが直接観測された。ただし、係数構造から反復数増加への因果機構は現時点では推論であり、複数 seed・単独実行での再現確認が必要である。

### 成果物と再現条件

| ケース | 原記録 | Stage 1 runtime | first incumbent | target gap到達 | final gap | simplex / barrier |
|---|---|---:|---:|---:|---:|---:|
| 晴天 | `output/research_phase3_sunny_gap2p5_telemetry_20260721/solver_result.json` の `metadata.stage1_search_telemetry` | 214.246秒 | 0.854秒 | 214.003秒 | 2.050102% | 301,789 / 41 |
| 雨天 | `output/research_phase3_rain_gap2p5_telemetry_20260721/solver_result.json` の `metadata.stage1_search_telemetry` | 61.186秒 | 0.893秒 | 60.966秒 | 2.436603% | 0 / 24 |

- 両ケースは全候補ネットワーク、15分間隔、seed 42、Stage 1上限240秒、Stage 2上限60秒、candidate warm start無効、MIP gap 2.5%で実行した。並列実行のため壁時計の絶対値は単独実行の性能ベンチマークには使わず、Gurobi内部の同一run内イベント時刻を原因分解に使う。
- 両ケースとも264/264便、hard validation全通過、candidate restrictionなし、fallbackなし、postsolve repairなし。晴天はBEV/ICE担当便78/186、雨天は46/218で、天候による担当比率差も維持された。
- 道路距離、`timetable_rows`、`operator_id`、および `arrival + turnaround + deadhead <= next departure` は変更していない。

### 実装で塞いだ穴

- `src/optimization/milp/solver_adapter.py` に `_Stage1SearchTelemetry` を追加し、5秒間隔の MIP progress、全 incumbent notification（保存上限200件）、first incumbent、requested gap到達時刻、最終 node/solution/iteration count、callback error を保存するようにした。
- 初回の本番再実行では、テレメトリは最終 plan metadata と `solver_result.json` の `metadata` に完全保存された一方、`MILPOptimizer` の明示的な metadata 選別により簡易 `summary.json` へ伝播しなかった。この成果物伝播バグを `src/optimization/milp/engine.py` で修正し、既存2 runの `summary.json` も同一runの原記録で補完した。数理結果への影響はない。
- `tests/test_stage1_search_telemetry.py` にsampling、Gurobi infinity sentinel、gap到達時刻、保存上限、最終集計の回帰テストを追加した。`tests/test_milp_fragment_pairwise_reset_cut.py` では実Gurobi callbackのエラーなしと plan → solver metadata伝播を検証する。

### 残る穴と次の順序

1. 今回の時間値は同一seed・並列実行なので、性能の一般化には晴天/雨天それぞれを単独で複数seed・複数反復し、first incumbent、root bound、target gap到達、反復数の分布を比較する必要がある。
2. 晴天の初期 incumbent は終了閾値から僅か383.67円だけ悪い。既存candidate warm startは実測で遅く、かつ悪い解だったため既定で再有効化しない。数式を変えずに改善するなら、Gurobiの探索設定（例: primal emphasis）を対照実験として比較し、目的値・gap・hard validation・担当比率が退行しない場合だけ採用を検討する。
3. `assignment_global_optimality=false` はバグではない。今回の2.05%/2.44%は設定gap以内の証明であって gap 0 の厳密大域最適性ではない。これを `true` に見せる変更は禁止する。


## 2026-07-21 Stage 1下界強化・統合MILP照合・候補生成退行の解消（最終監査）

### 結論

- 正式なweather runnerの実行経路は `run_research_phase3_frontend_weather.py` → `OptimizationEngine.solve()` → `GurobiMILPAdapter._solve_thesis_two_stage()` である。最終Stage 1は全候補ネットワークを使い、時刻表パスを固定していない。`timetable_rows`、`operator_id`、および `arrival + turnaround + deadhead <= next departure` は変更していない。
- 統合MILPのICE経路で、始業・終業回送燃料の目的関数・燃料残量・事後会計が不一致だった。MILPへ始業/終業回送燃料・CO2・燃料状態遷移を追加し、事後会計へ欠けていた終業回送燃料・CO2・終端燃料を追加した。さらにStage 1目的にも始業/終業回送燃料・CO2を追加し、有効な下界を強化した。
- ICE固定10便の厳密監査 `output/small_integrated_rain_ice_only_oracle_20260721/audit.json` では、二段階Stage 1、統合MILP、事後会計がすべて `44,293.380321円`、gap 0、会計残差0円、未配車0、hard validation全通過となった。これによりICE経路を直接通した一致を確認した。
- 制限付きStage 1候補生成は晴天で126秒を消費したうえ、BEV 14台/46便の劣るincumbentへ探索を誘導した。候補生成なしではBEV 19台/78便、ICE 13台/186便、gap 2.0501%、総runner時間235.77秒となり、候補ありの実測約350.5秒より約103秒短く、目的も改善した。雨天でも候補生成なしは同じ解を維持し、約126秒を削減した。この比較に基づき `--stage1-candidate-time-limit-sec` の既定値を240秒から0秒（無効）へ変更した。明示的opt-inは残し、opt-inしても最終Stage 1ネットワークは制限しない。

### フル264便の最終結果（seed 42、15分、候補生成なし、MIP gap目標2.5%）

| 天候 | 成果物 | Stage 1目的 | Stage 1下界 | 認証gap | runner時間 | 使用車両 | BEV/ICE担当便 | 会計総費用 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 晴 | `output/research_phase3_sunny_gap2p5_no_candidate_20260721/summary.json` | 703,718.31円 | 689,291.37円 | 2.0501% | 235.77秒 | 32台 | 78 / 186 | 705,429.48円 |
| 雨 | `output/research_phase3_rain_gap2p5_no_candidate_20260721/summary.json` | 715,275.27円 | 697,846.85円 | 2.4366% | 80.13秒 | 32台 | 46 / 218 | 716,289.31円 |

- 両ケースとも264/264便、未配車0、重複0、時間重複0、不可能接続0、EV/BESS SOC違反0、充電器同時使用違反0、契約電力違反0で、research run acceptanceと全hard validationを通過した。
- 晴雨でBEV担当が78便対46便となり、以前観測されていた天候別のEV/ICE割合差が復元した。これは候補生成の恣意的固定ではなく、同一の全候補ネットワーク・seed・時間離散化・gap目標で得た結果である。
- `assignment_global_optimality=false` は正しい。2.05%/2.44%の認証gapが残るためStage 1大域最適を証明しておらず、二段階法は統合総費用の大域最適も主張しない。`false` を表示上だけ `true` にする修正は禁止する。
- 道路距離への置換はユーザー指示により今回の範囲外とした。trip距離入力は既存stop-sequence haversine、deadhead燃料は既存のdeadhead時間×設定速度を維持している。

### 小規模厳密照合・感度分析

- 混成10便の厳密照合は、晴 `output/small_integrated_sunny_formal_oracle_20260721/audit.json`、雨 `output/small_integrated_rain_formal_oracle_20260721/audit.json` で、二段階法と統合MILPの費用・台数・車種別担当便が一致した。晴40,000円、雨41,966.821777円、統合MILP gap 0、会計残差0円である。
- 5分感度は `output/small_integrated_sunny_5min_sensitivity_20260721/audit.json` と `output/small_integrated_rain_5min_sensitivity_20260721/audit.json`。晴は15分との差0円、雨は5分が5.995435円（0.0143%）安く、両方ともBEV 2台/10便で車種構成は不変だった。
- seed×時間上限（17/42/73 × 5/15/60秒）は晴雨合計18ケースすべて未配車0。晴の費用範囲は40,000～40,000円、雨は41,966.821777～41,966.821777円で、seed・時間によるぶれは0円だった。
- PV×BEV電費（PV 0.8/1.0/1.2、電費0.9/1.0/1.1）は晴雨合計18ケースすべて未配車0。晴は全ケース40,000円、雨は41,128.690526～42,804.953027円で、全ケースBEV 2台/10便を維持した。成果物は `output/small_integrated_sunny_full_sensitivity_20260721/audit.json` と `output/small_integrated_rain_full_sensitivity_20260721/audit.json`。
- これらは「一日の端を含む決定論的10便subset」の検証であり、264便全体の統合MILP大域最適性へ一般化しない。

### 実装・回帰検証

- `solver_adapter.py`: 統合MILPのICE始業/終業回送燃料・CO2、燃料出発準備、slot遷移、終端reserve、車庫外給油禁止を追加。Stage 1目的にも同じICE境界費用を追加した。
- `evaluator.py`: ICE終業回送を燃料費イベント、終端燃料、CO2へ追加し、MILPと会計の境界を一致させた。
- `audit_small_integrated_weather_milp.py`: 15分対5分、seed/時間、PV/電費の要約、fail-closed exact gate、監査専用BEV/ICE固定を追加した。
- `test_multiday_phase1.py` はlocalhostへシナリオ作成・長時間job起動を行う手動スモークスクリプトであり、単体pytestではない。`__test__ = False` を明示し、任意依存 `requests` がなくても安全に収集できるようにした。手動実行時の機能は維持した。
- `python -m compileall -q src scripts tests bff test_multiday_phase1.py` 成功。ルート全体の `python -m pytest -q` は `790 passed`。

### 残る主張上の限界

- `assignment_global_optimality=false` と `full_network_global_optimality=false` は未解決バグではなく、現在の証明範囲を正直に示す研究上の制約である。0%証明を求める場合は数分ではなく追加計算資源が必要であり、今回の「時間を掛けすぎない」という要件とは別実験として扱う。
- 小規模統合MILPは10便subsetでのみ厳密oracleとして成立する。264便の統合MILP照合、他subset、実道路距離は今回の結論に含めない。

## 2026-07-21 Stage 1 gap縮小と小規模統合MILP照合

### 結論

- 正式weather runnerの既定MIP gapを`0.10`から`0.05`へ変更した。晴天264便の同一入力・seed 42では、Stage 1の目的値`703,389.366847円`、BEV/ICE使用台数`14/18`、BEV/ICE担当便数`46/218`を変えず、認証gapを`9.011988%`から`4.827341%`へ縮小した。
- 上記のStage 1実行時間は`23.702秒`から`38.511秒`へ増加した。gapは縮小したが0ではないため、`assignment_global_optimality=false`および`full_network_global_optimality=false`を維持する。過去の`0.10`設定を再現する場合は`--mip-gap 0.10`を明示する。
- 晴天の10便day-spanning subset、各車種最大5台、15分刻み、seed 42、終端SOC=`return_to_initial`、会計費用項目だけを目的関数に含める条件で、小規模統合MILPを厳密に照合した。成果物は`output/small_integrated_sunny_formal_oracle_20260721/audit.json`である。
- Phase 3二段階と統合MILPはともにBEV 2台で10/10便を担当し、会計費用はともに`40,000円`だった。統合MILPはraw objective=`40,000円`、accounting residual=`0円`、gap=`0`、全hard validation通過、終端エネルギー均衡済みで、`integrated_exact_oracle_eligible=true`となった。二段階と統合の費用差、車種別使用台数差、車種別担当便数差はいずれも0である。

### verified call chainと修正した穴

- 正式Stage 1: `run_research_phase3_frontend_weather.py` → `OptimizationEngine.solve()` → `GurobiMILPAdapter._solve_thesis_two_stage()` → full candidate network Stage 1 MILP。時刻表、`operator_id`、および`arrival + turnaround + deadhead <= next departure`は変更していない。
- 小規模照合: `audit_small_integrated_weather_milp.py` → 同じ`ProblemBuilder`入力 → Phase 3二段階および`phase4_integrated`のGurobi経路。fallback、postsolve repair、未配車許容は使用していない。
- 統合MILPに、Phase 3 Stage 2と同じ開始前の車庫充電窓、選択接続arcにより確認される運行間車庫滞在充電窓、出庫・接続回送中の充電禁止、出庫回送エネルギーのSOC遷移および出発時必要SOCを追加した。
- 会計外の`opportunistic_topup_deficit_penalty`が共通cost-component契約に未登録で、監査設定で無効化しても正規化時に捨てられる問題を修正した。小規模費用オラクルではこの項を含む運用上のsoft preferenceを明示的に除外する。
- 最小SOCだけの終端条件では初期電池在庫を一日で取り崩せて事後会計との残差が生じるため、小規模費用照合は代表日境界`return_to_initial`に固定した。これは照合条件の変更であり、本番weather scenarioを暗黙に書き換えるものではない。
- 監査JSONに統合MILPの厳密性、gap、全便配車、hard validation、終端エネルギー均衡、objective-accounting一致をまとめたfail-closed gateと、二段階対統合の費用・台数・担当車種差を追加した。
- `python -m compileall -q src scripts tests`と自動回帰`python -m pytest tests -q`を実行し、`786 passed`を確認した。リポジトリ直下の手動BFF試験`test_multiday_phase1.py`は、この仮想環境に`requests`がないため収集対象外とした。

### 限界と次の穴

- 小規模統合MILPとの一致は上記10便subsetに限る。264便全体の統合最適性、他subset、雨天、複数seedへの一般化は未証明である。
- Stage 1の4.827341%は改善後の上界・下界差であり、厳密最適解ではない。次段階では同じfull networkを保ったまま下界またはincumbentをさらに改善し、複数seed・計算時間感度へ進む。
- 今回はユーザー指示どおり道路距離を変更していない。距離入力・時刻表・運行事業者契約の比較可能性は維持した。
- 旧`small_integrated_*`成果物には、会計外SOC top-up penalty、終端在庫評価、またはPhase 3と異なる充電可能窓が混在するものがある。正式な小規模オラクルとして使用するのは`small_integrated_sunny_formal_oracle_20260721/audit.json`のみとする。

## 2026-07-21 最終全ネットワーク実行と総合評価

### 実行条件（再現可能な正式成果物）

- 晴天: `771d115b-75b0-49f7-a7f0-25f259a2cd21`、`2025-08-05`、成果物 `output/research_phase3_sunny_full_network_final_20260721`。
- 雨天: `b23fd26c-1233-4c73-bb9e-bdb8b1584760`、`2025-08-10`、成果物 `output/research_phase3_rain_full_network_final_20260721`。
- 両ケースとも `full_network_milp`、全678,600接続候補、15分刻み、seed 42、総時間上限1,500秒、Stage 1/2各750秒の設定で実行した。固定仕業・候補網の削減・fallback・postsolve repair は用いていない。
- `summary.json` を標準JSONパーサで再読込し、供給便数、SOC、充電器、契約電力、最適性ラベルの一貫性を再監査した。

### 結果

| ケース | 供給便 | 使用車両 | EV/ICE供給便 | Stage 1 | Stage 2 | 会計費用 |
|---|---:|---:|---:|---|---|---:|
| 晴天 | 264/264 | 32 | 46 / 218 | objective limit、gap 9.012% | 厳密最適（gap 0） | 705,759.17円 |
| 雨天 | 264/264 | 32 | 46 / 218 | solver optimal、gap 4.754% | 厳密最適（gap 0） | 714,699.31円 |

- 晴天ではPV 614.709 kWh、grid import 0 kWh、雨天ではPV 101.114 kWh、grid import 429.814 kWh、peak grid 21.491 kW となった。雨天の費用差は 8,940.14円で、主に電力購入・需要料金・CO2料金の増分による。
- 両ケースで未割当・重複・車両時刻重複・接続不可能・EV/BESS SOC違反・契約電力違反・充電器同時使用違反は全て0件。

### 最適性主張の是正（P1を発見・修正）

- Gurobiの生の `OPTIMAL` 表示だけでは、正のMIP gapが残る設定で「厳密な大域最適」とは主張できない。`stage1_exact_optimality_certified` は status が `optimal` かつ gap が 1e-8 以下の場合だけ true とし、`assignment_global_optimality` も同じ条件と全候補網条件を満たす場合だけ true とした。
- Phase 3はStage 1の配車を固定してStage 2の充電を最適化する二段階構造であるため、統合総費用の大域最適性は常に false と明記する。今回の晴・雨の `assignment_global_optimality` と `full_network_global_optimality` はいずれも false である。
- solver adapter → MILP engine → weather runner → `summary.json` の証明情報中継を追加し、全テスト `784 passed` を確認した。

### 総合判断と残る穴

- この一組は「全ネットワークで実行可能な配車・充電計画」としては有効である。一方、晴雨でEV/ICEの担当比率は同じ 46/218 であり、単一日・単一seedの比較から気象に応じた車種配分効果を主張してはならない。
- 次の研究上の穴は、Stage 1の上界をさらに改善してgapを縮めること、単一小規模日における統合MILPとの照合、複数seed・時間上限・5分刻み・PV/電費不確実性の感度分析である。道路距離は現段階では stop-sequence haversine 由来であり、道路ネットワーク距離へ置換するまでは距離起因の精密な費用比較は限定的に解釈する。

## 2026-07-21 正式Stage 1の等価な冗長制約削減と晴雨実測

### 開発原則として銘記

- 根拠未確認の固定化、近似、proxy、最適性主張を正式モデルへ昇格させない。変更前に実行経路と数理的意味を確認し、変更後に同一入力で比較測定と回帰検証を行う。効果がない変更や退行した変更は採用しない。
- 今回は全264便、全接続候補、`timetable_rows`、`operator_id`、`arrival + turnaround + deadhead <= next departure` を一切変えず、同じMILPから論理的に含意される制約だけを除いた。

### Verified call chainと原因

- 正式runnerは `run_research_phase3_frontend_weather.py` → `OptimizationEngine.solve()` → `MILPOptimizer.solve()` → `GurobiMILPAdapter._solve_thesis_two_stage()` → 全候補 `enumerate_arc_pairs()` のStage 1 MILPを実行する。`stage1_strategy=full_network_milp`、successor pruning無効、fallback・postsolve repair無効を維持した。
- 67.86万本の接続変数それぞれに `x(v,i,j) <= y(v,i)` と `x(v,i,j) <= y(v,j)` を明示していた。しかし同じモデルの `sum(outgoing x) + end = y`、`sum(incoming x) + start = y` と非負変数条件から両不等式は自動的に成立する。このため1,357,200本の冗長制約を削除した。
- 研究policyは1車両につきstart/endを各1以下に制限する。さらに全arcが出発時刻について厳密に前進することを実行時検査できた場合、node-flowは各車両を高々1本の非巡回pathに限定する。この条件下では複数fragment用のdepot-reset pairwise cut、fragment occupancy、trip overlap cliqueも含意済みなので生成しない。開始・終了数が2以上、同時刻逆向きarc、trip欠損のいずれかがあれば従来制約を保持するfail-closed実装とした。

### 実測結果（seed 42、15分、Stage 1上限30秒）

- 晴 `771d115b-75b0-49f7-a7f0-25f259a2cd21`: Stage 1制約数1,348,331→70,871、準備42.15→27.25秒、求解30.38→22.91秒、solver-path全体76.81→54.17秒。264/264便、32台、BEV14/ICE18、Stage 2 optimal、独立validation全項目合格。Stage 1目的703,389.367円、解析下界640,000円、証明gap 9.012%、status `objective_limit`。成果物は `output/research_phase3_sunny_full_network_single_path_redundancy_v3_20260721`。
- 雨 `b23fd26c-1233-4c73-bb9e-bdb8b1584760`: 70,871制約、準備27.60秒、求解30.30秒、solver-path全体62.07秒。264/264便、32台、BEV14/ICE18、Stage 2 optimal、独立validation全項目合格。Stage 1目的711,315.462円、解析下界640,000円、証明gap 10.026%、status `time_limit`。成果物は `output/research_phase3_rain_full_network_single_path_redundancy_v3_20260721`。
- `assignment_global_optimality` は両ケースともfalseである。晴は指定10% gap以内を証明したが大域最適解ではなく、雨は10%を0.026 percentage point超えた。`full_network_global_optimality` は二段階法全体について常にfalseとし、Stage 1の最適性と総費用最適性を混同しない。
- Gurobi一括変数生成も同一条件で測定したが、準備27.25→31.18秒、solver-path全体54.17→58.04秒へ退行したため撤回した。比較成果物へ `NOT_ADOPTED.md` を付け、コードは元へ戻した。

### 残る穴

- 変数数は729,638のままであり、準備時間約27秒の主因である。次は全接続を保持した同値な定式化、または列生成・network flow分解を小規模統合MILPと照合してから導入する。
- 晴雨とも既存warm startのBEV14/ICE18から新しい割当incumbentを得ていない。今回改善したのはモデル規模とgap証明時間であり、気象別の車種割合最適化が完了したとは主張しない。
- 雨を10%以内へ入れるには、恣意的に許容gapを広げず、Stage 1下界強化または全ネットワーク上の有効なincumbent生成を行う。

## 2026-07-21 訂正: 固定32仕業方式の正式採用を撤回

### 誤りと確認した実行経路

- 「固定した32本の時刻表パス」という表現と、それを正式な最適化範囲として既定化した判断は誤りだった。32は入力時刻表やユーザー指定の制約ではない。
- verified call chain は `ProblemBuilder._build_baseline_plan()` → `_build_pooled_shared_baseline()` → `_minimum_cost_maximum_matching()` である。便間接続グラフの最大マッチングから初期chainを作り、そのchainを利用可能車両とエネルギー可否に応じて分割した結果が32仕業だった。これは canonical baseline、すなわち初期解生成ヒューリスティックの出力である。
- `exact_fixed_path` は、この初期解32仕業を不変にして車両だけを割り当てていた。したがって、便のつなぎ替えと使用車両数を同時に探索するStage 1の代替にはならず、今回求める配車最適化の正式解として扱えない。
- 接続グラフ自体は `ConnectionGraphBuilder` → `FeasibilityEngine.can_connect()` を通り、`arrival + turnaround + deadhead <= next departure` を保持する。今回の訂正でも `timetable_rows` と `operator_id` を変更していない。

### 撤回した実装と成果物

- `build_exact_cost_aware_assignment()` とrunnerの `exact_fixed_path` 選択肢を削除した。正式runnerの既定値は `full_network_milp` に戻した。
- `fast_fixed_path` は比較・診断用の明示的opt-inとしてのみ残す。これは baseline chainを固定するheuristicであり、`assignment_global_optimality=false` のままである。正式なStage 1最適化結果には使用しない。
- 晴・雨の `output/research_phase3_*_exact_fixed_path_v2_20260721` は、固定32仕業内の診断結果にすぎず、正式な配車最適化結果として撤回する。各ディレクトリへ `WITHDRAWN.md` を追加し、元データは監査用に改変せず保存する。
- 固定割当の充電/SOC MILPがexactであることは、固定済み割当に対するエネルギー運用だけを指す。配車割当や会計総費用の大域最適性を意味しない。

### 検証と次の方針

- 回帰テストでは正式runnerの既定値が `full_network_milp` であることを固定する。
- 計算時間短縮は、32仕業を固定する方法ではなく、全便接続を最適化対象に残したまま、妥当な下界、変数削減、対称性除去、warm start、停止条件を改善して行う。
- Stage 1がtime limitで `assignment_global_optimality=false` の場合は、その事実とgapをそのまま報告する。速さのために探索空間を黙って別問題へ置き換えない。

## 2026-07-21 高速・費用対応の固定便列割当と晴雨再計算

### 今回つぶした問題

- 264便の正式経路は、Stage 1だけで約67.9万本の接続候補と6,755本の時刻別SOC必要条件を持ち、60秒ではroot relaxationにも到達せず、既存baselineから割当が動かなかった。晴雨ともBEV14台・46便、ICE18台・218便のままなのは、EVが高いからではなく、時間内に新しいincumbentを得られていない退行だった。
- baseline path coverの車両選択は、費用より先に「便列全体を無充電で走れる長さ」を優先してICEを選ぶため、走行単価の安いBEVが短い便列に偏っていた。一方、単純に長距離便列をBEVへ割り当てると、日中PVを受けられず系統充電と需要料金が増えた。EVの走行単価だけでなく、便列の時刻、PV利用可能量、充電可能時間、需要料金を候補生成へ入れる必要があった。
- 固定割当の`phase1_charging_only`はGurobiで完全な充電・PV・BESS・SOCモデルを解いていたが、割当arcのpruning監査を流用したため`supports_exact_milp=false`になり、研究受入ゲートに誤拒否されていた。固定割当Phase 1には割当arc探索がないため、Gurobi経路では「固定割当に対する充電問題がexact」であることを明示した。これは配車割当の大域最適性を意味しない。

### 最小修正

- `src/optimization/common/fast_cost_assignment.py`を追加した。canonical baselineが作った時刻表便列を一切分割・並べ替えず、利用可能な実車へだけ再割当する。全便の正距離、車種許可、実車availability、初期SOC、電費・燃費、電力・軽油・CO2、固定費、PVの時刻別利用可能性、日内充電可能時間、需要料金proxyを検査する。ゼロ又は欠損距離は停止し、補完しない。
- `scripts/run_research_phase3_frontend_weather.py`へ`--stage1-strategy fast_fixed_path`を追加した。最初に既存baselineを再検証し、そこからBEV台数を1台ずつ増やした候補を評価する。各候補はcanonical `phase1_charging_only` Gurobiで、全264便、接続、EV SOC上下限・終端SOC、10口の充電器競合、PV/BESS/grid収支、BESS終端、契約電力を検証する。fallback、postsolve repair、未配車、複数fragment、Stage 2非optimalの候補は採用しない。
- 候補選択は検証後の`total_cost`で行う。割当は高速heuristicであり、固定割当ごとの充電問題だけがoptimalである。`assignment_global_optimality=false`、`research_cost_optimality_eligible=false`を成果物へ残し、大規模総費用最適解とは呼ばない。
- 既定の正式`full_network_milp`経路は変更していない。`timetable_rows`、`operator_id`、`arrival + turnaround + deadhead <= next departure`も変更していない。

### 全候補照合結果（seed 42、15分、return-to-initial）

- 晴天scenario `771d115b-75b0-49f7-a7f0-25f259a2cd21`: baseline 705,759.17円（BEV14台・46便）に対し、最良候補は702,422.85円、BEV29台・250便、ICE3台・14便。PV 614.709 kWh、grid 2,575.7 kWh。全独立validationは0違反、Stage 2 optimal、研究feasibility gate通過。候補探索約51秒、入力構築込み約63秒。
- 雨天scenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`: baseline 714,699.31円（BEV14台・46便）に対し、最良の受理候補は712,679.86円、BEV27台・232便、ICE5台・32便。PV 101.114 kWh、grid 2,823.6 kWh。BEV28・29台候補は見かけの会計費用が低くても充電/SOC MILPがinfeasibleのため拒否した。全独立validationは0違反、Stage 2 optimal、研究feasibility gate通過。候補探索約50秒、入力構築込み約61秒。
- 晴天29台対雨天27台、BEV担当250便対232便となり、晴雨の車種担当割合が再び変化した。これはPV量と充電可能時刻を候補生成へ反映し、各候補を実費で比較した結果である。ただし固定便列を変えない近傍探索なので、全接続ネットワーク上の大域総費用最適性は未証明である。
- 成果物は`output/research_phase3_sunny_fast_complete_20260721`と`output/research_phase3_rain_fast_complete_20260721`。詳細候補、不採用理由、費用内訳は各`fast_assignment_audit.json`に保存した。
- 回帰テストは`python -m pytest -q tests`で777件すべて通過した。リポジトリ直下の手動用`test_multiday_phase1.py`は任意依存`requests`が`.venv`にないためroot全収集では停止するが、正規`tests/`の失敗ではない。

### 指定された外部実装との照合

- [UCDavis-EVResearchCenter-Bus-Scheduling](https://github.com/radhika2026/UCDavis-EVResearchCenter-Bus-Scheduling)の「割当・設備・エネルギーを分解して解く」構成を参考にした。ただし同実装のcolumn generationはdual閾値で既存変数をfixする簡略デモで、pricing subproblemを持つ厳密な列生成ではない。コード移植や「列生成済み」という主張はしていない。
- [Electric-Bus-Depot-Charging-Simulation](https://github.com/pulkitgarg3/Electric-Bus-Depot-Charging-Simulation)の充電器飽和、待ち時間、設備台数のシナリオ比較は、今後の充電器台数・Monte Carlo感度の参考にする。現段階の厳密な時刻表配車・SOC制約の代替にはしていない。
- [CentralPointEvacuateRouteOptimizer](https://github.com/ReedGAOOO/CentralPointEvacuateRouteOptimizer-use_GMM_pre-devide_angle_partition)のOSMnx/NetworkX道路網利用は道路距離化の参考になる。一方、GMM角度分割とGA-TSPは中心点避難路向けで、固定時刻表の便接続には適用しない。

### 残る最大の穴

1. 現在の264便距離は停留所緯度経度を使った隣接停留所間Haversine折線であり、道路ネットワーク距離ではない。sourceも`trip_stop_sequence_polyline_haversine`、semanticsも`adjacent_stop_haversine_polyline_not_road_network_distance`のままである。次はGTFS shapeを第一候補、OSM/道路routingを第二候補としてroute/trip距離を置換し、現行代理との差と到達不能区間を監査する。ゼロ距離は引き続き拒否する。
2. 固定path cover heuristicと正式full-network Stage 1の下界は別物である。小規模統合MILPとの照合、複数seed、時間上限感度、5分間隔の小規模感度、PV・電費の不確実性は継続する。
3. `05:00/23:00`を便の切出し条件には使わず、配車はscope済み時刻表全件を使う方針を維持する。ただし内部energy horizonはPV/BESS/TOU/需要料金/終端SOCを閉じるため必要であり、単純削除しない。通常UIの恣意的な開始終了入力を廃止し、service windowとenergy horizonを自動導出する契約の完全移行は引き続き未完了である。

## 2026-07-21 Stage 1下界・小規模統合MILP・道路距離代理・晴雨退行監査

### 確認した実行経路と研究上の前提

- 正式な晴雨runは、保存済みscenarioとprepared inputを読み、`materialize_scenario_from_prepared_input()`、weather policy、`ProblemBuilder`、`OptimizationEngine`、Gurobi Phase 3 Stage 1/2の順に通る。fallbackとpostsolve repairは許可していない。
- Slackの指導教員 @Chiyori T. Urabe との会話から、BESS日末エネルギー差、grid/PV/bus/BESSの全収支、PV→BESS、EV/BESS上下限、EV初期SOC、PV抑制、充電時間・90/50 kW上限、充電器台数、車両台数費用、晴雨比較、晴天時のEV35台利用有無を監査項目として再確認した。
- ローカルの先行文献レビューで整理済みの「15分離散化、充電器競合、EV/BESS終端SOC、PV/BESS/grid/curtailment同時収支、二段階法と統合MILPの役割分離」を今回の判断基準に用いた。二段階法の会計費用を大規模な総費用最適値とは呼ばない。
- `timetable_rows`、`operator_id`、および `arrival + turnaround + deadhead <= next departure` は変更していない。

### Stage 1下界の強化

- strict coverage precheckの緩和最小パス被覆から、全264便に必要な車両日数の下界32台をStage 1の `sum(used_vehicle_day) >= 32` として追加した。従来は車両変数と車両日変数の逆向きlinkが不足していたため、`used_vehicle <= sum(used_vehicle_day)` もStage 1と小規模統合MILPへ追加した。
- 車両日利用費が20,000円/台、その他のStage 1目的係数が非負である場合、解析的目的下界 `32 * 20,000 = 640,000円` を証明できる。Gurobi自身の `ObjBound` と混同しないよう、`stage1_solver_best_bound` と `stage1_analytical_objective_lower_bound` を分離し、有効下界とgapを合成するようにした。
- 30秒晴天probeでは、目的703,389.367円、Gurobi下界未確定、解析下界640,000円、証明gap 9.012%となった。以前のgap 100%より監査可能になったが、全候補ネットワークの最適性は未証明である。

### 小規模統合MILPとの照合と修正したP1

- 18便の決定論的・日跨ぎ小規模scopeで、Phase 3、15分統合MILP、5分統合MILPを比較する `scripts/audit_small_integrated_weather_milp.py` を追加した。小規模結果を264便全体へ一般化しない警告を成果物に固定した。
- 統合MILPで、帰庫deadheadを誤ったtransitionへ載せていたこと、最終slot endのSOC上限・終端SOC評価が欠けていたこと、車両別実在初期SOCを一律80%で上書きしていたことをP1として検出・修正した。修正後は独立validationのEV/BESS SOC、時刻、充電器、契約電力をすべて通過した。
- 全回帰テストで、車両レコードがない小規模caseの `initial_soc_percent` と `final_soc_floor_percent` が生成車両へ反映されず、常に100%初期SOC・10%下限になっていたP1を追加で検出した。生成車両にも指定率を適用し、80%/20%指定なら300 kWh車で240/60 kWhとなるよう修正した。保存済み実車inventoryを使う正式晴雨runのSOC値は変更しない。
- 60秒比較では、Phase 3 15分は5 BEV・18便すべてBEV・会計費用100,843.432円でoptimal。統合15分はBEV 5便/ICE 13便・会計費用144,538.535円・gap 5.111%。統合5分は同じBEV 5便/ICE 13便・144,791.719円・gap 6.574%。統合15分/5分は60秒では最適性未証明で、目的関数もPhase 3会計費用と同一ではないため、単純な最良下界比較はしない。
- seed 17/42/73、計算時間5/15/60秒では、Phase 3の割当は全ケース5 BEV・18 BEV便でoptimalだったが、選ばれる車両IDにより会計費用が100,843.432～101,850.034円と約1,006.6円変動した。これはPhase 3 Stage 1が最終会計費用を直接最適化しておらず、同価割当があることを示す。
- PV倍率0.8/1.0/1.2、BEV電費倍率0.9/1.0/1.1の9ケースは全件実行可能・Phase 3 optimalだった。費用は100,843～102,546円の範囲で一部非単調であり、現段階では因果効果推定ではなく退行検知用の感度と扱う。
- 成果物は `output/small_integrated_sunny_complete_20260721/audit.json`。

### 停留所緯度経度を用いた距離入力

- `data/built/tokyu_full/stops.parquet` と `stop_times.parquet` の停留所緯度経度・便別停車順序をprepared input生成へ接続した。全264便・77停留所で座標欠損はなく、隣接停留所間Haversine距離の総和を採用した。
- 新prepared inputは晴天 `prepared-cd884f1f3c16855d-e6406a7fd75ec751-0ec9cc15`、雨天 `prepared-3ed40c5d57fd5f91-0b337aa1f091e729-0ec9cc15`。距離は最小2.743 km、最大9.377 km、総計2,136.737 km、ゼロ距離0件。
- これは直線OD距離より路線形状を反映するが、道路ネットワーク距離ではない。sourceは `trip_stop_sequence_polyline_haversine`、semanticsは `adjacent_stop_haversine_polyline_not_road_network_distance` と明示した。GTFS shape、道路ネットワーク、実績走行距離による置換が次のP2である。

### 最新の全264便・晴雨比較と退行原因

- 晴天scenario `771d115b-75b0-49f7-a7f0-25f259a2cd21`：BEV14台・46便、ICE18台・218便、Stage 1目的703,389.367円、解析下界640,000円、gap 9.012%、会計費用705,759.174円。PV 614.709 kWh、grid import 0 kWh、peak 0 kW。
- 雨天scenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`：BEV14台・46便、ICE18台・218便、Stage 1目的711,315.462円、解析下界640,000円、gap 10.026%、会計費用714,699.315円。PV 101.114 kWh、grid import 429.814 kWh、peak 21.491 kW。
- 両runとも264/264便、Stage 2 optimal、EV/BESS終端SOC、時刻遷移、充電器同時使用、契約電力、全エネルギー収支の違反0。成果物は `output/research_phase3_sunny_multifidelity_20260721` と `output/research_phase3_rain_lb_probe_20260721`。
- 天候入力はPV・系統購入・ピーク・Stage 1目的へ正しく伝播している。しかし60秒Stage 1では両天候が共通のbaseline incumbentから動かず、BEV/ICE配車構成が同じである。数日前の60分・後継8・約750秒runで晴天141 BEV便、雨天119 BEV便となった差が今回消えた原因は、15分化でSOC必要条件が875本から6,755本へ増え、全枝67.86万の根緩和と探索が時間制限内に進まないためである。前回結果も枝制限付きheuristicであり、今回より正しい最適解だったとは断定しない。
- 候補段階だけ時系列SOC必要条件を省略し、最終Stage 1で全枝・全6,755条件を復元する多忠実度warm startも試した。120秒ではbaselineを改善できなかった。最終モデルは弱めていないが、これだけでは退行解消にならなかった。

### 次に塞ぐ穴（優先順）

1. Stage 1を車両個体の巨大対称MILPから、車種別path/column生成または対称性を除いたnetwork flow masterへ分解し、天候別の配車incumbentを短時間で生成する。解析下界と全モデルvalidationは維持する。
2. 過去の天候別実行可能解を現行距離・15分SOC条件で再検証してwarm startへ再利用し、同一時間予算での改善量を測る。旧解を最終結果として無条件採用しない。
3. GTFS shapeまたは道路routingで隣接停留所間距離を道路距離へ置換し、現行停留所折線代理との差をroute/trip別に監査する。ゼロ・欠損距離は引き続き拒否する。
4. 小規模統合MILPの目的関数と二段階会計費用の項目を揃えた条件を追加し、15分/5分を最適性gapが十分小さくなるまで解いて離散化誤差を評価する。
5. 全264便で複数seed・計算時間感度を実施する。小規模PV・電費感度を、複数実日または分布シナリオへ拡張し、robust/stochastic主張に必要な標本数と評価指標を事前定義する。

現段階のモデルは、実行可能性とエネルギー会計の穴は大きく縮小したが、大規模Stage 1の総費用最適性と天候別配車の探索性能は未解決である。「完璧なモデル」「晴雨の大域最適解」とは表現しない。

## 2026-04-22 時刻表駆動・15分フルケース晴雨再計算と会計監査

- 実行経路を再確認した。frontend/BFF の正式経路は、保存scenarioとprepared inputをmaterializeし、`ProblemBuilder.build_from_scenario()`、`OptimizationEngine.solve()`、Phase 3 Stage 1 Gurobi割当、固定割当のStage 2 Gurobi充電・PV・BESSへ進む。研究runnerも同じcanonical stackを使用し、fallbackとpostsolve repairを禁止する。
- 固定の`05:00`/`23:00`を運行便の切出し条件にする設計は採用しない。運行範囲はscope済み`timetable_rows`から導き、今回の264便では05:51発から23:24着までを全件保持する。電力評価範囲は別に24時間・15分96枠として保持する。これにより23:00以降の便を落とさず、PV/BESS/TOU/需要料金/終端SOCの日次収支を閉じる。
- `OptimizationScenario`へ明示的な`horizon_duration_min`を追加し、`planning_horizon_hours`をclock表記差ではなく実slot数×timestepから決めるようにした。`ProblemBuilder`は時刻表範囲と電力範囲を別metadataとして保存する。`timetable_rows`、`operator_id`、接続条件`arrival + turnaround + deadhead <= next departure`は変更していない。
- 研究runnerは主実験を15分へ固定し、`milp_max_successors_per_trip=0`（全実行可能後続）を明示する。距離は全264便について正値を要求し、非正距離が1件でもあれば停止する。今回の最小距離は2.241 km、最大10.935 km、sourceは全件`trip.haversine_distance`だった。
- 晴雨の比較指紋からservice-dateというラベルだけを除外し、実際の運行入力が同じならtrip hashが一致するschema v2へ更新した。今回の晴雨はtrip hashとvehicle hashが完全一致し、意図した天候/PV入力だけが異なる。

### 自己検出して修正した穴

- P1: 厳密なsolver電源フローで`grid_to_bus={}`が「系統0」を意味するのに、会計層が充電slotから系統量を再導出していた。さらに`pv:<depot>`をPVとして認識しないため、晴天のPV直給262.046 kWhを系統購入として重複計上していた。`source_provenance_exact=true`なら空mappingをゼロとして尊重し、PV sourceを明示認識するよう修正した。旧晴天会計は電力量料金・需要料金・系統CO2を合計8,193.462円過大計上していた。
- P1: 独立エネルギー監査が再構成時に研究runnerの15分設定を再適用せず、60分PV profileを96枠へ誤対応させていた。監査再構成にも記録済みtimestepとBEV終端policyを適用し、晴雨ともPV・bus source・BESSの最大残差を約`10^-14 kWh`まで低下させた。
- P1: 晴雨比較器が旧仕様の`research_cost_kpi_eligible=false`を要求し、現在の「検証済み会計KPI=true、総費用最適性=false」という分離と矛盾していた。`research_accounting_cost_eligible=true`と`research_cost_optimality_eligible=false`を個別に要求する契約へ更新した。
- 環境: project `.venv`に`gurobipy`がなく正式runが開始前停止した。Gurobi 13.0.1を同環境へ導入し、academic license（2027-07-20まで）と最小モデルのoptimal statusを確認した。fallbackには切り替えていない。

### 指導教員Slackと先行文献を反映した受入条件

- Slack DM（@Chiyori T. Urabe、2026-06-11〜2026-07-16）から、BESS日末SOC差0、PV→BESS、BESS上下限、EV初期/終端SOC、PV抑制、grid/PV/BESS時系列、充電時間とkW上限、充電器台数、燃料量と運行の一致、車両台数費用、晴雨比較を受入条件として再確認した。
- `先行文献/`のNo. 42、61〜64、日本語EVバス充電需要・PV低炭素化・MPC逐次充電の論文、および`docs/reviews/literature_model_gap_review_20260719.md`を照合した。主実験15分、明示的charger competition、BEV/BESS終端SOC、PV/BESS/grid/curtailment同時収支、実フロー会計は整合する。一方、現在の一方向二段階法はフィードバック分解や統合MILPではないため、大域総費用最適解とは呼ばない。

### 修正版の実行結果

- 共通条件: 264便、BEV 35台+ICE 25台、15分96枠、後続枝刈りなし、90 kW×5口+50 kW×5口、BESS 600 kWh/300 kW、初期=終端300 kWh、grid→BESS禁止、PV→BESS許可、各BEV`return_to_initial`、Gurobi 13.0.1、seed 42、総上限1500秒。
- 晴天（scenario `771d115b-75b0-49f7-a7f0-25f259a2cd21`）: 264/264便、使用32台（BEV14、ICE18）、PV 614.709 kWh、系統0 kWh、peak 0 kW、総会計費712,853.642円。Stage 1はtime limit・gap 100%、Stage 2はoptimal。全必須validation 0違反、BEV/BESS終端SOC合格。
- 雨天（scenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`）: 264/264便、使用32台（BEV14、ICE18）、PV 101.114 kWh、系統480.466 kWh、peak 24.050 kW、総会計費722,848.015円。Stage 1はtime limit・gap 100%、Stage 2はoptimal（gap 0.00683%表示だがstatusはoptimal）。全必須validation 0違反、BEV/BESS終端SOC合格。
- 雨天−晴天: PV -513.595 kWh、系統購入 +480.466 kWh、peak +24.050 kW、検証済み会計費 +9,994.373円。これは同一構造入力から得た実行可能scheduleの会計差であり、大域最適値の差ではない。
- 成果物: `output/research_phase3_sunny_15min_full_20260422/summary.json`、`output/research_phase3_rain_15min_full_20260422/summary.json`、`output/research_phase3_weather_energy_audit_15min_full_20260422/weather_energy_balance_audit.json`、同`weather_energy_hourly.csv`、同`weather_energy_daily_summary.csv`。

### 検証と残課題

- `python -m pytest -q tests`は`768 passed`、`git diff --check`は合格。root直下を含む`pytest -q`はlegacy `test_multiday_phase1.py`の`requests`未導入でcollection停止するため、テスト環境依存の残課題として分離する。
- strict晴雨比較器は両runの`git_dirty=true`を正しく拒否した。既存のREADME/docs frontend変更を含む作業ツリーを勝手にcommitしないため、今回の成果は検証済みだが正式なclean-commit比較artifactではない。変更をレビュー・commit後、同一コマンドで再実行する。
- 最大の数理的残課題はStage 1 gap 100%である。全候補化により物理的な枝落としは解消したが、下界が弱く、大域割当最適性は証明できない。次は小規模統合MILPとの照合、Stage 1下界強化、Stage 2 infeasibility/cost feedback、複数seed・計算時間感度を実施する。
- 距離はHaversine推定であり、道路実測距離ではない。燃料・電費KPIの正式主張前にGTFS shape/道路ネットワーク/実績走行距離へ置換して感度を確認する。
- 不確実性は今回の晴雨2実現値比較に留まる。No. 62/64に対応するPV・消費電力のrobust/stochastic条件、rolling/fixed/oracle比較、5分小規模感度を今後実施する。


このファイルは、今後の編集内容をメイン直下で日時付き管理するための開発ノートです。

既存の研究実験ログは `docs/notes/DEVELOPMENT_NOTES.md` に残し、このファイルでは現在の編集判断、検証結果、残課題を短く追記します。

## 2026-04-22 時刻表駆動の運行範囲と電力ホライズンの再検討（今後やるべきこと）

- 前回の「開始・終了時刻を手入力せず、時刻表から自動導出する」という方向は維持する。ただし、再検討の結果、**運行範囲と電力評価ホライズンを同じ開始・終了時刻で表す設計は不十分**と判断した。配車は時刻表と回送・折返し条件で決まり、充電・PV・BESS・TOU・需要料金・終端SOCは別の評価時間軸を必要とする。削除対象は通常利用者向けの恣意的な`05:00`/`23:00`入力であり、内部ホライズンそのものではない。
- 現行canonical経路は、準備済みの正本`timetable_rows`を時刻で切り捨てず配車へ渡す一方、`ProblemBuilder`は`start_time`未指定時`05:00`、`end_time`未指定時`23:00`を使用する。また`planning_horizon_hours`、`horizon_start/end`から求める需要料金換算期間、設備又は終端SOC方針により24時間へ拡張される電力slot数が別々に決まる。確認済みの鶴巻prepared scopeでは152便が`05:58`出発から`23:14`到着まで存在し、設定上の`23:00`は最終便到着より前である。このため、現在は設定20時間、`05:00-23:00`から導く18時間、実際の24電力slotが混在し得る。
- 自分から上げた反対仮説は、「最初の出発から最後の到着までへ単純に縮めればよい」である。これは採用しない。始発前の営業所出庫回送・充電、最終便後の帰庫回送・充電、終端SOC回復を落とし、日ごとに需要料金換算期間と充電機会が変わって研究比較を歪めるためである。`25:00`等の日跨ぎ表記を時計時刻へ`mod 24`するだけでもサービス日を誤るため、導出は日付付き又はサービス日起点の絶対分で行う。

### 実装前に固定する契約

- `service_window`を「対象scopeの全便に、始発地点までの出庫回送と最終到着地から営業所までの帰庫回送を加えた実運行範囲」とする。便間接続は既存の`arrival + turnaround + deadhead <= next departure`を一切弱めず、`timetable_rows`と`operator_id`を再生成・欠落させない。
- `energy_horizon`を「充電・PV・BESS・TOU・需要料金・SOCを評価するslot範囲」として分離する。代表日1日runの既定は、`service_window`を包含するサービス日起点24時間とし、複数日は`planning_days * 24時間`を基本に、最終帰庫又は明示した終端SOC期限を包含できなければ停止又は明示拡張する。通常画面では自動導出値を読取表示し、研究用の明示overrideだけを詳細設定に残す。
- 電力slot数、PV/TOUの回転基準、需要料金のhorizon係数、BESS/EV終端時刻は、すべて同じ`energy_horizon`を参照する。`planning_horizon_hours`と`start_time/end_time`を独立した正本として併存させない。
- 出庫・帰庫回送の距離又は時間が欠損・ゼロで、同一地点であることも確認できない場合は自動導出を失敗させる。ゼロ回送を発明して範囲内と判定しない。全便・回送・SOCイベントの一部でもslot外へ出る場合は、現行のout-of-horizon補正へ黙って渡さずbuild-time contract errorにする。

### 今後の実装順

1. `ProblemBuilder`へ副作用のない時間軸導出器を追加し、scope済み時刻表を絶対サービス分へ正規化して`service_window`と`energy_horizon`を返す。導出根拠として最初便、最終便、出庫・帰庫回送、slot丸め、planning days、終端SOC方針をmetadataへ保存する。
2. canonical problemの公開契約を上記2軸へ分離し、料金slot、PV/BESS系列、SOC、rolling horizon、需要料金換算を`energy_horizon`へ統一する。legacy `start_time`、`end_time`、`planning_horizon_hours`は移行期間だけ入力互換として読み、矛盾時は優先順位で黙って上書きせずエラー又は警告付き変換にする。
3. BFF prepare結果とscenario hashへ導出値・導出元・policy versionを含める。通常UIの開始・終了手入力は「自動計算」の読取表示へ置き換え、最初便、最終帰庫、電力評価終了を別々に表示する。
4. 既存成果物との比較影響を監査する。配車割当が同じでも、旧runの需要料金係数、終業後充電、PV/BESS利用可能slotが変わる場合は費用KPIの直接比較を禁止し、新契約のclean固定input baselineを作り直す。README、モデル仕様、実験runbook、Development Notesを同じ変更で更新する。

### 必須テストと完了条件

- 最終便が`23:14`、`24:xx`、`25:xx`となるケース、始発前出庫回送、最終便後帰庫回送、日跨ぎ便、空時刻表、欠損回送、15/30/60分slot、1日/複数日、`minimum_only`/`return_to_initial`/`fixed_target`を回帰テストする。
- 全`ProblemTrip`、出庫・便間・帰庫回送、充放電、EV/BESS SOCイベントが`energy_horizon`内にあり、slot外エネルギーが0 kWhとして消えないことを独立検証する。
- `len(price_slots) * timestep`、PV/BESS系列長、`planning_horizon_hours`、需要料金換算期間が一致することを数値テストする。代表日1日なら原則24時間、複数日なら原則`24 * planning_days`時間である。
- 同一scope・同一seedで、変更前後の対象便集合、`operator_id`、時刻表時刻、接続可否が不変であることを確認する。費用差が出た場合は、旧設定不整合の修正によるものか、充電可能時間の変更によるものかを分解して記録する。
- この項目は現時点では**設計メモのみで未実装**である。受入完了までは、`05:00/23:00`を削除済み、又は時刻表駆動ホライズンが完成済みとは説明しない。

## 2026-07-20 BEV終端SOC・費用KPI・日次→毎時連鎖の修正

- 7月19日の不足点レビューを実装へ反映した。正式な代表日比較では、各BEVを一日の開始時と同じ蓄電量まで戻す`return_to_initial`を既定とし、最低残量だけ守る`minimum_only`は可行性診断専用として明示した。従来の明示的な終端目標は`fixed_target`として互換性を保つ。
- Stage 2の最終slot後まで含め、車両別の開始・終端・目標SOC、実測開始SOCからの減少量、固定した終端目標への不足量を監査出力する。費用は、当日に購入・供給したエネルギー費と、初期在庫を消費した分の評価額を分離する。Phase 3の可行スケジュールに対する会計値と、全体費用の大域最適性の主張も別のeligibilityへ分離した。
- 日次解から毎時見直しへ移る際、実測SOCで`return_to_initial`の基準まで下がるP1を修正した。BEVとBESSの一日開始時目標を固定してから実測状態だけを更新する。日次runnerは実際に使用した`effective_scenario.json`、共通trip/vehicle fingerprint、`input_audit.json`を保存し、毎時runnerは同じsnapshotとhashが一致しなければ停止する。
- dirty worktree・successor上限8・20秒の日次診断解は264/264便、Stage 2 optimal、独立違反0、EV終端目標不足`3.7e-13 kWh`だった。これを入力契約の動作確認にのみ使い、5:00から翌5:00まで24回の固定割当充電見直しを完走した。全24回で264/264便、Stage 2 optimal、終端目標不足の最大`3.98e-13 kWh`、各回のwall time最大2.35秒だった。候補削減とdirty条件のため修論の正式費用結果には採用しない。
- Gurobi runtime修正後の全回帰は`755 passed`。除外した`test_multiday_phase1.py`はlocalhost BFFを必要とする手動E2Eである。
- Gurobi本体を先にimportすると期限切れの別ライセンスを自動選択するP1も修正した。モジュール読込時と`ensure_gurobi()`の双方で、ライセンスとDLL探索先をGurobi importより先に構成する。
- 詳細な実行経路、修正理由、用語、検証範囲は`docs/notes/DEVELOPMENT_NOTES.md`の同日追補を正本とする。正式baselineはclean commit・候補削減なし・固定入力で再実行し、その後に同じ契約でPV予測誤差、晴雨、successor感度へ進む。

## 2026-07-19 最新run監査後のP0帳票修正

- `output/2026-07-19/run_20260719_1617`を監査し、全264便・fallbackなし・Stage 2 optimalまで進んだ一方、MIP gap 41.0807%を0.4108%と表示する単位誤り、目的値721,657.93円・営業費76,926.89円・会計総額830,717.20円の混在、BEV/ICE便数125/133と担当表127/137の不一致、使用車両32台と38車両日の不一致、BESS効率を無視した9.7577kWhの偽ERRORを確認した。
- 便数・使用車両数・車両日数は、1時間枠へ集約された車両台帳ではなく`graph/trip_assignment.csv`を正本として再集計する。これにより同一時間枠に複数便がある場合の便欠落と、分割された運用を別車両として数える問題を防いだ。SOC統計はBEVだけを対象とし、ICEのSOC=0を最小SOCへ混入させない。
- BESSのSOC遷移は`終了SOC = 開始SOC + 充電量×充電効率 − 放電量÷放電効率`で検証する。reporting finalizerが終了SOCを開始・終了の両方へ上書きしていた問題も修正し、`bess_timeseries.csv`の明示的な開始SOC・終了SOCを保持する。古い成果物に開始・終了列がない場合は単一SOCを表示互換のため保持するが、1枠内の遷移は復元できないため検証を`SKIPPED`と明示する。
- MIP gapはratioからpercentへ100倍変換して表示する。実験レポートは目的値と「会計総費用」を分離し、車両使用費を含む最終台帳値を表示する。電気代は系統購入費とPV・BESSの台帳費用を一度ずつ足し、需要料金も同じ会計台帳を参照する。`solver_objective_matches_accounting_total`は明示フラグがあり、かつ数値が一致した場合だけtrueとし、欠落時の既定値をfalseへ変更した。実験hashには運行日、天候条件、営業所エネルギー設備を含めた。
- 最新runを一時コピーして再集計した結果、会計総費用716,926.890円、目的値721,657.933円、BEV/ICE 127/137便、使用車両・車両日32、MIP gap目標10.000%・実績41.0807%、BESS遷移OK、validation error 0を確認した。元のrunは証拠保全のため変更していない。
- 帳票・会計・不可行gateを含む関連回帰は59件pass、全体回帰は`731 passed, 15 skipped`。残課題は、7月19日run自体が60分刻み・`research_run_accepted=false`・successor上限8・Stage 1 gap 41.08%・天候PV未適用・毎時再最適化未実行である点であり、今回の修正で研究採用可能になったとは扱わない。

## 2026-07-19 React + FastAPI移行 Phase 0 要件・UI/UX設計

- Tkinterを破壊・置換しない前提で、React + FastAPIを先行し、同等性確認後にTauri sidecar化する移行仕様を`docs/frontend/`へ追加した。今回の変更は文書のみで、`run_app.py`、`tools/scenario_backup_tk.py`、BFF、最適化コアは変更していない。
- 現行到達経路を確認し、API prefixは`/api`、OpenAPIは82 paths/108 operations、ジョブ状態は`pending/running/completed/failed`、キャンセルAPIなし、現ワークツリーに`frontend/`なしであることを現行仕様として固定した。
- 自己レビューで、汎用`Dict[str, Any]`応答によるOpenAPI型生成の見せかけの型安全性、canonical/legacy結果漏出、無効結果の0 KPI誤表示、scenario選択とactivateの混同、Tauri終了時のsolver強制停止を主要課題として起票した。typed BFF DTO、validity/KPI gate、明示activate、Tauri shutdown policyを各受入Gateへ組み込んだ。
- 成果物は要件、現行機能、API契約、実装/Tauriアーキテクチャ、画面遷移、UI/UX、受入基準、要件追跡、課題/ADR、baseline fixture計画で構成する。実シナリオのmutation fixture取得は、使い捨て複製の選定後に別タスクとして実施する。

## 2026-07-18 不足点の確認とPhase 3モデルの初回修正

- 画面からの実行経路をBFF→ProblemBuilder→OptimizationEngine→Gurobi Stage 1→Stage 2まで確認し、画面実行でStage 2診断保存先が渡らない問題、Stage 2の候補接続削減情報に関する未定義変数、Stage 1が同じ車両・同じ時間枠の充電を重複して見込む問題、実行可能解を厳密性不足だけで`NO_VALID_INCUMBENT`へ書き換える問題を修正した。
- Stage 1の充電候補は、選択された車両経路に対応する出庫前・営業所待機中・帰庫後だけに限定し、1台・1時間枠につき最大1回分とした。充電器全体の競合、受電上限、PV・BESS、実充電量はStage 2で確認する。運行接続条件、時刻表、`operator_id`、距離、Stage 2の物理制約は変更していない。
- 最初の重複防止案は264便・15分ケースで追加制約155,575件となったため不採用とし、経路に対応する充電候補へ集約して6,755件まで削減した。30秒診断は264/264便、Stage 2 optimal、独立検証違反0、表示`feasible`。ただし候補接続削減あり・dirty worktreeのため研究受理不可であり、正式結果には使わない。
- 対象回帰`85 passed`、全回帰`733 passed`。詳細、修正の意味、診断run、次の優先作業は`docs/notes/DEVELOPMENT_NOTES.md`の2026-07-18追補を正本とする。次はclean・固定inputの15分正式baseline、その後に24回の毎正時更新を完走する。
- 正式baseline runnerは候補接続上限`0`を「削減なし」として固定できるようにし、この値をexperiment hashへ含めた。最終planの会計を再評価して全費用項目の残差`1e-6円`以下を受理条件へ追加し、clean commit、264便、違反0、fallback/repairなし、候補削減0をまとめて確認する`verify_research_phase3_baseline.py`を追加した。固定prepared SHAは`5f133b1dddabd7295a5e60e429ad008d966c690e70e19c2bcb6327d288094913`である。
- コミット前レビューで、候補接続を削ったMILPにも`Exact core solver`・main benchmark対象と表示するP1を検出した。削減ありはappendix又は感度分析用、削減なしだけをfull-network main benchmark候補とするようmetadataを統一した。
- `core_new` commit`1b5deeb`、固定prepared SHA、15分、候補接続678,600本・削減0で正式baselineを実行した。264/264便、Stage 2 optimal、独立検証違反0、fallback/repairなし、clean worktreeを確認した。会計総額707,747.004円を最終planから再評価し、全16費用項目の最大残差0円だった。Stage 1はtime limit、gap 12.582%のため最適解とは呼ばない。検証器は全14項目passし、成果物は`output/research_phase3_grid_only_15min_formal_20260718_full_network`に保存した。

## 2026-07-17 不可行KPI gate・MILP厳密性表示・文献基準レビュー

- actual BFF経路`POST /scenarios/{scenario_id}/run-optimization`からcanonical solver、rich output、reporting finalizerまでを追跡した。2026-07-17の2 runはcanonicalで`infeasible`かつ未担当264便だった一方、旧`summary.json`/`kpi_summary.json`が未担当0便・総費用0円・会計一致trueを表示していた。
- canonical結果が検証済み可行でない場合、研究評価用の費用・電力フロー・CO₂・SOC集計を`null`へ無効化するgateをBFF保存前とreporting再構築後の双方へ追加した。canonicalの担当/未担当便数、`result_status`、`failure_stage`、`research_kpi_eligible=false`を同期し、生ledgerは原因診断用に変更しない。
- `site_power_balance.csv`等で`null`が`float(value or 0)`により0へ戻る二次漏れも修正した。backfill時の`results.xlsx`は評価セルを空欄化してstatus sheetを追加し、既存`experiment_report.md`にはINVALID警告を付ける。baseline fallbackを数値KPIとして期待していた回帰テストは、新契約（生ledger保持・公開KPI無効化）へ更新した。
- successor pruningで候補arcを削除したrunにも`supports_exact_milp=true`を返していたP1を修正した。`pruned_arc_count > 0`ならfalseとし、「縮約ネットワーク上のGurobi解」と「元候補網の大域厳密解」を区別する。
- 文献PDFの該当ページを直接確認し、No42の15分充電/競合、No55の15–60分平均ピーク需要料金、No16のPV・負荷予測誤差5/10/15/20% Monte Carloを評価軸にした。再生成スクリプトは`scripts/audit_core_new_review_20260717.py`、成果物は`output/core_new_review_20260717`、レビュー本文は`docs/reviews/core_new_strict_review_20260717.md`。
- 15分grid-only clean baselineは264/264便・Stage 2 optimal・違反0だがStage 1 gap 45.69%、60分晴雨PV/BESS runは264/264便だがdirtyかつgap 13.11/12.94%である。前者は物理可行性、後者は暫定的な機序確認としてのみ扱い、正式な15分晴雨費用比較とは呼ばない。
- 検証は`python -m pytest -q --ignore=test_multiday_phase1.py`で`730 passed`。変更対象Pythonファイルの`py_compile`、`git diff --check`、不可行run複製に対するJSON/CSV/Excel gate再構築を確認した。除外testはlocalhost BFFを必要とする手動E2Eである。

## 2026-07-16 BESS終端条件の整理と「日次計画→毎時充電再最適化」

- BESS終端条件を明示的な3方針へ分離した。`minimum_only`は通常SOC上下限と終端SOC下限だけをhard constraintとして守り、`return_to_initial`は終端を初期SOCへ一致、`fixed_target`は指定値へ一致させる。旧scenarioは、正の終端目標があれば`fixed_target`、なければ`minimum_only`として再現する。方針解決はcore共通関数へ集約し、builder、MILP、独立feasibility、会計・BFF出力が同じ意味を使う。Phase 3 Stage 2は従来から目標をhard制約としていたが、統合MILP側は偏差penaltyだけだったため、選択方針どおり目標±許容幅のhard制約へ修正した。この点は統合MILPの数学的意味を変えるため、旧Phase 4成果物との費用比較を無効にする一方、現行Phase 3成果物の比較条件は変えない。
- Tkフロントの営業所設備・充電インフラ画面と詳細設備画面の双方に終端方針を追加した。`minimum_only`選択時は古い目標値を0へクリアし、初期SOCへ戻す場合は初期SOCを監査可能な目標値として保存し、任意目標は終端下限〜SOC上限内だけを許可する。SOCの%入力を画面上の正本とし、kWh換算値は読取表示にした。
- 点在していた主要入口を画面上部の設定ハブ（営業所設備・BESS、車両・テンプレート、ソルバー・実験条件）へ集約し、営業所設備タブを主パラメータ群へ追加した。`DESIGN.md`に色、文字、余白、部品、導線、アクセシビリティ、研究入力の表示規則をdesign.md形式で記録し、`@google/design.md lint DESIGN.md`を通過した。
- 毎時再最適化結果から、次slot開始EV SOC、最終実行slot終了BESS SOC、実行済みslotのon/off-peak最大受電kWを抽出する状態引継ぎを追加した。欠損時に初期値へ戻さず停止する。CLIは`--end-time`で1時間ずつ連鎖し、各stepの状態と全体summaryを保存する。残り時間目的値は重複区間を含むため加算しない。
- 予測誤差実験用に、毎時のfull-horizon PV予測を`--pv-forecast-updates-json`で差し替える経路を追加した。営業所ID、slot数、非負kWhを検証し、profile hashと日量を各stepへ保存する。長時間solveはユーザーが手動実行する方針のため、この変更では1500秒run、24時間連鎖、予測誤差、複数日、seed感度を実行していない。実行コマンドと受理条件は`docs/notes/phase3_manual_validation_runbook_20260716.md`に固定した。
- 文献上、定置型蓄電池の終端SOCは一律に初期SOCへ戻す物理条件ではない。代表日を繰り返す研究では初期・終端を一致させる一方、終端を初期値の近傍に置く方法、終端SOCを翌日の初期SOCへ引き継ぐ逐次計画も確認した。現行晴雨比較の`300 kWh → 300 kWh`は、日間在庫を同条件にして費用比較するための**シナリオ境界条件**として説明する。
- 曖昧だったStage 1用語を実装・metadata・資料で改称した。`EV外部充電量の下界`は、便・回送・終端SOCに必要なエネルギーから初期EV SOCを引き、充電効率で割った「時刻・設備を無視した最低充電器入力」であり、実現充電計画ではない。`初期BESS余剰`は`max(初期BESS SOC − 終端要求SOC, 0) × 放電効率`であり、現行比較では`max(300−300,0)×0.95=0 kWh`である。PV控除も日量集約の費用代理であり、実際のPV→busフローではない。
- `OptimizationConfig`へStage別制限時間とrolling-horizon設定を追加した。1500秒指定の従来挙動はStage 1/2各750秒のまま保存し、明示指定時だけ段階別時間を変更する。120/30秒の短縮runは可行だがStage 1 gap 100%、晴雨ともBEV/ICE担当便54/210となり、天候差が消えたため研究比較には採用しない。
- `DayAheadHourlyOptimizer`と毎時再最適化CLI/BFF経路を追加した。最初にPhase 3の日次割当を一度求め、その割当を固定して、毎正時に実測EV SOC・BESS SOC・当日既発生ピークを初期状態として、当日末までの充電・PV・BESS・系統運用だけを再最適化し、先頭60分のみ実行する。運行割当、接続条件、時刻表は書き換えない。
- 保存済み日次解の再利用契約を厳格化した。BFFはscenario、prepared input、service/depot scopeの一致を必須とし、CLIは日次解と同じディレクトリの`input_audit.json`からservice date、trip hash、vehicle hashまで照合する。復元したduty、trip、vehicle、served/unserved集合の不整合、未知の実測EV/BESS IDは黙って無視せず停止する。canonical tripを再利用するため`operator_id`と時刻表由来属性は保持する。
- 自己レビューで、BFFの最初の毎時結果が`optimization_result`を上書きし、2回目に元の日次割当を参照できないP1を検出した。毎時結果へ検証済み`canonical_solver_result`とscenario/prepared scopeを引き継ぐよう修正し、同じ固定日次割当で2回連続更新できる回帰テストを追加した。
- 接続・回送検査まで含む契約確認後の5:00固定割当再最適化は晴天1.964秒、雨天2.021秒（Stage 2 solve 0.064/0.062秒）でoptimalとなり、終端300 kWh条件では1500秒runと同じ電力運用・費用を再現した。終端下限のみ120 kWhにした感度では晴天費用が3,934円低下したが、初期BESS在庫180 kWhを消費した差であり、翌日価値を入れない限り「経済性改善」とは扱わない。
- 5:00結果のslot 1開始EV SOC・BESS SOC・既発生需要ピークを6:00へ引き継ぐ試験で、最初はMILP optimalにもかかわらず独立SOC検証が過去slotを再計上し、2台を終端不足として誤拒否した。rolling検証は実測SOCの時点より前の便energy・完了済み回送を再控除せず、進行中便の残余部分と未完了回送だけを評価するよう修正した。再実行は晴天2.032秒、雨天2.006秒、Stage 2 optimal、264便、違反0、BESS終端300 kWhで可行となった。これで5:00→6:00の1回連鎖は両天候で確認済みだが、24回連鎖と予測誤差試験は未実施である。
- 詳細な文献対応、数式、実験結果、適用範囲は`docs/notes/phase3_literature_and_two_level_optimization_20260716.md`に記録した。残課題は、運行中の各時刻で実測状態を与える逐次検証、予測誤差ケース、複数日終端価値、正式なclean-worktree再計算である。
- 文献準拠の表現、日次／毎時の二階層、BESS終端方針、修正内容、計算・費用・設備条件を反映した教員向け18枚版を`docs/presentations/phase3_weather_energy_balance_progress_20260716_revised.pptx`へ保存した。全スライドにカンペを残し、overflow検査とテンプレート忠実度検査（issue 0）を通過した。
- 文献PDFの抽出テキストとページ画像は再生成可能な作業用成果物なので、誤コミット防止のため`.gitignore`へ`tmp/`を追加した。文献から採用した根拠は上記ノートへ出典付きで固定した。
- 最終自己レビューではP0=0、未解決P1=0。途中で検出したP1（毎時2回目の日次割当参照喪失、rolling独立SOC検証の過去energy再計上、統合MILPだけ終端目標がsoftだった不一致）は修正・回帰化した。`GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic`でcompileall、`python -m pytest -q --ignore=test_multiday_phase1.py`を実行し`717 passed, 8 skipped`、`git diff --check`、design.md lint、Tk実画面確認、PPT overflow、テンプレート忠実度issue 0を確認した。除外testはlocalhost BFFを要求する手動E2Eである。

## 2026-07-16 晴雨の電力需給・BESS・燃料監査と教員向けPPT

- `scripts/audit_phase3_weather_energy_balance.py`を追加し、最終1500秒runを再求解せず、保存済みscenario / prepared scopeを同じcanonical build経路で読み直してtrip/vehicle hashを照合した。24時間枠ごとにPV発電、PV→bus/BESS、出力抑制、grid→bus/BESS、BESS→bus、充電入力、BESS SOC開始/終了、EV/ICE運行台数、ICE燃料をCSV/JSONへ再集計する。さらにsolver実測時間、総/段階別制限時間、MIPGap、seed、TOU、需要料金、燃料・CO₂・車両使用単価、充電器、受電上限、PV/BESS、SOC方針、objective flags/weightsを`scenario_parameters`へ保存する。成果物は`C:\master-course\output\phase3_weather_energy_audit_20260716`。
- BESSは両日とも300kWhで開始・終了し、晴天の運用範囲は120–480kWh、雨天は226.950–322.025kWhである。PV式、充電源式、BESS遷移式の最大絶対残差は晴天`3.41e-12 kWh`、雨天`1.98e-12 kWh`で、監査許容値`1e-6 kWh`を満たした。系統→BESSは設定どおり両日0kWh。
- 晴天でもEV35台全数は使用せず、使用EV/ICEは16/16台（141/123便）、雨天は15/17台（119/145便）である。依頼文の在庫`EV35/ICE26`に対し実run入力は`EV35/ICE25`のため、26台条件はscenario修正と再計算なしに主張しない。
- ICE燃料を割当便の営業距離と便間回送距離から再計算した。晴天は`1162.675 + 124.500 km → 284.773 L → 42,715.982円`、雨天は`1404.047 + 134.400 km → 340.364 L → 51,054.642円`で、報告燃料費との差は`2e-10円`未満。ただし`fuel_cost_final_source=provisional_distance_based`かつ給油イベント0件なので、実現給油計画・燃料タンク可行性の証拠ではない。
- `scripts/build_phase3_energy_balance_presentation.py`を追加し、添付9月発表PPTの白地・濃青見出し・青罫線・大学マーク・Meiryo・結論帯を参照した18枚の進捗PPTを生成した。モデル修正一覧、二段階モデルの役割と外部充電量下界式、計算/設備条件、費用/環境条件の4枚を追加した。角丸カードと装飾的な矢印をやめ、表・数式・角形パネル中心へ変更した。全定量グラフで晴天/雨天を同時比較し、全18枚のnotes欄へ目標時間付きカンペを保存した。成果物は`docs/presentations/phase3_weather_energy_balance_progress_20260716.pptx`。
- PowerPoint自身で18/18枚を1600×900 PNGへrenderし、ロゴ、文字切れ、比較軸、凡例、モデル式、パラメータ表、BESS/PV/充電/系統/燃料/費用図、notes本文を確認した。Stage 1 gap約13%、未コミット変更を含む暫定結果、非global-optimumという既存の研究限界は全て資料内に残した。

## 2026-07-16 Stage 1天候費用代理・所在地SOC必要条件・晴雨1500秒run

- 根本原因は、Phase 3 Stage 1がICE燃料・CO₂・車両費だけで割当を決め、PV量と充電費用をStage 2にしか渡していなかったことです。営業所別に、便・始発/便間/帰庫回送・実効終端SOCから外部充電必要量を求め、PV（フロント設定0円/kWh）・初期BESS余剰・最安系統電力へ単価順に配分する集約費用下界をStage 1へ追加しました。充電時刻・充電器競合・契約電力・需要料金はStage 2の厳密検証に残し、代理費用を実現費用とは扱いません。
- 最初の晴天1500秒候補はBEV190便を選びましたが、Stage 2 IISによりStage 1が営業所外充電を発明していたことを検出しました。slot別所在地制約69,300本は探索性能を失ったため不採用とし、割当に裏付けられたhome-depot充電窓と始発/便間/帰庫loadを累積する必要条件875本へ圧縮しました。hard dispatch条件、SOC、充電器、契約電力、fallback/postsolve repair禁止は緩和していません。
- 同一モデル、Gurobi 13.0.1、1500秒、gap 0.1、seed 42で、晴天は使用BEV/ICE=16/16・BEV/ICE担当便=141/123、雨天は15/17・119/145となりました。晴天は雨天よりBEV担当が22便多く、ユーザー仮説どおりPV 0円の価値が割当に反映されました。全264便担当、Stage 2 optimal、SOC/充電器/契約電力/接続等の独立validation違反は両方0です。
- 会計総費用は晴天713,032.185円、雨天722,511.345円で、雨天が+9,479.160円（+1.329%）です。雨天の燃料費は+8,338.660円、需要料金は+992.032円、ピークは+24.801kWです。一方、BEV担当便が22便減ったため系統買電は雨天の方が14.916kWh少なく、PV減少だけを単純に買電増加へ読み替えられません。
- 成果物は`C:\master-course\output\research_phase3_sunny_final_1500s_20260716`と`C:\master-course\output\research_phase3_rain_final_1500s_20260716`、教員向け13枚PPTは`docs/presentations/phase3_weather_model_progress_20260716.pptx`です。両runはdirty worktree上のprovisional evidenceで、strict comparatorは`git_dirty=true`を正しく拒否しました。commit後のclean rerunが正式比較への残作業です。
- 最終回帰は`683 passed, 8 skipped`（localhost BFFを要求する手動E2E `test_multiday_phase1.py`は除外）で、compileall、PPTのPowerPoint render 13/13枚、`git diff --check`も確認しました。

## 2026-07-15 BEV/ICE構成感度と帰庫SOC境界修正

- 正規Phase 3 frontend-weather runnerへ`--available-bev-count`を追加し、永続在庫を変更せず、初期SOC上位のN台だけを当日利用可能とするreadiness感度ケースを実行可能にしました。選択ID・利用可能台数・車種別使用台数/担当便数を監査成果物へ保存します。
- 晴天・120秒探索で、利用可能BEV35台は使用BEV17/ICE15、利用可能BEV10台は使用BEV8/ICE24となり、全264便・全hard validation通過の異なる構成を確認しました。Stage 1 gapは100%/15.68%のため、費用最適性や構成優劣の結論には使用しません。
- 最初の感度probeが、帰庫回送energyを帰庫完了後slotのtransitionへ1slot遅く計上するP1を露出しました。slot-start SOC定義に合わせ、帰庫完了slotへ至る直前transitionで控除し、同slot充電が帰庫直後SOC下限割れを隠せないよう修正しました。
- focused regressionは`41 passed`、全回帰は`680 passed, 8 skipped`、compileallとgit diff checkも通過しました。詳細・実行artifact・研究上の限界は`docs/notes/DEVELOPMENT_NOTES.md`の2026-07-15項に記録しています。

## 2026-06-25 14:05:13 +09:00 SOC制約と天候ポリシー修正

- 対象は SOC 制約、天候運用ポリシー、BFF の weather policy 伝播、回帰テストです。
- 通常実行では SOC 下限・上限をハード制約として扱い、SOC 不足をコストで買う運用にはしません。
- `allow_soc_violation_slack` / `use_soft_soc_constraint` は診断用モードとして扱い、通常の研究結果主張には使いません。
- 天候ポリシーに `final_soc_target_tolerance_percent` を含め、終端 SOC 目標の許容幅として扱います。
- `bff/services/optimization_run/weather.py` で `final_soc_target_tolerance_percent` を `simulation_config` へ注入し、`weather_policy_audit.json` にも残すようにしました。
- 雨天 `conservative` は運行中の安全床を `30%`、終端目標を `60%`、終端許容幅を `15%` にしました。
- この設定の実効終端下限は `max(30%, 60% - 15%) = 45%` です。
- 45% は常時 SOC 床ではなく、雨天時の終端実効下限として説明します。
- これはモデルの数学的意味を変えるため、旧 weather policy run と新 run は同一条件として直接比較しません。
- `tests/optimization/test_weather_policy_problem_integration.py` に、BFF の事前注入、audit 出力、雨天 conservative の実効終端下限を確認する回帰テストを追加しました。
- 検証 `python -m pytest -q tests\optimization\test_weather_policy_problem_integration.py tests\test_problemdata_soc_overrides.py tests\test_post_return_soc_target.py` は `24 passed` でした。
- 検証 `python -m pytest -q tests\test_milp_baseline_fallbacks.py tests\test_problem_builder_cost_component_toggles.py tests\test_solution_validity.py` は `9 passed` でした。
- 残課題として、晴天・雨天比較では `BASELINE_FALLBACK`、`vehicle_usage_cost` 条件差、既存 accounting 期待値、Gurobi ライセンス、BFF 起動依存テストを分けて扱う必要があります。
- 残課題として、BESS 終端 SOC 関連差分を今回の SOC 修正と同一変更として扱うか、別変更として分離するか確認が必要です。

## 2026-06-25 15:36:26 +09:00 天候ポリシーのPV-only化

- 雨天 `conservative` の SOC floor / target / tolerance 指定は撤廃しました。
- 理由は、雨天の主要な最適化上の意味は PV 発電見込みの低下であり、SOC 余裕や EV/ICE 選択を天候ポリシーで別途誘導すると、PV・買電・燃料費・需要料金・SOC制約から最適化が判断するという研究説明と重複するためです。
- weather policy は SOC 下限、帰庫後 SOC 目標、SOC 目標許容幅、初期SOC、BEV/ICE soft bias を上書きしない設計へ変更しました。
- `solcast_pv_proxy_v1` / `solcast_typical_pv_proxy_v1` がある場合は、PV 発電見込みだけを canonical problem の PV 列へ渡し、EV/ICE 選択は目的関数と制約に委ねます。
- `bff/services/optimization_run/weather.py` から weather 由来の SOC / strategy bias の `simulation_config` 注入を削除しました。
- `src/preprocess/weather/operation_policy.py` は operation profile を監査用の中立 profile にし、`apply_weather_policy_to_problem()` で車両初期SOCや SOC metadata を変更しないようにしました。
- 旧 `apply_initial_soc_policy` helper と `src/preprocess/weather/__init__.py` の再exportを削除し、weather module から初期SOCランダム化経路をなくしました。
- `src/optimization/common/builder.py` の weather strategy metadata 自動追加を削除し、weather policy enabled だけでは vehicle type sorting / objective bias が変わらないようにしました。
- Tk の weather proxy 反映は SOC 入力欄を書き換えず、summary に `SOC方針=変更なし` と表示するようにしました。
- `schema/weather_operation_policy.schema.json` と `README.md` を PV-only 方針に更新しました。
- 検証 `python -m pytest -q tests\optimization\test_weather_policy_problem_integration.py tests\test_problemdata_soc_overrides.py tests\test_post_return_soc_target.py tests\test_scenario_backup_tk_dataset_options.py tests\preprocess\test_weather_daily_schema.py tests\preprocess\test_weather_proxy_builder.py tests\preprocess\test_solcast_pv_proxy.py tests\preprocess\test_solcast_typical.py` は `85 passed` でした。
- 検証 `python -m pytest -q tests\test_milp_baseline_fallbacks.py tests\test_problem_builder_cost_component_toggles.py tests\test_solution_validity.py` は `9 passed` でした。
- この変更により、以前の weather policy run に含まれていた SOC 余裕・初期SOCランダム化・天気戦略 bias とは比較条件が変わります。今後の晴雨比較は PV 見込み差を主因として説明します。

## 2026-06-26 11:59:16 +09:00 システム全体レビュー対応

厳しめレビューで指摘された全項目に対応しました。

- README: `mode_milp_only` の「厳密解」表記を `supports_exact_milp=true / fallback なし / gap 確認済みのときのみ exact` に修正しました。天気戦略 bias 行を削除し、weather policy は SOC/初期SOC/EV-ICE bias を変更しないと明記しました。Solcast typical の説明から strategy bias 言及を削除しました。
- `docs/constant/formulation.md`: 接続可能条件に turnaround を追加し `arrival + turnaround + deadhead <= next departure` に修正しました。これは `src/dispatch/feasibility.py` の hard constraint と一致します。
- `bff/routers/optimization.py` `_solution_validity_payload`: `gurobi_unavailable_baseline` など非標準 fallback status を包括的に検出するように改善しました。`solver_metadata` から `postsolve_soc_repair_applied` / `postsolve_charging_recomputed` / `fallback_applied` / `supports_exact_milp` を参照し、`exact_or_validated` と `validated_non_exact` を区別します。fallback 時は scenario status を `optimized_provisional` にし、job message に fallback 理由を含めます。
- `src/preprocess/weather/solcast_pv_proxy.py`: `capacity_factor_by_slot` を metadata に保存し、最適化の PV 列適用経路へ乗るようにしました。
- `src/preprocess/weather/operation_policy.py`: `_apply_typical_pv_curve_to_problem` を `_apply_pv_proxy_curve_to_problem` に一般化し、`solcast_pv_proxy_v1` と `solcast_typical_pv_proxy_v1` の両方でPV曲線を適用可能にしました。
- `src/optimization/accounting/validate_outputs.py`: `--strict` 時に必須 ledger（`vehicle_slot_ledger.csv`, `energy_flow_ledger.csv`）の欠損を fail にしました。`UNKNOWN_OPERATOR` または空の `operator_id` がある場合も strict 時は fail にします。
- `docs/constant/README.md`: 正本候補に警告ブロックを追加し、`agent.md` や `masters_thesis_simulation_spec_v2.md` は研究計画段階の文書であり現コード実行経路と完全に一致しないことを明記しました。
- `tests/test_solution_validity.py` に `gurobi_unavailable_baseline` の fallback 分類テストと postsolve repair 検知テストを追加しました。
- `tests/optimization/test_weather_policy_problem_integration.py` に `solcast_pv_proxy_v1` のPV曲線適用テストを追加しました。
- 検証 `python -m pytest -q [全11ファイル]` は `97 passed` でした。
## 2026-07-19 先行文献との照合による研究モデル不足点レビュー

- `先行文献/`内のPDF 23本と、現行研究概要、定式化、実装状況、正式15分baseline、2026-07-19結果を照合し、`docs/reviews/literature_model_gap_review_20260719.md`へ整理した。
- 正式15分baselineは264/264便、独立違反0、fallbackなし、候補接続削減0まで達成している一方、現行Phase 3はStage 1割当固定後にStage 2で充電を決める二階層計画であり、研究概要の「運行・充電・PV/BESSを一体で最適化」という説明とは一致しない。Stage 2の費用や設備情報をStage 1へ返す仕組みもない。
- 新たなP0として、正式baselineが32台のBEV初期残量8,038.4 kWhを一日で約3,668.6 kWh減らし、当日充電は32.3 kWh、最低終了SOCは10%で成立していることを確認した。この結果は一日可行性の証拠だが、翌日を含む日次運用費やPV効果の公平な比較には使わない。代表日比較では終了SOCを開始SOCへ戻すか、複数日引継ぎ又は翌日に残す電気の価値が必要である。
- 会計総額707,747.0円の電気関連費66,438.1円には、実買電32.3 kWh相当581.7円だけでなく、暫定走行費の残額65,856.4円が含まれる。出力も`objective_is_actual_cost=false`、`research_cost_kpi_eligible=false`であり、この金額を実際の一日費用や最適費用として使わない。
- 文献対応上の必須不足は、PV/BESSありの正式15分run、24回の毎時状態引継ぎ、固定日次計画・毎時見直し・完全予測の比較、PV誤差と走行電力±10%の感度、複数seed、設備感度、小規模同時最適化との比較である。V2G、配電潮流、GA/ABC/ALNS拡大は現時点の必須課題から外す。
- 次のモデル修正は、BEV終端SOCの公平化、実現フロー会計への統一、研究表現を「二階層運行・充電計画」へ統一、PV/BESSあり15分固定入力、24時間毎時見直しの順とする。今回の作業はレビューと開発メモ更新のみで、数理制約・既存実験結果・実行コードは変更していない。
# 2026-07-28 — Rolling report gate consistency

The frontend-equivalent Phase 3 finalizer now derives the human-readable
`experiment_report.md` research-submission flag from the existing
`summary.json` release gate as well as rolling acceptance.  A completed
24-step chain is an operational result; it cannot upgrade a run whose cost,
optimality, provenance, or comparison gates remain blocked.  A regression test
locks this distinction in place.

# 2026-07-28 — Frontend run artifact completeness gate

- The reference frontend output
  `output/2026-07-27/run_20260727_1800` contains 182 files, while the
  frontend-equivalent research CLI bundle used for the later diagnostic
  rerun contains only 85. The CLI bundle is not relabelled as the ordinary
  frontend reporting bundle.
- The reachable ordinary path remains
  `Tk -> POST /run-optimization -> day-ahead -> 24-step Rolling ->
  independent physical validation -> executed-day accounting -> canonical
  reporting`. Its finalization now enforces
  `frontend_run_artifacts_v1` and writes
  `artifact_completeness.json`.
- The contract verifies the expected root/raw/graph files, research input
  provenance, `results.xlsx` sheets, graph-manifest declarations, accepted
  executed-day accounting, physical validation, final cost reconciliation,
  and every Rolling step. `state_for_next_hour.json` is required for steps
  0–22; step 23 has no successor handoff and therefore does not invent one.
- Any required file that is missing, empty, malformed JSON, absent from
  `run_manifest.files`, or semantically rejected makes the frontend job fail
  while retaining the diagnostic directory. The job metadata and Tk monitor
  show `run_dir`, `artifact_completeness_status`, and verified/required counts.
- Saved runs can be rechecked without solving by running
  `python scripts/verify_frontend_run_artifacts.py <RUN_DIR>
  --research-run --require-rolling`. This verifier does not upgrade research
  acceptance or global optimality.
- Focused artifact, Rolling orchestration, canonical graph/report, accounting,
  and Tk payload tests: `88 passed`. Full `tests/` regression:
  `981 passed`. `compileall` and `git diff --check` also pass. A fresh
  264-trip ordinary frontend run remains intentionally pending for the user's
  manual execution.
