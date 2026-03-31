# E-Bus Scheduling Optimization — Research Experiment Log

> **目的**: 電気バス運行・充電スケジューリング最適化の修士論文研究実験ログ。
> GUI変更履歴は `app/CHANGELOG.md` へ移動済み。本ファイルは実験・結果・設計判断のみ記録する。

---

## アーキテクチャ方針

```
src/         研究コア (schema / loader / optimizer / simulator / analysis / exporter)
app/         可視化・観察レイヤー (GUIはsrc.pipeline.*を呼ぶのみ、ソルバーロジックなし)
config/      実験設定JSON (ExperimentConfig)
data/        入力データ CSV (cases/ = 実験用, toy/ = 検証用)
results/     出力KPI (kpi.json, kpi.csv, report.md)
tests/       回帰テスト
```

**優先実装順**: `mode_A_journey_charge` → `mode_B_resource_assignment` → optimizer/simulator一貫性検証 → thesis_mode 拡張

---

## 10 KPI (全モード共通)

| KPI | 説明 |
|-----|------|
| `objective_value` | ソルバー目的関数値 [円] |
| `total_energy_cost` | 電力購入コスト [円] |
| `total_demand_charge` | デマンド料金 [円] |
| `total_fuel_cost` | 燃料コスト [円] |
| `vehicle_fixed_cost` | 車両固定使用コスト [円] |
| `unmet_trips` | 未対応タスク数 |
| `soc_min_margin_kwh` | 全車両・全スロットでのSOC下限余裕の最小値 [kWh] |
| `charger_utilization` | 充電器稼働率 [%] |
| `peak_grid_power_kw` | グリッドピーク電力 [kW] |
| `solve_time_sec` | ソルバー求解時間 [s] |

---

## 実験記録

### [DEV-2026-03-28] MILP重大バグ7件の一括修正（core_pv）

- **背景**:
  - コードレビューで、目的関数のデマンド料金換算、割当制約の計算量、SOCモデリング注記不足、logger import 破損、PV KPI 不足、冗長制約、既知制限の明示不足が指摘された。

- **対応**:
  - `src/objective.py`
    - デマンド料金を月額 [円/kW/月] からホライズン日数換算（`horizon_days/30.0`）へ修正。
  - `src/constraints/assignment.py`
    - `no_overlap` ペア列挙を削除し、`one_task_per_slot[k,t]` の時刻ベース実装へ置換。
    - `y_follow` 直前に depot 仮想ノード未実装の既知制限コメント（TODO）を追記。
  - `src/constraints/charging.py`
    - `add_soc_constraints()` docstring 冒頭へ、イベントベースSOC計上の仮定と安全マージン推奨を追記。
  - `src/milp_model.py`
    - `MILPResult` に `soc_modeling_note` と `pv_to_bus_kwh` を追加。
    - `pre_solve_check()` に SOC 安全マージン警告（最大単一トリップ消費の50%基準）を追加。
    - `extract_result()` で `pv_to_bus_kwh`（kWh換算）を集計。
  - `src/constraints/energy_balance.py`
    - 冗長な `pv_self_consume` 制約を削除し、`power_balance` 由来で上限制約される旨の NOTE を追記。
  - `src/experiment_logger.py`
    - 壊れた自己参照 import を廃止し、`src/pipeline/logger.py` からの公開エントリポイントへ置換。

- **検証**:
  - AC-1 ～ AC-6: すべて PASS（import確認、属性確認、換算係数、旧制約除去、冗長制約除去、py_compile）。
  - AC-7: `pytest tests/ -q` 実行で `148 passed`。
  - PR: `core_pv <- fix/milp-bugs-7items` として作成済み（#2）。

### [DEV-2026-03-27] Quick Setup保存整合 / SOC override / prepared stop coordinates

- **背景**:
  - 237d シナリオの cost-min 再実行で、Quick Setup の詳細設定と実ソルバー入力の間にドリフトが残っていた。
  - legacy ProblemData 側では `final_soc_target_percent` が車両 `soc_target_end` に反映されず、既定 `targetEndSoc=0.6` が優先されるケースがあった。
  - prepared input の `stops` が座標なし推論停止 (`prepared_input_inferred`) に落ちると、deadhead 距離/時間が 0 の接続が残り物理説明性が弱くなった。

- **対応**:
  - `bff/mappers/scenario_to_problemdata.py`
    - legacy `Vehicle` 生成時に `initial_soc_percent` / `soc_min` / `final_soc_floor_percent` / `final_soc_target_percent` を優先反映するよう修正。
  - `src/optimization/common/builder.py`
    - canonical vehicle state でも `initial_soc_percent` / `final_soc_floor_percent` / ICE燃料比 override を実車両へ反映し、ALNS/GA/ABC と MILP の初期条件差を縮小。
  - `bff/services/run_preparation.py`
    - scoped trip / timetable から参照 stop_id を収集し、`tokyu_bus_data.load_stops()` の座標付き stop を優先採用するよう変更。
    - 座標付き stop と inferred stop をマージし、missing name は補いながら deadhead 推論に必要な緯度経度を保持。
  - `bff/routers/scenarios.py` / `tools/scenario_backup_tk.py`
    - Quick Setup で `objectiveWeights` と `randomSeed` を保存・再読込。
    - frontend では `slack_penalty` / `degradation` を専用欄と JSON 欄で分解・再構成し、保存後のドリフトを抑制。

- **テスト**:
  - `tests/test_problemdata_soc_overrides.py`
  - `tests/test_run_preparation_stop_coords.py`
  - `tests/test_quick_setup_advanced_persistence.py`

### [DEV-2026-03-27] 充電物理妥当性の強化: timetable-based home-depot charging windows

- **背景**:
  - 既存 MILP は `home depot` 接続便の前後1スロット近傍に依存した proxy 拘束が中心で、
    発表時に「実際にその時刻に充電可能窓だったか」の説明が弱かった。
  - 学会向け説明では、厳密扱い領域と近似領域の切り分けをコード・README双方で一致させる必要があった。

- **対応**:
  - `src/optimization/common/builder.py`
    - `charging_window_mode`（`timetable_layover` / `home_depot_proxy`）を metadata へ保存。
    - `home_depot_charge_pre_window_min` / `home_depot_charge_post_window_min` を追加。
  - `src/optimization/milp/solver_adapter.py`
    - `timetable_layover` 時、trip の出発前/到着後ウィンドウを時刻ベースで列挙し、
      そのスロットでのみ充電・給油を許可する制約へ更新。
    - 互換性のため `home_depot_proxy` を残し、窓列挙が空になるケースには proxy へフォールバック。
    - `_slot_indices_for_interval()` の日跨ぎ処理を補強（`arrival <= departure` 時の 24h 補正）。
  - `README.md`
    - 充電窓モードの説明を追加。
    - デマンド料金の単日 proxy 前提を明記。

- **テスト**:
  - `tests/test_milp_route_band_settings.py`
    - builder metadata 反映（`charging_window_mode` と window 幅）を追加検証。
    - timetable-based 窓列挙ヘルパーのスロット整合テストを追加。

### [DEV-2026-03-26] MILP妥当性修正: ICE燃料上限・売電変数・課金/デマンド定義を実測整合へ

- **背景**:
  - MILPにおいて、ICEの燃料状態が制約化されておらず、タンク容量超過の割当が理論上許容される。
  - 電力収支は系統受電のみで表現され、PV余剰/V2G時の逆潮流を扱えない。
  - 電力料金が「走行消費」課金になっており、充電時刻最適化やPV自家消費効果が反映されない。
  - デマンド料金制約が走行エネルギーを需要電力に加算していた。

- **対応**:
  - `src/constraints/assignment.py`
    - ICE車両に `fuel_tank_cap` 制約を追加（`sum(task_fuel_ice * x) <= fuel_tank_capacity`）。
    - `use_link` を車両ごとの集約制約へ変更（制約本数削減）。
  - `src/milp_model.py`
    - `p_grid_export` 変数を追加（非負連続）。
    - `slack_cover` を `CONTINUOUS` から `BINARY` へ変更。
    - ICE向け `fuel[k,t]` 変数を追加し、燃料時系列制約を組み込み。
  - `src/constraints/energy_balance.py`
    - 電力収支式に `p_grid_export` を導入し、逆潮流を表現可能化。
    - デマンド追跡を `p_grid_import <= peak_demand` に統一（走行消費の混入を除去）。
  - `src/objective.py`
    - 電力量料金を「メーター課金」へ変更：`buy_price * p_grid_import * delta_h`。
    - 売電時は `sell_back_price * p_grid_export * delta_h` を控除。
    - `energy_balance` 非使用時は旧ロジックをフォールバックとして保持。
  - `src/constraints/charging.py`
    - SOC遷移の充電項を `charger_efficiency * vehicle.charge_efficiency` で換算するよう明示。
    - ICE燃料遷移 `fuel[k,t+1] = fuel[k,t] - burn[k,t]` と上下限制約を追加。

- **テスト**:
  - `pytest tests/test_objective_modes.py tests/test_milp_route_band_settings.py -q`
  - 結果: `12 passed`
  - `pytest tests/test_bev_energy_accounting.py -q`
  - 結果: `3 passed`

- **追加対応（同日）**:
  - `src/simulator.py`
    - 仮電力量の算定を改善し、BEVは `soc[t]-soc[t+1]` の放電量を優先利用（SOC系列がある場合）。
    - これにより長時間便・深夜跨ぎ時のスロット課金整合を改善。
    - `total_grid_export_kwh` / `grid_export_kw_series` を `SimulationResult` に追加。
  - `src/milp_model.py`
    - `MILPResult` に `grid_export_kw` を追加し、`p_grid_export` の抽出を実装。
    - `y_follow[k,r1,r2]` 変数を実際に生成するよう更新。
  - `src/constraints/assignment.py`
    - `y_follow` の連結パス制約を追加（in/out次数上限、edge_count整合）。
    - これにより回送コスト・回送エネルギーで参照する遷移弧が有効化。
  - `src/constraints/charging.py`
    - SOC遷移式に回送消費項（`deadhead_energy_kwh * y_follow`）を追加。
    - 後続便の出発直前スロットへ回送消費を計上する方式で反映。
  - `src/objective.py`
    - 回送コスト計算を全ペア総当たりから `y_follow` 既存弧のみ走査へ最適化。

- **追加対応（同日・本格実装）**:
  - `src/milp_model.py`
    - `x_assign` を feasible `(k,r)` のみ生成するスパース化へ変更。
    - `z_charge` / `p_charge` / `p_discharge` を feasible `(k,c,t)` のみ生成へ変更。
    - 結果抽出部をスパースkey存在チェック対応に更新。
  - `src/constraints/assignment.py`
    - 不適合ペア `x==0` 制約を削除（変数未生成で表現）。
  - `src/constraints/charging.py`
    - スパース `z/p` 前提で制約生成を更新（互換性0固定ループを廃止）。
  - `src/constraints/charger_capacity.py`
    - スパース `z_charge` での容量制約に対応。
  - `src/constraints/optional_v2g.py`
    - スパース `z_charge/p_discharge` 参照に対応。
  - `src/constraints/battery_degradation.py`
    - スパース `p_charge/p_discharge` 参照に対応。
  - `src/model_factory.py`
    - `mode_A_journey_charge` の固定割当をスパース変数対応に更新。

- **テスト**:
  - `pytest tests/test_objective_modes.py tests/test_milp_route_band_settings.py tests/test_bev_energy_accounting.py -q`
  - 結果: `15 passed`
  - `pytest -q`
  - 結果: `113 passed`

### [DEV-2026-03-27] ALNS/Rolling 本格修正（論文前提の致命ギャップ解消）

- **背景**:
  - ALNS の多くの repair operator が `charging_slots` を更新せず、
    評価関数の電力コスト/需要料金がダミー化するリスクがあった。
  - rolling reoptimize で API 入力 `actual_soc` が canonical problem の車両初期SOCへ反映されていなかった。
  - `peak_hour_removal` が 7-9 時ハードコード、`worst_trip_removal` が経験式スコアのまま。

- **対応**:
  - `src/optimization/rolling/reoptimizer.py`
    - `reoptimize(..., actual_soc=...)` を追加。
    - `actual_soc` を車両 `initial_soc` へ適用してから再最適化する実装を追加。
  - `bff/routers/optimization.py`
    - reopt worker から `RollingReoptimizer.reoptimize()` へ `actual_soc` を明示伝播。
  - `src/optimization/alns/operators_repair.py`
    - `greedy_trip_insertion` / `baseline_dispatch_repair` / `partial_milp_repair` / `regret_k_insertion` の返却時に
      充電スロット再計算を実行する `_with_recomputed_charging()` を追加。
    - 簡易SOC追跡で不足時に idle 窓へ充電を挿入する `_recompute_charging_slots()` を追加。
  - `src/optimization/alns/operators_destroy.py`
    - `peak_hour_removal` をデータ駆動化（`classify_peak_slots(price_slots)` を優先、fallback は設定窓）。
    - `worst_trip_removal` に `objective_fn` を導入し、限界改善量ベース除去を実装。
  - `src/optimization/alns/engine.py`
    - `peak_hour_removal` に問題データ（price slots）と設定を渡す。
    - `worst_trip_removal` に `CostEvaluator` ベースの限界改善スコア関数を渡す。
  - `src/optimization/common/feasibility.py`
    - `charging_slots` と trip energy に基づく SOC 妥当性チェックを追加（出発時必要SOC/下限違反を errors 化）。
  - `src/optimization/common/problem.py`
    - `OptimizationConfig` に `use_data_driven_peak_removal`, `peak_hour_windows_min`, `worst_trip_scoring` を追加。
  - `src/parameter_builder.py`
    - BEV 電費 fallback 既定値を `1.2 -> 1.8 kWh/km` へ上方修正。

- **テスト**:
  - 追加: `tests/test_reopt_alns_critical_fixes.py`
    - rolling actual_soc 伝播
    - data-driven peak removal
    - marginal-cost worst trip removal
    - feasibility SOC shortage 検出
  - 実行:
    - `pytest tests/test_reopt_alns_critical_fixes.py -q` → `4 passed`
    - `pytest tests/test_milp_route_band_settings.py tests/test_bev_energy_accounting.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py -q` → `17 passed`

### [DEV-2026-03-27] 再レビュー対応（reopt 安全化 + BFF実経路テスト）

- **背景**:
  - `RollingReoptimizer.reoptimize()` の baseline lock 分岐が `CanonicalOptimizationProblem(...)` 手組み再構築だったため、
    将来のフィールド追加時に情報欠落リスクがあった。
  - `actual_soc` は BFF 実装で伝播済みだが、BFF worker 経路を直接検証する回帰テストが未整備だった。
  - capabilities note が process 固定の文言で、Windows 既定 thread 実装と説明が不整合だった。

- **対応**:
  - `src/optimization/rolling/reoptimizer.py`
    - baseline lock 分岐を `replace(problem, baseline_plan=locked_plan, metadata=dict(problem.metadata))` に変更。
    - 問題定義フィールドを保ったまま lock 済み baseline だけ差し替える形へ統一。
  - `tests/test_reopt_alns_critical_fixes.py`
    - baseline lock 時に `routes/depots/vehicle_types/depot_energy_assets/metadata` が保持される回帰テストを追加。
  - `tests/test_bff_reoptimization_actual_soc_forwarding.py`（新規）
    - `_run_reoptimization()` worker 経路で `actual_soc` が `RollingReoptimizer.reoptimize(..., actual_soc=...)` へ渡ることを検証。
  - `bff/routers/optimization.py`
    - capabilities note を "dedicated executor (thread or process)" へ修正。

- **連続実行安定性チェック（Windows 実測）**:
  - full suite を 5 連続実行:
    - 各回 `122 passed`（失敗 0）
    - 実行時間: 約 23 秒/回
  - 最適化関連ターゲットを 10 連続実行:
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_reopt_alns_critical_fixes.py`
    - `tests/test_bff_reoptimization_actual_soc_forwarding.py`
    - 各回 `18 passed`（失敗 0）
    - 実行時間: 約 0.82-0.92 秒/回

### [DEV-2026-03-27] EV/ICE 共通 ledger 化 + 補給イベント再設計

- **背景**:
  - 既存は EV 電力のみ provisional/final 分離があり、ICE 燃料の同等会計と
    vehicle/day ledger の統一構造が不足していた。
  - ALNS の補給再計算は前倒し補給寄りで、必要時遅延補給に寄せる改善余地があった。

- **対応**:
  - `src/optimization/common/problem.py`
    - `VehicleCostLedgerEntry`, `DailyCostLedgerEntry` を追加。
    - `AssignmentPlan` に `vehicle_cost_ledger`, `daily_cost_ledger` を追加。
    - `OptimizationScenario` に multi-day / overnight 制御パラメータを追加。
  - `src/optimization/common/evaluator.py`
    - EV: provisional/final/leftover を ledger 指標として明示。
    - ICE: `_evaluate_liquid_fuel_with_overwrite()` を追加し、
      provisional fuel debt → refuel event で rollback/realize を実装。
    - `CostBreakdown` を provisional/realized/leftover の運用コスト系列で拡張。
    - `build_plan_ledgers()` を追加し、車両別・日別 ledger を生成。
  - `src/optimization/milp/engine.py`, `src/optimization/alns/engine.py`, `src/optimization/hybrid/hybrid_engine.py`
    - evaluator 生成 ledger を `AssignmentPlan` へ注入して返却。
  - `src/optimization/common/result.py`
    - `vehicle_cost_ledger`, `daily_cost_ledger` を API payload へ出力。
    - operating/EV/ICE provisional-realized-leftover のトップレベル出力を追加。
  - `src/optimization/alns/operators_repair.py`
    - `_recompute_charging_slots()` を「遅いスロット優先の必要量補給」に更新。
    - depot/port/slot電力の簡易上限制御を追加。
    - overnight window を見た補給禁止（forbid）ゲートを追加。
    - `_recompute_refuel_slots()` を追加し ICE の補給イベント再生成を実装。
  - `bff/mappers/solver_results.py`
    - simulator 出力にも operating/EV/ICE provisional-realized-leftover キーを追加（互換拡張）。

- **テスト**:
  - `tests/test_evaluator_provisional_overwrite.py`
    - ICE 補給なし leftover 検証
    - ICE 補給あり rollback + realized 検証
  - `tests/test_optimization_result_serializer.py`
    - ledger payload と operating split のシリアライズ検証
  - 実行結果:
    - `pytest tests/test_evaluator_provisional_overwrite.py tests/test_optimization_result_serializer.py tests/test_reopt_alns_critical_fixes.py tests/test_bff_reoptimization_actual_soc_forwarding.py -q` → `12 passed`
    - `pytest tests/test_milp_route_band_settings.py tests/test_case_comparison_pv_bess.py tests/test_bev_energy_accounting.py -q` → `16 passed`
    - `pytest -q` → `125 passed`

### [DEV-2026-03-27] 残タスク完了（MILP補給挙動ペナルティ + multi-day carryover）

- **背景**:
  - 前段で未着手だった 2 点:
    - MILP objective における全台同時/早期充電の抑制ペナルティ
    - multi-day ledger の day 間 carryover 継続性

- **対応**:
  - `src/optimization/milp/solver_adapter.py`
    - 追加した soft penalty フック:
      - `charge_session_start_penalty_yen`
      - `slot_concurrency_penalty_yen`
      - `early_charge_penalty_yen_per_kwh`
      - `charge_to_upper_buffer_penalty_yen_per_kwh`
    - 追加変数/制約:
      - charge session start binary
      - slot concurrency excess
      - SOC upper-buffer excess
    - metadata へ penalty 設定値を書き戻し。
  - `src/optimization/common/evaluator.py`
    - `build_plan_ledgers()` を multi-day 対応強化。
    - `planning_days > 1` のとき vehicle ledger を day ごとに展開し、
      `end(day n) == start(day n+1)` を満たす carryover 連鎖を生成。

- **テスト**:
  - 追加: `tests/test_milp_solver_penalty_helpers.py`
    - soft concurrency limit と early-charge weight の挙動を検証。
  - 追加: `tests/test_evaluator_multiday_ledger.py`
    - 3日 ledger の件数と day 間 carryover 継続性を検証。
  - 実行結果:
    - `pytest tests/test_milp_solver_penalty_helpers.py tests/test_evaluator_multiday_ledger.py tests/test_evaluator_provisional_overwrite.py tests/test_milp_route_band_settings.py -q` → `18 passed`
    - `pytest -q` → `128 passed`

  - `src/result_exporter.py`
    - `summary.json` の `kpi` に `total_grid_export_kwh` を追加。
  - `tools/bus_operation_visualizer_tk.py`
    - サマリー表示に以下を追加:
      - 電力コスト基準（provisional/charged）
      - 電力コスト(仮) / 電力コスト(充電実績)
      - 系統受電量 / 系統売電量

### [DEV-2026-03-25] 出力先ディレクトリを output に統一（output/outputs 混在解消）

- **背景**:
  - 実行経路によって `output/` と `outputs/` が混在し、成果物・ジョブ・prepared inputs の参照先が分散していた。

- **対応**:
  - 新規: `bff/store/output_paths.py`
    - `outputs_root()` を追加し、既定を `output/` に統一（`MC_OUTPUTS_DIR` があれば優先）。
    - `scenarios_root()` を追加し、既定を `output/scenarios/` に統一（`SCENARIO_STORE_PATH` があれば優先）。
  - 更新:
    - `run_app.py`（bundled mode 既定出力を `output/` に変更）
    - `bff/store/scenario_store.py`（scenario/app_context の既定ルートを共通ヘルパー経由へ）
    - `bff/store/job_store.py`（ジョブ保存先を `output/jobs` に変更）
    - `bff/routers/optimization.py`（prepared_inputs と最適化出力ルートを共通化）
    - `bff/routers/simulation.py`（prepared_inputs とシミュレーション出力ルートを共通化）
    - `bff/routers/graph.py`（subset export 先を共通化）
    - `bff/services/experiment_reports.py`（experiment report 出力先を共通化）

- **テスト**:
  - `pytest tests/test_prepared_scope_execution.py tests/test_run_preparation_hash.py -q`
  - 結果: `3 passed`

### [DEV-2026-03-25] Route Family runtime に公式根拠ベース override 層を追加（東98/渋41/渋42）

- **背景**:
  - runtime repair 後の真値に対し、Quick Setup 側で scenario ごとに見え方が揺れる課題が残っていた。
  - 複雑系統（東98/渋41/渋42）は heuristic 単独より、公式公開情報に沿った固定タグ層を持つ方が再現性が高い。

- **対応**:
  - `bff/services/runtime_route_family.py`
    - `official_manual_override` 層を追加（user manual override より下位、derived より上位）。
    - family code + terminal pair で以下を固定:
      - 東98: `main_outbound/main_inbound/depot_out/depot_in`
      - 渋41: `main_outbound/main_inbound/branch/short_turn`
      - 渋42: `main_outbound/main_inbound/branch`
    - 公式対象 family の `routeFamilyLabel` を固定補完:
      - 東98: `東京駅南口 ⇔ 清水`
      - 渋41: `渋谷駅 ⇔ 大井町駅`
      - 渋42: `渋谷駅 ⇔ 大崎駅西口`
    - user manual が存在する route は従来通り最優先で保持。

- **テスト**:
  - `tests/test_runtime_route_family.py`
    - 公式 override 回帰（東98/渋41/渋42の variant と source）を追加。
    - user manual override 優先の回帰を追加。
  - `tests/test_quick_setup_route_selection.py`
    - Quick Setup payload で公式 family label が露出する回帰を追加。

### [DEV-2026-03-24] 目黒1営業所で PVなし / PVあり / PV+BESSあり の3比較を試行

- **対象シナリオ**:
  - ベース: `outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-bb5102a730db115c.json`
  - 生成: `outputs/scenario_meguro_pv_bess_sat.json`

- **設定した基本パラメータ（目黒）**:
  - `timestep_min = 60`
  - `service_id = SAT`
  - `pv_capacity_kw = 480.8`
  - `pv_generation_kwh_by_slot` は `meguro_2025-08-01_60min.json` を基に、運行 horizon に合わせて 19 要素へ整合
  - `bess_energy_kwh = 1000.0`
  - `bess_power_kw = 250.0`
  - `bess_initial_soc_kwh = 500.0`
  - `bess_soc_min_kwh = 100.0`
  - `bess_soc_max_kwh = 1000.0`
  - `bess_terminal_soc_min_kwh = 300.0`
  - `allow_grid_to_bess = false`（case matrix 側で case ごとに切替）

- **実行コマンド**:
  - `python scripts/run_depot_energy_case_matrix.py --scenario outputs/scenario_meguro_pv_bess_sat.json --depot-id meguro --service-id SAT --output-dir outputs/case_matrix_meguro_sat --mode milp --time-limit-sec 180 --mip-gap 0.05 --random-seed 42 --alns-iterations 120`

- **出力**:
  - `outputs/case_matrix_meguro_sat/case_matrix_summary.csv`
  - `outputs/case_matrix_meguro_sat/case_matrix_results.json`

- **結果要約**:
  - case0 (PVなし): objective `3030546.0138`, `solver_status=optimal`, `feasible=false`
  - case1 (PVあり): objective `3030546.0138`, `solver_status=optimal`, `feasible=false`
  - case2 (PV+BESS): objective `2949002.7571`, `solver_status=optimal`, `feasible=false`
  - 注: `allow_partial_service=true` のため未充足便が残り、`feasible=false`。比較は目的値ベースで実施。

### [DEV-2026-03-24] Solcast CSV実投入: 全営業所日別JSON生成と台帳自動同期コマンド追加

- **背景**:
  - `data/external/solcast_raw/` に 12 営業所分の `*_2025_08_60min.csv` が配置されたため、
    全営業所一括で日別JSON生成と台帳ステータス更新を実行した。

- **実行内容**:
  - 日別JSON一括生成
    - コマンド: `python scripts/build_pv_profiles.py --raw-dir data/external/solcast_raw --out-dir data/derived/pv_profiles --slot-minutes 60 --mode gti --overwrite`
    - 結果: `JSON files written: 372`（12営業所 × 31日）
    - 出力: `data/derived/pv_profiles/{depot_id}_2025-08-XX_60min.json`
  - 台帳自動同期（新規補助コマンド）
    - 新規: `scripts/sync_solcast_registry.py`
    - コマンド: `python scripts/sync_solcast_registry.py --registry data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json --raw-dir data/external/solcast_raw --timezone +09:00 --fallback-period-min 60`
    - 結果: `updated=12, cached=12, missing=0`

- **更新された台帳情報**:
  - ファイル: `data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json`
  - `last_synced_at`: `2026-03-24T10:02:31.731615+00:00`
  - 各営業所に以下を自動付与:
    - `acquisition_status=cached`
    - `acquired_at`（CSV更新時刻UTC）
    - `record_count`
    - `available_dates`
    - `min_period_end`, `max_period_end`
    - `time_column`, `irradiance_column`

- **追記（同日）**:
  - `build_pv_profiles.py` の `period_end` 解釈を修正（区間終端を直前スロットへ割当）。
  - `pv_generation_kwh_by_slot` / `capacity_factor_by_slot` を 24 要素固定化。
  - 修正後に 12営業所 × 31日（372件）を再生成し、`meguro_2025-08-01_60min.json` の 24 要素を確認。

### [DEV-2026-03-24] フェーズ2着手: 実車両優先生成 + depot_energy_assets 編集導線（BFF/Schema/UI）

- **目的**:
  - canonical problem 生成時の車両IDを、タイプ別カウント由来の合成IDから「営業所別実車両情報」優先へ移行。
  - `depot_energy_assets` を Quick Setup/Prepare から編集・保存できる経路を確立。

- **対応**:
  - `src/optimization/common/builder.py`
    - `build_from_scenario()` で選択営業所スコープの実車両レコードを抽出し `build_from_dispatch()` に受け渡し。
    - `build_from_dispatch()` に `scenario_vehicles` / `disable_vehicle_acquisition_cost` 引数を追加。
    - 実車両レコード優先の `_build_vehicles_from_records()` を追加（`vehicle_id`, `depotId`, `enabled` を反映）。
    - 既存のタイプ別カウント生成 `_build_vehicles()` はフォールバックとして維持。
  - `bff/routers/scenarios.py`
    - `UpdateQuickSetupBody` に `depotEnergyAssets` を追加。
    - `GET /quick-setup` の `simulationSettings` に `depotEnergyAssets` を返却。
    - `PUT /quick-setup` で `simulation_config.depot_energy_assets` へ保存。
  - `bff/routers/simulation.py` / `bff/services/simulation_builder.py`
    - `PrepareSimulationSettingsBody` に `depot_energy_assets` を追加。
    - Prepare 適用時に `simulation_config.depot_energy_assets` へ保存。
  - `tools/scenario_backup_tk.py`
    - 詳細パラメータに `depot_energy_assets(JSON)` 入力欄を追加。
    - Quick Setup 読込/保存で JSON 往復を実装。
    - Prepare payload に `depot_energy_assets` を追加。

- **テスト**:
  - 更新: `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - 実車両優先（`bev-1`）と所属営業所（`dep-1`）を検証。
  - 更新: `tests/test_simulation_builder_prepare_scope.py`
    - `depot_energy_assets` が `simulation_config` に保存されることを検証。

