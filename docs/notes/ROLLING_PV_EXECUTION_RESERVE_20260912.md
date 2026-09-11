# Committed rolling commands under unobserved PV

## Observed failure

After correcting the unused minimum-only BESS reference, the retained spring
replay passed hours 54 through 100. Hour 101 was solver-feasible but its actual
PV execution violated the BESS lower bound. This was a genuine energy shortage,
not floating-point roundoff.

The observed initial BESS energy was `1199.9999999999998 kWh`, within numerical
tolerance of the `1200 kWh` floor. At slot 404, the forecast planned
`5.540166171158489e-5 kWh` of PV charging; actual PV was entirely needed by buses,
so none reached storage. At slot 407, the fixed BESS command still discharged
`4.9999999873762135e-5 kWh`. Its resulting inventory was
`1199.9999473684209 kWh`, below the floor by about `5.263e-5 kWh`, exceeding the
existing `1e-6 kWh` execution tolerance.

Evidence: `output/rolling_spring_bess_boundary_diagnostic/hour_101_energy_shortage_audit.json`
and the retained replay log. These are diagnostic regressions, not a fresh
complete campaign result. The original frozen campaign remains unchanged.

## Pre-solve correction and mathematical effect

The actual-PV controller already keeps bus charging, BESS discharge and
grid-to-BESS commands fixed. It supplies bus demand from available actual PV
first and only then executes up to the planned PV-to-BESS charge. Therefore,
future unobserved PV cannot safely fund a discharge command issued now.

The reachable native Stage 2 charging model now adds the following constraints
for each depot and each slot end `k` in the committed execution prefix:

```text
E_actual_start + eta_charge * sum(grid_to_bess[j], j <= k)
               - sum(bess_to_bus[j], j <= k) / eta_discharge
    >= E_physical_min
```

All flows are kWh. Efficiency multiplies charging energy and divides discharged
energy. The reserve uses the actual state supplied before solving and the
physical lower bound, not a period-end target. It does not reset at midnight.
No unobserved PV-to-BESS energy is credited before the next state update.

For hard grid-import limits only, each committed slot also requires:

```text
grid_to_bus[k] + pv_to_bus[k] + grid_to_bess[k]
    <= import_limit_kw * timestep_hours
```

This is the grid supply needed when actual PV is zero. Soft contract overage
keeps its existing policy. Existing source/time permissions, charge/discharge
modes, power limits, forecast upper SOC and terminal conditions remain active.
Because realized PV-to-BESS charge cannot exceed its issued command, the
forecast upper SOC bound also bounds the executed upper SOC.

The constraints are enabled only for remaining-day rolling with the existing
`date_series_contract.pv_information_mode="training_only_forecast_proxy"`.
This matches the production actual-PV input preparation contract. The prefix
uses `rolling_execution_minutes / timestep_min`, truncated at the horizon end.
Later forecast slots, day-ahead optimization and historical perfect-information
cases keep their existing formulation. No actual future PV values are passed
to these constraints.

This deliberately restricts the feasible set of the affected committed-prefix
model. It can change charging choices and costs; it is not a numerical-tolerance
change or a claim of equivalent objectives. Assignments remain fixed to the
day-ahead solution, and the full successor network is retained. The correction
does not repair, clamp or replace issued commands after solving.

## Audit and validation

Stage 2 success and failure metadata carry `rolling_pv_execution_reserve`, with
the policy, committed slots, constraint counts, initial BESS state and physical
floors. In serialized results this is in the plan `metadata` object.

The retained hour-101 replay now reaches the native solver and actual-PV
execution successfully: four reserve constraints cover slots 404 through 407,
with initial state and physical floor both `1200 kWh`. Its new issued BESS
discharge is zero throughout the prefix. Bus commands remain unchanged during
execution and no future observations are used. The retained replay then passed
all 67 native solves and actual-PV executions for hours 101 through 167. Evidence
is in `output/rolling_spring_pv_reserve_diagnostic/` and its sibling `.log` file.
It starts from a retained state and is not complete weekly acceptance evidence.

Seven new native-Gurobi regressions passed. They cover every committed prefix,
grid-charge efficiency, zero-PV controller execution, nonzero slot origins and
horizon clipping, inactive policies, hard versus soft import, and independent
depot physical floors. The independent helper/adapter implementation review
found P0=0/P1=0. Full regression with `python -X utf8 -m pytest -q` completed with
**2,212 passed / 2 existing PowerPoint evidence failures** in 98.32 seconds.
JUnit: `output/exact_depot_factor_validation/pytest-pv-execution-reserve-release-utf8.xml`.
An earlier run without UTF-8 additionally failed two presentation tests reading
UTF-8 evidence under Windows CP932; both passed with UTF-8. No presentation
source or expected evidence hashes were changed.

The reserve protects immediate physical feasibility under nonnegative PV; it
does not certify later terminal targets, weekly accounting or optimality.
Those gates still require complete executions and independent validation.
After the change, all four weeks must be freshly prepared and run from a new
clean frozen SHA. The old winter pass is not evidence for the new model.

Research status remains **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**.
See [BESS boundary failure and prior evidence](ROLLING_BESS_REFERENCE_POLICY_20260912.md)
and [current blockers](CURRENT_RESEARCH_RELEASE_BLOCKERS.md).
