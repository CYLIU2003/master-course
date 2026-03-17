# Tkinter Feature Parity Backlog

Purpose
- Track all capabilities currently available in the non-Tk frontend and preserve them as migration targets for Tkinter.
- Core cleanup must not remove backend/data/contracts needed by these capabilities.

Current route-level capabilities in non-Tk frontend
- Scenario management
  - Scenario list, create, duplicate, activate, delete, overview.
  - Source: frontend/src/app/Router.tsx, frontend/src/pages/scenario/ScenarioListPage.tsx, frontend/src/pages/scenario/ScenarioOverviewPage.tsx
- Quick setup execution flow
  - Select depot/routes, day type, trip filters, route swap permissions.
  - Save quick setup, prepare simulation, run simulation, run optimization, job polling.
  - Source: frontend/src/pages/scenario/ScenarioQuickPage.tsx
- Planning / master data editing
  - 3-pane planning layout with depots, vehicles, routes, stops.
  - Depot-route/vehicle-route permissions and family-level permissions.
  - Source: frontend/src/pages/planning/MasterDataPage.tsx and related planning components
- Vehicle template lifecycle
  - Create/update/delete templates, batch vehicle creation from template.
  - Supports BEV/ICE detail fields (energy/fuel/CO2/weight/engine/acquisition).
  - Source: frontend/src/pages/planning/VehicleTemplatesPage.tsx
- Input editors
  - Timetable, deadhead, rules pages.
  - Source: frontend/src/app/Router.tsx targets under pages/inputs
- Dispatch pipeline pages
  - Trips, graph, duties, precheck.
  - Source: frontend/src/app/Router.tsx targets under pages/dispatch
- Simulation/optimization run pages
  - Dedicated pages and API-backed run flows.
  - Source: frontend/src/app/Router.tsx, frontend/src/api/simulation.ts, frontend/src/api/optimization.ts
- Results pages
  - Dispatch, energy, cost result views.
  - Source: frontend/src/app/Router.tsx targets under pages/results
- Compare page
  - Scenario comparison view.
  - Source: frontend/src/app/Router.tsx target /compare
- Public data explorer paths
  - ODPT/public data exploration and compare-related views.
  - Source: frontend/src/pages/odpt/*, frontend/src/pages/compare/*

Tkinter parity status notes
- Already present in tools/scenario_backup_tk.py
  - Scenario CRUD/activate
  - Quick setup load/save
  - Route label apply to scenario
  - Vehicle and template CRUD, batch operations
  - Prepare/run simulation, run optimization, job polling
  - Cost/tariff and objective-related inputs
- Potential gaps to keep in backlog
  - Full planning 3-pane parity (map/node views)
  - Dedicated results views parity (dispatch/energy/cost detailed pages)
  - Compare workflow parity
  - Public data explorer parity

Non-negotiable migration rule
- Do not drop backend endpoints, schema fields, or config/data artifacts that are currently consumed by non-Tk frontend routes unless equivalent Tkinter capability is implemented and verified.

Verification checklist for future Tk parity work
- Feature exists in non-Tk route and in Tk tool with same backend contract.
- Same key parameters are editable and persisted.
- Same execution flow reaches completed jobs.
- Same critical outputs are inspectable.
