# Current research release blockers

## 2026-08-11 compact reporting release: progress presentation ready

The accepted current-code pair has now been canonicalized without another
optimization run. `scripts/build_reporting_snapshot.py` reads the final graph
assignment, accepted 24-hour Rolling accounting, physical validation, effective
solver controls and immutable pair manifests, then generates every public
table, workbook sheet and figure from one reporting snapshot. Source-run hashes
are checked before and after the operation and were unchanged.

The derived output is
`output/formal_pair_20260811_flat30_pv1000_bess6000_phase4_2632de9_gap01_progress/release/`
with sibling `release.zip`. All 15 public files record reporting snapshot
SHA-256
`dcd15a8a76c96b663070a7410b2f8fc0c22f9b27f313daab9ce43151106c97ef`.
The release reports the same accepted outcomes as the source pair: high PV
`32 BEV / 0 ICE`, `264 / 0` trips and `644741.923030 JPY`; low PV
`21 / 11`, `91 / 173` and `698419.690050 JPY`. It uses Rolling execution for
all published energy, cost and emissions figures and excludes the internal
search objective and return-leg adjustment.
Both cases reconcile the Solver's requested/effective day-ahead controls at
`3600 s` and `1%`, followed by `24` Rolling steps at `30 s` and `1%` each. The
low-PV raw `objective_limit`/`100%` Gurobi gap is retained beside its independent
`0.399008%` certified gap rather than relabelled `OPTIMAL`.

The compact bundle is `READY_FOR_PROGRESS_PRESENTATION`; every reporting gate,
workbook formula scan, visual-sheet render and stale-warning scan passes. Its
own `research_submission_ready=false` is an explicit scope boundary: this
postprocessor does not assess whether the input assumptions are realistic.
That field does not reverse the source pair's immutable formal attestation and
does not relabel either standalone case. Research-submission claims must still
cite `pair/pair_manifest.json` and separately justify the input assumptions.

## 2026-08-11 current-code progress bundle pair completed: no pair-level blocker

The pair runner now generates a progress-report evidence bundle automatically
after both normal frontend jobs, the pair manifest, case gates and fixed-control
audit exist. The bundle contains seven PNG/SVG comparison figures, six CSV
tables, the complete case/pair gate matrix, links to all ten per-run detailed
figures, a progress-report Markdown file and SHA-256 lineage for every source
and generated artifact. Missing or incomplete progress evidence blocks final
pair packaging, but this reporting gate cannot upgrade solver, physical,
accounting or research acceptance.

The previously pending current-code execution is complete. Frozen SHA
`2632de9962e85138c0fe6e4d3da1c74122c3dfff` was clean before submission and
unchanged/clean after both ordinary frontend HTTP jobs. Each case used fresh
Prepare for the same `2025-08-05` weekday service, 264 trips, 60 active
vehicles, ten chargers, `1000 kW` PV rating, `6000 kWh / 900 kW` BESS with
`3000 -> 3000 kWh`, `30 JPY/kWh` energy price and zero demand charge. The
trip, fleet, initial-state, charger, non-PV asset, tariff and solver-control
hashes match; only the PV profile hash differs (`6056.250` versus
`996.200 kWh`).

High PV uses `32 BEV / 0 ICE` for `264 / 0` trips at
`644741.923030 JPY`, with `155.472886 kWh` grid import, zero fuel,
`77.736443 kg` operational CO2 and a `0.735476%` certified gap. Low PV uses
`21 BEV / 11 ICE` for `91 / 173` trips at `698419.690050 JPY`, with
`124.985104 kWh` grid import, `357.881339 L` fuel,
`987.936116 kg` operational CO2 and a `0.399008%` gap. Both serve `264/264`,
complete `24/24` Rolling, and pass physical/SOC, accounting, provenance,
tariff, solver-control and artifact checks. The exhaustive export has
`70/70` passing case/pair gates.

`completion_audit.json` is `READY`, and `pair/pair_manifest.json` reports
`formal_research_submission_ready=true` with no failed checks. The progress
bundle has 7 PNG/SVG comparison figures, 6 CSV tables and 10 detailed-figure
references. Independent audit confirmed all 128 indexed source/generated
hashes, all 17 rendered figures, both three-sheet workbooks with zero formula
errors, and all 748 ZIP members with no CRC or byte-hash mismatch. Evidence is
under
`output/formal_pair_20260811_flat30_pv1000_bess6000_phase4_2632de9_gap01_progress/`
and its sibling `.zip` archive.

There is no remaining blocker for this pair-scoped 1% controlled-PV result.
The two standalone summaries still retain only
`controlled_counterfactual_pair_not_verified`, which is their intentional
pre-pair state; do not relabel either standalone file as READY. The pair-level
claim is supported by the immutable pair manifest. This documentation update
occurs after the run and does not change the frozen execution SHA.

## 2026-08-10 final clean 1% pair completed: no pair-level blocker

Clean frozen SHA `6bf6bd7eebec06dde1a899bebe5e02f3dc9fd62c` completed both fresh
frontend jobs and the pair postprocessor. Sunny is `32 BEV / 0 ICE`, 264/0
trips, 644,741.923030 JPY, and 0.735476% certified gap. Rain is `21/11`,
91/173 trips, 698,419.690050 JPY, and 0.399008% certified gap. Both are below
the predeclared 1% threshold and pass 264/264 coverage, 24/24 Rolling,
physical/SOC, accounting, provenance, tariff, solver-control, and artifact
gates. The all-BEV empty fuel outputs are valid header-only relations.

`completion_audit.json` is `READY`, with empty `failed_checks`. The pair
manifest accepts the controlled PV sensitivity and reports
`formal_research_submission_ready=true`, with all five formal release checks
passing. The standalone case summaries retain only
`controlled_counterfactual_pair_not_verified`: this is the intentional
pre-pair pending state and is discharged by the immutable pair manifest after
both cases exist. A single case must still not be presented as the verified
pair. There is no remaining blocker for this pair-scoped 1% release-candidate;
the historical 0.1% runs below remain historical and are not upgraded.

