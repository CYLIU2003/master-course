# Migration acceptance criteria

## Gate 0: Tkinter protection

- [ ] `run_app.py` still starts FastAPI and Tkinter.
- [ ] Scenario list/load, Quick Setup save, Prepare, optimization submission, job polling and result retrieval pass the Tkinter smoke procedure.
- [ ] No React change deletes, renames or weakens a Tkinter-consumed endpoint or field.
- [ ] Any BFF contract extension is backward compatible or carries a tested compatibility adapter.
- [ ] Tkinter remains documented as the fallback until Gate 6 sign-off.

Failure of Gate 0 blocks every React release regardless of React test results.

## Gate 1: Contract readiness

- [ ] Public response DTOs have explicit Pydantic response models and schema versions.
- [ ] Canonical and legacy internal results map to the same frontend result DTO.
- [ ] Unit-bearing fields and null/zero behavior are documented and tested.
- [ ] Stable error codes cover validation, stale Prepare, in-progress execution and unavailable results.
- [ ] OpenAPI-generated TypeScript compiles with no hand-written shadow types for public DTOs.

## Gate 2: Read-only MVP

- [ ] Health/readiness and scenario list render without loading large payloads.
- [ ] A scenario can be opened without activation/mutation.
- [ ] Latest valid, feasible, time-limit, infeasible and missing result states each render correctly.
- [ ] Assigned/unserved trips, used vehicles, total cost and PV utilization equal backend values before formatting.
- [ ] Energy charts preserve kW/kWh and null/zero distinctions.
- [ ] Artifact/audit evidence is reachable without guessed paths.
- [ ] Two compatible weather scenarios can be compared with controls and provenance visible.

## Gate 3: Execution workflow

- [ ] Quick Setup round-trip preserves every known field and unknown compatibility fields where required.
- [ ] Prepare displays prepared ID, scope counts, warnings and effective profile.
- [ ] Editing a dependency visibly invalidates the current prepared input.
- [ ] A stale ID receives the backend 409 and enters the `stale` state.
- [ ] One click creates at most one job.
- [ ] Reload resumes polling of a known active job.
- [ ] Pending/running/completed/failed and restart-orphan failure are tested.
- [ ] The UI has no Cancel affordance until cancellation exists in FastAPI.

## Gate 4: Editing parity

- [ ] Scenario CRUD/duplicate/activate/delete behavior matches Tkinter.
- [ ] Vehicle and template create/update/duplicate/bulk/delete match backend contracts.
- [ ] Depot, charger, PV/BESS, tariff/CO2, SOC/fuel, objective and solver settings round-trip without drift.
- [ ] `operator_id` remains present.
- [ ] Unrelated saves do not rewrite `timetable_rows`.
- [ ] Zero/missing distance is not silently accepted.
- [ ] Timetable import/replacement has preview, row count and explicit confirmation.

## Gate 5: Research validity and performance

- [ ] Dispatch feasibility is displayed from backend results; React has no independent feasibility formula.
- [ ] Invalid/infeasible KPI fields render unavailable rather than zero.
- [ ] Exact/optimal wording is proven by returned status and metadata.
- [ ] Fallback, repair and reduced-network conditions are visible.
- [ ] Cost component sum/reconciliation matches backend output.
- [ ] Initial shell does not request graph, full timetable, full schedules or timeseries.
- [ ] Large tables remain interactive using pagination/virtualization.
- [ ] Accessibility keyboard and screen-reader smoke checks pass.

## Gate 6: Primary-UI sign-off

- [ ] Playwright E2E covers the critical path: scenario -> save -> Prepare -> optimization -> poll -> result -> evidence.
- [ ] Contract fixture tests cover valid, time-limit, infeasible, stale and failed cases.
- [ ] Tkinter and React submit materially identical payloads for the agreed golden scenario.
- [ ] The same prepared input reaches the same backend execution path.
- [ ] Reviewer sign-off records remaining limitations and confirms no unsupported KPI claims.
- [ ] README and development notes identify React as primary only after this gate passes.

Tkinter may remain installed and usable after Gate 6. Removal requires a separate decision and is not part of this migration.

## Gate 7: Tauri packaging

- [ ] Browser-hosted React + FastAPI still passes Gates 0–6.
- [ ] Tauri launches a version-compatible FastAPI/Python sidecar on a non-conflicting port.
- [ ] Sidecar readiness, crash and shutdown behavior are tested on Windows.
- [ ] Output/scenario paths resolve to explicit writable directories.
- [ ] Tauri uses the same public DTOs and contract tests as browser React.
- [ ] Closing Tauri handles active jobs according to a documented policy; it does not silently kill a research run.

## Required test matrix

| Layer | Tests |
|---|---|
| BFF | Pydantic contract, adapters, errors, job persistence and endpoint fixtures |
| React unit | Schemas, formatters, state reducers and validity gates |
| React component | Forms, banners, tables, null/zero and accessibility |
| E2E | Critical read/run/edit paths against controlled FastAPI fixtures |
| Cross-UI | Tkinter and React payload/result parity for golden scenarios |
| Research regression | Existing Python dispatch, cost, SOC, energy and solver-path tests |

