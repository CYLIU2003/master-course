# Solver Identity Audit

## Current identity

| Solver | display_name | true_solver_family | independent_implementation | delegate | maturity |
|---|---|---|---:|---|---|
| MILP | MILP | milp | True | none | core |
| ALNS | ALNS | alns | True | none | core |
| GA | GA prototype | ga | True | none | prototype |
| ABC | ABC prototype | abc | True | none | prototype |
| Hybrid | MILP-seeded ALNS | mixed | False | `MILPOptimizer` -> `ALNSOptimizer` | experimental |

## Current metadata surface

### MILP
- `src/optimization/milp/engine.py`
- Exposes: `backend`, `supports_exact_milp`, `has_feasible_incumbent`, `incumbent_count`, `warm_start_applied`, `warm_start_source`, `best_bound`, `final_gap`, `nodes_explored`, `runtime_sec`, `first_feasible_sec`, `fallback_reason`, `iis_generated`, `presolve_reduction_summary`, `search_profile`, `objective_weights`
- Missing / weak:
  - exact bound/gap meaning on fallback-only paths
  - IIS generation is still diagnostics-gated on some infeasible paths

### ALNS
- `src/optimization/alns/engine.py`
- Exposes: `true_solver_family`, `independent_implementation`, `delegates_to`, `candidate_generation_mode`, `has_feasible_incumbent`, `incumbent_count`, `accepted_neighborhoods`, `rejected_neighborhoods`, `best_destroy_operator`, `termination_reason`, `search_profile`
- Metadata currently states:
  - `solver_display_name=ALNS`
  - `solver_maturity=core`
- Missing / weak:
  - per-operator improvement contribution beyond selected/accepted/reward
  - richer termination classification for early-stop vs time-limit edge cases

### GA
- `src/optimization/ga/engine.py`
- Independent population search
- Metadata currently states:
  - `delegates_to=none`
  - `true_solver_family=ga`
  - `independent_implementation=True`
  - `solver_display_name=GA prototype`
  - `solver_maturity=prototype`
- Comparison tier: prototype
- Missing:
  - solver-specific operator contribution accounting

### ABC
- `src/optimization/abc/engine.py`
- Independent bee-colony search
- Metadata currently states:
  - `delegates_to=none`
  - `true_solver_family=abc`
  - `independent_implementation=True`
  - `solver_display_name=ABC prototype`
  - `solver_maturity=prototype`
- Comparison tier: prototype
- Missing:
  - solver-specific operator contribution accounting

### Hybrid
- `src/optimization/hybrid/hybrid_engine.py`
- Current behavior is `MILP seed -> ALNS improve`
- Name is still "Hybrid", but the implementation is closer to `MILPSeededALNS`

## Partial MILP repair

- `src/optimization/alns/operators_repair.py`
- Already wired to `OptimizationConfig.partial_milp_trip_limit`, `time_limit_sec`, `mip_gap`, `random_seed`
- Repair settings are recorded in plan metadata

## Latest benchmark evidence

`outputs\\mode_compare_cost_minimize_1500_after_gaabc.*`

| solver | maturity | status | objective | wall_clock_sec | comparison_tier |
|---|---|---|---:|---:|---|
| MILP | core | BASELINE_FALLBACK | 4259515.117011707 | 1689.167945 | excluded |
| ALNS | core | SOLVED_INFEASIBLE | 4273603.50672764 | 416.494116 | excluded |
| GA prototype | prototype | SOLVED_FEASIBLE | 4333550.952272254 | 1502.582494 | prototype |
| ABC prototype | prototype | SOLVED_INFEASIBLE | 4281666.598847793 | 1500.217698 | prototype |

Main comparison rows should be restricted to `comparison_tier=core` **and** `SOLVED_FEASIBLE`; this run has no such row.

## Immediate implementation plan

1. Add solver profiling fields to shared metadata structures.
2. Replace GA/ABC wrappers with independent search loops.
3. Expand MILP metadata with bound/gap/node/fallback/IIS details.
4. Rename or relabel Hybrid to match actual execution path.
5. Add benchmark schema fields for profiling and fallback reasons.

