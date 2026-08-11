# master-course

## 2026-08-10 all-BEV fuel-artifact correction

- Clean SHA `6853edae956c71c3c28ec285660a0f0b7c788e69` completed both
  day-ahead and 24/24 Rolling calculations for the fresh 1% controlled pair.
  The integrated final compositions are `32 BEV / 0 ICE` (sunny, 264 BEV
  trips, `644,741.923030 JPY`, certified gap `0.735476%`) and
  `21 BEV / 11 ICE` (rain, 91 BEV trips, `698,419.690050 JPY`, certified gap
  `0.399008%`). This confirms a large PV-driven response without a weather
  preference term or BEV quota.
- The sunny frontend job nevertheless failed at the last artifact gate because
  a valid all-BEV day has zero fuel rows and three declared fuel CSVs were
  emitted as zero-byte files. Zero fuel is valid data; a zero-byte file is not
  self-describing evidence. Canonical fuel ledger, fuel timeseries and fuel
  summary exports now retain their CSV headers when the relation is empty.
- The failed pair remains `BLOCKED` and is not formal pair evidence. A fresh
  clean-commit rerun is required because the reporting contract changed; the
  solver, cost equations, feasible region and sunny/rain decisions are
  unchanged by this export-only correction.

## 2026-08-10 bounded Phase-4 completion path (fresh formal run pending)

- Phase 4 now evaluates a bounded, weather-neutral fixed-assignment
  neighborhood after its Phase-3 seed.  It tries unused-BEV activation,
  BEV/ICE whole-duty swaps and BEV-identity exchanges; every candidate must
  pass exact Stage 2, independent physical validation and canonical
  accounting.  Only a strict actual-cost improvement becomes the integrated
  MIP start.  The largest feasible BEV count is reported separately and is
  never presented as an optimum or an infeasibility certificate.
- Replaying the last clean pair's plans through this code is diagnostic only,
  but it identifies the missing sunny incumbent: the unchanged 32 duty paths
  are feasible as `32 BEV / 0 ICE` at `644,741.923030 JPY`, versus
  `666,164.082366 JPY` for the old `27/5` plan.  In rain, 512 bounded candidates
  did not improve the `21/11`, `698,419.690050 JPY` incumbent; `30/2` was the
  highest observed feasible composition, not a proof that `31/1` or `32/0` is
  impossible.
- The independent analytical energy/fuel certificate now takes the stronger
  of the old per-trip floor and a continuous powertrain path/source-flow LP.
  The LP includes optimistic service, startup, connection and return energy,
  and constrains free PV/BESS/SOC credit to energy selected on electric paths.
  It still relaxes vehicle identity, path count, time, chargers and depot
  coupling, so it is a lower bound rather than a dispatch estimate.  Its exact
  coefficient set is SHA-256 fingerprinted in the result audit.
- On the prior pair inputs, the new diagnostic total lower bounds are
  `640,000.000000 JPY` sunny and `695,632.938124 JPY` rain.  Combined with the
  candidate costs above, the implied certified gaps are about `0.7355%` and
  `0.3990%`.  When a verified same-model start already meets the predeclared
  gap, Phase 4 sets Gurobi `BestObjStop` to accept that start without spending
  the remaining branch-and-bound budget; the feasible set and objective are
  unchanged.
- Endpoint away-from-depot implications already dominated by their trip
  activity row are omitted.  The measured full model retains all 776,752
  variables while reducing rows from 1,929,173 to 1,587,351.  This is an LP-
  dominance reduction, not the previously rejected weak aggregation.
- The controlled frontend runner keeps its historical 0.1% default and now
  accepts `--actual-cost-mip-gap 0.01` for a separately predeclared 1%
  release-candidate.  The historical 0.1% pair remains `BLOCKED`; none of the
  diagnostics above are formal new-code evidence.  A clean commit, fresh
  Prepare, both day-ahead runs, 24/24 Rolling, physical/accounting/provenance
  checks and pair-manifest validation are still required.

## 2026-08-10 final-composition clarity and Phase-4 search diagnostics

- The latest completed controlled pair does **not** use the same fleet mix in
  both weather cases.  Its final integrated incumbents are `27 BEV / 5 ICE`
  (sunny, 183 BEV trips) and `21 / 11` (rain, 91 BEV trips).  The repeatedly
  displayed `13 / 19` value is the Phase-3 Stage-1 primary seed candidate, not
  the selected Stage-2 seed and not the final Phase-4 solution.
- Result summaries now publish `final_used_powertrain_composition` separately
  from `stage1_primary_candidate_used_powertrain_composition`.  The Tk result
  labels use “final solution” and explicitly mark the Stage-1 value as not the
  final solution, preventing seed-search telemetry from being read as the
  optimized fleet composition.
- Sunny PV quantity is not the current boundary: the completed sunny incumbent
  imports zero grid electricity and curtails 3,606.64 kWh.  Above 27 BEVs, the
  unresolved issue is whether another BEV can satisfy its chronological duty,
  charging-window, charger and terminal-SOC constraints while retaining the
  32-bus fleet.  Failure of the two tested `28/4` assignments is not proof that
  every `28/4` assignment is infeasible.
- Stage-2 diagnostics now simulate each BEV path in chronological order and
  separate departure, minimum-SOC and terminal-SOC shortages.  A vehicle-local
  IIS cuts only that exact vehicle assignment pattern; an IIS containing a
  shared charger/site constraint or a variable bound conservatively cuts the
  full assignment.  This avoids both repeating a known-bad path and incorrectly
  excluding untested supersets.
- A first attempt to aggregate activity-blocking implications was rejected
  after the clean-SHA sunny run reached 93.1% of the Windows commit limit
  (85.8/92.1 GB).  Although integer-equivalent, that aggregate has a weaker LP
  relaxation than the individual `activity <= 1 - blocker` rows.  The strong
  individual formulation is restored; the aborted run is diagnostic only.
  Integrated runs still spill the MIP node tree after 0.5 GB to an OS
  temporary directory as a branch-and-bound memory guard.  A separate attempt
  to disable degenerate root moves was also rejected and is not retained.
- A second clean-SHA sunny diagnostic with the restored strong formulation
  reproduced the same `32/0` through `28/4` failed-candidate frontier, but the
  integrated fixed-dispatch recourse root then drove Windows commit to 96.4%.
  This localizes the memory spike before branch-tree growth, where node-file
  spill cannot help.  Both the recourse preflight and final integrated search
  now use dual simplex (`Method=1`, `NodeMethod=1`) to avoid automatic
  concurrent root-method model copies and a 32 GB `SoftMemLimit` to terminate
  gracefully with an auditable `memory_limit` status if the exact solve still
  exceeds its budget.  These controls change search mechanics only; they do
  not alter the feasible set, objective, tariff, PV curve or weather response.
