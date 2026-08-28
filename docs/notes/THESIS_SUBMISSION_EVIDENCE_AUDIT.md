# Thesis submission evidence audit

**Audit date (Asia/Tokyo):** 2026-08-29

**Latest 264-trip two-weather A/B evidence:** clean frozen tag
`thesis-pure-ice-weather-ab-453b1d3` at execution SHA
`453b1d340311de109645d006b9ec5a0de2788c2e`

**Documentation HEAD immediately after the experiment:** `abf149d3dbc3909e40361ada3c9a8542c1cf1dd5`

## Scope and disposition

This is an evidence audit, not a change to the mathematical model, acceptance
gates, or claimed results. The numerical results belong to frozen execution
SHA `453b1d3`; the later `abf149d` commit records them and must not be presented
as the execution source. The Git-tracked review subset is
[docs/evidence/pure_ice_weather_ab_453b1d3](../evidence/pure_ice_weather_ab_453b1d3/README.md).
It makes the central result, both repeated comparisons, the cross-scenario
comparison, request/Fresh-Prepare manifests, and the full hash inventory
reviewable without rerunning Gurobi. These records do not make the 264-trip
Phase-3 result an integrated global total-cost optimum.

The research release is **BLOCKED** until the repository CI is green and the
thesis claim scope is made consistent with the certified gaps. Independent
review and a later fresh clean-commit formal run remain repository-level
requirements before `LGTM` or `READY`; this evidence-only audit does not
authorize that run. Evidence
accessibility is a release gate and is addressed for the review-sized subset
in this repository; durable publication of the complete 20-run raw bundle is
still open. Failure of aggregation to accelerate the solver is an adoption
result, not a thesis-wide release blocker. The authoritative live status is
[CURRENT_RESEARCH_RELEASE_BLOCKERS.md](CURRENT_RESEARCH_RELEASE_BLOCKERS.md).

The later clean-`f41e2b3` pure-aggregate `incumbent_focus` diagnostic is
recorded at
`output/diagnostics/pure_ice_aggregation_incumbent_focus_f41e2b3_20260824/`.
It verifies provenance, 264/264 physical execution, 24/24 Rolling, accounting,
and no fallback/repair, but its 4.010147% certified Stage-1 gap misses the
predeclared 1% target. It is a rejected single diagnostic, not a substitute
for the A/B evidence or a release-acceptance result.

The subsequent clean-`fabd665` `root_cut_focus` single diagnostic is stored
at
`output/diagnostics/pure_ice_aggregation_root_cut_focus_fabd665_20260824/`.
Its BFF provenance, hashes, physical execution, 24/24 Rolling, accounting,
and no-fallback/no-repair checks pass; its 4.968996% certified Stage-1 gap
does not. It rejects the internal-cut profile as a gap-closing path and cannot
be used as A/B, performance, cost, optimality, or release-acceptance evidence.

The clean-`21e2649` `bound_focus` single diagnostic is stored at
`output/diagnostics/pure_ice_aggregation_bound_focus_21e2649_20260824/`.
It passes provenance, hashes, physical execution, 24/24 Rolling, accounting,
and no-fallback/no-repair checks, but its 4.968996% Stage-1 certificate does
not meet 1%. This completes the existing aggregate solver-profile diagnostics;
it neither establishes an A/B result nor replaces a release-acceptance run.

## Requested work status

This matrix maps the stated thesis-preparation work to immutable artifacts.
Here, **complete** means that the named protocol and its evidence record exist;
it never promotes a bounded, diagnostic, or gap-missing result to a research
release conclusion.

| Requested item | Evidence status | Allowed conclusion |
| --- | --- | --- |
| Reproducibility records | **Complete for cited artifacts.** The A/B, oracle, stress, sensitivity, and root-diagnostic artifacts persist their clean source identity, inputs or prepared-input hashes, controls, and acceptance checks. | These records make the cited runs auditable; a later documentation-only commit does not relabel them as current-HEAD formal evidence. |
| 264-trip pure-ICE aggregation A/B | **Protocol complete for both PV counterfactual scenarios.** Twenty isolated executions form five AB/BA pairs for SUNNY and five for RAIN. | Both are `PASS_STRUCTURAL_ONLY`: verified correctness/recovery and model-size/RSS reductions, but materially worse solver time and no optimality benefit. Aggregation remains default-OFF. |
| 8/12/24/40 integrated oracle | **Protocol complete, bounded scope.** Each listed subset has its stored exact Phase-4 reference. | A formulation/approximation check for the listed small instances only; not a 264-trip integrated-optimality certificate. |
| One-factor response and fixed-plan stress | **Diagnostic execution complete.** The 13-case BEV-energy/PV/BESS/charger matrix, separate three-point electricity and diesel matrices, two-point vehicle-day-cost matrix, and seven fixed-decision stresses have immutable outcomes. | Every full-scale sensitivity is gap-blocked; only the initial-SOC-minus-5pp fixed plan is physically accepted. Neither result supports an economic-response or recourse-robustness claim. |
| M0--M3 common output | **Protocol complete, bounded scope.** The 40-trip audit contains all four methods. | `PASS_SMALL_SCOPE_ONLY`; only the matching-input M2--M3 numerical agreement is an algorithmic oracle check. |
| Submission release | **Not complete.** | CI must be green; cited evidence must remain accessible; claims must report the 9.5213476% SUNNY and 1.6563581% RAIN certified gaps rather than imply a 1%-optimal or integrated-global result. Whether 1% is an absolute submission gate is an advisor decision. |

