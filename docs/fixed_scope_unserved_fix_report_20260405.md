# 固定 scope 未担当便修理と 4 ソルバー再実行報告

> 先生向けの図表版は [output/reports/20260405_fixed_scope_237d5623_unserved_fix/report.md](../output/reports/20260405_fixed_scope_237d5623_unserved_fix/report.md) を参照。

## 1. Verified Call Chain

この報告は current call path から確認している。

1. `bff/routers/optimization.py::_run_optimization`
2. `src/optimization/common/builder.py::ProblemBuilder.build_from_scenario`
3. `src/optimization/engine.py::OptimizationEngine.solve`
4. `src/optimization/milp/engine.py`, `src/optimization/alns/engine.py`, `src/optimization/ga/engine.py`, `src/optimization/abc/engine.py`
5. `bff/routers/optimization.py::_persist_rich_run_outputs`, `_persist_canonical_graph_exports`

実行対象は以下に固定した。

- `scenario_id=237d5623-aa94-4f72-9da1-17b9070264be`
- `prepared_input_id=prepared-11efb997690030ef`
- `depot_id=tsurumaki`
- `service_id=WEEKDAY`
- `planning_days=1`
- `objective_mode=total_cost`
- `timetable_rows` は prepared input から materialize したものをそのまま使用し、再生成していない

## 2. Root Cause

今回の修理対象は「本来担当可能な便がコード都合で unserved になる」経路だった。以下は verified fact である。

- deadhead / turnaround lookup に stop name と stop id の混在があり、`DispatchContext.deadhead_rules` は stop id 基準なのに、複数 call site が stop label 側で引いていた
- この alias 不整合を直すと、旧 `974/974 served` は過小 deadhead に依存していたことが分かり、canonical BFF run では `957 served / 17 unserved` へ落ちた
- ただしその 17 便は depot から事前回送で到達可能で、前後接続数も十分あった。aggregate dispatch graph の最小 duty 数は `87` で、scope fleet `95` 台を下回っていた
- にもかかわらず baseline は「vehicle type ごとに full trip set で greedy duty を作ってから実車両へ materialize」しており、全 974 便が shared trip (`BEV/ICE`) の scope でも fleet 全体ではなく type 別に duty 分解してしまっていた
- さらに depot を `tsurumaki`、始終点を `odpt.BusstopPole:...Tsurumakieigyousho...` で持つ場合、0 分 deadhead を「同地点の 0」ではなく「経路欠損の 0」と扱う箇所があり、startup reachability 判定を落としていた
- canonical output path も旧 `output/run_20260324_2210` と比べて `charging_schedule.csv`, `vehicle_timelines.json`, `graph/cost_breakdown.json`, `graph/depot_power_timeseries_5min.csv`, `graph/kpi_summary.json`, `graph/manifest.json`, `graph/refuel_events.csv`, `graph/soc_events.csv`, `graph/trip_assignment.csv` が欠けていた

## 3. Minimal Patch

最小差分で以下を入れた。

- `src/dispatch/models.py`
  - `DispatchContext.locations_equivalent()` を追加し、alias 展開後に同地点判定できるようにした
- `src/dispatch/feasibility.py`
  - `deadhead_min == 0` でも alias 同値なら missing deadhead 扱いしないよう修正した
- `src/optimization/common/builder.py`
  - fully shared scope では pooled shared path-cover baseline を使い、type 別ではなく actual fleet 全体で duty cover を組むようにした
  - この path-cover baseline は current feasibility graph を使うため、hard condition `arrival + turnaround + deadhead <= next departure` 自体は変えていない
  - pooled baseline の startup では depot alias 同値も見て 0 分回送を許可するようにした
  - mixed / type-restricted scope では既存 per-type fallback を残した
- `bff/routers/optimization.py`
  - canonical rich output / graph export を拡張し、旧 run で見えていた generic artifact を run folder に揃えた

## 4. Validation

回帰テスト:

- `tests/test_dispatch_context_location_aliases.py`
- `tests/test_pooled_shared_baseline.py`
- `tests/test_baseline_vehicle_type_priority.py`
- `tests/test_vehicle_assignment_startup_deadhead.py`
- `tests/test_canonical_graph_export_parity.py`
- `tests/test_milp_baseline_fallbacks.py`
- `tests/test_route_family_deadhead_inference.py`
- `tests/test_problem_builder_timestep_and_pv_scaling.py`
- `tests/test_optimization_canonical_metaheuristics.py`
- `tests/test_prepared_scope_execution.py`
- `tests/test_optimization_result_serializer.py`

確認コマンド:

```powershell
python -m pytest tests\test_dispatch_context_location_aliases.py tests\test_pooled_shared_baseline.py tests\test_baseline_vehicle_type_priority.py tests\test_vehicle_assignment_startup_deadhead.py tests\test_canonical_graph_export_parity.py tests\test_milp_baseline_fallbacks.py tests\test_route_family_deadhead_inference.py tests\test_problem_builder_timestep_and_pv_scaling.py -q
python -m pytest tests\test_optimization_canonical_metaheuristics.py tests\test_prepared_scope_execution.py tests\test_optimization_result_serializer.py -q
```

## 5. 4 ソルバー再実行結果

actual BFF canonical path で `rebuild_dispatch=false` の fixed-scope rerun を実施した。dated run は以下。

- MILP: `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260405_1708/`
- ALNS: `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_alns_only/tsurumaki/WEEKDAY/run_20260405_1713/`
- GA: `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_ga_only/tsurumaki/WEEKDAY/run_20260405_1719/`
- ABC: `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_abc_only/tsurumaki/WEEKDAY/run_20260405_1724/`

| solver | status | objective | solve time [s] | served | unserved | vehicles used | exact/fallback |
|---|---:|---:|---:|---:|---:|---:|---|
| MILP | `time_limit_baseline` | `3,536,498.7170` | `1152.45` | `974` | `0` | `87` | fallback |
| ALNS | `feasible` | `3,453,137.5192` | `306.75` | `974` | `0` | `88` | metaheuristic |
| GA | `feasible` | `3,490,088.7734` | `300.74` | `974` | `0` | `88` | metaheuristic |
| ABC | `feasible` | `3,508,589.5957` | `300.28` | `974` | `0` | `90` | metaheuristic |

判定:

- 4 モードすべて `974/974 served`, `trip_count_unserved=0`
- best objective は ALNS
- MILP は `supports_exact_milp=false`, `termination_reason=time_limit`, `plan_source=dispatch_baseline_after_time_limit_no_incumbent` なので exact MILP ではない

## 6. Output Folder Parity

比較 bundle は `output/reports/20260405_fixed_scope_237d5623_unserved_fix/` に整理した。

- `comparison.json`
- `comparison.csv`
- `consistency_check.json`
- `artifact_parity_vs_run_20260324_2210.json`
- `run_manifest.json`
- `verdict.md`

旧基準 `output/run_20260324_2210/` に対する generic artifact parity は 4 モードとも `missing_generic_vs_baseline_count = 0` だった。  
差分に残るのは route-band SVG の路線集合だけで、これは scope が異なることによる expected difference であり、出力欠損ではない。

## 7. Remaining Uncertainty

- MILP は今回も exact incumbent を持てていない。exact MILP 最適解や proven optimum を主張してはいけない
- pooled shared path-cover baseline は fully shared scope 向けの修理であり、vehicle-type-exclusive trip が混ざる scope では既存 fallback を残している
- startup depot reachability と alias 同値は今回の call path で修理済みだが、別 scope でも depot id / stop id の表記揺れは引き続き監視が必要
