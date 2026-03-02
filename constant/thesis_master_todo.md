# 修論用 E-Bus Sim 開発 ToDo マスタ

## 0. 文書の目的
本書は、電気バス運行・充電スケジューリング最適化シミュレータを、
**先行研究再現 -> 基盤モデル確立 -> 修論独自拡張** の順で着実に開発するための実行計画書である。

本プロジェクトは、すでに以下の資産を持つ。
- Streamlit GUI の統合アプリ
- 路線管理・営業所管理・便チェーン管理の編集UI
- `src/` ベースの新アーキ構想
- `mode_A_journey_charge`, `mode_B_resource_assignment`, `thesis_mode` のモード設計

ただし、研究として最重要なのは、
**アプリ機能の多さではなく、先行研究を再現できる最小ケースが再現可能であること** である。

---

## 1. 研究開発の基本方針

### 1.1 守るべき順番
1. schema / loader / preprocess を固める
2. simulator を先に完成させる
3. mode_A を最初に完成させる
4. mode_B を小規模ケースで完成させる
5. route-editable 前処理を接続する
6. thesis_mode に独自性を順次追加する
7. GUI は研究ダッシュボードとして維持する

### 1.2 研究としての最低成功条件
- toy case で mode_A が再現できる
- toy case で mode_B が解ける
- optimizer の解を simulator で再評価できる
- route master を変えると generated trips と energy / fuel が変わる
- KPI が CSV / JSON / Markdown で出力できる
- 論文比較に使える結果表が作れる

### 1.3 2週間で狙う到達点
- `mode_A_journey_charge` の安定動作
- `mode_B_resource_assignment` の骨格完成 + 小規模動作
- route -> trip 前処理の接続
- GUI から src pipeline を呼び出せる状態
- 修論の中間報告に耐えるスクリーンショット・結果表の確保

---

# 2. Day 1-3

## Day 1 の目標
**再現Aの仕様固定と baseline 実験ケース確定**

### ToDo
- [ ] 再現対象Aを1本に固定する
  - 第一候補: He et al. 型の journey 後 charging decision モデル
  - 固定する内容:
    - [ ] 入力
    - [ ] 決定変数
    - [ ] 目的関数
    - [ ] 制約
    - [ ] 再現しない要素
- [ ] `docs/reproduction/mode_A_reproduction_spec.md` を作る
- [ ] `data/toy/mode_A_case01/` を作る
- [ ] 最低限必要な CSV を定義する
  - [ ] vehicles.csv
  - [ ] trips.csv
  - [ ] tariffs.csv
  - [ ] chargers.csv
  - [ ] fixed_journey_sequence.csv
- [ ] 手計算できる toy case を設計する
  - [ ] 1-2台
  - [ ] 5-8 journey
  - [ ] TOU 料金あり
  - [ ] 充電器台数制限あり

### 完了条件
- [ ] 再現Aの対象論文が決まっている
- [ ] toy case の入力一式が置かれている
- [ ] 再現仕様メモが1ページで読める

---

## Day 2 の目標
**simulator の最小版を完成させる**

### ToDo
- [ ] `src/simulate/schedule_simulator.py` を作る
- [ ] `simulate_schedule(schedule, inputs, config)` を実装
- [ ] `compute_soc_trace()` を実装
- [ ] `compute_site_power_trace()` を実装
- [ ] `compute_cost_breakdown()` を実装
- [ ] `check_schedule_feasibility()` を実装
- [ ] 返却オブジェクトを統一する
  - [ ] feasible
  - [ ] infeasible_reasons
  - [ ] soc_trace
  - [ ] charger_occupancy
  - [ ] site_power_trace
  - [ ] cost_breakdown
  - [ ] kpi_summary

### テスト
- [ ] SOC 下限違反を検出できる
- [ ] 同時充電台数超過を検出できる
- [ ] 料金変更でコストが変わる

### 完了条件
- [ ] 固定スケジュールを simulator に入れて結果が返る
- [ ] infeasible 理由が文字列で読める

---

## Day 3 の目標
**mode_A の MILP を完成させ、simulator と整合確認する**

### ToDo
- [ ] `src/model/mode_A_model.py` を作る
- [ ] journey 後の charge decision 変数を実装する
- [ ] objective = charging cost 最小化
- [ ] charger capacity 制約を実装
- [ ] SOC 下限制約を実装
- [ ] solver 実行結果を simulator に流す
- [ ] `results/mode_A_case01/` に出力する
  - [ ] result.json
  - [ ] kpi.csv
  - [ ] report.md

### 検証
- [ ] optimizer の SOC と simulator の SOC が一致する
- [ ] 料金時間帯を変えると charging timing が変わる
- [ ] charger 台数 1 -> 2 で feasible 性が変化するケースを確認

### 完了条件
- [ ] `python run_experiment.py --mode mode_A_journey_charge` が回る
- [ ] result を GUI なしでも確認できる

