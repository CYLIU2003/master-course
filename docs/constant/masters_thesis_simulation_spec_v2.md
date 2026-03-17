# 修論用シミュレーションツール開発仕様書 v2

## ステータス
- 分類: 正本候補
- 用途: 修論シミュレーション・最適化仕様の基準線を確認する
- 備考: 現行コード寄りの中心仕様として扱う

## 0. 文書の目的
本仕様書は、修士論文で扱う **電気バス運行・配車・充電スケジューリング・インフラ計画・再エネ活用** を対象に、
Vibe Coding Agent あるいは Python 実装者がそのままコード化できるよう、
**数理モデル・入力データ・運行ロジック・評価ロジック・先行研究再現モード・拡張モード** を一体で定義するものである。

本仕様書の目的は次の4点である。

1. 修論で扱う問題を、実装可能なデータ構造へ落とし込むこと。
2. 先行研究の代表的なモデルを、切替可能な「再現モード」として実装できるようにすること。
3. 研究独自拡張として、PV・需要料金・混成車両・不確実性・劣化コストなどを段階的に追加できるようにすること。
4. Toy Problem から実データ拡張まで、同一コード基盤で比較可能な研究環境を作ること。

---

## 1. 研究対象と開発コンセプト

### 1.1 対象問題
対象は、都市バス事業者の1日または複数日運行を想定した、以下の統合問題である。

- どの運行便または trip chain をどの車両が担当するか
- 各 BEV がどの時刻にどこでどれだけ充電するか
- どの充電器・充電拠点を使うか
- 充電器競合や拠点受電上限をどう処理するか
- 電力量料金、TOU 料金、需要料金、PV 自家消費をどう考慮するか
- 不確実な travel time / energy consumption に対して計画がどの程度頑健か
- 必要に応じて、車種構成・電池容量・充電器数・充電器設置箇所まで含めて最適化するか

### 1.2 ツールの基本思想
本ツールは単なる「最適化コード」ではなく、以下の3層で構成する。

1. **Optimization Layer**
   - MILP / MINLP / 近似解法(ALNS, GAなど)で計画を生成する。
2. **Simulation Layer**
   - 与えられた計画を時系列シミュレーションで追跡し、SOC推移・充電待ち・運行遅延・電力需要を評価する。
3. **Experiment Layer**
   - 先行研究の再現ケースと、自分の独自拡張ケースを同一インタフェースで比較する。

### 1.3 開発順序
開発は以下の順に行う。

- Phase 0: データスキーマと評価シミュレータを先に作る
- Phase 1: 単一路線・固定時刻表・固定 fleet の充電スケジューリング
- Phase 2: vehicle-trip assignment を含む electric bus scheduling
- Phase 3: charger capacity / TOU / demand charge / nonlinear charging を導入
- Phase 4: fleet composition / charger placement / battery degradation を導入
- Phase 5: uncertainty / robust evaluation / scenario simulation を導入
- Phase 6: PV / stationary battery / V2G 等の研究独自要素を導入

---

## 2. 参考文献ベースの設計方針

本仕様は、以下の代表的な論文群を「再現対象」として意識して構成する。

### 2.1 代表的な再現対象の整理

#### モードA: Journey後の充電意思決定モデル
- 代表: He et al. (2023, TRD 115, No42)
- 特徴:
  - 各 journey の後に充電するか否かを二値で決定
  - 充電コスト最小化
  - 同時充電台数制約
  - 単純化された charging decision モデル
- 実装上の意味:
  - `charge_after_trip[v,j]` 型の簡易充電スケジューラとして実装可能
  - 早い段階の baseline として有用

#### モードB: Resource assignment + charging station capacity + uncertainty
- 代表: Chen et al. (2023, TRD 118, No47)
- 特徴:
  - mixed fleet
  - nonlinear charging
  - charging station capacity 制約
  - energy consumption uncertainty
  - robustness 評価
- 実装上の意味:
  - 研究基盤として極めて重要
  - あなたの修論では、この系統を主要なベースラインとみなす

#### モードC: Joint optimization of charger placement + fleet configuration + battery degradation
- 代表: Wang et al. (2024, Renewable Energy, No43)
- 特徴:
  - heterogeneous vehicles
  - opportunity charging
  - charger placement
  - fleet configuration
  - battery degradation
- 実装上の意味:
  - 戦略計画と運用計画の橋渡しをする上位モード
  - 修論の発展系として重要

