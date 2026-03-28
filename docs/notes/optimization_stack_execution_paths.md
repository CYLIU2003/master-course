# Optimization Stack Execution Path Inventory

**Date:** 2026-03-28  
**Purpose:** Map actual runtime paths to identify canonical vs. legacy splits

---

## Executive Summary

The system currently has **TWO DISTINCT SOLVER PATHS** with inconsistent bridging:

1. **Canonical Path** (`mode_milp_only`, `mode_alns_only`, `mode_abc_only`, `mode_ga_only`):
   - Uses `src/optimization/` engine stack
   - Modern unified architecture
   - Clean separation of concerns
   - **DEFAULT for optimization API**

2. **Legacy Path** (`thesis_mode`, `mode_A_*`, `mode_B_*`, `mode_alns_milp`):
   - Uses `src/pipeline/solve.py` + `src/milp_model.py`
   - Original thesis implementation
   - Still active and used by some flows
   - **STILL USED BY SIMULATION**

**CRITICAL PROBLEM:** Optimization can produce canonical results, but simulation and downstream viewers often consume legacy-format results, causing data loss and inconsistencies.

---

## End-to-End Flow: Tkinter Frontend → Optimization → Simulation → Result Display

### 1. Prepare Phase

**Entry Point:** `tools/scenario_backup_tk.py` → `App.prepare_optimization()`

```
User clicks "実行準備" button
└─> App._do_prepare_simulation()
    └─> POST /scenarios/{id}/prepare-simulation
        └─> bff/routers/simulation.py::prepare_simulation_endpoint()
            └─> get_or_build_run_preparation()
                ├─> Filters trips by scope (depot, routes, day_type)
                ├─> Builds dispatch artifacts (if requested)
                └─> Saves prepared_input JSON snapshot
```

**Artifacts Created:**
- `output/prepared_inputs/{scenario_id}/{prepared_input_id}.json`
- Scenario fields updated: `trips`, `duties`, `blocks`, `graph`, `dispatch_plan`

---

### 2. Optimization Phase

**Entry Point:** `tools/scenario_backup_tk.py` → `App.run_optimization()`

```
User clicks "最適化計算" button
└─> App._do_optimization_execution()
    └─> POST /scenarios/{id}/run-optimization
        └─> bff/routers/optimization.py::run_optimization_endpoint()
            └─> _run_optimization() [in background thread/process]
                │
                ├─> MODE DETECTION: solver_mode = _normalize_solver_mode(mode)
                │
                ├─> CANONICAL PATH (mode_milp_only, mode_alns_only, mode_abc_only, mode_ga_only):
                │   ├─> ProblemBuilder().build_from_scenario()
                │   │   └─> Creates CanonicalOptimizationProblem
                │   ├─> OptimizationEngine().solve()
                │   │   └─> Routes to MILPOptimizer / ALNSOptimizer / etc.
                │   │       └─> src/optimization/milp/engine.py::MILPOptimizer.solve()
                │   │           └─> solver_adapter.py::build_gurobi_model()
                │   │               └─> Returns OptimizationEngineResult
                │   └─> ResultSerializer.serialize_result()
                │       └─> Stored as "canonical_solver_result"
                │
                └─> LEGACY PATH (thesis_mode, mode_A_*, mode_B_*, mode_alns_milp):
                    ├─> build_problem_data_from_scenario()
                    │   └─> Creates ProblemData (old style)
                    ├─> solve_problem_data()
                    │   └─> src/pipeline/solve.py
                    │       ├─> _solve_milp_core()
                    │       │   └─> src/model_factory.py::build_model_by_mode()
                    │       │       └─> src/milp_model.py + src/constraints/*
                    │       └─> Returns MILPResult
                    └─> serialize_milp_result()
                        └─> Stored as "solver_result"
```

**Result Storage:**
```python
optimization_result = {
    "solver_result": result_payload,              # Legacy MILPResult format
    "canonical_solver_result": _full_new_result,  # New format (if canonical path)
    "solver_status": "OPTIMAL",
    "objective_value": 123456.78,
    "cost_breakdown": {...},
    "dispatch_report": {...},
    ...
}
```