---

# 3. Day 4-7

## Day 4 の目標
**route-editable 前処理の骨格を接続する**

### ToDo
- [ ] `src/preprocess/route_builder.py` を整理
- [ ] `src/preprocess/trip_generator.py` を作成または整理
- [ ] `src/preprocess/deadhead_builder.py` を作成または整理
- [ ] route master から generated trips を作る流れを固定する
- [ ] 中間生成物の保存先を統一する
  - [ ] generated_trips.csv
  - [ ] deadhead_arcs.csv
  - [ ] terminals.csv

### 完了条件
- [ ] `routes.csv`, `stops.csv`, `timetable.csv` から generated trips が出る

---

## Day 5 の目標
**電費・燃費モデル Level 0 / Level 1 を実装する**

### ToDo
- [ ] `src/preprocess/energy_model.py` を作る
- [ ] `src/preprocess/fuel_model.py` を作る

### Level 0
- [ ] BEV: `energy_kwh = distance_km / efficiency_km_per_kwh`
- [ ] ICE/HEV: `fuel_l = distance_km / fuel_efficiency_km_per_l`

### Level 1
- [ ] travel_time 補正
- [ ] stop_count 補正
- [ ] gradient 補正
- [ ] HVAC 補正
- [ ] congestion 補正
- [ ] passenger_load 補正を拡張可能な形で入れる

### 出力
- [ ] generated_trips.csv に以下を追加
  - [ ] energy_kwh_bev
  - [ ] fuel_l_ice
  - [ ] fuel_l_hev
  - [ ] travel_time_min
  - [ ] deadhead_time_min

### 完了条件
- [ ] 路線パラメータを変えると energy / fuel が変わる

---

## Day 6 の目標
**can-follow arc を完成させる**

### ToDo
- [ ] `build_deadhead_matrix()` 実装
- [ ] `build_can_follow_arcs()` 実装
- [ ] 判定ロジックを固定する
  - [ ] arrival_time
  - [ ] deadhead_time
  - [ ] turnaround_buffer
  - [ ] terminal compatibility
  - [ ] garage return option
- [ ] `arc_reason` を持たせる
  - [ ] feasible
  - [ ] time_conflict
  - [ ] terminal_mismatch
  - [ ] buffer_shortage

### 完了条件
- [ ] trip network が CSV で見える
- [ ] どの trip が後続可能か追跡できる

---

## Day 7 の目標
**mode_B のモデル骨格を立てる**

### ToDo
- [ ] `src/model/mode_B_model.py` を作る
- [ ] 変数を定義する
  - [ ] assign_trip
  - [ ] follow_arc
  - [ ] charge_start / charge_power
  - [ ] soc
- [ ] 制約を分割ファイルで用意する
  - [ ] assignment_constraints.py
  - [ ] charging_constraints.py
  - [ ] soc_constraints.py
  - [ ] flow_constraints.py
- [ ] objective は簡易版にする
  - [ ] energy cost
  - [ ] penalty unmet trip
  - [ ] deadhead penalty

### 完了条件
- [ ] mode_B が build できる
- [ ] 小規模ケースで solve 実行まで行ける

---

# 4. Week 2

## Week 2 - Day 8
**mode_B の実行可能化**

### ToDo
- [ ] assignment 制約を完成
- [ ] trip cover 制約を完成
- [ ] flow balance 制約を完成
- [ ] charger capacity 制約を完成
- [ ] SOC 遷移を完成
- [ ] solve 後に simulator で再評価する

### 完了条件
- [ ] 3-5台、10-20 trip 規模で mode_B が動く

---

## Week 2 - Day 9
**KPI exporter と report 自動生成を完成させる**

### ToDo
- [ ] `src/export/result_exporter.py` を整理
- [ ] 常設 KPI を固定する
  - [ ] objective_value
  - [ ] charging_cost
  - [ ] fuel_cost
  - [ ] demand_charge
  - [ ] unmet_trip_penalty
  - [ ] min_soc
  - [ ] max_site_power
  - [ ] charger_utilization
  - [ ] deadhead_distance
  - [ ] solve_time
- [ ] `report.md` 自動生成
- [ ] `comparison.csv` 自動生成

### 完了条件
- [ ] 実験結果が論文図表の下書きに使える

---

## Week 2 - Day 10
**GUI と src pipeline を正しく接続する**

### ToDo
- [ ] GUI から直接 solver ロジックを書かないよう整理
- [ ] `app/main.py` から pipeline を呼ぶだけにする
- [ ] 新アーキタブで mode 切替
  - [ ] mode_A
  - [ ] mode_B
  - [ ] thesis_mode
- [ ] GUI で case JSON の保存/読込
- [ ] GUI で results/ を読んで可視化

### 完了条件
- [ ] CLI と GUI が同じ config を使って同じ結果を出せる