#### モードD: Joint optimization of infrastructure + vehicle scheduling + charging management
- 代表: He et al. (2023, TRD 117, No55)
- 特徴:
  - infrastructure planning
  - vehicle scheduling
  - charging management
  - TCO 最小化
- 実装上の意味:
  - 「運行スケジュール変更も許す」総合モデルの骨格
  - 再現実験と独自拡張の接続点になる

#### モードE: 再エネ併用・経済性評価モード
- 代表: Fantin et al. (No01)
- 特徴:
  - PV 導入
  - garage/depot の電力需要
  - TCO / payback / economic assessment
- 実装上の意味:
  - 修論独自の PV 連携評価に必要
  - 最適化というより techno-economic simulation の要素が強い

### 2.2 本研究での位置づけ
本ツールでは、上記を **完全に1本へ無理やり統合する** のではなく、以下のように階層化する。

- Core-1: electric bus scheduling
- Core-2: charging scheduling
- Core-3: charging infrastructure constraints
- Core-4: economic evaluation
- Extension-1: battery degradation
- Extension-2: uncertainty / robust evaluation
- Extension-3: PV / ESS / V2G

これにより、先行研究再現と独自拡張の両方がやりやすくなる。

---

## 3. 実装対象機能の全体像

### 3.1 必須機能
- バス路線・trip・block・デポ・terminal・charger site・車両・充電器を読み込めること
- fixed schedule に対して vehicle assignment ができること
- SOC 遷移を追跡できること
- charger capacity を守った charging schedule を生成できること
- TOU 電力料金で charging cost を計算できること
- case ごとの差分比較ができること
- infeasible のとき制約群を切り分けられること

### 3.2 準必須機能
- piecewise linear による nonlinear charging 近似
- battery degradation cost
- charger site ごとの受電上限
- demand charge
- scenario-based simulation
- route length / consumption sensitivity analysis

### 3.3 発展機能
- PV / ESS / V2G
- charger placement
- fleet composition
- robust optimization
- stochastic programming
- ALNS / GA / hybrid exact-heuristic

---

## 4. 推奨アーキテクチャ

```text
project_root/
  data/
    toy/
    literature_replication/
      mode_A_journey_charge/
      mode_B_resource_assignment/
      mode_C_joint_planning/
      mode_D_joint_tco/
      mode_E_pv_techno_economic/
    thesis_case/
  config/
    experiments/
    modes/
    objectives/
  src/
    schemas/
      entities.py
      io_schema.py
    loaders/
      csv_loader.py
      json_loader.py
    preprocess/
      time_expansion.py
      trip_chain_builder.py
      energy_estimator.py
      scenario_generator.py
    model/
      sets.py
      parameters.py
      variables.py
      constraints/
      objective.py
      model_factory.py
    solve/
      gurobi_runner.py
      alns_runner.py
      ga_runner.py
    simulate/
      event_simulator.py
      slot_simulator.py
      robustness_evaluator.py
    analysis/
      kpi.py
      sensitivity.py
      result_compare.py
    export/
      report_md.py
      export_csv.py
      export_json.py
      export_plots.py
  outputs/
    run_YYYYMMDD_HHMMSS/
```

---

## 5. モデルの粒度設計

### 5.1 時間表現
本ツールでは、以下の2方式を両方扱える設計にする。

1. **Discrete-time model**
   - 5分, 10分, 15分スロットなどで離散化
   - charger occupancy, grid power, TOU 料金に向く
2. **Discrete-event model**
   - trip start / trip end / charge start / charge end をイベントとして扱う
   - vehicle scheduling に向く

### 5.2 初期実装の推奨
- MILP は discrete-time を基本とする
- シミュレータは discrete-event を基本とする
- 両者の橋渡しとして、trip と charge event からスロット系列へ変換する関数を用意する

---

## 6. 運行ロジック仕様

この節は、単なる数式一覧ではなく、**バス運行にかかわるロジックそのもの** をコードに落とすための仕様である。

### 6.1 Trip / Block / Duty の定義

#### 6.1.1 Trip
最小単位の運行タスク。
例:
- 08:10 depot 発 -> Route 3 outbound
- 08:55 terminal 到着

持つ情報:
- 出発時刻
- 到着時刻
- 出発地点
- 到着地点
- 走行距離
- 旅客運行か回送か
- 想定消費電力量
- 必要車種・容量制約

