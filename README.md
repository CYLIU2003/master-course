# master-course core

この core は、Tkinter と BFF だけで東急バス全体の最適化を再現実行するための最終パッケージです。

## 実装ステータス（要点）

- MILP: C8/C11/C12/C15-C21 と O1/O2/O3 を `src/optimization/milp/solver_adapter.py` に実装済み
- ALNS/GA/ABC: 共通評価器 `src/optimization/common/evaluator.py` で O1/O2/O3 を同等評価
- モード: GA/ABC は独立選択可能（ALNS alias ではない）
- 文書: 旧 `constant/*.md` は `docs/constant/` へ統合済み

## 1. coreの目的

- 目的は「第三者が clone 後に最短で東急全体最適化を実行できること」です。
- 実行導線は Tkinter と FastAPI BFF のみです。
- 最適化に渡るパラメータは削除・簡略化しません。

## 2. coreに含まれるもの

- Tkinter
  - tools/scenario_backup_tk.py
  - tools/route_variant_labeler_tk.py
- Backend
  - bff/
- Core logic
  - src/dispatch/
  - src/optimization/
  - src/pipeline/
  - src/route_code_utils.py
- Config and constants
  - config/
  - docs/constant/
  - requirements.txt
- Dataset (Tokyu full optimization ready)
  - data/seed/tokyu/
  - data/built/tokyu_core/

## 3. coreから除外したもの

- React frontend
- tests
- 一時検証py、tmp系スクリプト
- __pycache__ / .pyc
- ログと一時成果物

## 4. 実行手順

### 4.1 環境構築

PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4.2 BFF起動

```powershell
python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000
```

### 4.3 Tkinter起動

別ターミナルで

```powershell
.\.venv\Scripts\Activate.ps1
python tools/scenario_backup_tk.py
```

### 4.4 タグ付与アプリ起動（Route Variant Labeler）

Route family / variant の手動タグ付与を行う場合は、別ターミナルで以下を実行します。

```powershell
\.venv\Scripts\Activate.ps1
python tools/route_variant_labeler_tk.py
```

最小操作手順:

1. 対象 Scenario を選択
2. Route family / variant を選択
3. 必要なタグ（variant type / canonical direction など）を編集
4. 保存して `tools/scenario_backup_tk.py` 側で `ラベルをシナリオへ反映` を実行

メモ:

- タグ付与は路線分類の運用補助であり、dispatch/optimization の物理可行性判定そのものを置き換えるものではありません。
- 反映後は Quick Setup を再読込して表示内容を確認してください。

## 5. 東急全体最適化の推奨フロー

1. シナリオ作成
2. Quick Setup 読込
3. 営業所と路線を選択
4. パラメータを設定して Quick Setup 保存
5. 入力データ作成 (Prepare)
6. 最適化実行
7. Job completed と Optimization結果を確認

## 6. 削除してはいけないパラメータ

最適化計算に直接関与するため、以下は core で必ず保持します。

- Solver and objective
  - solverMode, mode
  - objectiveMode
  - timeLimitSeconds, time_limit_seconds
  - mipGap, mip_gap
  - alnsIterations, alns_iterations
  - randomSeed
- Scope
  - selectedDepotIds, selectedRouteIds
  - dayType, service_id, service_date
  - includeShortTurn, includeDepotMoves, includeDeadhead
  - allowIntraDepotRouteSwap, allowInterDepotSwap
- Simulation and penalties
  - allowPartialService, unservedPenalty
- Tariff and emissions
  - gridFlatPricePerKwh, gridSellPricePerKwh
  - demandChargeCostPerKw
  - dieselPricePerL
  - gridCo2KgPerKwh
  - co2PricePerKg
  - depotPowerLimitKw
  - tou_pricing
- Vehicle and template
  - type, modelCode, modelName
  - capacityPassengers
  - batteryKwh, fuelTankL
  - energyConsumption, fuelEfficiencyKmPerL
  - co2EmissionGPerKm, co2EmissionKgPerL
  - curbWeightKg, grossVehicleWeightKg
  - engineDisplacementL, maxTorqueNm, maxPowerKw
  - chargePowerKw, minSoc, maxSoc
  - acquisitionCost, enabled

