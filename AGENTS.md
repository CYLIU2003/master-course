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
   Current baseline: **245 passing tests** (verified 2026-03-09).

---

## Future Expansion Targets

- Replace greedy dispatch with MILP while preserving interface.
- Add SoC-aware feasibility checks for BEV duties.
- Add multi-depot support with expanded deadhead rule tables.
- Add driver constraints (shift/break regulations).
- Support mixed-fleet relay duties if required.

---

## Optimization Engine Design Rules

### Purpose

The optimization backend must support:

- timetable-to-connection-graph conversion
- vehicle assignment
- charging / discharging scheduling
- depot / charger constraints
- PV-assisted energy use
- rolling-horizon re-optimization

Supported solver modes:

- `milp`
- `alns`
- `hybrid`

`hybrid` is the default research mode.

### Core Design Policy

1. Separate domain model from optimization model
   Raw GTFS / odpt / CSV / manual inputs must be normalized before solver logic.

2. Shared canonical problem
   `milp`, `alns`, and `hybrid` must consume the same canonical problem object.

3. Hybrid-first principle
   Use MILP for baseline and exact subproblems, ALNS for exploration, and Hybrid for production-scale experiments.

4. Research-grade extensibility
   Leave hooks for multi-depot, mixed fleet, charger planning, fleet composition, and column generation.

### Required Optimization Layers

- `src/optimization/common/`
- `src/optimization/milp/`
- `src/optimization/alns/`
- `src/optimization/hybrid/`
- `src/optimization/rolling/`

### MILP Rules

- Solver backend must be abstracted.
- Business logic must not hard-code solver-specific APIs.
- Warm start, time limit, and mip gap must be configurable.
- Infeasibility diagnostics must be surfaced when available.

### ALNS Rules

ALNS state must expose:

- `objective()`
- `clone()`
- `is_feasible()`

ALNS controls must be separate components:

- destroy operators
- repair operators
- acceptance criterion
- operator selection
- stopping criterion

### Hybrid Rules

Hybrid mode must support:

- MILP-based initial solution
- ALNS outer loop
- partial MILP repair
- incumbent polishing hooks

### UCDavis-Inspired Extension Points

Keep placeholders for:

- fleet composition optimization
- charger location / infrastructure search
- `ColumnPool`
- `PricingProblem`
- infrastructure neighborhoods
- GTFS preprocessing hooks beyond dispatch preprocessing

These are extension points only; they must not bypass timetable-first dispatch feasibility.

### Logging and Reproducibility

Every optimization run must save:

- scenario snapshot
- normalized problem summary
- solver config
- random seed
- best objective
- cost breakdown
- feasibility flags
- operator statistics
- runtime
- incumbent history

---

## Route Family / Variant Handling Rules

### Purpose

ODPT and GTFS may provide multiple raw route/pattern records that operationally
belong to the same line family. Examples:

- outbound / inbound pair of the same line code
- short-turn services
- depot-in / depot-out services
- branch variants

The system must preserve raw imported records, while also exposing a derived
"route family" layer for UI grouping and timetable-to-trip generation support.

### Core Policy

1. **Raw route/pattern records are immutable source facts**
   Imported ODPT / GTFS route or pattern records must not be merged
   destructively in storage. `odptPatternId`, `odptBusrouteId`, GTFS
   `route_id`, and any imported pattern identifiers remain preserved.

2. **Route family is a derived layer**
   A `routeFamilyCode` must be derived primarily from `routeCode` when available.
   If `routeCode` is missing, derive from normalized line label / route name.
   Full-width digits and symbols should be normalized via NFKC.
   Example: `園０１ (田園調布駅 -> 瀬田営業所)` → `routeFamilyCode = "園01"`

3. **Outbound / inbound are same family, not same record**
   Reverse-direction services with the same line code must be grouped under the
   same route family. However, outbound and inbound remain separate raw variants
   and separate generated trips.

4. **Short-turn / depot / branch services**
   Services that share the same line code but differ by terminal pair or coverage
   must still belong to the same route family in the UI. They must remain
   distinguishable by `routeVariantType` in downstream processing.

5. **Dispatch remains trip-based**
   Dispatch / optimization must operate on trips, not on route families directly.
   Route family is for grouping, filtering, reporting, and operator interpretation.
   Physical feasibility must always be evaluated on trip-level
   origin/destination/time continuity.

### Required Derived Fields

Every route-like entity exposed by BFF to frontend should support these optional
derived fields:

- `routeFamilyId`
- `routeFamilyCode`
- `routeFamilyLabel`
- `routeVariantId`
- `routeVariantType`
- `canonicalDirection`
- `isPrimaryVariant`
- `familySortOrder`
- `classificationConfidence`
- `classificationReasons`

Recommended `routeVariantType` values:
`main`, `main_outbound`, `main_inbound`, `short_turn`, `branch`,
`depot_out`, `depot_in`, `unknown`

Recommended `canonicalDirection` values:
`outbound`, `inbound`, `circular`, `unknown`

### Classification Rules

1. **Main pair detection first** — the route with the highest (tripCount, stopCount,
   distance) is the primary candidate. If a reverse terminal pair exists, it becomes
   the main inbound.

2. **depot_out / depot_in is a SCORED heuristic, NOT keyword-only**
   - `営業所/車庫` keywords alone do NOT classify a route as depot.
   - A route is classified as depot only when:
     - It is NOT already classified as main/reverse/short-turn/branch
     - AND its depot signal score >= threshold (composite of keyword + low trip count
       + shorter-than-main + subset of main stop sequence)
   - Routes where the main service naturally terminates at a depot-like stop
     remain classified as main_outbound/main_inbound.

