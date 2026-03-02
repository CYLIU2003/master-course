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
