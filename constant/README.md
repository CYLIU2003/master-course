# constant/ Document Index

This directory contains research notes, simulation specifications, agent
instructions, mathematical formulations, and working thesis artifacts.

Several files overlap in scope. This index is a non-destructive guide to help
contributors understand which documents are likely canonical, which are useful
reference material, and which look like older or overlapping candidates for
future consolidation.

## How To Read This Index

- `Canonical`: preferred starting points for current understanding
- `Reference`: useful supporting documents with narrower or specialized scope
- `Archive Candidate`: likely older, overlapping, or superseded documents that
  should be read with caution

This file does not delete or rewrite historical documents. It only clarifies the
current recommended reading order.

## Canonical

### `masters_thesis_simulation_spec_v2.md`

Recommended baseline thesis simulation and optimization specification.

Use this when you need the main architecture and behavior reference for the
 thesis system.

### `agent.md`

Recommended implementation-oriented guidance aligned to the thesis simulator
direction.

Use this when working on code structure or execution guidance derived from the
core thesis specification.

### `AGENTS_ev_route_cost.md`

Recommended route-cost and mixed EV/engine bus operation instruction document.

Use this when working on route profile logic, charging, and route-level cost
modeling.

### `masters_research_brief_alignment.md`

High-level research framing document.

Use this when aligning implementation decisions with thesis purpose, scope, and
research claims.

## Reference

### `AGENTS_engine_bus_integration.md`

Specialized reference for engine bus data extraction and integration from JH25
inputs.

### `formulation.md`

Mathematical formulation reference for the mixed-fleet and PV-aware model.

Use this when checking optimization notation or model structure rather than UI
or workflow behavior.

### `thesis_master_todo.md`

Execution checklist and planning notes.

Useful for historical planning context, but not ideal as a source of technical
truth.

## Archive Candidates

These documents appear older, narrower, or overlapping with the canonical set.
They should not be treated as the first source of truth without cross-checking.

### `AGENTS.md`

Appears to overlap strongly with `AGENTS_ev_route_cost.md`.

### `masters_thesis_simulation_spec.md`

Older broad simulation specification that appears superseded by later versions.

### `masters_thesis_simulation_spec_v3.md`

Looks like an extension of the v2 line with route-editable concepts. Useful, but
not yet treated as the sole canonical spec in the current repository state.

### `agent_route_editable.md`

Overlaps with `agent.md` while adding route-editable behavior.

### `thesis_agent_instruction_max.md`

Expanded maximal instruction set with strong overlap against `agent.md` and the
main thesis spec chain.

### `ebus_prototype_model_gurobi.md`

Prototype-era model document. Useful for history, but not ideal as the current
primary reference.

### `ebus_constraints_table.md`

Constraint cheat sheet associated with the prototype model.

## Recommended Reading Order

If you are new to this directory, read in this order:

1. `masters_research_brief_alignment.md`
2. `masters_thesis_simulation_spec_v2.md`
3. `agent.md`
4. `AGENTS_ev_route_cost.md`
5. specialized reference documents as needed

## Recommended Next Cleanup Step

Future cleanup can happen safely in stages:

1. keep this index updated
2. add explicit metadata headers to overlapping docs if needed
3. merge overlapping specs only after confirming current code usage and thesis
   intent

Until then, prefer indexing over deletion.