## 2026-08-10 all-BEV export gate requires one clean rerun

The fresh 1% calculations at clean SHA `6853edae956c71c3c28ec285660a0f0b7c788e69`
resolve the original fleet-response question at solver level. Sunny selects
`32 BEV / 0 ICE` and all 264 trips are electric at `644,741.923030 JPY` with a
`0.735476%` certified gap. Rain selects `21/11`, with 91 BEV and 173 ICE trips,
at `698,419.690050 JPY` with a `0.399008%` certified gap. Both complete 24/24
Rolling and use the controlled 30 JPY/kWh, zero-demand-charge, 1000 kW PV,
6000 kWh BESS setup.

Release remains `BLOCKED` because the sunny frontend job failed only after
calculation and Rolling: an all-BEV day generated no fuel rows, and the final
artifact gate correctly rejected three zero-byte fuel CSVs as ambiguous. The
export path now writes header-only canonical fuel ledger, fuel timeseries and
fuel summary files for a valid empty relation. This correction does not change
the objective, constraints, tariff, PV profile, seed, or selected composition.
A new clean commit and fresh two-case run are required before pair-manifest or
teacher-release acceptance can be claimed.

## 2026-08-10 1% release-candidate implementation awaits clean pair evidence

The nonterminating full search has been reduced to a bounded completion path.
A weather-neutral exact-Stage-2 neighborhood finds a lower-cost sunny
`32 BEV / 0 ICE` candidate at `644,741.923030 JPY`.  The corresponding rain
search retains the prior cost-minimizing `21/11` incumbent at
`698,419.690050 JPY`; it observes `30/2` as feasible but more expensive.  The
bounded search is upper-bound evidence only and does not certify the maximum
feasible EV count.

An independent continuous powertrain path/source-flow relaxation strengthens
the total analytical lower bound to `640,000.000000 JPY` sunny and
`695,632.938124 JPY` rain on the prior inputs.  Because free energy is bounded
by selected BEV path energy, it no longer subtracts all PV credit from a
hypothetical ICE-heavy solution.  Vehicle identity, path count, timing,
chargers and depot coupling remain relaxed, and the exact LP input is hashed.
The resulting diagnostic gaps are about `0.7355%` and `0.3990%`, below a newly
predeclared 1% target.  A verified integrated start that meets that certificate
can terminate through `BestObjStop` without changing the model objective or
feasible region.

Release remains `BLOCKED` at this point.  These numbers replay old plans and
inputs through a dirty working tree; they are not new formal evidence and do
not retroactively satisfy the historical 0.1% target.  The complete suite
passes (`1260 passed in 61.38s`).  Required next steps are review, a clean
commit, BFF restart, fresh Prepare for both cases, a separately labelled
`--actual-cost-mip-gap 0.01` run, 24/24
Rolling, physical/SOC/accounting/provenance checks, and controlled-pair
manifest acceptance.  No READY claim is permitted before those artifacts
exist.

## 2026-08-10 composition display corrected; new formal evidence pending

The apparent `13 BEV / 19 ICE` sunny/rain equality was caused by reading the
Phase-3 Stage-1 primary candidate as though it were the final integrated
solution.  The completed clean-SHA pair's authoritative Phase-4 incumbents are
`27/5` sunny and `21/11` rain, with 183 versus 91 BEV trips.  The controlled PV
response therefore exists and is already accepted at the pair-comparison
level; it is separate from formal optimality acceptance.

The remaining sunny boundary is not total PV energy.  Sunny imports no grid
energy and curtails 3,606.64 kWh.  Exact `28/4` remains unresolved because two
tested assignments fail Stage-2 chronological SOC/charging recourse and the
Stage-1 exact search has no incumbent, but no composition-wide infeasibility
certificate exists.  Neither “28/4 is impossible” nor “more PV must select
28/4” is currently supported.

The working implementation separates final and Stage-1 composition fields,
adds chronological vehicle-path shortage evidence, scopes vehicle-local IIS
feedback to an exact assignment-pattern cut, and preserves full-assignment
cuts for shared constraints and IIS bounds.  The attempted activity-row
aggregation was removed: it was integer-equivalent but weakened the LP
relaxation.  The clean-SHA `4e0558d` sunny run reached 85.8/92.1 GB Windows
commit (93.1%) and was safely stopped; rain never started.  That partial run is
diagnostic only.  Strong individual implication rows are restored, while MIP
node spill remains configured at 0.5 GB as a branch-tree safety guard.

The restored-row clean SHA `612e4a7` reproduced the same candidate failures,
including a maximum 111.30337352 kWh chronological shortage among the tested
`28/4` duties.  It then reached 96.4% Windows commit during integrated
fixed-dispatch recourse, before branch-tree growth.  Phase 4 now forces dual
simplex for both recourse preflight and final integrated root/node LPs and
sets a 32 GB Gurobi `SoftMemLimit`.  These are weather-neutral exact-search
controls; any `memory_limit` termination remains explicit diagnostic evidence
and cannot satisfy the formal gap gate.

Release remains `BLOCKED`.  The last completed pair still misses the 0.1%
certified-gap target (3.927573% sunny, 2.387096% rain), and the new code still
requires a clean commit, fresh Prepare and a new complete controlled pair.  No
old output may be relabelled as evidence for these changes.  The prior complete
suite (`1248 passed`) validates SHA `4e0558d` before its runtime defect was
observed.  The restored strong formulation passes the complete suite (`1247
passed in 55.79s`); the root-memory correction passes 153 focused regressions
and the complete suite (`1247 passed in 58.22s`).  It still needs a clean
commit and full pair.