## Reproducibility snapshot

The current environment observed during this audit is Windows 11
`10.0.26200`, CPython `3.14.6`, Gurobi/gurobipy `13.0.1`, an Intel Core
i7-12700 (20 logical CPUs), and 34,033,328,128 bytes of RAM. The individual
run artifacts persist their own pre/post Git SHA and clean state, prepared
input hash, scenario/prepared-input IDs, runtime environment, solver controls,
threads, seed, time limits, and requested MIP gap. Current machine information
is a verification observation; it is not substituted for frozen evidence.

The historical five-pair A/B bundle correctly retains a null presolve value.
The new frozen-`25ec2f1` five-pair bundle records the final Stage-1 Gurobi
`PRESOLVE` callback timestamp for every child and labels it as elapsed time
from `optimize` start, not as a dedicated internal presolve-duration attribute.
Its artifact hashes verify and its clean pre/post run SHA, prepared input,
runtime environment, seed, threads, time limits, and solver controls are
persisted. This read-only telemetry change does not alter the release gate.

## Requirement-by-requirement evidence

| Requirement | Evidence | Status and allowed conclusion |
| --- | --- | --- |
| Reproducible run identity | The [request manifest](../evidence/pure_ice_weather_ab_453b1d3/request_manifest.json) records clean execution SHA `453b1d3`, prepared-input and control hashes, seed 42, one thread, 435/30-second stage limits, candidate limit/radius `1/0`, 10% requested gap, selector OFF, BestObjStop OFF, and weather-operation policy OFF. | **Verified for the cited artifacts.** The later `abf149d` documentation HEAD does not relabel the runs as its own formal evidence. |
| 264-trip pure-ICE aggregation A/B | [SUNNY repeated comparison](../evidence/pure_ice_weather_ab_453b1d3/SUNNY_repeated_comparison.json), [RAIN repeated comparison](../evidence/pure_ice_weather_ab_453b1d3/RAIN_repeated_comparison.json), and [cross-scenario comparison](../evidence/pure_ice_weather_ab_453b1d3/weather_cross_scenario_comparison.json): twenty isolated children, ten AB/BA pairs, all 264/264 served, physical validation, Rolling 24/24, accounting, no fallback/repair/proxy, and exact aggregate-path recovery. RAIN keeps the 2025-08-05 WEEKDAY service and uses PV sourced from 2025-08-10. | **PASS_STRUCTURAL_ONLY in both scenarios.** Median variables/binaries/constraints decrease 29.392%/32.012%/17.171%, but solver time worsens from 30.754 to 435.106 seconds in SUNNY and 31.887 to 435.103 seconds in RAIN. Do not claim speedup, optimality improvement, endogenous fleet-composition response, 1%-optimality, or integrated global optimality. |
| Long-cap aggregate reachability | [Single diagnostic](../../output/diagnostics/pure_ice_aggregation_single_long_stage1_96982ab_20260824/diagnostic_result.json): one clean-`96982ab` pure-aggregate child with identical prepared input, seed, threads, model controls, and an explicit 870/30/120-second Stage-1/Stage-2/overhead contract. It serves 264/264, passes physical validation, accepts Rolling 24/24, reconciles accounting, has no fallback/repair, and has verified diagnostic artifact hashes and BFF input provenance. | **Valid diagnostic only.** The 3.041301684% certified Stage-1 gap is 0.036210 percentage points below the 435-second aggregate median but remains above 1%. One aggregate observation is not A/B, speed, cost, optimality, or research-acceptance evidence, and it cannot authorize a formal run. |
| Small integrated oracle | [Scale certificate](../../output/verification/small_integrated_oracle_scale/93e31b0_20260824/scale_certificate.json): 8/12/24/40-trip Phase-4 references are optimal at zero gap; Phase-3 pairs complete. | **Verified, bounded only.** 24/40-trip identifiable ApproxGap is 0.0 within numerical tolerance; 8/12 relative gaps are correctly not identifiable because the reference cost is zero. This does not certify 264-trip global optimality or a full-scale Phase-3 cost bound. |
| Economic one-factor response | [BEV-energy/PV/BESS/charger matrix](../../output/thesis_remaining_sensitivities_27ec8ce_20260824/sensitivity_execution_manifest.json), [electricity matrix](../../output/thesis_economic_electricity_93e31b0_20260824/sensitivity_execution_manifest.json), [diesel matrix](../../output/thesis_economic_diesel_93e31b0_20260824/sensitivity_execution_manifest.json), and [vehicle-day matrix](../../output/thesis_economic_vehicle_day_9650ed9_20260824/sensitivity_execution_manifest.json) each record fresh Prepare, complete successors, physical validation, Rolling, accounting, provenance, and stable non-varied controls within their own frozen family. The three current no-HTTP re-audits at `output/verification/thesis_economic_*_reaudit_365a6b5_20260824/` re-verify every copied source bundle. | **Executed but not accepted.** All 21 full-scale cases fail only `mip_gap_target_met` (1.780295%--26.849287% versus 1%). Candidate changes establish input propagation and feasible-candidate provenance only; they are not economic-response results and cannot be compared across differently frozen families as one common experiment. |
| Fixed-plan stress | [Stress result](../../output/diagnostics/fixed_solution_stress_0ddcd22_20260824/fixed_solution_stress.json) fixes the exact source decision and forbids reoptimization. | **Limited robustness evidence.** Only initial SOC -5 percentage points remains physically accepted (0 JPY fixed-decision delta); the other six predeclared stresses fail physically and have no invented cost. This is not recourse robustness. |
| M0--M3 comparison | [40-trip audit](../../output/verification/small_m0_m3/93e31b0_20260824/audit.json) has M0--M3 present and feasible; M0/M3 are exact small references and M2/M3 have the same declared problem-input hash. | **PASS_SMALL_SCOPE_ONLY.** M2--M3 differs by `2.546585164964199e-11` JPY. M0/M1 differ in fleet and/or PV/BESS treatment, so their deltas are descriptive ablations, not a full-network method comparison. |
| Independent review | Internal artifact and regression audit is complete. [External review brief](THESIS_EXTERNAL_REVIEW_BRIEF.md) identifies the frozen evidence, proof questions, commands, and requested decision. No separate external reviewer approval is stored in this repository. | **Open gate.** Do not report `LGTM`, `READY`, or “model complete.” |