詳細な保全定義は docs/core_parameter_preservation_manifest.md を参照してください。

## 7. 非Tkフロント機能の移植メモ

非Tkフロントで実現済み機能を、今後 Tkinter に移植するための棚卸しを保存しています。

- docs/tkinter_feature_parity_backlog.md

このファイルを移植バックログの正本として扱います。

## 8. 既知の実行注意

- Windowsでは最適化実行器の既定が thread です。
- 必要に応じて環境変数 BFF_OPT_EXECUTOR で process へ切替できます。
- ポート衝突時は 8000 以外のポートで起動し、Tkinter側の接続先を合わせてください。
- `mode_milp_only` で `ERROR: Name too long (maximum name length is 255 characters)` が出る場合は、MILP変数名長が原因です。
  2026-03-17時点で `src/optimization/milp/solver_adapter.py` は長い可読名を使わず自動命名に変更済みです。
- `POST /simulation/prepare` / `POST /run-optimization` が 503 の場合:
  - 多くは `BUILT_DATASET_REQUIRED`（`data/built/tokyu_core` 未準備）です。
  - `GET /api/app/context` の `built_ready` と `missing_artifacts` を確認してください。
  - `data/catalog-fast` が既にある場合は、以下で built を再生成できます。

```powershell
python catalog_update_app.py refresh gtfs-pipeline --source-dir data/catalog-fast --built-datasets tokyu_core,tokyu_full
```

  - builtデータを配置/生成後、BFFを再起動してください。

### 8.1 Gurobi 利用確認（MILP）

他PCで MILP + Gurobi が有効かは、以下で確認できます。

```powershell
python -c "import gurobipy as gp; m=gp.Model(); x=m.addVar(lb=0.0,name='x'); m.setObjective(x, gp.GRB.MINIMIZE); m.optimize(); print('gurobi_ok', gp.gurobi.version())"
```

補足:

- 上記で import / optimize が通れば、Python側の Gurobi は利用可能です。
- ライセンス未設定の場合は optimize 時にライセンスエラーになります。

## 9. 完成判定チェック

- BFF起動と /api/app/context 応答
- Tkinterから Prepare 成功
- Tkinterから最適化Jobが完走
- core内に frontend/tests/tmp/cache/log が存在しない
- パラメータ保全マニフェストに挙げた契約が保持されている

## 10. 先生レビュー用: 最適化定式と実装対応（constant反映）

この章は docs/constant/formulation.md を正本として、制約式 C1-C21 を core 実装へ対応付けた一覧です。
実装上の完全対応・部分対応・未対応を分けて明記します。
GA/ABC は独立モードとして起動し、評価器は ALNS と同一の `src/optimization/common/evaluator.py` を共有します。

### 10.1 記号・実装変数 対応表（制約式で使う主変数）

