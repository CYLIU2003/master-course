# AGENTS_ev_route_cost.md
## 路線プロフィール準拠で EV / エンジンバスの運行・充電・コスト計算を行うためのエージェント指示書

### 1. 目的
このエージェントの目的は、既存シミュレーションツールに対して、**設定済みの路線プロフィールに従って各バスが実際に走行したものとして**、運行・充電・燃料消費・買電・契約電力・TOU料金を整合的に計算できるようにすることである。

特に、現時点で不足している **コスト計算機能** を拡張し、少なくとも次の総コスト最小化を扱える形にする。

- 車両導入費
- 燃料費
- 買電費
- 需要料金 / 契約上限コスト
- TOU料金

本エージェントは、将来的な厳密 MILP 実装の前段としても使えるように、**まずは route-profile driven な deterministic simulation / optimization** を成立させることを優先する。

---

### 2. このエージェントが必ず守る基本方針
1. **バスは路線プロフィールに従って走る**  
   走った距離・時刻・便数・停車時間・待機時間に応じて消費エネルギーまたは燃料を計算すること。

2. **コストは運行結果から後付けで計算するのではなく、運行と同時に整合して計算する**  
   すなわち、SOC 推移・充電タイミング・電力ピーク・燃料消費は、すべて時系列整合が取れていなければならない。

3. **EV とエンジンバスを同じ運行枠組みで扱う**  
   ただし、エネルギー源とコスト項目は分けること。
   - EV: 買電、契約電力、TOU
   - エンジンバス: 燃料
   - 両者共通: 車両導入費、便担当、運行制約

4. **まずは最小限の実装でよいが、将来の数理最適化へ拡張できる構造にすること**

---

### 3. 対象とする最小問題
当面は次の混成運用を扱えるようにすること。

- EV バス
- エンジンバス
- 指定された路線プロフィール
- 指定された時刻分解能 (例: 15分, 30分, 60分)
- デポ / 充電拠点
- TOU料金
- 契約上限電力または需要料金

最初の完成条件は以下とする。

- 各便が誰に割り当てられたか分かる
- 各車両がいつ走行 / 待機 / 充電しているか分かる
- EV は SOC が逐次更新される
- エンジンバスは燃料消費量が積算される
- 時刻別買電量とピーク電力が計算できる
- 総コストが計算できる

---

### 4. 入力データの考え方
入力は最低でも次の 4 系統に分けること。

#### 4.1 車両ライブラリ
各車両について次を持つこと。

##### EV バス
- vehicle_id
- vehicle_type = `ev_bus`
- purchase_cost_yen
- battery_capacity_kWh
- usable_battery_capacity_kWh
- initial_soc
- min_soc
- max_soc
- energy_consumption_kWh_per_km_base
- charging_power_max_kW
- charging_efficiency
- passenger_capacity
- route_compatibility
- depot_id

##### エンジンバス
- vehicle_id
- vehicle_type = `engine_bus`
- purchase_cost_yen
- fuel_economy_km_per_L または diesel_consumption_L_per_km
- fuel_tank_capacity_L (任意)
- initial_fuel_L (任意)
- passenger_capacity
- route_compatibility
- depot_id

#### 4.2 路線プロフィール
各路線または各便について次を持つこと。

- route_id
- trip_id
- start_time
- end_time
- distance_km
- required_bus_type (任意)
- deadhead_distance_before_km
- deadhead_distance_after_km
- average_speed_kmh (任意)
- stop_count (任意)
- elevation_factor (任意)
- load_factor (任意)
- start_terminal
- end_terminal

注意:
- 将来的には秒単位・停留所単位へ拡張可能だが、初期段階では **便単位** でよい
- まずは 1 trip ごとに距離と時刻帯が定義されていればよい

#### 4.3 電力料金・契約条件
- tou_price_yen_per_kWh[t]
- demand_charge_yen_per_kW_month
- contract_power_limit_kW
- contract_penalty_mode
- grid_basic_charge_yen (任意)
- pv_generation_kWh[t] (任意。最初は 0 可)

