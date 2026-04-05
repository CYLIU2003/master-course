# 弦巻 `WEEKDAY` route24 近傍縮小問題の切り分けと 4 ソルバー再実行報告

## 1. 対象と結論

- 対象 scenario: `237d5623-aa94-4f72-9da1-17b9070264be`
- prepared input: `output/prepared_inputs/237d5623-aa94-4f72-9da1-17b9070264be/prepared-11efb997690030ef.json`
- 対象日: `2025-08-04`
- 対象営業所 / service: `tsurumaki` / `WEEKDAY`

2026-04-05 時点の現行コードで 4 ソルバーを再実行した結果、全モードで `trip_count_unserved=0` を確認した。  
ただし MILP は `solver_status=time_limit_baseline` であり、**300 秒以内に exact incumbent を得られなかったため dispatch baseline を返した fallback** である。これは exact MILP 最適解ではない。

> 要約
> - 4 モードすべてで `974/974` を担当し、`trip_count_unserved=0` だった。
> - best objective は ALNS の `2,955,072.4020 JPY`。
> - MILP は `time_limit_baseline` の fallback であり、exact MILP と扱ってはいけない。

## 実行条件

| 項目 | 値 |
|---|---|
| scenario_id | `237d5623-aa94-4f72-9da1-17b9070264be` |
| prepared_input_id | `prepared-11efb997690030ef` |
| scope / depot / service | `tokyu_full:2026-03-23` / `tsurumaki` / `WEEKDAY` |
| service_date / planning_days | `2025-08-04` / `1` |
| counts | `vehicle_count=95`, `charger_count=15`, `route_count=56`, `trip_count=974`, `timetable_row_count=24064` |
| solver_mode / objective | `mode_milp_only` / `total_cost` |
| solver limits | `time_limit_seconds=300`, `mip_gap=0.01`, `alns_iterations=500`, `no_improvement_limit=120`, `destroy_fraction=0.25` |
| service controls | `allow_partial_service=false`, `unserved_penalty=10000.0` |
| simulation controls | `start_time=05:00`, `planning_horizon_hours=20.0`, `time_step_min=60`, `initial_soc=0.8`, `deadhead_speed_kmh=18.0`, `random_seed=42` |
| inventory settings | `use_selected_depot_vehicle_inventory=true`, `use_selected_depot_charger_inventory=true`, `disable_vehicle_acquisition_cost=true` |
| charging assets | `charger_count=15`, `charger_power_kw=90.0`, `depot_power_limit_kw=200.0` |
| TOU / cost preset | 0-9: `25.0`, 9-16: `40.0`, 16-48: `25.0` JPY/kWh; `demand_charge_cost_per_kw_month=1650.0` |
| visualization flags | `fixed_route_band_mode=false`, `enable_vehicle_diagram_output=false`, `output_vehicle_diagram=false` |
| PV / weather | `pv_profile_id=tsurumaki_2025-08-04_60min`, `weather_mode=actual_date_profile`, `weather_factor_scalar=1.0` |
| reproducibility | `timetable_rows_regenerated=false`, `seed=42` |

Objective weights used in the run:

- `vehicle_fixed_cost=1.0`
- `electricity_cost=1.0`
- `demand_charge_cost=1.0`
- `fuel_cost=1.0`
- `deadhead_cost=0.0`
- `battery_degradation_cost=0.0`
- `emission_cost=0.0`
- `unserved_penalty=10000.0`
- `slack_penalty=1000000.0`

## 2. Verified Call Chain

この報告は current call path から確認している。

1. `bff/routers/optimization.py::_run_optimization`
2. `src/optimization/common/builder.py::ProblemBuilder.build_from_scenario`
3. `src/optimization/engine.py::OptimizationEngine.solve`
4. `src/optimization/milp/engine.py`, `src/optimization/alns/engine.py`, `src/optimization/ga/engine.py`, `src/optimization/abc/engine.py`

今回の再実行は、BFF の canonical path と同じ builder / engine を、prepared input 固定で直接呼ぶ形で行った。

## 3. route24 近傍の縮小問題

route24 近傍の切り分け対象として、旧 MILP run

- `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260404_1611/optimization_result.json`

を確認した。ここでは

