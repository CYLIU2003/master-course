# 修論用シミュレーションツール開発仕様書

## ステータス
- 分類: アーカイブ候補
- 用途: 旧版仕様の参照
- 備考: 基本参照は v2 系列を優先する

## 0. 文書の目的
本仕様書は、修士論文で扱う **電気バス運行・配車・充電スケジューリング最適化** を対象に、
Vibe Coding Agent あるいは Python 実装者がそのままコード化できるよう、
モデル内で必要となる **集合・定数・入力パラメータ・決定変数・導出変数・出力・制約対応** を整理したものである。

本仕様書の主目的は次の3点である。

1. 修論の定式化対象を、実装可能なデータ構造へ落とし込むこと。
2. Python + Gurobi による MILP 実装、ならびに ALNS 等のヒューリスティクス実装の共通土台を与えること。
3. Toy Problem から実データ拡張まで、段階的に開発できるようにすること。

---

## 1. 想定する研究対象

### 1.1 研究テーマの中心
対象は、**都市バス事業者における混成車両群（BEVバス + ICE/従来バス）** を想定した、
以下の統合最適化問題である。

- どの便・ブロックをどの車両が担当するか
- 各BEVがどの時刻にどこでどれだけ充電するか
- 充電器の利用競合をどう避けるか
- PV発電をどの程度自家消費するか
- 系統受電量・契約電力・電力料金をどう抑えるか
- 必要に応じてV2Gや蓄電池をどう扱うか

### 1.2 本ツールの役割
本ツールは大きく分けて、以下のいずれか、または両方を担う。

- **最適化エンジン**: Gurobi により数理最適化を解く
- **シミュレーション/評価エンジン**: 与えられた配車・充電計画を時系列に評価する

### 1.3 開発方針
初期段階では以下の順に開発する。

1. Toy Problem 用の小規模データで MILP を解く
2. 同じ入力形式で評価シミュレータを動かす
3. ALNS 等の近似解法を追加する
4. PV・需要料金・劣化コスト・不確実性を順次追加する

---

## 2. ツール全体の機能要件

### 2.1 必須機能
- 路線便・ブロック・デポ・充電拠点・車両・充電器のデータを読み込めること
- 時間離散化されたスケジュール問題を構築できること
- Gurobi 用 MILP モデルを自動生成できること
- 解の可否、目的関数値、各車両の運用計画、各時刻の充電計画を出力できること
- 目的関数・制約の ON/OFF 切替ができること
- Toy Problem と実験用ケーススタディの双方に対応できること

### 2.2 望ましい機能
- ALNS/GA 等のメタヒューリスティクスと共通のデータ構造を持つこと
- 結果を CSV / JSON / Markdown / 図表用データとして出力できること
- ケース比較（PVあり/なし、BEV比率違い、充電器数違い等）が自動実行できること
- infeasible のとき、どの制約群が原因かを切り分けやすい構造であること

---

## 3. 想定アーキテクチャ

```text
project_root/
  data/
    toy/
    case_study/
  config/
    experiment_config.json
    objective_flags.json
  src/
    data_loader.py
    data_schema.py
    model_sets.py
    parameter_builder.py
    milp_model.py
    constraints/
      assignment.py
      charging.py
      energy_balance.py
      charger_capacity.py
      pv_grid.py
      battery_degradation.py
      optional_v2g.py
    objective.py
    solver_runner.py
    simulator.py
    result_exporter.py
    visualization.py
  outputs/
    run_yyyymmdd_hhmm/
```

---

## 4. 数理モデルの粒度

本研究で最低限必要な離散化レベルは以下とする。

- 時間: `t ∈ T` （例: 5分, 10分, 15分刻み）
- 車両: `k ∈ K`
- 運行タスク/便/ブロック: `r ∈ R`
- 拠点/デポ/充電地点: `i ∈ I`
- 充電器: `c ∈ C`

実装上は、**便単位モデル** と **ブロック単位モデル** の両対応が望ましい。
初期版ではブロック単位を推奨する。

---

## 5. 集合・インデックス定義

以下はコード内で `set` または `list` として保持する対象である。

