# Phase 0 issues and decisions

## Issues raised during design

| ID | Priority | Issue | Resolution/status |
|---|---|---|---|
| FE-001 | P0 | A React rewrite could accidentally displace the current Tkinter tool | Resolved by Gate 0: additive migration, Tkinter remains fallback and regression oracle |
| FE-002 | P1 | Proposed `/api/v1` differs from reachable current prefix `/api` | Resolved for scaffold: use `/api`; versioning requires compatibility plan |
| FE-003 | P1 | Current worktree has no `frontend/`, while old docs cite React files | Resolved in inventory: historical references are not treated as reachable behavior |
| FE-004 | P1 | OpenAPI response schemas are generic objects, making client generation unsafe | Open: Phase 1 typed response DTOs are a hard prerequisite |
| FE-005 | P1 | Internal canonical/legacy result shapes can leak into UI | Open: BFF result adapter and public DTO required |
| FE-006 | P1 | Proposed cancelled state has no backend state or endpoint | Resolved for Phase A: reserve state but show no Cancel action |
| FE-007 | P1 | No verified comparison endpoint | Open: define server-side comparison/compatibility contract before comparison MVP sign-off |
| FE-008 | P1 | No verified artifact-manifest browsing endpoint | Open: expose manifest rather than guessing output paths |
| FE-009 | P2 | No job-list endpoint; local storage is the only reload recovery index | Open: MVP persists known IDs; backend listing is recommended before Tauri |
| FE-010 | P1 | Several list endpoints are unbounded and may be large | Open: add summary/pagination before full-network editor migration |
| FE-011 | P1 | Error shapes are inconsistent | Open: normalized `ApiError` contract required |
| FE-012 | P1 | Scenario selection and backend activation could be conflated | Resolved in UX: selection is read-only; activation is explicit |
| FE-013 | P0 | Invalid results may be misread as zero-cost valid outcomes | Resolved in requirements: validity banner and KPI-null gate are mandatory |
| FE-014 | P1 | Tauri shutdown could terminate an active solver | Deferred with explicit Gate 7 policy requirement |

## Architecture decisions

### ADR-FE-001: Delivery order

Decision: React + FastAPI first; Tauri only after web acceptance.  
Reason: separates UI/contract risk from packaging/process-lifecycle risk and preserves experiment comparability.

### ADR-FE-002: Tkinter coexistence

Decision: keep Tkinter working throughout migration and after initial React sign-off.  
Reason: it is the current proven operational path and provides a cross-UI regression reference.

### ADR-FE-003: API-only React boundary

Decision: React uses HTTP through FastAPI for all operations.  
Reason: one observable contract is required for browser and Tauri deployments. `MC_DIRECT_CALL` remains a Tkinter compatibility optimization, not a React feature.

### ADR-FE-004: Backend-authoritative research values

Decision: React formats but does not derive cost, SOC, energy balance, feasibility or eligibility.  
Reason: duplicating domain math would permit silent divergence and invalidate comparisons.

### ADR-FE-005: Typed adapter before generated client

Decision: do not treat generic OpenAPI object responses as a stable client contract. Add explicit BFF response models first.  
Reason: code generation without response semantics creates false type safety.

### ADR-FE-006: State ownership

Decision: TanStack Query owns server state, React Hook Form owns drafts, URL owns navigation context.  
Reason: limits synchronization loops and accidental mutation of large common assets.

### ADR-FE-007: Results-first migration

Decision: implement read-only result/evidence pages before full input editors.  
Reason: validates the hardest result contract without risking scenario mutations and provides immediate research-review value.

## Decisions still requiring explicit approval before implementation

1. Whether public DTOs extend existing endpoints or use parallel versioned endpoints.
2. Whether comparison is computed by a new BFF endpoint or assembled from an existing validated comparison artifact.
3. Whether artifact access is local-path reveal, HTTP download, or both in browser/Tauri modes.
4. Whether multiple concurrent simulation jobs are a supported product requirement; optimization currently enforces a single in-process future.
5. The sidecar shutdown policy when a Tauri window closes during a running job.

