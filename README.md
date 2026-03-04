# E-Bus Sim — 電気バス運行・充電スケジューリング最適化 シミュレータ

> PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 — 試作アプリケーション

## 概要

本アプリケーションは、電気バス（BEV）の**便割当・充電スケジュール・PV/買電配分**を統合的に最適化するための試作シミュレータです。  
Gurobi (MILP) による厳密解法、ALNS（Adaptive Large Neighbourhood Search）、GA（遺伝的アルゴリズム）、ABC（人工蜂コロニー）の4つのソルバーに対応し、最適化コストと計算時間を比較できます。

### 主な機能

- **GUI 上でシステム規模・車両性能を自由に変更可能**
- **Gurobi (MILP)**: ステージ別（段階的）求解に対応
- **ALNS**: 大規模問題向けのメタヒューリスティクス、SA受理付き
- **GA**: 遺伝的アルゴリズム（トーナメント選択・一様交叉・突然変異）
- **ABC**: 人工蜂コロニーアルゴリズム（雇用蜂・傍観蜂・偵察蜂）
- **4ソルバー比較**: コスト棒グラフ・計算時間比較・収束曲線重ね表示
- **結果可視化**: SOC推移、電力バランス、買電コスト、便割当ガントチャート
- **路線管理**: 複数路線の追加・編集、地図クリックで停留所配置、片道フラグ（outbound_only/inbound_only）、往路から復路を自動生成
- **営業所管理**: 複数営業所・車両・行路（便チェーン）の管理。**地図から営業所を選択・位置入力対応**（folium マーカークリックで選択、空地クリックで緯度経度プリフィル）
- **JSON インポート/エクスポート**: 既存の `ebus_prototype_config.json` と互換

---

## クイックスタート

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

Gurobi を使う場合は別途 Gurobi ライセンスとパッケージが必要です:

```bash
pip install gurobipy
```

> Gurobi がなくても ALNS / GA / ABC（内側 LP は scipy で代替）で動作します。

### 2. アプリの起動

```bash
streamlit run app/main.py
```

ブラウザで `http://localhost:8501` が自動で開きます。

> **注意**: `python -u app/main.py` や `python app/main.py` では起動できません。  
> 必ず `streamlit run app/main.py` を使用してください。

### 3. 基本的な使い方

1. サイドバーから **システム規模**（バス台数、便数、時間刻み等）を設定
2. **車両性能**（バッテリ容量、SOC 範囲、電費）を調整
3. **充電設備**（充電器出力・台数）、**PV・電力料金**を設定
4. 「設定を適用」ボタンを押す
5. ソルバータブで **Gurobi** / **ALNS** / **GA** / **ABC** を選択して求解
6. 「比較」タブで複数ソルバーのコスト・時間を比較
7. 結果を確認、必要ならJSON をダウンロード

---

## 詳細な使い方

### アプリの画面構成

```
┌──────────────────────────────────────────────────────────────────┐
│  サイドバー（左）    │  メインエリア（右） — 5 タブ構成            │
│  ─────────────────  │  ────────────────────────────────────       │
│  ⚙️ 設定方法の選択   │  ⚙️ 設定                                   │
│  ├─ 手動設定         │    └─ 問題設定・概要メトリクス・JSON I/O    │
│  └─ JSON インポート  │                                             │
│                     │  🔬 ソルバー（サブタブ）                    │
│  📐 システム規模     │    ├─ Gurobi (MILP)                        │
│  🚌 車両性能        │    ├─ ALNS                                  │
│  🔌 充電設備        │    ├─ GA                                    │
│  ☀️ PV・電力料金    │    ├─ ABC                                   │
│  🔧 拡張オプション  │    └─ 🆕 新アーキ (src/)                   │
│                     │                                             │
│  [🔄 設定を適用]    │  📊 比較・専用（サブタブ）                  │
│                     │    ├─ 全比較 / MILP専用 / ALNS専用          │
│                     │    └─ ALNS+MILP                             │
│                     │                                             │
│                     │  🗺️ 路線詳細（レガシー — 非推奨）           │
│                     │                                             │
│                     │  🚌 路線・営業所管理（サブタブ）            │
│                     │    ├─ 🚌 路線管理（地図入力・時刻表）       │
│                     │    └─ 🏢 営業所管理（地図選択・属性編集）   │
└──────────────────────────────────────────────────────────────────┘
```

---

### Step 1: 設定方法を選ぶ

サイドバー上部の「設定方法」ラジオボタンで選択します。

#### 手動設定モード

スライダーや数値入力でパラメータを調整し、最後に「**🔄 設定を適用**」ボタンを押すと問題インスタンスが生成されます。

| セクション | 主要パラメータ |
|---|---|
| **📐 システム規模** | バス台数 (1〜20)、便数 (1〜30)、時間刻み (0.25/0.5/1.0 h)、開始・終了時刻 |
| **🚌 車両性能** | バッテリ容量 [kWh]、初期SOC [%]、SOC下限 [%]、電費 [km/kWh] |
| **🔌 充電設備** | 充電拠点数、普通/急速充電出力と台数、充電効率 |
| **☀️ PV・電力料金** | PV 有効/無効、PV出力倍率、電力料金モード（TOU/一律） |
| **🔧 拡張オプション** | 終端SOC条件、デマンドチャージ（契約電力上限） |

> 🔁「設定を適用」を押すたびに便・PV・料金が自動生成されます（シード固定で再現性あり）。

#### JSON インポートモード

既存の `ebus_prototype_config.json` を読み込みます。

