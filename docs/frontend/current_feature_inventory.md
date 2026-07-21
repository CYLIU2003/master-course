# Current feature inventory

## Verification basis

This inventory was checked on 2026-07-19 against the reachable current path:

```text
run_app.py
  -> starts bff.main:app on 127.0.0.1:8000
  -> sets MC_DIRECT_CALL=1 by default
  -> starts tools.scenario_backup_tk.App

React target
  -> HTTP only
  -> bff.main:app under /api
  -> preparation / optimization / simulation services
  -> src optimization and dispatch code
```

The current worktree has no `frontend/` directory. References to prior React files in `docs/tkinter_feature_parity_backlog.md` and development history are not treated as reachable code.

## Current Tkinter capabilities to preserve

| Capability | Verified implementation | Migration target | Priority |
|---|---|---|---|
| Scenario CRUD, duplicate, activate | `tools/scenario_backup_tk.py` and scenario router | Scenario list/detail | P0 |
| Quick Setup load/save | Tk client and `/quick-setup` endpoints | Scope/setup form | P0 |
| Prepare with stale detection | Tk prepared-state/watchers and `/simulation/prepare` | Run workspace | P0 |
| Optimization execution | Tk job submission and `/run-optimization` | Run workspace | P0 |
| Prepared simulation | Tk `/simulation/run` client path | Run workspace | P1 |
| Reoptimization | Tk `/reoptimize` client path | Run workspace | P1 |
| Job polling and progress | Tk poller and `/jobs/{job_id}` | Persistent job panel | P0 |
| Optimization/simulation JSON result | Tk detail windows and result GET endpoints | Structured results + raw evidence | P0 |
| Vehicle operation diagram | Tk visualizer entry point | Dispatch result view/artifact link | P1 |
| Vehicles and templates | Tk CRUD/bulk/duplicate methods and master-data router | Fleet pages | P1 |
| Depot and energy asset settings | Tk forms and master/PV routers | Depot/energy page | P1 |
| Solver, objective, cost, CO2 and SOC/fuel settings | Tk Quick Setup/advanced forms | Settings sections | P1 |
| Timetable, rules and route data inspection | Scenario/graph/master-data routers | Inputs and diagnostics | P2 |
| Scenario comparison | Existing scripts/history; no single current BFF comparison endpoint verified | Comparison workspace | P1, contract needed |
| Artifact browser | Paths exist in result/reporting output; no dedicated manifest browsing endpoint verified | Evidence page | P1, contract needed |

## Current BFF capability groups

The generated OpenAPI currently exposes 82 paths and 108 operations.

| Tag | Operations | Notes |
|---|---:|---|
| `scenarios` | 25 | Scenario, Quick Setup, dispatch scope and timetable |
| `master-data` | 40 | Depot, vehicle, template, route and permission editing |
| `graph` | 16 | Trips, connection graph, duties, blocks and dispatch plan |
| `timetable` | 8 | Calendar and calendar-date mutations |
| `simulation` | 6 | Prepare, run, result, capabilities and experiment log |
| `optimization` | 4 | Run, reoptimize, result and capabilities |
| `app-state` | 4 | Dataset/readiness/bootstrap information |
| `pv_management` | 3 | PV dates/profile and depot asset update |
| `jobs` | 1 | Poll one job |
| untagged | 1 | `/health` |

## Current execution and state semantics

- FastAPI prefix: `/api`.
- Prepare endpoint: `POST /api/scenarios/{scenario_id}/simulation/prepare`.
- Optimization endpoint: `POST /api/scenarios/{scenario_id}/run-optimization`.
- Prepared simulation endpoint: `POST /api/scenarios/{scenario_id}/simulation/run`.
- Job states: `pending`, `running`, `completed`, `failed`.
- Job state is persisted under the output job store. An in-flight job whose process is gone after restart is marked failed/orphaned.
- A stale `prepared_input_id` is rejected with HTTP 409 and returns the submitted and current IDs.
- There is no verified job list or cancellation endpoint.
- The optimization and simulation result endpoints currently return internal aggregate dictionaries, not stable frontend DTOs.

## Compatibility rule for every React slice

Each migrated capability must satisfy all of the following before it can be called equivalent:

1. It sends the same material inputs through FastAPI.
2. It reaches the same backend execution path.
3. It displays backend values without semantic recomputation.
4. Its Playwright contract test passes.
5. The corresponding Tkinter smoke flow still passes.
6. It does not remove fields or endpoints needed by Tkinter.

