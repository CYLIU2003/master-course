# Phase 2-6 Implementation Specification

## Overview
This document provides comprehensive implementation specifications for Phases 2-6 of the optimization stack end-to-end consistency fix. Phase 1 (solver path unification) is complete and tested.

---

## PHASE 2: Fix Real Modeling Bugs

### 2.1: SOC Modeling - Mid-Trip Safety Fix

#### Problem Analysis
**Current Implementation (Both Paths):**
- Event-based energy accounting: full trip energy deducted at trip end slot
- File: `src/optimization/milp/solver_adapter.py` lines 256-262, 498-509
- File: `src/constraints/charging.py` lines 162-173
- Comment acknowledges issue (line 104-109 in charging.py):
  > "Trip energy is concentrated at the last slot before trip end. Actual consumption is continuous, so model SOC may appear higher than reality."

**Consequence:**
- Long trips spanning multiple slots can show safe SOC at slot boundaries but unsafe mid-trip
- Example: 60min trip consuming 30kWh, 15min slots
  - Model: SOC drops 30kWh at slot 4
  - Reality: SOC drops 7.5kWh per slot over slots 1-4
  - Mid-trip (slot 2): Model shows 100% SOC, reality shows 85% SOC

#### Recommended Solution: **Slot-Spread Distribution**

**Implementation Plan:**

1. **Add trip slot span calculator** (`solver_adapter.py`):
```python
def _trip_slot_span(
    self,
    problem: CanonicalOptimizationProblem,
    departure_min: int,
    arrival_min: int,
) -> List[int]:
    """Return list of slot indices that this trip spans."""
    timestep_min = max(problem.scenario.timestep_min, 1)
    start_slot = self._slot_index(problem, departure_min)
    end_slot = self._slot_index(problem, arrival_min)
    return list(range(start_slot, end_slot + 1))
```

2. **Distribute energy across slots** (`solver_adapter.py` line 498-509):
```python
# OLD: Event-based
trip_energy_expr = gp.quicksum(
    self._trip_energy_kwh(problem, vehicle, trip.trip_id)
    * y[(vehicle.vehicle_id, trip.trip_id)]
    for trip in problem.trips
    if (vehicle.vehicle_id, trip.trip_id) in y
    and self._trip_event_slot_index(...) == slot_idx
)

# NEW: Slot-spread
trip_energy_expr = gp.quicksum(
    (self._trip_energy_kwh(problem, vehicle, trip.trip_id) / len(trip_slots))
    * y[(vehicle.vehicle_id, trip.trip_id)]
    for trip in problem.trips
    if (vehicle.vehicle_id, trip.trip_id) in y
    for trip_slots in [self._trip_slot_span(problem, trip.departure_min, trip.arrival_min)]
    if slot_idx in trip_slots
)
```

3. **Update legacy path** (`src/constraints/charging.py` line 162-173):
```python
# Replace event-based with slot-spread
# Same pattern: distribute task energy across active slots
```

4. **Update comments** (both files):
- Remove warnings about event-based overestimation
- Document slot-spread approach
- Note that this provides conservative mid-trip SOC estimates

5. **Test mid-trip safety** (`tests/test_soc_midtrip_feasibility.py`):
```python
def test_long_trip_midtrip_soc_safety():
    """Verify multi-slot trips maintain safe SOC throughout duration."""
    # Create problem with 60min trip, 15min slots, tight SOC bounds
    # Verify: SOC at each intermediate slot >= soc_min
    # OLD behavior would fail, NEW should pass
```

**Estimated Impact:**
- More conservative SOC constraints
- Slightly higher vehicle count may be needed for tight scenarios
- Eliminates mid-trip infeasibility risk
- Aligns model with physical reality

---

### 2.2: Demand Charge Unit Contract

#### Problem Analysis
**Current State - Unit Ambiguity:**
- UI label: "需要電力料金 (円/kW)" - no time basis specified
- Legacy path (`src/objective.py`): Scales monthly rate to horizon
- Canonical path (`src/optimization/milp/solver_adapter.py`): Direct multiplication, no scaling
- Different formulas = inconsistent costs for same input

**Root Cause:**
- `demand_charge_cost_per_kw` field has no enforced unit convention
- UI doesn't specify if input is monthly, daily, or horizon-normalized
- BFF doesn't convert units
- Solvers interpret inconsistently

#### Recommended Solution: **Monthly Input, Horizon-Normalized Internally**

