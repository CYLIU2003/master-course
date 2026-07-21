# API contract inventory and normalization plan

## 1. Verified current contract

- Application: `bff.main:app`.
- Current base path: `/api`; health is `/health`.
- OpenAPI: 82 paths, 108 operations, 53 component schemas as of 2026-07-19.
- Request bodies use Pydantic models in important mutation paths.
- Success responses are overwhelmingly declared as `Dict[str, Any]`. The generated OpenAPI describes 100 JSON success responses only as generic objects, so generated TypeScript cannot yet provide meaningful response safety.
- Error bodies are not fully uniform: some endpoints return FastAPI string `detail`, others return structured `detail` containing `error` and `message`.

## 2. Boundary decision

Phase 1 introduces explicit frontend response DTOs at the BFF boundary. Core canonical and legacy payloads remain internal. The adapter must preserve raw evidence/provenance while exposing one stable public representation.

Do not rename the current base path during the initial React scaffold. A later `/api/v1` migration requires a compatibility alias and a separately approved deprecation plan because Tkinter currently uses `/api`.

## 3. Required public DTOs

| DTO | Minimum fields | Rules |
|---|---|---|
| `ApiEnvelope<T>` | `schemaVersion`, `data`, `warnings`, `provenance` | New typed endpoints only; do not wrap legacy endpoints silently |
| `ApiError` | `code`, `message`, `fieldErrors`, `context`, `requestId` | Stable machine code plus Japanese-displayable message |
| `ScenarioSummary` | `id`, `name`, `operatorId`, `datasetId`, `mode`, `isActive`, `updatedAt` | `operatorId` required; no invented default |
| `ScenarioDetail` | Summary plus revision/config references | Separate summary from large timetable/artifacts |
| `PreparedInputSummary` | `preparedInputId`, `isReady`, counts, scope, warnings, profile, provenance | Preserve zero vs missing counts |
| `OptimizationJob` | `jobId`, `kind`, `status`, `progressPercent`, `stage`, `message`, `error`, `timestamps` | Public enum independent of raw metadata text |
| `OptimizationResult` | result status, validity, KPI eligibility, solver evidence, KPI summary, artifact manifest | No direct exposure of canonical/legacy split |
| `SimulationResult` | status, validity, summaries, audits, artifact manifest | Source (`duties` or optimization result) explicit |
| `ArtifactManifest` | artifact ID/type/media type/path/size/hash/schema version | Frontend never guesses paths |
| `VehicleSchedule` | vehicle/trip/depot/times/distance/energy/SOC with units | Preserve `operatorId`, route family/variant and direction |
| `EnergyBalance` | timestamp/depot and kW/kWh flow fields | Power and energy cannot share ambiguous names |
| `ScenarioComparison` | run identities, compatibility checks, deltas and limitations | Invalid runs excluded from KPI ranking |

## 4. Field conventions

| Concern | Convention |
|---|---|
| Naming | New public DTOs use `camelCase`; adapters own legacy snake/camel conversion |
| Versioning | Top-level `schemaVersion` using a documented major/minor string |
| Money | Amount fields end in `Jpy`; rates include denominator, e.g. `JpyPerKwh` |
| Energy | `Kwh`; power `Kw`; demand price states monthly or horizon basis |
| SOC | Field name includes `Ratio`, `Percent`, or `Kwh`; no plain `soc` in public DTOs |
| Time | ISO 8601 timestamps with offset; service-local HH:mm fields are explicitly named |
| Missing | JSON `null` means known-unavailable/not-eligible; omission means not in that schema version; zero is numeric zero |
| IDs | Opaque strings; never parse semantic meaning in React |
| Status | Closed string enums with an `unknown` UI fallback for forward compatibility |
| Numbers | Non-finite Python values are converted to `null` and accompanied by validity/error context |

## 5. Job contract

### Current raw states

`pending -> running -> completed | failed`

### Target UI state model

| UI state | Source |
|---|---|
| `notPrepared` | No current prepared input |
| `preparing` | Prepare mutation pending |
| `ready` | Prepare response `ready=true` and nonempty scope |
| `queued` | Job `status=pending` |
| `running` | Job `status=running` |
| `succeeded` | Job `status=completed` and result fetch succeeds |
| `failed` | Job `status=failed` or terminal result retrieval fails |
| `stale` | Backend 409 prepared-input mismatch |
| `cancelled` | Reserved; must not be emitted until backend cancellation exists |

Polling requirements:

- Persist the current job ID per scenario and job kind in browser storage.
- Poll 1 second initially, then use a bounded 2–5 second interval for long jobs.
- Stop only at a terminal state or explicit navigation cleanup; resume after reload.
- Display `metadata.stage` as diagnostic detail, not as the authoritative status enum.
- Treat a restarted/orphaned job as failed and show the backend reason.

## 6. Error handling

Phase 1 must normalize at least:

| HTTP | UI behavior |
|---:|---|
| 400/422 | Keep form data, focus summary, show field/context details |
| 404 | Distinguish missing scenario/result/job; offer safe navigation |
| 409 | Show conflict details; stale Prepare requires re-Prepare |
| 503 | Execution already in progress; do not submit a duplicate |
| 500 | Show request/job/scenario identity and copyable diagnostic detail |

React must not parse English message fragments to decide behavior. It uses stable error codes after the adapter is introduced.

## 7. Query and payload policy

- Use summary endpoints for list/navigation surfaces.
- Defer graph, timetable rows, schedules and timeseries until their tabs become active.
- Respect existing pagination on timetable, stop timetable, trips, graph arcs, duties and blocks.
- Add pagination/summary endpoints before loading unbounded vehicles, stops, routes or permissions at full-network scale.
- Do not place optimization results, graphs or timetable rows in a global client store.
- TanStack Query owns server state; form state owns only deliberate edits.

## 8. Contract tests required before client generation

1. OpenAPI snapshot test for all public DTO endpoints.
2. Pydantic serialization tests for null/zero/non-finite boundaries.
3. Canonical and legacy internal-result fixtures mapping to the same public DTO.
4. Stale prepared input 409 fixture.
5. Invalid/infeasible result fixture proving KPI fields are null and ineligible.
6. Job restart/orphan fixture.
7. `operator_id`, trip identity, route variant/direction and distance preservation fixtures.

## 9. Endpoint gaps blocking complete UX

- No backend job cancellation.
- No list-jobs endpoint for recovery across devices/storage loss.
- No dedicated artifact-manifest browsing/download contract verified.
- No single scenario-comparison endpoint verified.
- No versioned public result DTO.

These gaps are recorded in `issues_and_decisions.md`; the React UI must not simulate them locally.