### 5.1 車両関連
- `K_BEV`: BEV車両集合
- `K_ICE`: ICE車両集合
- `K_ALL`: 全車両集合

### 5.2 運行関連
- `R`: 運行タスク集合
  - 便単位なら1便=1タスク
  - ブロック単位なら1日の連続運用単位=1タスク
- `R_BEV_ELIGIBLE`: BEVでも担当可能なタスク集合
- `R_ICE_ELIGIBLE`: ICEでも担当可能なタスク集合

### 5.3 時間関連
- `T`: 離散時刻集合
- `T_START`: 開始時刻インデックス
- `T_END`: 終了時刻インデックス

### 5.4 地点関連
- `I_DEPOT`: デポ集合
- `I_CHARGE`: 充電可能地点集合
- `I_ROUTE`: 中継地点・運行地点集合
- `I_ALL`: 全地点集合

### 5.5 充電設備関連
- `C`: 充電器集合
- `C_i`: 地点 `i` に属する充電器集合
- `K_COMPAT_c`: 充電器 `c` を使用可能な車両集合

### 5.6 エネルギー関連
- `S`: シナリオ集合（ロバスト/確率拡張時）

---

## 6. 入力パラメータ・定数一覧

以下のパラメータは、実装上 `dict`, `pandas DataFrame`, `dataclass`, `pydantic model` 等で保持する。

## 6.1 共通運行パラメータ

### 6.1.1 タスク基本情報
- `start_time[r]`: タスク `r` の開始時刻
- `end_time[r]`: タスク `r` の終了時刻
- `duration[r]`: タスク継続時間
- `origin[r]`: タスク開始地点
- `destination[r]`: タスク終了地点
- `distance[r]`: タスク走行距離
- `travel_time[r]`: タスク所要時間
- `required_vehicle_type[r]`: 必要車種条件

### 6.1.2 タスク間接続情報
- `can_follow[r1, r2] ∈ {0,1}`: `r1` の後に `r2` を同一車両で連続担当可能か
- `deadhead_time[r1, r2]`: 回送時間
- `deadhead_energy[r1, r2]`: 回送時消費電力量
- `deadhead_distance[r1, r2]`: 回送距離

### 6.1.3 運行需要条件
- `demand_cover[r]`: タスク `r` が必要本数として必ずカバーすべきか
- `penalty_unserved[r]`: 未割当許容時のペナルティ

## 6.2 車両パラメータ

### 6.2.1 共通
- `vehicle_type[k]`: 車両種別（BEV/ICE 等）
- `home_depot[k]`: 所属デポ
- `available_start[k]`: 運用開始可能時刻
- `available_end[k]`: 運用終了可能時刻
- `fixed_use_cost[k]`: 車両使用固定費
- `max_operating_time[k]`: 1日の最大稼働時間
- `max_distance[k]`: 1日の最大走行距離

### 6.2.2 BEV固有
- `battery_capacity[k]`: 電池容量 [kWh]
- `soc_init[k]`: 初期SOC [kWh または pu]
- `soc_min[k]`: 最低SOC
- `soc_max[k]`: 最大SOC
- `soc_target_end[k]`: 終了時目標SOC
- `energy_consumption_rate[k, r]`: タスク `r` 実行時の消費電力量 [kWh]
- `charge_power_max[k]`: 車両側最大受電電力 [kW]
- `charge_efficiency[k]`: 充電効率
- `discharge_power_max[k]`: V2G 時最大放電電力 [kW]
- `discharge_efficiency[k]`: 放電効率
- `battery_degradation_cost_coeff[k]`: 劣化コスト係数

### 6.2.3 ICE固有
- `fuel_consumption_rate[k, r]`: タスク `r` 実行時の燃料消費
- `fuel_tank_capacity[k]`: 燃料タンク容量
- `fuel_cost_coeff[k]`: 燃料単価係数
- `co2_emission_coeff[k]`: CO2排出係数

## 6.3 充電設備パラメータ

