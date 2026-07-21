# Requirements traceability

This matrix prevents a screen from being called complete without a corresponding contract and acceptance test.

| Requirement group | Primary screen/spec | BFF dependency | Acceptance gate |
|---|---|---|---|
| FR-APP-01 | Shell and startup in `screen_transition.md` | `/health`, app-state endpoints | Gate 2 |
| FR-SCN-01–05 | Scenario list/overview | Scenario CRUD/activate endpoints and typed summaries | Gates 2, 4 |
| FR-RUN-01–04 | Quick Setup and Run workspace | Quick Setup, `/simulation/prepare`, stale 409 | Gate 3 |
| FR-RUN-05–08 | Run workspace/job panel | Run endpoints, `/jobs/{job_id}` | Gate 3 |
| FR-RES-01–07 | Result and evidence pages | Public result DTO and artifact manifest | Gates 2, 5 |
| FR-CMP-01–03 | Comparison workspace | Validated comparison/compatibility contract | Gates 2, 5 |
| FR-EDT-01–05 | Inputs and asset editors | Scenario/master/PV/timetable mutations | Gate 4 |
| NFR-COR-01 | API client boundary | Typed Pydantic responses/OpenAPI | Gate 1 |
| NFR-REP-01 | Identity strip/evidence | Provenance and artifact DTOs | Gates 2, 5 |
| NFR-PERF-01–02 | Shell, tables and charts | Summary/paginated endpoints | Gates 2, 5 |
| NFR-REL-01 | Persistent job panel | Disk-backed job status; future job list | Gate 3 |
| NFR-A11Y-01 | All pages/components | Semantic DTO labels/errors | Gate 5 |
| NFR-I18N-01 | UI terminology | Error/message mapping | Gates 2–5 |
| NFR-SEC-01 | Browser runtime and Tauri shell | Origin, sidecar and artifact validation | Gate 7 |
| NFR-OBS-01 | Error/job/evidence panels | Stable errors, IDs and stages | Gates 1, 3 |
| NFR-COMP-01 | Cross-UI suite | Backward-compatible BFF | Gates 0, 6 |

## Definition of done for one feature slice

1. Requirement ID is referenced in the implementation issue/PR.
2. Public DTO and error states are fixed by contract tests.
3. The UI covers loading, empty, success, invalid and failure states relevant to the slice.
4. Playwright or component coverage proves the user-visible behavior.
5. The Tkinter counterpart still passes or the feature is documented as React-only with no shared-contract regression.
6. README/development notes are updated when behavior or contract changes.

