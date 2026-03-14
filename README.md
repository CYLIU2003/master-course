# master-course

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python\&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-20%2B-339933?logo=node.js\&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi\&logoColor=white)
![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB?logo=react\&logoColor=black)
![Optimization](https://img.shields.io/badge/Optimization-MILP%20%2B%20ALNS-F59E0B)
![Data](https://img.shields.io/badge/Data-Parquet%20%2B%20Manifest-7C3AED)
![Architecture](https://img.shields.io/badge/Architecture-Producer%20%2F%20Consumer-0EA5E9)
![Status](https://img.shields.io/badge/Status-Research%20Code-FACC15)

**東急バス BEV / ICE 混成車両スケジューリング研究システム**
**Tokyu Bus BEV/ICE Mixed Fleet Scheduling Research Application**
**东急巴士 BEV / ICE 混合车队调度研究系统**

4-depot Tokyu core case study · PV / TOU / demand charge · reproducible thesis experiments

---

## 概要 / Overview / 概述

本リポジトリは、東急バスの営業所単位ケーススタディ（主に `tokyu_core` の 4営業所コアスコープ: 目黒・瀬田・淡島・弦巻）を対象として、**BEV（電気バス）/ ICE（内燃機関バス）の混成運用、充電計画、事業者保有 PV（太陽光発電）、時間帯別料金（TOU）、デマンドチャージ、MILP + ALNS による最適化**を扱う研究システムです。

本仓库是一个围绕东急巴士营业所级案例研究（当前以 `tokyu_core` 的 4 营业所核心范围: 目黑、濑田、淡岛、弦卷为核心）的研究系统，涵盖 **BEV / ICE 混合车队调度、充电可行性、运营方自有光伏（PV）利用、分时电价（TOU）、需量电费（Demand Charge）以及基于 MILP + ALNS 的优化**。

This repository is a research system for Tokyu Bus depot-level case studies, primarily centered on the `tokyu_core` 4-depot scenario (Meguro, Seta, Awashima, and Tsurumaki). It studies **mixed BEV/ICE fleet scheduling, charging feasibility, operator-owned PV utilization, time-of-use pricing, demand charges, and MILP + ALNS-based optimization**.

> [!IMPORTANT]
> メインアプリは、実行時に ODPT / GTFS の生データ取得・変換を行いません。
> 主应用在运行时不会抓取、解析或转换原始 ODPT / GTFS 数据。
> The main app never fetches, parses, or transforms raw ODPT/GTFS data at runtime.

---

## 目次 / Table of Contents / 目录

* [このリポジトリの位置づけ / What This Repo Is Now / 当前定位](#このリポジトリの位置づけ--what-this-repo-is-now--当前定位)
* [二層アーキテクチャ / Two-App Architecture / 双应用架构](#二層アーキテクチャ--two-app-architecture--双应用架构)
* [データ契約 / Data Contract / 数据契约](#データ契約--data-contract--数据契约)
* [データセット定義 / Dataset Definitions / 数据集定义](#データセット定義--dataset-definitions--数据集定义)
* [アプリ状態 / App State / 应用状态](#アプリ状態--app-state--应用状态)
* [クイックスタート / Quick Start / 快速开始](#クイックスタート--quick-start--快速开始)

  * [Main Research App](#main-research-app)
  * [Data-Prep App](#data-prep-app)
* [再現性 / Reproducibility / 可复现性](#再現性--reproducibility--可复现性)
* [メインアプリに含めないもの / What Is NOT in the Main App / 主应用中不包含的内容](#メインアプリに含めないもの--what-is-not-in-the-main-app--主应用中不包含的内容)
* [レガシー要素 / Legacy Components / 冻结组件](#レガシー要素--legacy-components--冻结组件)
* [開発者向け / Development Reference / 开发参考](#開発者向け--development-reference--开发参考)
* [ディレクトリ構成 / Directory Structure / 目录结构](#ディレクトリ構成--directory-structure--目录结构)
* [ブランチ方針 / Branch Policy / 分支策略](#ブランチ方針--branch-policy--分支策略)
* [ライセンス / License / 许可证](#ライセンス--license--许可证)

---

## このリポジトリの位置づけ / What This Repo Is Now / 当前定位

本リポジトリは現在、**Producer / Consumer を厳密に分離した二層構成**を採用しています。

### Producer 側

* `data-prep/`

  * ODPT データ取得
  * 生データの整形・変換
  * 研究用データセットの構築
  * `data/built/` への成果物出力

### Consumer 側

* リポジトリルート直下のランタイム

  * `bff/`：API orchestration
  * `src/`：研究ロジック
  * `frontend/`：UI
  * `app/VERSION`：runtime version marker

本仓库当前采用 **严格的 Producer / Consumer 分离架构**。`data-prep/` 负责离线获取与构建数据集，根目录运行时应用仅消费 `data/built/` 中的构建结果。

The repository follows a **strict producer/consumer split architecture**. `data-prep/` builds offline datasets, while the runtime stack consumes only prebuilt artifacts from `data/built/`.

---

## 二層アーキテクチャ / Two-App Architecture / 双应用架构

```text
data-prep/                  ->   data/built/<dataset>/                 ->   app runtime
(producer)                       manifest.json                              (consumer)
                                 routes.parquet                             bff/ + src/ + frontend/
                                 trips.parquet
                                 timetables.parquet
```

### 設計原則 / Design Principles / 设计原则

* 両アプリは **ファイルのみ** を介して連携します

* 共有データベースはありません

* アプリ間 REST API はありません

* Consumer は `data-prep/` に実行時依存しません

* 两个应用之间 **仅通过文件进行交互**

* 无共享数据库

* 无应用间 REST API

* Consumer 不依赖 `data-prep/` 的运行时逻辑

* The two apps communicate **only through files**

* No shared database

* No inter-app REST API

* No runtime dependency of the consumer on `data-prep/`

> [!NOTE]
> `data-prep/` を先に実行して `data/built/` を生成する必要があります。
> ただし、ビルド済みデータが無い場合でもメインアプリは **seed-only mode** で起動できます。
> その場合、**simulation / optimization は無効**です。

---

## データ契約 / Data Contract / 数据契约

### Seed data（Git 管理・常時存在）

### Seed 数据（Git 管理，始终存在）

### Seed data (Git-managed, always present)

| File                                       | 内容 / Contents                                      |
| ------------------------------------------ | -------------------------------------------------- |
| `data/seed/tokyu/depots.json`              | 東急バス 12 営業所マスタ / 12 Tokyu Bus depot master records |
| `data/seed/tokyu/route_to_depot.csv`       | 系統→営業所対応表 / Route-to-depot mapping                 |
| `data/seed/tokyu/version.json`             | Seed provenance metadata                           |
| `data/seed/tokyu/datasets/tokyu_core.json` | 目黒・瀬田・淡島・弦巻 + `route_to_depot.csv` 起点の全 route rows / 4-depot core scope |
| `data/seed/tokyu/datasets/tokyu_dispatch_ready.json` | 目黒・瀬田・淡島・弦巻 + preload baseline / 4-depot dispatch-ready preload |
| `data/seed/tokyu/datasets/tokyu_full.json` | 全 12 営業所 + `route_to_depot.csv` 起点の全 route rows / All depots and routes |
| `data/vehicle_catalog.json`                | 大型路線バスのカタログ値ベース車両テンプレート seed / catalog-based large route-bus template seed |

`data/vehicle_catalog.json` の `ev_presets` / `engine_presets` は
scenario bootstrap の default vehicle templates の基準データです。
現行 runtime の template 層は `BEV` / `ICE` のみ自動 seed 対象で、`HEV` は reference-only に保持しています。

### Built data（`data-prep` が生成・Git には含めない）

### Built 数据（由 `data-prep` 生成，不提交 Git）

### Built data (generated by `data-prep`, not committed)

`data/built/` は `.gitignore` 対象です。

```bash
python -m data_prep.pipeline.build_all --dataset tokyu_core
```

| File                                      | 内容 / Contents                                        |
| ----------------------------------------- | ---------------------------------------------------- |
| `data/built/<dataset>/manifest.json`      | ビルド来歴、契約バージョン、producer/runtime バージョン、artifact hashes |
| `data/built/<dataset>/routes.parquet`     | 正規化済み路線一覧 / Canonical route list                     |
| `data/built/<dataset>/trips.parquet`      | 対象路線の全 trip / All trips for included routes          |
| `data/built/<dataset>/timetables.parquet` | 実行時ロード用 timetable-level trip rows                    |
| `data/built/<dataset>/gtfs_reconciliation.json` | route master と `GTFS/TokyuBus-GTFS/` の照合結果 / GTFS reconciliation report |

---

## データセット定義 / Dataset Definitions / 数据集定义

| Dataset ID   | Depots           | Routes               |
| ------------ | ---------------- | -------------------- |
| `tokyu_core` | `meguro,seta,awashima,tsurumaki` | 46 route rows / 43 route codes |
| `tokyu_dispatch_ready` | `meguro,seta,awashima,tsurumaki` | 46 route rows / 43 route codes |
| `tokyu_full` | All 12 depots    | 165 route rows / 159 route codes |

**Default dataset:** `tokyu_core`
**Default preloaded master dataset:** `tokyu_dispatch_ready`

---

## アプリ状態 / App State / 应用状态

メインアプリは `GET /api/app-state` により、現在の readiness と contract state を返します。

主应用通过 `GET /api/app-state` 返回当前 readiness 与 contract state。

The main app exposes `GET /api/app-state` to show the current readiness and contract state.

| Field                 | Meaning                                           |
| --------------------- | ------------------------------------------------- |
| `seed_ready`          | Seed data loaded successfully                     |
| `built_ready`         | Built dataset present, contract-valid, and loaded |
| `contract_error_code` | Why built data was rejected                       |
| `missing_artifacts`   | Missing required artifacts                        |
| `dataset_version`     | Accepted built dataset version                    |
| `producer_version`    | Producer app version                              |
| `schema_version`      | Manifest schema version                           |
| `runtime_version`     | Consumer runtime version                          |

---

## クイックスタート / Quick Start / 快速开始

## Main Research App

<details>
<summary><strong>メイン研究アプリ / 主研究应用 / Main Research App</strong></summary>

### Prerequisites

* Python 3.11+
* Node.js 20+
* built dataset in `data/built/tokyu_core/`

> [!TIP]
> built dataset がない場合でも起動は可能ですが、**optimization / simulation は無効**になります。

> [!NOTE]
> Tokyu catalog/timetable recovery can also run through a local SQLite catalog backend.
> In that mode the runtime still stays lightweight because it reads a prebuilt
> SQLite catalog (`data/tokyu_full.sqlite` by default) only for `/api/catalog/*`
> lookups and MILP trip extraction.

### Start backend

```bash
python -m pip install -r requirements.txt
uvicorn bff.main:app --reload --port 8000
```

Optional `.env` for local SQLite catalog recovery:

```dotenv
CATALOG_BACKEND=local_sqlite
TOKYU_DB_PATH=data/tokyu_full.sqlite
PRELOAD_MASTER_DATASET_ID=tokyu_dispatch_ready
ODPT_CONSUMER_KEY=your_actual_odpt_key
```

### Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

### App flow

1. dataset を選択（`tokyu_core` / `tokyu_full`）
2. depot と routes を選択
3. scenario を設定
4. simulation / optimization を実行
5. results と KPI を確認

### Check readiness

```bash
curl http://localhost:8000/api/app-state
curl http://localhost:8000/api/app/master-data
```

* `built_ready: true` → optimization available
* `/api/app/master-data` → scenario 非依存の depot / route / vehicle template blueprint

### Preloaded master data

* `GET /api/app/master-data` は scenario 非依存で営業所・路線・車両テンプレートを返します。
* dataset bootstrap は `vehicle_templates` を含むため、新規 scenario 作成直後からテンプレートが空になりません。
* dataset-backed scenario で `depots/routes/route_depot_assignments/depot_route_permissions/vehicle_templates` が空だった場合、load 時に seed dataset から自己修復します。
* `built_ready: false` → built data missing or invalid

### Optional local SQLite catalog recovery

```bash
python scripts/build_tokyu_full_db.py --skip-stop-timetables
python scripts/build_tokyu_gtfs_db.py --dataset-id tokyu_full --out data/tokyu_gtfs.sqlite
curl "http://localhost:8000/api/catalog/milp-trips?depot_ids=tokyu:depot:meguro,tokyu:depot:denenchofu&calendar_type=平日"
```

`build_tokyu_full_db.py` is the ODPT-backed path. `build_tokyu_gtfs_db.py` is the GTFS-backed path and keeps the route/depot mapping as separate bridge tables while loading GTFS stops, timetable trips, trip stop-times, and stop timetables into SQLite. This is the preferred recovery path when you already have a large `GTFS/TokyuBus-GTFS` feed and want a lightweight local catalog without live ODPT access.

The SQLite catalog stores stop coordinates and depot coordinates, and the local catalog backend computes straight-line trip distances from origin/destination stop coordinates for MILP input preparation. You can also round-trip the SQLite catalog back into built artifacts with `scripts/export_tokyu_sqlite_to_built.py`.

When `CATALOG_BACKEND=local_sqlite`, the main app now uses lightweight catalog summary endpoints for dispatch scope setup:

```text
GET /api/catalog/depots
GET /api/catalog/depots/{depot_id}/routes
GET /api/catalog/route-families/{route_family_id}/patterns
```

The dispatch scope UI reads depot / route-family summaries from SQLite first, then saves route-family-code filters back into `dispatch-scope`, where they are expanded into scenario route ids. GTFS-missing routes are simply absent from the catalog summary and are treated as out-of-scope for runtime selection. For Tokyu `東98`, the catalog summary keeps `東京駅南口 ↔ 等々力操車所` as the mainline reference, classifies daytime split patterns as `short_turn`, and marks `清水` / `目黒郵便局` terminals as Meguro depot-related in the notes.

</details>

## Data-Prep App

<details>
<summary><strong>データ前処理アプリ / 数据预处理应用 / Data-Prep App</strong></summary>

`data-prep/` は ODPT データを取得し、研究用 built dataset を構築するための前処理アプリです。

> [!IMPORTANT]
> `python -m data_prep.pipeline.build_all ...` は **必ずリポジトリルート (`master-course/`) から実行してください。**
> `data-prep/` ディレクトリ内で実行すると、`data_prep` パッケージが見つからず
> `ModuleNotFoundError: No module named 'data_prep'` になることがあります。

### Prerequisites

* Python 3.11+
* `.env` または環境変数に `ODPT_CONSUMER_KEY` を設定

> [!NOTE]
> ODPT キーは `ODPT_CONSUMER_KEY` を推奨します。互換で
> `ODPT_API_KEY` / `ODPT_TOKEN` も参照します。
> `YOUR_ODPT_KEY` はプレースホルダなので、そのまま実行すると 404 になります。

### Full build

```bash
python -m pip install -r requirements.txt

# Fetch ODPT + build artifacts + write manifest
python -m data_prep.pipeline.build_all --dataset tokyu_core

# Use cached raw data
python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch

# Build the full Tokyu dataset
python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch

# Fail fast if GTFS and route master do not fully reconcile
python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch --strict-gtfs-reconciliation

# Build a GTFS-backed local SQLite Tokyu catalog with route/depot bridges + stop timetables
python scripts/build_tokyu_gtfs_db.py --dataset-id tokyu_full --out data/tokyu_gtfs.sqlite

# Build a local SQLite Tokyu catalog for catalog recovery / MILP input generation
python scripts/build_tokyu_full_db.py --skip-stop-timetables

# Resume after interruption
python scripts/build_tokyu_full_db.py --skip-stop-timetables --resume

# Or override the key explicitly for one-off runs
python scripts/build_tokyu_full_db.py --api-key YOUR_ODPT_KEY --skip-stop-timetables

# Export SQLite subsets back into built artifacts (dataset definition decides depot scope)
python scripts/export_tokyu_sqlite_to_built.py --db data/tokyu_full.sqlite --dataset-id tokyu_core
python scripts/export_tokyu_sqlite_to_built.py --db data/tokyu_full.sqlite --dataset-id tokyu_full
python scripts/export_tokyu_sqlite_to_built.py --db data/tokyu_gtfs.sqlite --dataset-id tokyu_core

# Refresh Tokyu ODPT -> GTFS/TokyuBus-GTFS -> built datasets
python catalog_update_app.py refresh odpt --skip-stop-timetables --profile fast

# The same refresh, plus rebuild a GTFS-backed SQLite catalog
python catalog_update_app.py refresh odpt --skip-stop-timetables --profile fast --build-gtfs-db --gtfs-db-dataset-id tokyu_full
```

### Exit codes

| Code | Meaning                                            |
| ---- | -------------------------------------------------- |
| 0    | Success - manifest written and contract-validated  |
| 1    | Stage failure - build aborted, no manifest written |
| 2    | Artifacts written but contract validation failed   |

### Verify build

```bash
cat data/built/tokyu_core/manifest.json
cat data/built/tokyu_core/gtfs_reconciliation.json
```

`manifest.json` must contain at least:

* `schema_version`
* `producer_version`
* `artifact_hashes`

`gtfs_reconciliation.json` records which authoritative route codes are missing from the current
`GTFS/TokyuBus-GTFS` feed. Use `--strict-gtfs-reconciliation` if you want the build to fail
instead of writing a warning-only report.

`build_all` now also writes `stops.parquet` and `stop_timetables.parquet` alongside the required
`routes/trips/timetables` artifacts. Scenario bootstrap uses these optional artifacts so new
scenarios start with GTFS-backed stop master data and stop timetable linkage instead of empty
placeholders.

</details>

---

## 再現性 / Reproducibility / 可复现性

すべての simulation / optimization run は、**再現可能**である必要があります。
所有模拟与优化运行都必须具备 **可复现性**。
Every simulation or optimization run must be **fully reproducible**.

| Field             | Purpose                              |
| ----------------- | ------------------------------------ |
| `dataset_id`      | Which built dataset was used         |
| `dataset_version` | When the built dataset was generated |
| `random_seed`     | Solver random seed                   |
| `depot_ids`       | Which depots were in scope           |
| `route_ids`       | Which routes were in scope           |

### To reproduce a run

1. Use the same `dataset_id`
2. Use the same `dataset_version`
3. Use the same `ScenarioOverlay`
4. Use the same `random_seed`
5. Use the same runtime version

---

## メインアプリに含めないもの / What Is NOT in the Main App / 主应用中不包含的内容

以下の機能は、意図的にメインアプリから分離されています。
以下功能被有意排除在主应用之外。
The following capabilities are deliberately excluded from the main app.

| Capability                        | Location                             |
| --------------------------------- | ------------------------------------ |
| ODPT JSON fetch                   | `data-prep/pipeline/fetch_odpt.py`   |
| GTFS conversion                   | `data-prep/lib/tokyubus_gtfs/`       |
| Route-to-depot mapping generation | `data-prep/pipeline/build_routes.py` |
| Public transit data explorer      | `data-prep/`                         |
| Catalog quality dashboard         | `data-prep/`                         |
| Raw data browser                  | Not in this repo                     |

> [!WARNING]
> `bff/` や `src/` に ODPT / GTFS の生処理が現れた場合、それはアーキテクチャ違反です。
> If raw ODPT/GTFS logic appears in `bff/` or `src/`, it is a bug.

> [!NOTE]
> The optional local SQLite catalog backend is allowed because it reads a prebuilt
> file (`data/tokyu_full.sqlite`) rather than raw feed data.

---

## レガシー要素 / Legacy Components / 冻结组件

| Component          | Status   | Notes                                          |
| ------------------ | -------- | ---------------------------------------------- |
| `backend_legacy/`  | Frozen   | Reference only. Not imported by active runtime |
| `odpt_only` branch | Archived | Legacy ODPT-direct implementation              |
| `old` branch       | Archived | Legacy Streamlit UI                            |

Architecture tests enforce that `backend_legacy/` is not imported by active code.

---

## 開発者向け / Development Reference / 开发参考

<details>
<summary><strong>Tests / テスト / 测试</strong></summary>

### Run all tests

```bash
python -m pytest -v
```

Expected:

* **310+ passed**
* **0 unexplained skips**

### Architecture regression tests

```bash
python -m pytest tests/test_architecture.py -v
```

These tests enforce:

* no ODPT/GTFS imports in `bff/` or `src/`
* no `backend_legacy/` imports in active code
* simulation / optimization use shared run-preparation service
* summary endpoints do not return detail payloads
* built data without `manifest.json` is rejected

</details>

<details>
<summary><strong>Performance / 性能</strong></summary>

### Run performance benchmark

```bash
python tools/benchmark_api.py
```

See:

```text
docs/notes/performance_baseline.md
```

</details>

<details>
<summary><strong>Runtime cleanliness checks / 実行時健全性確認 / 运行时检查</strong></summary>

### Check runtime import graph

```bash
python -c "from bff.main import app; print('import graph OK')"
```

### Check legacy token leakage

```bash
grep -rn "odpt\|gtfs_import\|catalog_import" bff/ src/ --include="*.py" | grep -v "^\s*#"
```

Expected:

* **0 results**

</details>

<details>
<summary><strong>Frontend build / 前端构建</strong></summary>

```bash
cd frontend
npm run build
```

</details>

---

## ディレクトリ構成 / Directory Structure / 目录结构

<details>
<summary><strong>Show directory tree</strong></summary>

```text
master-course/
├── README.md
├── AGENTS.md
├── requirements.txt
├── .gitignore
├── app/
│   └── VERSION
├── data/
│   ├── seed/
│   │   └── tokyu/
│   │       ├── depots.json
│   │       ├── route_to_depot.csv
│   │       ├── version.json
│   │       └── datasets/
│   │           ├── tokyu_core.json
│   │           └── tokyu_full.json
│   └── built/
│       └── <dataset>/
│           ├── manifest.json
│           ├── routes.parquet
│           ├── trips.parquet
│           └── timetables.parquet
├── data-prep/
├── data_prep/
├── schema/
├── src/
├── bff/
├── frontend/
├── tests/
├── tools/
├── scripts/
├── docs/
├── config/
├── constant/
├── outputs/
└── backend_legacy/
```

</details>

---

## ブランチ方針 / Branch Policy / 分支策略

| Branch      | Purpose                                                      |
| ----------- | ------------------------------------------------------------ |
| `main`      | Active development - Tokyu Bus-only research app + data-prep |
| `odpt_only` | Archived - legacy ODPT-direct implementation                 |
| `old`       | Archived - legacy Streamlit UI                               |

---

## ライセンス / License / 许可证

> [!CAUTION]
> 現時点では、このリポジトリに独立したライセンスファイルは含まれていません。
> 维护者未明确发布许可证前，请将其视为 **作者保留权利的研究代码**。
> No standalone license file is currently included. Unless the maintainers publish one explicitly, treat this codebase as **author-retained research code rather than a general open-source release**.