3. **Confidence and reasons** — every classification carries
   `classificationConfidence` (0-1) and `classificationReasons` (list of strings).
   Low-confidence classifications should be shown as `unknown` in UI.

### Layer Responsibility

- **Backend raw store** — preserves imported route/pattern/timetable facts
- **BFF** — computes route family / variant DTO fields
- **Frontend** — displays grouped family list and expandable raw variants
- **Core dispatch / optimization** — consumes trips generated from raw timetable facts;
  may reference family metadata but must not replace trip-level feasibility with
  family-level assumptions

### Non-Negotiable Rules

1. Do not overwrite raw ODPT/GTFS identifiers with family IDs.
2. Do not merge opposite directions into one trip definition.
3. Do not treat all same-code services as identical operations.
4. UI grouping must not erase short-turn / depot / branch distinctions.
5. Timetable linkage counts must be computed against raw routes/variants first,
   then aggregated to family view.

### Timetable Linking Requirement

Route family grouping is **not** a substitute for timetable linking.

The following must be handled explicitly:

- raw timetable rows
- stop timetable rows
- trip generation from timetable rows
- route-to-trip linking
- stop-to-stop-timetable linking
- family-level aggregation of link status

If `timetable_rows = 0`, `stop_timetables = 0`, or `Timetable linked = 0`,
the implementation must first verify ingestion / storage / linker paths before
assuming a UI-only issue.

---

## GTFS Pipeline Architecture (tokyubus-gtfs)

### Purpose

`src/tokyubus_gtfs/` implements a 4-layer data pipeline that transforms raw
ODPT JSON into a canonical transit model, standard GTFS feed, and a research
feature store.  This replaces direct ODPT-to-scenario ingestion for Tokyu Bus
data with a reproducible, auditable pipeline.

### 4-Layer Architecture

```text
Layer A: Raw Archive     data/tokyubus/raw/{snapshot_id}/
    │   Immutable ODPT JSON snapshots with SHA-256 manifests
    ▼
Layer B: Canonical       data/tokyubus/canonical/{snapshot_id}/
    │   Normalised JSONL (stops, routes, route_stops, trips,
    │   stop_times, services, stop_timetables)
    ▼
Layer C: GTFS Export     GTFS/TokyuBus-GTFS/
    │   Standard GTFS feed + sidecar JSON for ODPT metadata
    ▼
Layer D: Features        data/tokyubus/features/{snapshot_id}/
        Research feature store (trip_chains, energy_estimates,
        depot_candidates, stop_distances, charging_windows,
        deadhead_candidates)
```

### Pipeline Execution Order

1. Archive raw ODPT snapshot (Layer A)
2. Normalise to canonical model (Layer B)
3. Export GTFS feed + sidecar files (Layer C)
4. Build research features (Layer D)

### Data Contracts

- **Raw data is immutable**: Once archived, snapshot files are never modified.
- **Original ODPT IDs preserved**: `odpt_id`, `odpt_pattern_id`, `odpt_raw`
  fields retain source provenance.
- **Both raw and normalised time values**: Original ODPT time strings AND
  `_seconds` (seconds from midnight) are stored side by side.
- **Coordinates carry provenance**: `coord_source_type` and `coord_confidence`
  on every stop.
- **Sidecar files for GTFS gaps**: Route patterns, variant metadata, ODPT
  provenance go in sidecar JSON — not flattened into GTFS core.

### File Layout

| Layer | Path | Contents |
|-------|------|----------|
| Pipeline code | `src/tokyubus_gtfs/` | Python package |
| JSON schemas | `src/tokyubus_gtfs/schemas/` | Canonical, sidecar, feature schemas |
| Raw archive | `data/tokyubus/raw/` | Immutable snapshots |
| Canonical | `data/tokyubus/canonical/` | JSONL tables |
| GTFS feed | `GTFS/TokyuBus-GTFS/` | Standard GTFS + sidecars |
| Features | `data/tokyubus/features/` | Research feature tables |

### Dependency Boundaries

1. `src/tokyubus_gtfs/` must not import from `frontend/` or `bff/`.
2. `src/tokyubus_gtfs/` may import from `src/dispatch/` constants only when
   needed for feature builders (e.g. deadhead rules).
3. `src/tokyubus_gtfs/models.py` is independent of `src/schemas/*`.
4. BFF and `catalog_update_app.py` call the pipeline through
   `src.tokyubus_gtfs.pipeline.run_pipeline()`.

### CLI Entry Points

```bash
# Full pipeline
python -m src.tokyubus_gtfs run --source-dir ./data/raw-odpt

# Individual layers
python -m src.tokyubus_gtfs archive --source-dir ./data/raw-odpt
python -m src.tokyubus_gtfs canonical --snapshot <id>
python -m src.tokyubus_gtfs gtfs --snapshot <id>
python -m src.tokyubus_gtfs features --snapshot <id>

# Via catalog_update_app.py
python catalog_update_app.py refresh gtfs-pipeline --source-dir ./data/raw-odpt
```

### Non-Negotiable Rules

1. **Raw snapshots are immutable** — never modify archived JSON.
2. **Never discard ODPT identifiers** — `odpt_id`, `odpt_pattern_id`,
   `odpt_raw_*` fields must survive normalisation.
3. **Do not flatten arrays into comma-joined strings** — use JSON lists.
4. **Vehicle type metadata lives in features, not GTFS** — BEV/ICE, charging
   constraints, depot info are Layer D concerns.
5. **Timetable-first principle still applies** — dispatch and optimisation
   consume trips from canonical/feature tables, never raw ODPT directly.
6. **`odpt_only` branch preserves legacy** — the ODPT-direct implementation
   is preserved on the `odpt_only` branch as a disabled fallback.