- Formal release remains `BLOCKED` until a fresh clean-commit pair closes the
  requested 0.1% certified gaps and passes every physical, rolling, provenance
  and accounting gate.  These implementation changes do not relabel the
  existing SHA-`99a2035` artifacts.  The pre-run complete repository suite
  passed (`1248 passed in 65.46s`).  After restoring the strong formulation,
  the complete suite passed (`1247 passed in 55.79s`); after adding the exact
  root-memory controls it passes again (`1247 passed in 58.22s`).  A new clean
  commit is still required before another formal run.

## 2026-08-10 controlled pair after feasibility-witness cutoff

- Clean frozen SHA `99a2035694fd90fccf42fe8222a4f1d3b344e83e` completed
  fresh Prepare, Phase 4 actual-cost optimization and 24/24 Rolling for both
  cases at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_witness_99a2035_gap001`.
  The bundle and ZIP preserve PV 1,000 kW, BESS 6,000 kWh, flat grid energy
  30 JPY/kWh, demand charge 0 JPY/kW and identical non-PV control hash
  `ebb5ddf8bf094c15f48c45e402b6825acb8b910235d936e940fd7a41e603c292`.
- Sunny uses `27 BEV / 5 ICE` and 183 / 81 trips at 666,164.082366 JPY;
  rain uses `21 / 11` and 91 / 173 trips at 698,419.690050 JPY. Both serve
  264/264, pass physical/SOC/accounting checks and 24/24 Rolling. The pair
  manifest accepts the controlled PV sensitivity.
- The cutoff works as intended: exact 25, 26 and 27-BEV targets now return
  their first witness in about 3.6 seconds. Exact `28/4` receives 47.8 seconds
  instead of 11.7, but finds no Stage-1 incumbent; its two complete
  constructive assignments are Stage-2 infeasible. This remains an unresolved
  composition boundary, not a proof that all `28/4` assignments are infeasible.
- Formal release remains `BLOCKED`: sunny certified gap is 3.927573% and rain
  is 2.387096%, both above the requested 0.1% (raw Gurobi gaps are 100%).
- Post-run audit found two evidence-output defects. The pair research table
  read only the Phase-3 certified-gap field, leaving the Phase-4 gap row blank;
  and Phase-4 internal Phase-3 candidates did not receive the diagnostics root,
  so failed `28/4` candidates exported no IIS/path files. The reporting path
  now prefers `certified_mip_gap_ratio`, and Phase 4 now enables candidate
  diagnostics without enabling recursive Phase-3 feedback. These post-run
  changes pass 35 focused regressions and the complete suite (`1242 passed in
  64.24s`), but do not relabel the SHA-99a2035 bundle as new-code evidence.

## 2026-08-09 exact-composition feasibility-witness cutoff

- The current controlled pair already shows the intended economic response:
  sunny uses `27 BEV / 5 ICE` and 183 BEV trips, while rain uses `21 / 11`
  and 91 BEV trips. The remaining sunny boundary is exact `28/4`, not a
  frozen-weather failure.
- Exact used-powertrain targets exist to recover one Stage-1-feasible witness
  for exact Stage 2 evaluation. They previously kept optimizing after finding
  that witness, so the easy `14/18` through `27/5` targets each consumed their
  full share and left only 11.696 seconds for the unresolved `28/4` target.
- Exact-composition searches now use Gurobi `SolutionLimit=1`. A found witness
  is passed to Stage 2 immediately and unused shared time remains available to
  harder adjacent targets. Targets with no incumbent continue until their
  allocated time limit or a genuine `INFEASIBLE` result, so IIS-backed
  composition certificates are not weakened.
- This is a weather-neutral search policy. It adds no BEV minimum, trip quota,
  sunny coefficient or objective bias; Stage 2 canonical actual cost still
  selects the final candidate. Focused regressions pass (`54`) and the full
  suite passes (`1240 passed in 56.27s`). Fresh clean-commit pair evidence is
  required before this search change is credited with a new result.

## 2026-08-09 controlled pair after adjacent continuation

- Clean SHA `32e3509cacd6309675bef2e850405e07483b24fb` completed fresh
  frontend Prepare, Phase 4 and 24/24 Rolling for both cases at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_adjacent_32e3509_gap001`.
  All 264 trips, physical checks, terminal SOC, accounting reconciliation and
  non-PV pair controls pass.
- Sunny selects `27 BEV / 5 ICE` and 183 BEV trips at 666,164.082366 JPY;
  rain selects `21 / 11` and 91 BEV trips at 698,419.690050 JPY. The controlled
  pair manifest accepts the PV sensitivity: weather response is no longer
  frozen to one used-powertrain composition.
- Formal release remains `BLOCKED`. The independent certified gaps are
  3.927573% sunny and 2.387096% rain, both above the requested 0.1%; raw Gurobi
  gaps remain 100% with a zero raw bound.
- Post-run audit found that the pair runner labeled the raw integrated gap as
  `certified_gap`. The formal gate now reads `certified_mip_gap_ratio` while
  preserving raw-gap telemetry separately. This correction does not change
  the current pair's BLOCKED outcome and requires fresh evidence for its new
  commit.
- Focused regressions pass (`81`) and the complete suite passes (`1240 passed
  in 64.68s`).

## 2026-08-09 adjacent feasible-continuation seed search

- A fresh sunny frontend run from clean commit `beb13e3` exposed a regression
  in the exact-composition search order. Optimistic-cost ordering tried
  `32/0`, `31/1`, `30/2` and `29/3` first, spent about 60 solver seconds on
  each without an incumbent, then left only 10.156 seconds for the promising
  `28/4` target. The run therefore fell back to `27/5`; this is search-budget
  starvation, not evidence that `28/4` is physically or economically worse.
- Exact fleet mixes now walk outward from the primary feasible solution in
  symmetric distance order. Each BEV-increasing and BEV-decreasing direction
  reuses its last feasible adjacent composition as a MIP start, and the
  remaining enumeration time is shared equally across remaining targets.
  This ordering contains no weather or BEV preference.
- Optimistic constructive cost remains exported as diagnostic evidence but no
  longer orders exact target solves. Stage 2 still ranks every recovered
  candidate by canonical actual cost including diesel, grid, PV/BESS recourse
  and vehicle-day cost. The unrestricted integrated MILP remains the only
  global proof model.
- The interrupted `beb13e3` pair is diagnostic only; its rain case was stopped
  after the sunny defect was established. A clean commit, fresh Prepare and
  both formal runs are required before the release status can change from
  `BLOCKED`.
- Focused regressions pass (`80`) and the complete repository suite passes
  (`1239 passed in 59.56s`).

## 2026-08-09 verified-start cutoff and bound-search correction