- **ファイルアップロード**: 「設定JSONをアップロード」から任意の JSON ファイルを選択
- **デフォルト読み込み**: 「デフォルト JSON を読み込む」ボタンでプロジェクト内の `ebus_prototype_config.json` を即時読み込み

---

### Step 2: 設定概要を確認する

設定適用後、メインエリア上部に概要が表示されます。

- **5つのメトリクス**: バス台数、便数、時間スロット数、充電拠点数、PV有効/無効
- **詳細設定の展開**: 「🔍 詳細設定を表示」をクリックするとバス・便・充電器・エネルギーの詳細テーブルを確認可能
- **設定JSONのエクスポート**: 「📦 設定 JSON をエクスポート」から現在の設定を JSON ファイルとしてダウンロード可能

---

### Step 3: ソルバーを選んで求解する

#### Gurobi (MILP) タブ

Gurobi がインストールされている環境でのみ使用可能です。

1. **ステージ**を選択（`full_with_pv` が完全モデル）
2. **制限時間** [秒] と **MIP Gap** を設定
3. 「**▶️ Gurobi で求解**」をクリック
4. 最適解 or 制限時間内最良解が表示される

| ステージ | 説明 |
|---|---|
| `assignment_only` | 便割当の実行可能性確認のみ |
| `assignment_plus_soc` | + SOC 推移・上下限 |
| `assignment_soc_charging` | + 充電スケジュール |
| `full_with_pv` | + PV/買電最適化（完全モデル） |

#### ALNS タブ

大規模問題の主力ソルバー。Gurobi 不要で動作します。

1. 反復回数・温度・冷却率・破壊率などを調整
2. 「**▶️ ALNS で求解**」をクリック
3. リアルタイムでプログレスバーとコストが更新される
4. 収束曲線（現在解 vs 最良解）が表示される

#### GA タブ

遺伝的アルゴリズム。ALNS との比較用に使います。

1. 集団サイズ・世代数・交叉率・突然変異率を調整
2. 「**▶️ GA で求解**」をクリック
3. 収束曲線（世代ごとの最良コスト）が表示される

#### ABC タブ

人工蜂コロニーアルゴリズム。GA・ALNS との比較用です。

1. コロニーサイズ・サイクル数・limit を調整
2. 「**▶️ ABC で求解**」をクリック
3. 収束曲線が表示される

---

### Step 4: 比較タブでソルバーを比較する

複数ソルバーを実行した後「**比較**」タブを開くと:

| 表示内容 | 説明 |
|---|---|
| **KPI 比較テーブル** | 全ソルバーの目的関数値・計算時間・KPIを横並び比較 |
| **目的関数値 棒グラフ** | ソルバー別コスト [円] の視覚比較 |
| **計算時間 棒グラフ** | ソルバー別実行時間 [秒] の視覚比較 |
| **収束曲線比較** | ALNS/GA/ABC の収束推移を重ねて表示（2つ以上実行時） |
| **SOC推移比較** | 全ソルバーの SOC 軌跡を重ねて比較（SOCあり解のみ） |

---

### Step 5: 結果を保存する

各ソルバータブの結果表示エリア下部に「**結果 JSON をダウンロード**」ボタンがあります。  
ソルバー名・ステータス・便割当・SOC系列・PV/買電データが JSON 形式で保存されます。

---

### Step 6: 路線を管理する（🚌 路線管理タブ）

「**🚌 路線管理**」タブでは、複数路線の停留所と時刻表を管理できます。

1. **路線の追加**: 路線一覧テーブルの下にある「新しい路線を追加」フォームで路線ID・路線名・管理営業所などを入力
2. **停留所の配置**: 入力モードを「地図入力」に切り替え、地図上をクリックして停留所を順に配置（始点→途中→終点）
   - 地図なし環境では「テーブル編集」モードで手入力可能
3. **片道フラグ**: 各停留所に `outbound_only`（往路のみ）/ `inbound_only`（復路のみ）を設定可能
4. **復路の自動生成**: 「復路を自動生成」ボタンで往路の停留所を逆順にコピー（`outbound_only` の停留所は除外）
5. **時刻表の編集**: 便ごとの出発・到着時刻、運行種別（平日/休日/全日）を設定
6. **保存**: 「保存」ボタンで `routes.csv` / `stops.csv` / `timetable.csv` に書き出し

> 地図入力には `folium` と `streamlit-folium` が必要です: `pip install folium streamlit-folium`

### Step 7: 営業所・車両・行路を管理する（🏢 営業所管理タブ）

「**🚌 路線・営業所管理**」タブの「**🏢 営業所管理**」サブタブでは、営業所・車両・行路（便チェーン）を管理できます。

1. **営業所の選択**: 左カラムの一覧ボタンで選択、または右カラムの地図マーカーをクリックして選択
2. **営業所の追加**: 地図の空地をクリックすると追加フォームに緯度・経度がプリフィル。名称・所在地・駐車容量を入力して保存
3. **営業所の編集**: 選択後に「✏️ 営業所属性を編集」エクスパンダーを開いて名称・住所・台数・kW 等を変更、「💾 保存」で確定
4. **テーブル一括編集**: 「📋 テーブルで一括編集」エクスパンダーで `st.data_editor` により全営業所を一覧編集
5. **車両の管理**: 各営業所に車両を登録（車両タイプ、バッテリー容量、電費、担当路線）
6. **行路の編成**: 時刻表から便を選んで便チェーン（行路）を作成。1台の車両が1日に複数便を担当する順序を定義