- `charger_site[c]`: 充電器 `c` の設置地点
- `charger_power_max[c]`: 充電器最大出力 [kW]
- `charger_power_min[c]`: 必要なら最低出力
- `charger_count_at_site[i]`: 地点 `i` の充電器数
- `charger_efficiency[c]`: 充電器効率
- `compatibility[k, c] ∈ {0,1}`: 車両 `k` と充電器 `c` の適合性
- `site_grid_limit[i]`: 地点 `i` の受電上限 [kW]
- `site_transformer_limit[i]`: 地点 `i` の設備上限制約

## 6.4 電力・PV・系統関連パラメータ

- `pv_generation[i, t]`: 地点 `i` 時刻 `t` のPV発電量 [kW or kWh/slot]
- `grid_energy_price[i, t]`: 系統電力量料金
- `sell_back_price[i, t]`: 逆潮流売電単価
- `demand_charge_rate[i]`: デマンド料金単価
- `base_load[i, t]`: 地点 `i` のバス以外の基礎負荷
- `grid_import_limit[i, t]`: 系統受電上限
- `grid_export_limit[i, t]`: 系統逆潮流上限
- `contract_demand_limit[i]`: 契約電力上限
- `co2_grid_factor[i, t]`: 系統電力 CO2 排出係数

## 6.5 定式化用ビッグM等

- `BIG_M_ASSIGN`: 割当制約用 Big-M
- `BIG_M_CHARGE`: 充電有無リンク用 Big-M
- `BIG_M_SOC`: SOC 遷移用 Big-M
- `EPSILON`: 数値安定用小値

## 6.6 時間離散化パラメータ

- `delta_t_hour`: 1スロット時間 [hour]
- `delta_t_min`: 1スロット時間 [min]
- `planning_horizon_hours`: 計画時間長

## 6.7 オプション拡張用パラメータ

### 6.7.1 蓄電池併設時
- `stationary_battery_capacity[i]`
- `stationary_soc_init[i]`
- `stationary_charge_power_max[i]`
- `stationary_discharge_power_max[i]`
- `stationary_efficiency_charge[i]`
- `stationary_efficiency_discharge[i]`

### 6.7.2 不確実性導入時
- `scenario_probability[s]`
- `pv_generation[i, t, s]`
- `energy_consumption_rate[k, r, s]`
- `travel_time[r, s]`
- `grid_energy_price[i, t, s]`

---

## 7. 決定変数一覧

以下は MILP 実装で `addVar` / `addVars` される主要変数である。

## 7.1 車両割当変数

### 7.1.1 タスク割当
- `x[k, r] ∈ {0,1}`
  - 車両 `k` がタスク `r` を担当するなら1

### 7.1.2 タスク接続
- `y[k, r1, r2] ∈ {0,1}`
  - 車両 `k` が `r1` の直後に `r2` を担当するなら1

### 7.1.3 車両使用有無
- `u[k] ∈ {0,1}`
  - 車両 `k` をその日に使用するなら1

## 7.2 位置・在車状態関連変数（時間展開モデル）

### 7.2.1 位置状態
- `loc[k, i, t] ∈ {0,1}`
  - 時刻 `t` に車両 `k` が地点 `i` に存在するなら1

### 7.2.2 運行中状態
- `in_service[k, t] ∈ {0,1}`
  - 時刻 `t` に車両 `k` が便運行中なら1

### 7.2.3 待機状態
- `idle[k, i, t] ∈ {0,1}`
  - 時刻 `t` に車両 `k` が地点 `i` で待機中なら1

## 7.3 充電関連変数

### 7.3.1 充電器利用有無
- `z[k, c, t] ∈ {0,1}`
  - 時刻 `t` に車両 `k` が充電器 `c` を使用しているなら1

### 7.3.2 充電電力
- `p_charge[k, c, t] ≥ 0`
  - 時刻 `t` に車両 `k` が充電器 `c` から受ける充電電力 [kW]

### 7.3.3 地点単位充電電力
- `p_charge_site[k, i, t] ≥ 0`
  - 地点 `i` ベースで扱う場合の充電電力

### 7.3.4 放電電力（V2G）
- `p_discharge[k, i, t] ≥ 0`
  - 時刻 `t` に地点 `i` で車両 `k` が放電する電力