| 数式記号 | 意味 | 実装変数（主） | 実装場所 |
|---|---|---|---|
| $x_{ij}^k$ | 車両 $k$ が便 $i$ の次に便 $j$ を担当 | `x[(vehicle_id, from_trip_id, to_trip_id)]` | src/optimization/milp/solver_adapter.py |
| $y_j^k$（被覆用） | 車両 $k$ が便 $j$ を担当 | `y[(vehicle_id, trip_id)]` | src/optimization/milp/solver_adapter.py |
| $u_j$ | 便 $j$ 未充足フラグ | `unserved[trip_id]` | src/optimization/milp/solver_adapter.py |
| $z_k$ | 車両 $k$ 使用フラグ | `used_vehicle[vehicle_id]` | src/optimization/milp/solver_adapter.py |
| $start_j^k$ | 便鎖の開始フラグ | `start_arc[(vehicle_id, trip_id)]` | src/optimization/milp/solver_adapter.py |
| $end_j^k$ | 便鎖の終端フラグ | `end_arc[(vehicle_id, trip_id)]` | src/optimization/milp/solver_adapter.py |
| $c_{k,t}$ | 充電電力 | `c_var[(vehicle_id, slot_idx)]` | src/optimization/milp/solver_adapter.py |
| $d_{k,t}$ | 放電電力 | `d_var[(vehicle_id, slot_idx)]` | src/optimization/milp/solver_adapter.py |
| $s_{k,t}$ | SOC（kWh） | `s_var[(vehicle_id, slot_idx)]` | src/optimization/milp/solver_adapter.py |
| $g_t$ | 系統買電量 | `g_var[slot_idx]` | src/optimization/milp/solver_adapter.py |
| $pv_t^{ch}$ | PV自家消費 | `pv_ch_var[slot_idx]` | src/optimization/milp/solver_adapter.py |
| $\bar{p}_t$ | スロット平均需要電力 | `p_avg_var[slot_idx]` | src/optimization/milp/solver_adapter.py |
| $W^{on}, W^{off}$ | 需要電力ピーク | `w_on_var`, `w_off_var` | src/optimization/milp/solver_adapter.py |
| $\\mathcal{A}$ | 可行接続アーク集合 | `problem.feasible_connections` 由来の `arc_pairs` | src/optimization/milp/model_builder.py |
| $e_k(j)$ | 便走行エネルギー | `trip.energy_kwh` | src/optimization/milp/solver_adapter.py |
| $P^{contract}$ | 契約電力上限 | `contract_limit_kw`（depot import limit由来） | src/optimization/milp/solver_adapter.py |

### 10.1.1 実装変数一覧（制約式・目的関数・後処理で使用）

以下は `src/optimization/milp/solver_adapter.py` の `GurobiMILPAdapter.solve()` 内で使用される変数を、用途別に網羅した一覧です。

| 区分 | 変数名 | 用途 |
|---|---|---|
| モデル/前処理 | `model` | Gurobiモデル本体 |
| モデル/前処理 | `builder` | MILP用の接続候補生成ヘルパ |
| モデル/前処理 | `trip_by_id` | 便ID→便オブジェクト参照 |
| モデル/前処理 | `dispatch_trip_by_id` | dispatch trip参照 |
| モデル/前処理 | `assignment_pairs` | `(vehicle_id, trip_id)` 候補集合 |
| モデル/前処理 | `arc_pairs` | `(vehicle_id, from_trip_id, to_trip_id)` 候補集合 |
| 決定変数 | `y` | 便被覆（二値） |
| 決定変数 | `x` | 便間接続アーク（二値） |
| 決定変数 | `start_arc` | 便鎖開始フラグ（二値） |
| 決定変数 | `end_arc` | 便鎖終端フラグ（二値） |
| 決定変数 | `unserved` | 未充足便フラグ（二値） |
| 決定変数 | `used_vehicle` | 車両使用フラグ（二値） |
| 充放電/SOC変数 | `c_var` | 充電電力（連続） |
| 充放電/SOC変数 | `d_var` | 放電電力（連続） |
| 充放電/SOC変数 | `s_var` | SOC（連続） |
| 系統/PV/需要変数 | `g_var` | 系統買電量（連続） |
| 系統/PV/需要変数 | `pv_ch_var` | PV自己消費量（連続） |
| 系統/PV/需要変数 | `p_avg_var` | 平均需要電力（連続） |
| 系統/PV/需要変数 | `w_on_var` | オンピーク最大需要（連続） |
| 系統/PV/需要変数 | `w_off_var` | オフピーク最大需要（連続） |
| 集合/インデックス | `bev_ids` | BEV/PHEV/FCEV車両ID集合 |
| 集合/インデックス | `slot_indices` | 時間スロットID集合 |
| 集合/インデックス | `outgoing_by_node` | ノード別出アーク辞書 |
| 集合/インデックス | `incoming_by_node` | ノード別入アーク辞書 |
| 制約中間式 | `assign_terms` | C1被覆制約の左辺和 |
| 制約中間式 | `incoming`, `outgoing` | C2流量保存の入出流量 |
| 制約中間式 | `vehicle_terms_start`, `vehicle_terms_end` | C3始終点回数制約用リスト |
| 制約中間式 | `trip_energy_expr` | C7便走行消費エネルギー式 |
| 制約中間式 | `deadhead_energy_expr` | C8 deadhead消費エネルギー式 |
| 制約中間式 | `running_expr` | C12走行中フラグ相当式 |
| 制約中間式 | `charge_kwh_expr` | C15充電電力量合計式 |
| 制約パラメータ | `timestep_h` | 時間刻み（hour） |
| 制約パラメータ | `cap` | 車両バッテリー容量 |
| 制約パラメータ | `soc_min` | SOC下限 |
| 制約パラメータ | `charge_max_kw` | 車両充電上限 |
| 制約パラメータ | `discharge_max_kw` | 車両放電上限 |
| 制約パラメータ | `initial_kwh` | 初期SOC（kWh換算） |
| 制約パラメータ | `total_kw` | 全充電器の総kW上限 |
| 制約パラメータ | `pv_by_slot` | スロット別PV上限辞書 |
| 制約パラメータ | `contract_limit_kw` | 契約電力上限 |
| 制約パラメータ | `price_values`, `median_price` | C20/C21のピーク帯判定用 |
| 目的関数構成 | `objective` | 目的関数線形式 |
| 目的関数構成 | `price_by_slot` | TOU単価辞書 |
| 目的関数構成 | `diesel_price` | 燃料単価 |
| 目的関数構成 | `fuel_l` | 便ごとの燃料消費量 |
| 目的関数構成 | `fuel_rate` | deadhead燃費係数 |
| 目的関数構成 | `deadhead_min`, `deadhead_km` | deadhead時間/距離 |
| 目的関数構成 | `unserved_penalty_weight` | 未充足ペナルティ係数 |
| 求解結果/後処理 | `status_map`, `solver_status` | Gurobi終了ステータス正規化 |
| 求解結果/後処理 | `empty` | 解なし時の空割当プラン |
| 求解結果/後処理 | `duties`, `legs` | 出力行路構築 |
| 求解結果/後処理 | `served_trip_ids`, `served_set`, `unserved_trip_ids` | 供給/未供給便集計 |
| 求解結果/後処理 | `plan` | 最終 `AssignmentPlan` |