- The clean frozen `96f17e10175d614d29f45ee79df95cf70ff4e6eb` pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_constructive_96f17e1_gap001`
  completed fresh frontend Prepare, Phase 4 and 24/24 Rolling for sunny and
  rain. The pair control hash matches, only the PV hash differs, 264/264 trips
  are served in both cases, physical/accounting gates pass and pair manifest
  v2 accepts the controlled PV sensitivity. Formal readiness is still
  `BLOCKED`.
- The repaired candidate path evaluated 29 Stage 1/Stage 2 candidates per
  case. Complete 32-, 31-, 30-, 29- and 28-BEV dispatch starts reached exact
  Stage 2 instead of being discarded at the short Stage 1 time limit. Those
  particular high-BEV duties were Stage 2 infeasible; this is candidate-level
  evidence, not a proof that every assignment at the same composition is
  infeasible. Sunny selected 27 BEVs / 5 ICE buses and rain selected 21 / 11.
- Sunny cost is 666,164.082366 JPY with a 3.927573% certified gap; rain cost is
  698,419.690050 JPY with a 2.387096% certified gap. Both Gurobi raw gaps remain
  100% because the 776,752-variable / 1,929,173-constraint integrated model
  spends the 3,600-second search at the root node. These are validated feasible
  candidates, not certified global optima.
- The current correction feeds the independently feasible fixed-recourse seed
  objective back to the same canonical-cost-primary integrated model as an
  explicit upper bound. It
  also derives an integer-valid used-vehicle-day cap when every objective term
  is nonnegative. Both constraints preserve the seed and every improving
  solution; they add no BEV minimum or weather preference. A verified seed now
  uses a weather-neutral lower-bound search profile (`MIPFocus=3`,
  `Heuristics=0.01`, conservative presolve) instead of spending half of the
  search effort on incumbent heuristics after feasibility is already proven.
  Maximum-EV lexicographic and partial-service multiobjective cases are
  explicitly excluded and retain their separately declared policy contracts.
  A vehicle-day cap is also disabled when that cost component is disabled.
- Focused regressions pass (`41 passed`) and the complete repository suite
  passes (`1237 passed in 54.15s`). A clean commit and fresh pair are still
  required. The `96f17e1` outputs remain the authoritative completed pair for
  the previous solver and are not relabelled as evidence for this correction.

## 2026-08-09 complete composition-candidate rescue and gap certification

- Exact-composition search no longer discards a complete dispatch merely
  because its short target MILP ends without an incumbent. When a MIP start
  contains exact 264-trip coverage, unique predecessor/successor paths, valid
  start/end fragments and the requested used-powertrain count, it is retained
  as a **constructive dispatch candidate** only after the target solve returns
  no incumbent. It is not a Stage 1 solution or energy-feasibility claim.
- Every constructive candidate must still pass the unchanged Stage 2 SOC,
  charger, PV/BESS/grid recourse, canonical cost evaluation and independent
  physical checker before it can enter final cost selection. No BEV minimum,
  weather bias, fallback, post-solve repair, timetable rewrite or successor
  pruning is added.
- Candidate ordering now reports
  `candidate_priority_cost_ascending_then_candidate_hash`. Solver candidates
  use the weather-aware Stage 1 relaxed objective. Constructive candidates use
  a separately labelled dispatch-only lower bound when the nonnegative-term
  certificate is valid; Stage 2 actual canonical cost remains authoritative.
- Phase 4 now exports Gurobi raw bound/gap and an independent certified
  bound/gap separately. The certified bound is the maximum of Gurobi's bound
  and the existing integer-valid analytical objective floor. Raw telemetry is
  never overwritten. The formal gap gate can use the certified gap only when
  that floor is eligible and its provenance is recorded.
- The complete repository suite passed (`1233 passed in 54.29s`) before the
  `96f17e1` pair above. That pair proves the candidate-rescue behavior but did
  not meet the requested 0.1% certified gap.

## 2026-08-09 current PV-1000 controlled-pair result

- Clean frozen commit `93d122e1fc929d4833f2997560fa16cf7523e96d`
  completed fresh frontend Prepare, day-ahead Phase 4, and 24/24 Rolling for
  both cases at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_pairhash_93d122e_gap001`.
  Both cases served 264/264 trips, used the same 60-vehicle/10-charger scope,
  flat 30 JPY/kWh energy, zero demand charge, a 1,000 kW PV rating, and a
  6,000 kWh BESS returning from 3,000 to 3,000 kWh. Only the separately hashed
  actual-day PV curve differed.
- Sunny generated 6,056.25 kWh and used 27 BEVs / 5 ICE buses for 183 / 81
  trips. Rain generated 996.2 kWh and used 21 / 11 for 91 / 173 trips. The
  controlled comparison is accepted and demonstrates a weather response
  without a hidden BEV or weather bias.
- Both integrated solves stopped at the 3,600-second limit with a 100% raw
  gap. They are physically valid, accounting-reconciled incumbents, not
  certified global optima. Formal research release remains `BLOCKED`.
- Pair-manifest schema v2 keeps these two statements separate:
  `accepted_for_controlled_pv_sensitivity_comparison` may be true for matched,
  physically valid incumbents, while `formal_research_submission_ready` is
  fail-closed unless both requested MIP-gap certificates are present.

## 2026-08-09 Phase 4 seed wall-budget correction

- Clean commit `bf3fc2907fe852b39aa303272287e2133bd628a9` was freshly
  prepared for the flat-30/no-demand/PV-1000/BESS-6000 pair. The sunny run at
  `output/2026-08-09/run_20260809_0608` is **DIAGNOSTIC ONLY**: Stage 1
  recovered feasible assignment incumbents from 7 through 27 used BEVs, but
  all 21 Stage 2 candidate rows were `not_run_feedback_budget_reserved`.
  Phase 4 consequently received no verified physical seed, found no incumbent
  in 3,600 seconds, served 0/264 trips and correctly blocked Rolling/release.
- The 600-second seed contract had been used simultaneously as a Gurobi solver
  budget and as a wall deadline. Rebuilding every exact-composition model is
  Python-side work excluded from Gurobi `TimeLimit`; on the full inventory it
  consumed the wall remainder reserved for Stage 2. The solver limits remain
  480 seconds for Stage 1 and 120 seconds for Stage 2. A separately reported,
  deterministic model-build allowance of 10 seconds per requested reachable
  alternative (maximum 600 seconds) now expands only the shared wall envelope.
- Stage 2 evaluates the unchanged candidate set in ascending weather-aware
  Stage 1 relaxed objective, with candidate hash as the deterministic tie
  break. This is not a BEV/weather policy preference: Stage 2 physical
  canonical cost remains the selection authority. The order and initial Stage
  2 budget are exported for audit, and the formal pair runner rejects missing
  or inconsistent solver/wall-budget records.
- The automatically started rain diagnostic was stopped after the deterministic
  seed-handoff defect was confirmed; code was not changed while either run was
  active. A fresh clean-commit pair is required after tests and commit.
- Focused Gurobi/Phase 4/BFF/runner regressions and the full repository suite
  pass (`1230 passed`). This validates code behavior only; it is not a formal
  pair result.

## 2026-08-09 Phase 4 composition-search regression diagnosis

- Clean commit `14bbcfa1ba97889674e113eae44bfa3ec71577e0` completed the
  fresh-Prepare controlled pair at
  `output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_proof_14bbcfa_gap001`.
  Both cases served 264/264, passed independent physical validation and 24/24
  Rolling, and reconciled objective to executed accounting exactly. The pair
  is nevertheless `BLOCKED`: both integrated MILPs stopped after one node with
  a 100% raw gap and best bound zero.
