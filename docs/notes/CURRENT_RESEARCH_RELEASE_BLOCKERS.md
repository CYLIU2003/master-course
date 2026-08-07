# Current research release blockers

Status date: 2026-08-07
Code status: slot-indexed Stage 1 energy recourse, multi-candidate Stage 2
evaluation, explicit same-service-date PV controls, and an HTTP-only frontend
pair runner are implemented. A final-slot return-boundary defect exposed by
the fourth HTTP attempt is corrected, and candidate selection now requires an
independent physical check in addition to Stage 2 feasibility. The fifth HTTP
attempt exposed and the current tree corrects a result-claim message that
conflated integrated-optimality scope with certified-gap status. The corrected
completion audit also rejects a contradiction between solver settings,
persisted claim classification, and terminal response. The current
explicit-zero regression passes (`133 passed`) and the complete suite passes
(`1116 passed`); compileall and `git diff --check` also pass.

## 2026-08-05 frontend 1,000 kW setting restoration

The two current frontend scenarios declare a common 1,000 kW PV rated output.
The prior 101.5 kW v6 controller environment explicitly overrode that frontend
field, so it must not be described as a run of the user's 1,000 kW scenario.
The runner now requires the separate
`--allow-frontend-pv-capacity-override` acknowledgement before accepting
`--pv-capacity-kw`; omitting both keeps the frontend value authoritative.

The restored 1,000 kW setting implies 6,056.25 / 996.2 kWh sunny/rain input,
5,000 m2 required installable area, and 14,285.714286 m2 reverse-estimated
depot-area equivalent. This correction does not make either old run current:
fresh Prepare is required, and no optimization was run during the restoration.
The existing 1,000 kW evidence indicates that even rain can saturate the BEV
renewable demand, so a null weather response at this capacity remains possible
and must not be hidden. A 101.5 kW run is a separate binding-PV sensitivity,
not the saved frontend baseline.

Teacher release status is fail-closed: **BLOCKED** unless
`output/formal_pair_20260730/completion_audit.json` records `status=READY`,
zero failed checks, the exact frozen Git SHA at start and end, and a completed
ZIP. When that artifact exists for the current frozen SHA, this blocker is
discharged without modifying the repository during the experiment.

## Quick Setup explicit-zero persistence repair (2026-08-07)

The affected scenarios retained `demand_charge_cost_per_kw=0.0` in the
scenario store. The defect was in the Tk reload path: Python falsey fallback
converted the saved zero to the UI default `1500`, and a later Prepare could
therefore materialize the wrong tariff despite the earlier save succeeding.

The current tree preserves explicit numeric zero through Quick Setup save,
BFF reload, Tk field restoration, Prepare controls, and `ProblemBuilder`.
Defaults now apply only when a value is absent or `null`. Explicit flat grid
price zero is also treated as a real tariff declaration rather than a reason
to reuse inherited price slots.

This repair does not validate either weather scenario and does not make an
older prepared input comparable. Tk/BFF must be restarted and each scenario
must be freshly Prepared from the reviewed clean commit. Any output produced
from the pre-repair reload/Prepare path remains diagnostic, and teacher
release remains **BLOCKED** until all existing formal gates pass.

## Formal-run dirty-worktree UX (2026-08-06)

Remote `main` at the start of this repair was
`da26b06c617256f27b08b4123a46169e185a833a`. The rejected user run did not
reach `ProblemBuilder` or Gurobi: its prepared scope and distance audits were
not the blocker; the request declared `research_run=true` while the BFF
observed `git_state_available=true`, a non-empty SHA, and `git_dirty=true`.

The UI now separates trial and formal execution. Trial mode is allowed on a
dirty tree but is permanently labelled diagnostic and teacher-release
`BLOCKED`. Formal mode performs a canonical Git preflight before submission,
the BFF repeats it before creating a job, and the unchanged worker guard checks
again before solving. The solve-end SHA/patch check remains mandatory.