### 7.3.5 充放電状態フラグ
- `z_charge[k, t] ∈ {0,1}`
- `z_discharge[k, t] ∈ {0,1}`

## 7.4 電池状態変数

### 7.4.1 SOC
- `soc[k, t]`
  - 時刻 `t` の車両 `k` のSOC [kWh]

### 7.4.2 劣化量近似変数
- `deg[k, t] ≥ 0`
  - 時刻 `t` に対応する劣化コスト用補助変数

## 7.5 系統・PV関連変数

- `p_grid_import[i, t] ≥ 0`: 系統からの受電電力
- `p_grid_export[i, t] ≥ 0`: 系統への逆潮流電力
- `p_pv_used[i, t] ≥ 0`: PV自家消費分
- `p_pv_curtail[i, t] ≥ 0`: 出力抑制分
- `peak_demand[i] ≥ 0`: 地点 `i` のピーク需要

## 7.6 未達・緩和用変数

- `slack_soc[k, t] ≥ 0`: SOC制約違反緩和
- `slack_cover[r] ≥ 0`: 需要未充足緩和
- `slack_grid[i, t] ≥ 0`: 系統上限違反緩和

---

## 8. 導出変数・評価指標

これらは決定変数ではなく、解から計算して評価する量である。

- `total_operating_cost`
- `total_energy_cost`
- `total_demand_charge`
- `total_degradation_cost`
- `total_fuel_cost`
- `total_co2_emission`
- `pv_self_consumption_ratio`
- `charger_utilization[c]`
- `vehicle_utilization[k]`
- `served_task_ratio`
- `infeasibility_penalty_total`

---

## 9. 目的関数候補

実装上、目的関数は加重和形式にし、設定ファイルで係数変更可能とする。

### 9.1 基本形
最小化対象の候補は以下。

- 車両使用固定費
- 電力量料金
- デマンド料金
- ICE燃料費
- 回送コスト
- 劣化コスト
- CO2排出コスト換算
- 未割当ペナルティ
- 緩和変数ペナルティ

### 9.2 実装用の目的関数例

```text
minimize
  w1 * vehicle_fixed_cost
+ w2 * electricity_cost
+ w3 * demand_charge_cost
+ w4 * fuel_cost
+ w5 * deadhead_cost
+ w6 * battery_degradation_cost
+ w7 * emission_cost
+ w8 * unserved_penalty
+ w9 * slack_penalty
```

### 9.3 実装要件
- 係数 `w1 ... w9` は JSON から変更可能にすること
- 目的関数の各項は個別にログ出力すること
- 比較実験時に各項の寄与率を確認できること

---

## 10. 制約群の実装仕様

ここでは「何を実装すべきか」を、コードモジュール単位で整理する。

## 10.1 割当制約群

### 10.1.1 各タスクの担当制約
- 各タスクは必要本数ぶん割り当てられること
- 完全充足なら `sum_k x[k,r] = 1`
- 不完全許容なら `sum_k x[k,r] + slack_cover[r] = 1`

### 10.1.2 車両ごとの担当可能性
- 車種不適合なら割当禁止
- 時間帯が重複するタスクを同一車両へ同時割当禁止

### 10.1.3 連続性制約
- `r1` の後に `r2` を担当できるのは時間・地点的に接続可能な場合のみ
- フローベース定式化では入次数・出次数整合が必要

## 10.2 稼働時間・距離制約群

- 1台あたり最大稼働時間を超えないこと
- 1台あたり最大走行距離を超えないこと
- 必要なら乗務員制約・休憩制約も将来拡張できる構造にすること

## 10.3 位置・時間整合制約群

- ある時刻で車両は1つの状態にのみ存在すること
  - 運行中、充電中、待機中の排他性
- 地点遷移とタスク実行の整合
- 初期地点は所属デポ
- 終了地点条件を必要に応じて設定

## 10.4 充電器容量制約群

### 10.4.1 同時利用制約
- 各充電器は同時に高々1台
  - `sum_k z[k,c,t] <= 1`

### 10.4.2 充電電力上限制約
- `p_charge[k,c,t] <= charger_power_max[c] * z[k,c,t]`
- 車両側受電上限も同時に満たすこと