**Unit Contract:**
```
INPUT (UI/API): demand_charge_monthly_yen_per_kw [yen/kW/month]
  ↓ BFF conversion
INTERNAL (solver): demand_charge_horizon_yen_per_kw [yen/kW/horizon]
  ↓ Formula
OUTPUT: demand_charge_cost = peak_demand_kw * demand_charge_horizon_yen_per_kw [yen]
```

**Implementation Plan:**

1. **UI Labels** (`tools/scenario_backup_tk.py`):
```python
# Line ~1200: Update label and tooltip
self._labeled_entry(
    pricing,
    "需要電力料金 (月額 円/kW)",  # Add "月額" explicitly
    self.demand_charge_var
)
_Tooltip(
    demand_charge_entry,
    "電力会社との契約における月額需要電力料金を入力してください。\n"
    "例: 東京電力 高圧契約 1700円/kW/月\n"
    "システム内部で計画期間に応じた日割り換算が行われます。"
)
```

2. **Schema Field** (`src/optimization/common/problem.py`):
```python
@dataclass
class OptimizationScenario:
    # ... existing fields ...
    demand_charge_monthly_yen_per_kw: float = 0.0  # NEW: explicit monthly unit
    
    @property
    def demand_charge_horizon_yen_per_kw(self) -> float:
        """Convert monthly rate to horizon-normalized rate."""
        if not self.planning_horizon_hours:
            return self.demand_charge_monthly_yen_per_kw
        days_in_horizon = self.planning_horizon_hours / 24.0
        monthly_factor = days_in_horizon / 30.0
        return self.demand_charge_monthly_yen_per_kw * monthly_factor
```

3. **BFF Mapping** (`bff/services/simulation_builder.py`):
```python
def _build_scenario_from_request(payload: dict) -> OptimizationScenario:
    # ...
    demand_charge_monthly = float(payload.get("demandChargeCostPerKw") or 0.0)
    return OptimizationScenario(
        # ...
        demand_charge_monthly_yen_per_kw=demand_charge_monthly,
        # Conversion happens in property getter
    )
```

4. **Canonical Solver** (`src/optimization/milp/solver_adapter.py`):
```python
# Replace direct usage with property
demand_charge_rate = problem.scenario.demand_charge_horizon_yen_per_kw
# Formula: peak_demand_kw * demand_charge_rate
```

5. **Legacy Solver** (`src/objective.py`):
```python
# Remove manual scaling, use property
demand_charge_rate = data.scenario.demand_charge_horizon_yen_per_kw
# Same formula as canonical
```

6. **Test** (`tests/test_demand_charge_unit_contract.py`):
```python
def test_demand_charge_monthly_to_horizon_conversion():
    """Verify monthly rate converts correctly to horizon rate."""
    scenario = OptimizationScenario(
        demand_charge_monthly_yen_per_kw=1700.0,
        planning_horizon_hours=24.0,  # 1 day
    )
    # Expected: 1700 * (1 / 30) = 56.67 yen/kW/day
    assert abs(scenario.demand_charge_horizon_yen_per_kw - 56.67) < 0.01

def test_demand_charge_canonical_legacy_symmetry():
    """Verify canonical and legacy paths produce same cost."""
    # Same problem, same monthly rate
    # Run both paths, compare demand_charge_cost
    # Should match within numerical tolerance
```

**Migration:**
- Existing scenarios: interpret `demandChargeCostPerKw` as monthly
- No data migration needed (same numeric values)
- UI clarifies unit, prevents future confusion

---

### 2.3: Result Metrics Symmetry

#### Problem Analysis
**Current Asymmetry:**
- Canonical result has full PV/grid/BESS breakdown (`ResultSerializer.serialize_result()`)
- Legacy result has limited fields (`serialize_milp_result()`)
- Optimization stores both `solver_result` and `canonical_solver_result`
- Simulation deserializes only `solver_result` (legacy format)
- **Data loss:** PV-to-bus, grid-to-BESS, BESS-to-bus details missing in downstream

**Files:**
- `bff/mappers/solver_results.py` - Legacy serializer (drops fields)
- `src/optimization/common/result.py` - Canonical serializer (preserves all)
- `bff/routers/simulation.py` - Deserializes legacy format only

#### Recommended Solution: **Canonical Schema as Single Source of Truth**

**Implementation Plan:**

