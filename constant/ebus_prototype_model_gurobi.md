# 電気バス運行・充電スケジューリング最適化 - Gurobi / Python 実装直結版

## 0. このファイルの目的

このファイルは、修士論文で定式化した内容を、そのまま **Python + Gurobi** に落とし込みやすい形で整理した試作モデル仕様書である。

想定する用途は以下の 3 つである。

- 修論本文用のモデル整理
- 試作ケーススタディの構築
- Python / Gurobi コードへの直接実装

本モデルは、まず **MILP で解きやすい基本形** を優先し、複雑な非線形要素や高度な不確実性は後段の拡張項目として扱う。

---

## 1. 研究対象

本研究では、事業者が自前で PV を保有する条件下で、電気バスの

- 便割当
- 充電スケジュール
- PV 活用
- 系統電力購入

を統合的に最適化する。

目的は、**運行成立性を満たしながら総電力コストを最小化すること**である。

---

## 2. モデルの基本方針

### 2.1 最初に解く問題

まずは以下の基本問題を扱う。

1. 各便をどのバスが担当するか決める
2. 各時間帯にどのバスが充電するか決める
3. 各時間帯の充電電力量を決める
4. PV 電力と系統買電の分担を決める

### 2.2 最初は入れないもの

試作段階では、以下は一旦除外または簡略化する。

- バッテリ劣化の厳密モデル
- V2G
- 交通渋滞の確率変動
- リアルタイム再スケジューリング
- 非線形充電特性
- 需要不確実性の確率モデル

### 2.3 なぜこの切り分けにするか

最初から全部入れると、

- 定式化ミス
- データ不整合
- 実装ミス
- 計算時間の悪化

の切り分けが難しくなるためである。

---

## 3. 実装前提

### 3.1 時間の離散化

時間は離散時間で扱う。たとえば 30 分刻みまたは 15 分刻みとする。

- `T = {0, 1, ..., T_max-1}`
- 各時間区間の長さを `delta_h [h]` とする

### 3.2 エネルギーの単位

- 電力量: kWh
- 電力: kW
- 時間: h
- SOC: kWh ベースで持つ

実装時には SOC を割合ではなく **kWh** で持つ方が分かりやすい。

---

## 4. 集合と添字

### 4.1 集合

- `B`: バス集合
- `R`: 便集合
- `T`: 時間区間集合
- `C`: 充電拠点集合
- `S`: 充電器種別集合

### 4.2 添字

- `b in B`: バス
- `r in R`: 便
- `t in T`: 時間
- `c in C`: 拠点
- `s in S`: 充電器種別

---

## 5. パラメータ定義

以下は Python 実装を意識したキー名で示す。

### 5.1 バス関連

- `cap_kwh[b]`
  - バス `b` のバッテリ容量 [kWh]

- `soc_init_kwh[b]`
  - 初期 SOC [kWh]

- `soc_min_kwh[b]`
  - 下限 SOC [kWh]

- `soc_max_kwh[b]`
  - 上限 SOC [kWh]

### 5.2 便関連

- `trip_start[r]`
  - 便 `r` の開始時刻インデックス

- `trip_end[r]`
  - 便 `r` の終了時刻インデックス

- `trip_energy_kwh[r]`
  - 便 `r` を走るために必要な電力量 [kWh]

- `trip_start_node[r]`
  - 便 `r` の出発地点

- `trip_end_node[r]`
  - 便 `r` の到着地点

### 5.3 時間展開済み補助パラメータ

- `trip_active[r][t]`
  - 便 `r` が時刻 `t` に運行中なら 1

- `trip_energy_at_time[r][t]`
  - 便 `r` の時刻 `t` における消費電力量 [kWh]

### 5.4 充電関連

- `charger_power_kw[c][s]`
  - 拠点 `c` の種別 `s` の充電電力 [kW]

- `charger_count[c][s]`
  - 同時利用可能台数

- `charge_efficiency`
  - 充電効率

### 5.5 位置整合関連

- `bus_can_charge_at[b][c][t]`
  - バス `b` が時刻 `t` に拠点 `c` で充電可能なら 1

### 5.6 電力関連

- `pv_gen_kwh[t]`
  - 時刻 `t` の PV 利用可能電力量 [kWh]

- `grid_price_yen_per_kwh[t]`
  - 時刻 `t` の系統電力単価 [円/kWh]

- `delta_h`
  - 時間刻み [h]

---

## 6. 決定変数

### 6.1 便割当変数

- `x[b,r] in {0,1}`
  - バス `b` が便 `r` を担当するなら 1

### 6.2 充電実行変数

- `y[b,c,s,t] in {0,1}`
  - バス `b` が時刻 `t` に拠点 `c` の種別 `s` で充電するなら 1

### 6.3 充電量変数

- `e[b,c,s,t] >= 0`
  - 時刻 `t` にバス `b` が拠点 `c`・種別 `s` で受ける充電電力量 [kWh]

### 6.4 SOC 変数

- `soc[b,t]`
  - 時刻 `t` のバス `b` の SOC [kWh]

### 6.5 PV 使用量