> 地図選択には `folium` と `streamlit-folium` が必要です: `pip install folium streamlit-folium`

---

### よくあるエラーと対処法

| エラー | 原因 | 対処法 |
|---|---|---|
| `AttributeError: 'NoneType' object has no attribute 'num_buses'` | `python app/main.py` で直接起動した | `streamlit run app/main.py` で起動する |
| `ModuleNotFoundError: No module named 'streamlit'` | 依存パッケージ未インストール | `pip install -r requirements.txt` を実行 |
| `⚠️ Gurobi がインストールされていません` | gurobipy または Gurobi ライセンス未設定 | ALNS/GA/ABC タブを使用する（Gurobi 不要） |
| `❌ 実行不能` | 制約が厳しすぎる（SOC 下限が高い等） | SOC 下限を下げる、バス台数を増やす、便数を減らす |
| 収束が遅い | 反復回数や集団サイズが小さい | 各ソルバーの反復数・集団サイズを増やす |

---

## 新アーキテクチャ (`src/` モジュール)

### 概要

`src/` ディレクトリには、修士論文の仕様書に準拠した**新しいモジュール型アーキテクチャ**が実装されています。CSV ベースのデータ入力、モード切替（先行研究再現 + 提案手法）、シミュレータ検証、実行可能性診断を統合しています。

### データパイプライン

```
CSV (data/toy/*.csv)
  ↓  data_loader.py
ProblemData
  ↓  model_sets.py
ModelSets (K_BEV, K_ICE, R, C, T, ...)
  ↓  parameter_builder.py
DerivedParams (task_energy_bev, task_lut, vehicle_lut, ...)
  ↓  model_factory.py / milp_model.py
Gurobi Model → MILPResult
  ↓  simulator.py
SimulationResult + FeasibilityReport
  ↓  result_exporter.py
CSV / JSON / Markdown
```

### モード一覧

| モード | 出典 | 特徴フラグ |
|---|---|---|
| `mode_A_journey_charge` | He et al. (2023) | 便割当固定 (greedy) + 充電LP のみ |
| `mode_B_resource_assignment` | Chen et al. (2023) | 便割当+充電 MILP、PV/V2G なし |
| `thesis_mode` | 提案手法 | 全機能有効: PV、デマンド料金、V2G、電池劣化 |

### CLI 実行

```bash
# 基本実行 (thesis_mode)
python run_experiment.py

# モード指定
python run_experiment.py --mode mode_A_journey_charge
python run_experiment.py --mode mode_B_resource_assignment

# オプション
python run_experiment.py --config config/experiment_config.json --time-limit 300 --mode thesis_mode
```

### Streamlit での利用

Streamlit アプリの「🆕 新アーキ (src/)」タブから新モジュールを利用できます:

1. config JSON パスを指定（デフォルト: `config/experiment_config.json`）
2. PV / デマンド料金 / V2G / 電池劣化のトグルを設定
3. 「📥 データ読込」でデータをロード
4. モデルモード（mode_A / mode_B / thesis_mode）を選択
5. ソルバー（Gurobi MILP / ALNS / 両方）を選択
6. 「▶️ 求解実行」で最適化 → 結果・グラフ・実行可能性診断を確認

### データ形式 (CSV)

`data/toy/` に含まれるサンプルデータ:

| ファイル | 内容 |
|---|---|
| `vehicles.csv` | 車両定義 (vehicle_id, type, cap_kwh, soc_init, soc_min, soc_max, ...) |
| `tasks.csv` | タスク定義 (task_id, distance_km, energy_kwh, start_time_idx, end_time_idx, ...) |
| `chargers.csv` | 充電器定義 (charger_id, site_id, power_kw, count, ...) |
| `sites.csv` | 拠点定義 (site_id, grid_capacity_kw, pv_capacity_kw, ...) |
| `tou_rates.csv` | TOU 電力単価 (time_idx, price_yen_per_kwh) |
| `pv_generation.csv` | PV 発電量 (time_idx, site_id, gen_kw) |
| `vehicle_task_feasibility.csv` | 車両–タスク割当可否 |
| `vehicle_charger_access.csv` | 車両–充電器アクセス可否 |
| `weights.csv` | 目的関数の重み係数 (9 項目) |

設定ファイル `config/experiment_config.json` でデータディレクトリと計画パラメータを記述:

```json
{
  "data_dir": "data/toy",
  "num_periods": 64,
  "delta_t_hour": 0.25,
  "enable_pv": true,
  "enable_demand_charge": true,
  "enable_v2g": false,
  "enable_battery_degradation": true
}
```

### 目的関数（9 項目加重和）

$$\min \sum_{i=1}^{9} w_i \cdot f_i(x)$$

| # | 項目 | 説明 |
|---|---|---|
| 1 | 電力量料金 | TOU 単価 × 系統買電量 |
| 2 | デマンド料金 | ピーク電力 × デマンド単価 |
| 3 | ICE 燃料費 | 軽油単価 × 燃料消費量 |
| 4 | ICE CO₂コスト | CO₂排出量 × 炭素価格 |
| 5 | 電池劣化コスト | 充電電力量 × 劣化係数 |
| 6 | 未担当ペナルティ | 未割当タスク数 × ペナルティ |
| 7 | PV 余剰ペナルティ | PV 発電量 − PV 利用量 |
| 8 | V2G 収益 (負コスト) | 放電量 × 売電単価 |
| 9 | 終端 SOC 偏差 | SOC 末値との差分ペナルティ |

### シミュレーション & 実行可能性診断