1. **Define Canonical Result Schema** (`src/optimization/common/result.py`):
```python
@dataclass
class CanonicalOptimizationResult:
    """Authoritative optimization result schema."""
    solver_status: str
    objective_value: float
    solve_time_sec: float
    mip_gap: float
    
    # Assignment
    vehicle_paths: Dict[str, List[str]]  # vehicle_id -> [trip_id, ...]
    unserved_trip_ids: List[str]
    
    # SOC series
    soc_kwh_by_vehicle_slot: Dict[str, List[float]]
    
    # Charging schedule
    charge_kw_by_vehicle_slot: Dict[str, List[float]]
    
    # Energy flow breakdown (NEW: preserve all fields)
    grid_to_bus_kwh: float
    pv_to_bus_kwh: float
    bess_to_bus_kwh: float
    grid_to_bess_kwh: float
    pv_to_bess_kwh: float
    pv_curtailed_kwh: float
    
    # Aggregates
    peak_demand_kw: float
    total_energy_cost: float
    total_demand_cost: float
    total_degradation_cost: float
    
    # Cost breakdown
    cost_breakdown: Dict[str, float]
    
    # Solver metadata
    solver_metadata: Dict[str, Any]
```

2. **Enhance Legacy Serializer** (`bff/mappers/solver_results.py`):
```python
def serialize_milp_result(result: MILPResult) -> Dict[str, Any]:
    """Serialize legacy result with FULL field preservation."""
    return {
        "status": result.status,
        "objective_value": result.objective_value,
        "solve_time_seconds": result.solve_time_sec,
        "mip_gap": result.mip_gap,
        "assignment": result.assignment,
        "soc_series": result.soc_series,
        "charge_schedule": result.charge_schedule,
        "charge_power_kw": result.charge_power_kw,
        "refuel_schedule_l": result.refuel_schedule_l,
        
        # ADD: PV/grid/BESS breakdown
        "grid_import_kw": result.grid_import_kw,
        "pv_used_kw": result.pv_used_kw,
        "grid_to_bus_kwh": getattr(result, "grid_to_bus_kwh", {}),
        "pv_to_bus_kwh": getattr(result, "pv_to_bus_kwh", {}),
        "bess_to_bus_kwh": getattr(result, "bess_to_bus_kwh", {}),
        "grid_to_bess_kwh": getattr(result, "grid_to_bess_kwh", {}),
        "pv_to_bess_kwh": getattr(result, "pv_to_bess_kwh", {}),
        
        "peak_demand_kw": result.peak_demand_kw,
        "obj_breakdown": result.obj_breakdown,
        "unserved_tasks": result.unserved_tasks,
        "infeasibility_info": result.infeasibility_info,
    }
```

3. **Canonical-to-Legacy Bridge** (if needed temporarily):
```python
def canonical_result_to_legacy_dict(canonical: CanonicalOptimizationResult) -> Dict:
    """Convert canonical result to legacy dict format without data loss."""
    return {
        "status": canonical.solver_status,
        "objective_value": canonical.objective_value,
        "assignment": canonical.vehicle_paths,
        "grid_to_bus_kwh": canonical.grid_to_bus_kwh,
        "pv_to_bus_kwh": canonical.pv_to_bus_kwh,
        # ... map all fields ...
    }
```

4. **Update MILPResult Dataclass** (`src/milp_model.py`):
```python
@dataclass
class MILPResult:
    # ... existing fields ...
    
    # ADD: PV/grid/BESS flow details
    grid_to_bus_kwh: Dict[int, float] = field(default_factory=dict)
    pv_to_bus_kwh: Dict[int, float] = field(default_factory=dict)
    bess_to_bus_kwh: Dict[int, float] = field(default_factory=dict)
    grid_to_bess_kwh: Dict[int, float] = field(default_factory=dict)
    pv_to_bess_kwh: Dict[int, float] = field(default_factory=dict)
```

5. **Extract Full Results** (`src/milp_model.py` extract_result()):
```python
def extract_result(...) -> MILPResult:
    # ... existing extraction ...
    
    # ADD: Extract PV/grid/BESS variables
    grid_to_bus = {
        slot_idx: model.getVarByName(f"g2bus_{depot_id}_{slot_idx}").X
        for depot_id, slot_idx in g2bus_vars.keys()
    }
    # ... extract all flow variables ...
    
    return MILPResult(
        # ... existing fields ...
        grid_to_bus_kwh=grid_to_bus,
        pv_to_bus_kwh=pv_to_bus,
        # ... all new fields ...
    )
```