#### 6.1.2 Block / Duty
連続して1台の車両が担当する trip 列。
初期版では、次のどちらかを選べるようにする。

- **trip-based assignment**: 便ごとに車両割当
- **block-based assignment**: あらかじめ作った block に車両割当

修論の早期段階では、block-based が実装しやすい。
その後、trip-based に拡張する。

### 6.2 Trip 接続ロジック
2つの trip `i, j` に対し、同一車両で連続担当可能かどうかを `can_follow[i,j]` として前処理する。

連続担当可能条件の例:
- `end_time[i] + deadhead_time[i,j] <= start_time[j]`
- `destination[i]` から `origin[j]` へ回送可能
- 休憩・折返し最低時間を満たす
- 車種制約に反しない

この前処理により、ネットワークフロー型・set partitioning 型いずれでも利用可能にする。

### 6.3 デポ出庫・入庫ロジック
- 各車両は初期時点でいずれかのデポに所属する
- 初回 trip の前に、所属デポから最初の trip 始点へ移動可能でなければならない
- 最終 trip の後に、必要ならデポへ帰庫できること
- overnight charging を扱う場合、日跨ぎの end-of-day SOC と翌日初期SOCを接続できるようにする

### 6.4 回送(deadhead)ロジック
旅客を乗せない移動を回送として別管理する。

必要項目:
- `deadhead_time[i,j]`
- `deadhead_distance[i,j]`
- `deadhead_energy[i,j]`
- `deadhead_cost[i,j]`

回送は見落としやすいが、BEV では SOC に直接効くため必須である。

### 6.5 遅延・余裕時間ロジック
将来拡張として、以下をオプションで持てるようにする。

- turnaround slack
- schedule buffer
- charging wait time
- stochastic travel time による到着遅れ

評価シミュレーションでは、充電待ちや遅延の蓄積を追跡可能にする。

---

## 7. 集合・インデックス定義

### 7.1 主要集合
- `V`: vehicle 集合
- `V_b`: BEV vehicle 集合
- `V_d`: diesel/ICE vehicle 集合
- `R`: route 集合
- `I`: trip 集合
- `B`: block / duty 集合
- `S`: stop / terminal / depot / charger site 集合
- `C`: charger 集合
- `T`: discrete time slot 集合
- `Ω`: scenario 集合
- `K`: vehicle type 集合

### 7.2 補助集合
- `I_r`: route `r` 上の trip 集合
- `C_s`: site `s` に属する charger 集合
- `Vtype_k`: type `k` の車両集合
- `I_start(v)`: 車両 `v` が最初に担当可能な trip 集合
- `I_end(v)`: 車両 `v` が最後に担当可能な trip 集合
- `Succ(i)`: trip `i` の後続候補集合
- `Pred(j)`: trip `j` の先行候補集合

---

## 8. 入力データ仕様

### 8.1 trip.csv
最低限の列例:

| column | meaning |
|---|---|
| trip_id | trip識別子 |
| route_id | 路線識別子 |
| start_time | 出発時刻 |
| end_time | 到着時刻 |
| origin_stop | 出発地点 |
| destination_stop | 到着地点 |
| distance_km | 走行距離 |
| energy_kwh_mean | 想定平均消費電力量 |
| energy_kwh_p90 | 保守側消費電力量 |
| travel_time_min_mean | 平均所要時間 |
| travel_time_min_p90 | 保守側所要時間 |
| trip_type | service/deadhead など |

### 8.2 vehicle.csv
| column | meaning |
|---|---|
| vehicle_id | 車両ID |
| vehicle_type | BEV/ICE |
| subtype | 車種分類 |
| home_depot | 所属デポ |
| battery_capacity_kwh | 電池容量 |
| soc_init_kwh | 初期SOC |
| soc_min_kwh | 最低SOC |
| soc_target_end_kwh | 終了目標SOC |
| max_charge_power_kw | 車両側最大充電電力 |
| charge_efficiency | 充電効率 |
| fixed_cost_day | 日次固定費 |
| depreciation_cost_day | 日次償却費 |

### 8.3 charger_site.csv
| column | meaning |
|---|---|
| site_id | 拠点ID |
| site_type | depot/terminal/on_route |
| grid_limit_kw | 拠点受電上限 |
| transformer_limit_kw | 変圧器上限 |
| demand_charge_applicable | 需要料金有無 |
| land_limit_chargers | 設置可能最大台数 |

