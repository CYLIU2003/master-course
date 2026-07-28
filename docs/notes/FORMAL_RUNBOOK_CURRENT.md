# Formal Phase 3 runbook

Status: **CURRENT**

This runbook supersedes fixed 35/26 procedures.

## Freeze and preflight

```powershell
git status --porcelain
git rev-parse HEAD
```

Do not start unless the worktree is clean. Record the SHA and do not edit code
until every case in the formal experiment is finished.

Prepare must materialize explicit vehicle records. Select the depot and
service explicitly; do not infer “all depots” from an empty value.

## Formal runner

The formal default is:

```text
day-ahead
  -> full 60-minute Rolling chain
  -> independent physical event validation
  -> executed-day accounting
  -> final JSON/Markdown/XLSX/ledger reconciliation
```

Example:

```powershell
.\.venv\Scripts\python.exe scripts\run_research_phase3_frontend_weather.py `
  --case-name <case> `
  --scenario-id <scenario-id> `
  --prepared-input-id <prepared-input-id> `
  --expected-service-date 2025-08-05 `
  --depot-id <depot-id> `
  --service-id WEEKDAY `
  --time-step-min 15 `
  --rolling-execution-minutes 60 `
  --output-dir <output-dir>
```

Counts are derived from `scenario_fleet_contract_v2`. Optional
`--assert-bev-count` / `--assert-ice-count` values only check a
scenario-specific expectation.

`--day-ahead-only-exploratory` is diagnostic. It is not a completed formal run,
writes `teacher_release_status=BLOCKED`, and returns a non-completion exit
code.

The Tk frontend and BFF accept the shared `5`, `15`, `30`, and `60` minute
time-axis values. The current formal experiment specification uses 15-minute
internal slots and 60-minute Rolling updates. A different slot width is a
separately declared sensitivity, not an implicit alternative formal model.

Do not use `--available-bev-count` in a formal run. It is accepted only
together with `--day-ahead-only-exploratory`; formal runs use the exact active
set frozen by Prepare.

## Runtime experiment

Runtime comparisons must keep the same prepared content hashes, seed, time
limits, and threads, and must disable the analytical objective stop:

```powershell
--no-stage1-best-obj-stop --gurobi-threads 1
```

Run each condition at least three times and report median wall time, first
incumbent, nodes, best bound, raw Gurobi gap, certified gap, and feedback
iterations.

## PV counterfactual

High-PV, low-PV, and no-PV cases must match on:

- trip hash;
- fleet-contract, active-ID, vehicle-parameter, and initial-state hashes;
- charger, BESS, tariff, service-calendar, and solver-control hashes.

Only the separately recorded PV curve hash may differ. Scenario and prepared
IDs remain provenance; scientific equality is determined by immutable content
hashes.

## Release rule

Every row in
[`CURRENT_RESEARCH_RELEASE_BLOCKERS.md`](./CURRENT_RESEARCH_RELEASE_BLOCKERS.md)
must be filled from fresh artifacts. A failed row retains diagnostic numbers
but requires:

- `DIAGNOSTIC RESULT`;
- `NOT USED FOR RESEARCH CONCLUSIONS`;
- the complete `BLOCKED` reason list.
