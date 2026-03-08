# Agent Handoff Boundaries

This repository is ready for agent-assisted changes only if the following
operational boundaries are treated as fixed:

- `src/dispatch/` remains timetable-first and owns dispatch feasibility.
- `frontend/src/pages/planning/` and `MasterDataPage` are the primary planning UI.
- `planning-legacy` is compatibility-only and should not receive new features.
- Scenario snapshots are persisted in the scenario store; background job state is not.
- Public transit import databases and scenario snapshots serve different purposes and
  must not be treated as interchangeable sources of truth.

## Runtime Status

- `run-simulation` is implemented against scenario-derived `ProblemData`.
- `run-optimization` is implemented against canonical optimization inputs.
- Both routes are asynchronous and persist final results to the scenario snapshot.
- Job state is process-local and is lost if the BFF restarts.

## Safe Priorities For Agents

1. Tighten schema contracts between frontend, BFF, and core.
2. Keep dispatch feasibility rules connected to scenario deadhead and turnaround data.
3. Split scenario storage responsibilities without changing external API behavior.
4. Do not add new work to legacy planning routes.
