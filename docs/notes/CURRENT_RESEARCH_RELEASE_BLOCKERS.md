# Current research release blockers

## 2026-08-26: SUNNY/RAIN aggregation attempt stopped at `FAIL_CORRECTNESS`

Frozen SHA `2fe63300270266fa6a87970330ac2f3a493b873b` Fresh Prepared both
scenarios successfully and began the required first SUNNY `A`/`B` pair at
`output/diagnostics/pure_ice_weather_ab_2fe6330_20260826/`. This is **not** a
completed SUNNY pair and it is **not** a SUNNY/RAIN A/B result:

- The discrete SUNNY `A` child materially served 264/264 trips and recorded
  physical validation, 24/24 Rolling, and accounting as accepted. It is still
  diagnostic-only because the request's one Gurobi thread was server-overridden
  to four by the reachable BFF interactive worker. Its `solver_settings.json`
  records `requested.gurobi_threads=1`, `effective.gurobi_threads=4`, and
  `override_applied=true`; its 71.061-second solver time and 9.5213476%
  certified gap cannot be compared under the declared one-thread protocol.
- The following pure-aggregate SUNNY `B` child ended
  `TIME_LIMIT_WITHOUT_VALID_SOLUTION`: it exported no duties, left 264/264
  trips uncovered, and did not start hourly Rolling. It has no solver-native
  aggregate `applied=true`/one-to-one recovery evidence. This independently
  fails coverage, Rolling, and aggregate-recovery gates.
- No RAIN child was started. Completed pair counts are SUNNY `0/5` and RAIN
  `0/5`; runtime, structural, cost, PV/BESS, weather-effect, and certified-gap
  comparisons are all **not available**. Aggregation remains default-OFF and
  the research release remains **BLOCKED**.

The preserved inputs/results are respectively SHA-256
`E32E7724F4FECEC2502252E7D8C1D7B0F7C8A1CD691B0AA1C284B6838219440D`
(`preparation/fresh_prepare_manifest.json`),
`07E0EB83E16765B25A385B9FFF69C279A093A626E73C4C6324D72348AD913AB5`
(SUNNY `A` `case_metrics.json`),
`16AA6E966B638A21BFEEFA0F973478D1C1FFE2B36B7FF7645D59816690D713AC`
(aggregate source-run `solver_result.json`), and
`907F55427E458CEF52B7C6E8232AF21D0B971AD5F4E96E0D925649E57EB16652`
(`assignment_validation_diagnostics.json`). The original coordinator did not
finalize its terminal status when a child process raised; the narrow follow-up
now persists `child_failure.json`, finalizes `FAIL_CORRECTNESS`, and stops the
remaining schedule. It does not replay or relabel this failed run.

The direct blockers before a new clean-SHA attempt are: (1) use a reachable
non-interactive/batch execution path that attests the requested one-thread
control instead of the BFF's four-thread interactive override; and (2) make
the pure-aggregate child obtain a valid 264-trip day-ahead result and emit the
required exact recovery audit. Re-run Fresh Prepare and the entire sequence
only after those narrow fixes, their focused tests, documentation, and a new
clean frozen commit/tag; do not resume this directory.

## 2026-08-26: Current-SHA SUNNY/RAIN aggregation evidence is pending

The recovery-gated implementation has a new bounded coordinator,
`scripts/run_pure_ice_aggregation_weather_ab.py`, but **no current-SHA
SUNNY/RAIN artifact exists yet**.  The historical one-scenario A/B measurements
remain diagnostic-only and cannot be relabelled as the requested two-scenario
evidence.

The pending protocol fixes SUNNY `771d115b-75b0-49f7-a7f0-25f259a2cd21` and
RAIN `b23fd26c-1233-4c73-bb9e-bdb8b1584760`, a 264-trip `tsurumaki`/`WEEKDAY`
scope, Fresh Prepare, the materialized `scenario_fleet_contract_v2`, 15-minute
internal slots, 60-minute Rolling, one thread, disabled BestObjStop and
powertrain selector, and the same seed/gap/stage caps.  RAIN keeps the
established fixed-WEEKDAY timetable with 2025-08-10 weather/PV provenance.
Only weather-linked/PV input hashes may differ between scenarios.

The coordinator now performs Fresh Prepare through the normal BFF endpoint,
records BFF runtime-Git attestation plus exact Prepare request/response, and
stores a fail-closed preflight artifact if those inputs are invalid or differ
outside weather/PV content.  The 24-hour clock starts before Fresh Prepare;
there is still no current-SHA solver-execution artifact and thus no new A/B
result.

At frozen SHA `d8cfcd2`, both Fresh Prepare responses were ready at 264 trips
but the coordinator stopped before any solver child because its initial
preflight checked for a serialized `scenario_fleet_contract_v2` in the
prepared JSON.  That assumption was incorrect: the canonical contract is
resolved from the materialized Prepared fleet by the problem builder and
persisted per solver run.  The preserved artifact
`output/diagnostics/pure_ice_weather_ab_d8cfcd2_20260826/` is therefore a
`FAIL_CORRECTNESS` protocol-preflight result, not research evidence.  The
narrow repair records the resolved pre-solve contract hashes and requires each
child's solver-native fleet contract to match before it can count toward A/B.

The same fail-closed audit found inherited RAIN differences in objective preset,
vehicle-day-cost semantics/value and diesel price.  The next fresh Prepare
explicitly pins those to the SUNNY control values; only named PV-curve/date
leaves are exempted, and any PV price/asset-cost divergence remains a blocker.

The immediate `1524a50` reattempt again Fresh Prepared both 264-trip inputs
but stopped before a solver child when an explicit zero
`stage1_composition_search_radius` was erroneously treated as absent.  This is
another preserved `FAIL_CORRECTNESS` preflight artifact at
`output/diagnostics/pure_ice_weather_ab_1524a50_20260826/`, not A/B evidence.
The next frozen attempt uses the direct `None`-versus-zero correction with a
focused regression test.

Five interleaved AB/BA pairs per scenario are required before any runtime
conclusion.  Any coverage, physical, Rolling, accounting, no-fallback/no-repair
or aggregate recovery failure is `FAIL_CORRECTNESS`; fewer than five completed
pairs before the 24-hour cutoff is `INTERRUPTED` and **DIAGNOSTIC, NOT USED FOR
RESEARCH CONCLUSIONS**.  In every outcome the release remains **BLOCKED**, and
aggregation must remain off in normal settings until both scenario artifacts
meet their stated gates.

## 2026-08-24: Aggregate bound-focus diagnostic rejected; profile search exhausted

Clean tag `thesis-aggregate-bound-focus-21e2649` / SHA
`21e2649055771563a12f2739b3a6c69427304b62` ran the pure-aggregate
`bound_focus` single diagnostic at
`output/diagnostics/pure_ice_aggregation_bound_focus_21e2649_20260824/`.
Only Gurobi `MIPFocus=3` and `Presolve=2` were non-default, with automatic
cuts; the model, objective, prepared input, seed, threads, caps, recovery,
and gates were unchanged. Frozen-request/BFF provenance and all three
diagnostic artifact hashes pass.

The run served 264/264 trips, passed physical validation, 24/24 Rolling,
accounting reconciliation, and no-fallback/no-repair checks. Stage 1
time-limited at a 55,507.320152-JPY incumbent and 52,749.163582-JPY bound,
or **4.968996%**, above 1% and identical to the rejected `root_cut_focus`
candidate. The default, `incumbent_focus`, `root_cut_focus`, and `bound_focus`
profiles now have frozen aggregate measurements; none closes the gap. This is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**. Further solver-profile
proliferation is not justified; a new run requires a separately proved,
feasible-set-preserving mathematical strengthening and focused exact/small-MILP
regression. The 1% and independent-review gates remain **BLOCKED**.

## 2026-08-24: Aggregate root-cut-focus diagnostic rejected, not release evidence

The pure-aggregate representation was measured once with the existing
`root_cut_focus` controls (`MIPFocus=3`, `Presolve=2`, `Cuts=3`) at clean tag
`thesis-aggregate-root-cut-focus-fabd665` / SHA
`fabd6650efabd152f0cd2e25f9ba6d976b28f28d`. It is an internal-solver-control
diagnostic only: it changes no model row, variable, objective, prepared input,
seed, threads, time limits, recovery rule, or acceptance gate.

The artifact at
`output/diagnostics/pure_ice_aggregation_root_cut_focus_fabd665_20260824/`
passes frozen-request/BFF provenance and all three diagnostic artifact hashes.
It served 264/264 trips, passed physical validation, 24/24 Rolling, accounting
reconciliation, and no-fallback/no-repair checks. Stage 1 was time-limited at
a 55,507.320152-JPY incumbent and 52,749.163582-JPY certified bound, a
**4.968996%** gap. This is above 1% and worse than the default aggregate A/B
median, so it rejects `root_cut_focus` as a gap-closing path. The artifact is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**; the 1% and independent-review
gates remain **BLOCKED**.

## 2026-08-24: Aggregate incumbent-focus diagnostic rejected, not release evidence

The exact pure-ICE aggregate representation leaves a 3.0775% median
264-trip Stage-1 gap under the default profile, while the discrete model is
root-bound dominated at 19.2273%. The new explicit `incumbent_focus` control
sets only Gurobi `MIPFocus=1`, `Heuristics=0.5`, and `Presolve=2`; all model
rows, variables, objectives, prepared inputs, seed, threads, time limits,
acceptance gates, recovery rules, and automatic cuts/method/node
method/symmetry remain unchanged.

Clean tag `thesis-aggregate-incumbent-focus-f41e2b3` at
`f41e2b3634d86e9f209f50d811f35f0e0123fb66` executed the frozen
single-representation diagnostic at
`output/diagnostics/pure_ice_aggregation_incumbent_focus_f41e2b3_20260824/`.
The controls were recorded in its request and manifest; its BFF provenance
and three artifact hashes verify. It served 264/264 trips, passed physical
validation, 24/24 Rolling, and accounting reconciliation, with no fallback
or repair.

The Stage-1 run was time-limited at a 54,952.853971-JPY incumbent and a
52,749.163582-JPY certified bound, or **4.010147%**, above the predeclared
1% target and worse than the 3.077512% aggregate A/B median. It therefore
rejects `incumbent_focus` as the current gap-closing path. The artifact is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**: it cannot establish an A/B
performance result, cost comparison, global optimum, or research acceptance.
The 1% and independent-review gates remain **BLOCKED**.

## 2026-08-24: Exact-clone rank symmetry rejected after controlled diagnostic

The clean `1aaaa27` candidate supplied the canonical chronological trip order
to the Phase-3 Stage-1 identical-vehicle duty-order helper. It added 24
equal-count assignment-rank rows after the existing 24 trip-count rows for the
exact 25-vehicle homogeneous ICE group; clone-signature, assignment-domain,
and complete-successor-domain checks remained unchanged. Any integer clone-duty
set can be relabelled into the trip-count then rank-sum order, so the candidate
was an exact identifier-permutation symmetry breaker.

The frozen 264-trip diagnostic at
`output/diagnostics/stage1_clone_rank_root_1aaaa27_20260824/` verifies its
artifact hashes and BFF input provenance. Its quality-qualified root LP value,
`52,749.16358183724` JPY, differs from the unstrengthened
`52,749.16358183805` JPY by approximately `-8.1e-10` JPY, inside the
predeclared `1e-5`-JPY tolerance. The 435-second primary MIP obtained no raw
Gurobi bound beyond `0`; its analytical-floor certified gap was `19.2651169%`,
worse than the prior `19.2273066%`.

The physical, Rolling, and accounting outputs are retained only as diagnostic
execution checks. This is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**.
The current source deliberately restores the prior Stage-1 count-only symmetry
call. This rejects the rank tie-breaker as a 264-trip certificate path and
does not authorize a MIP comparison, formal run, speed claim, cost claim, or
release-status change.

## 2026-08-24: Fresh A/B telemetry is explicit, not a release remedy

Frozen tag `thesis-freeze-25ec2f1` now has a fresh five-pair AB/BA,
isolated-process 264-trip bundle at
`output/diagnostics/pure_ice_aggregation_phase3_ab_25ec2f1_20260824/`. All
ten clean-SHA runs accept coverage, physical validation, 24/24 Rolling,
accounting, and no-fallback/no-repair gates; its four public comparison files
have verified SHA-256 hashes. Each artifact saves `presolve_time_sec` from the
final Stage-1 Gurobi `PRESOLVE` callback and the effective Stage-1 search
controls. Its machine-readable semantics state that the value is elapsed from
`optimize` start, not a dedicated Gurobi internal presolve-duration attribute.

The verdict is `PASS_STRUCTURAL_ONLY`: aggregation reduces model size and RSS,
and its callback timestamp is lower, but median solver time is 3.16% slower
and both representations miss the declared 1% gap (19.2273% discrete;
3.0775% aggregate). This read-only telemetry evidence neither reinterprets the
historical null values nor closes any optimality, sensitivity, or release gate.

An explicitly separate single-representation, long-Stage-1-cap diagnostic is
available for reachability investigation.  Its frozen global wall-clock limit
must equal the explicit Stage-1 cap, Stage-2 cap, and separately recorded
model-construction/finalization allowance; a first clean-`6f080ba` 870/30
attempt incorrectly kept the old 900-second global limit and gave Stage 2 only
0.214 seconds after Stage 1/candidate enumeration.  That frontend result is
invalid and is not used as a representation feasibility, gap, cost, or
performance observation.  The corrected runner rechecks clean-SHA/prepared
input provenance and prohibits A/B, runtime, cost, optimality, and formal
research-acceptance claims.  It cannot replace the five-pair AB/BA evidence or
close the 1% gate, even if its individual diagnostic gap improves.

The corrected clean-`96982ab` diagnostic at
`output/diagnostics/pure_ice_aggregation_single_long_stage1_96982ab_20260824/`
uses an explicit 870/30/120-second Stage-1/Stage-2/overhead envelope (1020
seconds total). Its artifact hashes and BFF run-input provenance verify; it
serves 264/264 trips, passes physical validation, accepts 24/24 Rolling,
reconciles accounting, and has no fallback or repair. Its one pure-aggregate
candidate has a 3.041301684% certified Stage-1 gap, only 0.036210 percentage
points below the prior 435-second aggregate median of 3.077511540%, and still
misses the 1% target. It is **DIAGNOSTIC, NOT USED FOR RESEARCH
CONCLUSIONS**: it makes no A/B, speed, cost, optimality, or release claim and
does not authorize a formal run.

## 2026-08-24: Thesis evidence audit confirms release remains blocked

`docs/notes/THESIS_SUBMISSION_EVIDENCE_AUDIT.md` maps the required
reproducibility, A/B, integrated-oracle, sensitivity, stress, and M0--M3
evidence to its exact claim boundary. It records the new frozen `25ec2f1`
A/B evidence and confirms that the requested baseline `a145cf3` is its
ancestor; no old artifact is relabelled as a current-HEAD formal run. The
documentation audit and the current documentation checkout's `1570` passing
regression tests do not satisfy an
optimality, economic-response, or independent-review gate.

The remaining mathematical blocker is unchanged: the quality-qualified
264-trip Stage-1 root LP splits every trip across vehicle labels despite the
existing time-indexed charger/PV/BESS/grid relaxation. No tested safe root
strengthening closes the declared 1% gap. A new formal run is prohibited until
a specific original-feasible-set-valid assignment/path strengthening has a
validity proof and focused exact/small-MILP regression; the release remains
`BLOCKED`.

Before the next clean-SHA root-LP observation, the diagnostic gained one
strictly read-only candidate audit: for each vehicle and same-day trip pair it
forms a permissive support graph from direct Stage-1 arcs and canonically
feasible depot-reset edges. A pair with no path is logged as a possible
`y[v,i] + y[v,j] <= 1` row, with no row added to the production model. The
audit records its separate evaluation time and excludes unavailable assignment
variables. The clean-`0bd81bc` normal-BFF run at
`output/2026-08-24/run_20260824_1050/` is quality-qualified (root LP optimum
52,749.163582 JPY; maximum unscaled primal violation `5.820766e-11`) and
checks all 1,404,360 candidate pairs in 9.652 seconds. It finds zero
violations and maximum assignment mass `0.8457521`, so this candidate is
rejected; no row is added. The artifact is **DIAGNOSTIC, NOT USED FOR RESEARCH
CONCLUSIONS**, and cannot weaken or close the 1% gate.

The next read-only diagnostic searches deterministic high-mass cliques of
same-day assignments that are pairwise unreachable in the same permissive
direct/depot-reset graph. Every emitted clique is a valid
`sum(y[v, trip] for trip in clique) <= 1` candidate, but the greedy discovery
is not exhaustive. The clean-`91cfbb5` normal-BFF root-LP artifact at
`output/2026-08-24/run_20260824_1114/` is quality-qualified and checks 815
cliques in 8.919 seconds; it finds zero violations and largest mass
`1 + 2.20e-14`, within the `1e-6` tolerance. This rejects the searched greedy
candidates only, is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**, and
adds no MIP row. A future clean-SHA result must first identify a violation and
receive a separate exactness proof and regression before any formulation
change is considered.

The current source also adds a default-off exhaustive, read-only
maximum-weight clique separator over the same support graph. It runs only
after an optimal, quality-qualified root LP; an auxiliary time limit or
skipped group is `inconclusive`; and a no-violation conclusion requires every
eligible vehicle/day auxiliary MIP to prove optimal. The frozen clean
`f71bc51` artifact at
`output/diagnostics/stage1_assignment_path_exact_clique_root_f71bc51_20260824/`
now executes it under the same prepared input, seed 42, four threads, complete
successor network, and explicit 435/30/420-second contract. Its root LP is
optimal and quality-qualified; all 59 eligible auxiliary MIPs prove optimal
(one group is trivially nonviolating), no group times out or is skipped, and
zero valid clique rows are violated. The maximum mass is `1 + 2.22e-14`,
within the `1e-6` tolerance. This exact diagnostic rejects the full no-path
clique family at that root point, adds no MIP row, and is **DIAGNOSTIC, NOT
USED FOR RESEARCH CONCLUSIONS**. Its Stage-1 certified gap remains
19.2273066%, so it does not authorize a formal run or weaken the 1% gate.

The certified `used_vehicle <= sum(path_start)` candidate remains valid only
under its strict acyclic-flow certificate and stays default-off. Its prior
clean-`3de101b` 264-trip ON diagnostic reached the 300-second barrier/crossover
clone limit with `SolCount=0`, so it had no comparable root point. The clean
`a51b1f3` follow-up at
`output/diagnostics/stage1_activation_start_dual_root_a51b1f3_20260824/`
uses dual simplex (`Method=1`) for that separate clone only, with the same
prepared-source hash, four threads, cap, 60 rows, and 762,906-variable/
108,122-constraint model. It also reaches 300 seconds with `SolCount=0`.
The `NO_COMPARABLE_ROOT_LP_SOLUTION` assessment is **DIAGNOSTIC, NOT USED FOR
RESEARCH CONCLUSIONS**; it leaves the production MIP and every acceptance gate
unchanged, supplies no comparative root bound, and is not a license to run a
formal experiment.

Because the all-row model has no comparable root solution under either
permitted algorithm, the bounded clean-`08af482` one-row diagnostic at
`output/diagnostics/stage1_activation_start_subset_root_08af482_20260824/`
tests the same certified inequality for the explicitly recorded largest-deficit
non-aggregate label. It retains the prepared source, root controls, and cap;
adds exactly one row; and returns a quality-qualified optimal root LP. Its
52,749.16358183801-JPY objective equals the unstrengthened
52,749.16358183805-JPY objective within the `1e-5`-JPY comparison tolerance.
The `NO_ROOT_BOUND_IMPROVEMENT` result is **DIAGNOSTIC, NOT USED FOR RESEARCH
CONCLUSIONS**. It rejects this one-row candidate as a root-bound path, so no
MIP ON/OFF or formal run is authorized.

The frozen clean-`f10525f` top-five follow-up at
`output/diagnostics/stage1_activation_start_top5_root_f10525f_20260824/`
precommits the five largest baseline deficits and adds exactly five certified
activation-start rows (108,067 constraints). It keeps the prepared-source
hash, seed 42, four threads, barrier/automatic crossover, 300-second root cap,
and default Stage-1 controls fixed; its normal-BFF run
`output/2026-08-24/run_20260824_1343/` passes run-input provenance. The root
LP is optimal and quality-qualified, but its 52,749.16358183858-JPY objective
is only `+5.3e-10` JPY from the unstrengthened point, within the same
`1e-5`-JPY tolerance. This is a second `NO_ROOT_BOUND_IMPROVEMENT`,
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**. It rejects the tested
one-row and five-row high-deficit subsets as a root-bound path, but makes no
claim about all other subsets and authorizes neither a MIP ON/OFF nor a formal
run.

## 2026-08-24: Remaining one-factor matrix completes diagnostics, not acceptance

The frozen tag `thesis-remaining-sensitivities-27ec8ce` ran the selected
13-case normal-BFF matrix at clean SHA
`27ec8cee6e9293000ba6f9d31b734e30a424f3fb`, stored at
`output/thesis_remaining_sensitivities_27ec8ce_20260824/`: BEV energy
0.8/1.0/1.2, PV 0.00/0.25/0.50/0.75/1.00, BESS ON/OFF, and 6/8/10 generated
90-kW single-port chargers. Each case has fresh Prepare input, all 264 trips
served, complete successors, physical validation, 24/24 Rolling, accounting,
artifact-hash verification, and unchanged source SHA. Each family has one
stable non-varied-control fingerprint; the charger normalizer varies only
declared port count/derived compatibility identifiers.

