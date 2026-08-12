# Thesis equation, implementation, and test map

Status: implementation traceability draft, 2026-08-12.

This file maps the thesis-facing model to the currently reachable Phase 4
integrated implementation. `docs/constant/formulation.md` remains the notation
reference. This map is deliberately explicit about tests that are still
missing; a named constraint is not evidence that the complete formulation is
validated.

| Thesis relation | Runtime variables / code | Independent or focused test | Current evidence |
|---|---|---|---|
| Every eligible trip is served exactly once | integrated `y[v,trip]`, strict `unserved[trip]=0`; `GurobiMILPAdapter.solve` | `tests/test_small_exact_assignment_oracle.py`; strict-coverage tests | Four-trip exhaustive assignment equality; full-run physical validation remains separate |
| Vehicle-trip compatibility (a_{v,i}) | Prepare `vehicle_trip_compatibility_audit`; canonical `allowed_vehicle_types`; integrated assignment-variable eligibility | `tests/test_run_preparation_scope_audit.py` | Complete vehicle-ID matrix and hash are exported; same-powertrain per-vehicle restrictions currently fail closed |
| Vehicle flow conservation | `start_arc`, `x[v,i,j]`, `end_arc`; incoming + start = assignment and outgoing + end = assignment | small exact oracle plus transition tests | Exhaustive four-trip path assignment agrees with MILP |
| Connection feasibility (a_i+turn_i+deadhead_{ij}\le d_j) | `DispatchContext.feasible_connections`; `fragment_transition_diagnostic` | `tests/test_route_band_transition_reason_codes.py`, `tests/test_run_preparation_scope_audit.py` | Missing OD, alias failure, route-band policy, and insufficient time are distinct |
| Startup, inter-trip, and return deadhead energy/fuel | `startup_deadhead_*`, `_deadhead_energy_kwh`, `_deadhead_fuel_l`, `return_deadhead_energy_kwh` | small exact fuel oracle; physical validation suites | All-ICE startup/connection/return fuel is independently enumerated; electric oracle boundary case remains open |
| BEV trip energy | `trip_energy_kwh`, `fuel_l_by_vehicle_type`, `trip_energy_proxy.py`; assignment-linked integrated expressions | `tests/test_trip_energy_proxy_and_location_aliases.py` and energy accounting suites | Route/direction/time-band proxy and sensitivity scale are tested; empirical calibration remains an input-study task |
| Vehicle SOC transition | integrated SOC expressions and `soc_transition__*`; Stage 2 `s_var`; independent `SOC_FRAGMENT` guard | SOC/terminal/physical-validation suites; `tests/test_immediate_charge_baseline.py` | Solver and independent physical checker evaluate single-fragment SOC; ambiguous multi-fragment electric transitions fail closed; a complete electric exhaustive oracle remains open |
| Charger availability, setup/teardown, minimum session, and taper | physical charger binaries/power variables; `charging_power_model=piecewise_soc_taper_v1`; M0/M2 `immediate_charge.py` | charge-taper and physical-charger test suites; `tests/test_immediate_charge_baseline.py` | Optimized and deterministic rule paths are separately identified; 15/30/60-minute formal comparison remains unexecuted at current HEAD |
| Depot power balance | `grid_import`, `pv2bus`, `pv2bess`, `bess2bus`, curtailment, bus load | energy-flow and accounting reconciliation suites | Exact depot/slot flows are preserved; final reporting uses executed Rolling values |
| BESS SOC and terminal target | integrated/Stage-2 BESS SOC expressions and resolved terminal target | BESS terminal and energy-flow tests | Initial inventory is not treated as free when terminal target equals initial SOC |
| Lexicographic objective | strict service, used vehicle-days, canonical operating cost, then deadhead/session terms | small exact oracle; objective and accounting reconciliation tests | Four-trip primary/secondary choice matches enumeration; formal full-scale optimality still depends on certified gap |
| Cost-CO2 epsilon constraint | `co2_emissions_epsilon_cap_kg` and `co2_emissions_epsilon_cap_kg` constraint | experiment-matrix contract tests | Parameter path exists; Pareto frontier has not been formally executed at current HEAD |

## Bound and Big-M policy

The integrated SOC transition is expressed with assignment-linked physical
energy expressions rather than a generic SOC Big-M. The Stage-1 energy proxy
uses a continuous upper bound

\[
M_v^{source}=\frac{\max(E_v^{positive}, B_v, 1)}{\eta^{ch}},
\]

where `positive_energy_bound_kwh` is the sum of all positive trip, startup,
connection, and return-energy coefficients available to vehicle `v`, and
`capacity_kwh` is its physical battery capacity. The implementation variables
are `battery_big_m_kwh` and `source_big_m_kwh` in
`src/optimization/milp/solver_adapter.py`. This value is a finite variable
bound for the positive-part proxy, not permission to relax physical SOC.

## Required additions before this map is complete

1. Add electric exhaustive fixtures for PV=0, BESS=0, charger shortage,
   terminal SOC, and electricity-price break-even.
2. Attach exact generated Gurobi constraint names to every row where the
   integrated path currently relies on unnamed constraints.
3. Persist the selected direct-versus-depot fragment transition and its energy
   in the solver result, then replay multi-fragment electric SOC continuously;
   until then `SOC_FRAGMENT` remains a formal blocker.
4. Execute M1 explicitly and compare fresh M0--M3 candidates from the same
   prepared input and frozen SHA. M0/M2/M3 day-ahead artifacts now share the
   BFF cost evaluator and physical checker, but this deliberately does not mix
   their day-ahead values with accepted Rolling accounting.
5. Execute the predeclared 15/30/60-minute, route-band, energy-scale, PV-scale,
   and CO2-cap matrices from a clean frozen commit.