### 8.4 charger.csv
| column | meaning |
|---|---|
| charger_id | 充電器ID |
| site_id | 所属拠点 |
| charger_type | plug/pantograph |
| max_power_kw | 最大出力 |
| efficiency | 効率 |
| install_cost | 設置費 |
| compatible_vehicle_types | 対応車種 |

### 8.5 tariff.csv
| column | meaning |
|---|---|
| time_slot | 時刻スロット |
| site_id | 拠点ID |
| tou_price_yen_per_kwh | 電力量料金 |
| sell_price_yen_per_kwh | 売電単価 |
| demand_charge_rate_yen_per_kw | 需要料金単価 |

### 8.6 pv.csv
| column | meaning |
|---|---|
| time_slot | 時刻スロット |
| site_id | 拠点ID |
| pv_generation_kw | PV発電量 |

### 8.7 deadhead.csv
| column | meaning |
|---|---|
| from_trip | 先行trip |
| to_trip | 後続trip |
| feasible | 連続担当可能か |
| deadhead_time_min | 回送時間 |
| deadhead_distance_km | 回送距離 |
| deadhead_energy_kwh | 回送消費電力量 |

### 8.8 scenario.csv
| column | meaning |
|---|---|
| scenario_id | シナリオID |
| probability | 発生確率 |
| factor_energy | 消費倍率 |
| factor_travel_time | 所要時間倍率 |
| factor_pv | PV倍率 |
| factor_price | 価格倍率 |

---

## 9. パラメータ定義

### 9.1 運行関連パラメータ
- `start_i`, `end_i`: trip `i` の出発・到着時刻
- `o_i`, `d_i`: trip `i` の始終点
- `dist_i`: trip距離
- `tau_i`: trip所要時間
- `e_i^ω`: scenario `ω` における trip消費電力量
- `tau_i^ω`: scenario `ω` における trip所要時間

### 9.2 車両関連パラメータ
- `G_v`: 車両 `v` の battery capacity [kWh]
- `soc0_v`: 初期SOC
- `soc_min_v`: 最低SOC
- `soc_end_target_v`: 終了時目標SOC
- `p_charge_max_v`: 車両側最大受電電力
- `η_charge_v`: 充電効率
- `cost_fixed_v`: 使用固定費

### 9.3 充電関連パラメータ
- `P_c`: charger `c` の最大充電出力
- `site(c)`: charger の所属site
- `L_s`: site `s` の grid / transformer limit
- `N_s`: site `s` の charger 台数上限
- `compat_{v,c}`: 車両-充電器適合性

### 9.4 電力・経済関連パラメータ
- `π_{s,t}`: site `s`, time `t` の電力量単価
- `π_sell_{s,t}`: site `s`, time `t` の売電単価
- `π_dem_s`: 需要料金単価
- `pv_{s,t}^ω`: PV 発電量
- `base_{s,t}`: site の基礎負荷

### 9.5 劣化関連パラメータ
- `c_deg_v`: 劣化コスト係数
- `ξ(...)`: SOC変化に応じた容量劣化率
- 必要に応じて Lam and Bauer 系 empirical model を piecewise または evaluation-only で扱う

---

## 10. 決定変数定義

### 10.1 vehicle-trip assignment 変数
- `x[v,i] ∈ {0,1}`
  - 車両 `v` が trip `i` を担当するなら1

- `y[v,i,j] ∈ {0,1}`
  - 車両 `v` が trip `i` の直後に trip `j` を担当するなら1

### 10.2 block assignment 変数
- `z[v,b] ∈ {0,1}`
  - 車両 `v` が block `b` を担当するなら1

### 10.3 charging 変数
- `u[v,c,t] ∈ {0,1}`
  - 車両 `v` が時刻 `t` に charger `c` を占有するなら1

- `p[v,c,t] >= 0`
  - 時刻 `t` に charger `c` から車両 `v` へ供給する電力

- `q[v,s,t] >= 0`
  - site `s` での車両 `v` の受電量

### 10.4 SOC 変数
- `soc[v,t]`
  - 時刻 `t` の車両 `v` の SOC

- `soc_arr[v,i]`, `soc_dep[v,i]`
  - trip 到着/出発時点SOC

### 10.5 site power 変数
- `grid_import[s,t] >= 0`
- `grid_export[s,t] >= 0`
- `site_peak[s] >= 0`
- `pv_use[s,t] >= 0`
- `pv_curtail[s,t] >= 0`

