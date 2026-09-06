# Dispatch Contracts

`src/dispatch/` is the canonical source of timetable-driven dispatch feasibility.
The BFF and frontend must consume the same contract rather than reconstructing
rules independently.

## Connection Graph

`GET /api/scenarios/{id}/graph` returns:

- `trips`: canonical trip list used for graph analysis
- `arcs`: every analyzed candidate connection for each eligible vehicle type
- `reason_counts`: aggregated counts by `reason_code`

Each arc includes:

- `from_trip_id`
- `to_trip_id`
- `vehicle_type`
- `deadhead_time_min`
- `turnaround_time_min`
- `slack_min`
- `feasible`
- `reason_code`
- `reason`

`reason_code` is one of:

- `feasible`
- `missing_deadhead`
- `insufficient_time`
- `vehicle_type_mismatch`

`reason` is a human-readable explanation suitable for logs and UI detail panes.

## Duty Validation

`GET /api/scenarios/{id}/duties/validate` returns:

- `duty_id`
- `valid`
- `errors`

Validation is always derived from the same dispatch-layer feasibility rules used
to build the connection graph.