- Sunny and rain both returned the same 16-BEV / 16-ICE, 58 / 206-trip
  incumbent at 704,401.909629 JPY. This is not evidence that the composition is
  optimal. Sunny generated 6,056.25 kWh and curtailed about 5,344.07 kWh. Rain
  still generated 996.2 kWh, enough to supply the selected assignment's
  650.493 kWh bus charging through PV/BESS with zero grid purchase. The weather
  difference therefore becomes economic only in the high-BEV compositions
  that this run failed to evaluate.
- The exact-composition seed divided 120 seconds across the complete inventory
  span, leaving only about 3.4--3.8 seconds per target. It found physically
  feasible 7--16 BEV compositions, while every 17--32 target ended unresolved
  at the time limit. Exact activation-prefix symmetry had coupled identifier
  order to duty replacement and forced economically poor duties into the BEV
  starts. The correction chooses duties by energy/cost suitability, then
  bijectively permutes only exact-identical vehicle IDs onto the prefix. This
  preserves the feasible set and all objective coefficients.
- The full model has about 776,752 variables and 1,929,173 constraints. The
  proof-focused `MIPFocus=3`, `Heuristics=0.01` profile neither improved the
  zero root bound nor repaired the weak seed. Phase 4 therefore returns to the
  weather-neutral incumbent-improvement profile (`MIPFocus=1`,
  `Heuristics=0.5`) while retaining the analytical lower-bound audit.
- A strict path-cover vehicle-day floor and an optimistic weather-energy/fuel
  floor are combined into an integer-valid objective lower-bound constraint.
  It is disabled fail-closed for partial service, non-total-cost objectives,
  negative objective terms, or a non-actual-cost model.
- Activation-prefix constraints remove only exact identifier-permutation
  symmetry among vehicles whose complete solver-relevant records are equal.
  Prefix normalization is an ID permutation after duty choice; it must never
  decide which duty is converted between powertrains.
- Interactive frontend runs use a fixed four Gurobi threads on this host. An
  eight-thread clean diagnostic exhausted the practical virtual-memory margin
  (about 58 GB private allocation with less than 1 GB remaining), so it was
  stopped and is not research evidence. The applied value is persisted and
  must match between controlled cases. These
  changes do not alter PV, tariff, fleet, timetable, SOC, charger, or
  accounting semantics and do not add a BEV/weather preference.
- The formal pair runner now requests and audits the same four-thread runtime
  contract, and Phase 4 carries its Phase 3 candidate/recourse evidence into
  the same-assignment audit instead of treating integrated output as if no seed
  alternatives existed.
- A fresh Prepare and clean frozen-commit sunny/rain rerun are still required.
  Formal release stays `BLOCKED` unless each run meets the requested 0.1% gap
  and all physical, Rolling, provenance, and accounting gates pass.

## 2026-08-08 weather response and inventory-scaled composition search

- Inventory-scaled exact-composition search never exports negative BEV/ICE
  counts. Non-negative targets outside the selected inventory remain explicit
  boundary evidence but are not solved, keeping large radii compatible with
  the strict pair-certificate validator.

- Clean commit `4cb571ade840d9147dd3c91d00718dfbdc531163` was run through
  fresh frontend Prepare for the controlled pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_radius10_4cb571a_gap001`.
  Both cases fixed 264 trips, 60 selected vehicles, 10 chargers, flat
  30 JPY/kWh energy, zero demand charge, a 1,000 kW PV rating and a
  6,000 kWh / 3,000->3,000 kWh BESS. Only the separately hashed PV curve
  differed.
- Sunny used 23 BEVs / 9 ICE buses and served 121 / 143 trips at
  685,663.511395 JPY. Rain used 21 / 11 and served 91 / 173 trips at
  698,419.690050 JPY. Both served 264/264, passed independent physical
  validation and 24/24 Rolling, and reconciled solver objective to canonical
  accounting exactly. The pair is accepted for controlled PV sensitivity but
  remains `BLOCKED` for formal optimality because both full integrated models
  stopped at 100% gap after one node.
- The rain cost curve reached its minimum at 21 BEVs: all 996.2 kWh of PV was
  used and 124.985 kWh of grid-to-bus energy was purchased; 22 and 23 BEVs
  increased cost. Sunny used 1,563.002 kWh of its 6,056.25 kWh PV input with
  zero grid purchase, and cost continued falling through the radius-10 search
  boundary at 23 BEVs. This proves the prior identical 18-BEV result was a
  candidate-search failure, not evidence that sunny PV lacked economic value.
- A second boundary defect was therefore corrected: the internal Phase 4 seed
  no longer assumes that a solver-dependent primary composition can be covered
  by a fixed +/-10 radius. Candidate count and symmetric radius now scale from
  the selected available fleet (61 candidates and radius 60 for this 60-bus
  scope), while Stage 2 actual cost remains the selector. The formal runner
  rejects truncated inventory spans. No weather direction or BEV preference
  is added.

## 2026-08-08 Phase 4 accounting and formal-evidence correction

- The clean `b64bedb` controlled pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_autosym_b64bedb_gap001`
  held flat 30 JPY/kWh, zero demand charge, 1,000 kW PV rating and a 6,000 kWh
  BESS fixed. Both cases returned the same 18-BEV / 14-ICE, 59 / 205-trip
  incumbent at 704,318.633649 JPY. This is not an economic optimum: both runs
  explored one node and stopped at 100% gap, while the earlier clean sunny
  run already contains a lower-cost 25-BEV incumbent. The selected 18-BEV
  dispatch consumes only about 714--716 kWh of PV input, so even rain's
  996.2 kWh PV curve is sufficient; sunny's remaining PV cannot affect a
  composition that the seed search never generated.
- The Phase 4 seed therefore expands its weather-neutral exact composition
  neighborhood from +/-5 to +/-10 vehicles (21 candidates including the
  primary). Stage 2 canonical cost still selects the hand-off; no weather or
  BEV preference enters the objective. The complete Phase 3 seed composition
  certificate is now propagated to Phase 4 instead of exporting an invalid
  empty artifact.
- The BFF cost bridge now preserves the engine's verified
  `objective_is_actual_cost`, accounting-match, and objective-semantics fields.
  Previously it discarded those fields before Rolling, causing a numerically
  exact Phase 4 result to be mislabeled as a proxy objective. The focused
  regression set passes 114 tests and the complete suite passes 1,220 tests.
- The controlled-pair runner's formal-control audit now checks the same
  21-candidate, radius-10 Phase 4 seed profile that the server actually runs;
  it no longer rejects a valid run against stale 10-candidate/radius-2 values.