### 10.4.3 互換性制約
- 不適合な車両と充電器の組み合わせは禁止

## 10.5 SOC 遷移制約群

### 10.5.1 基本遷移
各BEVについて、SOC は次式に従って更新する。

```text
soc[k,t+1] = soc[k,t]
           - driving_energy[k,t]
           - deadhead_energy[k,t]
           + charge_energy[k,t]
           - discharge_energy[k,t]
```

### 10.5.2 上下限制約
- `soc_min[k] <= soc[k,t] <= soc_max[k]`
- 終了時に `soc[k, T_END] >= soc_target_end[k]`

### 10.5.3 実装注意
- 時間離散化が粗い場合、充電と運行の同時発生矛盾に注意
- `kWh` ベースで統一し、`kW × delta_t_hour = kWh` を明示すること

## 10.6 電力需給制約群

各地点 `i`・時刻 `t` において、
充電・放電・PV・基礎負荷・系統受電のバランスを満たすこと。

例:

```text
p_grid_import[i,t] + p_pv_used[i,t] + p_discharge_total[i,t]
= base_load[i,t] + p_charge_total[i,t] + p_grid_export[i,t] + p_pv_curtail[i,t]
```

## 10.7 受電上限・デマンド制約群

- `p_grid_import[i,t] <= grid_import_limit[i,t]`
- `p_grid_import[i,t] + base_load[i,t] <= peak_demand[i]`
- `peak_demand[i] <= contract_demand_limit[i]` （必要に応じて hard/soft 切替）

## 10.8 PV 利用制約群

- `p_pv_used[i,t] + p_pv_curtail[i,t] <= pv_generation[i,t]`
- 自家消費優先、売電あり/なしは設定で切替

## 10.9 V2G 制約群（任意）

- 充電と放電の同時実行禁止
- 系統逆潮流や設備制約を満たすこと
- V2G許可対象時刻のみ許可する設定も可能にすること

## 10.10 劣化コスト制約群（任意）

- 充放電電力量に比例する近似
- または throughput ベース線形近似
- 初版では線形係数近似で十分

## 10.11 緩和制約群

- infeasible 回避のため、主要制約には緩和変数を付与可能にする
- ただし緩和には十分大きなペナルティを課すこと
- 緩和項は結果出力で必ず可視化すること

---

## 11. 実装上のデータモデル仕様

## 11.1 推奨データクラス

### 11.1.1 Vehicle
```python
@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    home_depot: str
    battery_capacity: float | None
    soc_init: float | None
    soc_min: float | None
    soc_max: float | None
    soc_target_end: float | None
    charge_power_max: float | None
    discharge_power_max: float | None
    fixed_use_cost: float
    max_operating_time: float
    max_distance: float
```

### 11.1.2 Task
```python
@dataclass
class Task:
    task_id: str
    start_time_idx: int
    end_time_idx: int
    origin: str
    destination: str
    distance_km: float
    energy_required_kwh_bev: float
    fuel_required_liter_ice: float
    required_vehicle_type: str | None
```

### 11.1.3 Charger
```python
@dataclass
class Charger:
    charger_id: str
    site_id: str
    power_max_kw: float
    efficiency: float
```

### 11.1.4 Site
```python
@dataclass
class Site:
    site_id: str
    site_type: str
    grid_import_limit_kw: float
    contract_demand_limit_kw: float
```

---

## 12. 入力ファイル仕様

最低限、以下のファイル群を読み込めるようにする。

## 12.1 vehicles.csv
列例:

```text
vehicle_id,vehicle_type,home_depot,battery_capacity,soc_init,soc_min,soc_max,soc_target_end,charge_power_max,discharge_power_max,fixed_use_cost,max_operating_time,max_distance
```

## 12.2 tasks.csv
```text
task_id,start_time_idx,end_time_idx,origin,destination,distance_km,energy_required_kwh_bev,fuel_required_liter_ice,required_vehicle_type
```

## 12.3 compatibility_vehicle_task.csv
```text
vehicle_id,task_id,feasible
```

