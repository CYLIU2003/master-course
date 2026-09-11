# Reuse an identical structural coverage precheck

The frozen winter rolling solve spent about 33 seconds per hour. Profiling one
retained-input replay recorded 134.713 seconds with instrumentation, of which
116.890 seconds were in `evaluate_strict_coverage_precheck`. It rebuilt the same
1,434,720 interval-feasible trip pairs on every hourly invocation. Profiling
overhead makes these instrumented times unsuitable as uninstrumented timings.

The relaxed precheck explicitly ignores SOC, fuel, chargers and per-type fleet
counts when computing its path-cover bound. Its result depends on timetable,
compatible types, available fleet count/home depots and dispatch transition
rules. The native solve and independent validation still evaluate energy state.

`OptimizationEngine` now keeps one private result. Its fingerprint includes the
entire canonical scenario, canonical trips, all DispatchContext dataclass fields,
fleet IDs/types/home depots/availability, and the three metadata controls consumed
by the precheck: coverage mode, fixed route bands and same-day depot cycles.
Values are serialized without rounding, with typed mapping keys. The same input
hash is checked before and after a fresh evaluation; any structural edit forces
the original complete precheck to run. Standard canonical contexts only are
eligible; subclasses, custom attributes and unsupported input objects disable
reuse. Each returned result is copied to avoid mutation of the stored audit.

This changes no feasible successor candidates, path-cover calculation, native
constraints, physics, solver budgets, objective or acceptance rules. It does not
reuse a solve result. The result audit retains the structural input SHA-256 and
whether the identical precheck was reused. A new engine/week begins without a
cached result. Actual SOC, fuel and PV changes still enter every hourly solve.

Fingerprinting the 1,704-trip / 60-vehicle diagnostic input took 0.0692 seconds.
Six sequential real-input hourly replays passed. The first evaluation took
33.028 seconds; the next five took 6.594 to 6.727 seconds. All six audits retained
the same input hash, 1,434,720 interval-feasible pairs and relaxed lower bound 32.
A separate controlled replay of exactly the same hour 27 and measured state took
33.246 seconds without reuse and 6.711 seconds with reuse. Assignment, charging,
SOC, source flows, cost breakdown and other decision fields were identical;
only timing/control audit metadata changed. These are retained-input diagnostics,
not seasonal acceptance evidence.

Independent review identified an omitted cache audit on the precheck-infeasible
early return. Both return paths now preserve the input hash and reuse flag.
The targeted cache/SOC/failure-progress suite passed 68 tests. Cache-specific
tests passed 15/15; final independent review found zero remaining P0/P1.
Full regression passed 2,197 tests with the two existing PowerPoint evidence
failures in 95.37 seconds; JUnit:
`output/exact_depot_factor_validation/pytest-rolling-roundoff-precheck-release.xml`.
A new frozen campaign with
fresh Prepare is required; retained-input timing does not establish seasonal
acceptance or research eligibility.
