# Fixed Scope Model Fix Report (2026-04-06)

## Scope

- scenario: `237d5623-aa94-4f72-9da1-17b9070264be`
- prepared input: `prepared-11efb997690030ef`
- depot / service: `tsurumaki` / `WEEKDAY`
- objective: `total_cost`
- timetable_rows regenerated: `False`

## What Was Corrected

- startup deadhead の既知 missing path を、baseline assignment と MILP `start_arc` の両方で禁止した
- 初便への回送は simulation horizon 外から開始できるようにし、`05:00` より前の startup deadhead と `23:00` 後の帰庫 deadhead を許容した
- deadhead metric merge に `deadhead_speed_kmh` を必ず渡し、既存・推論 metric が configured speed cap を超えないよう補正した
- `fixedRouteBandMode=true` の canonical run では route-band SVG を標準出力にした
- metaheuristic engine が wrapper 側の mode 設定を実際に使うよう修正し、GA=`genetic_like`、ABC=`bee_colony_like` を metadata へ反映した
- BFF canonical MILP path の `warm_start=True` を回復した

## Canonical Rerun Results

| Solver | Status | Objective | Solve Time (s) | Served | Unserved | Vehicles | Exact MILP |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| MILP | `time_limit_baseline` | 3548573.795919167 | 1104.0795609999914 | 974 | 0 | 87 | `False` |
| ALNS | `feasible` | 3534994.692990817 | 224.34049430000596 | 974 | 0 | 88 | `N/A` |
| GA | `feasible` | 3542971.744454992 | 320.58624860004056 | 974 | 0 | 88 | `N/A` |
| ABC | `feasible` | 3542971.744454992 | 336.2637850000174 | 974 | 0 | 88 | `N/A` |

## Interpretation

- 4 solver すべて `974/974 served` を達成した
- best objective は `ALNS = 3534994.692990817`
- MILP は `supports_exact_milp=false`, `termination_reason=time_limit`, `incumbent_history_count=0` のため exact ではなく fallback である
- この結果は current canonical BFF path で確認したものであり、`timetable_rows` の再生成は行っていない

## Standard Output Locations

- comparison bundle: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix`
- comparison summary: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix\comparison.json`
- solver table: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix\solver_comparison_table.csv`
- best-run route-band mirror: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix\graph\route_band_diagrams`
- per-solver route-band SVGs: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix\solver_route_band_diagrams`
- old-run parity check: `C:\master-course\output\reports\20260406_fixed_scope_237d5623_model_fix\artifact_parity_vs_run_20260324_2210.json`

## Canonical Run Directories

- MILP: `C:\master-course\output\2025-08-04\scenario\237d5623-aa94-4f72-9da1-17b9070264be\mode_milp_only\tsurumaki\WEEKDAY\run_20260406_0110`
- ALNS: `C:\master-course\output\2025-08-04\scenario\237d5623-aa94-4f72-9da1-17b9070264be\mode_alns_only\tsurumaki\WEEKDAY\run_20260406_0114`
- GA: `C:\master-course\output\2025-08-04\scenario\237d5623-aa94-4f72-9da1-17b9070264be\mode_ga_only\tsurumaki\WEEKDAY\run_20260406_0119`
- ABC: `C:\master-course\output\2025-08-04\scenario\237d5623-aa94-4f72-9da1-17b9070264be\mode_abc_only\tsurumaki\WEEKDAY\run_20260406_0125`

## Validation

- `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_milp_route_band_settings.py tests/test_canonical_graph_export_parity.py tests/test_optimization_canonical_metaheuristics.py tests/test_metaheuristic_mode_configs.py -q`
- `python -m pytest tests/test_milp_baseline_fallbacks.py tests/test_baseline_vehicle_type_priority.py tests/test_pooled_shared_baseline.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_visualizer_report_utils.py tests/test_route_family_deadhead_inference.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_milp_route_band_settings.py tests/test_canonical_graph_export_parity.py tests/test_optimization_canonical_metaheuristics.py tests/test_metaheuristic_mode_configs.py -q`
- `python -m py_compile bff/mappers/scenario_to_problemdata.py bff/routers/graph.py bff/routers/optimization.py src/dispatch/models.py src/optimization/abc/engine.py src/optimization/alns/acceptance.py src/optimization/alns/engine.py src/optimization/alns/selection.py src/optimization/common/builder.py src/optimization/common/feasibility.py src/optimization/common/vehicle_assignment.py src/optimization/ga/engine.py src/optimization/milp/solver_adapter.py src/route_family_runtime.py`