## 12.4 compatibility_vehicle_charger.csv
```text
vehicle_id,charger_id,feasible
```

## 12.5 chargers.csv
```text
charger_id,site_id,power_max_kw,efficiency
```

## 12.6 sites.csv
```text
site_id,site_type,grid_import_limit_kw,contract_demand_limit_kw
```

## 12.7 pv_profile.csv
```text
site_id,time_idx,pv_generation_kw
```

## 12.8 electricity_price.csv
```text
site_id,time_idx,grid_energy_price,sell_back_price,base_load_kw
```

## 12.9 travel_connection.csv
```text
from_task_id,to_task_id,can_follow,deadhead_time_slot,deadhead_distance_km,deadhead_energy_kwh
```

## 12.10 config.json
以下のようなフラグを持つ。

```json
{
  "time_step_min": 15,
  "allow_partial_service": false,
  "enable_pv": true,
  "enable_v2g": false,
  "enable_battery_degradation": true,
  "enable_demand_charge": true,
  "use_soft_soc_constraint": false,
  "objective_weights": {
    "vehicle_fixed_cost": 1.0,
    "electricity_cost": 1.0,
    "demand_charge_cost": 1.0,
    "fuel_cost": 1.0,
    "deadhead_cost": 1.0,
    "battery_degradation_cost": 1.0,
    "emission_cost": 0.0,
    "unserved_penalty": 10000.0,
    "slack_penalty": 1000000.0
  }
}
```

---

## 13. 出力仕様

## 13.1 必須出力

### 13.1.1 summary.json
- 実行日時
- 解ステータス
- 最適値
- ギャップ
- 計算時間
- 目的関数内訳
- infeasible 時はその旨

### 13.1.2 vehicle_schedule.csv
- 車両ごとの担当タスク一覧
- 時刻別状態遷移

### 13.1.3 charging_schedule.csv
- 車両×時刻×充電器の利用状況
- 充電電力
- SOC 推移

### 13.1.4 site_power_balance.csv
- 地点ごとの受電・PV・充電需要・基礎負荷・ピーク推移

### 13.1.5 experiment_report.md
- 条件一覧
- 目的関数内訳
- 主要結果
- 解釈メモ

## 13.2 可視化出力
- SOC 推移グラフ
- 受電電力時系列グラフ
- PV利用率グラフ
- 充電器利用率ヒートマップ
- ガントチャート風の車両運行図

---

## 14. モジュール別責務

## 14.1 data_loader.py
- CSV / JSON を読み込み、内部データクラスへ変換する
- 欠損・型・単位整合を検証する

## 14.2 parameter_builder.py
- 入力データから `can_follow` や `energy_consumption_rate` 等の派生パラメータを生成する
- Big-M 値を安全に計算する

## 14.3 milp_model.py
- Gurobi Model を生成
- 変数追加
- 制約追加
- 目的関数設定

## 14.4 constraints/*.py
- 制約群を分離し、個別にON/OFF可能にする
- 例: `add_assignment_constraints(model, data, vars)`

## 14.5 solver_runner.py
- solver parameter 設定
- MIPGap, TimeLimit, Threads, Presolve 等を制御
- 解取得・例外処理を行う

## 14.6 simulator.py
- 与えられた計画をもとに、時系列評価を再計算する
- MILP解の妥当性検証にも使う

## 14.7 result_exporter.py
- CSV / JSON / Markdown 出力を一括処理する

---

## 15. Gurobi 実装時の推奨変数命名

- `x_assign[k,r]`
- `y_follow[k,r1,r2]`
- `z_charge[k,c,t]`
- `p_charge[k,c,t]`
- `soc[k,t]`
- `p_grid_import[i,t]`
- `p_pv_used[i,t]`
- `peak_demand[i]`

命名規則は、**変数名だけで意味が分かること** を優先する。

---

## 16. 単位系ルール

実装で最も壊れやすいのは単位系であるため、以下を厳守する。

- 電力: `kW`
- 電力量: `kWh`
- 時間: `hour` または `time_idx`
- 距離: `km`
- SOC: 原則 `kWh` 表記で内部管理
- 価格: `円/kWh`, `円/kW`, `円/L` などを明示