### 10.2 制約式 C1-C21 と実装対応

| No. | 数式（docs/constant/formulation.md） | 実装状況 | 実装場所 | 実装の式・変数 |
|---|---|---|---|---|
| C1 | $\\sum_k y_j^k = 1$（各便一意割当） | 部分対応 | src/optimization/milp/solver_adapter.py | `sum(y[(k,j)]) + unserved[j] == 1`（未充足許容つき） |
| C2 | 便ノード流量保存（入流=出流） | 対応 | src/optimization/milp/solver_adapter.py | `incoming + start_arc == y`, `outgoing + end_arc == y` |
| C3 | 各車両の出庫・入庫は高々1回 | 対応 | src/optimization/milp/solver_adapter.py | `sum(start_arc)<=1`, `sum(end_arc)<=1` |
| C4 | 可行アークのみ利用 | 対応 | src/optimization/milp/model_builder.py, src/optimization/milp/solver_adapter.py | `arc_pairs` を feasible_connections から生成し、そのみ `x` を作成 |
| C5 | 同時刻の重複運行禁止 | 部分対応 | src/optimization/milp/model_builder.py, src/optimization/milp/solver_adapter.py | 時間可行アークと単一便鎖制約で間接抑止（重複ペア明示制約は未実装） |
| C6 | SOC遷移（デポ滞在中の充電） | 部分対応 | src/optimization/milp/solver_adapter.py | `s[t+1]=s[t]+0.95*c[t]*Δt-...` で時系列遷移を実装 |
| C7 | SOC遷移（便走行消費） | 部分対応 | src/optimization/milp/solver_adapter.py | `-trip_energy_expr`（`trip.energy_kwh * y`）を遷移式に加算 |
| C8 | SOC遷移（deadhead消費） | 対応（近似） | src/optimization/milp/solver_adapter.py | `deadhead_energy_expr` を SOC 遷移に投入 |
| C9 | SOC上下限 | 対応 | src/optimization/milp/solver_adapter.py | `s_var` の `lb=soc_min`, `ub=cap` |
| C10 | 出庫時SOC満充電 | 部分対応 | src/optimization/milp/solver_adapter.py | `s[first_slot] == initial_kwh`（満充電固定ではなく初期SOCパラメータ） |
| C11 | 帰庫後SOC下限 | 対応 | src/optimization/milp/solver_adapter.py | `s[last_slot] >= soc_min * used_vehicle` |
| C12 | 走行中充電禁止 | 対応 | src/optimization/milp/solver_adapter.py | `c[k,t] <= chargeMax * (1 - running_expr)` |
| C13 | 充電電力上限 | 部分対応 | src/optimization/milp/solver_adapter.py | `c_var` の `ub=charge_max_kw`（ON/OFF二値 `xi` なし） |
| C14 | 同時充電台数/容量上限 | 部分対応 | src/optimization/milp/solver_adapter.py | `sum_k c[k,t] <= total_kw`（台数ではなく総kW容量） |
| C15 | 電力バランス $g_t+pv_t^{ch}=\sum_k c_{k,t}Δt$ | 対応 | src/optimization/milp/solver_adapter.py | `g_var + pv_ch_var == sum(c)*Δt` |
| C16 | PV上限 $pv_t^{ch} \le PV_tΔt$ | 対応 | src/optimization/milp/solver_adapter.py | `pv_ch_var <= pv_available * Δt` |
| C17 | 非逆潮流 $g_t \ge 0$ | 対応 | src/optimization/milp/solver_adapter.py | `g_var` を `lb=0` で生成 |
| C18 | 契約電力上限 $g_t/Δt \le P^{contract}$ | 対応 | src/optimization/milp/solver_adapter.py | `g_var <= contract_limit_kw * Δt` |
| C19 | 期間平均需要電力定義 | 対応 | src/optimization/milp/solver_adapter.py | `p_avg_var[t] = g_var[t] / Δt` |
| C20 | オンピーク最大需要 | 対応（価格帯近似） | src/optimization/milp/solver_adapter.py | `w_on >= p_avg_var[t]`（高単価帯） |
| C21 | オフピーク最大需要 | 対応（価格帯近似） | src/optimization/milp/solver_adapter.py | `w_off >= p_avg_var[t]`（低単価帯） |