This code change is not itself formal run evidence. The branch must be reviewed,
committed, and frozen; Tk/BFF must then be restarted and both cases freshly
Prepared. Until fresh artifacts from that clean commit pass every per-run and
pair gate, teacher release remains **BLOCKED**.
## 2026-08-03 actual-cost and BEV-frontier implementation

The clean v5 binding-PV pair completed both 264/264 schedules, independent
physical validation, 24/24 Rolling, and all `K=15..35` frontier targets. It
then correctly remained **BLOCKED**. In addition to the intended rain
objective/accounting mismatch, the audit found a metadata-only defect:
`solver_settings.json` omitted `stage1_bev_frontier_enabled` even though the
frontier was active and its artifacts were complete. The current tree carries
that flag through the solver adapter, MILP engine, and BFF settings export.
This does not alter the solved model or retroactively validate v5.

The clean v6 rerun at frozen SHA
`7ab9f194216b1b7fe0e0ef49041314528438f6d5` verifies the correction. Both
cases now pass `solver_controls_match_formal_request`, all 21 frontier targets
resolve, all required controls match, and the assignment changes from sunny
17 BEV / 15 ICE and 54 BEV trips to rain 13 BEV / 19 ICE and 44 BEV trips.
Both serve 264/264 trips, pass independent physical validation, and complete
accepted 24/24 Rolling. The selected candidates and costs are byte-for-value
identical to v5, confirming the metadata fix did not change the solve. The
pair is still **BLOCKED**, correctly, because Phase 3 is not an integrated
actual-cost objective, the rain solver objective differs from executed-day
canonical accounting by 22.292853 JPY, and the 20,000 JPY/used-bus-day
coefficient remains `unclassified`.

The clean Phase-4 HTTP pair at commit
`0d4a68b783dd26f3a30b0030940e4a9b1e43799e`, common 1,000 kW rated PV,
30 JPY/kWh grid energy, and zero demand charge is **BLOCKED**. Sunny and rainy
each exhausted the 3,600-second solver limit with zero incumbents and only the
root node processed, so all 264 trips remained uncovered and hourly Rolling
was not started. The corresponding PV inputs were 6,056.25 kWh and 996.2 kWh;
these are input diagnostics, not utilized energy from a feasible schedule.
This attempt establishes a complete Phase-4 warm-start/computational blocker
and provides no evidence for an optimal BEV/ICE composition. The next formal
comparison must use the bounded Phase-3 frontier or first supply Phase 4 with a
fully feasible assignment/charger/SOC/source-flow start; model relaxation and
weather-direction bias are not acceptable substitutes.

The current working tree replaces the narrow fixed-32 composition neighborhood
for the requested diagnostic with a `used BEV >= K`, `K=15..35` frontier. ICE
and total used-fleet counts are endogenous. Each K receives an explicit status;
`TIME_LIMIT_NO_INCUMBENT` remains unresolved, and formal frontier evidence
requires every in-inventory target to be either physically feasible after
Stage 2 or covered by a valid Stage-1 IIS certificate. Phase 3 still remains a
two-stage method and cannot claim an integrated global total-cost optimum.

The first clean Phase-3 frontier execution from
`751762279adb28dac1039f4994f9538b83b6f928` is also **BLOCKED**. Both primary
schedules served 264/264 trips, passed independent physical validation and
24/24 Rolling, and selected 13 BEVs / 19 ICE buses with 44 / 220 trips and
707,808.660373 JPY canonical operating cost. All 21 K targets nevertheless
reached `TIME_LIMIT_NO_INCUMBENT`. The old helper was disabled for frontier
search and represented only one activation/retirement, while the first target
required two additional BEVs. The current tree supplies complete multi-vehicle
starts and records their full IDs and count without weakening any acceptance
gate. It also corrects two fail-closed CSV schema checks that had lagged their
writers. A fresh clean-commit run is required; code changes alone do not resolve
the composition-search blocker.