`simulator.py` により MILP/ALNS 結果を独立検証:

- **SOC トレース再計算**: 全 BEV の時系列 SOC を再構築
- **電力収支検証**: 系統受電・PV 利用・デマンドピークを算出
- **6 カテゴリ診断** (`FeasibilityReport`):
  1. タスク重複違反
  2. SOC 下限違反
  3. SOC 上限違反
  4. 充電器容量超過
  5. 運行中充電
  6. 系統容量超過

---

## v3 アーキテクチャ — Route-Editable 2 層構造 (spec_v3 / agent_route_editable)

### 設計思想

先行研究モデルは「便リスト」を固定入力として受け取りますが、本研究では **路線・停留所・セグメント** までを明示的にモデル化し、路線編集 → アクチュアルな便生成 → 最適化という連続フローを実現します。

```
[Layer A: route-detail 層]                    [Layer B: trip abstraction 層]
Route / Terminal / Stop
  ↓ RouteVariant (segment_id_list)
Segment (distance_km, grade_avg_pct, ...)   ──→  GeneratedTrip (energy_kwh, fuel_l, ...)
  ↓ TimetablePattern (headway, start, end)         ↓
ServiceCalendarRow (date → service_day_type)   DeadheadArc (空車回送弧)
                                                   ↓
                                            最適化モデル (milp_model.py)
```

### エネルギーモデル 3 レベル

| Level | 計算方法 | 用途 |
|---|---|---|
| 0 | `base_rate × distance` | 先行研究再現・固定入力 |
| 1 | 路線係数線形モデル (距離・勾配・停留所・乗客・渋滞・HVAC) | 標準解析 |
| 2 | セグメント集計 (stops を 1 区間ずつ積算) | 高精度・区間感度 |

### パワートレイン比較

同一の路線 (Layer A) データから BEV / ICE / HEV を横並びで評価:

- **BEV**: `estimate_trip_energy_bev()` → `energy_kwh` (充電スケジュールに入力)
- **ICE**: `estimate_trip_fuel_ice()` → `fuel_l` (燃料コスト比較)
- **HEV**: `estimate_trip_fuel_hev()` (ICE × efficiency)

### 新モード一覧 (spec_v3 §8)

| モード | 説明 | エネルギーモデル | 特記 |
|---|---|---|---|
| `mode_simple_reproduction` | 先行研究再現 (固定 trip 入力) | Level 0 | PV/V2G/劣化/デマンド料金 無効 |
| `mode_route_sensitivity` | 路線距離スケーリング感度 | Level 1 | `route_length_multiplier`: 0.5〜2.0 |
| `mode_uncertainty_eval` | シナリオサンプリング + ALNS ループ | Level 1 | `n_scenarios` 件の ScenarioTripEnergy |
| `thesis_mode_route_editable` | 完全 2 層構造 + BEV/ICE 比較 | Level 1/2 | `route_edit_rules` で路線動的編集 |

### Pipeline CLI (spec_v3 §5)

```bash
# Step 1: route_master/fleet CSVから GeneratedTrip と DeadheadArc を生成
python -m src.pipeline.build_inputs --config config/experiment_config.json

# Step 2: モード指定して最適化ソルバー実行
python -m src.pipeline.solve --config config/experiment_config.json --mode thesis_mode_route_editable

# Step 3: シミュレーション評価 (SOC トレース + 実行可能性診断)
python -m src.pipeline.simulate --config config/experiment_config.json

# Step 4: KPI レポート生成 (Markdown + CSV → outputs/)
python -m src.pipeline.report --config config/experiment_config.json
```

### v3 データフォルダ構成

```
data/
├── route_master/               # Layer A: 路線マスタ (手動編集可能)
│   ├── routes.csv              # 路線定義 (route_id, total_distance_km, ...)
│   ├── terminals.csv           # ターミナル/デポ (has_depot, has_charger, ...)
│   ├── stops.csv               # 停留所 (route / direction / sequence)
│   ├── segments.csv            # 区間 (distance_km, grade_avg_pct, signal_count, ...)
│   ├── route_variants.json     # 運行パターン (segment_id_list)
│   ├── timetable_patterns.csv  # ダイヤパターン (headway_min, start_time, end_time)
│   └── service_calendar.csv    # 運行日種別 (date → weekday/holiday)
├── fleet/
│   ├── vehicle_types.csv       # 車種定義 (BEV/ICE/HEV, battery/fuel params)
│   └── vehicles.csv            # 個別車両 (depot_id, initial_soc_kwh)
├── infra/
│   ├── charger_sites.csv       # 充電拠点 (max_grid_kw, pv_capacity_kw)
│   ├── chargers.csv            # 充電器 (power_kw, compatible_vehicle_types)
│   └── depot_grid_limits.csv   # 系統契約電力 (contract_demand_kw)
├── external/
│   ├── tariff.csv              # TOU 電力単価 (period_start → price_jpy_kwh)
│   ├── weather_timeseries.csv  # 気象データ (temp, rain, wind)
│   ├── passenger_load_profile.csv  # 乗客荷重プロファイル
│   └── traffic_profile.csv     # 交通渋滞プロファイル
└── derived/                    # 自動生成 (build_inputs が出力)
    ├── generated_trips.csv     # Layer B: GeneratedTrip 一覧
    ├── deadhead_arcs.csv       # DeadheadArc 一覧
    └── scenario_trip_energy.csv  # シナリオ別エネルギー
```

### v3 設定フィールド (config/experiment_config.json)