### 10.3 目的関数（参考）

docs/constant/formulation.md の O1-O4 に対し、現行実装の目的は以下です。

$$
\\min \sum_t price_t \cdot g_t
+ \sum_{k,j \in ICE} dieselPrice \cdot fuel_{k,j} \cdot y_j^k
+ \sum_{(i,j),k \in ICE} dieselPrice \cdot fuel^{dh}_{k,i,j} \cdot x_{i,j}^k
+ demandOn \cdot W^{on} + demandOff \cdot W^{off}
+ \sum_k fixedUseCost_k z_k
+ \sum_j penalty_{unserved} u_j
$$

実装場所: src/optimization/milp/solver_adapter.py

- O1（ICE燃料費）: 実装（便燃料 + deadhead燃料）
- O2（TOU買電費）: 実装（スロット別 `g_t` 課金）
- O3（デマンド料金）: 実装（`W^{on}`, `W^{off}`）
- O4（車両固定費）: 実装

### 10.3.1 ALNS / GA / ABC の同等対応

- GA/ABC は `src/optimization/ga/engine.py`, `src/optimization/abc/engine.py` から独立モードで起動し、探索カーネルは ALNS を利用。
- 3モード共通で `src/optimization/common/evaluator.py` を使用し、以下を同一評価する。
  - O1: ICE燃料費（便 + deadhead）
  - O2: TOU買電費（充電スロット別、PV自己消費差引き）
  - O3: デマンド料金（オン/オフピーク最大需要）

### 10.3.2 ALNS / GA / ABC（evaluator.py）変数一覧

以下は `src/optimization/common/evaluator.py` の `CostEvaluator.evaluate()` と関連メソッドで使用する変数の一覧です。