- The corrected clean pair at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_finalslot_b8793f3_gap001`
  confirms that integrated dispatch reacts to the 1,000 kW PV input: sunny
  uses 25 BEVs / 7 ICE buses (156 / 108 trips), while rain uses 15 BEVs /
  17 ICE buses (48 / 216 trips). Both serve 264/264 trips, pass the independent
  physical validator, and complete 24/24 Rolling. They remain non-optimal
  candidates because the requested 0.1% gap was not established.
- A formal-evidence audit found that Phase 4 applied the requested one-thread
  control but did not export it, discarded its measured solve time while
  constructing `solver_settings.json`, and was incorrectly required to emit a
  Stage-1 composition-search certificate. Phase 4 now exports its actual
  coupling/control metadata; a full-network integrated solve counts as fleet-
  composition evidence only after its requested global MIP gap is certified.
- BEV battery degradation no longer uses a hidden 50 JPY/cycle proxy. Solver,
  evaluator, and canonical ledger now share the scenario's
  `battery_degradation_cost_coeff_yen_per_kwh` throughput price. A disabled or
  zero-price component contributes exactly zero in all three paths.
- A clean-commit follow-up (`output/2026-08-08/run_20260808_1126`) verified the
  corrected zero degradation charge, exact solver/accounting reconciliation,
  one-thread control, solve-time export and integrated coupling metadata. It
  also exposed a search regression: using bound focus for the entire 3,600
  seconds retained the 15-BEV seed, explored one node and ended at 100% gap.
  The rain job was intentionally stopped before its long solve, so that
  directory is incomplete and is not pair evidence.
- A verified same-problem seed now keeps one uninterrupted, weather-neutral
  `MIPFocus=1, Heuristics=0.5` branch-and-bound search. Splitting the budget
  into two `optimize()` calls was rejected in review because a restart can
  discard the useful search tree and weaken the final bound. A subsequent
  clean sunny run showed that forcing `Symmetry=2` also regressed search: it
  spent heavy root-processing effort and returned 18 BEVs / 14 ICE buses,
  59 / 205 trips and 100% gap. Gurobi's automatic symmetry setting is therefore
  restored. The neutral Phase 3 seed still explores the primary composition
  plus both directions for deltas 1--10; Stage 2 actual cost selects the
  hand-off.
- Rolling finalization no longer hard-codes every day-ahead objective as
  non-actual-cost. Phase 3 remains false. Phase 4 is true only when its
  structural and numeric actual-cost contracts passed and the immutable solver
  objective still equals the accepted executed-day ledger within `1e-6 JPY`.
  The focused set passes `78 tests`; the complete suite passes `1218 tests`.
  Fresh clean-commit formal evidence is still required.

## 2026-08-08 Phase 4 final-slot and composition-resolution correction

- A fresh clean-commit diagnostic at
  `output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_fullscope_223c9f1`
  used 264 trips, flat 30 JPY/kWh grid energy, zero demand charge,
  1,000 kW PV and a 6,000 kWh BESS. Rain produced a physically valid
  15-BEV / 17-ICE day-ahead incumbent and accepted 24/24 Rolling, but its raw
  gap was 100%. Sunny reacted strongly to PV and reached 25 BEVs / 7 ICE buses,
  but failed postsolve validation; neither value is an accepted optimum.
- Sunny exposed two final-slot defects. Charging eligibility was emitted only
  for SOC-transition slots 0--22, so slot 23 could charge during a trip. The
  terminal SOC expression also subtracted a whole trip after prior hourly
  shares had already been consumed. For the three late BEVs, the false surplus
  exactly matched the duplicated 22:00--23:00 shares: 3.127139, 5.003422 and
  7.192420 kWh.
- Charging eligibility now covers every slot, while SOC transitions retain
  their correct one-shorter range. Terminal/day-end SOC uses the same
  slot-overlap energy expression as the transition rows, so each trip-energy
  share is debited exactly once. Return-to-initial and no-charge-during-trip
  contracts are preserved, not relaxed.
- BESS terminal deviation evidence is now computed from the solved final SOC
  and configured target. The unpenalized auxiliary absolute-deviation variable
  is no longer treated as physical evidence.
- The formal Phase 4 actual-cost pair now requests a 0.1% MIP gap. At the
  observed approximately 673,000 JPY objective scale, the former 5% target
  allowed about 33,000 JPY of uncertainty--roughly the entire sunny ICE fuel
  term--and therefore could terminate before resolving the powertrain mix.
  A time limit that misses 0.1% remains a feasible candidate only and is never
  reported as an optimum.
- Focused final-slot, BESS, actual-cost and frontend-runner tests pass; the
  complete repository suite passes `1212 passed`, and compileall/diff-check
  pass. A new clean commit and fresh sunny/rain Prepare/run are still required
  before this correction can discharge the research blocker.

## 2026-08-08 Phase 4 full-scope diagnostic correction

- A non-formal 264-trip HTTP diagnostic at
  `output/2026-08-08/run_20260808_0601` now proves that the verified Phase 3
  dispatch has feasible recourse in the integrated model. The fixed-dispatch
  solve returned an incumbent in about 0.8 seconds and promoted all 776,752
  integrated variable values as a complete warm start.
- The prior recourse IIS was caused by a false coarse-slot conflict. Charging
  and refueling used `on <= 1 - sum(y)` across every trip touching a one-hour
  energy slot. Two sequential, non-overlapping trips in the same slot made the
  right-hand side negative even when no charging/refueling occurred. Phase 4
  now applies the no-replenishment implication separately to each assignment;
  physical trip-overlap and turnaround constraints remain unchanged.
- The integrated extractor now publishes the exact solver expressions used by
  the final-day BEV SOC constraints. Missing initial SOC, target constraints,
  or terminal expressions fail closed. The 264-trip diagnostic reports all 15
  used BEVs, return-to-initial acceptance, a maximum deviation of approximately
  `1e-6 kWh`, and zero independent physical violations.
- A time-limit result with a verified incumbent is classified as a physically
  valid, non-exact candidate. It is never relabeled optimal. A time limit
  without an incumbent remains invalid.
- This diagnostic used a dirty, non-formal tree and a one-second unrestricted
  Phase 4 budget. It is implementation evidence only. A fresh Prepare and
  clean frozen sunny/rain pair remain mandatory before any research result or
  weather comparison is accepted.

## 2026-08-08 Phase 4 integrated-recourse-certified warm start

- The first clean implementation run at commit
  `e071446cb346092719a3103e81026bcb02d82a21` exposed a stricter defect: both
  264-trip cases accepted the Phase 3 seed and wrote every advertised `Start`
  value, but the integrated model rejected that vector and reached 3,600
  seconds with zero incumbents. Therefore `Start` assignment is no longer
  treated as proof of an integrated feasible warm start.

- Frontend `phase4_integrated` runs now build a Phase 3 two-stage plan on the
  same in-memory canonical problem before starting the full integrated MILP.
  The plan is accepted only when it covers the exact trip set, Stage 2 is
  feasible, and the independent physical validator passes.
- The accepted plan is only a Phase 4 MIP start and upper bound. Phase 3 cost,
  gap, or composition is never returned as a Phase 4 result and never implies
  integrated optimality.
- Formal actual-cost Phase 4 does not inject the one-sided `used BEV >= K`
  frontier. Its seed uses the primary Phase 3 candidate plus symmetric
  adjacent-composition candidates; the final objective contains no hidden
  weather or BEV-direction preference. The frontend Phase 4 request uses a
  5% gap target so the first 13/19 seed cannot terminate immediately at the
  former 10% threshold.
- After the Phase 3 plan is checked, Phase 4 temporarily fixes only its
  assignment/path/vehicle-use decisions and solves charging, physical-charger
  occupancy, vehicle/BESS SOC, PV, BESS and grid recourse in the integrated
  model itself. Only a feasible result is promoted to a complete all-variable
  MIP start; original dispatch bounds are then restored before the unrestricted
  actual-cost search. An infeasible fixed-dispatch recourse exports IIS names,
  counts and a fingerprint and fails the formal hand-off gate.
- The formal solver-control record declares the 600-second seed budget, its
  480/120-second Stage 1/2 split, a 300-second integrated fixed-dispatch
  recourse preflight, the 3,600-second unrestricted integrated budget, and the
  4,500-second total maximum. These controls are included in the sunny/rain
  comparison hash; each case gate separately requires a feasible preflight.
- Formal evidence still requires a fresh Prepare and a clean frozen commit.
  A feasible incumbent is distinct from meeting the requested MIP gap; any
  time-limit result must publish its achieved gap without claiming global
  optimality. The recourse correction has focused-test evidence only until the
  next clean 264-trip HTTP pair completes.

## 2026-08-07 PV/BESS and optimization-control contract

- Solcast records are resampled by source/target interval overlap. Converting
  a 60-minute irradiance interval to 5/15/30-minute slots now preserves daily
  kWh instead of assigning the whole interval to only one shorter slot.
- `POST /api/scenarios/{scenario_id}/depot-assets/update` is a patch API.
  Omitted PV/BESS fields retain their saved values; explicit `pv_enabled=false`
  and `pv_generation_kwh_by_slot=[]` are honored. Changing rated PV output
  also updates the reverse area estimates and rescales a derived curve.
- PV dates, slot lengths, performance ratio, PV generation, BESS ratings, SOC
  bounds, and charge/discharge efficiencies are validated before Prepare or
  optimization. Invalid physical inputs are not replaced by hidden defaults.
- Demand charge is billed per depot meter. The objective and canonical
  accounting both use the sum of the on/off-peak demand maxima for each depot.
- The Tk solver settings expose `phase3_two_stage`, `phase4_integrated`, Stage
  1 composition/frontier controls, and the Phase 4 canonical actual-cost and
  EV-utilization controls. Quick Setup persists and reloads the same fields.

These corrections invalidate prepared inputs and optimization outputs created
before this change. Restart Tk/BFF and run a fresh Prepare. A passing code test
suite does not make a research result READY; formal runs still require a clean
frozen commit and every per-run/pair acceptance gate.

> 東急バスの BEV／ICE 混成車両を対象に、便割当、充電、PV、BESS、系統電力を一貫して評価する研究用最適化システムです。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
![UI Tkinter](https://img.shields.io/badge/UI-Tkinter-3776AB?logo=python&logoColor=white)
![Solver Gurobi](https://img.shields.io/badge/Solver-Gurobi-EE3524)

> [!IMPORTANT]
> **現在の研究公開ステータスは `BLOCKED` です。** 個別ジョブの完了、可行解、Rolling の受理、正式な研究受理は別の判定です。最新の判定理由と必要な証跡は、[研究リリースのブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md)を確認してください。

## まず、目的に合う入口を選ぶ

| やりたいこと | 最初に読む・実行するもの |
| --- | --- |
| 画面から通常の最適化を動かす | [最短で起動する](#最短で起動する) → [最初の最適化](#最初の最適化) |
| 研究用の正式実行をする | [正式研究実行の手順](docs/notes/FORMAL_RUNBOOK_CURRENT.md) と [ブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md) |
| モデルを教員・共同研究者に説明する | [教員レビューガイド](README_core_professor.md) |
| 日常運用、比較、障害対応を確認する | [運用ガイド](readme_operation.md) |
| 実装・検証・変更履歴を確認する | [開発ノート](DEVELOPMENT_NOTES.md) |

## このシステムでできること

- 時刻表と営業所・路線スコープから、車両ごとの便割当と回送を作成する。
- BEV の SOC、充電器、PV、BESS、系統電力、料金を制約として充電計画を評価する。
- 日初の計画に加え、1 時間ごとの Rolling 再最適化、物理スケジュール検証、実行日会計を成果物として残す。

現行ソルバには、二段階の **Phase 3** と、配車・充電・PV・BESS・系統購入を結合する **Phase 4** があります。Phase 3は大域的総費用最適解ではなく、Phase 4も現時点ではclean formal pairが未受理です。どちらも、成果物ごとの物理・会計・最適性・研究受理ゲートを越えて主張範囲を広げないでください。

## 現在の構成と扱い

| 項目 | 現在の扱い |
| --- | --- |
| 操作画面 | Tkinter + FastAPI BFF。`python run_app.py` が両方を起動します。 |
| API | FastAPI の `/api` 配下。起動後の対話的な仕様は `http://127.0.0.1:8000/docs` で確認できます。 |
| React / Tauri | まだ設計・受入基準の段階です。通常運用の手順としては扱いません。詳細は [frontend 移行仕様](docs/frontend/README.md)。 |
| 出力 | 現在の既定ルートは `output/`。各 run は通常 `output/<日付>/run_*` に保存されます。 |

