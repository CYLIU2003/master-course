# Baseline request/response capture plan

This directory will hold sanitized golden HTTP fixtures for Tkinter/React parity. No live scenario payload is committed during the design-only Phase 0 because the golden scenario and data-sanitization policy have not yet been selected.

## Required fixture set

| Fixture | Request | Expected evidence |
|---|---|---|
| `health` | `GET /health` | BFF readiness |
| `app-state` | `GET /api/app/data-status` | Dataset readiness/version |
| `scenario-list` | `GET /api/scenarios` | Summary contract |
| `scenario-detail` | `GET /api/scenarios/{id}` | Identity and `operator_id` preservation |
| `quick-setup-get` | `GET /api/scenarios/{id}/quick-setup` | Current editable baseline |
| `quick-setup-put` | `PUT /api/scenarios/{id}/quick-setup` | Round-trip payload; capture against a disposable duplicate only |
| `prepare-ready` | `POST /api/scenarios/{id}/simulation/prepare` | Prepared ID, scope counts and warnings |
| `prepare-invalid` | Same endpoint with controlled invalid scope | Structured failure behavior |
| `optimization-submit` | `POST /api/scenarios/{id}/run-optimization` | Job contract and submitted prepared ID |
| `job-terminal` | `GET /api/jobs/{job_id}` | State/progress/error semantics |
| `optimization-valid` | `GET /api/scenarios/{id}/optimization` | Valid eligible result |
| `optimization-infeasible` | Controlled fixture | KPI null/ineligible behavior |
| `prepared-stale` | Submit an old prepared ID | HTTP 409 with old/current IDs |

## Capture rules

- Use a named disposable duplicate for every mutation fixture.
- Record method, path, headers relevant to content negotiation, request JSON, status and response JSON.
- Remove absolute user paths, hostnames and secrets; preserve schema and hashes needed for contract checks.
- Store numeric values unchanged. Do not round fixtures.
- Record dataset version, scenario revision/hash, prepared ID, random seed and git SHA where available.
- Never edit or replace production `timetable_rows` to produce a fixture.
- Do not commit large schedule/timeseries bodies; store a hash plus a minimal representative contract fixture.

## Proposed layout

```text
baseline_requests/
  manifest.json
  health.response.json
  scenario-list.response.json
  quick-setup.request.json
  quick-setup.response.json
  prepare-ready.request.json
  prepare-ready.response.json
  optimization-submit.request.json
  optimization-submit.response.json
  job-terminal.response.json
  optimization-valid.response.json
  prepared-stale.response.json
```

The fixture capture is a separate controlled task because mutation fixtures must run only against an explicitly selected disposable scenario.