## Root-cause evidence for the active blocker

The quality-qualified Stage-1 continuous relaxation at
`output/2026-08-24/run_20260824_0124/` is optimal at 52,749.163582 JPY with a
maximum primal violation of `5.820766e-11`. It splits every one of the 264
trips over vehicle labels (2,274 fractional assignment variables), while all
60 vehicle activations are integral. Stage 1 already includes the continuous,
time-indexed charger/PV/BESS/grid recourse relaxation. The blocker is therefore
the vehicle-labelled assignment/path relaxation, not an omitted time-indexed
energy balance.

Observed candidates do not justify a new row: the full vehicle-by-overlap
audit found no violated overlap-clique inequality; explicit/lifted fragment
rows and generic cut/scaling diagnostics did not improve the certified bound;
the activation-to-start row remains default-off because its 264-trip diagnostic
did not yield a comparable root-LP result; and the clean-`0bd81bc` BFF root-LP
audit at `output/2026-08-24/run_20260824_1050/` checks 1,404,360 same-day
no-path assignment pairs, finds zero violations (maximum mass `0.8457521`),
and adds no row. Its clean-`91cfbb5` successor at
`output/2026-08-24/run_20260824_1114/` checks 815 deterministic high-mass
no-path cliques and also finds zero violations (largest mass
`1 + 2.20e-14` within the `1e-6` tolerance); because that discovery is
heuristic, it rejects only the checked cliques. The current source adds a
default-off exhaustive read-only maximum-weight clique separator. Its frozen
clean-`f71bc51` 264-trip artifact at
`output/diagnostics/stage1_assignment_path_exact_clique_root_f71bc51_20260824/`
has an optimal, quality-qualified root LP and completes all 59 eligible
vehicle/day auxiliary MIPs (one is trivially nonviolating) with no timeout,
skip, or violation; its largest mass is `1 + 2.22e-14` within the `1e-6`
tolerance. This rejects the complete no-path clique family at that root point,
adds no row, remains diagnostic-only, and does not change this blocker. Adding a duplicate charger or
energy row, reducing the declared gap, or restricting fragments without a
proof would change or weaken the research contract and is not authorized.

