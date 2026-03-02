# E-Bus Sim 開発メモ

## アプリ概要

**E-Bus Sim**（電気バス最適化シミュレータ）は、PV出力を考慮した混成フリートの電気バス充電・運行スケジューリングを最適化する Streamlit アプリです。

- 起動コマンド: `streamlit run app/main.py`
- バージョン: v0.4.0

---

## 追加機能の設計方針

### 1. 路線プロフィール管理（`🚌 路線管理` タブ）

- **複数路線**を追加・編集・削除できる
- 各路線は「停留所リスト」と「時刻表（便単位の発着情報）」を保持する
- **行路（便チェーン）は路線側では管理しない** — 行路は営業所側が責任を持つ
- 地図入力（folium + streamlit-folium）に対応（ライブラリが未インストールでも手入力で動作する）

### 2. 営業所・車両プロフィール管理＋配車計画（`🏢 営業所管理` タブ）

- **複数営業所**を管理する
- 各営業所に**車両**を所属させる
- 時刻表から便を選んで**便チェーン（行路）**を編成する
- 路線間移動の許可/禁止を**営業所単位**で設定できる
- 便チェーン：ある便が終わったら同じまたは別路線の別運用に入る連鎖構造

---

## データ構造・CSVスキーマ

### `data/route_master/timetable.csv`

時刻表。便（trip）単位で発着情報を記録する。

| カラム | 説明 |
|--------|------|
| `trip_id` | 便ID（ユニーク） |
| `route_id` | 路線ID |
| `direction` | 方向（outbound / inbound） |
| `service_type` | 運行種別（weekday / saturday / holiday 等） |
| `dep_time` | 出発時刻（HH:MM） |
| `arr_time` | 到着時刻（HH:MM） |
| `from_stop_id` | 出発停留所ID |
| `to_stop_id` | 終着停留所ID |
| `travel_time_min` | 所要時間（分） |
| `notes` | 備考（始発・終発・ラッシュ等） |

### `data/operations/garages.csv`

営業所マスタ。

| カラム | 説明 |
|--------|------|
| `depot_id` | 営業所ID（ユニーク） |
| `depot_name` | 営業所名 |
| `city` | 所在市区町村 |
| `address` | 住所 |
| `lat` / `lon` | 緯度・経度 |
| `parking_capacity` | 駐車可能台数 |
| `grid_connection_kw` | 系統接続容量（kW） |
| `overnight_charging` | 夜間充電可否 |
| `has_workshop` | 整備工場の有無 |
| `notes` | 備考 |

### `data/operations/vehicles.csv`

車両マスタ。

| カラム | 説明 |
|--------|------|
| `vehicle_id` | 車両ID（ユニーク） |
| `vehicle_type` | 車両タイプ（BEV_large / BEV_mid 等） |
| `garage_id` | 所属営業所ID |
| `route_assignments` | 担当路線ID（カンマ区切り） |
| `battery_capacity_kwh` | バッテリー容量（kWh） |
| `soc_min_ratio` | SOC下限比率 |
| `soc_max_ratio` | SOC上限比率 |
| `efficiency_km_per_kwh` | 電費（km/kWh） |
| `status` | 稼働状況（active / inactive） |
| `notes` | 備考 |

### `data/operations/work_schedules.csv`

行路（便チェーン）マスタ。

| カラム | 説明 |
|--------|------|
| `work_id` | 行路ID（ユニーク） |
| `garage_id` | 担当営業所ID |
| `vehicle_id` | 担当車両ID |
| `service_date` | 運行日（YYYY-MM-DD） |
| `trips` | 便IDリスト（カンマ区切り、順序通り） |
| `total_trips` | 便数 |
| `start_time` | 行路開始時刻 |
| `end_time` | 行路終了時刻 |
| `total_km` | 総走行距離（km） |
| `notes` | 備考（朝行路・昼行路等） |

---

## ファイル一覧と役割

### 新規作成ファイル

| ファイル | 役割 |
|----------|------|
| `app/route_profile_editor.py` | 路線プロフィール管理エディタ。複数路線・停留所・時刻表編集・地図入力対応 |
| `app/depot_profile_editor.py` | 営業所・車両・行路（便チェーン）管理エディタ |
| `data/route_master/timetable.csv` | 時刻表CSVサンプル |
| `data/operations/garages.csv` | 営業所マスタCSVサンプル |
| `data/operations/vehicles.csv` | 車両マスタCSVサンプル |
| `data/operations/work_schedules.csv` | 行路（便チェーン）マスタCSVサンプル |

### 既存ファイル（参照・変更済み）

| ファイル | 役割 |
|----------|------|
| `app/main.py` | メインStreamlitアプリ。`🚌 路線管理` `🏢 営業所管理` タブを追加済み |
| `app/route_detail_editor.py` | 既存の路線詳細エディタ（単路線・停留所・デポ編集） |
| `app/map_editor.py` | 地図ベースエディタ（ターミナル・デポ・充電拠点・停留所） |
| `app/route_editor.py` | 旧ルートエディタ（CSV読込・編集・保存） |
| `data/route_master/routes.csv` | 既存路線マスタ |
| `data/route_master/stops.csv` | 既存停留所マスタ |
| `data/infra/depots.csv` | 既存デポ（充電拠点）マスタ |

### ディレクトリ構造

```
master-course/
├── app/
│   ├── main.py                    ← 🚌路線管理・🏢営業所管理タブ追加済み
│   ├── route_profile_editor.py    ← 新規作成
│   ├── depot_profile_editor.py    ← 新規作成
│   ├── route_detail_editor.py     ← 既存
│   ├── map_editor.py              ← 既存
│   └── route_editor.py            ← 既存
├── data/
│   ├── route_master/
│   │   ├── timetable.csv          ← 新規作成
│   │   ├── routes.csv             ← 既存
│   │   ├── stops.csv              ← 既存
│   │   └── ...
│   ├── operations/                ← 新規ディレクトリ
│   │   ├── garages.csv            ← 新規作成
│   │   ├── vehicles.csv           ← 新規作成
│   │   └── work_schedules.csv     ← 新規作成
│   └── infra/
│       └── depots.csv             ← 既存
└── DEVELOPMENT_NOTES.md           ← 本ファイル
```

---

## 起動方法

```bash
# 依存ライブラリのインストール
pip install streamlit pandas folium streamlit-folium

# アプリ起動
streamlit run app/main.py
```

地図入力機能（folium）がない環境でも、手入力モードでアプリは動作します。

---

## タブ構成（main.py）

| タブ | 内容 |
|------|------|
| ⚙️ 設定 | 問題設定・パラメータ入力 |
| 🔬 Gurobi (MILP) | Gurobi MILPソルバー |
| 🎡 ALNS | 適応的大近傍探索 |
| 🧬 GA | 遺伝的アルゴリズム |
| 🐝 ABC | 人工蜂群アルゴリズム |
| 🆕 新アーキ (src/) | 新アーキテクチャ |
| 📊 比較 | ソルバー比較 |
| 🎯 MILP専用 | MILP専用モード |
| 🔄 ALNS専用 | ALNS専用モード |
| ⚡ ALNS+MILP | ハイブリッドモード |
| 🗺️ 路線詳細 | 既存路線詳細エディタ（単路線） |
| 🚌 路線管理 | **新機能** 複数路線・時刻表管理 |
| 🏢 営業所管理 | **新機能** 営業所・車両・行路管理 |