All 13 cases still fail exactly one required gate: `mip_gap_target_met`. Their
certified gaps range from 2.404055% to 26.849287%, above the declared 1%
threshold, so the matrix status and every case remain `BLOCKED`. The candidate
PV, BESS, charger, and BEV-energy values are **DIAGNOSTIC, NOT USED FOR
RESEARCH CONCLUSIONS**. In particular, zero grid import or equal candidate
cost at PV 0.75/1.00 or charger 6/8/10 does not show no real effect; the
time-limited Phase-3 candidates need not be the same optimum.

The no-HTTP/no-solver re-audit at
`output/verification/thesis_remaining_sensitivities_reaudit_27ec8ce_20260824/`
rechecks all copied source bundles against source-manifest SHA-256
`17221d1d92da27043668d6549468cb6eb6b44ccc2d1ded38dfa62c1bfe5d7dbc`. It
confirms matching frozen/audit-builder SHA, every selected case completed, all
non-gap checks true, and stable controls by family. Its expected exit code 2
is the correct `BLOCKED` result, not a runner error. This closes neither the
full-network 1% certificate blocker nor any economic/optimality release gate.

## 2026-08-24: Repeated pure-ICE aggregation A/B passes structure, not release

The clean frozen tag `thesis-phase3-pure-ice-ab-0ddcd22` completed the
five-pair isolated-process bundle at
`output/diagnostics/pure_ice_aggregation_phase3_ab_0ddcd22_20260824/`. All
ten current-SHA children attest the same pre/post clean commit
`0ddcd2213c9d524f55e448ec046e2683eb2d03c8`, prepared-input SHA-256
`639b6754cccd1aef7758454b56640f968b6b1c277ec32c1c142f53f670ade558`, seed 42,
four threads, 435/30-second Stage-1/Stage-2 limits, and complete successor
network. They each serve 264/264 trips, pass physical validation and Rolling
24/24, reconcile accounting, and use neither fallback nor post-solve repair.
The parent verdict is `PASS_STRUCTURAL_ONLY`; its manifest and comparison
artifact hashes independently verify.

This clears only a representation-structure gate. Median variables,
binaries, constraints, and peak process-tree RSS fall 31.82%, 32.01%, 24.09%,
and 17.22%, respectively, but median solver time rises from 465.655 to
480.182 seconds. The discrete and aggregate cases remain time-limited at
19.2273% and 3.0775% certified gaps, respectively, both above the declared
1% target. Consequently neither the lower aggregate incumbent nor the lower
parent wall time establishes a cost, optimality, runtime-performance, or
economic-response claim. The full-network certified-gap/release blocker
remains active.

## 2026-08-24: Current-SHA small integrated oracle is verified but bounded

The frozen tag `small-integrated-oracle-f0240cc` produced
`output/verification/small_integrated_oracle_scale/f0240cc_20260824/` at
clean commit `f0240cc90fd44d92b9a39df2fbf0240c539ec825`. Its 8/12/24-trip
isolated-process certificate has matching clean pre/post SHA, the frozen
prepared-input SHA-256
`639b6754cccd1aef7758454b56640f968b6b1c277ec32c1c142f53f670ade558`, seed 42,
four threads, and a 300-second per-phase limit. All Phase-4 references are
`optimal` with zero solver gap; every paired Phase-3 schedule is feasible and
complete. The 24-trip canonical-cost delta is
`1.4551915228366852e-11` JPY against the `1e-5`-JPY tolerance, so its
identifiable ApproxGap is `0.0`. The 8/12-trip exact reference costs are
numerically zero and their relative gaps remain correctly not identifiable.

This clears only the bounded small-instance formulation check. The certificate
itself records `research_conclusion_eligible=false` and
`formal_full_network_optimality_substitute=false`: it is not evidence of a
264-trip integrated global optimum, a Phase-3 cost-optimality guarantee, a
runtime benefit, a formal economic response, or release readiness. The
full-scale certified-gap and acceptance blockers below remain in force.

## 2026-08-24: Fresh small, fixed-plan, and price artifacts do not close the gap

Clean `93e31b0` reran the 8/12/24/40 integrated oracle certificate at
`output/verification/small_integrated_oracle_scale/93e31b0_20260824/`. It is
`VERIFIED_BOUNDED_SMALL_INSTANCES`: Phase-4 is zero-gap at each size and the
identifiable 24/40-trip Phase-3 ApproxGaps are 0.0. The matching 40-trip
M0--M3 artifact at `output/verification/small_m0_m3/93e31b0_20260824/audit.json`
is `PASS_SMALL_SCOPE_ONLY`, with a same-input M2--M3 canonical-cost delta of
`2.546585164964199e-11` JPY. Both outputs remain bounded and are not 264-trip
optimality or release evidence.

The exact-source-SHA, no-reoptimization stress replay at
`output/diagnostics/fixed_solution_stress_0ddcd22_20260824/` accepts only the
fixed candidate under initial SOC -5pp (0 JPY delta); the six other
predeclared stresses physically fail and have no manufactured cost. This does
not establish recourse robustness.

Current BFF diesel and electricity matrices are also correctly `BLOCKED`:
`output/thesis_economic_diesel_93e31b0_20260824/` verifies the effective
116/145/174-JPY/L inputs and
`output/thesis_economic_electricity_93e31b0_20260824/` verifies the effective
24/30/36-JPY/kWh inputs. Each price case serves 264/264 trips, passes physical
and Rolling/accounting gates, and keeps non-varied controls stable, but every
case misses the 1% Stage-1 target at about 19.2273%. The observed candidate
cost response (and zero-grid-import electricity candidates) is therefore not
an economic-response conclusion. The full-network certified-gap blocker
remains unchanged.

The fresh `9650ed9` 0/20,000-JPY vehicle-day-cost matrix at
`output/thesis_economic_vehicle_day_9650ed9_20260824/` confirms that the
declared fixed cost reaches the model and canonical accounting: 32 vehicle
days produce exactly 640,000 JPY at 20,000 JPY/day. The paid case's certified
gap improves to 1.7803% but still misses 1%; both cases are therefore
`BLOCKED`. It establishes input/accounting propagation only. The later
`27ec8ce` diagnostic tranche ran the remaining selected rows and confirms that
they also cannot supply release-eligible sensitivity evidence before the
common certified-gap blocker is repaired.

The current no-HTTP/no-solver re-audits at
`output/verification/thesis_economic_diesel_reaudit_365a6b5_20260824/`,
`output/verification/thesis_economic_electricity_reaudit_365a6b5_20260824/`,
and `output/verification/thesis_economic_vehicle_day_reaudit_365a6b5_20260824/`
re-verify every copied price and vehicle-day source bundle. Across these eight
cases and the separate 13-case BEV-energy/PV/BESS/charger tranche, all 21
full-scale sensitivity cases fail only `mip_gap_target_met` (1.780295%--
26.849287%), with no accepted case. This strengthens the audit trail only; it
does not turn candidate differences into an economic-response conclusion or
permit cross-family comparisons as one common experiment.

## 2026-08-23: Current-code pure-ICE aggregation A/B is structural-only

The normal candidate's solver telemetry is root-bound dominated: the
52,749.163582-JPY Stage-1 root bound closely matches the independently
certified 52,724.471363-JPY analytical lower bound, while the incumbent is
65,305.688576 JPY. Code review confirmed that the Stage-1 SOC/BESS relaxation
already includes the required BEV return-to-initial and BESS terminal
contracts; no unsafe constraint weakening is proposed.

The current code now has a default-OFF read-only coefficient-source diagnostic
for this warning. It scans the completed Stage-1 matrix and records the rows
and variables attaining the smallest nonzero coefficients, but never changes
the model, starts, bounds, objective, or Gurobi controls. Enabling it forces a
diagnostic-only BFF result and cannot satisfy research acceptance. A fresh
clean-SHA 264-trip artifact at `output/2026-08-23/run_20260823_2354/` from
`5969f6a` completed this trace: it scanned 108,062 rows and 6,295,964
nonzeros in 26.031 seconds, with an identical payload in the canonical solver
result and `solver_settings.json`. Every recorded minimum is approximately
`1e-6` in `stage1_soc_relax_return_to_initial_upper__*` on a `used_*` binary.
For the current input this is the intentional return-to-initial upper band
(`0 <= net charge <= 1e-6 * used`), not an unexplained physical or objective
coefficient. The run remains diagnostic-only, with a 19.227307% certified
Stage-1 gap; it supplies no research conclusion.

An algebraic row multiplier is rejected as a remedy. Gurobi applies primal
feasibility tolerance in absolute row units, so multiplying this row would
change the effective terminal-SOC numerical acceptance band. The scientific
SOC tolerance and independent validator are therefore held fixed. Only a
separately traced, documented, diagnostic solver-scaling experiment or an
exactly proven alternative formulation may proceed; the release remains
blocked by the 1% MIP-gap gate.

Before the next root-LP observation, a P1 acceptance-boundary defect was
closed: `stage1_root_lp_diagnostic_enabled` created a separate relaxation but
did not itself force BFF diagnostic mode. The BFF now fails closed, marking
that flag diagnostic-only with a focused worker regression. No root-LP
artifact can therefore become research evidence merely because the main solve
also completes physical and Rolling gates.

The predeclared next observation, Gurobi-internal `ScaleFlag=2`, is complete
at frozen `diagnostic-stage1-scaleflag2-4ae58fc`. The implementation accepts
only `-1/0/1/2/3`, keeps default `-1`, records the effective value in Stage-1
solver controls, and makes every non-default BFF request diagnostic-only. It
neither multiplies a user row nor changes feasibility/SOC tolerances or
Stage-2 controls. The normal `-1` control is
`output/2026-08-24/run_20260824_0027/`; diagnostic-only `2` is
`output/2026-08-24/run_20260824_0015/`. They have the same clean SHA,
prepared-input SHA-256, seed, four threads, 900-second total / 435-second
Stage-1 / 30-second Stage-2 budget, selected candidate hash, Rolling
assignment hash, and executed-energy-flow hash.

Both conditions pass independent physical validation, 24/24 accepted Rolling,
executed-day accounting, and 240/240 artifact verification. The displayed
Stage-1 bound (52,749.163582 JPY), incumbent (65,305.688576 JPY), certified
gap (19.227307%), and final executed-day cost (64,422.491318 JPY) are the
same. Raw bound movement is below `1e-9` JPY, candidate and flow hashes are
identical, and Stage-1 runtime changes by only 0.005 seconds. The original
input-matrix coefficient range remains `1.4507364e9` with the same warning, as
expected from internal rather than user-side scaling. This single controlled
pair therefore rejects `ScaleFlag=2` as a demonstrated certificate, candidate,
or runtime improvement. It remains a diagnostic result and does not close the
predeclared 1% gap or research-release gate.

The first two root-LP attempts at `429c8db` are also non-evidence: the
30-second `output/2026-08-24/run_20260824_0047/` and 300-second
`output/2026-08-24/run_20260824_0051/` diagnostics both reached their limits
with no continuous solution (`SolCount=0`), so they contain no fractional
structure from which to derive a valid inequality. Inspection found that the
diagnostic clone hard-coded one thread. The corrected clean-`3a063f6` run at
`output/2026-08-24/run_20260824_0119/` uses the same prepared-input SHA-256,
four threads, barrier (`Method=2`), `Crossover=0`, and a 300-second cap. It
returned one `suboptimal` interior point in 24.032 seconds: 9,790 assignment
variables are fractional, all 264 trips are split across vehicle labels, and
all 60 vehicle activations are fractional. This is useful only to show where
the relaxation is weak; its `52,749.183898`-JPY interior objective is not a
certified LP lower bound.

The same artifact records a maximum unscaled primal violation of
`1.374481e-6` against the configured `1e-6` feasibility tolerance (and a
maximum complementarity violation of `0.0105805`). Its persisted
`primal_quality_within_configured_tolerance` flag is therefore `false`.
The implementation now fails closed on this condition: it stores the
primal/dual/complementarity quality metrics and prohibits using the point as
an optimality or valid-inequality certificate. The result is **DIAGNOSTIC, NOT
USED FOR RESEARCH CONCLUSIONS**; no structural change is authorized until a
quality-qualified observation exists and any proposed inequality is separately
proved valid.

That quality-qualified observation is now available, but it is not a release
result. The clean-`c11bb46` automatic-crossover diagnostic at
`output/2026-08-24/run_20260824_0124/` holds the prepared-input SHA-256,
four threads, and 300-second cap fixed while changing only the isolated LP
clone to `Crossover=-1`. It returns `optimal` in 29.100 seconds at
52,749.163582 JPY, with maximum unscaled primal violation `5.820766e-11`
under the same `1e-6` tolerance; its persisted quality flag is `true`.

The exact continuous relaxation contains 2,274 fractional assignment
variables and splits every one of the 264 trips across vehicle labels, but all
60 `used_vehicle` activations are integral. This localizes the weakness to the
trip-to-vehicle assignment relaxation rather than vehicle-count activation.
It authorizes only the next research step: derive a specific valid inequality
for that assignment structure and prove it before any controlled MIP test.
It is still **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** and does not
close the 1% MIP-gap or release gate.

The first specific candidate is rejected by a clean, read-only test. At
`ea9a279`, `output/2026-08-24/run_20260824_0131/` evaluates the exact root-LP
solution against all 157 maximal temporal-overlap cliques for all 60 vehicles
(9,420 inequalities of the form `sum(y[v, trip]) <= 1`). It finds zero
violations; the largest left-hand side is `0.9142023`. These rows are therefore
already implied strongly enough by the present single-path flow relaxation at
the observed root point. They must not be materialized as a purported root
tightening. The remaining candidate space is assignment/flow structure beyond
same-time overlap, and it still requires a separate validity proof.

The next clean, quality-qualified diagnostic at `653f697` is
`output/2026-08-24/run_20260824_0144/`. The separate root LP is optimal at
52,749.163582 JPY with automatic crossover, four threads, a 300-second cap,
and maximum unscaled primal violation `5.820766e-11`. It records 50 positive
`used_vehicle - sum(path_start)` deficits across 60 labelled vehicles; the
maximum is `0.8169431546`. Because up to 100 same-day fragments are permitted,
the equality `used_vehicle = sum(path_start)` is not valid and is prohibited.

The weaker inequality `used_vehicle <= sum(path_start)` is proved valid only
for non-aggregate labels: existing vehicle-day linkage makes an integral
active vehicle serve a trip, and strictly chronological arc flow gives every
integral nonempty labelled flow a path start. Exact-clone aggregate vehicles
are excluded because they have a different aggregate start domain. Current
code exposes this row only as the default-OFF
`stage1_activation_start_strengthening` diagnostic; it fails closed without
the certificate and marks the BFF request diagnostic-only. An actual-Gurobi
row test and a two-trip physical ON/OFF parity test pass. There is no 264-trip
MIP ON/OFF conclusion: the clean-`3de101b` ON artifact at
`output/2026-08-24/run_20260824_0155/` applies all 60 eligible rows with no
selected clone group, the same prepared-input hash, and unchanged clean Git
state. Its barrier/crossover root LP reaches the 300-second cap with
`SolCount=0`, so it contains no LP objective or quality-qualified point for a
controlled bound comparison. It is **DIAGNOSTIC, NOT USED FOR RESEARCH
CONCLUSIONS** and has no claimed gap, runtime, cost, physical, or release
benefit. The row remains default-OFF and the 1% MIP-gap blocker remains open.

The first diagnostic artifact from `9af1129` is not usable even as the
coefficient-source record: the canonical solver payload contained the scan,
but final `solver_settings.json` omitted it. The serialization defect is fixed
and covered by an actual-Gurobi engine regression. The replacement `5969f6a`
artifact above carries the exact same payload in both locations, so this
serialization blocker is closed. It does not close the numerical-performance
or 1% gap blocker.

An opt-in, default-OFF redundant trip-level electric selector has been added
for a controlled representation test. The two-trip physical fixture preserves
the integer assignment and Stage-1 objective with the flag ON/OFF, but that is
not 264-trip performance or gap evidence. Until a clean-commit same-SHA,
same-input, fixed-control A/B run reports its artifacts, the candidate remains
gap-blocked and this selector must not be presented as an improvement or
enabled as the ordinary representation.

The first attempted pair is explicitly excluded: its flag was supplied to
Prepare, which discarded it, so OFF and ON resolved to the same prepared input
without a canonical selector record. The queued ON job was stopped. The flag
now belongs to the optimization request and is persisted into canonical model
metadata; a fresh two-condition run from the new clean commit is still pending.

That corrected run is now complete at frozen SHA `b890c41` in
`output/thesis_powertrain_selector_ab_b890c41_20260823/`. The conditions share
the exact prepared input and all non-representation controls; canonical output
records 0 selectors for OFF and 264 for ON. Both are physically valid 264-trip
candidates with accepted 24/24 Rolling, but both remain at a 19.2273066%
certified Stage-1 gap. Solver time is effectively unchanged (463.816 s OFF;
463.918 s ON). Therefore this representation has no demonstrated benefit in
the fixed 264-trip condition, remains default-OFF, and does not alter the
gap-blocked release verdict.

The historical pure-ICE aggregation bundle
`output/diagnostics/pure_ice_aggregation_phase3_ab_817d938_20260823/` is not
current-code evidence. Although it contains five isolated AB/BA pairs and
reports `PASS_STRUCTURAL_ONLY`, its v3 runner used positional BFF worker
arguments before the selector parameter was added and did not persist the
full OS/CPU/RAM/gurobipy snapshot or explicit optimization-proxy checks. The
v4 runner fixes both issues. Its first clean-SHA bundle at
`output/diagnostics/pure_ice_aggregation_phase3_ab_01da730_20260823/` was
then retained only diagnostically after a further P1 review: the collector had
not yet failed closed on the exact aggregate-flow recovery fields. The current
gate requires unchanged integer and recoverable physical dispatch sets,
non-relaxed labelled region, and a one-to-one count of recovered canonical
ICE paths and IDs. No runtime or formulation claim is carried forward from
those earlier bundles.

The first recovery-gated v4 attempt at
`output/diagnostics/pure_ice_aggregation_phase3_ab_4e715da_20260823_r3/`
ended externally after four completed child artifacts and before finalization.
It has no repeated comparison and is `DIAGNOSTIC`, `NOT USED FOR RESEARCH
CONCLUSIONS`. The runner now supports a fail-closed manifest-attested resume
mode, but that is a source change and that partial bundle remains excluded.

The fresh recovery-gated bundle at
`output/diagnostics/pure_ice_aggregation_phase3_ab_ac8982d_20260823/` is now
complete at clean SHA `ac8982d33826f681c6441eeb3f7f320fc12f3a3b`. All five
AB/BA pairs hold the SHA, input hash, seed, threads, and Stage 1=435 / Stage
2=30-second controls fixed. All ten children passed physical validation,
24/24 Rolling, accounting, and fallback/repair exclusion. Aggregate recovery
is applied and preserves both integer and recoverable physical dispatch sets.
The result is `PASS_STRUCTURAL_ONLY`: median variables decreased 31.82% and
constraints 24.09%, but median solver time increased 3.16% (465.570 to 480.265
seconds), and all runs are time-limited. It closes only the current-code
structural-evidence gap; it does not close the 1% optimality, runtime-benefit,
cost-dominance, sensitivity, or research-release gates.

The current 8/12/24/40-trip integrated-oracle scale certificate at
`output/verification/small_integrated_oracle_scale/e672918_20260823/` is
`VERIFIED_BOUNDED_SMALL_INSTANCES`: all four Phase-4 references are exact and
the corresponding Phase-3 canonical costs agree within numerical tolerance.
The zero-cost 8/12 references have no relative gap; 24/40 report 0.0. This
closes no full-network gate: it is explicitly not a 264-trip optimum, runtime,
economic-sensitivity, or research-release conclusion.

The corresponding 40-trip M0--M3 artifact at
`output/verification/small_m0_m3/3e52305_20260823/audit.json` is
`PASS_SMALL_SCOPE_ONLY`. All methods are complete; only M2/M3 is a same-input
algorithmic pair, and its accounting-cost difference is within numerical
tolerance. M0/M1 change fleet or PV/BESS treatment and remain descriptive
ablations. This does not close any 264-trip or release gate.

The SHA-matched fixed-decision stress replay at
`output/diagnostics/fixed_solution_stress_ac8982d_20260823/` records no
reoptimization. Only initial SOC -5 points is physically accepted; the other
six energy, delay, PV, charger-outage, and combined stresses fail independent
physical validation and have null added costs. This blocks any claim of
fixed-plan robustness, recourse cost, or uncertainty resilience.

The 116/145/174-JPY/L diesel-price matrix at
`output/thesis_economic_diesel_4678e7d_20260823/` is `BLOCKED` only by the
unchanged 19.2273% Stage-1 gap. Its fixed controls and effective diesel prices
are audited, but all three time-limited candidates retain 48 BEV / 216 ICE
trips and 32 used vehicles. The cost movement is therefore diagnostic input
provenance, not accepted economic-dispatch or sensitivity evidence.