### 10.6 charger placement / fleet configuration 変数
- `build_charger[s,m] ∈ {0,1}`
  - site `s` に charger type `m` を設置するか
- `n_bus_type[k] ∈ Z_+`
  - 車種 `k` の導入台数

### 10.7 robust / scenario 変数
- `cost_ω`
- `unserved_ω`
- `worst_case_cost`

---

## 11. 導出量定義

- 各車両の日次走行距離
- 各車両の日次充電量
- 各 site のピーク需要
- TOU 別充電量
- PV 自家消費率
- 充電待ち時間
- 未充足 trip 数
- バッテリ劣化量
- ICE/BEV 比率
- 1日総費用
- 年換算TCO

---

## 12. 目的関数仕様

目的関数は単一でも多目的でもよいが、初期版では重み付き総費用最小化を基本とする。

### 12.1 基本形
最小化対象候補:
- 車両使用固定費
- 電力量料金
- 需要料金
- ICE 燃料費
- 回送コスト
- バッテリ劣化コスト
- 充電器設置費の年換算値
- 車両導入費の年換算値
- 未充足便ペナルティ
- 遅延ペナルティ

### 12.2 objective flag で切替える項目
- `use_energy_cost`
- `use_demand_charge`
- `use_battery_degradation_cost`
- `use_vehicle_capex_annualized`
- `use_charger_capex_annualized`
- `use_unserved_penalty`
- `use_delay_penalty`
- `use_carbon_cost`

---

## 13. 制約仕様

### 13.1 運行カバー制約
- 各必須 trip はちょうど1台、または少なくとも1台が担当する
- 未割当を許す場合は slack を入れて penalty を課す

### 13.2 車両重複禁止制約
- 同一車両は同時刻に複数 trip を担当できない
- trip-based の場合は arc flow で表現する

### 13.3 フロー保存制約
- vehicle scheduling のネットワークフローとして、先行-後続関係の整合を取る
- デポ出庫と入庫を source/sink ノードとして表現可能にする

### 13.4 時間整合制約
- `trip i` の終了と `trip j` の開始の間に deadhead と minimum layover を確保する

### 13.5 SOC 遷移制約
- trip 実行時は消費電力量分だけ SOC が減る
- charging 時は効率を考慮して SOC が増える
- `soc_min <= soc <= soc_max`
- 終了時 SOC は必要に応じて目標値以上

### 13.6 充電占有制約
- 1 charger は同一時刻に高々1台しか使えない
- 1車両は同一時刻に高々1 charger しか使えない

### 13.7 charger/site capacity 制約
- site の総充電電力は受電上限以下
- charger 数を変数にする場合は build decision と連動させる

### 13.8 charging feasibility 制約
- その時刻に車両がその site に存在しているときのみ充電可能
- trip中の走行中充電をしない場合、その間は充電不可
- opportunity charging を許す場合、停車時間・折返し時間内に限定する

### 13.9 TOU / demand charge 制約
- `grid_import[s,t]` に応じて energy cost を計算
- `site_peak[s] >= grid_import[s,t] + base[s,t]` でピーク需要を表現

### 13.10 PV 電力収支制約
- `pv_use + pv_curtail + grid_export = pv_generation`
- `charging_load + base_load = pv_use + grid_import - grid_export_adjusted` など、採用する電力収支式を明確にする

### 13.11 劣化コスト制約または評価式
- まずは evaluation-only として、解の SOC 軌跡から battery degradation を後計算してもよい
- その後、piecewise linear 化して MILP に組み込む

### 13.12 robust / scenario 制約
- シナリオごとのエネルギー消費・travel time で feasibility を確認
- 頑健性指標として
  - scenario feasibility ratio
  - expected cost
  - worst-case cost
  - worst-case unserved trips
  を計算する

---

## 14. 非線形充電ロジック

### 14.1 実装方針
CC-CV の完全再現は初期実装では不要とし、以下の2段階で実装する。

#### Stage 1
- `soc < alpha * capacity` の領域では定出力
- `soc >= alpha * capacity` の領域では出力逓減
- 2～4区分の piecewise linear approximation

#### Stage 2
- 論文再現モードで区分数や breakpoints を設定ファイルから切替可能にする

### 14.2 インタフェース
```json
{
  "charging_curve": {
    "type": "piecewise_linear",
    "breakpoints_soc": [0.0, 0.8, 0.9, 1.0],
    "relative_power": [1.0, 1.0, 0.6, 0.2]
  }
}
```

