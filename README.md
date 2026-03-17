# master-course core

この core は、Tkinter と BFF だけで東急バス全体の最適化を再現実行するための最終パッケージです。

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
  - constant/
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

## 9. 完成判定チェック

- BFF起動と /api/app/context 応答
- Tkinterから Prepare 成功
- Tkinterから最適化Jobが完走
- core内に frontend/tests/tmp/cache/log が存在しない
- パラメータ保全マニフェストに挙げた契約が保持されている

## 10. 先生レビュー用: 最適化定式と実装対応（constant反映）

この章は constant/formulation.md を正本として、制約式 C1-C21 を core 実装へ対応付けた一覧です。
実装上の完全対応・部分対応・未対応を分けて明記します。

### 10.1 記号・実装変数 対応表

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
| $g_t$ | 系統買電量 | 記述のみ（実変数未生成） | src/optimization/milp/model_builder.py |
| $pv_t^{ch}$ | PV自家消費 | 記述のみ（実変数未生成） | src/optimization/milp/model_builder.py |
| $W^{on}, W^{off}$ | 需要電力ピーク | 実変数未生成 | 未実装 |
| $\\mathcal{A}$ | 可行接続アーク集合 | `problem.feasible_connections` 由来の `arc_pairs` | src/optimization/milp/model_builder.py |
| $e_k(j)$ | 便走行エネルギー | `trip.energy_kwh` | src/optimization/milp/solver_adapter.py |
| $P^{contract}$ | 契約電力上限 | 記述のみ（実制約未生成） | src/optimization/milp/model_builder.py |

### 10.2 制約式 C1-C21 と実装対応

| No. | 数式（constant/formulation.md） | 実装状況 | 実装場所 | 実装の式・変数 |
|---|---|---|---|---|
| C1 | $\\sum_k y_j^k = 1$（各便一意割当） | 部分対応 | src/optimization/milp/solver_adapter.py | `sum(y[(k,j)]) + unserved[j] == 1`（未充足許容つき） |
| C2 | 便ノード流量保存（入流=出流） | 対応 | src/optimization/milp/solver_adapter.py | `incoming + start_arc == y`, `outgoing + end_arc == y` |
| C3 | 各車両の出庫・入庫は高々1回 | 対応 | src/optimization/milp/solver_adapter.py | `sum(start_arc)<=1`, `sum(end_arc)<=1` |
| C4 | 可行アークのみ利用 | 対応 | src/optimization/milp/model_builder.py, src/optimization/milp/solver_adapter.py | `arc_pairs` を feasible_connections から生成し、そのみ `x` を作成 |
| C5 | 同時刻の重複運行禁止 | 部分対応 | src/optimization/milp/model_builder.py, src/optimization/milp/solver_adapter.py | 時間可行アークと単一便鎖制約で間接抑止（重複ペア明示制約は未実装） |
| C6 | SOC遷移（デポ滞在中の充電） | 部分対応 | src/optimization/milp/solver_adapter.py | `s[t+1]=s[t]+0.95*c[t]*Δt-...` で時系列遷移を実装 |
| C7 | SOC遷移（便走行消費） | 部分対応 | src/optimization/milp/solver_adapter.py | `-trip_energy_expr`（`trip.energy_kwh * y`）を遷移式に加算 |
| C8 | SOC遷移（deadhead消費） | 未対応 | 未実装 | deadheadエネルギー項 `e_k^{dh}(i,j)` をSOC式に未投入 |
| C9 | SOC上下限 | 対応 | src/optimization/milp/solver_adapter.py | `s_var` の `lb=soc_min`, `ub=cap` |
| C10 | 出庫時SOC満充電 | 部分対応 | src/optimization/milp/solver_adapter.py | `s[first_slot] == initial_kwh`（満充電固定ではなく初期SOCパラメータ） |
| C11 | 帰庫後SOC下限 | 未対応 | 未実装 | 最終時刻SOC制約（terminal SOC）未追加 |
| C12 | 走行中充電禁止 | 未対応 | 未実装 | 走行中に `c_var=0` とする排他制約は未追加 |
| C13 | 充電電力上限 | 部分対応 | src/optimization/milp/solver_adapter.py | `c_var` の `ub=charge_max_kw`（ON/OFF二値 `xi` なし） |
| C14 | 同時充電台数/容量上限 | 部分対応 | src/optimization/milp/solver_adapter.py | `sum_k c[k,t] <= total_kw`（台数ではなく総kW容量） |
| C15 | 電力バランス $g_t+pv_t^{ch}=\\sum_k c_{k,t}Δt$ | 未対応 | 未実装（設計のみ） | model_builderに記述変数はあるが solver_adapter 側に制約未生成 |
| C16 | PV上限 $pv_t^{ch} \\le PV_tΔt$ | 未対応（実行系） | src/optimization/milp/model_builder.py | 記述モデルには `pv_limit` があるが実行ソルバへ未反映 |
| C17 | 非逆潮流 $g_t \\ge 0$ | 未対応 | 未実装 | `g_t` 相当の実変数未生成 |
| C18 | 契約電力上限 $g_t/Δt \\le P^{contract}$ | 未対応（実行系） | src/optimization/milp/model_builder.py | `depot_import_limit` は記述のみ、実行ソルバ未反映 |
| C19 | 期間平均需要電力定義 | 未対応 | 未実装 | `P_ζ^{avg}` 変数・制約なし |
| C20 | オンピーク最大需要 | 未対応 | 未実装 | `W^{on}` 変数・制約なし |
| C21 | オフピーク最大需要 | 未対応 | 未実装 | `W^{off}` 変数・制約なし |

### 10.3 目的関数（参考）

constant/formulation.md の O1-O4 に対し、現行実装の目的は以下です。

$$
\\min \sum_{k,j} (energy_kwh_j \cdot avgPrice) y_j^k
+ \sum_k fixedUseCost_k z_k
+ \sum_j penalty_{unserved} u_j
$$

実装場所: src/optimization/milp/solver_adapter.py

- O1（ICE燃料費）: 未実装
- O2（TOU買電費）: 部分実装（`avg_price` による近似）
- O3（デマンド料金）: 未実装
- O4（車両固定費）: 実装

### 10.4 実装上の重要補足

- 可行接続アークは dispatch 由来の `feasible_connections` を厳守する。
- 便未充足は `u[j]` で許容されるため、理論式 C1 の厳密等式は「罰則付き緩和」として実装されている。
- solver_status が ERROR/INFEASIBLE の場合、最適化結果ファイルが生成されないことがある。job completed はジョブ管理完了を意味し、数理最適化成功とは同義ではない。
