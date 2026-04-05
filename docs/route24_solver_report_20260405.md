# 弦巻 `WEEKDAY` route24 近傍縮小問題の切り分けと 4 ソルバー再実行報告

## 1. 対象と結論

- 対象 scenario: `237d5623-aa94-4f72-9da1-17b9070264be`
- prepared input: `output/prepared_inputs/237d5623-aa94-4f72-9da1-17b9070264be/prepared-11efb997690030ef.json`
- 対象日: `2025-08-04`
- 対象営業所 / service: `tsurumaki` / `WEEKDAY`

2026-04-05 時点の現行コードで 4 ソルバーを再実行した結果、全モードで `trip_count_unserved=0` を確認した。  
ただし MILP は `solver_status=time_limit_baseline` であり、**300 秒以内に exact incumbent を得られなかったため dispatch baseline を返した fallback** である。これは exact MILP 最適解ではない。

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

| solver | solver_status | objective_value | served | unserved | vehicles | exact MILP? | 備考 |
|---|---:|---:|---:|---:|---:|---|---|
| MILP | `time_limit_baseline` | `2,979,501.0139` | `974` | `0` | `91` | No | `dispatch_baseline_after_time_limit_no_incumbent` を返した fallback |
| ALNS | `feasible` | `2,955,072.4020` | `974` | `0` | `93` | No | 現行 rerun では最良 objective |
| GA | `feasible` | `2,979,501.0139` | `974` | `0` | `91` | No | baseline と同値 |
| ABC | `feasible` | `2,976,786.2861` | `974` | `0` | `91` | No | GA よりわずかに良い |

補足:

- 旧 direct rerun (`outputs/mode_compare_route24_fix_20260405_005825.json`) では、MILP が `time_limit` のまま空 plan を返し `trip_count_unserved=974` だった
- 同じ prepared input に対する現 rerun では、route24 / route23 の未担当は 0 まで解消した
- comparison JSON / CSV と per-solver JSON の一致確認は `outputs/mode_compare_route24_fix_rerun_20260405/consistency_check.json` に保存し、4 モードすべて `all_passed=true` を確認した

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
