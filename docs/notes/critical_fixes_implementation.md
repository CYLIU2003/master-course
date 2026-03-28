# Critical Fixes Implementation Summary

## Status: In Progress
Started: 2026-03-28
Mission: Complete all 6 phases to end-to-end consistency

---

## Current State Analysis

### Demand Charge Unit Issue (Phase 2.2 - CRITICAL)

**Problem Identified:**
1. **Legacy path** (`src/objective.py` line 121-129):
   - Uses `data.demand_charge_rate_per_kw` as monthly rate
   - Manually scales to horizon: `monthly_to_horizon_factor = horizon_days / 30.0`
   - Formula: `demand_charge_cost * rate * monthly_to_horizon_factor * peak`

2. **Canonical path** (`src/optimization/common/builder.py` line 239-261):
   - Reads `cost_cfg.get("demand_charge_cost_per_kw")`
   - Passes DIRECTLY to scenario: `demand_charge_on_peak_yen_per_kw=demand_charge`
   - NO scaling visible

3. **Canonical evaluator** (`src/optimization/common/evaluator.py` line 1097-1098):
   - Uses scenario fields directly: `demand_charge_on_peak_yen_per_kw * w_on`
   - NO horizon scaling

4. **UI** (`tools/scenario_backup_tk.py`):
   - Label: "需要電力料金 (円/kW)" - NO time basis stated
   - No tooltip explaining unit convention