## 2026-08-10 witness-cutoff pair: PV response accepted, proof still blocked

Clean frozen SHA `99a2035694fd90fccf42fe8222a4f1d3b344e83e` completed the
full controlled pair at
`output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_witness_99a2035_gap001`.
All pair-comparison checks pass. Sunny uses 27 BEVs / 5 ICE buses and 183 BEV
trips; rain uses 21 / 11 and 91 BEV trips. Both serve 264/264, complete 24/24
Rolling, pass physical and terminal-SOC checks, reconcile accounting and use
the same frozen non-PV control hash. The controlled PV sensitivity is accepted.

The cutoff is verified but does not expand the selected sunny composition.
Easy exact targets through 27 BEVs terminate in about 3.6 seconds, leaving
47.8 seconds for exact `28/4`. That target still has no Stage-1 incumbent; two
complete candidate assignments fail exact Stage 2. These are assignment-level
failures only because no IIS-backed exact-composition infeasibility certificate
exists.

Release remains `BLOCKED`. Sunny certified gap is 3.927573% and rain is
2.387096%, both above 0.1%; raw gaps are 100%. Post-run reporting and candidate
diagnostic fixes require a new clean commit and fresh evidence: the Phase-4
comparison table now reads the integrated certified gap, and internal Phase-3
candidate failures now receive an IIS/path diagnostics directory without
enabling recursive feedback. Focused regressions pass (`35`) and the complete
suite passes (`1242 passed in 64.24s`). The completed SHA-99a2035 artifacts are
not relabelled as results of those later fixes.

## 2026-08-09 exact `28/4` boundary search correction is awaiting evidence

The completed clean-SHA pair proves a PV response through `27/5` sunny versus
`21/11` rain, but it does not resolve exact `28/4`. The exact-composition loop
used each target's full optimization slice after finding a Stage-1 incumbent;
therefore earlier feasible counts consumed time that should have remained for
the harder adjacent boundary. The two `28/4` constructive assignments rejected
by Stage 2 remain assignment-level failures only.

The corrected exact-composition solve stops after its first feasible witness
and passes that unchanged assignment to exact Stage 2. A target without an
incumbent still runs until its allocated limit or a solver-proven infeasible
status, preserving the existing IIS-backed certificate contract. No BEV
minimum, weather preference, trip quota or accounting change is introduced.

Release remains `BLOCKED`. Focused regressions pass (`54`) and the complete
suite passes (`1240 passed in 56.27s`), but the change still needs a clean
commit, fresh Prepare for both cases, and a new controlled pair. Even if it
recovers a different sunny incumbent, both cases must still meet the requested
0.1% certified integrated gap before formal readiness.

## 2026-08-09 adjacent pair responds to PV; proof gap remains

Clean SHA `32e3509cacd6309675bef2e850405e07483b24fb` completed the controlled
pair at
`output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_adjacent_32e3509_gap001`.
The pair is physically and economically valid: both cases serve 264/264, pass
24/24 Rolling and SOC/accounting checks, preserve the frozen SHA and match all
non-PV controls. Sunny selects `27 BEV / 5 ICE` and 183 BEV trips; rain selects
`21 / 11` and 91 BEV trips. The pair-level controlled PV sensitivity is
accepted.

Release remains `BLOCKED` only on integrated proof: certified gaps are
3.927573% sunny and 2.387096% rain against the requested 0.1%, while raw Gurobi
gaps are 100%. The runner's completion audit mislabeled that raw 100% value as
`certified_gap`; the gate now reads the canonical `certified_mip_gap_ratio`.
This reporting correction does not make either case pass and has not yet been
rerun from its own clean commit.

Focused regressions pass (`81`) and the complete repository suite passes
(`1240 passed in 64.68s`). Re-auditing the completed artifacts in memory with
the corrected gate preserves both gap failures at their actual certified
values.

The next optimization boundary is exact `28/4`. The adjacent search reaches
`27/5`, then times out at `28/4` without an incumbent; two constructed `28/4`
assignments fail Stage 2 energy recourse. This is not a composition-wide
infeasibility certificate. Further work must use the recorded SOC/charger
failure evidence to construct a different duty reassignment, not force a BEV
minimum or relabel the target infeasible.

## 2026-08-09 adjacent-continuation correction requires a fresh formal pair

Clean SHA `beb13e303ce272b77caf719f8e745c65c22668cd` did not validate the
cost-ranked search strategy. In its fresh sunny run, exact compositions
`32/0`, `31/1`, `30/2` and `29/3` each used roughly 60 solver seconds without
an incumbent. Only 10.156 seconds remained for `28/4`, although a separate
diagnostic had previously found a physically valid `28/4` sunny candidate.
The selected `27/5` result therefore reflects target-order starvation and
cannot be used to conclude that sunny PV has no further effect on fleet mix.

The correction is weather-neutral: exact targets are traversed by distance
from the primary feasible composition, each direction continues from its last
feasible adjacent MIP start, and the remaining time is shared equally. No BEV
minimum, sunny preference, trip lower bound or weather coefficient is added.
Stage 2 canonical actual cost remains the selection authority and the
unrestricted Phase 4 MILP remains the proof authority.

Focused regressions pass (`80`) and the complete suite passes (`1239 passed in
59.56s`). These code checks do not replace the fresh formal pair.

Release remains `BLOCKED`. The interrupted `beb13e3` rain run and the older
prepared-input diagnostic are not formal pair evidence. Completion still
requires a clean frozen commit, fresh Prepare for sunny and rain, unchanged
non-PV control hashes, 264/264 service, 24/24 Rolling, physical and accounting
validity, and the requested 0.1% certified integrated gap in both cases.

## 2026-08-09 superseded cost-ranked under-search note

