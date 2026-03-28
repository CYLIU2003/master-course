# Optimization Stack End-to-End Consistency Fix

## Phase 1: Unify or Hard-Gate Solver Paths ✅ COMPLETE

### Summary
Established canonical `src/optimization/` engine stack as authoritative for all optimization modes. Legacy thesis modes are now deprecated with clear migration paths.

### Changes

#### 1. Backend: Solver Mode Gating (`bff/routers/optimization.py`)
- **Updated `_normalize_solver_mode()`:**
  - Hard-gates legacy modes (thesis_mode, mode_a_*, mode_b_*)
  - Auto-routes `mode_alns_milp` → `mode_hybrid` with deprecation warning
  - Raises ValueError for unsupported modes with clear guidance
  - Documented canonical vs legacy distinction

- **Updated path routing:**
  - Added `mode_hybrid` to canonical path check (line 788)
  - Added deprecation warning in legacy else branch
  - Legacy path kept temporarily for migration safety

- **Updated `_optimization_capabilities()`:**
  - Lists only canonical modes as supported
  - Documents mode aliases (milp → mode_milp_only, etc.)
  - Lists deprecated modes with replacement/status
  - Clarifies authoritative engine: `src/optimization/`

**Supported Modes (Canonical):**
- `mode_milp_only` - Exact MILP
- `mode_alns_only` - ALNS metaheuristic
- `mode_ga_only` - Genetic Algorithm
- `mode_abc_only` - Artificial Bee Colony
- `mode_hybrid` - ALNS+MILP hybrid (recommended)

**Deprecated Modes:**
- `mode_alns_milp` → auto-routed to `mode_hybrid`
- `thesis_mode` → BLOCKED (no replacement)
- `mode_a_*` → BLOCKED (no replacement)
- `mode_b_*` → BLOCKED (no replacement)

#### 2. Frontend: UI Updates (`tools/scenario_backup_tk.py`)
- **Updated solver mode default:**
  - Changed from `"hybrid"` to `"mode_hybrid"` (canonical)
  
- **Updated solver settings window:**
  - Combo box values: only canonical modes
  - Added tooltip explaining each mode
  - Noted deprecation of legacy modes
  - Recommended mode: `mode_hybrid`

#### 3. Tests: Verification (`tests/test_solver_path_routing.py`)
**New comprehensive test suite:**
- ✅ Canonical modes pass through unchanged
- ✅ Aliases resolve correctly (milp → mode_milp_only)
- ✅ mode_alns_milp auto-routes with deprecation warning
- ✅ Legacy modes raise ValueError with helpful message
- ✅ Case-insensitive normalization
- ✅ Default mode handling
- ✅ Capabilities endpoint correctness

**Test Results:** 10/10 passed

#### 4. Documentation
- Created `docs/notes/optimization_stack_execution_paths.md`
  - Maps end-to-end execution flow
  - Identifies 6 critical split points
  - Documents canonical vs legacy paths

- Created session plan and progress tracking

### Impact

**Before:**
- Two solver paths with silent divergence
- Users could select unsupported thesis modes
- No clear guidance on which path was used
- Potential for inconsistent behavior

**After:**
- Single authoritative path (canonical)
- Legacy modes gated with clear errors
- Auto-migration for mode_alns_milp → mode_hybrid
- UI shows only supported modes
- Capabilities endpoint documents deprecations

### Non-Breaking Changes
- `mode_alns_milp` users get automatic migration (with warning)
- Canonical modes work as before
- Legacy path temporarily preserved for safety

### Breaking Changes
- `thesis_mode`, `mode_a_*`, `mode_b_*` now raise ValueError
- Users must migrate to canonical modes

### Migration Guide
| Old Mode | New Mode | Notes |
|----------|----------|-------|
| `mode_alns_milp` | `mode_hybrid` | Auto-migrated with warning |
| `thesis_mode` | `mode_milp_only` OR `mode_hybrid` | Choose based on problem size |
| `mode_a_*` | `mode_milp_only` | Closest equivalent |
| `mode_b_*` | `mode_milp_only` | Closest equivalent |

### Next Phases

**Phase 2:** Fix Real Modeling Bugs
- 2.1: SOC modeling (mid-trip safety)
- 2.2: Demand charge unit contract
- 2.3: Result metrics symmetry

**Phase 3:** End-to-End Bridging
- Simulation consumes canonical results
- Vehicle diagram uses authoritative format

**Phase 4:** Frontend/UI Corrections
- Show active solver path
- Demand charge unit labels
- Result windows read canonical fields

**Phase 5:** Tests
- E2E canonical flow
- Result serialization round-trip
- Demand charge unit correctness
- SOC mid-trip feasibility

**Phase 6:** Cleanup
- Remove stale comments
- Delete dead code
- Document deprecated features
- Final validation

### Files Changed
- `bff/routers/optimization.py` - Solver mode gating and capabilities
- `tools/scenario_backup_tk.py` - UI mode selection
- `tests/test_solver_path_routing.py` - New test suite (10 tests)
- `docs/notes/optimization_stack_execution_paths.md` - Execution path inventory
- Session workspace: plan.md, phase1_progress.md

### Verification
```bash
# All tests pass
pytest tests/test_solver_path_routing.py -v
# 10 passed in 1.17s
```

---

**Status:** Phase 1 complete and tested ✅  
**Ready for:** Phase 2 implementation