The clean `1aaaa27` Stage-1 exact-clone equal-count rank tie-breaker attempt
at `output/diagnostics/stage1_clone_rank_root_1aaaa27_20260824/` held the
prepared input and solver controls fixed and added only 24 expected rows. Its
quality-qualified root LP differs from the unstrengthened value by about
`-8.1e-10` JPY, inside the predeclared `1e-5`-JPY tolerance. Its 435-second
primary MIP obtained raw bound `0`, leaving an analytical-floor gap of
`19.2651169%` versus the prior `19.2273066%`. Hash and BFF provenance checks
pass, but this is a negative diagnostic only; the source has been reverted to
the prior count-only Stage-1 symmetry call and it supplies no performance,
optimality, or release evidence.
For the activation-to-start diagnostic only, the next clean-SHA clone may use
dual simplex instead of the default barrier/crossover algorithm to determine
whether the absent LP point is algorithmic. That method selection is recorded,
does not alter the Stage-1 MIP, and supplies no evidence until the same quality
and controlled-comparison gates are met.
That follow-up is now complete at clean `a51b1f3`: the frozen normal-BFF
artifact `output/diagnostics/stage1_activation_start_dual_root_a51b1f3_20260824/`
keeps the prepared-source hash, four threads, 300-second cap, and the same 60
valid rows/model size, but selects dual simplex. It too ends at the cap with
`SolCount=0`; therefore there is no root objective or quality-qualified point
to compare with the barrier result. Its verdict is
`NO_COMPARABLE_ROOT_LP_SOLUTION`, not evidence that the inequality improves the
root bound or should be enabled.
The next clean `08af482` one-row subset observation restores a
quality-qualified barrier root-LP point, but not a stronger bound: the selected
row increases the model from 108,062 to 108,063 constraints and changes the
objective by `-4.37e-11` JPY, within the declared `1e-5`-JPY comparison
tolerance. Its `NO_ROOT_BOUND_IMPROVEMENT` verdict rejects MIP ON/OFF and
formal experimentation for this candidate.

The subsequent frozen clean-`f10525f` top-five subset diagnostic at
`output/diagnostics/stage1_activation_start_top5_root_f10525f_20260824/`
precommits the five largest baseline deficits, keeps the prepared-source hash,
seed 42, four threads, barrier/automatic crossover, 300-second root cap, and
default Stage-1 controls fixed, and adds exactly five rows (108,067
constraints). Its normal-BFF run `output/2026-08-24/run_20260824_1343/` passes
run-input provenance. The root LP is optimal and quality-qualified, but its
52,749.16358183858-JPY objective is only `+5.3e-10` JPY from the unstrengthened
point, within the same `1e-5`-JPY comparison tolerance. This second
`NO_ROOT_BOUND_IMPROVEMENT` rejects the tested high-deficit subsets of one and
five rows as root-bound paths. It does not establish redundancy of every other
subset, authorize a MIP ON/OFF comparison, or change the formal-release block.

## Thesis claim boundary

The evidence supports these statements:

- A BEV/ICE mixed-depot **two-stage** dispatch and charging method produced
  264-trip physically feasible, 24/24-Rolling, accounting-reconciled
  candidates under the cited frozen conditions.
- The small integrated reference model is exact for the bounded 8/12/24/40
  subsets under its recorded scalar-cost contract.
- Exact same-type ICE aggregation reduces the recorded Phase-3 formulation
  size and peak RSS on the five-pair controlled 264-trip study.

The evidence does not support these statements:

- 264-trip integrated global total-cost optimality, or a 1%-optimal final
  two-stage cost;
- a solver-speed improvement from aggregation;
- accepted full-scale economic sensitivity, PV/BESS/charger causal response,
  or recourse robustness; or
- deployment readiness, generalization to all depots, V2G optimization, or a
  complete independent review.

## Required next gate

No additional 264-trip formal run is authorized until a specific
vehicle-labelled assignment/path strengthening is proved valid for the
original integer feasible set, covered by a focused exact/small-MILP test, and
documented for its cost and comparability effects. Only then may a new clean
commit be tagged and submitted through the normal Prepare -> BFF ->
`/run-optimization` path. Existing output must not be reused as evidence for
that changed commit.

The current no-solver re-audit can be reproduced with the following command;
its expected exit code is `2` because the source matrix correctly remains
`BLOCKED`:

    .\.venv\Scripts\python.exe scripts\run_thesis_sensitivity_matrix.py `
      --rebuild-existing-dir output\thesis_remaining_sensitivities_27ec8ce_20260824 `
      --output-dir output\verification\thesis_remaining_sensitivities_reaudit_27ec8ce_20260824