The clean `c819e36` cutoff diagnostic did not move Gurobi's raw lower bound in
300 seconds. A one-sided `used BEV >= 32` diagnostic also showed why a BEV
minimum is not a remedy: it retained 19 ICE buses, used 51 total buses, and
optimized a policy-constrained problem rather than the requested cost problem.

The then-actionable defect was exact-composition time allocation. The last
formal pair gave `32/0` only 2.694 seconds and `31/1` only 2.772 seconds. Stage 2
infeasibility of their first reconstructed duties is not an infeasibility
certificate for every assignment at those mixes. The cost-ranked working tree
ordered exact mixes by audited constructive cost. A later fresh run
demonstrated starvation of the reachable adjacent path, so that strategy is
superseded by the correction above. Stage 2 actual cost and the unrestricted
Phase 4 model remain authoritative.

## 2026-08-09 verified candidate rescue; integrated proof still blocked

Clean SHA `96f17e10175d614d29f45ee79df95cf70ff4e6eb` completed
`output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_constructive_96f17e1_gap001`.
Both cases used fresh Prepare, served 264/264, passed physical validation and
24/24 Rolling, reconciled accounting, preserved the frozen Git SHA and matched
all non-PV controls. Pair manifest v2 accepts the controlled PV sensitivity but
sets `formal_research_submission_ready=false`.

The candidate fix is verified. Both cases evaluated complete high-BEV starts
through Stage 2: 32/0, 31/1, 30/2, 29/3 and 28/4 were infeasible for their
specific reconstructed duties. Sunny selected 27/5 and rain selected 21/11.
These Stage 2 failures are not global infeasibility certificates for every
assignment with the same counts.

Release remains `BLOCKED`. Sunny certified gap is 3.927573% and rain is
2.387096%, versus the requested 0.1%; both raw gaps are 100%. The integrated
model has 776,752 variables and 1,929,173 constraints and did not finish its
root node in 3,600 seconds. The exact failed checks are
`sunny:certified_gap_at_most_requested`,
`rain:certified_gap_at_most_requested` and
`pair:pair_formal_research_submission_ready`.

The current working-tree correction uses the independently feasible
fixed-recourse objective as an explicit integrated objective upper bound and,
only when all cost terms are nonnegative, as a used-vehicle-day upper bound.
It also changes a verified-start search from incumbent-heavy heuristics to a
weather-neutral lower-bound profile. These constraints preserve the seed and
all improving solutions; they do not force BEV use or encode weather direction.
The automatic cutoff is limited to canonical-cost-only primary runs and does
not alter partial-service or maximum-EV lexicographic policy scenarios. The
vehicle-day cap is omitted when that cost component is disabled.
Focused regressions pass (`41`) and the full suite passes (`1237 passed in
54.15s`). A clean commit and a fresh pair are still required.

## 2026-08-09 superseded pre-run candidate-rescue note

The current correction addresses the unresolved 28--32-BEV search boundary
without forcing BEV use. A complete discrete composition MIP start is retained
for Stage 2 only when its short Stage 1 target solve returns no incumbent. It
must prove exact trip/path coverage first and then pass unchanged SOC, charger,
PV/BESS/grid, accounting and independent physical checks. Solver-found
incumbents and IIS-backed infeasibility certificates keep precedence.

Integrated optimality telemetry is also split into immutable Gurobi raw
bound/gap and a separately named certified bound/gap based on the existing
integer-valid analytical objective floor. The formal gap gate may use the
certified value; it may not overwrite or conceal a 100% raw gap. Phase 3's
Stage 1 certificate remains distinct from Phase 4 integrated certification.

The full code suite passes `1233` tests. Release nevertheless remains
`BLOCKED`: these changes have not yet been committed and rerun through fresh
frontend Prepare from a clean frozen SHA. Completion requires both sunny and
rain to serve 264/264, pass physical validation and 24/24 Rolling, reconcile
canonical accounting, preserve all matched non-PV controls, and meet the
requested 0.1% certified integrated gap. If higher-BEV constructive candidates
fail Stage 2, the failure evidence must identify SOC, charger, trip-chain or
energy-recourse causes rather than treating target-MILP timeout as infeasible.

## 2026-08-09 current controlled pair: response verified, optimality blocked

Clean frozen SHA `93d122e1fc929d4833f2997560fa16cf7523e96d`
completed the fresh PV-only controlled pair at
`output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_pairhash_93d122e_gap001`.
All declared non-PV controls and the comparison hash match. Both cases served
264/264 trips, passed physical validation, completed 24/24 Rolling, returned
BEV/BESS SOC, and reconciled the solver objective to executed-day accounting.

The feasible response is now explicit: sunny used 27 BEVs / 5 ICE buses and
183 / 81 trips; rain used 21 / 11 and 91 / 173. Sunny generated 6,056.25 kWh,
bought zero grid energy, and curtailed 3,606.64 kWh. Rain generated 996.2 kWh
and bought 124.985 kWh. This supports a controlled PV-sensitivity claim, not
an optimal-composition claim.

Release remains `BLOCKED` because both integrated runs reached 3,600 seconds
with a 100% raw gap instead of the requested 0.1%. Sunny composition search
found physically feasible rows through 27 BEVs and decreasing cost through
that boundary; 28--32 were time-limit unresolved, not certified infeasible.
Thus 27 is an observed search frontier, not a proven physical or economic
maximum.

Post-run review also found that pair manifest v1 incorrectly wrote
`formal_research_submission_ready=true` while the completion audit correctly
blocked both missing gap certificates. Manifest v2 separates controlled-pair
acceptance from formal readiness and fails the latter closed unless both runs
record feasible incumbents and `mip_gap_target_met=true`. This reporting fix
has unit and diagnostic rebuild evidence; it does not relabel the frozen
SHA-93d solver outputs as evidence for the subsequent code commit.

## 2026-08-09 Phase 4 seed recourse was starved by model-build wall time