The 1,000 kW pair is not a binding-PV weather test. Rain supplied 996.2 kWh and
the selected schedule allocated only 565.86897 kWh of renewable energy in
Stage 1, so both cases legitimately had zero BEV grid purchase. A separate
binding-PV weather-response sensitivity may use the predeclared common
101.5 kW rating, which reconstructs approximately 614.709 / 101.114 kWh while
holding non-PV controls fixed. Until its frontier, Rolling, physical,
accounting, and pair gates pass, teacher release remains **BLOCKED**. That
sensitivity must not overwrite or be mislabelled as the frontend scenarios'
current 1,000 kW rated output.

The binding-PV v2 run now exists at
`output/formal_pair_20260803_flat30_pv101p5_phase3_frontier_v2`, frozen at
`fe453df2f8a2ea0bb9c2240d42f2df5af9f12180`. Its common 101.5 kW rating
reproduced 614.709375 / 101.1143 kWh. Both cases served 264/264 trips and
completed accepted 24/24 Rolling. K=15..27 produced Stage-2 and independently
physically feasible candidates. The resolved-range minima differed as expected:
sunny K=17 (17 BEV / 15 ICE, 54 BEV trips, 706,175.871233 JPY) versus rain
K=15 (15 BEV / 17 ICE, 44 BEV trips, 720,637.777812 JPY). Stage-1 grid energy
was 19.011025 / 411.374162 kWh. This demonstrates that PV availability now
changes the selected resolved-frontier composition without a weather bias.

The v2 pair is nevertheless **DIAGNOSTIC ONLY**. K=28..35 each reached
`TIME_LIMIT_NO_INCUMBENT`, so the frontier gate and both frontend jobs failed
closed. The current tree addresses that newly isolated blocker with a
duty-suffix split start that activates an unused BEV without retiring the
source bus, allowing total used-fleet size to grow above the 32-bus primary
path cover. A fresh clean-commit rerun must resolve every K target and all
other gates; the unclassified positive vehicle-day cost remains an independent
economic-claim blocker.

The succeeding v3 run at frozen SHA
`4d997be18c8507ac450001a27c32f6245b851b4e` generated Stage-1 incumbents
through K=35 for both cases, proving the suffix-split start reaches the former
high-K gap. Sunny resolved every target. Rain direct candidates at K=26 and
K=27 were rejected, without repair, for one independently detected contract-
power violation each; however, its physically feasible K=28 candidate is also
a valid witness for the nested `used BEV >= 26` and `>= 27` constraints. The
old finalizer failed to propagate that mathematical implication and therefore
blocked the rain frontend job. The current correction selects, for each K, the
lowest-cost physically feasible evaluated candidate satisfying `actual used
BEV >= K`, while preserving both the failed direct target and resolving witness
hashes. A fresh clean-commit pair is still required. The 22.292853 JPY rain
Phase-3 objective/canonical difference and `objective_is_actual_cost=false`
remain independent blockers to any integrated total-cost optimum claim.

The first v4 attempt is not formal evidence. Sunny completed optimization and
Rolling, then failed closed because the new composition-search CSV columns had
not yet been added to the exact artifact-schema validator. Rain was stopped
immediately to avoid a known-invalid long run. The writer, strict validator,
and regression fixture now share one header; both weather cases must be rerun
from the next clean SHA.

An opt-in `phase4_integrated_actual_cost` case now removes policy/solver-only
soft terms and uses the canonical accounting components as one integrated
objective. `objective_is_actual_cost` remains false until a post-solve numeric
audit reconciles the raw solver objective and canonical accounting within
`1e-6 JPY` without fallback or post-solve modification. This code path has unit
and small integration coverage, but the requested 264-trip sunny/rain HTTP
runs have not yet passed all Fresh Prepare, solver, 24/24 Rolling, physical,
accounting, and pair gates; teacher release therefore remains **BLOCKED**.
The current implementation has passed the complete 1,103-test regression suite;
that code validation does not substitute for the still-pending long-running
controlled runs.

