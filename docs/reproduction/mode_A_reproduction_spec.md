# mode_A_journey_charge — 再現仕様書

**バージョン**: 1.0  
**作成日**: 2026-03-02  
**対象ケース**: `config/cases/mode_A_case01.json`

---

## 1. 再現対象

**He et al. (2023)** ("Electric bus scheduling and charging optimization," TRD 115) に代表される、  
「**旅程(journey)終了後の充電決定**」型モデルの再現。

> 先行研究の特徴: 車両-便の割当は所与(固定)とし、**充電時刻・電力量のみをMILPで最適化**する。  
> TOU電力料金最小化を目的とし、SOC下限制約・充電器競合制約を含む。

---

## 2. モデル入力

| 項目 | 値 |
|------|-----|
| 計画水平線 | 16時間 (05:00–21:00) |
| 時間スロット幅 | 15分 (64スロット) |
| 車両 | BEV 3台、固定割当 |
| タスク | 6便 |
| 充電器 | 2基 (デポ内) |
| 電力料金 | TOU (時間帯別単価) |
| PV | 無効 |
| V2G | 無効 |
| デマンド料金 | 無効 |
| 電池劣化費用 | 無効 |

データファイル: `data/cases/mode_A_case01/`

---

## 3. 決定変数 (充電のみ)

車両-便割当 `x_assign[k, r]` は **固定値として外部入力** (`fixed_assignment.json`)。  
MILP が最適化するのは:

- `z_charge[k, c, t]` — 充電器利用バイナリ (0/1)
- `p_charge[k, c, t]` — 充電電力 [kW]
- `soc[k, t]` — SOC推移 [kWh]
- `p_grid_import[i, t]` — 系統受電量 [kW]

---

## 4. 制約

| 制約カテゴリ | 内容 |
|------------|------|
| SOC下限 | `soc[k,t] >= soc_min[k]` (全スロット) |
| SOC上限 | `soc[k,t] <= soc_max[k]` |
| SOC初期値 | `soc[k,0] = soc_init[k]` |
| SOCダイナミクス | `soc[k,t+1] = soc[k,t] - 消費 + 充電` |
| 充電器競合 | 各充電器は同時に1台のみ |
| 充電電力上限 | `p_charge[k,c,t] <= p_max[k,c]` |
| 系統受電上限 | `p_grid[i,t] <= grid_limit[i]` |
| タスク中充電禁止 | タスク実行中スロットは充電不可 |

---

## 5. 目的関数

```
minimize  Σ_{i,t} price[i,t] * p_grid[i,t] * Δt  +  Σ_k fixed_use_cost[k]
```

デマンド料金・燃料費・電池劣化費用の係数は 0 (無効)。

---

## 6. 再現結果 (mode_A_case01)

| KPI | 値 |
|-----|----|
| status | OPTIMAL |
| objective_value | 20,172 円 |
| total_energy_cost | 5,172 円 |
| total_demand_charge | 0 円 |
| vehicle_fixed_cost | 15,000 円 |
| unmet_trips | 0 |
| soc_min_margin_kwh | 65.0 kWh |
| charger_utilization | 46.9% |
| peak_grid_power_kw | 55.0 kW |
| solve_time_sec | 0.039 秒 |

実行コマンド:
```
python run_case.py --case config/cases/mode_A_case01.json
```

---

## 7. 先行研究との対応・相違点

### 再現している点
- TOU料金最小化の充電スケジューリング
- SOC下限/上限制約
- 充電器競合制約
- 固定割当前提 (assignment as input)

### 再現していない点 (本研究での拡張対象)
- 乗客需要の確率的変動 (先行研究は確定的)
- V2G / PV 連携
- デマンド料金
- 多デポ / 異種車両混在
- 車両-便割当の同時最適化 → **mode_B で対応**

---

## 8. 次ステップ

1. **mode_B_resource_assignment**: 車両-便割当と充電を同時最適化
2. **感度分析**: SOC下限・充電器台数・TOU料金単価の変化に対する最適コストの変化
3. **再現精度の定量評価**: 手計算可能なトイケース (`data/toy/mode_A_case01/`) で解の正しさを検証