The fresh sunny formal attempt from clean SHA
`bf3fc2907fe852b39aa303272287e2133bd628a9` is preserved at
`output/2026-08-09/run_20260809_0608` as **DIAGNOSTIC ONLY**. Its Stage 1
composition search repaired the earlier regression and recovered assignment
incumbents from 7 through 27 used BEVs. It did not produce a physical
day-ahead result: every Stage 2 candidate was
`not_run_feedback_budget_reserved`, the Phase 3 seed selected no candidate,
Phase 4 received no verified start and finished after 3,600 seconds with zero
incumbents and 264 unserved trips. Rolling correctly refused to start.

The root cause is a budget-semantics defect. Gurobi's per-model `TimeLimit`
does not include Python-side construction of the many exact-composition
models, while the Phase 3 feedback deadline was a single 600-second wall
clock. Model construction therefore spent the time intended for the explicit
120-second Stage 2 solver budget. The correction keeps the declared 480/120
solver limits unchanged and adds a separate deterministic wall allowance of
10 seconds per reachable requested alternative, capped at 600 seconds. Solver
and wall budgets are now distinct audited fields.

Stage 2 candidate evaluation is also reordered by the weather-aware Stage 1
relaxed objective, then candidate hash. The candidate set and feasible region
are unchanged, and physical canonical Stage 2 cost remains authoritative. This
prevents the 27-BEV sunny candidate—the lowest relaxed-cost row—from being
last solely because symmetric deltas were generated from the primary count.

The automatically started rain attempt was stopped before code changes; it is
not pair evidence. Release remains `BLOCKED` until the budget/order correction
passes tests, is committed cleanly, and a fresh controlled pair completes all
day-ahead, Rolling, physical, accounting, provenance, control-match and 0.1%
gap gates. A recovered high-BEV incumbent alone is not an optimality result.
The current code suite passes `1230` tests; that closes the code-regression
check only, not the fresh-run or optimality blockers.

## 2026-08-09 integrated optimality and composition coverage remain blocked

Frozen SHA `14bbcfa1ba97889674e113eae44bfa3ec71577e0` completed the
fresh-Prepare controlled pair at
`output/formal_pair_20260809_flat30_pv1000_bess6000_phase4_proof_14bbcfa_gap001`.
Both cases served 264/264, passed independent physical validation, returned
BEV/BESS SOC, completed 24/24 Rolling, and reconciled solver objective to
executed accounting. They are valid physical candidates, not optima. Both full
integrated models processed one node, retained native best bound zero, and
stopped at the 3,600-second limit with a 100% raw gap.

Both cases returned the same 16-BEV / 16-ICE, 58 / 206-trip incumbent at
704,401.909629 JPY. This does not refute the sunny-PV hypothesis. Sunny
generated 6,056.25 kWh and curtailed about 5,344.07 kWh. Rain still generated
996.2 kWh, while the selected low-BEV assignment needed only 650.493 kWh of
bus charging; both therefore bought zero grid energy. A weather response can
appear only after evaluating higher-BEV assignments.

The seed composition loop found physically feasible 7--16 BEV compositions.
Every 17--32 target received about 3.4--3.8 seconds and ended time-limit with no
incumbent; none was certified infeasible. Exact activation-prefix symmetry had
incorrectly influenced which duty was offered for powertrain replacement: the
suffix vehicle ID, rather than the easiest identical-ICE duty, was retired.
The working tree now selects duties by energy suitability and only afterwards
permutes exact-identical IDs onto the prefix. This is a symmetry-equivalent
relabeling, not a weather/BEV preference or feasible-set change.

The proof-focused `MIPFocus=3`, `Heuristics=0.01` run did not advance the root
bound and preserved the weak seed. The working tree restores the neutral
`MIPFocus=1`, `Heuristics=0.5` incumbent-improvement profile, keeps the audited
analytical lower-bound floor, aligns the formal runner with the four-thread
runtime contract, and propagates Phase 3 candidate/recourse evidence into the
Phase 4 same-assignment audit. An eight-thread attempt remains diagnostic only.

Release remains `BLOCKED` until the correction is committed, both cases are
freshly prepared and rerun from a frozen clean SHA, the composition audit
covers the relevant higher-BEV alternatives, and the requested 0.1% gap plus
all physical, Rolling, provenance, accounting, and pair-control gates pass. A
better time-limit incumbent alone does not close this blocker.

## 2026-08-08 inventory-span certificate producer/validator correction

The first inventory-span rerun found physically valid compositions from 7 to
27 used BEVs, but its pair builder correctly rejected the exported certificate:
the large symmetric radius also persisted impossible negative count targets.
The producer now omits negative targets while retaining non-negative
outside-inventory records as explicit boundary evidence; the fail-closed
validator remains unchanged. Results from the pre-fix SHA remain diagnostic
pair evidence only; a fresh clean-commit pair is required for release.

## 2026-08-08 controlled pair outcome and remaining optimality blocker

Clean commit `4cb571ade840d9147dd3c91d00718dfbdc531163` completed the
controlled frontend pair at
`output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_radius10_4cb571a_gap001`.
Sunny used 23 BEVs / 9 ICE buses for 121 / 143 trips at 685,663.511395 JPY;
rain used 21 / 11 for 91 / 173 at 698,419.690050 JPY. Both served all 264
trips, passed independent physical validation and 24/24 Rolling, and matched
the canonical executed accounting total exactly. All non-PV pair controls
matched and the PV profiles differed as declared, so the pair is accepted for
controlled PV sensitivity.

This pair demonstrates the expected direction without policy bias. Rain used
all 996.2 kWh PV plus 124.985 kWh grid-to-bus energy; its candidate cost was
lowest at 21 BEVs and rose at 22 and 23. Sunny used 1,563.002 kWh from
6,056.25 kWh PV with no grid purchase, and its cost continued falling to the
23-BEV search boundary. Thus the earlier identical 18-BEV result was caused by
candidate-search truncation. It was not evidence that additional sunny PV had
no dispatch value.