The current 24/30/36-JPY/kWh electricity-price matrix at
`output/thesis_economic_electricity_b7d4cd4_20260823/` is equally gap-blocked.
Tariffs are effective and controls match, but its time-limited candidates have
zero grid import/cost and unchanged assignments. This is a zero-import
candidate diagnostic only, not evidence that electricity price is irrelevant
or that the economic response gate is closed.

The current BFF BEV-trip-energy 0.8x/1.0x/1.2x matrix at
`output/thesis_economic_bev_energy_c6dec42_20260823/` is `BLOCKED` only by the
predeclared 1% Stage-1 gap (26.8493%, 19.2273%, and 14.0845%, respectively).
All cases have the same prepared-trip hash and non-varied controls, retain the
clean frozen SHA, and pass coverage, physical validation, 24/24 Rolling, and
final accounting. The 0.8x candidate uses 34 vehicles for 53 BEV / 211 ICE
trips at 63,983.495 JPY; the 1.0x and 1.2x candidates use 32 vehicles for 48
BEV / 216 ICE trips at 64,422.491 JPY. Those different time-limit incumbents
are feasible diagnostics only: they cannot close the energy-consumption,
economic-response, optimality, or research-release gates.

The BFF PV-supply 0.00x/1.00x pair at
`output/thesis_economic_pv_3985f80_20260823/` is also `BLOCKED` only by
`mip_gap_target_met` (3.4915% and 19.2273%, respectively). The parameter is
effective and all other input, physical, Rolling, accounting, and artifact
checks pass. Its time-limit candidates move from 477.578-kWh grid import and
zero PV/BESS flow at 0.00x to 996.2-kWh PV generation, 47.918-kWh direct PV,
559.783-kWh PV-to-BESS, 505.204-kWh BESS-to-bus, and zero grid import at
1.00x. Because the candidate dispatches and gaps differ, this can establish
only PV-parameter and candidate-flow provenance; it does not close PV-cost,
economic-response, optimality, or release gates.

The BFF common vehicle-day-cost 0/20,000-JPY-per-used-vehicle pair at
`output/thesis_economic_vehicle_day_d97d524_20260823/` is `BLOCKED` only by
the 19.2273% and 1.7803% Stage-1 gaps. Its fixed-vehicle-day-cost semantics
are research-eligible and the 20,000-JPY case's 640,000-JPY ledger term equals
32 used vehicles times 20,000 JPY with zero residual. Both time-limit
candidates retain 32 vehicles and 48 BEV / 216 ICE trips. This verifies only
the common cost coefficient and accounting; it cannot establish BEV-specific
or ICE-specific economic response, optimality, or release readiness.

The BFF `BESS_ON`/`BESS_OFF` pair at
`output/thesis_economic_bess_75c228f_20260823/` now supplies the missing
component-ablation execution. The immutable snapshots prove the respective
enabled states and all physical/accounting controls pass, but both cases are
`BLOCKED` only by `mip_gap_target_met` (19.2273% ON; 26.8205% OFF). The ON
candidate records 559.783-kWh PV-to-BESS, 505.204-kWh BESS-to-bus and zero grid
import; OFF records zero BESS flow and 203.310-kWh grid import. Its time-limit
candidates have different dispatches and gaps, so this establishes BESS-state
and candidate-flow provenance only—not accepted BESS-cost or economic-response
evidence. The economic-response and research-release gates remain open.

The first two 6/8/10-port charger trials at
`output/thesis_economic_charger_capacity_ff77ecd_20260823/` and
`output/thesis_economic_charger_capacity_c775562_20260823/` remain excluded:
their control fingerprints included deliberate charger-inventory changes. The
clean final trial at
`output/thesis_economic_charger_capacity_dde40a1_20260823/` corrects this
with an immutable-snapshot hash that normalizes only charger-derived
compatibility IDs and depot count fields, while retaining vehicle state and
parameters, non-charger depot data, and port specifications. Its 6/8/10-port
cases have one matching non-varied control fingerprint, the declared effective
counts, clean unchanged SHA, 264/264 coverage, physical validity, 24/24
Rolling, and accounting. They are nevertheless all `BLOCKED` by the same
19.2273% Stage-1 gap. Their identical time-limit candidates cannot support a
no-capacity-effect, cost, dispatch, equipment-capacity, or release claim.

## 2026-08-23: Latest normal 264-trip Phase-3 rerun remains gap-blocked

The frozen tag `phase3-current-formal-6e61b80` reran the ordinary BFF path
from Fresh Prepare through `phase3_two_stage` and 60-minute Rolling for the
central 145-JPY/L request. The one-case bundle
`output/thesis_current_phase3_6e61b80_20260823/` has manifest SHA-256
`f74c9ea76c24fae8f26ad3b043d54cf50fbd9d40a6c5ca1df52d3be04cd5796b`, matching
clean pre/post SHA `6e61b80`, fixed seed 42, four threads, a 900-second
request, and the same persisted prepared input. It passes valid/research-ready
input provenance, full successor coverage, 264/264 trip service, independent
physical validation, 24/24 accepted Rolling, executed-day accounting, and
240/240 finalized artifact hashes.

Its 64,422.491318-JPY candidate uses 32 vehicles for 48 BEV / 216 ICE trips,
but Stage 1 terminated at 19.227306637% certified gap after 464.581506 seconds
against the declared 1% target. The bundle is therefore `BLOCKED` solely by
`mip_gap_target_met`; it is a feasible/accounting candidate and cannot be
presented as an optimum, an accepted one-point economic sensitivity, or a
release result. Independent phase-gate audit
`output/diagnostics/thesis_phase_gate_6e61b80_20260823/current_phase_gate_audit.json`
(SHA-256 `47a267623dea68cc9e5c032f6b9e2fc6c2531204dbc62154b972241d6f551a2d`)
also remains `BLOCKED`: this Phase-3 source has no full Phase-4 execution and
does not meet its Stage-1 gap.

The exact-SHA fixed-decision stress rerun is
`output/diagnostics/fixed_solution_stress_6e61b80_20260823/` (manifest SHA-256
`d9a7160ead2227fdaa13d89b5a643f0afcee049ac3a1e3d62160fee3b86f90bd`). A clean
detached `6e61b80` worktree was required so the evaluator did not weaken its
source-SHA gate. It records `reoptimization_performed=false`. Only the
initial-SOC minus-five-point case is physically valid (0-JPY fixed-decision
delta); the other six specified stresses retain their violations and null
costs. This satisfies the fixed-plan stress-input record for this candidate,
but cannot close the gap, accepted sensitivity, recourse, Phase-4, or M0--M3
release gates.

## 2026-08-23: First bounded M0--M3 attempt is diagnostic; repaired rerun remains small-scope

The opt-in `--run-small-m0-m3` path in
`scripts/audit_small_integrated_weather_milp.py` now defines a small-subset
M0--M3 matrix with an all-ICE M0, no-PV/BESS mixed M1, deployed Phase-3 M2,
and scalar actual-cost-oracle M3. The protocol is designed to fail closed and
marks its output `small_subset_only_not_full_264_trip_evidence`. The clean
tag `phase3-small-m0-m3-ab55933` executed a 24-trip bundle at
`output/verification/small_m0_m3/ab55933_20260823/audit_24.json` (SHA-256
`f05cd64ae34925eeada14cb03ca6ebf3ab7d6075340fb66062a2b08134b412f8`). Its
M0 is infeasible in strict precheck because the first implementation gave it
five ICE vehicles, while the mixed M1/M2/M3 conditions had ten total vehicles.
The selected frozen trips actually allow both BEV and ICE; this is an
implementation defect, not a compatibility result. The artifact is therefore
`DIAGNOSTIC`, `NOT USED FOR RESEARCH CONCLUSIONS`. The repair gives M0 ten ICE
vehicles to match the mixed-condition total fleet count and was rerun from a
new clean commit.

That corrected clean-tag execution is now
`output/verification/small_m0_m3/4445ea3_20260823/audit_24.json` (SHA-256
`d8dce27a1a197705d6da3175bcf12f908089c699eb1c0fd8aba5e3b3ba5d6126`) and
returns `PASS_SMALL_SCOPE_ONLY`: M0/M3 are exact scalar-cost optima, M1/M2
are 24/24 feasible, and M2/M3 have identical declared input hashes with a
1.0914e-11-JPY difference. This still cannot discharge the 264-trip Phase-3
gap, full-scale frontend M0--M3, economic-sensitivity, or global-optimality
release gates, because the direct small-oracle CLI lacks frontend phase-token
research acceptance and is expressly small-subset only.

The small-oracle CLI has since been hardened to require clean Git provenance,
persist pre/post SHA, the prepared-input hash, runtime environment, and fixed
four-thread solver controls. A fresh artifact from that strengthened contract
is required before treating its bounded result as current-code evidence.
The 8/12/24/40 scale wrapper now forwards those fixed threads to each isolated
child and records its parent runtime environment; it likewise needs a fresh
clean-commit series before replacing the historical certificate.
The prior attested v1 series is also `DIAGNOSTIC` because its
`research_conclusion_eligible=true` field conflicts with its bounded-only
scope. Certificate schema v2 fixes the field to `false` permanently and
records bounded formulation eligibility separately.

The corrected v2 series is now
`output/verification/small_integrated_oracle_scale/f75ee78_20260823/`
(certificate SHA-256
`545ad7fe16c40847e0ee87a6ccdff268845991aa6fc4cf8dedbb8a4260a9a358`). All
8/12/24/40 sizes are verified from clean SHA `f75ee78`, fixed seed 42, four
threads, and 300 seconds per phase. It is `VERIFIED_BOUNDED_SMALL_INSTANCES`
with `bounded_formulation_conclusion_eligible=true` and
`research_conclusion_eligible=false`; it clears no full-network release gate.

## 2026-08-23: Diesel-price term is active; economic-response release gate remains blocked

At frozen tag `phase3-diesel-sensitivity-b505c7a`, the frontend/BFF-only
three-point bundle
`output/thesis_sensitivity_diesel_b505c7a_20260823_r1/` completed fresh
Prepare and Phase-3/Rolling runs for 116, 145, and 174 JPY/L. The manifest
SHA-256 is `ad3380032e561435b2fcabb94aa8c4543232090abe5650b35705910e4a9a223f`;
its non-varied-control fingerprint is shared by all three cases. Every source
run has valid/research-ready provenance, 264/264 coverage, physical validity,
24/24 Rolling, accounting, and a 240-artifact verification result.

The price input is not a no-op: the same 436.508457111-L fuel use produces
51,763.746062 / 64,422.491318 / 77,081.236574 JPY at 116 / 145 / 174 JPY/L.
The candidates retain 32 used vehicles and 48/216 BEV/ICE trips, so the
observed response is the exact ledger cost change rather than a dispatch
change. Each case failed only `mip_gap_target_met` at 19.227307%, making the
bundle `BLOCKED`. It cannot support a claim about optimal economic dispatch
response, but it does rule out an inactive diesel-price coefficient in these
candidate runs.

## 2026-08-23: Current-HEAD bounded oracle refresh is verified but does not release the full case

`output/verification/small_integrated_oracle_scale/e3fe904_20260823/` records
a clean pre/post SHA `e3fe904ba4afb6e2890aec7a7011e082f3aa20a0`, the frozen
prepared-input SHA-256 `639b6754cccd1aef7758454b56640f968b6b1c277ec32c1c142f53f670ade558`,
and isolated 8/12/24/40-trip Phase-3 versus Phase-4 actual-cost oracle runs.
All four Phase-4 cases are exact zero-gap optima and the certificate is
`VERIFIED_BOUNDED_SMALL_INSTANCES`. Phase-3 ApproxGap is zero within numerical
tolerance where identifiable (24/40 trips); it is correctly not identifiable
at 8/12 because the reference cost is numerically zero.

This removes no 264-trip release blocker. In particular, it is not evidence of
a full-network integrated optimum, a 1% Phase-3 global-cost guarantee, an
economic response, a runtime gain, or an accepted M0--M3 effect.

## 2026-08-23: Bounded integrated-oracle comparison reproduced on the current code

The isolated-process 8/12/24/40-trip certificate at
`output/verification/small_integrated_oracle_scale/0e9413c/scale_certificate.json`
has `VERIFIED_BOUNDED_SMALL_INSTANCES` at clean SHA `0e9413c`, with exact
zero-gap Phase-4 results at every scale. The 24/40 Phase-3 ApproxGap values are
zero within numerical tolerance; the 8/12 ratios are correctly not identified
because their reference costs are numerically zero. This removes no full-scale
blocker: it is neither a 264-trip integrated-global-optimum certificate nor a
substitute for the 1% Stage-1 gap, accepted economic/stress studies, or formal
M0--M3 evidence.

## 2026-08-23: Current-SHA feasible candidate and fixed-plan stress are complete

The frozen `phase3-current-candidate-5ee35f7` normal-BFF run at
`output/2026-08-23/run_20260823_0605/` has clean SHA `5ee35f7`, valid prepared
input provenance, complete successors, 264/264 coverage, physical validation,
24/24 Rolling, executed-day accounting, and all 240 finalized artifact hashes.
Its final cost is 64,422.491318 JPY, while its 19.227307% certified Stage-1
gap remains above the declared 1% target. It is a feasible/accounting
candidate, **not** an optimality or integrated-global-optimum result.

The same-SHA fixed-decision stress artifact at
`output/diagnostics/fixed_solution_stress_5ee35f7_20260823/` has matching
source/evaluator SHA and `reoptimization_performed=false`. Only initial SOC
minus five percentage points is physically valid (0 JPY delta); the remaining
six prescribed stresses have recorded physical violations and null costs.
This resolves the current-SHA stress-input gap but does not clear the 1% gap,
accepted economic sensitivities, M0--M3 comparison, or explicit Phase-4
integration gates.

## 2026-08-23: Current-SHA electricity-price tranche is complete but blocked

The frozen `phase3-economic-sensitivity-43112a3` normal-frontend/BFF bundle at
`output/thesis_sensitivity_electricity_43112a3_20260823_r2/` completed fresh
Prepare, Phase-3, and 60-minute Rolling for 24, 30, and 36 JPY/kWh at clean SHA
`43112a3`. Its one stable non-varied-control fingerprint, matching pre/post
SHA, valid/research-ready inputs, complete successors, 264/264 coverage,
physical validation, 24/24 Rolling, accounting, and finalized-artifact hashes
show that the three diagnostic candidates are comparable on the declared
controls.

Every case nevertheless has `case_accepted=false` because the 19.227307%
certified Stage-1 gap exceeds the declared 1% target. The recorded candidates
also import 0 kWh from the grid, so varying only grid price leaves the observed
cost (64,422.491318 JPY), assignment, and energy flows unchanged. This is not
evidence that electricity price has no effect; it only identifies an
inactive-price dispatch for these time-limited candidates. The full manifest is
`BLOCKED`, and the accepted multi-point economic-sensitivity gate remains open.

## 2026-08-23: Current-SHA M0--M3 source pair is complete but blocked

The frozen `phase3-method-comparison-406d02c` bundle has explicit M1 and M3
normal-frontend/BFF runs at `output/2026-08-23/run_20260823_0658/` and
`output/2026-08-23/run_20260823_0700/`. They share the same nonempty prepared
input and source SHA-256, clean SHA `406d02c`, 264-trip scope, seed, threads,
and declared solver controls. Each has valid/research-ready input provenance,
complete successors, 264/264 coverage, physical validation, 24/24 Rolling,
accounting, and a verified 240-artifact bundle.

The M1 requested gap is met. M3 is a physical/accounting-valid 3,600-second
time-limit incumbent with a 5.205591% certified gap, not a certified integrated
optimum. The fail-closed comparison at
`output/diagnostics/method_comparison_406d02c_20260823/comparison/` verifies
all common-input, phase-identity, source-acceptance, and M0-identity checks,
but reports `BLOCKED` solely because `both_source_mip_gap_targets_met=false`.
Its M0--M3 candidate costs are diagnostic only; no formal method-effect or
release claim is cleared.

## 2026-08-23: Aggregate path-start certificate tightening awaits 264-trip measurement

The analytical path/source LP and selector MIP now add the necessary aggregate
of the original Stage-1 per-vehicle path-start limits. For each powertrain,
selected starts are at most the available vehicle count times
`min(max_start_fragments_per_vehicle, covered_day_count * daily_fragment_limit)`.
The two rows, capacities, and per-vehicle limit are hashed in the certificate
input; they retain the lower-bound relaxation because every full Stage-1
solution obeys the underlying per-vehicle constraints. A focused Gurobi test
uses two sequential but intentionally disconnected trips with one BEV and one
ICE, proving a 10-JPY LP/MIP floor when the free BEV otherwise could begin both
paths. The fresh normal-BFF run at clean commit `763c7ad` is retained at
`output/2026-08-23/run_20260823_0555/`: it records two rows, per-vehicle limit
3, capacities 105 BEV / 75 ICE, and optimal LP/MIP floors 52,712.318101 /
52,724.471363 JPY. The native Gurobi bound (52,749.163582 JPY), incumbent
(65,305.688576 JPY), one explored node, and 19.227307% certified gap are
unchanged. Stage 2 has no valid candidate and Rolling is correctly not
started. It is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** and rejects
this aggregate start-capacity condition as the current gap-closing path.

## 2026-08-23: Analytical concurrent-service certificate corrected for overnight trips

The powertrain path/source LP and selector-MIP certificate now derives service
occupancy from the canonical `_trip_interval_bounds` convention. Thus a trip
whose wall-clock arrival is earlier than its departure is represented through
the service-day boundary rather than silently omitted from the fleet-capacity
necessary condition. The focused two-trip Gurobi regression passes (LP floor
10 JPY; capacity rows for both powertrains). This correction only strengthens
future lower-bound certificates. The fresh normal-BFF 264-trip artifact at
`output/2026-08-23/run_20260823_0538/` (clean commit `9a28677`) produces zero
such rows, because this prepared input has no relevant overnight overlap. Its
Stage-1 bound, incumbent, one explored node, and 19.227307% certified gap are
unchanged; Stage 2 has no feasible candidate and Rolling is correctly not
started. It is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** and does not
alter release status.

## 2026-08-23: Independent phase-gate audit confirms the remaining evidence gaps

`scripts/audit_thesis_model_phase_gates.py` was rerun without waivers against
the complete 264-trip candidate
`output/2026-08-22/run_20260822_2125/`; the immutable result is retained at
`output/diagnostics/thesis_phase_gate_5cf5e7f_20260823/a497166_phase_gate_audit.json`
(payload SHA-256 `f6f925ce4c3fd137d8c33f8598ad9dc2b7b03f7ccafb23a4c6c8450bc9be4165`).
It verifies the candidate's prepared-input provenance, clean SHA, 264/264
coverage, physical schedule, 24/24 Rolling, final accounting, and all 240
finalized artifact hashes. It nevertheless returns `BLOCKED`: the 1% certified
gap is not met and the evidence set lacks an explicit Phase-4 integrated run,
accepted route-band/turnaround/energy/time studies, formal M0--M3 comparison,
and the required accepted economic, charger, SOC, PV, and CO2 sensitivity
families. This audit composes recorded gates only; it does not upgrade the
older candidate or any diagnostic output to a research conclusion.

## 2026-08-23: Longer Phase-3 budget does not close the certified-gap gate

The one-case duration escalation at frozen tag
`phase3-gap-escalation-f9b83ad` is stored at
`output/thesis_phase3_gap_escalation_f9b83ad_20260823_r1/`. It held the
30-JPY/kWh prepared-scenario controls, complete successor network, seed 42,
four Gurobi threads, and 1% target fixed while increasing the requested budget
to Stage 1=1650 and Stage 2=120 seconds. It again served 264/264 and passed
physical, Rolling, accounting, provenance, and clean-SHA gates, but remains
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** because the certified gap is
still 19.227307%.

The Stage-1 incumbent (65,305.688576 JPY), certified bound
(52,749.163582 JPY), and final explored-node count (1) were unchanged from
the prior short run. Thus merely granting more wall time has not strengthened
the root relaxation; it is not evidence that a still longer identical run will
meet the 1% gate.

The follow-up frozen `bound_focus` diagnostic at commit
`8c37638364c6cd99a9637e23dbbe7c3b72be49ee` is stored at
`output/thesis_phase3_bound_focus_8c37638_20260823_r1/`. It changed only the
explicitly recorded Stage-1 search controls (`MIPFocus=3`, `Presolve=2`;
`Heuristics=0.05`) while preserving the 264-trip prepared scenario,
mathematical model, candidate policy, seed, four threads, total budget, and
1% threshold. It again passed physical, Rolling, accounting, provenance, and
complete-successor checks, but its sole failed check is `mip_gap_target_met`:
19.227307% after 1,680.193 solver seconds. It retained the same incumbent,
bound, and one explored node. This bundle is **DIAGNOSTIC, NOT USED FOR
RESEARCH CONCLUSIONS**. The time-allocation and tested search-profile levers
are both falsified as sufficient fixes; the release blocker remains a weak
Stage-1 relaxation and requires a separately verified mathematical tightening,
not more of the same search.

