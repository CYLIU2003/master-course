# 運用ガイド — ソルバー比較・結果確認・トラブルシューティング

> [!NOTE]
> このファイルは **研究運用向けの操作ガイド** です。
> 初回セットアップ・通常の最適化実行手順は [README.md](README.md) を参照してください。

---

## 目次

1. [ソルバーモード比較（benchmark）](#1-ソルバーモード比較benchmark)
2. [Tkinter コンソールの操作](#2-tkinter-コンソールの操作)
3. [研究比較の最小フロー](#3-研究比較の最小フロー)
4. [トラブルシューティング](#4-トラブルシューティング)
5. [営業所別 Solcast キャッシュ運用](#5-営業所別-solcast-キャッシュ運用)

---

## 1. ソルバーモード比較（benchmark）

MILP / ALNS / GA / ABC の4モードを同一シナリオ・同一条件で順次実行し、
実行時間・目的値・欠便数を比較します。

### 1.1 実行手順

**前提：** BFF が起動していること（`python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000`）

```powershell
python scripts/benchmark_solver_modes.py `
  --base-url http://127.0.0.1:8000 `
  --scenario-id <SCENARIO_ID> `
  --modes mode_milp_only,mode_alns_only,ga,abc `
  --service-id WEEKDAY `
  --time-limit-seconds 300 `
  --mip-gap 0.01 `
  --alns-iterations 500
```

| パラメータ | 説明 | 既定値 |
|-----------|------|--------|
| `--base-url` | BFF の URL | `http://127.0.0.1:8000` |
| `--scenario-id` | 比較対象のシナリオ ID | （必須） |
| `--modes` | 実行するモードのリスト（カンマ区切り） | 全4モード |
| `--service-id` | 運行種別（`WEEKDAY` / `SAT` / `HOL`） | `WEEKDAY` |
| `--time-limit-seconds` | MILP の制限時間 | `300` |
| `--mip-gap` | MILP の許容ギャップ | `0.01`（1%） |
| `--alns-iterations` | ALNS/GA/ABC のイテレーション数 | `500` |

### 1.2 出力ファイル

| ファイル | 内容 |
|---------|------|
| `outputs/mode_compare_YYYYMMDD_HHMMSS.json` | 全モードの詳細結果（生データ） |
| `outputs/mode_compare_YYYYMMDD_HHMMSS.csv` | 比較用の集計表 |

### 1.3 CSV の主要列

| 列名 | 意味 |
|-----|------|
| `mode` | 実行したソルバーモード |
| `objective_value` | 最適化の目的値（総費用）。`None` の場合は `solver_result.objective_value` を参照 |
| `solve_time_seconds` | 求解にかかった時間 |
| `total_energy_cost` | 電気代 + 燃料費の合計 |
| `total_fuel_cost` | ICE 燃料費のみ |
| `total_demand_charge` | デマンド料金 |
| `unmet_trips` | 担当不能だった便数（0 が理想） |

> [!IMPORTANT]
> 公平な比較のため、複数モードの**同時実行は行いません**（スクリプトが順次実行します）。
> BFF が単一ジョブ実行制御の場合も、順次実行なので 503 競合は発生しません。

---

## 2. Tkinter コンソールの操作

### 2.1 起動

```powershell
.\.venv\Scripts\Activate.ps1
python tools/scenario_backup_tk.py
```

### 2.2 結果の詳細確認

`Optimization結果` ボタンを押すと詳細ウィンドウが開きます。

| タブ | 内容 |
|-----|------|
| **Summary** | 総費用・欠便数・ソルバーステータスの概要 |
| **Details** | 車両ごとの運行スケジュール・充電スケジュール |
| **Raw JSON** | バックエンドが返す生のJSON（デバッグ用） |

> [!NOTE]
> `job completed` と表示されていても、**数理最適化が成功したとは限りません**。
> Summary の `solver_status` が `OPTIMAL` または `FEASIBLE` であることを確認してください。
> `INFEASIBLE` / `ERROR` の場合は最適化結果ファイルが生成されないことがあります。

### 2.3 シナリオ間の比較（Scenario Compare）

1. `Scenario Compare` を開く
2. Scenario A と Scenario B を選択
3. `Optimization比較` または `Simulation比較` を実行

比較表示される指標：

| 指標 | 意味 |
|-----|------|
| `status` | ソルバーの終了ステータス |
| `objective` | 目的値（総費用） |
| `solve_time` | 求解時間（秒） |
| `unmet_trips` | 未充足便数 |
| `total_energy_cost` | 電気代 + 燃料費 |
| `total_demand_charge` | デマンド料金 |
| `delta(B-A)` | B と A の差分（正 = B が大きい） |

---

## 3. 研究比較の最小フロー

同一シナリオで複数ソルバーを比較する場合の標準手順です。

```
Step 1: 条件の固定
  └─ 比較対象シナリオの Quick Setup を確認・保存
  └─ 車両台数・充電器台数・SOC設定を固定
  └─ Prepare を実行してから比較開始

Step 2: 一括実行
  └─ benchmark_solver_modes.py で4モードを順次実行

Step 3: 結果の整理
  └─ 生成された CSV を表計算ソフトで開く
  └─ 以下の3指標を中心に比較：
       ① solve_time_seconds（計算時間）
       ② objective_value（総費用）
       ③ unmet_trips（欠便数）

Step 4: 詳細確認（必要に応じて）
  └─ Tk の Scenario Compare でシナリオ間の差分を再確認
```

> [!TIP]
> 比較の公平性を確保するために、以下を揃えてください：
> - `time_limit_seconds`（MILP の制限時間）
> - `alns_iterations`（ALNS/GA/ABC のイテレーション数）
> - `service_id`（平日/土/休日）
> - 車両台数・充電器台数

---

## 4. トラブルシューティング

### `HTTP 500` が返る

| 原因 | 対処 |
|------|------|
| Prepare 済みの入力が破損 / 型エラー | `bff/services/run_preparation.py` の入力 JSON 化で非直列化型が混入していないか確認 |
| シナリオが存在しない | `GET /api/scenarios/{id}` でシナリオの存在を確認 |

### `HTTP 503`（他ジョブ実行中）

BFF は同時に1ジョブしか受け付けません。前のジョブが完了するまで待つか、
`benchmark_solver_modes.py` の順次実行を使ってください。

### `objective_value` が `None`

top-level の `objective_value` だけでなく、`solver_result.objective_value` も確認してください。
ALNS/GA/ABC は `solver_result` 配下に格納されることがあります。

### MILP が `INFEASIBLE`

> [!WARNING]
> INFEASIBLE は「制約を満たす解が存在しない」ことを意味します。

よくある原因：

| 原因 | 確認箇所 |
|------|---------|
| SOC 下限が高すぎる | `soc_min` / `initial_soc` のパラメータ確認 |
| 契約電力上限が低すぎる | `depotPowerLimitKw` のパラメータ確認 |
| 車両台数が便数に対して少なすぎる | 営業所の車両台数を確認し、Prepare を再実行 |
| `allowPartialService = false` かつ便数が多すぎる | `allowPartialService = true` に変更して試す |

### `No module named 'tokyubus_gtfs'`

```powershell
python catalog_update_app.py refresh gtfs-pipeline `
  --source-dir data/catalog-fast `
  --built-datasets tokyu_full
```

出力に `"pipeline_fallback": true` があれば、`normalized/*.jsonl` からの自動フォールバックで完了しています。
完了後、BFF を再起動してください。

### Gurobi ライセンスエラー

```powershell
python -c "import gurobipy as gp; m=gp.Model(); x=m.addVar(lb=0.0,name='x'); m.setObjective(x, gp.GRB.MINIMIZE); m.optimize(); print('gurobi_ok', gp.gurobi.version())"
```

`gurobi_ok` が出力されれば正常です。ライセンスエラーの場合は Gurobi のライセンスファイルを確認してください。

---

## 5. 営業所別 Solcast キャッシュ運用

「都度 API 取得」ではなく、`座標一覧 -> 一括取得 -> ローカルキャッシュ -> 日別 JSON` の流れで運用します。

### 5.1 営業所座標一覧を生成

```powershell
python scripts/build_pv_profiles.py export-coordinates `
  --depot-master tokyu_bus_depots_master_full.json `
  --output data/external/solcast_raw/depot_coordinates_tokyu_all.json
```

出力ファイルには `depot_id`, `lat`, `lon` が全営業所分入ります。

### 5.2 Solcast 一括取得（外部作業）

- 生成した座標一覧を使って Solcast Web Download（最大 20 地点/回）で CSV を取得
- 取得した CSV を `data/external/solcast_raw/` に保存
- ファイル名は `depot_id_*.csv` 形式を推奨（例: `meguro_2025_full_60min.csv`）

### 5.3 日別 JSON へ変換

```powershell
python scripts/build_pv_profiles.py build-daily `
  --coordinates data/external/solcast_raw/depot_coordinates_tokyu_all.json `
  --raw-dir data/external/solcast_raw `
  --output-dir data/derived/pv_profiles `
  --dates 2025-08-01,2025-08-02 `
  --slot-minutes 60 `
  --timezone +09:00 `
  --default-pv-capacity-kw 1.0 `
  --require-all-depots
```

生成物は `data/derived/pv_profiles/{depot_id}_{date}_60min.json` です。
JSON には以下が含まれます。

- `capacity_factor_by_slot`
- `pv_generation_kwh_by_slot`

`pv_generation_kwh_by_slot[t] = pv_capacity_kw * capacity_factor_by_slot[t] * Δt` で計算されます（$Δt = slot\_minutes / 60$）。

### 5.4 シナリオ投入

`simulation_config.depot_energy_assets` の営業所ごとエントリに、変換済み `pv_generation_kwh_by_slot` を設定して最適化へ投入してください。
