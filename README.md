# master-course

## 2026-08-09 cost-ranked exact-composition seed search

- A nonformal 300-second BFF diagnostic from clean commit `c819e36` confirmed
  that the verified-seed objective and vehicle-day cutoffs are active, but the
  776,752-variable integrated model still ends at root node one with raw bound
  zero. Parameter focus alone does not close the formal proof gap.
- A separate `used BEV >= 32` diagnostic is deliberately not used as an
  optimization result: it kept 19 ICE buses and activated 51 buses, proving
  that a one-sided BEV policy frontier is not a substitute for the canonical
  fixed-cost optimum.
- The remaining seed defect is budget allocation. In the completed formal
  pair, exact `32 BEV / 0 ICE` received 2.694 solver seconds and `31 / 1`
  received 2.772 seconds, while their unverified constructive duties were then
  rejected by Stage 2. This did not establish global infeasibility.
- Exact-composition targets are now ranked by the optimistic cost of their
  complete constructive dispatch, never by BEV direction. The Stage 1 reserve
  grows only when exact-composition search was explicitly requested; the
  highest cost-priority targets may receive up to 60 seconds while at least two
  seconds remain for every later target. Stage 2 canonical cost still chooses
  the seed, and the unrestricted integrated MILP remains the proof model.
- Focused regressions pass (`61`) and the full repository suite passes
  (`1239 passed in 55.35s`). Fresh clean-run evidence is still required.

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