The opt-in `explicit_root` representation of the exact fragment-transition
rows was tested at clean commit `dc759bebf169b88bbe563ae9d715cae431fcf3ad`.
Its small Gurobi regression preserves the same infeasible two-fragment case,
but the 264-trip artifact at
`output/thesis_phase3_explicit_root_dc759be_20260823_r1/` rejects it as a
full-case route: 1,243,440 rows increased Stage 1 to 1,351,502 constraints,
the 165-second primary search retained a 0.0 Gurobi bound, and Stage 2
time-limited without creating a physical-schedule artifact. The runner
correctly reports `source_artifact_validation_failed`. This is **DIAGNOSTIC,
NOT USED FOR RESEARCH CONCLUSIONS**, not a feasible candidate or lower-bound
improvement. Do not use full explicit row materialization for the release run.

A narrower pending diagnostic, `lazy_root_cuts`, keeps the lazy rows for
integer incumbents and submits only currently violated copies of those same
valid rows at fractional MIPNODE relaxations (maximum 100 per callback). The
small callback regression proves the submitted row is the existing exact
end/start restriction; it does not yet prove any 264-trip bound improvement.
No release or sensitivity conclusion may use it until its own frozen artifact
passes every gate.

The initial `8181622` trial is not valid evidence for this diagnostic because
the outer Stage-1 callback did not forward MIPNODE events, so no root user cut
could be considered. This routing defect is corrected and requires a new
clean-SHA execution; neither the zero-cut result nor its time-limited artifact
may be used for any formulation conclusion.

The routed rerun confirms zero MIPNODE events, so dynamic root user cuts are
not a viable strengthening in this Stage-1 execution path. The next pending
candidate is `lifted_root`: compact forward/reverse aggregates of the same
exact forbidden pairs, derived from the existing maximum fragment counts.
They are integer-equivalent to the pairwise restrictions but may strengthen
the fractional LP. No 264-trip conclusion exists yet.

The `lifted_root` 264-trip diagnostic at clean commit
`b484024e2ace6272b5a7cace4785887fa762925d` is also negative: 31,140 compact
rows raised Stage-1 constraints from 108,062 to 139,202, but the certified
bound, incumbent, and 19.227307% gap were identical. Its short budget ended
before physical validation (`source_artifact_validation_failed`). It is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**. Fragment-boundary
strengthening is not the current release path.

The bounded `root_cut_focus` control diagnostic kept that same mathematical
model and asked Gurobi for `MIPFocus=3`, `Presolve=2`, and generic `Cuts=3`.
The clean-SHA 264-trip artifact at `output/2026-08-23/run_20260823_0428/`
(commit `5665102c238e0ba519a402b567f6504dc371fb1e`) kept the prepared input,
complete successor network, seed, four threads, 240-second budget, candidate
policy, and 1% target fixed. Its certified bound (52,749.163582 JPY), primary
incumbent (65,305.688576 JPY), gap (19.227307%), and one explored node were
identical to the matched baseline. Stage 2 produced no valid physical
candidate and Rolling did not start, so the artifact is **DIAGNOSTIC, NOT USED
FOR RESEARCH CONCLUSIONS**. The tested generic-cut control is rejected as a
certificate path; the remaining blocker is structural, not the tested solver
profile.

The next bounded diagnostic is `stage1_root_lp_diagnostic_enabled`. It solves
a separate continuous copy of the fully built Stage-1 model and records only
aggregate fractional assignment and vehicle-activation evidence. It cannot
alter the production MIP's rows, bounds, starts, objective, or result. A
clean-SHA 264-trip run must first establish the actual fractional structure;
only then may a separately proved valid inequality be proposed.

The first clean-SHA trial at
`output/2026-08-23/run_20260823_0441/` (commit `7c090bb`) establishes a
negative but useful result: the 762,906-variable, 108,062-row completed LP
relaxation timed out after 300.234 seconds with no LP solution. Because that
early implementation let a diagnostic exceed the declared 240-second shared
Phase-3 budget, it is **DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** and
not comparable with the matched Phase-3 runs. The implementation now records
the diagnostic in `solver_settings.json`, defaults it to 30 seconds, and caps
it by the remaining shared deadline. The bounded rerun at
`output/2026-08-23/run_20260823_0452/` (commit `562fe2f`) held the prepared
input and all ordinary controls fixed, used a 30-second LP cap, and again
timed out without an LP solution after 30.239 seconds. It retained the
19.227307% Stage-1 gap, did not produce a Stage-2 physical candidate, and is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**. The unresolved blocker
remains that neither the native MIP root nor a separate full-model LP
relaxation has yielded an actionable fractional solution.

The next mathematical tightening is deliberately narrower than a reformulated
full solver: `path_powertrain_source_flow_mip` reuses the analytical
powertrain path/source LP but makes its trip/powertrain path selectors
integral. Vehicle identity, vehicle-count allocation, SOC, charger, and
time-indexed source coupling remain relaxed, so the proven objective is a
valid lower bound for every complete Stage-1 solution. It is adopted only when
the small certificate MIP reaches `optimal` within 30 seconds; a time limit is
ignored rather than being used as a bound. A fresh clean-SHA 264-trip run must
measure its lower-bound effect, Stage-1 gap, physical/rolling/accounting gates,
and compare it to the matched baseline before any release or performance claim.

That clean-SHA measurement is now at
`output/2026-08-23/run_20260823_0507/` (commit `93608f4`). The certificate
reached `optimal` in 0.637 seconds at 154 nodes and raised the analytical
weather-energy/fuel floor from 52,712.318101 to 52,724.471363 JPY. This is
strictly stronger than the LP floor but remains below the already available
52,749.163582-JPY Gurobi root bound, so the certified Stage-1 gap stayed
19.227307%. Stage 2 time-limited without a physical candidate and Rolling did
not start. The artifact passes input-provenance and clean-SHA checks but is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**; this valid lower-bound
tightening is not the remaining certificate path.

The next deliberately bounded certificate tightening retains one additional
necessary condition without changing the production Stage-1 model: at each
service instant, selected trips of a powertrain cannot exceed its available
fleet count. Vehicle identity, deadhead occupancy, SOC, chargers, depot
allocation, and time-indexed source coupling remain relaxed, so this is still
only a lower bound. The rows and fleet counts are hashed and audited. Its
small two-concurrent-trip regression passes. The clean-SHA 264-trip artifact
at `output/2026-08-23/run_20260823_0520/` (commit `98916ff`) generated zero
capacity rows for the available 35-BEV/25-ICE fleet; its LP/MIP floors stayed
52,712.318101/52,724.471363 JPY, while the native Gurobi bound remained
52,749.163582 JPY. The incumbent and 19.227307% certified gap were unchanged,
and Stage 2 had no feasible candidate, so Rolling did not start. Input
provenance and clean-SHA checks pass, but this is **DIAGNOSTIC, NOT USED FOR
RESEARCH CONCLUSIONS** and rejects aggregate concurrent-service capacity as
the current gap-closing path.

The reusable pure-ICE A/B harness was also corrected before any further
measurement: it now explicitly forwards every Stage-1 profile/diagnostic/cut
argument to the synchronous BFF worker. This prevents a positional-argument
shift from invalidating the required AB/BA controlled comparison.

## 2026-08-23: Three-point electricity-price tranche is physically valid but not research-accepted

The clean-SHA frontend/BFF Phase-3 tranche at
`output/thesis_sensitivity_electricity_19bb780_20260823_r1/` completed fresh
Prepare and solve/rolling runs for 24, 30, and 36 JPY/kWh at commit
`19bb78003cf6f44396093ca85022c2b58e56ce5f`. Every case served 264/264 trips,
passed the physical schedule, 24/24 Rolling, accounting, provenance, and
complete-successor checks without a SHA change. Each is nevertheless
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**: its only failed acceptance
check is `mip_gap_target_met`, with the same certified Stage-1 gap of
19.227307%, above the predeclared 1% target.

All three diagnostic ledgers report zero grid import and the same final cost
of 64,422.491318 JPY. This is not accepted evidence that electricity price has
no effect; under this particular time-limited candidate PV/BESS dispatch,
there was no imported grid energy to price. No economic-response, optimality,
or thesis sensitivity claim may be made from this tranche. The accepted
multi-point electricity-price sensitivity blocker remains open.

## 2026-08-23: Phase-3 aggregation A/B passed only its structural claim gate

The first completed bundle at
`output/diagnostics/pure_ice_aggregation_phase3_ab_81561d5_20260822/` remains
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS** because its effective Stage
1/2 limits drifted between representations. The fixed-control rerun at clean
commit `817d9385976a70e50fbc48aa72d34e02f5c13552` is the authoritative A/B
bundle: `output/diagnostics/pure_ice_aggregation_phase3_ab_817d938_20260823/`.

It completed alternating AB/BA isolated processes, five runs per
representation, with equal SHA/input hashes, seed, threads, request/gap, and
explicit Stage 1=435 / Stage 2=30 second limits. All ten cases served 264/264,
passed physical, 24/24 Rolling, and accounting gates without fallback or
repair. Its verdict is `PASS_STRUCTURAL_ONLY`: aggregate median size/RSS fell
from 762,906 variables / 108,062 constraints / 3,657,289,728 bytes to 520,173
/ 82,035 / 3,021,668,352 bytes. It is **not a speed claim**, because aggregate
median solver time was 480.192 seconds versus 465.531 seconds for discrete.
Presolve timing is unavailable from Gurobi. The A/B blocker is closed only for
the limited formulation-size conclusion; all release, sensitivity, and formal
comparison blockers remain.

## Historical 2026-08-22 evidence checkpoint: baseline and bounded checks pass; release remains blocked

The first fresh Phase-3 A/B discrete child on
`64c4a5a3ff1358e2f4b9397c51c5dfa078702a38` completed the underlying 264-trip
solve, physical validation, Rolling, and accounting, but its finalizer
incorrectly rejected the representation evidence. The discrete audit derived
its labelled-flow count only from clone groups eligible for the aggregate
network's stricter single-fragment condition; the target has a certified
three-fragment group and therefore yielded a false zero. The partial bundle
`output/diagnostics/pure_ice_aggregation_phase3_ab_64c4a5a_20260822/` is
**DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS**: it has no aggregate child or
comparison report. The counter and a two-fragment Phase-3 regression are
corrected. The A/B-only Phase-3 aggregate now supports the same integral
layered-fragment reset network and canonical recovery used by the bounded
Phase-4 reference; its one- and two-fragment Gurobi regressions pass. The
clean-SHA AB/BA x5 gate was open at that point and was subsequently completed
by the authoritative 2026-08-23 bundle above.

At clean SHA `a49716638a1d15567c190798f37b60e3b7920743`, the 264-trip Phase-3
baseline at `output/2026-08-22/run_20260822_2125/` passed 264/264 service,
independent physical validation, 24/24 Rolling, executed-day accounting, and
clean-SHA/fallback/repair gates. Its unique final cost source records
64,422.491318 JPY. Its Stage-1 certified gap is 19.227307% after the
900-second limit; therefore it is a feasible, cost-accounting baseline, not
an optimality or sensitivity-acceptance result.

The same-SHA fixed-decision stress artifact is complete at
`output/diagnostics/fixed_solution_stress_a497166_20260822/`. With no
reoptimization, only initial-SOC minus 5 percentage points remains physically
valid (0 JPY cost delta). The other six prescribed perturbations violate at
least one physical/PV constraint and have deliberately null cost fields. This
meets the reporting requirement, but it demonstrates limited fixed-plan
robustness rather than clearing the release gate.

The bounded small integrated-oracle certificate at
`output/verification/small_integrated_oracle_scale/a497166/` verifies
8/12/24/40 trips: Phase 4 reached `optimal` with zero solver gap at each
scale, and the 24/40 Phase-3 cost differences are within 1e-5 JPY. The 8/12
relative gaps are not identifiable because the reference cost is numerically
zero. This is not a proof of the 264-trip global optimum, a 1% full-scale
gap, or a full M0--M3 comparison.

The release is still **BLOCKED** by the 1% certified Stage-1 gap, accepted
multi-point economic and charger sensitivities, and the formal M0/M1/M2/M3
comparison. The completed Phase-3 pure-ICE AB/BA x5 bundle closes only its
formulation-size claim; it supplies neither a speed claim nor a release gate.
No historical Phase-4 representation measurement is used to fill any remaining
gap.

The Phase-3 exact-clone aggregate network, including its integral layered
fragment-reset flow and deterministic canonical-ID recovery, is implemented
behind the A/B-only diagnostic override. It is fail-closed when a nonzero
driver/switch cost, an existing no-good cut, or the exact-clone certificate
would alter the labelled model. Candidate-pool extraction is allowed because
each solution is recovered from the integral aggregate flow. Focused one- and
two-fragment aggregate/discrete Phase-3 regressions pass. The later full
264-trip AB/BA x5 execution passed its controlled structural gate, but did not
establish an improved solver-time median or clear the release gates.

## 2026-08-22 Phase-3 sensitivity correction; charger matrix remains blocked

The first charger-capacity command was stopped before it completed because its
saved request forced `phase4_integrated` on 264 trips. That mode is reserved
for the bounded 8/12/24-trip integrated oracle and cannot be accepted as a
Phase-3 economic or charger response result. No partial output from that
attempt is used. The matrix and its fail-closed audit now require
`phase3_two_stage` at requested, resolved, and executed phase; a fresh clean
Phase-3 execution is still required for all `CHARGER_COUNT_6/8/10` cases.
The first replacement `CHARGER_COUNT_6` run at clean SHA
`8044ab8995939382d68e1a1600ca6d3853df3435` reached feasible Stage 1, optimal
Stage 2, and accepted Rolling, but correctly failed closed in final reporting:
the artifact contract required the optional
`stage1_used_powertrain_composition_search.{json,csv}` despite solver metadata
recording that the composition search was disabled. This is a finalizer defect,
not an accepted sensitivity outcome. The 6-case bundle is `DIAGNOSTIC`, `NOT
USED FOR RESEARCH CONCLUSIONS`; the runner was stopped before 8/10 could
produce results. The contract now requires those artifacts only when the
solver explicitly enabled that search. A fresh clean-commit Phase-3 execution
for 6/8/10 remains required and must include the expanded pre-solve runtime
snapshot in `optimization_parameters.json`.

The clean 6-port replacement at SHA
`359cd3617206ac1d3e2ae9ff849c72e0697dffdc` is now complete, with an
accepted 240-artifact bundle, 264/264 coverage, physical validation, and
Rolling/accounting. It remains `DIAGNOSTIC`, `NOT USED FOR RESEARCH
CONCLUSIONS`: Stage 1 terminated at its 900-second time limit with a certified
19.227307% gap, above the predeclared 1% threshold. No 8/10-port case has
been run. A revised runtime-environment v3 snapshot now records physical RAM
without requiring `psutil`; a new clean 6/8/10 execution is required before
any formal charger-response conclusion.

## Historical 2026-08-22 Phase-3 A/B gate remains open

The archived ten-run pure-ICE aggregation bundle used `phase4_integrated`, not
the deployed `phase3_two_stage` method. It is retained only as a historical
structural diagnostic and cannot satisfy the requested Phase-3 A/B evidence
gate. A fresh same-SHA Phase-3-only AB/BA execution is required before making
any representation claim about the thesis method. The reused harness now
persists the Phase-3 request transformation, refuses a child whose
requested/resolved/executed mode differs from Phase 3, and records Stage-1
model/solve/bound/gap/node telemetry. The first fresh Phase-3 discrete child
at `c80fc260546a80a81622918029c1bdb3f0de6835` completed its physical and
accounting gates but had an empty representation audit. Source inspection
shows that the exact ICE-clone aggregate formulation is currently wired only
to the Phase-4 integrated builder, so this Phase-3 request did not prove that
the requested representation reached Stage 1. The parent was stopped before
the aggregate child completed. This partial bundle is `DIAGNOSTIC`, `NOT USED
FOR RESEARCH CONCLUSIONS`; it must not be compared with the historical
Phase-4 bundle. The harness now fails immediately when the Stage-1
representation audit is missing or mismatched. A genuine Phase-3 aggregation
implementation with an exact Stage-1 recovery/audit contract is required
before rerunning AB/BA x 5.

## 2026-08-22 charger sensitivity executable; SOC and stress paths remain blocked

`CHARGER_COUNT_6/8/10` is now an audited frontend/BFF family: all cases use a
generated 90-kW single-port inventory and vary the effective charger count.
No full-scale result has yet been run. The current BFF `initial_soc_percent`
is only a fallback when a vehicle lacks explicit SOC; it cannot support an
honest uniform -5-point initial-SOC sensitivity. A dedicated explicit policy
and fixed-solution stress evaluator remain required before those release gates
can be cleared.

## 2026-08-22 repeated pure-ICE A/B completed: structural benefit only

The required ten-run measurement completed at clean frozen commit
`7ae60bef01cd6c30d7c82befcae28c3de692d2df`, saved at
`output/diagnostics/pure_ice_aggregation_ab_repeated_7ae60be/`. It uses five
AB/BA-alternating pairs, isolated child processes, fixed seed 42/four threads/
900 seconds/requested 1% gap, and the same prepared-input SHA-256
`aa101b4b95364929d2683776b03a4347f06fe7157a8a9ed7e31138968a9fd5f6` for all
ten runs. Every case passed 264/264 coverage, physical validation, 24/24
Rolling, accounting, SHA/control checks, and fallback/repair exclusion.

The median aggregate representation reduces total variables from 780,113 to
536,180 and constraints from 355,581 to 233,579, with complete model-build
time 80.547 to 60.066 seconds. However, its median solver time is 644.374
seconds versus 624.566 seconds for discrete, with essentially unchanged
process-tree RSS. Both medians have 59,466.604450 JPY incumbent,
56,086.529926 JPY certified bound, and 5.683988% certified gap. The
machine-readable verdict is `PASS_STRUCTURAL_ONLY`: the result supports only
the checked formulation-size reduction, not a speedup, 1%-gap certificate, or
264-trip global-optimality claim. Presolve time is explicitly unavailable in
the Gurobi artifact, not inferred. The broader release remains blocked by the
separate sensitivity, stress, and formal-comparison gates.

## 2026-08-22 corrected electricity-price tranche is diagnostic, not accepted

The corrected three-point electricity-price execution completed from clean
SHA `c4c2ef4aca3f6bb156da10dda68be78867ee23ce` at
`output/thesis_sensitivity_electricity_low_pv_20260822_c4c2ef4/`. The
effective grid prices are exactly 24, 30, and 36 JPY/kWh, while diesel remains
145 JPY/L; submitted price controls and all non-varied controls match their
audited contracts. Each run served 264/264 trips, passed physical validation,
accepted Rolling accounting, and preserved Git provenance.

However, every case terminated at the time limit above the predeclared 1% MIP
gap: 5.099181%, 5.227442%, and 5.330183%, respectively. The matrix manifest is
therefore `BLOCKED`, and all three points are `DIAGNOSTIC`, `NOT USED FOR
RESEARCH CONCLUSIONS`. The 24/30 JPY incumbents have the same 78/186 BEV/ICE
trip split and 12.528570 kWh grid import; the 36 JPY incumbent has 76/188 and
zero import. This may describe the recorded incumbents only; it does not
establish an optimal price-response effect or clear the economic-sensitivity
release gate.

## 2026-08-22 bounded small integrated-oracle evidence verified; release remains blocked

The existing July 10-trip weather audits cannot support an integrated
actual-cost oracle claim. Their stored Phase-4 cases have
`objective_is_actual_cost=false`: the audit aligned cost flags in the problem
but did not request the engine's explicit integrated actual-cost contract. The
old predicate checked objective/accounting equality but omitted the exported
actual-cost flag, allowing a false-positive exact-oracle label.

The runner now fails closed on the explicit request, structural contract,
actual-cost flag, accounting equality, terminal energy balance, exact solver
status, complete coverage, and hard physical checks. A new scale certificate
runs 8, 12, and 24 trips in isolated processes and records the Phase-3 cost
deviation from each eligible integrated optimum. The fresh certificate at
`output/verification/small_integrated_oracle_scale/242f35e/` completed at
clean SHA `242f35e3698052d3e6e314ff8a377100b515e437`: 8/12/24 all have exact
Phase-4 status `optimal`, zero final gap, complete feasible schedules, and no
certificate blockers. This establishes bounded small-instance formulation
evidence only. It is not a full-network optimality result.

The first corrected-run attempt also exposed, and failed closed on, a separate
prepared-input materialization defect: an empty current `comparison_type`
erased the frozen `same_service_date_pv_counterfactual` declaration and caused
the calendar validator to treat the 2025-08-10 PV source as an actual-service
weather claim. The audit now restores only explicit prepared contract fields
and rejects a conflicting non-empty scenario value. A fresh clean-commit
8/12/24 execution is still required.

The subsequent clean execution exposed a second objective-boundary defect:
the frozen `research_lexicographic_v1` preset caused the Phase-4 reference to
minimize vehicle-days before canonical cost. Its artifact correctly reported
`integrated_actual_cost_objective_requested=false`, so the certificate stayed
blocked. The reference now explicitly uses scalar canonical actual cost while
Phase 3 retains its deployed policy and is compared by final accounting cost.
The clean failed bundle is retained as diagnostic history. The scalar-cost
reference was then run at the SHA above; no failed artifact was relabelled.

The successful run also showed that the 8- and 12-trip exact costs are
numerically zero. Relative gap is therefore intentionally
`not_identifiable_zero_reference_cost` for those sizes; their raw accounting
deltas remain in the artifact. The 24-trip gap is `0.0` within the documented
`1e-5 JPY` tolerance. Neither result establishes a 264-trip cost gap or
runtime-performance claim, so the broader release remains blocked pending
the separate full-scale and sensitivity gates.

