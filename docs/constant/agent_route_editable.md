# agent.md - route editable 対応版 実装指示書
## 修論用 電気バス・混成バス研究環境のための Agent 指示

## ステータス
- 分類: アーカイブ候補
- 用途: route editable 拡張の観点を確認するための差分資料
- 備考: 基本参照は `agent.md`、拡張論点の確認時のみ参照

## 0. この版の追加使命
既存の agent.md に加え、今回の版では **路線データを編集可能にすること** を中核要件とする。

理由:
- 電費 [kWh/km] と燃費 [L/km] を route 条件に応じて変化させたい
- 距離・勾配・混雑・停車回数・空調負荷が運行コストと feasibility に与える影響を評価したい
- 先行研究の route length sensitivity や energy uncertainty の再現をしたい
- 同一路線条件下で BEV と ICE/HEV の比較をしたい

**あなたは、固定 trip 入力だけで終わる最適化コードを書いてはいけない。**
必ず、route-detail layer から generated trip を作れる構造にすること。

---

## 1. Agent が理解すべき全体像

### 1.1 二層構造
以下の二層を分離して実装する。

#### 層A: route-detail layer
対象:
- routes
- terminals
- stops
- segments
- route variants
- timetable patterns
- service calendar
- weather / traffic / passenger load profiles

役割:
- 路線やダイヤを研究者が編集する場所
- trip の距離・所要時間・電費・燃費の元データを作る

#### 層B: trip abstraction layer
対象:
- generated trips
- deadhead arcs
- vehicle availability
- charger capacity
- tariff

役割:
- 最適化モデルが直接使う入力
- vehicle assignment, charging schedule, infrastructure usage の評価対象

### 1.2 実装ルール
route-detail を編集したとき、
1. generated trip を再生成
2. deadhead arc を再生成
3. energy / fuel estimate を再計算
4. optimization を再実行
の順に自然につながるようにする。

---

## 2. 最優先で作るべきモジュール

### 2.1 `src/schemas/route_entities.py`
最低限のモデル:
- Route
- Terminal
- Stop
- Segment
- RouteVariant
- TimetablePattern
- ServiceCalendarRow

条件:
- pydantic または dataclass
- 単位コメントを記述
- ID と参照整合性が分かるフィールド名を使う

### 2.2 `src/preprocess/trip_generator.py`
必須関数:
- `generate_departure_times()`
- `generate_trip_from_variant()`
- `generate_all_trips()`

要求:
- route variant の segment 列から trip を構成
- total distance, runtime, terminals を集計
- service day type ごとに生成可能
- generated_trips.csv を出力可能

### 2.3 `src/preprocess/energy_model.py`
必須関数:
- `estimate_trip_energy_bev()`
- `estimate_segment_energy_bev()`
- `decompose_energy_components()`

要求:
- Level 0, Level 1, Level 2 を切替可能
- Level 1 は route-factor linear
- Level 2 は segment aggregation
- contribution breakdown を返せること
  - distance
  - grade
  - stop/start
  - traffic
  - HVAC
  - load

### 2.4 `src/preprocess/fuel_model.py`
必須関数:
- `estimate_trip_fuel_ice()`
- `estimate_trip_fuel_hev()`

要求:
- BEV と同じ route 入力から計算
- 比較しやすいよう `L/trip`, `L/km`, `JPY/trip` に変換可能

### 2.5 `src/preprocess/deadhead_builder.py`
必須関数:
- `build_deadhead_arcs()`
- `build_can_follow_matrix()`

要求:
- terminal 間 deadhead を考慮
- turnaround buffer を考慮
- feasible / infeasible 理由を記録

---

## 3. Agent が守るべき設計原則

### 3.1 route editable を主設計にする
簡易再現モードのために fixed trip 入力は残してよい。
ただし主設計は route editable にすること。

### 3.2 powertrain 比較を最初から可能にする
vehicle type に `powertrain` を持たせ、
- BEV
- ICE
- HEV
- PHEV
を区別可能にすること。

同一 GeneratedTrip に対して
- `estimated_energy_kwh_bev`
- `estimated_fuel_l_ice`
の両方を持てる設計にする。

