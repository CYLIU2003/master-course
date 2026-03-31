# master-course — EV バス配車・充電スケジューリング最適化研究システム

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![UI](https://img.shields.io/badge/UI-Tkinter-3776AB?logo=python&logoColor=white)
![Solver](https://img.shields.io/badge/Solver-Gurobi-EE3524)
![Optimization](https://img.shields.io/badge/Optimization-MILP%2BALNS-FF6F00)
![Status](https://img.shields.io/badge/Status-Core%20Package%20%28Tkinter%2BFastAPI%29-0A66C2)

---

## クイックナビ

> [!TIP]
> **読む順番の推奨：** 要約 → 1章（問題設定）→ 2章（数理モデル）→ 4章（起動）→ 5章（フロー）→ 7章（トラブル）

| 節 | 参照先 | 使いどころ |
|---|---|---|
| 要約 | [このシステムが何をしているか（先生向け要約）](#このシステムが何をしているか先生向け要約) | 最初の 5 分で研究対象と全体像を掴む |
| 1 | [1. このシステムが解く問題](#1-このシステムが解く問題先生向け概要) | 入力・決定・出力の流れを確認する |
| 2 | [2. 最適化モデルの説明](#2-最適化モデルの説明) | 数理モデル、変数、制約、目的関数を見る |
| 3 | [3. 実装状況と研究フェーズ](#3-実装状況と研究フェーズ) | 実装済み範囲と未実装範囲を確認する |
| 4 | [4. セットアップと実行手順](#4-セットアップと実行手順) | 環境構築、起動、初回接続を行う |
| 5 | [5. 東急全体最適化の推奨フロー](#5-東急全体最適化の推奨フロー) | Prepare/最適化を流す順番を確認する |
| 6 | [6. システム構成](#6-システム構成) | ディレクトリ構成と主要 API を確認する |
| 7 | [7. 既知の注意事項とトラブルシューティング](#7-既知の注意事項とトラブルシューティング) | dataset 不整合・エラー時の対処を見る |
| 8 | [8. パラメータ保全リスト](#8-パラメータ保全リスト) | 研究パラメータをどこで保持しているか確認する |
| 9 | [9. 実装詳細（技術リファレンス）](#9-実装詳細技術リファレンス) | 実装変数や dispatch 判定式を追う |
| 10 | [10. 実測監査](#10-実測監査) | KPI と再現コマンドを確認する |
| 11 | [11. AI エージェント向けアーキテクチャ仕様](#11-ai-エージェント向けアーキテクチャ仕様) | 自動修正時の制約と責務境界を確認する |

```mermaid
flowchart LR
  UI[Tkinter UI] --> API[FastAPI BFF]
  API --> PREP[Prepare Input]
  PREP --> OPT[Optimization Core]
  OPT --> SOLVE[MILP / ALNS / GA / ABC]
  SOLVE --> OUT[Results / Audit]
```

> **要点**
> - 本 README は「理想仕様」ではなく「現行実装」を優先して説明します。
> - 実装済み/未実装は 3章で明示し、断定表現を避けています。
> - 実行前に 4章・5章、問題発生時は 7章、検証時は 10章を参照してください。

<details>
<summary><strong>更新メモ（2026-03-28）</strong></summary>

- 2026-03-31: PV は「月平均」ではなく `serviceDate/serviceDates` で選んだ実日プロファイルを使う方式へ切り替え、Tk / Quick Setup / Prepare / canonical optimizer で同じ日付列を共有するようにした
- 2026-03-31: 営業所別エネルギー資産は `depot_energy_assets` で `pv_capacity_kw` と `bess_energy_kwh / bess_power_kw` を編集できる前提に整理し、日別 PV capacity factor から複数日 horizon 用の発電列を再構築できるようにした
- 2026-03-31: `ProblemBuilder.build_from_scenario()` の `planning_days` 取りこぼし、multi-day price slot 複製時の `co2_factor` フィールド不整合、MILP metadata 用の重複 model build を修正した
- 2026-03-31: prepared-input optimization は `rebuild_dispatch=false` のとき scope artifact を SQLite に書き戻さず in-memory solve するよう変更し、`optimization_result` / `simulation_result` は SQLite lock 時に JSON sidecar へフォールバック保存できるようにした
- 2026-03-31: scenario `237d5623-aa94-4f72-9da1-17b9070264be` を `2025-08-04`, `fixedRouteBandMode=true`, `disableVehicleAcquisitionCost=true`, `objectiveMode=total_cost`, 実日 PV で 4 モード比較し、結果を `output/optimization_comparison_api_237d_actual_pv_2025-08-04_final.json` に保存した（MILP は `time_limit`, ALNS/GA/ABC は同一 incumbent で `trip_count_served=638`, `trip_count_unserved=336`）

- scenario `237d5623-aa94-4f72-9da1-17b9070264be` の total_cost 再検証に合わせ、prepared input から materialize した `stops` に catalog 座標を再補完するよう変更し、scoped prepared JSON が stale でも canonical dispatch graph の deadhead 推論が落ちないようにした
- `BusstopPole` の番線違い (`...00240050.` / `...00240050.4` など) は同一 physical stop alias として 0 分 deadhead を自動補完し、route-band 固定でも terminal bay 差分だけで接続不能にならないようにした
- canonical MILP の trip-connection arc は feasible graph 全探索から「近い successor 上位のみ」へ pruning し、`mode_milp_only` が 237d scoped case で 다시 `OPTIMAL` まで戻るようにした
- canonical MILP の解復元は `y` の時刻順ソートではなく選択 arc/path から duty fragment を再構成するよう修正し、結果検証での偽の infeasible chain を除去した
- `required_soc_departure_percent` の小数値 (`0.939` = 0.939%) を ratio (`93.9%`) と誤解していた経路を修正し、ALNS / GA / ABC の false SOC violation を解消した
- fragment integrity 検証は duty envelope ではなく actual trip interval 同士で重なりを見るよう変更し、同一車両の sparse fragment を誤って overlap 扱いしないようにした
- Quick Setup / Tk 既定は `fixedRouteBandMode=true`・`enableVehicleDiagramOutput=true` を標準化し、route-band 図を基本出力にした（fragment 上限は既存互換のため configurable のまま保持）
- BFF canonical solve (`/api/scenarios/{id}/run-optimization`) でも `graph/vehicle_timeline.csv` と `graph/route_band_diagrams/*.svg` を出力するようにし、フロント/バック経由の MILP 実行でも route-band 可視化を直接確認できるようにした

- `objectiveMode` の定義を `total_cost/co2/balanced/utilization` で統一（helper/overlay/schema を整合）
- `fixed_route_band_mode` を MILP 制約に反映し、1 車両が複数 route family をまたがない運用を選択可能に
- C3 の開始/終了断片上限を `max_start_fragments_per_vehicle` / `max_end_fragments_per_vehicle` で制御
- `required_soc_departure_percent` を trip レベルで導出し MILP の出発時 SOC 下限制約として適用（0-1/0-100 正規化）
- 最適化結果シリアライズに `objective_components_raw` / `_weighted` / `pv_summary` / `utilization_summary` / `termination_reason` / `effective_limits` を追加
- `energy_required_kwh_bev` が欠損/0 のタスクは走行距離と推定係数（既知タスク平均、未取得時は 1.2 kWh/km）で補完
- Quick Setup に `finalSocTargetPercent`（その日の最終SOC目標）を追加し、フロント入力→BFF保存→最適化設定参照を接続（`finalSocFloorPercent` と後方互換で同期）
- `finalSocTargetPercent` は「終端SOC下限」ではなく、終端時点SOCを目標値へ近づけるソフト制約（偏差ペナルティ）として MILP 目的に反映
- Quick Setup に `finalSocTargetTolerancePercent`（終端SOC目標の許容±%）を追加し、許容帯を超えた偏差分のみを MILP 目的でペナルティ化
- 「固定路線バンド（路線間車両トレード禁止）」チェックは `fixedRouteBandMode` として dispatch scope に保存され、MILP の route-family 制約に連動
- ICE 車両にも燃料残量の状態遷移を追加し、便出発前の必要燃料チェックと走行後の残量更新（trip + deadhead 消費）を MILP 制約で扱うよう拡張
- `disable_vehicle_acquisition_cost` は simulation 設定から共通最適化（`src/optimization/common`）経路にも反映され、ON 時は車両固定費（日割り導入費）を 0 として評価
- Quick Setup に `initialIceFuelPercent` / `minIceFuelPercent` / `defaultIceTankCapacityL` を追加し、ICE の初期燃料・最低バッファ・既定タンク容量をフロント入力から最適化へ反映
- デフォルト車両テンプレートを 6 車種（BYD K8 2.0 / ブルーリボン Z EV / エルガ EV / ブルーリボン 2KG-KV290N4 6AT / エルガ 2KG-LV290N4 6AT / エアロスター 2KG-MP38FK 6AT）へ更新し、ICE は `energyConsumption` を L/km（燃費逆数）で統一、タンク容量は標準 160L を採用
- ICE 燃料モデルを拡張し、燃料残量が下限バッファに近づいた場合は refuel 変数で補充できるようにした（補充速度は「5分で下限→上限バッファ到達」想定）。`maxIceFuelPercent` を上限バッファとして追加
- 回送速度を `deadhead_speed_kmh`（既定 18 km/h）でパラメータ化し、Tk 基本パラメータ・Quick Setup・Prepare・最適化計算（燃費/CO2/電費の deadhead 換算）へ反映
- 補給イベントを出力可視化へ追加し、`vehicle_timelines.json/csv`・`graph/vehicle_timeline.csv`・`optimization_result.refueling_schedule` で「いつ・何L補充したか」を確認可能にした。`route_band_diagrams/*.svg` には ICE 補給マーカー（緑の印）を表示
- 補給イベント専用CSV `refuel_events.csv`（run直下と `graph/` 配下）を追加し、時刻順に「車両・デポ・補充L」を単独確認できるようにした
- `refuel_events.csv` に可視化補助列として `vehicle_type` / `route_band_id` / `route_band_label` / `route_family_code` を追加し、可視化ツールから車種・路線帯別に扱えるようにした
- 充電・給油の許可窓を `charging_window_mode=timetable_layover`（既定）で運行時刻表ベース化し、`home_depot_charge_pre_window_min` / `home_depot_charge_post_window_min` で home depot 出発前・到着後の許可窓幅を分単位で制御可能にした（旧 `home_depot_proxy` 近似モードも互換維持）
- `tools/bus_operation_visualizer_tk.py` / `tools/multi_run_visualizer_tk.py` の UI 表示を日本語化し、主要数値パラメータに単位（`[台]` `[秒]` `[円]` `[kg-CO2]`）を明記
- Solcast 営業所一括取得フロー用の実データ台帳を生成：
  - 2026-03-24T06:51:40.627289+00:00 に `data/external/solcast_raw/depot_coordinates_tokyu_all.json`（12 営業所座標）を生成
  - 2026-03-24T07:10:50.337433+00:00 に `data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json`（取得・利用台帳）を生成
  - 詳細運用は `readme_operation.md` の「5. 営業所別 Solcast キャッシュ運用」を参照
- 距離推定で `zero distance ratio` が高くなるケース向けに、`distance`/`stop` のキー揺れ吸収、座標欠損時の `stop_count`・所要時間ベース補完、Prepare監査ログ（座標カバレッジ/route距離件数）を追加
- 最適化モニターの失敗時診断を強化し、`problemdata_build_audit` 未取得時でもエラー文から `tasks/vehicles/travel_connections` を抽出し、さらに prepared input サマリ（trip/route/vehicle/depot/timetable_rows とファイル位置）を表示するようにした
- 最適化ジョブで「要求 prepared_input_id」と「実使用 prepared_input_id / JSONパス」をメタデータと失敗メッセージに表示し、UI 側でも `payload_effective` を出して stale 自動同期後の実効入力を追跡できるようにした
- `fixed_route_band_mode` の拘束粒度を系統 family ベースへ寄せ、`黒07(本線/区間便/入出庫便)` のような variant 差分は同一 band（例: `黒07`）として扱うよう正規化した
- `travel_connections=0` かつ `allow_partial_service=false` で即停止していた最適化を自動緩和し、実行時のみ `allow_partial_service=true` を有効化して hard stop を回避するよう変更（監査 warning に理由を記録）
- 契約電力制約に「超過スラック（kWh）」を追加し、`contract_overage_penalty_yen_per_kwh` で超過罰金を目的関数へ加算できるよう拡張（`enable_contract_overage_penalty` で ON/OFF）
- BESS 有効営業所では `grid_to_bus_priority_penalty_yen_per_kwh` / `grid_to_bess_priority_penalty_yen_per_kwh` を目的関数に追加し、PV/BESS 優先・Grid 後順位の運用をコスト面で強化
- 最適化の時間刻み既定を 1 時間（`time_step_min=60` / `timestep_min=60`）へ統一し、PV 発電量・BESS/SOC 遷移・契約上限制約の評価を同一スロット幅で整合化
- SOCカウントを trip イベント照合型へ調整し、各 trip の終了時点で消費電力量を一括反映する運用（運行中充電禁止制約は維持）を追加
- デポ電力フローに `PV->Bus` 直給を追加し、`PV->BESS` のみだった供給構造を `PV->Bus/PV->BESS/PV Curtail` に拡張
- 充電器容量制約を「全体合算」から「デポ単位合算（同時台数・総kW）」へ変更
- 充電・給油について、非走行条件に加えて `charging_window_mode=timetable_layover` では時刻表ベースの home depot 充電窓（出発前/到着後）でのみ許可、`home_depot_proxy` では従来の前後スロット近傍近似を適用
- 出発時SOC下限制約を `required_soc_departure_percent` のみの判定から、車両ごとの `trip_energy_kwh + floor_kwh` 必要量判定へ変更（旧 percent は後方互換の補助下限として併用）
- MILP 内の trip 電費/燃料消費は `trip.energy_kwh` / `trip.fuel_l` 固定値優先から、車両レート（`energy_consumption_kwh_per_km` / `fuel_consumption_l_per_km`）優先へ変更

</details>

## このシステムが何をしているか（先生向け要約）

本システムの現行 core は、東急バス 1 日分の運行計画について以下の **3 つを同時に決める** 混合整数線形計画（MILP）です。

**① 決める内容（決定変数）**

- どの便をどの車両（BEV：電気バス / ICE：エンジンバス）に割り当てるか
- 電気バス（BEV）をいつ・何 kW 充電するか
- 充電電力を PV（太陽光）と系統電力からどう配分するか

**② 守る条件（制約の種類）**

- 時刻表の全便を担当車両に割り当てる（欠便は大きな罰則で抑止）
- 走行中に充電しない / バッテリー残量（SOC）を下限以上に保つ
- 充電設備の台数・出力の上限を守る / 系統受電が契約電力以内

**③ 最小化する費用（目的関数）**

- ICE バスの燃料費（O1）＋ 電気代・TOU（O2）＋ デマンド料金（O3）＋ 車両固定費（O4）を **1 本の式として合算して最小化**します
- CO₂ 費用・電池劣化費（パラメータで有効化、デフォルトは 0 = 無効）
- **O1 と O2 を別々に最小化しないことが重要です**：O1 だけなら「ICE を使わない」、O2 だけなら「BEV を充電しない」が自明な解となり研究上の意味がありません。合算することで ICE↔BEV の最適な混合比率が得られます

> **実装上の重要な注意点（誠実な開示）**
>
> - **C1 欠便制約**：「全便を必ず割り当てる」は絶対制約ではなく、欠便変数に大きな罰則を課す**罰則付き緩和**として実装しています（通常は欠便が抑止されますが、解なし状態の回避が目的です）。
> - **C14 充電器制約**：「各充電器にどの車両が接続されているか」を厳密に追うのではなく、デポ単位の合計容量（同時台数・総kW）制約として実装しています。
> - **C20/C21 ピーク判定**：tariff テーブルが設定されている場合はそれを優先しますが、未設定時は時間帯別価格の中央値で on/off を近似的に分類しています。
> - **目的関数モード**：`objectiveMode=total_cost` は従来のコスト最小、`objectiveMode=co2` は CO₂排出量最小、`objectiveMode=balanced` はコストと排出の加重和、`objectiveMode=utilization` は運行達成を維持しつつ車両稼働の効率化を重視します。`co2` モードでは `co2_price_per_kg=0` でも排出量そのものを最小化します。
> - **CO₂費・劣化費**：`total_cost` モードでは、パラメータ（`co2_price_per_kg`・`degradation` 重み）に正の値を設定すると目的関数へ加算されます。

実装本体：[`src/optimization/milp/solver_adapter.py`](src/optimization/milp/solver_adapter.py)
研究仕様（目標定式化）：[`docs/constant/formulation.md`](docs/constant/formulation.md)
実装済み範囲の詳細：[`docs/constant/implementation_status.md`](docs/constant/implementation_status.md)

---

Tkinter + FastAPI BFF のみで東急全体の最適化を再現実行できるパッケージです。

---

---

## 1. このシステムが解く問題（先生向け概要）

### 1.1 一言で言うと

東急バスの1日の運行計画において、

- **どの便をどの車両（BEV or ICE）に任せるか**
- **BEV をいつ・どれだけ充電するか**
- **充電に使う電力を PV（太陽光）と系統電力からどう調達するか**

の3つを同時に決定し、**1日の総費用を最小化**します。

### 1.2 入力・決定・出力の流れ

```
【入力】
  時刻表（便ごとの出発・到着・走行距離）
  車両諸元（BEV: バッテリー容量・充電出力 / ICE: 燃費・燃料単価）
  電力料金（時間帯別単価・デマンド料金・契約電力上限）
  PV 発電予測（時間帯別の太陽光発電量）
        ↓
【決定】（モデルが自動で決める項目）
  ① 各便をどの車両に割り当てるか
  ② 各 BEV をいつ・何 kW 充電するか
  ③ 充電電力を PV と系統電力からどう分配するか
        ↓
【守るべき条件（制約）】
  ✔ 時刻表の全便を必ず担当車両に割り当てる（欠便は大きなペナルティ）
  ✔ BEV は走行中に充電しない（デポ滞在中のみ充電可能）
  ✔ バッテリー残量（SOC）が下限を下回らない（電欠禁止）
  ✔ 充電器の台数・出力の上限を超えない
  ✔ 系統受電量が契約電力を超えない
        ↓
【出力】
  車両ごとの運行スケジュール（どの便を担当するか）
  充電スケジュール（いつ・何 kW 充電するか）
  費用内訳（燃料費・電気代・デマンド料金・CO₂費・劣化費）
  担当不能な未充足便のリスト
```

### 1.3 最小化する費用の内訳

| 費目 | 内容 | 設定 |
|------|------|------|
| ICE 燃料費 | エンジンバスの燃料消費量 × 燃料単価 | 常時有効 |
| 電気代（TOU） | 時間帯別電力単価 × 系統買電量 | 常時有効 |
| デマンド料金 | 「最大需要電力（ピーク電力）× デマンド単価」 | 常時有効 |
| 車両固定費 | 使用車両に対する日割り固定費 | 車両設定がある場合 |
| 欠便ペナルティ | 担当不能便への大きなペナルティ（実質禁止） | 常時有効 |
| CO₂ 費用 | CO₂ 排出量 × CO₂ 価格（ICE 燃料由来 + 系統電力由来） | `co2_price_per_kg > 0` で有効 |
| 電池劣化費 | 充電量 ÷ バッテリー容量 × 劣化単価 | `degradation > 0` で有効 |

> **デマンド料金について**：電力会社との契約では、その月の「最大需要電力（30分ごとの平均電力の最大値）」に応じた基本料金が発生します。
> BEV の充電タイミングを分散させると最大需要電力を抑えられ、デマンド料金が下がります。
> この効果を定量化するために O3 として目的関数に含めています。
> 現行 core は day-ahead 単日最適化のため、デマンド料金は「単日 proxy（ピーク抑制の代理評価）」として扱います。月次契約の厳密再現は rolling/月次拡張で扱う想定です。

---

## 2. 最適化モデルの説明

本システムは **MILP（混合整数線形計画）** で定式化されています。
ソルバーは [Gurobi](https://www.gurobi.com/) を使用します。

> **MILP とは**：0/1 の整数変数（「便 j を車両 k に割り当てるか否か」など）と
> 連続変数（「充電電力 c kW」など）を混在させた最適化問題の総称です。
> 線形式で書けるため、Gurobi などの商用ソルバーで大規模な実問題を解くことができます。

### 2.1 モデルが決める変数（決定変数）

> ソルバーが値を決定する変数です。制約と目的関数の中で使われます。
> 実装ファイル：[`src/optimization/milp/solver_adapter.py`](src/optimization/milp/solver_adapter.py)

#### 主要決定変数

| 記号 | 意味 | 型・範囲 | Python コード変数 | 定義行 |
|------|------|---------|-----------------|--------|
| $y_j^k$ | 車両 $k$ が便 $j$ を担当する（1）か否（0）か | 0/1 整数 | `y[(vehicle_id, trip_id)]` | [L97](src/optimization/milp/solver_adapter.py#L97) |
| $x_{ij}^k$ | 車両 $k$ が便 $i$ の直後に便 $j$ を担当（1）か否（0）か | 0/1 整数 | `x[(vehicle_id, from_trip_id, to_trip_id)]` | [L100](src/optimization/milp/solver_adapter.py#L100) |
| $u_j$ | 便 $j$ が未充足（担当不能）である（1）か否（0）か | 0/1 整数 | `unserved[trip_id]` | [L114](src/optimization/milp/solver_adapter.py#L114) |
| $z_k$ | 車両 $k$ が1日に1便以上使用される（1）か否（0）か | 0/1 整数 | `used_vehicle[vehicle_id]` | [L119](src/optimization/milp/solver_adapter.py#L119) |
| $\xi_{k,t}$ | 車両 $k$ がスロット $t$ に充電 ON（1）か OFF（0）か | 0/1 整数 | `charge_on_var[(vehicle_id, slot_idx)]` | [L215](src/optimization/milp/solver_adapter.py#L215) |
| $c_{k,t}$ | 車両 $k$ のスロット $t$ での充電電力（kW） | 連続 $[0,\, c_{\max}]$ | `c_var[(vehicle_id, slot_idx)]` | [L216](src/optimization/milp/solver_adapter.py#L216) |
| $s_{k,t}$ | 車両 $k$ のスロット $t$ でのバッテリー残量 SOC（kWh） | 連続 $[SOC_{\min},\, cap_k]$ | `s_var[(vehicle_id, slot_idx)]` | [L218](src/optimization/milp/solver_adapter.py#L218) |
| $g_t$ | スロット $t$ での系統買電量（kWh） | 連続 $\geq 0$ | `g_var[slot_idx]` | [L297](src/optimization/milp/solver_adapter.py#L297) |
| $pv_t^{ch}$ | スロット $t$ での PV 自家消費量（kWh） | 連続 $\geq 0$ | `pv_ch_var[slot_idx]` | [L298](src/optimization/milp/solver_adapter.py#L298) |
| $\bar{p}_t$ | スロット $t$ の平均需要電力（kW）= $g_t / \Delta t$ | 連続 $\geq 0$ | `p_avg_var[slot_idx]` | [L299](src/optimization/milp/solver_adapter.py#L299) |
| $W^{on}$ | オンピーク期間中の最大需要電力（kW） | 連続 $\geq 0$ | `w_on_var` | [L301](src/optimization/milp/solver_adapter.py#L301) |
| $W^{off}$ | オフピーク期間中の最大需要電力（kW） | 連続 $\geq 0$ | `w_off_var` | [L302](src/optimization/milp/solver_adapter.py#L302) |

#### 補助変数（制約式のみに使用）

| 用途 | Python コード変数 | 定義行 | 備考 |
|------|-----------------|--------|------|
| 便鎖の先頭フラグ | `start_arc[(vehicle_id, trip_id)]` | [L105](src/optimization/milp/solver_adapter.py#L105) | C2/C3 の流量保存で使用 |
| 便鎖の末尾フラグ | `end_arc[(vehicle_id, trip_id)]` | [L109](src/optimization/milp/solver_adapter.py#L109) | C2/C3 の流量保存で使用 |
| 放電電力（kW） | `d_var[(vehicle_id, slot_idx)]` | [L217](src/optimization/milp/solver_adapter.py#L217) | V2G 対応用・現行は SOC 遷移に組み込み |

### 2.2 守るべき条件（制約）の説明

制約には C1〜C21 の番号を付けて管理しています（詳細は `docs/constant/formulation.md`）。
以下では非専門家向けに意味を説明します。

#### 便割当の制約（C1〜C5）

- **C1：各便には必ず1台の担当車両を割り当てる（罰則付き緩和）**
  理論式では等式制約 $\sum_k y_j^k = 1$ ですが、実装では欠便変数 $u_j$ を導入して
  $\sum_k y_j^k + u_j = 1$ とし、欠便に大きなペナルティ $\pi \cdot u_j$ を課すことで実質的に抑止します。
  これにより「解なし（infeasible）」状態を避けつつ、通常は欠便が発生しない設計になっています。

  > **先生向け補足**：「欠便ゼロを絶対制約にしている」ではなく「欠便には大きな罰則をかけ、通常は回避されるようにしている」が正確な説明です。

- **C2：車両の行路は連続した便の鎖になる**
  便 $j$ を担当したら、その前後の便との「接続」が整合的でなければなりません（流量保存）。

- **C3：各車両の出庫・入庫は1日1回まで**

- **C4：時刻的に接続不可能な便への移動は禁止**
  便 $i$ の到着後、転換時間＋回送時間以内に便 $j$ の出発地へ到着できない組み合わせは最初から排除します。

- **C5：同じ車両が同時刻に2つの便を担当することを明示禁止**
  重複する時間帯の便ペア $(i, j)$ に対し $y_i^k + y_j^k \leq 1$ を直接追加します。

#### バッテリー残量（SOC）の制約（C6〜C11）

> **SOC（State of Charge）**：バッテリーの残量を指します。ここでは kWh 単位で管理します。

- **C6〜C8：SOC の時系列遷移**（充電で増加、走行・回送で減少）

  $$s_{k,t+1} = s_{k,t} + \eta \cdot c_{k,t} \cdot \Delta t - e_k(j) \cdot y_j^k - e_k^{dh} \cdot x_{ij}^k$$

  $\eta$：充電効率（≈ 0.95）、$e_k(j)$：便 $j$ の走行エネルギー（kWh）、$\Delta t$：時間刻み（h）

- **C9：SOC は常に上下限の範囲内**（電欠禁止・過充電禁止）

  $$SOC_{\min} \leq s_{k,t} \leq cap_k$$

- **C10：出庫時の SOC 設定**（パラメータ `initial_soc` で指定）

- **C11：帰庫後の SOC は翌日確保用の下限以上**

#### 充電設備の制約（C12〜C14）

- **C12：走行中は充電しない**

  $$c_{k,t} \leq c_{\max} \cdot (1 - \text{running}_{k,t})$$

- **C13：1台あたりの充電電力は充電器定格以下**（ON/OFF 二値変数 $\xi_{k,t}$ を導入して厳密化）

- **C14：同時充電台数と総 kW 容量の両方の上限**

  $$\sum_k \xi_{k,t} \leq N_c^{\max}, \quad \sum_k c_{k,t} \leq P_c^{\max}$$

  > **実装の正直な開示**：「各充電器にどの車両が物理的に接続されているか」を厳密に追う
  > 割当制約は実装していません。実装では、全充電器の合計台数（$N_c^{\max}$）と
  > 合計 kW 容量（$P_c^{\max}$）の上限を守ることで、過負荷を防ぐ設計になっています。

#### 電力システムの制約（C15〜C21）

- **C15：電力バランス**（系統 + PV = 充電需要を常に成立させる）

  $$g_t + pv_t^{ch} = \sum_k c_{k,t} \cdot \Delta t$$

- **C16：PV 自家消費量は発電量以内**

- **C17：系統への逆潮流禁止**（$g_t \geq 0$）

- **C18：系統受電量は契約電力以内（超過罰金モード時はスラック許容）**

- **C19〜C21：デマンド料金計算用のピーク電力定義**

  > **実装の正直な開示**：オンピーク / オフピークの時間帯分類は、tariff テーブルに `demand_charge_weight` が設定されている場合はその定義を優先します。
  > 未設定の場合は「時間帯別単価の中央値以上をオンピーク」という近似分類を使います。
  > 電力会社の正式な契約時間帯定義を完全再現しているわけではありません。

#### 制約コード対応表（C1〜C21）

| No. | 内容 | 実装コード式（抜粋） | 実装行 |
|-----|------|-------------------|--------|
| C1 | 各便一意割当（罰則付き緩和） | `sum(y[k,j]) + unserved[j] == 1` | [L130](src/optimization/milp/solver_adapter.py#L130) |
| C2 | フロー保存（便鎖整合性） | `incoming + start_arc[key] == y[key]` | [L156–157](src/optimization/milp/solver_adapter.py#L156) |
| C3 | 出庫・入庫は高々1回 | `sum(start_arc) <= 1`, `sum(end_arc) <= 1` | [L160–161](src/optimization/milp/solver_adapter.py#L160) |
| C4 | 可行アークのみ利用 | `arc_pairs` を `feasible_connections` から生成 | [model_builder.py](src/optimization/milp/model_builder.py) |
| C5 | 重複運行禁止（明示制約） | `y[key_a] + y[key_b] <= 1` （重複ペア全列挙） | [L163–178](src/optimization/milp/solver_adapter.py#L163) |
| C6–C8 | SOC 時系列遷移 | `s[next] == s[cur] + 0.95*c*Δt - trip_energy - dh_energy` | [L255–262](src/optimization/milp/solver_adapter.py#L255) |
| C9 | SOC 上下限（変数の lb/ub） | `lb=soc_min, ub=cap` | [L218](src/optimization/milp/solver_adapter.py#L218) |
| C10 | 出庫時 SOC 固定 | `s_var[first_slot] == initial_kwh` | [L229](src/optimization/milp/solver_adapter.py#L229) |
| C11 | 帰庫後 SOC 下限 | `s_var[last_slot] >= soc_min * used_vehicle[k]` | [L233](src/optimization/milp/solver_adapter.py#L233) |
| C12 | 走行中充電禁止 | `charge_on_var[k,t] <= 1 - running_expr` | [L271](src/optimization/milp/solver_adapter.py#L271) |
| C13 | 充電電力上限（充電器定格） | `c_var[k,t] <= charge_max_kw * charge_on_var[k,t]` | [L272–275](src/optimization/milp/solver_adapter.py#L272) |
| C14 | 同時充電台数・容量上限 | `sum(charge_on_var) <= total_ports`, `sum(c_var) <= total_kw` | [L284–291](src/optimization/milp/solver_adapter.py#L284) |
| C15 | 電力バランス | `g_var[t] + pv_ch_var[t] == charge_kwh_expr` | [L315](src/optimization/milp/solver_adapter.py#L315) |
| C16 | PV 自家消費上限 | `pv_ch_var[t] <= pv_available * Δt` | [L316](src/optimization/milp/solver_adapter.py#L316) |
| C17 | 非逆潮流 | `lb=0.0` （g_var の変数定義） | [L297](src/optimization/milp/solver_adapter.py#L297) |
| C18 | 契約電力上限（超過罰金モード時は `+ slack`） | `g_var[t] <= contract_limit_kw * Δt (+ slack)` | [L317](src/optimization/milp/solver_adapter.py#L317) |
| C19 | 平均需要電力の定義 | `p_avg_var[t] == g_var[t] / Δt` | [L320](src/optimization/milp/solver_adapter.py#L320) |
| C20 | オンピーク最大需要 | `w_on_var >= p_avg_var[t]` （on_peak スロット） | [L324](src/optimization/milp/solver_adapter.py#L324) |
| C21 | オフピーク最大需要 | `w_off_var >= p_avg_var[t]` （off_peak スロット） | [L326](src/optimization/milp/solver_adapter.py#L326) |

### 2.3 目的関数（最小化する式）

> [!IMPORTANT]
> **O1〜O4・欠便ペナルティはすべて 1 本の式に足し合わせて同時に最小化します。**
>
> O1（ICE 燃料費）だけを最小化すれば「ICE を 1 台も走らせない」が自明な最適解となり、
> O2（電気代）だけを最小化すれば「BEV を 1 台も充電しない（ICE のみ運用）」が自明な最適解となります。
> それぞれを単独で扱っても研究上の意味はありません。
>
> O1 と O2 を同一式で合算することで、「ICE を使えば燃料費（O1）が増え、BEV を充電すれば電気代（O2）が増える」
> というトレードオフが内在化され、ソルバーが **ICE と BEV の最適な混合比率** を自動決定します。
>
> **欠便ペナルティは常に有効**です（O1〜O4・CO₂費・劣化費のいずれの設定にも関わらず、
> すべての項の後に無条件で加算されます — [L425–426](src/optimization/milp/solver_adapter.py#L425)）。

#### 目的関数の全体式

$$
\min \quad C_{total} = \underbrace{O1 + O2 + O3 + O4}_{\text{常に有効}} + \underbrace{\sum_j \pi \cdot u_j}_{\text{欠便ペナルティ（常に有効）}} + \underbrace{C_{CO_2}^{*} + C_{degr}^{*}}_{\text{パラメータ設定時のみ有効}}
$$

各項の展開式：

$$
O1 = \underbrace{\sum_{k \in K^{ICE},\, j \in J} c_f \cdot f_k(j) \cdot y_j^k}_{\text{便走行分}}
   + \underbrace{\sum_{k \in K^{ICE},\, (i,j) \in A} c_f \cdot f_k^{dh}(i,j) \cdot x_{ij}^k}_{\text{回送走行分}}
$$

$$
O2 = \sum_{t \in T} p_t^{grid} \cdot g_t \qquad
O3 = p^{dem,on} \cdot W^{on} + p^{dem,off} \cdot W^{off} \qquad
O4 = \sum_{k \in K} c_k^{veh} \cdot z_k
$$

$$
C_{CO_2}^{*} = p^{CO_2} \cdot \Bigl(
  \alpha_{ICE} \sum_{k \in K^{ICE},j} f_k(j) \cdot y_j^k
  + \alpha_{grid} \sum_{t} g_t
\Bigr) \quad \bigl(p^{CO_2} > 0 \text{ のとき有効}\bigr)
$$

$$
C_{degr}^{*} = w^{degr} \cdot \sum_{k \in K^{BEV},\, t} \frac{c_{k,t} \cdot \Delta t}{cap_k} \cdot \beta
\quad \bigl(w^{degr} > 0 \text{ のとき有効}\bigr)
$$

#### 各費目の有効化条件

| 費目 | 記号 | 有効化条件 | コード行 |
|------|------|-----------|---------|
| ICE 燃料費（便走行） | $O1_{\text{trip}}$ | **常に有効**（ICE 車両が 0 台なら自動的に 0） | [L336–348](src/optimization/milp/solver_adapter.py#L336) |
| ICE 燃料費（回送） | $O1_{\text{dh}}$ | **常に有効**（同上） | [L350–362](src/optimization/milp/solver_adapter.py#L350) |
| 電気代（TOU） | $O2$ | **常に有効**（系統買電量が 0 なら自動的に 0） | [L332–334](src/optimization/milp/solver_adapter.py#L332) |
| デマンド料金 | $O3$ | **常に有効**（単価を 0 に設定すれば実質無効化可） | [L364–367](src/optimization/milp/solver_adapter.py#L364) |
| 車両固定費 | $O4$ | **常に有効**（`fixed_use_cost_jpy = 0` で実質無効化可） | [L369–370](src/optimization/milp/solver_adapter.py#L369) |
| 欠便ペナルティ | $\pi \cdot u_j$ | **常に有効・無条件**（O1〜O4・オプション項の設定に関わらず必ず加算） | [L425–426](src/optimization/milp/solver_adapter.py#L425) |
| CO₂ 費用 | $C_{CO_2}^{*}$ | `co2_price_per_kg > 0` のときのみ加算 | [L372–407](src/optimization/milp/solver_adapter.py#L372) |
| 電池劣化費 | $C_{degr}^{*}$ | `degradation_weight > 0` のときのみ加算 | [L409–423](src/optimization/milp/solver_adapter.py#L409) |

> **コードにおける加算順序（[L330–428](src/optimization/milp/solver_adapter.py#L330)）：**
> `objective = LinExpr()` → O2 → O1 → O3 → O4 → CO₂費（条件付き） → 劣化費（条件付き） → **欠便ペナルティ（無条件）** → `setObjective(minimize)`

> [!NOTE]
> **データの流れ：** Tkinter UI → Quick Setup 保存 → BFF `PUT /quick-setup` → `dispatch_scope` / `scenario_overlay` →
> `src/optimization/common/builder.py`（`CanonicalOptimizationProblem`）→ `solver_adapter.py`
>
> Quick Setup の `simulationSettings.depotEnergyAssets` は `simulation_config.depot_energy_assets` として保存され、
> B 案（PV/BESS/Grid）制御の入力に使われます。
> `builder.py` の車両展開は、選択営業所の実車両レコード（`vehicles[*].id` / `depotId`）を優先し、
> タイプ別カウント由来の合成ID生成はフォールバック経路としてのみ使用します。

### 2.4 解法モード

| モード | アルゴリズム | 用途 |
|--------|-------------|------|
| `mode_milp_only` | Gurobi MILP（厳密解） | 小〜中規模の厳密最適解 |
| `mode_alns_only` | ALNS（適応型大規模近傍探索） | 大規模の近似解・高速探索 |
| `mode_ga` | GA（遺伝的アルゴリズム） | 大規模の近似解 |
| `mode_abc` | ABC（人工蜂コロニー） | 大規模の近似解 |

ALNS・GA・ABC は共通評価器 `src/optimization/common/evaluator.py` で O1〜O4 および CO₂費・劣化費を評価します。

---

## 3. 実装状況と研究フェーズ

### 3.1 定式化・実装・今後の3層構造

| 層 | 内容 | 参照先 |
|----|------|--------|
| 目標定式化 | 研究として最終的に目指す C1〜C21 / O1〜O4 の完全モデル | `docs/constant/formulation.md` |
| 実装済み範囲 | 2026-03-18 時点で core に実装された範囲 | `docs/constant/implementation_status.md` |
| 今後の計画 | ε制約法による多目的化・MILP 妥当性確認（Phase 3-4） | 本章 3.3 節 |

### 3.2 制約の実装状況（C1〜C21）

| No. | 内容 | 状態 | 備考 |
|-----|------|------|------|
| C1 | 各便の一意割当 | 🔶 部分対応 | 欠便を罰則付き緩和で許容（意図的設計） |
| C2 | フロー保存（便鎖の整合性） | ✅ 対応 | |
| C3 | 各車両の出庫・入庫は高々1回 | ✅ 対応 | |
| C4 | 接続可能アークのみ利用 | ✅ 対応 | 不可アークは変数自体を作らない |
| C5 | 同時刻の重複運行禁止 | ✅ 対応 | 重複ペア明示制約 `y[k,i]+y[k,j]≤1` を実装済み |
| C6 | SOC 遷移（デポ滞在中充電） | 🔶 部分対応 | 連続遷移による近似（厳密 Big-M なし） |
| C7 | SOC 遷移（便走行消費） | 🔶 部分対応 | 同上 |
| C8 | SOC 遷移（回送消費） | 🔶 部分対応（近似） | 距離→エネルギー換算に近似あり |
| C9 | SOC 上下限（常時） | ✅ 対応 | |
| C10 | 出庫時 SOC | 🔶 部分対応 | 満充電固定ではなく `initial_soc` パラメータ依存 |
| C11 | 帰庫後 SOC 下限 | ✅ 対応 | |
| C12 | 走行中充電禁止 | ✅ 対応 | |
| C13 | 充電電力上限（定格） | ✅ 対応 | ON/OFF 二値変数 $\xi_{k,t}$ を導入 |
| C14 | 同時充電台数・容量上限 | ✅ 対応 | 台数と kW 容量を分離実装 |
| C15 | 電力バランス | ✅ 対応 | |
| C16 | PV 供給上限 | ✅ 対応 | |
| C17 | 非逆潮流 | ✅ 対応 | |
| C18 | 系統受電容量上限（契約電力） | ✅ 対応 | 既定は上限厳守。`enable_contract_overage_penalty` 有効時は超過スラックを罰金付きで許容 |
| C19 | 平均需要電力の定義 | ✅ 対応 | |
| C20 | オンピーク最大需要電力 | 🔶 改善対応 | tariff 設定がある場合は優先適用、未設定時は中央値フォールバック |
| C21 | オフピーク最大需要電力 | 🔶 改善対応 | 同上 |

### 3.3 目的関数の実装状況

| 費目 | 状態 | 条件 |
|------|------|------|
| O1：ICE 燃料費（便 + 回送） | ✅ 実装済み | 常時有効 |
| O2：TOU 電気代 | ✅ 実装済み | 常時有効 |
| O3：デマンド料金 | ✅ 実装済み | 常時有効 |
| O4：車両固定費 | ✅ 実装済み | 車両設定がある場合 |
| 欠便ペナルティ | ✅ 実装済み | 常時有効 |
| CO₂ 費用 | ✅ 実装済み | `co2_price_per_kg > 0` で有効 |
| 電池劣化費 | ✅ 実装済み | `weights.degradation > 0` で有効 |
| PV 余剰売電 | ❌ 未実装 | 将来拡張 |

MILP（`solver_adapter.py`）と ALNS/GA/ABC 評価器（`evaluator.py`）は同一条件で同一費目を計算します。

### 3.4 研究フェーズ別の実装計画

| Phase | 位置づけ | 状態 |
|-------|---------|------|
| Phase 1（説明責務） | README・formulation.md・implementation_status.md の整備、先生向け説明図 | ✅ 完了 |
| Phase 2（定式整合） | 充電器台数制約分離・充電 ON/OFF 二値・tariff 優先ピーク判定・C5 明示制約 | ✅ 完了 |
| Phase 3（目的関数拡張） | CO₂ 費用の目的関数化・電池劣化費の目的関数化 | ✅ 完了 / deterministic MILP 妥当性確認・ε制約法は 🔲 未 |
| Phase 4（研究拡張） | ALNS + MILP ハイブリッド本格導入・Rolling horizon / 不確実性対応 | 🔲 未 |

---

## 4. セットアップと実行手順

### 4.0 単一アプリ版からの起動（推奨・環境構築不要）
TkinterフロントエンドとFastAPIバックエンドは、**1つの実行ファイル（.exe）に統合**されています。

1. **配置先:** dist/MasterCourseApp/MasterCourseApp.exe
2. **実行:** 上記 .exe をダブルクリックするだけで、裏でFastAPIが立ち上がり、自動でTkinter画面が起動します。
3. **出力:** 実行結果等は .exe と同じディレクトリ内の outputs/scenarios/ へ保存されます。

※ 開発用として .exe を再ビルドしたい場合は、ターミナルで pyinstaller build_exe.spec -y を実行してください。

---

### 4.1 環境構築

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4.2 開発環境からの起動（1ターミナルでOK）

Python環境がある場合は、以下のコマンド1つでバックエンドとフロントエンドの両方が起動します。

```powershell
python run_app.py
```
*(内部でFastAPIサーバーをバックグラウンド起動し、自動的にTkinterが立ち上がります。画面を閉じるとバックエンドも自動終了します。)*

---

### 4.3 Route Variant Labeler（路線タグ付与）

路線バリアントの手動タグ付与が必要な場合のみ使用します。

```powershell
.\.venv\Scripts\Activate.ps1
python tools/route_variant_labeler_tk.py
```

操作手順：
1. 対象 Scenario を選択
2. Route family / variant を選択
3. タグ（variant type / canonical direction 等）を編集・保存
4. `tools/scenario_backup_tk.py` 側で `ラベルをシナリオへ反映` を実行

### 4.4 初回接続時の使い方

1. BFF を起動してから `python tools/scenario_backup_tk.py` を開く
2. Tk で `接続確認` を実行し、`/api/app/datasets` の候補取得ログを確認する
3. `datasetId` は runtime 実行可能な候補のみが既定表示される。2026-03-21 時点の既定 runtime dataset は `tokyu_full`
4. `新規作成` 後は必ず `Quick Setup 読込` を押し、営業所・路線の候補を読み直す
5. 路線一覧は `data/catalog-fast/normalized/routes.jsonl` があれば常にそれを優先して表示する。Quick Setup では「運行種別サマリ」表を営業所・路線一覧の上に置き、選択した `dayType` に trip が存在する raw route variant だけを営業所配下で `routeFamilyCode` 単位に折りたたみ表示する。系統番号の数字は半角に正規化して表示する
6. Quick Setup は保存済み `dispatch_scope` の route 選択をそのままベースにしつつ、現在選択している `dayType` に存在しない route variant は候補から外す。trip / timetable のスコープ確定は `Prepare` 実行時に「現在選択している route のみ」を対象に行う。展開すると本線・区間便・入出庫便などの raw variant を個別に外せる
7. 保存時は `refine + excludeRouteIds` として保存するため、同じ営業所の系統を基本全部含めつつ、特定 family の入出庫便だけ / 区間便だけ除外する設定を保持できる
8. 路線は raw route を消さずに保持したまま、`routeFamilyCode` で同一系統として束ねる。営業所行・系統行・variant 行には現在の `dayType` の trip 数を表示し、variant 行では必要に応じて総 trip 数も併記する。Prepare / dispatch / 最適化では「選択 route のみ」を使って trip / timetable を読み込み、`origin_stop_id` / `destination_stop_id` と stop 座標から同一系統内の上り下り・本線・区間便・入出庫便の terminal 間 deadhead を自動補完する
9. 既存シナリオを開いた直後に営業所や路線の選択が空なら、stale な保存選択が runtime 補正で外れた可能性があるため選び直す
10. `Quick Setup 保存` → `ソルバー設定` → `Solver対応 Prepare` → `実行` の順で進める。`実行` は `最適化計算` / `Preparedシミュレーション` / `再最適化` を切り替える

---

### 4.5 論文用バス運行状態可視化（EV/エンジン識別対応）

最適化 run フォルダから、論文掲載向けの運行状態図を生成する専用アプリです。

```powershell
.\.venv\Scripts\Activate.ps1
python tools/bus_operation_visualizer_tk.py
```

操作手順：
1. `Browse` で run フォルダ（例: `outputs/tokyu/.../run_YYYYMMDD_HHMM`）を選択
2. `Load` を押してデータを読込
3. `Only assigned buses` / `Max buses` を調整
4. `Summary` タブで `status/objective/solve_time_seconds/total_cost/total_co2_kg` を確認
5. `Details` タブで詳細 key-value を確認、`Raw JSON` タブで元JSONを確認
6. `Render` で2種類の図を生成
7. `Save PNG` / `Save SVG` / `Save PDF` で高解像度保存

特長：
- 英語フォントは Times New Roman、日本語フォントはメイリオを使用
- EV とエンジンバスを別ラベル（`EV-xx` / `ENG-xx`）で表示
- ガント図では EV/エンジンでハッチ方向を変えて識別
- 充電図では緑の濃淡で充電出力比を表示
- アプリ内の文字ベース表示（Summary/Details/Raw JSON）で総コスト・総CO2を即時確認可能

---

### 4.6 複数 run 比較可視化（multi-run）

`outputs/tokyu` 配下の複数日・複数シナリオ・複数 run を横断して、比較表と比較図を生成するアプリです。

```powershell
.\.venv\Scripts\Activate.ps1
python tools/multi_run_visualizer_tk.py
```

操作手順：
1. `Base folder` に `outputs/tokyu`（またはその下位）を指定
2. `Scan` で `run_*` フォルダを収集
3. `Date / Scenario / Depot / Service` フィルタを設定して `Apply Filter`
4. 比較対象 run を複数選択
5. `Preview Text Summary` で `status / total_cost / total_co2_kg / objective / solve_time_sec` を確認
6. `Preview Comparison Charts` で `Total Cost` と `Total CO2` の棒グラフを確認
7. 必要に応じて `Only assigned` / `Max buses` / `Export SVG` を調整
8. `Export Selected` で比較表と図を一括出力

出力内容（`<base>/analysis_export/<timestamp>/`）：
- `summary_table.csv`（比較テーブル）
- `summary_report.md`（比較レポート）
- `total_cost_comparison.png` / `total_co2_comparison.png`
- `Export SVG` 有効時: 比較図の `.svg`
- 各 run サブフォルダに `bus_operation_figure_a/b`（PNG、必要に応じてSVG）

使い分け：
- 単一 run を詳細に確認する場合: `tools/bus_operation_visualizer_tk.py`
- 複数 run の総コスト・総CO2を比較する場合: `tools/multi_run_visualizer_tk.py`

---

### 4.7 固定フォーマット Graph Exports（Phase 1 必須）

`export_all` 実行時に、論文・再分析向けの構造化データを自動生成します。

出力先：
1. run ごと: `.../run_YYYYMMDD_HHMM/graph/`

生成ファイル（Phase 1 必須）：
- `manifest.json`
- `vehicle_timeline.csv`
- `soc_events.csv`
- `depot_power_timeseries_5min.csv`
- `trip_assignment.csv`
- `cost_breakdown.json`
- `kpi_summary.json`

追加出力（route-band 可視化）：
- `route_band_diagrams/manifest.json`
- `route_band_diagrams/*.svg`

route-band 可視化の仕様：
- 出力先は各 optimization run 配下の `graph/` です。例: `outputs/tokyu/2026-03-22/optimization/<scenario_id>/<depot>/<service>/run_YYYYMMDD_HHMM/graph/`
- `vehicle_timeline.csv` には `vehicle_type`, `band_id`, `band_label`, `route_family_code`, `route_series_code`, `event_route_band_id` を含めます。
- `trip_assignment.csv` には `assigned_vehicle_type`, `assigned_vehicle_band_id`, `band_id` を含めます。
- SVG は actual service の `band_id` ごとに 1 band 1 ファイルで出力し、route `stopSequence` の順番を stop 軸の正本として使います。stop 名は `data/catalog-fast/normalized/stops.jsonl` と `data/catalog-fast/tokyu_bus_data/route_stop_times/*.jsonl` から補完し、対象 band の route 以外の stop は本線軸に出しません。
- 本線は最長の営業系統を基準に構成し、区間便はその stop 軸の途中に差し込みます。入出庫など本線外の terminal は main axis に混ぜず、図の上側または下側の side lane に分けて飛び線で表します。
- 上り/下り、区間便、入出庫便は同じ band の図へ統合し、service は stop-time polyline、same-band / depot deadhead は破線、depot stay は点線で重ねます。ICE/BEV は色系統を分け、凡例に `vehicle_id [ICE/BEV]` と type legend を表示します。
- catalog-fast に該当 trip の stop-time が無い場合だけ、route `stopSequence` 上を線形補間して「その時刻におおよそどこにいるか」を見られるようにします。
- 時間軸は常に `00:00` から `23:59` の 1 日固定です。`simulation_config.start_time` 起点の slot index を実時刻へ補正してから `vehicle_timeline.csv` / `trip_assignment.csv` / SVG に反映するため、夕方以降の便が軸外へ飛ぶことはありません。
- SVG では vehicle ごとの日内最初の便に対する `depot_out`、最後の便の後の `depot_in`、および同一 band 内の長い空き時間や charge row を挟む区間の temporary depot stay を推定描画します。depot が当該路線の stopSequence に含まれない場合は side lane にのみ出します。
- `fixed_route_band_mode=true` の run では、そのまま路線専属ダイヤ図として使えます。通常 run でも出力しますが、`route_band_diagrams/manifest.json` の `mixed_event_route_band_detected=true` は「その route graph に出てくる車両が同日に他 band の trip も担当した」ことを意味します。

補足：
- タイムゾーンは `Asia/Tokyo`、時刻は ISO 8601 形式です。
- まず構造化データを安定出力し、描画は Tk アプリ / Notebook / フロントで再利用する方針です。

### 4.8 readme_save（保存先・出力先一覧）

この節は、README に散らばりやすい保存先と出力先をひとまとめにした参照用メモです。

| 種別 | 保存先 / 出力先 | 補足 |
|---|---|---|
| シナリオ保存 | `outputs/scenarios/{scenario_id}/` | シナリオ本体、Quick Setup、派生成果物の集約先 |
| 実行 run 出力 | `outputs/tokyu/.../run_YYYYMMDD_HHMM/` | 最適化・simulation の run 単位出力 |
| Graph Exports | `.../run_YYYYMMDD_HHMM/graph/` | `manifest.json`、`vehicle_timeline.csv`、`soc_events.csv` など |
| route-band 図 | `.../run_YYYYMMDD_HHMM/graph/route_band_diagrams/` | `manifest.json` と `*.svg` |
| Prepare 入力 | `outputs/prepared_inputs/{scenario_id}/` | `Solver対応 Prepare` の生成物 |
| 監査出力 | `outputs/audit/{scenario_id}/` | `*.json` / `*.csv` / `*.md` |
| 複数 run 比較 | `outputs/tokyu/.../analysis_export/{timestamp}/` | 比較テーブル・比較レポート・比較図 |
| Built dataset | `data/built/{dataset_id}/` | runtime 実行可能な dataset の保存先 |
| Catalog 正規化データ | `data/catalog-fast/normalized/` | 路線一覧や Quick Setup で優先参照 |
| GTFS 出力 | `GTFS/TokyuBus-GTFS/` | 標準 GTFS feed と sidecar |

---

## 5. 東急全体最適化の推奨フロー

1. シナリオ作成
2. Quick Setup 読込
3. 運行種別サマリで `dayType` を決めてから営業所と路線を選択
4. パラメータを設定（費用・SOC 等）
5. **シナリオ設定を保存（Quick Setup 保存）**
6. **ソルバー詳細設定を確定** (`solverMode` / `objectiveMode=total_cost|co2`)
7. **`Solver対応 Prepare` を実行**（← 保存後・ソルバー設定後に実行）
8. Prepare ログで `tripCount` / `solver profile` / 車両台数・充電器台数を確認
9. 実行種別を選んで `④ 実行`
10. Job completed と Optimization / Simulation 結果を確認

> [!IMPORTANT]
> **保存・ソルバー設定を変更したら必ず `Solver対応 Prepare` を再実行すること。**
> Prepare を飛ばすと、最新の営業所・路線・SOC・solver mode / objective mode 設定が最適化入力に反映されません。
> trip / timetable の route スコープ確定も Prepare で初めて行います。

> [!NOTE]
> **台数について：** Prepare 時は「選択した営業所に登録済みの車両台数・充電器台数」をそのまま利用します。
> 手入力は不要です。SOC 設定は `Cost / Tariff Parameters` で `initial_soc` / `soc_min` / `soc_max` を指定します。

> [!NOTE]
> **保存先：** `Quick Setup 保存` では route/depot 選択を `dispatch_scope` と `scenario_overlay` の両方へ同期します。
> `Solver対応 Prepare` は現在の設定から solver-specific prepared input を作成し、`④ 実行` はその prepared input を正本として使います。

> [!WARNING]
> **既存シナリオを開いた場合：** 旧 `tokyu_dispatch_ready` ベースなど runtime 未整備 dataset のシナリオを開くと、
> BFF は利用可能な runtime master（現行既定は `tokyu_full`）へ自動補正します。
> 無効な営業所・路線選択はクリアされるため、`Quick Setup 読込` 後に選択内容を再確認してください。

---

## 6. システム構成

### 6.1 ファイル構成

| カテゴリ | パス |
|---------|------|
| Tkinter UI | `tools/scenario_backup_tk.py`, `tools/route_variant_labeler_tk.py`, `tools/bus_operation_visualizer_tk.py`, `tools/multi_run_visualizer_tk.py` |
| FastAPI BFF | `bff/` |
| Dispatch（運行可行性） | `src/dispatch/` |
| 最適化ソルバー | `src/optimization/` |
| パイプライン | `src/pipeline/` |
| 設定・定数 | `config/`, `docs/constant/` |
| データセット | `data/seed/tokyu/`, `data/built/{dataset_id}/`（現行既定 runtime は `data/built/tokyu_full/`） |

### 6.2 除外したもの

React frontend、テスト、一時検証スクリプト、`__pycache__`、ログ・一時成果物

### 6.3 主な API 導線

| エンドポイント | 用途 |
|--------------|------|
| `GET /api/app/datasets` | runtime 実行可能な dataset 候補と既定 dataset の確認 |
| `GET /api/app/context` | データセット準備状態の確認 |
| `GET /api/app/data-status` | dataset ごとの built/runtime readiness の確認 |
| `POST/GET /api/scenarios/*` | シナリオ CRUD |
| `GET/PUT /api/scenarios/{id}/quick-setup` | Quick Setup の読込・保存 |
| `POST /api/scenarios/{id}/simulation/prepare` | 最適化入力の生成（Prepare） |
| `POST /api/scenarios/{id}/simulation/run` | Prepared input を使って simulation job を開始 |
| `POST /api/scenarios/{id}/run-optimization` | 最適化ジョブの開始 |
| `GET /api/jobs/{job_id}` | ジョブ状態の確認 |

---

## 7. 既知の注意事項とトラブルシューティング

### 7.1 実行環境

- Windows では最適化実行器の既定が `thread` モードです。
  必要に応じて環境変数 `BFF_OPT_EXECUTOR=process` で切り替えられます。
- Windows では simulation 実行器の既定も `thread` モードです。
  必要に応じて環境変数 `BFF_SIM_EXECUTOR=process` で切り替えられます。
- ポート衝突時は 8000 以外のポートで起動し、Tkinter 側の接続先を合わせてください。

### 7.2 503 エラー（`BUILT_DATASET_REQUIRED`）

`data/built/tokyu_full` が未準備の場合に発生します。

```powershell
python catalog_update_app.py refresh gtfs-pipeline `
  --source-dir data/catalog-fast `
  --built-datasets tokyu_full
```

- `No module named 'tokyubus_gtfs'` の環境でも、`data/catalog-fast/normalized/*.jsonl` から自動フォールバックします。
- 出力に `"pipeline_fallback": true` があれば完了しています。
- データ配置・生成後、BFF を再起動してください。

### 7.3 runtime 未整備 dataset / stale scenario の補正

**Dataset の扱い**

- `tokyu_dispatch_ready` は runtime 用 `trips.parquet` を持たず実行対象 dataset には使えない
- `datasetId` 候補は `runtimeReady=true` を優先表示（runtime 未整備は通常候補から除外）
- 新規シナリオ作成時に runtime 未整備 dataset を選ぶと bootstrap は `tokyu_full` へ自動フォールバック
- 既存シナリオを開くと BFF は stale な route/depot master を runtime 実在データへ補正する
  → 選択が外れた場合は `Quick Setup 読込` 後に選び直してください

**Quick Setup の表示ルール**

- 営業所一覧はすべて表示し、初期選択は route-backed な営業所のみ（`routeCount=0` は路線未展開）
- 路線一覧は「現在の `dayType` に trip を持つ route variant」のみ表示
- route limit は 0 trip 候補を落とした後に適用（有効路線が limit で隠れることはない）
- 路線一覧の基本は `data/catalog-fast/normalized/routes.jsonl`（存在する場合優先）
- `simulationSettings.depotEnergyAssets` を設定すると `simulation_config.depot_energy_assets` に保存され、Prepare/Runで利用される

> [!WARNING]
> **`Prepare` 後に `tripCount=0`** → 「選択 route × dayType × service_date」に該当 trip なし。
> Quick Setup で dayType と路線選択を見直してください。

**Prepare・実行フロー**

- `Quick Setup 保存` → `dispatch_scope` + `scenario_overlay` に route/depot を同期
- `Solver対応 Prepare` → 現在の UI 選択と solver 設定から prepared input を再生成
- `④ 実行` → dispatch 再構築が不要なら prepared input を直接使用（従来より軽量）
- 実行時に prepared input の stale 409 が返った場合は、Tkinter が `currentPreparedInputId` へ自動同期して再送し、必要時のみ自動 Prepare を再実行して再送する

**`rebuild_dispatch` と duty**

- `rebuild_dispatch=false`（既定）では duty 再生成は行わないため `dutyCount=0` になる場合あり
- dispatch duty を確認したい場合は `dispatch再構築ON` で実行

**`No travel connections generated` と INFEASIBLE**

- `build_report.travel_connection_count=0` かつ `allowPartialService=false` のまま `tripCount > vehicleCount` で実行すると、MILP は厳格配車条件により INFEASIBLE になります
- まずは `未配車許容`（`allowPartialService`）を ON にして `Quick Setup 保存` → `Solver対応 Prepare` → `実行` の順で回避してください
- 恒久的には route スコープを段階的に絞り、`travel_connection_count` が 0 にならない構成へ調整してください

**`Distance estimation audit: zero distance ratio ...` が高い場合**

- Prepare ログの `stop_coords=x/y` と `routes_with_distance=a/b` を確認し、座標欠損か route 距離欠損かを先に切り分ける
- 2026-03-26 以降は `distance_km/distanceKm/distance`、`lat/lon/latitude/longitude` などのキー揺れを吸収して補完する
- それでも比率が高い場合は、対象 dataset の stop 座標（`stops`）と route 停留所連鎖（`stopSequence`）の欠損を優先修正する

**Timetable first の原則**

- `timetable_rows` / `stop_timetables` を更新すると BFF は stale な `trips` / `graph` / `duties` / `dispatch_plan` / `simulation_result` / `optimization_result` を破棄し scenario を `draft` へ戻す
- 大規模 scope では `TravelConnection` を feasible edge のみ保持する疎形式（全 trip 対の O(n²) 展開は行わない）

### 7.4 MILP 変数名の長さエラー

`ERROR: Name too long (maximum name length is 255 characters)` が出た場合は MILP 変数名長が原因です。
2026-03-18 時点で `src/optimization/milp/solver_adapter.py` は全変数を自動命名（`name=` 省略）に変更済みです。

### 7.5 Gurobi の動作確認

```powershell
python -c "import gurobipy as gp; m=gp.Model(); x=m.addVar(lb=0.0,name='x'); m.setObjective(x, gp.GRB.MINIMIZE); m.optimize(); print('gurobi_ok', gp.gurobi.version())"
```

`gurobi_ok` が出力されれば Python 側の Gurobi は利用可能です。
ライセンス未設定の場合は `optimize()` でライセンスエラーになります。

### 7.6 job completed ≠ 最適化成功

> [!WARNING]
> `job completed` はジョブ管理システム上の完了であり、数理最適化の成功とは別です。
> `solver_status` が `ERROR` / `INFEASIBLE` の場合、最適化結果ファイルが生成されないことがあります。

---

## 8. パラメータ保全リスト

> [!CAUTION]
> 以下のパラメータは最適化計算に直接関与します。**削除・名称変更しないでください。**
> 詳細は [`docs/core_parameter_preservation_manifest.md`](docs/core_parameter_preservation_manifest.md) を参照してください。

**ソルバー設定**
`solverMode`, `objectiveMode`, `timeLimitSeconds`, `mipGap`, `alnsIterations`, `randomSeed`

`solverMode` を変えた場合は prepared input が stale になるため、必ず `Solver対応 Prepare` をやり直してください。
`objectiveMode` は現在 `total_cost` / `co2` / `balanced` / `utilization` の 4 種類です。`co2` は `co2_price_per_kg` が 0 でも CO₂排出量最小として解きます。

**スコープ設定**
`selectedDepotIds`, `selectedRouteIds`, `dayType`, `service_id`, `service_date`,
`includeShortTurn`, `includeDepotMoves`, `includeDeadhead`,
`allowIntraDepotRouteSwap`, `allowInterDepotSwap`

**ペナルティ**
`allowPartialService`, `unservedPenalty`

**料金・排出係数**
`gridFlatPricePerKwh`, `gridSellPricePerKwh`, `demandChargeCostPerKw`,
`dieselPricePerL`, `gridCo2KgPerKwh`, `co2PricePerKg`, `iceCo2KgPerL`,
`depotPowerLimitKw`, `degradationWeight`, `tou_pricing`

**車両・テンプレート**
`type`, `modelCode`, `modelName`, `capacityPassengers`,
`batteryKwh`, `fuelTankL`, `energyConsumption`, `fuelEfficiencyKmPerL`,
`co2EmissionGPerKm`, `co2EmissionKgPerL`,
`curbWeightKg`, `grossVehicleWeightKg`, `engineDisplacementL`, `maxTorqueNm`, `maxPowerKw`,
`chargePowerKw`, `minSoc`, `maxSoc`, `acquisitionCost`, `enabled`

---

## 9. 実装詳細（技術リファレンス）

この章は開発者・指導教員向けの詳細情報です。

### 9.1 数式記号と実装変数の対応

| 数式記号 | 意味 | 実装変数（Python） |
|---------|------|-------------------|
| $y_j^k$ | 便割当 | `y[(vehicle_id, trip_id)]` |
| $x_{ij}^k$ | 便間接続アーク | `x[(vehicle_id, from_trip_id, to_trip_id)]` |
| $u_j$ | 欠便フラグ | `unserved[trip_id]` |
| $z_k$ | 車両使用フラグ | `used_vehicle[vehicle_id]` |
| $\xi_{k,t}$ | 充電 ON/OFF | `charge_on_var[(vehicle_id, slot_idx)]` |
| $c_{k,t}$ | 充電電力 | `c_var[(vehicle_id, slot_idx)]` |
| $s_{k,t}$ | SOC | `s_var[(vehicle_id, slot_idx)]` |
| $g_t$ | 系統買電量 | `g_var[slot_idx]` |
| $pv_t^{ch}$ | PV 自家消費 | `pv_ch_var[slot_idx]` |
| $\bar{p}_t$ | 平均需要電力 | `p_avg_var[slot_idx]` |
| $W^{on}, W^{off}$ | ピーク需要 | `w_on_var`, `w_off_var` |
| $P^{contract}$ | 契約電力上限 | `contract_limit_kw` |

実装ファイル: `src/optimization/milp/solver_adapter.py`（MILP）、`src/optimization/common/evaluator.py`（ALNS/GA/ABC）

### 9.2 C1〜C21 詳細実装表

詳細は `docs/constant/implementation_status.md` を参照してください。
本 README の 3.2 節が要約版です。

### 9.3 dispatch 接続可否の判定式

便 $i$ の後に便 $j$ を接続するには以下を満たす必要があります。

$$arrival(i) + turnaround(dest_i) + deadhead(dest_i, origin_j) \leq departure(j)$$

実装: `src/dispatch/feasibility.py`、`src/dispatch/graph_builder.py`

補足:
- 接続判定は stop 名ではなく `origin_stop_id` / `destination_stop_id` を優先して使います。
- 明示 `deadhead_rules` が無い場合でも、同一 `routeFamilyCode` の terminal stop 座標から回送候補を補完します。
- これにより、同一系統番号に属する上り下り・本線・区間便・入出庫便を raw trip のまま接続判定できます。

### 9.4 定数文書トレーサビリティ

| 定数文書 | 採用目的 | 反映先 |
|---------|---------|--------|
| `docs/constant/formulation.md` | C1-C21 / O1-O4 定式の正本 | 本 README、`src/optimization/milp/*` |
| `docs/constant/implementation_status.md` | 実装状況一覧 | 本 README 3章 |
| `docs/constant/AGENTS_ev_route_cost.md` | EV/ICE 混成・コスト統合方針 | `bff/routers/optimization.py` |
| `docs/constant/AGENTS.md` | timetable-first の不変条件 | `src/dispatch/*` |
| `docs/constant/ebus_prototype_model_gurobi.md` | Gurobi 実装指針 | `src/optimization/milp/solver_adapter.py` |

### 9.5 非 Tk フロント機能の移植バックログ

`docs/tkinter_feature_parity_backlog.md` を正本として管理しています。

### 9.6 完成判定チェックリスト

- BFF 起動と `/api/app/context` 応答
- Tkinter から Prepare 成功
- Tkinter から最適化 Job が完走
- core 内に `frontend/tests/tmp/cache/log` が存在しない
- パラメータ保全マニフェストに挙げた項目が保持されている

### 9.7 結果画面の確認ポイント

- `Optimization結果` / `Simulation結果` の Summary タブは、`総コスト`、`担当便数`、`未担当便数`、`使用車両数` と主要な非ゼロ内訳を先頭表示する。
- `Cost Breakdown` タブは、`総コスト` を先頭に非ゼロ項目を上段へ並べ、構成比 (`share`) も確認できる。
- 2026-03-31 時点では、シナリオ `237d5623-aa94-4f72-9da1-17b9070264be` の最新 `optimization_result` に非ゼロ内訳が保存済みであり、`energy_cost=202,796.50054309692`, `vehicle_cost=483,447.4885844756`, `driver_cost=2,006,683.333333335`, `penalty_unserved=3,360,000.0`, `total_cost=6,052,927.3224609075` を結果画面から確認できる前提とする。

### 9.8 コスト成分トグル

- `基本パラメータ` には `車両コスト / 運転士コスト / その他コスト` の ON/OFF 表を置き、各行はチェックボックスで切り替える。
- これらは Quick Setup 保存対象であり、未設定の旧シナリオは互換のため全て `ON` として扱う。
- `その他コスト` は電力・燃料・需要料金・劣化・CO2・欠便ペナルティなどの残りコスト群をまとめたスイッチとして扱う。

---

## 10. 実測監査

第三者が追試できるよう、監査スクリプトと成果物を追加しています。

- スクリプト: `scripts/audit_timetable_alignment.py`
- 提出版レポート: `docs/reproduction/timetable_alignment_audit_20260318.md`
- 監査成果物（WEEKDAY）: `outputs/audit/bbe1e1bd/timetable_alignment_audit.{json,csv,md}`

### 10.1 監査 KPI

| KPI | 意味 |
|-----|------|
| `timetable_rows_count` | 時刻表行数（便数） |
| `unserved_trip_count` | 担当不能便数 |
| `departure_arrival_match_rate` | 出発・到着一致率 |
| `checked_coverage_rate` | 一致率算出に使えた便の割合 |
| `day_tag_match` | prepared input と最適化結果の曜日タグ整合性 |

`day_tag_match = false` の場合、サービス日種別が異なるため `departure_arrival_match_rate` を品質判定に使わないでください。

### 10.2 再現コマンド

```powershell
python scripts/audit_timetable_alignment.py `
  --scenario-id bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f `
  --prepared-input-path outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-7822b5b6dd60630d.json `
  --optimization-result-path outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/WEEKDAY/optimization_result.json `
  --out-dir outputs/audit/bbe1e1bd
```

---

## 11. AI エージェント向けアーキテクチャ仕様

この README と関連ドキュメントを読む自動化エージェント向けの要約です。

### 11.1 守るべき基本方針

- **Timetable first, dispatch second.**
- Dispatch は `src/dispatch/` を通して扱い、UI や BFF で独自実装しない。
- 最適化入力に関わるパラメータは削除しない。
- `operator_id` を含まないデータは扱わない。
- `docs/constant/` は原則 read-only とする。

### 11.2 レイヤーの役割

| レイヤー | 役割 |
|---|---|
| Tkinter UI | 研究・運用の入力画面、結果確認 |
| FastAPI BFF | API 経由のオーケストレーション |
| Dispatch Core | 時刻表からの接続可否・車両 duty 生成 |
| Optimization Core | MILP / ALNS / GA / ABC による最適化 |
| Data / Catalog | シナリオ・マスタ・派生データの保管 |

### 11.3 実装時の注意点

- 既存の最適化パラメータ契約を壊さない。
- 既知の Tkinter 機能は維持する。
- 一時ファイル・cache・tmp スクリプトは core 配布前に整理する。
- 変更が README / development note に反映されているか確認する。
- 迷ったらまず既存の章と `docs/constant/` を優先して参照する。