- `trip_count_served=918`
- `trip_count_unserved=56`

であり、未担当は以下に集中していた。

- `渋24`: 49 便
- `渋23`: 7 便

未担当サンプルは、`渋24` の `06:24`, `06:37`, `06:49`, `06:56`, `07:03` 発や、`渋23` の `06:40`, `07:23`, `07:26`, `07:38`, `07:52` 付近に集中していた。  
このため、IIS ではなく route24 / route23 近傍の朝ピーク縮小問題として先に切り分けた。

## 4. 直した箇所

### 4.1 baseline / repair 側の主因

`ProblemBuilder` の旧 baseline 構築は、`allowed_vehicle_types=('BEV', 'ICE')` の shared trip を vehicle type の列挙順で先に消費していた。  
このケースでは raw baseline が一度 `BEV` duty に偏ってから、後段で actual fleet に materialize した時に崩れ、ヒューリスティック初期解が欠便寄りになっていた。

修正内容:

- `src/optimization/common/builder.py`
  - baseline を actual fleet 台数順で組み立てるよう変更
  - `assign_duty_fragments_to_vehicles` を baseline 構築時点で使い、実車両へ materialize できた trip だけを確定扱いに変更
- `src/optimization/alns/operators_repair.py`
  - `greedy_trip_insertion` でも `allowed_vehicle_types[0]` 固定ではなく、actual fleet 台数順で shared trip を処理するよう変更

現行コードでは baseline 自体が

- `served=974`
- `unserved=0`

になっている。確認 artefact:

- `outputs/baseline_route24_fix_diagnostic_20260405.json`

### 4.2 MILP 側の no-incumbent fallback

別の問題として、Gurobi が `TIME_LIMIT` で `SolCount==0` のまま終わると、旧コードは空の全欠便計画を返していた。  
これは route24 近傍の欠便を潰した後でも、MILP 表示上だけ `974` 便未担当に見える原因だった。

修正内容:

- `src/optimization/milp/solver_adapter.py`
  - `TIME_LIMIT && SolCount==0` の場合は `time_limit_baseline` を返す
  - `auto_relaxed_baseline` と `time_limit_baseline` のどちらでも `supports_exact_milp=false`
- `src/optimization/milp/engine.py`
  - `time_limit_baseline` と `auto_relaxed_baseline` の termination reason を明示

この変更は dispatch feasibility 条件

`arrival + turnaround + deadhead <= next departure`

を変えていない。`timetable_rows` も再導出していないため、既存実験との比較可能性は保っている。  
一方で、MILP の見え方は「全欠便」から「baseline fallback」へ変わるため、**solver status の解釈は以前と異なる**。

## 5. 2026-04-05 4 ソルバー再実行結果

比較 artefact:

- `outputs/mode_compare_route24_fix_rerun_20260405.json`
- `outputs/mode_compare_route24_fix_rerun_20260405.csv`
- `outputs/mode_compare_route24_fix_rerun_20260405/milp.json`
- `outputs/mode_compare_route24_fix_rerun_20260405/alns.json`
- `outputs/mode_compare_route24_fix_rerun_20260405/ga.json`
- `outputs/mode_compare_route24_fix_rerun_20260405/abc.json`
- `outputs/mode_compare_route24_fix_rerun_20260405/verdict.md`
- `outputs/mode_compare_route24_fix_rerun_20260405/consistency_check.json`

実行コマンド:

```powershell
$env:PYTHONPATH='C:\master-course'
python scripts/benchmark_fixed_prepared_scope.py `
  --scenario-id 237d5623-aa94-4f72-9da1-17b9070264be `
  --prepared-input-id prepared-11efb997690030ef `
  --depot-id tsurumaki `
  --service-id WEEKDAY `
  --objective-mode total_cost `
  --time-limit-seconds 300 `
  --mip-gap 0.01 `
  --alns-iterations 500 `
  --no-improvement-limit 120 `
  --destroy-fraction 0.25 `
  --output-stem outputs/mode_compare_route24_fix_rerun_20260405