---

## 15. 不確実性の扱い

### 15.1 対象不確実性
- trip travel time
- trip energy consumption
- PV 発電量
- 電力価格
- 乗降遅れ・停車時間ばらつき

### 15.2 初期実装
- scenario-based evaluation
- deterministic optimization で得た解を、複数 scenario 上で再評価する

### 15.3 発展実装
- robust counterpart
- chance constraint
- two-stage stochastic optimization

---

## 16. 先行研究再現モード仕様

### 16.1 mode_A_journey_charge
対象:
- journey 終了後に充電するか否かの単純化モデル

固定するもの:
- vehicle-trip assignment は入力済み
- charger site は1箇所または少数
- 充電 decision のみ最適化

可変要素:
- TOU tariff
- charger count
- charge threshold

### 16.2 mode_B_resource_assignment
対象:
- mixed fleet
- charging station capacity
- nonlinear charging
- uncertainty evaluation

固定するもの:
- route network, trip timetable

可変要素:
- bus type composition
- charger capacity
- scenario sample set

### 16.3 mode_C_joint_planning
対象:
- opportunity charging
- charger placement
- fleet configuration
- battery degradation

可変要素:
- charger設置箇所
- charger台数
- vehicle type 数量

### 16.4 mode_D_joint_tco
対象:
- infrastructure planning
- vehicle scheduling
- charging management
- total cost of ownership

可変要素:
- battery size
- charger power
- vehicle schedule adjustment

### 16.5 mode_E_pv_techno_economic
対象:
- PV 導入ありの depot/garage 電力評価
- 日次または年次コスト評価

可変要素:
- PV容量
- tariff
- demand charge
- ESS 有無

---

## 17. 研究独自拡張モード仕様

### 17.1 Thesis mode の中心アイデア
先行研究の多くは、
- fixed timetable
- fixed route network
- 充電器・電池容量・fleet 構成の一部固定
の前提を置いている。

あなたの修論用拡張では、以下を主軸に据える。

- **PVを保有する事業者** を想定する
- **充電場所選択 + 充電スケジュール + vehicle scheduling** を統合する
- 必要に応じて **BEV + ICE の混成移行期** を考慮する
- 頑健性評価を入れ、単なる最低コストでなく **実運用可能性** を見る

### 17.2 thesis_mode で有効化したい要素
- BEV / ICE 混成 fleet
- PV 自家消費
- site ごとの受電制約
- TOU + demand charge
- uncertainty simulation
- case comparison automation

---

## 18. 実験設計仕様

### 18.1 最低限のケース群
- Case 0: Diesel only baseline
- Case 1: BEV fixed fleet + depot charging only
- Case 2: BEV + opportunity charging
- Case 3: BEV + opportunity charging + charger capacity
- Case 4: Case 3 + nonlinear charging
- Case 5: Case 4 + battery degradation
- Case 6: Case 5 + uncertainty evaluation
- Case 7: Case 6 + PV
- Case 8: Case 7 + mixed fleet

### 18.2 感度分析候補
- charger台数
- charger出力
- battery容量
- route length
- energy consumption倍率
- TOU価格
- demand charge rate
- PV容量
- scenario conservativeness

### 18.3 比較指標(KPI)
- total daily cost
- annualized total cost
- energy cost
- demand charge
- fleet size
- charger utilization
- average SOC margin
- unmet trip count
- average charging waiting time
- PV self-consumption ratio
- worst-case scenario feasibility

---

## 19. 実装インタフェース仕様

### 19.1 設定ファイル config.json 例
```json
{
  "mode": "mode_B_resource_assignment",
  "solver": "gurobi",
  "time_step_min": 5,
  "objective_flags": {
    "use_energy_cost": true,
    "use_demand_charge": true,
    "use_battery_degradation_cost": false,
    "use_vehicle_capex_annualized": false,
    "use_charger_capex_annualized": false,
    "use_unserved_penalty": true
  },
  "uncertainty": {
    "enabled": true,
    "evaluation_only": true,
    "num_scenarios": 50
  },
  "charging_curve": {
    "type": "piecewise_linear",
    "breakpoints_soc": [0.0, 0.8, 0.9, 1.0],
    "relative_power": [1.0, 1.0, 0.6, 0.2]
  }
}
```

