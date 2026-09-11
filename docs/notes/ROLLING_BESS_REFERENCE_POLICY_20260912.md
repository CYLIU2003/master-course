# Rolling BESS minimum-only boundary policy

## Frozen campaign evidence

The fresh campaign at `803f8f9ff0208b2a21014ff0bdad59d0152ad858` completed
the winter week (2025-02-03) with 168/168 accepted hourly prefixes, independent
physical validation, and eligible executed accounting. The daily cost
reconciliation difference was 0 JPY. Independent evidence review found no P0/P1
issue in that diagnostic result. The accepted winter total is
4,221,601.863135596 JPY, from its `executed_day_accounting.json` only.

Spring (2025-05-12) passed day-ahead physical validation and 54 hourly prefixes,
then stopped with a BESS fixed-terminal validation exception. Summer and autumn
were not executed after the failure. The worktree stayed clean at the same SHA.
These outputs remain evidence for `803f8f9f`; they are not results for the fix.

Evidence root:
`C:/master-course-worktrees/shibu21-23-precheck-20260912/output/shibu21_23_exact_precheck_campaign_20260912`.
Each week has a `cases/<week>/summary.json`. Detailed inputs, forecasts, physical
checks and accounting are in `cases/<week>/diagnostic/<week>/`.

## Cause and correction

The public `RollingReoptimizer.reoptimize_charging_hour` path froze evaluation
targets, built intermediate day-ahead BEV and BESS targets, and only afterward
applied the explicit `bess_terminal_policy="minimum_only"` override. Replacing
the canonical problem validates BESS assets immediately. Thus an irrelevant
fixed BESS target could fail before the minimum-only override removed it.

At the failed spring hour 54, the 24-hour boundary was slot 312. The day-ahead
BESS trace at slot 311 was `1199.9999999999998 kWh`, versus the physical lower
bound `1200 kWh`: a difference of `-2.2737367544323206e-13 kWh`. The actual BESS
state carried from hour 53 was exactly `1200 kWh`.

The intermediate-target helper now receives the explicit rolling BESS policy.
For `minimum_only`, it constructs a minimum-only asset directly, without reading
or temporarily constraining the BESS boundary trace. The BEV boundary targets
and charging-session continuation metadata are still derived from the fixed
day-ahead forecast plan. The default `scenario` policy keeps its existing BESS
reference behavior and validation.

For an intermediate window, the effective BESS terminal floor remains the
physical lower bound, as before. At the true evaluation end, the original
period-end floor is preserved. Frozen daily balance targets remain unchanged.
This avoids imposing a stricter period-end floor on earlier windows.

The intended intermediate minimum-only model is still
`E_min <= E_t <= E_max`, with `E_window_end >= E_min` and no equality to the
day-ahead BESS reference. At the true evaluation end its declared terminal
floor applies. No physical bounds, SOC values, costs, energy conversions,
vehicle assignments, successor candidates, fuel rules or PV information
boundaries are relaxed or rewritten. On previously valid inputs, the model
sent to the solver is unchanged.

## Failure reporting

The campaign phase summary previously labelled a missing day-ahead feasibility
field in an exception record as `DAY_AHEAD_FAILED`, even when a separate saved
physical gate had passed. Missing solver results now use
`DAY_AHEAD_RESULT_UNAVAILABLE`; an explicit `False` remains a failure. A rolling
exception retains its reason in the rolling phase summary. These fields do not
infer feasibility from physical acceptance and do not grant accounting approval.
The original failed campaign files are preserved without alteration.

## Validation and remaining gates

The six boundary regressions include the actual physical-floor roundoff, missing
BESS reference data under minimum-only versus scenario policy, a stricter
period-end floor, and rejection of an invalid measured BESS state. Boundary and
campaign tests passed (13 tests); the independent code review found P0=0/P1=0.
The final full regression was **2,205 passed / 2 existing PowerPoint failures**
in 107.91 seconds. JUnit:
`output/exact_depot_factor_validation/pytest-bess-boundary-policy-release.xml`.

The retained-input spring replay passed hours 54 through 100 after the
minimum-only correction. Hour 101 then revealed a separate actual-PV energy
shortage, documented in [the committed-prefix reserve correction](ROLLING_PV_EXECUTION_RESERVE_20260912.md).
This replay starts from the saved hour-53 state and is a regression diagnostic
only. The 2,205-test full-suite result above predates the new PV reserve change. A fresh
clean-commit Prepare and all four complete weekly executions are still required
after this change.

The winter and spring Stage 1 certified gaps were 84.6452549% and 84.6046457%,
respectively, against a declared 10% target. All 78,647,760 successor candidates
were retained in winter, with zero pruning; that does not prove optimality.
The two-stage method is not an integrated global total-cost optimum.

Research release remains **BLOCKED**. These diagnostic inputs combine a 2026
timetable with 2025 PV and a provisional 2024-only training history. Formal
fleet-contract provenance is undeclared, and the two existing PowerPoint
evidence regression failures remain separate blockers. All campaign outputs
remain **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**.