Release remains `BLOCKED`: both integrated models processed one node and ended
at 100% gap, so neither composition is globally certified. The latest run also
showed that fixed radius ten was still unsafe because the primary composition
moved from 18 to 13 BEVs. The working tree replaces that fixed radius with a
selected-inventory-scaled symmetric span and makes formal control audit fail
closed when the span is truncated. Fresh clean-commit execution is required
before that follow-up correction can become current formal evidence.

Status date: 2026-08-08
Code status: clean commit `b8793f3` produced physically valid, weather-
responsive sunny/rain incumbents, but formal release remained blocked by the
requested 0.1% optimality gap plus three evidence/accounting defects. Commit
`3e49cff` fixed those evidence/accounting defects; sunny run
`output/2026-08-08/run_20260808_1126` verified exact reconciliation and
controls, but an all-budget bound-focus profile regressed to the 15-BEV seed
and 100% gap. The rain job was intentionally stopped and is not pair evidence.
Clean sunny run `output/2026-08-08/run_20260808_1300` then proved forced
`Symmetry=2` was also a regression: 18 BEVs / 14 ICE buses, 59 / 205 trips and
100% gap. It also exposed that accepted Rolling hard-coded
`objective_is_actual_cost=false` despite a `1.16e-10 JPY` numeric residual.
The subsequent clean `b64bedb` pair completed both jobs with valid physical
and Rolling evidence, but both returned the same 18-BEV / 14-ICE, 59 / 205-trip
incumbent at 100% gap. That incumbent uses only about 714--716 kWh of PV input,
so rain's 996.2 kWh is already sufficient. Radius five could not move from the
primary 18-BEV seed to the known lower-cost 25-BEV sunny composition; this is
candidate-search truncation, not evidence that sunny PV has no value. The
working tree expands the neutral exact neighborhood to +/-10, propagates the
seed composition certificate into Phase 4, and preserves the verified actual-
cost contract through the BFF cost bridge. Phase 3 remains non-actual-cost.
The pair runner's stale 10-candidate/radius-2 control expectation is also
updated to the server's 21-candidate/radius-10 profile.
The focused suite passes 114 tests and the complete suite passes 1,220 tests.
These changes are not yet clean-commit formal evidence. Release remains
blocked pending a new frozen commit, fresh Prepare, both completed
frontend jobs, accepted physical/Rolling/accounting gates and honestly reported
achieved gaps.

## 2026-08-08 accounting and optimality-certificate blocker

The clean pair at
`output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_finalslot_b8793f3_gap001`
is the current physical baseline. Sunny used 25 BEVs / 7 ICE buses for 156 /
108 trips; rain used 15 / 17 for 48 / 216. Both cases served all 264 trips,
returned BEV and BESS SOC to target, passed physical validation, and completed
24/24 Rolling. This confirms that 1,000 kW PV changes the integrated dispatch;
it does not prove either incumbent globally optimal.

Formal evidence then failed for reasons distinct from physical feasibility.
The solver/evaluator charged a hard-coded per-cycle degradation proxy while the
canonical ledger correctly used the scenario's zero JPY/kWh coefficient. The
Phase 4 plan omitted the effective one-thread/BestObjStop controls; the BFF
discarded its elapsed-time fallback before writing solver settings; Rolling
similarly omitted its applied thread count. Finally, the pair builder demanded
a Stage-1 composition-search artifact from a solver that has no Stage 1.

The current correction keeps one cost definition across solver, evaluator and
ledger, carries actual controls and runtime into artifacts, and recognizes
composition only when the full integrated successor network meets its requested
global gap. It does not waive the gap: sunny previously stopped at 5.1337% and
rain at 100%. A verified integrated incumbent now receives one uninterrupted
incumbent-and-bound search using the profile that previously improved the
sunny composition. Release remains blocked until a fresh clean run actually
reaches 0.1% or is honestly retained as a non-optimal diagnostic candidate.

## 2026-08-08 final-slot and composition-resolution blocker

The clean frontend pair at
`output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_fullscope_223c9f1`
is diagnostic failure evidence, not an accepted weather pair. Sunny found a
25-BEV / 7-ICE, 164 / 100-trip incumbent with zero grid import, 6,056.25 kWh
PV, 1,923.93 kWh BESS-to-bus energy and 3,851.51 kWh curtailment. It then
failed canonical postsolve validation: slot 23 lacked charging eligibility
rows and the terminal expression double-debited the pre-23:00 share of three
late trips. Rolling correctly did not start. Rain retained a 15-BEV / 17-ICE,
48 / 216-trip incumbent, passed physical validation and 24/24 Rolling, but
finished at time limit with raw gap 100% and no useful lower bound.

The current correction covers the final slot with the same no-charge-during-
trip, at-home, charger-power and session-start constraints as all earlier
slots. Terminal SOC now debits only the trip-energy fraction belonging to the
terminal slot. BESS terminal deviation evidence comes from the solved terminal
SOC trace. None of these changes weakens turnaround, trip coverage, SOC,
charger or return-to-initial requirements.

The old 5% integrated gap admitted approximately 32,101 JPY of sunny objective
uncertainty, roughly the whole 31,701 JPY ICE fuel component. It therefore
could not answer how many additional BEVs were cost-minimizing even after the
PV signal increased BEV use. The formal actual-cost runner and its audit now
request 0.1%. A time-limit incumbent that misses that target remains useful as
a physical candidate but cannot close the optimality or teacher-release gate.

This blocker closes only after the corrected clean SHA produces fresh sunny
and rain inputs and artifacts with 264/264 coverage, physical terminal BEV/BESS
balance, accepted 24/24 Rolling, exact source provenance, solver/accounting
reconciliation, unchanged Git state, and either the requested 0.1% certificate
or an explicit non-optimal candidate classification.