**SPLIT POINT #1:** Two different result schemas depending on mode

---

### 3. Simulation Phase

**Entry Point:** `tools/scenario_backup_tk.py` → `App.run_simulation()`

```
User clicks "シミュレーション" button
└─> App._do_simulation_execution()
    └─> POST /scenarios/{id}/run-simulation
        └─> bff/routers/simulation.py::run_simulation_endpoint()
            └─> _run_simulation() [in background thread/process]
                ├─> load_prepared_input()
                ├─> build_problem_data_from_scenario()  # ALWAYS LEGACY PATH
                │   └─> Creates ProblemData
                │
                ├─> SOURCE SELECTION:
                │   ├─> source="duties":
                │   │   └─> _run_duty_based_simulation()
                │   │       └─> Uses duties from dispatch pipeline
                │   │
                │   └─> source="optimization_result":
                │       └─> Loads optimization result
                │           ├─> deserialize_milp_result()  # LEGACY DESERIALIZER
                │           │   └─> Expects MILPResult format
                │           └─> simulate_problem_data()
                │               └─> src/pipeline/simulate.py
                │
                └─> serialize_simulation_result()
```

**SPLIT POINT #2:** Simulation ALWAYS uses legacy ProblemData and legacy result deserialization

**CONSEQUENCE:** If optimization ran in canonical mode:
- `canonical_solver_result` contains full new-style data
- But simulation reads `solver_result` (legacy format)
- PV/grid/BESS breakdown fields may be MISSING or LOSSY

---

### 4. Result Display Phase

**Entry Points:**
- Vehicle Diagram: `App.show_vehicle_diagram()`
- Optimization Result: `App.show_optimization_result_detail()`
- Simulation Result: `App.show_simulation_result_detail()`

```
Vehicle Diagram:
└─> GET /scenarios/{id}/optimization-result
    └─> Returns optimization_result dict
        ├─> dispatch_report.trips  # Used for trip metadata
        └─> solver_result.assignment  # Legacy field
            └─> {vehicle_id: [trip_id, ...]}

Optimization Result Window:
└─> GET /scenarios/{id}/optimization-result
    └─> Displays full optimization_result as JSON tree

Simulation Result Window:
└─> GET /scenarios/{id}/simulation-result
    └─> Displays simulation_result as JSON tree
```

**SPLIT POINT #3:** Result viewers read `solver_result` (legacy), not `canonical_solver_result`

---

## Demand Charge Unit Paths

### Legacy Path (`src/objective.py` + `src/constraints/energy_balance.py`):
```python
# Config has monthly rate
demand_charge_cost_per_kw = 1700  # yen/kW/month

# src/objective.py scales to horizon
days_in_horizon = num_periods / SLOTS_PER_DAY
monthly_factor = days_in_horizon / 30.0
demand_charge_term = peak_demand_kw * demand_charge_cost_per_kw * monthly_factor
```

**Convention:** Input is monthly, formula scales to horizon

### Canonical Path (`src/optimization/common/builder.py` + `src/optimization/milp/solver_adapter.py`):
```python
# Config has per-kW cost (unclear if monthly or horizon)
demand_charge_cost_per_kw = 1700  # Unit ambiguous

# src/optimization/milp/solver_adapter.py
demand_charge_term = peak_demand_kw * demand_charge_cost_per_kw
```

**Convention:** Input unit is UNCLEAR, no horizon scaling visible

**SPLIT POINT #4:** Different demand charge formulas, no enforced unit contract

---

## SOC Modeling Paths

### Legacy Path (`src/constraints/charging.py`):
```python
# Trip energy is event-based (single deduction at trip start)
soc[v, t] == soc[v, t-1] - task_energy_kwh  # if trip starts at t
```

**Issue:** Can overestimate mid-trip SOC for long trips spanning multiple slots

### Canonical Path (`src/optimization/milp/solver_adapter.py`):
```python
# Similar event-based approach
# TODO: Needs slot-spread trip energy consumption
```

