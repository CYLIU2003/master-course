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

この章は docs/constant/formulation.md を正本として、制約式 C1-C21 を core 実装へ対応付けた一覧です。
実装上の完全対応・部分対応・未対応を分けて明記します。
GA/ABC は独立モードとして起動し、評価器は ALNS と同一の `src/optimization/common/evaluator.py` を共有します。

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
| $g_t$ | 系統買電量 | `g_var[slot_idx]` | src/optimization/milp/solver_adapter.py |
| $pv_t^{ch}$ | PV自家消費 | `pv_ch_var[slot_idx]` | src/optimization/milp/solver_adapter.py |
| $W^{on}, W^{off}$ | 需要電力ピーク | `w_on_var`, `w_off_var` | src/optimization/milp/solver_adapter.py |
| $\\mathcal{A}$ | 可行接続アーク集合 | `problem.feasible_connections` 由来の `arc_pairs` | src/optimization/milp/model_builder.py |
| $e_k(j)$ | 便走行エネルギー | `trip.energy_kwh` | src/optimization/milp/solver_adapter.py |
| $P^{contract}$ | 契約電力上限 | `contract_limit_kw`（depot import limit由来） | src/optimization/milp/solver_adapter.py |

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