### [DEV-2026-03-24] フェーズ1着手: timestep可変化とPV換算のslot幅連動、depot_default依存の縮小

- **目的**:
  - 30分固定前提を外し、Solcast 1時間データと整合する基盤へ移行する。
  - 単一営業所（安全側）で `depot_default` 依存を下げる。

- **対応**:
  - `src/optimization/common/builder.py`
    - `simulation_config.timestep_min` / `scenario_overlay.solver_config.timestep_min` を受け取り、未指定時 60 分を既定化。
    - `OptimizationScenario.timestep_min` の固定 30 分を撤廃し、可変 `timestep_min` を適用。
    - `pv_available_kw * 0.5` 固定換算を廃止し、`slot_h = timestep_min / 60` で `pv_generation_kwh_by_slot` を構成。
    - canonical problem の depot id を選択営業所 ID（単一営業所）で生成し、車両 `home_depot_id` も同一 ID で統一。
    - `depot_energy_assets` の fallback 読み込みで `depot_default` と canonical depot id の互換を保持。
    - 時刻スロット生成・TOU展開・tariff展開の `delta_t_min` を `timestep_min` 連動化。

- **テスト**:
  - 追加: `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - 60分設定で `pv_generation_kwh_by_slot == (2.0, 4.0)`
    - 30分設定で `pv_generation_kwh_by_slot == (1.0, 2.0)`
  - 更新: `tests/test_problem_builder_depot_energy_asset_controls.py`
    - canonical depot id を `dep-1` 前提へ再整合。
  - 実行:
    - `pytest tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_optimization_result_serializer.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `11 passed`

### [DEV-2026-03-24] 充電地点を営業所固定として座標を出力に連携

- **方針**:
  - 充電地点は営業所とみなし、車両別の推定滞在地点推論は導入せず、まず営業所経緯度を確実に出力へ流す。

- **対応**:
  - `src/optimization/common/problem.py`
    - `ProblemDepot` に `latitude` / `longitude` を追加。
    - `ChargingSlot` に `charging_depot_id` / `charging_latitude` / `charging_longitude` を追加。
  - `src/optimization/common/builder.py`
    - scenario の `depots` から営業所座標を読み取り、`metadata.depot_coordinates_by_id` に保持。
    - 選択営業所情報を `ProblemDepot` の name/座標へ反映。
  - `src/optimization/milp/solver_adapter.py`
    - `ChargingSlot` 生成時に営業所IDと営業所経緯度を付与。
  - `src/optimization/common/result.py`
    - `charging_schedule` に営業所IDと経緯度をシリアライズ。

- **テスト**:
  - 追加: `tests/test_optimization_result_serializer.py` に営業所座標出力検証を追加。
  - 実行:
    - `pytest tests/test_optimization_result_serializer.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `9 passed`

### [DEV-2026-03-24] core_pv フォローアップ: BESS終端・同時充放電・CO2会計・Grid→BESS価格条件を修正

- **背景**:
  - 営業所別 PV/BESS フロー導入後、終端スロットの BESS 物理整合性と CO2 会計の厳密性を強化する必要があった。

- **対応**:
  - `src/optimization/milp/solver_adapter.py`
    - BESS 充放電の同時成立を禁止（スロットごと binary mode 制約）。
    - 充放電出力上限を全スロットに適用（終端スロット含む）。
    - 終端 SOC 下限制約（`bess_terminal_soc_min_kwh`）を導入し、最終時刻の過放電抜け穴を抑止。
    - `allow_grid_to_bess=True` 時でも、価格閾値・許可スロットに応じて `g2bess=0` を課すゲートを追加。
    - CO2 目的項を BEV 走行電力量ベースから、`Grid→Bus + Grid→BESS` 実フローベースへ変更。
  - `src/optimization/common/evaluator.py`
    - CO2 評価を実フロー（`grid_to_bus + grid_to_bess`）優先へ変更（fallback は従来方式）。
  - `src/optimization/common/problem.py` / `src/optimization/common/builder.py`
    - `DepotEnergyAsset` に以下を追加し scenario から取り込み:
      - `grid_to_bess_price_threshold_yen_per_kwh`
      - `grid_to_bess_allowed_slot_indices`
      - `bess_terminal_soc_min_kwh`
  - `scripts/build_depot_energy_case.py`
    - 上記パラメータを CLI から生成可能に拡張。

- **テスト**:
  - 追加: `tests/test_evaluator_co2_from_actual_grid_import.py`
  - 追加: `tests/test_problem_builder_depot_energy_asset_controls.py`
  - 実行:
    - `pytest tests/test_problem_builder_depot_energy_asset_controls.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `7 passed`

### [DEV-2026-03-24] BFF/Tk/exporter に最終電力費・仮残高と営業所フロー出力を反映

- **目的**:
  - 最適化で導入した `electricity_cost_final` / provisional 残高を API・UI・レポートに貫通させる。
  - solver 出力に営業所フロー列 (`grid_to_bus`, `bess_to_bus`, `pv_to_bess`, `grid_to_bess`) を追加する。
  - 実データで Case0〜3 を一括比較する runner を追加する。

- **主変更**:
  - `bff/mappers/solver_results.py`
    - simulation payload に `electricity_cost_basis` / `electricity_cost_provisional_jpy` /
      `electricity_cost_charged_jpy` / `electricity_cost_provisional_leftover_jpy` を追加。
  - `bff/routers/optimization.py`
    - `cost_breakdown` に `electricity_cost_final` / provisional 残高 / depot energy flow 集計キーを追加。
  - `bff/services/experiment_reports.py`
    - 実験ログ用 payload で `electricity_cost_jpy` を最終値ベース化し、
      provisional 残高とフロー KPI を追加。
  - `tools/scenario_backup_tk.py`
    - Summary/Compare に `electricity_cost_final` と `electricity_cost_provisional_leftover` を表示。
  - `src/result_exporter.py`
    - `depot_energy_flows.csv` / `depot_energy_flows.json` を追加。
    - `experiment_report.md` に最終/仮/充電実績/仮残高の電力費行を追加。
  - `scripts/run_depot_energy_case_matrix.py`（新規）
    - scenario JSON を入力に Case0〜3 を連続実行し、
      `case_matrix_summary.csv` / `case_matrix_results.json` を出力。

### [DEV-2026-03-24] core_pv B案: 営業所別 PV→BESS→EV 充電モデルと仮コスト上書き会計を導入

- **目的**:
  - 従来の `系統 + PV = 充電需要` 1本モデルを、営業所別の `PV→BESS→Bus` / `Grid→Bus` / `Grid→BESS` フローへ拡張。
  - 電力費を「走行時仮計上」から「充電実績 source ベース上書き」へ移行。

- **主変更**:
  - `src/optimization/common/problem.py`
    - `DepotEnergyAsset` 追加。
    - `CanonicalOptimizationProblem.depot_energy_assets` 追加。
    - `AssignmentPlan` に営業所×スロットのエネルギーフロー出力（grid_to_bus, bess_to_bus, pv_to_bess, grid_to_bess, pv_curtail, bess_soc）追加。
    - slot 長不一致・BESS初期SOC境界のバリデーション追加。
  - `src/optimization/milp/solver_adapter.py`
    - C15-C21 相当を営業所別フロー制約へ置換。
    - Grid→BESS フラグ (`allow_grid_to_bess`) を制約化。
    - O2 を実充電源ベース（Grid/BESS/c Curtail penalty）へ変更。
    - 解から営業所フロー時系列と source 付き `charging_slots` を復元して `AssignmentPlan` に出力。
  - `src/optimization/common/evaluator.py`
    - 仮計上→充電時FIFO上書きの台帳評価を追加。
    - `electricity_cost_final` / `electricity_cost_provisional_leftover` / `grid_purchase_cost` などを `CostBreakdown` に追加。
    - BESS/PV 資産費（日割）計算と `total_cost_with_assets` 追加。
  - `src/optimization/common/builder.py`
    - シナリオから `depot_energy_assets` を canonical problem へ橋渡し。

- **補助スクリプト追加**:
  - `scripts/build_pv_profiles.py`（Solcast風 CSV から営業所別 slot kWh 作成）
  - `scripts/build_depot_energy_case.py`（Case JSON 雛形生成）

- **ドキュメント更新**:
  - `docs/constant/implementation_status.md` に C22-C27 / O2 実充電源化 を追記。
  - `docs/constant/formulation.md` に B案追補（PV→BESS→Bus, Grid→BESSフラグ）を追記。

- **テスト**:
  - 追加: `tests/test_depot_energy_asset_schema.py`
  - 追加: `tests/test_evaluator_provisional_overwrite.py`
  - 回帰実行:
    - `pytest tests/test_depot_energy_asset_schema.py tests/test_evaluator_provisional_overwrite.py tests/test_bev_energy_accounting.py tests/test_objective_modes.py -q`
    - 結果: `10 passed`

### [DEV-2026-03-24] EV電力コストを「仮計算→充電実績上書き」に変更

- **背景**:
  - BEVが走行していても充電が発生しないケースで、日次報告の電力コスト解釈が分かりにくかった。
  - 充電が発生した場合は、走行時刻ではなく「実際に充電した時刻帯のTOU単価」で評価したい要件がある。

- **対応**:
  - `src/simulator.py` にて、電力コストを二段階で算出する方式へ変更。
    - 1) 走行電力量ベースの仮コストを常時計算 (`provisional_*`)
    - 2) 充電電力量が存在する場合は、充電時刻TOUで再計算した実コスト (`charged_*`) で上書き
  - 採用された計算根拠を `energy_cost_basis` (`provisional_drive` / `charged_energy_override`) として保持。
  - `src/result_exporter.py` の `summary.json` / KPI系JSONに、仮値・実値・採用basisを出力する項目を追加。

- **検証**:
  - `tests/test_bev_energy_accounting.py` に充電実績あり時の上書きテストを追加。
  - `python -m pytest tests/test_bev_energy_accounting.py -q` で `3 passed` を確認。

### [DEV-2026-03-22] Tokyu Bus の route-scoped trip 生成を追加し、21万件 overcount の代替データを分離

- **問題**:
  - `data/catalog-fast/raw/bus_timetable.json` / `busstop_pole_timetable.json` は ODPT top-level 取得の 1000件打ち切り状態で、`catalog-fast` 正規化データ単体では全量 trip を復元できなかった。
  - 一方で既存 `data/built/tokyu_full/trips.parquet` は GTFS family 展開起点の重複を含み、`tripCount` 合計が約 210,704 件まで膨らんでいた。
  - そのまま route 単位選択に使うと、Quick Setup / Prepare / 最適化の対象 trip 数が実運用とかけ離れる。

- **対応**:
  - `scripts/build_tokyu_bus_data.py` を追加し、`data/tokyubus/canonical/<snapshot>/` の完全 snapshot から `data/catalog-fast/tokyu_bus_data/` を生成できるようにした。
  - 出力は global JSONL に加えて route-scoped JSONL を持つ:
    - `route_trips/<route_id>.jsonl`
    - `route_stop_times/<route_id>.jsonl`
    - `route_stop_timetables/<route_id>.jsonl`
  - `route_index.json` / `family_index.json` / `summary.json` も生成し、将来 route 単位ロードへ切り替えやすい補助メタデータを追加した。
  - 再生成時に route-scoped ディレクトリが追記で二重化しないよう、出力ディレクトリ全体を clean してから rebuild するようにした。
  - `src/tokyu_bus_data.py` を追加し、`tokyu_bus_data` から route 別 trip / stop_times / stop timetables / day type 集計を読む補助ローダーを実装した。
  - 既存システムの参照元はこの時点では変更せず、別 agent による `data/catalog-fast` 修正と独立に比較できる状態を維持した。

- **実データ生成結果**:
  - `python scripts/build_tokyu_bus_data.py`
    - source snapshot: `data/tokyubus/canonical/20260311T044200Z`
    - generated counts: `routes=764`, `routesWithTrips=757`, `families=184`, `stops=3084`, `trips=33360`, `stopTimes=583165`
  - route 側 `tripCount` 合計も `33360` で一致し、route file 数は `764` を確認した。
  - 今回は既存参照元維持のため `data/built/tokyu_full` は再生成していない。

- **検証**:
  - `tests/test_tokyu_bus_data.py` を追加し、route-scoped 生成・再実行時の非重複・補助ローダー読込を固定した。
  - `PYTHONPATH=C:\\master-course pytest tests/test_tokyu_bus_data.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py -q`
    で `10 passed` を確認。
  - `.gitignore` に `data/catalog-fast/tokyu_bus_data/` を追加し、生成キャッシュが GitHub に同期されないようにした。
  - 既存参照元維持のため、`src/runtime_scope.py` / `bff/store/trip_store.py` / `bff/services/run_preparation.py` 側でも `trip_id` の `__vN` 重複除外が効くことを追加テストで固定した。
  - `src/tokyu_bus_data.py` / `scripts/build_tokyu_bus_data.py` にも同じ `__vN` 除外を追加し、代替 route-scoped データ経路でも重複 trip が混入しないようにした。

### [DEV-2026-03-22] Gurobi import の誤検知を緩和し、Windows 実行時の runtime bootstrap を追加

- **問題**:
  - `mode_milp_only` 実行時に `solver_result.infeasibility_info = "Gurobi が必要です"` で落ちるケースがあり、`gurobipy` / ライセンス自体は shell から正常でも、BFF 実行時だけ誤って unavailable 扱いになることがあった。
  - `src/model_factory.py` に solver 構築前の不要な `import gurobipy` があり、ここで失敗すると `src.milp_model.build_milp_model()` 側の retry に到達しなかった。

- **対応**:
  - `src/model_factory.py` の不要な `import gurobipy` を削除し、Gurobi import は `src.milp_model.build_milp_model()` 側に一本化した。
  - `src/milp_model.py` に runtime bootstrap を追加し、Windows では `GUROBI_HOME` 候補配下の `bin` を `PATH` / `os.add_dll_directory()` に補完し、`GRB_LICENSE_FILE` も既定候補から自動解決するようにした。
  - さらに `site.getsitepackages()` / `getusersitepackages()` / `sys.prefix` 由来の `site-packages` を solve 時に再探索して `sys.path` へ補完し、`run_app.py` 経由で `No module named 'gurobipy'` になるケースも潰した。
  - `src/pipeline/solve.py` は solver 例外時に例外クラス名を含めて記録するようにし、将来 `GUROBI_UNAVAILABLE` が出ても原因追跡しやすくした。

- **検証**:
  - shell から `gurobipy 13.0.1` import と簡易モデル optimize が通ることを確認した。
  - 弦巻 `WEEKDAY` 実データでも BFF と同じ ProblemData 経路から solver 実行に入り、`GUROBI_UNAVAILABLE` ではなく `TIME_LIMIT` まで進むことを確認した。
  - `tests/test_model_factory_gurobi_import.py` を追加し、`build_model_by_mode()` が直接 `gurobipy` import に依存しないこと、および solve 時の `site-packages` 補完が効くことを固定した。

### [DEV-2026-03-22] Quick Setup が全 route を誤表示し、Prepare が `tripCount=0` になりやすい問題を修正

- **問題**:
  - `tools/scenario_backup_tk.py` の `load_quick_setup()` が `GET /quick-setup` で返した depot-scoped route 一覧を捨てて、
    `GET /routes` の全件一覧で上書きしていた。
  - `bff/store/scenario_store.py` の `candidateRouteIds` が full-matrix `depot_route_permissions` を使っており、
    営業所選択後でも全 route が候補に残りやすかった。
  - その結果、UI では選べるが `trips.parquet` と link していない route を既定選択しやすく、
    Prepare が `tripCount=0` になっていた。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - Quick Setup 読込時に `/quick-setup` の route payload をそのまま使うよう修正し、
      global route 一覧で上書きしないようにした。
    - backend から返る `availableDayTypes` で day type 候補を同期し、
      link 済み route が 0 件のときはログで明示するようにした。
    - Prepare 未完了メッセージも `route / day type / timetable linkage` を確認する文面へ更新した。
  - `bff/store/scenario_store.py`
    - `candidateRouteIds` / `effectiveRouteIds` は selected depot 配下の route を基準に計算するよう修正し、
      full-matrix permission で候補を拡張しないようにした。
  - `bff/routers/scenarios.py`, `bff/services/simulation_builder.py`, `bff/services/route_linking.py`
    - `trips.parquet` の route link 数を読み、Quick Setup の `tripCount` と既定選択を trip-linked subset に揃えた。
    - builder 側も未リンク route を自動採用しないようにし、false positive な route 選択を避けるようにした。

- **検証**:
  - `tests/test_quick_setup_route_selection.py`
    - selected depot assignment で route list が絞られる回帰
    - Quick Setup payload が trip-linked route だけを既定選択する回帰
    を追加。
  - `tests/test_scenario_store_dispatch_scope_overlay.py`
    - full-matrix permission が candidate route を全件化しない回帰
    を追加。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `28 passed` を確認。

### [DEV-2026-03-22] Quick Setup の路線選択を系統単位 UI に変更し、variant 個別除外を保持

- **問題**:
  - `tools/scenario_backup_tk.py` の Quick Setup 路線一覧は営業所配下に raw route をフラット表示しており、
    同じ系統番号でも本線・区間便・入出庫便の関係が見えにくかった。
  - family 単位でまとめて見たい一方、将来的には特定シナリオで「入出庫便だけ外す」「区間便だけ外す」を保存したかった。
  - `PUT /quick-setup` は `selectedRouteIds` をそのまま `includeRouteIds` へ入れていたため、
    `refine` モードでは営業所配下の route が再び全部有効になりやすく、
    個別 route の除外が保持されにくかった。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - 営業所配下の route を `routeFamilyCode` 単位で折りたたみ表示する family grouping を追加。
    - family header は NFKC 正規化で系統番号の数字を半角表示。
    - family header のチェックで系統内 variant を一括選択/解除、展開後は raw variant を個別選択/解除できるようにした。
    - `include` モードで読み込んだ初期選択は、同一 family の route をまとめて既定選択へ展開するようにした。
  - `bff/routers/scenarios.py`
    - Quick Setup payload の `dispatchScope` に `routeSelectionMode` を追加。
    - `update_quick_setup()` は `selectedRouteIds` を `refine + excludeRouteIds` へ変換する helper を使うよう変更し、
      営業所の既定 family 全選択を維持しながら、個別 variant の除外を保存できるようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py`
    - half-width family code 展開
    - family grouping
    を追加。
  - `tests/test_quick_setup_route_selection.py`
    - unchecked route が `excludeRouteIds` に落ちる回帰
    - selected depot 外の route が `includeRouteIds` として保持される回帰
    を追加。
  - `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_quick_setup_route_selection.py tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `28 passed` を確認。

### [DEV-2026-03-22] route family を dispatch / Prepare / 最適化の terminal deadhead 補完へ反映

- **問題**:
  - route family 派生情報は route DTO には載っていたが、実行系では主に表示メタデータ扱いで、
    上り下り・本線・区間便・入出庫便の接続可否や回送候補生成に十分反映されていなかった。
  - さらに dispatch の `Trip` は `origin` / `destination` に stop 名を持ち、
    `deadhead_rules` は `from_stop` / `to_stop` として stop_id を持っていたため、
    明示 deadhead rule も一致しにくかった。

- **対応**:
  - `src/route_family_runtime.py` を追加し、
    detailed variant 正規化（`main_outbound`, `main_inbound`, `depot_out`, `depot_in` など）と
    same-family terminal stop の座標ベース deadhead 補完を共通化した。
  - `src/dispatch/models.py`, `src/data_schema.py`
    - `Trip` / `Task` に `origin_stop_id`, `destination_stop_id` を追加。
  - `src/dispatch/feasibility.py`
    - 接続判定は stop 名より stop_id を優先して参照するよう変更。
  - `bff/routers/graph.py`, `bff/mappers/scenario_to_problemdata.py`,
    `src/optimization/common/builder.py`
    - same-family terminal deadhead 補完を dispatch / Prepare / optimization builder 全経路へ適用。
    - route family / variant 情報を Trip/Task に詳細値のまま保持するよう修正。
  - `src/dispatch/problemdata_adapter.py`
    - `TravelConnection.deadhead_distance_km` に推定 deadhead 距離を載せるよう変更。
  - `bff/routers/master_data.py`, `bff/routers/scenarios.py`, `tools/scenario_backup_tk.py`
    - variant 正規化の collapse をやめ、manual label / API 応答でも detailed variant を保持するよう修正。
  - `src/tokyu_shard_loader.py`
    - dispatch trip rows に `origin_stop_id` / `destination_stop_id` を残すよう修正。

- **検証**:
  - `tests/test_route_family_deadhead_inference.py` を追加。
    - detailed variant 正規化
    - Prepare 経由の same-family terminal deadhead 補完
    - graph context での stop_id ベース接続
    を回帰化した。
  - `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `24 passed` を確認。

### [DEV-2026-03-22] `python run_app.py` 起動直後の Tk callback crash 修正

- **問題**:
  - `tools/scenario_backup_tk.py` は scenario 一覧更新直後に `on_scenario_changed()` を呼んでいたが、
    車両・テンプレート管理ウィンドウをまだ開いていない状態でも
    `refresh_vehicles()` / `refresh_templates()` を実行していた。
  - そのため `fleet_depot_var` / `template_tree` 未生成のままアクセスし、
    `AttributeError` で Tk callback が繰り返し落ちていた。
  - さらに background thread の完了通知が root close 後に `root.after()` へ戻ると、
    `RuntimeError: main thread is not in main loop` が出る経路があった。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - fleet/template 関連 widget を `None` 初期化し、
      `_fleet_window_ready()` / `_vehicle_panel_ready()` / `_template_panel_ready()` を追加。
    - `on_scenario_changed()` は fleet window が開いている場合だけ
      `refresh_vehicles()` / `refresh_templates()` を呼ぶよう修正。
    - `refresh_vehicles()` / `refresh_templates()` の実行前後で
      widget 生存確認を行い、遅延 callback でも destroyed widget に触れないよう修正。
    - fleet window close 時に widget 参照をリセットする `WM_DELETE_WINDOW` ハンドラを追加。
    - プログラム起動直後の自動 scenario 選択では `messagebox.showinfo()` を出さないようにした。
    - `run_bg()` の UI 戻しを `_queue_on_ui_thread()` 経由に変更し、
      root close 後の `after()` 失敗を握りつぶすようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py` に
    fleet window 未生成時の `refresh_*()` / `on_scenario_changed()` が no-op で落ちない回帰を追加。
  - 同テストに `_queue_on_ui_thread()` の closed root / broken after 回帰を追加。
  - `python run_app.py` 起動時に `fleet_depot_var` / `template_tree` の `AttributeError` が出ないことを確認。

