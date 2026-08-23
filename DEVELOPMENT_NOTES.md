# Development Notes

## 2026-08-23: Stage-1 coefficient-source diagnostic is read-only and fail-closed

- Fixed a P1 acceptance-boundary omission before the next root-LP observation:
  `stage1_root_lp_diagnostic_enabled` already created an auxiliary relaxation,
  but did not itself mark the BFF request diagnostic-only. It now does, with a
  BFF-worker regression that proves this flag alone sets `diagnostic_mode`.
  The auxiliary result therefore cannot be upgraded to research evidence.

- The separate root-LP clone no longer overrides the requested Gurobi thread
  count with one thread. It explicitly uses barrier (`Method=2`) with
  `Crossover=0` and persists method, crossover, and effective threads in the
  diagnostic artifact. This returns only a barrier interior solution when one
  is available; it is still diagnostic-only, is never used as a MIP start, and
  cannot alter Stage-1 rows, bounds, objective, or acceptance. The focused
  actual-Gurobi regression verifies both the fractional fixture and this
  persisted diagnostic-control contract. A returned Gurobi `SUBOPTIMAL`
  interior point is explicitly persisted as `suboptimal`, never as an opaque
  numeric status or an LP-optimality claim.

- Every returned root-LP diagnostic solution now also persists Gurobi's
  unscaled maximum bound/constraint violations and residuals, plus dual and
  complementarity quality metrics. These are descriptive quality evidence for
  the interior point, not acceptance thresholds and not an optimality
  certificate.

- The 264-trip Stage-1 telemetry reports a coefficient range of about
  `1.45e9`, above the explicit scaling-warning threshold, while its root bound
  remains unchanged. The new default-OFF
  `stage1_numeric_coefficient_diagnostic_enabled` flag scans the completed
  Gurobi linear matrix and exports the row/variable locations of the smallest
  nonzero coefficients (capped at 20 examples).
- The diagnostic performs no formulation or solver-control modification. The
  BFF marks an enabled request as `diagnostic_mode`, so its result cannot pass
  the research acceptance gate or be used for performance, cost, feasibility,
  or optimality conclusions. The replacement clean-`5969f6a` BFF execution at
  `output/2026-08-23/run_20260823_2354/` retained the SHA throughout the solve
  and persisted an identical scan in the canonical solver result and final
  `solver_settings.json`. It scanned 108,062 rows / 6,295,964 nonzeros in
  26.031 seconds and found all 20 minimum examples at approximately `1e-6` in
  `stage1_soc_relax_return_to_initial_upper__*` on `used_*`. This is the
  deliberate upper side of the return-to-initial scientific terminal-SOC
  band, not a free scaling constant. The artifact is diagnostic-only and
  remains excluded with a 19.227307% certified Stage-1 gap.
- The first clean diagnostic at `9af1129` is excluded: it correctly scanned
  108,062 rows and found the return-to-initial SOC relaxation coefficient, but
  a MILP-engine serialization omission left final `solver_settings.json`
  empty. The engine now explicitly forwards this field and an actual-Gurobi
  round-trip test verifies the handoff; the `5969f6a` rerun above closes that
  artifact-persistence defect only.
- The new `stage1_gurobi_scale_flag` records only Gurobi's internal
  row/column-scaling setting (`-1`, `0`, `1`, `2`, or `3`); default `-1`
  preserves existing behavior. A non-default BFF request is forced to
  diagnostic mode and the effective value is persisted with the other
  Stage-1 controls. The actual-Gurobi startup-deadhead fixture uses
  `ScaleFlag=2` and still passes the independent physical validator, but this
  is deliberately small-scope implementation parity. The completed frozen
  `4ae58fc` 264-trip pair uses the same prepared-input SHA-256, seed, threads,
  900/435/30-second limits, selected candidate hash, Rolling assignment hash,
  and executed-energy-flow hash. The normal `-1` control is
  `output/2026-08-24/run_20260824_0027/`; diagnostic-only `2` is
  `output/2026-08-24/run_20260824_0015/`. Both have the same displayed bound,
  incumbent, 19.227307% certified gap, final cost, physical acceptance, 24/24
  Rolling, accounting eligibility, and 240/240 artifact verification. Raw
  bound difference is below `1e-9` JPY and Stage-1 runtime differs by 0.005
  seconds, so this one pair supplies no gap/candidate/runtime benefit. No
  user-side row scaling or tolerance change is authorized.

## 2026-08-23: Charger-capacity candidate set is comparable but gap-blocked

- Frozen tag `economic-charger-capacity-dde40a1` completed the normal BFF
  6/8/10-port matrix at
  `output/thesis_economic_charger_capacity_dde40a1_20260823/`. All three
  cases retain the clean source SHA, prove their effective requested count,
  serve 264/264 trips, and pass input provenance, artifact hashes, physical
  validation, 24/24 Rolling, final accounting, and the snapshot-control gate.
- The normalized non-varied control hash is identical across the family. It
  removes only charger-derived compatibility IDs and depot count fields while
  retaining vehicle state/parameters, non-charger depot data, and the set of
  port specifications. This closes the prior provenance-definition defect.
- The manifest remains `BLOCKED` solely by `mip_gap_target_met`: each case has
  a 19.2273% certified Stage-1 gap. Their 64,422.491-JPY, 48-BEV/216-ICE,
  32-vehicle time-limit candidates are numerically the same, so they cannot
  establish a no-capacity-effect finding, an accepted cost response, or a
  capacity recommendation. The local BFF was stopped after finalization.

## 2026-08-23: Second charger-control audit isolates derived compatibility data

- The clean follow-up at `economic-charger-capacity-c775562` completed the
  6/8/10-port BFF trial in
  `output/thesis_economic_charger_capacity_c775562_20260823/`. Like the first
  attempt, all cases pass the individual provenance, coverage, physical,
  Rolling, accounting, and effective-count checks but miss the 1% Stage-1 gap
  target. It is excluded from comparison because the family manifest still
  finds different stable-control hashes.
- Artifact-level comparison showed that generated port count propagates beyond
  `charger_input_sha256`: it changes BEV `compatibleChargerIds`, depot
  `fastChargerCount`, and the fleet contract composed from those fields. The
  former patch was therefore necessary but insufficient.
- The new immutable-snapshot hash removes only charger IDs and count fields,
  while retaining vehicle parameters and initial state, non-charger depot
  fields, and the set of charger port specifications. A focused test proves
  that count/compatibility changes compare equal but a vehicle energy-rate
  change does not. Fresh execution from the next clean commit is required.

## 2026-08-23: Charger-capacity fingerprint defect found before comparison

- The normal BFF completed the 6/8/10-port trial at frozen tag
  `economic-charger-capacity-ff77ecd` in
  `output/thesis_economic_charger_capacity_ff77ecd_20260823/`. Every case
  passed request provenance, 264/264 coverage, physical validation, 24/24
  Rolling, final accounting, and the effective-count audit, but all missed the
  1% Stage-1 gap target.
- Finalization also found a separate provenance defect: the family-aware
  stable-control fingerprint retained `charger_input_sha256`, even though the
  generated charger inventory is deliberately varied by this family. The
  matrix correctly remained `BLOCKED`; this trial is excluded rather than
  interpreted as a charger-capacity comparison.
- The fingerprint now excludes only that declared hash for
  `charger_capacity_sensitivity`; a regression test proves it still detects a
  vehicle-input change. A new clean frozen commit and fresh BFF 6/8/10-port
  run are required before any charger result can be recorded.

## 2026-08-23: BESS on/off candidate-flow response is gap-blocked

- The normal BFF executed `BESS_ON` and `BESS_OFF` at frozen tag
  `economic-bess-response-75c228f` in
  `output/thesis_economic_bess_75c228f_20260823/`. The matrix has matching
  non-varied controls and clean source SHA; both 264-trip cases pass input
  provenance, artifact hashes, physical validation, 24/24 Rolling, final
  accounting, and the immutable-snapshot BESS state audit.
- It is `BLOCKED` only by `mip_gap_target_met`: BESS_ON has a 19.2273%
  certified Stage-1 gap and BESS_OFF has 26.8205%. The ON snapshot records
  `{"tsurumaki": true}` with 559.783-kWh PV-to-BESS, 505.204-kWh BESS-to-bus,
  zero grid import, 48 BEV / 216 ICE trips, and 64,422.491 JPY. OFF records
  `{"tsurumaki": false}`, zero BESS flow, 203.310-kWh grid import, 42 BEV /
  222 ICE trips, and 71,979.208 JPY.
- These differing time-limit incumbents demonstrate effective BESS state and
  candidate-flow provenance only. They are not an accepted BESS-cost,
  economic-dispatch, or optimality result; the local BFF was stopped after
  finalization.

## 2026-08-23: BESS on/off sensitivity is now fail-closed and auditable

- `scripts/build_thesis_experiment_matrix.py` now declares `BESS_ON` and
  `BESS_OFF`; `scripts/run_thesis_sensitivity_matrix.py` applies only the
  narrowly declared BESS enablement transformation to existing
  `depot_energy_assets`. `BESS_ON` requires an already enabled asset with
  positive energy and power, while `BESS_OFF` clears BESS capacity, state, and
  transfer controls without changing PV or any non-energy input.
- The result audit reads `scenario_input_snapshot.json` and records effective
  BESS enablement by depot. It rejects a case when the immutable snapshot does
  not prove the declared on/off state; the family-aware control fingerprint
  excludes only the deliberately varied energy-asset hash.
- Focused verification:
  `python -m pytest -q tests/test_thesis_experiment_matrix.py
  tests/test_thesis_sensitivity_matrix.py` -> `32 passed`; `git diff --check`
  passed. This implementation evidence preceded the subsequently recorded BFF
  pair above; its economic-response gate remains gap-blocked.

## 2026-08-23: Common vehicle-day cost reaches the ledger but is gap-blocked

- The normal BFF executed `VEHICLE_DAY_0` and `VEHICLE_DAY_20000` at frozen tag
  `economic-vehicle-day-d97d524` in
  `output/thesis_economic_vehicle_day_d97d524_20260823/`. Both cases retain
  the clean frozen SHA, matching non-varied controls, 264/264 trip coverage,
  physical validation, 24/24 Rolling, final accounting, and artifact hashes.
- The matrix is `BLOCKED` only by `mip_gap_target_met` (19.2273% and 1.7803%).
  The fixed-vehicle-day-cost semantics are research-eligible and the formula
  residual is zero: the 20,000-JPY case records 640,000 JPY for 32 used
  vehicles, increasing candidate total cost from 64,422.491 to 704,422.491
  JPY. Both candidates retain 32 used vehicles and 48 BEV / 216 ICE trips.
- This verifies the common per-used-vehicle-day cost coefficient and ledger,
  not BEV-specific or ICE-specific cost elasticity, behavioral response, or an
  optimal economic comparison. The local BFF was stopped after finalization.

## 2026-08-23: PV-supply response is a gap-blocked flow diagnostic

- The normal BFF executed `PV_0.00` and `PV_1.00` at frozen tag
  `economic-pv-response-3985f80` in
  `output/thesis_economic_pv_3985f80_20260823/`. Both cases retain the clean
  frozen SHA, have matching non-varied controls, and pass input provenance,
  264/264 trip coverage, physical validation, 24/24 Rolling, final accounting,
  and artifact-hash checks.
- The matrix is `BLOCKED` only by `mip_gap_target_met`: 0.00x has a 3.4915%
  certified Stage-1 gap and 1.00x a 19.2273% gap. The effective PV change is
  visible in candidate flows: 0.00x has 477.578-kWh grid import and no PV/BESS
  flow, whereas 1.00x has 996.2-kWh PV generation, 47.918-kWh direct PV use,
  559.783-kWh PV-to-BESS, 505.204-kWh BESS-to-bus, and zero grid import.
- Their 80,810.195- and 64,422.491-JPY time-limit candidate costs are not an
  optimal PV-cost comparison. This establishes the PV parameter and flow
  provenance only; the local BFF was stopped after finalization.

## 2026-08-23: BEV-trip-energy response is feasible-candidate evidence only

- The normal BFF executed `BEV_ENERGY_0.8`, `BEV_ENERGY_1.0`, and
  `BEV_ENERGY_1.2` at frozen tag `economic-bev-energy-c6dec42` in
  `output/thesis_economic_bev_energy_c6dec42_20260823/`. The three cases share
  the prepared-trip hash and non-varied control fingerprint; each source run
  retained the clean frozen SHA, served 264/264 trips, passed physical
  validation, accepted 24/24 Rolling steps, and reconciled final accounting.
- The matrix is `BLOCKED` only by `mip_gap_target_met`: its certified Stage-1
  gaps are 26.8493%, 19.2273%, and 14.0845% for 0.8x, 1.0x, and 1.2x. The 0.8x
  time-limit candidate uses 34 vehicles for 53 BEV / 211 ICE trips and costs
  63,983.495 JPY; the latter two use 32 vehicles for 48 BEV / 216 ICE trips and
  cost 64,422.491 JPY within numerical precision.
- The parameter reached the normal frontend/BFF path, but differing
  time-limited incumbents cannot establish a cost, behavioral, or optimal
  energy-consumption response. The local BFF was stopped after finalization.

## 2026-08-23: Electricity-price response is zero-import diagnostic only

- The current BFF 24/30/36-JPY/kWh matrix at frozen tag
  `economic-electricity-response-b7d4cd4` completed in
  `output/thesis_economic_electricity_b7d4cd4_20260823/`. The TOU tariff
  values are effective, all non-varied controls match, and every source run
  retains the clean frozen SHA.
- The manifest is `BLOCKED` only by `mip_gap_target_met`: each candidate is
  time-limited at a 19.2273% certified Stage-1 gap. All three candidate
  ledgers report 0.0-kWh grid import and 0-JPY grid cost, the same
  64,422.491318-JPY total (within numerical precision), 48 BEV / 216 ICE
  trips, and 32 used vehicles.
- This is not a no-price-effect result. It only shows that this fixed
  zero-grid-import candidate has no exposed grid-price term; the BFF was
  stopped after finalization and the matrix remains ineligible for a formal
  economic sensitivity conclusion.

## 2026-08-23: Diesel-price response is diagnostic and gap-blocked

- The normal current BFF path executed `DIESEL_PRICE_116`, `DIESEL_PRICE_145`,
  and `DIESEL_PRICE_174` at frozen tag `economic-diesel-response-4678e7d` in
  `output/thesis_economic_diesel_4678e7d_20260823/`. Each case freshly
  prepared the scenario, kept the non-varied control fingerprint identical,
  used seed 42, four threads, and explicit Stage 1=435 / Stage 2=30 seconds.
- The matrix status is `BLOCKED`: all three physical/accounting candidates are
  rejected only by `mip_gap_target_met` (19.2273% certified Stage-1 gap,
  time-limit), so none is an accepted sensitivity or an optimal economic
  response. The diagnostic 116/145/174-JPY/L total costs are 51,763.746 /
  64,422.491 / 77,081.237 JPY, with a constant 48 BEV / 216 ICE trip split,
  32 used vehicles, and 0.0-kWh grid import.
- This demonstrates that the diesel coefficient reached the reachable BFF
  model and ledger, but not a behavioral dispatch response: fuel cost changes
  mechanically with the price while the time-limited incumbent does not change
  assignment. The local BFF used for this run was stopped after finalization.

## 2026-08-23: Current 264-trip fixed-decision stress evaluation

- `output/diagnostics/fixed_solution_stress_ac8982d_20260823/` replays the
  clean-`ac8982d` discrete A/B source candidate in an SHA-matched detached
  worktree. The evaluator records `reoptimization_performed=false` and seven
  predeclared stresses, preserving the source run and frozen optimization
  request hashes.
- Only `initial_soc_minus_5pp` is physically accepted, with full completion
  and a 0-JPY fixed-decision accounting delta. `bev_energy_plus_10pct`,
  `bev_energy_plus_20pct`, `travel_time_plus_10pct`, `pv_minus_20pct`,
  `one_charger_outage`, and the combined case are physically rejected. The
  event validator reports terminal-SOC, timing/overlap, PV, and/or charger
  failures as applicable; their additional costs remain null rather than being
  repaired or invented.
- This is an honest post-solve stress screen, not a robust optimization or
  recourse result. It demonstrates that this fixed candidate cannot support a
  general uncertainty-robustness or additional-cost claim.

## 2026-08-23: Bounded 40-trip M0--M3 comparison completed

- Frozen tag `small-m0m3-3e52305` executed
  `output/verification/small_m0_m3/3e52305_20260823/audit.json` from clean
  `3e523056972b847871e12976c6db0a513611c025`, using the 40-trip deterministic
  subset, five vehicles per type, seed 42, four threads, and 300 seconds.
- The M0 all-ICE exact baseline, M1 mixed Phase-3 without PV/BESS, M2 deployed
  mixed Phase-3, and M3 mixed integrated scalar-actual-cost oracle are all
  feasible and complete. M0/M3 have `optimal` status and gap 0. The same-input
  M2/M3 pair is `PASS_SMALL_SCOPE_ONLY`: 2,439.5361535728903 versus
  2,439.536153572865 JPY, a numerical-tolerance difference of
  `2.55e-11 JPY` with lower-bound consistency.
- M0/M1 versus M2/M3 intentionally change the energy-asset or fleet contract;
  their 13,057.776 / 13,728.193 / 2,439.536 / 2,439.536-JPY values are
  descriptive small-scope ablations, not a full-service algorithmic or
  economic result. This run cannot establish 264-trip optimality, runtime, or
  release readiness.

## 2026-08-23: 8/12/24/40-trip integrated-oracle scale certificate

- Frozen tag `small-integrated-oracle-e672918` executed
  `output/verification/small_integrated_oracle_scale/e672918_20260823/` from
  clean `e672918d082d4a0d2c90df9a663b9e60ba0ab2ba`. It used the same prepared
  input, seed 42, four Gurobi threads, and 300 seconds per phase for fresh
  8-, 12-, 24-, and 40-trip day-spanning subsets.
- The certificate is `VERIFIED_BOUNDED_SMALL_INSTANCES`: each Phase-4 run is
  `optimal` at gap 0 and each Phase-3 canonical accounting cost equals the
  exact Phase-4 canonical-actual-cost value within numerical tolerance. The
  relative two-stage difference is identifiable and 0.0 at 24 and 40 trips;
  it is deliberately undefined at 8 and 12 trips because the exact reference
  cost is zero.
- The certificate explicitly remains ineligible for a research-release or
  full-network-optimality conclusion. It is exact bounded formulation evidence
  only; it neither proves a 264-trip optimum nor validates a runtime claim.

## 2026-08-23: Current recovery-gated pure-ICE A/B completed

- Clean commit `ac8982d33826f681c6441eeb3f7f320fc12f3a3b` completed the
  recovery-gated v4, isolated-process Phase-3 bundle at
  `output/diagnostics/pure_ice_aggregation_phase3_ab_ac8982d_20260823/`.
  It contains five alternating AB/BA pairs, 10 children total, the fixed
  prepared input `prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a`, seed
  42, four Gurobi threads, Stage 1=435 seconds, Stage 2=30 seconds, and the
  frozen request hash recorded with each child.
- All 10 children share the clean SHA and prepared-input hash; each served
  264/264 trips, passed independent physical validation, accepted 24/24
  Rolling steps, reconciled final accounting, and used neither fallback nor
  post-solve repair. Every aggregate child records `applied=true`, unchanged
  integer and recoverable physical dispatch sets, a non-relaxed labelled
  region, and 19 recovered canonical ICE paths/IDs.
- `repeated_comparison.json` reports `PASS_STRUCTURAL_ONLY`. Median total
  variables fell 762,906 to 520,173 (-31.82%), binaries 726,240 to 493,756
  (-32.01%), constraints 108,062 to 82,035 (-24.09%), and process-tree RSS
  3,654,950,912 to 3,026,780,160 bytes (-17.19%). Median total solver time
  increased 465.570 to 480.265 seconds (+3.16%); although median wall time
  fell 648.756 to 619.371 seconds, the collector correctly rejects a solver
  performance claim. Both representations remain time-limited, so the lower
  aggregate candidate incumbent and 3.08% gap do not establish cost dominance
  or a 264-trip optimum.
- Verification before this run: the focused suite reported `116 passed`; the
  completed bundle is the current structural diagnostic, not a release or
  sensitivity-acceptance result. Historical v3, initial-v4, and interrupted-r3
  bundles remain diagnostic only and are not combined with this SHA.

## 2026-08-23: Pure-ICE A/B runner can now resume interrupted batches

- The recovery-gated r3 attempt at
  `output/diagnostics/pure_ice_aggregation_phase3_ab_4e715da_20260823_r3/`
  was externally interrupted after four individually valid children and before
  final comparison. It has no `repeated_comparison.json`; it is diagnostic
  only and must not be combined with a later SHA.
- Added `--resume-pure-ice-aggregation-ab` to the existing runner. It verifies
  the frozen manifest (SHA, input hash, request hash, solver controls, case
  plan), reloads only individually valid completed children, and writes every
  retried child under a distinct `resume_attempts/attempt_NN/` path. Duplicate,
  partial, dirty, hash-drifted, or invalid children fail closed.
- The regression simulates an interruption after the first child, then resumes
  to all ten cases without rerunning that child (`15 passed` in
  `tests/test_lazy_fragment_performance_diagnostic.py`). A fresh clean commit
  and new five-pair bundle are required; the r3 partial cannot be reused after
  this source change.

## 2026-08-23: Aggregation A/B recovery gate made fail-closed

- The completed initial v4 A/B bundle exposed different time-limited feasible
  incumbents: B used more BEV trips and had a lower evaluated candidate cost.
  Its Stage-1 audit records an integral aggregate ICE flow, deterministic
  recovery to 19 canonical ICE IDs, and no changed recoverable dispatch set;
  its 24-step Rolling, independent physical validation, and accounting also
  pass. This difference is therefore not itself evidence of a relaxation, but
  neither result is a performance or optimality claim.
- Review found a P1 gap in the harness: it checked only representation and
  model-size counters, rather than the exactness/recovery fields. The A/B gate
  now rejects aggregate evidence unless `applied=true`, the integer feasible
  set and recoverable physical dispatch set are unchanged, the labelled
  extended region is not relaxed, and every recovered path has a canonical
  clone ID. The discrete control must likewise state that no set changed.
- Added a negative regression that flips the recovery-set flag and requires
  `FAIL_CORRECTNESS`. Focused A/B plus exact-clone regression tests pass
  (`21 passed`). Because the harness contract changed, the initial v4 bundle
  `output/diagnostics/pure_ice_aggregation_phase3_ab_01da730_20260823/` is
  diagnostic-only. A fresh five-pair run from the post-fix clean commit is
  required before recording a verdict.

## 2026-08-23: Hardened the 264-trip pure-ICE aggregation A/B contract

- Found a P1 regression in
  `scripts/build_lazy_fragment_performance_diagnostic.py`: the BFF private
  worker signature acquired `stage1_powertrain_selector_strengthening`, while
  the aggregation runner still supplied positional arguments. On current code,
  that could shift the thread and later controls. The runner now calls the
  reachable BFF worker with named arguments and has a focused regression test
  that proves selector and thread forwarding.
- Raised the repeated aggregation artifact schema to v4. Its request manifest
  now records Python, Gurobi/gurobipy, OS, CPU, RAM, frozen-request SHA-256,
  and explicit solver controls. Per-run validity now rejects synthetic-PV
  fallback, Stage-1 objective proxy use, weather-proxy input, fallback, and
  post-solve repair. The frozen trip-energy model remains disclosed as a common
  input rather than mislabelled as an optimization-time substitution.
- Commands: `.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_lazy_fragment_performance_diagnostic.py
  tests\\test_stage1_runtime_telemetry.py
  tests\\test_optimization_canonical_metaheuristics.py` and
  `.venv\\Scripts\\python.exe -m compileall -q
  scripts\\build_lazy_fragment_performance_diagnostic.py`. Result: 39 passed;
  compile succeeded. `ruff` is not installed in this virtual environment.
- The old five-pair v3 artifact at
  `output/diagnostics/pure_ice_aggregation_phase3_ab_817d938_20260823/` stays
  diagnostic-only. A clean v4 commit and fresh five-pair AB/BA rerun are now
  required; old results will not be relabelled as current-code evidence.

## 2026-08-23: Pending controlled Stage-1 BEV/ICE selector representation test

- The normal 264-trip candidate's search telemetry reached the substantive
  52,749.163582-JPY root bound at node 0 and remained there through the
  433.932-second Stage-1 primary search; its independent analytical bound is
  52,724.471363 JPY. The 65,305.688576-JPY Stage-1 incumbent therefore shows
  a structural integer-relaxation gap, not a claim that merely extending the
  time limit will meet the 1% target. Inspection confirmed that Stage 1 already
  includes the BEV return-to-initial terminal SOC constraint and BESS terminal
  policy, so neither was weakened or changed.
- Added the opt-in metadata flag
  `stage1_powertrain_selector_strengthening`. When enabled, it introduces a
  trip-level binary equal to the existing electric-assignment sum only when a
  trip has both electric and combustion alternatives, and assigns it branch
  priority 100. This is an integral-assignment-redundant extended formulation;
  the ordinary default remains false pending controlled measurement. Metadata
  records its enabled state, selector count, constraint count, and semantics.
- `tests/test_weather_coupled_assignment.py` compares OFF/ON on the existing
  two-trip Phase-3 physical-PV fixture and confirms identical assignment and
  Stage-1 objective. The focused run plus the full test module passed (18
  tests). That validates only equivalence on the bounded fixture. The next
  permissible evidence is a clean-commit 264-trip A/B with unchanged SHA,
  prepared input, objective/constraints, seed, threads, time limit, MIP gap,
  and solver settings; only the representation flag may differ.
- An initial 264-trip attempt put the flag in `simulation_settings`; both
  Prepare calls consequently resolved to the same prepared-input ID and the
  selector was absent from canonical metadata. The OFF result is retained only
  as an incomplete execution diagnostic and the queued ON job was stopped;
  neither is A/B evidence. The flag is now an explicit `RunOptimizationBody`
  field, forwarded to `_run_optimization`, and written into the canonical
  problem metadata after the prepared input is materialized. Focused BFF,
  metadata-forwarding, Phase-3, and README tests passed (48 tests).
- The corrected two-condition frontend/BFF bundle is
  `output/thesis_powertrain_selector_ab_b890c41_20260823/`, frozen at
  `b890c410f6c7b7125c1d7d0d721147bac44c4a75`. Its manifest is `BLOCKED` only
  because each feasible candidate misses the declared 1% gap. Both cases use
  prepared input `prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a`, the
  same 264 trips, seed 42, four threads, 900-second request, full successor
  network, and 60-minute Rolling. OFF has zero selector variables/rows; ON
  has 264/264. Both have the same Stage-1 incumbent 65,305.688576 JPY,
  candidate cost 64,422.491318 JPY, 32 vehicles, 48/216 BEV/ICE trips, 264/264
  service, accepted Rolling and physical validation. Their certified gaps are
  19.227306637367274% (OFF) and 19.227306637127555% (ON), while Stage-1 solver
  times are 463.816 and 463.918 seconds respectively. The one-run controlled
  result shows no benefit; the flag remains default-OFF and does not close any
  release gate.

## 2026-08-23: Current-SHA normal frontend/BFF Phase-3 rerun remains a feasible candidate

- Before execution, recorded baseline `a145cf3a8b9cba0e4d97c48f800fba9ff07a1e69`
  and current `6e61b808025385cfbf6b67efa37025d82ac44e31`: the baseline is an
  ancestor and the current history contains 69 commits. The active environment
  was Python 3.14.6, Gurobi/gurobipy 13.0.1, and Windows 11; the runtime
  artifact additionally records the machine, thread, seed, input and solver
  controls.
- Created annotated tag `phase3-current-formal-6e61b80`, restarted the
  port-8000 BFF from that clean SHA, and verified
  `/api/research/git-preflight` reports matching clean runtime/current SHA.
  The existing HTTP-only runner then executed exactly `DIESEL_PRICE_145` from
  Fresh Prepare with four threads, seed 42, 900 seconds, 1% requested gap and
  60-minute Rolling. Command:
  `python scripts/run_thesis_sensitivity_matrix.py --scenario-id b23fd26c-1233-4c73-bb9e-bdb8b1584760 --base-url http://127.0.0.1:8000 --base-prepare-request output/thesis_sensitivity_diesel_b505c7a_20260823_r1/cases/DIESEL_PRICE_145/frontend_prepare_request.json --base-optimization-request output/thesis_sensitivity_diesel_b505c7a_20260823_r1/cases/DIESEL_PRICE_145/frontend_optimization_request.json --output-dir output/thesis_current_phase3_6e61b80_20260823 --case-id DIESEL_PRICE_145 --timeout-seconds 2400 --poll-interval-seconds 10`.
- The completed bundle is `output/thesis_current_phase3_6e61b80_20260823/`.
  Its manifest SHA-256 is
  `f74c9ea76c24fae8f26ad3b043d54cf50fbd9d40a6c5ca1df52d3be04cd5796b`.
  It has valid/research-ready input provenance, complete successors, 264/264
  coverage, physical validity, 24/24 accepted Rolling, executed-day
  accounting, and 240/240 finalized artifact hashes. Final candidate cost is
  64,422.491318 JPY, using 32 vehicles for 48 BEV / 216 ICE trips.
- The only one-case matrix failure is the declared gap: Stage 1 is a
  time-limit result at 19.227306637% after 464.581506 solver seconds, above
  1%. The runner consequently labels the manifest `BLOCKED`; this single
  central-price rerun is not a completed price sensitivity. Independent
  `audit_thesis_model_phase_gates.py` produced
  `output/diagnostics/thesis_phase_gate_6e61b80_20260823/current_phase_gate_audit.json`
  (SHA-256
  `47a267623dea68cc9e5c032f6b9e2fc6c2531204dbc62154b972241d6f551a2d`) and
  also returns `BLOCKED`, specifically including the absent full Phase-4 run
  and the unmet Stage-1 gap. No optimality, accepted sensitivity, or release
  claim is added.
- Used a clean detached worktree at the exact source SHA (rather than bypassing
  the evaluator/source-SHA guard) to run
  `run_fixed_solution_stress.py` against that copied source run. The result is
  `output/diagnostics/fixed_solution_stress_6e61b80_20260823/`, with manifest
  SHA-256
  `d9a7160ead2227fdaa13d89b5a643f0afcee049ac3a1e3d62160fee3b86f90bd`.
  It records matching source/evaluator SHA, a clean worktree, the fixed
  prepared input and solver controls, and `reoptimization_performed=false`.
  All seven fixed-plan stresses retain 264/264 assigned trips. Only
  `initial_soc_minus_5pp` is physically valid (minimum 53.207928 kWh and
  0-JPY delta); BEV energy +10/+20%, travel time +10%, PV -20%, charger
  outage, and the combined condition fail physical validation and deliberately
  have null cost deltas. This is a failure-revealing fixed-decision stress
  result, not a reoptimized recourse or optimum claim.

## 2026-08-23: Bounded M0--M3 actual-cost-oracle protocol

- Extended `scripts/audit_small_integrated_weather_milp.py` with the opt-in
  `--run-small-m0-m3` path. It runs exactly four 15-minute, deterministic
  day-spanning-subset cases: M0 is available-ICE-only with PV/BESS disabled;
  M1 is the mixed fleet with PV/BESS disabled; M2 is the deployed Phase-3
  two-stage method; and M3 is the same mixed-fleet/PV/BESS input under the
  scalar canonical-actual-cost Phase-4 oracle. M0 and M3 must independently
  satisfy the existing exact-oracle gate; all four must be feasible and
  complete before the artifact can be `PASS_SMALL_SCOPE_ONLY`.
- PV/BESS removal changes both `depot_energy_assets` and `pv_slots`, preventing
  the no-PV/BESS ablation from retaining a hidden source representation. The
  result records each method contract, exact-oracle eligibility, descriptive
  deltas, and an M2--M3 same-input/lower-bound check. It fails closed when any
  method is absent, incomplete, non-exact where exactness is required, or when
  the M2--M3 pair is not comparable.
- The path is intentionally separate from the full frontend M0--M3 assembly:
  full `phase4_integrated` uses the production lexicographic policy, whereas
  this M3 explicitly requires the scalar actual-cost oracle. The implementation
  and 14 focused tests were committed as `ab559338a8eafcd45309afd4b56a2e9e6a93a6f4`
  and frozen with tag `phase3-small-m0-m3-ab55933` before execution.
- The resulting 24-trip artifact is
  `output/verification/small_m0_m3/ab55933_20260823/audit_24.json` (SHA-256
  `f05cd64ae34925eeada14cb03ca6ebf3ab7d6075340fb66062a2b08134b412f8`). It is
  `BLOCKED_SMALL_SCOPE` and is retained as `DIAGNOSTIC`, not a partial success
  relabelled as a comparison. The first implementation selected only five ICE
  vehicles for M0 while M1/M2/M3 had five BEVs plus five ICE vehicles. Strict
  precheck therefore correctly rejected M0's insufficient fleet. A direct
  input audit confirms every selected trip allows both BEV and ICE, so the
  earlier explanation of an ICE-compatibility blocker was wrong. The repair
  constructs M0 afresh with ten ICE vehicles—the same total fleet budget as
  the mixed conditions. No values from the invalid four-method attempt are
  used for a method-effect claim.
- The repaired clean-tag run `phase3-small-m0-m3-4445ea3` produced
  `output/verification/small_m0_m3/4445ea3_20260823/audit_24.json` (SHA-256
  `d8dce27a1a197705d6da3175bcf12f908089c699eb1c0fd8aba5e3b3ba5d6126`) with
  `PASS_SMALL_SCOPE_ONLY`. M0 is a 10-ICE-vehicle, no-PV/BESS exact scalar-cost
  optimum at 12,131.306002 JPY; M1 is mixed Phase 3 without PV/BESS at
  12,163.196412 JPY; M2 is deployed mixed Phase 3 at 577.394095 JPY; and M3
  is its scalar actual-cost exact oracle at 577.394095 JPY. M2/M3 share
  declared-input hash
  `1cc0362caf019d6b08ad50125595be99a754317e877822b1edebe140c87e561b` and
  differ by 1.0914e-11 JPY. The CLI is a direct bounded-model audit and does
  not satisfy the frontend phase-token research-acceptance contract; these are
  not full 264-trip method effects, economics, or release evidence.

## 2026-08-23: Small-oracle reproducibility hardening

- The small integrated-oracle CLI now refuses a dirty or Git-unattested
  worktree before it creates its output directory. It records the full
  `runtime_environment_v3` snapshot, Git provenance before and after the
  solve, a canonical prepared-input SHA-256, and a SHA-256 of declared solver
  controls in `reproducibility`.
- Added explicit `--gurobi-threads` (default `4`); all cases use the fixed
  thread count, exact `mip_gap=0`, fixed seed, fixed per-phase time limit,
  disabled warm start/repair, and disabled Phase-4 seed handoff. This closes a
  reproducibility omission in the prior bounded M0--M3 artifact and requires
  a fresh clean-commit rerun before using the strengthened contract.
- `build_small_integrated_oracle_scale_certificate.py` now forwards that
  explicit thread control to every isolated 8/12/24/40-trip child and writes
  the same runtime snapshot into its parent provenance. The scale certificate
  therefore needs its own fresh clean-commit run; older scale artifacts remain
  historical bounded checks only.
- A direct invocation initially exposed that the wrapper imported the BFF
  helper before adding the repository root to `sys.path`. The import ordering
  is corrected, and a subprocess `--help` regression now executes it from the
  `scripts/` directory. This prevents a test-only import path from masking an
  unusable experiment command.
- Corrected the scale-certificate claim field: a verified bounded series now
  sets `bounded_formulation_conclusion_eligible=true` but always sets
  `research_conclusion_eligible=false`. The schema is v2; the former v1
  `true` value is an overclaiming artifact and is not current evidence.
- The clean tag `phase3-small-oracle-scale-scoped-f75ee78` produced
  `output/verification/small_integrated_oracle_scale/f75ee78_20260823/`.
  The v2 certificate SHA-256 is
  `545ad7fe16c40847e0ee87a6ccdff268845991aa6fc4cf8dedbb8a4260a9a358` and
  verifies all 8/12/24/40-trip child artifacts with matching clean pre/post
  SHA `f75ee78`, prepared-input hash
  `639b6754cccd1aef7758454b56640f968b6b1c277ec32c1c142f53f670ade558`, seed
  42, four threads, and 300 seconds per phase. Phase 4 is exact at every
  size; ApproxGap is zero where identifiable (24/40) and deliberately
  unidentifiable at zero-cost 8/12. The certificate has
  `bounded_formulation_conclusion_eligible=true` and
  `research_conclusion_eligible=false`.

## 2026-08-23: Current-SHA diesel-price response tranche

- Restarted the port-8000 BFF before the run because its runtime Git
  attestation still named `19bb780`; the replacement runtime attested clean
  SHA `b505c7acd7b0c7daf678cd86e9cae69119a37bba`. Tagged that commit
  `phase3-diesel-sensitivity-b505c7a`, then executed the existing HTTP-only
  matrix runner with case IDs `DIESEL_PRICE_116`, `DIESEL_PRICE_145`, and
  `DIESEL_PRICE_174`, seed 42, four threads, a 900-second request, 1% target,
  and 60-minute Rolling. The bundle is
  `output/thesis_sensitivity_diesel_b505c7a_20260823_r1/`; its manifest SHA-256
  is `ad3380032e561435b2fcabb94aa8c4543232090abe5650b35705910e4a9a223f`.
- All cases completed Fresh Prepare and passed valid/research-ready input
  provenance, 264/264 coverage, physical validation, accepted 24/24 Rolling,
  executed-day accounting, and 240 finalized artifact hashes. The shared
  non-varied-control fingerprint is
  `be00dff409d09358f8ccfc5d0b861049e75f0069c90b1da82da640bd96ece673`.
  Independent provenance and artifact commands also pass for each source run
  (`run_20260823_0813`, `0824`, and `0836`).
- The diesel coefficient is demonstrably active. All three candidates consume
  436.508457111 L ICE fuel and retain 32 used vehicles with 48 BEV / 216 ICE
  trips; final costs are 51,763.746062 / 64,422.491318 / 77,081.236574 JPY at
  116 / 145 / 174 JPY/L. The 12,658.745256-JPY step is fuel litres times the
  29-JPY/L price change. No dispatch change was observed in these same
  time-limit incumbents. Every case is therefore `BLOCKED` solely by the
  unchanged 19.227307% certified Stage-1 gap, not by a silent/no-op price
  input. It is a diagnostic cost-response result, not an accepted optimal
  dispatch-response claim.

## 2026-08-23: Current-SHA bounded Phase-3 versus integrated actual-cost oracle

- Reran the existing fail-closed, isolated-process scale certificate at clean
  commit `e3fe904ba4afb6e2890aec7a7011e082f3aa20a0` against the frozen prepared
  input `prepared-ee27696fc37f0c7a-f1e18f252e336f1f` (SHA-256
  `639b6754cccd1aef7758454b56640f968b6b1c277ec32c1c142f53f670ade558`). The
  artifact is `output/verification/small_integrated_oracle_scale/e3fe904_20260823/`.
  Each 8/12/24/40-trip child ran in a separate Python process; every Phase-4
  actual-cost oracle is `optimal` with zero gap and every Phase-3 case is
  feasible and complete. The certificate is
  `VERIFIED_BOUNDED_SMALL_INSTANCES` with no blockers.
- ApproxGap is identifiable at 24 and 40 trips and is zero within numerical
  tolerance; its 8/12-trip denominator is numerically zero and is explicitly
  labelled `not_identifiable_zero_reference_cost`. This refreshes the bounded
  RQ2 formulation evidence on the current code only. It neither validates the
  264-trip Phase-3 global cost optimum nor clears the 1% Stage-1 gap,
  sensitivity, stress, or full-scale method-comparison gates.

## 2026-08-23: Phase-3 gap-control telemetry and search-control falsification

- Tightened the analytical `path_powertrain_source_flow_lp` and its integral
  selector-MIP companion with a necessary aggregate path-start capacity for
  each powertrain. The row is the direct sum of the original per-vehicle
  constraints: selected starts are bounded by available vehicles times
  `min(max_start_fragments_per_vehicle, covered_day_count * daily_fragment_limit)`.
  It cannot exclude a full Stage-1 solution, while vehicle identity, SOC,
  chargers, depot allocation, and time-indexed source coupling remain relaxed.
  The per-vehicle limit and powertrain capacities are included in the
  certificate input hash; LP/MIP audits expose the two rows and capacities.
  `test_weather_energy_fuel_certificate_limits_powertrain_path_starts` uses
  two sequential, deliberately disconnected trips with one BEV and one ICE to
  prove that free electricity cannot fund two BEV path starts; both certificates
  retain a 10-JPY floor. Focused verification is `81 passed` across the
  Stage-1 certificate, coverage, graph parity, artifact, and README tests.
  The fresh normal-BFF 264-trip diagnostic at clean commit
  `763c7adabdd2012e15c455001dcb038d149e2f5c` is retained at
  `output/2026-08-23/run_20260823_0555/` (job
  `17b028be-8750-49e1-a699-7e4b261d9de7`). The prepared-input validation is
  valid/research-ready; the two rows have a per-vehicle limit of 3 and
  capacities 105 BEV / 75 ICE. LP/MIP were optimal at 52,712.318101 /
  52,724.471363 JPY, but the native Gurobi bound (52,749.163582 JPY),
  incumbent (65,305.688576 JPY), one explored node, and certified gap
  (19.227307%) were unchanged. Stage 2 had no valid candidate and Rolling did
  not start. This is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**; the
  aggregate start-capacity condition is not the current gap-closing path.

- Tightened the analytical `path_powertrain_source_flow_lp` and its integral
  selector-MIP companion with a necessary powertrain-level concurrent-service
  capacity row. At every trip departure instant, the selected active BEV/PHEV/
  FCEV or combustion trips cannot exceed the count of available vehicles in
  that powertrain. This is valid for every full Stage-1 solution and remains a
  lower-bound relaxation because it omits vehicle identity, deadhead occupancy,
  SOC, chargers, depot allocation, and time-indexed energy sources. The
  certificate input hash now includes the retained capacity rows and fleet
  counts; audits expose their count. A two-concurrent-trip, one-BEV/one-ICE
  regression proves that the cheaper BEV cannot be selected twice. This code
  tightening was measured by the clean `98916ff` 264-trip frontend artifact at
  `output/2026-08-23/run_20260823_0520/`: its 35-BEV/25-ICE fleet produced
  zero capacity rows, so the LP/MIP floors stayed 52,712.318101/
  52,724.471363 JPY. The Gurobi bound (52,749.163582 JPY), incumbent
  (65,305.688576 JPY), and certified gap (19.227307%) were unchanged; Stage 2
  time-limited without a physical candidate and Rolling correctly did not
  start. The artifact has clean-SHA and input-provenance validation, but is
  `DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS`; this aggregate capacity
  condition is not a gap-closing path.

- Added the bounded `path_powertrain_source_flow_mip` certificate to the
  existing weather-aware Stage-1 analytical lower bound. It reuses the
  continuous powertrain path/source-flow model but makes only assignment,
  start, end, and chronological connection selectors binary. The certificate
  still relaxes vehicle identity, vehicle-count allocation, SOC, charger, and
  time-indexed source coupling, so its proven optimum is a valid lower bound
  on the full Stage-1 model. It is used only if Gurobi returns `optimal` within
  30 seconds; any time-limit or error leaves the existing lower bound intact.
  Focused Gurobi regression verifies that this certificate dominates the LP
  floor for both sunny and rain cases. The clean `93608f4` 264-trip frontend
  diagnostic at `output/2026-08-23/run_20260823_0507/` solved the certificate
  to optimality in 0.637 seconds (154 nodes) and raised its own floor from
  52,712.318101 to 52,724.471363 JPY. Gurobi's native root bound was already
  52,749.163582 JPY, so the certified 19.227307% Stage-1 gap did not change;
  Stage 2 time-limited without a physical candidate. This is
  `DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS`. Verification command:
  `python -m pytest -q tests/test_weather_coupled_assignment.py
  tests/test_milp_strict_coverage_metadata.py
  tests/test_canonical_graph_export_parity.py
  tests/test_frontend_artifact_completeness.py tests/test_readme_navigation.py`
  (`79 passed`), plus `python scripts/verify_run_input_provenance.py --run-dir
  output/2026-08-23/run_20260823_0507` (all checks valid).

- Added opt-in `stage1_root_lp_diagnostic_enabled`. When requested, Stage 1
  clones its fully constructed model with all discrete variables relaxed and
  records the isolated LP objective, solution status, aggregate powertrain
  trip equivalents, split-trip count, fractional assignment count, and
  fractional vehicle activations. It cannot add cuts, alter the original MIP,
  or reuse any diagnostic solution. The BFF request and final solver metadata
  persist the flag and result. The diagnostic has an explicit 30-second
  default and is capped by the remaining shared Phase-3 deadline; it cannot
  consume an unbounded extra solver budget. The original 264-trip diagnostic
  at `output/2026-08-23/run_20260823_0441/` timed out after 300.234 seconds
  with no LP solution and is retained only as non-comparable diagnostic
  evidence because it predated that cap. The bounded clean-SHA rerun at
  `output/2026-08-23/run_20260823_0452/` (commit `562fe2f`) likewise timed
  out after 30.239 seconds with no LP solution; it left 156 seconds for the
  primary Stage-1 search, which retained the 19.227307% gap but yielded no
  Stage-2 physical candidate. It is diagnostic only. Focused verification:
  `py_compile` and `74 passed` across the Stage-1, BFF-worker, artifact,
  harness, and documentation checks.
- Code review found and fixed a P1 A/B-harness integration defect: its
  positional synchronous-worker call omitted the existing Stage-1 profile and
  fragment-cut fields. It now forwards the profile, root-LP diagnostic flag,
  fragment-cut mode, then thread count in the worker's exact signature order.
  Harness/pairwise-cut verification adds `18 passed`; this does not alter the
  represented model or any completed A/B artifact.

- The frozen `phase3-gap-escalation-f9b83ad` frontend/BFF run is retained at
  `output/thesis_phase3_gap_escalation_f9b83ad_20260823_r1/`. Command used
  the existing sensitivity runner with the 30-JPY/kWh case, fresh Prepare,
  1800-second total budget, explicit Stage 1=1650 seconds, Stage 2=120
  seconds, seed 42, four threads, and 1% requested MIP gap. It completed
  264/264 coverage, physical validation, 24-step Rolling/accounting and
  provenance checks, but failed only `mip_gap_target_met`: 19.227307% after
  1680.778 solver seconds. The primary incumbent 65,305.688576 JPY, certified
  bound 52,749.163582 JPY, and final node count 1 were unchanged from the
  900-second trial. This falsifies time allocation alone as a sufficient fix;
  it is diagnostic, not accepted research evidence.
- `OptimizationConfig.stage1_gurobi_search_profile` now makes the Stage-1
  Gurobi controls explicit: `default` reproduces documented defaults and
  `bound_focus` uses `MIPFocus=3` and aggressive presolve. The BFF request and
  `solver_settings.json` persist profile, MIPFocus, Heuristics, Presolve,
  Method, NodeMethod and Symmetry. The profile changes search controls only;
  it does not alter the objective, variables, constraints, inputs, validation,
  or 1% acceptance threshold. Verification: `python -m py_compile
  src/optimization/common/problem.py src/optimization/milp/solver_adapter.py
  src/optimization/milp/engine.py bff/routers/optimization.py`; `python -m
  pytest -q tests/test_milp_strict_coverage_metadata.py
  tests/test_canonical_graph_export_parity.py tests/test_thesis_sensitivity_matrix.py
  tests/test_frontend_artifact_completeness.py` (`87 passed`).
- The frozen `bound_focus` frontend/BFF diagnostic at commit
  `8c37638364c6cd99a9637e23dbbe7c3b72be49ee` is retained at
  `output/thesis_phase3_bound_focus_8c37638_20260823_r1/`. It held the
  prepared scenario, mathematical model, 1800-second total budget, Stage-1
  primary-search limit (1605 seconds), candidate policy, seed 42, four
  threads, and 1% threshold fixed; only the recorded profile changed to
  `MIPFocus=3`, `Presolve=2`, and unchanged `Heuristics=0.05`. It served
  264/264 trips and passed physical, Rolling/accounting, provenance, and
  complete-successor checks. Its sole failed check is still
  `mip_gap_target_met`: 19.227307% after 1680.193 solver seconds, with the
  same 65,305.688576-JPY incumbent, 52,749.163582-JPY bound, and one explored
  node. Therefore the tested bound-focused profile is not a sufficient
  certificate fix; this bundle is `DIAGNOSTIC`, not accepted research
  evidence.
- Added the opt-in `stage1_fragment_transition_cut_mode="explicit_root"`
  representation for the next controlled strengthening diagnostic. It
  materializes the same invalid end/start pair rows that the default lazy
  callback adds only at integer incumbents, so it changes neither the Stage-1
  objective nor the integer feasible set. The BFF request and solver metadata
  record the mode and the materialized row count. A Gurobi two-fragment
  infeasibility regression confirms equivalence with the lazy contract;
  focused verification is `98 passed`.
- The frozen full-case `explicit_root` diagnostic at
  `output/thesis_phase3_explicit_root_dc759be_20260823_r1/` used commit
  `dc759bebf169b88bbe563ae9d715cae431fcf3ad`, the same prepared scenario,
  full successor network, seed, four threads, candidate policy, and objective,
  with a 240-second total budget (Stage 1=210, Stage 2=30). Materializing
  1,243,440 exact rows expanded Stage 1 from 108,062 to 1,351,502 constraints.
  The 165-second primary search ended with Gurobi bound 0.0 and no root-LP
  certificate; Stage 2 then time-limited, so the runner correctly failed
  `source_artifact_validation_failed` because no physical schedule artifact
  exists. This is `DIAGNOSTIC`, not a feasible, performance, or bound-improving
  result. Full explicit root materialization is rejected as the next release
  path.
- Added the opt-in `stage1_fragment_transition_cut_mode="lazy_root_cuts"`
  diagnostic. It keeps the default MIPSOL lazy separation and, at a Gurobi
  optimal MIPNODE relaxation, adds at most 100 currently violated instances
  of the same proven-valid `end_arc + start_arc <= 1` row. The callback fails
  closed, records node/user-cut counts, and leaves the objective and integer
  feasible set unchanged. A focused fake-MIPNODE regression checks the exact
  selected row; the existing fail-closed callback regression caught and then
  verified a missing test-double guard. Verification: `96 passed`. No
  full-case result exists yet.
- The first `lazy_root_cuts` artifact on `8181622` is invalid for evaluating
  user cuts: although the separator supported MIPNODE, the outer Stage-1
  callback forwarded only MIPSOL events, yielding zero MIPNODE callbacks and
  zero cuts. The exact callback-routing defect is repaired by forwarding
  MIPNODE to the same fail-closed separator; focused verification remains
  `96 passed`. A new clean-SHA run is required before any conclusion.
- The routed rerun still received no MIPNODE callbacks, so `lazy_root_cuts`
  added zero rows and is not viable for the current Stage-1 root path. Added
  pending `lifted_root` aggregates instead: for every endpoint, the sum of
  incompatible opposite endpoints is bounded by the existing maximum fragment
  count times `(1 - endpoint)`. At binary endpoints this is equivalent to the
  exact pairwise restrictions; on fractional endpoints it is stronger and
  requires O(vehicle × trip) rows. Focused verification: `47 passed`.
- The frozen `lifted_root` 264-trip diagnostic at commit
  `b484024e2ace6272b5a7cace4785887fa762925d` is stored at
  `output/thesis_phase3_lifted_root_b484024_20260823_r1/`. It added 31,140
  rows (108,062 to 139,202 constraints) while retaining the same prepared
  input, full successor network, seed, threads, objective, and 240-second
  budget. Its certified bound (52,749.163582 JPY), primary incumbent
  (65,305.688576 JPY), and 19.227307% gap were unchanged. Stage 2 time-limited
  before physical validation, so the runner correctly reported
  `source_artifact_validation_failed`. This is diagnostic only and rejects
  fragment-boundary LP strengthening as the next certificate path.
- Added the opt-in `root_cut_focus` Stage-1 Gurobi profile. It preserves every
  model coefficient, variable, and constraint while explicitly recording
  `MIPFocus=3`, `Presolve=2`, and generic `Cuts=3`; `default` and
  `bound_focus` retain Gurobi's automatic cut setting (`Cuts=-1`). The BFF
  schema accepts the profile and solver metadata persists the effective value.
  Focused contract/round-trip/artifact verification: `39 passed`. No full-case
  result exists yet, so it is not a performance or research claim.
- The clean-SHA 264-trip result is now retained at
  `output/2026-08-23/run_20260823_0428/` from commit
  `5665102c238e0ba519a402b567f6504dc371fb1e`. With the same prepared input,
  complete successor network, seed 42, four threads, 240-second total budget,
  Stage 1=210 seconds, Stage 2=30 seconds, candidate policy, and 1% target,
  `root_cut_focus` changed only Gurobi `Cuts` from automatic to `3`. Its
  certified bound (52,749.163582 JPY), primary incumbent (65,305.688576 JPY),
  certified gap (19.227307%), and one explored node were identical to the
  matched baseline. Stage 2 had no valid physical candidate, so Rolling did
  not start and the runner rejected the artifact. This is diagnostic only and
  rejects the tested generic-cut control as a certificate path.

## 2026-08-23: Electricity-price Phase-3 tranche completed as a diagnostic

- Executed the frontend/BFF sensitivity runner at clean commit
  `19bb78003cf6f44396093ca85022c2b58e56ce5f` using a fresh Prepare for each
  declared price: 24, 30, and 36 JPY/kWh. The immutable result bundle is
  `output/thesis_sensitivity_electricity_19bb780_20260823_r1/` and its three
  `case_execution_audit.json` files record 264/264 served trips, valid
  physical schedules, accepted 24-step Rolling/accounting, verified request
  provenance, complete successor networks, and an unchanged SHA.
- The runner correctly rejects every case for one reason only:
  `mip_gap_target_met=false` (certified gap 19.227307%, versus the 1% target).
  The cases are therefore `DIAGNOSTIC`, not thesis economic-response evidence.
  Their final ledgers each contain 0.0 kWh grid import and 64,422.491318 JPY;
  that equality must not be generalized into a no-price-effect claim because
  it comes from this time-limited candidate's zero-import dispatch.

## 2026-08-23: Accepted fixed-stage Phase-3 aggregation AB/BA x5 result

- Clean commit `817d9385976a70e50fbc48aa72d34e02f5c13552` was tagged
  `phase3-ab-fixed-stage-817d938` and executed through the normal BFF worker
  as ten isolated child processes (AB/BA alternating, five per
  representation). The frozen controls are the same 264-trip prepared input
  `prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a`, seed 42, four Gurobi
  threads, 900-second request, 1% requested gap, explicit Stage 1=435 seconds
  and Stage 2=30 seconds, and hourly Rolling. Command:
  `python -u scripts/build_lazy_fragment_performance_diagnostic.py --run-pure-ice-aggregation-ab --output-dir output/diagnostics/pure_ice_aggregation_phase3_ab_817d938_20260823 --scenario-id b23fd26c-1233-4c73-bb9e-bdb8b1584760 --prepared-input-id prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a --optimization-request output/thesis_sensitivity_charger_capacity_20260822_359cd36/cases/CHARGER_COUNT_6/frontend_optimization_request.json --expected-git-sha 817d9385976a70e50fbc48aa72d34e02f5c13552 --ab-repetitions 5 --stage1-time-limit-seconds 435 --stage2-time-limit-seconds 30 --small-exact-parity-passed`.
- `repeated_comparison.json` reports `PASS_STRUCTURAL_ONLY`: all ten children
  served 264/264 trips, passed independent physical validation, accepted all
  24 Rolling steps, reconciled final accounting, had matching input/control
  contracts, and used neither fallback nor post-solve repair. The aggregate
  median is 520,173 variables, 493,756 binary variables, 82,035 constraints,
  and 3,021,668,352-byte peak RSS versus discrete 762,906, 726,240, 108,062,
  and 3,657,289,728 bytes. This supports a formulation-size and sampled-RSS
  reduction only.
- No speedup is claimed. Aggregate median solver time was 480.192 seconds
  versus 465.531 seconds (+14.661 seconds); its runner wall median was 617.899
  versus 646.931 seconds, but the harness requires an improved solver-time
  median for `PASS_PERFORMANCE`. Gurobi did not expose separate presolve time
  in any child. The 264-trip results remain time-limited feasible candidates,
  not an integrated global-optimality or 1%-gap result.
- Documentation consistency correction: older 2026-08-22 checkpoint entries
  now state that the required rerun was pending *at that time*. The completed
  `817d938` bundle closes only the controlled formulation-size claim; the
  current release blockers remain the 1% certified-gap gate, accepted
  multi-point economic/charger sensitivities, and formal M0/M1/M2/M3 evidence.

## 2026-08-23: Phase-gate evidence inventory rerun

- `scripts/audit_thesis_model_phase_gates.py` was run without waivers against
  the fully accounted 264-trip candidate
  `output/2026-08-22/run_20260822_2125/`; output:
  `output/diagnostics/thesis_phase_gate_5cf5e7f_20260823/a497166_phase_gate_audit.json`.
  It validates prepared-input provenance, frozen SHA, 264/264 coverage,
  physical validation, 24/24 Rolling, canonical accounting, and 240 finalized
  artifact hashes. Its `BLOCKED` verdict is therefore not an artifact-read
  failure: the remaining gates are the 1% MIP gap, explicit Phase-4 integration,
  accepted controlled studies/sensitivities, and formal M0--M3 evidence. The
  audit is an inventory only and does not promote the old candidate or any
  diagnostic run to a research conclusion.

## 2026-08-23: Overnight service is included in the analytical fleet-capacity lower bound

- Corrected `src/optimization/milp/solver_adapter.py` so the analytical
  powertrain path/source LP and selector MIP derive simultaneous-service rows
  from `_trip_interval_bounds`, not raw wall-clock arrival/departure values.
  A trip ending after midnight previously made the capacity condition weaker by
  being omitted; this did not invalidate the lower bound, but it was an
  incomplete necessary condition. The canonical service-day interval is now
  hashed through the resulting deterministic rows.
- Added the Gurobi regression
  `test_weather_energy_fuel_certificate_counts_overnight_overlap_capacity` in
  `tests/test_weather_coupled_assignment.py`. Two 23:00-to-after-midnight trips
  with one BEV and one ICE produce both powertrain capacity rows and a 10-JPY
  LP floor. Command:
  `python -m pytest -q tests/test_weather_coupled_assignment.py tests/test_milp_strict_coverage_metadata.py tests/test_canonical_graph_export_parity.py tests/test_frontend_artifact_completeness.py tests/test_readme_navigation.py`
  (`80 passed`). This is a correctness repair for future certificates; it has
  now been measured through the normal BFF path at clean commit
  `9a286772c8b8a2580832fc021a8074ad4f69845a`:
  `output/2026-08-23/run_20260823_0538/` (job
  `caebed4d-1e0f-416b-84af-6052d3d7bdc4`). The saved input provenance is valid
  and research-ready; the 264-trip prepared input generated zero capacity rows
  for both LP/MIP, as it has no relevant overnight overlap. Stage 1 retained
  52,749.163582 JPY bound, 65,305.688576 JPY incumbent, one explored node, and
  19.227307% certified gap; Stage 2 had no feasible candidate, so Rolling was
  correctly not started. This remains **DIAGNOSTIC, NOT USED FOR RESEARCH
  CONCLUSIONS** and is not a gap-improvement or release claim.

## 2026-08-23: Current-SHA 8/12/24/40 integrated-oracle scale certificate

- Executed the existing fail-closed CLI in isolated Python child processes:
  `python scripts/build_small_integrated_oracle_scale_certificate.py --scenario-id b23fd26c-1233-4c73-bb9e-bdb8b1584760 --prepared-input-id prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a --output-dir output/verification/small_integrated_oracle_scale/0e9413c --trip-counts 8 12 24 40 --depot-id tsurumaki --service-id WEEKDAY --vehicles-per-type 5 --time-limit-sec 300 --random-seed 42`.
  The certificate at
  `output/verification/small_integrated_oracle_scale/0e9413c/scale_certificate.json`
  records clean pre/post SHA `0e9413c`, the same prepared-input SHA-256, seed
  42, 300 seconds per phase, and `VERIFIED_BOUNDED_SMALL_INSTANCES`.
- Every Phase-4 run reached `optimal` with zero solver gap and every Phase-3
  run completed. For 24/40 trips, Phase-3 minus integrated cost is within
  numerical tolerance (`ApproxGap=0`); for 8/12 trips the exact integrated
  reference cost is numerically zero, so relative gap is intentionally marked
  not identifiable. This revalidates only the bounded oracle comparison on the
  current code and is not a 264-trip global-optimality, full-scale gap,
  sensitivity, or M0--M3 release claim.

## 2026-08-23: Fixed-decision stress remains correctly SHA-bound

- Rechecked `scripts/run_fixed_solution_stress.py` and its contract regression:
  `python -m pytest -q tests/test_fixed_solution_stress.py tests/test_small_exact_electric_oracle.py tests/test_weather_coupled_assignment.py tests/test_canonical_graph_export_parity.py tests/test_frontend_artifact_completeness.py tests/test_readme_navigation.py`
  (`81 passed`). The CLI rejects a source result whose recorded SHA differs
  from the evaluator SHA and records `reoptimization_performed=false`; it must
  not be weakened to reuse the old `a497166` stress artifact after the current
  code changes.
- Froze clean commit `5ee35f70543fc9ff4962a5f396d34ade6a41a7a2` as
  `phase3-current-candidate-5ee35f7`, then ran the normal BFF path with the
  historical 900-second control (`seed=42`, `threads=4`, 1% request, same
  prepared input). Job `ddb36963-81fa-49a3-b3e8-5309d89b91c3` wrote
  `output/2026-08-23/run_20260823_0605/`: 264/264 coverage, independent
  physical validation, 24/24 Rolling, executed-day accounting and the 240-file
  artifact bundle all pass. `verify_run_input_provenance.py` and
  `verify_frontend_run_artifacts.py --research-run --require-rolling` pass.
  The final cost is 64,422.491318 JPY; the certified Stage-1 gap is still
  19.227307%, so the candidate is feasible/accounted but not optimality or
  release evidence.
- Executed the unchanged-plan CLI at the matching SHA:
  `python scripts/run_fixed_solution_stress.py --source-run
  output/2026-08-23/run_20260823_0605 --optimization-request
  output/diagnostics/thesis_phase_gate_5ee35f7_20260823/current_candidate_optimization_request.json
  --output-dir output/diagnostics/fixed_solution_stress_5ee35f7_20260823`.
  The manifest records matching source/evaluator SHA, frozen artifact hashes,
  and `reoptimization_performed=false`. Only `initial_soc_minus_5pp` is
  physically accepted (0 JPY delta); the other six stresses have physical
  violations and null costs. This is valid stress evidence, not an economic
  reoptimization result.

## 2026-08-23: Current-SHA electricity-price tranche is diagnostic only

- Froze clean commit `43112a3ba5b82558c3f32f94a9c121191cbcb85a` as
  `phase3-economic-sensitivity-43112a3` and used the normal frontend/BFF
  runner to execute fresh Prepare -> Phase-3 -> 60-minute Rolling cases at
  24, 30, and 36 JPY/kWh. The evidence bundle is
  `output/thesis_sensitivity_electricity_43112a3_20260823_r2/`; its execution
  manifest records unchanged pre/post SHA, a common non-varied-control
  fingerprint, and fresh prepared-input provenance for every case.
- All three cases served 264/264 trips and passed input provenance, complete
  artifact, physical schedule, 24/24 Rolling, accounting, complete-successor,
  and declared-control checks. Each has the same 19.227307% certified Stage-1
  gap, above the predeclared 1% target, so `case_accepted=false` solely because
  `mip_gap_target_met=false`.
- The three candidates have zero grid import and therefore the same recorded
  64,422.491318-JPY cost, BEV/ICE trip counts, and executed energy flows. This
  is an expected inactive-price condition for the recorded PV/BESS dispatch,
  not evidence of a zero price effect. The manifest remains `BLOCKED`; the
  tranche must not be cited as an accepted economic response, optimality, or
  thesis sensitivity conclusion.

## 2026-08-23: Current-SHA M0--M3 source pair is comparable but blocked

- Froze clean commit `406d02ca0fcd66e229fa739f057a158f7a30389c` as
  `phase3-method-comparison-406d02c`, prepared the 264-trip scenario once, and
  executed explicit M1 (`phase1_charging_only`) and M3
  (`phase4_integrated`) frontend/BFF jobs. M1 is
  `output/2026-08-23/run_20260823_0658/`; M3 is
  `output/2026-08-23/run_20260823_0700/`. Both share prepared input
  `prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a`, its source SHA-256,
  clean code SHA, seed 42, four threads, 60-minute Rolling, and a 1% target.
- Both input-provenance checks returned valid/research-ready and both
  `verify_frontend_run_artifacts.py --research-run --require-rolling` checks
  verified 240/240 required artifacts. The M1 job met its requested gap. M3
  served all trips and passed physical/Rolling/accounting gates, but its
  time-limit incumbent retained a 5.205591% certified gap after 3,600 seconds.
- `build_thesis_ablation_comparison.py` wrote
  `output/diagnostics/method_comparison_406d02c_20260823/comparison/`. It
  verified phase identity, exact common inputs, clean provenance, source
  acceptance, and M0 identity; the only failed check is
  `both_source_mip_gap_targets_met`. Its `BLOCKED` artifact records M0/M1/M2/M3
  day-ahead candidate costs of 81,030.774749 / 65,305.688576 / 84,078.282216 /
  55,619.811284 JPY, respectively. These are not accepted method effects or
  optimality evidence.

## 2026-08-23: Phase-3 A/B time-allocation control failure and fail-fast repair

- The clean-SHA, isolated-process AB/BA x5 diagnostic at
  `output/diagnostics/pure_ice_aggregation_phase3_ab_81561d5_20260822/`
  completed all ten individual 264-trip cases. Every child served 264/264
  trips, passed independent physical validation, 24/24 Rolling, and accounting,
  and used neither fallback nor post-solve repair. It is nevertheless
  `FAIL_CORRECTNESS`, `DIAGNOSTIC`, and **not usable for a performance or
  formulation claim**.
- The comparison artifact correctly caught a control-contract violation:
  discrete children reported effective Stage 1/2 limits of 434/30 seconds,
  while aggregate children reported 435/329 seconds. Phase 3 dynamically
  distributes Stage-2 time across the available candidate pool when no explicit
  Stage-2 value is frozen; the two representations exposed different pool
  shapes. Identical total request limits alone are therefore insufficient.
- `build_lazy_fragment_performance_diagnostic.py` now requires explicit
  `--stage1-time-limit-seconds` and `--stage2-time-limit-seconds` for the
  264-trip A/B command, writes those values into the frozen request and manifest,
  and refuses execution before creating an output directory when either control
  is absent. This fixes experiment control only; it does not alter the Phase-3
  objective, feasible region, solver formulation, physical checks, or release
  thresholds. Focused diagnostic regression: `10 passed`.

## 2026-08-22: Phase-3 A/B discrete-audit false rejection corrected

- The first clean-SHA 264-trip Phase-3 discrete child under
  `output/diagnostics/pure_ice_aggregation_phase3_ab_64c4a5a_20260822/`
  completed its solve and the physical, Rolling, and accounting paths, but the
  child finalizer rejected it before writing a comparison artifact. The
  counter used as proof of the discrete vehicle-labelled flow was incorrectly
  restricted to clone groups eligible for the aggregate network's stricter
  single-fragment precondition. The target group has three fragment layers,
  so that value was zero even though the discrete Stage-1 model was used.
- The representation telemetry now derives the discrete variable count from
  every certified clone group, independently of aggregate eligibility. The
  A/B-only aggregate now also uses the existing integral layered-fragment reset
  flow and canonical recovery path for certified multi-fragment groups. The
  normal frontend Phase 3 remains discrete. Candidate-pool extraction is
  permitted because it reuses that exact recovery; an already-present
  vehicle-labelled no-good cut remains fail-closed. A zero-weight switch term
  no longer blocks aggregation. Added Gurobi Phase-3 regressions for a
  two-fragment group, including pool extraction. Verification:
  `C:\master-course\.venv\Scripts\python.exe -m pytest -q
  tests\test_integrated_actual_cost_objective.py
  tests\test_lazy_fragment_performance_diagnostic.py` (`80 passed`), plus
  `python -m py_compile src/optimization/milp/solver_adapter.py
  scripts/build_lazy_fragment_performance_diagnostic.py` and `git diff --check`.
- The interrupted bundle is `DIAGNOSTIC`, `NOT USED FOR RESEARCH
  CONCLUSIONS`; it contains no aggregate counterpart and no comparison report.
  A new frozen-SHA AB/BA x5 execution is required after this correction.

## 2026-08-22: Phase-3 single-fragment pure-ICE aggregation is now wired and tested

- `src/optimization/milp/solver_adapter.py` now connects the pre-existing
  exact-clone certificate to Phase-3 Stage 1 only when the isolated A/B
  diagnostic explicitly requests `pure_aggregate`. The normal frontend
  Phase-3 path remains discrete. The aggregate replaces the selected
  certified ICE group's labelled assignment/connection/start/end flow with
  a binary group path-cover network and deterministically restores canonical
  vehicle IDs before Stage 2.
- The application is fail-closed: it requires a one-day, single-fragment
  certified group and rejects aggregation when driver cost, vehicle-labelled
  switch cost, a candidate pool, or a Stage-1 no-good cut would make the
  representation non-equivalent. Fixed vehicle and vehicle-day costs remain
  linked to the aggregate path count; fuel, CO2, startup, and terminal-return
  fuel terms use the certified representative's identical coefficients.
- The A/B collector now reads
  `stage1_exact_combustion_clone_flow_aggregation_audit` before its legacy
  Phase-4 field. Added a Phase-3 regression covering aggregate/discrete
  Stage-1 objective equality, complete recovered dispatch, and representation
  telemetry. Verification:
  `C:\master-course\.venv\Scripts\python.exe -m pytest -q
  tests\test_integrated_actual_cost_objective.py
  tests\test_lazy_fragment_performance_diagnostic.py
  tests\test_milp_strict_coverage_metadata.py` (`90 passed`), plus
  `python -m py_compile src/optimization/milp/solver_adapter.py
  scripts/build_lazy_fragment_performance_diagnostic.py` and
  `git diff --check`.
- A fresh clean-SHA 264-trip AB/BA x5 run is still required. No small-instance
  test is presented as a full-scale representation or runtime result.

## 2026-08-22: same-SHA Phase-3 baseline, fixed-decision stress, and 40-trip oracle completed

- A clean `a49716638a1d15567c190798f37b60e3b7920743` Phase-3 run completed at
  `output/2026-08-22/run_20260822_2125/`. It served 264/264 trips and passed
  independent physical validation, 24/24 hourly Rolling, executed-day
  accounting, SHA consistency, and the no-fallback/no-post-solve-repair gates.
  The sole final-cost source is
  `rolling_hourly_chain/executed_day_accounting.json`, which reports
  `64,422.491318 JPY`. Stage 1 ended at its 900-second limit with a certified
  `19.227307%` gap, so this is an accepted feasible/cost-accounting result,
  not an optimality result.
- `scripts/run_fixed_solution_stress.py` was executed without reoptimization
  against that exact same-SHA source, writing
  `output/diagnostics/fixed_solution_stress_a497166_20260822/`. The stress
  manifest fixes the 264-trip scope, 60 vehicles, six chargers, seed 42,
  four Gurobi threads, 900-second limit, and all source-artifact hashes.
  Initial-SOC minus five percentage points remained physically valid and had
  a 0 JPY fixed-decision delta. BEV-energy +10%/+20%, travel time +10%,
  PV -20%, one used-charger outage, and the combined case all failed the
  independent fixed-decision physical/PV checks. Their cost fields are
  correctly `null`; no infeasible fixed schedule was assigned an invented
  additional cost.
- The bounded integrated oracle was rerun from the same clean SHA with
  `--trip-counts 8 12 24 40`, producing
  `output/verification/small_integrated_oracle_scale/a497166/`. Each Phase-4
  reference reached `optimal` with zero final MIP gap. The 24- and 40-trip
  Phase-3 accounting deltas are within the documented 1e-5 JPY tolerance
  (ApproxGap `0.0`); the 8- and 12-trip exact costs are numerically zero, so
  relative gaps remain intentionally `not_identifiable_zero_reference_cost`.
  The 40-trip run has a different optimal powertrain-assignment hash, while
  cost equality remains within tolerance. This certificate is bounded
  small-instance evidence only and is not evidence of 264-trip optimality.
- Commands run:
  `C:\master-course\.venv\Scripts\python.exe scripts\run_fixed_solution_stress.py --source-run output/2026-08-22/run_20260822_2125 --optimization-request output/thesis_sensitivity_charger_capacity_20260822_359cd36/cases/CHARGER_COUNT_6/frontend_optimization_request.json --output-dir output/diagnostics/fixed_solution_stress_a497166_20260822`
  and
  `C:\master-course\.venv\Scripts\python.exe scripts\build_small_integrated_oracle_scale_certificate.py --scenario-id b23fd26c-1233-4c73-bb9e-bdb8b1584760 --prepared-input-id prepared-ee27696fc37f0c7a-f1e18f252e336f1f-8acc7b3a --output-dir output/verification/small_integrated_oracle_scale/a497166 --trip-counts 8 12 24 40 --depot-id tsurumaki --service-id WEEKDAY --vehicles-per-type 5 --time-limit-sec 300 --random-seed 42`.
  The focused implementation/regression suite remains
  `49 passed` for the stress, serializer, A/B harness, and strict-coverage
  metadata tests; no model code was changed while these two executions ran.

## 2026-08-22: Phase-3 pure-ICE A/B stopped on missing representation evidence

- The first fresh Phase-3 child at clean `c80fc26` completed 264/264 service,
  independent physical validation, 24/24 Rolling, and accounting, but its
  canonical metadata contained no
  `integrated_exact_combustion_clone_flow_aggregation_audit`. Code inspection
  confirmed the clone aggregate model is currently built only in the
  integrated Phase-4 path; the Phase-3 Stage-1 formulation therefore did not
  change representation. The parent and incomplete second child were stopped
  rather than spending the remaining nine runs on an invalid A/B.
- `build_lazy_fragment_performance_diagnostic.py` now requires a matching
  representation audit in every child immediately after collection, as well
  as at comparison finalization. `tests/test_lazy_fragment_performance_diagnostic.py`
  now covers a missing audit and requires `FAIL_CORRECTNESS`.
- The partial directory
  `output/diagnostics/pure_ice_aggregation_phase3_ab_c80fc26_20260822/` is
  diagnostic only. It is not a Phase-3 A/B result. A Stage-1 exact aggregate
  implementation and recovery proof are required before retrying the
  AB/BA x 5 experiment.

## 2026-08-22: pure-ICE A/B harness is now Phase-3-only

- The previous repeated A/B artifact was discovered to have executed
  `phase4_integrated`; it cannot support the requested deployed-method claim.
  `scripts/build_lazy_fragment_performance_diagnostic.py` now compiles a
  documented Phase-3 request from the frozen source request, changes only the
  mode, removes only Phase-4-specific fields, and stores both requests plus
  the transformation. Each child rejects any run whose requested/resolved/
  executed phase is not `phase3_two_stage`.
- Added Stage-1 Gurobi model telemetry (binary, integer, continuous, and
  nonzero counts) to the existing solver metadata and exports it through the
  MILP engine for the A/B artifact. The run-level collector now reads Phase-3
  Stage-1 build/solve/bound/gap/node fields rather than integrated-search
  fields; it continues to mark Gurobi presolve time unavailable when not
  exposed.
- Updated `tests/test_lazy_fragment_performance_diagnostic.py` and
  `tests/test_milp_strict_coverage_metadata.py`. Focused verification command:
  `.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_lazy_fragment_performance_diagnostic.py
  tests\\test_milp_strict_coverage_metadata.py`. A fresh clean-SHA ten-run
  AB/BA experiment remains required; no historical Phase-4 value is relabelled.

## 2026-08-22: reproducibility snapshot records physical RAM without psutil

- The first clean Phase-3 charger execution exposed that the optional `psutil`
  probe left `memory_total_bytes` null. Replaced that dependency-only behavior
  with a fallback to Windows `GlobalMemoryStatusEx` (and POSIX `sysconf` when
  applicable), while persisting `memory_probe_source` and any probe error.
  `runtime_environment` is now schema `v3`; the local probe records
  `34,033,328,128` bytes from `windows_GlobalMemoryStatusEx`.
- Updated `bff/services/optimization_run/input_provenance.py` and
  `tests/test_run_input_provenance.py`. Focused verification:
  `.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_run_input_provenance.py
  tests\\test_thesis_sensitivity_matrix.py
  tests\\test_frontend_artifact_completeness.py` (`58 passed`), plus direct
  runtime-snapshot inspection and `git diff --check`.

## 2026-08-22: 6-port Phase-3 charger run completed as a gap-missed diagnostic

- At frozen clean SHA `359cd3617206ac1d3e2ae9ff849c72e0697dffdc`,
  `CHARGER_COUNT_6` completed its 264-trip Phase-3 run at
  `output/thesis_sensitivity_charger_capacity_20260822_359cd36/`. The case
  has a complete 240-artifact bundle, exact requested/resolved/executed Phase
  3 evidence, 264/264 service, independent physical validation, and accepted
  Rolling/accounting. Its final canonical accounting cost is 64,422.491318
  JPY.
- Stage 1 stopped at the 900-second limit with a certified 19.227307% gap;
  the 1% acceptance gate is false. Consequently the matrix case is
  `DIAGNOSTIC`, `NOT USED FOR RESEARCH CONCLUSIONS`, and no charger-response
  claim is made. The runner stopped before 8/10-port results were created.

## 2026-08-22: disabled Phase-3 composition search no longer breaks finalization

- The first corrected 264-trip `CHARGER_COUNT_6` run at clean SHA
  `8044ab8995939382d68e1a1600ca6d3853df3435` completed feasible Stage 1,
  optimal Stage 2, and accepted Rolling, but the BFF then failed finalization:
  it required `stage1_used_powertrain_composition_search.{json,csv}` even
  though the solver correctly recorded that optional search as disabled and
  emitted no such files. The bundle remains a failed diagnostic and is not
  used as sensitivity evidence; the queued 8/10 cases were stopped.
- Added `_requires_two_stage_composition_certificate` so the artifact contract
  requires this evidence only for a research two-stage run whose solver
  metadata explicitly says the composition search was enabled. This preserves
  the strict validation when the claim is made without inventing disabled-mode
  artifacts. Focused verification:
  `.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_frontend_artifact_completeness.py
  tests\\test_thesis_sensitivity_matrix.py
  tests\\test_run_input_provenance.py` (`58 passed`), plus `git diff --check`.
  A fresh clean-commit 6/8/10 Phase-3 run remains required.
## 2026-08-22: fixed-decision stress CLI made reproducible

- Added `scripts/run_fixed_solution_stress.py`. It reuses the source run's
  frozen `effective_scenario.json`, `canonical_solver_result.json`, and
  frontend request; `ProblemBuilder` rebuilds the canonical 264-trip problem
  without a solver invocation. It writes a hash manifest plus JSON/CSV stress
  results only into a new output directory.
- The CLI requires a clean worktree and exactly matching source/evaluator Git
  SHA. It also rejects a non-Phase-3 source and a reconstructed trip scope
  that differs from the saved canonical assignment. This prevents a later
  code revision or mismatched prepared input from being relabelled as a
  post-solve stress result.
- Verification: `python -m py_compile scripts/run_fixed_solution_stress.py`
  and `pytest -q tests/test_fixed_solution_stress.py
  tests/test_canonical_graph_export_parity.py` (`28 passed`). A deliberate
  execution from the dirty implementation worktree returned
  `RuntimeError: fixed-decision stress requires a clean Git worktree` and did
  not create an output directory. After committing at `4194c24`, the same
  historical source also failed closed on its different SHA
  (`359cd36` vs `4194c24`) and again created no output. A new same-SHA source
  baseline remains required before this CLI may produce evidence.

## 2026-08-22: fixed-decision stress evaluator added without reoptimization

- Added `src/optimization/validation/fixed_solution_stress.py`. It applies
  only declared input changes to a copied canonical problem and retains the
  serialized day-ahead decision unchanged. The standard catalog covers BEV
  energy +10%/+20%, travel time +10%, PV -20%, one *actually used* charger
  outage, initial SOC -5 percentage points, and their combined case.
- Every case is independently reconstructed with
  `validate_physical_event_schedule`. A PV-source flow above the perturbed
  per-slot supply is an explicit violation. If any physical/PV gate fails,
  `fixed_decision_cost_jpy` and `additional_cost_jpy` are `null`; an
  infeasible fixed schedule is never turned into a fabricated realized-cost
  comparison. The artifact explicitly records `reoptimization_performed=false`.
- Added `tests/test_fixed_solution_stress.py`. Focused verification:
  `C:\\master-course\\.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_fixed_solution_stress.py
  tests\\test_canonical_graph_export_parity.py -k
  "fixed_solution_stress or result_serializer_restores_complete"` (`6
  passed`). A run-level CLI still needs to materialize the exact prepared
  problem and write these outputs beside the frozen source run.

## 2026-08-22: canonical fixed-decision plan restoration added

- Added `ResultSerializer.deserialize_plan(problem, serialized_plan)` as the
  inverse of the existing canonical plan serializer. It restores duties,
  charging/refueling sessions, source-flow maps, SOC trajectories, cost
  ledgers, and metadata from `canonical_solver_result.json` without invoking
  any optimizer. This is the reusable foundation for the required
  fixed-decision stress checks; the rolling reoptimizer remains intentionally
  unsuitable because it drops charging decisions before re-solving.
- Added a lossless serializer round-trip regression test. Verified with
  `C:\\master-course\\.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_canonical_graph_export_parity.py -k
  result_serializer_restores_complete` (`1 passed`) and
  `python -m py_compile src/optimization/common/result.py`.
- This change does not yet claim a stress result or change Phase-3 behavior.
  The next change must apply explicitly declared perturbations to a copied
  canonical problem, preserve the saved decision, independently validate it,
  and label the unmodified-plan cost as unavailable when a physical violation
  prevents an honest realized-cost claim.

## 2026-08-22: run-provenance environment snapshot expanded

- Reused the existing pre-solve `optimization_parameters.json` provenance
  writer instead of adding a parallel artifact. Its `runtime_environment`
  snapshot now records the OS, logical CPU count, processor label, total RAM
  when probeable, Gurobi version, and `gurobipy` version alongside the already
  recorded Python executable/version. An unavailable RAM probe is recorded as
  an explicit error rather than failing or inventing a value.
- The first Phase-3 charger run was stopped before completion because this
  pre-solve environment contract was incomplete. A fresh clean-commit run is
  required; no partial output is evidence.

## 2026-08-22: full-scale sensitivity matrix corrected to Phase 3

- During execution review, the new `CHARGER_COUNT_6` request was found to
  force `phase4_integrated` on the 264-trip case. The process and its local
  BFF were stopped before completion; no artifact from that attempt is used as
  a result. The thesis target is the deployed `phase3_two_stage` method;
  Phase 4 remains limited to the separately bounded integrated-oracle scale
  certificate.
- Changed `scripts/build_thesis_experiment_matrix.py` to prepare and submit
  `phase3_two_stage`, updated the matrix schema, and changed
  `scripts/run_thesis_sensitivity_matrix.py` to fail closed unless the solver
  records Phase 3 as requested, resolved, and executed. The vehicle-day
  sensitivity audit now checks the same model identity instead of the
  Phase-4-only actual-cost contract. The compiler additionally removes the
  Phase-4-only `integrated_actual_cost_objective` field inherited from an old
  exported base request.
- Updated `tests/test_thesis_experiment_matrix.py` and
  `tests/test_thesis_sensitivity_matrix.py`. Pending verification command:
  `.venv\\Scripts\\python.exe -m pytest -q
  tests\\test_thesis_experiment_matrix.py
  tests\\test_thesis_sensitivity_matrix.py`. A fresh clean-commit Phase-3
  charger-capacity execution remains required after this change.

## 2026-08-22: charger-capacity sensitivity made executable and auditable

- Extended the existing frontend-only thesis matrix with 6/8/10 port cases.
  Every member explicitly selects the generated 90-kW single-port inventory;
  this avoids silently ignoring `charger_count` when the persisted selected
  inventory is active. The solver-visible effective count is fail-closed in
  `run_thesis_sensitivity_matrix.py`; source/power remain in the frozen Prepare
  request because the existing result metadata does not export those fields.
- Updated `tests/test_thesis_experiment_matrix.py` and
  `tests/test_thesis_sensitivity_matrix.py`; focused result: `29 passed`.
  No formal run was started from this dirty worktree. Initial-SOC sensitivity
  remains deliberately unimplemented here: the existing global setting is only
  a fallback behind explicit vehicle SOC and cannot honestly represent -5
  points without an explicit BFF policy path.

## 2026-08-22: repeated isolated-process pure-ICE A/B measurement completed

- Executed the existing harness from clean frozen commit
  `7ae60bef01cd6c30d7c82befcae28c3de692d2df`:
  `.venv\\Scripts\\python.exe scripts\\build_lazy_fragment_performance_diagnostic.py
  --run-pure-ice-aggregation-ab --scenario-id
  b23fd26c-1233-4c73-bb9e-bdb8b1584760 --prepared-input-id
  prepared-4df75af5493bd446-f1e18f252e336f1f-8acc7b3a
  --optimization-request
  output\\thesis_sensitivity_powertrain_low_pv_20260815_94ce217_bev12_900s\\cases\\BEV_ENERGY_1.2\\frontend_optimization_request.json
  --output-dir output\\diagnostics\\pure_ice_aggregation_ab_repeated_7ae60be
  --ab-repetitions 5 --small-exact-parity-passed`.
- The resulting `repeated_comparison.json` records AB/BA/AB/BA/AB, five
  isolated processes per representation, same SHA and prepared-input hash for
  every case, and ten passing individual correctness checks: 264/264 coverage,
  physical validation, 24-hour Rolling, accounting, and no fallback/repair.
- Median discrete/aggregate model sizes are 780,113/536,180 variables and
  355,581/233,579 constraints. Median complete model-build time falls from
  80.547 to 60.066 seconds, but median solver time rises from 624.566 to
  644.374 seconds. The two medians have the same incumbent (59,466.604450 JPY),
  certified bound (56,086.529926 JPY), and 5.683988% certified gap. Measured
  process-tree RSS medians are 3,699,630,080 and 3,698,847,744 bytes.
- Verdict: `PASS_STRUCTURAL_ONLY`. This verifies the bounded formulation-size
  reduction but explicitly rejects a runtime-speedup claim. Separate presolve
  time remains `null` with availability metadata because the Gurobi artifact
  does not publish it. The 1% target remains unmet, so these data are not a
  formal full-network optimality or research-release certificate.
- Verification after the run will use
  `.venv\\Scripts\\python.exe -m pytest -q tests\\test_lazy_fragment_performance_diagnostic.py
  tests\\test_integrated_actual_cost_objective.py tests\\test_readme_navigation.py`
  and `git diff --check`; subsequent sensitivity/stress work must start from a
  new clean commit rather than modify this measured SHA.

## 2026-08-22: repeated isolated-process pure-ICE A/B harness

- Extended the existing `scripts/build_lazy_fragment_performance_diagnostic.py`
  rather than adding a parallel benchmark. The default full A/B mode now
  requires five pairs and orders them AB/BA/AB/BA/AB, giving five executions
  each for `discrete` and `pure_aggregate`.
- Each planned run starts a fresh Python child which invokes the normal BFF
  worker once under its own clean-SHA pre/post gate. The parent rejects any
  source SHA/worktree drift, freezes the request bytes before the first child,
  verifies the prepared-input SHA before/after every child and in its emitted
  run artifact, records child command/run/job provenance, and measures maximum
  sampled concurrent RSS over the full child-process tree; this includes the
  virtual-environment launcher child on Windows.
- The output contract is now
  `pure_ice_aggregation_ab_v2_repeated_processes`: run-level metrics include
  solver/model/correctness data and RSS, while `repeated_comparison.*` reports
  median, Q1/Q3, minimum, maximum and IQR. Separate Gurobi presolve time is
  retained as explicit `null` with availability metadata because the current
  solver artifact does not expose it; it is never fabricated.
- A review found that sampling only the launcher PID under-reports RSS on
  Windows. The implementation now enumerates descendants and samples their
  concurrent working sets; a live 80 MB child allocation test observed
  96,841,728 bytes. Focused tests and integrated actual-cost regressions:
  `75 passed`. The completed repeated run is recorded above; the old one-pair
  `a145cf3` artifact remains historical `PASS_STRUCTURAL_ONLY` only.
- The first frozen `af452a3` launch stopped before any solver call: the hidden
  child CLI inherited the parent parser's required `--output-dir` contract but
  the parent command omitted that syntactic argument. The failure is retained
  in `output/diagnostics/pure_ice_aggregation_ab_repeated_af452a3/`; no case
  metric or research conclusion exists. The child now receives its own
  run-directory output argument, and parser/focused regression checks pass
  (`10 passed`) before a new frozen commit is made.

## 2026-08-22: corrected electricity-price diagnostic tranche completed

- After the fail-closed TOU-precedence repair, executed only
  `ELECTRICITY_PRICE_24`, `ELECTRICITY_PRICE_30`, and
  `ELECTRICITY_PRICE_36` through the frontend/BFF path from clean frozen
  commit `c4c2ef4aca3f6bb156da10dda68be78867ee23ce`. The immutable result
  bundle is `output/thesis_sensitivity_electricity_low_pv_20260822_c4c2ef4/`;
  the run manifest confirms unchanged Git SHA and matched non-varied controls.
- The audit proved that the effective grid marginal prices were 24, 30, and
  36 JPY/kWh respectively (diesel remained 145 JPY/L). Every case served
  264/264 trips, had zero unserved trips, passed physical validation,
  24-step Rolling/accounting, artifact/provenance, and effective-parameter
  gates. The BFF started only for this frozen tranche was stopped after the
  runner completed.
- All three cases remain `DIAGNOSTIC`, `NOT USED FOR RESEARCH CONCLUSIONS`:
  each reached `time_limit` without the declared 1% MIP certificate
  (5.099181%, 5.227442%, and 5.330183%). The 24/30 JPY incumbents were
  identical on BEV/ICE trips (78/186) and grid import (12.528570 kWh); at 36
  JPY they were 76/188 and 0 kWh. This is an observed incumbent change, not
  evidence of an optimal economic-response direction.
- Execution command: `.venv\\Scripts\\python.exe
  scripts\\run_thesis_sensitivity_matrix.py --scenario-id
  b23fd26c-1233-4c73-bb9e-bdb8b1584760 --base-url http://127.0.0.1:8000
  --base-prepare-request
  output\\thesis_sensitivity_powertrain_low_pv_20260815_94ce217_bev12_900s\\cases\\BEV_ENERGY_1.2\\frontend_prepare_request.json
  --base-optimization-request
  output\\thesis_sensitivity_powertrain_low_pv_20260815_94ce217_bev12_900s\\cases\\BEV_ENERGY_1.2\\frontend_optimization_request.json
  --output-dir output\\thesis_sensitivity_electricity_low_pv_20260822_c4c2ef4
  --case-id ELECTRICITY_PRICE_24 --case-id ELECTRICITY_PRICE_30 --case-id
  ELECTRICITY_PRICE_36 --timeout-seconds 7200 --poll-interval-seconds 10`.

## 2026-08-22: fail-closed integrated-oracle scale certificate

- Audited `scripts/audit_small_integrated_weather_milp.py` before extending
  its 10-trip workflow. The Phase-4 case did not request
  `integrated_actual_cost_objective`, while the exact-oracle predicate omitted
  the already exported `objective_is_actual_cost` field. Archived sunny and
  rain audits consequently reported exact eligibility even though both stored
  `objective_is_actual_cost=false`.
- Phase-4 oracle cases now explicitly request the canonical actual-cost
  contract and disable their Phase-3 seed. Eligibility requires the request,
  structural application, actual-cost flag, accounting-objective equality,
  balanced EV energy inventory, exact solver termination, complete coverage,
  and all hard validation checks. Phase-3 comparison behavior is unchanged.
- Added `scripts/build_small_integrated_oracle_scale_certificate.py`. It runs
  the existing audit in a separate process for each requested trip count
  (default 8, 12, and 24), rejects a dirty or drifting Git state, refuses to
  overwrite an output bundle, hashes the prepared input and artifacts, and
  emits JSON/CSV/Markdown evidence. Any missing size, non-optimal integrated
  solve, incomplete Phase-3 schedule, accounting-contract failure, or negative
  comparison delta blocks the entire certificate.
- The first clean execution exposed a separate provenance defect before any
  solve: materialization let an empty current `comparison_type` erase the
  prepared input's explicit `same_service_date_pv_counterfactual` contract,
  causing an `actual_weather_date_differs_from_service_date` rejection. The
  audit now restores only explicit prepared comparison fields and rejects any
  conflicting non-empty current value. A strict build-only check records
  `comparison_type=counterfactual_weather_profile`, no calendar errors, and
  preserves the 2025-08-05 service date with the frozen 2025-08-10 PV source.
- The resulting 8/12/24 run then exposed the next fail-closed boundary: the
  prepared `research_lexicographic_v1` preset caused Phase 4 to optimize used
  vehicle-days before canonical cost, so its own metadata correctly reported
  `integrated_actual_cost_objective_requested=false`. The reference-only
  Phase-4 path now clears that preset and records
  `scalar_canonical_actual_cost`; Phase 3 retains its deployed policy and its
  final canonical accounting cost is the comparison quantity. The blocked
  `output/verification/small_integrated_oracle_scale/37a1fad/` bundle is kept
  as diagnostic evidence and will not be relabelled.
- A subsequent clean `7b5a392` scale run made all three Phase-4 cases exact,
  but the 8- and 12-trip reference costs were numerically zero. The former
  reporting denominator floor of 1 JPY made floating-point noise appear as a
  small signed relative advantage. The report now preserves the raw delta,
  emits an approximate gap only when the exact reference cost is above
  `1e-5 JPY`, and marks zero-reference cases `not_identifiable_zero_reference_cost`.
  That `7b5a392` bundle remains diagnostic for its own SHA; a new clean run is
  required after this reporting correction.
- The required fresh execution completed at clean commit
  `242f35e3698052d3e6e314ff8a377100b515e437` in
  `output/verification/small_integrated_oracle_scale/242f35e/`: all 8/12/24
  Phase-4 references reached `optimal` with zero final gap and all certificate
  gates passed. The 24-trip Phase-3/Phase-4 cost delta is within tolerance and
  reports approximate gap `0.0`; 8 and 12 retain their raw near-zero deltas
  but are explicitly not identifiable as relative gaps. The scope remains
  bounded small-instance formulation evidence only, not 264-trip global
  optimality, production cost performance, or a release-ready conclusion.
- Focused oracle gate, scale aggregation, immutability, and input-validation
  tests plus integrated-cost regressions pass (`133 passed`). No archived
  10-trip result is relabelled by this implementation change.

## 2026-08-21: same-SHA pure ICE aggregation A/B harness

- Added a diagnostic-only, process-local representation selector around the
  existing `exact_combustion_clone_flow_aggregation_enabled` implementation.
  The default remains `pure_aggregate`; the selector is not part of the BFF,
  frontend, public API, prepared-input schema, or scenario JSON. Both cases
  therefore reuse the same objective, costs, constraints, successor network,
  canonical prepared input, and normal BFF/24-step Rolling finalization path.
- Extended the exact small fixture so discrete and pure-aggregate runs must
  match objective, full coverage, normalized duties, ICE fuel, deadhead, CO2,
  vehicle-days, and canonical-ID recovery without duplicates or missing
  duties. The audit now records the requested and actual representation plus
  vehicle-labelled and aggregate-network variable counts.
- Added read-only integrated MIP telemetry for root-bound availability,
  first-incumbent objective/time, requested-gap time, and final LP iteration
  count. Initial continuous-variable and nonzero-coefficient counts are also
  persisted. These callbacks do not terminate search or change parameters.
- Extended `scripts/build_lazy_fragment_performance_diagnostic.py` with a
  synchronous BFF A/B mode. It executes A=`discrete` once and
  B=`pure_aggregate` once, then writes provenance, model-size, timing, solver,
  physical-validation, Rolling, accounting, logs, comparison, and artifact
  hashes to `output/diagnostics/pure_ice_aggregation_ab_<short-sha>/`.
- Focused regression using the project environment passed:
  `.venv/Scripts/python.exe -m pytest -q tests/test_lazy_fragment_performance_diagnostic.py tests/test_integrated_actual_cost_objective.py`
  -> `72 passed`. The system Python 3.14 executable has no `pytest`; it was not
  used as test evidence.
- Claim scope remains diagnostic. No column generation, set partitioning,
  high/low-PV formal pair, M0-M3 comparison, sensitivity sweep, or time-step
  comparison is authorized in this checkpoint.
- The clean-commit A/B measurement is complete at
  `a145cf3a8b9cba0e4d97c48f800fba9ff07a1e69`, using the canonical prepared
  input `prepared-4df75af5493bd446-f1e18f252e336f1f-8acc7b3a` and the unchanged
  low-PV `BEV_ENERGY_1.2` Phase-4 integrated request. Both runs used seed 42,
  four threads, a 900-second limit, and a requested 1% gap.
- A=`discrete` and B=`pure_aggregate` both served 264/264 trips with 17 ICE
  buses, produced the same 61,970.856672 JPY incumbent and 57,986.661708 JPY
  certified bound, and passed physical validation, 24/24 Rolling, accounting,
  and fallback/repair checks. Their certified gaps were equal at 6.429143%,
  so the 1% target was not met.
- B reduced total variables from 780,113 to 536,180, binaries from 739,728 to
  507,244, constraints from 355,581 to 233,579, and nonzero coefficients from
  3,409,213 to 2,044,502. Complete model-build time fell from 167.473 to
  124.684 seconds, but total solver time increased from 476.701 to 517.938
  seconds. The only supported verdict is `PASS_STRUCTURAL_ONLY`.
- The authoritative bundle is
  `output/diagnostics/pure_ice_aggregation_ab_a145cf3/`. Its seven recorded
  hashes and both source-input hashes were reverified; the focused regression
  remains `72 passed`. Prompt B and all broader experiments remain unexecuted.

## 2026-08-15: frozen pure-aggregate 264-trip diagnostic completed

- Stopped new optimization work at the requested checkpoint after completing
  one frozen frontend/BFF run from clean `main` commit
  `94ce217a4daab48b08646be85e18c388289bf026`. The authoritative result is
  `output/2026-08-15/run_20260815_1155` (job
  `947648c9-1024-47bb-84b8-45bff2b41f3b`). The polling client hit its own
  short shell timeout after submission, but the persisted BFF job continued
  without restart and completed normally; the partially populated
  `output/thesis_sensitivity_powertrain_low_pv_20260815_94ce217_bev12_900s`
  directory is therefore not the result authority.
- The BFF performed fresh Prepare for the same controlled low-PV sensitivity
  input: 264 trips, 60 active vehicles, 10 chargers, 11,310 complete feasible
  successor arcs, service date 2025-08-05, PV source date 2025-08-10,
  1,000 kW rated PV, 6,000 kWh / 900 kW BESS with 3,000 -> 3,000 kWh terminal
  target, flat 30 JPY/kWh grid energy, zero demand charge, BEV trip-energy
  scale 1.2, four Gurobi threads, 1% requested gap and a 900-second shared
  Phase-4 budget.
- Relative to the original labelled flow (`10a6621`) and the layered network
  with continuous labels (`f1690c6`), the pure network produced the following
  frozen measurements:

  | Metric | `10a6621` labelled | `f1690c6` layered + labels | `94ce217` pure aggregate |
  |---|---:|---:|---:|
  | Initial variables | 780,113 | 848,980 | 536,180 |
  | Initial binary variables | 739,728 | 507,194 | 507,244 |
  | Initial constraints | 355,581 | 286,282 | 233,579 |
  | Pre-optimize wall time | 166.509116 s | 165.812070 s | 130.419562 s |
  | Gurobi optimize time | 474.988037 s | 474.744153 s | 505.784332 s |
  | Integrated wall time | 644.478106 s | 642.979000 s | 637.485161 s |
  | Shared Phase-4 wall time | 906.442815 s | 905.939554 s | 903.051735 s |
  | Incumbent | 61,883.346234 JPY | 61,883.346234 JPY | 61,883.346234 JPY |
  | Certified bound | 57,986.661708 JPY | 57,986.661708 JPY | 57,986.661708 JPY |
  | Certified gap | 6.296823% | 6.296823% | 6.296823% |
  | Explored nodes | 1 | 1 | 1 |

- The v3 certificate removed 302,550 vehicle-labelled flow variables, added
  70,067 aggregate/layer/reset integer variables, and reports a net 232,483
  binary-variable reduction. The extra 50 binaries relative to v2 are the
  intentionally retained canonical activation labels. Model construction is
  35.39 seconds faster than `f1690c6`, but Gurobi optimization is 31.04
  seconds slower; total integrated time improves by only 5.49 seconds and the
  bound/gap are unchanged. This is a useful negative result: removing the
  continuous extension reduces model size and construction cost, but does not
  resolve the root-proof bottleneck.
- The incumbent remains useful only as a feasible candidate: 264/264 trips,
  74 BEV and 190 ICE trips, 32 used vehicles, physical validation `VALID`,
  24/24 accepted Rolling steps, accepted executed-day accounting, exact
  solver/accounting reconciliation, and 240/240 required artifacts. The solve
  stopped at `time_limit`; `mip_gap_target_met=false`,
  `research_submission_ready=false`, and teacher release remains `BLOCKED`.
  No integrated-global-optimality or controlled-PV-pair claim is permitted.
- Resume point: do not repeat this 900-second formulation run. The next
  performance investigation should target the root lower bound/decomposition
  (or introduce a separately labelled approximate method comparable to No06
  or No63), while preserving the exact formulation and claim boundary as the
  baseline. No further solve was started after this checkpoint.

## 2026-08-15: removed continuous exact-clone label extension

- Raised the next P1 performance defect from the `f1690c6` negative run: the
  layered aggregate network reduced binaries and rows but retained all 302,600
  vehicle-labelled assignment/connection/boundary variables as a continuous
  extension, increasing the 264-trip model to 848,980 variables and leaving
  the root proof unchanged.
- Replaced that extended formulation with a pure integral group network for
  the one certified ICE-clone group. The four vehicle-labelled flow families
  are not instantiated for those members. Strict coverage includes the group
  assignment variable directly; single-fragment and layered flow equations
  enforce exact path cover, and canonical depot-reset arcs connect successive
  fragments.
- Preserved every omitted label-specific coefficient through the certified
  representative: trip fuel, connection deadhead fuel/distance, startup and
  terminal-return fuel, CO2, weather-policy coefficient, and return-leg term.
  Driver cost still blocks aggregation because it is path-label-specific.
  Per-vehicle fuel state remains omitted only under the existing conservative
  `K * longest_fragment_fuel <= usable_initial_fuel` proof.
- Retained binary clone activation only for canonical ID selection, added an
  activation prefix, and tied its sum to the integral root-path count. Recovery
  assigns every layered path to the same canonical prefix. Phase-3 warm-start
  initialization now treats those duties as aggregate-represented, seeds all
  aggregate/layer/reset decisions, and overwrites activation starts with the
  canonical prefix before fixed-dispatch recourse certification.
- Updated the audit to
  `exact_combustion_clone_flow_aggregation_audit_v3`. It distinguishes removed
  label-flow variables from retained activation binaries and reports pure
  aggregate semantics; it no longer describes the labelled feasible region as
  relaxed. Application now additionally requires a strictly positive audited
  binary-variable reduction, preventing the layered representation from
  increasing small models.
- Exact regression compares the pure and discrete formulations' objective,
  served trips, path count and recovered IDs, and verifies actual model-size
  reduction (398 -> 300 variables; 58 -> 55 binaries) on the one-trip fixture.
  Two-fragment recovery and complete Phase-3-to-Phase-4 starts also pass. The
  integrated test file passes (`68 passed`), the focused fragment/oracle/
  feedback/research/accounting set passes (`130 passed`), and the full suite
  passes (`1491 passed` in 153.92 seconds).
- The subsequently completed frozen diagnostic and its negative performance
  result are recorded immediately above. Research release remains `BLOCKED`.

## 2026-08-15: literature-checked multi-fragment exact clone network

- Re-read the computation-time tables in `先行文献/No06.pdf`, `No16.pdf`,
  `No63.pdf`, and `No64.pdf`. The fast exact cases mainly optimize charging
  for predetermined vehicle schedules or use at most 98,784 variables. The
  closest assignment-plus-charging study (No06) reports Gurobi 617.6 seconds
  for 50 trips and no feasible Gurobi solution for 200 or 418 trips within six
  hours; the 418-trip 202.3-second value belongs to ALNS-SA. This confirms that
  the current 264-trip complete-network model must reduce its vehicle-labelled
  combinatorics before a comparable exact runtime can be expected.
- Raised and fixed the structural blocker that kept exact ICE-clone flow
  aggregation disabled whenever more than one same-day duty fragment was
  permitted. The audit now derives the exact layer count as the minimum of the
  daily, start, and end fragment limits and certifies fuel redundancy against
  `layer_count * longest_single_fragment_fuel`, including startup, service,
  connection deadhead, and terminal return.
- Added canonical depot-reset enumeration using the same
  `fragment_transition_diagnostic` as physical validation. Reset pairs exclude
  route-band-blocked or time-infeasible fragment boundaries and are hashed;
  the model reconstruction must reproduce both count and hash or it fails
  before optimization.
- Added an integral layered group network. Each layer has binary assignment,
  direct-connection, start, and end variables. A higher-layer start equals its
  incoming reset flow; each prior-layer end has at most one reset successor.
  Aggregate assignment/connection/boundary variables remain linked to the
  continuous exact-clone label extension, and used clone count equals both the
  number of layer-0 roots and final fragment ends net of resets. The recovered
  physical dispatch set and objective are unchanged.
- Complete MIP starts now map all fragments of one Phase-3 vehicle onto
  successive layers and populate reset variables. Solution recovery traces
  each layered path through its reset chain and assigns one canonical clone ID
  to every fragment on that path. Missing trips, shared vertices, cycles,
  non-root fragments without reset predecessors, or unrecovered reset arcs
  raise an error rather than invoking repair.
- The saved 264-trip audit has 25 exact ICE clones, 264 assignment nodes and
  11,310 direct arcs per clone. Its maximum one-fragment fuel is 46.036430 L;
  three fragments require at most 138.109290 L versus 144 L usable initial
  fuel. There are 10,829 valid depot-reset pairs. The projected integer count
  changes from 302,600 vehicle-label binaries to 70,067 aggregate/layer
  binaries, a net reduction of 232,533. Because the label extension remains as
  continuous variables, this is a binary reduction rather than a total-
  variable reduction.
- Added exact small-instance regressions for the multiplied fuel bound,
  discrete-versus-aggregated objective equality, two fragments on one vehicle,
  layered recovery, and a complete verified two-fragment MIP start. The full
  integrated actual-cost test file passes (`68 passed`), the focused solver,
  fragment, oracle, feedback, and research-contract set passes (`128 passed`),
  and the repository regression passes (`1491 passed` in 160.65 seconds). No
  older result is attributed to this formulation.
- Froze commit `f1690c6a9a6145086a96df05193794065e6c2f40`, restarted the
  port-8000 BFF, and reran the identical low-PV `BEV_ENERGY_1.2` case through
  fresh frontend Prepare, Phase 4, 24-step Rolling, physical validation and
  accounting under the same 900-second shared budget, four threads, seed 42,
  and 1% target. The source run is
  `output/2026-08-15/run_20260815_1109`; the immutable bundle is
  `output/thesis_sensitivity_powertrain_low_pv_20260815_f1690c6_bev12_900s`.
- The reformulation was applied to all 25 exact ICE clones with three fragment
  layers and 10,829 certified depot-reset pairs. It relaxed 302,600 labelled
  binaries and added 70,067 aggregate integer variables. Relative to the
  `10a6621` control, initial binary variables fell 739,728 -> 507,194 and rows
  fell 355,581 -> 286,282, while total variables increased 780,113 -> 848,980
  because the labelled extension remained continuous. Pre-optimization wall
  time changed 166.509116 -> 165.812070 seconds and cost-stage solve time
  474.988037 -> 474.744153 seconds.
- The incumbent, bound, gap and tree were numerically unchanged:
  61,883.346234 JPY, 57,986.661708 JPY, 6.296823%, and one explored node.
  Complete shared Phase-4 wall time changed 906.442815 -> 905.939554 seconds,
  and complete frontend-runner wall time was 1,122.593744 seconds. This matched
  negative result disproves a material benefit from binary-only reduction in
  this extended formulation. It does not justify longer limits or a speedup
  claim.
- All 264 trips, physical validation, 24/24 Rolling, canonical accounting and
  clean-SHA provenance passed. `mip_gap_target_met` alone failed, so the case
  and research release remain `BLOCKED`. The next exact change must eliminate
  the continuous vehicle-label connection extension, for example through an
  exact column/duty master with certified recourse. A Lagrangian, ALNS or other
  approximate path is permitted only as a separately labelled comparison mode.

## 2026-08-15: exact bound propagation and complete clone-duty ordering

- Self-review of `run_20260815_0747` isolated the proof bottleneck from the
  feasible-schedule path. The integrated model had 780,112 variables,
  including 678,600 vehicle-labelled connection binaries, and 355,557 rows.
  It retained a verified 61,883.346234 JPY incumbent but spent 2,814 seconds
  at one root node with raw Gurobi bound 0 JPY. The independent certified
  analytical floor was already 57,986.661708 JPY (6.296823% certified gap).
- Raised and fixed a P1 `BestObjStop` defect. Both integrated scalar-cost paths
  computed a valid stop threshold but installed it only if the fixed-recourse
  start already crossed that threshold. `BestObjStop` is now installed whenever
  the certified lower bound yields a finite threshold; later incumbents can
  trigger it. The parameter remains disabled for invalid/blocked certificates
  and is cleared before objectives with different units.
- Replaced the standalone analytical inequality with one continuous
  `integrated_canonical_cost_with_certified_floor` variable. Its lower bound is
  the same integer-valid certificate and an equality ties it to the unchanged
  canonical cost expression. Cost objectives use this proxy; recourse,
  accounting, caps and reported cost continue to use the original expression.
  This changes neither feasible integer schedules nor monetary semantics, but
  prevents an eligible objective from presenting an initial 0-JPY domain.
- Strengthened exact-clone symmetry without successor pruning. Adjacent
  identical vehicles remain ordered by assigned-trip count; equal-count duties
  are additionally ordered by the sum of chronological assignment ranks. Any
  unlabeled duty set can be sorted by this tuple, including multi-fragment
  duties, so the rows preserve an orbit representative. A further start-trip
  order is enabled only when the configured maximum start-fragment count is
  exactly one. Groups with unequal assignment, start or transition domains are
  skipped. The formulation adds no variables and at most three rows per
  adjacent eligible clone pair.
- Added unit/integration regressions for pre-threshold stop installation,
  equal-count label-orbit selection, exact-objective preservation, disabled
  certificate behavior and exported telemetry. Focused Phase-4 tests pass
  (`64 passed`); adjacent lower-bound/research/weather telemetry tests pass
  (`54 passed`). The full repository regression passes (`1487 passed` in
  155.40 seconds). A fresh clean-SHA diagnostic was then required before this
  repair could change the research release decision; its result is recorded
  below.
- Restarted only the port-8000 BFF from clean commit
  `5d0a1c5ed7cb99fb01aa7c036f8e06f65d844273` and reran the low-PV
  `BEV_ENERGY_1.2` case through fresh frontend Prepare, Phase 4, 24 Rolling
  steps, physical validation and accounting with a 900-second Day-ahead
  diagnostic limit. The source run is `output/2026-08-15/run_20260815_0921`;
  the immutable execution bundle is
  `output/thesis_sensitivity_powertrain_low_pv_20260815_5d0a1c5_bev12_900s`.
- The intended proof telemetry changed exactly as designed. Raw Gurobi best
  bound is now 57,986.661708 JPY instead of 0 JPY, equal to the independent
  analytical certificate. The objective proxy count is one, its defining row
  count is one, the certified stop threshold is 58,572.385564 JPY, and
  `integrated_certified_gap_stop_applied=true` even though the initial gap
  exceeded 1%.
- The performance blocker remains. The integrated cost stage used 466.355
  seconds, explored one node, found no better incumbent and retained
  61,883.346234 JPY / 6.296823%. Complete runner wall time was 1,122.977
  seconds. Dispatch, physical, Rolling, cost, CO2 and minimum-SOC results are
  identical to the prior 3,600-second case. This is a valid negative result:
  lower-bound visibility and termination semantics were repaired, but they do
  not tighten the relaxation or improve the incumbent.
- The new chronological-start tie order was not applied: the active model
  declares `max_start_fragments_per_vehicle=100`, so the one-start proof is
  unavailable and its row count is zero. Only the existing 24 activation and
  24 trip-count rows remained. The next performance work must therefore reduce
  or aggregate the 678,600 vehicle-labelled connection binaries using an exact
  duty/path formulation; simply extending wall time is not justified.
- A follow-on exact symmetry row now covers that multi-fragment case without
  changing its fragment allowance. For adjacent exact clones with equal trip
  counts, it orders the sum of chronological assigned-trip ranks. The Big-M is
  the sum of all ranks, which fully relaxes the row whenever the preceding
  clone has at least one more trip. Thus the existing unlabeled feasible set is
  preserved while the current 25-ICE group gains 24 applicable rows. This may
  reduce label symmetry but does not reduce the 678,600 binary count; fresh
  timing evidence remains necessary.
- Focused solver/oracle/feedback regression passes (`83 passed`), followed by
  the full repository regression (`1487 passed` in 158.02 seconds).
- Froze `7fe44ebdee8a211c47704d79b066685582ef72be`, restarted the frontend/BFF
  execution path and repeated the same low-PV `BEV_ENERGY_1.2` 900-second
  diagnostic. The source run is `output/2026-08-15/run_20260815_0948`; its
  immutable bundle is
  `output/thesis_sensitivity_powertrain_low_pv_20260815_7fe44eb_bev12_900s`.
  The model exported 24 trip-count rows, 24 equal-count assignment-rank rows,
  zero start-rank rows and 48 total exact duty-order rows. The zero start-row
  count is expected because the fragment limit remains 100.
- The matched result is a negative performance finding. It retained the exact
  same 61,883.346234 JPY incumbent, 57,986.661708 JPY bound, 6.296823% gap,
  74/190 BEV/ICE trip split and one explored node. Solve time changed from
  467.776 seconds at `5d0a1c5` to 470.404 seconds; complete runner wall time
  changed from 1,122.977 to 1,123.794 seconds. One pair cannot estimate a
  stable runtime distribution, but it disproves a material improvement in this
  diagnostic and gives no basis for a speedup claim.
- The rank-sum row is retained because it is exact and tested, but further
  row-only clone symmetry tuning is stopped. The remaining engineering work is
  to reduce Python/model-construction overhead without changing mathematics,
  then replace or aggregate the 678,600 labelled connection binaries through
  an exact path/network formulation if proof time remains dominant.
- Raised a separate Python/Gurobi construction bottleneck. The four integrated
  unit-interval families were created with one `model.addVar` call per key;
  the measured case therefore made hundreds of thousands of Python API calls
  before optimization. Added a single batching helper that uses `addVars` once
  per family in the all-binary case and partitions a family only when the
  certified exact-clone convexification needs continuous labels. It returns an
  ordinary dictionary in original key order and preserves `[0,1]` bounds and
  the exact binary/continuous classification.
- Added search-profile evidence for the number of batched variables, actual
  API calls, batch-build wall time and full pre-optimization wall time. Unit
  tests cover all-binary and mixed-type families; the Phase-4 integration test
  checks that only its three non-empty families cross the API boundary and
  validates the telemetry. Focused integrated/exactness/
  research-contract regression passes (`134 passed`). The full repository
  regression also passes (`1489 passed` in 164.85 seconds). A frozen-commit
  matched timing run was then performed as recorded below.
- Froze clean commit `10a662159d4b0cd2a26caf8bc162816f67848a22` and
  reran the identical low-PV `BEV_ENERGY_1.2` frontend/BFF case with fresh
  Prepare, the same 900-second/4-thread/1% controls, Phase 4 and 24-step
  Rolling. The source run is `output/2026-08-15/run_20260815_1018`; bundle is
  `output/thesis_sensitivity_powertrain_low_pv_20260815_10a6621_bev12_900s`.
  The prepared input ID and all reported dispatch, energy, cost, CO2 and SOC
  KPIs exactly match the `7fe44eb` comparator.
- Telemetry confirms that 726,120 assignment/connection/start/end variables
  were created with four `addVars` calls in 1.748726 seconds. Complete
  pre-optimization time was 166.509116 seconds versus a derivable 168.229836
  seconds in the prior profile, a 1.720720-second reduction. The cost-stage
  solve instead varied from 469.005764 to 473.556456 seconds; total reported
  solve time varied from 470.403739 to 474.988037 seconds. The incumbent,
  57,986.661708 JPY bound, 6.296823% gap and one explored node were unchanged.
- Complete frontend-runner wall time decreased from 1,123.793917 to
  1,117.950286 seconds, but one unmatched-noise timing pair cannot attribute
  that difference to the batching change, especially because solve time moved
  in the opposite direction. No runtime speedup is claimed. The batching code
  is retained as exact, simpler boundary use with explicit telemetry; the
  experiment shows that the dominant remaining costs are constraint/model
  construction and the labelled root relaxation.
- The `10a6621` run passed 264/264 coverage, physical validation, all 24
  Rolling steps, accounting and clean-SHA provenance. It remains `BLOCKED`
  solely by `mip_gap_target_met`. Further micro-optimization of variable
  creation or row-only symmetry is stopped; the next model work must remove or
  aggregate vehicle-labelled connection variables through an exact duty/path
  formulation while preserving the full successor network.

## 2026-08-15: independent powertrain energy sensitivities

- Raised a Phase-2 identifiability defect during self-review. The existing
  `trip_energy_sensitivity_scale` multiplied BEV kWh and ICE liters by the
  same factor. A dispatch response from that family cannot distinguish BEV
  consumption-model sensitivity from ICE fuel-model sensitivity.
- Added `bev_trip_energy_sensitivity_scale` and
  `ice_trip_fuel_sensitivity_scale` through the typed scenario overlay,
  Quick Setup save/load, Tk input controls, Prepare request, canonical
  `ProblemBuilder`, `OptimizationConfig`, trip-demand provenance and
  optimization metadata. For common factor `s_c`, the model now applies
  `s_BEV = s_c * s_BEV-specific` and
  `s_ICE = s_c * s_ICE-specific` independently.
- Preserved the common factor for immutable historical experiments and for a
  shared distance/demand calibration. It is no longer described as evidence
  for either powertrain coefficient in isolation. The current
  `literature_proxy_v1` remains a deterministic literature proxy: BEV weights
  use distance and duration, ICE weights use distance and declared peak-time
  bands. No unobserved route/direction empirical coefficient was invented.
- Added separate `BEV_ENERGY_0.8`--`1.2` and
  `ICE_FUEL_0.8`--`1.2` frontend/BFF experiment families. Each case fixes the
  other powertrain factor, PV/BESS, timetable, fleet, tariff, solver and
  Rolling controls. The Phase-2 completion gate now requires both one-factor
  families in addition to the legacy common-demand family.
- Fixed a pre-existing schema-boundary P1 found during this work. The runner
  emitted `thesis_sensitivity_execution_v3_turnaround_buffer`, while the
  phase audit and time/energy reporting accepted only v2. A shared contract
  now accepts immutable v2, v3 and current
  `thesis_sensitivity_execution_v4_powertrain_coefficients`, and rejects
  undeclared versions. The matrix schema was later extended to
  `thesis_experiment_matrix_v6_economic_price_sensitivity`.
- Added explicit, frontend-only economic price families: flat grid purchase
  price 24/30/36 JPY/kWh and diesel price 116/145/174 JPY/L. Each case fixes
  the other price, PV/BESS, fleet, timetable, energy factors, solver controls
  and Rolling controls. The runner rejects a case unless the corresponding
  canonical marginal price matches and includes both observed prices in the
  CSV. Stable-control hashes are now checked within, rather than across,
  sensitivity families, excluding only each family’s declared varied input.
  This is execution support; no price sensitivity result is claimed until a
  fresh clean-SHA BFF run completes.
- The first clean `ELECTRICITY_PRICE_24` execution exposed a P1 request
  precedence defect: its base payload retained a one-band 30 JPY/kWh TOU
  schedule, which canonical construction prioritizes over
  `grid_flat_price_per_kwh`; the audit correctly observed 30 rather than 24
  and blocked the case. Price-family request compilation now rewrites an
  explicitly uniform TOU schedule to the declared price and fails closed for
  a non-uniform source tariff. The runner and BFF were stopped before the
  remaining invalid cases could be used. Focused tests: `27 passed`.
- Bumped prepared input to
  `v11_powertrain_coefficient_sensitivity`; pre-change prepared inputs remain
  immutable history and cannot serve as current-SHA execution evidence.
- Added proxy isolation, ProblemBuilder propagation, Quick Setup persistence,
  Prepare payload, one-factor matrix, runner parameter/control audit, schema
  compatibility, reporting, phase-gate and controlled-PV-pair regressions.
  Focused verification: `212 passed`; prepared-input/README regression:
  `192 passed`; full repository regression: `1484 passed` in 155.67 seconds.
  No optimizer was invoked, so the two independent 0.8--1.2 tranches and
  Phase-2 research evidence remain pending.
- After freezing clean commit `b9e5234eede192526b5442cc4bf26b0b96981a0a`,
  restarted only the port-8000 BFF and executed the low-PV
  `BEV_ENERGY_1.2` case through fresh frontend/BFF Prepare, Phase 4, 24-step
  Rolling, physical validation, accounting, immutable-copy and case-audit
  paths. Prepared input was
  `prepared-4df75af5493bd446-f1e18f252e336f1f-8acc7b3a`; source run was
  `output/2026-08-15/run_20260815_0747`.
- The audit proved the intended one-factor contract: common scale 1.0, BEV
  scale 1.2, ICE scale 1.0, unchanged prepared trip-structure hash
  `1c382c9c3dc6eec41173c1c451d790a66ae41ffef5c4bd10d2caabc7826511f9`,
  unchanged Git SHA, complete artifacts, and matching submitted/effective
  controls. It served 264/264 trips with 74 BEV and 190 ICE trips, used 15
  BEVs and 17 ICE buses, passed independent physical validation, accepted all
  24 Rolling steps, and produced accounting-eligible executed cost
  61,883.346234 JPY and CO2 1,046.678340 kg. Minimum executed BEV SOC was
  20.389317%, only 0.389317 percentage points above the vehicle limit.
- The solver ended at `time_limit`; solve time was 2,814.453791 seconds,
  certified gap was 6.296823% against the 1% target, and complete runner wall
  time was 3,824.702382 seconds. The signed execution-manifest payload is
  `b9a70a09c44668f3fab949012087ddc40c13c383c21b7e791e7fa37033d3fa2b`
  under
  `output/thesis_sensitivity_powertrain_low_pv_20260815_b9e5234_bev12`.
  Its `BLOCKED` status is correct; the remaining nine independent cases were
  not launched blindly after this proof/runtime blocker became explicit.

## 2026-08-15: high-PV v6 runtime evidence and seed-budget reallocation

- Executed a fresh high-PV case through frontend-equivalent HTTP Prepare and
  `/run-optimization` from clean SHA
  `335331836393c58a1334639e37bbca1ca7f55976`. The saved frontend controls were
  retained: 1,000 kW PV, 6,000 kWh/900 kW BESS with 3,000 -> 3,000 kWh SOC,
  flat 30 JPY/kWh grid energy, zero demand charge, and 20,000 JPY per used bus
  day. Fresh Prepare materialized 264 trips, 60 vehicles, ten chargers and the
  complete 11,310-arc successor network.
- The 600-second Day-ahead exploratory run completed physically feasible with
  30 BEVs/2 ICE buses, 231/33 trips, and 650,390.858978 JPY canonical cost.
  Phase 4 wall time was 607.038977 seconds, the independent bound stayed at
  640,000 JPY, and the certified gap was 1.597633%; therefore it remains a
  diagnostic feasible candidate, not a 1% certificate or formal pair result.
- The v6 neighborhood behaved as designed: 16 candidate slots and 30 seconds
  were reserved, local search began with 28.614860 seconds remaining, 7,305
  suffix candidates were generated, and 57 candidates were evaluated. Suffix
  rounds 1, 2 and 3 successively produced 28/4, 29/3 and 30/2 used-powertrain
  compositions; round 3 was selected. The old v5 high-PV run generated zero
  suffix candidates and stopped at 659,706.858143 JPY after 3,606.883660
  seconds, so v6 improved the incumbent by 9,315.999165 JPY in a much shorter
  diagnostic budget.
- Raised a follow-on P1 search-profile defect: every allowed suffix round
  strictly improved cost, but the server capped the search at three rounds.
  The following route-band phase consumed 23.873713 seconds and generated no
  candidate. The total neighborhood allowance remains exactly 120 seconds,
  but the server profile now allocates 105 seconds to fixed-duty/path-changing
  candidates, 15 seconds to route-band repartition, and up to eight improving
  suffix/swap rounds. This changes only the verified MIP-start upper bound;
  integrated constraints, objective, lower bound, total wall budget, tariff,
  and 1% gate are unchanged.
- The first clean-SHA rerun of that 105/15-second profile at `41250f7` was
  intentionally retained even though it regressed. It served all 264 trips
  and passed physical validation, but exhausted exactly 64 candidate
  evaluations after two suffix rounds, selected 29 BEVs/3 ICE buses at
  655,537.125622 JPY, and ended with a 2.370137% certified gap. The extra
  pre-local wall time let sequential activation consume more of the fixed
  candidate count, so only 17 suffix evaluations remained; the second round's
  truncated candidate-generation list contained no feasible improvement.
- Raised the production candidate ceiling from 64 to 128 without changing the
  105+15=120 second wall allowance. The existing v6 rule therefore reserves
  32 candidate slots for path-changing search, expands suffix candidate
  ranking, and remains wall-clock bounded. This is a generic search-budget
  correction applied identically to both weather cases, not a BEV count
  constraint or weather-specific setting.
- The clean-SHA 128-candidate rerun at `f2f800e` evaluated 94 candidates,
  found a validated 31-BEV/1-ICE incumbent at 649,936.120270 JPY, served
  248/16 trips by powertrain, and passed physical validation in 606.804350
  seconds of Phase 4 wall time. Its bound remained 640,000 JPY and the gap was
  1.528784%, so the 1% cost certificate is still blocked. This establishes
  31/1 feasibility but not 32/0 infeasibility or global cost optimality.
- A separate clean-SHA minimum-ICE-fuel policy diagnostic returned the same
  31/1 composition with 35.884956 L ICE fuel and 649,936.120270 JPY canonical
  cost. It did not export a primary best bound, because the former
  `setObjectiveN` path exposed only an overall time-limit state after the
  interrupted multi-objective solve. The 35.884956 L value is therefore an
  incumbent, not a lower-bound certificate.
- Raised and fixed that P1 evidence defect. The EV-utilization hierarchy is
  now executed as explicit scalar stages under the same shared wall clock:
  coverage when partial service is permitted, minimum ICE fuel, and canonical
  cost only after the fuel optimum is certified and fixed within numeric
  tolerance. Every stage records status, incumbent, best bound, gap, wall
  time and certificate. An unproven fuel stage stops the hierarchy and leaves
  cost-bound fields empty. The unconstrained cost-minimization formulation and
  high/low-PV comparison objective are unchanged.
- The clean-SHA sequential rerun at `0dbdc7d` confirmed that contract: the
  minimum-fuel stage ran for 209.645384 seconds, retained the 35.884956 L
  incumbent, exported a 0 L best bound and 100% primary gap, stopped before
  secondary cost, and preserved the physically valid 31-BEV/1-ICE result.
  Inspection of the same run's seed audit then exposed a separate P1 selection
  bug: several suffix-exchange candidates were already physically feasible at
  32 BEVs/0 ICE and 650,053.898604 JPY, but the seed selector still passed the
  cheaper 31/1 candidate to an explicitly minimum-ICE-fuel solve.
- Fixed the objective mismatch at the seed boundary. Canonical-cost runs keep
  the existing strict-cost-improvement rule. A
  `minimum_ice_fuel_lexicographic` run now selects an independently validated
  zero-ICE seed whenever one exists. This is not a BEV lower-bound constraint:
  zero liters is the analytical lower bound of the nonnegative policy
  objective, and the all-BEV candidate has already passed fixed-assignment
  Stage 2 plus physical validation. The audit now records selection objective,
  zero-ICE availability, and whether that policy seed was selected.
- Clean-SHA frontend revalidation at `abc9257` (`run_20260815_0705`) selected
  the validated 32-BEV/0-ICE seed and served all 264 trips with BEVs. The
  minimum-fuel stage certified incumbent=bound=0 L in 0.209859 seconds and
  zero nodes, then advanced to the all-BEV canonical-cost tie-break stage. The
  latter retained 650,053.898604 JPY but timed out after 207.226111 seconds
  with no useful cost bound, so it is an all-BEV policy incumbent rather than
  a certified minimum-cost all-BEV schedule. Physical validation was VALID and
  Git SHA stayed unchanged during solve.
- Against the physically valid 31-BEV/1-ICE incumbent at 649,936.120270 JPY,
  the all-BEV policy incumbent is 117.778334 JPY more expensive. The measured
  delta is +5,501.622710 JPY electricity, -5,382.743360 JPY fuel, -1.101016
  JPY CO2 and 0 JPY vehicle-day cost. It requires 183.387424 kWh more grid
  energy, giving a dispatch-specific break-even grid price of about
  29.357762 JPY/kWh. Therefore 1,000 kW of sunny PV makes all-BEV operation
  feasible, but does not make this particular marginal replacement cheaper at
  the configured 30 JPY/kWh. The unrestricted cost optimum remains unproven.

## 2026-08-15: literature-driven Phase 4 seed restart and budget repair

- Reviewed the local `先行文献` corpus instead of assuming that reported
  computational times were directly comparable. No16, No61, and No63 obtain
  seconds-to-hundreds-of-seconds results mainly with fixed vehicle operations;
  No63's fastest results use decomposition. No06 is the closest integrated
  dispatch comparison: exact Gurobi took 617.6 seconds for 50 trips and found
  no feasible solution for 200/418 trips within six hours, while ALNS-SA solved
  418 trips in 202.3 seconds. The current exact model has 780,112 variables and
  678,600 vehicle-indexed successor arcs, so candidate time, incumbent time,
  certification time, and end-to-end time must remain separate metrics.
- Raised and fixed a P1 candidate-budget defect. With the production
  `maximum_candidate_evaluations=64`, direct/pairwise checks plus matching
  validation could exhaust all 64 slots. The enabled suffix-exchange,
  powertrain-swap, and identity-exchange loops then executed zero candidates.
  The fixed-duty search now reserves a bounded local-search tail before
  allocating pairwise/matching work.
- Added sequential whole-duty activation restarts. After an exact
  fixed-assignment Stage-2/physical/accounting validation improves the seed,
  the next activation round is anchored on that new incumbent, allowing the
  search to evaluate 13->14->15 BEV transitions rather than only alternatives
  to the original 13-BEV seed. Exact clone classes and depot compatibility are
  preserved, and the final unrestricted Phase 4 MILP remains authoritative.
- Raised and fixed a second P1 budget-contract defect. Route-band repartition
  advertised a separate wall-clock budget, but the shared candidate limit
  silently disabled it whenever fixed-duty search reached the cap. It now has
  a finite additional candidate allowance bounded by the number of active ICE
  duties, and a regression test exhausts the fixed-duty limit before proving
  that route-band repartition still executes and receives full Stage-2
  validation.
- Diagnostic reconstruction of the exact `8066330` low-PV pre-neighborhood
  13-BEV/19-ICE seed reproduced 707,518.152327 JPY. Under the frontend
  75-second/3-second/64-candidate controls, the revised fixed-duty search used
  32.178553 seconds and selected a validated 15-BEV/17-ICE incumbent at
  697,433.686483 JPY. Against the unchanged independent lower bound of
  694,498.136390 JPY, the certified gap is 0.420907%. This is a diagnostic
  replay from preserved input, not fresh formal evidence; no older output is
  relabelled and a clean current-SHA frontend run remains mandatory.
- Mathematical scope is unchanged: no weather bias, BEV lower bound,
  post-solve repair, objective change, feasibility relaxation, or 1% gate
  relaxation was introduced. The audit schema is now
  `phase4_seed_unused_bev_activation_neighborhood_v5` and records all reserved
  limits, sequential rounds, route-band allowance, and evaluated candidates.
- Focused neighborhood and integrated-cost regression passed (`75 passed`).
  The first complete-suite attempt had one transient missing-metadata failure
  in an unrelated tiny MILP consistency test; that test passed immediately in
  isolation and the complete suite then passed cleanly (`1473 passed in
  144.20s`). No failure is suppressed or xfailed.

## 2026-08-15: fail-closed thesis Phase 0--7 ledger

- Raised a P1 research-governance defect: provenance, physical validation,
  accounting, sensitivity, ablation, and equation/test evidence were each
  independently audited, but there was no single machine-readable decision
  enforcing the required Phase 0 -> Phase 7 order. A physically valid or
  visually complete result could therefore be discussed without an explicit
  list of earlier incomplete research gates.
- Added
  `bff/services/optimization_run/thesis_phase_gate_audit.py` and the read-only
  CLI `scripts/audit_thesis_model_phase_gates.py`. The audit re-hashes the
  materialized prepared input through the canonical provenance validator,
  verifies every file recorded by `artifact_completeness.json`, and requires
  clean/unchanged Git state, a formal accepted run, no successor pruning,
  zero fallback/post-solve repair, complete trip coverage, independent
  physical validity, 24-step accepted Rolling, executed-day accounting,
  final cost reconciliation, and the declared MIP-gap target for Phase 0.
- Phase 1 combines the structural route-band-OFF/deadhead, additive 5/10/15
  minute turnaround, explicit compatibility-matrix, and independent event
  checks with fresh accepted optimized route-band and turnaround manifests.
  Structural readiness alone is deliberately insufficient. Later phases
  similarly require the declared energy, vehicle-day, time-step, M0--M3, PV,
  price/infrastructure/SOC, CO2, and final equation-code-test evidence.
- Every sensitivity or ablation artifact must have a valid canonical payload
  SHA-256 and the same frozen Git SHA as the reference run. Evidence from
  different commits cannot be unioned into a completion claim. Unknown or
  missing Phase 6 experiment families fail closed rather than being silently
  ignored.
- The mathematical model and feasible region are unchanged. This is an
  evidence-composition and claim-scope change: `COMPLETE` now means all local
  checks and all earlier phase dependencies pass; otherwise the ledger emits
  `BLOCKED` or `BLOCKED_BY_PREVIOUS_PHASE` with exact check names.
- Added nine focused tests for the Phase 0 baseline, Phase 1 evidence,
  payload tampering, cross-SHA evidence, post-finalization artifact mutation,
  inconsistent sensitivity case identity, run-manifest SHA mismatch,
  independent trip-count mismatch, and compact prepare-snapshot compatibility.
  Focused verification: `9 passed`; related research-contract regression:
  `88 passed`; complete repository regression after the final refactor:
  `1473 passed in 143.70s`.
- Read-only application to the `ac0115e` day-ahead diagnostic correctly leaves
  Phase 0 blocked because the run is nonformal, lacks Rolling/standalone
  physical/final-reconciliation artifacts, and misses the 1% gap. Application
  to the older time-discretization execution revalidates all 240 snapshotted
  files but still blocks Phase 0 on the recorded gap and later phases on
  missing/current-SHA experiments. No old artifact is upgraded.
- Remaining work is intentionally explicit: fresh accepted Phase 0 evidence,
  then same-SHA route-band ON/OFF and turnaround runs, followed in order by
  energy, objective, time-step, M0--M3, full Phase 6, and final equation/report
  integration. The active thesis goal is not complete.

## 2026-08-14: Phase 4 shared wall-clock budget and seed-scope correction

- Raised a P1 runtime-contract defect from a fresh Prepare and normal
  frontend/BFF diagnostic at SHA
  `102546170dc8a07fa91e0b71beaa8c71ca1ea327`. A requested 600-second Phase 4
  run first spent 607.319707 wall seconds in the Phase 3 hand-off and then
  spent another 601.350376 seconds in the integrated Gurobi solve. The Phase 3
  solver itself recorded only 61.586327 seconds; most of its wall time came
  from rebuilding exact used-powertrain-composition models under a 600-second
  Python-side construction allowance. This proves that the prior UI limit was
  not an end-to-end optimization budget.
- The reachable BFF Phase 4 path now disables the inventory-wide Phase 3
  composition sweep and unused-BEV neighborhood for warm-start generation.
  It requests one neutral primary candidate, still requiring Stage 1, exact
  Stage 2, exact trip-set equality, a nonempty plan fingerprint, and an
  independent physical-feasibility pass. This does not freeze the final fleet
  mix: the unrestricted integrated MILP still contains all assignment and
  activation decisions. Explicit Phase 3 experiments retain the wider
  composition and neighborhood controls.
- `OptimizationEngine` now starts one Phase 4 wall clock before the strict
  precheck, subtracts precheck/seed time from the integrated allocation, and
  exports `phase4_shared_wall_clock_budget_v1`. The integrated adapter further
  charges model construction and fixed-dispatch recourse against that
  remaining allocation before setting Gurobi `TimeLimit`. An exhausted budget
  fails closed instead of silently granting another full solver interval.
- `solver_settings.json` now exposes the requested shared budget, precheck and
  seed wall time, remaining integrated budget, total optimization wall time,
  and overrun. The controlled-pair runner rejects the former summed-subphase
  contract and accepts only the bounded primary-seed contract with a small
  audited overrun tolerance.
- The same diagnostic disproved applicability of the new exact ICE clone-flow
  convexification to the current full scenario. Effective
  `daily_fragment_limit=3` and start/end limits of 100 violate its certified
  single-fragment precondition, so `applied=false`, variable count stayed
  780,112, and the final 1.583730% gap was slightly worse than the historical
  1.574005% matched-limit diagnostic. The previous 290,448-binary estimate was
  a hypothetical single-fragment audit and is not runtime evidence.
- Focused shared-budget, integrated-cost, research-contract, and frontend-pair
  regression passed (`126 passed`), followed by the complete repository suite
  (`1450 passed` in 136.86 seconds). A fresh clean-commit 264-trip diagnostic is still
  required before claiming a runtime improvement; no old output is relabelled.
- The subsequent fresh frontend/BFF diagnostic at that commit
  (`output/2026-08-14/run_20260814_2138`, job
  `8a27c63e-27d5-4d84-9a16-dd06bfd588ff`) verified the outer deadline but
  failed the solve contract. Submit-to-terminal was 628.656745 seconds;
  `phase4_shared_wall_clock_budget_v1` recorded 600 seconds requested,
  604.204202 seconds optimization wall time, and 4.204202 seconds overrun.
  The primary-only seed nevertheless took 142.768869 seconds because Stage 1
  set its 80-second Gurobi limit before approximately 60 seconds of model
  construction. It returned a Stage-1 incumbent but no Stage-2 candidate.
- With no verified seed, integrated Phase 4 used its remaining 451.735358
  seconds, found no incumbent, and the nonresearch call produced a diagnostic
  baseline fallback. Artifact completeness then failed on the intentionally
  absent `graph/vehicle_soc_timeseries.csv`; generating fake SOC rows would be
  wrong, so the artifact gate is retained.
- Raised and fixed the nested P1 budget defect: immediately before Stage-1
  optimization, the adapter recomputes the shared time remaining after model
  construction. If the configured Stage-1 and Stage-2 limits no longer fit,
  it scales their split proportionally, so neither stage can claim its old
  full solver allowance after Python construction has consumed the deadline.
  Focused deadline and integrated tests passed (`112 passed`), followed by the
  complete repository suite (`1451 passed` in 160.67 seconds). A second clean
  diagnostic remains required.

## 2026-08-14: exact vehicle-label symmetry reduction

- Added non-increasing total assigned-trip-count ordering for adjacent
  vehicles only when every `ProblemVehicle` solver field and the complete
  assignment and transition-arc domains match. This is an exact relabelling
  cut: any feasible solution can permute identical vehicle IDs into the
  retained order without changing its constraints or objective.
- The first draft used a canonical earliest-fragment prefix state. Review
  rejected it before commit because the all-identical 35-BEV/25-ICE,
  264-trip upper-bound fixture would add about 15,840 continuous variables
  and tens of thousands of constraints while the observed bottleneck is root
  processing. The final formulation
  adds no variables and one dense inequality per adjacent clone pair. Its
  all-identical 35+25 upper-bound fixture adds 58 rows.
- Read-only verification of the historical high-PV `solver_settings.json`
  found one exact 25-ICE group and no BEV group: the 35 BEVs have distinct
  initial SOC, which is solver-relevant. Therefore the actual recorded fleet
  would receive 24 trip-count rows, not 58. The code deliberately does not
  manufacture BEV symmetry by ignoring initial state.
- Symmetry groups fail safe. Unequal/empty assignment domains or unequal
  transition domains receive an explicit skipped audit record, and neither
  trip-count nor activation-prefix cuts are added for that group. The
  transition check is required because successor pruning may preserve a
  baseline arc for only one vehicle ID. Public Phase 3/Phase 4 metadata records
  the schema, eligible/skipped groups, both domain hashes, added rows, zero
  added variables, and orbit-preservation semantics.
- Baseline vehicle labels are ordered by used state, descending assigned-trip
  count, earliest represented trip, then ID. Composition-neighbourhood MIP
  starts apply the same count ordering while remapping all assignment, path,
  activation, and vehicle-day keys consistently.
- Tests cover canonical/swapped label feasibility, unequal-domain skipping,
  partial-start relabelling, warm-start ordering, exact Phase-4 objective
  invariance, Phase-3 metadata, and current full-scope model size. This change
  does not support a runtime claim until a clean frozen-commit matched
  diagnostic is run; the high-PV 1% gap blocker remains open.
- Verification: focused integrated/Stage-1/weather/exactness regression
  `84 passed`; full repository regression `1441 passed`.

## 2026-08-14: literature runtime verification and buffer sensitivity runner

- Rechecked the local prior-work PDFs rather than comparing headline times.
  No06's Table 5 shows 617.6 seconds for Gurobi at 50 trips, no feasible
  Gurobi result for 200/418 trips within six hours, and 202.3 seconds for the
  418-trip ALNS-SA heuristic. No16's 1.5-second result optimizes charging and
  ESS dispatch for a fixed 49-bus/275-trip schedule with 9,946 continuous and
  9,506 binary variables. No64 ranges from 52.41 to 3002.07 seconds on
  31,883--98,784 variables, with a 7200-second/0.5% stop and 80 Xeon cores.
  These findings preserve separate claims for feasible candidates, certified
  gaps, decomposition methods, and heuristics.
- Added a formal `turnaround_buffer_sensitivity` family to the frontend/BFF
  thesis matrix with additive 5, 10, and 15 minute cases. The matrix keeps
  all other families at the current zero-buffer baseline and does not alter
  timetable rows or replace stop-specific base turnaround rules.
- The execution auditor now verifies the effective margin from canonical
  optimization metadata and exports it in JSON/CSV outcomes. Schema versions
  are `thesis_experiment_matrix_v4_turnaround_buffer` and
  `thesis_sensitivity_execution_v3_turnaround_buffer`.
- Focused matrix and execution-contract regression: `23 passed`; broader
  turnaround/Prepare/README regression: `46 passed`; full repository
  regression: `1431 passed`. No solver was invoked by this change, so no
  solve-time improvement or optimized 5/10/15-minute result is claimed.

## 2026-08-14: additive turnaround buffer and Prepare sensitivity certificate

- Added an explicit non-negative `turnaround_buffer_min` to the canonical
  dispatch context. It is added to the stop-specific or default minimum
  turnaround before deadhead travel, so the hard connection rule is now
  documented and implemented as
  `arrival + base_turnaround + operating_buffer + deadhead <= next departure`.
  Existing scenarios retain identical behavior because the default buffer is
  zero. The base rule remains separately inspectable through
  `get_base_turnaround_min()`.
- Propagated the buffer through the canonical `ProblemBuilder`, ProblemData
  adapter, CSV preprocessing, ALNS repair subcontexts, and public solver
  metadata. This prevents a repair or compatibility path from silently
  dropping a nonzero operating margin.
- Added typed scenario/Quick Setup/Prepare fields and round-trip persistence
  for `defaultTurnaroundMin` and `turnaroundBufferMin`. Prepare preserves the
  saved values when an older frontend omits the optional fields, while an
  explicit API value overrides them. The graph preview reads the same values
  as the solver instead of silently reverting to 10+0 minutes.
- Prepare now generates
  `turnaround_buffer_sensitivity_audit_v1` from the route-band-OFF canonical
  problem at 5, 10, and 15 minutes. It exports connection counts, relaxed
  vehicle lower bounds, blocked reasons, infeasibility status, and a SHA-256
  over all non-buffer structural controls. The certificate is valid only when
  connection counts are nonincreasing, lower bounds nondecreasing, and
  interval-only pairs constant.
- Fixed a fail-open defect found during review: when the route-band-OFF audit
  rebuild failed, an empty audit could previously be interpreted as
  `deadhead_missing=0` and therefore READY. Formal readiness now also requires
  an actually checked audit, and release output distinguishes
  `route_band_off_transition_audit_invalid` from a complete audit that found
  missing OD entries.
- Bumped the prepared input schema from `v9_immutable_scope_identity` to
  `v10_turnaround_buffer_sensitivity`; old prepared files remain immutable
  history and must not be reused as current evidence. Formal teacher release
  now fails closed on an invalid turnaround sensitivity certificate.
- Added route-band mode, base turnaround, operating buffer, and connection
  semantics to the Rolling comparison-case control hash. Two cases with
  different transition feasibility can no longer pass a PV-only pair check
  merely because their timetable rows are identical.
- Focused regression covers base-plus-buffer semantics, ProblemBuilder and
  ProblemData propagation, 5/10/15 structural monotonicity, audit-exception
  fail-closed behavior, and teacher-release reason codes. This is structural
  connection evidence only: optimized cost/BEV-trip route-band and buffer
  comparisons still require fresh clean-commit runs. Final verification:
  targeted persistence and new-contract tests `60 passed`, broader dispatch/Prepare/pair
  regression `189 passed`, and full repository regression `1430 passed`.

## 2026-08-14: trip-energy sensitivity fingerprint bug and fail-closed repair

- Frozen source SHA `735527da7f117f5af894263dcdf4fe55e8226328`
  completed the five low-PV `ENERGY_0.8`--`ENERGY_1.2` cases through fresh
  Prepare, frontend/BFF Phase 4, physical validation, 24-step Rolling, and
  canonical executed-day accounting. Git remained clean and unchanged.
- The source manifest was `BLOCKED` because all certified gaps exceeded 1%
  and because each case had a different stable-control fingerprint. A field
  audit showed that every canonical dimension matched except
  `trip_structure_input_sha256`. Its old definition removed direct kWh/liter
  fields but retained `required_soc_departure_percent`, even though that value
  is derived from trip demand and therefore changes with the sensitivity
  multiplier.
- The mathematical/provenance correction is
  `H_schedule = SHA256(trip fields excluding energy, fuel, energy-model
  provenance, type-specific demand, and derived departure-SOC requirement)`.
  This changes no feasible-region constraint, coefficient, objective,
  assignment, Rolling result, or accounting value. It changes only which
  fields are legitimately classified as non-varied controls.
- New runs persist `prepared_trip_input_sha256` while the already-loaded
  prepared payload is available. For legacy runs, re-audit may reconstruct it
  only from a prepared source whose existence, byte size, and full SHA-256
  have all been validated. Missing or invalid provenance fails the case.
- Independent read-only hashing of all five 264-row prepared trip arrays gave
  the same SHA-256:
  `1c382c9c3dc6eec41173c1c451d790a66ae41ffef5c4bd10d2caabc7826511f9`.
  Focused provenance, sensitivity, time-reporting, ablation, and frontend-pair
  regression: `71 passed`; full repository regression at that repair point:
  `1394 passed`.
- The re-audit now also computes each case's minimum executed BEV SOC from
  the active vehicles' 00:00 cyclic target, 01:00--23:00 Rolling state
  handoffs, and 24:00 terminal target. Battery capacity and minimum-SOC limits
  come from the prepared vehicle inventory. The snapshot, chain summary, and
  all 23 state files must match the final artifact hash ledger; a mismatch
  fails the case instead of falling back to the day-ahead SOC series.
- Added a dedicated trip-energy reporting snapshot and immutable builder. It
  accepts the five-case tranche only when the signed source manifest, common
  controls, prepared-trip hash, exact case coverage, 264/264 service,
  frontend/BFF provenance, physical/accounting gates, and executed SOC ledger
  all pass. A sole MIP-gap failure is emitted as
  `DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED`; it never becomes a certified
  demand transition. JSON, CSV, Markdown, Excel, workbook QA previews and four
  PNG/SVG figure pairs are all hashed by one reporting manifest.
- Clean re-audit builder SHA
  `2a4da8b6ad48c8ffc297b784c616dabd83ba1281` reprocessed the immutable
  `735527d` source cases without Prepare, HTTP, or solver calls. Re-audit
  payload SHA-256 is
  `b5736dec1edfd1ddb2c0b7861f2127b77dd6a74a2dc59375f3d88b73175a75e4`;
  its independent canonical-hash check matches. All five cases share control
  fingerprint
  `d19d1c70780ced02def96f2edfde8a2ccdc7fbd9da15b9bd7329933af3c43252`
  and fail only `mip_gap_target_met`.
- At demand scale 0.8/0.9/1.0/1.1/1.2, the gap-limited feasible incumbents
  assign 105/91/91/77/77 BEV trips, use 22/21/21/20/20 BEVs, and record
  43,887.594 / 50,635.719 / 58,318.002 / 64,864.887 / 72,450.669 JPY
  executed cost. Operational CO2 is 741.944 / 857.382 / 986.112 /
  1,098.804 / 1,226.171 kg. Minimum executed SOC is 27.566% / 27.086% /
  26.607% / 26.127% / 22.063%, with all margins above the 20% vehicle limit.
- The observed incumbent BEV-trip steps are 105 to 91 between 0.8 and 0.9,
  and 91 to 77 between 1.0 and 1.1. They are not certified transition
  thresholds because the gaps are 8.246% / 6.446% / 6.550% / 4.952% /
  5.020% against the declared 1% target.
- Final report-builder SHA `d26a0f23d152bc54b0cf9ce3a8432ae3b2e0bdfc`
  generated the immutable bundle under
  `output/thesis_sensitivity_energy_low_pv_20260814_735527d/reaudit/8e98b34aa295a88f-2a4da8b/reporting/b5736dec1edfd1dd-d26a0f23d152`.
  Reporting snapshot SHA-256 is
  `66eda171d30a04db76727f1b344a3eba2e4bb24c1b7fe8991e4b4a9928c8160e`;
  reporting-manifest payload SHA-256 is
  `d7633210d18dc35519522e32cae3975adc0cfd2098c13212f315a3c36c37383d`.
  All 18 registered derivatives re-hash, the five-sheet Excel workbook has
  zero detected formula errors, and every sheet plus all four public figures
  passed visual QA. Workbook SHA-256 is
  `e6e9661dc40801b50a0ecd79e4e3aad9ec365ff1fab7f9b3f0a72295db97d24f`.

## 2026-08-14: trip-energy sensitivity preflight

- Before launching the next formal tranche, the matrix contract was made
  explicit: `ENERGY_0.8` through `ENERGY_1.2` multiply both aggregate BEV-kWh
  and ICE-liter demand targets after deterministic trip-level proxy weights
  are formed. Trip structure, PV, tariff, fleet, charging, and Rolling
  controls remain fixed.
- Parameterized regression now proves exact aggregate scaling at 0.8, 0.9,
  1.0, 1.1, and 1.2 for both powertrains. This is a clarification and test of
  the existing mathematics, not a formula change.

## 2026-08-14: corrected time-discretization rerun and diagnostic reporting

- Clean frozen SHA `88f76a9af79a8d46c1502a51ed03778ab99f20e9`
  completed `TIME_60`, `TIME_30`, and `TIME_15` through fresh Prepare, the
  normal frontend/BFF Phase-4 path, 24-step Rolling, physical validation, and
  canonical executed-day accounting. Source directory:
  `output/thesis_sensitivity_time_low_pv_20260814_corrected_88f76a9`.
  Manifest payload SHA-256:
  `5d58aca1284c4dddd33dd070831dbe3d300bf23017547ba17226f46ea9200b20`.
- All non-varied controls share fingerprint
  `a78671ce3f4a79ea436893863f4e699393afaaf7537b9b32a50ec16a939c523a`.
  For every case, submitted/requested/effective Rolling is 60/60/60 minutes;
  the internal time step alone is 60/30/15 minutes. Git stayed unchanged,
  source artifacts re-hash, the full successor network is used, and all
  request/effective provenance checks pass.
- All cases serve 264/264 trips with 32 buses and 91/173 BEV/ICE trips.
  For 60/30/15 minutes, executed cost is 58,318.002033 / 58,235.852189 /
  58,221.042678 JPY; grid import is 130.948752 / 128.255315 / 127.769757
  kWh; CO2 is 986.112082 / 984.765363 / 984.522584 kg. PV-to-bus rises from
  293.407649 to 321.032649 and 326.012728 kWh as the slot is refined.
- All three solves return `time_limit` after about 3,601 solver seconds. Their
  certified gaps are 6.550063%, 6.418238%, and 6.352187%, so
  `case_accepted=false` and the matrix remains `BLOCKED`. The corrected run
  removes the earlier provenance confound but does not discharge the
  predeclared optimality gate.
- `time_discretization_reporting.py` and
  `scripts/build_time_discretization_reporting.py` revalidate the signed
  source manifest, exact three-case coverage, common controls, full physical
  and accounting evidence, Rolling controls, Git immutability, and gap-only
  failure scope. The builder emits immutable JSON/CSV/Markdown plus separate
  executed-KPI and solver-evidence PNG/SVG figures. Any non-gap failure or
  source tampering blocks report creation; gap-limited cases are labeled
  `DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED`.
- The clean builder SHA
  `8c3307182c6b951a3005050ee63ec9bc7502d1d4` generated seven hashed
  derivatives under
  `output/thesis_sensitivity_time_low_pv_20260814_corrected_88f76a9/reporting/5d58aca1284c4ddd-8c3307182c6b`.
  Manual PNG review found and fixed a zero-reference label/title collision;
  the corrected bundle was generated into a new immutable version instead of
  overwriting the first derivative. Reporting-manifest SHA-256:
  `58c9cebf6d771c7d5a809044768a8ce8306075e8c4c102e017aed6f6016781ba`.
  Full repository regression before the reporting commits: `1385 passed`.

## 2026-08-14: time-discretization diagnostic exposed provenance mismatch

- Clean frozen SHA `01986881c8c4c2d69802be482dddf58865eb8535` executed the
  predeclared low-PV `TIME_60`, `TIME_30`, and `TIME_15` cases through fresh
  Prepare, the normal frontend/BFF Phase-4 path, and the accepted
  fixed-assignment Rolling chain. The source execution is
  `output/thesis_sensitivity_time_low_pv_20260813_0198688`; its original
  manifest payload SHA-256 is
  `68a9c858591f4c094b3d6df5f06a8ad496ecbd8e3a50c34329d8348147b3e3c5`.
- Each case served 264/264 trips with 32 buses and the same 91/173 BEV/ICE
  trip split. Executed-day totals for 60/30/15 minutes were respectively
  58,318.002033 / 58,235.852189 / 58,221.042678 JPY, 986.112082 /
  984.765363 / 984.522584 kg-CO2, and 130.948752 / 128.255315 /
  127.769757 kWh of grid import. These values are diagnostics only.
- All three day-ahead solves stopped at 3,600 seconds. Their independently
  certified gaps were 6.550063%, 6.418238%, and 6.352187%, so none met the
  declared 1% requirement. Physical feasibility and Rolling accounting pass;
  optimality certification fails. The original matrix therefore remains
  `BLOCKED` and does not establish time-step convergence.
- Audit review found two non-mathematical defects. First, the matrix changed
  both internal slot resolution and requested Rolling advance, while the
  formal BFF intentionally enforces a 60-minute Rolling advance. Second, the
  endpoint replaced the saved `raw_frontend_body` with server-effective
  controls, preventing reconstruction of the sent request. A separate false
  negative compared the unlimited-successor sentinels `None` and `0` by
  object identity.
- The matrix now holds Rolling advance fixed at 60 minutes and varies only the
  internal energy-slot resolution. The BFF preserves the parsed client body
  before applying effective controls. The sensitivity audit separately checks
  the submitted JSON, persisted raw body, effective Rolling controls, and
  finite/unlimited successor semantics. Re-audit mode reads the stored matrix
  and immutable source runs, records source-run and audit-builder Git SHAs
  separately, verifies artifact snapshots, and writes to a new directory
  without HTTP, Prepare, solver, or source overwrite.
- These changes do not alter the feasible region, objective, tariff, energy
  equations, assignment, or gap rule. The fresh corrected clean-commit rerun
  and its current gap-limited verdict are recorded in the section above.

## 2026-08-13: verified low-PV M0--M3 comparison and reporting derivatives

- Fresh frontend/BFF Phase 1 and Phase 4 jobs completed from clean frozen SHA
  `f5c8ba7395665493a718423d2232bb28a15e07bd` against the same immutable v9
  prepared input
  `prepared-8331f7eaa9fcb7eb-f1e18f252e336f1f-746edf1f`. Its 251,647,636-byte
  source SHA-256 is
  `d9e2d63ce2c044d4ee6c2324677e59c9f64a24f792b9b9ee5acb2a3a8b4018c6`,
  and the prepared ID, stored scope hash and independently recomputed scope
  hash all contain `f1e18f252e336f1f`.
- M3 run `run_20260813_2317` served 264/264 trips with 21 BEVs and 11 ICE
  buses (91/173 trips), completed 24/24 Rolling, passed physical and canonical
  accounting validation, and met the declared 1% target through the preserved
  0.547009% certificate. M1 run `run_20260813_2337` evaluated the fixed
  baseline dispatch through the explicit charging-only frontend phase. Both
  source manifests retain the same prepared bytes, canonical input hash and
  Git SHA.
- `scripts/build_thesis_ablation_comparison.py` returned
  `READY_FOR_DAY_AHEAD_METHOD_COMPARISON` with no failed checks. Canonical
  day-ahead totals are: M0 723,243.238501 JPY / 1,402.028088 kg-CO2; M1
  707,518.152327 JPY / 1,144.239790 kg-CO2; M2 726,612.173278 JPY /
  1,449.950955 kg-CO2; and M3 698,318.002033 JPY / 986.112082 kg-CO2.
  M0/M1 keep 13/19 BEV/ICE buses and 44/220 trips; M2/M3 use 21/11 buses and
  91/173 trips.
- The predeclared effects are now evidence-backed: M0->M1 changes cost by
  -15,725.086173 JPY and CO2 by -257.788298 kg without changing dispatch;
  M2->M3 changes cost by -28,294.171245 JPY and CO2 by -463.838873 kg;
  M1->M3 adds eight used BEVs and 47 BEV trips while reducing cost by
  9,200.150294 JPY and CO2 by 158.127709 kg. M2 alone is 3,368.934778 JPY and
  47.922866 kg-CO2 worse than M0, so the result supports the joint
  dispatch-energy interaction rather than a claim that BEV assignment alone
  is always beneficial.
- READY comparisons now generate canonical method/effect CSVs, Markdown, and
  PNG/SVG figures from the verified payload. The reporting manifest records
  the source-run SHA separately from the clean report-builder SHA and hashes
  every derivative. The charts use explicit day-ahead scope, units, zero
  baselines and direct labels; Rolling values remain excluded. Manual visual
  QA also checks title/legend/label collisions and reserves headroom above the
  largest stacked energy bar. Regression tests reject payload tampering,
  reordered methods, dirty/unattested report provenance and missing artifact
  hashes.
- This discharges the low-PV same-input day-ahead M0--M3 evidence item only.
  It does not cure the high-PV pair's 1.574005% versus 1% gap, establish a
  global integrated optimum, or discharge the declared time-step and other
  sensitivity experiments.

## 2026-08-13: prepared-input immutability across BFF restarts

- The first clean-commit HTTP Prepare after the immutability patch failed
  before solver submission and exposed a second v7 identity defect: the
  prepared filename/ID used the pre-materialization scope hash `404f3679...`,
  while `_build_canonical_input()` augmented the scope payload, recomputed it,
  and saved `f1e18f25...` inside the JSON. The ID and payload therefore claimed
  two different scope identities. No optimization job was created.
- `_scope_cache_payload()` now materializes the stored depot/route/primary-depot
  aliases before hashing. `_build_canonical_input()` receives that certified
  hash used to construct `prepared_input_id`; it no longer recomputes a second
  hash from an augmented representation.
- The first v8 fresh Prepare served 264 trips, but the independent post-Prepare
  re-hash found `f1723217...` instead of stored `f1e18f25...` because the
  derived `prepared_scope_audit` is appended after selection hashing. No solver
  job was submitted. The audit is now explicitly excluded from the selection
  scope hash, and the regression adds it before recomputing the stored scope.
  The prepared schema at this historical checkpoint was
  `v9_immutable_scope_identity`; conflicting v7/v8 files remained preserved
  and a fresh corrected artifact received a different ID/path. It is
  superseded by the v10 schema documented in the 2026-08-14 entry above.
- The first controlled low-PV M1/M3 assembly was intentionally rejected by
  `build_thesis_ablation_comparison.py`. Both jobs recorded prepared input ID
  `prepared-8331f7eaa9fcb7eb-404f36795e908d12-d5e8413e`, canonical ablation
  input hash
  `9693fb2c52952480160b0a455a154bca9b02edb01f28f7ab3695b34ae0fc29c3`,
  clean Git SHA `f46f1e8`, and matching M0 output, but their source byte hashes
  were `c7091202...` and `4a45a62d...`. The blocked candidate metrics are not
  adopted as thesis results.
- Root cause: after a BFF restart the in-memory Prepare cache was empty.
  `get_or_build_run_preparation()` regenerated the deterministic ID and wrote
  the rebuilt JSON to the same path. The two recorded Prepare snapshots differ
  only at top-level `prepared_at`, but that legitimate provenance timestamp
  changed the full source-file SHA and destroyed the byte-identity evidence
  required by the comparison gate.
- `run_preparation.py` now rehydrates a matching saved prepared artifact without
  rebuilding it. Repeated explicit Prepare uses create-once persistence: if
  the complete canonical payload excluding only `prepared_at` is identical,
  the original file, timestamp and SHA remain unchanged. If any other field
  differs under the same ID, `PREPARED_INPUT_ID_COLLISION` stops the request;
  the prior artifact is never overwritten. Concurrent creates use the same
  equality check after the exclusive-create race.
- The mathematical feasible region, energy/cost equations and objective are
  unchanged. This is a provenance and reproducibility correction. Regression
  tests cover timestamp-only reuse, real trip-content collision with byte
  preservation, and process-restart reuse without invoking the builder.
- The production-size 251,647,658-byte low-PV prepared artifact was replayed
  with only `prepared_at` changed in memory. Its full file SHA-256 remained
  `4A45A62DE369651487C72842D4C14D90F4ED276A6E3CE9651560BFF4797917D5`
  before and after the immutability check.
- Post-v9 focused preparation/provenance/ablation regression:
  `31 passed`; complete repository regression: `1374 passed in 69.77s`.
  The later clean-commit evidence is recorded in the section above; no pre-fix
  run was relabeled.

## 2026-08-13: runtime-attested r7 validates feedback budgeting and provenance

- Executed the normal frontend/BFF controlled pair from clean frozen SHA
  `f46f1e821e6773f7f647dd130b28427bbb3df10d` after restarting the BFF.
  Both jobs attest PID 60504 and matching clean startup/current/frozen SHAs;
  Git stayed unchanged throughout the run. Fresh Prepare materialized the same
  264-trip `WEEKDAY` scope, 60 active vehicles, ten chargers, 30 JPY/kWh,
  zero demand charge, 1,000 kW PV and 6,000 kWh / 900 kW BESS.
- Both cases serve 264/264 trips, accept 24/24 Rolling steps, pass independent
  physical validation and canonical executed-day accounting, and return BESS
  from 3,000 to 3,000 kWh. High PV remains 31/1 BEV/ICE buses, 248/16 trips,
  650,234.729396 JPY and 170.814257 kg-CO2. Low PV remains 21/11, 91/173,
  698,318.002033 JPY and 986.112082 kg-CO2. The pair control hash is
  `d08c5fa55f984e0f83417c247910d34ae57e636d51b1953fdd0ba5c575dfe68b`.
- High PV again stops at a certified 1.574005% gap and low PV meets the target
  at 0.547009%. The controlled PV comparison passes, while formal submission
  remains blocked only by `baseline_requested_mip_gap_certified`. The progress
  bundle is independently `READY` with seven figures and six tables.
- The retry allocator and new evidence fields behave as designed. Sunny
  `渋23` funds two passes (33-second Stage 1, 9-second Stage 2, five-second
  overhead reserve) under an 89-second limit, but Stage 1 has no incumbent;
  Stage 2 is therefore `not_run`, feedback history is empty and no no-good cut
  is claimed. Low-PV `渋22` funds 15 + 5 seconds per pass, obtains Stage-2
  `optimal`, passes full validation and produces the known 26/6 candidate at
  704,330.168664 JPY. Low-PV `渋23` records the same honest `not_run` outcome
  after a Stage-1 time limit without an incumbent.
- This run proves the audit no longer conflates "feedback allowed" with
  "feedback applied". It does not show an IIS retry, because no reduced Stage
  2 was proven infeasible. It also does not improve the sunny incumbent or
  lower bound, and does not certify 32-BEV infeasibility.
- Evidence:
  `output/formal_pair_20260813_route_band_feedback_budget_attested_v7_flat30_pv1000_bess6000_phase4_f46f1e8_gap01_r7`;
  total wall time 4,738.905068 seconds high PV and 1,163.467083 seconds low PV;
  ZIP size 20,612,441 bytes; SHA-256
  `EC05E786943500E6E032BE86841FEBC9E935E9FF790BC337FC8A4F318A765064`.

## 2026-08-13: reserve and expose a complete route-band feedback retry

- Raised a P1 candidate-search evidence defect from the clean runtime-attested
  r6 pair. The audit declared `stage2_feedback_max_iterations=1`, but the
  initial Stage 1 received half of the group budget and Stage 2 then consumed
  part of the remaining shared deadline. The artifact did not record the
  reduced Stage-2 status or feedback history, so it was impossible to prove
  whether an IIS retry ran. Sunny used 44 + 5 seconds of an 89-second limit and
  returned after 48.091 seconds; one low-PV group similarly used 30 + 5 of 61.
- Added a pure retry-budget allocator. It retains the same fair group deadline,
  funds the initial and maximum one feedback pass equally, reserves five
  percent for construction/IIS overhead, and gives Stage 2 at least 20% of a
  pass or the configured per-solve floor. If even two seconds per pass cannot
  be funded, feedback is disabled explicitly instead of being advertised but
  unreachable.
- Route-band attempt telemetry now records the reduced Stage-2 status, actual
  feedback iteration and history, applied flag, Stage-1 no-good count, funded
  pass count and overhead reserve. A retry remains legal only after Gurobi
  proves Stage 2 `INFEASIBLE`; a time-limit without an incumbent is not treated
  as an infeasibility certificate.
- This changes only bounded Phase-4 warm-start candidate generation and audit
  semantics. The total solver allowance, final integrated constraints,
  objective coefficients, validation, accounting, and 1% acceptance gate are
  unchanged. Related regression passes `72 passed`; the complete repository
  suite passes `1370 passed in 71.39s`; compileall and `git diff --check` pass.
  The clean r7 evidence above verifies the allocator and telemetry. No IIS
  retry was applicable in r7 because the only failed route-band attempts did
  not produce a Stage-1 incumbent, so their Stage 2 correctly remained
  `not_run`.

## 2026-08-13: runtime-attested r6 controlled pair

- Restarted the BFF from clean frozen SHA
  `ccfbbbb321cfe4a9150f0e135172e52ee9751a6b`. Both jobs attest PID 50628,
  the same clean startup/current/frozen SHA, unchanged Git state during solve,
  fresh Prepare and the ordinary frontend/BFF execution path.
- Both cases serve 264/264 trips, accept 24/24 Rolling steps, pass physical
  validation, return BESS from 3,000 to 3,000 kWh, and reconcile canonical
  executed-day accounting. The pair fixes 2025-08-05 `WEEKDAY`, 60 active
  vehicles, ten chargers, 30 JPY/kWh, zero demand charge, 1,000 kW PV, and a
  6,000 kWh / 900 kW BESS; only the separately hashed PV curve differs.
- High PV produces 6,056.25 kWh and selects 31/1 BEV/ICE buses for 248/16
  trips, 650,234.729396 JPY and 170.814257 kg-CO2. Low PV produces 996.20 kWh
  and selects 21/11 buses for 91/173 trips, 698,318.002033 JPY and
  986.112082 kg-CO2. The controlled comparison is accepted.
- Low PV satisfies the declared gap with a certified 0.547009%; high PV is
  time-limited at 1.574005%. Formal research submission therefore remains
  blocked only by `baseline_requested_mip_gap_certified`; reporting readiness
  is not promoted to formal readiness.
- The low-PV route-band search produced a full Stage-2-feasible 26/6 candidate
  at 704,330.168664 JPY. It was correctly rejected because it costs
  6,012.166631 JPY more than the selected 21/11 composition. Sunny did not
  find an exact all-BEV candidate, but no infeasibility certificate was
  generated. The verified-start canonical objective cap is eligible and one
  cap constraint is recorded in both cases.
- Evidence:
  `output/formal_pair_20260813_route_band_feedback_runtime_attested_v6_flat30_pv1000_bess6000_phase4_ccfbbbb_gap01_r6`;
  ZIP size 20,602,885 bytes; SHA-256
  `5B4A7014EBD7162D0B06F18AB87BECED878F057439306827692475921239E5F0`.

## 2026-08-13: bind formal runs to the code loaded by the BFF process

- Raised a P0 research-provenance defect during the r5 rerun. Port 8000 was
  owned by a long-lived Windows BFF process. Its request-time Git collector
  read clean HEAD `e321a3a`, but its loaded Python modules were older: the
  produced seed audit omitted the newly implemented feedback/budget fields
  and reproduced the v4 result exactly. The r5 artifacts are retained for
  diagnosis and must not be cited as evidence for `e321a3a`.
- The BFF optimization router now captures Git SHA, dirty state, repository
  root, PID and startup timestamp once at module import. A formal request is
  accepted only when that startup record is clean and matches the current
  clean checkout. The same fail-closed check runs synchronously before job
  creation, again in the worker before model construction, and after solve.
- Solver metadata and `optimization_audit.json` persist
  `bff_runtime_git_attestation`; research Git eligibility also requires its
  match flag. `GET /api/research/git-preflight` exposes the same record so the
  UI and automated pair runner can explain a stale-process rejection.
- `run_frontend_controlled_pv_pair.py` now requires attestation schema fields
  and exact equality between local frozen SHA, current BFF SHA and startup BFF
  SHA immediately after the health check. A pre-attestation or stale BFF fails
  before Prepare and before any Gurobi work.
- Focused provenance/BFF/pair-runner regression passes `52 passed`; the full
  repository suite passes `1367 passed in 68.57s`. Compileall and
  `git diff --check` also pass. The clean r6 evidence above verifies this
  attestation. The change affects evidence validity only; optimization
  equations and acceptance gap thresholds are unchanged.

## 2026-08-13: feed reduced route-band Stage-2 IIS back to Stage 1

- Raised a remaining P1 candidate-search defect from the v4 formal evidence.
  The sunny 32-BEV constructive dispatch failed fixed-assignment Stage 2, and
  the later route-band repartition also failed local Stage 2. Although the
  general two-stage solver already supports IIS-backed exact-assignment
  no-good cuts, the reduced route-band problem explicitly set
  `stage2_feedback_max_iterations=0`, so no alternative repartition was tried.
- Each route-band group still has the same separately declared 90-second
  maximum and fair sharing. The initial reduced Stage 1 now receives at most
  half of that group's remaining share. One IIS feedback iteration may use the
  rest of the same shared deadline to reject only the proven-infeasible exact
  assignment and rerun the identical all-BEV/count-constrained reduced scope.
- The retry is not a weather policy, BEV lower bound on the final solve, repair,
  or fallback. Any candidate must still pass local Stage 2, exact merge checks,
  the original full-problem Stage 2, independent physical validation, and
  canonical accounting. The integrated Phase-4 feasible region and formal gap
  gate are unchanged.
- Fixed a provenance inconsistency in the sequential integrated solver. The
  verified canonical-cost upper bound was installed after the exact
  vehicle-day stage, but metadata retained the earlier ineligible result from
  when vehicle-days were the active objective. The helper now accepts an
  explicit certified objective field, and the cost-stage audit reports the
  canonical field, eligibility, tolerance, and one installed cap row.
- Focused regression: `45 passed`; complete repository regression:
  `1364 passed in 68.47s`. Compileall and `git diff --check` also pass.
  Clean-commit controlled-pair evidence is still pending at this checkpoint;
  no existing output is relabelled.

## 2026-08-13: preserve fixed-duty search before route-band re-partitioning

- Executed the normal frontend/BFF controlled pair from clean frozen SHA
  `583dced3306f3e27b1de248605b70c51fc72e570` with fresh Prepare, 30 JPY/kWh,
  zero demand charge, 1,000 kW PV and 6,000 kWh BESS. Both 264-trip cases
  completed 24/24 Rolling, physical validation, executed-day accounting,
  pair finalization, progress figures/tables and ZIP export. The pair control
  contract passed and PV-only sensitivity was accepted.
- High PV produced 31 BEVs / 1 ICE, 248/16 trips, 650,298.979262 JPY and a
  1.583730% certified gap. Low PV produced 21/11, 91/173 trips,
  698,318.002033 JPY and a certified 0.547009% gap. The formal pair remains
  blocked only by `baseline_requested_mip_gap_certified`. The high-PV cost is
  64.249866 JPY worse than the preceding `b06c451` incumbent and the gap is
  0.009725 percentage point wider.
- Audit isolated the regression: the v3 route-band reduced Stage 1 ran before
  the fixed-duty neighborhood. One high-PV and two low-PV candidate solves
  consumed 60--102 seconds from the same 120-second allowance, and every
  merged candidate then failed the original full-problem Stage 2. High PV
  consequently selected the earlier combined matching result instead of the
  cheaper powertrain-duty-swap result previously found near evaluation 81.
- v4 preserves the complete 120-second fixed-duty search first, then starts
  route-band repartition from its cheapest independently validated incumbent
  under a separate explicit 90-second budget. Multiple route bands divide the
  remaining budget fairly. The reduced candidate solve now includes Stage 2;
  a local SOC/charging-infeasible candidate is rejected before full-problem
  recourse, while every locally feasible candidate must still pass the full
  fixed-assignment Stage 2, physical validation and canonical accounting.
- The new control is
  `phase4_phase3_seed_route_band_repartition_time_limit_sec=90`. It is
  persisted in solver settings, Rolling provenance and the controlled-pair
  hash. The declared Phase-4 solver budget increases from 4,620 to 4,710
  seconds. This changes only upper-bound candidate generation and runtime;
  dispatch constraints, tariffs, PV/BESS equations, objective coefficients,
  integrated feasible region and formal gap rules are unchanged.
- Focused regression covers fixed-duty-before-route ordering, required reduced
  Stage 2, local-infeasibility rejection, full-problem Stage-2 validation,
  exact activation counts and pair-control persistence. Older `583dced`
  artifacts remain frozen and are not relabelled. Focused regression passes
  65 tests; the complete
  repository suite passes `1363 passed in 71.02s`; compileall and
  `git diff --check` also pass.
- The fresh v4 pair at frozen SHA
  `ad0d4f2c4c1acb10233516309c11a9a4c00b362d` completed both frontend/BFF
  cases, 24/24 Rolling, physical/accounting validation, pair finalization and
  reporting ZIP. High PV recovered the prior best seed exactly:
  650,234.729396 JPY, 31/1 BEV/ICE buses and 248/16 trips. The fixed-duty
  neighborhood evaluated 109 candidates in 120.172 seconds and selected
  `powertrain_duty_swap_round_1` before route-band search started.
- The high-PV route-band reduced solve used 62.342 seconds and reported local
  Stage-2 infeasibility, so no full-system candidate evaluation was attempted.
  Low PV evaluated 210 fixed-duty candidates in 120.594 seconds; its two
  route-band groups received fair budgets and both failed local Stage 2 within
  89.520 seconds total. This verifies that v4 preserves the established
  incumbent and rejects energy-infeasible repartitions earlier.
- Low PV remains 698,318.002033 JPY, 21/11 buses, 91/173 trips and meets the
  declared gap at 0.547009%. High PV remains time-limited at a 1.574005%
  certified gap, so the pair manifest accepts controlled PV sensitivity but
  formal release remains blocked only by
  `baseline_requested_mip_gap_certified`. The complete progress bundle is
  `READY` with seven figures, six tables and a ZIP; this reporting readiness
  is not promoted to formal research readiness.
- Evidence:
  `output/formal_pair_20260813_route_band_v4_flat30_pv1000_bess6000_phase4_ad0d4f2_gap01_r4`.

## 2026-08-13: first route-band re-partitioning implementation (v3, superseded)

- Raised and addressed the next failure exposed by the frozen `b06c451` pair:
  whole-duty replacement and one reciprocal suffix exchange preserve too much
  of the long ICE/BEV path structure. They cannot redistribute all trips in the
  affected route band to create the charging windows needed for a final
  one-for-one ICE retirement.
- Added a bounded candidate-generation solve before the existing fixed-duty
  neighborhood. For each active-ICE `(depot, route band)` group, the solver
  constructs a reduced canonical problem containing the complete trip set
  currently served by that ICE group and every used BEV confined to the same
  route band. Candidate vehicles are those used BEVs plus the depot's unused
  available BEVs; active ICE vehicles are excluded.
- The reduced exact Stage 1 applies `sum(used_BEV) >= K` and
  `sum(used_vehicle) <= K`, where `K` is the number of affected vehicle paths
  before replacement. Thus it searches a one-for-one all-BEV re-partition
  without increasing the vehicle-day count. The Stage-1 upper-count constraint
  is accepted only when the problem is explicitly marked as an internal
  route-band Phase-4 seed candidate; it cannot silently constrain an ordinary
  Phase-3 run. It is audited alongside the existing minimum-BEV constraint.
- The reduced solve is an upper-bound candidate generator only. Its charging
  relaxation cannot certify full-system energy feasibility because unaffected
  routes also consume chargers, PV and BESS. The merge therefore fails closed
  on changed/duplicate trip coverage, duty-ID collision, or reuse of an
  unaffected vehicle; it clears every energy/SOC/accounting field and then
  runs exact fixed-assignment Stage 2 on the original full problem. Independent
  physical validation and canonical accounting remain mandatory, and only a
  strict actual-cost improvement may become the Phase-4 MIP start.
- The audit schema is now
  `phase4_seed_unused_bev_activation_neighborhood_v3`. It records the depot,
  route band, affected trips/vehicles, exact target count, reduced Stage-1
  status/runtime, activated BEVs, merged assignment hash, and full Stage-2
  result. It explicitly records candidate-only semantics, no global-optimum
  claim, and no weather-specific assignment bias.
- Added fail-closed merge coverage tests, a real-Gurobi reduced Stage-1 test,
  a full-Stage-2-before-selection test, and a real-Gurobi exact activation-count
  constraint test. This changes candidate generation and the feasible upper
  bound supplied to Phase 4; it does not change tariffs, PV/BESS equations,
  canonical accounting, or the integrated feasible region. Focused regression
  passes 76 tests; the complete repository regression passes
  `1362 passed in 66.95s`; compileall and `git diff --check` also pass.
- At this implementation checkpoint no 264-trip formal run had yet been
  executed. The later `583dced` pair above exercised v3 and exposed its search
  ordering regression; those frozen outputs are preserved without relabelling.

## 2026-08-13: sequential formal pair, evidence audit, and reporting repair

- Re-ran the full frontend-equivalent controlled pair from clean frozen SHA
  `b06c451b9f89e7930f25b7d7e28cf50af54df21c` after adding the IIS-motivated
  duty-suffix neighborhood. Both fresh Prepare records retained the common
  2025-08-05 `WEEKDAY` 264-trip service, 60-vehicle fleet, ten chargers,
  30 JPY/kWh energy, zero demand charge, 1,000 kW PV rating and 6,000 kWh BESS.
  Both cases completed, accepted 24/24 Rolling steps, passed physical and
  accounting checks, and the pair control hash matched while PV hashes differed.
- Canonical results were unchanged: high PV used 31 BEVs / 1 ICE for 248/16
  trips, cost 650,234.729396 JPY and emitted 170.814257 kg-CO2; low PV used
  21/11 for 91/173 trips, cost 698,318.002033 JPY and emitted 986.112082 kg.
  Certified cost gaps are 1.574005% and 0.547009%. Pair sensitivity acceptance
  is true, but formal submission is still blocked only by
  `baseline_requested_mip_gap_certified`.
- In high PV, suffix search generated 1,335 raw exchanges; six passed both
  canonical cross-arc checks. Twenty-four 32-BEV fixed assignments were
  evaluated and all were Stage-2 infeasible, so the selected seed stayed the
  earlier 31/1 powertrain-duty-swap result. Low PV evaluated 56 suffix-derived
  candidates, 13 were feasible, but none beat its 21/11 baseline cost. This is
  negative experimental evidence: one reciprocal suffix exchange is too local
  to create the charging windows needed to retire the final sunny ICE duty.
  The next model change is a route-band restricted re-partitioning MILP, not a
  larger blind enumeration of the same move.
- The progress artifact is
  `output/formal_pair_20260813_suffix_exchange_flat30_pv1000_bess6000_phase4_b06c451_gap01`
  and its ZIP. `progress_report/` is `READY` for progress-evidence completeness
  with seven PNG/SVG figure pairs, six tables, ten detailed per-run figures and
  106 indexed source artifacts. It explicitly displays the formal pair as
  BLOCKED and does not convert progress readiness into research readiness.
- Ran the requested high/low-PV pair from clean frozen SHA
  `7cb1192cf6278e8854add16b58f04639a6656336` through the same frontend/BFF
  endpoints used by the application. Both fresh prepared inputs materialized
  the 2025-08-05 `WEEKDAY` service with 264 trips, 60 active vehicles, ten
  chargers, 30 JPY/kWh grid energy, zero demand charge, manually rated
  1,000 kW PV and a 6,000 kWh / 900 kW BESS at 3,000 -> 3,000 kWh.
- Both cases served all trips, passed independent physical validation,
  accepted 24/24 Rolling steps and reconciled canonical executed-day costs.
  High PV used 31 BEVs / 1 ICE for 248/16 trips and cost 650,234.729396 JPY;
  low PV used 21/11 for 91/173 trips and cost 698,318.002033 JPY. Canonical
  operational CO2 is 170.814257 versus 986.112082 kg. The pair is accepted for
  the controlled PV sensitivity comparison.
- Sequential certification proved 32 vehicle-days exactly in both cases. Low
  PV has a 0.547009% certified cost gap using the documented independent
  integer-valid lower bound even though Gurobi's raw gap is 8.351210%. High PV
  has a 1.574005% cost gap. Formal release therefore remains `BLOCKED` only on
  `baseline_requested_mip_gap_certified`; neither case is relabelled as a
  Gurobi global optimum.
- Authoritative frozen output:
  `output/formal_pair_20260813_sequential_lexgap_flat30_pv1000_bess6000_phase4_7cb1192_gap01`.
  The progress bundle is complete with seven PNG/SVG figure pairs, six CSV
  tables and hashed source indexes. The observed high-minus-low response is
  +10 used BEVs and +157 BEV trips; low PV costs 48,083.272637 JPY more.
- Post-run review found three P1 evidence-path defects. First,
  `integrated_actual_cost_objective_requested=false` is correct for a
  vehicle-day-first lexicographic objective, but the runner incorrectly used
  it to reject real slot-level recourse and solver controls. The audit now
  recognizes the certified sequential cost contract. Second, the small oracle
  used the CLI dataset ID (`tokyu_full`) rather than the `WEEKDAY` service ID
  materialized by Prepare. Prepare/service drift now fails before solve and
  the oracle reads the case manifest. Both preserved cases pass the corrected
  bounded oracle. Third, objective reconciliation compared only the primary
  vehicle-day scalar with accounting. New `canonical_cost_*` fields compare
  the sequential cost-stage objective directly with accepted Rolling
  accounting and are validated fail-closed by artifact and pair gates.
- The frozen run also exposed reporting-source drift: `kpi_summary.json`
  contained day-ahead fuel/CO2, whereas the canonical Rolling ledger contained
  170.814257/986.112082 kg-CO2 and fuel costs equivalent to
  35.884956/356.022849 L at 150 JPY/L. `CostBreakdown` now exports
  `ice_fuel_consumed_l`, and new pair comparisons prefer that executed-day
  field. Existing output is preserved; only a fresh run will carry the new
  field natively.
- Focused frontend, BFF, pair-manifest, telemetry and evaluator regression
  passes 87 tests. The complete repository regression passes
  `1357 passed in 69.10s`; compileall and `git diff --check` also pass. None
  of these post-run changes relabels `7cb1192` evidence; a new clean frozen
  SHA is mandatory before another formal pair.
- Tested the proposed weather-neutral incumbent-gap search profile from clean
  SHA `698ef44622a50a1d5a06368aea6d7fc6914b1457` through the ordinary
  frontend/BFF pair path. It produced exactly the same high-PV
  31-BEV/1-ICE, 650,234.729396 JPY incumbent and 1.574005% certificate, again
  after 3,600 seconds at one root node. Low PV also reproduced its previous
  result and 0.547009% certificate, but solver time increased to about
  322.6 seconds. The changed `MIPFocus`, heuristic share and presolve setting
  therefore provided no benefit and are reverted rather than retained as an
  unsupported improvement. The frozen output remains at
  `output/formal_pair_20260813_incumbent_gap_flat30_pv1000_bess6000_phase4_698ef44_gap01`.
- Candidate-level IIS evidence then isolated the limiting construction. The
  generated 32-BEV/0-ICE candidate moved a 16-trip 07:26--23:24 duty unchanged
  to BEV `befc4670-e889-45d9-bd65-23118c02e196`. Its fixed-assignment recourse
  was infeasible: required energy including the terminal target was
  362.486315 kWh, usable initial energy was 160.557620 kWh, time-ordered
  deliverable charging was only 90.642380 kWh, and terminal shortage was
  111.286315 kWh. This proves that candidate assignment infeasible, not that
  every 32-BEV schedule is infeasible.
- The unused-BEV neighborhood now reconstructs paths before activation. For an
  active ICE duty and same-depot BEV duty (and the same route band when route
  bands are fixed), it exchanges non-empty suffixes only when both crossover
  arcs pass the shared turnaround/deadhead feasibility engine. It then replaces
  the remaining ICE identity with an unused BEV, clears all stale recourse and
  ledger fields, and accepts the candidate only after exact fixed-assignment
  Stage 2, physical validation and canonical accounting. The audit schema v2
  records split points, replacement IDs, path-distance proxies and IIS samples.
  A focused constructed case verifies that whole-duty replacement can fail
  while suffix reconstruction yields an exact lower-cost all-BEV candidate.
  Focused tests pass 75/75; the complete repository regression passes
  `1359 passed in 73.77s`, compileall succeeds, and `git diff --check` is clean.
  Fresh formal-pair evidence remains required.

## 2026-08-12: thesis-model validity contract implementation

- A second clean-SHA frontend/BFF attempt at
  `624b42dcc5c40a07598000218d737a96569a5095` used fresh Prepare ID
  `prepared-e56fd617b42198a7-e6406a7fd75ec751-d5e8413e` for the sunny case.
  The Phase-4 incumbent served 264/264 trips using 31 BEVs and 1 ICE bus
  (248/16 trips). Its raw status was `time_limit`; the requested 1% gap was not
  met, so no optimality claim is permitted.
- All 24 hourly Rolling subproblems were feasible and the chain acceptance
  checks passed, demonstrating that the charging-session boundary correction
  removed the prior 06:00 infeasibility. Final independent physical validation
  nevertheless stopped the run with 31 BEV terminal-SOC and four lower-SOC
  violations. The low-PV job was started automatically by the pair runner but
  intentionally stopped once the shared validation defect and dirty-worktree
  consequence were known; it is not evidence.
- Root cause: `physical_event_schedule._service_energy()` ignored
  `ProblemTrip.energy_kwh_by_vehicle_type` and
  `ProblemTrip.fuel_l_by_vehicle_type`. It rebuilt service consumption from
  the legacy vehicle-average distance rate while the MILP and Rolling chain
  used the materialized `literature_proxy_v1` trip quantities. Individual
  errors ranged from about 0.004 to 1.52 kWh and happened to offset in the
  aggregate, which is why aggregate terminal energy alone did not detect the
  semantic mismatch.
- The independent validator now uses canonical trip-specific BEV energy and
  ICE fuel inputs, not serialized solver SOC. Added explicit BEV and ICE
  regression cases. A diagnostic replay using the preserved canonical input,
  assignment, and executed charging decisions reconstructed 588 physical
  events and 433 SOC events with zero violations and `accepted=true`.
- Validation after the correction: focused physical/rolling/trip-demand suite
  `35 passed`; complete repository suite `1345 passed`. The preserved failed
  run and its generated pair ZIP remain `BLOCKED` and must not be relabelled;
  fresh clean-commit evidence is required.

- Ran the first clean-SHA frontend/BFF formal attempt for the revised model at
  `6f645020f8473c42c15dce8d654bcc00d052615a`. The sunny case used fresh
  Prepare and the saved 1,000 kW PV / 6,000 kWh BESS controls. Phase 4 served
  264/264 trips with a 31-BEV / 1-ICE, 248/16-trip incumbent, but stopped at
  the declared time limit without satisfying the requested gap. Hourly Rolling
  subsequently failed closed at 06:00, so neither that case nor the aborted
  low-PV case is formal pair evidence.
- Root-caused the 06:00 Rolling failure to loss of charge-session state at the
  receding-horizon boundary. The 05:00 solve planned a continuous two-slot
  session and correctly allowed 82.5 kW in its second slot. When 06:00 became
  the first slot of the next solve, the taper/session model incorrectly
  treated it as a new session, deducted both five-minute setup and teardown,
  reduced usable power to 75 kW, and made terminal SOC infeasible.
- Added `active_charge_session_vehicle_ids` to the measured hourly execution
  state and `rolling_active_charge_session_vehicle_ids` to the solver config.
  The next remaining-day MILP now suppresses setup only for a verified
  continuation; ended, inactive, or unknown vehicles cannot obtain that credit.
  State provenance defines continuation as positive charging power in both the
  last executed slot and the next planned boundary slot.
- Added focused state, forwarding, and one-slot Gurobi tests. The exact failed
  sunny prepared input, day-ahead assignment, and step-5 measured state were
  also replayed diagnostically: step 6 changed from `INFEASIBLE` to Stage-2
  `optimal`, restored 82.5 kW for `builder-bev-tsurumaki-002`, and returned no
  infeasibility reasons. This replay is bug evidence only, not a formal rerun.

- Added a deterministic trip-level demand model, `literature_proxy_v1`.
  BEV trip weights use distance and duration elasticities from Ji et al.
  (2022, DOI `10.1016/j.commtr.2022.100069`); ICE trip weights use the
  reported peak/off-peak consumption ratio. Both are normalized to preserve
  the configured fleet-average daily demand, and an explicit sensitivity
  multiplier supports 0.8--1.2 checks. These are literature proxies, not
  measured trip observations.
- Added powertrain-specific trip energy/fuel fields to the canonical problem.
  The MILP now gives these explicit trip values precedence over vehicle-wide
  rates. The canonical trip fingerprint was bumped to
  `canonical_optimization_input_v4_trip_energy_model` so pre-change prepared
  inputs and results cannot be treated as comparable evidence.
- Completed ODPT platform-family aliasing for trip endpoints. IDs such as an
  empty platform suffix and `.1` now resolve as the same physical stop without
  inventing a deadhead rule. Prepare also exports a route-band-OFF transition
  audit and records `formal_transition_network_ready=false` while any
  `deadhead_missing` pair remains.
- Defined PV input as `available_surplus_after_depot_load`. The legacy
  `pv_generation_kwh_by_slot` series remains for compatibility, while the
  canonical asset also records the equivalent available-surplus series and
  semantics. Gross PV input is rejected while no explicit depot-load series
  exists, preventing gross generation from being mislabeled as surplus.
- Added `research_lexicographic_v1`: service coverage (when partial service is
  allowed), used vehicle-days, canonical operating cost, inter-trip deadhead,
  and charge-session count are optimized in that order. Weather bias and the
  return-leg bonus are forbidden/disabled for this preset. The 20,000 JPY
  vehicle-day parameter remains available as an explicit sensitivity; it no
  longer determines the primary research objective under this preset.
- Added a solver-native CO2 epsilon constraint using the same ICE fuel and
  grid-energy emissions expression used for carbon cost. Added
  `piecewise_soc_taper_v1`: 100% charge power below 80% SOC, 2/3 power at
  80--90%, and 1/3 power above 90%, with explicit setup, teardown, and minimum
  session-duration constraints in both Phase 4 and Phase 3 Stage 2.
- Wired every new parameter through Tk Quick Setup load/save, Prepare DTOs,
  scenario overlay persistence, canonical metadata, and economic audit output.
  Prepared-input schema is now `v6_trip_energy_pv_semantics_charge_taper`.
- Added `scripts/build_thesis_experiment_matrix.py`. It generates the
  time-step, energy-demand, PV, route-band, vehicle-day-cost, and CO2 epsilon
  experiment contract for the normal frontend/BFF path and never invokes the
  solver directly. The later M0/M2 rule adapters and explicit M1/M3 merge now
  provide the separate same-input method-comparison path; no method is
  fabricated from another Phase result.
- Fixed two no-op sensitivity definitions found by tracing the reachable
  Prepare-to-ProblemBuilder path. `pv_scale` is now a validated Prepare field,
  is persisted in scenario/overlay input, multiplies the constructed PV kWh
  series without changing rated `pv_capacity_kw`, and is recorded per depot as
  `pv_supply_scale`. Route-band OFF now explicitly enables intra-depot route
  swapping, because the canonical scope lock otherwise correctly forces the
  route band back ON.
- Added `scripts/run_thesis_sensitivity_matrix.py`. It accepts complete
  frontend Prepare/optimization request templates, obtains a fresh prepared
  input for every selected row, submits only the BFF HTTP endpoints, polls the
  public job API, copies the finalized run, and emits an audited JSON/CSV
  result. It checks the declared effective parameter, unpruned Phase 4,
  research/gap/physical/Rolling gates, final artifact hashes, frozen Git SHA,
  and a cross-case stable-control fingerprint. A subset is labeled
  `COMPLETED_SUBSET`, never a complete research matrix.
- Fixed the sensitivity runner's completeness-snapshot boundary found during
  review. `artifact_completeness.json` is the container written after the
  final artifact hashes are computed and therefore cannot hash itself; the
  runner now validates its status/schema separately while verifying every
  snapshotted source artifact against the recorded size and SHA-256.
- Updated `run_frontend_controlled_pv_pair.py` to put the revised thesis model
  on the actual formal execution path. Fresh Prepare now records the explicit
  Phase, time limit/gap, trip-energy proxy, research objective preset,
  SOC-taper charging, setup/teardown/minimum-session controls, surplus-PV
  semantics, and unit PV multiplier. The case audit distinguishes a declared
  lexicographic solver objective from scalar accounting equality instead of
  rejecting or mislabelling it.
- Updated the pair manifest to apply the same distinction. Scalar cost cases
  still require exact solver/accounting reconciliation. A declared
  `research_lexicographic_v1` pair instead requires a valid reconciliation
  schema, Rolling as the canonical accounting source, explicit non-scalar
  labels, lexicographic semantics, and the same objective preset in both
  cases. Mixed objective presets fail closed.
- Focused verification completed: trip proxy/platform alias/fingerprint/taper
  tests, assignment audit/artifact completeness, Quick Setup/Prepare scope,
  integrated actual-cost, Stage 2 feedback, and objective-mode tests. A fresh
  full suite also passed (`1340 passed`). A fresh clean-commit formal pair is
  still required before research release.

## 2026-08-11: canonical Rolling reporting snapshot and compact presentation release

- Added `scripts/build_reporting_snapshot.py`, a fail-closed read-only
  postprocessor for an already completed controlled PV pair. It never invokes
  optimization and hashes every required source before and after generation so
  source-run mutation aborts the release.
- Final assignment and used-vehicle counts now come only from
  `graph/trip_assignment.csv`. Energy flows, electricity/fuel/vehicle/CO2 cost,
  accounting total, operational CO2 and terminal energy come only from
  `rolling_hourly_chain/executed_day_accounting.json`. The 24 hourly plots and
  tables come from the accepted Rolling chart relation, while physical and
  solver-quality claims retain their dedicated canonical sources.
- The snapshot intentionally excludes the internal Rolling/search objective and
  the `111500 JPY` return-leg search adjustment. Public reports expose only the
  executed accounting total and its canonical components. High PV is labelled
  `SOLVED_WITHIN_DECLARED_GAP` at `0.735476%`; the low-PV raw
  `objective_limit` result remains visible and is labelled
  `CERTIFIED_NEAR_OPTIMAL` from its independent `0.399008%` certificate rather
  than being relabelled `OPTIMAL`.
- The postprocessor verifies trip coverage, unique vehicle counts, vehicle-day
  cost, canonical cost summation, PV/grid energy balances, hourly-to-daily
  reconciliation, PV-rated-output area/capacity reverse calculations, BESS
  request/accounting SOC consistency, physical validation, 24/24 Rolling,
  solver requested/effective settings, gap certificates, matched
  asset/effective-control hashes, differing PV hashes and the immutable pair
  manifest. It also blocks legacy superseded
  warning text and requires one shared snapshot digest in every public artifact. The
  Python and workbook generators are themselves content-hashed in the snapshot
  and rechecked after generation; release and ZIP targets are restricted to
  safe immediate children of the source pair directory.
- Added `scripts/build_reporting_snapshot_workbook.mjs` using the bundled
  `@oai/artifact-tool` runtime. The workbook separates summary, assignment,
  energy, cost, validation, hourly energy, hourly SOC and provenance sheets;
  comparison differences and chart helpers remain formula-driven. All eight
  sheets are rendered during generation for visual QA and the workbook is
  scanned for formula errors before release.
- Applied the postprocessor without reoptimization to
  `output/formal_pair_20260811_flat30_pv1000_bess6000_phase4_2632de9_gap01_progress`.
  The compact `release/` has 15 files and a sibling `release.zip`, all tied to
  snapshot SHA-256
  `dcd15a8a76c96b663070a7410b2f8fc0c22f9b27f313daab9ce43151106c97ef`.
  It reports high PV as `32 BEV / 0 ICE`, `264 / 0` trips and
  `644741.923030 JPY`; low PV as `21 / 11`, `91 / 173` and
  `698419.690050 JPY`. The input-side `1000 kW` PV rating, reverse-calculated
  `5000 m2` panel area, `14285.714286 m2` required depot area and
  `6000 kWh` BESS are included in the snapshot and workbook.
- This derived bundle is `READY_FOR_PROGRESS_PRESENTATION` and deliberately
  sets `research_submission_ready=false` because the compact postprocessor does
  not assess input realism. It preserves the source pair manifest's separate
  formal readiness field and never rewrites the two standalone case summaries.
- Regression coverage in `tests/test_reporting_snapshot.py` checks canonical
  assignment selection, internal-objective exclusion, near-optimal status
  normalization, vehicle-day mismatch failure, single-digest propagation,
  source/generator immutability, ZIP integrity, output-path containment and
  stale-warning rejection. Workbook release also fails closed unless all eight
  sheets and previews exist and the formula-error count is exactly zero.
- Final verification passed `34` focused reporting/pair/README regressions and
  the complete repository suite (`1279 passed in 59.47s`). Independent release
  audit rehashed all 24 canonical source files plus both generator files,
  confirmed all `38/38` release gates, the exact 15-file release/ZIP inventory,
  zero workbook formula errors, one shared snapshot digest, and no legacy
  warning or internal return-leg objective value. All six public figures and
  all eight workbook-sheet renders were visually inspected; the one cost-chart
  legend collision found
  during review was corrected before the final release was generated.

## 2026-08-11: progress-report evidence bundle and cumulative work record

### Fresh formal pair evidence at frozen SHA `2632de9`

- The current implementation was committed as
  `2632de9962e85138c0fe6e4d3da1c74122c3dfff`, the worktree was verified
  clean, and a dedicated no-reload BFF was started from that frozen commit.
  Both cases then used fresh Prepare and the ordinary frontend HTTP job path;
  the ending SHA was unchanged and the ending porcelain status was empty.
- The saved frontend inputs were used without a command-line PV-capacity
  override: PV rated output `1000 kW`, estimated installable panel area
  `5000 m2`, capacity-implied depot area `14285.714286 m2`, BESS
  `6000 kWh / 900 kW`, BESS initial/terminal target `3000 / 3000 kWh`, ten
  chargers, grid energy `30 JPY/kWh`, and demand charge `0 JPY/kW`.
- The controlled pair holds the `2025-08-05` weekday timetable, 264 trips,
  60 active vehicles, initial SOC, charger and non-PV depot assets, tariff,
  seed and day-ahead/Rolling controls fixed. The comparison-control hash is
  `a5504ea4a0a13bb7870475aed85859a6dd71c6272603739ff8ecbb6aa0f7b1fd`;
  only the separately hashed PV curve differs. High PV supplies
  `6056.250 kWh`, while the low-PV curve sourced from `2025-08-10` supplies
  `996.200 kWh`.
- The high-PV solution uses `32 BEV / 0 ICE` and assigns `264 / 0` trips;
  its canonical executed-day total is `644741.923030 JPY`, grid import is
  `155.472886 kWh`, fuel is zero, operational CO2 is `77.736443 kg`, and the
  certified MILP gap is `0.735476%`. The low-PV solution uses
  `21 BEV / 11 ICE` and assigns `91 / 173` trips; its total is
  `698419.690050 JPY`, grid import is `124.985104 kWh`, fuel is
  `357.881339 L`, operational CO2 is `987.936116 kg`, and its gap is
  `0.399008%`. Thus the controlled high-PV response is `+11` used BEVs and
  `+173` BEV trips, with `53677.767020 JPY` lower executed cost and
  `910.199673 kg` lower operational CO2.
- Both cases serve `264/264` trips, complete `24/24` accepted Rolling steps,
  pass physical schedule, charger, BEV/BESS terminal SOC, grid contract,
  objective/accounting, artifact, provenance and solver-control checks, and
  reconcile the canonical cost components within floating-point tolerance.
  The exported matrix contains `70/70` passing gates (30 per case and 10 at
  pair scope). `completion_audit.json` is `READY`; the immutable pair manifest
  has `formal_research_submission_ready=true` and no failed check.
  Standalone case files intentionally retain only
  `controlled_counterfactual_pair_not_verified`; pair-scope claims must cite
  `pair/pair_manifest.json` rather than relabel either standalone summary.
- The evidence directory is
  `output/formal_pair_20260811_flat30_pv1000_bess6000_phase4_2632de9_gap01_progress/`
  and the matching archive is the same path with `.zip`. Its progress bundle
  contains seven comparison figures in PNG/SVG, six CSV tables and links to
  all ten per-run detailed figures. Independent inspection opened all 17 PNG
  figures and all six workbook sheets; both `results.xlsx` files have zero
  formula-error matches. All 106 indexed source artifacts and 22 generated
  artifacts match their SHA-256 entries. The ZIP contains 748 files with no
  CRC, path, presence or byte-hash mismatch.

### Cumulative implementation evidence

- Frontend scenario persistence was traced from the Tk editor through the BFF
  scenario DTO and Prepare materialization. Saved flat energy price, demand
  charge, PV rated output, BESS capacity/power/SOC and their explicit input
  modes are now preserved instead of being overwritten by derived defaults.
  A manually entered PV rating is authoritative; the estimated installable
  panel area and area-equivalent depot capacity are reverse-calculated from
  that rating while the stored physical depot-area observation remains
  unchanged.
- Same-service-date PV counterfactual Prepare now carries the explicit
  comparison type and the fixed-weekday-timetable waiver only when required.
  The high-PV and low-PV cases therefore share service date, timetable, route
  scope, selected-depot fleet/initial state, chargers, BESS, tariff and solver
  controls; only the separately hashed PV curve differs.
- Formal and diagnostic execution semantics remain separated. Formal frontend
  execution requires a clean frozen Git SHA before submission and verifies the
  same SHA/dirty state after solving. Diagnostic dirty-tree runs remain
  non-submission evidence and cannot become teacher-ready through a UI label
  or report postprocessor.
- The assignment/energy work introduced source-aware Stage-1 recourse,
  adjacent used-powertrain composition search, unused-BEV activation
  neighborhoods, exact Stage-2/physical screening, objective/accounting
  reconciliation and the unrestricted integrated Phase-4 actual-cost model.
  No weather coefficient, BEV minimum, timetable rewrite, fallback or
  post-solve repair was added. The 2026-08-10 clean pair demonstrates the
  intended response: high PV selected 32 BEVs/0 ICE and all 264 BEV trips;
  low PV selected 21/11 and 91/173 trips under the same non-PV controls.
- Reporting corrections distinguish the Phase-3 primary seed composition from
  the final integrated assignment, retain canonical header-only fuel CSVs for
  all-BEV solutions, use the predeclared Phase-4 gap in pair auditing, and keep
  standalone-case and pair-level release scopes immutable and separate.

### New progress-report artifact contract

- `scripts/build_frontend_pv_pair_progress_report.py` is a read-only pair
  postprocessor. It reads executed-day accounting, assignment timelines,
  solver certificates, physical/Rolling gates, pair controls and both
  literature-figure manifests. It does not recalculate monetary totals from
  plotted values and does not modify either source run.
- A completed controlled pair now automatically writes `progress_report/`
  with seven comparison figures in both PNG and SVG, six analysis-ready CSV
  tables, a Japanese progress-report Markdown summary, an exhaustive case/pair
  validation-gate matrix, a catalog of the existing five detailed figures per
  run, and an `evidence_index.json` containing file size and SHA-256 lineage
  for every required source and generated artifact.
- The seven pair figures cover headline status/KPIs; used vehicle and trip
  composition; executed PV/BESS/grid flows; 24-hour energy profiles; canonical
  cost components; fuel/operational CO2; and certified MILP gaps plus selected
  acceptance gates. The case-level `results.xlsx` files and ten detailed
  literature figures remain in their canonical run directories and are
  referenced rather than copied or rewritten.
- `run_frontend_controlled_pv_pair.py` persists `case_gate_audits.json`, invokes
  the new builder before packaging, records its subprocess evidence, and
  blocks pair completion when the progress bundle is absent or incomplete.
  This is an evidence-completeness gate; it does not upgrade a BLOCKED model or
  case claim to READY.
- A read-only replay against a junctioned copy of the prior clean pair produced
  all 7 figures, 6 tables and 10 per-run figure references without changing a
  source hash. Focused regression tests cover output completeness, source
  immutability, lineage hashes, 48 hourly rows, gate export and overwrite
  refusal and manifest path confinement (`33 passed`). The complete repository
  suite passes (`1265 passed in 60.01s`), along with `compileall` and
  `git diff --check`. The fresh frozen-SHA run documented above now satisfies
  the current-code evidence requirement; the earlier replay remains only a
  visualization regression check.

## 2026-08-10: preserve empty fuel schemas for all-BEV solutions

- Fresh SHA-`6853eda` Phase-4 calculations produced a physically and
  economically valid sunny all-BEV result (`32/0`, 264/0 trips,
  `644,741.923030 JPY`, certified gap `0.735476%`) and a rain `21/11` result
  (`698,419.690050 JPY`, certified gap `0.399008%`). Both completed 24/24
  Rolling, but the sunny frontend job failed during final artifact enforcement.
- The failure was an export-contract defect: `fuel_canonical_ledger.csv`,
  `fuel_timeseries.csv`, and `fuel_summary.csv` were zero bytes when their row
  sets were empty. The exporters now write canonical headers for empty fuel
  relations, matching the existing zero-refuel-event convention. Non-empty
  fuel rows and all cost/model semantics are unchanged.
- The all-BEV graph regression now requires all three fuel artifacts to be
  nonzero, schema-readable CSVs with zero data rows. The failed SHA-`6853eda`
  pair remains diagnostic; formal pair evidence requires a new clean commit
  and fresh Prepare for both weather cases.

## 2026-08-10: bounded Phase-4 seed improvement and source-coupled proof floor

- The prior full Phase-4 model had a verified feasible start but could spend
  3,600 seconds without processing a branch-and-bound node.  Removing
  endpoint away-from-depot rows that are LP-dominated by the corresponding
  endpoint trip activity row reduces the measured model from 1,929,173 to
  1,587,351 constraints while preserving 776,752 variables.  The proof uses
  `start[v,r] <= y[v,r]` and `x[v,i,j] <= y[v,i], y[v,j]` from node flow; no
  implications are summed or weakened.
- A bounded candidate generator now runs between the neutral Phase-3 seed and
  integrated preflight.  Whole duties may be remapped from used ICE to unused
  BEV, swapped between used BEV/ICE identities, or exchanged between BEV
  identities.  Stale charging, SOC, source-flow, refuelling and ledger fields
  are cleared before exact Stage 2 reconstructs them.  Acceptance requires a
  Stage-2 incumbent, `FeasibilityChecker.feasible`, canonical accounting
  feasibility and a strict cost reduction.  The search has a 120-second wall
  limit, 5-second per-candidate limit and 512-evaluation cap; it introduces no
  weather coefficient, BEV quota or global-optimality claim.
- Diagnostic replay of the old clean pair plan finds a sunny all-BEV
  fixed-dispatch recourse at `644,741.923029935 JPY` with 155.472886 kWh grid
  purchase.  The rain neighborhood retains `21/11` at
  `698,419.690050 JPY`; the maximum observed feasible count is `30/2` at
  `710,619.401404 JPY`.  These results explain why sunny EV use should rise,
  while also showing why maximum feasible EV count and minimum actual cost
  must remain separate questions.  They are dirty-worktree diagnostics, not
  formal pair evidence.
- The weather energy/fuel lower bound now solves the continuous relaxation

  `min C_ICE(path) + c_grid * E_grid`

  subject to continuous powertrain path coverage and

  `E_free + E_grid = E_BEV_service + E_BEV_start + E_BEV_arc + E_BEV_return`,
  `0 <= E_free <= pooled admissible PV/BESS/vehicle-SOC source energy`.

  Service/start/return quantities use the minimum compatible vehicle value;
  connection quantities use the minimum compatible powertrain arc value.
  Vehicle identity, fleet path counts, timing, charger occupancy and depot
  source coupling are relaxed and all omitted objective terms must be
  nonnegative.  Therefore the LP is optimistic and its maximum with the older
  independent-trip floor is still a valid lower bound.  Its sorted coefficient
  payload receives an input SHA-256 which is included in the outer certificate
  hash.
- Applying that certificate to the prior inputs yields an energy/fuel floor of
  `0 JPY` sunny and `55,632.938123641 JPY` rain.  Adding the separately proven
  32-bus vehicle-day floor gives `640,000.000000` and `695,632.938123641 JPY`;
  the diagnostic incumbent gaps are `0.735476%` and `0.399008%` respectively.
  Phase 4 now derives a `BestObjStop` threshold from this independently audited
  floor only when exact integrated fixed-dispatch recourse has already
  supplied a complete feasible start within the requested gap.
- `run_frontend_controlled_pv_pair.py` retains the 0.1% default but accepts a
  validated `--actual-cost-mip-gap` so a distinct 1% experiment can be
  declared before fresh Prepare.  It records that target in environment and
  optimization-request evidence.  Focused cost, pair-runner, strict-model and
  neighborhood regressions pass (`74`), and the complete repository suite
  passes (`1260 passed in 61.38s`).  A clean formal pair is still required
  before release status changes.

## 2026-08-10: distinguish the final integrated fleet from its Stage-1 seed

- Audit of
  `formal_pair_20260809_flat30_pv1000_bess6000_phase4_witness_99a2035_gap001`
  found a presentation ambiguity, not a missing weather response.  Phase 4
  finally uses `27 BEV / 5 ICE` in sun and `21 / 11` in rain.  The `13 / 19`
  composition belongs to the Stage-1 primary candidate inside Phase-3 seed
  generation; treating it as the Phase-4 result discards both Stage-2
  candidate selection and the unrestricted integrated incumbent.
- `bff/routers/optimization.py` now emits an explicit final composition plus
  the separately named Stage-1 primary composition.  The Tk summary reader
  prefers the final field and labels the Stage-1 field “not the final
  solution”.  Phase-4 seed audit also records the selected Stage-2-feasible
  seed composition and its Stage-1 objective/bound provenance.
- The sunny result has 6,056.25 kWh of PV, zero grid import and 3,606.64 kWh of
  curtailment.  Consequently, adding nameplate PV cannot by itself move the
  current 27-BEV boundary.  Candidate `28/4` assignments must still align each
  duty's departures and terminal target with vehicle-local charge windows and
  shared chargers.  The current evidence rejects two assignments, not the
  entire composition.
- The optimistic Stage-2 path audit is now chronological.  It records charge
  deliverable before each departure, departure/minimum/terminal SOC shortage,
  and an individually feasible flag while retaining the old whole-day energy
  total as a non-authoritative aggregate diagnostic.
- IIS feedback is deliberately scoped.  An IIS containing only vehicle-local
  SOC and charging-availability rows produces an exact-pattern no-good for the
  implicated vehicle(s).  Shared capacity rows, unknown rows or IIS variable
  bounds retain the conservative full-assignment no-good.  The decision and
  IIS-bound inventory are exported in feedback history and diagnostics.
- Clean SHA `4e0558d` began a fresh sunny run, but it was stopped before a
  result when Windows committed bytes reached 85.8/92.1 GB (93.1%).  The
  process still had physical memory available, so monitoring only working-set
  RAM would have missed the failure risk.  This run is diagnostic and the rain
  case was not started.
- Root review identified the new activity aggregation as mathematically
  integer-equivalent but LP-weaker: `m*a + sum(b) <= m` does not preserve the
  relaxation of every `a + b_i <= 1` row.  The aggregate and its refuel
  activation binaries are therefore removed and the strong individual
  implications restored.  Gurobi node files still start at 0.5 GB in the OS
  temporary directory, but node spill cannot repair a weak or memory-heavy
  root relaxation.  `DegenMoves=0` remains reverted as well.
- Clean SHA `612e4a7` then reproduced the same candidate frontier with the
  restored strong rows: `32/0`, `31/1`, `30/2`, `29/3` and two `28/4`
  assignments all failed exact Stage-2 recourse, with a maximum chronological
  shortage of 111.30337352 kWh in the `28/4` diagnostics.  The integrated
  fixed-dispatch recourse preflight nevertheless reached 96.4% Windows commit
  before branch-and-bound node growth.  The root cause is therefore not the
  rejected aggregate alone and not a branch-tree spill failure.
- Phase 4 now applies the same weather-neutral memory controls to the recourse
  preflight and the final integrated solve: dual-simplex root and node LP
  methods (`Method=1`, `NodeMethod=1`) and `SoftMemLimit=32 GB`.  Automatic
  concurrent root methods can retain multiple model copies; forcing one
  simplex method avoids that avoidable duplication.  A soft limit returns a
  recorded `memory_limit` termination instead of risking an operating-system
  commit failure.  The values are promoted into plan, solver-settings and
  search-profile evidence.  The exact MILP rows and cost coefficients are
  unchanged, so a memory-limited run remains diagnostic and release-blocked.
- The existing controlled pair remains `BLOCKED` at 3.927573% sunny and
  2.387096% rain certified gaps versus the requested 0.1%.  A new clean frozen
  commit, fresh Prepare and both complete runs are required before any release
  claim changes.  The `1248 passed` suite preceded the rejected formal run;
  after restoration, focused regressions pass (`136`) and the complete suite
  passed (`1247 passed in 55.79s`).  The root-memory correction passes 153
  focused regressions and the complete suite (`1247 passed in 58.22s`).  A new
  clean commit is required next.

## 2026-08-10: clean witness-cutoff pair and post-run evidence fixes

- Frozen SHA `99a2035694fd90fccf42fe8222a4f1d3b344e83e` completed the
  controlled same-service-date pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_witness_99a2035_gap001`.
  Both cases use fresh prepared inputs, serve 264/264, preserve the fleet and
  initial-state hashes, pass physical validation, terminal BEV/BESS SOC,
  executed-day accounting and 24/24 Rolling. Pair comparison checks all pass;
  only the separately hashed PV profile differs.
- Sunny remains `27 BEV / 5 ICE`, 183 / 81 trips, 6,056.25 kWh PV, zero grid
  import and 666,164.082366 JPY. Rain remains `21 / 11`, 91 / 173 trips,
  996.2 kWh PV, 124.985104 kWh grid import and 698,419.690050 JPY. This is a
  verified PV response of six used BEVs and 92 BEV trips without a weather
  objective bias.
- Exact 25--27 BEV targets terminate with `SOLUTION_LIMIT` after about 3.6
  seconds. Exact `28/4` now receives 47.798 seconds (previously 11.696) but has
  no Stage-1 incumbent. Two complete 28/4 constructive candidates reach Stage
  2 and are infeasible in about 0.16 seconds each. The target remains
  unresolved because no composition-wide infeasibility certificate exists.
- Formal readiness is false. The analytical certified gaps are 3.927573%
  sunny and 2.387096% rain versus the requested 0.1%; the raw Gurobi bound is
  zero and raw gap is 100% in both cases.
- Post-run review found that `research_comparison.md` sourced only
  `stage1_certified_mip_gap_ratio`, so its Phase-4 certified-gap row was blank
  even though formal gating used the correct integrated field. `_solver_row`
  now prefers `certified_mip_gap_ratio` and falls back to the Stage-1 field.
- Phase-4 problems now attach the Phase-3 candidate diagnostics directory so
  internal fixed-assignment Stage-2 failures can write IIS, energy-shortage and
  vehicle-path evidence. Recursive no-good feedback remains enabled only for a
  direct Phase-3 run, so this diagnostics fix does not alter Phase-4 search
  semantics. Focused regressions pass (`35`), compileall/diff checks pass and
  the complete suite passes (`1242 passed in 64.24s`). Fresh evidence for
  these post-run changes is pending.

## 2026-08-09: exact-composition search stops at its first feasibility witness

- The fresh adjacent pair established feasible Stage-2 compositions from
  `7/25` through `27/5`, but every easy exact-composition solve continued to
  close its Stage-1 objective gap after finding an incumbent. Exact `28/4`
  consequently received only 11.696 seconds and remained unresolved; two
  constructive duties failed Stage 2, which is not composition-wide proof.
- Exact used-powertrain targets are candidate-generation feasibility problems,
  not independent optimality claims. Their Gurobi solve now sets
  `SolutionLimit=1`, records
  `search_termination_policy=first_incumbent_feasibility_witness`, extracts the
  unchanged-model incumbent, and returns unused shared time to later targets.
- Frontier sensitivity targets retain their existing optimization policy. If
  an exact target has no solution, `SolutionLimit` never triggers: the model
  can still reach the allocated time limit or `INFEASIBLE`, followed by the
  existing IIS and model-hash certificate checks. The prior solution limit is
  restored after every temporary target.
- The change is neutral with respect to weather and powertrain economics.
  Stage 2 still performs exact charging/PV/BESS evaluation and final candidates
  are selected by canonical actual cost. Focused regressions pass (`54`),
  compileall/diff checks pass, and the complete suite passes (`1240 passed in
  56.27s`). A new formal pair is pending.

## 2026-08-09: adjacent pair result and certified-gap audit correction

- Frozen SHA `32e3509cacd6309675bef2e850405e07483b24fb` completed the fresh
  controlled 1,000-kW-PV / 6,000-kWh-BESS pair. Both cases serve 264/264,
  preserve the Git SHA, pass independent physical validation, 24/24 Rolling,
  terminal SOC and canonical/executed-day accounting. Pair controls match and
  only the separately hashed PV curve differs.
- Sunny selects `27/5` with 183 BEV trips, zero grid purchase and
  666,164.082366 JPY. Rain selects `21/11` with 91 BEV trips, 124.985104 kWh
  grid purchase and 698,419.690050 JPY. The same candidate search recovers
  many feasible compositions in both cases; Stage 2 canonical actual cost
  creates the six-BEV and 92-trip response without a weather bias.
- Exact `28/4` obtained no Stage 1 incumbent in 11.696 seconds. Two complete
  constructive `28/4` assignments were evaluated and rejected by Stage 2.
  The target correctly remains unresolved: failure of those assignments is
  not a proof that every `28/4` assignment is infeasible.
- The completion runner incorrectly used integrated `achieved_mip_gap` (raw
  Gurobi gap) as `certified_gap`. The canonical artifacts retain the correct
  values: 3.927573% sunny and 2.387096% rain versus raw 100%. A pure helper now
  selects `certified_mip_gap_ratio` for integrated formal gating and fails
  closed when it is missing; Phase 3 continues to use
  `stage1_certified_mip_gap_ratio`.
- The gate correction does not change this pair's result because both
  certified gaps still exceed 0.1%. New-code formal evidence remains pending.
- The focused frontend/research/optimization regressions pass (`81`), the
  complete repository suite passes (`1240 passed in 64.68s`), and re-reading
  the completed pair through the corrected gate returns 0.0392757 sunny and
  0.0238710 rain without modifying the old artifacts.

## 2026-08-09: adjacent feasible-continuation fixes seed-search starvation

- Fresh sunny job `60af38bd-c548-4971-aeae-3fc3785945b9` from clean SHA
  `beb13e303ce272b77caf719f8e745c65c22668cd` used fresh frontend Prepare and
  reproduced `27 BEV / 5 ICE`, but its target telemetry identified a search
  regression. Exact `32/0`, `31/1`, `30/2` and `29/3` each consumed about 60
  seconds without an incumbent. `28/4` was reached with only 10.156 seconds
  remaining, and `27/5` received 1.999 seconds. The rain job was aborted after
  this deterministic defect was established; the incomplete pair is not
  research evidence.
- A separate short diagnostic had already recovered a physically valid
  `28/4`, 199-BEV-trip sunny seed at 660,983.783805 JPY. That diagnostic used
  an older prepared input and is not formal evidence, but it falsifies the
  assumption that the cost-ranked run had proved `28/4` unavailable.
- Exact-composition feasibility traversal now sorts by absolute distance from
  the primary feasible used-powertrain composition, preserving the original
  symmetric `+1, -1, +2, -2, ...` order. Direction-specific state therefore
  continues `K -> K+1` (or `K -> K-1`) from the last feasible MIP start rather
  than jumping directly from the primary mix to an extreme target.
- Remaining composition time is divided equally among remaining targets and
  capped by the configured per-target limit. Optimistic constructive cost is
  still exported for audit, but it does not order feasibility solves. Stage 2
  candidate evaluation remains `canonical actual cost ascending`, so the
  change introduces neither a weather strategy nor a BEV lower bound.
- Focused regressions cover order, equal budget sharing, continuation warm
  starts and Stage 2 cost selection (`80 passed`); the complete suite passes
  (`1239 passed in 59.56s`). Fresh clean-commit pair evidence remains required
  before claiming an improved feasible seed or formal optimality.

## 2026-08-09: superseded cost-prioritized exact fleet-mix search

- Clean commit `c819e36fdf5c315d0132015bb6e7154a31708cec` was exercised through
  the BFF with the previous sunny prepared input as a diagnostic-only run.
  The new objective cutoff and 34-vehicle-day cap were present, but 300 seconds
  still produced raw bound `0`, raw gap `100%`, node count `1`, and a weak
  690,112.753616 JPY seed because the shortened request evaluated only through
  22 BEVs. It is not fresh-Prepare or research evidence.
- A second Phase 3 diagnostic set `used BEV >= 32`. It found a physically valid
  but policy-distorted 32-BEV / 19-ICE / 51-bus candidate at
  1,087,748.735571 JPY; the ordinary 13/19 candidate remained cheaper. This
  confirms that the one-sided frontier must remain a policy sensitivity and
  cannot repair actual-cost minimization.
- Artifact inspection identified the neutral search defect: formal exact mixes
  `32/0`, `31/1`, `30/2`, `29/3`, and `28/4` received only 2.694--3.465
  seconds each. Their reconstructed starts failed Stage 2, but alternative
  assignments at those same mixes were not searched enough to establish a
  physical boundary.
- Exact fixed-total targets at this historical point carried an audited
  constructive-dispatch optimistic cost and were solved in ascending cost
  order. The subsequent fresh run showed that this jump-to-extreme ordering
  starved adjacent continuation; it is superseded by the section above.
- Focused composition/integrated/BFF research-contract regressions pass (`61`)
  and the full suite passes (`1239 passed in 55.35s`).

## 2026-08-09: verified incumbent cutoff after complete-candidate pair

- Clean SHA `96f17e10175d614d29f45ee79df95cf70ff4e6eb` completed the
  fresh controlled pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_constructive_96f17e1_gap001`.
  Both cases served 264/264, passed independent physical validation and 24/24
  Rolling, reconciled solver/canonical/executed-day accounting and retained a
  clean unchanged Git SHA. Pair manifest v2 accepts the controlled PV
  sensitivity and correctly leaves formal readiness false.
- Candidate rescue is exercised, not merely unit-tested. Each case evaluated
  29 candidate rows. Constructive 32/0, 31/1, 30/2, 29/3 and 28/4 starts were
  sent to Stage 2 first and rejected as energy/charging infeasible for those
  exact duties. Sunny selected the feasible 27/5 candidate at 666,164.082366
  JPY; rain selected 21/11 at 698,419.690050 JPY. These failures do not certify
  every alternative assignment at those compositions.
- The remaining blocker is integrated proof. Sunny records a 640,000 JPY
  independent lower bound and 3.927573% certified gap. Rain records
  681,747.739537 JPY and 2.387096%. Raw Gurobi bound remains zero in both runs;
  the 776,752-variable / 1,929,173-constraint model reaches only root node one
  in the 3,600-second budget.
- `_verified_start_objective_search_bounds()` now derives a canonical objective
  cutoff from the independently solved fixed-dispatch recourse model. The
  unrestricted model adds `objective <= verified_seed_cost + tolerance`, which
  preserves the verified solution and every improvement. When the existing
  nonnegative-term audit passes, the same certificate adds a common
  vehicle-day count upper bound (33 days for the sunny incumbent, 34 for rain).
  Negative objective terms or a disabled vehicle-usage component disable the
  count bound; no hidden directional preference is introduced. The automatic
  cutoff is disabled when canonical cost is not the sole primary objective, so
  partial-service multiobjective and maximum-EV lexicographic cases retain
  their separate explicit policy contracts.
- Verified integrated starts now use `MIPFocus=3`, `Heuristics=0.01` and
  `Presolve=1`. An unverified start retains the feasibility-oriented controls.
  Solver metadata exports both new constraint counts, the exact bound inputs
  and blockers. This changes search performance only, not feasible schedules,
  objective coefficients or accounting semantics. Focused tests pass (`41`)
  and the complete suite passes (`1237 passed in 54.15s`). Fresh clean-run
  evidence is required before claiming an optimality improvement.

## 2026-08-09: complete dispatch promotion and independent integrated gap

- The PV-1000 pair at clean SHA `93d122e` reached 27 BEVs in sunny and 21 in
  rain, but exact 28--32-BEV target solves ended after roughly three seconds
  with no incumbent. Their activation-replacement builders had already formed
  complete discrete dispatches. The old path discarded those structures unless
  Gurobi reproduced an incumbent inside the short target solve, so the result
  confused a computational frontier with a physical/economic boundary.
- `_build_vehicle_duties_from_selected_assignment_keys()` now reconstructs
  duties from complete selected assignment, successor and start keys. Promotion
  requires exact duplicate-free trip coverage, in-domain arcs, unique incoming
  and outgoing successors, balanced start/end fragments, the exact activated
  vehicle set and the requested powertrain composition.
- Promotion occurs only when the corresponding target solve has no incumbent
  and is not infeasible. A normal solver incumbent retains the previous path;
  an IIS-backed infeasible target is never overridden. Promoted plans explicitly
  state that Stage 1 energy recourse is uncertified and must pass exact Stage 2
  plus independent physical validation before cost comparison.
- Candidate priority preserves honest cost semantics. Native candidates retain
  their weather-aware relaxed objective. Constructive candidates use exact ICE
  fuel/CO2, fixed-vehicle and vehicle-day costs while omitting other terms. It
  is labelled a valid lower bound only when the analytical nonnegative-term
  guard passes; otherwise it is an uncertified priority score. Neither value is
  substituted for Stage 2 canonical actual cost.
- `MILPSolverOutcome`, engine metadata and BFF solver settings now preserve
  `raw_best_bound` / `raw_mip_gap_ratio` separately from
  `certified_best_bound` / `certified_mip_gap_ratio`. For integrated Phase 4,
  the certified bound is `max(Gurobi ObjBound, independent analytical floor)`
  clamped to the incumbent. Phase 3 Stage 1 certificates remain separately
  named and are not relabelled as integrated proof.
- Focused composition, integrated actual-cost, BFF, pair-runner, Rolling and
  research-contract tests pass; the complete suite passes `1233` tests in
  `54.29s`. Fresh Prepare and a clean frozen-commit frontend pair remain
  necessary before the new candidate coverage or certified gap becomes
  research evidence.

## 2026-08-09: Phase 4 seed wall-budget starvation correction

- Fresh sunny run `output/2026-08-09/run_20260809_0608` from clean SHA
  `bf3fc2907fe852b39aa303272287e2133bd628a9` confirmed that the symmetry-safe
  composition starts restored Stage 1 incumbents across 7--27 used BEVs. The
  lowest sunny Stage 1 relaxed objective was the 27-BEV/5-ICE candidate at
  666,164.082366 JPY. This is candidate evidence, not a physical or optimal
  result.
- The run nevertheless ended `NO_VALID_INCUMBENT`: Phase 3 seed runtime was
  485.502 solver seconds, but exact-composition model construction consumed the
  shared 600-second wall deadline. All 21 Stage 2 evaluations were marked
  `not_run_feedback_budget_reserved`; the selected candidate hash was empty,
  integrated warm start was rejected as `baseline_is_not_verified_phase3_seed`,
  and Phase 4 found zero incumbents in 3,600 seconds. Rolling correctly did not
  start, and the result remains diagnostic.
- `_with_verified_phase4_phase3_seed()` now distinguishes declared solver time
  from model-build wall allowance. Stage 1/Stage 2 limits remain 480/120
  seconds. The shared wall envelope receives a deterministic allowance of 10
  seconds per reachable requested alternative, capped at 600 seconds. Audit
  fields persist seed solver budget, seed wall budget, overhead allowance and
  the existing combined solver budget separately.
- Before physical Stage 2 evaluation, the unchanged Stage 1 candidate set is
  ordered by finite weather-aware relaxed objective and then candidate hash.
  This prevents generation order from starving the economically best sunny
  high-BEV candidate. Stage 2 canonical physical cost still selects the final
  plan; no BEV minimum, weather bias, fallback or repair was added.
- The failed sunny artifacts were retained. The automatically launched rain
  run was terminated before changing code because the same deterministic
  handoff defect made the pair incapable of satisfying the formal contract.
  A fresh Prepare and clean-commit controlled pair remain required.
- Focused seed/composition/Gurobi/BFF/runner/Rolling tests pass, followed by the
  full repository suite (`1230 passed in 63.76s`).

## 2026-08-09: controlled-pair diagnosis and symmetry-safe composition starts

- Frozen SHA `14bbcfa1ba97889674e113eae44bfa3ec71577e0` completed the
  flat-30/no-demand/PV-1000/BESS-6000 frontend pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_proof_14bbcfa_gap001`.
  Both cases served all 264 trips, passed independent physical validation and
  24/24 Rolling, and reconciled the integrated objective to executed-day
  accounting with zero residual. Both remained `FEASIBLE_CANDIDATE` /
  `BLOCKED` because the 0.1% gap was not established.
- Sunny and rain both selected 16 BEVs / 16 ICE buses and 58 / 206 trips at
  704,401.909629 JPY. Sunny generated 6,056.25 kWh and curtailed about
  5,344.07 kWh; rain generated 996.2 kWh. The selected assignment charged only
  650.493 kWh, so even rain supplied it from PV/BESS with zero grid purchase.
  Equality at this low-BEV incumbent is therefore expected; it says nothing
  about the unsearched high-BEV region.
- The inventory-wide exact-composition loop allocated only 3.4--3.8 seconds to
  each target. It found physical candidates from 7 through 16 used BEVs; all
  17--32 targets were time-limit/no-incumbent, not infeasibility certificates.
  The previous clean SHA had reached 27 BEVs with the same nominal per-target
  budget, identifying activation-prefix warm-start construction as the
  regression rather than the mathematical model.
- Composition replacements again choose source duties by their deterministic
  energy score. A new exact-identical-vehicle bijection then remaps only active
  identifiers onto the activation prefix. This keeps every start compatible
  with the symmetry cuts without forcing the suffix identifier's potentially
  unsuitable duty into a BEV. The remap and normalization flag are persisted
  in the composition certificate.
- The all-budget proof profile (`MIPFocus=3`, `Heuristics=0.01`) left the root
  bound at zero and preserved the weak seed. Since the same full model also
  fails to finish its root relaxation under the incumbent profile, Phase 4 now
  uses `MIPFocus=1`, `Heuristics=0.5` after a verified start so it can improve
  a weak incumbent; no claim is made that this proves the requested gap.
- The controlled-pair payload and formal audit now both require four Gurobi
  threads. Phase 4 seed audit metadata also carries the Phase 3 candidate rows,
  selected hash, and recourse configuration so a same-assignment investigation
  can audit actual alternatives and verify that arbitrary weather bias is off.

## 2026-08-09: Phase 4 bound certification and exact fleet symmetry

- The latest clean pair produced a lower-cost sunny incumbent with 27 BEVs / 5
  ICE buses and a rain incumbent with 21 / 11, but each 776,752-variable,
  1,929,148-constraint integrated solve processed one node and stopped at a
  100% raw gap with best bound zero. The result diagnoses proof-search failure;
  it does not establish either fleet composition as optimal.
- The initial implementation applied `MIPFocus=3`, `Heuristics=0.01`, and
  `Presolve=2` after verified fixed-dispatch recourse. The subsequent clean
  pair above showed that this did not advance the root bound and could preserve
  a weak incumbent; it has been superseded by the incumbent-improvement
  profile documented above.
- Phase 4 adds an integer-valid total-cost floor equal to the strict relaxed
  path-cover vehicle-day floor plus the existing optimistic weather-aware
  service energy/fuel floor. It ignores deadhead, timing, charger contention,
  demand and other nonnegative costs. The constraint is fail-closed when
  partial service, a non-total-cost objective, a non-actual-cost model, a
  negative fixed vehicle cost, a negative weather term, or a return-leg reward
  could invalidate it. Its components, certificate hash, blockers and applied
  constraint count are persisted through the engine and BFF.
- Exact identifier-permutation symmetry is removed with activation prefixes
  only when every `ProblemVehicle` solver-relevant field except `vehicle_id`
  matches. Baseline-active IDs precede unused IDs, preserving the complete MIP
  start. Adjacent composition warm starts use the same ordering, and each next
  delta starts from the last feasible adjacent composition instead of always
  rebuilding from the primary composition.
- The first clean execution with eight threads reached about 58 GB of private
  allocation and left less than 1 GB of OS virtual-memory headroom. It was
  stopped before an out-of-memory failure and is diagnostic only. The
  interactive BFF/Tk contract therefore fixes Gurobi at four threads rather
  than one, records requested/effective values, and keeps both controlled cases
  identical. This changes search resources, not the mathematical feasible set,
  prices, PV/BESS flows, or objective semantics.
- Focused cost, composition, research-contract, runtime-control and frontend
  regressions pass (`159 passed`), and the complete suite passes (`1,226
  passed`). Fresh clean-commit Prepare and both complete frontend cases remain
  necessary before these changes are research evidence.

## 2026-08-08: inventory-span composition targets are count-valid

- Exact used-powertrain composition search now omits negative BEV/ICE targets
  before exporting the formal certificate. Non-negative targets beyond the
  selected inventory remain as explicit inventory-boundary evidence and are
  never solved. This keeps large inventory-scaled radii compatible with the
  fail-closed pair-artifact validator; the validator itself remains strict.
- A regression test exercises a radius much larger than the synthetic fleet and
  requires every exported target count to remain non-negative; the existing
  one-powertrain Phase 4 seed test preserves the no-adjacent-inventory boundary.

## 2026-08-08 controlled-pair diagnosis and adaptive seed span

- Frozen SHA `4cb571ade840d9147dd3c91d00718dfbdc531163` completed the
  frontend-controlled flat-30/no-demand/PV-1000/BESS-6000 pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_radius10_4cb571a_gap001`.
  Pair controls and fleet/timetable/initial-state hashes matched; only the PV
  profile hash differed. Both jobs served 264/264, passed physical validation
  and 24/24 Rolling, retained `objective_is_actual_cost=true`, and reconciled
  objective and executed accounting total exactly.
- Sunny selected 23 BEVs / 9 ICE buses and 121 / 143 trips at
  685,663.511395 JPY. It used 1,563.002 kWh of 6,056.25 kWh PV input and zero
  grid energy. Rain selected 21 / 11 and 91 / 173 at 698,419.690050 JPY. It
  exhausted 996.2 kWh PV and purchased 124.985 kWh grid-to-bus energy. Rain's
  candidate objective fell through 21 BEVs, then rose for 22 and 23; sunny's
  objective was still falling at the 23-BEV boundary.
- The full integrated model has roughly 776,752 variables and 1,929,148
  constraints. Both cases processed only one node and stopped at 100% gap, so
  the verified Phase 3 seed determined the incumbent. These are physically
  valid controlled-sensitivity candidates, not global optima.
- The run exposed that the previous fixed radius ten was still primary-point
  dependent: the fresh primary was 13 BEVs, not the earlier 18, so the search
  stopped at 23 and omitted the known feasible 25-BEV region. Phase 4 now
  derives the neutral candidate limit and symmetric radius from the selected
  available vehicle count, subject to an explicit 100-vehicle research cap.
  With 60 selected vehicles the effective controls are 61 candidates and
  radius 60; exact inventory-invalid targets are skipped, and canonical Stage
  2 actual cost selects the hand-off.
- Solver/BFF/runner metadata now records the available count, required limits,
  coverage scope and truncation flag. Formal pair execution rejects a search
  whose applied controls are smaller than required or whose selected-inventory
  span hit the cap. Focused regression coverage includes both the 60-vehicle
  scaling case and fail-closed formal-control checks.

## 2026-08-08 Phase 4 accounting, telemetry and search-profile correction

- Clean commit `b64bedbd0bf5e371d1b6a31f9d8478a7b0d07295` was run through
  fresh Prepare for the controlled sunny/rain pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_autosym_b64bedb_gap001`.
  Both cases were physically valid, completed 24/24 Rolling and reconciled
  within `1.16e-10 JPY`, but both selected 18 BEVs / 14 ICE buses and 59 / 205
  trips at 704,318.633649 JPY. Both explored one node and stopped at 100% gap.
  The result is dominated by the earlier 25-BEV sunny incumbent and is not an
  optimality result.
- The identical incumbent has a concrete energy explanation: its PV-to-bus
  plus PV-to-BESS input is about 716 kWh in sunny and 714 kWh in rain. Rain's
  996.2 kWh curve can already cover it, so the extra sunny PV has zero marginal
  value until a higher-BEV composition is evaluated. Radius five constrained
  the primary 18-BEV seed search to at most 23 BEVs and could not reach the
  known 25-BEV sunny solution.
- The same-problem Phase 3 seed now retains 21 candidates and searches exact
  symmetric deltas +/-1 through +/-10. The Phase 3 composition certificate and
  acceptance flag are copied into Phase 4 solver evidence. This broadens
  candidate generation without a directional weather/BEV policy.
- `cost_breakdown()` now preserves actual-cost, accounting-match and objective
  semantics from the engine. This closes the remaining BFF-to-Rolling metadata
  loss that kept `objective_is_actual_cost=false` despite a structurally and
  numerically verified Phase 4 objective. The relevant focused suite passes
  114 tests; the complete repository suite passes 1,220 tests in 56.50 seconds.
- The controlled-pair runner previously hard-coded the obsolete Phase 4 seed
  contract as 10 candidates/radius 2, making
  `solver_controls_match_formal_request=false` even when the server applied
  its declared profile. The audit now uses one tested helper and matches the
  server-authoritative 21-candidate/radius-10 contract.
- The clean `b8793f342c1c886a3f44db843448c13505d62a78` pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_finalslot_b8793f3_gap001`
  closed the final-slot physical defects. Sunny returned 25 BEVs / 7 ICE buses
  and 156 / 108 trips; rain returned 15 / 17 and 48 / 216. Both served 264/264,
  had terminal BEV/BESS balance, passed independent physical validation, and
  completed 24/24 Rolling. Sunny ended at 5.1337% raw gap; rain ended at 100%,
  so both remain `validated_non_exact` candidates.
- The remaining 297.07357 JPY sunny objective/accounting mismatch was a hidden
  semantic split: integrated and Stage-1 objectives plus `CostEvaluator` used
  `50 * charged_kWh / capacity_kWh`, while the canonical ledger used the saved
  scenario throughput coefficient, which is zero in this pair. ProblemBuilder
  now materializes `battery_degradation_price_jpy_per_kwh`; both MILPs and the
  evaluator charge `weight * price * charged_kWh`, exactly matching the ledger.
- Phase 4 now exports `phase4_integrated_slot_energy_recourse`, the effective
  `gurobi_threads`, Stage-1 BestObjStop state, and solve time. Phase-1 Rolling
  metadata also exports its effective thread count. The BFF no longer inserts
  measured elapsed time into a temporary dictionary and then builds
  `solver_settings.json` from the stale pre-insertion metadata.
- The pair manifest treats a full-network Phase 4 solve as powertrain-
  composition certification only when an incumbent exists and the requested
  global MIP gap is met. Stage-1 adjacent-composition evidence remains required
  for two-stage Phase 3 and is not fabricated for integrated Phase 4.
- Commit `3e49cff3cc0a25ac9fcd96c47c34af17777b19a0` was then executed through
  the clean frontend path. Sunny `output/2026-08-08/run_20260808_1126`
  reconciled the solver objective and accounting total exactly, exported one
  Gurobi thread and the integrated coupling mode, and passed physical checks.
  However, all-budget `MIPFocus=3, Heuristics=0.1` retained the 15-BEV / 17-ICE
  Phase 3 seed, explored one node and stopped after 3,600 seconds at 100% gap.
  Because this was a clear search regression from the 25-BEV clean baseline,
  the rain job was stopped before its main solve. It is an incomplete
  diagnostic, not a formal pair.
- The corrected profile keeps one uninterrupted integrated solve on the known
  incumbent-improving `MIPFocus=1, Heuristics=0.5` profile. A proposed final
  bound-focused restart was rejected during review because a second
  `optimize()` call may discard the useful branch-and-bound tree and leave a
  weaker final certificate. Objective, bound, gap and runtime are exported for
  the single search.
- The neutral Phase 3 hand-off now reserves 21 candidates: the primary
  composition and exact symmetric used-powertrain deltas +/-1 through +/-10.
  The one-sided BEV frontier remains disabled; Stage 2 canonical actual cost
  chooses the hand-off, so no weather or BEV preference is introduced.
- Clean sunny run `output/2026-08-08/run_20260808_1300` then showed that forced
  `Symmetry=2` was also a regression. It served 264/264 and passed physical
  checks, but returned 18 BEVs / 14 ICE buses, 59 / 205 trips, objective
  704,318.633649 JPY, best bound zero and 100% gap after 3,600 seconds. Root
  processing temporarily used about 17.6 GB private memory. The rain job was
  stopped before its main solve because the shared profile was already known
  to be defective. The solver now retains Gurobi's automatic symmetry policy.
- The same run exposed a reporting defect after accepted Rolling: the numeric
  solver/executed-day difference was only `1.16e-10 JPY`, but rolling
  finalization hard-coded `objective_is_actual_cost=false` for all phases.
  Phase 3 remains false; Phase 4 now retains true only when its day-ahead
  structural/numeric contracts passed and the executed total equals the
  immutable solver objective within `1e-6 JPY`.
- Focused regression coverage exercises the shared degradation price, Phase 4
  source-flow audit, solver telemetry, and gap-certified composition semantics.
  The updated focused set passes `78 tests`; the complete repository suite
  passes `1218 tests` in 68.17 seconds. A fresh clean-commit sunny/rain pair
  remains required before release status can change.

## 2026-08-08 Phase 4 late-service SOC and MIP-gap correction

- Executed a clean fresh-Prepare pair at commit
  `223c9f1302f9a45264e1e1732bb5fb5d41219e76` through the frontend HTTP/BFF
  path. Both cases held the 264-trip scope, 60-vehicle selected-depot fleet,
  10 chargers, flat 30 JPY/kWh grid price, zero demand charge, 1,000 kW PV
  rating, and 6,000 kWh / 900 kW / 3,000->3,000 kWh BESS controls fixed.
- Rain completed with 15 BEVs / 17 ICE buses and 48 / 216 trips, exact trip
  coverage, physical day-ahead acceptance and 24/24 accepted Rolling. It was a
  3,600-second incumbent with raw gap 100% and best bound zero, so it is not an
  optimality result. Sunny improved the incumbent to 25 BEVs / 7 ICE buses and
  164 / 100 trips, demonstrating that integrated PV value does affect dispatch,
  but day-ahead postsolve validation rejected the solution and Rolling did not
  start. The pair correctly ended `BLOCKED`.
- Sunny's three late Shibu21 duties ended after 23:00. The transition rows had
  already debited the share driven before 23:00, while `_slot_end_soc_expr`
  debited the full trip again. The independent replay surplus matched the
  duplicate shares exactly: 3.127139, 5.003422 and 7.192420 kWh. A separate
  loop-bound defect omitted C12 charging eligibility and charge-power linkage
  for slot 23, allowing one BEV to charge while its 22:37--23:01 trip was active.
- `_trip_energy_in_slot_expr` is now shared by SOC transitions and terminal
  expressions. Charging eligibility, at-home/away implications, charge-power
  linkage and session-start rows iterate over all price slots. The BESS
  terminal deviation audit reads the final solved end-of-slot SOC trace and
  target, failing closed if that trace is absent; it does not read a zero-cost
  auxiliary deviation variable.
- The formal integrated actual-cost request and its case-gate audit now use a
  0.1% relative gap. The failed sunny run stopped at 4.772850% with objective
  672,565.367369 JPY and bound 640,464.829587 JPY. Its 32,100.54 JPY absolute
  uncertainty was almost identical to its 31,700.89 JPY ICE fuel term, proving
  that the old 5% threshold could not resolve the powertrain composition.
  Policy-oriented Phase 4 cases retain their distinct 5% setting.
- Focused regression coverage verifies a trip spanning 22:50--23:14, no slot-23
  trip charging, exact return-to-initial SOC, physical BESS deviation semantics,
  fail-closed missing BESS trace handling, and frontend 0.1% request parity.
  The focused set passes 48 tests; the complete repository suite passes 1,212
  tests in 74.52 seconds; compileall and `git diff --check` pass. A clean
  commit and fresh formal pair remain required.

## 2026-08-08 Phase 4 coarse-slot and terminal-SOC diagnostic closure

- Replayed the 264-trip sunny canonical input through the frontend HTTP/BFF
  path after adding semantic fixed-recourse IIS evidence. The old IIS involved
  two sequential duties on the same BEV: `07:03--07:47` and `07:57--08:48`.
  Their exact ten-minute turnaround is feasible; they merely intersect the
  same 60-minute energy slot.
- Root cause was the integrated replenishment implication
  `charge_on[v,t] <= 1 - sum_r y[v,r]` (and the analogous refueling row).
  When two non-overlapping trips touched slot `t`, `sum_r y[v,r]=2`, making a
  valid duty infeasible even with `charge_on=0`. The model now emits
  `charge_on[v,t] <= 1-y[v,r]` and
  `refuel[v,t] <= M(1-y[v,r])` for each active assignment. This changes only
  the erroneous coarse-slot aggregation; trip overlap, turnaround, deadhead,
  charger occupancy, SOC and source-flow equations are not relaxed.
- The corrected fixed-dispatch integrated recourse in
  `output/2026-08-08/run_20260808_0601` has 776,752 variables and 1,926,978
  constraints, returns `solution_limit` with an incumbent in about 0.8 seconds,
  and supplies a complete all-variable Phase 4 start. The unrestricted
  diagnostic then retains a 264/264 incumbent under its intentionally tiny
  one-second budget.
- A second reporting defect was exposed: the integrated extractor exported
  per-slot SOC but omitted initial, final and target BEV SOC maps. The engine
  therefore defaulted `bev_terminal_soc_balance_satisfied` to false even when
  the model satisfied its hard target. The extractor now evaluates the exact
  final-day solver expressions, exports per-vehicle deviations, and fails
  closed if a used BEV lacks an initial value, terminal expression, or required
  target constraint. The full-scope diagnostic reports 15/15 maps, terminal
  balance accepted, maximum absolute deviation about `1e-6 kWh`, BESS terminal
  deviation zero, and all independent physical counters zero.
- BFF physical validity now accepts a `TIME_LIMIT`, `OBJECTIVE_LIMIT`, or
  `SOLUTION_LIMIT` result only when the core reports a feasible incumbent and
  all existing physical gates pass. Such a result is explicitly
  `validated_non_exact`; no optimality or research-ready status follows. A
  limit result without an incumbent still fails.
- Relevant Phase 4, strict-coverage, validity, accounting and reporting tests
  pass (`79 passed`); the focused terminal-SOC/coarse-slot subset passes
  `39 passed`; the complete repository suite passes `1209 passed`;
  `compileall` and `git diff --check` pass. This diagnostic was non-formal and
  dirty, so it cannot discharge the release blocker. A clean commit, fresh
  Prepare, and a new controlled sunny/rain run remain required.

## 2026-08-08 Phase 4 integrated fixed-dispatch recourse correction

- Clean commit `e071446cb346092719a3103e81026bcb02d82a21` was exercised through
  the frontend HTTP path at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_neutral_seed_e071446`.
  The Phase 3 seed passed Stage 1, Stage 2, exact 264-trip coverage and the
  independent physical validator in both weather cases. The adapter reported
  complete assignment, charger, SOC, BESS-mode and source-flow `Start` values,
  but Gurobi produced zero integrated incumbents in 3,600 seconds for both
  cases. The prior `applied=true` evidence proved attribute assignment only and
  was insufficient.
- Phase 4 now performs an exact integrated recourse preflight before the main
  search. It temporarily fixes only `y`, path arcs, boundary arcs, unserved and
  vehicle/day activation binaries from the verified Phase 3 seed. Charging,
  physical charger selection, refueling, vehicle SOC, PV/grid/BESS routing,
  BESS modes and SOC remain endogenous to the integrated model.
- When fixed-dispatch recourse has an incumbent, all integrated variable values
  are fingerprinted and installed as a complete MIP start, the temporary
  dispatch bounds are restored, and the 3,600-second canonical-cost model is
  solved without a composition or weather bias. If recourse is proven
  infeasible, the audit records IIS constraint/bound names, counts and SHA-256;
  a time limit without an incumbent remains unresolved. In every failure path
  the provisional Stage 2 start is cleared.
- `warm_start_applied` and the formal seed gate now require an integrated-
  feasible complete start, not merely submitted values. The v2 audit and
  solver settings include the preflight outcome; the sunny/rain control hash
  includes its enabled flag and 300-second limit. The declared maximum is now
  600 + 300 + 3,600 = 4,500 seconds per case.
- The Phase 3 seed runtime audit now reads the canonical `runtime_sec` solver
  metadata key. The seed budget is clamped to at least 120 seconds so its
  Stage 1/Stage 2 split cannot silently exceed the declared total in small
  direct-call tests.
- Focused tests cover a successful integrated recourse promotion and a proven
  infeasible recourse with IIS plus bound restoration. A fresh clean-commit
  264-trip pair remains required before this correction can be considered
  research-release evidence. The Phase 4/BFF/Rolling focused set passes `182`
  tests; the complete repository suite passes `1204` tests. `compileall` and
  `git diff --check` also pass.

## 2026-08-08 Phase 4 same-problem feasible-incumbent hand-off

- Root cause of the 2026-08-03 full Phase 4 failure was not the absence of a
  `Start` vector. The old dispatch path-cover baseline supplied only selected
  assignment/charging values, left most path and charger binaries undefined,
  and had no verified Stage 2 SOC/source-flow trace. The 678,600-arc model
  consequently reached 3,600 seconds with no valid incumbent.
- `OptimizationEngine` can now run Phase 3 as an in-process seed solve for a
  frontend Phase 4 request. It uses the already materialized Phase 4 canonical
  problem, so timetable, selected fleet, initial SOC, chargers, PV, tariff,
  BESS, and objective controls cannot drift through an external artifact.
  Fallback and post-solve repair are disabled for the seed.
- Formal actual-cost Phase 4 reserves 600 seconds for a neutral seed
  (480 seconds Stage 1 and 120 seconds Stage 2), 300 seconds for integrated
  fixed-dispatch recourse, and 3,600 seconds for the unrestricted integrated
  solve. The 4,500-second total maximum and every seed control are
  exported and included in the pair control hash. The automatic one-sided
  `used BEV >= K` frontier was removed because a time-limited integrated solve
  could retain that directed incumbent. The seed now uses the primary plan
  plus symmetric adjacent-composition candidates only.
- The frontend formal Phase 4 gap target is 5%, not 10%. A 13/19 seed near
  707,000 JPY is already within roughly 9.5% of the 640,000 JPY vehicle-day
  lower bound, so the former target could stop before the integrated model
  searched for a weather-responsive lower-cost incumbent.
- Seed acceptance fails closed unless the exact eligible-trip set is served,
  Stage 1 and Stage 2 are feasible, and `FeasibilityChecker` independently
  accepts the plan. Accepted metadata identifies the plan as
  `mip_start_only`; it is not a Phase 4 result or optimality certificate.
- The integrated adapter now submits explicit zero/one starts for every
  assignment, connection, boundary, vehicle-use, charging, physical-charger,
  and BESS-mode binary. It also supplies charger power, vehicle/BESS SOC,
  vehicle source split, depot PV/BESS/grid flows, curtailment, grid import,
  demand peaks, and refueling starts. Unverified dispatch baselines are no
  longer reported as applied integrated warm starts.
- `phase4_phase3_seed_audit_v1` and `integrated_mip_start_audit_v2` are carried
  into solver metadata and `solver_settings.json`. They expose acceptance,
  same-problem provenance, a plan-native SHA-256 fingerprint, complete vehicle
  and BESS SOC traces, full-coverage checks, failure reasons, and variable
  coverage counts. A declared but failed seed hand-off blocks per-run research
  acceptance in the core engine, not only in the pair wrapper.
- Focused regression covers acceptance of a same-problem Phase 3 plan with a
  physical charger and BESS, rejection of an unverified dispatch baseline,
  actual-cost reconciliation, and existing Stage 1/strict-coverage behavior.
  The superseding recourse-focused set passes `182` tests and the complete
  repository suite passes `1204` tests; `compileall` and `git diff --check`
  also pass.
  A fresh clean-commit 264-trip HTTP run is still required; passing unit tests
  alone do not resolve the research blocker.

## 2026-08-07 clean 1,000 kW PV BEV-frontier evidence

- Executed a fresh frontend HTTP pair from clean frozen commit
  `e94c8154cdcb566cb298a2a8a92ef14b2d1a5f7a` at
  `output/formal_pair_20260807_flat30_pv1000_bess6000_phase3_frontier_head`.
  Both cases used the saved 1,000 kW PV rating, 6,000 kWh / 900 kW BESS with
  3,000 -> 3,000 kWh inventory, flat 30 JPY/kWh grid energy, zero demand
  charge, and a declared 20,000 JPY fixed vehicle-day cost. The runner made
  fresh prepared inputs and did not use stale duties or a weather policy.
- The full `used BEV >= K`, `K=15..35`, frontier changes the resolved schedule
  from high PV 27 BEVs / 5 ICE buses and 183 / 81 trips to low PV 21 BEVs / 11
  ICE buses and 91 / 173 trips. Both use 32 buses, serve 264/264 trips, pass
  independent physical validation and terminal energy checks, and complete
  accepted 24/24 Rolling. All 21 requested frontier targets resolve.
- Executed-day accounting reports 666,164.082366 JPY and zero grid import at
  6,056.25 kWh PV, versus 698,469.250509 JPY and 126.610037 kWh grid import at
  996.2 kWh PV. The high-PV candidate is therefore 32,305.168143 JPY/day
  (4.625%) cheaper, uses six more BEVs and 92 more BEV trips, and emits
  545.342135 kgCO2/day (55.155%) less in this operating-cost scope.
- This corrects the interpretation of the earlier 15-BEV local candidate pool:
  its cost decreased through the largest searched composition, so it did not
  prove a 15-BEV optimum. The expanded frontier provides a physically
  validated high-BEV/low-cost witness without a weather-direction bias.
- The pair remains intentionally `BLOCKED`. Phase 3 is not an integrated
  global actual-cost objective. High PV has a zero numeric solver/accounting
  residual but `objective_is_actual_cost=false`; low PV has a -49.560460 JPY
  residual. The pair manifest therefore rejects both actual-cost objective
  checks. The result may be presented as a controlled, physically feasible
  frontier result, not as an integrated global optimum.
- The 1,000 kW rating is a high-PV sensitivity, not a current-roof potential:
  its reverse audit requires 5,000 m2 of installable panel area and about
  14,285.7 m2 of depot area under the saved assumptions, versus the stored
  1,450 m2 site area. PV/BESS CAPEX and financing also remain outside the
  daily operating-cost total.
- The adjacent ZIP contains 536 entries, is 23,514,502 bytes, and passes
  `ZipFile.testzip()` with no corrupt member. Git SHA and clean status match
  at experiment start and end.

## 2026-08-07 PV/BESS, demand-charge, and frontend closure

- Replaced the Solcast period-end anchor approximation with interval-overlap
  resampling. A source interval contributes capacity-factor-hours to every
  target slot it overlaps, so 60-minute input preserves its kWh at
  5/15/30/60-minute output. Invalid slot lengths, performance ratios, dates,
  and dates absent from the source artifact now fail closed.
- Changed `depot-assets/update` to true patch semantics using Pydantic's
  explicitly supplied field set. BESS-only edits no longer reset PV area,
  rated output, enable state, or curve. Explicit false and empty arrays are
  meaningful. Rated-output changes refresh reverse area estimates and either
  rebuild generation from capacity factors or proportionally rescale the
  stored curve; direct curve replacement removes stale date-indexed variants.
- Added API and canonical validation for non-negative finite PV/BESS values,
  SOC ordering/capacity bounds, and efficiencies in `(0, 1]`. `ProblemBuilder`
  no longer converts an explicitly supplied zero efficiency to `0.95` through
  truthiness fallback.
- Defined demand charge as per-depot-meter billing. Integrated MILP, Stage 2,
  Stage 1 energy recourse, and `CostEvaluator` now all charge the sum of each
  depot's on/off-peak maximum rather than mixing maximum-of-depots with an
  aggregate simultaneous peak.
- Exposed explicit Phase 3 and Phase 4 modes in Tk. Candidate count,
  composition radius, BEV frontier, canonical actual-cost objective,
  utilization mode, and cost-cap controls persist through Quick Setup and are
  included in the exact submitted payload. Incompatible controls are disabled
  in the payload and rejected by BFF validation.
- Removed the duplicate `planningDays` dictionary key and replaced silent
  vehicle-timeline JSON conversion suppression with a traceback-bearing
  warning. Artifact completeness remains the fail-closed release gate.
- Validation: focused regression `131 passed`, follow-up solver/persistence
  regression `126 passed`, final full suite `1196 passed`; `compileall` and
  `git diff --check` pass. No Prepare or optimization run was performed during
  that code-validation step. The subsequent clean frontier run is recorded
  above and remains teacher-release `BLOCKED` for the stated Phase-3 objective
  and accounting reasons.

## 2026-08-07 Branch integration validation

- Local `main` now contains both the Phase 3 composition/PV-rated-output
  lineage and the powertrain-sensitive dispatch-audit lineage. The integration
  preserves the explicit-zero Quick Setup repair and the formal-run Git
  preflight that were already present on `main`.
- Conflict resolution kept the saved `pv_capacity_kw` value authoritative,
  retained reverse area/capacity estimates as audit outputs, and aligned
  `vehicle_usage_cost_semantics` validation across Quick Setup and Prepare.
- Focused persistence, PV, cost, composition, formal-contract, and README
  regressions pass (`177 passed`). The complete repository suite passes
  (`1163 passed`), `compileall` passes, and `git diff --check` passes.
- No Prepare or optimization run was performed during branch integration.
  Existing prepared inputs and outputs are not relabelled as evidence for the
  integrated commit; teacher release remains fail-closed until a fresh formal
  pair is run from a clean frozen commit.

## 2026-08-07 Quick Setup の明示的な 0 を保存・再読込・Prepare まで保持

- 原因は Tk の `load_quick_setup()` にあった `saved_value or default` である。BFF とシナリオストアには `demand_charge_cost_per_kw=0.0` が正しく保存されていても、保存直後の自動再読込で画面が `1500` に戻り、その後の Prepare が誤った値を再送していた。
- Tk の全数値設定を `None` のときだけ既定値へフォールバックする共通処理へ統一した。対象には系統買電・売電単価、基本料金、PV 費用、軽油・CO2・車両使用費、営業所電力上限、燃料条件、BESS サイクル費、およびソルバー数値設定を含む。
- BFF の Quick Setup 応答、bootstrap、更新時の未担当便ペナルティ、Prepare の乱数 seed も同じ欠損判定へ統一した。これにより、保存値 `0` は画面再読込と materialization の両方で保持される。
- API 入力は canonical overlay と同じ数値範囲へ揃えた。料金・排出係数・営業所電力上限・未担当便ペナルティ・mip gap・seed では `0` を受理する一方、実行時間、反復回数、destroy fraction、fragment 上限、回送速度など正値必須の項目は保存・Prepare 前に拒否し、既定値へ黙って戻さない。
- `ProblemBuilder` では、明示的な flat 買電単価 `0` を有効な料金設定として認識し、既存の時刻別料金へ黙って戻さないようにした。基本料金、軽油単価、ICE 排出係数、営業所電力上限、未担当便ペナルティでも `0` を欠損扱いしない。
- 回帰テストは、保存 API、Quick Setup 応答、Tk 表示値、Prepare seed、ProblemBuilder の canonical price slots を個別に検証し、対象回帰 `133 passed`、全体 `1116 passed` を確認した。最適化計算や保存済みシナリオの変更はこの修正では行っていない。アプリ再起動後、対象シナリオを再読込し、必ず fresh Prepare してから次の計算を行う。

## 2026-08-07 README の利用者導線を再設計

- GitHub 上の入口を、約 1,600 行の契約・履歴・数式の混在した構成から、目的別の短い導線へ再構成した。現在の実装、数理モデル、受理条件は変更していない。
- README は「何をするシステムか」「ソースからの起動」「最初の最適化」「結果の判定」「正式研究実行」の順に整理した。詳細な契約は削除して主張を弱めたのではなく、現行の `FORMAL_RUNBOOK_CURRENT.md`、`CURRENT_RESEARCH_RELEASE_BLOCKERS.md`、教員向け資料、運用ガイドへのリンクを正本として明示した。
- 実装と不一致だった新規利用者向け出力先表記を `outputs/` から既定の `output/` に是正し、存在しない配布済み `.exe` を通常の起動導線から外した。React/Tauri は引き続き設計段階であり、現行操作画面は Tkinter + FastAPI であることを明示した。
- `tests/test_readme_navigation.py` を追加し、実際の起動・操作・研究判定への入口と、README 内のローカル文書リンクを回帰確認する。

## 2026-08-06 Formal-run Git preflight and explicit trial mode

- Root cause: Tk `_build_optimization_run_payload()` hard-coded
  `research_run=true` for the ordinary optimization action. A dirty worktree
  was therefore correctly rejected by the BFF worker before `ProblemBuilder`
  or the solver ran, but only after a job had been created.
- The Tk run panel now defaults visibly to `試行計算（研究提出不可）` and
  offers a separate `正式研究実行（clean Git必須）` choice. The exact payload
  object is logged and submitted, and compact payload logging includes the
  boolean `research_run` for both true and false.
- `GET /api/research/git-preflight` exposes the canonical Git collector's SHA,
  dirty state, error, and `git status --porcelain` rows. Formal Tk submission
  stops with those rows before job creation. The BFF independently repeats the
  same check synchronously before job creation and preserves
  `_require_clean_research_git_state()` in the worker immediately before the
  solve; the existing post-solve SHA/patch identity check is unchanged.
- Nonformal optimization artifacts are fail-closed with
  `diagnostic_only=true`, `research_submission_ready=false`,
  `teacher_release_status=BLOCKED`, and
  `blocking_reason=dirty_or_nonformal_run` in the result, audit, summary, run
  manifest, and research claim scope. This changes claim metadata only; it
  does not weaken feasibility, accounting, physical validation, or solver
  constraints.
- Formal evidence still requires committing this implementation, restarting
  Tk/BFF from that clean frozen commit, and running fresh Prepare. No solver run
  was performed as part of this UX correction.
## 2026-08-05 Frontend PV rated-output authority guard

- The current sunny/rain frontend scenarios are restored to the user's common
  1,000 kW rated output. Their date-specific capacity-factor curves therefore
  materialize 6,056.25 / 996.2 kWh, with 5,000 m2 required installable area and
  14,285.714286 m2 reverse-estimated depot-area equivalent. The measured
  1,450 m2 depot-area field remains unchanged. No Prepare or optimization was
  run as part of this correction.
- The latest 101.5 kW pair was not evidence of the saved frontend selection:
  its controller environment explicitly supplied `pv_capacity_kw=101.5`.
  The HTTP pair runner now rejects `--pv-capacity-kw` unless
  `--allow-frontend-pv-capacity-override` is supplied as a separate deliberate
  acknowledgement. Omitting both options keeps the frontend rated output
  authoritative.
- Date-specific PV generation now updates the direct slot series, capacity
  factors, date-indexed series, profile identifiers, and overlay summary in one
  operation. This prevents a generated 1,000 kW direct curve from coexisting
  with stale 101.5 kW date-indexed rows. Focused PV/frontend tests pass; all
  pre-correction prepared inputs remain stale.

## 2026-08-03 BEV actual-cost and fleet-frontier correction

- The clean v5 binding-PV run exposed one fail-closed metadata omission after
  both weather cases had otherwise completed: the BEV frontier was active and
  its `K=15..35` artifacts were complete, but `solver_settings.json` omitted
  `stage1_bev_frontier_enabled`. The adapter, engine, and BFF settings export
  now preserve that explicit control and focused tests cover both the solver
  metadata path and final settings payload. This changes no variable,
  constraint, objective coefficient, candidate, or acceptance threshold. The
  completed v5 artifacts retain the old missing field and remain diagnostic.
- The succeeding clean v6 pair at frozen SHA
  `7ab9f194216b1b7fe0e0ef49041314528438f6d5` verified the metadata repair:
  `stage1_bev_frontier_enabled=true` and
  `solver_controls_match_formal_request=true` are present for both cases.
  All 21 K targets resolved with zero frontier monotonicity violations;
  sunny evaluated 22/22 physically feasible candidates and selected
  17 BEV / 15 ICE with 54/210 trips, while rain evaluated 20/22 physically
  feasible candidates and selected 13 BEV / 19 ICE with 44/220 trips. The
  selected candidate hashes and all selected costs exactly match v5, showing
  that the metadata-only correction did not change the optimization result.
  Both cases served 264/264 trips and completed accepted 24/24 Rolling.
  The pair remains correctly BLOCKED: Phase 3 is not an integrated actual-cost
  objective, rain differs from executed-day canonical accounting by
  22.292852588 JPY, and the positive 20,000 JPY used-bus-day coefficient is
  still `unclassified`.
- The first clean 264-trip Phase-4 HTTP pair at explicit 1,000 kW PV rating
  reached the 3,600-second limit with no incumbent in both cases. Both runs
  correctly failed before Rolling and the pair bundle is `BLOCKED`. This is a
  computation/warm-start blocker, not evidence about the preferred BEV/ICE
  composition. The failed-run economic audit now recovers gross PV directly
  from canonical depot-asset input slots, so the absence of solved source
  flows cannot turn 6,056.25 kWh (sunny) or 996.2 kWh (rain) into a reported
  zero-PV input.
- The first clean 264-trip Phase-3 `K=15..35` frontier pair at frozen SHA
  `751762279adb28dac1039f4994f9538b83b6f928` produced physically valid
  264/264-trip, 24/24 Rolling primary schedules in both weather cases. Both
  selected 13 BEVs and 19 ICE buses with 44/220 trips and canonical operating
  cost 707,808.660373 JPY. This is a diagnostic null response: at 1,000 kW,
  even rain supplied 996.2 kWh against 565.86897 kWh of Stage-1 renewable BEV
  allocation, so neither case purchased BEV grid energy. It is not evidence
  that the composition is optimal because every K target timed out without an
  incumbent and the pair remained BLOCKED.
- The frontier failure was traced to its MIP-start contract: activation starts
  were disabled for the frontier, and the old helper represented only a
  one-vehicle delta although the first target was K=15 from a 13-BEV primary.
  Frontier targets now receive deterministic non-conflicting multi-vehicle
  activation/retirement starts for every reachable delta. The starts do not
  change the objective, K constraint, Stage 2, or physical acceptance. The
  audit persists the complete source/target ID lists and replacement count.
  Artifact completeness now matches the exact writer schemas for the four
  vehicle-day-semantics columns and the frontier minimum/status columns.
- A binding-PV rerun from frozen SHA
  `fe453df2f8a2ea0bb9c2240d42f2df5af9f12180` used the common 101.5 kW
  rating, producing 614.709375 / 101.1143 kWh sunny/rain input. Both cases
  completed 264/264 service and 24/24 Rolling but were correctly BLOCKED by
  unresolved K=28..35 targets. K=15..27 were Stage-2 and independently
  physically feasible in both cases. Within that resolved frontier, sunny
  selected K=17 (17 BEV / 15 ICE, 54 BEV trips, 706,175.871233 JPY) while
  rain selected K=15 (15 BEV / 17 ICE, 44 BEV trips, 720,637.777812 JPY).
  Sunny used 614.709375 kWh renewable plus 19.011025 kWh grid in Stage 1;
  rain used 101.1143 kWh renewable plus 411.374162 kWh grid. This is direct
  weather-responsive diagnostic evidence, but not a formal optimum because the
  high-K search remains incomplete and the 20,000 JPY coefficient is still
  unclassified.
- The high-K blocker occurs because whole-duty replacement preserves the
  32-bus path-cover size and may create BEV duties that fail energy recourse.
  The next correction adds a distinct suffix-split start: the source retains a
  nonempty prefix and an unused BEV receives a nonempty suffix, increasing both
  BEV count and total fleet size. It records start mode, replacement count,
  split-activation count, total activation count, and moved trip IDs. A focused
  Gurobi counterexample verifies an ICE-only prefix prevents whole-duty
  replacement while the split start reaches a larger feasible fleet.
- A clean v3 run at SHA `4d997be18c8507ac450001a27c32f6245b851b4e`
  confirmed that suffix-split starts produce incumbents through K=35 in both
  weather cases. Sunny completed all K targets, 264/264 service, and 24/24
  Rolling. Rain also produced an incumbent for every K, but direct K=26 and
  K=27 candidates each failed independent physical validation because one
  contract-power violation remained. Physically feasible K=28 already proves
  feasibility of the nested `used BEV >= 26` and `>= 27` sets, but the old
  finalizer did not propagate higher-K witnesses downward, so rain and the pair
  correctly remained BLOCKED. The finalizer now constructs the lowest-cost
  physically feasible evaluated candidate-pool envelope for every K and records
  the direct target hash separately from the resolving witness hash/source.
  This does not repair either rejected schedule or assert global optimality.
- The first v4 attempt was intentionally stopped after sunny finalization
  exposed a strict CSV-header failure: the writer had the new nested-witness
  fields but the artifact validator and test fixture still declared the prior
  header. Those three definitions are now synchronized and covered by the
  strict artifact-completeness regression before another formal rerun.
- Added an explicit Phase-3 BEV lower-bound frontier for `K=15..35`. Each
  temporary model uses only `sum(used_electric_vehicle) >= K`; neither ICE
  count nor total used-fleet size is fixed. The previous K solution is used as
  a warm start, every target records one of `FEASIBLE`,
  `CERTIFIED_INFEASIBLE`, `TIME_LIMIT_WITH_INCUMBENT`,
  `TIME_LIMIT_NO_INCUMBENT`, or `ERROR`, and a no-incumbent time limit remains
  unresolved.
- Stage-2 candidates are ranked by independently evaluated canonical cost only
  after Stage-2 feasibility and physical validation. This improves the Phase-3
  search but does not turn the two-stage method into an integrated global
  total-cost optimum.
- Added the explicit `phase4_integrated` actual-cost contract. It removes
  weather/EV preference and solver-only soft terms, retains enabled canonical
  battery degradation, fixes BEV/BESS terminal inventory to its initial level,
  and sets `objective_is_actual_cost=true` only when the raw solver objective
  reconciles to canonical accounting within `1e-6 JPY` without post-solve
  modification.
- Added two separate Phase-4 EV-utilization policy cases. The unconstrained
  case lexicographically minimizes ICE fuel liters and then canonical cost. The
  epsilon case adds the exact canonical-cost constraint
  `C <= C* (1 + delta)` for externally evidenced `C*` and delta in
  `{0%, 1%, 3%, 5%, 10%}`. Neither case reports
  `objective_is_actual_cost=true`, because actual cost is respectively the
  secondary objective or a constraint rather than the primary objective.
- The positive per-used-bus-day coefficient now carries one of
  `fixed_vehicle_day_cost`, `driver_cost_proxy`, `provisional_sensitivity`, or
  `unclassified` through Quick Setup, Prepare, the canonical problem, and run
  artifacts. A positive `unclassified` or `provisional_sensitivity` value
  blocks a research economic claim. The UI no longer presents the coefficient
  as self-explanatory.
- Added `powertrain_marginal_cost_audit.*`,
  `trip_powertrain_cost_comparison.csv`, `bev_cost_frontier.*`,
  `maximum_bev_feasibility_search.csv`,
  `baseline_vs_integrated_actual_cost.csv`, and the explicit
  `operating_and_lifecycle_cost_scope.*`. Trip-level charging/PV feasibility is
  deliberately unresolved unless a solved duty/charger/SOC path supports it;
  incomplete charger/financing CAPEX likewise remains labelled partial rather
  than fabricated.
- The controlled HTTP pair runner now supports
  `--optimization-experiment-case phase3_bev_frontier` and
  `phase4_integrated_actual_cost`, plus the unconstrained and cost-constrained
  Phase-4 EV-utilization policy cases, while retaining the existing baseline.
  It also persists the chosen vehicle-day-cost semantics. No new formal result is
  claimed until a clean frozen commit completes Fresh Prepare, day-ahead solve,
  24/24 Rolling, physical validation, and accounting/pair gates.
- Regression status before the next clean freeze: the focused frontier,
  weather-coupling, and artifact-completeness suite passes (38 tests). The full
  suite and a fresh binding-PV 101.5 kW controlled pair remain required.

## 2026-08-02 interactive Sunday-PV Prepare provenance repair

- Fixed the `HTTP 422: comparison_type must be
  'same_service_date_pv_counterfactual'` failure when scenario
  `b23fd26c-1233-4c73-bb9e-bdb8b1584760` is interactively prepared as
  `2025-08-10` + `WEEKDAY` + `actual_date_profile`.
- Root cause was a field collision: Quick Setup stored the calendar waiver
  name `fixed_weekday_timetable_pv_counterfactual` in `comparison_type`, while
  Prepare correctly reserves that field for the formal pair design
  `same_service_date_pv_counterfactual`. The scenario also retained the prior
  pair role/source after its service date was changed.
- Quick Setup now keeps the waiver solely in `calendar_policy` and
  `allow_fixed_weekday_timetable_pv_counterfactual`, and clears stale formal
  comparison type/role/source metadata on an interactive save. Prepare accepts
  and normalizes only the exact legacy Sunday/WEEKDAY/actual-profile shape so
  already-saved scenarios are not stranded; other invalid comparison types
  remain rejected.
- This is a provenance repair only. It does not change the selected date,
  weekday timetable rows, route/depot scope, fleet, PV curve, tariff, BESS, or
  optimization semantics. The result must still be labelled a fixed-weekday
  timetable PV counterfactual, not actual Sunday operation.
- Validation: the focused Quick Setup/Prepare/calendar/Rolling/pair suite
  passes (52 tests), the complete suite passes (1,089 tests), and the exact
  persisted legacy shape from the affected scenario reaches builder
  configuration with `comparison_type/role/source=None` while retaining the
  explicit calendar waiver.
- Live BFF verification from code commit `dd829a9` then completed Fresh Prepare
  for the affected scenario without HTTP 422. Prepared input
  `prepared-b8601506bd9b49e5-dbc36084d07b5fa8-9dd564c9` is `ready=true` with
  service date `2025-08-10`, 1 depot, 16 routes, 264 trips, 60 vehicles, and 10
  chargers. Its schema is `v5_pv_rated_output_authoritative`; comparison
  type/role/source are null and the explicit fixed-weekday calendar policy is
  retained.

## 2026-08-02 PV rated-output input and reverse area estimate

- The depot manager and detailed depot-energy editor now treat
  `pv_capacity_kw` as the editable optimization input. Changing the rated
  output rebuilds PV generation from the persisted capacity-factor shape;
  grid price, weather policy, BESS state, and timetable semantics are not
  modified.
- The shared calculation now reports
  `estimated_installable_area_m2 = pv_capacity_kw /
  panel_power_density_kw_m2` and a separately named
  `estimated_depot_area_from_pv_capacity_m2 =
  estimated_installable_area_m2 / usable_area_ratio`. Measured
  `depot_area_m2` remains master data and is never overwritten by this inverse
  estimate. The round-trip `derived_pv_capacity_kw` is retained as an audit
  value.
- `pv_capacity_kw_manual_override=true` and
  `pv_capacity_input_mode=rated_output_manual` carry the selection through
  the Tk editor, PV API, Prepare, and `ProblemBuilder`. Rows without the
  explicit override continue to use the legacy area-derived capacity for
  backward compatibility. An explicit rated output of zero disables PV.
- The formal HTTP pair runner no longer replaces a frontend manual rated
  output with `depot_area_m2 * usable_area_ratio * panel_power_density`. Its
  new `--pv-capacity-kw` option fixes one declared rated output across both
  cases and scales each independently hashed weather curve by that same value.
- `PREPARED_INPUT_SCHEMA_VERSION` is now
  `v5_pv_rated_output_authoritative`. All formal comparisons after this model
  change require fresh Prepare and fresh optimization artifacts; older runs
  remain diagnostic and must not be relabelled.
- A fresh controlled pair was executed from frozen SHA
  `bb6c7fc3e49067f178a1540e4061ad4b83c015e0` (tag
  `research-pv-rated-1000kw-20260802`) with a common 1,000 kW rated output,
  flat 30 JPY/kWh grid price, and zero demand-charge rate. Prepare and the
  canonical scenario retained the measured 1,450 m2 depot area while recording
  5,000 m2 required installable area and 14,285.714286 m2 estimated depot-area
  equivalent. Sunny/rain PV totals were 6,056.25 / 996.2 kWh.
- Both cases served 264/264 trips, passed independent physical checks and the
  24/24 Rolling chain, and selected the same 14-BEV/18-ICE composition with
  46/218 trips. Both had zero grid-to-bus energy. Rain still used only
  575.541036 kWh of PV directly or through BESS and curtailed 420.658964 kWh;
  1,000 kW therefore saturates even the rain case, so an equal assignment is
  economically expected rather than evidence of a remaining capacity-input
  bug. The pair is retained at
  `output/formal_pair_20260802_flat30_pv1000_rated_output` as diagnostic only.
- The pair remains `BLOCKED`: only three of 21 requested candidates were
  evaluated; the same-assignment strict audit is incomplete; and Phase 3 still
  declares `objective_is_actual_cost=false` even though the numeric solver to
  canonical-accounting residual was only `1.164153e-10 JPY`. A smaller-capacity
  sweep is required to locate the binding-PV range; this 1,000 kW pair must not
  be used to claim that weather has no dispatch effect.

## 2026-08-02 Composition-target search budget correction

- The first flat-30 rerun from `fc3f4ba41648d6138c81a59ef6a76a74e094bbff`
  reached feasible 264/264-trip rolling artifacts in both cases, but all
  four in-inventory adjacent used-powertrain targets were `TIME_LIMIT` with
  zero incumbents.  The prior per-target 4.5-second cap therefore left the
  composition evidence unresolved; it did not establish that `(13,19)` was
  optimal.  The pair remains diagnostic at
  `output/formal_pair_20260802_flat30_composition_search_r2`.
- `OptimizationConfig.stage1_composition_target_time_limit_sec` now records
  a 25-second per-target cap, bounded by the existing 100-second Stage 1
  candidate reserve and divided across the remaining targets.  This is a
  solver-budget correction, not a BEV preference or weather strategy.  The
  effective cap is persisted in the candidate-selection metadata so a fresh
  frozen rerun can be audited.
- The second fresh rerun from `a083919ec679fdec64907ef46ba94cbf2dffc8c3`
  still reached `TIME_LIMIT` with no incumbent for all four adjacent targets.
  Exact-count targets now receive partial MIP starts that activate an unused
  opposite-powertrain vehicle and retire the source vehicle's duties.  The
  starts are hints only: the unchanged Stage 1 model, temporary count
  equalities, Stage 2, and independent physical validation must accept the
  resulting candidate.  This remains diagnostic until a fresh frozen pair
  confirms composition evidence.
- The fresh pair from frozen SHA `b02859b826165c8a612a81c145eb1b06f24cb7e3`
  used those activation/retirement starts successfully.  Both cases produced
  three physically valid compositions `(12,20)`, `(13,19)`, and `(14,18)`;
  the sunny selected candidate was `(14,18)` with 46 BEV trips, while rain
  selected `(12,20)` with 42 BEV trips.  Both served 264/264 trips and passed
  24/24 rolling and independent physical validation.  This is diagnostic
  evidence only: the formal pair remains BLOCKED because only three of the
  requested ten Stage 2 candidates were evaluated, the +/-2 targets remained
  unresolved time limits, and the solver objective is still a two-stage proxy
  rather than an actual-cost objective (rain residual: -19.214065 JPY).

## 2026-08-01 Phase 3 composition evidence and formal cost-release guard

- Review of the reachable Phase 3 path corrected an outdated diagnosis: the
  current Stage 1 objective already contains a slot-indexed, assignment-coupled
  continuous PV/grid/BESS recourse, with PV supply limits, charge windows,
  BESS losses/terminal SOC, and slot-specific grid prices. The historical
  `min(grid_price)` aggregate calculation remains a labelled lower-bound
  diagnostic and is not reintroduced into the objective. Stage 2 remains the
  fixed-assignment binary charging/physical-dispatch authority.
- `used_vehicle` and `used_vehicle_day` activation binaries and one-time
  vehicle-day cost were already linked to assignments. The missing evidence was
  a search over different activated powertrain counts: the old alternatives
  excluded trip-level BEV/ICE patterns and used only already-active whole-duty
  swap starts, so 21 candidates could all retain one `(used_bev, used_ice)`
  pair without proving alternatives infeasible.
- `OptimizationConfig.stage1_composition_search_radius` now requests exact
  temporary Stage 1 count constraints around the primary composition:
  `(BEV+d, ICE-d)` and `(BEV-d, ICE+d)` for `d=1..radius`. Formal frontend
  research runs force radius `>=2`; normal callers retain the legacy behavior
  only when they explicitly leave it at zero. Each target records target and
  observed counts, status, bound, gap, runtime, candidate hash, and an IIS
  hash/list if Gurobi proves `INFEASIBLE`. An accepted IIS certificate must be
  nonempty, contain a temporary target-count constraint, and carry the
  SHA-256 of the exact temporary Stage 1 LP plus solver controls; otherwise it
  is diagnostic only. A time limit, no incumbent, failed Stage 2, failed
  physical validation, failed IIS, or missing LP hash is explicitly
  `unresolved`, never an infeasibility certificate.
- `stage1_used_powertrain_composition_search.json/.csv` and the enriched
  candidate audit persist this evidence. Formal composition evidence is
  accepted only when two or more physically valid used-powertrain pairs were
  evaluated, every in-inventory adjacent target is exactly certified
  infeasible, or the selected inventory itself has no adjacent composition.
  The formal claim gate otherwise adds
  `used_powertrain_composition_search_not_certified`.
- Every rich frontend result now writes
  `assignment_economic_audit.json/.csv`. The audit distinguishes Stage 1
  continuous recourse from Stage 2/rolling authority; gives scalar grid BEV,
  ICE, and break-even marginal costs only for uniform selected-scope
  coefficients; reports gross PV only as an input-side diagnostic instead of
  inventing a scalar renewable budget under slot/terminal constraints; excludes
  initial BESS inventory from a free-renewable credit; and keeps depot-slot
  source flows separate from non-solver-native vehicle-source attribution.
- Formal two-stage pair construction now rejects a case when
  `solver_objective_matches_accounting_total` is false or composition evidence
  is unaccepted. This is a release-scope guard, not a false conversion of a
  Phase 3 Stage 1 score into canonical rolling cost. Current historical
  2026-07-31 outputs remain diagnostic and require a fresh clean-commit rerun.
- Focused regression added: interchangeable BEV/ICE duties produce multiple
  used-powertrain candidates; pair construction rejects objective/accounting
  and composition failures; the economic audit verifies 30 JPY/kWh grid BEV
  charging at `1.316/0.95*30` JPY/km, ICE at
  `0.2212389*150` JPY/km, and zero free initial BESS credit.

## 2026-07-31 Controlled uniform-tariff sensitivity support

- The first `30 JPY/kWh` / `0 JPY/kW` HTTP attempt is preserved as diagnostic
  evidence at `output/formal_pair_20260731_flat30_no_demand`. Both individual
  jobs completed their run gates and the canonical 24-slot tariff evidence was
  correct, but the pair was rejected: the effective sunny and rain PV curves
  were both `6056.25 kWh` with the same hash. Investigation showed that
  Prepare had changed PV labels while retaining a stale frontend depot-asset
  manual capacity/profile. Those numbers are not used for the tariff
  sensitivity conclusion.
- The HTTP-only controller now fetches the frontend's
  `GET /api/scenarios/{id}/editor-bootstrap` settings immediately before each
  fresh Prepare, preserves all non-PV depot-asset fields, and embeds a
  date-specific PV replacement asset in the normal Prepare payload. The
  replacement uses the selected depot's physical area, usable-area ratio, and
  panel-power density together with the separately hashed derived PV
  capacity-factor file; it replaces `pv_case_id`, dates, slot factors, slot
  generation, and the manual PV capacity consistently. This is a settings
  delivery repair, not a weather-specific objective bias or a prepared-input
  reuse. The runner persists the bootstrap response, PV source hash, and
  exact asset request for audit.
- `scripts/run_frontend_controlled_pv_pair.py` now accepts an explicitly paired
  grid-energy price and demand-charge rate for a user-authorized scenario
  mutation through the ordinary BFF Prepare endpoint. The override writes
  `grid_flat_price_per_kwh`, `demand_charge_cost_per_kw`, and one `00:00--24:00`
  TOU band. Sending only a flat value would be incorrect because a persisted
  multi-band TOU schedule has precedence in canonical price construction.
- A rate of `30 JPY/kWh` and demand/basic-charge coefficient `0 JPY/kW` is
  represented as 24 canonical price slots at 30 and 24 demand-charge weights
  at zero. It does not alter import limits, chargers, BESS, fleet, SOC, trips,
  PV, or solver controls. The same mutation must be included in both Prepare
  requests, and the pair's price-slot hash must match.
- Each case audit now reads the solver-produced
  `simulation_conditions_tou_prices.csv`; missing rows, a nonuniform price,
  or a nonzero requested-zero demand coefficient fail closed. The runner also
  writes `tariff_condition.json` and embeds the condition in
  `code_and_environment.json` and `completion_audit.json`.
- This support creates a distinct controlled tariff sensitivity. It must use
  fresh prepared inputs and a new output directory, and it cannot overwrite or
  relabel the prior PV-only formal pair.

## 2026-07-29 P0 slot-level weather/dispatch coupling and controlled HTTP pair

- Root cause: Phase 3 Stage 1 used a whole-day PV-energy credit in its
  assignment objective. That aggregate lower-bound proxy could offset charging
  without matching PV generation to vehicle depot-presence windows, charger
  capacity, SOC, BESS operation, TOU prices, or demand peaks. Stage 2 then fixed
  the Stage 1 assignment, so different PV curves could change charging and
  grid purchase without materially informing dispatch.
- Stage 1 now contains an assignment-coupled, time-indexed continuous energy
  recourse. It links per-vehicle charging to assignment-derived home-depot
  windows and compatible charger ports/power; propagates BEV SOC with
  service/deadhead energy; balances bus charging against per-slot grid, PV, and
  BESS sources; enforces per-slot PV conservation, BESS power/capacity/terminal
  SOC, grid import and contract overage, and peak demand; and prices TOU energy,
  demand, fuel, CO2, vehicles, drivers, degradation, and other enabled
  accounting terms. The former aggregate PV proxy is retained only as a
  labelled diagnostic lower bound. No weather assignment bias is used.
- Stage 2 remains the exact fixed-assignment binary charging/SOC/PV/BESS
  validation. Formal research requests now ask Stage 1 for a systematic
  time-bounded pool and pass at least ten distinct assignments through Stage 2
  under one global deadline. Candidate feasibility, hashes, relaxed objective,
  exact canonical cost, fleet mix, runtime, and IIS evidence are persisted in
  `stage1_stage2_candidate_evaluation.json/.csv`; the selected result is the
  feasible candidate with the lowest canonical actual cost. This does not claim
  integrated global optimality.
- Prepare schema
  `v5_pv_rated_output_authoritative` retains the v4 requirement that the
  service date and counterfactual PV source date to remain explicit and
  separate. The rain role additionally requires the explicit fixed-weekday
  counterfactual permission. Pair validation rejects implicit legacy weather
  contracts and verifies the non-PV control hash independently of the PV hash.
- `scripts/run_frontend_controlled_pv_pair.py` imports no optimization domain
  code. It calls the normal BFF Prepare and run-optimization HTTP endpoints,
  polls jobs sequentially, preserves unrounded request/response JSON, rejects
  forbidden old prepared IDs, invokes the pair manifest and small Phase 4
  oracle audits, produces assignment/solver/research comparisons with source
  artifacts, and creates the requested evidence ZIP only after fail-closed
  audits.
- Focused tests cover the intentionally weather-sensitive assignment
  counterexample, slot-local PV, depot-presence charging, charger ports and
  power, BESS terminal SOC, demand charge, contract overage parity with Stage
  2, deterministic replay, candidate selection by canonical cost, explicit
  counterfactual Prepare controls, pair-manifest rejection, and the HTTP-only
  runner boundary.
- Verification before freezing: the requested focused regression plus the
  HTTP/control tests passed (`85 passed`), the complete suite passed
  (`1056 passed`), `compileall` passed for `src`, `bff`, `scripts`, and
  `tools`, and `git diff --check` reported no whitespace error. A read-only
  scenario comparison found one non-PV mismatch in the rain case (BESS
  terminal policy); the existing alignment service was applied to the rain
  scenario and a second audit confirmed zero remaining non-weather
  simulation-config or overlay mismatches while preserving the
  `tsurumaki_2025-08-10_60min` PV input.
- The first frozen HTTP attempt at
  `d95e0e049a254bb3f3e560aa86e986ec4a773b7f` is preserved under
  `output/formal_pair_20260730` as diagnostic evidence. Both synchronous
  Prepare requests exceeded the runner's former 120-second HTTP default, so
  neither optimization job was submitted and the runner correctly returned
  `BLOCKED`. The runner now applies its explicit formal job timeout to Prepare
  and submit as well as polling, preventing a timed-out Prepare from advancing
  to the next case.
- The second frozen attempt at
  `3ee1c2f46a7d3bbbfa1244baf61fd7b5319188f5` is also preserved as
  diagnostic evidence. It exposed two independent Prepare-contract defects:
  an empty `selected_route_ids` expanded to all 56 depot routes and 974 trips
  instead of retaining the instructed common 16-route/264-trip scope, and
  omitted ICE initialization fields produced no explicit `initialFuelL` for
  the 25 selected-depot ICE vehicles. Both jobs therefore failed closed in the
  fleet contract before solving. The HTTP runner now sends the identical
  audited 16 route IDs in both cases, sends the common SOC/terminal/ICE-fuel
  and cost-component controls that generated the earlier explicit fleet-state
  contract, and rejects any Prepare route-count drift. The trip count remains
  materialized data and is not hard-coded.
- The third frozen attempt at
  `92c4f36e934ac10a4b12dd7b45aae6068ac6483f` is preserved under
  `output/formal_pair_20260730_diagnostic_attempt3` and remains diagnostic.
  Its fresh prepared inputs materialized the intended common 16-route scope,
  264 trips, 60 selected-scope vehicles, and 10 chargers. Sunny job
  `169e2fe4-8591-437d-8783-bf89b867a7c3` and rain job
  `d04bac53-de83-4235-940c-cc73d1cf7ead` both completed 24/24 Rolling,
  independent physical validation, terminal SOC, executed-day accounting,
  final reconciliation, and 229/229 artifact checks. The pair was nevertheless
  correctly blocked: only one distinct Stage 1 assignment was evaluated; the
  runner incorrectly treated a present zero unserved count as missing; the
  small integrated oracle exposed an unaccounted vehicle-discharge sink; the
  rain certified gap was 10.666%; and the unchanged assignment lacked the
  required alternative-cost audit.
- The follow-up correction preserves numeric zero in the run gate. Integrated
  Phase 4 now fixes vehicle discharge to zero until V2G has solver-native depot
  flow, accounting, and artifact provenance, and uses the Stage 2
  `FeasibilityTol=IntFeasTol=1e-9` physical numeric contract. Re-running the
  ten-trip sunny and rain integrated oracles against the archived inputs
  produced eligible, physically valid, accounting-matched results in both
  cases; these remain diagnostic checks rather than full-run evidence.
- Stage 1 now records a weather-sensitive analytical cost floor in addition to
  Gurobi's raw bound. It combines the strict path-cover vehicle-use floor with
  an optimistic independent-trip service-energy/fuel floor after maximally
  pooling PV, usable BESS inventory, and permissible initial BEV SOC. The
  certificate changes neither objective nor assignment and fails closed for a
  negative external vehicle fixed-use cost. On the archived 264-trip inputs it
  implied 3.4503% sunny and 3.2840% rain gaps against the prior incumbents,
  while retaining the raw Gurobi bound and gap separately.
- Candidate enumeration no longer spends the primary budget on continuous-flow
  solution-pool symmetries. It reserves a bounded post-primary interval,
  excludes previously evaluated trip-level BEV/ICE patterns, and supplies
  deterministic opposite-powertrain whole-duty swaps only as partial MIP
  starts. The unchanged Stage 1 model must still accept each candidate, and
  exact Stage 2 plus canonical accounting still determine feasibility and
  final selection. A full-scope diagnostic using the archived sunny prepared
  input found seven alternative BEV/ICE patterns in a 36-second enumeration
  reserve; all eight total candidates were Stage 2 optimal and canonically
  evaluable. This preflight used an old prepared input solely to validate
  enumeration mechanics and is not frontend or formal comparison evidence.
- The fourth frozen HTTP attempt at
  `19644e4449ec4a6fc7314d067cfba9dad944da03` is preserved under
  `output/formal_pair_20260730_diagnostic_attempt4` (and the matching ZIP).
  Sunny job `070606f1-89fb-4f1d-880e-1a0d374746b6` completed 264/264
  trips, 21/21 feasible candidates, 24/24 Rolling, independent physical
  validation, terminal SOC, executed-day reconciliation, and 229/229 artifact
  checks; its raw/certified gaps were 9.5801%/3.4503%. Rain job
  `4e06bb9c-c296-45f6-abed-32d9fd0d754d` generated 21/21 Stage 2-feasible
  candidates but failed before Rolling. The selected candidate's Stage 2
  terminal SOC was 218.14836 kWh, while the independent replay incorrectly
  checked the pre-return final-slot state of 219.72756 kWh. Its 23:14 trip
  arrival plus four-minute return completed at 23:18; the missing 1.5792 kWh
  was exactly the canonical terminal-return energy.
- The independent SOC replay now extends through the ceil boundary at which a
  final return completes and, when that boundary is beyond the nominal final
  slot index, evaluates the post-return state captured before any following-day
  charging. This aligns the replay with Stage 2's transition-ending-at-event
  convention without widening any SOC tolerance. Candidate selection now also
  runs `FeasibilityChecker` for every Stage 2 incumbent and requires Stage 2
  feasibility, canonical cost evaluability, and independent physical
  feasibility simultaneously. JSON/CSV candidate evidence records the
  physical status, error count, and error hash.
- The fifth frozen HTTP attempt at
  `448d52a0e876335a3df63776039a393db6ab4029` is preserved under
  `output/formal_pair_20260730_diagnostic_attempt5` (and the matching ZIP).
  Sunny job `7ba14751-51d5-4f7b-9108-e15f8285783a` and rain job
  `a6acab0c-630d-4b9f-ae3b-f5c190991b88` both completed 264/264 trips,
  21/21 exact-Stage-2 and independently physical candidates, 24/24 Rolling,
  terminal SOC, executed-day accounting, final reconciliation, and 229/229
  artifact checks. The controlled pair matched every non-PV control, used
  614.709375/101.1143 kWh PV, and changed the powertrain assignment of 37
  trips. Raw/certified Stage 1 gaps were 9.5801%/3.4503% (sunny) and
  100%/3.2840% (rain).
- Attempt 5 nevertheless remains diagnostic because both terminal job
  responses said the requested gap was unestablished even though their
  persisted `mip_gap_target_met` fields were true. The classification was
  correctly limited by the two-stage method's lack of integrated
  global-optimality proof, but its fixed interpretation and job-message text
  incorrectly conflated that scope blocker with gap failure.
- Result-claim classification now persists `mip_gap_target_met` explicitly.
  A feasible two-stage candidate that meets the certified Stage 1 target is
  reported as passing that gap gate while still stating that integrated global
  optimality is unestablished; a real gap miss remains fail-closed. The HTTP
  completion audit now rejects any contradiction between solver settings,
  persisted claim classification, and terminal response. Focused regression
  including the pass, miss, and old contradictory response branches passes
  (`90 passed`) and the complete suite passes (`1067 passed`). A new clean
  commit and a complete two-case HTTP rerun are still required. The release
  blocker is discharged only by a same-SHA `completion_audit.json` with
  `status=READY`, zero failed checks, and a completed evidence ZIP; no
  repository file is changed during that run.
- The sixth frozen HTTP attempt at
  `e63224fc2f627197fc6edde2264739eb4f440dc6` is preserved under
  `output/formal_pair_20260730_diagnostic_attempt6` (and the matching ZIP).
  Both runs again passed all solver, 24/24 Rolling, physical, accounting,
  artifact, pair, oracle, and terminal-claim gates. Packaging then exposed a
  25-byte metadata contradiction: `completion_audit.zip_size_bytes` described
  the first archive, after which the runner rewrote the audit/log and rebuilt
  a larger final archive. The field was therefore self-referential and could
  not truthfully describe the archive containing it.
- Packaging now finalizes the completion audit and execution log first, writes
  one temporary ZIP, validates CRCs, and atomically promotes it only when the
  destination is absent. The audit records creation intent/path but no
  self-referential size; ZIP failure rewrites the source-tree audit as
  `BLOCKED`. A byte-equality regression verifies that the archived and source
  completion audits are identical. Attempt 6 remains diagnostic, and a fresh
  same-SHA pair is required for final evidence.

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
  `1033` tests; `compileall` and `git diff --check` also passed before the
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
- The subsequent frozen run, `run_20260728_2036`, passed the corrected
  physical gate, final-cost reconciliation, 24/24 Rolling, and executed-day
  accounting, but artifact completeness correctly rejected a zero-byte
  `graph/refuel_events.csv`. The schedule had zero ICE refueling events; the
  generic graph writer had represented that valid empty event set as an empty
  file. The graph exporter now writes the declared CSV header even with zero
  rows. The artifact audit binds both `refuel_events.csv` and
  `graph/refuel_events.csv` to `canonical_solver_result.json`'s
  `refueling_schedule`: the exact schema and refueling-event multiset must
  match, and header-only exports are accepted only when the canonical schedule
  is empty. A missing, zero-byte, schema-invalid, or row-mismatched export
  still fails. This run remains
  diagnostic and a new clean-commit rerun is required.

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
- Tk Quick Setup and Prepare now derive the same declaration from the user's
  exact single-date selection (`Sunday` + `WEEKDAY` + `actual_date_profile`) and
  persist it to the prepared input. This fixes the prior UI-only failure before
  the solver; it does not alter the selected service date, timetable rows,
  route scope, or actual-date PV curve. `ProblemBuilder` propagates the
  verified declaration to the Rolling calendar audit.
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
  values. This 2026-07-28 change used a 15-minute internal-slot specification;
  the later 2026-07-30 controlled-PV instruction supersedes that experiment
  setting with common 60-minute internal slots and 60-minute Rolling updates.
  `--available-bev-count` is restricted to blocked day-ahead exploratory runs
  because a formal run may not mutate the prepared active fleet.
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
  `gurobi_threads=1` at that time (the current interactive contract is eight
  threads), and the BFF worker enforces the current values immediately
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

# 2026-08-09 - PV pair control-hash runtime telemetry fix

- The clean `b29c6e0` Phase 4 pair completed both 264-trip cases and accepted
  24/24 Rolling. Sunny used 27 BEVs/5 ICE buses and rain used 21 BEVs/11 ICE
  buses, but the pair builder incorrectly rejected `fixed_controls_match`.
- Root cause: `comparison_control_hash` included observed
  `phase4_phase3_seed_wall_runtime_sec` and
  `phase4_phase3_seed_candidate_evaluation_initial_budget_sec`. The values
  differed by normal runtime jitter even though all pre-solve controls matched.
- The comparison hash now includes declared budgets and search settings but
  excludes those two runtime outcomes. Per-run solver settings still retain
  both values for audit. The control-payload schema is bumped to
  `frontend_pv_control_contract_v2`.
- Focused regression: `47 passed`. Re-normalizing the completed pair's stored
  control payloads produced the same hash on both sides. Because acceptance
  code changed after the pair ran, those outputs remain evidence for SHA
  `b29c6e0` and are not relabelled as a formal result for the new commit.

# 2026-08-09 - PV1000 pair rerun and pair-readiness gap gate

- Clean frozen SHA `93d122e1fc929d4833f2997560fa16cf7523e96d`
  completed the fresh controlled pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_pairhash_93d122e_gap001`.
  Sunny used 27 BEVs / 5 ICE buses for 183 / 81 trips; rain used 21 / 11 for
  91 / 173. Both served 264/264, completed 24/24 Rolling, returned BEV/BESS
  SOC, reconciled executed-day accounting, and matched every declared non-PV
  control under comparison hash
  `18e7afc99d1aae1f118da8b3beceb65d11a66dc30552ef7bd60c31fb82e80cf1`.
- Sunny generated 6,056.25 kWh, bought no grid energy, and curtailed 3,606.64
  kWh. Rain generated 996.2 kWh and bought 124.985 kWh. The observed 27/5
  versus 21/11 composition is accepted controlled-sensitivity evidence, but
  both integrated solves stopped at a 100% raw gap instead of the requested
  0.1%, so the completion audit remains `BLOCKED`.
- Post-run review found that pair manifest v1 could still write
  `formal_research_submission_ready=true` because it discharged the pending
  comparison blocker without consulting each run's `mip_gap_target_met`.
  Manifest v2 now retains controlled-comparison acceptance separately and
  requires a feasible incumbent plus the requested MIP-gap certificate in
  both cases before formal readiness can become true. Missing legacy solver
  telemetry fails closed.
- Focused manifest tests pass (`10 passed`). Rebuilding only the pair manifest
  from the frozen run artifacts in a separate diagnostic directory produces
  comparison accepted=true, formal ready=false, with the two missing gap
  certificates reported explicitly. The original SHA-93d artifacts are not
  relabelled as results of the post-run reporting fix.

# 2026-08-10 - Memory-safe Phase 4 PV1000 pair and EV plateau diagnosis

- Frozen clean SHA `06ae09218be99ca47b951dcf6ddad886056b0ad6` completed
  the fresh pair at
  `output/formal_pair_20260810_flat30_pv1000_bess6000_phase4_06ae092_gap001`.
  Gurobi dual simplex was fixed for root and node LPs, node files start at
  0.5 GB, and `SoftMemLimit=32 GB`; this preserved the exact feasible set and
  objective while avoiding the earlier concurrent-root memory exhaustion.
- Both runs used the same 2025-08-05 weekday service, 264 trips, 60 active
  vehicles, 10 chargers, 6,000 kWh BESS with 3,000 -> 3,000 kWh SOC,
  30 JPY/kWh grid energy, 0 JPY/kW demand charge, and 1,000 kW PV rating.
  Only the separately hashed PV curve changed.
- Final high-PV assignment: 27 BEVs/5 ICE buses, 183/81 trips, total cost
  666,164.082366 JPY. Final low-PV assignment: 21/11 buses, 91/173 trips,
  total cost 698,419.690050 JPY. Both served 264/264, completed 24/24 Rolling,
  returned BEV/BESS SOC, passed physical validation, and reconciled solver and
  canonical accounting totals.
- The high-PV case generated 6,056.25 kWh, imported 0 kWh, charged buses with
  2,219.59 kWh, and curtailed 3,606.64 kWh. Therefore PV energy quantity is
  not the reason the observed incumbent stops at 27 BEVs. The final charging
  plan used at most 8 of 10 chargers concurrently.
- Eight examined 28--32 BEV seed assignments all failed exact fixed-assignment
  Stage 2 recourse. In a representative 28/4 candidate, BEV
  `befc4670-e889-45d9-bd65-23118c02e196` served 16 trips from 07:26 through
  23:24, required 201.946 kWh including deadhead/return energy, could accept
  only 90.642 kWh in chronological home-depot windows, and missed its
  return-to-initial terminal target by 111.303 kWh. Its IIS contains only
  vehicle charging-availability, vehicle charging-power, SOC-transition, and
  terminal-SOC constraints. This identifies a vehicle-local time/location
  bottleneck, not a depot-PV or shared-charger bottleneck.
- This is not a composition-wide infeasibility certificate. The integrated
  runs reached their 3,600-second limits with certified gaps 3.9276% and
  2.3871%, above the requested 0.1%. The pair is accepted as a controlled PV
  sensitivity but remains `BLOCKED` for formal research submission.
- Post-run artifact review found a diagnostic-only defect: the Stage 2
  energy-shortage CSV applied battery-SOC arithmetic to ICE duties using a
  synthetic 1 kWh capacity. SOC/charging precheck rows now include only
  BEV/PHEV/FCEV. Assignment and duty evidence still includes ICE, and the
  solver, IIS, objective, feasibility, and frozen run results are unchanged.
- The diagnostic fix passed 60 focused tests; `compileall`, `git diff --check`,
  and the complete regression suite passed with `1256 passed`.

# 2026-08-10 - Controlled-pair postprocessor respects declared Phase 4 gap

- Clean SHA `fa2c3808fdedb986ab703770ab8c9b6cf4cb17c7` completed both
  frontend jobs after the empty all-BEV fuel export correction. Sunny produced
  `32 BEV / 0 ICE`, 264/0 trips and a 0.735476% certified gap; rain produced
  `21/11`, 91/173 trips and a 0.399008% certified gap. Both used the
  predeclared 1% target and passed physical, Rolling, accounting, provenance,
  tariff, and artifact-completeness checks.
- The pair completion audit nevertheless failed three reporting checks. The
  case-audit helper discarded the CLI `--actual-cost-mip-gap 0.01` and compared
  both results with the historical `PHASE4_ACTUAL_COST_MIP_GAP=0.001` constant.
  It also required the old `feasible_candidate` label and exact English gap
  phrases, while an integrated accepted result correctly uses
  `validated_optimality_claim_candidate` and may return the generic terminal
  message `Optimization complete.`.
- The audit now receives the declared actual-cost gap explicitly, validates it
  as finite in `[0, 1)`, and compares structured result-classification fields,
  blocker lists, requested/certified gaps, and solver settings. Terminal prose
  is used only to reject explicit contradictions. Re-auditing the frozen
  artifacts in read-only mode accepts both cases with no failed checks; those
  artifacts are not relabelled as results of the new code.
- Focused runner regression tests cover integrated structured success, a
  certified gap above the request, legacy two-stage scope blockers, real gap
  misses, contradictory terminal text, and the custom 1% propagation. A fresh
  clean-commit pair is still mandatory before release readiness is claimed.
- `compileall`, `git diff --check`, and the complete regression suite pass
  (`1263 passed in 57.56s`). MIT-style self-review found no P0/P1 issue in the
  bounded postprocessor change; external Claude Code is not installed in this
  environment, so no independent Claude review is claimed.

# 2026-08-10 - Final clean PV1000 1% pair accepted

- Frozen clean SHA `6bf6bd7eebec06dde1a899bebe5e02f3dc9fd62c` completed
  the fresh pair at
  `output/formal_pair_20260810_flat30_pv1000_bess6000_phase4_6bf6bd7_gap01`
  in 2,324.1 seconds. Sunny and rain frontend jobs both reached `completed`
  after integrated Phase 4, 24-step Rolling, independent validation, and
  report finalization. The evidence ZIP was created beside the directory.
- Controlled inputs are 2025-08-05 weekday service, 264 trips, the identical
  active fleet and initial state, 10 chargers, 30 JPY/kWh grid energy,
  0 JPY/kW demand charge, 1,000 kW manual PV rating, and a 6,000 kWh / 900 kW
  BESS at 3,000 -> 3,000 kWh. Only the PV curve differs: 6,056.25 kWh high PV
  versus 996.2 kWh low PV. The comparison control hash is
  `3c0ee7cc5bfcd78a16b7a2f10c9177c8b08071710d362394f14ab842f0605c50`.
- High PV selected 32 BEVs / 0 ICE buses and 264/0 trips. Executed cost is
  644,741.923030 JPY, grid import 155.472886 kWh, fuel 0 L, and certified gap
  0.735476%. Low PV selected 21/11 and 91/173 trips. Executed cost is
  698,419.690050 JPY, grid import 124.985104 kWh, fuel 357.881339 L, and
  certified gap 0.399008%. The weather response is therefore 11 used BEVs and
  173 BEV trips, not the identical 13/19 Phase-3 seed composition.
- `completion_audit.json` is `READY` with no failed checks. Both case audits,
  the controlled comparison, pair controls, differing PV hashes, assignment
  difference, and `frontend_pv_pair_manifest_v2` pass. The pair manifest has
  `formal_research_submission_ready=true` and no formal-release failures.
- The standalone case claim scopes remain immutable and contain only the
  pending `controlled_counterfactual_pair_not_verified` release check. The
  pair builder is explicitly designed to discharge that one circular pending
  check after both cases exist; it does not rewrite the source run artifacts.
  Pair-level claims must cite the pair manifest, while a case viewed alone
  remains correctly blocked.
- The sunny all-BEV fuel ledger, time series, and summary are valid header-only
  CSV relations rather than zero-byte files. Artifact completeness accepts all
  three, confirming the empty-fuel export correction on the formal path.

# 2026-08-12 - Transition truthfulness, compatibility contract, and exact oracle

- Rebuilt the current 264-trip prepared scope before changing the solver. The
  old diagnostic reported 676 `deadhead_missing` pairs with route-band ON.
  Manual tracing showed that a same-place Soshigaya connection had a valid
  zero-minute deadhead alias but only four minutes of schedule slack against a
  ten-minute turnaround rule. The failure was therefore time insufficiency,
  not a missing OD.
- `src/dispatch/route_band.py` now separates direct location/OD resolution from
  the turnaround-time test. A known OD with insufficient slack is exported as
  `insufficient_transition_time`; `deadhead_missing` and
  `location_alias_missing` remain reserved for their actual data failures.
  The hard feasibility inequality is unchanged.
- Found a second audit defect: the route-band-OFF clone cleared the solver flag
  but retained Quick Setup's `allowIntraDepotRouteSwap=false`, so
  `ProblemBuilder` silently restored route-band ON. The audit now clears both
  controls. On the current prepared input the corrected results are:
  interval-only lower bound 18 vehicles; route-band ON lower bound 32 with
  20,048 route-band blocks and 676 insufficient-time blocks; route-band OFF
  lower bound 25 with 1,867 insufficient-time blocks and zero missing OD.
  These are lower bounds, not optimized fleet-composition claims.
- Prepare schema v7 now writes a complete vehicle-by-trip compatibility matrix,
  its powertrain projection, permission source, and SHA-256. Explicit trip permissions, explicit
  vehicle-route permissions, and an explicit all-selected-powertrains
  assumption are distinguishable. The backward-compatible implicit all-type
  fallback is still usable for non-formal data but now blocks teacher release.
  Vehicle-specific restrictions within one powertrain also block because the
  current solver projects eligibility by powertrain. The current scope
  explicitly permits every selected BEV and ICE on all 264 trips.
- Added `small_exact_assignment_oracle_v1`, an independent Cartesian
  enumeration for strict one-day all-ICE cases up to ten trips. It fails closed
  outside that scope and does not import the MILP implementation. The four-trip
  fixture enumerates 16 assignments, finds two feasible ones, and certifies a
  two-vehicle, 6 L, 900 JPY optimum.
- The first oracle/MILP comparison exposed a real accounting bug: the integrated
  mathematical model used vehicle-specific ICE fuel rates (6 L) but the
  evaluator, end-fuel ledger, and CO2 ledger reused the vehicle-type trip
  default (5 L, 750 JPY). Those ledgers now use the same precedence as the
  solver: explicit trip/powertrain quantity, then physical vehicle rate, then
  trip fallback. The independent oracle and integrated MILP now agree on
  assignment, liters, cost, and emissions.
- Renamed the thesis method contract to M0--M3 and separated it from the
  PV/BESS component ablation.
- Added `arrival_immediate_charge_baseline_v1`. M0 applies it to the canonical
  rule assignment and M2 applies it to the optimized assignment. The adapter
  allocates physical charger ports by continuous home-depot arrival order,
  uses direct PV before grid, holds BESS at initial SOC, and fails closed on
  SOC, transition, charger, or coverage errors. It never repairs or reassigns
  a candidate. The v1 session contract is conservative and explicit: only
  complete residence slots are used, and piecewise-taper setup/teardown is
  deducted per charged slot rather than claiming optimized continuous
  sessions. Depot-reset energy is materialized at a multi-fragment boundary,
  but a plan exceeding the canonical fragment limit remains infeasible; the
  adapter does not override that independent checker.
- A final self-review found that the legacy SOC checker restarted every BEV
  duty fragment from initial SOC and replayed the vehicle's complete charge
  ledger for each fragment. Stage 2 currently proves only that a direct or
  depot-reset transition is possible; it does not persist the selected
  alternative or its energy. `FeasibilityChecker` now fails closed with
  `SOC_FRAGMENT` for every multi-fragment electric vehicle and skips the
  ambiguous replay. Single-fragment formal cases are unchanged. Continuous
  electric fragment SOC remains an explicit blocker until transition choice
  and energy are solver-native.
- Canonical frontend runs now emit
  `thesis_ablation/day_ahead_method_candidates.json` and `.csv`, with every
  available candidate evaluated by the same `CostEvaluator` and
  `FeasibilityChecker`. The method label follows solver structure:
  `charging_only` supplies M1, dispatch-capable runs can supply M2, and only
  `integrated` supplies M3. Missing methods remain explicit separate-run
  requirements; no additional solver is hidden in postprocessing and no
  day-ahead candidate cost is mixed with Rolling accounting. The partial
  artifact is therefore `research_conclusion_eligible=false`.
- Added both ablation candidate files to the frontend artifact-completeness
  v2 contract. The semantic audit verifies the payload SHA, exact M0--M3 method
  set, and method availability appropriate to `charging_only`,
  `assignment_only`, `two_stage`, or `integrated`. A failed adapter or
  non-integrated result mislabeled as M3 can no longer be hidden by an
  otherwise successful primary solve.
- Corrected `trip_energy_kwh` precedence so independent SOC/charging checks
  honor explicit per-powertrain trip energy before a vehicle distance rate,
  matching the integrated MILP.
- A no-solver smoke check against the latest existing 264-trip, 60-vehicle
  prepared input constructed the 32-vehicle M0 baseline and passed coverage,
  transition, SOC, and charger validation with no errors. This is
  implementation evidence only: the prepared input predates this commit and
  no optimization result or research claim was generated from it.
- Focused regression after the transition/oracle implementation: `38 passed`.
  The M0/M2 adapter, canonical BFF path, and artifact gate subsequently passed
  46 focused tests. After the final fail-closed electric-fragment guard, the
  complete repository regression passed `1306 passed in 65.70s`. No formal
  optimization run was executed from this
  dirty development state. Because prepared schema
  and accounting semantics changed, all future evidence requires fresh
  Prepare and a clean frozen commit; older outputs retain their original SHA.

# 2026-08-12 - Independent grid-only electric exact oracle

- Added `small_exact_electric_oracle_v1` for bounded formulation verification.
  It supports only strict one-day, one-depot cases with at most ten
  depot-to-depot trips, PV=0, BESS=0, a flat grid tariff,
  `constant_power_v0`, and BEV terminal SOC equal to initial SOC. Unsupported
  powertrains, cost semantics, nonzero PV/BESS, time-varying tariffs, or
  charger-ID compatibility fail closed.
- Assignment is completely enumerated. For each dispatch-feasible assignment,
  a separate SciPy/HiGHS MILP optimizes grid charging with binary charger-port
  occupation, vehicle/charger power limits, depot import limit, slot SOC
  bounds, departure readiness, and terminal equality. The audit intentionally
  does not import or reuse the production Gurobi equations, so agreement is an
  independent check rather than solver self-certification.
- Added machine-readable optimal and infeasible certificates. They record the
  total assignment enumeration, dispatch-feasible and energy-feasible counts,
  costs, grid input, fuel, terminal SOC, and chosen assignment.
- Added fixtures for the hand-calculated BEV/ICE grid-price break-even
  `(150 / 4.52) * 0.95 / 1.316 = 23.956344 JPY/kWh`, BEV preference at
  20 JPY/kWh, ICE preference at 30 JPY/kWh, return-to-initial infeasibility
  without a charger, and simultaneous two-BEV infeasibility with one 20 kW
  port versus feasibility with two ports. Each feasible oracle plan is also
  checked by the canonical `FeasibilityChecker` and `CostEvaluator`; the
  integrated Gurobi model matches the independent assignment and accounting
  cost at both tariff sides within numerical tolerance.
- Focused regression for both exact oracles passes `11 passed`; the related
  SOC, charger, accounting, and integrated-objective regression passes
  `68 passed`; and the complete repository regression passes
  `1315 passed in 117.73s`. No frontend, 264-trip, Rolling, or formal research
  optimization was executed from this code-changing state. The exact oracle
  closes only the bounded electric formulation-test item; fresh M1/M0--M3,
  sensitivity, and controlled-pair evidence remain required.

# 2026-08-12 - Explicit M1 and same-input M0--M3 comparison contract

- Confirmed that the reachable canonical M1 path already exists:
  `phase1_charging_only` normalizes the supplied fixed assignment (or the
  canonical baseline assignment) and calls the same Stage-2 charging/PV/BESS
  MILP used by the thesis pipeline. Added an end-to-end bounded Gurobi test
  proving that the trip-to-vehicle assignment is unchanged, charging dispatch
  and exact source provenance are evaluated, and the resulting frontend
  candidate is labeled M1 rather than M2/M3.
- Exposed `phase1_charging_only` in the Tk solver settings. Fixed Prepare's
  phase classification so all explicit Phase 1--4 tokens use the
  `milp_exact` profile instead of being mislabeled `hybrid_seeded`. The Tk
  Prepare dependency watcher now preserves the prepared ID when switching
  only among these explicit MILP phases; changing to ALNS/GA/ABC/hybrid still
  marks it stale. This makes a literal same-prepared-input M1/M3 frontend pair
  possible without weakening input mutation invalidation.
- Extended `optimization_parameters.json` with hashes for chargers, depots,
  vehicle types, tariffs, and one `canonical_ablation_input_sha256`. The latter
  covers the effective scenario, objective weights, trips, vehicles, vehicle
  types, depots, chargers, tariff/PV/BESS inputs, feasible connection network,
  and baseline assignment. This prevents separate M1/M3 runs with a changed
  tariff, charger set, connection graph, or rule dispatch from being combined.
- Added `thesis_day_ahead_ablation_comparison_v1` and
  `scripts/build_thesis_ablation_comparison.py`. The builder never invokes a
  solver. It selects M0/M1 from the explicit Phase 1 artifact and M0/M2/M3 from
  the explicit Phase 4 artifact only after verifying both source payload
  digests, the same prepared ID and source bytes, the same canonical input and
  clean Git SHA, valid research input bundles, accepted source solutions,
  achieved MIP-gap targets, identical M0, and physical/comparison eligibility
  for all four methods. Any mismatch produces `BLOCKED` with named failures.
- The experiment matrix now records M1 as an available explicit frontend
  phase and requires the merged comparison artifact. Focused M1, comparison,
  input-provenance, Prepare, Tk, and experiment-contract regressions pass
  `111 passed`. The comparison merge also rechecks the final hashes recorded
  in each source `artifact_completeness.json` for the method candidates,
  summary, solver settings, and run manifest. A post-hoc edit cannot inherit a
  stale source acceptance label. No fresh 264-trip M1/M3 run was started from this dirty
  development state; current-HEAD method effects remain unreported. The full
  repository regression passes `1326 passed in 122.44s`.

# 2026-08-13 - Revised-model formal pair and lexicographic contract repair

- Ran the two saved Tsurumaki scenarios through the ordinary frontend/BFF
  path from clean frozen SHA
  `332b6af48260c89bc14a2ad2be67a0fd1d2f168e`. Both fresh Prepare inputs held
  the 2025-08-05 weekday service, 30 JPY/kWh flat energy price, zero demand
  charge, 1,000 kW PV rating, 6,000 kWh / 900 kW BESS, 3,000 -> 3,000 kWh BESS
  SOC, 60 selected vehicles, ten chargers, and 264 trips fixed. Only the
  separately hashed 2025-08-05 and 2025-08-10 PV curves differed.
- Both cases served 264/264 trips, completed and accepted 24/24 hourly
  Rolling, passed the independent physical event validation, reconciled
  executed-day accounting, and produced the complete pair progress-report
  figures and source CSVs. The high-PV incumbent used 31 BEVs / 1 ICE bus for
  248/16 trips; the low-PV incumbent used 21/11 for 91/173 trips.
- Rolling accounting reported 650,234.729396 JPY and 170.814257 kg-CO2 for
  high PV, versus 698,318.002033 JPY and 986.112082 kg-CO2 for low PV. High PV
  generated 6,056.25 kWh, used 401.407349 kWh directly for buses and
  2,781.817437 kWh for BESS, and curtailed 2,873.025214 kWh. Low PV generated
  996.2 kWh, used 293.407649 kWh directly and 702.792351 kWh for BESS, with no
  curtailment.
- The pair remains `BLOCKED`. Both Phase 4 solves ended at `time_limit` and
  did not establish the requested 1% gap. The preserved run must therefore be
  described only as a physically valid feasible controlled candidate, not an
  optimal fleet-composition result.
- Pair finalization found a second, independent software defect. The canonical
  metadata contained `objective_preset=research_lexicographic_v1`, but the
  assignment economic audit read only solver metadata and exported null. The
  pair builder consequently reported false objective-preset mismatch and
  false scalar-accounting requirements. The audit now falls back to canonical
  problem metadata and records the preset in both JSON and CSV; artifact
  completeness requires the field.
- A model-control review then found that the integrated adapter installed the
  lexicographic objectives with `setObjectiveN` and later called
  `setObjective`, overwriting objective 0. The scalar/policy objective branch
  now explicitly skips that call when the research hierarchy is active.
- Gurobi does not expose one scalar `MIPGap` for a completed hierarchical
  multi-objective solve. The bounded exact-oracle gate now accepts missing
  scalar gap only when both public and raw solver statuses are `OPTIMAL`, all
  physical/accounting checks pass, and the recorded raw primary objective
  equals the used vehicle-day count under the exact declared hierarchy.
- Post-fix diagnostic execution on ten day-spanning trips at 15-minute
  resolution completed with exit code 0: integrated Gurobi status `OPTIMAL`,
  two used vehicles, raw primary objective 2.0, secondary accounting cost
  40,000 JPY, and exact-oracle eligibility true. This bounded diagnostic does
  not relabel the pre-fix 264-trip pair or discharge its missing full-run gap.
- Focused regression for economic-audit provenance, artifact completeness,
  pair semantics, frontend execution, and the small integrated oracle passes
  `79 passed`; the complete repository regression passes
  `1348 passed in 70.73s`. A fresh clean-commit full pair is required because
  the lexicographic objective implementation changed after the preserved run.

# 2026-08-13 - Post-fix controlled PV pair completed at `e4ddd3f`

- Executed the mandatory post-fix pair from clean frozen SHA
  `e4ddd3f146975c34ac61e957385cd5a26daaca66` through the ordinary frontend/BFF
  Prepare, Phase 4, job polling, 24-hour Rolling, validation, accounting, pair
  finalization, bounded-oracle and progress-report path. The worktree was clean
  at both ends and the SHA did not change during either solve.
- Both cases used the same 2025-08-05 `WEEKDAY` service, 264 trips, 60 active
  vehicles, ten chargers, 30 JPY/kWh flat energy tariff, zero demand charge,
  1,000 kW manually rated PV, 6,000 kWh / 900 kW BESS and 3,000 -> 3,000 kWh
  BESS SOC. The input/output audit reports 5,000 m2 estimated installable panel
  area and 14,285.714286 m2 estimated depot area from the 1,000 kW rating.
  Non-PV controls share hash
  `1ae12973a92ad50c1257cd67c351f485f4451b6d164298a72fc72204fd12df11`;
  the two separately hashed PV curves differ by 5,060.05 kWh.
- Both runs served 264/264 trips with zero missing/duplicate/overlapping trips,
  zero transition, SOC, charger-concurrency and grid-contract violations,
  accepted all 24 Rolling steps, kept the assignment hash constant during
  Rolling, and reconciled the executed-day ledger. No fallback or post-solve
  repair was used.
- High PV used 31 BEVs / 1 ICE bus for 248/16 trips. Its executed ledger records
  6,056.25 kWh PV generation, 401.407349 kWh PV-to-bus, 2,781.817437 kWh
  PV-to-BESS, 2,510.590237 kWh BESS-to-bus, 156.039059 kWh grid import,
  2,873.025214 kWh curtailment, 35.884956 L Rolling-consistent fuel,
  650,234.729396 JPY total
  cost and 170.814257 kg-CO2.
- Low PV used 21 BEVs / 11 ICE buses for 91/173 trips. Its executed ledger
  records 996.2 kWh PV generation, 293.407649 kWh PV-to-bus, 702.792351 kWh
  PV-to-BESS, 634.270097 kWh BESS-to-bus, 130.948752 kWh grid import, zero
  curtailment, 356.022849 L Rolling-consistent fuel,
  698,318.002033 JPY total cost and
  986.112082 kg-CO2.
- `pair/pair_manifest.json` accepts the pair for the explicitly scoped
  same-service-date PV-supply sensitivity comparison. Objective presets match;
  both lexicographic objective-semantics audits, composition-search audits,
  physical/accounting/artifact gates and pair-control checks pass. Assignment
  hashes differ, so the observed response is not a reporting-only difference.
- Formal research submission remains `BLOCKED` only at the pair release layer:
  both integrated solves terminated at the time limit without a certified
  full-model gap, so `baseline_requested_mip_gap_certified` and
  `counterfactual_requested_mip_gap_certified` fail. These are physically valid
  feasible incumbents and controlled sensitivity evidence, not certified
  global or lexicographic optima.
- Both post-fix 10-trip, 15-minute bounded integrated oracles returned exit code
  0 and `integrated_exact_oracle_eligible=true`; integrated and two-stage
  accounting costs were both 40,000 JPY with two used BEVs. This confirms the
  repaired hierarchy on the bounded exact problem but does not discharge the
  full 264-trip gap gate.
- Authoritative directory:
  `output/formal_pair_20260813_thesis_model_flat30_pv1000_bess6000_phase4_e4ddd3f_gap01_r2`.
  The generated ZIP is 19,860,911 bytes with SHA-256
  `504C282BDC51710AB821CCBCA2BDEA66FFBCFAC5B3D0AA5A4C42A2A63633E932`.
  `progress_report/` is complete (`READY`) with seven PNG/SVG figures, six CSV
  tables and hashed evidence indexes. Full-scale M0--M3 and the predeclared
  sensitivity matrix remain unexecuted evidence tasks; their code paths are
  implemented but this pair must not be presented as those experiments.
- The post-run metadata review found one remaining evidence-label defect:
  `integrated_primary_objective_kind` still said `canonical_actual_cost` under
  `research_lexicographic_v1`, although Gurobi's actual first objective was used
  vehicle-days. `_apply_phase_contract` now records
  `minimum_used_vehicle_days_lexicographic` and correctly marks scalar actual
  cost as not requested for that preset. This changes provenance only, not the
  solved equations or preserved `e4ddd3f` results; the frozen pair is not
  rewritten after the run. The pair runner now requires this truthful primary
  label whenever `research_lexicographic_v1` is active, even if a conflicting
  legacy EV-policy flag is also present. The relevant objective, exact-oracle,
  pair and frontend-runner regressions pass `79 passed`; the complete repository
  regression passes `1349 passed in 66.32s`.

# 2026-08-13 - Sequential lexicographic cost-gap certification

- Audited the remaining pair blocker and confirmed that the integrated
  `research_lexicographic_v1` path used Gurobi `setObjectiveN`. When the full
  model reached its time limit, the returned model state did not provide a
  single canonical-operating-cost `ObjBound` or `MIPGap`; the release gate
  therefore could not distinguish an uncertified cost stage from the
  vehicle-day primary objective.
- Replaced that path with sequential scalar solves under one unchanged Phase 4
  wall-clock budget. The mathematical hierarchy is now implemented as
  `min used_vehicle_days`, fix the certified integer optimum, then
  `min canonical_operating_cost`. Exact cost is fixed before the optional
  deadhead and charge-session tie-break stages. A stage that is not certified
  prevents every lower-priority stage from running.
- The strict path-cover lower bound and a complete integrated fixed-dispatch
  recourse incumbent can certify the vehicle-day stage without re-solving when
  both counts match. The preflight now records its used vehicle-days and its
  canonical cost as separate quantities. A cost upper bound from that seed is
  added only after the same minimum vehicle-day count is fixed, so it cannot
  exclude a lexicographically superior lower-count solution.
- Raw cost-stage objective, bound, gap, status, completed hierarchy levels and
  the primary certificate are propagated through the MILP engine and BFF
  `solver_settings.json`. The formal controlled-pair audit requires the
  sequential solve mode, an exact primary certificate and non-null cost-stage
  objective/bound before accepting the requested cost gap.
- Independent four-trip enumeration agrees with the integrated result:
  two vehicle-days, 900 JPY canonical cost, 900 JPY bound and zero cost gap;
  all four requested hierarchy levels complete. A verified Phase 3 seed test
  separately proves the no-resolve primary-certificate path. Focused Phase 4,
  exact-oracle, BFF and pair regressions pass `130 passed`; the complete
  repository regression passes `1351 passed in 65.94s`.
- This changes solve sequencing and evidence metadata, not the feasible region,
  energy balance, tariff or accounting equations. The frozen `e4ddd3f` pair is
  not relabeled. Current-HEAD formal evidence remains pending a clean commit,
  fresh Prepare, both full Phase 4 runs, Rolling and pair finalization.

# 2026-08-14 - Publishable bounded electric exact-oracle certificate

- Audited the existing `small_exact_electric_oracle_v1` implementation instead
  of duplicating it. The independent oracle already covers complete assignment
  enumeration, BEV slot SOC, departure readiness, terminal return-to-initial
  SOC, charger-port concurrency, grid import, canonical electricity/fuel cost,
  the 23.956344 JPY/kWh hand break-even boundary, PV=0, and BESS=0.
- Added `small_electric_oracle_verification_v1` and
  `scripts/build_small_electric_oracle_certificate.py`. The fixed benchmark
  matrix publishes five cases: tariff below/above break-even, terminal SOC with
  no charger, one port for two simultaneous BEVs, and the corresponding
  feasible two-port case. Positive PV and hidden positive BESS capacity are
  independently exercised as fail-closed scope guards.
- Every feasible independent-oracle result is replayed through the canonical
  `FeasibilityChecker` and `CostEvaluator`. When building publishable evidence,
  the same input is also solved by the production integrated Gurobi path with
  zero requested MIP gap. The certificate records costs, assignments,
  enumeration counts, terminal SOC, scope guards, solver status and numerical
  residuals under one deterministic payload SHA-256.
- The first integrated two-port regression exposed a legitimate symmetric
  alternative solution: the two identical BEV IDs were exchanged while the
  trip-powertrain assignment, cost, energy and feasibility were identical.
  The comparison now records exact vehicle-ID equality separately and accepts
  only exact trip-powertrain plus canonical-cost equality. It does not hide or
  relabel the ID permutation.
- The bundle writer emits JSON, CSV, Markdown and a manifest containing source
  Git provenance and byte hashes. Its normal CLI refuses a dirty worktree;
  `--allow-dirty-git` is explicitly diagnostic. Every bundle remains
  `research_conclusion_eligible=false` and cannot substitute for a full
  network, positive-PV/BESS, Rolling, or formal gap certificate.
- Final code review found that the ten-trip limit did not by itself bound the
  Cartesian assignment count: ten trips against a large fleet could still
  make the test-only oracle run effectively forever. Both all-ICE and electric
  oracles now hard-cap complete enumeration at 1,000,000 assignments and allow
  callers to choose only a lower cap. Regression tests prove that a 16-case
  fixture is rejected before enumeration when the declared cap is 15.
- Focused regression after final review passes `17 passed`, including both
  exact oracles, canonical reconciliation, scope rejection, bundle hashing,
  tamper detection and integrated Gurobi agreement. The complete repository
  regression passes `1408 passed in 73.27s`.
- Committed the implementation as clean SHA
  `3307f964b8992377b166901d474ebbcb899f548a`, then generated
  `output/verification/small_electric_oracle/3307f964/`. The source worktree
  was clean, certificate status and integrated-Gurobi comparison are both
  `VERIFIED`, and all ten declared checks pass. The deterministic certificate
  payload SHA-256 is
  `dd797eba2ac3d1d26ea39ab85672bf8d23a349be3b0e362fe04f990df42dd0bf`;
  the bundle-manifest payload SHA-256 is
  `92abe15b903529cf20ea478de586d33cd4f5c9a2e4a87eaf368a41b4e46b3604`
  and its file SHA-256 is
  `bbb29244cfc4885bd83e7ade8d5bae7387bfa59a942af0cdea9bfec5cd1e2cd0`.
  This closes the bounded electric-oracle evidence item only. The certificate
  itself remains explicitly ineligible for full-network research conclusions.
- After the enumeration guard, clean SHA
  `305b5e3a3493b9198c6d0d8ea612b6f383d326c6` regenerated the superseding
  bundle at `output/verification/small_electric_oracle/305b5e3/`. Its
  certificate payload remains byte-identical at
  `dd797eba2ac3d1d26ea39ab85672bf8d23a349be3b0e362fe04f990df42dd0bf`,
  showing that the bounded mathematical results did not change. The new
  manifest payload/file SHA-256 values are
  `c4e643e6ec5071804c8f6ecaa9ef362bf7ff7aaa60a92b286ba63e8f72bb67bc`
  and `9be2a8ec70f7ea4e6a5169feb0e288ffda800bd340681dafe84e0b68f139f44d`.
  The earlier `3307f964` directory is retained as immutable historical output;
  the `305b5e3` bundle is the current oracle evidence.

# 2026-08-14 - Vehicle-day-cost sensitivity preflight and accounting gate

- Audited the predeclared `VEHICLE_DAY_0` and `VEHICLE_DAY_20000` cases. Both
  intentionally use `scalar_total_cost_v1`; using
  `research_lexicographic_v1` would minimize vehicle days before monetary cost
  and would therefore make a 0/20,000 JPY coefficient comparison incapable of
  isolating the coefficient's effect.
- The existing sensitivity audit checked only that the requested unit cost and
  objective preset reached model metadata. It could not prove that the cost
  component was enabled, charged exactly once per used vehicle-day, included
  in the actual scalar objective, or reconciled in the executed Rolling
  accounting. A silently disabled or duplicated cost could therefore have
  passed the parameter check.
- Added a family-specific fail-closed audit requiring
  `vehicle_usage_cost=true`, `canonical_actual_cost` as the integrated primary
  objective, the actual-cost structural contract, identical declared/model/
  accounting unit cost, one-day vehicle count equal to vehicle-day count,
  `fixed_vehicle_day_cost` classified as research-eligible, and
  `vehicle_usage_cost_jpy = used_vehicle_day_count * unit_cost` within
  `1e-6 JPY`.
- Added the unit, used vehicle-days, charged cost, formula residual, semantics
  and research-eligibility flag to every sensitivity row. Non-vehicle-day
  families record this audit as not applicable and remain unaffected.
- Focused matrix, vehicle-cost, integrated-objective and literature-figure
  regression passes `67 passed`; the repository suite passes `1410 passed`.
  A clean commit, fresh Prepare and the two
  normal frontend/BFF sensitivity jobs remain required before any numerical
  effect is reported.

# 2026-08-14 - Literature solve-time audit and current bottleneck diagnosis

- Read the 23 PDFs under `先行文献/` and extracted the reported computation
  scope, instance size, method, hardware, stopping rule, runtime and gap where
  available. The evidence table is in
  `docs/notes/LITERATURE_SOLVE_TIME_COMPARISON_20260814.md`.
- Confirmed that tens-to-hundreds-of-seconds results are common for fixed
  vehicle schedules, charging-only MILPs, Lagrangian/dynamic-programming
  decompositions and near-optimal metaheuristics. The closest integrated
  comparison, No06, solves 418 trips with ALNS-SA in 202.3 seconds, while
  Gurobi fails to find a feasible solution for 200 and 418 trips within six
  hours. No55 reports about five hours for 70 trips using a GA with 120-way
  parallel chromosome evaluation.
- Audited frozen formal pair SHA `f46f1e8`. Both cases record 678,600 complete
  successor arcs, 780,112 fixed-recourse variables, 1,598,973 constraints and
  726,240 discrete start values. The high-PV case reaches a feasible incumbent
  immediately but spends 3,600.80 seconds proving only a 1.574% gap; the
  low-PV case is independently certified to 0.547% in 18.36 seconds.
- The asymmetry comes from the certified lower bound. Low PV contributes a
  54,498.14 JPY unavoidable energy/fuel floor. High PV permits all pooled PV
  to be treated as free in the current optimistic relaxation, so its
  energy/fuel floor is zero and the bound remains the 640,000 JPY vehicle-day
  minimum.
- The next performance change must target formulation size and proof strength,
  not research-gate relaxation: aggregate vehicle-indexed path symmetry with
  a certified path-cover/column or decomposition approach, and add only
  mathematically unavoidable high-PV costs to the lower bound. Any ALNS-style
  hundreds-of-seconds mode must be labeled near-optimal and kept separate from
  the full-network formal certificate.

# 2026-08-14 - Exact lazy separation of fragment-transition constraints

- Decomposed the frozen high-PV model's 1,598,973 rows by formulation source.
  `integrated_fragment_pairwise_constraint_count` alone was 1,243,440, or
  about 77.8% of all recorded constraints. These rows enumerated every
  chronologically ordered vehicle/end-fragment/start-fragment pair before the
  solve, although one incumbent selects only a small number of boundaries.
- Replaced this quadratic row materialization in both Stage 1 and integrated
  Phase 4 with `_FragmentTransitionLazySeparator`. At every integer incumbent
  it checks only selected same-day chronological boundary pairs using the
  unchanged canonical `fragment_transition_diagnostic`, then submits the same
  `end_arc + start_arc <= 1` inequality that the explicit formulation used.
  Complete successor arcs, fragment occupancy, overlap cliques, route-band,
  energy, SOC, charger, tariff and accounting semantics are unchanged.
- The first direct Gurobi regression exposed a correctness issue in the draft:
  Gurobi may present the same invalid incumbent more than once while presolve
  or solution processing continues. Suppressing an already-submitted pair let
  the repeated invalid point survive. The final callback therefore re-submits
  every currently violated row, while recording unique cut count and total
  submission count separately.
- All Stage 1 primary, composition and enumeration optimize calls, plus every
  integrated search phase, now install the exact callback. Callback exceptions
  terminate the model and are raised after optimize; they cannot silently
  produce a research-eligible result. `solver_settings.json` exports the
  explicit-row count, formulation mode, callback counts and errors for Stage 1
  and integrated Phase 4.
- Added real-Gurobi tests for an invalid two-fragment pair, a valid Phase 4
  depot cycle, repeated lazy enforcement, callback fail-closed behavior and
  BFF metadata propagation. The focused solver/BFF/README regression passes
  `80 passed in 3.45s`; the complete repository regression passes
  `1413 passed in 74.01s`.
- This patch changes model construction and branch-and-cut execution, but not
  the integer feasible set or objective. Old outputs remain immutable. A clean
  commit and fresh 264-trip high-PV diagnostic are required before claiming any
  runtime reduction or formal-gap improvement.

# 2026-08-14 - 600-second lazy-fragment diagnostic and metadata repair

- From clean SHA `885bacbec2c5cd19450fae84ef719fb0a1639489`, executed a fresh
  frontend/BFF high-PV Prepare and diagnostic optimization for scenario
  `771d115b-75b0-49f7-a7f0-25f259a2cd21`. The request used 264 trips, 60
  vehicles, 10 chargers, PV 1000 kW, BESS 6000 kWh, flat 30 JPY/kWh,
  zero demand charge, Phase 4 integrated MILP, seed 42, 1% target gap and a
  600-second Phase 4 limit. It was deliberately `research_run=false` and did
  not execute Rolling, so it is diagnostic evidence only.
- The fixed-recourse model retained 780,112 variables and reduced constraints
  from the historical 1,598,973 to 355,533. The difference is exactly the
  1,243,440 explicit fragment-pair rows moved to lazy separation. Fragment
  occupancy stayed at 24,600 rows and overlap cliques at 9,420 rows.
- Phase 4 stopped after 601.236881 seconds with the same incumbent
  650,234.729396 JPY, certified bound 640,000 JPY and certified gap
  1.574005345% as the historical 3600-second run. The Phase 3 seed wall time
  was 478.338058 seconds. One MIPSOL callback occurred; the incumbent used one
  fragment per used vehicle, so zero unique lazy cuts and zero submissions
  were needed.
- Added `scripts/build_lazy_fragment_performance_diagnostic.py`. It consumes
  immutable baseline/candidate run directories and generates
  `performance_comparison.json`, `.csv` and `.md`. It verifies unique recorded
  model counts, exact row deltas, separator fail-closed metadata and outcome
  equality. It refuses a runtime claim when canonical fingerprints, time
  limits, formal scope or repeated-run eligibility differ. For this pair it
  correctly reports `runtime_claim.status=NOT_CERTIFIED`: the observed Phase 4
  time ratio is not a speedup claim.
- The diagnostic exposed a P1 reporting bug. Separator metadata was correct in
  `canonical_solver_result.json.metadata`, but absent from the allow-list that
  copies `plan.metadata` into the public engine `solver_metadata`; therefore
  the historical diagnostic's `solver_settings.json` contains null/empty
  separator fields. Added a failing TDD regression, then propagated Stage 1
  and integrated pairwise mode/count/separator plus occupancy/clique counts
  through both `src/optimization/milp/engine.py` and
  `src/optimization/engine.py`. Existing output files remain immutable; only
  future runs receive the repaired public metadata.
- Added direct MILP, top-level engine, BFF/README and postprocessing regression
  coverage. The final focused set passes `30 passed in 1.55s`; the complete
  repository regression passes `1416 passed in 130.92s`.
- This diagnostic falsified the hypothesis that explicit fragment-pair rows
  alone caused the high-PV proof gap. Row count fell 77.8%, but incumbent,
  bound and gap were unchanged. The next performance tranche must strengthen
  the valid high-PV lower bound or replace the monolithic vehicle-indexed
  master with a certified path/column decomposition; research gates will not
  be relaxed.

# 2026-08-14 - Use Phase-3 Stage-2 IIS as non-directional Phase-4 guidance

- Re-read the clean `885bacb` 600-second high-PV diagnostic. Phase 3 did not
  omit the all-BEV composition: candidate `32 BEV / 0 ICE` was evaluated first
  and Stage 2 proved it infeasible in 1.545 seconds. The `31/1` through `28/4`
  candidates were also Stage-2 infeasible; `27/5` was the first feasible seed.
  Integrated Phase 4 later found a better `31/1` incumbent, so those fixed
  assignment failures do not prove an infeasible composition.
- The all-BEV candidate IIS contained 63 constraints and one variable bound.
  Its named constraints and optimistic path-energy audit isolated a
  vehicle-local SOC/charging/terminal-SOC conflict, including one vehicle with
  a 111.286315 kWh optimistic terminal shortfall. The historical piecewise
  charge rows appeared as opaque `R####` names, which prevented the existing
  scope classifier from safely treating the IIS as vehicle-local.
- Every piecewise charge/session constraint now has a stable semantic name.
  The IIS classifier recognizes vehicle-local SOC, charge power, charge-on and
  piecewise variable bounds. Shared charger, depot, grid, unknown constraints,
  or unknown bounds remain explicitly classified as shared/unknown evidence.
- Phase-3 candidate evaluation now exports the cut type, scope, implicated
  vehicle IDs and classification reason. The Phase-4 seed handoff discards
  time-limit/no-IIS rows and deduplicates certified Stage-2 patterns.
- MIT review found a P1 correctness defect in the first draft: Phase 3 Stage 2
  and integrated Phase 4 are different mathematical formulations. A Stage-2
  IIS cannot, without an integrated fixed-dispatch infeasibility proof, remove
  a Phase-4 assignment. The draft hard-cut transfer was therefore deleted
  before commit.
- The final implementation sets only `BranchPriority=1` on assignment binaries
  implicated by certified Stage-2 IIS patterns. It sets no `VarHintVal`, no
  constraint, no BEV/ICE preference and no objective term. The solver chooses
  both branch direction and final value; Phase-4 objective and feasible set are
  unchanged.
- Public evidence now includes pattern count and hashes, source candidate
  hashes, promoted variable count, priority and semantics in
  `solver_settings.json`, plus
  `phase4_iis_assignment_guidance_audit.json`. The audit explicitly records
  `objective_changed=false`, `feasible_set_changed=false`,
  `preferred_assignment_value=null` and `phase4_hard_cut_applied=false`.
- Focused tests cover extraction, rejection of uncertified failures, local vs
  shared IIS classification, the existing exact Phase-3 feedback cut, and an
  actual Gurobi counterexample proving that the same Stage-2 pattern remains
  feasible under Phase-4 guidance. Engine metadata and BFF propagation are
  covered. The repository regression passes `1422 passed in 130.60s`. A fresh
  clean-commit 264-trip diagnostic remains pending; no runtime or formal-gap
  improvement is claimed yet.

# 2026-08-14 - Exact ICE clone group-flow convexification

- Connected the certified one-day ICE clone group to the integrated Phase 4
  model. The largest certified group is selected only when `driver_cost=false`.
  Every label-specific assignment, connection, start/end, `used_vehicle` and
  vehicle-day variable in that group is relaxed to `[0,1]`, while binary
  aggregate assignment/connection/start/end variables and one integer path
  count retain the integral group path cover.
- The reformulation retains at most one continuous clone group. All remaining
  vehicle assignment variables are binary, so strict or penalized coverage
  leaves an integer residual incidence for the selected group. Aggregate node
  and boundary links then define an integral DAG path cover. The returned paths
  are decomposed deterministically onto the canonical clone IDs without
  changing selected trips, connections, path count, fuel cost, deadhead cost,
  vehicle-day cost or CO2.
- Per-label ICE fuel/refuelling states are omitted only for the selected group
  because the preceding longest-duty certificate proves every possible path
  fits within initial fuel minus reserve. `driver_cost=true`, multi-day,
  multi-fragment, unequal-domain and insufficient-fuel cases remain on the
  original integer formulation and record explicit application blockers.
- Complete Phase 4 MIP starts now populate the aggregate variables, and the
  fixed-dispatch recourse preflight fixes and verifies them along with the
  original dispatch variables. Public metadata records application status,
  blockers, relaxed binary count, aggregate integer count, net binary
  reduction, recovered path count and recovered vehicle IDs.
- Added exact small-oracle regressions comparing reformulated and original
  objectives and verifying that two parallel trips still recover two physical
  ICE duties. A verified Phase 3 seed also populates and certifies every new
  aggregate MIP-start variable. These tests prohibit fractional label sharing
  from understating the vehicle-day count. The focused integrated/research
  suite passes `70 passed`; the complete repository regression passes
  `1448 passed in 133.19s`. A clean matched 264-trip runtime comparison remains
  required before claiming a speedup or improved formal gap.

# 2026-08-14 - Literature-aligned exact-clone aggregation precondition

- Rechecked the local `先行文献` corpus instead of treating every published
  runtime as a like-for-like benchmark. No06 is the closest dispatch/charging
  comparison: Gurobi takes 617.6 seconds at 50 trips and does not obtain a
  feasible 200/418-trip solution within six hours, while its 418-trip 202.3
  second result is ALNS-SA and near-optimal. No16/No61/No63 mainly fix vehicle
  operation or assignment; No64 uses up to 80 Xeon cores and 314 GB RAM.
- Added an exact-clone ICE aggregation precondition audit before attempting a
  group-flow reformulation. It fails closed unless the horizon has one day and
  one fragment per vehicle, all clone assignment and transition domains match,
  and the chronological successor network is acyclic.
- For each candidate group, a longest-path dynamic program accounts for
  startup deadhead, every service trip, inter-trip deadhead and return-to-depot
  fuel. Per-vehicle fuel state/refuelling is certified redundant only when the
  maximum possible duty consumes no more than initial fuel minus reserve.
  Candidate count, blockers, proof path, fuel margin and the potential binary
  reduction are propagated through the MILP engine and BFF solver settings.
- The audit itself changes no feasible set. Commit `ad1cb9d` first exported it
  with `applied=false`; the subsequent convexification above consumes only a
  certified group and records whether the reformulation was actually applied.
- A read-only reconstruction of the saved 264-trip high-PV Prepared Input
  found one exact 25-ICE group. Its common domain has 264 assignments and
  11,310 successor arcs per vehicle. The maximum reachable 11-trip duty uses
  46.036430 L against 144.0 L of usable initial inventory, leaving a
  97.963570 L margin. The certified group-flow target would remove an
  estimated 290,448 binary variables. This is structural diagnostic evidence,
  not a solve-time result; no optimization was run from the dirty worktree.
- MIT self-review rejected the draft change that re-enabled Gurobi
  `Symmetry=2`: clean run `run_20260808_1300` had already shown 3,600 seconds,
  heavy root processing and a 100% gap. The automatic policy remains in force.
  Tests cover the successful proof, unequal domains, insufficient initial fuel,
  multi-day rejection, metadata propagation and the integrated search profile.
  At the precondition commit, the focused integrated suite passed `56 passed`
  and the complete repository regression passed `1445 passed in 131.05s`.
  The convexification test totals are recorded after its final full-suite run;
  a matched 264-trip runtime comparison is still required before any
  performance claim.

# 2026-08-14 - Shared-budget feasible run and cost-selected Phase 4 start

- Clean commit `ecdb0b1` was exercised through the same frontend/BFF Prepare
  and optimization endpoints with scenario
  `771d115b-75b0-49f7-a7f0-25f259a2cd21`, 264 trips, 60 vehicles, ten
  chargers, PV rated output 1000 kW, BESS 6000 kWh, flat grid price
  30 JPY/kWh, demand charge 0 JPY/kW, four Gurobi threads and a 600-second
  shared Phase 4 limit. The run was deliberately `research_run=false`,
  day-ahead-only and diagnostic.
- The repaired Phase 3 seed completed Stage 1, Stage 2 and independent physical
  validation. Seed wall time was 96.226 seconds; precheck plus seed was
  101.397 seconds. Integrated Phase 4 received 498.603 seconds and total solver
  wall time was 605.867 seconds, a 5.867-second finalization overrun within the
  declared 1% audit tolerance. HTTP submit-to-terminal time was 630.538
  seconds. This confirms that the earlier duplicated/nested time budgets are
  closed.
- The run was feasible without fallback, served 264/264 trips, applied the
  complete fixed-recourse MIP start and passed artifact completeness. It did
  not improve the 13-BEV/19-ICE seed (44/220 trips): the 780,112-variable,
  355,557-constraint integrated model spent 348.048 seconds in its canonical
  cost phase, explored one node, and stopped at 707,518.152 JPY with a
  640,000 JPY bound and 9.542957% gap. This is not a 1% result and is not used
  for research conclusions.
- Post-run data-flow validation found an independent P1 accounting mismatch.
  The MILP and `CostEvaluator` used `ProblemTrip.fuel_l_by_vehicle_type`, while
  the BFF assignment export silently returned to `distance_km * fuel_rate`.
  Physical fuel was 444.396649 L versus the solver's 442.492750 L, causing a
  285.584764 JPY fuel residual and 4.923281 kg-CO2 residual. Assignment export
  now reads the same per-powertrain trip quantity as the model and uses the
  fleet rate only when no explicit trip quantity exists. ICE rows no longer
  report BEV drive energy.
- To strengthen the feasible upper bound without restoring the inventory-wide
  Phase 3 composition sweep, the existing fixed-assignment neighborhood now
  tries one deterministic full retirement of all active ICE duties onto unused
  BEVs first. It accepts the candidate only after exact Stage 2 recourse,
  independent physical validation and canonical accounting, and short-circuits
  only when actual cost strictly improves. The unrestricted integrated Phase 4
  still searches every composition; no weather term, BEV lower bound, hard cut,
  fallback or post-solve repair is added. Frontend defaults bound this
  neighborhood to 60 seconds plus at most 60 seconds of route-band repartition,
  three seconds per fixed solve and 64 evaluations, all inside the same shared
  request budget.
- Focused regression: `69 passed in 4.00s`. Complete repository regression:
  `1452 passed in 133.69s`. A fresh clean-commit high-PV diagnostic is required
  to determine whether the direct candidate is feasible and improves the
  incumbent; no improvement is claimed from tests alone.

# 2026-08-14 - Validated BEV seed improvement and exact-clone representative search

- Clean commit `4f6a808` was rerun through fresh frontend/BFF Prepare with the
  same 264-trip high-PV diagnostic controls: 1000 kW PV, 6000 kWh BESS,
  30 JPY/kWh flat energy price, zero demand charge, four threads and one shared
  600-second Phase 4 budget. Solver wall time was 605.836 seconds and HTTP
  submit-to-terminal time was 631.299 seconds. This remained a
  `research_run=false`, day-ahead-only diagnostic.
- Canonical assignment export now reconciles. The final data-flow validation
  reported 62 `OK`, one `SKIPPED`, and zero failed checks; solver objective and
  accounting total matched. This fixes the earlier fuel/CO2 ledger defect but
  does not retroactively change the `ecdb0b1` artifacts.
- The fixed-assignment seed neighborhood found an independently validated
  one-duty ICE-to-unused-BEV replacement. The selected seed improved from
  13 BEVs/19 ICE buses and 44/220 trips to 14/18 and 60/204 trips. Canonical
  daily cost decreased by 5,146.266645 JPY to 702,371.885683 JPY. The direct
  all-active-ICE retirement candidate was infeasible.
- Integrated Phase 4 retained that seed but explored one node and stopped with
  an 8.880180% certified gap. It therefore proves neither 14/18 optimal nor a
  literature-comparable exact solution in hundreds of seconds.
- Post-run audit showed 64/64 candidate evaluations had been exhausted while
  repeatedly testing exact-clone unused BEV identifiers. Candidate generation
  now reuses `_ordered_identical_vehicle_groups`: one representative per exact
  unused-BEV symmetry class is evaluated for each active ICE duty, and a
  feasible edge is expanded to its clone IDs for maximum-cardinality matching.
  The symmetry signature includes powertrain, home depot, initial state,
  capacity/reserve, availability, fuel/energy parameters, fixed cost, maximum
  charge power and compatible charger IDs.
- Edge expansion alone cannot select a result. The maximum matching and every
  cumulative replacement still undergo exact fixed-assignment Stage 2,
  independent physical validation and canonical cost comparison. Public audit
  fields record exact-clone classes, representative solve count and inferred
  edges. The unrestricted integrated Phase 4 model is unchanged; no BEV lower
  bound, weather bias, hard feasibility cut or post-solve repair was added.
- Focused regression for the representative search passed `108 passed`;
  complete repository regression passed `1452 passed in 137.04s`. A fresh
  clean-commit runtime diagnostic remains required before making any
  performance claim.

# 2026-08-14 - Round-robin ICE-duty coverage and matching-validation reserve

- Clean commit `9db438a` was exercised through fresh frontend/BFF Prepare under
  the same 264-trip, 1000 kW PV, 6000 kWh BESS, flat 30 JPY/kWh, zero-demand,
  four-thread and shared-600-second high-PV diagnostic. Job
  `6430503c-cfdf-47a2-acb2-ce8ba031357c` completed physically valid at
  `output/2026-08-14/run_20260814_2243`; the portable evidence copy is
  `output/perf_clone_seed_9db438a_sunny_600s_20260814/sunny`.
- Solver wall time was 605.912 seconds, including a 5.912-second audited
  finalization overrun; HTTP submit-to-terminal time was 630.574 seconds. The
  integrated cost phase received about 302.60 seconds, explored one node and
  stopped at 702,371.885683 JPY against the 640,000 JPY certified bound. The
  8.880180% gap misses the declared 1% target.
- Assignment remained 14 BEVs/18 ICE buses and 60/204 trips. Physical status,
  artifact completeness and canonical total-cost reconciliation passed; no
  fallback or Rolling execution was used. This is a bounded diagnostic only.
- The clone audit correctly inferred zero edges. All 22 unused BEVs were
  singleton classes because their recorded initial SOC values differ (roughly
  21.9%--75.1%). Treating those vehicles as interchangeable would have changed
  fixed-assignment readiness/charging feasibility, so the exact signature was
  not weakened.
- The source-major loop spent 63 pairwise evaluations on only the first three
  of 19 active ICE duties. It found a maximum matching of size three, but the
  direct candidate plus those pairwise solves exhausted all 64 evaluations;
  the combined matching was never submitted to Stage 2.
- Pairwise candidate order is now round-robin over ICE duties with a
  deterministic per-duty rotation of depot-compatible target classes.
  Evaluation and wall-clock reserves are held for a full matching candidate
  and cumulative prefixes. Audit output exposes the strategy, completed
  rounds, evaluation limit, and both reserves.
- Fixed a second correctness bug in the cumulative fallback. Its first
  single-edge prefix was already in the duplicate hash set, so the old code
  returned `None` and never added that certified edge to the prefix. The new
  code seeds the prefix from the independently validated pairwise certificate,
  then re-solves every extension of size two or greater.
- Added a four-ICE/three-distinct-BEV regression proving broad source coverage,
  matching-slot reservation, rejection of an infeasible three-BEV combined
  candidate, and selection of a separately validated two-BEV cumulative
  candidate. Focused suite: `120 passed`; complete repository regression:
  `1453 passed in 134.99s` after the final reserve-boundary adjustment. Clean
  runtime evidence is pending.

# 2026-08-14 - Validated 30-BEV start and suffix-round restart

- Clean commit `fb72281` completed the same frontend/BFF high-PV diagnostic as
  job `8ef9eb6c-acb5-4455-840f-0ddf68b6c249`. Canonical artifacts are under
  `output/2026-08-14/run_20260814_2306`; the portable evidence copy is
  `output/perf_round_robin_seed_fb72281_sunny_600s_20260814/sunny`.
- HTTP submit-to-terminal time was 630.499 seconds and shared Phase 4 solver
  wall time was 606.003 seconds. All 264 trips were served, physical status was
  `VALID`, artifact completeness was `OK`, data-flow validation had 62 `OK`,
  one intentional `SKIPPED`, and zero failures, and canonical accounting
  reconciled. Rolling was not run and this was not a formal research run.
- Pairwise evaluation used the declared round-robin order: 43 single
  replacements across all 19 ICE duties, with 16 duties having at least one
  feasible edge. The maximum matching size increased from three to 16. Its
  complete fixed assignment was separately solved in 0.921 seconds and was
  feasible at 29 BEVs/3 ICE buses, cost 655,689.265969 JPY.
- A duty-suffix exchange then produced a validated 30-BEV/2-ICE start with
  232/32 trips and canonical cost 650,542.999324 JPY. This improves the
  `9db438a` result by 51,828.886359 JPY and the original 13/19 Phase 3 seed by
  56,975.153003 JPY. The integrated model retained that start, explored one
  node, and ended with a 640,000 JPY bound and 1.620646% certified gap. It is
  materially closer but still not a 1% optimality result.
- The fixed-duty audit ended after 62.012 seconds with only suffix round one
  complete. Candidate 46 was already a strict 30/2 improvement, but another 14
  round-one 30/2 candidates were evaluated while the second configured round
  never started. Route-band candidate generation used another 41.944 seconds
  but produced no fully validated repartition candidate.
- Suffix local search now records the first strict improvement, evaluates at
  most eight additional candidates for within-composition cost comparison,
  selects the best validated result in that bounded window, and restarts from
  the improved anchor when another suffix round is configured. The final round
  may use the remaining budget. Audit fields record per-round anchor cost,
  evaluation count, improving count, first-improvement index, restart index and
  restart count.
- A regression with two ICE duties, one active BEV and ten distinct unused
  BEVs proves that round one terminates at the bounded patience and round two
  reaches the all-BEV validated result. Focused suite: `121 passed`; complete
  repository regression: `1454 passed in 135.38s` after the final audit-count
  correction. Clean runtime evidence remains pending.

# 2026-08-14 - Validated 31-BEV start and funded final suffix round

- Clean commit `6755213` completed the same frontend/BFF high-PV diagnostic as
  job `ccb69bf7-4fd0-41c0-a28e-dadf3105e65a`. Canonical artifacts are under
  `output/2026-08-14/run_20260814_2328`; the portable evidence copy is
  `output/perf_suffix_restart_6755213_sunny_600s_20260814/sunny`.
- HTTP submit-to-terminal time was 631.631 seconds and shared Phase 4 solver
  wall time was 606.092 seconds. All 264 trips were served, physical status was
  `VALID`, artifact completeness was `OK`, data-flow validation had 62 `OK`,
  one intentional `SKIPPED`, and zero failures, and canonical accounting
  reconciled. Rolling was not run and this was not a formal research run.
- Suffix round one evaluated nine candidates and found five strict-cost
  improvements. After restarting from the best validated anchor, round two
  evaluated six and found three improvements. The selected start used 31 BEVs
  and one ICE bus, assigned 248/16 trips, and cost 648,332.208836 JPY. It is
  2,210.790488 JPY below the preceding 30/2 start and 59,185.943491 JPY below
  the original 13/19 Phase 3 seed.
- The remaining ICE duty belongs to vehicle
  `b46f03c3-cfd6-4398-ad6a-a3bbfac7528f`: 16 `渋23` trips, 149.109944 service
  kilometres and 32.566372 litres of service fuel. This is a measured
  constraint-search target, not evidence that one ICE duty is necessary.
- The integrated solve retained the 31/1 start. Its canonical ledger contains
  2,809.840081 JPY electricity, 5,382.743360 JPY fuel, 640,000 JPY vehicle-use
  cost and 139.625396 JPY CO2 cost. Against the 640,000 JPY bound, the certified
  gap is 1.285176%; the declared 1% optimality gate therefore remains blocked.
- The next bounded experiment keeps the overall 600-second Phase 4 budget and
  120-second seed-neighborhood allocation unchanged. Fixed-duty search receives
  75 seconds, route-band repartition receives 45 seconds, suffix search allows
  three rounds, and restart patience is eight evaluations in round one and
  four in round two. The 64-candidate cap remains. These settings affect MIP
  start search only and do not change the integrated model or acceptance gates.
- Focused policy and suffix-search regression: `113 passed in 4.00s`. Complete
  repository regression: `1454 passed in 141.89s`. Fresh clean-commit runtime
  evidence is pending.

# 2026-08-15 - `ac0115e` high/low-PV diagnostic pair and fail-fast control audit

- Clean commit `ac0115e40c392b9e99e461f1c7263a27d75c1571` was started through
  `run_app.py`/BFF and fresh frontend-equivalent Prepare. Both runs used the
  2025-08-05 WEEKDAY service day, Tsurumaki, 264 trips, 60 active vehicles,
  ten 90 kW chargers, complete 11,310 feasible successor arcs, four Gurobi
  threads, seed 42, shared Phase 4 limit 600 seconds and requested gap 1%.
  Energy controls were flat 30 JPY/kWh, demand charge 0, PV rated 1,000 kW,
  BESS 6,000 kWh / 900 kW, 3,000 -> 3,000 kWh, and used-vehicle-day cost
  20,000 JPY.
- High-PV job `319ffc0b-6dd9-42c1-9aa3-9e25336df087` used prepared input
  `prepared-41562dd0dfb91577-453c50ff177c277b-8fa1f41d`. Canonical artifacts
  are at `output/2026-08-14/run_20260814_2351`; the portable evidence copy is
  `output/perf_final_suffix_ac0115e_sunny_600s_20260814/sunny`. It used
  31 BEVs/1 ICE bus and assigned 248/16 trips. Canonical total cost was
  648,332.208836 JPY: electricity 2,809.840081, fuel 5,382.743360,
  vehicle-day 640,000 and CO2 accounting 139.625396 JPY. PV generation was
  6,056.25 kWh and operational CO2 was 139.625396 kg. HTTP wall time was
  631.745774 seconds; certified gap was 1.285176%.
- Its third suffix round evaluated five 32-BEV/0-ICE candidates and found none
  feasible. The direct full ICE-retirement candidate was also infeasible.
  IIS samples identify charge-availability while in service/not at depot,
  charge power and SOC transition constraints. This is measured binding
  evidence, not a proof that 31 BEVs are optimal or that one ICE duty is
  structurally necessary.
- An initial low-PV attempt exposed a frontend-control bug: the saved rain
  scenario carried `vehicle_usage_cost_jpy_per_used_bus=0` with provisional
  semantics while the sunny scenario carried 20,000 JPY with fixed-day
  semantics. That run is preserved only as a diagnostic and is excluded from
  every pair comparison. Previously, the runner discovered the effective
  control mismatch only after paying for both solver runs.
- The corrected low-PV job `fc3103df-b04f-42e4-b92f-38c0fbfde61f` explicitly
  sent the shared 20,000 JPY value in Prepare and used prepared input
  `prepared-7d5cb8da296d5499-f1e18f252e336f1f-8fa1f41d`. Canonical artifacts
  are at `output/2026-08-15/run_20260815_0019`; the portable evidence copy is
  `output/perf_final_suffix_ac0115e_rain_vehicle_cost_20000_600s_20260815/rain`.
  It used 14 BEVs/18 ICE buses for 60/204 trips. Cost was 702,184.658838 JPY:
  effectively zero grid electricity, 61,130.806525 JPY fuel, 640,000 JPY
  vehicle-day and 1,053.852313 JPY CO2 accounting. PV generation was
  996.2 kWh and operational CO2 was 1,053.852313 kg. HTTP wall time was
  630.878637 seconds; independently certified gap was 1.094658%.
- Both cases served 264/264 trips with physical status `VALID`, accounting
  equality, artifact completeness and data-flow validation. Both were
  `research_run=false`, both missed the requested 1% certificate, and neither
  ran the 24-hour Rolling chain. The observed +17 used BEVs and +188 BEV trips
  in high PV is therefore a descriptive day-ahead incumbent comparison, not a
  formal causal or global-optimality result.
- `run_frontend_controlled_pv_pair.py` now fetches both editor bootstraps before
  Prepare, records `vehicle_usage_cost_control_preflight.json`, rejects saved
  cross-scenario cost differences before any solver work, and supports one
  explicit shared `--vehicle-usage-cost-yen-per-used-bus` override. Prepare
  carries that value explicitly, preventing a scenario-save regression from
  silently changing the controlled pair.
- Added `build_day_ahead_diagnostic_pair_report.py`. It accepts only matching
  clean-SHA, physically valid, accounting-reconciled day-ahead cases with an
  accepted artifact-completeness gate and no failed data-flow checks; rejects
  non-PV control differences; and emits one immutable diagnostic snapshot,
  comparison/cost/energy/solver/hourly CSVs, a technical Markdown report, and
  seven figures in PNG and SVG. Cost reconciliation reads every component from
  `summary.json::canonical_cost_components_jpy`; non-primary components are
  retained as `other_cost_jpy` instead of being silently omitted. The generated
  five-sheet `results.xlsx`
  separates summary, case results, hourly energy, controls and provenance;
  formulas were scanned with zero errors and every sheet was rendered for
  visual QA. Current bundle:
  `output/progress_report_ac0115e_day_ahead_pair_20260815/`.
- Focused pair-runner, manifest and diagnostic-report regression:
  `60 passed in 10.80s`. Final full-suite validation:
  `1464 passed in 143.73s`; changed Python entrypoints also passed `py_compile`.

# 2026-08-15 - Clean `8066330` formal low-PV Phase-0 reference run

- A fresh frontend-equivalent formal run was executed from clean commit
  `80663305863a31cee1c90c5ffea6ce88eaab16b3` using scenario
  `b23fd26c-1233-4c73-bb9e-bdb8b1584760`, service date 2025-08-05, low-PV
  source date 2025-08-10, 264 trips, 60 active vehicles, ten 90 kW chargers,
  PV 1,000 kW, BESS 6,000 kWh / 900 kW with 3,000 -> 3,000 kWh SOC, flat
  30 JPY/kWh energy price, zero demand charge, and 20,000 JPY per used
  vehicle-day. The formal Phase-4 request used four Gurobi threads, seed 42,
  a 3,600-second shared wall-clock budget and a predeclared 1% gap.
- Job `61ffd673-932b-4d72-bd73-dfd56f2ff778` completed through
  Prepare -> `/run-optimization` -> hourly Rolling. The canonical run is
  `output/2026-08-15/run_20260815_0143`; the immutable evidence copy is
  `output/formal_phase0_reference_8066330_low_pv/reference_low_pv`.
  End-to-end wall time was 3,804.389 seconds. Shared Phase-4 wall time was
  3,606.030 seconds; the integrated solve received 3,042.031 seconds after
  precheck and verified-start work, and the recorded solve time was
  2,885.321 seconds. A feasible warm start existed at time zero.
- The accepted assignment used 14 BEVs and 18 ICE buses for 60 and 204 trips,
  respectively. All 264 trips were served. Independent physical validation
  was `VALID`; the 24/24 fixed-assignment Rolling chain was accepted; executed
  accounting was eligible; final cost reconciliation was `OK`; and artifact
  completeness verified 240/240 required files. Executed-day accounting was
  702,184.658838 JPY, including 640,000 JPY vehicle-day cost,
  61,130.806525 JPY fuel inventory valuation and 1,053.852313 JPY CO2 cost.
- Gurobi terminated at the time limit. Its raw gap was 8.855884%; the
  independent certified gap was 1.094658%, still 0.094658 percentage points
  above the declared 1% target. The formal run is therefore a physically
  valid feasible candidate but not an optimality result. The Phase-0 ledger
  fails only `declared_mip_gap_target_met`; no tolerance or release gate was
  weakened.
- Local literature evidence was rechecked against the source PDFs. In the
  closest integrated-dispatch comparison, No06 reports Gurobi at 617.6
  seconds for 50 trips but no feasible Gurobi solution for 200 or 418 trips
  within six hours; its 418-trip 202.3-second result is ALNS-SA. Fixed-dispatch
  charging/PV/ESS studies cannot be treated as equal-scope exact-MILP timing
  evidence. Future performance reporting will separate feasible-candidate
  time, best-incumbent time, gap-certification time and end-to-end wall time.

# 2026-08-15 - Formal `79e61ae` pair timing and v5 control-gate correction

- Ran the controlled high/low-PV pair through fresh Prepare and the normal
  frontend/BFF formal route from clean commit
  `79e61ae8cd43acb350c452e7f9eed68bf79507c1`. Frozen and ending SHAs matched
  and the worktree stayed clean. Shared controls were 2025-08-05 WEEKDAY,
  Tsurumaki, 264 trips, 60 vehicles, ten 90 kW chargers, flat 30 JPY/kWh,
  zero demand charge, PV rating 1,000 kW, BESS 6,000 kWh / 900 kW with
  3,000 -> 3,000 kWh, four threads, seed 42, 3,600 seconds and 1% gap.
- High-PV job `3eab15a6-7b19-49e0-8b39-bdee64fa67ea` is under
  `output/2026-08-15/run_20260815_0330`. Phase 4 wall time was
  3,606.883660 seconds; the feasible assignment used 28 BEVs/4 ICE buses and
  202/62 trips. Executed-day cost was 659,706.858143 JPY and the certified gap
  was 2.987214%, so the declared 1% gate failed.
- Low-PV job `835dbdb0-0a2f-44eb-bea2-4ebd6b1890e3` is under
  `output/2026-08-15/run_20260815_0434`. Phase 4 wall time was 794.541743
  seconds; the assignment used 15 BEVs/17 ICE buses and 75/189 trips.
  Executed-day cost was 697,433.686483 JPY and the independent certified gap
  was 0.420907%, meeting the declared 1% target.
- Both cases served 264/264 trips, passed independent physical checks,
  accepted all 24 fixed-assignment Rolling steps, reconciled executed-day
  accounting and generated the complete report set. The pair remains
  `BLOCKED` because high PV missed its gap certificate. The progress-only
  bundle contains seven PNG/SVG figure pairs and six CSV tables at
  `output/formal_pair_20260815_seed_restart_79e61ae_flat30_pv1000_bess6000_gap01_r1`.
- Found a separate P1 reporting defect in
  `scripts/run_frontend_controlled_pv_pair.py::_phase4_seed_controls_match`.
  It required the legacy Phase-3 candidate sort order and a positive initial
  candidate budget even though v5 deliberately emits an empty order and zero
  initial budget. The gate now accepts either the legacy contract or a fully
  consistent `phase4_seed_unused_bev_activation_neighborhood_v5` audit. The
  v5 path verifies requested/emitted wall limits, per-solve limit, candidate
  caps/counts, local-search reserve, termination evidence, and that neither a
  global-optimality claim nor weather bias was applied.
- Added regression coverage for a valid current v5 payload and tampered count
  and weather-bias failures. The focused pair-runner suite passed 40 tests.
  The final complete repository regression passed 1,474 tests in 154.74
  seconds; changed Python entrypoints also passed `py_compile` and
  `git diff --check`.
  Both preserved `79e61ae` `solver_settings.json` files pass the corrected
  helper when replayed read-only. They are not rewritten or relabelled because
  this code fix changes the SHA; a fresh formal run is still required.

# 2026-08-15 - Phase 4 seed v6 wall-time reserve

- Audited the high-PV `79e61ae` neighborhood rather than attributing the
  28-BEV/4-ICE incumbent only to Gurobi. The v5 audit evaluated 53 candidates:
  one direct retirement, 27 pairwise replacements, one combined matching and
  24 sequential whole-duty candidates. It generated zero suffix-exchange,
  powertrain-swap or identity-exchange candidates. The fixed-duty search used
  its wall window before those enabled neighborhoods were reached.
- The root cause was two-dimensional starvation. The code reserved 16
  evaluation slots for local path search, but had no corresponding wall-time
  reserve. A later sequential-search calculation then replaced that 16-slot
  reserve with four slots. Count-only regression tests therefore passed while
  the production wall-clock path still skipped the search that previously
  produced 30/2 and 31/1 high-PV starts.
- `phase4_seed_unused_bev_activation_neighborhood_v6` keeps the same total
  75-second fixed-duty and 45-second route-band budgets. Under current formal
  controls it reserves 30 seconds and 16 candidate evaluations for suffix and
  powertrain path changes. Pairwise search additionally preserves its matching
  validation allowance. Sequential whole-duty activation receives at least
  one evaluation but cannot consume the post-sequential reserve.
- Added a deterministic fake-clock regression with ten distinct unused BEVs.
  Whole-duty replacements consume the early budget and remain infeasible;
  v6 must still start suffix exchange within the reserved tail and select the
  independently feasible lower-cost all-BEV candidate. Formal runner checks
  accept v5 for preserved artifacts and require the new wall-reserve evidence
  for v6, including requested/remaining wall consistency.
- This is feasible-upper-bound generation only. It does not alter the Phase 4
  integrated feasible set, canonical accounting, lower bound, objective or
  acceptance gap. A fresh frontend-equivalent run is required before any
  performance or solution-quality claim.
- Focused Phase 4 seed, formal-runner and research-contract regression passed
  126 tests. The complete repository suite passed 1,474 tests in 153.79
  seconds; changed entrypoints passed `py_compile` and `git diff --check`.
