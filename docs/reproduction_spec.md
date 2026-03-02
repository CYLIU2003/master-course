# 先行研究再現仕様書

## 本文書の目的

本文書は、修論研究基盤として再現する先行研究2本について、
入力・決定変数・制約・目的関数・再現しない要素を明確に定義する。

---

## 再現A: mode_A_journey_charge

### 対応論文

**He et al. (2023)** — "Optimal charging scheduling of electric buses with energy consumption uncertainty"
*Transportation Research Part D*, Vol. 115 (TRD 115)
仕様書内番号: **No42**

### モデル概要

路線バス事業者が、固定された行路（vehicle-trip assignment）のもとで、
**各運行（journey）後に充電するかどうか、いつ・どの充電器で・いくら充電するか**を
TOU電力料金を考慮して最適化する。

### 入力（外生値）

| 項目 | 説明 | 既存データ対応 |
|------|------|----------------|
| 車両集合 K_BEV | BEVバスのリスト（容量・SOC初期値・SOC上下限・充電出力上限） | `vehicles.csv` |
| タスク集合 R | 固定された便リスト（出発・到着時刻、消費電力量） | `tasks.csv` |
| 車両-タスク割当 | **外部入力**として固定（greedy等で事前決定） | `fixed_assignment` dict |
| 充電器集合 C | 充電器のリスト（出力・効率・台数=1台/充電器ID） | `chargers.csv` |
| 拠点集合 | 充電器が設置されている拠点（系統接続容量） | `sites.csv` |
| TOU電力料金 | 時刻別の系統買電単価 [円/kWh] | `electricity_price.csv` |
| 時間刻み | 15分刻み、64スロット（05:00-21:00） | `experiment_config.json` |

### 決定変数

| 変数 | 型 | 説明 |
|------|-----|------|
| `z_charge[k, c, t]` | Binary | BEV k が時刻 t に充電器 c で充電するか |
| `p_charge[k, c, t]` | Continuous >= 0 | 充電電力 [kW] |
| `soc[k, t]` | Continuous | 時刻 t の BEV k の SOC [kWh] |
| `p_grid_import[site, t]` | Continuous >= 0 | 拠点の系統買電電力 [kW] |

**注意**: `x_assign[k, r]`（割当変数）は存在するが、外部値で固定される。

### 目的関数

$$\min \sum_{t \in T} \sum_{i \in Sites} \text{grid\_price}(i, t) \times p\_grid\_import(i, t) \times \Delta t$$

系統電力購入コストの最小化。（PV・デマンド料金・燃料費は含まない）

### 制約

| # | 制約 | 数式概要 | 有効 |
|---|------|----------|------|
| 1 | SOC初期条件 | `soc[k,0] = soc_init[k]` | Yes |
| 2 | SOC推移 | `soc[k,t+1] = soc[k,t] - consumption[k,t] + eta * p_charge[k,c,t] * dt` | Yes |
| 3 | SOC下限 | `soc[k,t] >= soc_min[k]` | Yes |
| 4 | SOC上限 | `soc[k,t] <= soc_max[k]` | Yes |
| 5 | 充電出力上限 | `p_charge[k,c,t] <= P_max[c] * z_charge[k,c,t]` | Yes |
| 6 | 同時充電台数 | 各充電器は各時刻に最大1台 | Yes |
| 7 | 運行中充電禁止 | 車両が走行中のスロットでは充電不可 | Yes |
| 8 | 単一充電器制約 | 各車両は各時刻に最大1基の充電器を使用 | Yes |
| 9 | 拠点電力収支 | `grid_import = sum(charging) + base_load` | Yes |
| 10 | 系統容量上限 | `grid_import[site,t] <= grid_limit[site]` | Yes |

### 再現しない要素

- **エネルギー消費の不確実性** — 論文はrobust optimization的手法を含むが、ここではdeterministicのみ
- **非線形充電カーブ** — 線形近似のまま
- **PV** — mode_A では無効
- **デマンド料金** — mode_A では無効
- **V2G / 電池劣化** — mode_A では無効

### 検証基準（再現成功の判定）

構造的挙動の再現を確認する（数値の完全一致は不要）：

1. **TOU応答**: 電力単価が安い時間帯に充電が集中するか
2. **充電器競合**: 充電器が2台しかないとき、3台目のBEVは待つか
3. **SOCマージン**: SOC下限に近づくタスクの直後に充電が入るか
4. **コスト構造**: 充電器台数を減らすとコストが上がるか（代替充電タイミングの悪化）
5. **系統容量制約**: grid_limit を絞ると、充電が分散されるか

---

## 再現B: mode_B_resource_assignment

### 対応論文

**Chen et al. (2023)** — "Integrated optimization of electric bus scheduling and charging"
*Transportation Research Part D*, Vol. 118 (TRD 118)
仕様書内番号: **No47**

### モデル概要

路線バス事業者が、**どのバスにどの便を割り当てるか**と
**充電スケジューリング**を**同時に最適化**する。
充電器容量制約（同時充電台数上限）が assignment と charging の相互作用を生む。

### 入力（外生値）

| 項目 | 説明 | 既存データ対応 |
|------|------|----------------|
| 車両集合 K | BEV + ICE（混成フリート） | `vehicles.csv` |
| タスク集合 R | 便リスト（出発・到着時刻、消費電力量/燃料、出発地・目的地） | `tasks.csv` |
| 走行接続 | タスク間の接続可否・deadhead距離・エネルギー | `travel_connection.csv` |
| 充電器集合 C | 充電器のリスト | `chargers.csv` |
| 拠点集合 | 充電器設置拠点 | `sites.csv` |
| TOU電力料金 | 時刻別の系統買電単価 | `electricity_price.csv` |
| 車両-タスク互換性 | どの車両がどのタスクを実行可能か | `compatibility_vehicle_task.csv` |
| 車両-充電器互換性 | どの車両がどの充電器を使えるか | `compatibility_vehicle_charger.csv` |