---

## Week 2 - Day 11
**scenario evaluation を実装する**

### ToDo
- [ ] `generate_scenarios()` を実装
- [ ] deterministic solve + post evaluation を作る
- [ ] 揺らぎを最低4つ定義する
  - [ ] trip energy +10%
  - [ ] travel time +10%
  - [ ] charger available -1
  - [ ] tariff high window expansion
- [ ] worst / mean KPI を出力する

### 完了条件
- [ ] robust 本実装前に脆弱性診断ができる

---

## Week 2 - Day 12
**先行研究比較用の最小図表を作る**

### ToDo
- [ ] mode_A 再現結果表を作る
- [ ] mode_B 再現結果表を作る
- [ ] 比較軸を固定する
  - [ ] charging cost
  - [ ] max simultaneous charging
  - [ ] min SOC
  - [ ] fleet size
  - [ ] charger count
- [ ] `docs/reproduction/comparison_notes.md` を作る

### 完了条件
- [ ] 修論発表で「先行研究模擬の結果」を見せられる

---

## Week 2 - Day 13
**thesis_mode の差分仕様書を作る**

### ToDo
- [ ] `docs/thesis_mode_gap_analysis.md` を作る
- [ ] mode_B との差分を明記する
  - [ ] PV
  - [ ] mixed fleet
  - [ ] demand charge
  - [ ] charging location selection
  - [ ] uncertainty evaluation
- [ ] 目的関数の候補を整理する
  - [ ] OPEX 最小化
  - [ ] TCO 最小化
  - [ ] CO2 + cost
  - [ ] lexicographic

### 完了条件
- [ ] 修論独自性を説明できる

---

## Week 2 - Day 14
**総点検・実験再実行・次フェーズ計画**

### ToDo
- [ ] mode_A 再実行
- [ ] mode_B 再実行
- [ ] GUI 動作確認
- [ ] 主要 CSV / JSON / report 出力確認
- [ ] 失敗ケースのログ確認
- [ ] backlog を更新
- [ ] 次週着手項目を決める

### 完了条件
- [ ] 2週間の成果を第三者に説明できる
- [ ] 次フェーズに滑らかに入れる

---

# 5. 2週間後の backlog

## 5.1 thesis_mode 初期拡張
- [ ] PV generation profile 接続
- [ ] demand charge モデル追加
- [ ] grid import/export 分離
- [ ] mixed fleet (BEV + ICE / HEV)
- [ ] terminal charging site selection

## 5.2 advanced planning
- [ ] charger placement
- [ ] fleet composition
- [ ] battery degradation
- [ ] annualized capex
- [ ] depot + on-route charging coexistence

## 5.3 uncertainty / robust
- [ ] scenario tree
- [ ] box uncertainty
- [ ] budgeted uncertainty
- [ ] stochastic evaluation
- [ ] sensitivity sweep runner

## 5.4 algorithmic extensions
- [ ] ALNS baseline
- [ ] ALNS-SA
- [ ] GA baseline
- [ ] ABC baseline
- [ ] exact vs heuristic comparison harness

## 5.5 GUI 強化
- [ ] route detail editor の segment 機能を新 UI に移植
- [ ] charger sites layer を地図に表示
- [ ] work schedule 地図対応
- [ ] KPI ダッシュボード整備
- [ ] comparison dashboard 改善

---

# 6. 毎日守る運用ルール

## 毎日の3点確認
- [ ] 今日増やしたコードは simulator で再評価できるか
- [ ] GUI なし CLI でも再現できるか
- [ ] その機能は mode_A / mode_B / thesis_mode のどこに属するか明確か

## 毎日の終了時に残すもの
- [ ] 変更ファイル一覧
- [ ] 実行コマンド
- [ ] 成功したケース
- [ ] 失敗したケース
- [ ] 明日の最優先1件

---

# 7. 研究上の注意
- いきなり巨大な monolithic 実装にしない
- GUI の中に数理モデル本体を書かない
- optimizer と simulator のロジックを二重管理しない
- いきなり実データ大規模ケースに行かない
- 先行研究再現前に thesis_mode を肥大化させない

---

# 8. 参照する主要論点
本 ToDo マスタは、以下の研究論点を踏まえている。
- journey 後 charging decision による charging cost 最小化
- fixed trip timetable と trip energy estimation に基づく充電計画
- vehicle scheduling と charging scheduling の統合
- charger placement と fleet configuration の相互依存
- TOU 料金と demand charge を含む TCO 評価
- opportunity charging の有効性
- battery degradation と heterogeneous vehicles の戦略変数化

---

# 9. 次の一手
この ToDo を実行するときの実務上の最初の一手は次である。
1. mode_A の再現仕様書を1ページで書く
2. toy case を1本作る
3. simulator を完成させる
4. mode_A を最後まで通す

ここを突破すると、以後の拡張はかなり楽になる。