#### 4.4 燃料価格
- diesel_price_yen_per_L

---

### 5. 状態量
シミュレーションでは、少なくとも以下の状態量を明示的に管理すること。

#### 5.1 EV バス
- soc[v, t]
- charging_power[v, t]
- energy_used_running[v, t]
- assigned_trip[v, trip]

#### 5.2 エンジンバス
- fuel_used_running[v, t]
- remaining_fuel[v, t] (任意)
- assigned_trip[v, trip]

#### 5.3 系統側
- total_charging_power[t]
- net_grid_purchase_power[t]
- net_grid_purchase_energy[t]
- peak_demand_kW
- contract_excess_kW (必要なら)

---

### 6. 路線プロフィール準拠の運行ロジック
#### 6.1 基本ルール
各便 trip は、開始時刻から終了時刻まで 1 台の車両に連続して割り当てられなければならない。

車両は次を同時に満たす必要がある。
- その時刻に他の便を担当していない
- 路線互換条件を満たす
- EV の場合は当該 trip を走行できるだけの SOC がある
- エンジンバスの場合は必要なら燃料残量条件を満たす

#### 6.2 デッドヘッドも距離に含める
trip の前後に回送距離がある場合は、必ずエネルギー消費または燃料消費に反映すること。

```text
effective_trip_distance_km
= deadhead_distance_before_km
+ distance_km
+ deadhead_distance_after_km
```

#### 6.3 走行中は充電しない
初期実装では、走行時刻中はその車両の充電電力を 0 とすること。

#### 6.4 待機時間にのみ充電可能
EV は、次の条件をすべて満たす場合のみ充電可能とする。
- その時間スロットで trip を担当していない
- 充電拠点にいる
- 充電器上限を超えない
- 車両の最大充電電力を超えない
- SOC 上限を超えない

---

### 7. EV のエネルギー消費計算
最初は過度に複雑にせず、次の式を基本とすること。

```text
trip_energy_kWh
= effective_trip_distance_km
  * energy_consumption_kWh_per_km_effective
```

ここで、

```text
energy_consumption_kWh_per_km_effective
= energy_consumption_kWh_per_km_base
  * alpha_load
  * alpha_speed
  * alpha_gradient
  * alpha_hvac
```

初期段階では、補正係数はすべて 1.0 でもよい。  
ただし将来拡張のために、係数を入力可能な形にしておくこと。

推奨:
- alpha_load: 乗車率補正
- alpha_speed: 平均速度補正
- alpha_gradient: 勾配補正
- alpha_hvac: 空調補正

#### 7.1 SOC 更新
時刻スロット単位で以下を守ること。

```text
soc[v, t+1]
= soc[v, t]
+ (charging_power[v, t] * charging_efficiency * delta_t_hour) / usable_battery_capacity_kWh
- energy_used_running[v, t] / usable_battery_capacity_kWh
```

制約:
- min_soc <= soc[v, t] <= max_soc

---

### 8. エンジンバスの燃料消費計算
エンジンバスについては、まずは JH25 モード等から得た燃費値ベースで次を用いる。

```text
trip_fuel_L
= effective_trip_distance_km * diesel_consumption_L_per_km
```

または

```text
trip_fuel_L
= effective_trip_distance_km / fuel_economy_km_per_L
```

将来的には路線特性補正を付けてよい。

```text
diesel_consumption_L_per_km_effective
= diesel_consumption_L_per_km_base
  * beta_load
  * beta_speed
  * beta_gradient
  * beta_stopgo
```

---

### 9. 買電量の計算
各時刻 t において、買電量は少なくとも以下で求めること。

```text
net_grid_purchase_power[t]
= max(0, total_charging_power[t] - pv_power[t])
```

```text
net_grid_purchase_energy[t]
= net_grid_purchase_power[t] * delta_t_hour
```

ここで
- total_charging_power[t] = sum_v charging_power[v, t]
- pv_power[t] が未使用なら 0
- 放電や V2G は初期実装では扱わなくてよい