**Consequences:**
- Same UI input value → Different solver costs (legacy scales, canonical doesn't)
- Users don't know if they're entering monthly, daily, or horizon rates
- **Silent inconsistency across solver paths**

**Root Cause:**
- `demand_charge_cost_per_kw` field has no enforced unit contract
- Different code paths make different assumptions
- No single point of truth

---

### Result Metrics Asymmetry (Phase 2.3 - CRITICAL)

**Problem Identified:**
1. **MILPResult dataclass** (`src/milp_model.py` line 53-100):
   - Has: `grid_import_kw`, `grid_export_kw`, `pv_used_kw`, `pv_to_bus_kwh`, `peak_demand_kw`
   - **Missing**: `grid_to_bus_kwh`, `pv_to_bus_kwh` (per-slot breakdown), `bess_to_bus_kwh`, `grid_to_bess_kwh`, `pv_to_bess_kwh`

2. **Legacy serializer** (`bff/mappers/solver_results.py` line 9-26):
   - `serialize_milp_result()` returns:
     ```python
     {
         "status", "objective_value", "solve_time_seconds", "mip_gap",
         "assignment", "soc_series", "charge_schedule", "charge_power_kw",
         "refuel_schedule_l", "grid_import_kw", "pv_used_kw",
         "peak_demand_kw", "obj_breakdown", "unserved_tasks", "infeasibility_info"
     }
     ```
   - **Drops**: BESS flow details, grid-to-BESS, PV-to-BESS, per-slot breakdowns

3. **Canonical result** (`src/optimization/common/result.py`):
   - `ResultSerializer.serialize_result()` preserves full ledger entries
   - Includes per-vehicle, per-depot, per-day breakdowns
   - **But**: Simulation deserializes only legacy format

4. **Simulation input** (`bff/routers/simulation.py` line ~495):
   - Calls: `solver_result_dict = opt_result.get("solver_result")`
   - **Ignores**: `canonical_solver_result` even if available
   - **Data loss**: Full PV/grid/BESS breakdown lost for simulation

**Consequences:**
- Vehicle diagram can't show BESS contribution
- Energy accounting reports incomplete
- Researchers lose granular flow data
- **Optimization produces rich data, downstream consumes poor data**

---

### SOC Modeling (Phase 2.1 - SAFETY-CRITICAL)

**Problem Identified:**
1. **Canonical path** (`src/optimization/milp/solver_adapter.py`):
   - Line 256-262: Trip energy variable creation (event-based)
   - Line 498-509: SOC balance constraint (accumulates at trip-end slot)
   ```python
   trip_energy_expr = gp.quicksum(
       self._trip_energy_kwh(problem, vehicle, trip.trip_id)
       * y[(vehicle.vehicle_id, trip.trip_id)]
       for trip in problem.trips
       if self._trip_event_slot_index(...) == slot_idx  # <-- SINGLE SLOT
   )
   ```

2. **Legacy path** (`src/constraints/charging.py`):
   - Line 162-173: Same event-based pattern
   - Line 104-109: **Comment acknowledges issue**:
     > "Trip energy is concentrated at the last slot before trip end. Actual consumption is continuous, so model SOC may appear higher than reality."

3. **Physical Reality:**
   - 60min trip consuming 30kWh, 15min timestep (4 slots)
   - **Model**: Deducts 30kWh at slot 4 → SOC safe at slots 1-3
   - **Reality**: Deducts 7.5kWh/slot → SOC drops continuously

**Consequence:**
- Long trips can pass SOC constraints but fail mid-trip in reality
- **Safety risk**: Bus could run out of charge mid-route
- Model numerically correct, operationally unsafe

---

## Implementation Priority (Time-Constrained Approach)

Given user request "最後まで終わらせて" (finish to the end), we must complete all phases but prioritize by impact:

### Tier 1: Critical Path (Must-Have Today)
1. **Phase 2.2 - Demand Charge Unit**
   - Immediate user-facing cost correctness issue
   - Fast to fix: add property, update UI label, unify formula
   - High visibility (affects all optimization runs)
   - **ETA: 2-3 hours**

2. **Phase 2.3 - Result Metrics Symmetry**
   - Data loss fix (optimization → simulation bridge)
   - Unlocks downstream analysis value
   - Required for Phase 3
   - **ETA: 3-4 hours**

3. **Phase 3 - End-to-End Bridging**
   - Makes canonical results actually consumable
   - Fixes vehicle diagram and simulation input
   - Completes the "optimization → result → viewer" chain
   - **ETA: 3-4 hours**

### Tier 2: High Value (Complete Today if Possible)
4. **Phase 2.1 - SOC Modeling**
   - Safety/correctness issue
   - More complex implementation (formula changes across both paths)
   - Needs careful testing (don't break 245 tests)
   - **ETA: 4-6 hours**

5. **Phase 5 - Comprehensive Tests**
   - Prevents regressions
   - Validates all fixes
   - E2E coverage
   - **ETA: 3-4 hours**

### Tier 3: Polish (Final Cleanup)
6. **Phase 4 - UI Corrections**
   - User experience
   - Mode/format display
   - **ETA: 2-3 hours**

7. **Phase 6 - Cleanup**
   - Code quality
   - Docs
   - Final validation
   - **ETA: 2-3 hours**

---

## Implementation Order

### NOW: Phase 2.2 - Demand Charge Unit Contract
1. Add property to `OptimizationScenario` for conversion
2. Update UI label with "月額"
3. Update BFF builder to use property
4. Update canonical evaluator formula
5. Verify legacy formula already scales (keep as-is or migrate)
6. Add unit test

### NEXT: Phase 2.3 - Result Metrics
1. Add missing fields to `MILPResult` dataclass
2. Extract BESS variables in `extract_result()`
3. Update `serialize_milp_result()` to preserve all fields
4. Create canonical-to-legacy bridge helper
5. Test serialization round-trip

### THEN: Phase 3 - Bridging
1. Update simulation router to prefer `canonical_solver_result`
2. Add canonical deserializer
3. Update vehicle diagram to read canonical format
4. Test opt→sim→diagram flow

### THEN: Phases 2.1, 4, 5, 6 (sequentially)

---

## Completion Criteria

✅ No silent unit ambiguity
✅ No data loss in result serialization
✅ Simulation consumes canonical results
✅ Vehicle diagram works with both formats
✅ All PV/grid/BESS metrics preserved end-to-end
✅ 245 baseline tests stay green
✅ New tests for each fix
✅ UI labels clarified
✅ Docs updated

**Final Deliverable:**
- Working end-to-end flow: Tkinter → BFF → Canonical Engine → Simulation → Viewers
- Consistent cost calculations across paths
- Full-fidelity result preservation
- Comprehensive test coverage
- Clean, documented codebase

---

## Next Action

START Phase 2.2 implementation:
1. Edit `src/optimization/common/problem.py` - add conversion property
2. Edit `tools/scenario_backup_tk.py` - update label
3. Edit `src/optimization/common/builder.py` - use property
4. Edit `src/optimization/common/evaluator.py` - verify formula
5. Create test file