- `pv_use[t] >= 0`
  - 時刻 `t` に利用する PV 電力量 [kWh]

### 6.6 系統買電量

- `grid_buy[t] >= 0`
  - 時刻 `t` に系統から購入する電力量 [kWh]

---

## 7. 目的関数

### 7.1 基本形

総系統電力コストを最小化する。

```text
min sum_t grid_price_yen_per_kwh[t] * grid_buy[t]
```

### 7.2 拡張候補

必要なら以下を追加する。

- 充電器利用コスト
- バッテリ劣化コスト
- 充電回数ペナルティ
- 便未達成ペナルティ
- 需要ピーク抑制項

ただし試作モデルでは、まず **系統買電コスト最小化のみ** でよい。

---

## 8. 制約

## 8.1 各便は必ず 1 台に割り当てる

```text
sum_b x[b,r] = 1    for all r
```

### 実装メモ

```python
for r in R:
    m.addConstr(gp.quicksum(x[b,r] for b in B) == 1, name=f"assign_{r}")
```

---

## 8.2 同一バスの重複運行禁止

便 `r1` と `r2` の時間帯が重なる場合、同じバスには両方割り当てられない。

```text
x[b,r1] + x[b,r2] <= 1    for all b, for all overlapping (r1,r2)
```

### 実装メモ

- あらかじめ `overlap_pairs` を作っておく
- `overlap_pairs = [(r1, r2), ...]`

```python
for b in B:
    for r1, r2 in overlap_pairs:
        m.addConstr(x[b,r1] + x[b,r2] <= 1, name=f"overlap_{b}_{r1}_{r2}")
```

---

## 8.3 初期 SOC

```text
soc[b,0] = soc_init_kwh[b]    for all b
```

```python
for b in B:
    m.addConstr(soc[b,0] == soc_init_kwh[b], name=f"soc_init_{b}")
```

---

## 8.4 SOC 上下限

```text
soc_min_kwh[b] <= soc[b,t] <= soc_max_kwh[b]    for all b,t
```

```python
for b in B:
    for t in T:
        m.addConstr(soc[b,t] >= soc_min_kwh[b], name=f"soc_min_{b}_{t}")
        m.addConstr(soc[b,t] <= soc_max_kwh[b], name=f"soc_max_{b}_{t}")
```

---

## 8.5 SOC 推移

各時刻の SOC は、

- その時刻に担当した便の消費
- その時刻に行った充電

を反映して更新する。

### 8.5.1 時刻 `t` の走行消費量

バス `b` の時刻 `t` における消費量は、便割当変数を用いて

```text
drive_use[b,t] = sum_r trip_energy_at_time[r][t] * x[b,r]
```

と表せる。

### 8.5.2 SOC 推移式

```text
soc[b,t+1] = soc[b,t]
             - sum_r trip_energy_at_time[r][t] * x[b,r]
             + charge_efficiency * sum_c sum_s e[b,c,s,t]
```

```python
for b in B:
    for t in T[:-1]:
        drive_use = gp.quicksum(trip_energy_at_time[r][t] * x[b,r] for r in R)
        charge_in = gp.quicksum(e[b,c,s,t] for c in C for s in S)
        m.addConstr(
            soc[b,t+1] == soc[b,t] - drive_use + charge_efficiency * charge_in,
            name=f"soc_balance_{b}_{t}"
        )
```

---

## 8.6 充電量と充電実行の連動

充電を選んだときのみ、充電量が正になる。

```text
e[b,c,s,t] <= charger_power_kw[c][s] * delta_h * y[b,c,s,t]
```

```python
for b in B:
    for c in C:
        for s in S:
            for t in T:
                m.addConstr(
                    e[b,c,s,t] <= charger_power_kw[c][s] * delta_h * y[b,c,s,t],
                    name=f"charge_link_{b}_{c}_{s}_{t}"
                )
```

---

## 8.7 充電器の同時利用上限

```text
sum_b y[b,c,s,t] <= charger_count[c][s]    for all c,s,t
```

```python
for c in C:
    for s in S:
        for t in T:
            m.addConstr(
                gp.quicksum(y[b,c,s,t] for b in B) <= charger_count[c][s],
                name=f"charger_cap_{c}_{s}_{t}"
            )
```

---

## 8.8 バスは同時に複数箇所で充電できない

```text
sum_c sum_s y[b,c,s,t] <= 1    for all b,t
```

```python
for b in B:
    for t in T:
        m.addConstr(
            gp.quicksum(y[b,c,s,t] for c in C for s in S) <= 1,
            name=f"one_charge_place_{b}_{t}"
        )
```

---

## 8.9 運行中は充電できない

便 `r` が時刻 `t` に動いているかどうかを `trip_active[r][t]` で表すと、
バス `b` が時刻 `t` に運行中であるかは

```text
sum_r trip_active[r][t] * x[b,r]
```

で表現できる。

したがって、

```text
sum_r trip_active[r][t] * x[b,r] + sum_c sum_s y[b,c,s,t] <= 1
```

