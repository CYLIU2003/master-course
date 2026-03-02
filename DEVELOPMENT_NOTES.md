# E-Bus Sim 開発メモ

## アプリ概要

**E-Bus Sim**（電気バス最適化シミュレータ）は、PV出力を考慮した混成フリートの電気バス充電・運行スケジューリングを最適化する Streamlit アプリです。

- 起動コマンド: `streamlit run app/main.py`
- バージョン: v0.4.0

---

## 変更履歴

### v2 — 路線プロフィールエディタ全面書き直し & タブ統合

**route_profile_editor.py を全面書き直し（v2）:**

- **左クリックで停留所を即追加**（フォーム入力不要、自動命名「停留所N」）
- **右クリックで最寄り停留所を削除**（Leaflet `contextmenu` イベントを JS 注入で捕捉）
- 各停留所に `outbound_only` / `inbound_only` フラグを設定可能
- 往路から復路を自動生成（`_generate_inbound_stops` 関数）。`outbound_only=True` の停留所は復路に含めない
- 路線ごとに `garage_id`（管理営業所）をドロップダウンで選択（`garages.csv` から参照）
- `st.rerun()` による即時反映
- セッションキーの適切な管理（`_rpe_` プレフィックス、路線ID別スコープ）
- stop_id の一意生成（`stop_{route_id}_{seq:03d}`）
- 距離自動計算（haversine）
- 保存時に `routes.csv` の `num_stops` / `total_distance_km` を自動更新
- テーブル編集モード（folium 未インストール時のフォールバック）
- 番号ラベル付きマーカー、色分け（始終点=赤, 車庫=紫, 片道=オレンジ, 通常=青）

**Cities Skylines 風ツールバー + JS 注入の技術的詳細（v2.1 修正済み）:**

streamlit-folium の JS バンドル（`main.bf2f01a4.js`）では `onMapClick(t)` がローカル関数として定義されており、`debouncedUpdateComponentValue` も window に非公開。編集ツールバーと操作検出には以下の方式を採用:

**JS 注入方法（重要）:**

- `folium.Element(...).add_to(m)` は HTML に反映されない（branca の Element はテンプレート経由）
- 正しい方法: `m.get_root().script.add_child(BrancaElement(生JSコード))` (`<script>` タグなし)
- streamlit-folium は `t.innerHTML = script + "window.map = map_div; ..."` の形でスクリプトを実行するため、注入コードは `window.map` 設定より前に実行される
- そのため `inject()` 内で `if(!map){ setTimeout(inject, 300); return; }` のリトライが必須

**クリックアクション伝達の仕組み:**

1. `m.get_root().script.add_child(BrancaElement(_EDITOR_JS))` で Cities Skylines 風ツールバーを注入
2. ツールバーのモード（`'add'` / `'delete'` / `'none'`）を JS 変数 `MODE` で管理
3. マップクリック時: `window.__GLOBAL_DATA__.lat_lng_clicked = { lat, lng, _action: MODE }` をセット
4. streamlit-folium の `debouncedUpdateComponentValue`（250ms debounce）が `last_clicked` として Python に返す
5. Python 側で `last_clicked.get("_action", "none")` により動作を分岐
6. `action not in ("add", "delete")` の場合はスキップ（`"none"` モードでの誤動作防止）

**右クリックショートカット:**

- `map.on('contextmenu', ...)` で `pendingRC = true` をセット → `map.fire('click', ...)` で合成クリック発火
- `map.on('click', ...)` ハンドラが `pendingRC` を見て `action = 'delete'` として処理

**CSVスキーマ拡張:**

- `routes.csv` に `garage_id` 列を追加（管理営業所の紐付け）
- `stops.csv` に `outbound_only`, `inbound_only` 列を追加（片道フラグ）

**main.py タブ統合:**

- サイドバー「🛣️ 路線詳細設定」エキスパンダーから旧エディタの直接呼び出しを削除（`_rde_` キー重複エラーの解消）。新タブへの誘導メッセージに変更
- `🗺️ 路線詳細` タブに非推奨（レガシー）の警告を表示。セグメント編集が必要な場合のみ使用する旨を明記
- `🚌 路線管理` タブが正式な路線編集ポイントとなる
- `🏢 営業所管理` タブが営業所・車両・行路の編集ポイント

### v1 — 初期実装

- `route_profile_editor.py` 初版作成
- `depot_profile_editor.py` 新規作成
- `data/operations/` ディレクトリ以下に `garages.csv`, `vehicles.csv`, `work_schedules.csv` を新規作成
- `data/route_master/timetable.csv` 新規作成
- `main.py` に `🚌 路線管理` / `🏢 営業所管理` タブを追加

---

## 追加機能の設計方針

### 1. 路線プロフィール管理（`🚌 路線管理` タブ）

- **複数路線**を追加・編集・削除できる
- 各路線は「停留所リスト」と「時刻表（便単位の発着情報）」を保持する
- **行路（便チェーン）は路線側では管理しない** — 行路は営業所側が責任を持つ
- 地図入力（folium + streamlit-folium）に対応（ライブラリが未インストールでも手入力で動作する）
- 各停留所に `outbound_only` / `inbound_only` フラグを設定可能
- 復路は往路から自動生成（`outbound_only=True` の停留所は復路に含めない）
- 路線ごとに管理営業所（`garage_id`）を選択（営業所の追加・編集は営業所管理タブで行う、路線側ではドロップダウン参照のみ）

