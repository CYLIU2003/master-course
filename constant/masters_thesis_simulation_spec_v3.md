# 修論用シミュレーションツール開発仕様書 v3
## 路線データ編集・電費/燃費推定・先行研究再現環境の強化版

## 0. この更新版の目的
本版は、既存の `masters_thesis_simulation_spec_v2.md` に対して、特に以下を強化した版である。

1. **路線データを編集可能にする**
   - 区間長、停留所、所要時間、勾配、停車回数、平均速度、混雑、空調負荷などをユーザが変更できるようにする。
2. **路線属性から電費・燃費を計算できるようにする**
   - BEV の電費 [kWh/km] と ICE/HEV の燃費 [L/km または km/L] を、路線・気象・運行条件から推定できるようにする。
3. **先行研究の再現環境として使えるようにする**
   - 「単純な trip 単位入力」と「詳細な route-segment 単位入力」の両方を扱えるようにし、論文再現と自分の独自拡張を両立させる。

この追加は、電気バス計画問題が charging scheduling だけでなく、vehicle scheduling、fleet composition、charging station capacity、energy consumption uncertainty に強く依存するという先行研究の整理と整合する。特に、trip 距離や energy consumption の変化が resource assignment と robustness に影響することが重要である。  
参考: Chen et al. (2023), He et al. (2023), He et al. (2023), Perumal et al. (2021), Ji et al. (2022), Bie et al. (2021).

---

## 1. 研究用ツールの設計方針の更新

### 1.1 これまでの弱点
固定 trip 入力だけで最適化を行うと、次の問題が生じる。

- trip ごとの消費エネルギーが外生的に固定される
- route length や勾配変更の影響を直接表現できない
- 電費と燃費の比較が「与えられた係数の比較」になりやすい
- 先行研究で議論される route length sensitivity や uncertainty evaluation が弱くなる
- 実データへ近づけるときに、交通・停車・勾配・混雑の影響を吸収できない

### 1.2 本版で追加する考え方
本版では、入力を以下の2層で定義する。

- **Layer A: Trip abstraction layer**
  - 1本の trip に対して、出発時刻、到着時刻、始点、終点、距離、消費量などを直接与える
  - 先行研究再現や Toy Problem に向く
- **Layer B: Route-detail layer**
  - route / direction / stop sequence / segment ごとの情報を持ち、そこから trip の travel time と energy/fuel consumption を生成する
  - あなたの修論で、路線条件変更や電費・燃費比較を行う基礎になる

**原則として、最適化モデルは Trip abstraction layer を入力として受け取る。**  
ただし、その trip を作る手前で route-detail layer から生成できるようにする。

---

## 2. 新規に追加するデータモデル

## 2.1 路線ネットワークの最上位エンティティ

### Route
- `route_id`: str
- `route_name`: str
- `operator_id`: str
- `mode`: str
  - "urban_bus", "shuttle", "BRT" など
- `direction_set`: list[str]
  - 例: ["outbound", "inbound"]
- `base_headway_min_peak`: float | None
- `base_headway_min_offpeak`: float | None
- `route_type`: str
  - "loop", "bidirectional", "branch"
- `notes`: str | None

### Terminal
- `terminal_id`: str
- `terminal_name`: str
- `lat`: float | None
- `lon`: float | None
- `is_depot`: bool
- `has_charger_site`: bool
- `charger_site_id`: str | None

### Stop
- `stop_id`: str
- `route_id`: str
- `direction_id`: str
- `stop_sequence`: int
- `stop_name`: str
- `lat`: float | None
- `lon`: float | None
- `elevation_m`: float | None
- `is_terminal`: bool
- `dwell_time_mean_min`: float
- `boarding_mean`: float | None
- `alighting_mean`: float | None

### Segment
路線を stop-to-stop 単位で分割した最小単位。

- `segment_id`: str
- `route_id`: str
- `direction_id`: str
- `from_stop_id`: str
- `to_stop_id`: str
- `sequence`: int
- `distance_km`: float
- `scheduled_run_time_min`: float
- `mean_speed_kmh`: float | None
- `speed_limit_kmh`: float | None
- `grade_avg_pct`: float | None
- `grade_max_pct`: float | None
- `intersection_count`: int | None
- `signal_count`: int | None
- `curvature_level`: float | None
- `road_type`: str | None
  - "arterial", "local", "express", "mixed"
- `traffic_level`: float | None
  - 0.0 to 1.0
- `congestion_index`: float | None
  - 0.0 to 3.0 など
- `surface_condition`: str | None
- `deadhead_allowed`: bool
- `energy_factor_override`: float | None
- `fuel_factor_override`: float | None