```mermaid
flowchart LR
    UI[Tkinter 操作画面] --> BFF[FastAPI BFF /api]
    BFF --> CORE[配車・最適化コア]
    CORE --> ART[run 成果物]
    ART --> CHECK[Rolling・物理検証・会計・研究受理]
```

## 最短で起動する

### 前提

- Windows / PowerShell
- Python 3.11 以上（CI の検証対象は Python 3.11）
- MILP を実行する場合は、別途 Gurobi と有効なライセンス
- 利用対象の built dataset（画面のデータ状態で確認）

初回だけ、仮想環境と依存関係を準備します。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

MILP を使う環境では、Gurobi を導入・ライセンス設定したうえで `gurobipy` も追加します。

```powershell
python -m pip install gurobipy
python -c "import gurobipy as gp; m=gp.Model(); x=m.addVar(lb=0.0, name='x'); m.setObjective(x); m.optimize(); print('gurobi_ok', gp.gurobi.version())"
```

起動は次の一行です。FastAPI が起動可能になるのを待ってから Tkinter 画面を開き、画面を閉じると BFF も終了します。

```powershell
python run_app.py
```

API だけを起動して確認したい場合は、次を使います。

```powershell
python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000
```

> [!NOTE]
> この checkout には配布済みの `.exe` は含まれていません。配布物を受け取っている場合は、その配布元の手順を優先してください。

## 最初の最適化