The distinct maximum-EV and epsilon-cost policy frontiers are also represented
as different integrated MILPs: ICE fuel liters are the primary objective and
canonical cost is the secondary objective, while epsilon cases additionally
enforce an externally evidenced absolute `C* (1 + delta)` bound. These runs are
policy sensitivities, not substitutes for the unconstrained actual-cost optimum,
and cannot set `objective_is_actual_cost=true`.

The 20,000 JPY/used-bus-day coefficient is no longer silently treated as a
research-ready cost. Quick Setup/Prepare must classify it as a fixed vehicle-day
cost, driver-cost proxy, provisional sensitivity, or unclassified. A positive
provisional or unclassified value blocks the EV/ICE economic claim. The user
has not yet supplied evidence selecting a research-eligible interpretation for
the existing 20,000 JPY value, so the rerun must preserve this blocker unless
that meaning is explicitly established.

New required artifacts include the BEV frontier, source-specific marginal cost,
trip replacement cost, baseline/integrated comparison, and an explicit split
between daily operating cost and partial lifecycle scope. Trip-level PV/BESS
availability and a complete lifecycle total are never inferred when charger/
SOC or CAPEX/financing inputs are absent.

## 2026-08-02 interactive 2025-08-10 Prepare repair

The interactive `2025-08-10` + `WEEKDAY` + actual-date-PV Prepare failure was
caused by stale formal-pair metadata and a collision between calendar-policy
and comparison-design fields. Quick Setup now invalidates the old pair
type/role/source, while the Sunday/WEEKDAY exception remains explicitly stored
as `calendar_policy=fixed_weekday_timetable_pv_counterfactual` with its allow
flag. A narrowly scoped legacy migration unblocks already-saved scenarios.
This changes no timetable, PV, fleet, tariff, or solver input and does not
remove any formal research-release blocker; fresh Prepare is still required.
Fresh Prepare now succeeds through the live BFF for the affected scenario as
`prepared-b8601506bd9b49e5-dbc36084d07b5fa8-9dd564c9` (`ready=true`, 264 trips,
60 vehicles, 10 chargers). This proves the pre-solver HTTP 422 is resolved; it
does not constitute an optimization run or discharge pair-level release gates.

## 2026-08-02 PV rated-output model-input change

PV capacity can now be selected directly with `pv_capacity_kw` and is carried
through fresh Prepare into the canonical builder. Its inverse area estimates
are audit metadata; they do not overwrite measured depot area. This changes
the prepared-input schema to `v5_pv_rated_output_authoritative`, so every
pre-change prepared payload and optimization artifact is stale for a new PV
capacity experiment. The formal HTTP pair runner must receive the common value
through `--pv-capacity-kw`; it no longer replaces that value with the
area-derived 101.5 kW setting. No existing 2026-07-31 or 2026-08-02 pair is evidence for
the new capacity setting. A fresh same-commit rerun is required to discharge
this capacity-input freshness blocker; all other release gates remain
independent.

That rerun now exists at
`output/formal_pair_20260802_flat30_pv1000_rated_output`, frozen at
`bb6c7fc3e49067f178a1540e4061ad4b83c015e0`. It verifies that 1,000 kW reaches
Prepare and the canonical solver unchanged, with 5,000 m2 reverse-estimated PV
installation area. Sunny/rain generation is 6,056.25 / 996.2 kWh, but both
select the identical 14-BEV/18-ICE, 46/218-trip assignment and zero grid-to-bus
energy. Rain still curtails 420.658964 kWh, so the chosen capacity has saturated
both weather cases; this is a valid null weather response at that capacity.

The new pair is still **DIAGNOSTIC ONLY**. It evaluates three rather than the
requested 21 candidates, does not pass the same-assignment strict audit, and
the Phase 3 objective remains a two-stage proxy (`objective_is_actual_cost`
is false) even though its numeric residual against canonical accounting is
only `1.164153e-10 JPY`. The pair manifest and teacher release therefore remain
blocked. A fresh, predeclared rated-capacity sweep below 1,000 kW is needed to
identify the range where rain PV becomes binding without changing any non-PV
control.