### RouteVariant
分岐や短折返しを扱うための route pattern。

- `variant_id`: str
- `route_id`: str
- `direction_id`: str
- `variant_name`: str
- `segment_id_list`: list[str]
- `is_default`: bool

### TimetablePattern
- `pattern_id`: str
- `route_id`: str
- `direction_id`: str
- `variant_id`: str
- `service_day_type`: str
  - "weekday", "saturday", "holiday"
- `start_time`: str
- `end_time`: str
- `headway_min`: float
- `dispatch_rule`: str
  - "fixed_headway", "fixed_departure", "custom"

---

## 2.2 Trip 生成関連エンティティ

### GeneratedTrip
route-detail layer から生成され、最適化モデルへ渡される trip。

- `trip_id`: str
- `route_id`: str
- `direction_id`: str
- `variant_id`: str
- `service_day_type`: str
- `departure_time`: datetime
- `arrival_time`: datetime
- `origin_terminal_id`: str
- `destination_terminal_id`: str
- `distance_km`: float
- `scheduled_runtime_min`: float
- `scheduled_dwell_total_min`: float
- `deadhead_before_km`: float | None
- `deadhead_after_km`: float | None
- `estimated_energy_kwh_bev`: float | None
- `estimated_fuel_l_ice`: float | None
- `estimated_energy_rate_kwh_per_km`: float | None
- `estimated_fuel_rate_l_per_km`: float | None
- `trip_category`: str
  - "revenue", "deadhead", "pull_out", "pull_in"

### DeadheadArc
- `arc_id`: str
- `from_trip_id`: str
- `to_trip_id`: str
- `from_terminal_id`: str
- `to_terminal_id`: str
- `deadhead_time_min`: float
- `deadhead_distance_km`: float
- `deadhead_energy_kwh_bev`: float | None
- `deadhead_fuel_l_ice`: float | None
- `is_feasible_connection`: bool

---

## 2.3 車両側エンティティの拡張

### VehicleType
- `vehicle_type_id`: str
- `powertrain`: str
  - "BEV", "ICE", "HEV", "PHEV"
- `battery_capacity_kwh`: float | None
- `usable_battery_ratio`: float | None
- `fuel_tank_l`: float | None
- `base_vehicle_mass_ton`: float | None
- `passenger_capacity`: int | None
- `seated_capacity`: int | None
- `charging_power_max_kw`: float | None
- `discharging_power_max_kw`: float | None
- `regen_efficiency`: float | None
- `hvac_power_kw_cooling`: float | None
- `hvac_power_kw_heating`: float | None
- `base_energy_rate_kwh_per_km`: float | None
- `base_fuel_rate_l_per_km`: float | None
- `purchase_cost_jpy`: float | None
- `fixed_om_cost_jpy_per_day`: float | None

### Vehicle
- `vehicle_id`: str
- `vehicle_type_id`: str
- `depot_id`: str
- `initial_soc_kwh`: float | None
- `initial_fuel_l`: float | None
- `availability_start`: datetime | None
- `availability_end`: datetime | None
- `assigned_driver_group`: str | None

---

## 3. 路線編集を可能にする入出力仕様

## 3.1 必須 CSV / JSON ファイル
最低限、以下のファイルを編集可能にする。

1. `routes.csv`
2. `terminals.csv`
3. `stops.csv`
4. `segments.csv`
5. `route_variants.json`
6. `timetable_patterns.csv`
7. `service_calendar.csv`
8. `vehicle_types.csv`
9. `vehicles.csv`
10. `chargers.csv`
11. `tariff.csv`
12. `weather_timeseries.csv` (任意だが推奨)
13. `passenger_load_profile.csv` (任意)
14. `traffic_profile.csv` (任意)

## 3.2 研究者が編集する想定の列
研究で頻繁に変える列を明示する。

### segments.csv で頻繁に変える列
- `distance_km`
- `scheduled_run_time_min`
- `grade_avg_pct`
- `signal_count`
- `traffic_level`
- `congestion_index`

### timetable_patterns.csv で頻繁に変える列
- `headway_min`
- `start_time`
- `end_time`

### vehicle_types.csv で頻繁に変える列
- `battery_capacity_kwh`
- `base_energy_rate_kwh_per_km`
- `base_fuel_rate_l_per_km`
- `charging_power_max_kw`

### weather_timeseries.csv で頻繁に変える列
- `ambient_temp_c`
- `rain_flag`
- `hvac_mode`

---

## 4. 路線データから trip を生成するロジック

