# Professor Guide: System Architecture, Mathematical Model, and Traceability

## 1. この文書の目的

本ガイドは、以下を数理最適化の専門家向けに明示するための技術文書である。

- constant 内で参照した仕様文書と採用理由
- その仕様をどのアプリ構成（Tkinter + BFF + Core）に落としたか
- 現在実現されているパラメータ、運行ルール、制約
- 実装済み・部分実装・未実装の境界

## 2. 参照した constant 文書と役割

| 参照ファイル | 位置づけ | 本システムでの利用 |
|---|---|---|
| docs/constant/README.md | constant 文書群の索引 | 正本候補/参考資料/アーカイブ候補の整理に使用 |
| docs/constant/formulation.md | 混成フリート + PV の MILP 定式化（C1-C21, O1-O4） | 制約式・目的関数の正本として、実装対応表の基準に使用 |
| docs/constant/AGENTS_ev_route_cost.md | route-profile driven の運行・充電・コスト統合方針 | EV/ICE 混成、TOU、契約電力、運行整合の設計方針として採用 |
| docs/constant/AGENTS.md | 全体の設計不変条件（timetable-first, operator境界等） | dispatch feasibility のハード制約と境界条件の遵守に使用 |
| docs/constant/ebus_prototype_model_gurobi.md | 試作段階の Gurobi 実装指針 | 変数設計と MILP 実装の参考（現行では一部のみ採用） |
| docs/constant/ebus_constraints_table.md | 制約一覧の簡易表 | 実装済み/未実装の棚卸し確認に使用 |
| docs/constant/masters_thesis_simulation_spec_v3.md | route editable と推定拡張の設計論点 | 将来拡張（路線詳細層・推定層）としての設計方向確認 |

## 3. どのようなアプリを作ったか（構成）

### 3.1 システム構成

- UI層: Tkinter
  - tools/scenario_backup_tk.py
  - tools/route_variant_labeler_tk.py
