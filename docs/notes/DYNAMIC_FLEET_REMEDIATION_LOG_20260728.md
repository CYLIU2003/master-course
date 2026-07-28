# Dynamic fleet remediation log — 2026-07-28

Status: local implementation and regression completed; fresh formal evidence
pending.

## Reachable path reviewed

```text
frontend POST run-optimization
  -> BFF research preflight
  -> materialized prepared scenario
  -> ProblemBuilder
  -> Phase 3 Stage 1 / Stage 2
  -> 24-step Rolling
  -> independent event validator
  -> executed-day accounting
  -> final report reconciliation
```

## Changes

- Replaced fixed fleet-count authority with
  `scenario_fleet_contract_v2`.
- Added strict raw ID/type/depot/availability/parameter validation, including
  contradictory availability fields and explicit initial SOC/fuel.
- Unified availability and powertrain normalization.
- Materialized vehicle-type-catalog battery, consumption, charge-power, and
  charger-compatibility parameters into the canonical active records and hash.
- Preserved excluded unavailable vehicles with reasons.
- Bound BFF, ProblemBuilder, formal CLI, comparison, and audit outputs to
  exact active vehicle IDs and content hashes.
- Made formal CLI Rolling the default; day-ahead-only is explicitly
  exploratory and blocked.
- Removed generic 264-trip/15-minute/96-slot comparison constants; experiment
  assertions are optional.
- Added independent service/deadhead/waiting/charging/refueling/return event
  reconstruction with fail-closed metrics and charger/location checks.
- Aggregated grid/PV/BESS source rows into one physical charging session.
- Added a run-global wall-clock deadline shared by Stage 2 feedback retries.
- Reconciled every enabled canonical accounting component across final
  artifacts, and kept vehicle usage, fixed, and acquisition cost fields
  semantically separate in the human-facing report.
- Made the legacy feasibility metric gate fail closed on missing/invalid
  required metrics and included duplicate-trip assignments in the clean gate.
- Enabled the Tk frontend to preserve the shared 5/15/30/60-minute time-axis
  choices; the current formal experiment specification uses 15-minute internal
  slots and 60-minute Rolling execution.
- Removed tracked one-off temporary scripts and added a Windows GitHub Actions
  workflow for compile, focused research contracts, and the full non-licensed
  test suite.

## Mathematical and comparability effect

The fleet feasible region is now defined by the prepared scenario's exact
active vehicle set, not a repository-wide count. This may change every prior
assignment, charging plan, objective, gap, and runtime comparison. Old outputs
must not be reused after this change.

The event validator does not change the solver feasible region. It adds an
independent release gate and may correctly reject schedules that older
aggregate metrics accepted.

The feedback deadline does not add or remove a mathematical constraint. It
changes termination by enforcing the declared wall-clock budget across every
retry.

## Remaining evidence

- clean frozen commit;
- fresh high-PV, low-PV, and no-PV formal runs;
- 24/24 Rolling and all release-table rows;
- runtime repetitions, small integrated-MILP comparison, and uncertainty
  stress tests.

## Local validation

- focused research contracts and critical Gurobi integration: passed;
- full suite: `972 passed`;
- fresh high/low/no-PV solver run: not executed;
- GitHub Actions: workflow added, remote run not yet available.

Until those are present:

`BLOCKED — fresh formal execution evidence is absent`