## 2026-08-21 same-SHA A/B complete; structural benefit only

The exact ICE-clone discrete/pure-aggregate selector is internal to the solver
process and reuses the pre-existing aggregation flag. It does not change the
public BFF/frontend/scenario contracts. The A/B harness invokes the normal BFF
worker synchronously with the same canonical prepared input and controls,
including 24 hourly Rolling steps, physical validation, and canonical
accounting. Audit artifacts identify the representation actually used and
count vehicle-labelled versus aggregate-network variables.

The required small exact parity test passes for objective, coverage,
vehicle-ID-independent duties, fuel, deadhead, CO2, vehicle-days, and canonical
ID recovery. The 264-trip A/B measurement is also complete at clean commit
`a145cf3a8b9cba0e4d97c48f800fba9ff07a1e69`. Both cases used the same
canonical prepared input and Phase-4 integrated request, seed 42, four threads,
900-second budget, requested 1% gap, complete successor network, and costs;
only the ICE representation changed.

Both cases served 264/264 trips with 17 ICE buses, returned the identical
61,970.856672 JPY incumbent and 57,986.661708 JPY certified bound, and passed
physical validation, 24/24 Rolling, accounting reconciliation, and the
fallback/repair exclusions. Pure aggregation reduced total variables from
780,113 to 536,180, binaries from 739,728 to 507,244, constraints from 355,581
to 233,579, and nonzero coefficients from 3,409,213 to 2,044,502. Complete
model-build time fell by 25.55%.

This structural reduction did not improve the solve. Total solver time rose
from 476.701 to 517.938 seconds (+8.65%), and both cases stopped at the time
limit with the same 6.429143% certified gap. The verdict is therefore
`PASS_STRUCTURAL_ONLY`: exact representation equivalence and formulation-size
reduction are supported, but a speedup, a 1% certificate, and global optimality
are not. The authoritative bundle is
`output/diagnostics/pure_ice_aggregation_ab_a145cf3/`.

This checkpoint does not authorize a research release or a formal PV-pair
claim. Column generation, set partitioning, high/low-PV reruns, M0-M3,
sensitivity sweeps, and time-step comparisons remain out of scope.

## 2026-08-15 pure aggregate measured; root-proof blocker remains

The frozen frontend/BFF diagnostic at clean commit `94ce217` is complete in
`output/2026-08-15/run_20260815_1155`. It reduced the initial formulation from
848,980 to 536,180 variables and the pre-optimize wall time from 165.812070 to
130.419562 seconds relative to `f1690c6`. It also reduced constraints from
286,282 to 233,579 while retaining all 11,310 feasible successor arcs.

This did not improve the proof. Gurobi optimize time increased from 474.744153
to 505.784332 seconds, the explored node count remained one, and the incumbent,
certified bound and certified gap remained respectively 61,883.346234 JPY,
57,986.661708 JPY and 6.296823%. The requested 1% gap is not established.
Consequently the smaller exact formulation is retained as an implementation
improvement, but it is not evidence of global optimality or of a
hundreds-of-seconds 1% certificate.

The candidate itself is physically valid: all 264 trips are served, 24/24
Rolling steps are accepted, executed-day accounting is eligible, and artifact
completeness is 240/240. These gates do not override
`mip_gap_target_met=false`; `research_submission_ready=false` and teacher
release remains **BLOCKED**. The next exact-work target is the root lower
bound/decomposition rather than another unchanged 900-second rerun.

## 2026-08-15 pure aggregate implementation complete; measurement pending

The continuous vehicle-label extension identified by the `f1690c6` negative
run has now been removed for the certified exact ICE-clone group. Its
assignment, direct connection, start and end decisions exist only in the
integral group/layer/reset network. Strict coverage and all representative
fuel, deadhead, CO2, fixed-cost and vehicle-day coefficients are attached
directly to that network; canonical vehicle IDs are recovered from integral
paths, not repaired. The optimization applies this representation only when
the certificate also shows a strictly positive binary-variable reduction, so
nonreducing small groups retain their original discrete flow.

Small exact comparisons match the original discrete objective, coverage,
path count and used IDs while reducing the one-trip model from 398 to 300
variables. Single- and two-fragment recovery, complete warm starts, focused
research-contract tests and all 1,491 repository tests pass. The audit schema
is now `exact_combustion_clone_flow_aggregation_audit_v3` and explicitly
records that zero continuous label-flow variables remain.

The frozen measurement is now recorded above. It confirms the implementation
benefit but leaves the research proof gate **BLOCKED**.

## 2026-08-15 exact proof-performance repairs measured; proof blocker remains

The first independent BEV-coefficient run established a valid schedule but
also exposed an exact-proof bottleneck: 678,600 vehicle-labelled connection
binaries, one explored root node, a raw Gurobi bound of 0 JPY after 2,814
seconds, and a separate valid analytical floor of 57,986.661708 JPY. This is
not evidence that the feasible incumbent is optimal.

Three formulation-equivalent repairs are now implemented. First, the
certified `BestObjStop` threshold is installed before search whenever its
lower-bound certificate is valid, rather than only when the initial incumbent
already meets it. Second, the certified cost floor is the explicit lower bound
of an equality-linked canonical-cost objective variable, so it is visible in
the objective domain before root relaxation completes. Third, exact-identical
vehicle duties are ordered by assigned-trip count and, only when one start per
vehicle is proven, by equal-count chronological start trip. A multi-fragment-
safe row also orders equal-count duties by the sum of chronological assignment
ranks. This eliminates vehicle-ID permutations while preserving one member of
every unlabeled duty orbit. Domain-mismatch cases skip the stronger rows.

None of these repairs changes trip coverage, successor arcs, SOC, charging,
PV/BESS flows, objective coefficients, canonical accounting, or the 1% target.
They also do not retroactively certify `run_20260815_0747`. The full repository
regression passes (`1487 passed`); the required frozen-commit frontend/BFF
diagnostic and its still-blocked result are recorded below.

The clean-SHA rerun at `5d0a1c5` has now measured those fields. With a
900-second Day-ahead diagnostic request, Gurobi used a 466.355-second
integrated cost stage and the full frontend/Prepare/Rolling runner took
1,122.977 seconds. Raw and certified bounds both equal 57,986.661708 JPY,
`BestObjStop` was active at 58,572.385564 JPY, and all physical/Rolling/
accounting checks passed. The incumbent nevertheless remained
61,883.346234 JPY at one explored node, leaving the same 6.296823% gap.

This resolves the false 0-JPY raw-bound evidence but not Phase 2. The stronger
start-trip symmetry also added zero rows because the configured fragment limit
is 100 rather than one. The next exact performance change must address the
678,600 vehicle-labelled connection binaries or strengthen their relaxation;
running the other nine cases with longer limits is not accepted as a remedy.
Research release remains **BLOCKED**.

The follow-on assignment-rank symmetry was measured at frozen commit
`7fe44ebdee8a211c47704d79b066685582ef72be`. It gave the current 25-ICE clone
group 24 additional exact rows even with a fragment limit of 100, for 48 total
duty-order rows. The matched run retained the same incumbent, bound, 6.296823%
gap and one explored node. Solve time was 470.404 seconds versus 467.776
seconds for the preceding control, and complete wall time was 1,123.794 versus
1,122.977 seconds. This single pair is not a runtime distribution, but it
provides no evidence of a speedup and rules out treating the added rows as the
solution to the bottleneck. The run remains `BLOCKED` solely by the 1% gap
target despite complete coverage, physical validity, 24/24 Rolling and
accounting reconciliation.

Further row-only clone symmetry tuning is no longer the next action. The
immediate safe construction change now batches the four dominant vehicle-
indexed unit-interval families through Gurobi `addVars` while preserving every
key, bound and variable type. The search profile exports its variable count,
actual API-call count, batch-build wall time and full pre-optimization wall
time. Focused tests (`134 passed`) and the full regression (`1489 passed` in
164.85 seconds) succeed. The frozen `10a6621` comparison created 726,120 such
variables with four calls in 1.748726 seconds, but pre-optimization time only
changed from a derived 168.229836 to a measured 166.509116 seconds. Solve time
changed from 470.403739 to 474.988037 seconds with identical incumbent, bound,
6.296823% gap and one node. Complete wall time changed from 1,123.793917 to
1,117.950286 seconds; this single noisy pair does not support a speedup claim.

The run nevertheless passed all non-optimality gates: 264/264 coverage,
physical validity, 24/24 Rolling, accounting and clean-SHA provenance. It is
`BLOCKED` solely by `mip_gap_target_met`. Variable batching is retained as an
exact implementation cleanup, but the evidence rules it out as the main
bottleneck. The required architectural change is now an exact duty/path or
aggregated network formulation that removes vehicle-labelled connection
binaries without successor pruning, fallback, or post-solve repair.

That first exact aggregated network has now been measured at frozen commit
`f1690c6a9a6145086a96df05193794065e6c2f40`. Its three-layer clone network was
correctly applied to the 25-ICE group and reduced initial binary variables
from 739,728 to 507,194 and rows from 355,581 to 286,282. However, retaining
the labelled flow as continuous variables increased total variables from
780,113 to 848,980. Pre-optimization time was 165.812070 seconds and the
cost-stage solve was 474.744153 seconds, essentially equal to the `10a6621`
control. Incumbent, bound, gap, and node count were exactly unchanged at
61,883.346234 JPY, 57,986.661708 JPY, 6.296823%, and one node.

The run served 264/264 trips and passed physical validation, 24/24 Rolling,
accounting and clean-SHA provenance, but `mip_gap_target_met` failed. Therefore
the exact layered representation is retained for correctness evidence but is
not a performance solution. The active proof blocker is now the continuous
vehicle-labelled extended flow/root relaxation itself. Research release stays
**BLOCKED**; the next implementation must remove that extension or introduce a
certified decomposition. Any ALNS/Lagrangian/heuristic alternative must remain
a separately labelled approximation result.

## 2026-08-15 independent coefficient sensitivity implemented; solves pending

Phase 2 previously relied on a common `trip_energy_sensitivity_scale` that
multiplied both BEV kWh and ICE liters. The observed BEV/ICE response therefore
could not identify whether the BEV coefficient, the ICE coefficient, or their
shared distance/demand basis caused the change.

The frontend, Prepare contract and canonical problem now carry independent
`bev_trip_energy_sensitivity_scale` and
`ice_trip_fuel_sensitivity_scale` values. The thesis matrix declares five
one-factor levels (0.8--1.2) for each powertrain and fixes the other factor at
1.0. The execution auditor checks the effective coefficient, common controls,
prepared trip structure, accepted physical/Rolling/accounting evidence, Git
SHA and artifact hashes. The Phase-2 gate requires both independent families;
the legacy common-demand family alone can no longer complete it.

No new route/direction empirical coefficients were invented. The current
`literature_proxy_v1` is still a deterministic proxy whose BEV allocation uses
distance and duration and whose ICE allocation uses distance and peak-time
bands. Empirical route/direction calibration remains unavailable and must be
described as a limitation or replaced by sourced input data.

The prepared schema is now `v11_powertrain_coefficient_sensitivity`; fresh
Prepare is mandatory. The independent matrices have not been optimized at the
current clean SHA. Consequently, this is implementation evidence only and
Phase 2 plus the overall research release remain **BLOCKED**.

Phase 6 also now has declared but unexecuted economic price families: flat
grid purchase price 24/30/36 JPY/kWh and diesel price 116/145/174 JPY/L. The
runner verifies each effective canonical marginal price and writes both values
to the result table. These cases are not a price-response claim until all
three points per family complete from a clean frozen SHA with their existing
physical, Rolling, accounting, provenance, and gap gates.

The first attempted 24 JPY/kWh point is explicitly invalidated: the saved
request's 30 JPY/kWh TOU band took precedence over the changed flat-price
field, so the artifact's effective price remained 30 and its parameter gate
failed. The compiler now synchronizes a uniform TOU band with the declared
flat price and rejects non-uniform tariffs. A fresh clean-SHA three-point run
is required; the cancelled remainder and the failed 24 JPY/kWh artifact are
diagnostic only.

A first clean-commit execution at `b9e5234` now provides one diagnostic point.
The low-PV `BEV_ENERGY_1.2` case correctly held the common and ICE factors at
1.0, served 264/264 trips, assigned 74 BEV and 190 ICE trips, used 15 BEVs and
17 ICE buses, passed physical validation, accepted 24/24 Rolling steps and
reconciled executed accounting. It did not clear the Phase-2 gate: status was
`time_limit`, certified gap was 6.296823%, and full runner wall time was
3,824.702 seconds. The manifest therefore remains `BLOCKED` solely by
`mip_gap_target_met` after every other case check passed.

This result makes the next blocker concrete. Completing the other nine
one-factor runs with the same 3,600-second control would require hours and
would still not certify a transition boundary if their gaps remain above 1%.
The next action is to diagnose and strengthen the Phase-2 lower bound or exact
formulation without changing the feasible region, objective, coefficients or
acceptance threshold. The single diagnostic must not be compared as a
same-SHA 1.0/1.2 effect until the matching current-SHA baseline exists.

## 2026-08-15 clean-SHA high-PV v6 diagnostic: incumbent improved, 1% still blocked

A fresh frontend/BFF Day-ahead diagnostic at clean SHA `3353318` used the
saved 1,000 kW PV and 6,000 kWh BESS controls with the same 264-trip scope,
flat 30 JPY/kWh tariff and zero demand charge. It passed independent physical
checks and returned 30 BEVs/2 ICE buses for 231/33 trips at 650,390.858978 JPY
in 607.038977 seconds. The 640,000 JPY certified lower bound left a 1.597633%
gap, so it does not satisfy the predeclared 1% target and did not execute the
required 24-step Rolling chain. Release remains **BLOCKED**.

The run does validate the v6 correction. It generated 7,305 suffix-exchange
candidates, evaluated 57 candidates, retained 28.614860 seconds when local
search began, and strictly improved the incumbent in each of three permitted
suffix rounds. The selected 30/2 candidate is 9,315.999165 JPY cheaper than
the previous v5 3,600-second high-PV incumbent. Thus the previous 28/4 result
cannot be treated as evidence of a stable sunny-day optimum.

The remaining immediate defect is now explicit: the server stopped after the
configured third improving round, then spent 23.873713 seconds on route-band
repartition without generating a candidate. The same 120-second allowance is
rebalanced to 105 seconds of fixed-duty/path-changing search, 15 seconds of
route-band search and at most eight improving rounds. No weather bias, BEV
minimum, objective change, lower-bound change or extra runtime is introduced.
A new clean-SHA diagnostic is required before deciding whether a stronger
lower bound is still necessary.

The first 105/15-second rerun did not clear the blocker. It exhausted its
64-candidate ceiling before the expanded wall window, returned 29 BEVs/3 ICE
buses at 655,537.125622 JPY, and left a 2.370137% gap. This negative result is
retained. The candidate ceiling is now 128 under the same 120-second wall
budget; v6 consequently reserves 32 path-changing evaluations. Research
release remains **BLOCKED** until a fresh run proves the effect and completes
the formal Rolling/pair gates.

The clean-SHA 128-candidate measurement subsequently reached 31 BEVs/1 ICE
bus at 649,936.120270 JPY, but its cost gap was still 1.528784%. A separate
minimum-ICE-fuel run found 35.884956 L, yet the old multi-objective API path
did not persist the primary best bound. Neither result proves that one ICE bus
or that fuel quantity is unavoidable. The policy solver now uses sequential
scalar stages and stops before secondary cost unless the fuel optimum is
certified. A fresh run is required; research release remains **BLOCKED**.

The first sequential diagnostic at clean SHA `0dbdc7d` correctly exported a
0 L primary bound, 100% fuel gap, and no secondary-cost solve. Its seed audit
also proved that multiple 32-BEV/0-ICE fixed-assignment candidates were already
Stage-2 and physically feasible. They were not selected because the seed
neighborhood always ranked by canonical cost, even under the minimum-fuel
policy. That P1 objective-boundary bug is fixed: only the policy path selects a
validated zero-ICE seed, while the formal cost-minimization path remains
unchanged. The correction still requires a fresh clean-SHA rerun; formal pair
release remains **BLOCKED**.

That policy rerun is now complete at clean SHA `abc9257`. It selected a
validated 32-BEV/0-ICE seed, served all 264 trips with BEVs, and certified the
minimum-fuel objective at 0 L in 0.209859 seconds. Physical validation is
VALID. The subsequent all-BEV cost stage timed out with a 0 JPY raw bound, so
650,053.898604 JPY is only an all-BEV incumbent. It is 117.778334 JPY above
the validated 31/1 cost incumbent because +5,501.622710 JPY electricity
slightly exceeds -5,382.743360 JPY fuel and -1.101016 JPY CO2 savings. This
resolves the policy-path selection bug but does not certify the unrestricted
cost optimum or the controlled high/low-PV formal pair. Release remains
**BLOCKED** pending a fresh unrestricted pair and all pair/Rolling gates.

## 2026-08-15 formal `79e61ae` pair: low PV certified, high PV still blocked

The controlled pair was executed through fresh Prepare and the normal
frontend/BFF formal path from clean SHA
`79e61ae8cd43acb350c452e7f9eed68bf79507c1`. Both cases used the same
2025-08-05 WEEKDAY timetable, 264 trips, 60 active vehicles, ten chargers,
flat 30 JPY/kWh energy price, zero demand charge, 1,000 kW PV rating,
6,000 kWh BESS, four Gurobi threads, seed 42 and a predeclared 1% gap. Only
the hashed PV curve differed.

Low PV completed Phase 4 in 794.541743 seconds with a 0.420907% independent
certificate. It used 15 BEVs and 17 ICE buses for 75 and 189 trips. High PV
used 3,606.883660 seconds but stopped at 2.987214%; it used 28 BEVs and four
ICE buses for 202 and 62 trips. Both served 264/264 trips, passed physical
validation, accepted 24/24 Rolling steps and reconciled executed-day
accounting. Therefore the controlled response is physically observed, but
formal pair release remains **BLOCKED** by the high-PV gap.

The run also exposed an independent reporting P1: the case gate required the
retired Phase-3 candidate-order and initial-candidate-budget fields even when
the current v5 incumbent neighborhood was present and fully audited. This made
`solver_controls_match_formal_request=false` for both cases and was the only
case-gate failure for low PV. The runner now validates the v5 schema, requested
and emitted budgets, evaluation counts, termination evidence, and absence of
weather bias. Because this fix changes the Git SHA, it does not retroactively
upgrade the `79e61ae` artifacts. A new clean-commit run is required before the
low-PV case or the pair can be marked current-SHA accepted.

The complete progress-only bundle, including seven figures and six CSV tables,
is `output/formal_pair_20260815_seed_restart_79e61ae_flat30_pv1000_bess6000_gap01_r1`.
Its ZIP is adjacent to that directory. The literature/timing interpretation is
documented in
`docs/notes/LITERATURE_SOLVE_TIME_FORMAL_PAIR_20260815.md`.

The high-PV v5 audit also proves an incumbent-search defect. It recorded 53
candidate evaluations and 99.853669 seconds total neighborhood time, but
`duty_suffix_exchange_candidates_generated=0`, zero powertrain-swap rounds and
zero identity-exchange rounds. Candidate-count reserve existed, while the
75-second fixed-duty wall deadline was exhausted by pairwise/matching and two
sequential activation rounds. Moreover, the sequential limit retained only
four downstream evaluations instead of the declared 16 local-search slots.

The v6 implementation reserves both resources. With the production controls,
16 evaluations and 30 of the existing 75 seconds are reserved for suffix and
powertrain path changes. Pairwise search stops before a separate matching
reserve, and matching/sequential search stops before the local-search wall
boundary. No new solver time, fleet restriction, BEV minimum, weather bias or
feasibility cut is introduced. Regression tests reproduce the old starvation
with a synthetic ten-second budget and prove that suffix exchange is reached
under v6. Fresh clean-SHA runtime evidence remains required; release is still
**BLOCKED**.

## 2026-08-15 stronger seed found diagnostically; fresh formal run pending

The literature audit confirms that many published hundreds-of-seconds results
solve fixed-assignment energy dispatch, a decomposed relaxation, or a heuristic
rather than the current complete individual-trip integrated MILP. Nevertheless,
the comparison exposed a local implementation defect: the production
64-candidate seed budget could be exhausted before enabled trip-chain and
route-band neighborhoods were reached.

The seed search now reserves fixed-duty local-search capacity, restarts
whole-duty BEV activation from a newly improved incumbent, and gives route-band
repartition a separate finite candidate allowance consistent with its separate
wall-clock budget. All candidates still require exact fixed-assignment Stage 2,
independent physical validation, and canonical accounting. The integrated
feasible region, objective, full successor network, and declared 1% gap remain
unchanged.

A diagnostic reconstruction of the preserved `8066330` low-PV seed reproduced
707,518.152327 JPY at 13 BEVs/19 ICEs. The revised fixed-duty neighborhood found
697,433.686483 JPY at 15 BEVs/17 ICEs in 32.178553 seconds. Against the unchanged
694,498.136390 JPY independent lower bound, this candidate is within 0.420907%.
This is not a current-SHA formal run and cannot clear Phase 0. A clean commit,
fresh Prepare, normal frontend/BFF formal execution, accepted 24-step Rolling,
physical validation, accounting reconciliation, and artifact completeness are
still required. Research release remains **BLOCKED** until that evidence exists.