## 2026-08-01 flat-30 pair: composition and accounting blockers

`output/2026-07-31/run_20260731_1201` (sunny) and
`output/2026-07-31/run_20260731_1210` (rain) are retained as **DIAGNOSTIC
RESULTS — NOT USED FOR RESEARCH CONCLUSIONS**. They share the controlled
non-PV hash and have distinct PV totals (614.709375 / 101.1143 kWh), but all
21 retained Stage-1/Stage-2 candidates in each case use the single activated
composition `(used_bev, used_ice)=(13,19)`. The selected BEV trip counts are
43 / 44. Existing trip-pattern alternatives do not prove that adjacent fleet
compositions are infeasible, so this is not evidence that the common
composition is cost-optimal.

The current source already uses a slot-level assignment-coupled continuous
PV/grid/BESS recourse in Stage 1; it is not correct to repair this result by
reintroducing a whole-day `min(grid_price)` or unlimited zero-price grid proxy.
The actual missing evidence was an explicit activated-BEV/ICE neighborhood and
certificate. The current tree adds that search and rejects a formal release
unless it finds more than one physically valid composition or proves every
in-inventory adjacent target infeasible. A formal infeasibility certificate
requires a successful nonempty IIS containing the temporary count constraint,
the exact temporary Stage 1 LP SHA-256, and the recorded solver controls;
`TIME_LIMIT`, an empty/failed IIS, or a missing model hash is unresolved, not
a certificate.

The rain artifact additionally has
`solver_objective_matches_accounting_total=false`: Stage-1 solver objective
`720352.6732800236 JPY` and canonical executed-day accounting
`720374.9661326109 JPY` differ by `22.2928525873 JPY`. Its
`final_cost_reconciliation.json=OK` reconciles reporting artifacts to the
executed-day ledger only; it does not reconcile the solver objective. The
formal pair builder now blocks this condition using a numeric
`solver_objective_accounting_reconciliation.json` evidence artifact rather
than a Boolean flag or relabelling it as a total-cost optimum. A clean frozen
SHA must rerun both cases and preserve the new composition certificate plus
`assignment_economic_audit.json/.csv`.

For interpretation, 30 JPY/kWh grid energy gives approximately
`1.316 / 0.95 * 30 = 41.56 JPY/km` at the charger-input contract, whereas ICE
fuel is `0.2212389 * 150 = 33.19 JPY/km`; the corresponding energy-only grid
break-even is about `23.96 JPY/kWh`. This supports neither a hidden BEV
preference nor an assertion that sunny PV must always increase BEV use: any
remaining equal-composition result requires the persisted binding/certificate
evidence before research interpretation.

The first fresh rerun from frozen SHA
`fc3f4ba41648d6138c81a59ef6a76a74e094bbff` is retained at
`output/formal_pair_20260802_flat30_composition_search_r2` as **DIAGNOSTIC
ONLY**. Both cases completed 264/264 trips, independent physical validation,
24/24 rolling, and terminal BESS/SOC checks, but the four adjacent targets in
each case were each limited to 4.5 seconds and returned `TIME_LIMIT` with no
incumbent. Consequently the composition artifact remained unresolved and the
BFF artifact contract correctly rejected finalization; the pair was not built
and no cross-weather claim is allowed. The next frozen rerun uses the explicit
25-second target cap recorded by
`stage1_composition_target_time_limit_cap_seconds`, while preserving the same
100-second bounded reserve and all scenario controls.