### 2. 営業所・車両プロフィール管理＋配車計画（`🏢 営業所管理` タブ）

- **複数営業所**を管理する
- 各営業所に**車両**を所属させる
- 時刻表から便を選んで**便チェーン（行路）**を編成する
- 路線間移動の許可/禁止を**営業所単位**で設定できる
- 便チェーン：ある便が終わったら同じまたは別路線の別運用に入る連鎖構造

---

## 既知の課題

### 旧エディタとの CSV 競合

`route_detail_editor.py`（旧）と `route_profile_editor.py`（新）は **共に `routes.csv` と `stops.csv` に書き込む**。旧エディタは新スキーマの列（`garage_id`, `outbound_only`, `inbound_only`）を認識しないため、旧エディタで保存すると新列が失われる可能性がある。

**対策**: 旧エディタは非推奨とし、`🗺️ 路線詳細` タブに警告を表示。セグメント（`segments.csv`）の編集が必要な場合のみ旧エディタを使用する。

### 旧エディタにあって新エディタにない機能

- セグメント（`segments.csv`）の自動生成
- 充電拠点レイヤー（`charger_sites.csv`）の地図表示
- `is_revenue_stop` の編集UI
- 方向別統計パネル

これらは将来の拡張で追加予定。

---

## データ構造・CSVスキーマ

### `data/route_master/routes.csv`

| カラム | 説明 |
|--------|------|
| `route_id` | 路線ID（ユニーク） |
| `route_name` | 路線名 |
| `operator` | 運行事業者 |
| `city` | 所在市区町村 |
| `total_distance_km` | 総距離（自動計算） |
| `num_stops` | 停留所数（自動計算） |
| `description` | 説明 |
| `garage_id` | 管理営業所ID（`garages.csv` 参照） |

### `data/route_master/stops.csv`

| カラム | 説明 |
|--------|------|
| `stop_id` | 停留所ID（ユニーク） |
| `stop_name` | 停留所名 |
| `route_id` | 路線ID |
| `direction` | 方向（outbound / inbound） |
| `sequence` | 順番 |
| `lat` / `lon` | 緯度・経度 |
| `is_terminal` | ターミナルフラグ |
| `terminal_id` | ターミナルID |
| `is_depot` | デポフラグ |
| `is_revenue_stop` | 営業停留所フラグ |
| `distance_from_prev_km` | 前停留所からの距離（km） |
| `outbound_only` | 往路のみフラグ |
| `inbound_only` | 復路のみフラグ |

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
| `app/route_profile_editor.py` | 路線プロフィール管理エディタ v2。複数路線・停留所・時刻表・地図入力・片道フラグ・復路自動生成 |
| `app/depot_profile_editor.py` | 営業所・車両・行路（便チェーン）管理エディタ |
| `data/route_master/timetable.csv` | 時刻表CSVサンプル |
| `data/operations/garages.csv` | 営業所マスタCSVサンプル |
| `data/operations/vehicles.csv` | 車両マスタCSVサンプル |
| `data/operations/work_schedules.csv` | 行路（便チェーン）マスタCSVサンプル |

### 既存ファイル（参照・変更済み）

| ファイル | 役割 | 変更内容 |
|----------|------|----------|
| `app/main.py` | メインStreamlitアプリ | `🚌路線管理`・`🏢営業所管理`タブ追加、サイドバー旧エディタ呼び出し削除、旧タブに非推奨警告追加 |
| `data/route_master/routes.csv` | 路線マスタ | `garage_id` 列追加 |
| `data/route_master/stops.csv` | 停留所マスタ | `outbound_only`, `inbound_only` 列追加 |

### レガシーファイル（変更なし・非推奨）

| ファイル | 役割 |
|----------|------|
| `app/route_detail_editor.py` | 旧路線詳細エディタ（単路線・停留所・デポ・セグメント編集）。`🗺️ 路線詳細` タブで使用（非推奨） |
| `app/map_editor.py` | 旧地図ベースエディタ（ターミナル・デポ・充電拠点・停留所） |
| `app/route_editor.py` | 旧ルートエディタ（CSV読込・編集・保存） |

### ディレクトリ構造

```
master-course/
├── app/
│   ├── main.py                    ← タブ統合済み
│   ├── route_profile_editor.py    ← v2 全面書き直し
│   ├── depot_profile_editor.py    ← 新規作成
│   ├── route_detail_editor.py     ← レガシー（非推奨）
│   ├── map_editor.py              ← レガシー（非推奨）
│   └── route_editor.py            ← レガシー（非推奨）
├── data/
│   ├── route_master/
│   │   ├── timetable.csv          ← 新規作成
│   │   ├── routes.csv             ← garage_id 列追加
│   │   ├── stops.csv              ← outbound_only, inbound_only 列追加
│   │   └── ...
│   ├── operations/                ← 新規ディレクトリ
│   │   ├── garages.csv            ← 新規作成
│   │   ├── vehicles.csv           ← 新規作成
│   │   └── work_schedules.csv     ← 新規作成
│   └── infra/
│       └── depots.csv             ← 既存（旧エディタ用）
├── DEVELOPMENT_NOTES.md           ← 本ファイル
└── README.md
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
| 🗺️ 路線詳細 | レガシー路線詳細エディタ（**非推奨** — セグメント編集用） |
| 🚌 路線管理 | **正式** 複数路線・時刻表・地図入力・片道フラグ・復路自動生成 |
| 🏢 営業所管理 | **正式** 営業所・車両・行路（便チェーン）管理 |