---

### 10. TOU料金の計算
TOU は時刻別単価を用い、次で計算する。

```text
electricity_cost_yen
= sum_t net_grid_purchase_energy[t] * tou_price_yen_per_kWh[t]
```

重要:
- 必ず **時刻別料金** を使うこと
- 1日単位でも月単位でもよいが、単価の適用時間帯がずれないようにすること

---

### 11. 需要料金・契約上限の計算
少なくとも以下の 2 通りのどちらかを選べるようにすること。

#### 11.1 契約電力固定 + 超過禁止
```text
total_charging_power[t] <= contract_power_limit_kW
```

この場合、契約上限を超える充電計画は不可とする。

#### 11.2 契約電力固定 + 超過ペナルティ
```text
contract_excess_kW[t]
= max(0, total_charging_power[t] - contract_power_limit_kW)
```

```text
contract_excess_cost_yen
= penalty_yen_per_kW * max_t contract_excess_kW[t]
```

#### 11.3 需要料金
月次近似として、ピーク需要を使って次を計算してよい。

```text
peak_demand_kW = max_t net_grid_purchase_power[t]
```

```text
demand_charge_yen
= peak_demand_kW * demand_charge_yen_per_kW_month
```

注意:
- 日シミュレーションしかしていない場合、月次費用をそのまま加えるか、日割換算するかを必ず明示すること
- 初期実装では `cost_time_basis = daily` または `monthly` をパラメータとして持つこと

---

### 12. 車両導入費の扱い
車両導入費は、そのまま一括計上してもよいが、運用コスト比較では大きすぎるため、原則として**年換算または日換算**できるようにすること。

推奨:
- purchase_cost_yen
- lifetime_year
- operation_days_per_year
- residual_value_yen (任意)
- discount_rate (任意)

最小実装では次でよい。

```text
daily_vehicle_capex_yen
= (purchase_cost_yen - residual_value_yen)
  / (lifetime_year * operation_days_per_year)
```

総導入費:

```text
vehicle_capex_cost_yen
= sum_v daily_vehicle_capex_yen
```

もし導入台数自体を最適化するなら、車両採用 binary と掛け合わせること。

---

### 13. 総コスト関数
最低限、総コストは次で計算すること。

```text
total_cost_yen
= vehicle_capex_cost_yen
+ fuel_cost_yen
+ electricity_cost_yen
+ demand_charge_yen
+ contract_excess_cost_yen
```

ここで

```text
fuel_cost_yen
= diesel_price_yen_per_L * total_fuel_consumption_L
```

```text
total_fuel_consumption_L
= sum_v sum_t fuel_used_running[v, t]
```

必要なら
- 固定基本料金
- 充電器設置費
- 保守費
- バッテリ劣化費
も後から追加可能な構造にしておくこと。

---

### 14. エージェントが作るべき最小出力
このエージェントは、少なくとも次の出力を返すこと。

#### 14.1 時系列出力
- vehicle_operation_timeline.csv
- vehicle_soc_timeline.csv
- charging_power_timeline.csv
- grid_power_timeline.csv

#### 14.2 集計出力
- cost_breakdown.json
- trip_assignment.json
- fleet_summary.json

#### 14.3 人間向け確認
- simulation_summary.md

---

### 15. `cost_breakdown.json` の推奨形式
```json
{
  "time_basis": "daily",
  "vehicle_capex_cost_yen": 125000,
  "fuel_cost_yen": 84230,
  "electricity_cost_yen": 56310,
  "demand_charge_yen": 42000,
  "contract_excess_cost_yen": 0,
  "total_cost_yen": 307540,
  "peak_demand_kW": 210,
  "total_grid_purchase_kWh": 735.2,
  "total_fuel_consumption_L": 269.1
}
```

---

### 16. 代表的な計算フロー
エージェントは基本的に以下の順で処理すること。