## 2026-08-14 Phase 4 time-limit defect repaired; fresh timing evidence pending

The clean-SHA diagnostic
`output/2026-08-14/run_20260814_2056` used fresh Prepare and the normal
frontend/BFF route with a displayed 600-second limit. It revealed two separate
budgets: the Phase 3 seed consumed 607.319707 wall seconds and the integrated
solve then consumed 601.350376 seconds. The job therefore took more than
twenty minutes before reporting finalization even though the UI said 600
seconds. The seed's Gurobi runtime was only 61.586327 seconds; repeated
composition-model construction and the unused-BEV neighborhood caused the
excess wall time.

The reachable Phase 4 path now uses one shared wall-clock budget. The neutral
Phase 3 hand-off searches one physical incumbent only, and the remaining time
is passed to an integrated adapter that also charges model construction and
fixed-dispatch recourse against the same deadline. This is not a heuristic
fleet restriction: all powertrain compositions remain present in the
integrated MILP. Separate Phase 3 composition-sensitivity experiments still
require adjacent alternatives or infeasibility certificates.

The diagnostic also showed that exact ICE clone-flow aggregation does not
apply to the current multi-fragment contract. With `daily_fragment_limit=3`
and start/end fragment limits of 100, its single-fragment proof correctly
fails closed. The model remained at 780,112 variables and ended at
650,298.979 JPY with a 640,000 JPY bound and 1.583730% certified gap. This is
slightly worse than the historical 600-second diagnostic and is not evidence
of a performance gain.

Code and focused tests enforce the shared budget. The first post-repair clean
full-size run below failed before producing a valid integrated incumbent, so
objective, physical validation, accounting, and the 1% gap must still be
remeasured through fresh Prepare. Research release remains **BLOCKED**.

The first post-repair run at SHA `6b090e4` measured 628.656745 seconds from
HTTP submit to terminal and 604.204202 seconds inside optimization for a
600-second request, proving that the former 1200-second solver duplication was
removed. It did **not** produce a valid optimization result. The one-candidate
seed spent 142.768869 seconds because Stage 1 received an 80-second Gurobi
limit before about 60 seconds of model build, then Stage 2 had no remaining
time. Phase 4 received no verified start, found no incumbent in its remaining
451.735358 seconds, and nonresearch fallback was rejected by artifact
completeness due to absent SOC evidence. This is a valid fail-closed outcome,
not a result to report.

The nested Stage-1 budget is now recalculated immediately before Gurobi and
the requested Stage-1/Stage-2 split is proportionally scaled over the actual
remaining wall time. This follow-up code has focused tests but has not yet been
measured on 264 trips. The blocker therefore remains open.

## 2026-08-14 connection-buffer audit implemented; optimized evidence pending

The canonical connection rule now has a separately auditable operating margin:

`arrival + base_turnaround + turnaround_buffer + deadhead <= next departure`.

`turnaround_buffer_min` defaults to zero, so existing scenario mathematics do
not change until the input explicitly selects a margin. Prepare recomputes the
route-band-OFF relaxed transition network at additive 5, 10, and 15 minute
buffers and exports `turnaround_buffer_sensitivity_audit_v1`. Its control hash,
connection counts, vehicle lower bounds, and monotonic checks are part of the
prepared evidence. A failed transition rebuild or invalid sensitivity now
blocks teacher release; an empty audit can no longer masquerade as zero missing
deadhead OD entries.
The same route-band and turnaround fields are now fixed controls in the
Rolling comparison-case hash; a high/low-PV pair with different transition
rules fails comparison rather than being accepted as PV-only.

This closes the missing structural audit and the fail-open bug. The thesis
experiment runner now also declares `TURNAROUND_BUFFER_5`,
`TURNAROUND_BUFFER_10`, and `TURNAROUND_BUFFER_15`, submits each through fresh
Prepare and the frontend/BFF Phase-4 path, verifies the effective buffer in
canonical metadata, and exports it in the comparison CSV. This is runner
support only: the three cases have not been solved, and no certified effect on
cost, BEV trips, SOC, or runtime is claimed. Route-band ON/OFF optimized
comparison also remains pending. Fresh Prepare is mandatory because the
prepared schema is now `v10_turnaround_buffer_sensitivity`. Research release
remains **BLOCKED**.

## 2026-08-14 high-PV optimality proof: model-size and lower-bound blocker

The local literature audit is recorded in
[`LITERATURE_SOLVE_TIME_COMPARISON_20260814.md`](LITERATURE_SOLVE_TIME_COMPARISON_20260814.md).
Reported tens-to-hundreds-of-seconds results are common, but the closest
integrated dispatch comparison uses a heuristic for the large instance:
No06 reports 202.3 seconds for ALNS-SA on 418 trips, while Gurobi found no
feasible solution for its 200- and 418-trip cases within six hours. Other
fast examples mainly keep vehicle schedules fixed and optimize charging and
energy flows.

The frozen `f46f1e8` high-PV run has a feasible incumbent from the start but
ends at 3,600.80 seconds with a 1.574% certified gap. Its complete network
contains 678,600 vehicle-indexed successor arcs; the recorded fixed-recourse
model has 780,112 variables and 1,598,973 constraints. The matching low-PV
run is certified to 0.547% in 18.36 seconds because its independent
energy/fuel lower bound contributes 54,498.14 JPY. In the high-PV run, the
pooled free-PV relaxation makes the energy/fuel floor zero, leaving only the
640,000 JPY vehicle-day floor.

Therefore this is primarily a proof and formulation-size blocker, not a
failure to find a physically feasible plan. Do not shorten the time limit and
relabel the incumbent as optimal. The required performance work is to reduce
vehicle-indexed arc symmetry through a certified path-cover/column or
decomposition formulation and to strengthen the high-PV lower bound without
double counting. A separate ALNS-style operational candidate may target
hundreds of seconds, but it must remain explicitly near-optimal and cannot
replace the formal full-network certificate.

### Exact-clone ICE layered group-flow convexification: implemented; fresh timing evidence pending

Phase 4 continues to use Gurobi's automatic symmetry policy; the existing clean
`Symmetry=2` sensitivity regressed to a 100% gap and must not be reintroduced
without new controlled evidence. The exported
`integrated_exact_combustion_clone_flow_aggregation_audit` does not assume
that equal vehicle fields alone permit aggregation. It requires identical
assignment and complete-transition domains, a one-day acyclic chronological
successor network, and a conservative fuel proof. The proof now covers the
actual multi-fragment contract: the configured fragment-layer count multiplied
by the worst single-fragment startup, service, connection-deadhead and return
fuel must fit inside initial fuel minus reserve.

The integrated model consumes the certificate when `driver_cost=false`. For
the single largest certified group, per-vehicle-label flow and activation
variables are continuous while binary aggregate and fragment-layer variables
retain an integral group path cover. Direct arcs stay inside a layer. Canonical
depot-reset arcs connect each fragment end only to the next layer; every
higher-layer start requires one reset predecessor and each end can feed at
most one reset. Used count is the layer-0 root count and also the number of
final fragment ends net of resets. Integral paths are decomposed
deterministically back to canonical vehicle IDs. Fuel state is redundant only
under the conservative certificate. This is exact representation recovery,
not post-solve feasibility repair.

The reformulation fails closed when path-specific driver cost is active or any
structural/fuel/reset proof fails. Small exact regressions show objective
equivalence with the original binary-label model, preserve a two-path/two-bus
parallel case, recover two fragments on one vehicle, and accept a complete
two-fragment Phase-3 MIP start. The saved 264-trip input has an exact 25-ICE
group with 264 assignment nodes and 11,310 direct arcs per clone. Its longest
single fragment consumes 46.036430 L. The actual three-fragment limit therefore
requires at most 138.109290 L, below 144.0 L usable initial fuel. Canonical
enumeration produces 10,829 valid depot-reset pairs.

For that group, the projected formulation relaxes 302,600 labelled binary
variables and adds 70,067 aggregate/layer/reset binaries, reducing the binary
count by 232,533. It retains the label extension as continuous variables, so
the total variable count may rise and no speedup follows from the count alone.
The earlier fresh SHA `1025461` result predates this layered implementation and
must not be reused as performance evidence. A clean commit, fresh Prepare, and
frontend/BFF run must measure model construction, presolve, root relaxation,
incumbent, bound, nodes, gap, physical validation, Rolling, and accounting.
Until that run meets the declared 1% gap and all downstream gates, research
release remains **BLOCKED**.

### Stage-1 exact-clone equal-count rank symmetry: rejected after controlled diagnostic

The clean `1aaaa27` candidate supplied the existing canonical chronological
trip order to the Phase-3 Stage-1 clone-duty helper, adding 24 equal-count
rank-sum rows for the exact 25-ICE-clone group while preserving all frozen
inputs and controls. Its artifact at
`output/diagnostics/stage1_clone_rank_root_1aaaa27_20260824/` verifies hashes
and BFF input provenance. The quality-qualified root LP value,
`52,749.16358183724` JPY, differs from the unstrengthened
`52,749.16358183805` JPY by about `-8.1e-10` JPY, inside the predeclared
`1e-5`-JPY tolerance. It therefore provides no relaxation improvement.

The 435-second primary MIP obtained no raw Gurobi bound beyond `0`; only the
analytical floor `52,724.471326575986` JPY certified a `19.2651169%` gap,
worse than the prior `19.2273066%`. Although downstream physical, Rolling, and
accounting checks completed, this is **DIAGNOSTIC, NOT USED FOR RESEARCH
CONCLUSIONS**. The source deliberately restores Stage 1 to the prior count-only
symmetry call. This rejects this exact rank tie-breaker as a 264-trip
certificate path and does not authorize a MIP comparison or formal run.

### Exact identical-vehicle trip-count ordering: implemented; timing pending

Phase 3 Stage 1 and integrated Phase 4 now add an exact label-symmetry cut for
vehicle clones. Within a group whose complete `ProblemVehicle` signature and
assignment and transition-arc domains match, adjacent identifiers satisfy
non-increasing total assigned-trip count. The transition check prevents a
baseline-preserved arc in a successor-pruned diagnostic from being mistaken
for exact symmetry. Every original feasible solution has an identifier
permutation satisfying this order, so the cut preserves at least one member
of each exact symmetry orbit and does not alter the optimal objective value.

The initially considered earliest-fragment prefix formulation was rejected
before commit because it would add roughly 15,840 continuous states and tens
of thousands of rows in the all-identical 60-vehicle/264-trip upper-bound
fixture. The retained
formulation adds zero variables and 58 adjacent-pair rows for 35 identical
BEVs plus 25 identical ICE buses in the structural upper-bound fixture. The
historical high-PV artifact itself records only one exact 25-ICE group; its 35
BEVs have distinct initial SOC and are correctly excluded. The current data
would therefore add 24 rows. If assignment or transition domains differ, the
group is reported as skipped and no activation or count ordering is imposed.
Warm-start vehicle labels are sorted by used state and assigned-trip count so
the cuts do not intentionally invalidate the incumbent seed.

Small exact Gurobi regressions confirm objective invariance and retention of a
canonical label representative. The full-scope structural test confirms the
zero-variable/58-row bound. No matched 264-trip runtime comparison has yet
been executed, so this is not evidence of a speedup and does not close the
high-PV 1% certificate. A fresh frozen-commit diagnostic followed by the
controlled formal pair remains required. Research release is **BLOCKED**.

### Exact fragment-cut separation: diagnostic complete; formal evidence pending

The constraint-type audit found that 1,243,440 of the recorded 1,598,973
rows were explicit pairwise depot-reset checks over vehicle, fragment-end and
fragment-start combinations. The current implementation replaces only those
materialized rows with exact lazy separation at every integer incumbent. It
uses the same canonical transition diagnostic and adds the same
`end + start <= 1` inequality for every violated pair. Complete successor
arcs, physical constraints, objective terms and acceptance gates are
unchanged.

The callback fails closed: an exception terminates and invalidates the solve.
Metadata records the formulation mode, unique cuts, repeated submissions and
callback error. A real Gurobi regression also guards against suppressing
repeated lazy-row submissions; Gurobi can present the same invalid incumbent
more than once.

The clean SHA `885bacb` fresh-Prepare high-PV diagnostic completed through the
frontend/BFF path with `research_run=false`, a 600-second Phase 4 limit and no
Rolling chain. It retained 780,112 variables and reduced fixed-recourse rows
from 1,598,973 to 355,533, exactly the 1,243,440 explicit fragment-pair rows.
At 601.237 seconds it had the same 650,234.729 JPY incumbent, 640,000 JPY
certified bound and 1.574005% gap as the historical 3,600.801-second run. The
callback was invoked once; the accepted incumbent used one fragment per used
vehicle, so no lazy row was required.

This result closes the row-materialization diagnosis but does not certify a
wall-clock speedup. The two runs use different time limits and formal scopes,
several canonical input fingerprints differ, and neither side has repeated
matched executions. The machine-readable comparison therefore records
`runtime_claim.status=NOT_CERTIFIED` and remains diagnostic-only at
`output/diagnostic_lazy_fragment_20260814_885bacb/performance_comparison.json`.

The diagnostic also exposed a reporting defect: its canonical plan metadata
contains the correct separator audit, while the contemporaneous
`solver_settings.json` has null/empty separator fields. The current code now
copies these fields through direct MILP and top-level engine metadata, with
regression coverage; the historical artifact is not rewritten. A new frozen
commit run is required to prove the corrected public artifact contract.

This closes a code-level model-size defect, not the full-run optimality
blocker. The next mathematical target is a stronger valid high-PV lower bound
or a certified path/column decomposition. A fresh controlled formal pair and
1% certificate remain required, so research release is **BLOCKED**.

### Phase-3 IIS branch guidance: implemented; runtime evidence pending

The `885bacb` high-PV diagnostic confirms that Phase 3 evaluated the all-BEV
candidate before mixed compositions. Fixed-assignment Stage 2 proved `32/0`,
`31/1`, `30/2`, `29/3`, and `28/4` candidates infeasible; `27/5` was the first
feasible seed. Integrated Phase 4 nevertheless found a feasible `31/1` plan,
so no composition-level infeasibility claim is permitted.

The all-BEV IIS was vehicle-local but included formerly unnamed piecewise
charge constraints. Current code gives those rows stable names and classifies
vehicle-local SOC/charging bounds. MIT review then rejected the draft hard-cut
transfer: Phase 3 Stage 2 and Phase 4 are different mathematical formulations,
so Stage-2 infeasibility alone cannot remove a Phase-4 assignment. The final
implementation uses only non-directional Gurobi branch priorities for the
implicated assignment binaries. It sets no preferred value, constraint, or
objective bias. Time limits, missing IIS data, or heuristic shortages never
generate guidance.

The public artifacts expose pattern count, hashes, source candidate hashes,
promoted variable count, branch priority and semantics in
`solver_settings.json` and `phase4_iis_assignment_guidance_audit.json`. A
real-Gurobi counterexample proves that the formerly disproved Stage-2 pattern
remains feasible in Phase 4 guidance because no hard cut is added. This is
code-level evidence only: no current frozen-commit 264-trip run has measured
its effect. A matched fresh diagnostic and then the controlled formal pair are
still required. The high-PV 1% optimality and research release remain
**BLOCKED**.

## 2026-08-14 vehicle-day-cost sensitivity: execution pending after gate repair

The declared 0 and 20,000 JPY/used-bus-day cases both use
`scalar_total_cost_v1`, holding the physical/tariff/PV/BESS controls fixed.
This is the correct experiment for the monetary coefficient: the thesis
lexicographic preset minimizes vehicle days before cost and would mask the
coefficient's dispatch effect.

The runner now rejects a case unless the cost component is enabled, the
integrated primary objective is canonical actual cost, the unit reaches model
and executed accounting, the saved semantics are a classified
`fixed_vehicle_day_cost`, one-day used buses equal used vehicle-days, and the
charged amount equals used vehicle-days times unit within `1e-6 JPY`. These
checks close the prior evidence gap where a saved coefficient alone could be
mistaken for an active and correctly accounted objective term.

No current-HEAD numerical sensitivity result exists yet. Fresh Prepare and
both frontend/BFF jobs must run from one clean frozen commit. Until their
physical, Rolling, accounting, provenance, and declared gap gates pass, the
effect of the 20,000 JPY coefficient remains **BLOCKED**.

## 2026-08-14 energy-demand tranche: evidence complete; 1% gap still blocks

Frozen SHA `735527da7f117f5af894263dcdf4fe55e8226328` completed all five
0.8--1.2 trip-energy demand cases with fresh prepared inputs, 264/264 served
trips, physical validation, and accepted 24-step Rolling accounting. The
source execution is
`output/thesis_sensitivity_energy_low_pv_20260814_735527d`.

The original manifest remains `BLOCKED`. Its initial common-control fingerprint
incorrectly treated the energy-derived departure-SOC requirement as immutable
trip structure. All genuinely non-varied dimensions match, and the full
prepared trip arrays independently share SHA-256
`1c382c9c3dc6eec41173c1c451d790a66ae41ffef5c4bd10d2caabc7826511f9`.
The provenance implementation now separates schedule structure from demand
and fails closed unless the prepared source is fully hash-verified. Clean
re-audit SHA `2a4da8b6ad48c8ffc297b784c616dabd83ba1281` now closes that
provenance defect: all five cases share control fingerprint
`d19d1c70780ced02def96f2edfde8a2ccdc7fbd9da15b9bd7329933af3c43252`.

This repair does not discharge the optimality blocker. The five source solves
are time-limited and miss the declared 1% target at 8.246%, 6.446%, 6.550%,
4.952%, and 5.020%. All other case checks pass, so the rows are physically
valid, Rolling/accounting-eligible feasible incumbents, not certified optima.

The re-audit now treats minimum SOC as an executed-chain quantity. It verifies
the prepared vehicle capacities, 00:00/24:00 cyclic boundary and every
01:00--23:00 Rolling state handoff against the final artifact hashes. This
closes the reporting ambiguity between day-ahead SOC and executed SOC, but it
does not change any source solution or its gap status.

The energy-sensitivity reporting builder is also fail-closed. It may publish
the five feasible incumbents for progress reporting only when the complete
control, prepared-input, physical, accounting, Rolling and SOC evidence passes;
the only tolerated failed case gate is `mip_gap_target_met`. Its observed
0.8--0.9 and 1.0--1.1 dispatch steps must remain labeled as gap-limited
incumbent changes until certified solves establish the transition boundaries.

The final progress-report bundle is
`output/thesis_sensitivity_energy_low_pv_20260814_735527d/reaudit/8e98b34aa295a88f-2a4da8b/reporting/b5736dec1edfd1dd-d26a0f23d152`.
It includes one signed JSON snapshot, CSV, Markdown, a five-sheet Excel
workbook, four PNG/SVG figure pairs, workbook QA evidence and previews. The
reporting-manifest payload SHA-256 is
`d7633210d18dc35519522e32cae3975adc0cfd2098c13212f315a3c36c37383d`.
This bundle is eligible for progress presentation only; both
`research_conclusion_eligible` and `transition_boundary_certified` are false.

## 2026-08-14 corrected time-step tranche: provenance fixed; 1% gap still blocks

Frozen SHA `88f76a9af79a8d46c1502a51ed03778ab99f20e9` completed fresh
60/30/15-minute internal-discretization jobs through the frontend/BFF path.
All three cases preserve the same non-varied-control fingerprint, record
submitted/requested/effective Rolling as 60/60/60 minutes, re-hash every
final artifact, and retain unchanged clean Git provenance. The earlier
request/effective ambiguity is therefore closed.

Every case serves 264/264 trips, uses 32 buses, assigns 91 BEV and 173 ICE
trips, passes independent physical validation, and produces an accepted
24-step fixed-assignment Rolling accounting chain. Executed cost changes from
58,318.002033 JPY at 60 minutes to 58,235.852189 at 30 minutes and
58,221.042678 at 15 minutes. Grid import falls from 130.948752 to 128.255315
and 127.769757 kWh; the dispatch composition does not change.

This still does not discharge the time-step blocker. All day-ahead solves
reach about 3,601 seconds and miss the declared 1% target: certified gaps are
6.550063% (60), 6.418238% (30), and 6.352187% (15). The manifest remains
`BLOCKED`; these are physically valid, accounting-eligible feasible
incumbents, not certified discretization optima.

The reporting builder fail-closes on manifest tampering, a changed common
control, a non-gap validation failure, Rolling mismatch, or Git/artifact
provenance failure. It labels the current evidence
`DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED`. A future run must meet the
predeclared gap requirement before the thesis may claim time-step convergence.

Diagnostic evidence bundle:
`output/thesis_sensitivity_time_low_pv_20260814_corrected_88f76a9/reporting/5d58aca1284c4ddd-8c3307182c6b`.
Reporting-manifest SHA-256:
`58c9cebf6d771c7d5a809044768a8ce8306075e8c4c102e017aed6f6016781ba`.

## 2026-08-13 low-PV M0--M3 gate discharged; broader release blockers remain

