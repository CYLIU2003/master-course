# 2026-07-26 remediation self-review

## Code Review Summary

**Reviewer:** Codex self-review (MIT-style lenses)

**Scope:** Current remediation commit series
**Verdict:** Code-level P0/P1 not found after regression; research submission remains blocked

### Severity counts

- P0 BLOCKER: 0 code findings
- P1 MUST: 0 code findings
- P2 SHOULD: 0 open code findings
- External research gates: 3 open

This is not the independent Claude Code or executive review required by
`docs/AI_AGENT_REMEDIATION_20260726.md`.

## 1. Verified call chain

The current interactive path is:

`BFF _run_optimization`
→ `ProblemBuilder.build_from_scenario`
→ `OptimizationEngine.solve`
→ `_persist_canonical_graph_exports`
→ `build_accounting_artifacts`
→ reporting finalizer.

The movement regression invokes the production canonical-export/accounting
function rather than calling `ledger_builder` in isolation. The separate SOC
round-trip invokes Gurobi, converts the result to an `AssignmentPlan`, and
requires the independent `FeasibilityChecker` to return `VALID`.

## 2. Root cause

The prior BFF export represented one connection twice: as the following leg's
`deadhead_before_km` and as the preceding leg's `deadhead_after_km`. The
accounting layer summed both fields. This inflated physical distance, fuel,
ICE CO2, and fuel cost. The valid repair is a unique movement-event source,
not a monetary scaling factor.

The reviewed runs also lacked a fail-closed service calendar/weather contract,
clean and stable code provenance, truthful reporting `updated_files`, and a
terminal-SOC validity gate at the BFF boundary.

## 3. Minimal patch reviewed

- Added unique `startup`, `connection`, and `terminal_return` movement events.
- Made vehicle-slot accounting consume the event ledger without also consuming
  legacy before/after movement columns.
- Preserved physical fuel/CO2 independently from component enablement and
  objective semantics.
- Added service-date/day-type/holiday/counterfactual and declared-fleet checks.
- Added complete input hashes, runtime environment, dirty-patch identity, and
  start/end Git-state validation.
- Made BEV/BESS terminal failure block validated feasibility.
- Made reporting list only content-hash changes as updated files.
- Added machine-readable calendar/weather, fleet, and movement artifacts.

The patch does not alter `timetable_rows`, `operator_id`, or
`arrival + turnaround + deadhead <= next departure`.

## 4. Risks and side effects

- Fuel/CO2/deadhead KPIs from runs produced before this patch are not directly
  comparable and must not be repaired in place.
- Research runs now fail if Git is unavailable, dirty at start/end, or changes
  while the solver runs. Diagnostic runs remain allowed but are not
  research-ready.
- A weekday public holiday requires an explicit holiday date in the scenario
  calendar contract. Missing holiday metadata fails closed when the timetable
  day type disagrees.
- A declared inventory is enforced, but the optimizer does not force all BEVs
  to be used. Usage remains an output unless a separate policy experiment
  explicitly constrains it.

## 5. Validation

Executed with `GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q src bff
git diff --check
```

Results:

- 858 tests passed.
- Gurobi SOC round-trip was not skipped.
- Compileall passed.
- No whitespace errors were reported.

The ICE movement regression contains 12 km of service and 18 km of
startup/connection/terminal movement at 0.2 L/km. It verifies 6.0 L total,
3.6 L movement fuel, the corresponding ICE CO2, unique event IDs, and
solver-versus-physical fuel/CO2 checks.

## 6. Remaining uncertainty and external gates

The code change is not enough to accept a research result. These gates remain:

1. Commit the reviewed source and generate a new clean-worktree paired
   264-trip high/low-PV run with the declared 35 BEV + 26 ICE inventory.
2. Execute and accept both complete hourly rolling chains; do not relabel the
   day-ahead artifact as rolling evidence.
3. Obtain independent Claude Code and executive reviews. The `claude` CLI was
   not available in the current environment.

Until all three pass, the old 2026-07-26 runs and any new incomplete run remain
exploratory/non-research, and no global-optimality or actual-weather claim is
eligible.
