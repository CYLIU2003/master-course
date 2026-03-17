# readme_operation

## 目的
- ソルバー比較（MILP/ALNS/GA/ABC）の実行時間と目的値を同一シナリオ条件で比較する。
- Tkバックアップ運用ツールで、結果詳細表示とシナリオ比較を実行できるようにする。

## 1) 比較実行手順（APIベース）
1. BFFを起動する。
2. 比較対象シナリオIDを確認する。
3. 以下を実行する。

```powershell
python scripts/benchmark_solver_modes.py `
  --base-url http://127.0.0.1:8771 `
  --scenario-id <SCENARIO_ID> `
  --modes mode_milp_only,mode_alns_only,ga,abc `
  --service-id WEEKDAY `
  --time-limit-seconds 300 `
  --mip-gap 0.01 `
  --alns-iterations 500
```

出力:
- JSON: `outputs/mode_compare_YYYYMMDD_HHMMSS.json`
- CSV: `outputs/mode_compare_YYYYMMDD_HHMMSS.csv`

CSV主要列:
- `mode`
- `objective_value`
- `solve_time_seconds`
- `total_energy_cost`
- `total_fuel_cost`
- `total_demand_charge`
- `unmet_trips`

注意:
- 比較スクリプトは `solver_result.objective_value` / `solver_result.solve_time_seconds` を優先参照する。
- BFFが単一ジョブ実行制御の場合でも、モードを順次実行するため503競合を回避できる。
- 性能比較の公平性確保のため、複数ソルバーの同時実行は行わない（順次実行のみ）。

## 2) Tkバックアップコンソール操作
起動:

```powershell
python tools/scenario_backup_tk.py
```

追加された主な操作:
- `Simulation結果` / `Optimization結果`
  - 詳細ウィンドウを開き、Summary/Details/Raw JSONを確認。
- `Scenario Compare`
  - Scenario A/B を選択して `Optimization比較` または `Simulation比較` を実行。
  - 指標（status/objective/solve_time/unmet/cost系）を横比較し、`delta(B-A)` を表示。

## 3) 研究比較に使う最小フロー
1. 比較対象シナリオの quick-setup と車両条件を固定。
2. `benchmark_solver_modes.py` で4モードを順次実行。
3. CSVを表計算ソフトに読み込み、
   - `solve_time_seconds`
   - `objective_value`
   - `unmet_trips`
   を中心に比較。
4. 必要に応じてTk比較画面でシナリオ間の結果差分を再確認。

## トラブルシュート
- `HTTP 500` が出る場合:
  - `bff/services/run_preparation.py` の入力JSON化で非直列化型が混ざっていないか確認。
- `HTTP 503`（他ジョブ実行中）が出る場合:
  - 並列起動ではなく順次実行にする。
- objectiveが `None` の場合:
  - top-levelだけでなく `solver_result.objective_value` を参照する。