### 3.3 最適化前の derived data を明確化する
次は derived data として別ファイルに出力する。
- generated_trips.csv
- deadhead_arcs.csv
- trip_energy_estimates.csv
- trip_fuel_estimates.csv

これにより、研究者が「路線を変えた結果どうなったか」を途中で確認できる。

### 3.4 explanation-first
最適化だけ通ればよい設計にしてはいけない。
各 trip の energy/fuel が、何によって決まったか説明可能にすること。

必ず component breakdown を保持する。
例:
- base distance energy
- grade penalty
- stop/start penalty
- congestion penalty
- HVAC
- passenger load penalty

---

## 4. 先行研究再現に向けた mode 設計

### 4.1 `mode_simple_reproduction`
- 外生 trip 入力を使う
- 論文表の再現に使う
- 最適化部分の検証を早く進める

### 4.2 `mode_route_sensitivity`
- route length multiplier を使う
- Chen et al. 系の sensitivity に対応

### 4.3 `mode_uncertainty_eval`
- travel time, energy consumption の scenario を生成
- robustness 指標を出す

### 4.4 `mode_thesis_route_editable`
- route/segment 編集
- trip 自動生成
- BEV/ICE 比較
- charging schedule
- tariff
- PV
を統合する

---

## 5. Agent が実装する CLI / pipeline
以下のような流れを作ること。

```bash
python -m src.pipeline.build_inputs --config config/experiment_config.json
python -m src.pipeline.solve --config config/experiment_config.json
python -m src.pipeline.simulate --config config/experiment_config.json
python -m src.pipeline.report --config config/experiment_config.json
```

### build_inputs の責務
- route master を読む
- timetable を展開する
- trip を生成する
- energy/fuel を推定する
- deadhead arcs を作る
- derived データを書き出す

### solve の責務
- mode に応じた最適化モデルを構築
- Gurobi または ALNS を実行
- raw solution を保存

### simulate の責務
- solution を時系列で再評価
- SOC, charger occupancy, depot demand, fuel consumption を再計算
- infeasible の理由を出す

### report の責務
- KPI 表
- powertrain 比較
- route sensitivity 比較
- scenario robustness 比較
を出力する

---

## 6. テストケースの必須要件

### Case 1: toy_single_route
- 1路線
- 2 terminal
- 10-20 trip
- 1 charger site
- fixed energy
- baseline 検証用

### Case 2: toy_route_editable
- 1路線
- segment 入力あり
- grade / congestion を変更可能
- generated trip を作る
- energy/fuel が変わることを確認

### Case 3: toy_mixed_fleet
- BEV + ICE
- 同一路線で比較
- 電費と燃費の出力を確認

### Case 4: route_length_sensitivity
- route distance を 0.9x, 1.0x, 1.1x, 1.2x
- resource assignment と cost がどう変わるか確認

### Case 5: uncertainty_case
- travel time / energy の scenario を複数生成
- deterministic plan の robustness を評価

---

## 7. 実装禁止事項
- trip 消費をすべて手入力前提に固定すること
- BEV と ICE の比較で route 条件を別入力にしてしまうこと
- route 編集結果が optimization に反映されない設計にすること
- energy model の計算根拠が見えないブラックボックスにすること
- mode ごとの条件分岐をコード全体に散らばらせること

---

## 8. この研究で最終的に欲しい状態
最終的に研究者は次のような操作ができる必要がある。

1. `segments.csv` の距離や勾配を編集する
2. `timetable_patterns.csv` の headway を編集する
3. `weather_timeseries.csv` の温度や空調条件を変える
4. build_inputs を実行する
5. trip の電費・燃費が再計算される
6. vehicle assignment と charging schedule を解く
7. BEV 案と ICE 混成案を比較する
8. route length sensitivity や robustness を見る

この一連の流れができて初めて、修論で使える「研究環境」と呼べる。

---

## 9. 参照文書
- `masters_thesis_simulation_spec_v3.md`
- 旧版 `masters_thesis_simulation_spec_v2.md`

Agent は、旧版より新しい v3 を優先して参照すること。