## 4.1 Trip 生成の流れ
1. `RouteVariant` を読み込む
2. `TimetablePattern` と `service_calendar` を読み込む
3. 所定の時間帯に応じて出発列を生成する
4. variant を構成する `segment_id_list` を順に走査する
5. 各 segment の走行時間と stop dwell を積み上げる
6. total distance, total runtime, terminal information を集計する
7. 当該 trip の energy / fuel を推定する
8. `GeneratedTrip` として出力する

## 4.2 サービス日の扱い
最低限、以下を扱う。
- weekday
- saturday
- holiday
- custom_event_day

## 4.3 デッドヘッド接続の生成
trip 間の接続可能性は以下で判定する。

### 接続 feasible 条件
trip i の終了後、次の条件を満たすと trip j に接続可能。
- `arrival_time_i + turnaround_buffer + deadhead_time_ij <= departure_time_j`
- terminal / depot / charger site の位置関係が整合
- 必要なら SOC / fuel が接続時点で成立

### deadhead 入力
deadhead は以下のどちらかで与える。
- 実データテーブルで与える
- terminal 間距離から近似計算する

---

## 5. 電費・燃費推定ロジック

## 5.1 基本思想
先行研究では、trip の energy consumption は実測データから得た分布や回帰式、または簡易モデルで与えられることが多い。一方で高精度すぎる vehicle dynamics モデルは charging schedule 問題に対して過剰なことがある。したがって本ツールでは、**簡易だが説明可能で、感度分析しやすい推定モデル** を採用する。  
参考: He et al. (2023) は実測データと journey energy estimation model を用いた簡易モデルを採用。Chen et al. (2023) は trip energy consumption samples を生成し、vehicle type に応じた調整を導入。Ji et al. (2022) は trip energy estimation を別論文として参照。

## 5.2 推定レベルの切替
エネルギー/燃料推定は 3 段階にする。

### Level 0: fixed exogenous
- trip ごとに `energy_kwh` または `fuel_l` を外生で与える
- 文献再現の最小モード

### Level 1: route-factor linear model
- 距離、時間、勾配、停車回数、混雑、空調などから線形または affine に推定する
- 修論の基礎モード

### Level 2: segment aggregation model
- segment ごとの消費を積み上げて trip 消費を計算する
- route detail をより素直に反映できる

---

## 5.3 BEV 電費推定の標準式

### Level 1 標準式
trip t, vehicle type k に対して

`e_bev[t,k] = dist_t * beta0_k
            + runtime_h_t * beta_time_k
            + positive_grade_dist_t * beta_grade_up_k
            + abs(negative_grade_dist_t) * beta_grade_down_k
            + stop_count_t * beta_stop_k
            + passenger_load_factor_t * beta_load_k * dist_t
            + hvac_energy_t
            + congestion_index_t * beta_cong_k * dist_t
            + weather_penalty_t`

ここで
- `dist_t`: trip 距離 [km]
- `runtime_h_t`: trip 所要時間 [h]
- `positive_grade_dist_t`: 上り勾配換算距離 [km]
- `negative_grade_dist_t`: 下り勾配換算距離 [km]
- `stop_count_t`: 停車回数
- `passenger_load_factor_t`: 平均混雑率
- `hvac_energy_t`: 空調負荷に対応する電力消費 [kWh]
- `congestion_index_t`: 渋滞度指標

### Level 2 segment aggregation
segment s を trip t に含むとき

`e_bev[t,k] = sum_s e_seg_bev[s,k] + e_dwell_aux[t,k]`

segment 消費の標準式:

`e_seg_bev[s,k] = distance_s * alpha_dist_k
                + runtime_h_s * alpha_time_k
                + max(grade_avg_pct_s, 0) * distance_s * alpha_up_k
                - max(-grade_avg_pct_s, 0) * distance_s * alpha_regen_k
                + signal_count_s * alpha_stopstart_k
                + traffic_level_s * distance_s * alpha_traffic_k
                + load_factor_s * distance_s * alpha_load_k`

### 非負制約
`e_bev[t,k] >= e_min_idle_aux_t`

下り坂回生を考慮しても負値にはしない。

## 5.4 ICE / HEV 燃費推定の標準式
比較対象として ICE/HEV を入れるときは、以下の形式とする。

`f_ice[t,k] = dist_t * gamma0_k
            + runtime_h_t * gamma_time_k
            + stop_count_t * gamma_stop_k
            + positive_grade_dist_t * gamma_grade_k
            + congestion_index_t * gamma_cong_k * dist_t
            + hvac_fuel_penalty_t
            + passenger_load_factor_t * gamma_load_k * dist_t`

必要に応じて
- 出力単位を `L/trip`
- または `km/L` に変換
のいずれかで管理するが、内部表現は `L/trip` を推奨する。