- Fresh normal frontend/BFF Phase 1 and Phase 4 jobs completed from clean
  frozen SHA `f5c8ba7395665493a718423d2232bb28a15e07bd`. They share prepared
  input `prepared-8331f7eaa9fcb7eb-f1e18f252e336f1f-746edf1f`, exact source
  SHA-256 `d9e2d63ce2c044d4ee6c2324677e59c9f64a24f792b9b9ee5acb2a3a8b4018c6`
  and canonical ablation input SHA-256
  `9693fb2c52952480160b0a455a154bca9b02edb01f28f7ab3695b34ae0fc29c3`.
  The stored scope hash and independent re-hash also match the ID.
- Phase 4 run `run_20260813_2317` passes 264/264 trip coverage, 24/24 Rolling,
  physical validation, canonical accounting and the declared 1% gap through
  its 0.547009% certificate. Phase 1 run `run_20260813_2337` is the explicit
  fixed-dispatch charging optimization. The merge validates both final
  artifact snapshots and returns `READY_FOR_DAY_AHEAD_METHOD_COMPARISON` with
  zero failed checks.
- Day-ahead M0/M1 use 13 BEV and 19 ICE buses for 44/220 trips; M2/M3 use
  21/11 buses for 91/173 trips. M0->M1 reduces cost by 15,725.086173 JPY and
  CO2 by 257.788298 kg without changing dispatch. M2->M3 reduces cost by
  28,294.171245 JPY and CO2 by 463.838873 kg. M1->M3 adds eight BEVs and 47
  BEV trips while reducing cost by 9,200.150294 JPY and CO2 by 158.127709 kg.
- The first rejected v7 comparison remains historical diagnostic evidence; it
  was not relabeled. The immutable v9 rerun is the sole adopted low-PV M0--M3
  source. This discharges item 6 of the 2026-08-12 list for this low-PV,
  same-input, day-ahead scope only.
- Formal thesis release is still `BLOCKED`: the controlled high-PV result has
  a 1.574005% certified gap against the declared 1%, and the 15/30/60-minute
  plus other predeclared sensitivity experiments remain incomplete. This
  comparison is not a Rolling-method comparison and is not a global-optimum
  certificate for the full two-case study.

## 2026-08-13 latest verdict: r7 verifies feedback evidence; sunny gap is unchanged

Frozen SHA `f46f1e821e6773f7f647dd130b28427bbb3df10d` completed fresh
Prepare, both frontend/BFF Phase-4 jobs, 24/24 Rolling, physical and canonical
accounting validation, pair finalization, seven figures, six tables and the
progress ZIP. Runtime PID 60504 and startup/current/frozen Git SHAs match and
remain clean for both cases.

The controlled result remains high PV 31/1 BEV/ICE buses and 248/16 trips at
650,234.729396 JPY, versus low PV 21/11 and 91/173 at 698,318.002033 JPY.
Both serve all 264 trips and differ in 157 powertrain assignments. The pair is
accepted for controlled PV sensitivity. Formal submission remains `BLOCKED`
solely because high PV has a certified 1.574005% gap against the declared 1%;
low PV is certified at 0.547009%.

The new route-band audit closes the evidence ambiguity but does not improve
the result. Failed sunny `渋23` and low-PV `渋23` attempts time out in reduced
Stage 1 without an incumbent, so Stage 2 is explicitly `not_run`; no IIS, cut
or retry is claimed. Low-PV `渋22` reaches Stage-2 `optimal` and produces a
fully validated 26/6 candidate at 704,330.168664 JPY, 6,012.166631 JPY more
expensive than the selected 21/11 composition. This verifies search diversity
and rational rejection, not all-BEV infeasibility.

Evidence:
`output/formal_pair_20260813_route_band_feedback_budget_attested_v7_flat30_pv1000_bess6000_phase4_f46f1e8_gap01_r7`.
ZIP SHA-256:
`EC05E786943500E6E032BE86841FEBC9E935E9FF790BC337FC8A4F318A765064`.

## 2026-08-13 latest verdict: r6 controlled pair accepted; sunny gap blocks formal release

Frozen SHA `ccfbbbb321cfe4a9150f0e135172e52ee9751a6b` completed the normal
frontend/BFF path with fresh Prepare and matching clean runtime/current/frozen
Git attestation. Both 264-trip cases passed 24/24 Rolling, physical validation,
terminal SOC, canonical accounting and controlled-pair finalization.

High PV uses 31 BEVs / 1 ICE for 248/16 trips at 650,234.729396 JPY. Low PV
uses 21/11 for 91/173 trips at 698,318.002033 JPY. The only controlled input
difference is the PV curve (6,056.25 versus 996.20 kWh), so the pair is
accepted for PV sensitivity. Formal submission remains `BLOCKED` solely
because the sunny certified gap is 1.574005% against the predeclared 1%; low
PV meets it at 0.547009%. Neither result is mislabeled as a global optimum.

The low-PV neighborhood found a physically and Stage-2-feasible 26/6
composition at 704,330.168664 JPY, 6,012.166631 JPY above the selected 21/11
solution. This is direct evidence that composition search is not frozen and
that more BEVs are not automatically cheaper under low PV and 30 JPY/kWh.
Sunny did not find a 32-BEV incumbent, but the run contains no certificate
that such a composition is infeasible.

Evidence:
`output/formal_pair_20260813_route_band_feedback_runtime_attested_v6_flat30_pv1000_bess6000_phase4_ccfbbbb_gap01_r6`.
ZIP SHA-256:
`5B4A7014EBD7162D0B06F18AB87BECED878F057439306827692475921239E5F0`.

## 2026-08-13 verified in r7: complete feedback budget and audit

r6 also showed that `stage2_feedback_max_iterations=1` did not by itself fund
or prove a complete retry. The initial Stage 1 and Stage 2 shared the deadline,
and the attempt omitted Stage-2 status and IIS/no-good history. The current
code divides the unchanged fair group deadline into equal initial/retry
passes, reserves five percent for construction/IIS work, and records the
actual feedback status and history. Only a proven `INFEASIBLE` Stage 2 can add
the exact-assignment no-good cut; `TIME_LIMIT` is not an infeasibility proof.

This is an upper-bound candidate-generation and evidence change, not a change
to the final feasible region or lower bound. The clean r7 above verifies the
new telemetry. The formal blocker stays the sunny 1% certified-gap gate until
a qualifying run satisfies it.

## 2026-08-13 P0 provenance correction: r5 used a stale BFF runtime

The attempted r5 rerun is not current-code evidence. Although its wrapper and
request-time provenance recorded clean HEAD `e321a3a`, inspection of the
solver-native seed audit showed the old v4 field set: there was no
`route_band_repartition_feedback_max_iterations`, no reduced shared-budget
telemetry, and the verified-start cost-cap audit retained the old ineligible
label. Its numerical result was also exactly v4. The BFF listening on port
8000 had loaded an older solver before the repository advanced.

This is a provenance failure, not a new optimization result. The r5 directory
remains diagnostic and cannot supersede the accepted v4 pair or support a
claim about the IIS-feedback implementation.

Current code now captures the BFF's clean Git identity at process startup and
requires an exact match with the request-time clean checkout at three formal
boundaries: before job creation, before solver construction, and after solve.
The automated pair runner independently requires the runtime attestation and
exact frozen-SHA equality before Prepare. A missing field, old process, dirty
startup or SHA/root mismatch is a hard failure with no solver job.

The clean r6 above verifies matching runtime/current/frozen SHAs and the
canonical cost-cap telemetry. Its feedback audit exposed the separate budget
and evidence defect now awaiting a fresh rerun. Runtime provenance alone does
not discharge the sunny optimality blocker.

## 2026-08-13 historical checkpoint: route-band IIS feedback before r6

At this checkpoint, v4 was the latest accepted controlled-PV evidence. Its
audit exposed that the reduced route-band solve had an unused feedback path:
the general Stage-2 IIS/no-good mechanism existed, but the internal candidate
problem explicitly disabled it and spent most of the 90-second allowance on a
single Stage 1.

That patch gave the first reduced Stage 1 at most half of each route-band
group's fair shared allowance and permits one IIS-backed exact-assignment
no-good retry inside the unchanged deadline. This may find a different
charging-feasible all-BEV partition; it does not prove that one exists and does
not change the final integrated feasible region. A candidate remains
inadmissible until it passes local Stage 2, exact trip/count merge checks, the
full original Stage 2, independent physical validation, and canonical
accounting.

The same patch corrected the lexicographic verified-start audit: after minimum
vehicle-days are certified, the recorded bound now references
`dispatch_fixed_recourse_canonical_cost_jpy` and reports the cost-cap row that
was actually installed. This is evidence/provenance repair, not a stronger
lower bound. The runtime-attested r6 above supersedes this checkpoint and
exposes the narrower feedback-budget/audit defect addressed by current code.

## 2026-08-13 historical v3/v4 verdict: controlled pair accepted

The latest fresh pair at frozen SHA
`583dced3306f3e27b1de248605b70c51fc72e570` completed the ordinary frontend/BFF
path, fresh Prepare, both 264-trip Phase-4 solves, 24/24 Rolling, physical and
executed-day accounting validation, pair finalization, progress figures/tables
and ZIP export. Non-PV controls match and PV differs by 5,060.05 kWh. The pair
is accepted for controlled PV sensitivity, with 157 changed trip assignments.

High PV uses 31 BEVs / 1 ICE for 248/16 trips and costs 650,298.979262 JPY;
low PV uses 21/11 for 91/173 trips and costs 698,318.002033 JPY. Low PV meets
the declared gap using the certified 0.547009% bound. High PV stops at
1.583730%, so the only formal release failure is
`baseline_requested_mip_gap_certified`. These are feasible, physically valid
solutions; the high-PV result is not a global-optimum claim.

The v3 route-band experiment is negative evidence. It generated one high-PV
and two low-PV reduced all-BEV candidates, but all failed the original full
fixed-assignment Stage 2. It also ran before the proven fixed-duty neighborhood
and consumed 60--102 seconds from the same 120-second budget. The high-PV
incumbent therefore regressed by 64.249866 JPY relative to `b06c451`, and its
certified gap widened by 0.009725 percentage point.

Frozen SHA `ad0d4f2c4c1acb10233516309c11a9a4c00b362d` verifies the v4 behavior.
It preserves the full 120-second fixed-duty replacement/matching/suffix/swap/
identity search first. Route-band repartition starts afterwards
from the cheapest independently validated incumbent and has a separate,
audited 90-second budget. Its reduced problem now runs both Stage 1 and Stage 2;
local SOC/charging infeasibility is rejected before full-system evaluation.
Locally feasible candidates must still preserve the exact trip set and pass
the unchanged full-problem fixed-assignment Stage 2, independent physical
validation and canonical accounting. No weather-specific objective bias or
BEV lower bound is introduced into the final integrated solve.

The fresh frontend/BFF pair restores high PV to 650,234.729396 JPY, 31/1 buses
and 248/16 trips. Its fixed-duty search evaluated 109 candidates in 120.172
seconds and selected the prior best powertrain-swap incumbent. The subsequent
reduced route-band Stage 2 was infeasible and correctly stopped before a full
candidate evaluation. Low PV remains 698,318.002033 JPY, 21/11 buses and
91/173 trips; two route-band groups were fairly budgeted and both failed local
Stage 2. The controlled comparison and progress bundle pass, but high PV still
has a 1.574005% certified gap. Formal release therefore remains blocked solely
by `baseline_requested_mip_gap_certified`.

Evidence:
`output/formal_pair_20260813_route_band_v4_flat30_pv1000_bess6000_phase4_ad0d4f2_gap01_r4`.

The first clean full pair using sequential scalar lexicographic certification
completed at frozen SHA `7cb1192cf6278e8854add16b58f04639a6656336`.
Both cases served 264/264 trips, accepted all 24 Rolling steps, passed physical
and canonical accounting checks, and preserved identical non-PV controls.
The pair manifest sets
`accepted_for_controlled_pv_sensitivity_comparison=true`.

| Metric | High PV | Low PV |
|---|---:|---:|
| Used BEV / ICE | 31 / 1 | 21 / 11 |
| BEV / ICE trips | 248 / 16 | 91 / 173 |
| PV generation | 6,056.25 kWh | 996.20 kWh |
| Grid import | 156.039059 kWh | 130.948752 kWh |
| Rolling-consistent ICE fuel | 35.884956 L | 356.022849 L |
| Executed total cost | 650,234.729396 JPY | 698,318.002033 JPY |
| Executed operational CO2 | 170.814257 kg | 986.112082 kg |
| Certified cost gap | 1.574005% | 0.547009% |
| Gurobi raw cost gap | 1.574005% | 8.351210% |

The low-PV certificate uses the maximum of Gurobi's bound and a separately
validated integer-valid analytical lower bound; it must not be described as a
Gurobi `OPTIMAL` result. The high-PV result exceeded the declared 1% gap.
Consequently `formal_research_submission_ready=false`, with the only pair
release failure `baseline_requested_mip_gap_certified`.

The artifact is:
`output/formal_pair_20260813_sequential_lexgap_flat30_pv1000_bess6000_phase4_7cb1192_gap01`.
The high/low assignment difference is 157 BEV trips and ten used BEVs; the
executed cost difference is 48,083.272637 JPY. This is controlled PV-supply
sensitivity evidence, not proof of the high-PV global cost optimum.

Post-run audit found that the frozen output's general-purpose KPI files still
contained day-ahead CO2/fuel values while the progress report correctly used
Rolling CO2. Current code now persists `ice_fuel_consumed_l` in executed-day
accounting, explicitly reconciles the sequential canonical-cost level to that
accounting total, and fails before solve when Prepare materializes a different
service ID. The small oracle also reads the materialized `WEEKDAY` service ID;
both preserved cases pass the corrected bounded oracle. Because these are
post-run code changes, they require a new clean commit and fresh pair and do
not rewrite the frozen artifacts.

The sunny cost solve explored only its root node for the full 3,600-second
budget. A second clean controlled pair at
`698ef44622a50a1d5a06368aea6d7fc6914b1457` tested an incumbent-focused
profile (`MIPFocus=1`, `Heuristics=0.25`, `Presolve=2`). It reproduced exactly
the same high-PV incumbent and 1.574005% gap and made the low-PV solve slower.
That experiment did not close the blocker, so current code restores the prior
bound-certification profile instead of presenting the search-control change as
an improvement.

The useful diagnosis came from Stage-2 IIS evidence. A generated 32-BEV
candidate copied one 07:26--23:24, 16-trip ICE path unchanged to an unused
BEV. Under the configured return-to-initial terminal policy, that path had
160.557620 kWh usable initial energy and only 90.642380 kWh time-ordered
deliverable charging against 362.486315 kWh required energy, leaving a
111.286315 kWh terminal shortage. This is an infeasibility certificate for
that fixed assignment only; it is not a certificate that every 32-BEV
assignment is infeasible.

The frozen `b06c451` code added an IIS-motivated duty-suffix exchange neighborhood.
It preserves exact trip coverage, validates both new cross-arcs with the same
turnaround/deadhead engine as the dispatch graph, respects fixed route bands,
clears stale energy/SOC/accounting state, and requires exact fixed-assignment
Stage-2 recourse plus independent validation before a reconstructed candidate
can become the integrated MIP start. Candidate generation is weather-neutral
and no BEV count is forced. Current code extends that search with the
route-band re-partitioning described above. Until a fresh clean controlled
pair exercises the new audit schema and the high-PV case meets the declared
1% cost gap, formal release remains `BLOCKED`.

## 2026-08-13 sequential cost-gap path implemented; fresh formal evidence pending

The remaining full-pair optimality blocker was traced to evidence semantics,
not to physical feasibility. `research_lexicographic_v1` previously used one
Gurobi multi-objective solve. At a time limit, that path did not expose a
scalar lower bound and MIP gap for the canonical-cost level, so the formal gate
correctly rejected both `e4ddd3f` cases.

Current code now performs sequential scalar certification under one shared
Phase 4 time budget:

1. certify minimum used vehicle-days exactly;
2. fix that integer value;
3. minimize canonical operating cost and export its `ObjBound`/`MIPGap`;
4. run deadhead and charge-session tie-breaks only after exact cost.

When a complete integrated recourse seed uses the independent strict
path-cover lower-bound count, step 1 is certified without another solve. If
the primary count is not exact, no cost gap is exported. The pair gate now
requires this primary certificate and explicit cost-stage objective/bound
telemetry, preventing a vehicle-count gap or tie-break gap from being reported
as a cost certificate.

Bounded tests pass, but this implementation postdates the authoritative
`e4ddd3f` pair. Formal release therefore remains `BLOCKED` until a fresh clean
current-HEAD pair completes Prepare, both 264-trip Phase 4 solves, 24/24
Rolling, physical/accounting validation and pair finalization. Even then, each
case must still meet the requested 1% canonical-cost gap; the code change does
not guarantee that computational result. Full-scale M0--M3 and the declared
sensitivity matrix also remain separate evidence blockers.

## 2026-08-13 post-fix pair accepted for PV sensitivity; formal gap still blocks release

The required clean post-fix rerun completed from frozen SHA
`e4ddd3f146975c34ac61e957385cd5a26daaca66` through fresh Prepare, Phase 4,
24/24 Rolling, independent physical validation, executed-day accounting,
bounded exact-oracle audit and pair finalization. Git remained clean and
unchanged. The two cases held all non-PV controls fixed and share comparison
control hash
`1ae12973a92ad50c1257cd67c351f485f4451b6d164298a72fc72204fd12df11`;
their PV-profile and final-assignment hashes differ.

| Metric | High PV | Low PV |
|---|---:|---:|
| Used BEV / ICE | 31 / 1 | 21 / 11 |
| BEV / ICE trips | 248 / 16 | 91 / 173 |
| PV generation | 6,056.25 kWh | 996.20 kWh |
| Grid import | 156.039059 kWh | 130.948752 kWh |
| Day-ahead KPI fuel (not Rolling canonical) | 36.307510 L | 357.881339 L |
| Executed total cost | 650,234.729396 JPY | 698,318.002033 JPY |
| Executed CO2 | 170.814257 kg | 986.112082 kg |

The pair passes physical, SOC, charger, Rolling, accounting, artifact,
tariff, provenance, composition-search, objective-semantics and controlled-PV
comparison gates. `objective_preset=research_lexicographic_v1` is now exported
and matched, and both bounded 10-trip integrated oracles are exact-eligible.
Accordingly, `pair/pair_manifest.json` sets
`accepted_for_controlled_pv_sensitivity_comparison=true`.

Formal research submission remains `BLOCKED` because neither full 264-trip
integrated run established the predeclared 1% MIP gap before the time limit.
The only pair release failures are
`baseline_requested_mip_gap_certified` and
`counterfactual_requested_mip_gap_certified`. The reported schedules are valid
feasible incumbents and demonstrate a scoped PV-supply response, but they are
not certified global or lexicographic optima.

Authoritative evidence:
`output/formal_pair_20260813_thesis_model_flat30_pv1000_bess6000_phase4_e4ddd3f_gap01_r2`
and its ZIP (SHA-256
`504C282BDC51710AB821CCBCA2BDEA66FFBCFAC5B3D0AA5A4C42A2A63633E932`).
The progress bundle contains seven PNG/SVG figures, six source tables and a
hashed evidence index. Full-scale M0--M3 ablation and the predeclared
sensitivity matrix are still separate unexecuted evidence requirements.

A post-run metadata review also found that the frozen run's
`integrated_primary_objective_kind` label remained `canonical_actual_cost`
despite the actual `research_lexicographic_v1` hierarchy. Current code now
exports `minimum_used_vehicle_days_lexicographic`. This is a provenance-label
correction only; it does not change or relabel the frozen `e4ddd3f` evidence.

## 2026-08-13 revised-model pair completed; objective-contract rerun required

Frozen clean SHA `332b6af48260c89bc14a2ad2be67a0fd1d2f168e` completed
fresh Prepare, Phase 4, 24/24 Rolling, physical validation, executed-day
accounting and progress-report generation for both controlled PV cases. The
non-PV control hash matched and the PV hashes differed. Both cases served all
264 trips with zero unserved trips, no fallback and no post-solve repair.

Observed feasible incumbents:

| Metric | High PV | Low PV |
|---|---:|---:|
| Used BEV / ICE | 31 / 1 | 21 / 11 |
| BEV / ICE trips | 248 / 16 | 91 / 173 |
| PV generation | 6,056.25 kWh | 996.20 kWh |
| Grid import | 156.039059 kWh | 130.948752 kWh |
| Executed total cost | 650,234.729396 JPY | 698,318.002033 JPY |
| Executed CO2 | 170.814257 kg | 986.112082 kg |

This demonstrates a strong PV response in the two feasible incumbents. It
does not establish that either composition is globally or lexicographically
optimal. Both integrated solves ended at `time_limit`, and neither established
the predeclared 1% gap.

The run also exposed two P1 contract defects in the frozen code:

1. `assignment_economic_audit.json` exported a null `objective_preset` even
   though the canonical problem recorded `research_lexicographic_v1`. This
   caused false objective-preset mismatch and false scalar-accounting failures.
2. The integrated adapter called `setObjective` after `setObjectiveN`,
   overwriting objective 0 of the declared research hierarchy.

Both defects are fixed and covered by focused tests. The bounded 10-trip,
15-minute post-fix diagnostic is Gurobi `OPTIMAL`, reports raw primary
objective 2.0 for two vehicle-days and secondary accounting cost 40,000 JPY,
passes physical/accounting validation, and is exact-oracle eligible. That
small result is formulation evidence only. Because the objective implementation
changed after the 264-trip run, the `332b6af` pair remains `DIAGNOSTIC` and a
fresh clean-commit pair is mandatory. Even after rerun, the requested full-run
gap remains an independent release gate.

