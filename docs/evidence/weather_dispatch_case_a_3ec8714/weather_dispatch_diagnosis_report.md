# SUNNY/RAIN Phase-3 weather-dispatch diagnosis

> Re-audited at clean SHA `3401ad8`. The original `3ec8714` report is retained
> byte-for-byte as `weather_dispatch_diagnosis_report_frozen_3ec8714.md`.
> Costs below now separate the day-ahead candidate from the authoritative
> accepted Rolling-day accounting total.

## Verdict

**PASS_NORMAL_PATH_CONFIRMATION / Case A (candidate-generation insufficiency).**

The former identical SUNNY/RAIN dispatch was not an exact-optimum result.  The
one-candidate Phase-3 path failed to expose weather-dependent canonical-cost
ordering.  A 22-candidate discrete-A union was fixed and cross-evaluated under
both weather cases; all 44 Stage-2, physical, accounting, unchanged-assignment,
and no-fallback/no-repair gates passed, and the two scenarios selected different
physical assignments.

The repaired public BFF path was then run from clean execution SHA
`ba5ac4abac490caccca006260670dfbc2c411fa9` after Fresh Prepare.  Both recorded
client requests asked for one candidate, radius zero, and frontier OFF.  The
formal server policy applied 22 candidates, radius four, and the existing
neutral BEV frontier.  The formal path preserved one Gurobi thread,
585/435/30-second total/Stage-1/Stage-2 limits, 10% requested gap, seed 42,
selector OFF, and BestObjStop OFF.  Pure-ICE aggregate representation B
remained OFF and was not rerun.

## Normal-path confirmation

| Scenario | Run | Candidates | Service | Physical | Rolling | Accounting | Used BEV/ICE | BEV/ICE trips | Day-ahead candidate (JPY) | Executed-day Rolling (JPY) | Physical assignment |
|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|---|
| SUNNY | `output/2026-08-28/run_20260828_0107` | 22/22 feasible | 264/264 | PASS | 24/24 | OK | 28/4 | 199/65 | 660,983.783805 | 660,983.783805 | `76fb6a9b635b...a516c` |
| RAIN | `output/2026-08-28/run_20260828_0119` | 22/22 feasible | 264/264 | PASS | 24/24 | OK | 21/11 | 91/173 | 698,296.465284 | 698,598.628643 | `213b2ccd4095...5316` |

Both physical assignment hashes exactly match the winners declared by
`cross_weather_fixed_dispatch_matrix.json`.  Fixed request controls match,
the internal timestep is 15 minutes, Rolling execution is 60 minutes, and both
runs used the same trip, vehicle, charger, depot, BESS-control, tariff,
objective, fleet-contract, and solver-control hashes.  The complete comparison
is in `normal_confirmation_input_contract_reaudit_3401ad8.json`; only scenario-specific
prepared snapshots, PV, and the canonical hash derived from PV differ.

## Case-A six-check audit

The union contains all ten frozen A incumbents plus 44 expanded source
candidates: 54 source rows deduplicate to 22 physical assignments.  Every
candidate was evaluated under both scenarios.
`case_a_candidate_selection_audit_reaudit_3401ad8.json`
records the following for both SUNNY and RAIN:

1. weather PV/BESS/tariff inputs enter Stage 1;
2. `used_in_stage1_objective=true`;
3. all 22 Stage-1 proxy and Stage-2 canonical ranks were compared (zero rank
   reversals in both scenarios);
4. final selection is not first-feasible or Stage-1-only;
5. physical assignment-hash deduplication is active; and
6. the confirmed normal run selects the minimum physically feasible,
   accounting-reconciled Stage-2 canonical cost.

SUNNY's second-place delta is 5,180.298562 JPY; RAIN's is 566.622470 JPY.
The final cross-evaluation/audit SHA is
`3ec87149d5d5fac3c3fae3c043bd1d69e89df7c6`.

## Gap and runtime interpretation

- In the frozen A/B bundle, discrete A reached the requested 10% gap after
  roughly 31 seconds, while aggregate B exhausted its approximately 435-second
  Stage-1 limit.  This is a termination-policy decomposition, not evidence that
  either incumbent is an exact optimum.
- The former common incumbent was 707,349.173370 JPY.  SUNNY's certified bound
  was 640,000 JPY (9.5213476% gap), while RAIN's was 695,632.938124 JPY
  (1.6563581% gap).  The difference was bound-side, not incumbent-side.
- The confirmed expanded-candidate runs retain those Stage-1 certified gaps;
  candidate coverage improves final feasible-dispatch selection but does not
  prove integrated global optimality.
- No runtime improvement is claimed from the production candidate repair.  It
  deliberately performs more Stage-2 candidate work.  Pure-ICE aggregation
  remains `PASS_STRUCTURAL_ONLY`, default-OFF, with no runtime or optimality
  benefit established.

## Excluded diagnostics

`output/2026-08-27/run_20260827_2359` is excluded from all conclusions.  Its
physical, Rolling, and accounting gates passed, but the confirmation harness
incorrectly overwrote the internal timestep to 60 minutes and misread an
unserved count of zero.  The harness repair is commit `710556b`; no solver
number from the excluded run is reused.

`output/2026-08-28/run_20260828_0022` and
`output/2026-08-28/run_20260828_0034` are also excluded from fixed-control
claims because the ordinary public BFF policy changed their requested one
thread to four effective threads.  They motivated the runtime-control repair;
their solver measurements are not reused as formal evidence.

## Claim boundary

Supported:

- the original same-dispatch observation was a candidate-coverage artifact in
  these two fixed scenarios;
- SUNNY and RAIN select different validated Phase-3 dispatches after neutral
  candidate coverage is applied;
- all required feasibility, Rolling, accounting, provenance, and fixed-control
  gates pass for the two confirmation runs.

Not supported:

- integrated global optimality;
- a general weather benefit beyond these two scenarios;
- a certified-gap improvement;
- a runtime benefit from expanded candidate coverage or pure-ICE aggregation;
- enabling pure-ICE aggregation by default;
- thesis/research release readiness.

The active release blocker is the unresolved Stage-1 certification gap,
especially SUNNY's 9.5213476%.  Phase 3 remains a bounded two-stage method.

## Validation and clock

- Goal start: `2026-08-27T22:24:56.4747651+09:00`
- Final evidence completion: `2026-08-28` (within the same goal window)
- 20-hour implementation cutoff: not approached
- 24-hour hard cutoff: not approached
- Related integration tests: `247 passed in 2.99 s`
- Full suite: `1602 passed in 88.55 s`
- Fresh execution SHA: `ba5ac4abac490caccca006260670dfbc2c411fa9`
- Final cross-evaluation/audit SHA: `3ec87149d5d5fac3c3fae3c043bd1d69e89df7c6`

## Reproduction command

There is no valid `--resume` command.  A deliberate full reproduction must use
a new empty output directory, a clean frozen commit, and the BFF from that same
commit:

```powershell
.\.venv\Scripts\python.exe scripts\run_weather_dispatch_diagnosis.py `
  --stage all `
  --base-url http://127.0.0.1:8000 `
  --existing-bundle output\diagnostics\pure_ice_weather_ab_453b1d3_20260827 `
  --output-dir output\diagnostics\weather_dispatch_diagnosis_<new-date>
```

This command re-reads the old B evidence but executes only discrete A for new
candidate discovery and confirmation; it does not rerun aggregate B.