| 区分 | 変数名 | 用途 |
|---|---|---|
| 入力 | `problem` | 正規化済み問題（シナリオ/車両/便/価格帯） |
| 入力 | `plan` | ALNS/GA/ABC が生成した割当・充放電計画 |
| 固定パラメータ | `prep_time_min` | 乗務員準備時間（分） |
| 固定パラメータ | `wage_regular_jpy_per_h` | 通常時給 |
| 固定パラメータ | `regular_hours_per_day` | 所定労働時間 |
| 固定パラメータ | `overtime_factor` | 残業割増係数 |
| 重み | `weights` | 目的重み（vehicle/unserved/deviation等） |
| コスト集計 | `vehicle_cost` | 車両固定費累積 |
| コスト集計 | `driver_cost` | 乗務員費累積 |
| コスト集計 | `energy_cost` | 燃料費+買電費累積 |
| コスト集計 | `demand_cost` | デマンド費累積 |
| 参照辞書 | `vehicle_by_id` | `vehicle_id -> vehicle` |
| 参照辞書 | `vehicle_type_by_id` | `vehicle_type_id -> vehicle_type` |
| ループ変数 | `duty` | 行路単位の走査変数 |
| ループ変数 | `leg` | 行路内の便レッグ |
| 中間変数 | `v_type` | 車両タイプ情報 |
| 中間変数 | `fixed_use_cost` | 行路に対する固定車両費 |
| 中間変数 | `first_trip`, `last_trip` | 行路先頭/末尾便 |
| 中間変数 | `duty_duration_min` | 行路所要時間（分） |
| 中間変数 | `total_hours` | 準備時間込み拘束時間（h） |
| 中間変数 | `regular_hours`, `overtime_hours` | 通常/残業時間 |
| 充放電集約 | `slot_totals` | `slot_index -> net_kw` |
| 充放電集約 | `slot` | `plan.charging_slots` の要素 |
| 充放電集約 | `net_kw` | 各スロット純充電電力 |
| O3関連 | `demand_cost` | `_demand_charge_cost()` の戻り値 |
| スイッチ関連 | `baseline_map` | 基準計画の trip->vehicle_type |
| スイッチ関連 | `current_map` | 現計画の trip->vehicle_type |
| スイッチ関連 | `switch_count` | 車種切替件数 |
| スイッチ関連 | `switch_cost` | 切替ペナルティ費 |
| 劣化関連 | `slot_hours` | 1スロット時間（h） |
| 劣化関連 | `degradation_cycles` | 劣化サイクル推定量 |
| 劣化関連 | `vehicle` | 充放電スロット対応車両 |
| 劣化関連 | `capacity_kwh` | 車両電池容量 |
| 劣化関連 | `charged_kwh` | スロット内充電量 |
| 劣化関連 | `degradation_cost` | 劣化費 |
| 未充足関連 | `unserved_penalty` | 未配車ペナルティ |
| 乖離関連 | `baseline_ids` | 基準計画の配車便集合 |
| 乖離関連 | `deviation_count` | 対基準差分便数 |
| 乖離関連 | `deviation_cost` | 乖離ペナルティ |
| 合算 | `total_cost` | 最終評価値 |
| 戻り値 | `CostBreakdown(...)` | 各コスト内訳を返すデータクラス |

補助メソッド側の主要変数:

| メソッド | 変数名 | 用途 |
|---|---|---|
| `_trip_fuel_cost` | `trip`, `fuel_rate`, `fuel_l` | 便ごとの燃料費算出 |
| `_deadhead_fuel_cost` | `deadhead_from_prev_min`, `distance_km`, `fuel_l` | deadhead燃料費算出 |
| `_charging_energy_cost` | `timestep_h`, `pv_kw_map`, `slot_idx`, `buy_price`, `charge_kwh`, `pv_kwh`, `grid_kwh`, `total_cost` | TOU買電費算出 |
| `_demand_charge_cost` | `price_slots`, `sorted_prices`, `threshold`, `on_peak`, `off_peak`, `w_on`, `w_off` | オン/オフピークデマンド費算出 |
| `_slot_buy_price` | `price_map`, `selected_price`, `nearest_slot` | スロット単価補間 |
| `_trip_vehicle_type_map` | `mapping`, `trip_id` | 便→車種写像作成 |