### 16.1 重要ルール
- `kW` と `kWh` を混同しないこと
- 時間離散化があるため、
  - `energy = power * delta_t_hour`
  を毎回明示すること

---

## 17. 初期実装のスコープ分割

## Phase 1: 最小Toy Problem
- 車両数 3〜5台
- タスク数 5〜10件
- デポ1箇所
- 充電地点1箇所
- 充電器1〜2口
- PVなし
- 需要料金なし
- V2Gなし

### この段階で必要な変数
- `x[k,r]`
- `z[k,c,t]`
- `p_charge[k,c,t]`
- `soc[k,t]`
- `u[k]`

## Phase 2: 修論本体の骨格
- 混成 fleet 対応
- 回送考慮
- 電力料金導入
- PV導入
- デマンド料金導入

## Phase 3: 高度化
- 蓄電池併設
- V2G
- 劣化コスト
- ロバスト/確率シナリオ
- ALNS 比較

---

## 18. agent に伝えるべき実装要求

以下は Vibe Coding Agent へそのまま渡してよい要求文である。

### 18.1 実装要求文

```text
このプロジェクトでは、修士論文用の電気バス運行・充電スケジューリング最適化ツールを Python で実装したい。
Gurobi を用いた MILP を主解法とし、将来的に ALNS を追加できる構造にしてほしい。

要件:
1. 入力は CSV / JSON ベースで、vehicles, tasks, chargers, sites, pv_profile, electricity_price, travel_connection を読み込めること。
2. データクラスを使って入力スキーマを明確にすること。
3. 制約群は assignment, charging, SOC, charger capacity, grid balance, PV, demand charge に分割すること。
4. 各制約や目的関数項は config で ON/OFF できること。
5. 結果は summary.json, vehicle_schedule.csv, charging_schedule.csv, site_power_balance.csv, experiment_report.md として出力すること。
6. 最初は Toy Problem が必ず解けることを優先し、その後に機能を拡張すること。
7. 単位系は kW, kWh, hour, km に統一すること。
8. 変数名・関数名は意味がわかる英語で統一すること。
9. infeasible の場合に原因切り分けしやすいよう、制約群をモジュール分離すること。
10. pandas と gurobipy を前提とし、必要に応じて matplotlib で可視化できるようにすること。
```

---

## 19. この仕様書に基づく最重要「変数・定数」総覧

最後に、修論で「何が変数・定数たるものか」を一覧で再整理する。

### 19.1 集合
- 車両集合 `K_BEV, K_ICE, K_ALL`
- タスク集合 `R`
- 時刻集合 `T`
- 地点集合 `I`
- 充電器集合 `C`
- シナリオ集合 `S`（必要時）

### 19.2 定数・入力
- タスク開始時刻、終了時刻、距離、必要エネルギー
- 車両の電池容量、初期SOC、最大充電電力
- 充電器出力、互換性、地点上限
- 電力料金、PV発電量、基礎負荷
- 回送時間、回送距離、回送エネルギー
- 各種コスト係数、Big-M、時間刻み幅

### 19.3 決定変数
- 割当変数 `x`
- 接続変数 `y`
- 車両使用変数 `u`
- 充電器利用変数 `z`
- 充電電力 `p_charge`
- 放電電力 `p_discharge`
- SOC `soc`
- 系統受電 `p_grid_import`
- PV利用 `p_pv_used`
- ピーク需要 `peak_demand`
- 各種 slack 変数

### 19.4 導出量
- 総コスト
- 総電力コスト
- 総燃料コスト
- 総劣化コスト
- CO2排出量
- PV自家消費率
- 充電器利用率
- 車両稼働率

---

## 20. 備考
本仕様書は、まず **「実装のための共通言語」** を作ることを重視している。
したがって、厳密な論文用 LaTeX 定式化とは少し異なり、
**コード化しやすさ・データ化しやすさ・段階実装しやすさ** を優先している。

今後はこの仕様書を基に、次の2つへ派生できる。

1. **論文本文用の厳密 LaTeX 定式化**
2. **Gurobi / Python 実装に直結する JSON・CSV スキーマ定義**