## 5.5 BEV と ICE を同一土台で比較するための原則
- route-detail は共通入力を使う
- パワートレイン別に係数だけ変える
- same trip に対し `estimated_energy_kwh_bev`, `estimated_fuel_l_ice` を両方計算可能にする
- これにより「同一路線・同一ダイヤで BEV と ICE の運用コスト比較」ができる

---

## 6. 係数の校正とシナリオ

## 6.1 校正方法
係数は次の優先順で設定する。

1. 実測データ回帰
2. 文献値
3. 初期仮定値
4. 感度分析でレンジ評価

## 6.2 文献由来の補助知見
- 路線長や trip energy consumption の変化は resource assignment と robustness に影響する
- energy consumption uncertainty は確率分布または scenario samples で扱う
- battery capacity の違いは energy consumption rate の差として近似されることがある
- road grade, temperature, auxiliary load, passenger load, traffic condition が電費に効く

## 6.3 uncertainty シナリオ
`scenario_id` ごとに以下を変動させる。

- travel_time_multiplier
- energy_multiplier
- congestion_index_shift
- ambient_temp_c
- passenger_load_multiplier
- rainfall_flag

trip 消費は例えば
`e_bev_scenario[t,k,omega] = e_bev[t,k] * energy_multiplier[omega,t]`
で生成する。

---

## 7. バス運行ロジックとして実装すべきもの

## 7.1 基本運行ロジック
- 全 trip はちょうど1回カバーされる
- 車両は同時に複数 trip を担当しない
- 接続可能 arc のみ連続運行できる
- pull-out / pull-in を持てる
- deadhead を伴う接続を許す
- ターミナルで turnaround buffer を確保する
- 必要なら休憩制約や driver-related 制約を将来拡張できる

## 7.2 electric bus 特有ロジック
- 各時点で SOC 下限以上
- 充電は charger site と charger capacity の制約内
- 充電パワーは車両側上限と charger 側上限の min
- depot overnight charging と en-route charging を区別できる
- partial charging を許容可能
- nonlinear charging は piecewise linear で近似可能

## 7.3 mixed fleet ロジック
- BEV, ICE, HEV を同一 trip pool に割当可能
- ただし route restriction や terminal restriction を付けられる
- BEV は電池制約、ICE は燃料制約、HEV は簡略燃料制約
- 車種別の運行コスト、充電/給油コスト、排出係数を比較可能

---

## 8. 先行研究再現モードの更新

## 8.1 reproduction_mode_simple
- trip ごとに距離と消費量を直接与える
- 既存論文の表をそのまま再現しやすい

## 8.2 reproduction_mode_route_length_sensitivity
- route length を倍率で変更する
- Chen et al. (2023) 系の sensitivity を再現しやすい

## 8.3 reproduction_mode_uncertainty
- travel time, energy consumption を scenario sample で変動
- robustness を評価する

## 8.4 thesis_mode_route_editable
- route / segment / timetable を編集可能
- そこから trip を自動生成
- BEV と ICE の電費/燃費を比較
- charging scheduling, fleet assignment, tariff, PV を統合

---

## 9. 推奨フォルダ構成の更新

```text
project_root/
  data/
    route_master/
      routes.csv
      terminals.csv
      stops.csv
      segments.csv
      route_variants.json
      timetable_patterns.csv
      service_calendar.csv
    fleet/
      vehicle_types.csv
      vehicles.csv
    infra/
      charger_sites.csv
      chargers.csv
      depot_grid_limits.csv
    external/
      tariff.csv
      weather_timeseries.csv
      passenger_load_profile.csv
      traffic_profile.csv
    derived/
      generated_trips.csv
      deadhead_arcs.csv
      scenario_trip_energy.csv
  src/
    schemas/
      route_entities.py
      trip_entities.py
      fleet_entities.py
    preprocess/
      route_builder.py
      timetable_generator.py
      trip_generator.py
      deadhead_builder.py
      energy_model.py
      fuel_model.py
      scenario_generator.py
    model/
      ...
```

---

## 10. 実装モジュール仕様の追加

## 10.1 `route_builder.py`
責務:
- route / stop / segment / variant の整合性検査
- segment sequence の復元
- terminal と charger site の対応確認

主関数:
- `validate_route_network()`
- `build_variant_segments()`
- `summarize_route_statistics()`

## 10.2 `timetable_generator.py`
責務:
- headway または departure list から trip 列を生成

主関数:
- `generate_departure_times()`
- `expand_service_calendar()`

## 10.3 `trip_generator.py`
責務:
- variant + departure time から GeneratedTrip を作る