1. 車両ライブラリ読み込み
2. 路線プロフィール読み込み
3. 時刻スロット展開
4. trip を車両へ割当
5. EV の SOC 推移計算
6. エンジンバスの燃料消費計算
7. 時刻別充電電力集計
8. 買電量・ピーク需要計算
9. TOU料金計算
10. 需要料金 / 契約超過コスト計算
11. 車両導入費計算
12. 総コスト集計
13. サマリ出力

---

### 17. 最初に実装すべき簡易割当ロジック
厳密最適化の前に、まずは次の簡易ルールでもよい。

#### 17.1 trip 割当
- 先着順で未割当 trip を処理
- 条件を満たす車両の中から
  - EV を優先する
  - 無理ならエンジンバス
  - さらに同種内では追加コストが最小のもの
を選ぶ

#### 17.2 EV の追加コスト判定
EV 候補については、その trip を担当した場合の
- 必要消費電力量
- 充電必要量
- TOU 時間帯への影響
- ピーク需要悪化
を見て近似的な増分コストを評価してよい

#### 17.3 エンジンバスの追加コスト判定
エンジンバス候補については
- trip_fuel_L * diesel_price_yen_per_L
を基本増分コストとしてよい

---

### 18. 品質チェック
出力前に必ず次を確認すること。

#### 18.1 運行整合
- 同一車両が同時刻に複数便を担当していない
- trip の開始終了時刻がタイムラインに反映されている
- 走行時に充電していない

#### 18.2 EV 整合
- SOC が min_soc を下回っていない
- SOC が max_soc を超えていない
- 充電電力が車両上限と設備上限を超えていない

#### 18.3 コスト整合
- fuel_cost_yen >= 0
- electricity_cost_yen >= 0
- demand_charge_yen >= 0
- total_cost_yen
  = vehicle_capex_cost_yen
  + fuel_cost_yen
  + electricity_cost_yen
  + demand_charge_yen
  + contract_excess_cost_yen
  が成立している

#### 18.4 路線整合
- すべての trip に対し effective_trip_distance_km が正
- deadhead を含めた距離で消費計算している
- route_profile 未設定便があれば warning を出す

---

### 19. してはいけないこと
- 路線プロフィールを無視して「1日総走行距離だけ」で計算しないこと
- TOU を平均単価で潰してしまわないこと
- 契約上限とピーク需要を同一視して雑に扱わないこと
- EV の SOC 制約を無視して EV 便担当を決めないこと
- エンジンバスの燃料費を固定費扱いしないこと
- 車両導入費を時間基準不明のまま足し込まないこと

---

### 20. 実装時の推奨データ構造
```json
{
  "simulation_settings": {
    "delta_t_min": 30,
    "time_basis": "daily",
    "contract_mode": "hard_limit"
  },
  "fleet": [],
  "route_profile": [],
  "tou_tariff": [],
  "results": {
    "timeline": {},
    "cost_breakdown": {}
  }
}
```

---

### 21. まず作るべき最小完成版
初期完成版では、以下ができればよい。

#### Phase 1
- 路線プロフィールを読み、各 trip を車両に割り当てる
- EV の SOC とエンジンバスの燃料消費を計算する
- TOU買電費と燃料費を計算する
- 車両導入費を日割で足す
- 総コストを出す

#### Phase 2
- 契約上限と需要料金を入れる
- ピーク回避のための充電シフトを入れる
- EV / エンジン混成最小コスト配車を改善する

#### Phase 3
- MILP / MINLP / ALNS 等へ接続
- バッテリ劣化費、充電器設置費、PV、自家消費、V2G を追加
- 季節別 / 平日休日別 / 月次契約最適化へ拡張する

---

### 22. 最終目的
このエージェントの最終目的は、**設定した路線プロフィールどおりに実際に車両が走った結果として**、

- EV バスの消費電力量
- エンジンバスの燃料消費量
- TOU 買電費
- 契約上限制約
- 需要料金
- 車両導入費

を整合的に算出し、**総コスト最小** の比較・評価・最適化へ接続できる基盤を作ることである。

そのため、実装では常に
**「運行が先、コストはその運行から自然に出る」**
という原則を守ること。