通常は、画面の案内どおり次の 4 ステップで十分です。

1. シナリオを選び、対象の運行日・営業所・路線を確認する。
2. `Quick Setup 保存` で選択内容を確定する。
3. 条件を変える必要がある場合だけ `ソルバー設定` を開く。
4. `高速実行` を押す。未 Prepare または stale のときは、画面が Prepare を先に実行してから最適化ジョブを開始します。

対象スコープ、便数、車両、充電器を実行前に明示確認したいときは、`Solver対応 Prepare` を個別に使います。Quick Setup やソルバー条件を変更した後は、必ず再 Prepare してください。

Quick Setup の数値入力では、`0` は「未入力」ではなく明示値です。たとえば、基本料金
`0 JPY/kW`、売電単価 `0 JPY/kWh`、乱数 seed `0` は、保存後の再読込と次回
Prepare でもそのまま保持されます。既定値が使われるのは項目が未設定 (`null`) の場合だけです。
入力範囲として無効な値は、別の既定値へ黙って置換せず、各入力・実行時の検証でエラーにします。

PV設備は、画面で保存した `pv_capacity_kw`（PV定格出力）を最適化入力の正本とします。
面積からの推定容量や、定格出力から逆算する必要設置面積・面積相当値は監査用の派生値であり、
保存済みの定格出力や実測営業所面積を黙って上書きしません。定格出力を変えた場合もfresh Prepareが必要です。

### 結果を正しく読む

| 表示・成果物 | 分かること | それだけでは分からないこと |
| --- | --- | --- |
| ジョブが `completed` | 非同期ジョブが終端状態になった | 可行性、物理妥当性、研究受理 |
| `solver_status=OPTIMAL` または `FEASIBLE` | 数理最適化が解を返した | Rolling、独立物理検証、正式な研究主張 |
| `rolling_execution.status=executed_and_accepted` | 保存された Rolling 連鎖が受理された | 比較対照の妥当性、研究公開の可否 |
| `teacher_release_status=READY` | 正式な研究リリースの全ゲートが通った | それ以上の一般化や統合大域最適性 |

画面の `Optimization結果` から run ディレクトリを確認してください。主な成果物は次のとおりです。

- `summary.json`: 実行・受理状態の要約
- `experiment_report.md`: 読みやすい実験報告
- `results.xlsx`: 集計と照合用の表
- `rolling_hourly_chain/executed_day_accounting.json`: 受理済み Rolling の最終費用正本

`job completed` だけを成功や研究成果として扱わないでください。

## 研究用の正式実行

通常の試行計算と正式研究実行は意図的に分けています。試行計算は診断用であり、dirty な Git worktree でも動かせますが、成果物は研究公開 `BLOCKED` のままです。

正式実行では、少なくとも次を満たす必要があります。

1. clean な worktree と固定した Git SHA から開始する。
2. 運行日、時刻表、営業所・路線、車両、初期状態、充電器、BESS、料金、ソルバー条件を明示して Prepare する。
3. 日初計画、全時間帯の Rolling、独立物理検証、実行日会計、成果物照合をすべて通す。
4. PV 比較では、PV 曲線以外の対照条件をハッシュで一致させる。

具体的なコマンド、必須証跡、失敗時の表記は [正式研究実行の手順](docs/notes/FORMAL_RUNBOOK_CURRENT.md) を正本とします。最新の未解決事項は [研究リリースのブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md) で確認してください。

## よくある確認ポイント

### データが利用できない