### [DEV-2026-03-22] Quick Setup の路線一覧を catalog-fast 優先へ変更

- **問題**:
  - `build_dataset_bootstrap("tokyu_full")` は `routes.parquet` と trip-backed route ids を基準に route inventory を作っており、
    Quick Setup の路線一覧が 21 路線程度に縮んでいた。
  - 一方で `data/catalog-fast/normalized/routes.jsonl` には 764 route pattern があり、
    UI ではこの inventory を常時見られる必要があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - `data/catalog-fast/normalized/routes.jsonl` を読む `_read_jsonl_rows()` /
      `_load_catalog_fast_routes()` を追加。
    - dataset bootstrap の route inventory は catalog-fast normalized routes を優先し、
      `dispatch_scope.routeSelection.includeRouteIds` / `scenario_overlay.route_ids` は
      trip-backed subset のみに絞るようにした。
    - これにより Quick Setup は catalog-fast 全 route を表示しつつ、
      初期選択は現行 timetable/trip が存在する route に限定される。
  - `bff/services/master_defaults.py`, `bff/store/scenario_store.py`
    - 既存 scenario の runtime alignment 判定を拡張し、
      現在の route/depot master が preload runtime master の proper subset の場合も自動補正するようにした。
  - `README.md`
    - 路線一覧は `data/catalog-fast/normalized/routes.jsonl` 優先であること、
      一覧件数と初期選択件数が一致しない場合があることを追記。

- **検証**:
  - `build_dataset_bootstrap("tokyu_full")` が `routes > selectedRouteIds` を返すことを確認。
  - `tests/test_research_dataset_bootstrap_alignment.py` に
    catalog-fast route inventory 回帰を追加。
  - `tests/test_scenario_store_dispatch_scope_overlay.py` に
    runtime master superset 差分で alignment が必要になるケースを追加。

### [DEV-2026-03-22] Quick Setup の営業所一覧が一部しか出ない問題を修正

- **問題**:
  - `build_dataset_bootstrap("tokyu_full")` が trip-backed route 文脈に合わせて `depots` 自体を削っており、
    Quick Setup の営業所一覧が `ebara / aobadai / nijigaoka` など一部しか出なくなっていた。
  - ただし実データの seed 定義では `tokyu_full` は 12 営業所を持っており、
    UI で営業所管理や選択確認をするには一覧自体は全件見える必要があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - bootstrap の `depots` は dataset 定義どおり保持し、
      route 文脈で絞った depot 集合は `dispatch_scope.depotSelection.depotIds` /
      `scenario_overlay.depot_ids` の既定選択だけに使うよう修正。
  - `bff/services/master_defaults.py`
    - stale scenario 補正時の `valid_depot_ids` を
      bootstrap の `dispatch_scope.depotSelection.depotIds` 優先に変更し、
      表示対象 depot は広く保ちつつ、実行不能な旧選択 depot は引き続き自動解除されるようにした。
  - `README.md`
    - Quick Setup の営業所一覧は全営業所を表示し、
      `routeCount=0` の営業所は runtime で route 未展開であることを追記。

- **検証**:
  - `build_dataset_bootstrap("tokyu_full")` で `depots` が dataset 定義の全営業所を返し、
    `dispatch_scope.depotSelection.depotIds` はその部分集合になることを確認。
  - `tests/test_research_dataset_bootstrap_alignment.py` に営業所表示回帰を追加。
  - `tests/test_master_defaults_runtime_repair.py` に
    「表示対象 depot は残すが stale selection は解除される」ケースを追加。

### [DEV-2026-03-21] README 使用方法更新と Tk dataset 候補の runtime-ready 化

- **問題**:
  - `README.md` の早見表が下位章の並びと 1 対 1 で対応しておらず、使用方法の参照導線が実装現況とずれていた。
  - README 内に `Quick Setup 保存 -> scenario_overlay に保存` とある箇所が残っており、
    実装済みの `dispatch_scope` 同期保存と食い違っていた。
  - `tools/scenario_backup_tk.py` の dataset 候補は `/api/app/datasets` の全件をそのまま表示しており、
    runtime 未整備 dataset をユーザーが新規 scenario に選べてしまっていた。

- **対応**:
  - `README.md`
    - 早見表を「要約 + 1章〜11章」の各節対応に更新。
    - `4.4 初回接続時の使い方` を追加し、`接続確認`、dataset 候補、Quick Setup 読込、
      stale scenario 補正後の選び直し手順を明記。
    - Quick Setup 保存先を `dispatch_scope / scenario_overlay` の同期保存に修正。
    - データセット配置の説明を `data/built/{dataset_id}/` 基準へ更新し、
      既定 runtime dataset が `tokyu_full` であることを追記。
    - API 導線に `GET /api/app/datasets` と `GET /api/app/data-status` を追加。
  - `tools/scenario_backup_tk.py`
    - `/api/app/datasets` の `runtimeReady` / `builtReady` / `shardReady` を見て、
      runtime 実行可能な dataset を優先表示するよう修正。
    - runtime-ready dataset が 1 件もない場合だけ全候補へ fallback するようにした。
    - scenario 作成ログに requested / effective datasetId を表示し、
      backend の fallback を確認しやすくした。
    - Quick Setup 読込時に depot/route の総数と選択数をログへ表示するようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py` を追加し、
    `runtimeReady` 優先と全候補 fallback の 2 ケースを確認できるようにした。
  - README の記述が 2026-03-21 時点の runtime 補正挙動と一致することを目視確認。

### [DEV-2026-03-21] Prepared実行 timeout の原因修正（simulation job submit の自己デッドロック）

- **問題**:
  - `POST /api/scenarios/{id}/simulation/run` が `job_id` を返す前に長時間停止し、
    Tk の `Prepared実行` が timeout していた。
  - `bff/routers/simulation.py` の `_submit_simulation_job()` は
    `_SIMULATION_FUTURE_LOCK` を保持したまま `_get_simulation_executor()` を呼び、
    `threading.Lock` の自己再取得でデッドロックしていた。
  - prepared run 前の再検証が `get_scenario_document()` を読んでいたため、
    heavy artifact 差分で `prepared_input_id` hash が不安定になりやすく、
    前段処理も不要に重かった。
  - `tools/scenario_backup_tk.py` の `/simulation/run` は明示 timeout 未設定で、
    既定 45 秒待ちに依存していた。

- **対応**:
  - `bff/routers/simulation.py`
    - `_SIMULATION_FUTURE_LOCK` を `threading.RLock` へ変更し、job submit の自己デッドロックを解消。
    - simulation executor に `BFF_SIM_EXECUTOR` を追加し、
      Windows 既定を `thread` モードへ変更。
    - `run_prepared_simulation()` / `run_simulation()` の prepared validation を
      `get_scenario_document_shallow()` 基準へ変更。
  - `bff/services/simulation_builder.py`
    - `apply_builder_configuration()` を shallow load 基準に変更し、
      prepare 時に timetable / graph / result artifact を読まないようにした。
  - `bff/routers/optimization.py`
    - `run_optimization()` / `reoptimize()` でも
      `get_or_build_run_preparation()` 呼び出し前に shallow doc を使うよう統一した。
  - `bff/services/run_preparation.py`
    - `prepared_input_id` hash の volatile key に
      `timetable_rows` / `stop_timetables` / `trips` / `graph` / `blocks` / `duties` /
      `dispatch_plan` / `simulation_result` / `optimization_result` / `meta` / `stats` / `refs`
      を追加し、shallow/full load 差分で hash が揺れないようにした。
  - `tools/scenario_backup_tk.py`
    - `/simulation/run` の client timeout を `180` 秒へ明示した。

- **検証**:
  - ローカル実測で `_submit_simulation_job` は `0.001s` で返ることを確認。
  - `run_prepared_simulation()` は `job_id` を約 `1.5s` で返すことを確認。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py -q`
    で `4 passed` を確認。

### [DEV-2026-03-21] 最適化/Prepare の front-run mismatch 修正（stale dataset bootstrap + dispatch_scope 優先）

- **問題**:
  - `tokyu_dispatch_ready` はこの clone では runtime 用 `trips.parquet` を持たず、scenario bootstrap が seed-only (`44 routes / 0 trips`) になっていた。
  - その状態で作られた既存 scenario は、フロントで選べる route/depot と runtime 実行時の built dataset (`tokyu_full`) が食い違い、Prepare/最適化が `trip_count=0` になりやすかった。
  - さらに `src/runtime_scope.py` は `dispatch_scope` より `scenario_overlay.route_ids / depot_ids` を優先していたため、Quick Setup 保存後の route 選択が実行時に無視される条件があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - `build_dataset_bootstrap()` を修正し、要求 dataset が runtime 未整備で trip-backed data を返せない場合は、
      `tokyu_full` へ自動フォールバックするようにした。
    - `feed_context.requestedDatasetId` / `dataset_status.fallbackDatasetId` を付与し、fallback 発生を追跡可能にした。
  - `bff/services/master_defaults.py`
    - preloaded master data の `datasetId` を bootstrap の実効 dataset から返すよう修正。
    - `repair_missing_master_data()` を拡張し、runtime に存在しない stale route/depot master を
      実効 dataset の master へリベースしつつ、solver config などの scenario overlay は保持するようにした。
  - `bff/store/scenario_store.py`
    - `ensure_runtime_master_data()` を追加し、既存 scenario の stale master を必要時に永続補正できるようにした。
    - `set_dispatch_scope()` で `scenario_overlay.depot_ids / route_ids` も同期し、
      実行時 scope と UI 保存状態が乖離しないようにした。
  - `src/runtime_scope.py`
    - `resolve_scope()` を修正し、`scenario_overlay` より `dispatch_scope` の選択 route/depot を優先するようにした。
  - `bff/routers/scenarios.py`, `bff/routers/master_data.py`, `bff/routers/simulation.py`, `bff/routers/optimization.py`
    - editor bootstrap / quick setup / master-data read / prepare / simulation / optimization の入口で
      `ensure_runtime_master_data()` を通すようにし、フロントから stale master を見えないようにした。

- **効果**:
  - 新規 scenario 作成時に runtime 未整備 dataset を選んでも、実行可能な runtime master に揃う。
  - 既存 stale scenario を開いた際も、フロントが runtime に存在しない route/depot を出さなくなる。
  - Quick Setup 保存後の route/depot 選択が Prepare / Prepared実行 / 最適化にそのまま反映される。

