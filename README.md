# master-course — EV バス配車・充電スケジューリング最適化研究システム

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-20%2B-339933?logo=node.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black)
![Optimization](https://img.shields.io/badge/Optimization-MILP%20%2B%20ALNS-F59E0B)
![Status](https://img.shields.io/badge/Status-Research%20Code-FACC15)

---

## 目次

1. [研究目的と概要](#1-研究目的と概要)
2. [アーキテクチャ概要](#2-アーキテクチャ概要)
3. [起動手順](#3-起動手順)
4. [主要画面と操作フロー](#4-主要画面と操作フロー)
5. [最適化計算の仕組み](#5-最適化計算の仕組み)
6. [データ構造とファイルレイアウト](#6-データ構造とファイルレイアウト)
7. [開発ノート・既知問題](#7-開発ノート既知問題)
8. [AI エージェント向けアーキテクチャ仕様](#8-ai-エージェント向けアーキテクチャ仕様)

---

## 更新履歴（2026-03-16）

- optimization evaluator の算定式を修正（デマンド料金をピーク課金化、TOUのスロット単価反映、deadheadを距離換算で計算）。
- optimization problem の trip lookup をキャッシュ化し、反復評価時の辞書再生成を削減。
- BFF mapper の logger 未定義クラッシュを修正（scenario_to_problemdata で logging 初期化）。
- hybrid metadata から固定値化される generated_columns 指標を削除。
- dispatch mapper の deadhead_distance_km を 0 固定から時間ベース推定に変更。
- 距離推定を再設計し、route normalizer・stop_distances・trip_chains・BFF mapper で stop 座標/停留所連結/時刻表由来フォールバックを統合、渋41(約13km)・東98(約15km)のファミリー距離キャリブレーションを追加。
- data_loader で duplicate task_id を検出・正規化し、compat / travel connection 参照を追従させる修正を追加。
- run_case の --verbose 実行時に一時設定ファイルの相対パス解決が壊れる問題を修正。
- result_exporter の Excel 出力で charger_utilization が dict の場合に失敗する問題を修正。
- result_exporter の KPI シートで未割当タスクがリスト型のときに Excel 出力が失敗する問題を修正。
- src/optimization/milp の solver_adapter を Gurobi 実接続に変更し、engine が baseline ではなく solver が返す plan を採用するよう修正。
- src/optimization/milp/model_builder の SOC 遷移制約を placeholder からスロット遷移式ベースの定義へ更新。
- solver_adapter の pairwise incompatibility を廃止し、arc-flow 制約（x/start/end）へ置換。
- solver_adapter の目的関数で発生していた固定費二重計上を修正。
- evaluator の deadhead コストを TOU 価格参照に変更し、PV credit と switch_cost の定義を運用可能な形へ修正。
- ALNS の soc_repair / partial_milp_repair / regret_k_insertion をスタブから実装に更新。
- hybrid/column_generation の Placeholder 実装を dual-guided 候補生成へ更新。
- optimization 回帰テストを追加し、arc-flow 連鎖許容・固定費二重計上防止・deadhead TOU・PV credit 算定を自動検証。
- 最適化出力を output/run_YYYYMMDD_HHMM に統一し、対象便一覧・便種別本数・コスト内訳・CO2内訳・車両別タイムライン・目的関数内訳を JSON/CSV で自動出力。
- 車両別タイムライン出力を拡張し、`vehicle_timeline_gantt.csv` / `vehicle_timelines.json` にイベントID・開始/終了時刻(HH:MM)・継続時間・運行/回送/充電区分・路線ラベル（route_id/direction/variant）・回送の前後便情報を含めて、全車両ガント可視化へ直接利用できる形式に更新。
- 実行条件の監査用として `simulation_conditions.json` と補助CSV（車両導入費・燃料単価・TOU単価テーブル・契約電力上限）を `output/run_*/` に自動出力し、需要/契約関連単価と将来拡張向け係数（objective_weights 全項目）を保存するよう更新。
- `tools/route_variant_labeler_tk.py` を追加し、路線ごとの手動ラベリング（本線上り/下り・区間便・入出庫便・方向）を GUI で編集して `routeVariantType` / `canonicalDirection` / Manual override 列を CSV/JSON へ保存できるよう更新。
- `tools/route_variant_labeler_tk.py` のUI文言を日本語化し、タグ付与運用時の操作ラベル・警告・保存ダイアログを日本語表示に統一。
- フロントエンドに軽量導線 `ScenarioQuickPage` を追加し、対象営業所・対象路線・便種フィルタ・路線間/営業所間トレード許可・ソルバー選択・Prepare/Run 実行を1画面で完結できるよう更新（`/scenarios/:id/quick`）。
- BFF に `GET/PUT /scenarios/{id}/quick-setup` を追加し、重い editor bootstrap を使わずに軽量サマリ取得と一括設定保存（dispatch scope + solver 設定）を可能化。
- バックアップ運用向けに `tools/scenario_backup_tk.py` を追加し、シナリオ作成・quick-setup 保存・営業所BEV台数調整・simulation prepare/run・optimization 実行・job 監視を単体GUIで実行可能に。
- 路線系統番号抽出ロジックを `src/route_code_utils.py` に共通化し、`tools/route_variant_labeler_tk.py` / BFF route family 集約 / 最適化入力（Task メタデータ）で共通利用するよう更新。タグ付与アプリでは文頭の漢字/ひらがな/カタカナプレフィックス単位でグループ化し、番号の昇順/降順ソートを切替可能に。
- Planning の路線一覧と Public Data Explorer の route family 一覧で `routeSeriesPrefix` 単位の折りたたみ表示を追加。
- 最適化結果CSV（`targeted_trips.csv` / `vehicle_schedule.csv` / `vehicle_timeline_gantt.csv`）に `route_series_code` 列を追加し、系統単位分析を容易化。

## 1. 研究目的と概要

**修士研究テーマ：PV 出力を考慮した BEV/ICE 混成フリートの充電・運行スケジューリング統合最適化**

東急バスを対象ケーススタディとして、以下を比較検証する。

| ケース | 内容 |
|--------|------|
| A（ベースライン） | ICE バスのみ、現行ダイヤ通り運行 |
| B（混成） | BEV + ICE 混成、充電なし最適化 |
| C（混成 + PV） | BEV + ICE、PV 出力あり最適化 |
| D（提案手法） | 混成 + PV + TOU 料金 + デマンド制限 統合最適化 |

**目標：**
- 車両割り当てコスト（燃料費 + 電力費 + デマンド料金）の最小化
- CO2 排出量の削減
- 実運行ダイヤの完全カバー（上り・下り・区間便・入出庫便すべて）

---

## 2. アーキテクチャ概要

```
┌─────────────────────────────────────────────────┐
│                フロントエンド                       │
│  React + Vite + TypeScript + Zustand              │
│  ポート: 5173 (dev) / dist/ (prod)                │
│                                                   │
│  主要画面:                                         │
│  ① Scenario Overview (シミュレーション入力設定)     │
│  ② Planning (営業所・路線・権限管理)                │
│  ③ Graph / Timetable / Results                   │
└────────────────┬────────────────────────────────┘
                 │ HTTP /api/*
┌────────────────▼────────────────────────────────┐
│              BFF (Backend for Frontend)           │
│  FastAPI + Python  ポート: 8000                   │
│                                                   │
│  主要 Router:                                      │
│  /scenarios  — シナリオ CRUD + editor-bootstrap   │
│  /graph      — trips, graph, blocks, duties      │
│  /simulation — prepare + run                     │
│  /optimization — run-optimization + reoptimize  │
│  /jobs       — ジョブポーリング                    │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│           コアライブラリ (src/)                    │
│                                                   │
│  src/dispatch/        — 配車パイプライン            │
│    models.py          — Trip / DispatchContext    │
│    graph_builder.py   — 接続可能グラフ構築          │
│    feasibility.py     — フィジビリティ判定          │
│    dispatcher.py      — Greedy 配車 (帰り便優先)   │
│    pipeline.py        — TimetableDispatchPipeline │
│    validator.py       — DutyValidator             │
│                                                   │
│  src/optimization/    — 最適化エンジン             │
│    milp/              — MILP ソルバー              │
│    alns/              — ALNS ヒューリスティック     │
│    hybrid/            — Hybrid (MILP + ALNS)      │
│    rolling/           — ローリングホライズン再最適  │
│                                                   │
│  src/pipeline/        — E2E パイプライン            │
│  src/data_schema.py   — ProblemData / Task / Vehicle │
└─────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│             データストア (outputs/)               │
│  outputs/scenarios/{id}.json      — シナリオメタ  │
│  outputs/scenarios/{id}/          — アーティファクト │
│    artifacts.sqlite               — trips/duties/graph │
│    master_data.sqlite             — depot/route/vehicle │
│  outputs/jobs/*.json              — バックグラウンドジョブ │
│  data/built/tokyu_core/           — 事前ビルド済みデータ │
│  data/seed/tokyu/                 — シードマスタデータ │
└─────────────────────────────────────────────────┘
```

### 設計の核心原則

1. **Timetable First, Dispatch Second** — 時刻表から導出した trips が配車の唯一の入力。配車が時刻表を書き換えることは絶対に禁止。
2. **Operator 境界の厳格分離** — 東急バス・都営バス等は operator_id で必ず分離。混在禁止。
3. **段階的データロード** — 初期表示は editor-bootstrap（depots + summary）のみ。重い timetable / graph / trips は使用時に遅延読み込み。
4. **フィジビリティは不変** — `arrival_time + turnaround + deadhead <= departure_time` という接続可能性の基準は変更禁止。

---

## 3. 起動手順

### 必要環境

- Python 3.11+（3.14 動作確認済み）
- Node.js 20+
- pip と npm

### バックエンド起動

```bash
# リポジトリルートで
pip install -r requirements.txt   # 初回のみ

python -m uvicorn bff.main:app --reload --port 8000
```

### フロントエンド起動

```bash
cd frontend
npm install   # 初回のみ
npm run dev
```

ブラウザで `http://localhost:5173` を開く。

### 3.1 予備アプリ（バックアップ用 Tkinter）の使い方

対象ファイル: `tools/scenario_backup_tk.py`

```bash
# リポジトリルートで
python tools/scenario_backup_tk.py
```

前提:
- バックエンド（FastAPI）が起動済みであること（`http://127.0.0.1:8000`）

基本手順:
1. 上部の `BFF URL` を確認し、`接続確認` を押す
2. `一覧更新` でシナリオ一覧を取得（必要なら `新規作成` で新規作成）
3. 必要に応じて `複製` / `有効化` / `削除` / `App Context` を利用する
4. `Quick Setup 読込` で営業所・路線・solver 設定を読み込む
5. 必要に応じて `ラベルファイル選択` で `route_variant_manual_labels.csv/json` を選び、`ラベルをシナリオへ反映` を実行する
  - `routeFamilyCode` / `routeSeriesCode` / `routeVariantTypeManual` / `canonicalDirectionManual` を route マスタへ一括反映
  - 反映後は Quick Setup 路線一覧・配車（dispatch）・最適化入力に同一タグが伝搬
6. 営業所/路線選択、便種フィルタ、トレード許可、solver 条件を調整して `Quick Setup 保存`
7. 右側 `車両管理` タブで営業所単位の車両一覧取得、車両の新規作成/更新/削除、単体/一括複製、テンプレート導入を実行する
8. 右側 `テンプレート管理` タブでテンプレートの新規作成/更新/削除を実行する
9. `Cost / Tariff Parameters` で車両導入費（車両/テンプレート個別設定）、燃料単価、電力単価、TOU帯、需要単価、契約上限、契約超過罰金係数、将来拡張用 `objective_weights` を設定する
10. `Advanced Options` ボタンを押した場合のみ、`solver_mode` / `objective_mode` / `time_limit_seconds` / `mip_gap` / `alns_iterations` などの詳細設定を編集する
11. `入力データ作成 (Prepare)` → `Prepared実行` または `最適化実行` を実行する
12. 必要に応じて `シミュレーション実行(legacy)` / `再最適化` を実行する
13. `ジョブ監視` で `job_id` の状態を確認し、`機能情報` / `Simulation結果` / `Optimization結果` で結果を確認する

補足:
- ログは画面下部に逐次出力される
- `Prepare` 後に取得した `prepared_input_id` がシミュレーション実行に使われる

### 3.2 路線タグ割り振りアプリ（Tkinter）の使い方

対象ファイル: `tools/route_variant_labeler_tk.py`

```bash
# リポジトリルートで
python tools/route_variant_labeler_tk.py
```

基本手順:
1. `Open File (CSV/JSONL)` で路線情報を含む CSV/JSONL を読み込む
  - `operator_id` がデータに無い場合は、画面上部の `operator_id 補完`（`tokyu` / `toei`）を選択して読込する
2. 左側リストで対象行を選択する
  - 画面上部 `営業所表示` プルダウンで対象営業所を選択可能（`all` は全営業所）
  - 左リストは `営業所 → family(系統番号) → 路線` の折りたたみ表示
  - マウスホイールで上下スクロール可能
  - 縦スクロールバー / 横スクロールバーで一覧移動可能
  - `Ctrl`/`Shift` で複数行選択可能（複数路線の一括編集用）
3. 右側で以下を編集する
  - `direction / canonicalDirection`
  - `routeVariantType`
  - `isPrimaryVariant`
  - `classificationConfidence`
  - `classificationReasons`
4. `Series number order` を `asc` / `desc` で切り替え、`Apply Sort` で系統番号順に並び替える
  - 文頭の漢字/ひらがな/カタカナプレフィックスでまとまり
  - 同一プレフィックス内で数字を昇順または降順で整列
5. `Apply Label`（選択行へラベル反映）で選択中の1件または複数件に一括反映する
6. `Save Labels CSV/JSON` で手動ラベル定義を保存する
7. 必要に応じて `Save Merged CSV` または `Save Merged JSONL` で元データにラベル列を反映したファイルを出力する

直接読込に対応する主な路線データ:
- `data/catalog-fast/normalized/routes.jsonl`（正規化済み路線）
- `data/tokyubus/canonical/*/routes.jsonl`（スナップショット別 canonical）

補足（normalized routes の読込）:
- `data/catalog-fast/normalized/routes.jsonl` は `operator_id` 列が無いケースがあるため、通常は `operator_id 補完 = tokyu` を選択してから読み込む

互換性ルール:
- `operator_id` が無い行は、`operator_id 補完` が指定されていればその値で補完して読込する
- `operator_id 補完` が空の場合は、`operator_id` 欠損行を読み込み時にスキップする（operator 境界不整合を防ぐため）

主な出力:
- `route_variant_manual_labels.csv`
- `route_variant_manual_labels.json`
- `labeled_input.csv`（マージ保存時）
- `labeled_input.jsonl`（JSONLマージ保存時）
- 追加列: `routeSeriesCode`, `routeSeriesPrefix`, `routeSeriesNumber`
 - 追加列: `routeFamilyCode`, `routeFamilyLabel`

補足:
- 系統番号抽出ロジックは `src/route_code_utils.py` に共通化され、
  tkinterツール（手動ラベル）、BFF route family 集約、最適化入力生成（Task メタデータ）で共通利用される。
- 最適化前段の配車（dispatch）では、`routeFamilyCode` / `routeSeriesCode` が同じ便同士を同一路線扱いとして接続優先スコアに反映する（未設定時は `route_id` ベース）。

### 3.3 シナリオに依存せず路線情報を確認する

路線情報はシナリオを作成しなくても、以下のフォルダ/データから直接確認できます。

- `data/route_master/routes.csv`（基本の路線マスタ）
- `data/catalog-fast/normalized/routes.jsonl`（正規化済み路線）
- `data/tokyubus/canonical/*/routes.jsonl`（スナップショット別 canonical）

CLI で確認する場合:

```bash
# リポジトリルートで（シナリオ不要）
python query_routes.py --limit 30

# キーワード検索
python query_routes.py --q 渋41 --limit 20

# ソース固定（csv / normalized / canonical）
python query_routes.py --source normalized --limit 20
```

API で確認する場合（CATALOG_BACKEND=local_sqlite で有効）:

- `GET /api/catalog/operators/{operator_id}/route-families`
- 例: `GET /api/catalog/operators/tokyu/route-families`

### 3.4 推奨運用フロー（タグ付与 → シナリオ作成 → 最適化）

本プロジェクトの実運用では、次の順序で実施する。

1. `tools/route_variant_labeler_tk.py` で路線タグを手動付与する
  - `routeVariantType`: `main` / `short_turn` / `depot_out` / `depot_in` など
  - `canonicalDirection`: `outbound` / `inbound`
  - 必要に応じて `isPrimaryVariant`, `classificationConfidence`, `classificationReasons` を更新
2. ラベル結果を保存し、必要なら `Save Merged CSV` / `Save Merged JSONL` で元データへ反映する
3. `tools/scenario_backup_tk.py` を起動し、対象シナリオを作成または選択する
4. `Quick Setup` で対象営業所・対象路線・便種条件を設定して保存する
5. 車両管理/テンプレート管理で営業所別の保有車両を調整する
6. `Cost / Tariff Parameters` と必要時の `Advanced Options` を設定する
7. `入力データ作成 (Prepare)` 実行後、`Prepared実行` または `最適化実行` を実行する
8. `ジョブ監視` と `Optimization結果` で結果を確認する

OK 判定（この一連が成功したとみなす条件）:
- タグ付与アプリで対象路線の `routeVariantType` と `canonicalDirection` を保存できる
- バックアップTkでシナリオ作成・quick-setup保存・車両編集が実行できる
- 最適化ジョブが `failed` にならず完了し、結果APIで KPI / cost breakdown を確認できる

### ビルド確認

```bash
# フロントエンド本番ビルド
cd frontend && npm run build

# バックエンドテスト
python -m pytest tests/ -q
```

### 他PCへ移行する場合（キャッシュ除外）

- キャッシュ系はすべてリポジトリ直下の `.cache/` に集約する運用です（Git 管理対象外）。
- 他PCへコピーする際は、`/.cache/`, `/.venv/`, `/frontend/node_modules/`, `/__pycache__/` を除外してください。
- コピー先では仮想環境を再作成し、依存関係を再インストール後にそのまま `data/` と `outputs/` を参照して実行できます。

---

## 4. 主要画面と操作フロー

### シミュレーションを動かすまでの手順

```
① Scenario Overview を開く
  → 左: シナリオ選択（または新規作成）

② Step 1: Depot & Route 選択
  → 対象営業所を選択
  → 対象路線をチェック（上り↗/下り↙/区間/入出庫のバッジで確認）
  → 便種フィルタ（区間便・入出庫便のON/OFF）
  → 車両トレード許可（路線内 / 営業所間）を設定

③ Step 2: Simulation Settings
  → 車両台数、充電器、solver モード、コスト設定を入力

④ 「入力データ作成」ボタン（prepare）
  → BFF が dispatch scope を確定し、trip count を返す

⑤ 「シミュレーション開始」ボタン（run）
  → バックグラウンドジョブで最適化実行
  → ポーリングで完了を待つ

⑥ 結果ページで確認
  → duties, energy, cost breakdown を表示
```

### Planning 画面

- 左パネル：営業所一覧（bootstrap から即時表示）
- 右パネル：営業所詳細（タブ選択時に遅延ロード）
- 「配車スコープ設定」エリア：
  - **便種フィルタ**：区間便・入出庫便の ON/OFF（dispatch scope に保存）
  - **路線内トレード許可**：同一営業所内で異なる路線間の車両融通を許可
  - **営業所間トレード許可**：複数営業所の trips を統合して最適化（計算コスト増）

---

## 5. 最適化計算の仕組み

### 配車パイプライン（dispatch pipeline）

```
timetable_rows
  ↓ (service_id + route フィルタ + variant フィルタ)
Trip[] (direction・route_variant_type 付き)
  ↓
DispatchContext (trips + rules + vehicle_profiles + swap フラグ)
  ↓
ConnectionGraphBuilder.analyze()
  → 全ペア可能性チェック: arrival + turnaround + deadhead <= departure
  → O(n²) — trips が多いほど計算コスト増
  ↓
feasibility graph (trip_id → [接続可能 trip_id, ...])
  ↓
DispatchGenerator.generate_greedy_duties_from_graph()
  → 帰り便優先スコアリング:
    +200: 同一路線の逆方向 (上り→下り or 下り→上り)
    +100: 出発地 == 前便の到着地 (デッドヘッドなし)
    +50:  同一路線・同方向 (ループ・折り返し)
    +20:  路線内トレード許可 + 同一停留所
    +5:   営業所間トレード許可 (任意接続)
    -1/分: デッドヘッド時間ペナルティ
  ↓
VehicleDuty[] → DutyValidator → PipelineResult
```

### 最適化エンジン

```
ProblemData (trips → Tasks, vehicles, chargers, costs)
  ↓
OptimizationEngine.solve(mode, config)
  ├── mode_milp_only  → MILPOptimizer (ベースライン実行可能解)
  ├── mode_alns_only  → ALNSOptimizer (ヒューリスティック探索)
  ├── mode_alns_milp  → ALNS + MILP 補修
  └── hybrid          → MILP 初期解 + ALNS 外部ループ (デフォルト研究モード)
  ↓
OptimizationResult (duties, charging_schedule, cost_breakdown)
```

### 目的関数

```
min C_total = C_fuel + C_elec + C_demand + C_vehicle_depreciation

C_elec    = Σ (energy_kwh × tou_price(t)) — TOU 料金
C_demand  = peak_kw × demand_charge_rate  — デマンド料金
C_vehicle = acquisition_cost / lifetime_days × days — 減価償却
```

---

## 6. データ構造とファイルレイアウト

```
master-course/
├── frontend/           — React フロントエンド
│   ├── src/
│   │   ├── pages/      — Scenario, Planning, Graph, Results
│   │   ├── features/   — planning, common コンポーネント
│   │   ├── hooks/      — React Query hooks
│   │   ├── stores/     — Zustand stores (ui, planning-dataset, simulation-builder)
│   │   └── types/      — TypeScript 型定義
│   └── vite.config.ts
│
├── bff/                — FastAPI BFF
│   ├── routers/        — scenarios, graph, simulation, optimization, ...
│   ├── services/       — simulation_builder, run_preparation, app_cache
│   ├── store/          — scenario_store (SQLite/Parquet/JSON), job_store
│   └── mappers/        — scenario_to_problemdata
│
├── src/                — コアライブラリ (dispatch / optimization / pipeline)
│   ├── dispatch/       — Trip, DispatchContext, GraphBuilder, Dispatcher, Validator
│   ├── optimization/   — MILP, ALNS, Hybrid, Rolling
│   ├── pipeline/       — E2E pipeline, solve
│   └── data_schema.py  — ProblemData, Task, Vehicle, Charger
│
├── data/
│   ├── built/tokyu_core/   — 事前ビルド済み Parquet (trips, routes, timetables)
│   └── seed/tokyu/         — シードマスタデータ (depots.json, version.json)
│
├── outputs/
│   ├── scenarios/      — シナリオ JSON + artifact SQLite/Parquet
│   ├── jobs/           — バックグラウンドジョブ状態
│   └── experiments/    — 実験ログ
│
├── tests/              — pytest テストスイート
├── constant/           — 研究仕様書・エージェント指示書 (読み取り専用)
└── AGENTS.md           — 開発ルール (最優先で遵守)
```

---

## 7. 開発ノート・既知問題

### 2026-03 時点での実装状態

| 機能 | 状態 |
|------|------|
| editor-bootstrap（営業所一覧・概要） | ✅ 実装済み・軽量化済み |
| Trip direction/variant 伝搬 | ✅ 2026-03 実装 |
| 帰り便優先 greedy dispatcher | ✅ 2026-03 実装 |
| 路線内/営業所間トレード許可 | ✅ 2026-03 実装（フラグ制御） |
| MasterPlanningPage swap トグル | ✅ 2026-03 実装 |
| ScenarioOverviewPage 便種バッジ | ✅ 2026-03 実装 |
| 本番 MILP ソルバー（Gurobi） | ⚠️ ベースライン実装のみ（接続未完）|
| 多営業所統合最適化 | ✅ フラグ実装済み（allowInterDepotSwap） |
| PV プロファイル | ✅ データ構造あり・UI 未完 |
| ローリングホライズン再最適化 | ✅ 実装済み |

### パフォーマンス上の注意

- `ConnectionGraphBuilder.analyze()` は O(n²) — 東急バス全線（825 trips）で約 4 秒
- `_rebuild_dispatch_artifacts()` は DispatchContext を 1 回だけビルドして再利用
- `editor-bootstrap` のペイロードは 28KB（shardManifest 等を除外済み）
- BFF の `_load()` は `skip_graph_arcs=True` がデフォルト — graph 136 万弧は必要時のみ

### 禁止事項（AGENTS.md より）

1. timetable_rows を配車側から書き換えてはいけない
2. feasibility 判定（arrival + turnaround + deadhead <= departure）を変更してはいけない
3. `constant/` フォルダのファイルは指示なしに変更しない
4. operator_id のない entity を保存・返却・描画してはいけない
5. `src/dispatch/` は `frontend/` や `bff/` からインポートされてはいけない

---

## 8. AI エージェント向けアーキテクチャ仕様

> このセクションは Claude Code や他の AI エージェントが本リポジトリを理解するための機械可読仕様です。

### 層構造と依存ルール

```
frontend/ (React)
  └── calls /api/* via fetch
      └── bff/ (FastAPI)
            ├── bff/routers/ — HTTP エンドポイント
            ├── bff/services/ — ビジネスロジック
            ├── bff/store/ — 永続化 (scenario_store, job_store)
            └── bff/mappers/ — DTO 変換
                  └── calls src/* — コアライブラリ
                        └── src/dispatch/ — 配車層 (独立)
                        └── src/optimization/ — 最適化層 (独立)
                        └── src/pipeline/ — E2E パイプライン
```

**禁止インポート：**
- `src/dispatch/` → `frontend/` or `bff/` or `src/constraints/` or `src/pipeline/` は禁止
- `src/optimization/` → `frontend/` or `bff/` は禁止

### 主要エンドポイントマップ

| エンドポイント | 処理内容 | 速度 |
|---------------|---------|------|
| `GET /api/app/context` | アクティブシナリオID | < 5ms |
| `GET /api/scenarios/{id}/editor-bootstrap` | depots + routes(slim) + summary | ~50ms |
| `PUT /api/scenarios/{id}/dispatch-scope` | swap フラグ・tripSelection 保存 | ~300ms |
| `POST /api/scenarios/{id}/simulation/prepare` | scope 確定・trip count 検証 | ~500ms |
| `POST /api/scenarios/{id}/run-optimization` | Job 登録（処理はworkerプロセス） | ~5s (job submit) |
| `GET /api/jobs/{job_id}` | ジョブポーリング | < 10ms |

### DispatchContext の swap フラグ動作

```python
DispatchContext(
    ...,
    allow_intra_depot_swap=False,  # デフォルト: 路線間トレード禁止
    allow_inter_depot_swap=False,  # デフォルト: 営業所間トレード禁止
)
```

- `allow_intra_depot_swap=True`: greedy dispatcher の接続スコアに +20 (同一停留所の異路線接続)
- `allow_inter_depot_swap=True`: `_build_dispatch_context` が全選択 depot の trips を一つの context に統合

### Trip dataclass（dispatch 層）

```python
@dataclass(frozen=True)
class Trip:
    trip_id: str
    route_id: str
    origin: str           # 出発停留所 ID
    destination: str      # 到着停留所 ID
    departure_time: str   # "HH:MM"
    arrival_time: str     # "HH:MM"
    distance_km: float
    allowed_vehicle_types: Tuple[str, ...]
    direction: str = "unknown"           # "outbound" | "inbound" | "unknown"
    route_variant_type: str = "unknown"  # "main_outbound" | "main_inbound"
                                         # | "short_turn" | "depot_in" | "depot_out"
```

`direction` と `route_variant_type` は `_build_dispatch_context`（`bff/routers/graph.py`）で timetable_rows から伝搬される。

### シナリオストアの読み込み戦略

| 関数 | graph arcs | timetable_rows | trips | 用途 |
|------|------------|----------------|-------|------|
| `_load_shallow()` | ❌ (skip) | ❌ (skip) | ❌ (skip) | editor-bootstrap, read-only |
| `_load(skip_graph_arcs=True)` | ❌ (skip) | ✅ | ✅ | write operations |
| `get_field("trips")` | ❌ | ❌ | ✅ | trip のみ必要な場合 |
| `get_field("graph")` | ✅ | ❌ | ❌ | graph のみ必要な場合 |

### テスト最低ライン

```bash
# 必須テスト（PR 前に必ず通すこと）
python -m pytest tests/test_architecture.py tests/test_dispatch_pipeline.py tests/test_bff_simulation_builder.py -q
```

現在の基準: **245 以上のテストがパス**（2026-03-09 確認）

### constant/ フォルダの読み方

`constant/` フォルダには研究の仕様書が格納されている。実装時の優先順位は以下のとおり：

1. `AGENTS.md`（リポジトリルート） — 最優先の禁止事項・非変更ルール
2. `constant/agent.md` — 実装ステージ順序（Stage 0〜7）
3. `constant/AGENTS_ev_route_cost.md` — EV/ICE コスト計算エージェント指示書
4. `constant/formulation.md` — MILP 数理定式化（制約 C1〜C21）
5. `constant/masters_research_brief_alignment.md` — 研究目的の上位整理

これらは **読み取り専用**。指示なしに変更しない。