まず画面または `GET /api/app/data-status` でデータ状態を確認してください。`BUILT_DATASET_REQUIRED` が出た場合は、データを推測で補わず、[運用ガイドのデータ復旧手順](readme_operation.md#no-module-named-tokyubus_gtfs)に従ってください。

### 503 またはジョブ待ちになる

BFF は同時に一つの実行しか受け付けません。前のジョブの終了を待つか、比較実行には [運用ガイド](readme_operation.md#1-ソルバーモード比較benchmark) の順次実行スクリプトを使ってください。

### `INFEASIBLE` になる

SOC、初期状態、車両台数、充電器・契約電力、回送接続、`allowPartialService` を確認し、条件を変えた後は Prepare からやり直してください。制約を緩めたり、時刻表を勝手に加工したりして解を作ることはしません。

## 関連資料

| 読者・用途 | 資料 |
| --- | --- |
| 日常操作・比較・トラブルシューティング | [運用ガイド](readme_operation.md) |
| 指導教員・共同研究者向けのモデル説明 | [教員レビューガイド](README_core_professor.md) |
| 定式化と実装状況 | [制約・目的関数の定式化](docs/constant/formulation.md) / [実装状況](docs/constant/implementation_status.md) |
| 車両セットを固定する研究契約 | [Scenario Fleet Contract](docs/model/SCENARIO_FLEET_CONTRACT.md) |
| 図表・生データの対応 | [Literature Figure Mapping](docs/model/LITERATURE_FIGURE_MAPPING.md) |
| React + FastAPI、その後の Tauri 移行 | [frontend 移行仕様](docs/frontend/README.md) |
| 実装の変更履歴・検証結果 | [開発ノート](DEVELOPMENT_NOTES.md) |

## リポジトリの見取り図

```text
run_app.py                  Tkinter + FastAPI をまとめて起動
tools/scenario_backup_tk.py 現行の操作画面
bff/                        FastAPI BFF と run の最終化
src/                        配車・最適化・検証のコア
data/                       入力データと built dataset
output/                     実行成果物（Git 管理外）
docs/                       研究・運用・移行の詳細資料
tests/                      回帰テスト
```

## 開発・検証

開発環境では `pytest` を追加してから、少なくとも次を実行してください。

```powershell
python -m pip install pytest
python -m compileall -q src bff scripts tools
python -m pytest -q -p no:cacheprovider
```

README の入口とリンクだけを確認する軽量テストは次です。

```powershell
python -m pytest -q tests/test_readme_navigation.py
```

## Controlled PV comparison hashes

Sunny/rain controlled comparisons hash only controls declared before the
solve: timetable and fleet fingerprints, tariff and depot assets, solver time
limits, gap target, threads, random seed, and Phase 4 seed budgets/search
settings. Observed telemetry such as actual seed wall time and the seconds
remaining when Stage 2 starts is retained in each run audit, but is not part of
`comparison_control_hash`. Those values naturally vary between otherwise
identical cases and must never be treated as experimental-control differences.

研究計算の意味、制約、受理ゲートに影響する変更では、README だけで説明を完結させず、該当する runbook・開発ノート・ブロッカー資料も同時に更新してください。

## Latest controlled PV1000 evidence (2026-08-10)

The clean frozen commit `06ae09218be99ca47b951dcf6ddad886056b0ad6`
was run through the ordinary HTTP Prepare/optimization path with a common
2025-08-05 weekday service, 30 JPY/kWh energy charge, 0 JPY/kW demand charge,
1,000 kW PV rating, and 6,000 kWh BESS. The final Phase 4 incumbents used
27 BEVs/5 ICE buses in the high-PV case and 21 BEVs/11 ICE buses in the low-PV
case. The `13 BEV/19 ICE` value in the artifacts is the Phase 3 seed candidate,
not the final integrated assignment.

Both cases served 264/264 trips, completed 24/24 Rolling, passed physical and
accounting validation, and the pair passed the controlled-PV comparison
contract. They did not meet the requested 0.1% MILP gap (3.928% high PV and
2.387% low PV), so formal research submission remains `BLOCKED`.

High-PV output was not energy-limited: 6,056.25 kWh was generated and
3,606.64 kWh was curtailed. Candidate diagnostics for 28--32 BEVs instead
identify vehicle-local charging-window/terminal-SOC conflicts in the examined
assignments. These failed assignments are evidence about the observed
incumbent plateau, not a proof that every 28-BEV assignment is infeasible.

### 1% pair-audit compatibility fix (2026-08-10)

The controlled-pair runner now carries the explicitly predeclared
`--actual-cost-mip-gap` value into its post-run case audit. A run requested at
1% is therefore checked against 1%, not the historical 0.1% default. Claim
consistency is checked from `result_claim_classification` and solver settings;
generic successful frontend text such as `Optimization complete.` is accepted
when those structured fields agree. Explicit prose that contradicts a gap or
integrated-scope gate still fails closed. A fresh clean-commit pair remains
required after this reporting-only correction.

### Final PV1000 1% controlled pair (2026-08-10)

Clean frozen SHA `6bf6bd7eebec06dde1a899bebe5e02f3dc9fd62c`
completed the ordinary frontend HTTP path with fresh Prepare for both cases.
The high-PV case used 32 BEVs and 0 ICE buses for all 264 trips; the low-PV
case used 21 BEVs and 11 ICE buses for 91/173 trips. Certified gaps were
0.735476% and 0.399008%, both within the predeclared 1% target. Both cases
passed 264/264 coverage, 24/24 Rolling, physical/SOC, accounting, artifact,
tariff, Git-provenance, and solver-control gates. The pair manifest reports
controlled comparison accepted and formal research submission ready with no
failed checks.

The authoritative pair output is
`output/formal_pair_20260810_flat30_pv1000_bess6000_phase4_6bf6bd7_gap01`.
Standalone case summaries remain blocked only by
`controlled_counterfactual_pair_not_verified`, because they are finalized
before their counterpart exists. The immutable pair manifest is the
pair-scoped release attestation and discharges that single pending check.

## Progress-report output for a controlled PV pair

`scripts/run_frontend_controlled_pv_pair.py` uses the same Prepare,
`run-optimization`, job-polling and finalized run directories as the frontend.
After both cases and the immutable pair audit finish, it also writes
`progress_report/` inside the pair directory. Start with:

- `progress_report/progress_report.md` for the progress-report narrative;
- `progress_report/00_progress_summary.png` for the one-page result summary;
- `progress_report/00_release_and_provenance.csv` for scenario, prepared input,
  job, source-run, frozen-SHA and case/pair claim identifiers;
- `progress_report/01_scenario_controls.csv` for matched controls including
  30 JPY/kWh, zero demand charge, 1,000 kW PV rating, reverse-calculated PV
  area fields and the 6,000 kWh BESS;
- `progress_report/02_outcome_kpis.csv` and
  `04_hourly_energy_comparison.csv` for analysis-ready result data;
- `progress_report/03_validation_gate_matrix.csv` for every exported case and
  pair gate;
- `progress_report/05_per_run_figure_catalog.csv` for the five detailed
  PNG/SVG/source-CSV figures already generated by each run; and
- `progress_report/evidence_index.json` plus `manifest.json` for file hashes,
  completeness and claim scope.

Seven pair figures are exported as both PNG and SVG: summary, powertrain
composition, energy flows, hourly profiles, cost breakdown, fuel/emissions,
and solver/acceptance evidence. The evidence ZIP includes this directory, both
canonical `results.xlsx` files and all underlying run artifacts. A complete
chart bundle does not by itself make a pair research-ready; cite
`pair/pair_manifest.json` for pair scope and each `research_claim_scope.json`
for standalone-case scope.

## Canonical reporting snapshot for a completed pair

`scripts/build_reporting_snapshot.py` is the read-only presentation-release
postprocessor for an already completed controlled pair. It does not call the
optimizer and does not rewrite either run. It uses:

- `graph/trip_assignment.csv` for final service-trip and used-vehicle counts;
- `rolling_hourly_chain/executed_day_accounting.json` for final energy, cost,
  emissions and terminal-energy results;
- `rolling_hourly_chain/hourly_energy_flow_chart.csv` for the published hourly
  energy and SOC series;
- `graph/physical_schedule_validation.json` for the final physical verdict;
- `solver_settings.json` and the effective values in
  `optimization_parameters.json` for solver controls and certificates; and
- the two case manifests plus `pair/pair_manifest.json` for controlled-pair
  identity and claim scope.

The command requires the Node executable and `node_modules` directory returned
by the workspace dependency loader because `results.xlsx` is authored with the
bundled spreadsheet runtime:

```powershell
.\.venv\Scripts\python.exe scripts\build_reporting_snapshot.py `
  <PAIR_DIR> `
  --node-executable <BUNDLED_NODE_EXE> `
  --node-modules-dir <BUNDLED_NODE_MODULES> `
  --workbook-preview-dir <VISUAL_QA_DIRECTORY>
```

After every gate passes, the script atomically writes `release/` and
`release.zip`. The release contains one `reporting_snapshot.json`, seven compact
JSON/CSV result/validation relations, a formula-audited `results.xlsx`, and six
PNG figures. Every public file records the same `reporting_snapshot_sha256`; the
snapshot also records the content hashes of both reporting generators. Custom
release and ZIP paths are accepted only as safe immediate children of the pair
directory.

Day-ahead energy-flow tables and the internal search objective (including any
return-leg search adjustment) are excluded from public final-cost KPIs.

The fixed public inventory is:

```text
release/
├─ reporting_snapshot.json
├─ result_summary.json
├─ comparison_pair_manifest.json
├─ validation_summary.json
├─ comparison_summary.csv
├─ vehicle_assignment.csv
├─ energy_balance.csv
├─ cost_breakdown.csv
├─ results.xlsx
└─ figures/
   ├─ cost_comparison.png
   ├─ dispatch_comparison.png
   ├─ energy_flow_baseline.png
   ├─ energy_flow_low_pv.png
   ├─ soc_baseline.png
   └─ soc_low_pv.png
```

The 2026-08-11 pair snapshot is under
`output/formal_pair_20260811_flat30_pv1000_bess6000_phase4_2632de9_gap01_progress/release/`.
Its derived release is `READY_FOR_PROGRESS_PRESENTATION`. The field
`research_submission_ready=false` means this compact presentation postprocessor
does not assess input realism; it does not downgrade or replace the immutable
pair-level formal attestation in `pair/pair_manifest.json`.