**Issue:** Same problem exists in canonical path

**SPLIT POINT #5:** Both paths have unsafe mid-trip SOC modeling

---

## Result Metrics Preservation

### Fields in Canonical Result (`ResultSerializer.serialize_result()`):
```python
{
    "solver_status": "OPTIMAL",
    "objective_value": 123456.78,
    "cost_breakdown": {
        "energy_cost": ...,
        "demand_cost": ...,
        "degradation_cost": ...,
        "grid_to_bus_kwh": ...,
        "pv_to_bus_kwh": ...,
        "bess_to_bus_kwh": ...,
        "pv_to_bess_kwh": ...,
        "grid_to_bess_kwh": ...,
        ...
    },
    "plan": {
        "duties": [...],
        "vehicle_paths": {...},
        ...
    },
    "solver_metadata": {...}
}
```

### Fields in Legacy Result (`serialize_milp_result()`):
```python
{
    "status": "OPTIMAL",
    "objective_value": 123456.78,
    "solve_time_seconds": 12.34,
    "mip_gap": 0.001,
    "assignment": {vehicle_id: [trip_id, ...]},
    "soc_series": {...},
    "charge_schedule": {...},
    "charge_power_kw": {...},
    "grid_import_kw": {...},  # Basic field
    "pv_used_kw": {...},       # Basic field
    "peak_demand_kw": {...},
    "obj_breakdown": {...},    # Limited breakdown
    "unserved_tasks": [...]
}
```

**SPLIT POINT #6:** Legacy serializer DROPS detailed PV/grid/BESS flow breakdown

---

## Identified Split Points Summary

| # | Location | Issue |
|---|----------|-------|
| 1 | Optimization result storage | Two schemas: `solver_result` vs `canonical_solver_result` |
| 2 | Simulation input | Always deserializes legacy `solver_result`, ignores canonical |
| 3 | Result viewers | Read legacy fields, miss canonical data |
| 4 | Demand charge formula | Different scaling, unclear unit contract |
| 5 | SOC modeling | Event-based in both paths, mid-trip unsafe |
| 6 | Result serialization | Legacy format loses PV/grid/BESS breakdown |

---

## Files by Layer

### Tkinter Frontend
- `run_app.py` — App launcher
- `tools/scenario_backup_tk.py` — Main UI implementation

### BFF API Layer
- `bff/routers/optimization.py` — Optimization endpoints
- `bff/routers/simulation.py` — Simulation endpoints
- `bff/mappers/solver_results.py` — Result serialization
- `bff/mappers/scenario_to_problemdata.py` — Legacy ProblemData builder

### Canonical Engine (NEW)
- `src/optimization/engine.py` — Mode router
- `src/optimization/common/builder.py` — Problem builder
- `src/optimization/common/result.py` — Result serializer
- `src/optimization/milp/engine.py` — MILP optimizer
- `src/optimization/milp/solver_adapter.py` — Gurobi adapter
- `src/optimization/alns/engine.py` — ALNS optimizer

### Legacy Engine (OLD)
- `src/pipeline/solve.py` — Legacy solve entry point
- `src/model_factory.py` — Model builder dispatcher
- `src/milp_model.py` — Core MILP model and result extraction
- `src/objective.py` — Objective function
- `src/constraints/*.py` — Constraint builders

### Shared/Simulation
- `src/pipeline/simulate.py` — Simulation logic (uses legacy ProblemData)
- `src/simulator.py` — Core simulator

---

## Next Steps (Phases 1-6)

See main mission document for detailed phase requirements.

**Phase 1 Priority:** Decide canonical engine as authoritative, hard-gate or bridge legacy path  
**Phase 2 Priority:** Fix SOC modeling, demand charge units, result metrics symmetry  
**Phase 3 Priority:** Make simulation consume canonical results  
**Phase 4 Priority:** Update Tkinter UI labels and mode selection  
**Phase 5 Priority:** Add comprehensive end-to-end tests  
**Phase 6 Priority:** Clean up stale comments and dead code