### 19.2 出力ファイル
- `solution_summary.json`
- `vehicle_schedule.csv`
- `charging_schedule.csv`
- `soc_trace.csv`
- `site_power_trace.csv`
- `kpi_summary.csv`
- `scenario_evaluation.csv`
- `comparison_table.csv`
- `auto_report.md`

---

## 20. コードモジュール責務

### 20.1 data_loader
- CSV / JSON の読込
- スキーマ検証
- 型変換

### 20.2 trip_chain_builder
- `can_follow`
- deadhead matrix
- feasible arc list の生成

### 20.3 parameter_builder
- 離散時刻展開
- TOU 価格列生成
- energy consumption / scenario parameter 整形

### 20.4 model_factory
- mode に応じて有効な変数・制約・目的関数を切替

### 20.5 simulator
- event simulation
- SOC 追跡
- charger queue 追跡
- infeasibility detection

### 20.6 evaluator
- KPI 計算
- robust evaluation
- sensitivity analysis

### 20.7 exporter
- CSV / JSON / Markdown 出力
- 図表作成用 tidy data の出力

---

## 21. 開発時の注意事項

### 21.1 いきなり全部入れない
以下を同時に全部実装しないこと。
- charger placement
- fleet composition
- nonlinear charging
- battery degradation
- uncertainty
- PV
- mixed fleet

まずは再現しやすい baseline を動かし、その後に一つずつ足す。

### 21.2 infeasible 切り分け
制約群を必ずモジュール分割し、以下の順で ON/OFF できるようにする。
- coverage
- time feasibility
- SOC balance
- charger occupancy
- site capacity
- end-of-day SOC
- demand charge / economic components

### 21.3 評価器を先に作る
最適化器が未完成でも、手書きの簡単な schedule を simulator に流し込んで SOC と charger occupancy を確認できる状態を先に作る。

---

## 22. Vibe Coding Agent に実装してもらうための要件

Agent に要求する内容は次の通り。

1. まず `schemas`, `loaders`, `simulator` を先に実装すること。
2. 次に `mode_A_journey_charge` を最も小さい baseline として作ること。
3. その後 `mode_B_resource_assignment` を作り、vehicle-trip assignment, charger capacity, nonlinear charging を入れること。
4. optimizer と simulator の結果が一致するかを必ず検証すること。
5. すべての mode について、`toy dataset` を最低1個ずつ付けること。
6. 解が infeasible の場合は、どの制約群が原因かをログ出力すること。
7. すべての主要出力は CSV と JSON の両方で保存すること。
8. 実装は拡張しやすいよう、mode 切替式にすること。

---

## 23. 今後の発展方向

- ALNS による large-scale electric vehicle scheduling
- robust optimization と deterministic planning の比較
- PV + depot charging + demand response
- mixed BEV/ICE transition planning
- route electrification priority analysis
- battery replacement / lifecycle planning
- 年次計画と日次運用の多段階モデル

---

## 24. 参考文献(本仕様書で重視したもの)

1. He, Y. et al. (2023). Joint optimization of electric bus charging infrastructure, vehicle scheduling, and charging management. Transportation Research Part D, 117, 103653.
2. Chen, Q. et al. (2023). Cost-effective electric bus resource assignment based on optimized charging and decision robustness. Transportation Research Part D, 118, 103724.
3. Wang, Y. et al. (2024). Optimal battery electric bus system planning considering heterogeneous vehicles, opportunity charging, and battery degradation. Renewable Energy, 237, 121596.
4. He, J. et al. (2023). BEB charging plan schedule optimization under time-varying electricity price assumptions. Transportation Research Part D, 115, 103587.
5. Fantin, C.A. et al. Solar-supported electric BRT systems の technical and financial feasibility を扱うケーススタディ論文 (No01).
6. Electric bus scheduling / charging / infrastructure planning に関するレビュー論文および関連文献群 (No35, No27 等).

---

## 25. 付録: 最小実装スコープ

### Step 1
- trip.csv
- vehicle.csv
- charger.csv
- tariff.csv
- deadhead.csv
- event simulator

### Step 2
- `mode_A_journey_charge`
- SOC trace
- charger occupancy
- energy cost 計算

### Step 3
- trip assignment を追加
- `mode_B_resource_assignment`

### Step 4
- nonlinear charging
- scenario evaluation

### Step 5
- PV / demand charge / mixed fleet

この順なら、研究としても実装としても破綻しにくい。