## 2026-08-08 Phase 4 feasible-incumbent remediation status

The clean `e071446` pair proved that submitted Phase 3 `Start`
values were not an integrated-feasibility certificate. A later non-formal
264-trip diagnostic (`output/2026-08-08/run_20260808_0601`) now reaches a
feasible integrated fixed-dispatch recourse and complete 776,752-variable
warm start after correcting a false coarse-slot charging/refueling conflict.
It also closes an integrated terminal-SOC metadata omission and distinguishes
a physically valid time-limit incumbent from an optimality result. Relevant
focused tests pass (`79 passed`), the complete repository suite passes
`1209 passed`, and `compileall`/`git diff --check` pass. The diagnostic used a
dirty tree, a reused prepared input, `research_run=false`, and a one-second
unrestricted solve, so it is **not** research evidence. A fresh Prepare from a
clean frozen commit and its sunny/rain per-run/pair gates remain authoritative.

The clean frontend pair at commit
`e071446cb346092719a3103e81026bcb02d82a21`, stored under
`output/formal_pair_20260808_flat30_pv1000_bess6000_phase4_neutral_seed_e071446`,
did **not** produce a Phase 4 result. Sunny and rain each had an accepted,
physically valid Phase 3 seed but `NO_VALID_INCUMBENT`, 0/264 served trips and
zero integrated incumbents. Those diagnostics must not be interpreted as
equal EV use or as an optimized weather comparison.

The current working tree addresses the no-incumbent mechanism seen in the
clean 2026-08-03 Phase 4 pair. A frontend Phase 4 request now performs a
bounded Phase 3 seed solve on the same canonical problem. Only an exact
full-trip, Stage-2-feasible, independently physically valid plan is eligible.
No prior-run JSON, stale prepared input, fallback plan, post-solve repair, or
weather-direction preference enters the hand-off.

The corrected integrated solver first receives the dispatch decisions, fixes
them only for a bounded recourse solve, and rebuilds charger selection, SOC and
PV/BESS/grid flows under the exact integrated constraints. A feasible recourse
is promoted to a complete all-variable start; the dispatch bounds are restored
before unrestricted optimization. A proven infeasible recourse records IIS
constraint and variable-bound evidence. Submitted Stage 2 values alone are no
longer reported as an applied integrated warm start.

The formal actual-cost frontend path now uses a 600-second neutral seed
(480 seconds Stage 1, 120 seconds Stage 2), a 300-second integrated recourse
preflight, and then a 3,600-second unrestricted integrated solve. The complete
4,500-second maximum and all seed/preflight controls are
persisted in the comparison-control hash. Automatic `used BEV >= K` frontier
injection is disabled: under a time limit it would be a directed incumbent,
even though it does not change the final objective. The seed uses only the
primary candidate and symmetric adjacent-composition search. The formal
integrated MIP gap target is reduced from 10% to 5%, preventing the first
13-BEV seed from satisfying the stopping rule solely because its cost is
within about 9.5% of the 640,000 JPY vehicle-day lower bound.

Seed provenance no longer depends on optional candidate-pool metadata. The
actual assignment, charger/source decisions, vehicle SOC, depot flows, and
BESS trace are fingerprinted with SHA-256. Missing vehicle/BESS SOC slots or a
declared seed that is not loaded into the integrated model now fail the core
per-run research gate as well as the pair runner.

This implementation does **not** yet discharge the release blocker. Focused
tests prove the small-model hand-off, bound restoration, IIS audit and
actual-cost reconciliation, but the
264-trip full-network model must be run from a fresh Prepare and clean frozen
commit. Release remains **BLOCKED** until that run has a physically valid
incumbent, exact source provenance, terminal energy balance, solver/accounting
agreement, accepted Rolling chain, unchanged Git state, and an honestly
reported achieved gap. A time-limit incumbent remains a feasible candidate,
not a global-optimality result.

The latest full-scope diagnostic narrows that blocker. Fixed-dispatch recourse
is now feasible in about 0.8 seconds; all 264 trips are served; independent
trip, transition, SOC-bound, BESS, contract and charger-concurrency counters
are zero; 15 used BEVs have explicit initial/target/terminal SOC records; and
the canonical objective residual is numerically zero. The remaining release
work is a clean formal pair, adequate unrestricted search, accepted Rolling,
and pair-level controlled-counterfactual verification. None of those gates is
waived by the diagnostic.

## 2026-08-07 clean high-PV BEV-frontier result

A fresh frontend HTTP pair now exists at
`output/formal_pair_20260807_flat30_pv1000_bess6000_phase3_frontier_head`,
frozen at clean commit `e94c8154cdcb566cb298a2a8a92ef14b2d1a5f7a`.
Both cases use the saved 1,000 kW PV rating, 6,000 kWh / 900 kW BESS,
3,000 -> 3,000 kWh stationary inventory, flat 30 JPY/kWh grid energy, zero
demand charge, and the same 32-bus used-fleet size. The 20,000 JPY coefficient
is explicitly declared as a fixed vehicle-day cost for this sensitivity.

All 21 `used BEV >= K`, `K=15..35`, targets resolve. High PV selects a
physically validated 27 BEVs / 5 ICE buses with 183 / 81 trips and
666,164.082366 JPY/day. The low-PV counterfactual selects 21 BEVs / 11 ICE
buses with 91 / 173 trips and 698,469.250509 JPY/day. Both serve 264/264
trips, pass terminal BEV/BESS energy and independent schedule validation, and
complete accepted 24/24 Rolling. The controlled comparison holds all audited
non-PV inputs fixed (`comparison_control_hash =
8a09ea3a3017f8e6fd4caf64fa56de0ff2ff303735d7d13e10e10d5bb4df676f`).
Relative to low PV, high PV uses six more BEVs and 92 more BEV trips while
reducing canonical operating cost by 32,305.168143 JPY/day (4.625%) and
operational CO2 by 545.342135 kg/day (55.155%).