### 10.4 実装上の重要補足

- 可行接続アークは dispatch 由来の `feasible_connections` を厳守する。
- 便未充足は `u[j]` で許容されるため、理論式 C1 の厳密等式は「罰則付き緩和」として実装されている。
- solver_status が ERROR/INFEASIBLE の場合、最適化結果ファイルが生成されないことがある。job completed はジョブ管理完了を意味し、数理最適化成功とは同義ではない。

## 11. システム全体の使い方（運用手順）

### 11.1 初回セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 11.2 起動

```powershell
# Terminal 1: BFF
python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Tkinter
.\.venv\Scripts\Activate.ps1
python tools/scenario_backup_tk.py
```

### 11.3 標準オペレーション

1. Tk で接続確認（Connect）
2. Scenario を作成または複製
3. Quick Setup 読込・編集・保存
4. Route label が必要なら `tools/route_variant_labeler_tk.py` で編集
5. Vehicle/Template を整備
6. `入力データ作成 (Prepare)` を実行
7. `最適化実行` を実行
8. `ジョブ監視` で completed 確認
9. `Optimization結果` を確認

### 11.5 Tk UI/UX 改善（2026-03-18）

- シナリオ作成の `datasetId` は `/api/app/datasets` の候補から選択する方式に変更。
  - 無効ID時は候補一覧を含むエラー表示で原因を明示。
  - 既定値は `tokyu_full`（東急バス全体）を優先。
- 路線一覧は `quick-setup` の `routeLimit` 依存表示ではなく、`/api/scenarios/{id}/routes` を優先して取得。
  - タグ付与アプリとの件数乖離を抑制。
- 対象営業所・路線の選択は、営業所折りたたみ + 実チェックボックス方式へ変更。
  - 営業所配下の路線は1文字インデント表示。
- メイン画面に `営業所別車両管理` ボタンを追加。
  - 専用画面で営業所選択と充電器設定（普通/急速の台数・出力）編集が可能。
- 右側の車両管理タブにある営業所選択は、入力欄ではなくプルダウン選択に変更。
- スコープ設定の運行種別 (`day_type`) はプルダウン選択に変更。
- ソルバー設定は `詳細設定画面を開く` ボタンから別画面で編集。
  - プルダウンでモード選択し、モードに応じて項目を出し分け。
  - 旧 Advanced 設定も同じ別画面へ集約し、メイン画面の混在を解消。
- 車両管理/テンプレート管理で新規追加は専用ダイアログ（別画面）に変更。
  - 車両追加時は営業所・台数・詳細パラメータを別画面で指定。
  - テンプレート追加時は詳細パラメータに加え、作成後に営業所へ何台追加するかを同画面で指定可能。
- 車両編集・テンプレート編集は日本語表示へ統一し、EV/ICE で該当パラメータのみ表示。
- シナリオ選択時に「シナリオ選択完了」メッセージを表示。
- 画面上部のシナリオ行に `シナリオ設定を保存` ボタンを追加（Quick Setup保存を即実行）。
- `入力データ作成 (Prepare)` / `Prepared実行` / `最適化実行` の開始時にメッセージ表示を追加。
- `最適化実行` は専用モニター画面を開く方式に変更。
  - 進捗%バー、ステータス表示、PowerShell風ログ表示で実行状況を確認可能。
- `シミュレーション実行(legacy)` ボタンは通常運用では非表示化。
- 最適化設定に `終了まで待つ（大規模向け）` を追加。
  - ON時は実質無制限に近い長時間タイムリミットで実行。
- 最適化設定に `実行前にdispatchを再構築する（重い）` を追加。
  - 既存dispatchを使う軽量実行を選べるようにし、開始時timeoutを回避しやすくした。
- 最適化開始API呼び出しのクライアント側タイムアウトを延長し、
  大規模シナリオでも開始要求が落ちにくいよう安定化。
- Windows環境で `シナリオ設定を保存` 時にディレクトリrenameが失敗する場合に備え、
  非原子的フォールバック保存を追加（WinError 5/32 の500を回避）。

### 11.4 主な API 導線（Tk が呼び出す先）