```json
{
  "mode": "thesis_mode_route_editable",
  "energy_model_level": 1,
  "fuel_model_enabled": true,
  "allow_deadhead": true,
  "allow_partial_charging": true,
  "service_day_type": "weekday",
  "route_length_multiplier": 1.0,
  "uncertainty": {
    "enabled": false,
    "n_scenarios": 10,
    "seed": 42,
    "energy_range": [0.85, 1.15],
    "travel_time_range": [0.90, 1.20]
  },
  "route_edit_rules": {
    "segment_distance_overrides": {},
    "powertrain_comparison": ["BEV", "ICE", "HEV"]
  }
}
```

`dispatch_preprocess` options reference: `docs/dispatch_preprocess_config.md`

---

## ファイル構成

```
master-course/
├── src/                              # 🆕 新アーキテクチャ (仕様書準拠)
│   ├── __init__.py
│   ├── data_schema.py
│   ├── data_loader.py
│   ├── model_sets.py
│   ├── parameter_builder.py
│   ├── objective.py
│   ├── milp_model.py
│   ├── model_factory.py              # モード切替 (mode_A / mode_B / thesis_mode / v3 新4モード)
│   ├── solver_runner.py
│   ├── solver_alns.py
│   ├── simulator.py
│   ├── visualization.py
│   ├── result_exporter.py
│   ├── schemas/                      # 🆕 v3 エンティティ定義
│   │   ├── __init__.py
│   │   ├── route_entities.py         # Route, Terminal, Stop, Segment, RouteVariant, GeneratedTrip, DeadheadArc
│   │   ├── fleet_entities.py         # VehicleType (BEV/ICE/HEV/PHEV), VehicleInstance
│   │   └── trip_entities.py          # ScenarioTripEnergy
│   ├── preprocess/                   # 🆕 v3 前処理パイプライン
│   │   ├── __init__.py
│   │   ├── route_builder.py          # 路線ネットワーク検証・統計
│   │   ├── timetable_generator.py    # 発車時刻生成・運行日展開
│   │   ├── trip_generator.py         # GeneratedTrip 生成
│   │   ├── energy_model.py           # BEV エネルギー Level 0/1/2
│   │   ├── fuel_model.py             # ICE/HEV 燃料推定
│   │   ├── deadhead_builder.py       # DeadheadArc 生成・接続行列
│   │   └── scenario_generator.py     # 不確実性シナリオ生成
│   ├── pipeline/                     # 🆕 v3 CLI パイプライン
│   │   ├── __init__.py
│   │   ├── build_inputs.py           # route_master CSV → generated_trips, deadhead_arcs
│   │   ├── solve.py                  # モード別ソルバー実行
│   │   ├── simulate.py               # シミュレーション評価
│   │   └── report.py                 # KPI レポート生成
│   └── constraints/
│       ├── __init__.py
│       ├── assignment.py
│       ├── charging.py
│       ├── charger_capacity.py
│       ├── energy_balance.py
│       ├── pv_grid.py
│       ├── battery_degradation.py
│       └── optional_v2g.py
├── app/                              # Streamlit GUI
│   ├── main.py
│   ├── model_core.py
│   ├── solver_gurobi.py
│   ├── solver_alns.py
│   ├── solver_ga.py
│   ├── solver_abc.py
│   └── visualizer.py
├── config/
│   └── experiment_config.json        # 実験設定 JSON (v3 フィールド追加済み)
├── data/
│   ├── route_master/                 # 🆕 v3 路線マスタ CSV
│   ├── fleet/                        # 🆕 v3 車両定義 CSV
│   ├── infra/                        # 🆕 v3 充電インフラ CSV
│   ├── external/                     # 🆕 v3 外部データ (TOU/気象/乗客/交通)
│   ├── derived/                      # 🆕 v3 自動生成 (build_inputs が出力)
│   └── toy/                          # 既存サンプルデータ (旧アーキ用)
├── constant/                         # 研究資料
├── run_experiment.py                 # CLI エントリポイント
├── requirements.txt
└── README.md
```

---

## 変数仕様書

### 集合 (Sets)

| 記号 | Python キー | 説明 |
|---|---|---|
| $B$ | `buses` | バス集合 |
| $R$ | `trips` | 便集合 |
| $T$ | `range(num_periods)` | 時間区間集合 ( $0, 1, \ldots, T_{max}-1$ ) |
| $C$ | `depots` | 充電拠点集合 |
| $S$ | `charger_types` | 充電器種別集合 (`"slow"`, `"fast"`) |

### パラメータ (Parameters)

#### バス関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| バッテリ容量 | `cap_kwh` | float | kWh | バス $b$ の公称バッテリ容量 |
| 初期 SOC | `soc_init_kwh` | float | kWh | 計画開始時の SOC |
| SOC 下限 | `soc_min_kwh` | float | kWh | 安全のため下回ってはならない SOC |
| SOC 上限 | `soc_max_kwh` | float | kWh | 過充電防止上限（通常 = `cap_kwh`） |
| 電費 | `efficiency_km_per_kwh` | float | km/kWh | BEV の走行効率 |
| 燃費 | `fuel_efficiency_km_per_l` | float | km/L | ICE 比較用 |
| CO2 原単位 | `co2_g_per_km` | float | g/km | CO2 排出原単位 |

