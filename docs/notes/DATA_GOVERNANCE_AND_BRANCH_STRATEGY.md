# Data Governance And Branch Strategy

This document defines how this repository should evolve from the current shared
branch state, with the primary point of view of a bus operator that needs to
trust the data used for service planning, dispatch generation, and operational
review.

## Core Principle

For operator-facing planning, the most important question is not "what screen is
available" but:

> Which dataset is the approved source of truth for today's planning decision?

That means the repository should treat data lineage, approval state, and change
history as first-class concerns.

## Operator-Oriented Requirements

The system should make the following things clear at all times:

- what data was imported
- when it was imported
- what warnings occurred
- what was manually adjusted
- what dataset version was approved
- what dataset version was used to build trips, graphs, and duties

If these answers are unclear, the tool is difficult to trust in an actual bus
operation setting.

## Recommended Data Layers

The repository should move toward these data layers.

### 1. Raw Imports

Unmodified imported source data, grouped by resource type.

Examples:

- `BusTimetable`
- `BusstopPoleTimetable`
- route/pattern/stop imports

Rules:

- never overwrite the meaning of raw data with manual edits
- keep provenance such as operator, import time, warnings, cursor progress, and
  source type
- keep raw data available for re-normalization after logic changes

### 2. Normalized Datasets

Cleaned and mapped planning-ready tables produced from raw imports.

Examples:

- normalized routes
- normalized timetable rows
- normalized stop timetables

Rules:

- normalization rules should be reproducible
- warnings should remain attached to the dataset version
- source-to-output traceability should remain possible

### 3. Planning Datasets

Operator-reviewed and approved planning data used as the source of truth for
business planning.

Rules:

- include approval status such as `draft`, `approved`, and `archived`
- support versioning and comparison
- separate machine-imported data from operator overrides
- allow review before dispatch generation

### 4. Scenarios

Scenario entities should be treated as analysis or experiment snapshots derived
from approved planning datasets.

Rules:

- scenarios should record which planning dataset version they depend on
- scenario edits should not silently rewrite the approved source dataset
- dispatch and optimization outputs should be traceable back to the scenario and
  dataset version used

### 5. Results And Audit Logs

Operational outputs and user actions should remain traceable.

Examples:

- built trips
- connection graphs
- duties
- simulation results
- optimization results
- import history
- approval history
- duplication history

## Source Of Truth Rule

For operator use, the preferred source of truth is:

1. approved planning dataset
2. scenario snapshot derived from that dataset
3. analysis results generated from that scenario

Raw imports are evidence and inputs, but not the final business truth.

## Manual Edit Policy

Manual adjustments are useful, but they should not be mixed directly into raw
imports.

Recommended rule:

- raw import stays immutable in meaning
- manual changes are stored as overrides or approved edits on top of normalized
  data
- approvals explicitly confirm those overrides before planning use

This makes it possible to answer:

- what came from ODPT
- what was changed by the operator
- what version was finally approved

## Warning And Approval Policy

Warnings should never disappear after a pop-up or single session.

Warnings should be retained with:

- resource type
- generated/imported time
- dataset version
- warning message list
- review status

Recommended planning rule:

- import may create a draft dataset
- dispatch generation for formal review should use approved datasets only
- draft datasets may still be used for exploratory testing

## Permission Handling Policy

Vehicle and depot permission handling should stay explainable.

Current direction:

- depot-route permission is the policy boundary
- vehicle-route permission is an operational refinement
- when duplicating a vehicle into another depot, only routes allowed in the
  target depot should remain on the duplicated vehicle

This keeps cross-depot duplication aligned with depot policy and avoids hidden
permission drift.

## Branch Roles

All four working branches are currently aligned to the same code state. Going
forward, they should serve different purposes.

### `main`

Stable operator-facing baseline.

Recommended changes:

- keep daily planning flows simple and dependable
- only merge features that are understandable to non-developer operators
- prefer proven import, review, approval, and dispatch flows over experiments
- preserve backward compatibility where practical

### `feat/data-core`

Data model and lifecycle branch.

Recommended changes:

- add dataset versioning and provenance structures
- formalize raw vs normalized vs approved data layers
- add approval states and audit logs
- strengthen validation for route/stop/timetable consistency
- make permission derivation and cross-depot behavior reproducible

### `feat/app-core`

Operator workflow and UI branch.

Recommended changes:

- add import review and approval screens
- add dataset diff views and warning dashboards
- improve bulk operations for depots, routes, and vehicles
- expose permission impacts before save or duplicate actions
- improve wording toward bus operator terminology

### `master-course-parent`

Integration and acceptance branch.

Recommended changes:

- integrate `feat/data-core` and `feat/app-core`
- validate full operator workflows end to end
- resolve branch interaction issues without turning the branch into a feature
  development branch
- keep integration documentation and acceptance checklists current

## Recommended Implementation Priority

1. formalize dataset lineage and approval in `feat/data-core`
2. build review and diff workflows in `feat/app-core`
3. validate end-to-end operator usage in `master-course-parent`
4. merge stable slices into `main`

## Practical Near-Term Data Model

The following conceptual entities are recommended, even if they are initially
stored inside current scenario JSON documents.

- `raw_imports`
- `normalized_datasets`
- `planning_datasets`
- `scenarios`
- `scenario_results`
- `audit_log`

Even before introducing separate storage files or tables, the code should start
thinking in these layers.

## Documentation Rule For `docs/constant/`

The `docs/constant/` directory contains valuable but overlapping research and agent
documents. To reduce confusion:

- treat `docs/constant/README.md` as the index for current document status
- avoid deleting historical specs without explicit review
- identify canonical vs reference vs archive-candidate documents clearly

See `docs/constant/README.md` for the current non-destructive consolidation view.