## 2026-08-13 trip-specific independent validation fixed, fresh pair pending

The clean-SHA attempt at `624b42dcc5c40a07598000218d737a96569a5095`
confirmed that the Rolling session-boundary fix works through the normal
frontend/BFF path: the sunny case completed 24/24 feasible hourly solves and
the rolling-chain acceptance checks passed. Day-ahead served all 264 trips
with a 31-BEV / 1-ICE composition and a 248/16 trip split. The raw integrated
status remained `time_limit` and the requested 1% MIP gap was not met.

Finalization correctly failed closed, but the reported SOC violations were a
validator semantic defect rather than physical violations in the canonical
model. The independent event validator still recomputed each trip from the
legacy vehicle-average distance rate. The revised model materializes
trip-specific `literature_proxy_v1` BEV energy and ICE fuel quantities in the
canonical problem, so the validator and solver were evaluating different
energy demand for the same trip.

The validator now consumes the canonical trip-specific demand while remaining
independent of solver SOC output. BEV and ICE regression tests pass. A
diagnostic replay of the preserved sunny assignment and executed charging
schedule produces zero violations and an accepted 588-event physical ledger.
This replay demonstrates the bug fix only. The original sunny run remains
`BLOCKED`; the automatically started low-PV run was stopped because the shared
defect made it ineligible and the source fix made the worktree dirty. A fresh
clean-SHA pair, including the declared gap gate, 24/24 Rolling, physical
validation, accounting reconciliation, and pair hashes, is still required.

## 2026-08-12 revised-model formal attempt: Rolling boundary bug fixed, rerun pending

Frozen clean SHA `6f645020f8473c42c15dce8d654bcc00d052615a` was exercised
through the normal frontend/BFF path with fresh Prepare, 30 JPY/kWh energy,
zero demand charge, 1,000 kW PV and a 6,000 kWh / 900 kW BESS. The sunny
Phase-4 day-ahead solve served all 264 trips and produced a 31-BEV / 1-ICE,
248/16-trip incumbent. It reached its declared time limit without the requested
gap, so it was already ineligible for an optimality claim.

Hourly Rolling then failed at 06:00. This was not a hidden SOC repair or a
physical relaxation: the run stopped and retained its IIS. The failure was a
software defect in the piecewise charging-session boundary. A session that was
active in the last executed slot was forgotten when the next remaining-day
horizon began. The first new slot therefore paid setup time again, reducing
the affected slot from 82.5 kW to 75 kW and making the fixed assignment
infeasible.

The implementation now passes the active charge-session vehicle IDs with the
measured SOC/BESS/demand state and suppresses setup only when both the last
executed slot and next planned slot have positive charging for that vehicle.
Focused tests pass, and a diagnostic replay of the exact failed
prepared input, assignment and 05:00 state makes the 06:00 Stage-2 solve
optimal and feasible with the expected 82.5 kW charge. The original run remains
`BLOCKED` and diagnostic; the low-PV solve was intentionally stopped after the
common Rolling defect was confirmed. A fresh clean-commit sunny/rain run with
24/24 accepted Rolling, physical validation, accounting, pair hashes and the
declared gap gate is still required.

## 2026-08-12 model revision: fresh formal evidence required

> Historical checkpoint. Item 6 was later discharged for the low-PV
> same-input day-ahead comparison by the clean `f5c8ba7` evidence recorded at
> the top of this document; the other listed items retain their stated scope.

The current worktree changes the canonical feasible region, objective
hierarchy, charging-power constraints, trip energy/fuel inputs, transition
aliases, prepared-input schema, and research fingerprints. Consequently, every
2026-08-11 pair remains valid only as historical evidence for its frozen SHA;
it is not evidence for the revised model. Current-HEAD research release is
`BLOCKED` until all of the following are complete from one clean frozen commit:

1. fresh Prepare for both controlled PV cases;
2. route-band-OFF transition audit with `deadhead_missing = 0`, or an explicit
   non-READY result listing the still-missing matrix entries;
3. 15/30/60-minute, common trip-demand, independent BEV-energy, independent
   ICE-fuel, route-band, and vehicle-day-cost sensitivity;
4. accepted Phase 4 plus 24/24 Rolling, physical validation, canonical
   accounting, and immutable pair verification;
5. a fresh frontend/BFF ablation matrix (the bounded all-ICE and grid-only
   electric exact-model audits are now implemented and tested);
6. execute the now-available explicit M1 fixed-dispatch charging job and a
   fresh M3 job, then pass the same-input M0--M3 comparison gate before
   method-level effect sizes may be claimed.

The implemented PV semantics are
`available_surplus_after_depot_load`; gross PV is not accepted without an
explicit depot-load series. `literature_proxy_v1` is a deterministic proxy,
not a measured trip-energy model, and that limitation must remain in the
thesis. Only bounded unit-test oracles were solved during this code-changing
step; no frontend, full-scale, Rolling, or formal research run was executed.

The sensitivity execution path is now implemented but not yet executed at the
current HEAD. `scripts/run_thesis_sensitivity_matrix.py` compiles the
predeclared matrix into fresh frontend Prepare and Phase 4 requests, then
requires physical, Rolling, gap, artifact-hash, Git, and cross-case control
checks. Two previously silent no-op cases were fixed: `pv_scale` now changes
the canonical PV kWh series while preserving rated kW, and route-band OFF now
also permits intra-depot route swapping so the scope lock does not force it
back ON. Item 3 remains an evidence blocker until the clean-commit matrix (or
an explicitly scoped subset) is actually run; a subset cannot discharge the
full-matrix gate.

The controlled sunny/rain runner now also sends the revised model controls in
its fresh Prepare request and aligns Prepare's Phase/time-limit/gap fields with
the submitted Phase 4 job. Its audit accepts the explicit
`research_lexicographic_v1` hierarchy only when the solver correctly reports
that the hierarchy is not a scalar accounting objective; it does not convert
that result into an unconstrained total-cost optimum. The current-HEAD pair is
still unexecuted, so this closes an execution-path bug, not the evidence gate.
Pair verification applies the same semantic audit and rejects mixed objective
presets rather than requiring false scalar equality from a valid hierarchy.

The independent exact-audit boundary now includes a second, electric oracle.
It completely enumerates assignments and uses a separate SciPy/HiGHS charging
MILP for strict one-depot, one-day, flat-tariff, PV=0, BESS=0,
return-to-initial-SOC cases of at most ten trips. Tests cover the
23.9563 JPY/kWh hand-calculated energy-price crossing, no-charger terminal-SOC
failure, one-port versus two-port charger concurrency, canonical cost and
physical validation, and agreement with the integrated Gurobi result. This is
bounded formulation evidence only; it does not discharge the fresh 264-trip
formal-run, M1/M0--M3, sensitivity, or pair gates above.

The M1 execution and comparison path was implemented at this checkpoint. The Tk solver list
exposes `phase1_charging_only`, Prepare classifies every explicit thesis phase
as `milp_exact`, and the existing canonical Stage-2 solver keeps the baseline
vehicle-trip assignment fixed while optimizing charging, PV, BESS, and grid
flows. `scripts/build_thesis_ablation_comparison.py` merges that explicit M1
run with an explicit Phase 4 run only after matching the prepared artifact,
clean Git SHA, and a canonical fingerprint covering the scenario, objective
weights, trips, vehicles, vehicle types, depots, chargers, tariffs, PV/BESS,
feasible connections, and baseline assignment. Source acceptance, declared
MIP-gap achievement, method physical validity, payload SHA, and identical M0
are also mandatory. The merge rechecks the immutable hash snapshot recorded in
each source `artifact_completeness.json`; edits to the candidates, summary,
solver settings, or run manifest after finalization force `BLOCKED`. The
implementation was tested, but no fresh full-scale M1 or M3 frontend job had
yet been executed at that historical HEAD. The later clean `f5c8ba7` run now
discharges item 6 for the explicit low-PV day-ahead scope only.

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

## 2026-08-12 current implementation boundary

The Phase-1 structural audit is now materially stronger. On the current
264-trip Tsurumaki prepared input, route-band OFF has `deadhead_missing=0`; the
previous 676 count was an incorrect label for insufficient turnaround slack.
The corrected relaxed vehicle lower bounds are 32 with route-band ON and 25
with route-band OFF, compared with 18 from interval overlap alone. A future
paper must therefore state the route-band rule explicitly and report the
ON/OFF sensitivity; it must not call 32 an unconstrained fleet optimum.

Fresh Prepare now also requires an explicit vehicle-by-trip compatibility
contract for formal release. The current input explicitly allows every
selected BEV and ICE on every trip. Any future input that reaches the builder's
implicit all-powertrain fallback, or contains same-powertrain vehicle-specific
restrictions that the current solver would project away, is blocked with
`vehicle_trip_compatibility_contract_incomplete`.

The bounded exact-oracle suite now has two independent scopes. The all-ICE
four-trip oracle matches integrated assignment, vehicle-specific fuel,
canonical fuel cost, and CO2. The complementary grid-only electric oracle
independently enumerates BEV/ICE assignments and solves fixed-assignment
charging with SciPy/HiGHS, including slot SOC, departure readiness, terminal
return-to-initial SOC and charger-port concurrency. It verifies PV=0, BESS=0,
the 23.956344 JPY/kWh tariff break-even, no-charger infeasibility and one-port
shortage. These are bounded formulation checks only; positive PV/BESS and the
full 264-trip network remain outside this oracle scope.
Both oracles now fail closed before Cartesian enumeration exceeds 1,000,000
assignments; the bounded verification path cannot silently expand into a
production-size exhaustive search.

Remaining blocking work for the requested method comparison:

- M0 and M2 now have canonical deterministic charging adapters, and ordinary
  frontend runs emit their day-ahead candidate costs, assignments, source
  flows, and physical validation beside M3 under `thesis_ablation/`;
- the frontend artifact-completeness gate now rejects missing or malformed
  candidates, verifies the artifact payload hash, and prevents Phase 1/2/3
  results from being mislabeled as the integrated M3 method;
- M1 still requires an explicit `phase1_charging_only` run against the same
  prepared input and frozen SHA. The ordinary frontend postprocessor does not
  silently launch this additional optimization;
- therefore the emitted M0/M2/M3 partial artifact is explicitly
  `research_conclusion_eligible=false`, and M0--M3 comparative effect sizes
  remain blocked until fresh controlled four-method evidence exists;
- the all-ICE and grid-only electric exact-oracle fixtures are implemented and
  tested. Current clean SHA `305b5e3a3493b9198c6d0d8ea612b6f383d326c6`
  produced `output/verification/small_electric_oracle/305b5e3/` with status
  `VERIFIED`, all ten checks passing, and certificate payload SHA-256
  `dd797eba2ac3d1d26ea39ab85672bf8d23a349be3b0e362fe04f990df42dd0bf`.
  This discharges the bounded electric-oracle fixture item, but not the missing
  full-network M0--M3 evidence;
- a multi-fragment electric assignment is now rejected with `SOC_FRAGMENT`.
  Stage 2 does not yet persist whether the feasible fragment transition is
  direct or a depot reset, so its transition energy cannot be independently
  replayed without inference. Formal evidence must remain single-fragment per
  electric vehicle until that solver-native choice and continuous SOC ledger
  are implemented; and
- every pre-v7 prepared input and every pre-fix result remains evidence for its
  original code only. Fresh Prepare from a clean frozen commit is mandatory.

## 2026-08-14 600-second Phase 4 diagnostic status

The clean `ecdb0b1` high-PV frontend/BFF diagnostic closed the runaway runtime
defect: precheck, the verified Phase 3 seed, integrated model construction,
fixed-dispatch recourse and branch-and-bound shared one 600-second budget. The
solver wall time was 605.867 seconds and HTTP submit-to-terminal time was
630.538 seconds. It served all 264 trips, applied no fallback, and passed the
independent physical check.

It remains BLOCKED for research use for two independent reasons:

1. the integrated result retained 13 BEVs and 19 ICE buses, assigned 44/220
   trips, and stopped at a 9.542957% certified gap against the declared 1%
   target; and
2. canonical export reconstructed explicit trip fuel with the fleet-average
   distance rate, producing a 285.584764 JPY fuel mismatch and an ERROR data
   flow audit.

The reporting defect is fixed in code by preserving
`fuel_l_by_vehicle_type`/`energy_kwh_by_vehicle_type` through the public
assignment ledger. The candidate generator now tests one complete ICE-duty
retirement first and uses it only when exact Stage 2, physical validation and
canonical cost all pass with a strict improvement. Neither fix makes the
`ecdb0b1` result valid retroactively. Required next evidence is a fresh Prepare
and run from the new clean commit, followed by the rain case and accepted
24/24 Rolling only after the day-ahead gap and accounting gates pass.

Clean commit `4f6a808` supplied that next high-PV diagnostic. Canonical
assignment, fuel, CO2 and total-cost accounting reconciled with zero failed
data-flow checks. The validated seed improved from 13 BEVs/19 ICE buses and
44/220 trips to 14/18 and 60/204 trips, lowering canonical daily cost by
5,146.266645 JPY. The complete all-ICE-duty retirement candidate was
infeasible, and integrated Phase 4 retained the 14/18 seed.

This run is still BLOCKED for research release. It stopped after one search
node at an 8.880180% certified gap against the declared 1% target. It was also
`research_run=false`, day-ahead only, and had no accepted 24/24 Rolling chain
or controlled rain pair. The result is evidence that the cost-selected seed
can change BEV adoption, not evidence that 14/18 is optimal.

The neighborhood then exhausted its 64-evaluation cap by testing equivalent
unused BEV IDs. The current code collapses only exact solver-clone IDs to one
representative fixed-assignment solve and expands a feasible representative
edge for matching. A combined or cumulative candidate is never accepted from
that inference alone: it must pass Stage 2, independent physical validation
and canonical accounting. The final integrated feasible region and objective
are unchanged. A fresh clean-commit diagnostic must verify the effect before
the rain case or a formal pair is run.

The `9db438a` fresh rerun confirmed that the exact-clone optimization did not
apply to this fleet: the 22 unused BEVs have different recorded initial SOCs,
so all equivalence classes were singletons and zero edges were inferred. The
neighborhood evaluated 63 single replacements, but source-major ordering
covered only three of 19 ICE duties. Although those edges admitted a matching
of size three, the direct candidate plus 63 singles exhausted the 64-candidate
limit before the combined assignment could be solved. Assignment and cost
therefore remained 14/18, 60/204 trips and 702,371.885683 JPY; the certified
gap remained 8.880180%.

Current code now rotates target classes across ICE duties in round-robin order
and reserves candidate count plus wall time for exact combined/cumulative
Stage-2 validation. It also repairs the cumulative-prefix duplicate bug that
prevented extensions beyond an already tested single edge. No initial-SOC
difference is ignored and no inferred multi-vehicle candidate is accepted.
The 1% gap, formal-run, Rolling and controlled-pair blockers remain until a
fresh clean-commit run validates this new search order.

Clean commit `fb72281` validated the search order. It covered all 19 ICE duties,
found feasible single-replacement edges for 16, and separately validated the
size-16 matching. Subsequent suffix exchange reached 30 BEVs/2 ICE buses,
232/32 trips and 650,542.999324 JPY. Physical, accounting and artifact gates
passed. This is a real feasible-start improvement, not an inferred assignment.

Research release remains BLOCKED. The integrated solve retained the 30/2 start
but ended at a 1.620646% certified gap against the 1% declaration. It was also
a nonformal day-ahead diagnostic with no Rolling or rain pair. The remaining
two ICE duties cannot yet be called necessary or optimal.

The current implementation also fixes the next measured seed bottleneck:
suffix round one found a strict improvement at its first evaluated candidate
but consumed the rest of the 60-second local-search budget comparing the same
30/2 composition. A bounded eight-evaluation patience now selects a low-cost
round-one result and restarts from it in round two. The final integrated model
is unchanged. Fresh clean evidence is required to determine whether this
reaches 31/1 or 32/0 and whether the 1% gap gate closes.

Clean commit `6755213` reached a separately validated 31-BEV/1-ICE start,
248/16 trips and 648,332.208836 JPY. Suffix round one evaluated nine candidates
and round two evaluated six after the bounded restart. Physical, accounting,
artifact and data-flow gates passed. The remaining ICE duty contains 16 `渋23`
trips and 149.109944 service kilometres; it has not been proved unavoidable.

Research release remains BLOCKED because the integrated certified gap is
1.285176% against the declared 1% threshold. This run was also diagnostic,
nonformal and day-ahead only; it did not execute Rolling or the controlled rain
case. The next bounded search keeps the overall 600-second Phase 4 budget and
the 120-second seed-neighborhood allocation fixed, reallocates that neighborhood
to 75 seconds of fixed-duty search and 45 seconds of route-band repartition,
and permits a third suffix round. Round-two restart patience is reduced to four
evaluations so a final round can be attempted. These are candidate-order and
budget controls only; no BEV lower bound, weather bias, acceptance bypass or
feasible-region change is introduced.

## 2026-08-15 `ac0115e` PV-response diagnostic pair

The funded third suffix round was exercised from clean commit `ac0115e` on the
same frontend/BFF path. High PV reached 31 BEVs/1 ICE bus and 248/16 trips;
low PV with the same non-PV controls reached 14/18 and 60/204 trips. High PV
reduced canonical day-ahead cost from 702,184.658838 to 648,332.208836 JPY and
operational CO2 from 1,053.852313 to 139.625396 kg. Both served all 264 trips,
passed physical checks and reconciled canonical accounting.

This does not clear the release. High PV ended at a 1.285176% certified gap and
low PV at 1.094658%, both above the predeclared 1% threshold. Both were
nonformal day-ahead diagnostics and neither executed 24/24 Rolling. There is
no accepted executed-day accounting pair or formal pair manifest. The only
allowed pair-level statement is that the two physically valid incumbents show
a strong descriptive dispatch response under recorded controls.

The first low-PV attempt is explicitly invalid for comparison because its
saved frontend scenario reset the used-vehicle-day cost to 0 JPY while high PV
used 20,000 JPY. The runner now detects that mismatch before Prepare/solve and
requires an explicit shared override if saved values differ. No artifact from
that invalid attempt may be mixed into the corrected pair.

All evaluated high-PV 32-BEV candidates were infeasible in the bounded suffix
round, and IIS samples implicated charger availability, vehicle location and
SOC transitions. That is a binding-constraint report only. It does not certify
31 BEVs as the fleet-composition optimum or prove that one ICE duty is
unavoidable.

The progress bundle
`output/progress_report_ac0115e_day_ahead_pair_20260815/` is deliberately
`DIAGNOSTIC`, `research_submission_ready=false` and
`teacher_release_status=BLOCKED`. It is suitable as progress evidence with its
limitations visible, but must not be used as the thesis's final formal pair.

## 2026-08-15 Phase-ledger enforcement

The repository now has a single fail-closed Phase 0--7 evidence ledger:
`scripts/audit_thesis_model_phase_gates.py`. It composes, but never replaces,
the source run's own provenance, physical, Rolling, accounting, artifact,
sensitivity, ablation, and release gates.

Current blocker order is:

1. obtain one clean current-SHA formal reference run with 264/264 coverage,
   accepted 24/24 fixed-assignment Rolling, independent physical validity,
   executed-day accounting/final reconciliation, complete artifact hashes,
   and the predeclared MIP-gap target;
2. execute same-SHA accepted route-band ON/OFF and 5/10/15-minute turnaround
   comparisons; structural Prepare audits alone do not complete Phase 1;
3. execute accepted trip-energy, vehicle-day, and 15/30/60-minute families;
4. complete the same-input M0--M3 comparison;
5. add and execute the still-missing electricity-price, diesel-price,
   charger-capacity, initial/terminal-SOC, and PV-by-tariff experiment families,
   together with the existing PV-scale and CO2-cap families; and
6. issue a same-SHA final equation-code-test-figure audit only after all prior
   phases pass.

The `ac0115e` pair and the older energy/time sensitivity runs remain useful
diagnostic evidence for their recorded commits. They do not satisfy this
ordered ledger and are not thesis-release evidence for current `main`.

## 2026-08-15 clean `8066330` formal Phase-0 reference result

The first clean current-SHA formal reference run completed through fresh
Prepare, full unpruned Phase 4, 24/24 fixed-assignment Rolling, independent
physical validation, executed-day accounting, final reconciliation and
artifact hashing. The canonical run is
`output/2026-08-15/run_20260815_0143`; the evidence copy is
`output/formal_phase0_reference_8066330_low_pv/reference_low_pv`.

Every Phase-0 gate passed except the predeclared MIP-gap target. The run served
264/264 trips with 14 BEVs and 18 ICE buses, passed physical validation,
accepted all 24 Rolling steps, reconciled 702,184.658838 JPY of executed-day
accounting, and verified 240/240 required artifacts. Git SHA and dirty state
were unchanged throughout the solve.

The solver terminated at the time limit. End-to-end wall time was 3,804.389
seconds, shared Phase-4 wall time was 3,606.030 seconds, and the independently
certified gap was 1.094658% against the 1% declaration. The Phase-0 audit is
therefore `BLOCKED` only on `declared_mip_gap_target_met`. This result is a
formal physically feasible candidate, not an optimality result; no threshold
or validation rule will be relaxed to promote it.