### 決定変数

| 変数 | 型 | 説明 |
|------|-----|------|
| `x_assign[k, r]` | Binary | 車両 k がタスク r を担当するか |
| `u_vehicle[k]` | Binary | 車両 k が使用されるか |
| `z_charge[k, c, t]` | Binary | BEV k が時刻 t に充電器 c で充電するか |
| `p_charge[k, c, t]` | Continuous >= 0 | 充電電力 [kW] |
| `soc[k, t]` | Continuous | BEV k の SOC [kWh] |
| `p_grid_import[site, t]` | Continuous >= 0 | 系統買電電力 [kW] |
| `peak_demand[site]` | Continuous >= 0 | ピーク電力 [kW]（KPI用、目的関数外） |

### 目的関数

$$\min \sum_k w_1 \cdot \text{fixed\_cost}[k] \cdot u[k] + \sum_{t,i} w_2 \cdot \text{price}(i,t) \cdot p\_grid(i,t) \cdot \Delta t + \sum_r w_8 \cdot \text{penalty} \cdot \text{slack}[r]$$

車両固定費 + 電力料金 + 未担当ペナルティの加重和。

### 制約

mode_A の制約（#1-#10）に加えて：

| # | 制約 | 数式概要 | 有効 |
|---|------|----------|------|
| 11 | タスク担当（一意割当） | 各必須タスクは1台以上（正確には1台）に割り当て | Yes |
| 12 | 重複タスク排他 | 時間が重なるタスクを同一車両に割り当てない | Yes |
| 13 | 車両使用連動 | `x[k,r] <= u[k]` | Yes |
| 14 | 車両-タスク互換性 | 互換性がない (k,r) ペアは `x[k,r] = 0` | Yes |
| 15 | 最大運行時間 | 各車両の総運行時間が上限以下 | Yes |
| 16 | 最大走行距離 | 各車両の総走行距離が上限以下 | Yes |

### 再現しない要素

- **非線形充電カーブ** — 線形近似
- **PV** — mode_B では無効
- **デマンド料金** — mode_B では無効（peak_demand は KPI としては計算するが制約・目的関数外）
- **V2G / 電池劣化** — mode_B では無効
- **不確実性 / シナリオ評価** — deterministic のみ

### 検証基準（再現成功の判定）

1. **assignment-charging相互作用**: 充電器台数を減らすと、assignment が変わるか（充電しやすい時間帯にタスクが空く車両を選ぶ傾向）
2. **fleet規模**: 車両台数を増やすと固定費は増えるがエネルギーコストは下がるか
3. **タスクカバレッジ**: 車両が足りない状況で、ペナルティ付きの未担当タスクが出るか
4. **ICE活用**: BEVでカバーしきれないとき、ICE車両がfuel costを払って補完するか
5. **deadheadコスト**: 接続の悪いassignmentだとdeadheadが増え、SOC消費が上がるか

---

## 共通: KPI出力仕様

両modeで、以下のKPIを**毎回同じ形式で出力**する。

| # | KPI | 単位 | 説明 |
|---|-----|------|------|
| 1 | `objective_value` | 円 | MILP目的関数値 |
| 2 | `total_energy_cost` | 円 | 系統買電コスト |
| 3 | `total_demand_charge` | 円 | デマンド料金（mode_Aでは0） |
| 4 | `total_fuel_cost` | 円 | ICE燃料費（mode_Aでは0） |
| 5 | `vehicle_fixed_cost` | 円 | 車両固定費合計 |
| 6 | `unmet_trips` | 件 | 未担当タスク数 |
| 7 | `soc_min_margin_kwh` | kWh | 最低SOCマージン（= min_soc - soc_min_limit） |
| 8 | `charger_utilization` | % | 充電器稼働率（平均） |
| 9 | `peak_grid_power_kw` | kW | ピーク系統受電電力 |
| 10 | `solve_time_sec` | 秒 | MILP求解時間 |

---

## 実験ケース構造

```
data/cases/
  mode_A_case01/          # mode_A 最小再現ケース
    vehicles.csv          # BEV 3台
    tasks.csv             # 6便（固定割当用）
    chargers.csv          # 2基
    sites.csv             # 1拠点（depot_A）
    electricity_price.csv # TOU 2区分
    pv_profile.csv        # 全0（PV無効）
    travel_connection.csv # 接続情報
    compatibility_vehicle_task.csv
    compatibility_vehicle_charger.csv
    fixed_assignment.json # 車両→タスクの固定割当

  mode_B_case01/          # mode_B 最小再現ケース
    vehicles.csv          # BEV 3台 + ICE 1台
    tasks.csv             # 8便（割当は最適化対象）
    chargers.csv          # 2基
    sites.csv             # 2拠点
    electricity_price.csv # TOU 2区分
    pv_profile.csv        # 全0
    travel_connection.csv # 接続情報
    compatibility_vehicle_task.csv
    compatibility_vehicle_charger.csv

config/cases/
  mode_A_case01.json      # mode_A実験設定
  mode_B_case01.json      # mode_B実験設定
```

---

## 実験の実行手順

```bash
# mode_A: journey後充電の最適化
python run_case.py --case mode_A_case01

# mode_B: vehicle-trip assignment + charging
python run_case.py --case mode_B_case01

# 結果比較
python run_case.py --compare mode_A_case01 mode_B_case01
```

出力先: `outputs/cases/{case_name}/{timestamp}/`