#### 便関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| 開始時刻 | `start_t` | int | — | 便 $r$ の開始時刻インデックス |
| 終了時刻 | `end_t` | int | — | 便 $r$ の終了時刻インデックス |
| 消費電力量 | `energy_kwh` | float | kWh | 便 $r$ 全体の走行消費電力量 |
| 走行距離 | `distance_km` | float | km | ICE コスト算出用 |
| 出発地 | `start_node` | str | — | 便の出発拠点 |
| 到着地 | `end_node` | str | — | 便の到着拠点 |

#### 充電器関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| 充電出力 | `power_kw` | float | kW | 充電器 1 口の定格出力 |
| 台数 | `count` | int | — | 同時利用可能台数 |
| 充電効率 | `efficiency` | float | — | 充電効率（0.0〜1.0、通常 0.95） |

#### エネルギー関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| PV 発電量 | `pv_gen_kwh[t]` | float | kWh | 時刻 $t$ の PV 発電可能量 |
| 電力単価 | `grid_price_yen_per_kwh[t]` | float | 円/kWh | 時刻 $t$ の系統電力単価（TOU） |
| 時間刻み | `delta_h` | float | h | 1 スロットの長さ（0.25, 0.5, 1.0） |
| 充電効率 | `charge_efficiency` | float | — | グローバル充電効率 |
| 軽油単価 | `diesel_yen_per_l` | float | 円/L | ICE 比較用の燃料単価 |

#### フラグ・オプション

| パラメータ | Python キー | 型 | 説明 |
|---|---|---|---|
| PV 有効 | `enable_pv` | bool | PV 発電を考慮するか |
| 終端 SOC | `enable_terminal_soc` | bool | 計画末尾の SOC 下限を課すか |
| 終端 SOC 値 | `terminal_soc_kwh` | float? | 終端 SOC 下限値 [kWh] |
| デマンドチャージ | `enable_demand_charge` | bool | 契約電力制約を導入するか |
| 契約電力 | `contract_power_kw` | float? | 契約電力上限 [kW] |

### 決定変数 (Decision Variables)

| 変数 | Python 名 | 型 | 説明 |
|---|---|---|---|
| $x_{b,r}$ | `x[b,r]` | Binary | バス $b$ が便 $r$ を担当するなら 1 |
| $\text{soc}_{b,t}$ | `soc[b,t]` | Continuous | 時刻 $t$ のバス $b$ の SOC [kWh] |
| $y_{b,c,s,t}$ | `y[b,c,s,t]` | Binary | バス $b$ が時刻 $t$ に拠点 $c$・種別 $s$ で充電するなら 1 |
| $e_{b,c,s,t}$ | `e[b,c,s,t]` | Continuous $\geq 0$ | 充電電力量 [kWh] |
| $\text{pv\_use}_t$ | `pv_use[t]` | Continuous $\geq 0$ | PV 利用量 [kWh] |
| $\text{grid\_buy}_t$ | `grid_buy[t]` | Continuous $\geq 0$ | 系統買電量 [kWh] |

### 目的関数

$$\min \sum_{t \in T} \text{grid\_price}[t] \times \text{grid\_buy}[t]$$

系統電力購入コストを最小化する。

### 制約一覧

| No. | 制約名 | 数式 | 実装ステージ |
|---|---|---|---|
| 1 | 便の一意割当 | $\sum_{b} x_{b,r} = 1 \quad \forall r$ | `assignment_only` |
| 2 | 重複便禁止 | $x_{b,r_1} + x_{b,r_2} \leq 1 \quad \forall b, (r_1,r_2) \in \text{overlap}$ | `assignment_only` |
| 3 | 初期 SOC | $\text{soc}_{b,0} = \text{soc\_init}[b]$ | `assignment_plus_soc` |
| 4 | SOC 下限 | $\text{soc}_{b,t} \geq \text{soc\_min}[b]$ | `assignment_plus_soc` |
| 5 | SOC 上限 | $\text{soc}_{b,t} \leq \text{soc\_max}[b]$ | `assignment_plus_soc` |
| 6 | SOC 推移 | $\text{soc}_{b,t+1} = \text{soc}_{b,t} - \text{drive}_{b,t} + \eta \sum_{c,s} e_{b,c,s,t}$ | `assignment_plus_soc` |
| 7 | 充電量連動 | $e_{b,c,s,t} \leq P_{c,s} \cdot \Delta h \cdot y_{b,c,s,t}$ | `assignment_soc_charging` |
| 8 | 充電器台数上限 | $\sum_{b} y_{b,c,s,t} \leq \text{count}[c][s]$ | `assignment_soc_charging` |
| 9 | 同時多拠点禁止 | $\sum_{c,s} y_{b,c,s,t} \leq 1$ | `assignment_soc_charging` |
| 10 | 運行中充電禁止 | $\text{running}_{b,t} + \sum_{c,s} y_{b,c,s,t} \leq 1$ | `assignment_soc_charging` |
| 11 | 位置整合 | $y_{b,c,s,t} \leq \text{allowed}[b][c][t]$ | `assignment_soc_charging` |
| 12 | PV 利用上限 | $\text{pv\_use}_t \leq \text{pv\_gen}[t]$ | `full_with_pv` |
| 13 | 電力収支 | $\sum_{b,c,s} e_{b,c,s,t} = \text{pv\_use}_t + \text{grid\_buy}_t$ | `full_with_pv` |
| 14 | 終端 SOC | $\text{soc}_{b,T} \geq \text{soc\_terminal}$ | オプション |
| 15 | デマンドチャージ | $\text{grid\_buy}_t / \Delta h \leq P_{\text{contract}}$ | オプション |

---

## Gurobi (MILP) ソルバー

### ステージ別実行

段階的にモデルを構築・デバッグできます:

| ステージ | 含まれる制約 | 用途 |
|---|---|---|
| `assignment_only` | 便割当、重複禁止 | 便割当だけが成立するか確認 |
| `assignment_plus_soc` | + SOC 推移、上下限 | 電池残量込みで成立するか確認 |
| `assignment_soc_charging` | + 充電変数、充電器容量、位置整合 | 充電スケジュールの妥当性 |
| `full_with_pv` | + PV、電力収支、コスト最適化 | 完全モデル |

### Gurobi パラメータ

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `time_limit_sec` | 300.0 | 求解制限時間 [秒] |
| `mip_gap` | 0.01 | MIP ギャップ閾値（1% で十分近似的に最適） |
| `verbose` | False | Gurobi のログを出力するか |

---

## ALNS ソルバー

### アーキテクチャ

```
外側: ALNS（便割当 x の探索）
  ├── 破壊オペレータ
  │   ├── random_destroy: ランダムに便を除去
  │   ├── worst_destroy:  消費電力量の大きい便を優先除去
  │   └── related_destroy: 同一バスの便をまとめて除去
  │
  ├── 修復オペレータ
  │   ├── greedy_repair: 負荷均等化で貪欲割当
  │   └── random_repair: ランダム割当
  │
  └── 内側: LP/MILP（充電量・SOC・PV・買電を最適化）
      ├── Gurobi LP（利用可能な場合）
      └── scipy.linprog（フォールバック）
```

### ALNS ハイパーパラメータ

| パラメータ | Python キー | デフォルト | 説明 |
|---|---|---|---|
| 最大反復回数 | `max_iterations` | 500 | ALNS の最大ループ回数 |
| 改善なし上限 | `max_no_improve` | 100 | 改善なしで早期終了する回数 |
| 初期温度 | `init_temp` | 1000.0 | SA の初期温度 |
| 冷却率 | `cooling_rate` | 0.995 | 温度の減衰率 (0.99〜0.999) |
| 最小破壊率 | `destroy_ratio_min` | 0.1 | 最小破壊比率 |
| 最大破壊率 | `destroy_ratio_max` | 0.4 | 最大破壊比率 |
| セグメント長 | `segment_length` | 50 | 重み更新の間隔 |
| 最良スコア | `score_best` | 10.0 | 全体最良解更新時のスコア |
| 改善スコア | `score_better` | 5.0 | 現在解改善時のスコア |
| 受理スコア | `score_accept` | 2.0 | SA で受理時のスコア |
| 棄却スコア | `score_reject` | 0.0 | 棄却時のスコア |
| 重み減衰 | `decay_factor` | 0.8 | 重み更新の減衰係数 |
| 乱数シード | `seed` | 42 | 再現性のための乱数シード |

---

## GA（遺伝的アルゴリズム）ソルバー

### アーキテクチャ

```
染色体 = trip_id → bus_id マッピング（AssignmentSolution と同一表現）

操作フロー:
  ├── 初期集団: 貪欲法 + ランダム可能割り当て
  ├── 選択: トーナメント選択
  ├── 交叉: 一様交叉（便ごとに50%で親切替）
  ├── 突然変異: ランダム便の再割り当て（1-3便）
  ├── 修復: オーバーラップ解消
  ├── 評価: evaluate_assignment()（内側LP/ヒューリスティック）
  └── エリート保存 → 次世代
```

### GA ハイパーパラメータ

| パラメータ | Python キー | デフォルト | 説明 |
|---|---|---|---|
| 集団サイズ | `population_size` | 30 | 各世代の個体数 |
| 最大世代数 | `max_generations` | 200 | 進化の最大世代数 |
| 改善なし上限 | `max_no_improve` | 50 | 改善なしで早期終了する世代数 |
| 交叉率 | `crossover_rate` | 0.85 | 交叉を実行する確率 |
| 突然変異率 | `mutation_rate` | 0.15 | 突然変異を実行する確率 |
| トーナメントサイズ | `tournament_size` | 3 | トーナメント選択の候補数 |
| エリート数 | `elitism_count` | 2 | 次世代にそのまま保存する最良個体数 |
| 乱数シード | `seed` | 42 | 再現性のための乱数シード |

---

## ABC（人工蜂コロニー）ソルバー

### アーキテクチャ

```
食料源 = trip_id → bus_id マッピング（AssignmentSolution と同一表現）

サイクルループ:
  ├── 雇用蜂フェーズ: 各食料源の近傍探索（便の再割り当て）
  │   └── 貪欲選択: 近傍が改善なら採用
  ├── 傍観蜂フェーズ: 適応度ベースのルーレット選択 → 近傍探索
  │   └── 高適応度の食料源ほど選ばれやすい
  ├── 偵察蜂フェーズ: trial ≥ limit の食料源を破棄 → ランダム再生成
  └── 最良解更新
```

### ABC ハイパーパラメータ

| パラメータ | Python キー | デフォルト | 説明 |
|---|---|---|---|
| コロニーサイズ | `colony_size` | 30 | 食料源数（= 雇用蜂数 = 傍観蜂数） |
| 最大サイクル数 | `max_iterations` | 200 | 最大反復サイクル数 |
| 改善なし上限 | `max_no_improve` | 50 | 全体最良解の改善なし上限 |
| limit | `limit` | 20 | 個別食料源の改善なし回数 → 偵察蜂発動 |
| 近傍変更便数 | `perturbation_size` | 3 | 近傍生成で再割り当てする便の数 |
| 乱数シード | `seed` | 42 | 再現性のための乱数シード |