6. **Test Round-Trip** (`tests/test_optimization_result_serializer.py`):
```python
def test_result_serialization_preserves_all_fields():
    """Verify no data loss in serialization round-trip."""
    original = create_test_result_with_all_fields()
    serialized = serialize_milp_result(original)
    deserialized = deserialize_milp_result(serialized)
    
    # Verify all fields preserved
    assert deserialized.grid_to_bus_kwh == original.grid_to_bus_kwh
    assert deserialized.pv_to_bus_kwh == original.pv_to_bus_kwh
    # ... check all critical fields ...
```

**Impact:**
- Simulation gets full energy breakdown
- Result viewers show complete PV/grid/BESS flows
- No more "missing fields" in downstream analysis
- Enables proper cost attribution

---

## PHASE 3: End-to-End Bridging

### Problem
- Optimization produces canonical results
- Simulation consumes legacy `solver_result` format
- Vehicle diagram reads from `solver_result`
- **Gap:** `canonical_solver_result` is stored but ignored

### Solution: Prefer Canonical, Bridge if Needed

**Files to Update:**
1. `bff/routers/simulation.py` - Simulation input
2. `bff/routers/optimization.py` - Result storage
3. `tools/scenario_backup_tk.py` - Vehicle diagram

**Implementation:**

1. **Simulation Input** (`bff/routers/simulation.py` line ~495):
```python
def _run_simulation(...):
    # Load optimization result
    opt_result = store.get_field(scenario_id, "optimization_result") or {}
    
    # PREFER canonical result if available
    canonical_result = opt_result.get("canonical_solver_result")
    legacy_result = opt_result.get("solver_result")
    
    if canonical_result:
        # Use canonical (full fidelity)
        solver_result = _canonical_to_milp_result(canonical_result)
    elif legacy_result:
        # Fallback to legacy
        solver_result = deserialize_milp_result(legacy_result)
    else:
        raise ValueError("No optimization result found")
    
    # Simulate with full-fidelity result
    sim_result = simulate_problem_data(data, solver_result)
```

2. **Canonical-to-MILP Bridge** (new helper):
```python
def _canonical_to_milp_result(canonical_dict: Dict) -> MILPResult:
    """Convert canonical result dict to MILPResult for simulation."""
    return MILPResult(
        status=canonical_dict["solver_status"],
        objective_value=canonical_dict["objective_value"],
        assignment=canonical_dict["plan"]["vehicle_paths"],
        soc_series=canonical_dict["plan"]["soc_kwh_by_vehicle_slot"],
        # ... map all fields ...
    )
```

3. **Vehicle Diagram** (`tools/scenario_backup_tk.py` line ~5794):
```python
def _open_vehicle_diagram_window(self, result: dict[str, Any]) -> None:
    # PREFER canonical if available
    canonical = result.get("canonical_solver_result")
    if canonical:
        assignment = canonical.get("plan", {}).get("vehicle_paths", {})
    else:
        assignment = (result.get("solver_result") or {}).get("assignment") or {}
    
    # ... rest of logic ...
```

4. **Test** (`tests/test_canonical_result_to_simulation_bridge.py`):
```python
def test_canonical_optimization_to_simulation():
    """E2E: Canonical opt → simulation → valid results."""
    # Run optimization in canonical mode
    # Verify canonical_solver_result is stored
    # Run simulation
    # Verify simulation consumes canonical result
    # Verify all energy fields present in simulation output
```

**Impact:**
- Simulation uses full-fidelity canonical results
- No more data loss between optimization and simulation
- Vehicle diagram works with both formats
- Graceful fallback for legacy results

---

## PHASE 4: Frontend/UI Corrections

### Tasks

1. **Show Active Solver Mode** (`tools/scenario_backup_tk.py`):
```python
# Add to optimization monitoring window
self.solver_mode_label = ttk.Label(
    monitor_frame,
    text=f"Solver Mode: {payload.get('mode')} (Canonical Engine)",
    foreground="#0066cc"
)
```

2. **Demand Charge Unit Label** (DONE in Phase 2.2 spec)

3. **Result Window Canonical Support**:
```python
def show_optimization_result_detail(self, scenario_id: str) -> None:
    # Fetch result
    result = self.client.get_optimization_result(scenario_id)
    
    # Show which result format is available
    has_canonical = "canonical_solver_result" in result
    has_legacy = "solver_result" in result
    
    format_label = ttk.Label(
        window,
        text=f"Result Format: {'Canonical' if has_canonical else 'Legacy'}",
        foreground="#666"
    )
```