The second fresh rerun from frozen SHA
`a083919ec679fdec64907ef46ba94cbf2dffc8c3` is retained at
`output/formal_pair_20260802_flat30_composition_search_r3` as **DIAGNOSTIC
ONLY**. The 25-second cap still left all four in-inventory adjacent targets
at `TIME_LIMIT` with zero incumbents in both weather cases. The next attempt
adds partial MIP starts that activate an unused opposite-powertrain vehicle
and retire the source vehicle while leaving all objective, recourse, and
weather controls unchanged. These starts are hints rather than accepted
assignments; unresolved targets continue to block formal release.

The next fresh pair from frozen SHA
`b02859b826165c8a612a81c145eb1b06f24cb7e3` is retained at
`output/formal_pair_20260802_flat30_composition_search_r4` and its ZIP. The
activation/retirement starts produced physically feasible adjacent
compositions `(12,20)`, `(13,19)`, and `(14,18)` in both cases. The selected
sunny candidate is `(14,18)` with 46 BEV trips; the selected rain candidate is
`(12,20)` with 42 BEV trips. Both cases served 264/264 trips, completed 24/24
rolling steps, and passed independent physical validation. PV totals were
614.709375 kWh (sunny) and 101.1143 kWh (rain); Stage 1 allocated
586.4129614696021/101.1143 kWh of renewable energy and
0/392.6302101003947 kWh of grid energy for BEV recourse, respectively.

The pair remains **DIAGNOSTIC ONLY / BLOCKED**. Only three Stage 2 candidates
were evaluated in each case (the formal controller requires at least ten),
the +/-2 composition targets were still unresolved `TIME_LIMIT` results, and
the Stage 1 objective is not an actual-cost objective. Sunny's numeric
residual is approximately zero but fails the actual-cost semantic gate; rain's
solver-minus-canonical residual is `-19.214065002277493` JPY. The observed
sunny-versus-rain BEV difference is therefore a valid physical candidate
observation, not a formal weather-optimality claim.

## Separate controlled tariff sensitivity (2026-07-31)

A user-authorized tariff mutation is a separate experiment from the frozen
PV-only pair. For the requested condition, both scenarios must be freshly
prepared through `POST /api/scenarios/{scenario_id}/simulation/prepare` with
one `00:00--24:00` TOU band at `30 JPY/kWh`,
`grid_flat_price_per_kwh=30`, and `demand_charge_cost_per_kw=0`. The one-band
TOU replacement is required: merely changing the flat-rate field would leave
the inherited TOU schedule effective. Both runs must show 24 canonical price
slots at 30 and 24 demand-charge weights at zero in
`simulation_conditions_tou_prices.csv`; otherwise the result is diagnostic
and must be reported as blocked. This condition changes neither physical grid
limits nor the fleet/PV/service controls, and it must be common to the two
cases so the price-slot hash matches.

The initial tariff attempt at
`output/formal_pair_20260731_flat30_no_demand` is **DIAGNOSTIC ONLY**. Its
canonical tariff rows were correct, but both effective PV profiles resolved to
`6056.25 kWh` and the same profile hash despite distinct PV source labels.
The comparison is therefore invalid and must not be summarized as a tariff or
weather result. The HTTP runner now records the frontend bootstrap response
and sends an explicit one-date PV asset in each normal Prepare request, built
from the frontend depot's physical PV design controls and the separately
hashed date-specific derived capacity-factor curve. A fresh clean-commit pair
is required; the old diagnostic directory remains untouched.

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

The sixth frozen attempt at
`e63224fc2f627197fc6edde2264739eb4f440dc6` is retained under
`output/formal_pair_20260730_diagnostic_attempt6`. Both cases passed the
solver, 24/24 Rolling, independent physical, terminal SOC, accounting,
artifact, controlled-pair, small-oracle, and corrected terminal-claim gates.
It remains diagnostic because the completion audit recorded the size of an
initial ZIP and the runner then rewrote two embedded files and rebuilt a final
ZIP 25 bytes larger. Packaging now finalizes the audit/log before one
temporary CRC-validated archive is atomically promoted, and it no longer
claims a self-referential archive size. A fresh same-SHA HTTP pair is required
to validate the corrected final package.

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
