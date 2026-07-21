# React + FastAPI frontend migration specification

Status: Phase 0 design baseline  
Last updated: 2026-07-19

## Purpose

This directory defines the safe migration from the current Tkinter + FastAPI application to React + FastAPI, followed by React + FastAPI + Tauri.

The current Tkinter application is not deprecated. It remains the operational fallback and regression oracle until every Phase A acceptance gate passes. Phase 0 changes documentation only; it does not modify `run_app.py`, `tools/scenario_backup_tk.py`, the BFF, or the optimization core.

## Authoritative reading order

1. [Product requirements](product_requirements.md)
2. [Current feature inventory](current_feature_inventory.md)
3. [API contract inventory](api_contract_inventory.md)
4. [Implementation architecture](implementation_architecture.md)
5. [Screen transitions](screen_transition.md)
6. [UI/UX specification](ui_ux_spec.md)
7. [Migration acceptance criteria](migration_acceptance_criteria.md)
8. [Requirements traceability](requirements_traceability.md)
9. [Issues and decisions](issues_and_decisions.md)
10. [Baseline request capture](baseline_requests/README.md)

`DESIGN.md` remains the repository-wide source for colors, typography, spacing, and evidence-first presentation rules. This directory adds React-specific interaction and information architecture requirements without replacing that file.

## Delivery phases

| Phase | Deliverable | Tkinter status |
|---|---|---|
| 0 | Verified inventory, contracts, flows, UX and acceptance criteria | Unchanged and primary |
| 1 | Typed frontend DTO adapter and stable errors/job contract | Unchanged and primary |
| 2 | React foundation and generated API client | Unchanged and primary |
| 3 | Read-only results MVP | Unchanged and primary |
| 4 | Prepare, optimization, simulation and job monitoring | Retained as fallback |
| 5 | Scenario and input editing | Retained as fallback |
| 6 | Automated parity and research-validity gate | Retained until formal sign-off |
| 7 | Tauri packaging with FastAPI/Python sidecar | Retained as recoverable tool |

## Non-negotiable boundaries

- React calls FastAPI only. It must never import or directly invoke Python optimization code.
- React displays backend-authoritative cost, energy, SOC and feasibility values. It does not recalculate research KPIs.
- The dispatch condition `arrival + turnaround + deadhead <= next departure` remains owned by `src/dispatch/`.
- `timetable_rows` and `operator_id` are never silently dropped, rebuilt, or invented by the frontend.
- Zero and missing route/trip distance remain distinguishable and must block execution where the backend contract requires it.
- Solver exactness, fallback use and result validity are displayed from returned metadata, never inferred from a mode label.
- Tauri work begins only after the browser-hosted React + FastAPI acceptance gates pass.