```

| solver | solve time [s] | objective [JPY] | gap vs best [JPY] | served / total | unserved | route24 unserved | route23 unserved | used vehicles | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| MILP | `1130.5` | `2,979,501.0139` | `+24,428.6118` | `974 / 974` | `0` | `0` | `0` | `91` | `time_limit_baseline` |
| ALNS | `296.0` | `2,955,072.4020` | `0.0000` | `974 / 974` | `0` | `0` | `0` | `93` | `feasible` |
| GA | `187.8` | `2,979,501.0139` | `+24,428.6118` | `974 / 974` | `0` | `0` | `0` | `91` | `feasible` |
| ABC | `276.2` | `2,976,786.2861` | `+21,713.8840` | `974 / 974` | `0` | `0` | `0` | `91` | `feasible` |

補足:

- 旧 direct rerun (`outputs/mode_compare_route24_fix_20260405_005825.json`) では、MILP が `time_limit` のまま空 plan を返し `trip_count_unserved=974` だった
- 同じ prepared input に対する現 rerun では、route24 / route23 の未担当は 0 まで解消した
- comparison JSON / CSV と per-solver JSON の一致確認は `outputs/mode_compare_route24_fix_rerun_20260405/consistency_check.json` に保存し、4 モードすべて `all_passed=true` を確認した
- 先生向けのローカル版は `output/reports/route24_teacher_report_20260405/report.md` にも保存した

## 路線帯担当図

以下は MILP 代表解の便数分布を、路線帯ごとに見やすく並べた図である。棒の上に便数を表示してある。対応する local 画像は `output/reports/route24_teacher_report_20260405/assets/route_band_trip_counts.svg` に保存した。

![route band chart](../output/reports/route24_teacher_report_20260405/assets/route_band_trip_counts.svg)

BEV が入った帯だけを抜き出すと、混在は次の 5 帯に集中していた。

| 路線帯 | BEV 便数 | 備考 |
|---|---:|---|
| 渋24 | 4 | 代表解では 224 便中 4 便だけ BEV |
| 黒07 | 2 | 少数の BEV を吸収 |
| 反11 | 2 | 夕方帯を中心に BEV 混在 |
| 渋21 | 2 | 端数的に BEV を配置 |
| 渋22 | 1 | 単発の BEV 便 |
| 合計 | 11 | `served_trip_count_by_vehicle_type` の BEV 合計 |

## PV 出力図

run summary では `pv_generated_kwh=360.0`、`pv_used_direct_kwh=0.0`、`pv_curtailed_kwh=360.0` であり、PV はこの比較では直接は使われていない。ここでは capacity factor ではなく出力値を縦軸にした。凡例には弦巻営業所 PV の定格 `675.9 kW` を入れてある。local 画像は `output/reports/route24_teacher_report_20260405/assets/pv_output_profile.svg` に保存した。

![pv output profile](../output/reports/route24_teacher_report_20260405/assets/pv_output_profile.svg)

表示単位は `kWh/slot`（60分スロット）で、日中に立ち上がり、12 時前後でピークを迎える。

## 6. 先生向けの説明ポイント

1. 欠便の主因は「route24 そのものの infeasible」より、shared trip を BEV 側へ先食いする baseline / repair の偏りだった
2. route24 近傍の縮小問題で `渋24=49`, `渋23=7` に集中していたため、そこを起点に builder / repair を修理した
3. 現在は heuristic 3 手法が 0 欠便まで戻っている
4. MILP も運用上は 0 欠便に戻るが、これは exact incumbent ではなく baseline fallback なので、論文・発表では exact MILP と言ってはいけない
5. 現時点の best objective は ALNS で、MILP は「空解を返さない安全化」が主改善点である

## 7. 追加 validation

- `pytest tests/test_milp_baseline_fallbacks.py tests/test_baseline_vehicle_type_priority.py tests/test_route_family_deadhead_inference.py tests/test_problem_builder_timestep_and_pv_scaling.py -q`
  - `14 passed`

追加 artefact:

- route24 近傍 pre-fix 診断: `outputs/route24_neighborhood_pre_fix_diagnostic_20260405.json`
- fixed-scope sequential harness: `scripts/benchmark_fixed_prepared_scope.py`
- MILP rerun: `outputs/milp_route24_fix_rerun_20260405_014904.json`
- metaheuristics rerun: `outputs/metaheuristics_route24_fix_rerun_20260405_020120.json`