```python
for b in B:
    for t in T:
        running = gp.quicksum(trip_active[r][t] * x[b,r] for r in R)
        charging = gp.quicksum(y[b,c,s,t] for c in C for s in S)
        m.addConstr(running + charging <= 1, name=f"run_or_charge_{b}_{t}")
```

---

## 8.10 位置整合制約

その時刻にその拠点で充電可能なときだけ充電を許す。

```text
y[b,c,s,t] <= bus_can_charge_at[b][c][t]
```

```python
for b in B:
    for c in C:
        for s in S:
            for t in T:
                m.addConstr(
                    y[b,c,s,t] <= bus_can_charge_at[b][c][t],
                    name=f"location_feasible_{b}_{c}_{s}_{t}"
                )
```

---

## 8.11 PV 利用量上限

```text
0 <= pv_use[t] <= pv_gen_kwh[t]
```

```python
for t in T:
    m.addConstr(pv_use[t] >= 0, name=f"pv_nonneg_{t}")
    m.addConstr(pv_use[t] <= pv_gen_kwh[t], name=f"pv_cap_{t}")
```

---

## 8.12 電力収支

各時間帯の総充電量は、PV と系統買電でまかなう。

```text
sum_b sum_c sum_s e[b,c,s,t] = pv_use[t] + grid_buy[t]
```

```python
for t in T:
    total_charge = gp.quicksum(e[b,c,s,t] for b in B for c in C for s in S)
    m.addConstr(total_charge == pv_use[t] + grid_buy[t], name=f"power_balance_{t}")
```

---

## 8.13 系統買電量の非負制約

```text
grid_buy[t] >= 0
```

```python
for t in T:
    m.addConstr(grid_buy[t] >= 0, name=f"grid_nonneg_{t}")
```

---

## 9. Python / Gurobi 実装の流れ

## 9.1 推奨ファイル構成

```text
project/
  data/
    prototype_case.json
  src/
    build_sets.py
    build_params.py
    model_milp.py
    solve.py
    export_results.py
```

---

## 9.2 実装手順

### Step 1. JSON を読み込む

- バス情報
- 便情報
- 時間情報
- 充電器情報
- PV 情報
- 電力単価情報

を Python の dict / list として読み込む。

### Step 2. 補助データを作る

- `overlap_pairs`
- `trip_active[r][t]`
- `trip_energy_at_time[r][t]`
- `bus_can_charge_at[b][c][t]`

を生成する。

### Step 3. Gurobi モデルを生成する

- `Model()` を作る
- 変数 `x, y, e, soc, pv_use, grid_buy` を生成する
- 制約を順に追加する
- 目的関数を設定する

### Step 4. 求解する

- `m.optimize()`

### Step 5. 結果を出力する

- 便割当表
- SOC 推移
- 充電時刻表
- PV 使用量
- 買電量
- 総コスト

を CSV または Excel に出力する。

---

## 10. 試作ケーススタディの最小構成

最初は以下程度の小規模データで十分である。

### 10.1 ケース例

- バス: 3 台
- 便: 6 - 10 本
- 時間刻み: 30 分
- 時間帯: 6:00 - 22:00
- 充電拠点: 2 箇所
- 充電器種別: 普通 / 急速

### 10.2 最初に確認すること

1. すべての便が割り当たるか
2. SOC が下限を割らないか
3. 充電器口数制約を守れているか
4. 昼間の PV が優先的に使われるか
5. 高単価時間帯の買電が減るか

---

## 11. 推奨する試作の順番

## Phase 1. 運行割当だけ

- `x[b,r]`
- 各便 1 台
- 重複便禁止

## Phase 2. SOC を追加

- `soc[b,t]`
- `trip_energy_at_time[r][t]`
- SOC 推移

## Phase 3. 充電を追加

- `y[b,c,s,t]`
- `e[b,c,s,t]`
- 充電器容量

## Phase 4. PV と電力料金を追加

- `pv_use[t]`
- `grid_buy[t]`
- コスト最小化

この順番で進めることで、問題の切り分けがしやすい。

---

## 12. 今後の拡張候補

以下は試作モデルが動いた後で追加するとよい。

### 12.1 充電場所選択の強化

- 終点でのみ機会充電を許す
- デポ充電と路線途中充電を分ける

### 12.2 料金制度の高度化

- デマンドチャージ
- TOU 料金
- 再エネ自家消費率最大化

### 12.3 不確実性考慮

- PV 予測誤差
- 遅延
- 消費電力量変動

### 12.4 解法面の拡張

- MILP で小規模ケース
- ALNS で大規模ケース
- MILP 解との比較

---

## 13. 修論本文に使えるまとめ文

本研究では、電気バスの便割当、充電スケジュール、および PV を考慮した電力調達を統合的に扱う混合整数線形計画モデルを構築する。モデルでは、各便を 1 台のバスに割り当てる制約、同一車両の重複運行を禁止する制約、各車両の SOC 推移制約、充電設備容量制約、および電力収支制約を導入する。さらに、時刻別の PV 発電可能量と系統電力単価を考慮することで、運行成立性を満たしながら総買電コストを最小化する。この基本モデルをもとに、試作ケーススタディを通じて定式化と実装の妥当性を確認し、その後に大規模化・高精度化へ拡張する。