- API/BFF層: FastAPI
  - bff/routers/*.py
- Core層:
  - src/dispatch/*（時刻表準拠配車）
  - src/optimization/*（MILP/ALNS/Hybrid）
  - src/pipeline/*（problem build と solve）

### 3.2 主要実行フロー

1. Tk でシナリオ作成・Quick Setup保存
2. BFF /simulation/prepare で canonical 入力を生成
3. BFF /run-optimization で最適化ジョブを起動
4. job polling で完了確認
5. /optimization 結果を確認

## 4. 実装済みパラメータ（レビュー観点）

### 4.1 主要パラメータ群

現行 core が保持する主要パラメータ群は以下。

- Solver and mode
  - mode, solverMode, objectiveMode
  - timeLimitSeconds, mipGap, alnsIterations, randomSeed
- Scope and service
  - selectedDepotIds, selectedRouteIds, dayType, service_id, service_date
  - includeShortTurn, includeDepotMoves, includeDeadhead
  - allowIntraDepotRouteSwap, allowInterDepotSwap
- Cost and tariff
  - gridFlatPricePerKwh, gridSellPricePerKwh, demandChargeCostPerKw
  - dieselPricePerL, gridCo2KgPerKwh, co2PricePerKg, depotPowerLimitKw, tou_pricing
- Vehicle/template
  - batteryKwh, fuelTankL, chargePowerKw, minSoc, maxSoc
  - energyConsumption, fuelEfficiencyKmPerL, co2EmissionGPerKm
  - maxTorqueNm, maxPowerKw, acquisitionCost, enabled

### 4.2 パラメータ保全文書

- docs/core_parameter_preservation_manifest.md

## 5. バス運行ルール（dispatch 側ハード制約）

時刻表優先（timetable-first）で、以下をハード制約として実装。

### 5.1 連続運行可否

便 i の次に便 j を同一車両で担当可能なのは次を満たすときのみ。

$$
arrival(i) + turnaround(dest_i) + deadhead(dest_i, origin_j) \le departure(j)
$$

加えて、停留所連続性（deadhead rule の存在）と車種適合を要求。

### 5.2 実装位置

- feasibility判定:
  - src/dispatch/feasibility.py
- feasible graph 構築:
  - src/dispatch/graph_builder.py
- duty 生成:
  - src/dispatch/dispatcher.py

## 6. 最適化モデル（MILP 実行系）

### 6.1 変数

| 数式記号 | 実装変数 | 説明 |
|---|---|---|
| $y_j^k$ | y[(vehicle_id, trip_id)] | 便担当 |
| $x_{ij}^k$ | x[(vehicle_id, from_trip_id, to_trip_id)] | 可行アーク選択 |
| $u_j$ | unserved[trip_id] | 未充足便フラグ |
| $z_k$ | used_vehicle[vehicle_id] | 車両使用フラグ |
| $c_{k,t}$ | c_var[(vehicle_id, slot_idx)] | 充電電力 |
| $d_{k,t}$ | d_var[(vehicle_id, slot_idx)] | 放電電力 |
| $s_{k,t}$ | s_var[(vehicle_id, slot_idx)] | SOC (kWh) |

### 6.2 制約対応（C1-C21）

詳細表は README.md の対応表を正本とし、本節では要点のみ示す。

- 実装済み/部分実装
  - C1, C2, C3, C4, C5(部分), C6, C7, C8(近似), C9, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20(価格帯近似), C21(価格帯近似)

### 6.3 目的関数

現行の実行系（solver_adapter）は以下を最小化。

$$
\min \sum_t price_t \cdot g_t
+ \sum_{k,j \in ICE} dieselPrice \cdot fuel_{k,j} \cdot y_j^k
+ \sum_{(i,j),k \in ICE} dieselPrice \cdot fuel^{dh}_{k,i,j} \cdot x_{i,j}^k
+ demandOn \cdot W^{on} + demandOff \cdot W^{off}
+ \sum_k fixedUseCost_k z_k
+ \sum_j penalty_{unserved} u_j
$$

- O1 ICE燃料費: 実装（便 + deadhead）
- O2 TOU買電費: 実装（スロット別）
- O3 デマンド料金: 実装（オン/オフピーク）
- O4 車両固定費: 実装

## 7. 制約・ルール・実装のトレーサビリティ

| 観点 | 仕様起点 | 実装ファイル |
|---|---|---|
| timetable-first dispatch | docs/constant/AGENTS.md | src/dispatch/feasibility.py, src/dispatch/graph_builder.py |
| EV/ICE混成運行とコスト | docs/constant/AGENTS_ev_route_cost.md | bff/routers/optimization.py, src/optimization/milp/solver_adapter.py |
| C1-C21 制約体系 | docs/constant/formulation.md | src/optimization/milp/model_builder.py, src/optimization/milp/solver_adapter.py |
| Gurobi実装方針 | docs/constant/ebus_prototype_model_gurobi.md | src/optimization/milp/solver_adapter.py |

## 8. システム全体の使い方（教員レビュー向け）

### 8.1 事前準備

1. Python venv 作成
2. requirements.txt インストール
3. BFF 起動
4. Tk 起動

### 8.2 最短操作

1. Tk で接続確認
2. シナリオ作成
3. Quick Setup（営業所・路線・日種）保存
4. Prepare 実行
5. Optimization 実行
6. Job completed と result を確認

### 8.3 確認ポイント

- Prepare が ready=true を返す
- Job が completed になる
- solver_status を確認（optimal/suboptimal/time_limit/infeasible/error）
- solver_status=ERROR の場合は optimization_result.json 未生成の可能性が高い

## 9. 今後の実装優先度（C1-C21 完全化）

1. C15-C18（電力収支・PV・契約電力）を solver_adapter に実装
2. C11/C12（終端SOC・走行中充電禁止）を追加
3. C8（deadhead energy）を SOC 遷移に統合
4. C19-C21（デマンド計算）を導入

この順で実装すると、docs/constant/formulation.md との対応が大幅に向上する。