- **検証**:
  - `build_dataset_bootstrap("tokyu_dispatch_ready")` が
    `feed_context.datasetId="tokyu_full"`, `routes=21`, `depots=3`, `trips=1000` を返すことを確認。
  - `get_preloaded_master_data("tokyu_dispatch_ready")` が `datasetId="tokyu_full"` を返すことを確認。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py -q`
    で `12 passed` を確認。

### [DEV-2026-03-18] Prepare時の台数決定を営業所在庫ベースへ変更（Basic Parameters廃止）

- **背景課題**:
  - Tk の `Basic Parameters` で手入力した車両台数/充電器台数が、営業所に既に設定した実在庫と乖離しやすかった。
  - SOC関連が `Cost / Tariff` と別枠で分かれており、運用上の入力導線が分散していた。

- **対応**:
  - `bff/routers/simulation.py` の `PrepareSimulationSettingsBody` に以下を追加:
    - `soc_min`, `soc_max`
    - `use_selected_depot_vehicle_inventory`
    - `use_selected_depot_charger_inventory`
  - `bff/services/simulation_builder.py` を更新し、Prepare時に
    - 選択営業所の既存 `vehicles` を優先採用
    - 選択営業所の既存 `chargers`（無い場合は depot charger 設定から生成）を優先採用
    - BEVへ `initial_soc` と `soc_min/soc_max` を反映
    するロジックへ変更。
  - `tools/scenario_backup_tk.py` を更新し、
    - `Basic Parameters` セクションを削除
    - `Cost / Tariff Parameters` 内に `initial_soc`, `soc_min`, `soc_max` を移設
    - Prepare payload で営業所在庫利用フラグを常時 `true` 送信
    するよう変更。

- **効果**:
  - シミュレーション車両台数・充電器台数は「選択営業所に設定済みの実在庫」に自動一致。
  - 初期SOCとバッファSOC下限/上限を同一UI群で設定でき、運用が単純化。

- **追加対応（同日）**:
  - `POST /scenarios/{id}/simulation/prepare` のレスポンスに
    `vehicleCount` / `chargerCount` を追加。
  - Tk の Prepare完了ログに `Prepare採用台数: vehicles=... / chargers=...` を表示。
  - Tk 実行パネルに推奨手順（保存→Prepare→最適化）を明記し、Prepare未実行で最適化画面を開く際はログで注意を表示。

### [DEV-2026-03-18] BUILT_DATASET_REQUIRED の復旧導線を catalog-fast 基準へ更新

- **背景課題**:
  - 他PC clone 環境で `BUILT_DATASET_REQUIRED` が発生した際、`tokyu_core` 固定の案内だけでは復旧が遅れた。
  - 実際には `data/catalog-fast` に再構築元が存在するケースがある。

- **対応**:
  - `bff/dependencies.py` の 503メッセージを更新し、
    `data/catalog-fast` からの built 再生成コマンドを明示。
  - `tools/scenario_backup_tk.py` のエラーダイアログにも同コマンドを表示。
  - `README.md` の 503対処手順に catalog-fast 起点の再生成手順を追加。

- **効果**:
  - `tokyu_core` が未配置でも、`data/catalog-fast` があれば復旧手順を即実行できる。

- **追加対応（同日）**:
  - coreパッケージに `data-prep` / `tokyubus_gtfs` が同梱されていない環境で
    `python catalog_update_app.py refresh gtfs-pipeline --source-dir data/catalog-fast ...` が
    `ModuleNotFoundError: tokyubus_gtfs` で停止する問題を修正。
  - `catalog_update_app.py` に fallback を実装し、
    `data/catalog-fast/normalized/*.jsonl` から `data/built/{dataset}` の parquet + manifest を
    直接再生成できるようにした。
  - 実行結果に `pipeline_fallback=true` を付与して、fallback経路での成功を判別可能にした。
  - 既定datasetを `tokyu_core` 依存から外すため、
    `src/research_dataset_loader.py` と `bff/services/app_cache.py` の default を `tokyu_full` へ変更。

### [DEV-2026-03-18] Tkinter UI/UX 改善 + Tk/BFF 不整合の解消

- **背景課題**:
  - Tkで新規シナリオ作成時に `POST /api/scenarios` が 404 となるケースがあり、実体は datasetId 不一致由来だった。
  - タグ付与アプリで見える路線数に対し、Tkの路線表示が欠けるケースがあった（`quick-setup` の routeLimit 依存）。
  - 車両管理、営業所充電器設定、ソルバー設定が分散し、操作導線が重かった。

- **対応**:
  - `tools/scenario_backup_tk.py` で datasetId を `/api/app/datasets` 候補選択化。
  - 新規シナリオ作成時の既定datasetを `tokyu_full`（東急バス全体）優先へ変更。
  - シナリオ作成エラー表示を改善し、dataset候補を提示。
  - 路線表示を `/api/scenarios/{id}/routes` 優先に変更し、欠落率を低減。
  - 営業所/路線選択UIを営業所折りたたみ + 実Checkbuttonへ置換。
  - メインに `営業所別車両管理` ボタンを追加し、専用画面で営業所充電器設定を編集可能化。
  - スコープの `day_type`（運行種別）をプルダウン選択へ変更。
  - 右側車両管理の営業所選択・複製先営業所をプルダウン選択へ変更。
  - `詳細設定画面を開く` を追加し、旧 Advanced 設定とソルバー設定を別画面へ集約。
  - 設定画面でソルバーモード別にパラメータ表示を切替。
  - 車両/テンプレートの新規追加は専用ダイアログ（別画面）へ分離。
  - テンプレート作成時に「作成後に営業所へ何台追加するか」を同ダイアログで指定可能化。
  - 車両編集フォームとテンプレート編集フォームを日本語ラベル化。
  - 車両編集・テンプレート編集で EV/ICE に応じて該当パラメータのみ表示。
  - シナリオ選択時に完了メッセージを表示。
  - 画面上部に `シナリオ設定を保存` ボタンを追加し、編集内容の保存導線を明確化。
  - Prepare / Prepared / 最適化の開始時メッセージを追加。
  - 最適化実行は専用モニター画面へ遷移し、進捗%・ステータス・PowerShell風ログを表示。
  - `シミュレーション実行(legacy)` ボタンを通常運用画面から非表示化。
  - 最適化設定に `終了まで待つ` オプションを追加（長時間タイムリミットを適用）。
  - 最適化設定に `dispatch再構築（重い）` オプションを追加し、軽量起動を選択可能化。
  - 最適化開始APIのクライアント側タイムアウトを延長し、開始時タイムアウトを低減。
  - `PUT /quick-setup` 保存時、Windowsのファイルロックにより rename が失敗するケースに対し、
    `bff/store/scenario_store.py` に WinError 5/32 用の非原子的フォールバック保存を追加。
  - 他PC clone 環境での `simulation/prepare`・`run-optimization` の 503 は
    `BUILT_DATASET_REQUIRED` が主因になり得るため、READMEに `built_ready` 確認手順を追記。
  - READMEに Gurobi (MILP) の最小動作確認コマンドを追記。

- **確認**:
  - `python -m py_compile tools/scenario_backup_tk.py` で構文エラーなし。

### [DEV-2026-03-18] Timetable整合監査の自動化（第三者追試向け）

- **背景課題**:
  - 教員レビュー用に、`timetable_rows` 件数・`unserved_trip_ids` 件数・採用便の departure/arrival 一致率を実測値で提示する必要があった。
  - 既存のログ確認だけでは、入力ファイルと結果ファイルの突合根拠が散在していた。

- **対応**:
  - `scripts/audit_timetable_alignment.py` を追加し、prepared input と optimization result を突合する監査を自動化。
  - JSON/CSV/Markdown の3形式で監査成果物を出力。
  - 追加指標として `checked_coverage_rate` と `day_tag_match` を導入し、曜日不整合ケースを品質判定から除外可能にした。
  - 提出用文書 `docs/reproduction/timetable_alignment_audit_20260318.md` を作成。

- **出力先**:
  - `outputs/audit/bbe1e1bd/timetable_alignment_audit.{json,csv,md}`（WEEKDAY）
  - `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.{json,csv,md}`（SAT比較）

- **主結果（WEEKDAY）**:
  - `timetable_rows_count = 1010`
  - `unserved_trip_count = 0`
  - `departure_arrival_match_rate = 100.0%`
  - `checked_coverage_rate = 100.0%`
  - `day_tag_match = true`

- **注意（SAT比較）**:
  - `day_tag_match = false`（prepared=Weekday, result=Saturday）
  - このため SAT 側の一致率は品質判定に使わず、入力不整合検知の証跡として扱う。

### [DEV-2026-03-15] Simulation Input Builder 化の第1段（lite bootstrap + depot-scoped 権限 + invalidate 範囲縮小）

- **背景課題**:
  - Planning 画面の初期ロードが `editor-bootstrap` 前提で広すぎ、summary-first 設計と乖離していた。
  - DepotRouteMatrix が depot 単位 UI にもかかわらず、全 depots / 全 route-families / 全 permissions を取得していた。
  - 営業所・車両・permission 更新で dispatch/graph/simulation/optimization まで即 invalidate しており、
    微小編集でも待ち時間が増える構造だった。

- **対応（Backend）**:
  - `bff/routers/scenarios.py`
    - `GET /scenarios/{id}/editor-bootstrap-lite` を追加。
    - 共通 builder `_build_editor_bootstrap_payload()` を導入し、
      - full: `editor-bootstrap`
      - lite: `editor-bootstrap-lite`
      を同じ整形ロジックで返す構成に変更。
    - lite では `routes`, `vehicleTemplates`, `depotRouteIndex`, `availableDayTypes`, `builderDefaults` を返さず、
      `scenario + dispatchScope + depots + depotRouteSummary` 中心の summary payload に限定。
  - `bff/routers/master_data.py`
    - `GET /scenarios/{id}/route-families` に `depotId` query を追加（depot-scoped route family 取得）。
    - `GET /scenarios/{id}/depots/{depotId}/route-family-permissions` を追加。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - 初期取得を `useEditorBootstrapLite()` へ切替。
  - `frontend/src/hooks/use-scenario.ts`, `frontend/src/api/scenario.ts`
    - `editor-bootstrap-lite` 用の query key / API client / hook を追加。
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - 全体取得をやめ、`depotId` スコープの
      - route families
      - depot route-family permissions
      のみ取得するよう変更。
  - `frontend/src/hooks/use-master-data.ts`, `frontend/src/api/master-data.ts`
    - `useRouteFamiliesScoped(...)` と depot-scoped permissions API を追加。
    - 既存 update mutation（depot/vehicle/route/permission/stop import 等）から
      `invalidateDispatchOutputs(...)` を除去し、即時の重い再同期を停止。

- **型更新**:
  - `frontend/src/types/domain.ts`
    - `EditorBootstrapLite` 型を追加。
  - `frontend/src/types/api.ts`, `frontend/src/types/index.ts`
    - `EditorBootstrapLiteResponse` を追加。

- **期待効果**:
  - Planning 初期表示時の payload と query 本数を削減。
  - 営業所タブの詳細操作が depot 単位に閉じ、全体取得を回避。
  - 微小な master 編集で dispatch/optimization 系キャッシュを揺らさないため、
    体感の待ち時間を大幅に減らす基盤を確立。

### [DEV-2026-03-15] Simulation Input Builder 化の第2段（Dispatch Scope を draft→保存に変更）

- **背景課題**:
  - Planning の「配車スコープ設定」がトグル変更のたびに即 `PATCH /dispatch-scope` を発行していた。
  - 微小編集でも network + invalidation が発生し、Builder 操作の連続性を損なっていた。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - Dispatch Scope を即時保存から **local draft + 明示保存** に変更。
    - トグルはローカル state (`scopeDraft`) のみ更新。
    - `保存` ボタン押下時のみ `useUpdateDispatchScope().mutate(...)` を実行。
    - `破棄` ボタンで bootstrap 起点値へ復元。
    - `未保存の変更あり` / `保存済み` 表示を追加。

- **関連改善**:
  - `frontend/src/hooks/use-master-data.ts`
    - `routeKeys.families` の key を `{ operator, depotId }` へ正規化。
  - `bff/routers/master_data.py` + `frontend/src/api/master-data.ts`
    - route family の depot filter (`depotId`) を利用する depot-scoped 流れに統一。

- **期待効果**:
  - スコープ調整中に不要な即時同期を発生させず、入力体験を builder 型に近づける。
  - 保存タイミングをユーザー主導にし、1操作ごとの待ち時間を抑制。

### [DEV-2026-03-15] Simulation Input Builder 化の第3段（Permission Matrix を draft→保存に変更）

- **背景課題**:
  - 営業所-路線許可 / 車両-路線許可の行列が、チェック1回ごとに即 mutation されていた。
  - 「行列調整中に毎回保存」が発生し、操作体験が重くなる要因だった。

- **対応（Frontend）**:
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - チェック操作を local draft に反映する方式へ変更。
    - `保存` で dirty family 分だけ一括送信。
    - `破棄` でサーバ状態へ復元。
  - `frontend/src/features/planning/VehicleRouteMatrix.tsx`
    - 同様に vehicle x routeFamily 行列を draft 方式へ変更。
    - dirty pair（vehicleId:routeFamilyId）単位で保存 payload を構成。

- **対応（API / Hook）**:
  - `bff/routers/master_data.py`
    - `GET /scenarios/{id}/depots/{depotId}/vehicle-route-family-permissions` 追加。
  - `frontend/src/api/master-data.ts`
    - depot-scoped vehicle-family permissions API client を追加。
  - `frontend/src/hooks/use-master-data.ts`
    - `useVehicleRouteFamilyPermissionsForDepot(...)` 追加。
  - `frontend/src/hooks/index.ts`
    - 上記 hook を export。

- **期待効果**:
  - permission matrix 編集中の即時同期を止め、入力の連続性を改善。
  - depot-scoped 取得で読み込み範囲を局所化し、タブ体感速度を改善。

### [DEV-2026-03-15] Simulation Input Builder 化の第4段（未保存変更の可視化と離脱ガード）

- **背景課題**:
  - scope / permission の draft 方式は導入済みだが、画面全体で「未保存状態」を横断把握しづらかった。
  - ページ離脱時に未保存編集が失われるリスクがあった。

- **対応（Frontend）**:
  - `frontend/src/stores/planning-draft-store.ts` を新規追加。
    - scenario 単位で以下の dirty flag を保持。
      - `scope`
      - `depotPermissions`
      - `vehiclePermissions`
    - `useHasPlanningDraftChanges(scenarioId)` を追加。
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - ページ上部に「未保存の変更があります」バナーを表示。
    - `beforeunload` で未保存時の離脱ガードを追加。
    - scope 保存/破棄で dirty flag を更新。
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - toggle/save/reset で `depotPermissions` dirty flag を更新。
  - `frontend/src/features/planning/VehicleRouteMatrix.tsx`
    - toggle/save/reset で `vehiclePermissions` dirty flag を更新。

- **期待効果**:
  - Builder 画面で draft が残っているかを常に把握できる。
  - 誤離脱による設定ロストを防止できる。

### [DEV-2026-03-15] Simulation Input Builder 化の第5段（DispatchScopePanel の draft-save 統一 + prepare 直前ガード）

- **背景課題**:
  - `DispatchScopePanel` は checkbox/select 変更ごとに `updateDispatchScope` を即時発火していた。
  - ScenarioOverview 側の prepare 実行時に Planning の未保存 draft を見ずに進められてしまう状態だった。

- **対応（Frontend）**:
  - `frontend/src/features/planning/DispatchScopePanel.tsx`
    - 即時 mutation を廃止し、panel 内 `scopeDraft` で編集。
    - `保存` / `破棄` ボタンを追加。
    - dirty 判定中は `planning-draft-store` の `scope` flag を更新。
    - route/family の candidate + include/exclude から、表示用 effective 集合を draft ベースで再計算。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - `useHasPlanningDraftChanges(scenarioId)` を参照。
    - 未保存 draft がある場合は prepare を無効化し、実行時も alert でブロック。

- **Drawer dirty 集約（可能な範囲）**:
  - `frontend/src/features/planning/DepotEditorDrawer.tsx`
    - 入力変更時に `depotEditor` dirty を立てる。
    - 保存/削除成功時に dirty を解除。
  - `frontend/src/features/planning/VehicleEditorDrawer.tsx`
    - 入力変更時に `vehicleEditor` dirty を立てる。
    - 保存/削除成功時に dirty を解除。
  - `frontend/src/stores/planning-draft-store.ts`
    - `depotEditor` / `vehicleEditor` フラグを追加。

- **期待効果**:
  - DispatchScopePanel でも Builder の「下書き→保存」方針を一貫適用。
  - 未保存入力のまま prepare へ進む事故を防止。
  - drawer 編集を含め、未保存状態を横断的に把握可能。

### [DEV-2026-03-15] Master tab の追加軽量化（不要 query 抑制 + summary API 呼び出し削減）

- **背景課題**:
  - backend 側の高速化後も、実ブラウザでは「depots / vehicles / routes」タブで体感遅延が残るケースがあった。
  - 初期表示や tab 遷移時に、一覧操作に不要な query が走る余地が残っていた。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - `useTimetableSummary` を削除。
    - Header の時刻表件数は `useScenario().stats.timetableRowCount` を使用。
    - これにより master tab 表示時の `/timetable/summary` 呼び出しを削減。
  - `frontend/src/hooks/use-master-data.ts`
    - `useVehicles` に `enabled` オプションを追加。
    - `useDepots/useVehicles/useRoutes/useStops` に `refetchOnWindowFocus: false` を設定し、
      フォーカス復帰時の再取得バーストを抑制。
  - `frontend/src/features/planning/VehicleTableNew.tsx`
    - 営業所未選択時は `useVehicles(..., { enabled: false })` で車両一覧 query を停止。
    - 「営業所を選択してから車両表示」の UX と fetch 条件を一致させた。
  - `frontend/src/pages/planning/MasterLeftPanel.tsx`
    - `activeTab` に応じて depots query を条件実行（stops タブでは読み込まない）。

- **検証**:
  - `npx eslint "src/pages/planning/MasterDataHeader.tsx" "src/hooks/use-master-data.ts" "src/pages/planning/MasterLeftPanel.tsx" "src/features/planning/VehicleTableNew.tsx"` → pass
  - `npm run build` (frontend) → pass

### [DEV-2026-03-15] Master Data の体感速度を改善（営業所編集の即時反映 + ルート一覧軽量化）

- **背景課題**:
  - 「営業所・車両・路線」画面で、営業所編集後の一覧反映が遅い。
  - Header / map 周辺で重い query が先に走り、初期表示と切り替えが重い。
  - `/scenarios/{id}/routes` が一覧用途に対して過剰な enrich 経路を通っていた。

- **対応（Backend）**:
  - `bff/store/scenario_store.py`
    - master-data 操作（depot/vehicle/route update 系）向けに `_save_master_only()` を追加。
      - master DB (`master_data.sqlite`) と slim meta のみ更新。
      - dispatch 無効化が必要な場合は artifact 側をクリアして整合を維持。
      - full `_save()` を回避し、編集応答を短縮。
    - `summarize_route_service_trip_counts()` を追加。
      - timetable sqlite から `route_id x service_id` 集計のみ取得（軽量）。
      - `list_routes()` に `stopCount` を付与。
  - `bff/store/trip_store.py`
    - `summarize_timetable_routes()` を追加（SQL GROUP BY 集計）。
  - `bff/routers/master_data.py`
    - `GET /depots`: `list_routes()` を depot ごとに N 回呼ばない構成へ変更（N+1 解消）。
    - `GET /routes`: 一覧専用の軽量 summary payload に変更。
      - route family 派生情報は保持。
      - `tripCount/serviceTypes/stopCount` は軽量集計で補完。
      - route detail (`GET /routes/{id}`) 側の link 詳細は維持。

- **対応（Frontend）**:
  - `frontend/src/hooks/use-master-data.ts`
    - `useDepots/useStops/useRoute` に `enabled` オプションを追加。
    - `useUpdateDepot` に optimistic update を追加。
      - 保存直後に depots list/detail を即時更新し、反映遅延を解消。
  - `frontend/src/features/planning/RouteMapPanel.tsx`
    - tab / view / selection 条件で query を遅延。
      - route 未選択時に route detail + stops を読まない。
      - depots/vehicles tab で route 系 query を読まない。
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - route/stop 件数を `useScenario().stats` 参照に切替。
      - 起動時の `useRoutes/useStops` を除去し、ヘッダ描画を軽量化。
    - import progress/log を routes/stops タブ時のみ描画（depots/vehicles の不要描画を回避）。
  - `frontend/src/pages/planning/MasterDataPage.tsx`
    - planning tab の warm gate を外して即時描画に変更。
  - `frontend/src/features/planning/RouteTableNew.tsx`
    - 停留所数表示を `stopCount` 優先にし、一覧 API の軽量化に追従。
  - `frontend/src/types/domain.ts`
    - `Route.stopCount`, `Route.serviceTypes`, `Scenario.stats` を型定義に追加。

- **追加高速化（第二段）**:
  - `bff/services/master_defaults.py`
    - dataset bootstrap 補完処理に guard + cache を導入し、既に master が揃っている scenario で
      毎回重い bootstrap 再構築を走らせないよう改善。
  - `bff/store/master_data_store.py`
    - `load_master_collection()` / `save_master_collections()` を追加して collection 単位 I/O を可能化。
  - `bff/store/scenario_store.py`
    - `_save_master_subset()` を追加し、depot/vehicle/route 等の変更で必要 collection のみ更新。
    - `list_*` 系は master_data.sqlite の単一 collection 直接ロードを優先。
    - timetable route集計は row_artifacts fallback まで対応し、summary計算で full load を回避。
  - `bff/routers/scenarios.py`
    - `GET /app/context` の active scenario 名取得を軽量化（meta fallback）。

- **ローカル実測（代表シナリオ）**:
  - `_load_shallow()`:
    - 改善前: 約 4.0-4.5 秒
    - 改善後: 約 0.008 秒
  - `master_data.list_routes()`:
    - 改善後: 約 0.36 秒（136 routes）
  - `scenarios.get_editor_bootstrap()`:
    - 改善後: 約 0.019 秒
  - `scenarios.get_app_context()`:
    - 改善後: 約 0.010 秒

- **検証**:
  - `python -m pytest tests/test_bff_route_family.py tests/test_bff_scenario_store.py tests/test_architecture.py tests/test_performance_contracts.py -q`
    - 結果: `79 passed`
  - `npx eslint "frontend/src/hooks/use-master-data.ts" "frontend/src/pages/planning/MasterDataHeader.tsx" "frontend/src/features/planning/RouteMapPanel.tsx" "frontend/src/features/planning/RouteTableNew.tsx" "frontend/src/types/domain.ts"`
    - 結果: pass
  - `npm run build` (frontend)
    - 結果: pass

### [DEV-2026-03-15] Scenario 一覧で dataset 表示名と複数削除を追加

- **目的**:
  - `Tokyu Bus Research Cases` 画面で dataset ID だけでは判別しにくいため、
    人間向けの表示名を追加して選択しやすくする。
  - scenario 運用時に不要ケースをまとめて整理できるよう、複数同時削除を可能にする。

- **対応** (`frontend/src/pages/scenario/ScenarioListPage.tsx`):
  - Dataset カードに `datasetDisplayName` を導入。
    - 例: `tokyu_core` → `Tokyu Core (4 depots)`
    - 例: `tokyu_full` → `Tokyu Full (all depots)`
    - 生ID (`datasetId`) も副表示として残し、技術的識別子も確認可能にした。
  - Create 時の scenario 名も dataset ごとに自然なタイトルへ調整。
  - Scenario 一覧に選択チェックボックスを追加。
  - 上部に bulk action bar を追加:
    - `Select all`
    - `Clear selected`
    - `Delete selected`
  - 複数削除は `Promise.allSettled` で並列実行し、失敗IDのみ選択を維持して再試行しやすくした。

- **性能配慮**:
  - 選択状態は ID 配列 + `Set` (`useMemo`) で管理し、行単位の `includes` 連発を回避。
  - 複数削除はネットワークI/Oを並列化し、一覧再取得は最後に 1 回の invalidate のみ。
  - 追加した表示名マップは dataset 一覧から `useMemo` で計算。

### [DEV-2026-03-15] Scenario 一覧でシナリオ表示名編集と初期日本語化

- **要望反映**:
  - 「複数削除」だけでなく、Scenario 一覧で **シナリオ表示名を編集可能** にした。
  - `Tokyu Bus Research Cases` 画面の初期表示文言を日本語優先に変更。

- **対応**:
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 各 scenario 行に `表示名を編集` ボタンを追加。
    - 上部に rename editor を表示し、`scenarioApi.update(id, { name })` で保存。
    - 保存後は scenario query を invalidate して一覧へ即反映。
    - 入力が空のときは保存不可。
  - `frontend/src/i18n/index.ts`
    - 初期言語フォールバックを `ja` に変更（保存済み言語がない場合に日本語で起動）。
    - `fallbackLng` も `ja` に設定。
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 見出し/サブテキストを日本語化:
      - `東急バス研究ケース`
      - `Step 1: 事前に用意した Tokyu dataset を選択し、シナリオを作成または開きます。`

- **確認**:
  - `npx eslint "src/pages/scenario/ScenarioListPage.tsx" "src/i18n/index.ts"`
  - `npm run build`
  - いずれも成功。


### [DEV-2026-03-15] Scenario builder に ParamEditor 風クイック導線を統合（最適化実行まで短縮）

- **目的**:
  - シナリオ作成後、初見ユーザーでも `目黒営業所 -> 路線選択 -> prepare -> 最適化` まで迷わず到達できる導線を作る。
  - 既存 Step2 の詳細設定は保持しつつ、性能負荷を増やさない範囲で ParamEditor モックの要点だけを統合する。

- **対応**:
  - `frontend/src/features/planning/ScenarioQuickParamGuide.tsx` を新規追加。
    - 軽量なクイック設定カード（Solver/Object/TimeLimit/ALNS/MIPGap/Fleet/Charger/Demand）を実装。
    - `Balanced / Quick / Robust` のプリセットを追加し、`updateSettings` に patch 適用。
    - selected depot / route / trip の要約と、推定 fleet / charge capacity を同時表示。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - Step1 に `Top 3 by tripCount` 選択ボタンを追加（目黒3路線実行を即時化）。
    - Step2 上部に `ScenarioQuickParamGuide` を配置（詳細フォームは保持）。
    - Step3 に `最適化開始` ボタンを追加し、prepare 済み scope を使って
      `POST /scenarios/{id}/run-optimization` を直接起動する導線を追加。
    - simulation job と optimization job の両方を同画面で表示。
    - prepare後カードから `Optimization view` へのリンクを追加。
  - `frontend/src/features/planning/index.ts`
    - `ScenarioQuickParamGuide` の export を追加。

- **性能配慮**:
  - route 一覧は既存の `visibleRoutes`（summaryベース）を再利用し、追加 API fetch はなし。
  - Top3 選択は `useMemo` 内の既存配列ソートのみ（小規模 index データ対象）。
  - クイックガイドは controlled input + patch 更新のみで、重い計算や副作用は追加しない。


### [DEV-2026-03-15] run-optimization タイムアウトの原因を修正（最適化ジョブ投入の自己デッドロック）

- **問題**:
  - `POST /api/scenarios/{id}/run-optimization` 実行時、job を返す前に API 応答がタイムアウトする事象を確認。
  - 原因は `bff/routers/optimization.py` のロック構造で、
    `_submit_optimization_job()` が `_OPTIMIZATION_FUTURE_LOCK` を保持したまま
    `_get_optimization_executor()` を呼び、同じロックを再取得しようとして自己デッドロックしていた。

- **対応**:
  - `bff/routers/optimization.py`
    - `_OPTIMIZATION_FUTURE_LOCK` を `threading.Lock()` から `threading.RLock()` に変更。
    - 同一スレッドでの再入ロックを許可し、job submit 経路のブロッキングを解消。

- **テスト追加**:
  - `tests/test_bff_optimization_router.py`
    - `test_optimization_future_lock_is_reentrant`
      - 最適化ロックが再入可能ロックであることを確認。
    - `test_submit_optimization_job_does_not_deadlock_on_nested_lock`
      - `submit` を別スレッドで実行し、短時間で復帰することを確認して
        自己デッドロック再発を防止。

- **確認**:
  - `python -m pytest tests/test_bff_optimization_router.py tests/test_bff_simulation_builder.py tests/test_bff_scenario_store.py -q`
  - 結果: `33 passed`

### [DEV-2026-03-15] Simulation Builder の dispatch scope 初期同期を修正

- **問題**:
  - `ScenarioOverviewPage` の builder store は `includeShortTurn` / `includeDepotMoves` /
    `allowIntraDepotRouteSwap` / `allowInterDepotSwap` を固定初期値で持っていた。
  - 既存 scenario の `dispatch_scope` を編集しても、ページ再表示時に builder 側へ反映されず、
    UI表示と backend の scope が乖離する可能性があった。

- **対応**:
  - `frontend/src/stores/simulation-builder-store.ts`
    - `scopeFlagsFromBootstrap()` を追加。
    - `hydrateFromBootstrap()` で `bootstrap.dispatchScope` から以下の初期値を同期するよう修正。
      - `tripSelection.includeShortTurn`
      - `tripSelection.includeDepotMoves`
      - `allowIntraDepotRouteSwap`
      - `allowInterDepotSwap`

- **効果**:
  - シナリオ保存済み `dispatch_scope` を開いたときに、builder のトグル表示と prepare payload が
    scope 実態と一致する。

### [DEV-2026-03-15] Dispatch scope を source-of-truth とする UI/Backend 同期を追加整理

- **問題**:
  - `PUT /scenarios/{id}/dispatch-scope` で `allowIntraDepotRouteSwap` /
    `allowInterDepotSwap` が body schema に定義されておらず、UI から保存しても
    `scenario_store.set_dispatch_scope()` まで値が届かない。
  - builder 画面を開いたまま別画面で scope 更新した場合、同一 scenario 再hydrate時に
    scope フラグが store 側へ再同期されない。
  - `MasterPlanningPage` の tripSelection 更新は `includeDeadhead` を固定 `true` で送っており、
    scope の既存値を上書きしてしまう。

- **対応（scope source-of-truth）**:
  - `bff/routers/scenarios.py`
    - `UpdateDispatchScopeBody` に
      `allowIntraDepotRouteSwap`, `allowInterDepotSwap` を追加。
    - `body.model_dump(exclude_unset=True)` を使用し、未指定項目を不要上書きしない。
  - `bff/store/scenario_store.py`
    - `set_dispatch_scope()` の `next_scope` に swap フラグをマージする処理を追加。
  - `frontend/src/stores/simulation-builder-store.ts`
    - 同一 scenario の再hydrate時にも `dispatchScope` 由来フラグを再同期。
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - `includeDeadhead` を scope から読み取り、tripSelection patch で保持。

- **対応（state責務分離フェーズ1）**:
  - `frontend/src/stores/scenario-draft-store.ts` を新規追加。
    - scenario 別ドラフト state として `selectedDepotIdByScenario` を保持。
  - `frontend/src/features/planning/DepotListPanel.tsx` と
    `frontend/src/pages/planning/MasterPlanningPage.tsx` を
    `ui-store` 依存から `scenario-draft-store` 依存へ移行。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx` で
    builder の選択営業所を scenario draft へ同期。
  - `frontend/src/stores/ui-store.ts` から `selectedDepotId` を除去し、
    global UI state と scenario draft state の責務を分離。

- **テスト追加**:
  - `tests/test_bff_scenario_store.py`
    - `test_dispatch_scope_setter_persists_swap_flags` を追加。
  - `tests/test_bff_simulation_builder.py`
    - `test_prepare_keeps_existing_scope_flags_when_body_does_not_override` を追加。

### [DEV-2026-03-14] `.claude/worktrees/magical-elgamal` の残差分を main へ吸収

- **確認した状態**:
  - `claude/magical-elgamal` branch 自体は `main` と同一 commit で、
    worktree 側には未コミット差分だけが残っていた。
  - 差分の大半は既に main 側へ別経路で反映済みだったため、
    丸ごと checkout すると current main を後退させる恐れがあった。

- **吸収したもの**:
  - `frontend/src/pages/planning/SimulationBuilderPage.tsx`
    - dedicated route wrapper を main 側へ追加し、
      `/simulation-builder` の実体を明示した。
  - `scripts/simulation_profile_cli.py`
    - `_build_parser()` を追加し、CLI parser を個別テスト可能にした。
  - `tests/test_experiment_reports.py`
    - experiment report payload と simulation profile CLI parser の
      最小回帰テストを main 側へ追加した。
  - `README.md`
    - 上記 test の位置を追記。

- **吸収しなかったもの**:
  - `.claude/settings.local.json`
    - ローカル開発設定なので main には取り込まない。
  - worktree 内の旧 `simulation.py` / TS 型差分
    - main 側で既により新しい実装へ再整列済みのため、
      そのままは採用しなかった。

### [DEV-2026-03-14] Simulation builder / experiment logger の実装実態を再整列

- **確認した問題**:
  - 共有された完了報告と実ワークツリーに差分があり、専用 `SimulationBuilderPage` は存在しなかった。
  - simulation 側は `experiment_reports.py` があるにもかかわらず、
    `bff/routers/simulation.py` で実験ログ出力と取得 endpoint が未配線だった。
  - frontend builder defaults と TypeScript 型に
    `alnsIterations`, `randomSeed`, `experimentMethod`, `experimentNotes`
    が無く、backend に保存済みでも UI 側が保持できなかった。
  - `simulation_profile_cli show` は raw JSON をそのまま出すだけで、
    frontend fallback としては条件確認性が弱かった。
  - builder UI の TOU 表示は hour を `/2` しており、0-24 時間帯の表示として誤っていた。

- **対応**:
  - `bff/routers/scenarios.py`
    - builder defaults に `alnsIterations`, `randomSeed`,
      `experimentMethod`, `experimentNotes`, `startTime`,
      `planningHorizonHours` を追加。
  - `bff/routers/simulation.py`
    - simulation 完了時に `log_simulation_experiment()` を呼び、
      `simulation_result.experiment_report` と
      `simulation_audit.experiment_report` を保存するようにした。
    - `GET /api/scenarios/{id}/simulation/experiment-log` を追加。
    - simulation result に `vehicle_count_by_type`, `trip_count_by_type`,
      `trip_count_served` summary を付与した。
  - `bff/services/experiment_reports.py`
    - simulation report に BEV / ICE / total trip counts を含めるよう修正。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - 既存 builder UI を拡張し、
      mixed fleet 編集、TOU band add/remove、grid flat/sell、
      ALNS iterations、random seed、experiment method、
      experiment notes、start time、planning horizon を編集可能にした。
    - TOU 表示を 0-24 hour 表記に修正した。
  - `frontend/src/app/Router.tsx`, `frontend/src/features/layout/Sidebar.tsx`
    - `/scenarios/:id/simulation-builder` alias と
      「シミュレーション設定」サイドバー導線を追加。
  - `frontend/src/types/domain.ts`, `frontend/src/types/api.ts`,
    `frontend/src/stores/simulation-builder-store.ts`
    - 上記 builder パラメータの型・store hydrate を追加。
  - `scripts/simulation_profile_cli.py`
    - `show` を人間向け summary 表示へ変更し、
      depots / routes / fleet / charging / solver / costs / experiment を
      一目で確認できるようにした。
  - `README.md`
    - builder で編集できる条件、experiment logging、CLI fallback の実態を追記。

- **メモ**:
  - この worktree では専用新規 page を別実装するのではなく、
    既存 `ScenarioOverviewPage` を simulation builder 本体として拡張し、
    `simulation-builder` route alias を追加する方針で整えた。
  - full test / build はこのターンでは実施していない。ユーザー指示に合わせ、
    実装整合と説明資料の整備を優先した。

### [DEV-2026-03-14] frontend fallback 用 simulation profile CLI を追加

- **問題**:
  - main frontend が起動できない場合、営業所・路線・車両・料金・solver 条件を
    安全に差し替える手段が scenario JSON 直編集しか無かった。
  - 直編集対象が `dispatch_scope` / `scenario_overlay` / `simulation_config` に分散しており、
    手作業では壊しやすかった。
  - builder 内の charger 生成で `charger_power_kw=0` 分岐時に
    未定義 `template` を参照する latent bug があった。

- **対応**:
  - `bff/services/simulation_builder.py`
    - builder apply ロジックを router から切り出し、CLI からも共通利用可能にした。
    - `random_seed`, `alns_iterations`, `experiment_method`, `experiment_notes`
      を simulation profile から反映可能にした。
    - charger 生成の未定義参照 bug を解消した。
  - `scripts/simulation_profile_cli.py`
    - `export`, `show`, `apply` を追加。
    - export JSON に `_meta.depots`, `_meta.routes_by_depot`,
      `_meta.vehicle_templates` を埋め、frontend 不在でも選択可能にした。
  - `README.md`
    - fallback CLI の使い方を追記。

- **最小確認**:
  - `python -m py_compile ...` で関連 Python 変更の構文確認を実施。
  - `python -m scripts.simulation_profile_cli --help` を確認。
  - smoke として新規 scenario で `export -> JSON 編集 -> apply` を実行し、
    `experiment_method`, `experiment_notes`, `dispatch_scope` が保存されることを確認。

### [DEV-2026-03-14] Meguro 3-route shard runtime / Gurobi 実走確認と cost parameter surfaced

- **実施条件**:
  - depot: `meguro`
  - routes: `tokyu:meguro:さんまバス`, `tokyu:meguro:東98`, `tokyu:meguro:渋72`
  - runtime source: `tokyu_shards`
  - solver: Gurobi (`mode_milp_only`)
  - tariffs: `constant/input_template.json` 相当
    - TOU `00:00-08:00=18`, `08:00-22:00=32`, `22:00-24:00=20`
    - diesel `150 JPY/L`
    - demand charge `1200 JPY/kW`
    - depot power limit `200 kW`

- **確認した問題**:
  - 3路線 scope の最大同時運行は 19 本で、16台 fleet では MILP が infeasible。
    これは shard runtime 不具合ではなく fleet shortage だった。
  - fresh scenario の builder defaults が `constant/input_template.json` を見ず、
    diesel / demand / TOU / depot limit が 0 扱いになっていた。
  - `simulation.prepare` が TOU band を dict のまま overlay へ入れており、
    Pydantic serializer warning を出していた。
  - frontend builder store / prepare payload が
    `objectiveMode`, `allowPartialService`, `unservedPenalty`,
    `fleetTemplates`, cost / CO2 / depot limit / TOU を drop していた。

- **対応**:
  - `src/scenario_overlay.py`
    - `constant/input_template.json` から overlay default を構築する loader を追加。
    - TOU / diesel / demand charge / depot power limit を fresh scenario default に反映。
  - `bff/routers/simulation.py`
    - TOU band を `TimeOfUseBand` として overlay に格納し、serializer warning を解消。
  - `data-prep/pipeline/build_tokyu_shards.py`
    - `distance_hint_km` が trip / pattern に無い場合でも、
      route row の `distance_km` を fallback に使って shard へ残すよう修正。
  - `frontend/src/stores/simulation-builder-store.ts`
    - builder defaults の cost / objective / mixed-fleet / TOU を hydrate するよう修正。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - prepare payload に `fleet_templates`, `objective_mode`,
      `allow_partial_service`, `unserved_penalty`,
      `demand_charge_cost_per_kw`, `diesel_price_per_l`,
      `grid_co2_kg_per_kwh`, `co2_price_per_kg`,
      `depot_power_limit_kw`, `tou_pricing` を追加。
    - Step 2 に objective / cost / CO2 / depot limit の入力と、
      fleet / TOU summary 表示を追加。

- **Gurobi 実測結果**:
  - `total_cost` mode
    - status: `OPTIMAL`
    - objective: `18592.2765`
    - total operating cost: `18592.23 JPY`
    - fuel: `18589.068 JPY`
    - electricity: `0.6485 JPY`
    - demand: `2.56 JPY`
    - total CO2: `319.7433 kg`
  - `co2` mode
    - status: `OPTIMAL`
    - objective: `243.8922 kg-CO2`
    - total operating cost: `229294.96 JPY`
    - fuel: `6331.1 JPY`
    - electricity: `6963.86 JPY`
    - demand: `216000.0 JPY`
    - total CO2: `243.8922 kg`

- **現時点の示唆**:
  - shard runtime で prepare / optimization は end-to-end に成立した。
  - `total_cost` と `co2` で fuel / electricity / demand の構成差は明確に出た。
  - ただし `vehicle_fixed_cost = 0` 設定では使用台数に tie-break が無く、
    solver が全 vehicle を使う解を返しやすい。これは secondary objective
    ないし fixed-use cost 設計の課題として残る。

### [DEV-2026-03-14] Tokyu shard build 基盤と runtime shard fallback を追加

- **問題**:
  - scenario open / simulation prepare が `data/built/<dataset>/timetables.parquet` と
    `trips.parquet` を広く読むため、Tokyu 全体時刻表の読み込みコストが高すぎた。
  - `build_dataset_bootstrap()` が built dataset を見つけると scenario document に
    full `timetable_rows` / `trips` を preload しており、保存サイズと open latency を押し上げていた。
  - Tokyu 向けに必要な `depot x route x day_type` の build-time shard / index / summary /
    schema / validation CLI が存在しなかった。

- **対応**:
  - `data-prep/pipeline/build_tokyu_shards.py`
    - canonical Tokyu data から `outputs/built/tokyu/` を生成する Tokyu-only shard builder を追加。
    - `manifest.json` / `depots.json` / `routes.json` / `depot_route_index.json` /
      `depot_route_summary.json` / `shard_manifest.json` と
      `trip_shards` / `timetable_shards` / `stop_time_shards` を出力。
    - `python -m data_prep.pipeline.build_tokyu_shards --dataset ...`
      `--validate-only` `--depot ...` をサポート。
    - build 時の整合性チェック
      （trip shard 所属、manifest 件数、summary/index 整合、trip/timetable 対応、
      stop sequence 昇順、schema validation）を追加。
  - `schema/tokyu_shards/*.schema.json`
    - manifest / index / summary / shard manifest / trip shard /
      timetable shard / stop_time shard の JSON Schema を追加。
  - `data-prep/pipeline/build_all.py`
    - `build_tokyu_shards` stage を追加し、通常 build で shard も生成するよう変更。
  - `src/tokyu_shard_loader.py`
    - runtime 専用 shard loader を拡張し、trip rows / dispatch trip rows /
      stop-time rows / timetable summary / stop timetable summary を scope 指定でロード可能にした。
  - `src/runtime_scope.py` / `bff/routers/graph.py` / `bff/routers/scenarios.py`
    - scenario に full `timetable_rows` / `trips` が無い場合でも、
      shard manifest があれば scope 限定で fallback 読み込みするよう変更。
  - `src/research_dataset_loader.py`
    - shard manifest が ready の場合は `feed_context.source = "tokyu_shards"` を返し、
      bootstrap では route/depot/calendar のみ materialize、full timetable/trips preload を停止。
  - `bff/store/scenario_store.py`
    - bootstrap payload の `runtime_features` を永続化対象に追加。

- **検証結果**:
  - `python -m pytest tests/test_build_tokyu_shards.py tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_run_preparation_parity.py tests/test_bff_scenario_timetable_summary.py tests/test_bff_graph_router.py -q` → pass
  - `python -m pytest tests/test_architecture.py tests/test_performance_contracts.py -q` →
    `test_app_bootstrap_manager_prewarms_setup_and_execute_tabs` が既存 frontend 差分起因で fail
    （今回変更の Python shard 経路とは無関係）

### [DEV-2026-03-14] Scenario UI を viewer から simulation input builder へ再設計

- **問題**:
  - scenario open 時に timetable summary / detail を先読みする viewer 寄りの構成が残っており、
    「subset を選んで simulation input を作る」主目的に対して無駄な read が多かった。
  - frontend store は閲覧用 cache と builder state が混在しており、
    depot / route / day type / solver 条件の確定前に重い payload を抱えやすかった。
  - `run_preparation` は built parquet filter 前提だったため、
    Tokyu shard runtime artifact が存在しても prepare がそれを優先利用していなかった。
  - prepared input hash には `scenario_store._scope_summary()` が meta へ注入する
    `selectedDepotIds` / `selectedRouteIds` / `serviceIds` まで含まれ、
    prepare 直後の run でも stale 判定になるケースがあった。

- **対応**:
  - `bff/routers/scenarios.py`
    - `GET /api/scenarios/{id}/editor-bootstrap` を追加。
    - scenario metadata / depots / routes / vehicle templates / depotRouteIndex /
      depotRouteSummary / availableDayTypes / builderDefaults だけを返す pure-read endpoint にした。
  - `bff/routers/simulation.py`
    - `POST /api/scenarios/{id}/simulation/prepare` を追加し、
      builder で選ばれた depot / route / day type / vehicle / charger / solver 条件を
      scenario overlay / dispatch scope / generated vehicles / chargers に反映して一度だけ保存。
    - `POST /api/scenarios/{id}/simulation/run` を追加し、
      prepared input id を検証した上で simulation job を起動する構成にした。
    - request body は `Field(default_factory=...)` に変更し、mutable default を排除。
  - `bff/services/run_preparation.py`
    - prepared input に `dataset_id` / `random_seed` / `depot_ids` / `route_ids` /
      `service_ids` / `trip_count` などの top-level compatibility key を追加。
    - `outputs/prepared_inputs/<scenario_id>/...` を新 API 用の標準保存先に整理し、
      旧 `.../<scenario_id>/prepared_inputs/...` caller との互換も維持。
    - Tokyu shard runtime artifact が存在する場合は `src/tokyu_shard_loader.py` を優先し、
      `trip_shard` / `stop_time_shard` から prepared input を組み立てるよう変更。
    - built stops が無い場合でも stop-time rows から最小 stop list を推定して canonical input に含めるようにした。
    - hash の volatile key に `selectedDepotIds` / `selectedRouteIds` / `serviceIds` を追加し、
      prepare 後の即 run が stale 判定される問題を解消。
  - `src/tokyu_shard_loader.py`
    - `load_stop_time_rows_for_scope()` を追加し、
      stop-time shard を canonical stop-time sequence へ変換できるようにした。
  - `frontend`
    - `ScenarioOverviewPage` を 3-step builder UI に置換。
    - `simulation-builder-store` を追加し、
      selected depots / routes / day type / settings / prepared result / active job を一元管理。
    - `useEditorBootstrap` / `usePrepareSimulation` / `useRunPreparedSimulation` を追加。
    - `AppBootstrapManager` は open 時に editor-bootstrap だけを warm し、
      timetable / dispatch 系は lazy load 優先に変更。

- **回帰テスト**:
  - `tests/test_run_preparation_parity.py`
    - prepared input の `random_seed` / scope key 互換を検証。
    - Tokyu shard runtime artifact がある場合に shard を優先することを検証。
  - `tests/test_bff_simulation_builder.py`
    - editor-bootstrap の軽量 payload を検証。
    - prepare → run prepared simulation の builder flow を検証。

### [DEV-2026-03-14] Scenario activate/open の bootstrap/save 競合を緊急修正

- **問題**:
  - `GET /api/scenarios/{id}` や `GET /api/scenarios/{id}/dispatch-scope` の read path が
    bootstrap 保存を誘発していた。
  - `bff/routers/scenarios.py` の bootstrap 判定は `store.get_scenario()` の meta payload を見ており、
    `depots/routes` を持たないため高確率で「未bootstrap」と誤判定していた。
  - `POST /activate` と複数の GET が短時間に重なると、
    同じ scenario の `.staging/artifacts.sqlite` を並行保存・削除し、
    Windows で `WinError 32` が発生していた。
  - frontend では `ScenarioListPage` と `AppLayout` の両方が `/activate` を叩き、
    open 直後に request burst を作っていた。

- **対応**:
  - `bff/routers/scenarios.py`
    - GET 系から bootstrap 保存を除去し、`get_scenario` / `get_dispatch_scope` を pure read 化。
    - activate 専用の `_ensure_scenario_bootstrap_persisted()` を追加し、
      raw scenario document を見て bootstrap 要否を判定するよう修正。
  - `bff/store/scenario_store.py`
    - `_load(..., repair_missing_master=True)` に分離し、read path の self-heal が `_save()` しないよう変更。
    - `get_scenario_document(..., repair_missing_master=False)` を追加し、
      persisted state と in-memory repaired view を使い分け可能にした。
    - scenario 単位 `RLock` を `_save()` と `apply_dataset_bootstrap()` に導入。
    - `apply_dataset_bootstrap()` を dataset/version/fingerprint ベースで idempotent 化し、
      同一 bootstrap 再適用では `_save()` を skip。
    - `_remove_tree_with_retries()` は retry 後に quarantine rename を試すようにし、
      Windows の cleanup 衝突に強くした。
  - `frontend/src/features/layout/AppLayout.tsx`
    - route 遷移後の child render / boot prewarm を、activate 完了まで待つ構成へ変更。
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 同一 scenario の activate 二重送信を抑止し、open 中はボタンを disable。
  - `frontend/src/api/scenario.ts`
    - in-flight dedupe 付き `ensureScenarioActivated()` を追加。
  - `frontend/src/app/AppBootstrapManager.tsx`
    - open 直後の一斉 prewarm を削減し、scenario detail / dispatch scope 確認後は
      timetable / dispatch / explorer を lazy load 優先に変更。

- **確認結果**:
  - `python -m pytest tests/test_bff_research_scenario_bootstrap.py tests/test_bff_scenario_store.py -q` → pass
  - `cd frontend && npx tsc --noEmit` → pass

### [DEV-2026-03-14] Vehicle template catalog を実車カタログ値へ更新

- **問題**:
  - `src/research_dataset_loader.py` の `default_vehicle_templates()` が汎用ダミー値のままで、
    `data/vehicle_catalog.json` や `config/ebus_asset_factors.json` の車両カタログとも乖離していた。
  - BYD K8 2.0 / エルガEV / ブルーリボン Z EV / エルガ / ブルーリボン / エアロスターの
    大型路線バス実車テンプレートが scenario 初期値に出てこなかった。
  - HEV 参考車種を保持したくても、現行 template 層は `BEV` / `ICE` 二値前提だった。

- **対応**:
  - `data/vehicle_catalog.json`
    - 大型路線バスカタログ値 dataset として全面更新。
    - `ev_presets` / `engine_presets` を実車ベースへ差し替え、
      scenario template seed の正本に位置づけた。
    - HEV は `hybrid_reference_presets` に reference-only で保持。
  - `src/research_dataset_loader.py`
    - `default_vehicle_templates()` を `data/vehicle_catalog.json` 読み込みに変更。
    - scenario bootstrap / master preload の vehicle templates が catalog 連動になった。
  - `config/ebus_asset_factors.json`
    - `vehicle_catalog` を同じカタログ値へ更新し、研究設定側とのズレを解消。
  - `README.md`
    - `data/vehicle_catalog.json` を seed asset として明記。

- **制約メモ**:
  - 現行 runtime の vehicle template は `BEV` / `ICE` のみ自動 seed。
  - `isuzu_erga_hybrid_swb` は catalog reference として保持し、HEV template 自動投入は将来拡張扱い。

### [DEV-2026-03-13] Tokyu-only two-app data contract baseline

- **目的**:
  - `main` を Tokyu Bus 専用の research consumer とし、runtime ETL / explorer 責務を切り離す。
  - `data/seed/` と `data/built/` を明示し、seed-only 起動でも app が落ちない基盤を先に固める。

- **対応（data contract）**:
  - `data/seed/tokyu/depots.json`
  - `data/seed/tokyu/route_to_depot.csv`
  - `data/seed/tokyu/version.json`
  - `data/seed/tokyu/datasets/tokyu_core.json`
  - `data/seed/tokyu/datasets/tokyu_full.json`
  - を追加し、`.gitignore` に `data/built/` を追加。
  - ルートの `tokyu_bus_depots_master.json` / `tokyu_bus_route_to_depot.csv` は
    `data/seed/tokyu/sources/` に移動。

- **対応（schema / loader）**:
  - `src/scenario_overlay.py` を追加し、`ScenarioOverlay` / `FleetConfig` /
    `ChargingConfig` / `CostConfig` / `SolverConfig` を Pydantic で定義。
  - `schema/scenario.schema.json` に `ScenarioOverlay` 関連定義を追加。
  - `src/research_dataset_loader.py` を追加し、seed master 読込・built dataset status・
    seed-only bootstrap を `src/` に集約。

- **対応（BFF main / startup）**:
  - `bff/services/research_catalog.py` と `bff/routers/app_state.py` を追加し、
    `GET /api/app/datasets` / `GET /api/app/data-status` を追加。
  - `bff/main.py` から `catalog` / `public_data` router を外し、main runtime の公開面を
    planning / dispatch / simulation / optimization に絞った。
  - `bff/services/app_cache.py` の startup warm-up を ODPT / GTFS refresh 前提から
    dataset catalog / built status 前提へ変更。
  - `bff/routers/scenarios.py` の scenario 作成時に dataset bootstrap を適用し、
    Tokyu Core を seed-only でも生成できるようにした。

- **対応（frontend）**:
  - Scenario list を Tokyu dataset 選択 UI に変更し、`tokyu_core` / `tokyu_full` の
    built readiness を表示。
  - Overview に `datasetId` / `datasetVersion` / `randomSeed` を表示。
  - public-data route と `/odpt-explorer` redirect を main router から外し、
    Header / Sidebar / MasterDataHeader も main app 向け文言に整理。
  - `TimetablePage` では runtime ETL を無効化し、data-prep 先行を案内。

- **対応（data-prep / docs）**:
  - `data-prep/api/main.py` を追加し、catalog API を producer-side entrypoint として分離。
  - `data-prep/README.md` を追加。
  - root の dated notes / governance / development notes を `docs/notes/` へ移動。
  - `README.md` の architecture / startup / docs link を新しい two-app 方針に更新。

- **検証結果**:
  - `python -m pytest` → **294 passed**
  - `cd frontend && npm run build` → **pass**

### [DEV-2026-03-14] Incomplete artifact 500エラー修正 / Explorer ローディング修正 / Depot assignment 改善

- **問題①: Incomplete artifact が全 API で 500 を返す**
  - `bff/store/scenario_store.py` の `_load()` が `_INCOMPLETE` マーカーを検出して `RuntimeError` を上げるが、
    複数の router が `RuntimeError` を `HTTPException` に変換していなかったため HTTP 500 が返っていた。
  - `graph.py`・`master_data.py`・`optimization.py`・`public_data.py` の既存 `_require_scenario` は対応済みだったが、
    `scenarios.py` の `update_scenario` / `get_dispatch_scope` / `update_dispatch_scope` /
    `get_depot_scope_trips` / `duplicate_scenario` / `activate_scenario` /
    `get_timetable` / `get_timetable_summary` / `update_timetable` が未対応だった。

- **対応①**:
  - `bff/routers/scenarios.py` に `_runtime_err_to_http(e)` ヘルパーを追加。
    `"artifacts are incomplete"` を含む RuntimeError → HTTP 409 `INCOMPLETE_ARTIFACT`、
    それ以外の RuntimeError → re-raise (FastAPI が 500 扱い) に統一。
  - 上記の全 9 エンドポイントに `except RuntimeError as e: raise _runtime_err_to_http(e)` を追加。
  - `get_app_context` は `except (KeyError, RuntimeError):` に統合し、incomplete な active scenario を
    静かに deactivate する（500 にしない）。

- **対応①-frontend**:
  - `frontend/src/api/client.ts`
    - `extractErrorMessage` が `{"detail": {"code": "INCOMPLETE_ARTIFACT", "message": "..."}}` 形式の
      object detail を正しく取り出せるよう修正。
    - `isIncompleteArtifactError(error)` 関数を export 追加。
  - `frontend/src/types/api.ts`
    - `ApiError.detail` を `string | Record<string, unknown>` に拡張。
  - `frontend/src/hooks/use-scenario.ts`
    - `useScenarioIsIncomplete(id)` 便利フックを追加。
  - `frontend/src/hooks/index.ts`
    - `useScenarioIsIncomplete` を export に追加。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - `IncompleteArtifactBanner` コンポーネントを追加。
      409 INCOMPLETE_ARTIFACT を受け取った場合に「削除して一覧に戻る」バナーを表示。

- **問題②: orphan legacy ファイルの残留**
  - `outputs/scenarios/74aa5521-..._timetable.json` と `_stop_timetables.json` が残留していた。

- **対応②**:
  - `outputs/scenarios/74aa5521-5492-495f-9421-c35d0a5fb0e6_timetable.json` を削除。
  - `outputs/scenarios/74aa5521-5492-495f-9421-c35d0a5fb0e6_stop_timetables.json` を削除。

- **問題③: Public Data Explorer が「準備しています」から進まない**
  - `AppBootstrapManager` が `explorer` タブの warm status を `"idle"` のまま残す 2 パターンがあった:
    1. `scenarioId` が null/undefined のとき `resetWarmTabs()` 後に return するが、
       `explorer` を `"ready"` にセットしないため永遠に `"idle"` のまま。
    2. bootstrap が失敗（catch ブロック）したとき `planning/timetable/dispatch` は `"error"` にセットされるが
       `explorer` は `"idle"` のまま残る。
  - `explorer` タブは active scenario に依存しないのに、scenario lifecycle に連動していた。

- **対応③**:
  - `frontend/src/app/AppBootstrapManager.tsx`
    - `!scenarioId` の early-return パスで `setTabStatus("explorer", "ready", "Explorer はいつでも利用可能")` を追加。
    - catch ブロックにも `setTabStatus("explorer", "ready", "Explorer はいつでも利用可能")` を追加。

- **問題④: depot assignment が name string 比較のみで精度が低い**
  - `bff/services/depot_assignment.py` の `calculate_assignment_scores()` は
    depot 名が terminal stop 文字列に含まれるかどうかの heuristic のみだった。
  - stop ID レベルの geographic マッチングや sidecar depot_candidate_map が活用されていなかった。

- **対応④**:
  - `bff/services/depot_assignment.py` を全面改修:
    - `DepotAssignmentScore` dataclass を追加（depot_id, route_id, score, reasons, tier プロパティ）。
    - `compute_depot_route_scores(depots, routes, sidecar_depot_candidate_map)` を新規追加。
      スコアリング: geographic(3pt) + sidecar_map(2pt) + operator_match(1pt) の加算式。
    - `auto_assign_depots(depots, routes, sidecar_map, min_score, allow_multi_depot)` を新規追加。
    - 既存 `calculate_assignment_scores()` は legacy wrapper として維持（後方互換）。
  - `bff/routers/master_data.py`
    - `AutoAssignDepotsBody` (minScore / applyNow / operatorId / sidecarDepotCandidateMap) を追加。
    - `POST /scenarios/{id}/auto-assign-depots` を `compute_depot_route_scores` ベースに刷新:
      - tier / reasons / candidates を含むレスポンスを返す。
      - `applyNow=true` の場合は depot_route_permissions に即時保存。
      - `appliedCount` / `meta` を含む構造化レスポンスに変更。

- **テスト修正**:
  - `tests/test_bff_scenario_store.py`
    - `test_feed_context_roundtrip_is_exposed_in_scenario_meta` を修正:
      `_normalize_feed_context` に追加された `datasetFingerprint` / `manualRouteFamilyMapHash` フィールドを
      期待値に追加（既存の store 変更により生じた pre-existing failure を解消）。

- **確認結果**:
  - Python tests: `tests/test_bff_scenario_store.py` 他主要テスト群 pass（20 + 59 tests）。
  - TypeScript: `npx tsc --noEmit` → 0 errors。
  - orphan ファイル削除確認済み。

### [DEV-2026-03-14] Scenario 非依存 master preload と dataset-backed scenario 自己修復

- **問題**:
  - 既存 scenario の一部は `feed_context.datasetId` を持っていても `depots/routes/route_depot_assignments/depot_route_permissions` が空のまま残っていた。
  - `vehicle_templates` は dataset bootstrap に含まれておらず、scenario ごとに毎回手動で作る必要があった。
  - app 起動時に scenario 非依存で参照できる depot / route / template の基準 master がなかった。

- **対応**:
  - `data/seed/tokyu/datasets/tokyu_dispatch_ready.json` を追加し、目黒・瀬田・淡島・弦巻の 4営業所 / 43 route code を preload 用 dataset として固定。
  - `src/research_dataset_loader.py`
    - `default_vehicle_templates()` を追加。
    - `build_dataset_bootstrap()` が `vehicle_templates` を返すよう変更。
  - `bff/services/master_defaults.py` を追加。
    - `GET /api/app/master-data` 用の scenario 非依存 master blueprint を構築。
    - dataset-backed scenario の欠落 master data を埋める repair helper を追加。
  - `bff/store/scenario_store.py`
    - `_load()` 時に `scenario_overlay/feed_context.datasetId` を見て
      `depots/routes/route_depot_assignments/depot_route_permissions/vehicle_templates`
      を自己修復するよう変更。
    - `apply_dataset_bootstrap()` が `vehicle_templates` を保存するよう変更。
  - `bff/services/app_cache.py`
    - startup warm-up で preloaded master blueprint をキャッシュするよう変更。
  - `bff/routers/app_state.py`
    - `GET /api/app/master-data` を追加。

- **確認結果**:
  - `tokyu_dispatch_ready` で 4営業所 / 46 route rows / default vehicle templates を app-level に返却できることを確認。
  - dataset-backed だが master が空の scenario は `_load()` 一発目で自己修復されることをテスト追加で確認。

### [DEV-2026-03-13] 起動画面で既存シナリオを選択できない問題を修正

- **問題**:
  - 起動時に `/` から最後に開いたシナリオへ自動リダイレクトされ、既存シナリオ一覧を最初に選べない。

- **対応**:
  - `/` の起動 loader を廃止し、初期表示は常に `/scenarios` へ統一。
  - 既存シナリオは一覧から選択して開く導線へ変更。
  - `frontend/README.md` の起動時挙動を更新。

### [DEV-2026-03-13] シナリオ一覧に「開く」ボタンを追加

- **問題**:
  - 既存シナリオを開く導線が行クリックに依存し、ボタンが欲しいという要望が出た。

- **対応**:
  - シナリオ一覧カード右側に「開く」ボタンを追加。
  - 既存の削除ボタンは維持。

### [DEV-2026-03-08] Frontend boot pipeline + timetable summary/page + perf instrumentation

- **目的**:
  - `Maximum update depth exceeded` の温床になっていた大型ページの state/effect 連鎖を減らす。
  - 数万件規模の ODPT / GTFS timetable を summary-first + page access で扱う。
  - 起動時・tab 切替時・import 中の状態を可視化し、固まって見える時間を減らす。

- **実装（BFF）**:
  - `bff/routers/scenarios.py`
    - `GET /scenarios/{id}/timetable` と `GET /scenarios/{id}/stop-timetables` に `limit/offset` を追加。
    - `GET /scenarios/{id}/timetable/summary`
    - `GET /scenarios/{id}/stop-timetables/summary`
    - service / route / stop 単位の lightweight summary を返す helper を追加。
  - `tests/test_bff_scenario_timetable_summary.py`
    - summary 集計 helper の回帰テストを追加。

- **実装（Frontend 基盤）**:
  - `frontend/src/app/AppBootstrapManager.tsx`
    - app context / scenario / dispatch scope を確認後、依存のない master data / timetable summary / explorer overview を並列 prefetch。
  - `frontend/src/app/BootSplashOverlay.tsx`
    - boot 進捗オーバーレイ + 完了時フェードアウトを実装。
  - `frontend/src/stores/boot-store.ts`
    - boot step registry と weighted progress を Zustand 化。
  - `frontend/src/stores/tab-warm-store.ts`
    - planning / timetable / explorer / dispatch の warm state を管理。
  - `frontend/src/stores/import-job-store.ts`
    - import job の stage progress / logs を共通管理。
  - `catalog_update_app.py`
    - ODPT / GTFS の catalog refresh と scenario sync を行う standalone updater CLI を追加。

- **実装（Frontend 表示最適化）**:
  - `frontend/src/pages/inputs/TimetablePage.tsx`
    - 全件取得をやめ、summary + page 読みへ移行。
    - import progress / logs を panel で表示。
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - header summary を full timetable query から summary query へ切替。
  - `frontend/src/pages/dispatch/PrecheckPage.tsx`
    - timetable 全件 filter ではなく `routeServiceCounts` ベース集計へ変更。
  - `frontend/src/pages/odpt/OdptExplorerPage.tsx`
    - DB/API tab を hidden 切替にして unmount 再初期化を回避。
    - public-data sync / catalog refresh に import job progress を接続。
  - `frontend/src/pages/dispatch/TripsPage.tsx`
  - `frontend/src/pages/dispatch/DutiesPage.tsx`
    - VirtualizedList 化。
  - `frontend/src/features/common/TabWarmBoundary.tsx`
    - warm 中 placeholder を共通化。

- **実装（Catalog / Import 運用分離）**:
  - `bff/services/transit_catalog.py`
    - source + dataset_ref から保存済み snapshot を引く helper を追加。
  - `bff/routers/master_data.py`
  - `bff/routers/scenarios.py`
  - `bff/routers/public_data.py`
    - import / public-data fetch を「保存済み snapshot 優先、明示時だけ refresh」に変更。
    - snapshot 不在時は `catalog_update_app.py` を案内するエラーを返す。

- **実装（Fast ingest 追加）**:
  - `tools/fast_catalog_ingest.py`
    - ODPT の raw JSON を async + http2 + retry/backoff で取得する別 CLI を追加。
    - `raw/*.json` と `raw/*.ndjson`、checkpoint、benchmark、`bundle.json`、`operational_dataset.json` を生成。
    - 途中中断後は resource 単位で resume 可能。
  - `tests/test_fast_catalog_ingest.py`
    - 最小 raw snapshot から bundle/operational_dataset を再構築できることを確認する回帰テストを追加。

- **実装（Perf / Worker）**:
  - `frontend/src/utils/perf/`
    - `useRenderTrace`, `useMeasuredMemo`, `measureAsyncStep`, `useTabSwitchTrace`, `DebugPerfOverlay`
  - `frontend/src/features/common/VirtualizedList.tsx`
    - visible slice 計算の selector timing を記録。
  - `frontend/src/workers/assignment-sort.worker.ts`
  - `frontend/src/hooks/useSortedAssignments.ts`
    - explorer の depot assignment sort を worker 化。
  - `frontend/src/workers/route-family-group.worker.ts`
  - `frontend/src/hooks/useGroupedRouteFamilies.ts`
    - routes tab の route family grouping / variant sort を worker 化。
  - `frontend/src/workers/public-diff-preview.worker.ts`
  - `frontend/src/hooks/usePreparedPublicDiffItems.ts`
    - public-data diff preview の field diff 要約と sort を worker 化。

- **実装（追加の code split / dispatch summary-first / backend job UI）**:
  - `bff/routers/graph.py`
    - `GET /scenarios/{id}/trips` / `duties` / `blocks` に `limit/offset` を追加。
    - `GET /scenarios/{id}/trips/summary`
    - `GET /scenarios/{id}/graph/summary`
    - `GET /scenarios/{id}/graph/arcs`
    - `GET /scenarios/{id}/duties/summary`
    - graph build 系 job metadata に stage / count を付与。
  - `frontend/src/pages/dispatch/TripsPage.tsx`
  - `frontend/src/pages/dispatch/GraphPage.tsx`
  - `frontend/src/pages/dispatch/DutiesPage.tsx`
    - dispatch 一覧を summary-first + page access に移行。
    - backend job panel を表示。
  - `frontend/src/pages/results/DispatchResultsPage.tsx`
  - `frontend/src/pages/results/EnergyResultsPage.tsx`
  - `frontend/src/pages/results/CostResultsPage.tsx`
    - placeholder をやめ、既存 result summary を表示。
  - `frontend/src/api/jobs.ts`
  - `frontend/src/hooks/use-job.ts`
  - `frontend/src/features/common/BackendJobPanel.tsx`
    - `/jobs/{job_id}` poll で backend async job progress を表示。
  - `frontend/src/app/Router.tsx`
    - route-level lazy loading を適用。
  - `frontend/vite.config.ts`
    - manual chunk 設定を追加し、main chunk の肥大化を抑制。

- **確認結果**:
  - `cd frontend && npm run build` → **pass**

- **未確認 / 制約**:
  - この実行環境には `pytest` と `fastapi` が入っていないため、Python 側の新規テストは未実行。
  - main chunk warning は解消したが、`MapLibre GL` 由来の大きい地図 chunk warning は継続。地図依存をさらに細かく split するなら map provider 周辺の import 境界を再整理する必要がある。

### [DEV-2026-03-04] 設定タブ再設計 + Dispatch前処理統合

- **目的**:
  - GUIの設定導線を「時刻表ファースト」に再編し、設定ロジックの分散を解消する。
  - backend 側で `ProblemData` から `dispatch` の接続グラフを生成し、`travel_connections` を再構築できるようにする。

- **実装（UI）**:
  - `app/main.py` の巨大な設定タブ実装を分離し、`render_settings_tab()` 呼び出しに集約。
  - `app/settings_page.py` 新設:
    - サブタブ順をワークフロー順へ変更
      (`🗺️ 路線・時刻表` → `🚌 車両フリート` → `🏢 営業所・配車` → `⚙️ システム設定・適用`)
  - `app/system_config_editor.py` 新設:
    - 計画軸、便データソース、フォールバック車両、電力設定を集約
    - 「時刻表→接続グラフ」プレビューを追加
    - `build_problem_config_from_session_state()` を使って `ProblemConfig` を構築
  - `app/config_builder.py` 新設:
    - 手動設定の便生成を timetable ベースへ切り替え
    - `timetable.csv` / `segments.csv` / `routes.csv` を使って `TripSpec` を構築
  - `app/depot_profile_editor.py`:
    - `show_energy_settings` フラグを追加し、電力設定の重複表示を抑制可能に。

- **実装（dispatch / pipeline）**:
  - `src/dispatch/context_builder.py` 新設:
    - CSV (`route_master` / `operations`) から `DispatchContext` を構築。
  - `src/dispatch/dispatcher.py`:
    - greedy配車が precomputed graph を直接利用する API を追加。
  - `src/dispatch/pipeline.py`:
    - `uncovered_trip_ids` / `duplicate_trip_ids` を追加。
    - `all_valid` は duty妥当性 + カバレッジ妥当性を反映。
  - `src/dispatch/problemdata_adapter.py` 新設:
    - `ProblemData.tasks` を dispatch graph へ変換し、
      `TravelConnection` 全ペア行列を生成。
  - `src/data_loader.py`:
    - `dispatch_preprocess` 設定を追加。
    - `travel_connection_csv` がない場合、dispatch graph 由来で
      `travel_connections` を再構築可能に。
  - `src/pipeline/solve.py`:
    - dispatch 前処理レポートをログ出力し、戻り値にも含める。

- **テスト追加**:
  - `tests/test_dispatch_pipeline.py`
  - `tests/test_dispatch_context_builder.py`
  - `tests/test_dispatch_problemdata_adapter.py`
  - `tests/test_data_loader_dispatch_preprocess.py`

- **検証結果**:
  - `python -m pytest -q` → **178 passed**

- **追補 (同日)**:
  - `config/cases/mode_B_case01.json` と
    `config/cases/toy_mode_A_case01.json` に
    `dispatch_preprocess` ブロックを追加し、case 単位で前処理挙動を明示化。
  - `src/data_loader.py` の `build_inputs` 経路レポートを
    `edge_count` / `generated_connections` 形式に揃え、
    `src/pipeline/solve.py` で dict / dataclass の双方を安全にログ表示できるよう改善。
  - `docs/dispatch_preprocess_config.md` を追加し、
    `dispatch_preprocess` キーの意味・推奨プリセット・ログ形式を明文化。
  - `tests/test_pipeline_solve_dispatch_report.py` を追加し、
    `connection_source=build_inputs` 相当の dict レポートが
    `solve.py` で正しく表示・返却されることを確認。
  - `config/cases/mode_B_case01_build_inputs.json` を新設し、
    `dispatch_preprocess.connection_source=build_inputs` を case 単位で実配線。
  - `src/preprocess/energy_model.py` の HVAC 合算式を修正
    (`None` を含む場合に `TypeError` が出る優先順位バグを解消)。
  - `tests/test_energy_model.py` を追加し、
    Level 1 電費推定で `hvac_power_kw_heating=None` のときも
    例外なく推定できることを回帰テスト化。
  - **E2E 比較 (dispatch_graph vs build_inputs)**:
    - Baseline: `python run_case.py --case config/cases/mode_B_case01.json`
      - status=OPTIMAL, objective=9,594.05, unmet=0
    - build_inputs case:
      `python run_case.py --case config/cases/mode_B_case01_build_inputs.json`
      - status=OPTIMAL, objective=7,411.22, unmet=0
      - dispatch report: `source=build_inputs, trips=29, edges=812, connections=812`
    - 同一 task 集合上での接続差分（build_inputs case を再評価）:
      - build_inputs: feasible 812 / 812
      - dispatch_graph: feasible 0 / 812
      - 差分: `build_inputs-only true = 812`（全ペアで不一致）
    - 参考: baseline 8-task ケースでも
      `travel_connection.csv` と dispatch_graph は完全一致せず
      (`true`: 9 vs 10, csv-only 4, dispatch-only 5)。
  - 回帰確認: `python -m pytest -q` → **180 passed**

---

### [EXP-001] mode_A_case01 — 先行研究再現ベースライン

- **日付**: 2026年初頭
- **目的**: He et al. 2023 (TRD 115) 型「行路後充電決定」の再現
- **設定**: `config/cases/mode_A_case01.json`
- **データ**: `data/cases/mode_A_case01/` — 3台BEV, 6タスク, 64スロット(15分/スロット)

**結果:**
```
status         : OPTIMAL
objective_value: 20,172 円
solve_time_sec : 0.039 s
unmet_trips    : 0
```

**判定**: ✅ PASS — mode_A パイプライン動作確認。固定割当前提の充電最適化が正常動作。

---

### [EXP-002] toy_mode_A_case01 — 手計算検証トイケース

- **日付**: 2026-03-02
- **目的**: mode_A ソルバーの正しさを手計算で検証
- **設定**: `config/cases/toy_mode_A_case01.json`
- **データ**: `data/toy/mode_A_case01/` — 2台BEV, 5タスク, 1充電器(C1:50kW), 20スロット(60分/スロット)

**設定詳細:**
- V1 → {T1(20kWh), T2(20kWh), T3(20kWh)} 固定割当、合計消費60kWh
- V2 → {T4(20kWh), T5(10kWh)} 固定割当、合計消費30kWh
- TOU料金: t=0–7: **10円/kWh** (安価), t=8–19: 30円/kWh (高価)
- 各車両: soc_init=80kWh, soc_min=20kWh, soc_target_end=50kWh, fixed_use_cost=3,000円

**手計算 (修正版):**
- V1: 80 → (60消費) → 20kWh。target=50 → 充電必要量 = **30kWh**
- V2: 80 → (30消費) → 50kWh = target → 追加充電 **不要**
- 最適行動: 安価スロット(t=0–7)に30kWhを充電 → **30 × 10 = 300円**
- 固定コスト: 2台 × 3,000 = **6,000円**
- **期待合計: 6,300円**

**実際の結果:**
```
status             : OPTIMAL
objective_value    : 6,300 円
total_energy_cost  :   300 円
vehicle_fixed_cost : 6,000 円
unmet_trips        : 0
peak_grid_power_kw : 20.0 kW
solve_time_sec     : 0.017 s
```

**判定**: ✅ PASS — ソルバー結果が手計算と完全一致。

> **NOTE (修正)**: 当初の手計算では soc_init=80 と soc_target_end=50 を無視して「90kWh × 10円 = 900円」と誤推定していた。正しくは V2 が充電不要であり合計は 300円。

---

### [EXP-003] mode_B_case01 — 車両割当＋充電同時最適化

- **日付**: 2026-03-02
- **目的**: mode_B (vehicle-trip assignment + charging) の動作確認
- **設定**: `config/cases/mode_B_case01.json`
- **データ**: `data/cases/mode_B_case01/` — 3台BEV + 1台ICE, 8タスク

**結果:**
```
status             : OPTIMAL
objective_value    : 9,594 円
total_energy_cost  : 2,796 円
total_fuel_cost    : 1,798 円  (ICE使用: 約12.4L × 145円/L)
vehicle_fixed_cost : 5,000 円  (BEV 1台使用)
unmet_trips        : 0
charger_utilization:   6.25%
peak_grid_power_kw : 35.0 kW
solve_time_sec     : 0.093 s
```

**判定**: ✅ PASS — mode_B 動作確認。ICE 車両の燃料コストが非ゼロで整合。充電器稼働率 6.25% は BEV 使用台数が少ないため妥当。

---

## テスト状況

```
tests/test_simulator.py  — 6テスト全通過
  test_soc_lower_limit_violation        ✅
  test_simultaneous_charger_overload    ✅
  test_task_sequence_time_overlap       ✅
  test_end_of_day_soc_violation         ✅
  test_grid_capacity_violation          ✅
  test_ok_schedule_passes_all_checks    ✅
```

実行コマンド: `python -m pytest tests/test_simulator.py -v`

---

## バグ修正履歴

| 日付 | ファイル | 修正内容 |
|------|----------|----------|
| 初期 | `src/data_loader.py` | `_find_project_root()` 追加 — `.git/` or `src/` を上位探索し、`config/cases/*.json` パス解決を修正 |
| 初期 | `src/pipeline/solve.py` | `run_gap_analysis()` 引数順序修正 (result, sim_result, data, ms, dp → data, ms, dp, result, sim_result) |
| 初期 | `src/pipeline/solve.py` | `run_delay_resilience_test()` の `duties` / `trips` 引数を `getattr` で安全取得 |

---

## 次のステップ (優先度順)

1. **mode_B vs mode_A 比較実験**: 同一トリップセットで両モードを解き、mode_B の目的関数値 ≤ mode_A を確認 (緩和方向の理論的保証)
2. **Simulator 一貫性検証**: optimizer の充電スケジュールを simulator に通してフィジビリティ確認 (SOC violationがゼロであること)
3. **thesis_mode 設計**: デマンド料金・PV統合・V2G の追加検討
4. **感度分析**: TOU料金比 (安価/高価)、充電器容量、soc_target_end を変えたパラメータスイープ

---

## ファイル構成 (研究関連のみ)

```
master-course/
├── src/
│   ├── pipeline/solve.py     ← 正規パイプライン入口 solve(config_path, mode)
│   ├── data_loader.py        ← load_problem_data() + _find_project_root()
│   ├── milp_model.py         ← MILPResult, build_milp_model()
│   ├── simulator.py          ← SimulationResult, simulate(), check_schedule_feasibility()
│   ├── model_sets.py         ← build_model_sets()
│   └── parameter_builder.py  ← build_derived_params()
├── config/cases/
│   ├── mode_A_case01.json         ← EXP-001 [VERIFIED]
│   ├── mode_B_case01.json         ← EXP-003 [VERIFIED]
│   └── toy_mode_A_case01.json     ← EXP-002 [VERIFIED]
├── data/
│   ├── cases/mode_A_case01/       ← 3BEV, 6tasks, 64slots
│   ├── cases/mode_B_case01/       ← 3BEV+1ICE, 8tasks
│   └── toy/mode_A_case01/         ← 2BEV, 5tasks, 20slots (手計算検証用)
├── results/
│   ├── mode_A_case01/             ← kpi.json, kpi.csv, report.md
│   ├── mode_B_case01/             ← kpi.json, kpi.csv, report.md
│   └── toy_mode_A_case01/         ← kpi.json, kpi.csv, report.md
├── tests/test_simulator.py        ← 6 tests, all PASS
├── docs/reproduction/mode_A_reproduction_spec.md
└── run_case.py                    ← CLI実行ハーネス
```
- 2026-03-09
  - `catalog_update_app.py` の `--fast-path` 運用を README に明記し、`tools/benchmark_catalog_ingest.py` / `tools/profile_catalog_ingest.py` の使用例を追記。
  - 開発用 perf は明示 opt-in に変更。`?debugPerf=1` か `localStorage["debug-perf"]="1"` が無い限り observer / entry push を止め、通常の開発表示負荷を下げた。
  - `RouteTableNew` を family group 付きの virtualized list へ切り替え、planning の route 一覧でも全件 DOM 描画を避ける構成にした。

- 2026-03-13
  - `schema/parquet/*.schema.json` を追加し、`src/research_dataset_loader.py` で built parquet 読み込み時に schema 検証を強制。
  - `src/dataset_integrity.py` を追加し、seed/built/manifest 整合性チェックを実装。
  - `GET /api/app/data-status` に `seed_ready` / `built_ready` / `missing_artifacts` / `integrity_error` を追加し、`GET /api/app-state` を新設。
  - simulation / optimization / reoptimize 実行前に built dataset readiness を必須化（不足時は HTTP 503, `BUILT_DATASET_REQUIRED`）。
  - frontend の Simulation / Optimization ページに seed-only banner と実行ボタン disable を追加。
  - `backend/` を `backend_legacy/` へリネームし、README と関連注記を更新。
  - 構造回帰テスト `tests/test_architecture.py`（12件）と built guard テスト `tests/test_bff_run_guards.py` を追加。

- 2026-03-13 (Phase 3.5 hard cut)
  - `bff/` と `src/` の runtime から ODPT/GTFS/catalog ingest 依存を除去し、関連モジュールを `data-prep/lib/` へ移設。
  - `bff/routers/scenarios.py` から feed import/runtime snapshot import 経路を削除し、runtime-safe な CRUD/timetable 系に限定。
  - `bff/routers/master_data.py` から feed import エンドポイントを削除し、seed/built 前提の master CRUD のみに整理。
  - `bff/routers/catalog.py` / `bff/routers/public_data.py` を削除。
  - legacy runtime テスト群（ODPT/GTFS ingest 前提）を削除し、architecture boundary テストを強化。
  - `data-prep/README.md` を producer 契約に合わせて更新し、`data-prep/pipeline/*.py` の入口スクリプトを追加。

- 2026-03-14 (Phase 5-6 changes summary)
  - contract state cleanup: app-state judgment を `src/artifact_contract.py` + `bff/services/app_cache.py` に集中し、loader 側の重複 metadata 判定を削除。
  - producer pipeline: `data-prep/pipeline/build_all.py` を canonical build entry point として追加し、stale manifest 削除・manifest write・post-build contract validation を統合。
  - performance baseline tooling: `bff/middleware/timing.py`, `bff/services/metrics.py`, `tools/benchmark_api.py`, `docs/notes/performance_baseline.md`, `docs/notes/api_inventory_phase5.md` を追加。
  - API/runtime efficiency: scenario list summary 化、route/depot list summary 化、`tests/test_performance_contracts.py` を追加。
  - scoped runtime loading: `src/runtime_scope.py` を追加し、simulation/optimization run 前に `bff/services/run_preparation.py` で scoped solver_input を生成する構成へ拡張。
  - operational docs: `docs/notes/run_prep_contract.md` を追加。
  - `data-prep/` をカレントディレクトリにして `python -m data_prep.pipeline.build_all` を実行すると
    `ModuleNotFoundError` になる問題を確認。`data-prep/data_prep/` に互換 shim package を追加し、
    root の `data_prep.pipeline.build_all` へ委譲する形で、root / `data-prep/` どちらからでも同じ
    モジュールパスで起動できるよう修正。
  - `data-prep/README.md` に上記の実行方法を追記。

- 2026-03-14 (Tokyu subset emergency recovery)
  - `scripts/tokyu_subset_config.py` を追加し、目黒・瀬田・淡島・弦巻の default depot subset を1か所で編集できるようにした。
  - `scripts/build_tokyu_subset_db.py` を追加し、権威データ `tokyu_bus_depots_master.json` / `tokyu_bus_route_to_depot.csv` を正本にした depot-scoped SQLite subset builder を実装。
  - shared route code を単一 `depot_id` 列で潰さないため、subset DB schema に `route_pattern_depots` / `route_family_depots` / `route_code_depots` bridge を追加した。
  - `bff/services/local_db_catalog.py` を short depot id (`meguro`) / canonical depot id (`tokyu:depot:meguro`) 両対応にし、複数営業所 union・midnight rollover・optimizer-ready trip shape を実装。
  - `bff/routers/catalog_local.py` の `/api/catalog/milp-trips` を複数営業所対応のまま canonical depot ids を返す形へ調整。
  - `src/research_dataset_loader.py` は built manifest があっても routes / timetables / trips が空なら seed bootstrap にフォールバックするよう修正し、研究 bootstrap が止まらないようにした。
  - `README.md` に subset builder の使い方、`TOKYU_DB_PATH=data/tokyu_subset.sqlite`、short depot id API 例を追記。
  - 追加テスト: `tests/test_build_tokyu_subset_db.py`, `tests/test_local_db_catalog_subset.py`, `tests/test_catalog_local_subset.py`

- 2026-03-14 (ODPT key resolution cleanup)
  - `scripts/_odpt_runtime.py` を追加し、ODPT キー解決を共通化した。
  - `scripts/build_tokyu_full_db.py` / `scripts/build_tokyu_subset_db.py` は `--api-key` 未指定時でも `.env` / 環境変数の `ODPT_CONSUMER_KEY` / `ODPT_API_KEY` / `ODPT_TOKEN` を自動参照するよう修正。
  - `data-prep/lib/catalog_builder/odpt_fetch.py` と `tools/fast_catalog_ingest.py` も同じキー名セットを参照するよう揃えた。
  - `README.md` と `bff/services/local_db_catalog.py` の案内文を更新し、`YOUR_ODPT_KEY` がプレースホルダである点と `.env` 自動読込を明記した。

- 2026-03-14 (Tokyu core/full scope + GTFS reconciliation + updater hardening)
  - `data/seed/tokyu/datasets/tokyu_core.json` を 4営業所コア（目黒・瀬田・淡島・弦巻）へ更新し、`included_routes` を固定リストではなく `ALL` に変更して `route_to_depot.csv` を正本化した。
  - `data/seed/tokyu/datasets/tokyu_dispatch_ready.json` も同じ 4営業所スコープで `ALL` 運用に切り替え、preload dataset と core dataset の route drift を防止した。
  - `data/seed/tokyu/datasets/tokyu_full.json` は全 12 営業所を含む定義に整理し直した。
  - `src/research_dataset_loader.py` は dataset definition の depot 順を保持して bootstrap するよう修正し、`tokyu_core` の primary depot が `meguro` で安定するようにした。
  - `data-prep/pipeline/_gtfs_built_artifacts.py` に `gtfs_reconciliation.json` 生成を追加し、route master と `GTFS/TokyuBus-GTFS` の不一致（missing / extra route codes）を dataset 単位で保存するようにした。
  - `data-prep/pipeline/build_all.py` に `--strict-gtfs-reconciliation` を追加し、必要時は照合不一致で build を失敗させられるようにした。
  - `scripts/_stop_timetable_fallback.py` を追加し、ODPT `BusstopPoleTimetable` が 0件でも `trip_stops` から synthetic `stop_timetables` を再構成する fallback を実装した。
  - `scripts/build_tokyu_full_db.py` / `scripts/build_tokyu_subset_db.py` は上記 fallback を利用し、`pipeline_meta` に synthetic stop timetable 件数を記録するよう修正した。
  - `scripts/export_tokyu_sqlite_to_built.py` は `--depot-ids` 未指定時に dataset definition の `included_depots` を自動適用するよう修正し、`tokyu_core` / `tokyu_full` export が seed scope と一致するようにした。
  - `catalog_update_app.py` の Tokyu 更新導線を修正し、デフォルト GTFS パスを `GTFS/TokyuBus-GTFS` に変更、ODPT/GTFS pipeline 実行後に `tokyu_core` / `tokyu_full` built datasets を再生成できるようにした。
  - 追加・更新テスト: `tests/test_stop_timetable_fallback.py`, `tests/test_catalog_update_app.py`, `tests/test_data_prep_gtfs_built_artifacts.py`, `tests/test_build_tokyu_subset_db.py`, `tests/test_research_dataset_loader.py`, `tests/test_bff_research_scenario_bootstrap.py`
  - 確認:
    - `python -m pytest tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_build_tokyu_subset_db.py tests/test_stop_timetable_fallback.py tests/test_data_prep_gtfs_built_artifacts.py tests/test_catalog_update_app.py tests/test_build_tokyu_full_db.py tests/test_odpt_runtime.py -q` → 20 passed
    - `python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch` → pass, `gtfs_reconciliation.json` 生成
    - `python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch` → pass, `gtfs_reconciliation.json` 生成
    - `python scripts/build_tokyu_subset_db.py --depots meguro --route-codes 黒01 --out data/tokyu_subset_stop_verify.sqlite --no-cache` → `BusstopPoleTimetable=0` でも synthetic `stop_timetables=587`

- 2026-03-14 (Scenario bootstrap hardening + GTFS SQLite recovery)
  - `src/research_dataset_loader.py` の parquet 読み出しを再帰正規化し、`stopSequence` / `stop_timetables.items` が parquet 復元で `numpy.ndarray` になっても scenario bootstrap が落ちないよう修正。
  - `bff/routers/master_data.py`, `bff/services/route_family.py`, `bff/store/scenario_store.py`, `bff/mappers/scenario_to_problemdata.py` を list-like 正規化対応にし、built dataset 境界での配列真偽判定エラーを除去。
  - `data-prep/pipeline/build_all.py` は `stops.parquet` / `stop_timetables.parquet` も生成するよう拡張し、`build_dataset_bootstrap()` が built dataset から stops / stop timetables を初期投入できるようにした。
  - `scripts/build_tokyu_gtfs_db.py` を追加し、`GTFS/TokyuBus-GTFS` から Tokyu local SQLite catalog を直接生成できるようにした。route/depot bridge (`route_family_depots`, `route_pattern_depots`, `route_code_depots`) を保持し、GTFS stops / timetable trips / trip stops / stop timetables を SQLite 化する。
  - `scripts/export_tokyu_sqlite_to_built.py` は routes の `startStop/endStop/stopSequence/tripCount` を戻し、`stops.parquet` / `stop_timetables.parquet` も export するよう拡張。`calendar_type=平日/土曜/日曜・休日` は canonical `service_id` (`WEEKDAY` / `SAT` / `SUN_HOL`) に正規化する。
  - `catalog_update_app.py` に `--build-gtfs-db`, `--gtfs-db-dataset-id`, `--gtfs-db-path` を追加し、ODPT/GTFS refresh 後に GTFS-backed SQLite catalog も同時再生成できるようにした。
  - 確認:
    - `python -m pytest tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_data_prep_gtfs_built_artifacts.py tests/test_build_tokyu_gtfs_db.py tests/test_catalog_update_app.py tests/test_bff_graph_router.py tests/test_bff_scenario_to_problemdata.py tests/test_build_tokyu_subset_db.py tests/test_build_tokyu_full_db.py tests/test_stop_timetable_fallback.py tests/test_odpt_runtime.py -q` → 35 passed
    - `python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch` → pass (`routes=41`, `trips=9174`, `stops=876`, `stop_timetables=2387`)
    - `python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch` → pass
    - `POST /api/scenarios` + `POST /api/scenarios/{id}/activate` の API smoke → 201 / 200
    - small-scope smoke: `tokyu_core` 1 route + 1 BEV で duties 生成後 `simulate_problem_data()` 実行 → pass
    - `python scripts/build_tokyu_gtfs_db.py --dataset-id tokyu_core --out data/tokyu_core_gtfs.sqlite` → pass
    - `python scripts/export_tokyu_sqlite_to_built.py --db data/tokyu_core_gtfs.sqlite --dataset-id tokyu_core --built-root data/gtfs_sqlite_export_test` → pass (`stops.parquet` / `stop_timetables.parquet` も出力)

- 2026-03-28 (237d total_cost canonical rerun hardening)
  - 対象 scenario `237d5623-aa94-4f72-9da1-17b9070264be` / prepared input `prepared-c954365437b0f8f6` の total_cost 再実行で、canonical path の main blockers を順に潰した。
  - `bff/services/run_preparation.py`
    - `materialize_scenario_from_prepared_input()` でも catalog stop を再参照し、prepared JSON 側 `stops` が stale / inferred-only でも座標を backfill するよう修正した。
    - これにより 237d scoped case で `ConnectionGraphBuilder().build(..., "BEV")` の outgoing edge が `0` 件しか出ない状態を解消した（座標 backfill 後は多数の feasible successor を再獲得）。
    - `_scenario_hash()` から `optimization_audit` / `simulation_audit` / `problemdata_build_audit` / `__unloaded_artifact_fields__` も除外し、Prepare 直後に `prepared_input_id` が即 stale 化するドリフトを止めた。
  - `src/route_family_runtime.py`
    - `BusstopPole` の番線 suffix 違いを同一 stop family とみなし、`stop_platform_alias` の 0 分 deadhead rule を双方向に自動補完するよう変更した。
    - `...00240050.` / `...00240050.4`、`...00240324.` / `...00240324.1` のような terminal bay 差分で location continuity が壊れていたのを是正した。
  - `src/optimization/milp/model_builder.py`
    - MILP arc enumeration を `milp_max_successors_per_trip`（既定 8）で pruning するよう変更し、237d の dense feasible graph で Gurobi が極端に重くなる問題を抑えた。
  - `src/optimization/milp/solver_adapter.py`
    - MILP 解の duty 復元を `y` の単純 departure sort から、選択 `x/start_arc` をたどる fragment 復元へ変更した。
    - これで solver 自体は full service でも、post validation で「存在しない trip 直結」を拾って infeasible 扱いになる問題を除去した。
  - `src/optimization/common/problem.py`, `src/optimization/common/feasibility.py`, `src/optimization/milp/solver_adapter.py`
    - `required_soc_departure_percent` の小数値 (`0.939` = 0.939%) を 93.9% ratio と誤解する経路を修正した。
    - builder-generated canonical problem では `required_soc_departure_unit="percent_0_100"` を明示し、feasibility / MILP の両方で同じ解釈を使うようにした。
  - `src/optimization/common/evaluator.py`
    - actual charging flow が無い provisional-only plan では fake demand charge / fake grid import を立てないよう修正した。
    - `grid_purchase_cost=0`, `demand_cost=0`, `pv_curtailed_kwh=total PV` を返す fallback に整理し、metaheuristic result の cost breakdown を物理的に誤解しにくい形へ寄せた。
  - `src/optimization/common/feasibility.py`
    - vehicle fragment overlap 判定を duty envelope ベースから actual trip interval ベースへ変更し、同一車両の sparse fragment を false positive で弾かないようにした。
  - `bff/routers/scenarios.py`, `bff/store/scenario_store.py`, `tools/scenario_backup_tk.py`
    - `fixedRouteBandMode=true` / `enableVehicleDiagramOutput=true` を標準デフォルトへ寄せ、route-band diagram を基本出力にした。
    - fragment 上限は scenario 互換性と solve stability を優先して configurable のまま維持した。
  - `bff/routers/optimization.py`
    - canonical solve 完了後に `graph/vehicle_timeline.csv` と `graph/route_band_diagrams/manifest.json` / `*.svg` を直接生成する helper を追加した。
    - これにより BFF/Tk 経由の `mode_milp_only` でも route-band diagram を確認できるようになった。
  - 追加/更新テスト:
    - `tests/test_run_preparation_stop_coords.py`
    - `tests/test_route_family_deadhead_inference.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_reopt_alns_critical_fixes.py`
    - `tests/test_evaluator_provisional_overwrite.py`
    - `tests/test_bev_energy_accounting.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
  - 確認:
    - `python -m pytest tests/test_milp_route_band_settings.py tests/test_reopt_alns_critical_fixes.py tests/test_run_preparation_stop_coords.py tests/test_route_family_deadhead_inference.py tests/test_optimization_canonical_metaheuristics.py tests/test_evaluator_provisional_overwrite.py tests/test_bev_energy_accounting.py` → `38 passed`
    - canonical direct rerun (`output/tmp_canonical_237d/*_cap100.json`):
      - `MILP`: `OPTIMAL`, `served=488/488`, `objective=1640378.9059`
      - `ALNS`: `feasible`, `served=488/488`, `objective=1843087.2393`
      - `GA`: `feasible`, `served=488/488`, `objective=1843520.5726`
      - `ABC`: `feasible`, `served=488/488`, `objective=1827362.2393`
    - いずれも `disable_vehicle_acquisition_cost=true`, `objective_mode=total_cost`, `fixed_route_band_mode=true` で再現した。
    - BFF route sync smoke (`run_optimization()` を同期 submit patch で直実行): `solver_status=optimal`, `served=488/488`, `graph_artifacts.enabled=true`, `diagram_count=4` を確認
    - Tk E2E smoke（withdrawn Tk root + sync run_bg + TestClient 経由）: `Quick Setup保存 -> Prepare -> run-optimization` の一連で `prepared_id_stable=true`, `solver_status=optimal`, `served=488`, `route_band_diagrams=4` を確認

- 2026-03-14 (Catalog-backed dispatch scope for runtime route selection)
  - `bff/services/local_db_catalog.py` に depot / route-family summary 読み出しを追加し、`/api/catalog/depots`, `/api/catalog/depots/{depot_id}/routes`, `/api/catalog/route-families/{route_family_id}/patterns` を `bff/routers/catalog_local.py` から公開した。
  - 軽量 summary は既存 SQLite schema をそのまま使い、追加 catalog table は作らずに `route_families`, `route_patterns`, `route_pattern_depots`, `timetable_trips` を集計する方式にした。
  - `東98` は summary 分類で `東京駅南口 ↔ 等々力操車所` を mainline 固定にし、昼間 split を `short_turn`, `清水` / `目黒郵便局` 端点を Meguro depot-related note として返すようにした。
  - `bff/store/scenario_store.py` の `dispatch_scope` 正規化は `includeRouteFamilyCodes` / `excludeRouteFamilyCodes` を受け付け、runtime では既存どおり route ids に展開するよう拡張した。
  - `frontend/src/features/planning/DispatchScopePanel.tsx` は local SQLite catalog summary を優先表示し、catalog が使えないときだけ scenario master routes へフォールバックするよう変更した。
  - GTFS 未収録路線は runtime scope UI に出さない方針とし、catalog summary 上は「存在しない route family は選択不可」として扱う。
  - 追加確認:
    - `python -m pytest tests/test_catalog_local.py tests/test_bff_scenario_store.py -q` → 29 passed
    - `cd frontend && npm run build` → pass

- 2026-03-14 (Scenario open regression on Windows)
  - `bff/store/master_data_store.py` と `bff/store/trip_store.py` の SQLite artifact connection を `journal_mode=WAL` から `journal_mode=DELETE` に変更した。
  - `bff/store/scenario_store.py` の staging cleanup に retry 付き削除を追加し、直前の SQLite close と競合した `PermissionError [WinError 32]` を吸収するようにした。
  - Windows では scenario save の staging cleanup 時に `master_data.sqlite` / `artifacts.sqlite` の `-wal` / `-shm` 系ハンドルが残り、`GET /api/scenarios/{id}` や `POST /api/scenarios/{id}/activate` が `PermissionError [WinError 32]` で落ちるケースがあったため。
  - 確認:
    - `python -m pytest tests/test_bff_scenario_store.py tests/test_bff_research_scenario_bootstrap.py -q` → 26 passed
    - `TestClient(bff.main:app)` 経由の `GET /api/scenarios/e2379614-2885-40c4-b064-6982bdf57e31` → 200

- 2026-03-17 (Solver mode benchmark script + Tk compare/results parity)
  - `scripts/benchmark_solver_modes.py` を追加し、`mode_milp_only` / `mode_alns_only` / `ga` / `abc` をBFF API経由で順次実行して、runtime/objective比較をJSON/CSV出力できるようにした。
  - 比較値は top-level だけでなく `solver_result.objective_value` / `solver_result.solve_time_seconds` を優先参照する実装にした。
  - `tools/scenario_backup_tk.py` に以下を追加した。
    - 結果詳細ビュー: Simulation/Optimization結果を Summary/Details/Raw JSON で表示。
    - シナリオ比較ビュー: Scenario A/B の Optimization比較・Simulation比較を表示し、主要指標の `delta(B-A)` を確認可能にした。
  - 運用手順書として `readme_operation.md` を追加し、比較実行コマンドと確認項目を明文化した。

- 2026-03-17 (MILP only ERROR pinpoint fix)
  - `mode_milp_only` 実行時の `solver_result.infeasibility_info = "Name too long (maximum name length is 255 characters)"` を確認。
  - 原因は `src/optimization/milp/solver_adapter.py` の Gurobi 変数名に `vehicle_id/trip_id` を長文字列で埋め込んでいたこと。
  - 対策として MILP変数生成時の `name=...` 指定を除去し、自動命名へ変更して名称長制限を回避した。

- 2026-03-22 (Gurobi late-import stabilization across MILP/ALNS/constraints)
  - `run_app.py` 再起動後の `mode_milp_only` で `solver_result.infeasibility_info = "NameError: name 'gp' is not defined"` を確認。
  - 原因は `src/constraints/*` と `src/objective.py` がモジュール読込時の `try: import gurobipy as gp` に失敗したまま `gp` 未定義で残り、`src/milp_model.py` 側だけ solve 時に import 復旧しても stale import が解消されなかったこと。
  - `src/gurobi_runtime.py` を追加し、Gurobi site-packages / DLL path / license 補完と `ensure_gurobi()` を共通化した。
  - `src/milp_model.py`, `src/objective.py`, `src/solver_runner.py`, `src/solver_alns.py`, `src/optimization/milp/solver_adapter.py`, `src/constraints/assignment.py`, `src/constraints/battery_degradation.py`, `src/constraints/charger_capacity.py`, `src/constraints/charging.py`, `src/constraints/duty_assignment.py`, `src/constraints/energy_balance.py`, `src/constraints/optional_v2g.py`, `src/constraints/pv_grid.py`, `src/constraints/soc_threshold_charging.py` を修正し、Gurobi 参照をすべて呼び出し時の `ensure_gurobi()` 経由へ統一した。
  - `tests/test_model_factory_gurobi_import.py` に constraints / objective の late-binding 回帰テストを追加した。
  - 確認:
    - `python -m pytest tests -q` → `50 passed`
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を同じ `tsurumaki` / `WEEKDAY` / `mode_milp_only` で direct smoke 実行 → Gurobi ライセンス読込成功、`status='OPTIMAL'`, `infeasibility_info=''`

- 2026-03-23 (Quick Setup trip counts now use `tokyu_bus_data` when shard runtime is unavailable)
  - Quick Setup の運行種別サマリーと営業所路線選択で `routes=0 / trips=0` になる原因は、`bff/routers/scenarios.py` が `shard_runtime_ready(dataset_id)` を満たさないと day-type summary を一切作らず、route list 側だけ `route.tripCount` 総数にフォールバックしていたこと。
  - `bff/routers/scenarios.py` に `build_timetable_summary_for_scope()` ラッパーを追加し、`data/catalog-fast/tokyu_bus_data` を優先、次に legacy shard runtime を使う順へ変更した。
  - `_route_trip_inventory_for_quick_setup()` は shard readiness に依存せず dataset summary を引くよう修正し、`_shard_scope_params()` も dataset が分かれば summary endpoint から `tokyu_bus_data` に到達できるようにした。
  - これにより Quick Setup の `dayTypeSummaries` と route list の `tripCount/tripCountSelectedDay/tripCountTotal` が同じ day-type 別集計を使うようになった。
  - 実データ確認: scenario `2b0a60cf-61ad-4094-807c-f766641984c6` / depot `tsurumaki` で `dayTypeSummaries = SAT 714 / SUN_HOL 754 / WEEKDAY 974`、route list 先頭も `tripCountSelectedDay` が非 0 で返ることを確認。
  - 追加テスト: `tests/test_quick_setup_route_selection.py` に `tokyu_bus_data` fallback ケースを追加。
  - 確認:
    - `python -m pytest tests -q` → `51 passed`

- 2026-03-23 (Tokyu 全体便数の presentation 向け network scale を `tokyu_bus_data` に追加)
  - 問題は `data/catalog-fast/tokyu_bus_data/summary.json` の `counts.trips=33360` が「平日便数」に見えやすいことだった。実際にはこれは `WEEKDAY/SAT/SUN_HOL` を全部足した総 trip 数で、weekday-only の値ではない。
  - `scripts/build_tokyu_bus_data.py` を修正し、summary に `countSemantics` と `networkScale` を追加した。`networkScale` には day-type 別総便数、day-type 別 active route 数、weekday 比率、route-variant / route-family の分布統計、day-type 別の上位 route variants を持たせた。
  - `data/catalog-fast/tokyu_bus_data/network_summary.json` も追加生成するようにし、presentation 用の規模感だけを summary 本体から独立して読みやすくした。
  - `src/tokyu_bus_data.py` に `load_network_scale_summary()` を追加し、将来 UI/API 側が `summary.json` のネスト構造に直接依存しなくてよいようにした。
  - 実データ再集計結果:
    - route variants: `764`
    - families: `184`
    - weekday trips: `14,437`
    - saturday trips: `8,477` (`58.72%` of weekday)
    - sunday/holiday trips: `10,446` (`72.36%` of weekday)
    - weekday active route variants: `698`
    - weekday average trips per route variant: `18.90` across all 764 variants / `20.68` across active weekday variants
  - これで `33360` は「全 day-type 合計」、発表で使う weekday 規模感は `14437` と明示的に区別できるようになった。

- 2026-03-23 (BEV の電気コスト集計を charging-centric から operating-centric へ修正)
  - 問題は BEV の `energy_cost` / `demand_charge` が「充電したときだけ」発生する設計になっていたことだった。初期 SOC だけで走り切れる解では、BEV が多数運行していても `energy_cost=0`, `demand_charge=0` になり、ICE の fuel cost と対称でなかった。
  - `src/objective.py` を修正し、legacy MILP の電力量料金と電力由来 CO2 を `p_grid_import` / `p_charge` ではなく `x_assign * task_energy_per_slot` ベースで計上するよう変更した。充電は SOC feasibility のためだけに残し、追加コストは課さない。
  - `src/constraints/energy_balance.py` の peak tracking も `p_grid_import` ではなく BEV の走行電力需要ベースへ変更し、`demand_charge_cost` が operating demand を見るようにした。
  - `src/simulator.py` は simulation summary の `total_energy_cost`, `total_demand_charge`, `total_grid_kwh`, `peak_demand_kw` を BEV の走行消費プロファイルから再計算するように変更した。これで solver 後の可視化でも `充電しなかったので電気代 0` にならない。
  - canonical path とのズレも防ぐため、`src/optimization/common/evaluator.py`, `src/optimization/milp/solver_adapter.py`, `src/solver_alns.py` も同じ operating-centric 基準へ揃えた。ALNS heuristic 側には「全 assigned task を BEV energy に混ぜる」退行もあり、あわせて修正した。
  - 回帰テスト `tests/test_bev_energy_accounting.py` を追加し、
    - BEV が charge import に依存せず走行消費分だけ電気代・デマンド料金を持つこと
    - canonical `CostEvaluator` でも charging slot 無しで BEV energy cost が立つこと
    を固定した。
  - 確認:
    - `python -m pytest tests -q` → `53 passed`
    - synthetic smoke: `energy_cost=300.0`, `demand_charge=1000.0`, `grid_kwh=20.0`, `peak_kw=10.0`

- 2026-03-31 (実日 PV / 複数日 planning_days / prepared-input optimization 実行の整備)
  - 問題として、営業所 PV は 2025/08 月平均へ潰してから `depot_energy_assets` へ同期しており、`serviceDate` を変えても実日に応じた日射差が solver 入力へ入っていなかった。加えて、Tk / Quick Setup / Prepare / canonical optimizer の間で `planning_days` と `service_dates` の受け渡しも分断されていた。
  - `tools/scenario_backup_tk.py` を更新し、`運行日 + 計画日数` から `service_dates` を生成して `data/derived/pv_profiles/{depot}_{YYYY-MM-DD}_60min.json` を実日読み込みするよう変更した。PV 同期は `pv_generation_kwh_by_date` / `pv_capacity_factor_by_date` / `pv_profile_dates` / `pv_slot_minutes` を保持し、`pv_capacity_kw` を編集した時は capacity factor から日別発電列を再生成する。UI も `天気モード` を手入力からプルダウンへ変更し、営業所エネルギー資産表で `pv_capacity_kw`, `bess_energy_kwh`, `bess_power_kw` を編集できる前提へ整理した。
  - `bff/routers/scenarios.py`, `bff/routers/simulation.py`, `bff/services/simulation_builder.py`, `bff/services/run_preparation.py`, `src/optimization/common/builder.py` を通して `service_dates`, `planning_days`, `planning_horizon_hours` を保持するようにし、canonical builder は multi-day trip / tariff / PV slot を正しく複製できるよう修正した。途中で自分から上げた不具合として `ProblemBuilder.build_from_scenario()` が `planning_days` を受けておらず、さらに multi-day price slot 複製で存在しない `co2_kg_per_kwh` を参照していたため、両方修正して回帰テストを追加した。
  - 追加で、MILP engine が solver metadata 用に `MILPModelBuilder.build()` を一度回し、その後 adapter 側で同じ巨大モデルを Gurobi 用に再構築していた。これでは 974 trip case の `mode_milp_only` 比較が極端に重くなるため、metadata は lightweight count 集計へ置き換え、重複 model build を除去した。
  - 最適化 API 実行ではさらに 2 段階の lock 問題を自分から確認した。1 つ目は `prepared_input` から materialize した scope artifact を `rebuild_dispatch=false` でも SQLite へ書き戻していたことで、background job から `timetable_rows` 保存時に `database is locked` を起こした。2 つ目は solve 完了後の `optimization_result` 保存でも同じ lock が起きたことだった。
  - 対策として `bff/routers/optimization.py` は `rebuild_dispatch=false` の prepared-input solve では scope artifact を scenario DB へ戻さず、materialized scenario をそのまま canonical optimizer へ渡すよう変更した。さらに `bff/store/scenario_store.py` では scalar artifact (`optimization_result` / `simulation_result` / `dispatch_plan`) の SQLite 保存が lock した場合、既存 refs の JSON sidecar へフォールバック保存し、読取側 `get_field()` も sidecar を見に行くようにした。これで background optimization job が結果保存で落ちず、`GET /api/scenarios/{id}/optimization` から結果取得できる。
  - 実行確認として `FastAPI TestClient` 経由で scenario `237d5623-aa94-4f72-9da1-17b9070264be` を対象に、`serviceDate=2025-08-04`, `serviceDates=["2025-08-04"]`, `planningDays=1`, `fixedRouteBandMode=true`, `disableVehicleAcquisitionCost=true`, `objectiveMode=total_cost`, `weatherMode=actual_date_profile`, `pvProfileId=tsurumaki_2025-08-04_60min` を Quick Setup へ反映したうえで、既存 BFF API (`/simulation/prepare` → `/run-optimization` → `/jobs/{id}` → `/optimization`) を 4 モードで実行した。
  - 比較結果は `output/optimization_comparison_api_237d_actual_pv_2025-08-04_final.json` に保存した。要約は以下の通り。
    - `mode_milp_only`: `solver_status=time_limit`, `objective_value=9740000.0`, `trip_count_served=0`, `trip_count_unserved=974`, `solve_time_seconds=97.6972`
    - `mode_alns_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=65.7632`
    - `mode_ga_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=62.1353`
    - `mode_abc_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=63.2371`
  - 回帰テスト:
    - `tests/test_scenario_backup_tk_pv_sync.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_problem_builder_depot_energy_asset_controls.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_bff_reoptimization_actual_soc_forwarding.py`
    - `tests/test_milp_engine_lightweight_stats.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py bff/routers/scenarios.py bff/routers/simulation.py bff/services/simulation_builder.py bff/services/run_preparation.py bff/routers/optimization.py bff/store/scenario_store.py src/optimization/common/builder.py src/optimization/milp/engine.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_scenario_backup_tk_pv_sync.py tests/test_simulation_builder_prepare_scope.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_bff_reoptimization_actual_soc_forwarding.py tests/test_milp_engine_lightweight_stats.py tests/test_prepared_scope_execution.py tests/test_optimization_canonical_metaheuristics.py tests/test_scenario_store_dispatch_scope_overlay.py -q` → pass

- 2026-03-23 (Prepared-scope optimization と scenario artifact の整合を修正)
  - 問題は Tk/BFF の既定フローで `rebuild_dispatch=false` のまま最適化を完了すると、`optimization_result` だけは更新される一方で scenario 側の `trips` / `timetable_rows` / `stats` が古いまま残り、フロント・BFF・最適化監査で見える件数が食い違うことだった。
  - さらに `scenario_store.set_field(..., invalidate_dispatch=True)` の direct row-artifact 更新経路は `timetable_rows` / `stop_timetables` 更新時に stale な `trips` / `duties` / `optimization_result` を落としておらず、timetable-first なのに古い dispatch/optimization が残り得た。
  - `bff/routers/optimization.py` では prepared input 直実行でも `trips` / `timetable_rows` / `stops` / `stop_timetables` を scenario artifact へ同期するようにし、dispatch 再構築を省く run では stale `graph` / `blocks` / `duties` / `dispatch_plan` を明示クリアするよう修正した。
  - 同時に `optimization_result` と `optimization_audit` に `prepared_input_id` / `prepared_scope_summary` を保存し、どの prepared scope で solve したかを追跡できるようにした。
  - `bff/store/scenario_store.py` では direct row-artifact 更新後も meta を更新し、`invalidate_dispatch=True` 時は scenario status を `draft` に戻し、`tripCount` / `dutyCount` を 0 リセットしたうえで stale dispatch/optimization artifact を削除するよう修正した。
  - ドキュメントも現行保存先 `outputs/prepared_inputs/<scenario_id>/<prepared_input_id>.json` に合わせて README / run prep contract / reproduction note を更新した。
  - 回帰テスト:
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m pytest tests/test_prepared_scope_execution.py tests/test_scenario_store_dispatch_scope_overlay.py` → pass
    - `python -m pytest tests` → `62 passed`
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を `tsurumaki` / `WEEKDAY` / `mode_milp_only` / `rebuild_dispatch=false` で再実行し、`prepared_input_id=prepared-e0fb1e07bb3635d8`, `trip_count_served=702`, `tripCount=702`, `timetableRowCount=702`, `solver_status=OPTIMAL` を確認

- 2026-03-23 (Graph Exports に route-band 別の車両ダイヤ SVG を追加)
  - 要件は「固定路線バンドで路線間車両トレードを許可しない run では、鉄道ダイヤグラム風に route ごとの車両位置推移を見たい」というものだった。
  - `src/result_exporter.py` を拡張し、optimization run 配下の `graph/vehicle_timeline.csv` に `vehicle_type` / `band_id` / `route_family_code` / `route_series_code` / `event_route_band_id` を追加した。
  - 同じ情報から `graph/route_band_diagrams/manifest.json` と `graph/route_band_diagrams/*.svg` を生成するようにし、1 band 1 図で `vehicle_id [ICE/BEV]` 凡例付きの time-space diagram を出せるようにした。
  - 初版は「車両の主担当 band」で grouping していたため、同じ車両が他路線を担当した stop が route graph に混入する欠陥があった。
  - 2026-03-23 夜に `bff/mappers/scenario_to_problemdata.py` から route `stopSequence` を graph export context として渡し、SVG 側は actual `band_id` 単位で再 grouping するよう修正した。これで route 軸は当該路線の stop だけになり、上り/下り/区間便/入出庫便は同一路線グラフへ統合、ICE/BEV は色系統と type legend で識別できる。
  - その後、prepared payload 内の `stop_time_sequences` が stop-level ではなく trip-level 行だったため、中間 stop 時刻が取れていない問題を追加で確認した。`data/catalog-fast/tokyu_bus_data/route_stop_times/{route_id}.jsonl` から selected trip の stop-time を補完するよう変更し、catalog-fast に無い trip だけ route `stopSequence` 上の線形補間へフォールバックするようにした。
  - さらに、stop 軸の順番を adjacency 推定で並べ替えていたため、variant stop が末尾へ落ちる問題を追加で確認した。route `stopSequence` を本線基準でマージする方式へ変更し、区間便は本線の間へ差し込み、本線外 terminal は top/bottom side lane として分離した。
  - 2026-03-23 18:30 頃、Graph SVG だけ夕方便が欠けて見える問題を追加で確認した。原因は slot index を `00:00` 起点として ISO 化していたことで、実際には `simulation_config.start_time=05:00` 起点の `vehicle_timeline.csv` / `trip_assignment.csv` が stop-time polyline と 5 時間ずれていた点だった。`src/result_exporter.py` で planning start を graph export builder に通し、slot->時刻変換を補正した。
  - 同時に、route-band SVG の時間軸を常に `00:00-23:59` の full-day 固定へ変更し、plot width を拡大、clip-path を導入して path がフレーム外へ飛んでも表示破綻しないようにした。
  - さらに、営業所入出庫の条件緩和が図に出ていなかったため、band 図の row 生成を `vehicle_timeline.csv` 全体から vehicle ごとに再構成する方式へ変更した。これにより、その日最初の便の前の `depot_out`、最後の便の後の `depot_in`、同一 band 内の長い空き時間や charge row を挟む temporary depot stay を `弦巻営業所` などの depot side lane として推定描画できるようにした。
  - side lane label を top/bottom に二重登録して同じ depot 名が軸に 2 回出る不具合も追加で確認し、`_diagram_location_labels()` で重複抑止を入れた。
  - `mixed_event_route_band_detected=true` は「その route graph に出てくる車両が同日に他 band も担当した」ことを示す警告値へ意味を変更した。
  - 回帰テスト `tests/test_graph_export_route_band_diagrams.py` を拡張し、SVG の生成、ICE/BEV 凡例、full-day 軸、slot 時刻補正、depot stay 推定、manifest 出力を固定した。
  - 実データ確認:
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を `prepared_input_id=prepared-23163ca5b3496ca1`, `tsurumaki`, `WEEKDAY`, `mode_milp_only`, `rebuild_dispatch=false` で再実行し、`outputs/tokyu/2026-03-22/optimization/2b0a60cf-61ad-4094-807c-f766641984c6/tsurumaki/WEEKDAY/run_20260323_1833/graph/route_band_diagrams/` に `黒06.svg`, `黒07.svg`, `渋21.svg`, `渋22.svg`, `渋23.svg`, `渋24.svg` が生成されることを確認
    - `run_20260323_1833/graph/vehicle_timeline.csv` は `min_start=2026-03-22T05:30:00+09:00`, `max_end=2026-03-22T23:15:00+09:00` で、夕方便が CSV / SVG ともに落ちていないことを確認
    - `渋22.svg` は `viewBox width=3556`, `plot width=2880`, 軸 `00:00-23:59`, stop 軸末尾 `弦巻営業所`, `stroke-dasharray="8 5"` の depot deadhead と `stroke-dasharray="2 6"` の depot stay を含むことを確認
    - `python -m pytest tests` → `66 passed`

- 2026-03-23 (UI: 営業所別充電器管理・充電器出力グローバルパラメータ廃止・バス導入費無効化チェックボックス追加)
  - **変更内容**:
    - `tools/scenario_backup_tk.py` の基本パラメータ欄から「充電器出力(kW)」グローバル入力を削除。充電器出力は `営業所充電器設定`（`normalChargerPowerKw` / `fastChargerPowerKw`）から参照するように統一。`use_selected_depot_charger_inventory=True` は既に有効だったため、mapper 側の動作変更はなし。
    - `simulation_settings` dict から `charger_power_kw` 送信も廃止（`PrepareSimulationSettingsBody.charger_power_kw` フィールドは残存、デフォルト 90 kW）。
    - トップバーのボタン名「営業所別車両管理」→「**営業所別充電器管理**」に変更。ウィンドウタイトルも同様に更新。車両管理は「車両・テンプレート管理」ボタンに集約。
    - 「営業所別充電器管理」画面の「選択営業所を車両タブへ反映」ボタンを削除し、「保存」ボタンのみ残した。
    - 基本パラメータ欄に **「バス導入費の日割り計算を無効化 (disable_vehicle_acquisition_cost)」チェックボックス**を追加（デフォルト OFF）。
  - **バックエンド対応**:
    - `bff/routers/simulation.py` の `PrepareSimulationSettingsBody` に `disable_vehicle_acquisition_cost: bool = False` を追加。
    - `bff/services/simulation_builder.py` の `simulation_config` dict に `disable_vehicle_acquisition_cost` を追加で渡すよう変更。
    - `bff/mappers/scenario_to_problemdata.py` の `build_problem_data_from_scenario` で `simulation_cfg.get("disable_vehicle_acquisition_cost", False)` を読み、`True` のとき全車両の `fixed_use_cost` を `dataclasses.replace` で 0.0 に上書きするよう変更。
  - **ドキュメント反映**: `docs/constant/formulation.md` O4 節・`docs/constant/implementation_status.md` O4 行を更新。
  - **既存テスト**: `tests/test_problem_builder_disable_acquisition_cost.py` が既に存在し pass 確認済み。

- 2026-03-23 (Tokyu route-family trip replication を全系統で除去し、front/back/最適化の入力 source を統一)
  - 問題は `data/built/tokyu_full/trips.parquet` / `timetables.parquet` の再生成ロジックが、GTFS trip を `routeFamilyCode + depotId` に一致する全 route variant へ複製していたことだった。代表例の `meguro / 黒01` では 587 便が family 内 9 route に複写され、`__vN` 除外後も base trip 群が先頭 route に偏って残るため、営業所路線選択・backend summary・最適化入力が route variant と一致しなかった。
  - `scripts/rebuild_built_from_normalized.py` を修正し、trip-to-route mapping を family-based replication から `trip_id` に埋め込まれた `odptPatternId` の exact match へ変更した。fallback は `(routeFamilyCode, depotId, first_stop_id, last_stop_id)` の単一候補だけに限定し、1 便を複数 route に複写しないようにした。
  - これにより `data/built/tokyu_full` を上書き再生成し、`trips.parquet=33354`, `timetables.parquet=33354`, `__vN=0` になった。`黒01` は `31 / 22 / 28 / 10 / 495 / 1` の route-variant 別 count に戻り、`587 x 9` の増殖は解消した。
  - ただし built GTFS export と `data/catalog-fast/tokyu_bus_data` の間に route-level で 4 件だけ残差（`あ28`, `空港` 2 variant, `自02`）があり得るため、現在系では `src/runtime_scope.py`, `src/research_dataset_loader.py`, `bff/services/run_preparation.py`, `bff/routers/graph.py`, `bff/routers/scenarios.py` を修正し、Tokyu 系 timetable/trip scope load は `tokyu_shards` の次に `data/catalog-fast/tokyu_bus_data` を優先するよう揃えた。これで front/back/最適化計算は built の stale/misaligned route trip count に依存しない。
  - 追加で、day-type 分離が route list 表示で落ちないよう `src/research_dataset_loader.py` の bootstrap route metadata に `tripCountsByDayType` / `tripCountTotal` を埋め込み、`bff/routers/master_data.py` の `/scenarios/{id}/routes` は `serviceId` 指定時、または scenario の現在 `dispatch_scope.serviceId` を既定 selected day として `tripCountSelectedDay` を返すよう修正した。これで route list API も total count ではなく selected day count を既定表示できる。
  - 監査として `data/catalog-fast/tokyu_bus_data` の全 764 route variant を再走査し、同一 service 内で `origin + destination + departure + arrival` が重複する route は `0`、別 route 間で exact stop-time sequence まで一致する duplicate も `0` を確認した。terminal/time だけ同じ cross-route signature は 8 件あったが、すべて stop sequence が異なる別系統だった。
  - 回帰テスト:
    - `tests/test_rebuild_built_from_normalized.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_research_dataset_bootstrap_alignment.py`
  - 確認:
    - `python -m pytest tests -q` → `78 passed`
    - `python scripts/rebuild_built_from_normalized.py` 実行済み
    - `src.runtime_scope.load_scoped_trips()` で `odpt-route-9e1a26bc3c19` は `WEEKDAY=11`、residual mismatch route `odpt-route-ff937d39d487` も runtime では `WEEKDAY=7, SUN_HOL=7` を返し、`tokyu_bus_data` 側 count と一致することを確認

- 2026-03-23 (再起動・再読込後に route trip count が壊れる問題を修正し、Tokyu route/day-type count を scenario reload でも維持)
  - 実シナリオ `2b0a60cf-61ad-4094-807c-f766641984c6` を確認すると、`outputs/scenarios/.../master_data.sqlite` の `routes` に古い `tripCount=587` が残ったまま、`artifacts.sqlite` の `timetable_rows` / `trips` が 0 件へ上書きされるケースがあった。これにより、アプリ再起動後は route list / Quick Setup が stale route metadata へフォールバックし、`黒01` をはじめ高本数系統が「平日・土曜・休日で分別されず 587 が何個もある」表示になっていた。
  - 根本原因は `bff/store/scenario_store.py` の `_load_shallow()` が heavy artifact を空既定値で埋めた doc を返し、その doc を `_save()` する経路が row/parquet artifact を丸ごと空で再保存していたことだった。`set_public_data_state()` など master-only 更新でも dispatch artifact を消し得る状態だった。
  - 対策として `scenario_store._save()` に unloaded artifact 保護を追加し、`_load_shallow()` 由来の未ロード artifact は既存 `artifacts.sqlite` / parquet / json を staging へコピーして保持するよう修正した。逆に `_invalidate_dispatch_artifacts()` で明示的に無効化した `trips` / `graph` / `duties` / result artifact は unloaded マーカーから外し、意図した invalidation はそのまま効くようにした。
  - 同時に `scenario_store._load_shallow()` / `_load()` で Tokyu の route metadata を preload master から自動補修するようにし、既存 scenario の `routes.tripCount`, `tripCountTotal`, `tripCountsByDayType` が stale でも request ごとに現行 `tokyu_bus_data` ベースの値へ戻るようにした。
  - `get_field()`, `count_field_rows()`, `page_field_rows()`, `page_timetable_rows()`, `count_timetable_rows()`, `get_field_summary()`, `summarize_route_service_trip_counts()` も、scenario artifact が空のときは `data/catalog-fast/tokyu_bus_data` へフォールバックして件数・行・route/service summary を返すよう修正した。これで stale / missing artifact があっても front/back の count 表示は current Tokyu dataset に揃う。
  - Quick Setup には追加の穴があり、summary 側が `0 便 route` を返さないため、`黒01` の 0 便 variant が `tripCountsByDayType={}` 扱いで route list に残っていた。`bff/routers/scenarios.py` で route metadata の `tripCountsByDayType` を事前 seed し、summary count は上書きマージに変更したことで、0 便 variant は非表示、正の count variant だけが selected day 別本数で残るようにした。
  - 実データ確認:
    - `bff.routers.master_data.list_routes('2b0a60cf-61ad-4094-807c-f766641984c6', service_id='WEEKDAY')` で `黒01` は `11 / 8 / 12 / 2 / 191 / 1`、`tripCountTotal` は `31 / 22 / 28 / 10 / 495 / 1` を返すことを確認
    - 同じ scenario を `meguro + WEEKDAY` 相当に正規化した Quick Setup payload では、`黒01` の 0 便 variant 3 件が消え、残る 6 variant が source 通りの day-type count を返すことを確認
  - 回帰テスト:
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_master_data_route_counts.py`
  - 確認:
    - `python -m pytest tests -q` → `82 passed`

- 2026-03-24 (固定路線バンド UI 整理・全 route family/便数監査・営業所別 PV 平均自動同期)
  - 問題として、Quick Setup 画面に「営業所内車両トレード」と「車両固定バンド」で意味の重なる操作が残っており、route 固定の要件が UI 上で曖昧だった。また route family のひも付けずれや day-type 便数ずれが front 表示だけでなく最適化入力へ混入するリスクが残っていた。
  - `tools/scenario_backup_tk.py` では営業所内 route trade の単独チェックを見せない構成に変更し、`日次路線固定（車両固定バンド）` を ON にすると `allowIntraDepotRouteSwap=False` と `enable_vehicle_diagram_output=True` を自動適用するよう整理した。最適化結果を確認しやすいよう `ダイヤグラム表示` ボタンも追加した。
  - 追加で自分から見つけた問題として、途中で `配車済み路線のみ` という別チェックを足すと既存 optimize 結果依存の分岐が増え、今回要件の route 固定と責務が混ざる状態だったため、その UI と処理は削除した。
  - `bff/services/route_catalog_audit.py` を追加し、scenario の全 route を対象に `routeFamilyCode` 欠落、派生 family code との不一致、同一営業所内の family 分裂、`data/catalog-fast/tokyu_bus_data` 実便数との差分を監査するようにした。`bff/services/run_preparation.py` は prepare 時にこの監査を必ず実行し、warning と `scope_summary.route_catalog_audit` へ結果を残すよう変更した。これにより、便数や family の不整合を黙って solver へ流さない。
  - 営業所別 PV は `data/derived/pv_profiles/*_2025-08-*_60min.json` を読み、選択営業所ごとに 2025/08 の 1 か月平均を自動生成して `depot_energy_assets` へ同期するようにした。weather mode は自由入力をやめて readonly のプルダウンに変更し、既定値を `solcast_avg_2025_08_60min` に揃えた。
  - `bff/routers/simulation.py` / `bff/services/simulation_builder.py` も更新し、prepare payload から `fixed_route_band_mode`, `enable_vehicle_diagram_output`, `objective_preset`, `pv_profile_id`, `weather_mode`, `weather_factor_scalar` を保持できるようにした。
  - 回帰テスト:
    - `tests/test_route_catalog_audit.py`
    - `tests/test_run_preparation_audit_warnings.py`
    - `tests/test_scenario_backup_tk_pv_sync.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_run_preparation_hash.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_solcast_pv_profiles.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_problem_builder_depot_energy_asset_controls.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m py_compile bff/services/route_catalog_audit.py bff/services/run_preparation.py bff/routers/simulation.py bff/services/simulation_builder.py tools/scenario_backup_tk.py` → pass
    - 上記回帰テストの対象実行合計 → `49 passed`

- 2026-03-24 (全営業所・全 route の family 分類ロジックを再設計し、day-type trip count 欠落を補修)
  - 追加で自分から上げた問題として、`routeFamilyCode` の元ロジックが `高速` / `空港` / `直行` / `急行` / `出入庫` の generic code をそのまま family code にしており、無関係な長距離路線や直行便まで 1 family に束ねていた。その結果、`routeVariantTypeManual=main` の legacy override も相まって、`東98` のような入出庫便だけでなく、高速・空港系も正しい本線/区間便/入出庫便に落ちない状態だった。
  - `bff/services/route_family.py` では stopSequence が stop ID のまま比較されていた問題を修正し、`data/catalog-fast/tokyu_bus_data/stops.jsonl` / `normalized/stops.jsonl` から stop name を解決してから corridor 判定するよう変更した。あわせて terminal 比較は `日吉駅` と `日吉駅東口`、`溝の口駅` と `溝の口駅南口` のような駅出口差分を吸収する coarse normalization を追加した。
  - `bff/services/runtime_route_family.py` を中心に runtime 再分類を強化し、legacy `classificationSource=manual_override` は user manual override でない限り無視、同 family の depot feeder corridor まで見て `depot_in/depot_out` を判定するよう見直した。これで `東98` は `東京駅南口->清水` 系を本線、`等々力操車所` 発着や `目黒郵便局->等々力操車所` を入出庫便として正しく再分類できるようにした。
  - family code 抽出も見直し、generic code は terminal pair ベースの family code (`高速:河口湖駅⇔渋谷駅(マークシティ)` など) に再分解した。これにより `高速` 46 variant は 11 family、`空港` 79 variant は 23 family、`直行` 10 variant は 5 family、`急行` 3 variant は 2 family、`出入庫` 7 variant は 4 family に正しく分かれた。最終監査では runtime route variant count が `main_inbound=203, main_outbound=199, short_turn=134, main=94, depot_in=47, depot_out=44, branch=43, unknown=0` になり、generic code の素通し family は 0 件になった。
  - 便数側では `src/research_dataset_loader.py` の `_apply_route_day_type_counts()` に穴があり、Tokyu catalog の route index を `depot_ids` 付きで引くと営業所未割当 route の `tripCountsByDayType` だけ落ち、`tripCountTotal` だけ残る route が 254 件あった。ここは route 単位で `depot_ids=None` の fallback lookup を追加し、全 route が authoritative `tokyu_bus_data.route_trip_counts_by_day_type()` と一致するよう補修した。
  - さらに `bff/services/master_defaults.py` と `bff/store/scenario_store.py` も更新し、preload master data と既存 scenario repair の両方で全 route を `reclassify_routes_for_runtime()` に通してから保存・返却するようにした。これで API 表示だけでなく、保存済み scenario の `routes` 自体が補修済み family/variant metadata を持つ。user manual override は `classificationSource/manualClassificationLocked` ごと保持したまま再適用する。
  - 影響範囲として `bff/routers/master_data.py`, `bff/routers/scenarios.py`, `bff/routers/graph.py`, `bff/mappers/scenario_to_problemdata.py`, `src/research_dataset_loader.py` を runtime 再分類前提へ統一し、front 表示・Quick Setup・scope export・最適化入力が同じ family/variant 判定を使うよう揃えた。
  - 回帰テスト:
    - `tests/test_runtime_route_family.py`
    - `tests/test_master_defaults_runtime_repair.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_research_dataset_bootstrap_alignment.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_route_catalog_audit.py`
  - 確認:
    - `python -m py_compile bff/services/route_family.py bff/services/runtime_route_family.py src/research_dataset_loader.py tests/test_runtime_route_family.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_runtime_route_family.py tests/test_master_data_route_counts.py tests/test_quick_setup_route_selection.py tests/test_research_dataset_bootstrap_alignment.py -q` → `20 passed`
    - `PYTHONPATH=C:\master-course pytest tests/test_runtime_scope_route_mapping.py tests/test_prepared_scope_execution.py tests/test_milp_route_band_settings.py tests/test_simulation_builder_prepare_scope.py tests/test_route_catalog_audit.py -q` → `18 passed`

- 2026-03-25 (Quick Setup front に route truth を出すため、運行種別サマリと営業所路線選択 UI を再設計)
  - 問題として、route family / trip count の backend 補修後も `Quick Setup` payload が痩せており、`運行種別サマリ` は `routeCount` / `tripCount` しか持たず、`営業所・路線選択` も family label と運行種別内訳が見えなかった。そのため、`東98` のような再分類済み line でも front では「何が本線で、何が入出庫便か」が読みにくかった。
  - 追加で自分から上げた問題として、検索を掛けた状態で family の一部 variant だけを出す UI は件数と便数の誤読を生みやすかった。ここは filter を「表示対象の depot / family を絞るだけ」に限定し、表示した family の route / trip 集計は常に full truth を返す方針に直した。
  - `bff/routers/scenarios.py` の quick setup 集計を拡張し、`dayTypeSummaries` に `familyCount` と `main / shortTurn / depot / branch / unknown` の route / trip 内訳を追加した。`build_timetable_summary_for_scope()` が使えない fallback 時でも、current scenario の route metadata から selected day の summary が 0 固定にならないよう補修した。
  - 同時に depot payload も拡張し、`familyCount`, `visibleFamilyCount`, `visibleRouteCount`, `tripCountSelectedDay`, `selectedTripCount`, variant 別 route / trip count を返すよう変更した。route list は route_limit のまま返しつつ、depot summary は full visible route set から集計するため、front の総量表示が route_limit に引きずられない。
  - 2026-03-25 夜に追加で確認した問題として、Quick Setup payload が `selectedDepotIds` で route 一覧自体を絞っていたため、シナリオごとに front で見える路線が変わっていた。要件は「シナリオで変わってよいのは選択状態と曜日別便数だけ」であり、表示母集団は固定であるべきなので、payload 生成は常に全営業所・全 route を対象にし、`selectedDepotIds` / `selectedRouteIds` は check state だけへ使うよう修正した。
  - さらに `東98 / 渋41 / 渋42` を確認すると、runtime では正しく main / branch / short_turn / depot へ再分類されている一方、family header は `routeFamilyLabel=東98` のような code-only 表示のままだった。`bff/routers/scenarios.py` に family terminal label 補完を追加し、同営業所・同 family の全 variant から主系統の terminal pair を拾って `東京駅南口 ⇔ 清水`, `渋谷駅 ⇔ 大井町駅`, `渋谷駅 ⇔ 大崎駅西口` のような表示へ置き換えた。
  - `tools/scenario_backup_tk.py` では `運行種別サマリ` を `service / 種別 / familyCount / variantCount / tripCount / 運行種別内訳` 表示へ拡張した。`営業所・路線選択` には検索ボックス、表示/選択サマリ、family label の `code | label` 表示、depot/family 行の `本線 / 区間 / 入出庫 / 枝線` 便数内訳を追加した。
  - route filter は `routeFamilyCode`, `routeFamilyLabel`, `routeLabel`, `variantLabel`, `depotId` などを対象に全文検索しつつ、open した family の child route は full family variant を見せるようにした。これで `東98` と打った時も、該当 family を見つけたあとに本線・入出庫便の全 variant をそのまま確認できる。
  - 回帰テスト:
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_route_catalog_audit.py`
  - 確認:
    - `python -m py_compile bff/routers/scenarios.py tools/scenario_backup_tk.py tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py -q` → `20 passed`
    - `PYTHONPATH=C:\master-course pytest tests/test_master_data_route_counts.py tests/test_runtime_scope_route_mapping.py tests/test_simulation_builder_prepare_scope.py tests/test_route_catalog_audit.py -q` → `10 passed`

- 2026-03-26 (Quick Setup「設定保存」で基本パラメータ一式が保存されない不具合を修正)
  - 問題として、`tools/scenario_backup_tk.py` の `設定保存`（`save_quick_setup`）が `initial_soc / soc_min / soc_max / disable_vehicle_acquisition_cost / tou_pricing / no_improvement_limit / destroy_fraction` を API へ送っておらず、再読込時に基本パラメータ欄と ALNS 関連が既定値へ戻る状態だった。
  - 追加で backend 側でも `bff/routers/scenarios.py` の `UpdateQuickSetupBody` が上記キーを受理しておらず、フロントで送っても保存できない経路があった。
  - 対応として、Quick Setup API の request/response を拡張し、`solverSettings` と `simulationSettings` の双方で `noImprovementLimit / destroyFraction / initialSoc / socMin / socMax / disableVehicleAcquisitionCost / touPricing` を往復できるようにした。
  - `update_quick_setup()` では `scenario_overlay`（solver/cost）と `simulation_config` へ同キーを保存する処理を追加し、`load_quick_setup()` は TOU 配列を UI テキストへ復元するフォーマッタを追加して再表示できるようにした。
  - これにより、`バス導入費の日割り計算を無効化` を含む基本パラメータの保存漏れが解消され、再Prepare時の設定ドリフトを抑制した。

- 2026-03-31 (結果画面で非ゼロの最適化内訳を前面表示し、API 保存済み結果と UI の見え方を一致させた)
  - 問題として、BFF の `optimization_result` には `driver_cost / vehicle_cost / penalty_unserved / total_cost` が非ゼロで保存されている一方、`tools/scenario_backup_tk.py` の Summary タブは `energy_cost` など一部しか拾わず、`summary.trip_count_served / trip_count_unserved / vehicle_count_used` も表示していなかった。そのため「結果は出ているのに、フロントでは内訳が見えない」状態になっていた。
  - 追加で自分から上げた問題として、cost breakdown の表示順が未定義で、payload に存在しない primary key まで空行で出す余地があり、非ゼロ項目を素早く確認しにくかった。
  - 対応として `tools/scenario_backup_tk.py` に結果表示用ラベル・数値整形・cost breakdown 並び替え helper を追加し、Summary タブで `総コスト / 担当便数 / 未担当便数 / 使用車両数 / 電力コスト / 車両コスト / 乗務員コスト / 未担当ペナルティ` を非ゼロ強調付きで表示するようにした。
  - さらに `Cost Breakdown` タブを新設し、`total_cost` を先頭に非ゼロ項目を上段へ並べ、`share` 列で構成比も見えるようにした。`Details` タブも `summary` ブロックを含めて表示し、`cost_breakdown` は同じ並び順で確認できるよう揃えた。比較画面も同じメトリクス群に拡張している。
  - 実データ確認として、`GET /api/scenarios/237d5623-aa94-4f72-9da1-17b9070264be/optimization` の最新結果から `total_cost=6052927.3224609075`, `served_trips=638`, `unserved_trips=336`, `vehicle_count_used=55`, `energy_cost=202796.50054309692`, `vehicle_cost=483447.4885844756`, `driver_cost=2006683.333333335`, `penalty_unserved=3360000.0` を UI helper が正しく抽出できることを確認した。
  - 回帰テスト:
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_scenario_backup_tk_pv_sync.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py tests/test_scenario_backup_tk_dataset_options.py` → pass
    - `$env:PYTHONPATH='C:\master-course'; pytest tests\test_scenario_backup_tk_dataset_options.py tests\test_scenario_backup_tk_pv_sync.py -q` → `15 passed`

- 2026-03-31 (車両コスト・運転士コスト・その他コストの個別トグルを UI / Quick Setup 保存 / prepare / builder に通した)
  - 問題として、コスト内訳は結果で見えるようになっても、どのコスト成分を目的関数に含めるかを front から明示的に切り替える手段がなかった。また既存の `disable_vehicle_acquisition_cost` は車両コストの内訳調整であって、車両・運転士・その他の大分類 ON/OFF とは責務が異なっていた。
  - 追加で自分から上げた問題として、ここを UI だけで実装すると「チェックは切り替わるが scenario 保存で戻る」「保存されても prepare / solver に届かない」経路が発生するため、Quick Setup payload、`simulation_config` 保存、prepare 時の builder 反映まで同時に揃える必要があった。
  - `tools/scenario_backup_tk.py` の `基本パラメータ` に `コスト成分ON/OFF` 表を追加し、`車両コスト / 運転士コスト / その他コスト` を各チェックボックスで切り替えられるようにした。Quick Setup の load/save と prepare payload に `enableVehicleCost / enableDriverCost / enableOtherCost` を追加し、未設定シナリオは互換のため `True` 扱いにしている。
  - `bff/routers/scenarios.py` は Quick Setup API の request/response に上記 3 フィールドを追加し、`simulation_config` へ保存するよう更新した。`bff/routers/simulation.py` と `bff/services/simulation_builder.py` も prepare body から `enable_vehicle_cost / enable_driver_cost / enable_other_cost` を scenario へ保持するよう通している。
  - `src/optimization/common/builder.py` では cost component flag を canonical problem metadata と objective weights に反映し、`vehicle` OFF 時は vehicle weight を 0、`other` OFF 時は energy/demand/unserved/switch/degradation/deviation を 0 に落とすようにした。`src/optimization/common/evaluator.py` は同 flags を見て cost breakdown の `vehicle_cost / driver_cost / energy_cost / demand_cost / co2_cost / total_cost / total_cost_with_assets` などを 0 化するため、結果画面にもトグル状態がそのまま出る。
  - 回帰テスト:
    - `tests/test_quick_setup_advanced_persistence.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_problem_builder_cost_component_toggles.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py bff/routers/scenarios.py bff/routers/simulation.py bff/services/simulation_builder.py src/optimization/common/builder.py src/optimization/common/evaluator.py tests/test_quick_setup_advanced_persistence.py tests/test_simulation_builder_prepare_scope.py tests/test_problem_builder_cost_component_toggles.py` → pass
    - `$env:PYTHONPATH='C:\master-course'; pytest tests\test_quick_setup_advanced_persistence.py tests\test_simulation_builder_prepare_scope.py tests\test_problem_builder_cost_component_toggles.py tests\test_scenario_backup_tk_dataset_options.py -q` → `17 passed`