主関数:
- `generate_trip_from_variant()`
- `generate_all_trips()`

## 10.4 `energy_model.py`
責務:
- BEV trip energy estimation
- segment aggregation
- scenario perturbation

主関数:
- `estimate_trip_energy_bev()`
- `estimate_segment_energy_bev()`
- `apply_energy_uncertainty()`

## 10.5 `fuel_model.py`
責務:
- ICE / HEV fuel estimation

主関数:
- `estimate_trip_fuel_ice()`
- `estimate_trip_fuel_hev()`

## 10.6 `deadhead_builder.py`
責務:
- trip 間接続可能性、deadhead time, deadhead distance を生成

主関数:
- `build_deadhead_arcs()`
- `build_can_follow_matrix()`

---

## 11. 研究者向け設定ファイル仕様

### `experiment_config.json`
```json
{
  "mode": "thesis_mode_route_editable",
  "time_resolution_min": 5,
  "energy_model_level": 2,
  "fuel_model_enabled": true,
  "allow_deadhead": true,
  "allow_partial_charging": true,
  "allow_enroute_charging": true,
  "uncertainty_enabled": true,
  "objective_weights": {
    "energy_cost": 1.0,
    "demand_charge": 1.0,
    "fleet_cost": 0.0,
    "degradation_cost": 0.3,
    "delay_penalty": 10.0
  }
}
```

### route editing 用設定例
```json
{
  "route_edit_rules": {
    "apply_distance_multiplier": {
      "route_101": 1.10
    },
    "apply_congestion_shift": {
      "weekday_peak": 0.20
    },
    "apply_grade_override": {
      "segment_101_05": 3.5
    }
  }
}
```

---

## 12. 最低限の KPI の追加
路線編集機能を入れることで、KPI も追加する。

### route / trip 系
- route total distance [km/day]
- revenue distance [km/day]
- deadhead distance [km/day]
- average commercial speed [km/h]
- average turnaround slack [min]

### energy / fuel 系
- total BEV energy consumption [kWh/day]
- average BEV energy rate [kWh/km]
- total ICE fuel consumption [L/day]
- average ICE fuel rate [L/km]
- auxiliary energy share [%]
- energy due to grade / congestion / HVAC の寄与分解

### operation / infra 系
- charger utilization [%]
- depot peak demand [kW]
- unserved trip count
- infeasible connection count
- low-SOC violation count

---

## 13. 実装優先順位の更新
次の順で作ることを推奨する。

### Step 1
- route / stop / segment の schema
- timetable から trip 生成
- fixed energy input

### Step 2
- route-factor linear energy model
- fuel model
- generated_trips.csv 出力

### Step 3
- deadhead arc 自動生成
- vehicle-trip assignment
- SOC tracking

### Step 4
- charger capacity
- TOU / demand charge
- partial charging

### Step 5
- uncertainty scenarios
- route length sensitivity
- congestion / weather sensitivity

### Step 6
- PV / ESS / mixed fleet strategic planning

---

## 14. Vibe Coding Agent に伝えるべき要点
この研究ツールは、単なる「充電最適化コード」ではない。  
**路線を編集して、その変更が trip travel time、energy consumption、fuel consumption、vehicle assignment、charging schedule、運用コストにどう効くかを一気通貫で見るための研究基盤** である。

したがって Agent は次を守ること。

1. route-detail layer と trip abstraction layer を分離して実装する
2. route を編集したら generated_trips が再生成される構造にする
3. BEV と ICE/HEV を同一 route データから比較できるようにする
4. fixed-energy 再現モードと editable-route モードを両立させる
5. 先行研究再現に必要な簡易入力も残す

---

## 15. 参考文献
本仕様の設計で特に意識した文献は以下である。

1. Chen, Q. et al. (2023). Transportation Research Part D, 118, 103724.
   - multiple vehicle types, charging station capacity, nonlinear charging, energy consumption uncertainty, route length sensitivity
2. He, Y. et al. (2023). Transportation Research Part D, 117, 103653.
   - joint optimization of charging infrastructure planning, vehicle scheduling, charging management, TOU and demand charge
3. He, Y. et al. (2023). Transportation Research Part D, 115.
   - journey energy estimation model and simple charging schedule model
4. Wang, X. et al. (2024 or related). charger placement / fleet configuration / battery degradation 系
5. Perumal, S. et al. (2021). European Journal of Operational Research.
   - electric bus planning and scheduling review
6. Ji, J. et al. (2022). Trip energy consumption estimation for electric buses.
7. Bie, Y. et al. (2021). Optimization of electric bus scheduling considering stochastic volatilities in trip travel time and energy consumption.

以上。