---

## PHASE 5: Tests

### Required Test Coverage

1. **E2E Canonical Flow** (`tests/test_e2e_canonical_optimization.py`):
   - Prepare → Optimize (canonical) → Simulate → Vehicle Diagram
   - Verify all steps succeed
   - Verify result fields preserved end-to-end

2. **Result Round-Trip** (covered in Phase 2.3)

3. **Demand Charge Unit** (covered in Phase 2.2)

4. **SOC Mid-Trip** (covered in Phase 2.1)

5. **Legacy Mode Handling** (covered in Phase 1)

### Test Execution
```bash
pytest tests/test_solver_path_routing.py -v  # Phase 1
pytest tests/test_soc_midtrip_feasibility.py -v  # Phase 2.1
pytest tests/test_demand_charge_unit_contract.py -v  # Phase 2.2
pytest tests/test_optimization_result_serializer.py -v  # Phase 2.3
pytest tests/test_canonical_result_to_simulation_bridge.py -v  # Phase 3
pytest tests/test_e2e_canonical_optimization.py -v  # Phase 5
```

---

## PHASE 6: Cleanup

### Tasks

1. **Remove Stale Comments**:
   - Search for: "TODO", "FIXME", "event-based" warnings
   - Remove comments describing old behavior
   - Update docstrings to reflect new reality

2. **Delete Dead Code**:
   - Legacy else branch in `optimization.py` (after migration period)
   - Unused compatibility helpers
   - Old test fixtures for thesis modes

3. **Document Deprecated Features** (`docs/notes/deprecated_features.md`):
```markdown
# Deprecated Features

## Solver Modes (Deprecated 2026-03-28)

| Mode | Status | Replacement |
|------|--------|-------------|
| thesis_mode | BLOCKED | mode_milp_only or mode_hybrid |
| mode_a_* | BLOCKED | mode_milp_only |
| mode_b_* | BLOCKED | mode_milp_only |
| mode_alns_milp | AUTO-ROUTED | mode_hybrid |

## Unit Conventions Changed

| Field | Old | New |
|-------|-----|-----|
| demand_charge_cost_per_kw | Ambiguous | demand_charge_monthly_yen_per_kw (explicit monthly) |
```

4. **Final Validation**:
```bash
# Run ALL tests
pytest tests/ -v

# Check imports
python -c "import bff.routers.optimization; import src.optimization"

# Verify no git unstaged changes
git status

# Run a full scenario through UI
```

---

## Success Criteria

✅ Phase 1: Solver paths unified, legacy gated, tests passing
✅ Phase 2: SOC slot-spread, demand charge monthly→horizon, full metrics
✅ Phase 3: Simulation consumes canonical, vehicle diagram works
✅ Phase 4: UI shows mode/format, demand charge labeled
✅ Phase 5: All tests pass (E2E + unit)
✅ Phase 6: No stale code, docs updated

**Final State:**
- Single authoritative solver path (canonical)
- Consistent demand charge unit contract
- Safe SOC mid-trip modeling
- No data loss in result serialization
- Full chain works: UI → API → Engine → Storage → Simulation → Viewers
- Comprehensive test coverage
- Clean, documented codebase

---

## Estimated Effort

- Phase 2.1 (SOC): 4-6 hours (complex formula changes + testing)
- Phase 2.2 (Demand): 3-4 hours (schema + UI + conversion + tests)
- Phase 2.3 (Metrics): 4-5 hours (serializer enhancement + extraction)
- Phase 3 (Bridge): 3-4 hours (simulation input + vehicle diagram)
- Phase 4 (UI): 2-3 hours (labels + mode display)
- Phase 5 (Tests): 3-4 hours (E2E + integration tests)
- Phase 6 (Cleanup): 2-3 hours (comments + dead code + docs)

**Total: ~25-35 hours of focused implementation work**

---

## Priority Order (if time-constrained)

1. **Critical Path (must-have):**
   - Phase 2.2 (Demand Charge) - Immediate user impact
   - Phase 2.3 (Result Metrics) - Data loss fix
   - Phase 3 (Bridging) - Makes canonical results actually usable

2. **High Value:**
   - Phase 2.1 (SOC) - Safety/correctness
   - Phase 5 (Tests) - Prevents regressions

3. **Polish:**
   - Phase 4 (UI) - User experience
   - Phase 6 (Cleanup) - Code quality

