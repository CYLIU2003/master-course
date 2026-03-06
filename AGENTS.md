# AGENTS.md
# Timetable-Driven Dispatch Planning System

## Purpose

This document defines the architecture constraints and non-negotiable rules for
the EV bus dispatch planning module (`src/dispatch/`).

The central principle is:

> **Timetable first, dispatch second.**

Dispatch plans must always be derived from timetable constraints, never the
other way around.

---

## Scope

This contract applies to:

- `src/dispatch/*`
- BFF dispatch integration paths that call dispatch logic (`bff/routers/graph.py`)
- Any adapter that maps external models into dispatch entities

---

## Core Requirement

Given a set of revenue trips defined in the timetable, produce vehicle duties
such that:

1. Every eligible trip is covered exactly once.
2. Every consecutive trip pair in a duty is physically feasible.
3. No infeasible connection is introduced by assumptions or shortcuts.

---

## Feasibility Logic (Hard Constraints)

A vehicle may operate trip **j** immediately after trip **i** if and only if
all of the following are true.

### 1. Location Continuity

The vehicle must be able to move from `trip_i.destination` to
`trip_j.origin`.

- If `trip_i.destination == trip_j.origin`: no deadhead is needed.
- Otherwise, a `DeadheadRule` must exist for
  `(trip_i.destination, trip_j.origin)`.
- If no rule exists, the connection is infeasible.

### 2. Time Continuity

```
arrival_time(i) + turnaround_time(i.destination) + deadhead_time(i.destination, j.origin)
    <= departure_time(j)
```

This is a hard constraint. If false, the connection is infeasible.

### 3. Vehicle Type Constraint

`vehicle_type` must be included in `trip_j.allowed_vehicle_types`.

---

## Required Processing Pipeline

The pipeline must run in this order:

1. Load timetable data.
2. Apply feasibility checks for candidate pairs.
3. Build a directed connection graph (feasible edges only).
4. Generate dispatch duties (greedy baseline, MILP-compatible interface).
5. Validate generated duties.

---

## Output Contract

Each `VehicleDuty` must include:

- `duty_id`
- `vehicle_type`
- `legs` (ordered `DutyLeg` list with deadhead from previous trip)

Each `ValidationResult` must include:

- `valid: bool`
- `errors: tuple[str, ...]`

---

## Validation Standards

All duties from any dispatcher must pass
`DutyValidator.validate_vehicle_duty()` before being considered final.

Validation failures must be surfaced as:

- warning messages in `PipelineResult.warnings`
- duty IDs in `PipelineResult.invalid_duties`

Coverage integrity must also be checked:

- `PipelineResult.uncovered_trip_ids`
- `PipelineResult.duplicate_trip_ids`

---

## Layering and Dependency Boundaries

1. `src/dispatch/` must not import from `frontend/` or `bff/`.
2. `src/dispatch/` must not import from `src/constraints/` or `src/pipeline/`.
3. `src/dispatch/models.py` dataclasses remain separate from
   `src/schemas/*` entities to avoid solver coupling.
4. UI and API layers must call dispatch logic through `src.dispatch.*` (or
   thin orchestration wrappers), and must not duplicate dispatch rules.

---

## Implementation Notes

- `hhmm_to_min()` is the canonical time conversion function.
- All time comparisons must be performed in integer minutes from midnight.
- Turnaround rules apply at `trip_i.destination`.
- Deadhead direction is ordered (`from -> to`) and not assumed symmetric.
- Timetable inputs are read-only from the dispatch layer perspective.

---

## Non-Negotiable Rules

1. **No physical impossibilities**
   Infeasible chains must never appear in generated output.

2. **Timetable is read-only**
   Dispatch must not rewrite departure/arrival times or trip definitions.

3. **Frontend -> API only; logic in core**
   `frontend/` calls `/api`; `bff/` orchestrates and calls `src.dispatch.*` / `src.pipeline.*`.
   Dispatch logic must not be reimplemented in UI components or API DTO glue.

4. **`constant/` is read-only**
   Never modify files under `constant/` unless explicitly instructed.

5. **All pre-existing tests must stay green**
   Current baseline: **180 passing tests** (verified 2026-03-06).

---

## Future Expansion Targets

- Replace greedy dispatch with MILP while preserving interface.
- Add SoC-aware feasibility checks for BEV duties.
- Add multi-depot support with expanded deadhead rule tables.
- Add driver constraints (shift/break regulations).
- Support mixed-fleet relay duties if required.