This establishes a high-BEV, lower-operating-cost feasible frontier witness
and overturns the earlier inference from the local 11--15 BEV candidate pool.
It does **not** discharge teacher release. Phase 3 remains a two-stage proxy,
not the integrated canonical actual-cost objective. The high-PV numeric
solver/accounting residual is zero but `objective_is_actual_cost=false`; the
low-PV residual is -49.560460 JPY. Consequently the pair manifest and
completion audit remain **BLOCKED** and the result must not be described as an
integrated global optimum.

The 1,000 kW input is also an expanded-site/off-site high-PV sensitivity. Its
reverse audit requires 5,000 m2 installable panel area and about 14,285.7 m2
depot area under the saved assumptions, versus the stored 1,450 m2 site area.
The reported daily total excludes PV/BESS CAPEX, financing, and replacement;
it is not a lifecycle-cost result. The experiment ZIP has 536 entries and
passes `ZipFile.testzip()`.

## 2026-08-07 branch integration status

Local `main` now contains the Phase 3 composition/PV-rated-output lineage and
the powertrain-sensitive dispatch-audit lineage. Conflict resolution preserved
the explicit-zero Quick Setup fix and the pre-solve formal Git gate. Saved
`pv_capacity_kw` remains the authoritative optimization input; reverse
area/capacity values remain derived audit fields. No Prepare or optimization
run was performed during integration, so no older artifact is promoted to
evidence for this tree and teacher release remains **BLOCKED**.

## 2026-08-07 PV/BESS and optimization-control bug closure

The current tree closes the defects found in the saved-scenario-to-solver path:
Solcast profiles now conserve daily energy when resampled from 60-minute data;
depot energy-asset updates preserve omitted fields while honoring explicit
`false`, zero, and empty-curve values; PV rated-output changes rebuild the
derived curve and reverse area/capacity audit fields; invalid PV/BESS values no
longer enter the canonical problem through silent coercion; and demand charges
are consistently billed as the sum of per-depot meter peaks in the integrated
model, the two-stage recourse model, and canonical accounting.

Quick Setup now round-trips the Stage 1 candidate/composition/frontier controls
and the Phase 4 actual-cost/utilization controls exposed by the backend. The Tk
payload normalizes mutually exclusive settings instead of sending contradictory
states, and vehicle-timeline export failures are logged rather than silently
discarded. Focused regressions cover the repaired contracts, and the complete
suite passes (`1196 passed`).

No Prepare or optimization run was performed while the tree was dirty, and no
pre-change prepared input or output is valid evidence for this implementation.
The subsequent frozen-commit frontier pair is recorded above. Teacher release
remains **BLOCKED** because its Phase-3 objective/accounting gates fail; a
future integrated actual-cost run must still satisfy every per-run and
pair-level formal gate.

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

## 2026-08-09 Phase 4 PV1000 pair status

The clean-SHA `b29c6e0` pair completed both day-ahead and 24/24 Rolling cases
with 264/264 trips, no fallback, no successor pruning, valid physical checks,
and reconciled executed-day accounting. The observed feasible incumbents were
27 BEVs/5 ICE buses (sunny) and 21 BEVs/11 ICE buses (rain). This is useful
diagnostic evidence that assignment now responds to PV availability.

The pair is still `BLOCKED` for research release:

- both integrated runs reached the 3,600-second limit with a raw gap of 100%,
  not the requested 0.1%; and
- the `b29c6e0` pair manifest falsely rejected fixed controls because its hash
  included actual seed runtime and the realized Stage 2 starting budget.

The latter acceptance bug is fixed after that run by excluding observed
runtime telemetry from the fixed-control hash while preserving it in per-run
audits. A fresh clean-commit pair is required; the older outputs must not be
relabelled as evidence for the repaired commit. Even after a successful pair
manifest, the 0.1% gap remains a separate blocker.

## 2026-08-10 current Phase 4 PV1000 pair status

This section supersedes the stale statements above that a repaired-hash fresh
pair is still absent. Frozen clean SHA
`06ae09218be99ca47b951dcf6ddad886056b0ad6` completed both normal frontend
cases and assembled
`output/formal_pair_20260810_flat30_pv1000_bess6000_phase4_06ae092_gap001`.

Verified now:

- same 2025-08-05 weekday service and matching non-PV controls;
- 1,000 kW PV rating, 6,000 kWh BESS, 30 JPY/kWh energy charge, and
  0 JPY/kW demand charge;
- 264/264 trips, no fallback, no post-solve repair, no successor pruning;
- 24/24 Rolling, valid physical schedule and terminal SOC, complete artifacts,
  and accounting reconciliation in both cases;
- controlled-PV comparison accepted under control hash
  `32a67fadd0e94f238407bea9160c1f96b0b2451ad18f15beb7b91c7ac012026d`;
- high PV used 27 BEVs/5 ICE buses for 183/81 trips; low PV used 21/11
  for 91/173 trips.

Still blocked:

- high-PV certified gap is 3.9276% and low-PV certified gap is 2.3871%,
  versus the predeclared 0.1% target; and
- therefore `formal_research_submission_ready=false`, even though
  `accepted_for_controlled_pv_sensitivity_comparison=true`.

The high-PV incumbent curtailed 3,606.64 of 6,056.25 kWh, so the observed
27-BEV plateau is not an energy-supply shortage. Examined 28--32 BEV candidate
assignments failed exact recourse on vehicle-local depot-presence,
charge-power, and terminal-SOC constraints. That explains the examined
candidate failures but is not a proof that every assignment with 28 or more
BEVs is infeasible; the remaining MILP gaps prohibit that claim.