- `/api/app/context`
- `/api/scenarios/*`（scenario CRUD）
- `/api/scenarios/{id}/quick-setup`
- `/api/scenarios/{id}/simulation/prepare`
- `/api/scenarios/{id}/run-optimization`
- `/api/jobs/{job_id}`

## 12. constant 参照と実装トレーサビリティ

### 12.1 参照した constant 文書

| constant ファイル | 採用目的 | 反映先 |
|---|---|---|
| `docs/constant/formulation.md` | C1-C21, O1-O4 の定式正本 | 本README 10章、`src/optimization/milp/*` |
| `docs/constant/AGENTS_ev_route_cost.md` | EV/ICE 混成、運行+コスト統合方針 | `bff/routers/optimization.py`, `tools/scenario_backup_tk.py` |
| `docs/constant/AGENTS.md` | timetable-first と feasibility の不変条件 | `src/dispatch/*`, `bff/routers/graph.py` |
| `docs/constant/ebus_prototype_model_gurobi.md` | Gurobi 実装指針 | `src/optimization/milp/solver_adapter.py` |
| `docs/constant/ebus_constraints_table.md` | 制約棚卸し | 本README 10章の実装状況表 |
| `docs/constant/README.md` | 文書の正本候補整理 | レビュー時の参照順序ガイド |

### 12.2 どのようなアプリを構築したか

- UI: Tkinter
  - `tools/scenario_backup_tk.py`（シナリオ/Quick Setup/Prepare/Optimization）
  - `tools/route_variant_labeler_tk.py`（路線バリアント手動ラベル）
- API/BFF: FastAPI
  - `bff/routers/graph.py`（dispatch artifact 生成）
  - `bff/routers/optimization.py`（最適化ジョブ）
  - `bff/services/run_preparation.py`（prepare入力生成）
- Core: dispatch + optimization
  - `src/dispatch/feasibility.py`
  - `src/dispatch/graph_builder.py`
  - `src/optimization/milp/model_builder.py`
  - `src/optimization/milp/solver_adapter.py`

### 12.3 バス運行ルール（実装されている数理的ルール）

dispatch の接続可否は次を満たす場合のみ許可する。

$$
arrival(i) + turnaround(dest_i) + deadhead(dest_i, origin_j) \le departure(j)
$$

実装位置:
- `src/dispatch/feasibility.py`（可否判定）
- `src/dispatch/graph_builder.py`（可行アーク生成）
- `src/dispatch/dispatcher.py`（可行アーク上の duty 構築）

### 12.4 教員レビュー向け詳細ガイド

以下に、constant 参照元、アプリ構成、パラメータ、制約、実装差分を詳細にまとめた。

- `docs/professor_system_model_guide.md`

## 13. 実測監査（timetable_rows / unserved / departure-arrival一致率）

第三者が追試できるよう、以下の監査スクリプトと成果物を追加しました。

- スクリプト: `scripts/audit_timetable_alignment.py`
- 提出版レポート: `docs/reproduction/timetable_alignment_audit_20260318.md`
- 監査成果物（WEEKDAY）: `outputs/audit/bbe1e1bd/timetable_alignment_audit.{json,csv,md}`
- 監査成果物（SAT比較）: `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.{json,csv,md}`

### 13.1 監査対象KPI

- `timetable_rows_count`
- `unserved_trip_count`
- `departure_arrival_match_rate`

加えて、監査の妥当性確認のために以下を併記します。

- `checked_coverage_rate`（一致率算出に使えた便の割合）
- `prepared_day_tag`, `result_day_tag`, `day_tag_match`（曜日タグ整合性）

### 13.2 再現コマンド

```powershell
python scripts/audit_timetable_alignment.py `
  --scenario-id bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f `
  --prepared-input-path app/scenarios/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared_inputs/prepared-7822b5b6dd60630d.json `
  --optimization-result-path outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/WEEKDAY/optimization_result.json `
  --out-dir outputs/audit/bbe1e1bd
```

`day_tag_match=false` の場合は、prepared input と最適化結果のサービス日種別が異なるため、
`departure_arrival_match_rate` を品質判定に用いてはいけません。