---

## ソルバー比較ガイド

| ソルバー | 分類 | 解の品質 | 計算速度 | スケーラビリティ | 用途 |
|---|---|---|---|---|---|
| **Gurobi (MILP)** | 厳密解法 | 最適解 | △（問題規模に依存） | 中規模まで | 基準解の取得、小規模問題 |
| **ALNS** | メタヒューリスティクス | 近似最適 | ○ | 大規模可能 | 大規模問題の主力ソルバー |
| **GA** | 進化的アルゴリズム | 近似 | ○ | 中〜大規模 | ALNSとの比較、多様解探索 |
| **ABC** | 群知能アルゴリズム | 近似 | ○ | 中〜大規模 | 局所最適回避の比較 |

> **比較タブ**で全ソルバーの目的関数値・計算時間・収束曲線を一覧比較できます。

---

## 評価指標 (KPI)

| 指標 | 説明 | 単位 |
|---|---|---|
| 目的関数値 | 総系統買電コスト | 円 |
| 総買電量 | 全時間帯の系統買電量合計 | kWh |
| PV 利用量 | PV 自家消費量合計 | kWh |
| 最低 SOC | 全バス・全時刻の最低 SOC | kWh |
| 最大同時充電台数 | 充電器の最大同時稼働数 | 台 |
| 計算時間 | ソルバーの実行時間 | 秒 |

---

## 感度分析で変更可能なパラメータ

研究計画（`ebus_asset_factors.json`）に基づく感度分析軸:

| 軸 | GUI での変更方法 | 推奨範囲 |
|---|---|---|
| PV 容量 | PV出力倍率スライダー | 0.0 〜 5.0 |
| BEV 比率 | バス台数 (将来: ICE/BEV 混在を拡張) | 0% 〜 100% |
| 充電器台数 | 普通/急速充電器台数 | 0 〜 10 |
| 契約電力上限 | デマンドチャージオプション | 100 〜 300 kW |
| 時間帯別電力単価 | TOU / 一律 モード切替 | 自由設定 |
| 軽油単価 | 軽油単価入力 | 130 〜 160 円/L |

---

## 既存ファイルとの互換性

- `ebus_prototype_config.json` → 「JSON インポート」で直接読み込み可能
- `solve_ebus_gurobi.py` → 同等の定式化を `solver_gurobi.py` で再実装
- `ebus_asset_factors.json` → 車両カタログ情報を参照可能（将来拡張で自動マージ予定）

---

## 今後の拡張予定

- [x] GA（遺伝的アルゴリズム）ソルバーの追加
- [x] ABC（人工蜂コロニー）ソルバーの追加
- [x] 全ソルバーのコスト・計算時間比較機能
- [x] BEV/ICE 混成フリートの明示的サポート（`src/` で実装済み）
- [x] バッテリ劣化コストの簡易モデル（`src/` で実装済み）
- [x] V2G 拡張（`src/` で実装済み）
- [x] CSV ベースデータ入力 + モード切替 + CLI 実行（`src/` + `run_experiment.py`）
- [x] シミュレータ検証 + 実行可能性診断（`src/simulator.py`）
- [x] ALNS の新データ構造対応（`src/solver_alns.py`）
- [x] **v3 2層 route-editable アーキテクチャ** (`src/schemas/`, `src/preprocess/`)
- [x] **エネルギーモデル Level 0/1/2** + ICE/HEV 燃料モデル (`src/preprocess/energy_model.py`, `fuel_model.py`)
- [x] **Pipeline CLI** `build_inputs → solve → simulate → report` (`src/pipeline/`)
- [x] **4 新モード**: `mode_simple_reproduction`, `mode_route_sensitivity`, `mode_uncertainty_eval`, `thesis_mode_route_editable`
- [x] **サンプルデータ** `data/route_master/`, `data/fleet/`, `data/infra/`, `data/external/` 作成
- [x] **路線プロフィール管理**（`🚌 路線管理` タブ）: 複数路線対応、地図クリック停留所配置、片道フラグ、復路自動生成、営業所紐付け
- [x] **営業所・車両管理**（`🏢 営業所管理` タブ）: 複数営業所、車両所属管理、行路（便チェーン）編成
- [x] **CSV スキーマ拡張**: `routes.csv` に `garage_id`、`stops.csv` に `outbound_only`/`inbound_only` 列追加
- [x] **旧エディタ非推奨化**: サイドバー二重呼び出し削除、`🗺️ 路線詳細` タブに非推奨警告
- [x] **タブ再編成**: 13タブ → 5タブ（`⚙️ 設定` / `🔬 ソルバー` / `📊 比較・専用` / `🗺️ 路線詳細` / `🚌 路線・営業所管理`）＋ 各種サブタブ
- [x] **営業所マップ選択**: 地図から営業所を選択・位置入力（folium マーカークリック → 選択、空地クリック → 緯度経度プリフィル）
- [ ] HEV 車両の MILP モデル統合 (現在は燃料コスト比較のみ)
- [ ] セグメント自動生成を新エディタに統合（現在は旧エディタのみ対応）
- [ ] 充電拠点レイヤーを新エディタの地図に表示
- [ ] `route_edit_rules` による動的路線編集 UI (Streamlit 連携)
- [ ] バッチ感度分析（パラメータスイープ + Pareto フロンティア可視化）
- [ ] 結果の CSV/Excel エクスポート（`src/result_exporter.py` で一部対応済み）

---

## ライセンス

修士論文研究用の試作アプリケーションです。
