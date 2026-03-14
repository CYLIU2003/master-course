# API Inventory - Phase 5

## Mounted endpoints

| Method | Path | Summary/Detail | Paginated | Est. payload risk |
|--------|------|----------------|-----------|-------------------|
| GET | /health | summary | N/A | low |
| GET | /api/app/datasets | summary | N/A | low |
| GET | /api/app/data-status | summary | N/A | low |
| GET | /api/app-state | summary | N/A | low |
| GET | /api/scenarios | list summary | no | low |
| GET | /api/scenarios/default | summary | no | low |
| POST | /api/scenarios | create | N/A | low |
| POST | /api/scenarios/{scenario_id}/duplicate | create | N/A | low |
| GET | /api/scenarios/{scenario_id} | detail | no | medium |
| PUT | /api/scenarios/{scenario_id} | detail | no | medium |
| DELETE | /api/scenarios/{scenario_id} | mutation | N/A | low |
| POST | /api/scenarios/{scenario_id}/activate | mutation | N/A | low |
| GET | /api/app/context | summary | no | low |
| GET | /api/scenarios/{scenario_id}/dispatch-scope | detail | no | low |
| PUT | /api/scenarios/{scenario_id}/dispatch-scope | detail | no | low |
| GET | /api/planning/depot-scope/{depot_id}/trips | detail | no | high |
| GET | /api/scenarios/{scenario_id}/timetable | detail list | yes (`limit`/`offset`) | medium |
| GET | /api/scenarios/{scenario_id}/timetable/summary | summary | no | low |
| PUT | /api/scenarios/{scenario_id}/timetable | detail mutation | no | medium |
| POST | /api/scenarios/{scenario_id}/timetable/import-csv | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/timetable/export-csv | export | no | medium |
| GET | /api/scenarios/{scenario_id}/stop-timetables | detail list | yes (`limit`/`offset`) | medium |
| GET | /api/scenarios/{scenario_id}/stop-timetables/summary | summary | no | low |
| GET | /api/scenarios/{scenario_id}/deadhead-rules | detail list | no | medium |
| GET | /api/scenarios/{scenario_id}/turnaround-rules | detail list | no | medium |
| GET | /api/scenarios/{scenario_id}/calendar | detail list | no | low |
| PUT | /api/scenarios/{scenario_id}/calendar | mutation | N/A | low |
| POST | /api/scenarios/{scenario_id}/calendar/{service_id} | mutation | N/A | low |
| DELETE | /api/scenarios/{scenario_id}/calendar/{service_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/calendar-dates | detail list | no | low |
| PUT | /api/scenarios/{scenario_id}/calendar-dates | mutation | N/A | low |
| POST | /api/scenarios/{scenario_id}/calendar-dates/{date} | mutation | N/A | low |
| DELETE | /api/scenarios/{scenario_id}/calendar-dates/{date} | mutation | N/A | low |
| POST | /api/scenarios/{scenario_id}/auto-assign-depots | detail compute | no | medium |
| GET | /api/scenarios/{scenario_id}/depots | summary list | no | low |
| POST | /api/scenarios/{scenario_id}/depots | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/depots/{depot_id} | detail | no | low |
| PUT | /api/scenarios/{scenario_id}/depots/{depot_id} | mutation | N/A | low |
| DELETE | /api/scenarios/{scenario_id}/depots/{depot_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/vehicles | detail list | no | medium |
| POST | /api/scenarios/{scenario_id}/vehicles | mutation | N/A | low |
| POST | /api/scenarios/{scenario_id}/vehicles/bulk | mutation | N/A | medium |
| GET | /api/scenarios/{scenario_id}/vehicles/{vehicle_id} | detail | no | low |
| PUT | /api/scenarios/{scenario_id}/vehicles/{vehicle_id} | mutation | N/A | low |
| DELETE | /api/scenarios/{scenario_id}/vehicles/{vehicle_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/vehicle-templates | detail list | no | medium |
| POST | /api/scenarios/{scenario_id}/vehicle-templates | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/vehicle-templates/{template_id} | detail | no | low |
| PUT | /api/scenarios/{scenario_id}/vehicle-templates/{template_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/stops | detail list | no | medium |
| GET | /api/scenarios/{scenario_id}/routes | summary list | no | medium |
| POST | /api/scenarios/{scenario_id}/routes | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/routes/{route_id} | detail | no | medium |
| GET | /api/scenarios/{scenario_id}/route-families | summary list | no | medium |
| GET | /api/scenarios/{scenario_id}/route-families/{route_family_id} | detail | no | medium |
| PUT | /api/scenarios/{scenario_id}/routes/{route_id} | mutation | N/A | low |
| DELETE | /api/scenarios/{scenario_id}/routes/{route_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/explorer/overview | summary | no | low |
| GET | /api/scenarios/{scenario_id}/explorer/depot-assignments | detail list | no | medium |
| PATCH | /api/scenarios/{scenario_id}/explorer/depot-assignments/{route_id} | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/depot-route-permissions | detail list | no | medium |
| GET | /api/scenarios/{scenario_id}/depot-route-family-permissions | detail list | no | medium |
| PUT | /api/scenarios/{scenario_id}/depot-route-permissions | mutation | N/A | low |
| PUT | /api/scenarios/{scenario_id}/depot-route-family-permissions | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/vehicle-route-permissions | detail list | no | medium |
| GET | /api/scenarios/{scenario_id}/vehicle-route-family-permissions | detail list | no | medium |
| PUT | /api/scenarios/{scenario_id}/vehicle-route-permissions | mutation | N/A | low |
| PUT | /api/scenarios/{scenario_id}/vehicle-route-family-permissions | mutation | N/A | low |
| GET | /api/scenarios/{scenario_id}/trips | detail list | yes (`limit`/`offset`) | medium |
| GET | /api/scenarios/{scenario_id}/trips/summary | summary | no | low |
| POST | /api/scenarios/{scenario_id}/subset-export | export | no | medium |
| POST | /api/scenarios/{scenario_id}/build-trips | build | N/A | medium |
| GET | /api/scenarios/{scenario_id}/graph | detail | no | high |
| GET | /api/scenarios/{scenario_id}/graph/summary | summary | no | low |
| GET | /api/scenarios/{scenario_id}/graph/arcs | detail list | yes (`limit`/`offset`) | high |
| POST | /api/scenarios/{scenario_id}/build-graph | build | N/A | medium |
| GET | /api/scenarios/{scenario_id}/duties | detail list | yes (`limit`/`offset`) | medium |
| GET | /api/scenarios/{scenario_id}/duties/summary | summary | no | low |
| GET | /api/scenarios/{scenario_id}/blocks | detail list | yes (`limit`/`offset`) | medium |
| GET | /api/scenarios/{scenario_id}/dispatch-plan | detail | no | medium |
| POST | /api/scenarios/{scenario_id}/build-blocks | build | N/A | medium |
| POST | /api/scenarios/{scenario_id}/build-dispatch-plan | build | N/A | medium |
| POST | /api/scenarios/{scenario_id}/generate-duties | build | N/A | medium |
| GET | /api/scenarios/{scenario_id}/duties/validate | detail | no | medium |
| GET | /api/scenarios/{scenario_id}/simulation | detail | no | medium |
| GET | /api/scenarios/{scenario_id}/simulation/capabilities | summary | no | low |
| POST | /api/scenarios/{scenario_id}/run-simulation | run | N/A | medium |
| GET | /api/scenarios/{scenario_id}/optimization | detail | no | medium |
| GET | /api/scenarios/{scenario_id}/optimization/capabilities | summary | no | low |
| POST | /api/scenarios/{scenario_id}/run-optimization | run | N/A | medium |
| POST | /api/scenarios/{scenario_id}/reoptimize | run | N/A | medium |
| GET | /api/jobs/{job_id} | detail | no | low |

## High risk endpoints (payload > 300KB or no pagination)

- `GET /api/scenarios/{scenario_id}/graph`
- `GET /api/scenarios/{scenario_id}/graph/arcs`
- `GET /api/planning/depot-scope/{depot_id}/trips`
- `GET /api/scenarios/{scenario_id}/routes/{route_id}`

## Endpoints missing pagination

- `GET /api/scenarios/{scenario_id}/depots`
- `GET /api/scenarios/{scenario_id}/vehicles`
- `GET /api/scenarios/{scenario_id}/stops`
- `GET /api/scenarios/{scenario_id}/routes`
- `GET /api/scenarios/{scenario_id}/depot-route-permissions`
- `GET /api/scenarios/{scenario_id}/vehicle-route-permissions`

## Endpoints returning detail in list response

- `GET /api/scenarios/{scenario_id}/vehicles`
- `GET /api/scenarios/{scenario_id}/stops`
- `GET /api/scenarios/{scenario_id}/explorer/depot-assignments`
- `GET /api/scenarios/{scenario_id}/depot-route-permissions`
- `GET /api/scenarios/{scenario_id}/vehicle-route-permissions`
