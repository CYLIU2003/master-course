# 🚌 EV Bus Dispatch Planning System / 电动公交调度规划系统

> **修士研究向け 電動バス配車・充電計画・運行最適化 プロジェクト**
>
> **电动公交调度、充电计划与运营优化 — 硕士研究项目**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/tests-284%20passed-brightgreen.svg)](#13-テスト状況--test-status)

---

## 📖 概要 / Overview / 概述

本リポジトリは、修士研究のための **EVバス（電気バス）の配車・充電スケジューリング・運行最適化** システムです。

時刻表データからバスの配車計画を生成し、電力制約（SOC管理・充電器容量・デマンド料金など）を考慮した最適なスケジュールを求めます。MILP / ALNS / Hybrid の 3 つのソルバーモードをサポートし、シミュレーション・感度分析・ギャップ分析といった研究評価パイプラインを備えます。

**This repository** is a master's research project for **EV bus dispatch, charging, and operations optimization**. It produces dispatch plans from timetable data, computes optimal schedules under power constraints (SOC management, charger capacity, demand charges), and supports three solver modes (MILP / ALNS / Hybrid) along with simulation, sensitivity analysis, and gap analysis pipelines.

本仓库是一个面向硕士研究的 **电动公交调度、充电计划与运营优化** 系统。从时刻表数据生成公交调度计划，在电力约束（SOC 管理、充电桩容量、需量电费等）下求解最优调度方案。支持 MILP / ALNS / Hybrid 三种求解模式，并配备仿真、灵敏度分析和差距分析等研究评估流水线。

---

## 目次 / Table of Contents

1. [ブランチ方針 / Branch Policy](#1-ブランチ方針--branch-policy)
2. [アーキテクチャ / Architecture](#2-アーキテクチャ--architecture)
3. [技術スタック / Tech Stack](#3-技術スタック--tech-stack)
4. [クイックスタート / Quick Start](#4-クイックスタート--quick-start)
5. [開発コマンド / Dev Commands](#5-開発コマンド--dev-commands)
6. [ディレクトリ構成 / Directory Structure](#6-ディレクトリ構成--directory-structure)
7. [研究コア (src/) の設計 / Core Module Design](#7-研究コア-src-の設計--core-module-design)
8. [Dispatch モジュール / Dispatch Module](#8-dispatch-モジュール--dispatch-module)
9. [最適化エンジン / Optimization Engine](#9-最適化エンジン--optimization-engine)
10. [BFF API / BFF API Reference](#10-bff-api--bff-api-reference)
11. [フロントエンド / Frontend](#11-フロントエンド--frontend)
12. [実験ワークフロー / Experiment Workflow](#12-実験ワークフロー--experiment-workflow)
13. [テスト状況 / Test Status](#13-テスト状況--test-status)
14. [10 KPI 定義 / 10 KPI Definitions](#14-10-kpi-定義--10-kpi-definitions)
15. [データ構成 / Data Structure](#15-データ構成--data-structure)
16. [Git ポリシー / Git Policy](#16-git-ポリシー--git-policy)
17. [関連ドキュメント / Related Documents](#17-関連ドキュメント--related-documents)
18. [現在の制約と優先事項 / Limitations & Priorities](#18-現在の制約と優先事項--limitations--priorities)
19. [メンテナー向けメモ / Maintainer Notes](#19-メンテナー向けメモ--maintainer-notes)

---

## 1. ブランチ方針 / Branch Policy / 分支策略

| ブランチ | 役割 |
|---------|------|
| `main` | 現行開発ブランチ（React Frontend + FastAPI BFF + Python Core） |
| `old` | 旧 Streamlit UI 資産の退避ブランチ（原則更新しない） |
| `odpt_only` | Tokyu Bus の ODPT 直結実装を保存する legacy ブランチ |

- 新機能開発は `main` で行います。
- 旧 Streamlit UI は `old` ブランチにアーカイブ済みです（参照が必要な場合: `git checkout old`）。
- Tokyu Bus の旧 ODPT 直結経路は `odpt_only` に保存し、`main` では layered pipeline を標準とします。
- 運用者向けデータガバナンス・ブランチ戦略は [`DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md`](DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md) を参照。

EN: Develop new features on `main`. `old` is archival for legacy Streamlit references.
Tokyu Bus ODPT-direct legacy code is preserved on `odpt_only`.

中文：新功能请在 `main` 开发；`old` 仅用于保留旧版 Streamlit 参考。Tokyu Bus 的 ODPT 直连旧实现保存在 `odpt_only`。

---

## 2. アーキテクチャ / Architecture / 架构

```text
┌───────────────────────────────────────────────────┐
│              React Frontend (frontend/)            │
│  React 19 + TypeScript + Vite 7 + Tailwind CSS v4 │
│  TanStack Query · Zustand · Zod · SVG preview map │
└──────────────────────┬────────────────────────────┘
                       │  HTTP /api (Vite proxy)
┌──────────────────────▼────────────────────────────┐
│              FastAPI BFF (bff/)                    │
│  Scenario / MasterData / Timetable / Graph /       │
│  Simulation / Optimization / Catalog / Jobs        │
│  ── DTO 整形 + ジョブ制御 ──                        │
└──────────────────────┬────────────────────────────┘
                       │  Python import
┌──────────────────────▼────────────────────────────┐
│          Python Research Core (src/)               │
│  dispatch/ · pipeline/ · optimization/ ·           │
│  constraints/ · preprocess/ · schemas/ ·           │
│  simulator · milp_model · data_loader · ...        │
└───────────────────────────────────────────────────┘
```

### 設計原則 / Design Principles / 设计原则

- **Frontend は `/api` のみ呼び出し**、研究ロジックを直接持たない
- **BFF は UI 向け DTO とジョブ制御** を提供する薄いオーケストレーション層
- **コア計算は `src/` に集約**。dispatch / pipeline / optimization / simulator 等
- **Timetable first, dispatch second**: 配車計画は常に時刻表制約から生成
- **`bff/` が正式な研究本体 API**。`backend/` は legacy / 補助用途に限定し、新規機能は追加しない
- **公開情報 Explorer は補助導線**。Planning / Dispatch / Results の初回表示では explorer 詳細を先読みしない
- **Scenario 保存は分割保存優先**。重い timetable / stop_timetable / dispatch artifacts は別ファイル化して本体 JSON を軽量に保つ
- **Scenario artifact は refs ベース**。`scenario.json` は軽量メタのみを保持し、`master_data.sqlite` / `artifacts.sqlite` を参照する

EN: Frontend only calls `/api`. BFF orchestrates APIs/jobs. Core research logic stays in `src/`.

中文：前端仅调用 `/api`，BFF 负责编排与任务管理，核心研究逻辑集中在 `src/`。

---

## 3. 技術スタック / Tech Stack / 技术栈

### Backend (Python)

| ライブラリ | 用途 |
|-----------|------|
| Python 3.11+ | ランタイム |
| FastAPI + Uvicorn | BFF API サーバー |
| pandas ≥ 2.0 | データ処理 |
| scipy ≥ 1.11 | 科学計算 |
| plotly ≥ 5.18 | 可視化 |
| gurobipy *(optional)* | MILP ソルバー（別途 Gurobi ライセンス必須） |

### Frontend

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| React | 19 | UIフレームワーク |
| TypeScript | 5.9 | 型安全 |
| Vite | 7 | 開発サーバー・ビルドツール |
| React Router | 7 | SPA ルーティング |
| TanStack Query | 5 | サーバー状態管理 |
| Zustand | 5 | クライアント状態管理 |
| Zod | 4 | スキーマバリデーション |
| Tailwind CSS | v4 | スタイリング |
| SVG Preview Map | custom | 軽量地図プレビュー |
| React Hook Form | 7 | フォーム管理 |
| i18next | 25 | 国際化 (i18n) |

---

## 4. クイックスタート / Quick Start / 快速开始

### 4.1 前提条件 / Prerequisites / 前置条件

- **Python 3.11+**
- **Node.js 18+** / npm 9+
- （最適化実行時のみ）**Gurobi** + ライセンス

`npm` は Node.js に同梱されています。PowerShell で `npm` が見つからない場合は、
まず Node.js が未導入か、PATH が通っていない可能性を確認してください。

```powershell
node -v
npm -v
```

どちらかが `not recognized` になる場合は、先に Node.js を導入してください。

- Windows:
  [Node.js 公式サイト](https://nodejs.org/) から LTS 版をインストール
- バージョン管理を使う場合:
  `nvm-windows` 等で Node.js 18 以上を導入

インストール後に PowerShell を開き直し、`node -v` と `npm -v` が表示されることを確認してから
`frontend/` で `npm install` を実行してください。

### 4.2 セットアップ / Install Dependencies / 安装依赖

```bash
# Python 依存関係
python -m pip install -r requirements.txt

# Frontend 依存関係
cd frontend
npm install
```

Windows / PowerShell での例:

```powershell
cd D:\master-course\frontend
node -v
npm -v
npm install
```

Remote SSH / 別ホストで frontend と BFF を分けて動かす場合は、
`frontend/.env.example` を元に `frontend/.env.development.local` を作成し、
接続先を明示してください。

```bash
cd frontend
cp .env.example .env.development.local
```

同一リモートホスト上で frontend と BFF を動かす場合の基本設定:

```dotenv
VITE_DEV_HOST=0.0.0.0
VITE_DEV_PORT=5173
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_ODPT_PROXY_TARGET=http://127.0.0.1:3001
```

`VITE_ODPT_PROXY_TARGET` は legacy ODPT proxy を併用する場合のみ必要です。標準の研究 UI では `bff.main:app` を正式バックエンドとします。

frontend から別ホストの BFF を直接叩く場合は、`VITE_API_BASE_URL` に
`http://<backend-host>:8000/api` を設定してください。その場合は BFF 側でも
`BFF_CORS_ALLOW_ORIGINS` または `BFF_CORS_ALLOW_ORIGIN_REGEX` を合わせて設定します。

標準構成では `backend/` の起動は不要です。研究本体は `bff.main:app` と `frontend/` のみを起動してください。

### 4.3 起動 / Run / 启动

**ターミナル 1 — BFF サーバー:**

```bash
python -m uvicorn bff.main:app --reload --host 0.0.0.0 --port 8000
```

**ターミナル 2 — Frontend 開発サーバー:**

```bash
cd frontend
npm run dev
```

VS Code Remote SSH を使う場合は、`8000` と `5173` のポートフォワードを有効にしてください。

### 4.4 アクセス先 / Access URLs / 访问地址

| サービス | URL |
|---------|-----|
| Frontend (UI) | http://localhost:5173/ |
| BFF API | http://localhost:8000/api |
| Health Check | http://localhost:8000/health |

> 起動後、アプリは `GET /api/scenarios/default` を呼び出し、最新シナリオがあればそれを開き、なければデフォルトシナリオを自動作成して `/planning` 画面へ遷移します。
>
> EN: On startup, the app calls `GET /api/scenarios/default`; it opens the latest scenario or auto-creates a default one.
>
> 中文：启动后会调用 `GET /api/scenarios/default`；若无场景会自动创建默认场景并进入操作页面。

---

## 5. 開発コマンド / Dev Commands / 开发命令

```bash
# Python テスト実行
python -m pytest tests/ -q

# 詳細テスト（verbose）
python -m pytest tests/ -v

# Frontend ビルド確認
cd frontend && npm run build

# 独立データ更新アプリ
python catalog_update_app.py --help
python catalog_update_app.py refresh odpt --force-refresh
python catalog_update_app.py sync gtfs --scenario latest --refresh --resources all
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --concurrency 64 --build-bundle
# canonical catalog output: ./data/catalog-fast/canonical/catalog.sqlite

# Frontend Lint
cd frontend && npm run lint

# BFF import 確認
python -c "from bff.main import app; print(f'Routes: {len(app.routes)}')"

# 単一ケース実験実行（Gurobi 必須）
python run_case.py --case config/cases/mode_A_case01.json

# 修論実験エントリポイント（Gurobi 必須）
python run_experiment.py --config config/experiment_config.json
```

---

## 6. ディレクトリ構成 / Directory Structure / 目录结构

```text
master-course/
├── README.md                       # 本ファイル
├── AGENTS.md                       # アーキテクチャ制約と不変条件
├── DEVELOPMENT_NOTES.md            # 研究実験ログ
├── DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md
├── requirements.txt                # Python 依存関係
├── run_case.py                     # ケース別実験 CLI ハーネス
├── run_experiment.py               # 修論実験エントリポイント
│
├── frontend/                       # React 19 + TypeScript + Vite 7
│   ├── src/
│   │   ├── api/                    # API クライアント層 (fetch wrapper)
│   │   ├── app/                    # Router, QueryProvider
│   │   ├── features/               # UI コンポーネント群
│   │   │   ├── common/             # 共通UI: PageSection, EmptyState, TabWarmBoundary 等
│   │   │   ├── explorer/           # 取込進捗 / ログ可視化
│   │   │   ├── layout/             # AppLayout, Header, Sidebar
│   │   │   └── planning/           # 計画系コンポーネント
│   │   ├── hooks/                  # TanStack Query hooks (scenario, master-data, graph, run)
│   │   ├── i18n/                   # 国際化 (日英中)
│   │   ├── pages/                  # ページコンポーネント
│   │   │   ├── planning/           # マスタ計画・シミュレーション環境
│   │   │   ├── inputs/             # 時刻表・デッドヘッド・ルール
│   │   │   ├── dispatch/           # 便・グラフ・勤務・事前確認
│   │   │   ├── results/            # 結果表示（配車・エネルギー・コスト）
│   │   │   ├── scenario/           # シナリオ一覧・概要
│   │   │   ├── compare/            # シナリオ比較
│   │   │   └── odpt/               # ODPT 連携
│   │   ├── stores/                 # Zustand (ui-store, boot-store, import-job-store)
│   │   ├── schemas/                # Zod バリデーション
│   │   ├── types/                  # 型定義 (domain, api)
│   │   ├── utils/                  # ユーティリティ (format, time, perf)
│   │   └── workers/                # 重いUI導出処理の Web Worker
│   └── README.md                   # Frontend 固有の README
│
├── bff/                            # FastAPI BFF (Backend For Frontend)
│   ├── main.py                     # アプリエントリポイント (/api prefix)
│   ├── routers/                    # API ルーター
│   │   ├── scenarios.py            # Scenario CRUD
│   │   ├── timetable.py            # Timetable + Calendar CRUD
│   │   ├── master_data.py          # Depot / Vehicle / Route / Permission CRUD
│   │   ├── catalog.py              # Transit Catalog (ODPT/GTFS import)
│   │   ├── graph.py                # Trips / Connection Graph / Duties
│   │   ├── simulation.py           # Simulation 実行
│   │   ├── optimization.py         # Optimization 実行
│   │   └── jobs.py                 # 非同期ジョブポーリング
│   ├── services/                   # ビジネスロジック
│   │   ├── gtfs_import.py          # GTFS インポート
│   │   ├── odpt_timetable.py       # ODPT 時刻表取得
│   │   ├── odpt_routes.py          # ODPT 路線取得
│   │   ├── odpt_stops.py           # ODPT 停留所取得
│   │   ├── odpt_stop_timetables.py # ODPT 停留所時刻表
│   │   ├── transit_catalog.py      # Transit カタログ管理
│   │   └── transit_db.py           # Transit DB 操作
│   ├── store/                      # Scenario / Job split storage
│   └── mappers/                    # DTO マッパー
│
├── src/                            # 研究コア (Research Core)
│   ├── dispatch/                   # 配車ロジック
│   │   ├── models.py               # DispatchTrip, VehicleDuty 等のデータクラス
│   │   ├── feasibility.py          # 接続可否判定（位置・時刻・車種制約）
│   │   ├── graph_builder.py        # 有向接続グラフ構築
│   │   ├── dispatcher.py           # 貪欲法による配車生成
│   │   ├── validator.py            # 勤務バリデーション
│   │   ├── pipeline.py             # Dispatch パイプライン統合
│   │   ├── context_builder.py      # CSV → DispatchContext 構築
│   │   ├── problemdata_adapter.py  # ProblemData → Dispatch グラフ変換
│   │   └── odpt_adapter.py         # ODPT データ → Dispatch モデル変換
│   │
│   ├── pipeline/                   # パイプライン処理
│   │   ├── build_inputs.py         # 入力データ構築
│   │   ├── solve.py                # MILP 求解メインエントリ
│   │   ├── simulate.py             # シミュレーション実行
│   │   ├── report.py               # レポート生成
│   │   ├── gap_analysis.py         # ギャップ分析
│   │   ├── delay_resilience.py     # 遅延耐性テスト
│   │   ├── sensitivity_runner.py   # 感度分析
│   │   └── logger.py               # パイプラインロガー
│   │
│   ├── optimization/               # 最適化エンジン
│   │   ├── common/                 # 共通インターフェース・正規化問題
│   │   ├── milp/                   # MILP ソルバー
│   │   ├── alns/                   # ALNS (適応大近傍探索)
│   │   ├── hybrid/                 # ハイブリッド (MILP + ALNS)
│   │   ├── rolling/                # ローリングホライゾン
│   │   └── engine.py               # ソルバーエントリポイント
│   │
│   ├── constraints/                # 制約定義
│   │   ├── assignment.py           # 車両割当制約
│   │   ├── charging.py             # 充電制約
│   │   ├── energy_balance.py       # エネルギー収支
│   │   ├── duty_assignment.py      # 勤務割当
│   │   ├── charger_capacity.py     # 充電器容量
│   │   ├── battery_degradation.py  # バッテリー劣化
│   │   ├── soc_threshold_charging.py # SOC 閾値充電
│   │   ├── optional_v2g.py         # V2G (Vehicle-to-Grid)
│   │   └── pv_grid.py              # PV・系統連携
│   │
│   ├── preprocess/                 # 前処理
│   │   ├── energy_model.py         # 電費推定モデル
│   │   ├── fuel_model.py           # 燃費モデル
│   │   ├── deadhead_builder.py     # デッドヘッド走行構築
│   │   ├── duty_loader.py          # 勤務データ読込
│   │   ├── passenger_load.py       # 乗客荷重
│   │   ├── route_builder.py        # 路線構築
│   │   ├── tariff_loader.py        # 電気料金読込
│   │   ├── timetable_generator.py  # 時刻表生成
│   │   ├── trip_converter.py       # 便変換
│   │   ├── trip_generator.py       # 便生成
│   │   └── scenario_generator.py   # シナリオ生成
│   │
│   ├── schemas/                    # 内部スキーマ定義
│   │   ├── duty_entities.py        # 勤務エンティティ
│   │   ├── fleet_entities.py       # 車両エンティティ
│   │   ├── route_entities.py       # 路線エンティティ
│   │   └── trip_entities.py        # 便エンティティ
│   │
│   ├── data_loader.py              # load_problem_data()
│   ├── data_schema.py              # ProblemData 定義
│   ├── milp_model.py               # MILP モデル構築
│   ├── model_factory.py            # モデルファクトリ
│   ├── model_sets.py               # build_model_sets()
│   ├── objective.py                # 目的関数構築
│   ├── parameter_builder.py        # build_derived_params()
│   ├── simulator.py                # スケジュール実行可能性チェック
│   ├── solver_runner.py            # Gurobi ソルバー実行
│   ├── solver_alns.py              # ALNS ソルバー
│   ├── route_cost_simulator.py     # 路線コストシミュレータ
│   ├── result_exporter.py          # 結果エクスポート
│   ├── visualization.py            # 可視化
│   ├── engine_bus_extractor.py     # エンジンバス性能抽出
│   └── engine_bus_loader.py        # エンジンバスデータ読込
│
├── tests/                          # テストスイート (24 テストファイル)
│   ├── test_dispatch_*.py          # Dispatch モジュールテスト (6 ファイル)
│   ├── test_bff_*.py               # BFF ルーターテスト (8 ファイル)
│   ├── test_simulator.py           # シミュレータテスト
│   ├── test_route_cost_simulator.py # 路線コストシミュレータテスト
│   ├── test_optimization_engine.py # 最適化エンジンテスト
│   ├── test_energy_model.py        # 電費モデルテスト
│   ├── test_engine_bus_*.py        # エンジンバステスト (2 ファイル)
│   └── ...
│
├── schema/                         # JSON Schema 定義 (12 ファイル)
│   ├── canonical-problem.schema.json
│   ├── dispatch_input.schema.json
│   ├── scenario.schema.json
│   ├── vehicle.schema.json
│   ├── trip.schema.json
│   └── ...
│
├── config/                         # 実験・テスト設定
│   ├── cases/                      # ケース別設定
│   │   ├── mode_A_case01.json      # Mode A: 行路後充電決定 ✅ VERIFIED
│   │   ├── mode_B_case01.json      # Mode B: 車両割当+充電同時最適化 ✅ VERIFIED
│   │   ├── mode_B_case01_build_inputs.json
│   │   └── toy_mode_A_case01.json  # Toy: 手計算検証用 ✅ VERIFIED
│   └── experiment_config.json      # 修論実験設定
│
├── data/                           # 入力データ
│   ├── cases/                      # 実験ケースデータ
│   ├── toy/                        # 検証用トイデータ
│   ├── engine_bus/                 # エンジンバス参照データ
│   ├── external/                   # 外部データ
│   ├── fleet/                      # 車両フリートデータ
│   ├── infra/                      # インフラデータ（充電器等）
│   ├── operations/                 # 運行データ
│   ├── route_master/               # 路線マスタ
│   ├── sim_configs/                # シミュレーション設定
│   └── vehicle_catalog.json        # 車両カタログ
│
├── GTFS/                           # GTFS データ (都営バス)
│   └── ToeiBus-GTFS/
│
├── constant/                       # 読取専用の研究仕様書・指示書
│   ├── README.md                   # 文書インデックス
│   ├── formulation.md              # MILP 数理定式化
│   ├── masters_thesis_simulation_spec_v2.md  # 修論仕様書
│   └── ...                         # (詳細は constant/README.md 参照)
│
├── docs/                           # 開発ドキュメント
│   ├── dispatch_preprocess_config.md
│   ├── dispatch_contracts.md
│   ├── reproduction_spec.md
│   └── ...
│
├── scripts/                        # ユーティリティスクリプト
│   ├── batch_sensitivity.py        # バッチ感度分析
│   ├── dispatch_prototype.py       # Dispatch プロトタイプ
│   ├── run_route_cost_sim.py       # 路線コストシミュレーション実行
│   ├── extract_engine_bus.py       # エンジンバスデータ抽出
│   └── query_engine_bus.py         # エンジンバスデータ照会
│
└── outputs/                        # 実行出力 (.gitignore 管理)
```

---

## 7. 研究コア (src/) の設計 / Core Module Design / 研究核心设计

`src/` は研究計算のすべてを担います。UI や API 層からは独立しており、単独でテスト・実行可能です。

EN: `src/` handles all research computation. It is independent of UI and API layers and can be tested/run standalone.

中文：`src/` 承担所有研究计算。它独立于 UI 和 API 层，可单独测试与运行。

### データフロー

```text
config/*.json ──→ data_loader.py ──→ ProblemData
                                          │
                                     model_sets.py ──→ ModelSets
                                          │
                                  parameter_builder.py ──→ DerivedParams
                                          │
                              ┌───────────┼────────────┐
                              ▼           ▼            ▼
                        milp_model.py  solver_alns.py  optimization/
                              │           │            │
                              └───────────┼────────────┘
                                          ▼
                                     MILPResult
                                          │
                                   simulator.py ──→ SimulationResult
                                          │
                              ┌───────────┼────────────┐
                              ▼           ▼            ▼
                      gap_analysis  delay_resilience  report
```

### 主要エントリポイント

| ファイル | 関数 | 説明 |
|---------|------|------|
| `pipeline/solve.py` | `solve(config_path, mode)` | パイプラインメイン。データ読込→求解→シミュレーション→レポート |
| `data_loader.py` | `load_problem_data(path)` | 設定 JSON から `ProblemData` を構築 |
| `model_sets.py` | `build_model_sets(data)` | 車両・タスク・充電器の集合を構築 |
| `parameter_builder.py` | `build_derived_params(data, ms)` | 派生パラメータ（エネルギー消費率等）を計算 |
| `simulator.py` | `simulate(data, ms, dp, result)` | ソルバー結果の実行可能性を検証 |

---

## 8. Dispatch モジュール / Dispatch Module / 调度模块

`src/dispatch/` は **Timetable first, dispatch second** の不変条件を厳守します。

EN: Physically impossible chains are hard-infeasible and must never appear in output.

中文：任何物理上不可行的班次连接都属于硬约束违规，禁止出现在输出中。

### 接続可否判定（ハード制約）

車両がトリップ **j** をトリップ **i** の直後に運行できるのは、以下の **3条件すべて** を満たす場合のみです：

| # | 制約 | 条件 |
|---|------|------|
| 1 | **位置連続性** | `trip_i.destination → trip_j.origin` のデッドヘッド移動が可能 |
| 2 | **時刻連続性** | `arrival(i) + turnaround + deadhead_time ≤ departure(j)` |
| 3 | **車種制約** | `vehicle_type ∈ trip_j.allowed_vehicle_types` |

### 処理パイプライン

```text
1. 時刻表データ読込
2. 候補ペアの接続可否チェック (feasibility.py)
3. 有向接続グラフ構築 (graph_builder.py)
4. 配車勤務生成 — 貪欲法ベースライン (dispatcher.py)
5. 生成された勤務のバリデーション (validator.py)
```

### 出力

- `VehicleDuty`: `duty_id`, `vehicle_type`, `legs` (deadhead 付き DutyLeg 列)
- `ValidationResult`: `valid`, `errors`
- `PipelineResult`: `uncovered_trip_ids`, `duplicate_trip_ids`, `invalid_duties`

> 詳細は [`AGENTS.md`](AGENTS.md) を参照。

---

## 9. 最適化エンジン / Optimization Engine / 优化引擎

`src/optimization/` は 3 つのソルバーモードをサポートします。

| モード | 説明 | 用途 |
|-------|------|------|
| `milp` | 混合整数線形計画法 | ベースライン・厳密解 |
| `alns` | 適応大近傍探索 | 大規模探索 |
| `hybrid` | MILP + ALNS | **デフォルト研究モード** |

### レイヤー構成

```text
optimization/
├── common/     # 共通インターフェース、正規化問題オブジェクト
├── milp/       # MILP ソルバー (Gurobi 抽象化)
├── alns/       # ALNS ソルバー
│   ├── destroy operators
│   ├── repair operators
│   ├── acceptance criterion
│   ├── operator selection
│   └── stopping criterion
├── hybrid/     # MILP初期解 + ALNS探索 + MILP部分修復
└── rolling/    # ローリングホライゾン再最適化
```

### MILP 設計ルール

- ソルバーバックエンドは抽象化（Gurobi 固有 API をビジネスロジックに埋め込まない）
- Warm start / time limit / MIP gap は設定可能
- 不実行可能性診断を出力

### Hybrid モード

1. MILP で初期解を生成
2. ALNS 外部ループで探索
3. 部分 MILP 修復
4. Incumbent polishing

### 将来の拡張ポイント

- フリート構成最適化
- 充電器配置探索
- Column Generation (`ColumnPool`, `PricingProblem`)
- GTFS 前処理フック拡張

---

## 10. BFF API / BFF API Reference / BFF API 参考

すべてのエンドポイントは `/api` プレフィックス下にマウントされます。

### Scenario

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/scenarios` | シナリオ一覧 |
| POST | `/api/scenarios` | シナリオ作成 |
| GET | `/api/scenarios/default` | デフォルトシナリオ取得/作成 |
| GET | `/api/scenarios/{id}` | シナリオ詳細 |
| PUT | `/api/scenarios/{id}` | シナリオ更新 |
| DELETE | `/api/scenarios/{id}` | シナリオ削除 |

### Master Data（Depot / Vehicle / Route / Permission）

| メソッド | パス | 説明 |
|---------|------|------|
| GET/POST | `/api/scenarios/{id}/depots` | 営業所 CRUD |
| GET/POST | `/api/scenarios/{id}/vehicles` | 車両 CRUD |
| GET/POST | `/api/scenarios/{id}/routes` | 路線 CRUD |
| PUT/DELETE | `.../depots/{depotId}` 等 | 個別更新・削除 |
| GET/PUT | `.../depot-route-permissions` | 営業所→路線 許可 |
| GET/PUT | `.../depot-route-family-permissions` | 営業所→route family 一括許可 |
| GET/PUT | `.../vehicle-route-permissions` | 車両→路線 許可 |
| GET/PUT | `.../vehicle-route-family-permissions` | 車両→route family 一括許可 |

### Timetable & Calendar

| メソッド | パス | 説明 |
|---------|------|------|
| GET/PUT | `/api/scenarios/{id}/timetable` | 時刻表 CRUD |
| GET/PUT | `/api/scenarios/{id}/calendar` | 運行カレンダー |

### Dispatch Pipeline

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/scenarios/{id}/build-trips` | 便生成 |
| POST | `/api/scenarios/{id}/subset-export` | 現在の営業所・route family・route scope を研究入力 JSON として保存 |
| POST | `/api/scenarios/{id}/build-graph` | 接続グラフ構築 |
| POST | `/api/scenarios/{id}/generate-duties` | 勤務生成 |
| GET | `/api/scenarios/{id}/duties/validate` | 勤務バリデーション |

### Simulation / Optimization

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/scenarios/{id}/run-simulation` | シミュレーション実行 |
| POST | `/api/scenarios/{id}/run-optimization` | 最適化実行 |

### Transit Catalog (ODPT / GTFS)

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/catalog/gtfs/import` | GTFS インポート |
| GET | `/api/catalog/operators` | 事業者一覧 |
| GET | `/api/catalog/operators/{operatorId}/route-families` | 事業者別 route family summary |
| GET | `/api/catalog/operators/{operatorId}/route-families/{routeFamilyId}` | 事業者別 route family detail |

### Jobs

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/jobs/{job_id}` | ジョブステータス取得 |

> **永続化**: シナリオデータは `outputs/scenarios/` の split artifact (`scenario.json` + `master_data.sqlite` + `artifacts.sqlite` + parquet) として保存されます。ジョブステータスは `outputs/jobs/*.json` に永続化され、再起動時の in-progress job は orphaned failed として可視化されます。
>
> EN: Scenario documents are persisted as JSON files under `outputs/scenarios/`. Job status is stored in-memory (ephemeral).
>
> 中文：场景数据以 JSON 文件保存到 `outputs/scenarios/`；任务状态为内存存储（服务重启后不保留）。

---

## 11. フロントエンド / Frontend / 前端

### タブ構成

| タブ | 名称 | 内容 |
|-----|------|------|
| **Tab 1** | Planning（営業所・車両・路線） | マスタデータ管理 |
| **Tab 2** | Simulation（シミュレーション環境） | シミュレーション設定 |

これに加え、**Dispatch**（配車パイプライン）と **Results**（結果表示）セクションが常時表示されます。

### ユーザーワークフロー

```text
1. 営業所を作成
2. 車両を営業所に追加
3. 路線を作成
4. route family を確認しながら営業所→route family / route 許可を設定
5. route family を確認しながら車両→route family / route 許可を設定
6. シミュレーション環境を設定
7. 必要なら現在の depot + route family scope を subset export
8. Dispatch パイプラインを実行（便生成→グラフ構築→勤務生成）
9. 結果を確認
```

### ドメインモデル

```text
Depot ──1:N──→ Vehicle (vehicle.depotId)
Depot ──M:N──→ Route   (DepotRoutePermission)
Vehicle ──M:N──→ Route  (VehicleRoutePermission)
Route ──1:N──→ Trip
```

### 主要ルート

| パス | ページ |
|------|--------|
| `/scenarios` | シナリオ一覧 |
| `/scenarios/:id/planning` | マスタ計画（Tab 1） |
| `/scenarios/:id/simulation-env` | シミュレーション環境（Tab 2） |
| `/scenarios/:id/timetable` | 時刻表管理 |
| `/scenarios/:id/trips` | 便一覧 |
| `/scenarios/:id/graph` | 接続グラフ |
| `/scenarios/:id/duties` | 勤務表 |
| `/scenarios/:id/simulation` | シミュレーション実行 |
| `/scenarios/:id/optimization` | 最適化実行 |
| `/scenarios/:id/results/*` | 結果（配車/エネルギー/コスト） |
| `/compare` | シナリオ比較 |

> 詳細は [`frontend/README.md`](frontend/README.md) を参照。

### 大規模時刻表対応 UI

- ODPT / GTFS の重い更新処理は main app から切り離し、`catalog_update_app.py` で個別実行できます。通常の frontend/BFF 起動では保存済み catalog / scenario データを使います。
- `AppBootstrapManager` と `BootSplashOverlay` が scenario 起動時に段階 prefetch を行い、進捗率・ステップ名・件数を表示します。依存のない `master / timetable / explorer` は並列 prewarm です。
- Scenario import / Public Data Explorer は保存済み snapshot を優先して読み込みます。snapshot が無い状態では自動 refresh せず、`forceRefresh=true` を明示したときだけ app 側で更新を実行します。
- 時刻表 UI は summary-first です。`/timetable/summary` と `/stop-timetables/summary` を先に読み、全件本文は `limit/offset` page に遅延します。
- dispatch UI も summary-first です。`/trips/summary`、`/graph/summary`、`/duties/summary` を先に読み、一覧は page API で取得します。
- Planning と Public Data Explorer の両方で route family detail panel を開けるようになっており、variant / canonical pair / timetable diagnostics を同じ見た目で確認できます。
- `TabWarmBoundary` が planning / timetable / public-data / dispatch タブの warm state を扱い、重い tab mount を抑制します。
- `ImportJobStore`、`ImportProgressPanel`、`ImportLogPanel` が ODPT / GTFS import と public-data sync の進捗・ログを共通方式で表示します。
- 大きい一覧は `VirtualizedList` に統一し、explorer の depot assignment sort は `assignment-sort.worker.ts`、route family grouping は `route-family-group.worker.ts`、public diff preview は `public-diff-preview.worker.ts` へオフロードしています。
- Router は route-level lazy loading を採用し、Vite build の main chunk は縮小済みです。Planning 地図は lightweight SVG preview を使い、重い map runtime を初期 bundle に含めません。
- `/jobs/{job_id}` poll により、Trips / Graph / Duties / Simulation / Optimization の backend job progress を画面側で確認できます。
- 開発モードの `DebugPerfOverlay` は常時表示ではありません。`?debugPerf=1` を URL に付けるか、`localStorage["debug-perf"]="1"` を設定したときだけ render count、selector time、import time、tab switch time、long task、heap 使用量を右下に表示します。

### 独立データ更新アプリ

`catalog_update_app.py` は ODPT / GTFS の catalog refresh と scenario sync を行う standalone Python app です。通常運用ではこの CLI で先に snapshot を更新し、frontend 側はその snapshot を参照して差分確認・取込を行います。

```powershell
# PowerShell / Windows 推奨
.\catalog_update_app.ps1 --help
.\catalog_update_app.ps1 refresh odpt --force-refresh
.\catalog_update_app.ps1 refresh gtfs --feed-path GTFS/ToeiBus-GTFS
.\\catalog_update_app.ps1 refresh gtfs-pipeline --source-dir .\\data\\raw-odpt
.\catalog_update_app.ps1 sync odpt --scenario latest --refresh --resources all
.\catalog_update_app.ps1 sync gtfs --scenario latest --refresh --resources routes,stops,timetable,stop-timetables,calendar
```

```bash
# 直接 python を使う場合
python catalog_update_app.py --help
python catalog_update_app.py refresh odpt --force-refresh
python catalog_update_app.py refresh gtfs --feed-path GTFS/ToeiBus-GTFS
python catalog_update_app.py refresh gtfs-pipeline --source-dir ./data/raw-odpt
python catalog_update_app.py sync odpt --scenario latest --refresh --resources all
python catalog_update_app.py sync gtfs --scenario latest --refresh --resources routes,stops,timetable,stop-timetables,calendar
python catalog_update_app.py refresh odpt --fast-path --out-dir ./data/catalog-fast --concurrency 64 --resume
python catalog_update_app.py sync odpt --scenario latest --refresh --resources all --fast-path --out-dir ./data/catalog-fast --concurrency 64

# 対話メニュー
python catalog_update_app.py
```

PowerShell で `python3` を使うと、環境によっては Python 本体ではなく Windows の alias 側に吸われて期待通りに動かないことがあります。`python` か `.\catalog_update_app.ps1` を使ってください。

### Tokyu Bus ODPT → GTFS Pipeline / 东急巴士 ODPT → GTFS 流水线

Tokyu Bus については、ODPT の生 JSON を直接研究本体や UI に読ませず、次の 4 層で処理します。

For Tokyu Bus, do not feed raw ODPT JSON directly into the research core or UI. Always use the layered pipeline below.

对于东急巴士，不要将原始 ODPT JSON 直接送入研究核心或 UI。必须经过以下分层流水线。

```text
Raw ODPT -> Raw Archive -> Canonical JSONL -> GTFS + Sidecar -> Research Features
```

標準の実行順 / Standard execution order / 标准执行顺序:

1. `tools.fast_catalog_ingest` で raw ODPT を取得
2. `src.tokyubus_gtfs` で `archive -> canonical -> gtfs -> features`
3. `validate` で GTFS の必須ファイル・件数整合・参照整合を監査

```bash
# 1. Fetch ODPT raw bundle
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --concurrency 64 --build-bundle

# 2. Run the full Tokyu layered pipeline
python -m src.tokyubus_gtfs run --source-dir ./data/catalog-fast

# 3. Audit the GTFS export
python -m src.tokyubus_gtfs validate --snapshot <snapshot_id>
```

`run` は `./data/catalog-fast/raw/` でも動きます。入力として受け付けるのは `BusstopPole.json`、`busstop_pole.json`、`*.ndjson` などの raw ファイルです。

段階実行したい場合は次の順です。

```bash
python -m src.tokyubus_gtfs archive --source-dir ./data/catalog-fast
python -m src.tokyubus_gtfs canonical --snapshot <snapshot_id>
python -m src.tokyubus_gtfs gtfs --snapshot <snapshot_id>
python -m src.tokyubus_gtfs features --snapshot <snapshot_id>
python -m src.tokyubus_gtfs validate --snapshot <snapshot_id>
```

出力先 / Outputs / 输出目录:

- Raw archive: `data/tokyubus/raw/{snapshot_id}/`
- Canonical: `data/tokyubus/canonical/{snapshot_id}/`
- GTFS: `GTFS/TokyuBus-GTFS/`
- Features: `data/tokyubus/features/{snapshot_id}/`
- Manual route-family map: `data/tokyubus/manual/route_family_map.csv`

Tokyu GTFS export now writes `feed_metadata.json` and `validation_report.json` under `GTFS/TokyuBus-GTFS/`.
Representative sidecars now include `sidecar_route_family_map.json`, `sidecar_pattern_role_map.json`, `sidecar_service_profile.json`, and `sidecar_depot_candidate_map.json`.

東急 GTFS を family ベースの `routes.txt` に切り替える前に、`data/tokyubus/manual/route_family_map.csv` を先に手で整備してください。

Before switching Tokyu GTFS export to family-based `routes.txt`, curate `data/tokyubus/manual/route_family_map.csv` first.

东急 GTFS 在切换到 family 级 `routes.txt` 之前，应先维护 `data/tokyubus/manual/route_family_map.csv`。

この CSV は、現在 trip が付いている pattern を seed として並べた初期マッピングです。`direction_bucket` と `pattern_role` は必ず人手で再確認してください。

GTFS validation checks:

- required GTFS files
- count alignment against `canonical_summary.json`
- route/trip/stop/service/shape referential integrity
- sidecar presence and entry counts (`service_profile`, `route_family_map`, `pattern_role_map`, `depot_candidate_map`)
- service coverage summary (`trip_count`, `public_trip_count`, `deadhead_trip_count` by `service_id`)
- duplicate `stop_sequence`, time regression, `arrival_time > departure_time`
- optional external validator command output

`catalog_update_app.py` 経由で一括実行する場合はこれです。

```bash
python catalog_update_app.py refresh gtfs-pipeline --source-dir ./data/catalog-fast
```

### 高速 ingest CLI / Fast ingest CLI / 高速采集 CLI

ODPT の重い raw 取得を高速化したい場合は `tools/fast_catalog_ingest.py` を使えます。raw JSON を保持しつつ、`raw/*.ndjson`、checkpoint、`bundle.json`、`operational_dataset.json` を生成します。

`httpx` の HTTP/2 を使える環境では自動で HTTP/2 を使います。`h2` が未導入でも
CLI は HTTP/1.1 に自動フォールバックします。HTTP/2 を明示的に無効化したい場合は
`--http1-only` を使ってください。必要なら次でも導入できます。

```bash
python -m pip install "httpx[http2]"
```

```bash
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --concurrency 64 --build-bundle
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --concurrency 64 --http1-only --build-bundle
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --resume --only stopTimetables --build-bundle
python -m tools.fast_catalog_ingest fetch-odpt --out-dir ./data/catalog-fast --skip-stop-timetables --build-bundle
python -m tools.fast_catalog_ingest sync-gtfs --scenario latest --refresh --resources all
```

ベースライン比較と profiling も別 CLI で実行できます。

```bash
python tools/benchmark_catalog_ingest.py odpt --include-baseline --out-dir ./data/catalog-fast
python tools/benchmark_catalog_ingest.py gtfs --scenario latest --resources all --refresh
python tools/profile_catalog_ingest.py catalog -- refresh odpt --force-refresh
python tools/profile_catalog_ingest.py fast -- fetch-odpt --out-dir ./data/catalog-fast --concurrency 64 --build-bundle
```

この分離により、通常の frontend / BFF 起動時に ODPT / GTFS refresh を前提にしない運用ができます。機能自体は main app 側にも残りますが、重い更新作業は updater app 側で行う想定です。

### Feed Identity / Feed ID 設計 / Feed 标识设计

混線防止のため、GTFS 系 feed は永続 `feed_id` を持ちます。

To prevent Toei/Tokyu collisions, GTFS-backed datasets use stable feed identities.

为避免都营与东急在内部 ID 上发生冲突，GTFS 数据集使用稳定的 `feed_id`。

| Feed | feed_id | snapshot_id example | dataset_id example |
|------|---------|---------------------|--------------------|
| Toei Bus GTFS | `toei_gtfs` | `2026-03-09-official` | `toei_gtfs:2026-03-09-official` |
| Tokyu Bus ODPT→GTFS | `tokyu_odpt_gtfs` | `2026-03-09T180500Z` | `tokyu_odpt_gtfs:2026-03-09T180500Z` |

API / runtime bundle / GTFS import payloads should expose scoped identifiers alongside raw IDs:

```text
scoped_route_id   = "{feed_id}:{route_id}"
scoped_trip_id    = "{feed_id}:{trip_id}"
scoped_stop_id    = "{feed_id}:{stop_id}"
scoped_service_id = "{feed_id}:{service_id}"
```

---

## 12. 実験ワークフロー / Experiment Workflow / 实验工作流

### CLI による単一ケース実験

```bash
# Mode A: 行路後充電決定
python run_case.py --case config/cases/mode_A_case01.json

# Mode B: 車両割当+充電同時最適化
python run_case.py --case config/cases/mode_B_case01.json

# Toy ケース（手計算検証用）
python run_case.py --case config/cases/toy_mode_A_case01.json

# Verbose（Gurobi ログ表示）
python run_case.py --case config/cases/mode_A_case01.json --verbose
```

### 出力ファイル

各ケースの結果は `results/{case_name}/` に出力されます：

| ファイル | 内容 |
|---------|------|
| `kpi.json` | 10 KPI の数値データ |
| `kpi.csv` | 論文比較用フラット CSV |
| `report.md` | 実験サマリ Markdown |

### 修論実験（フル機能）

```bash
python run_experiment.py \
    --config config/experiment_config.json \
    --time-limit 300 \
    --verbose
```

オプション: `--no-pv`, `--no-demand-charge`, `--soft-soc`, `--allow-partial`

---

## 13. テスト状況 / Test Status / 测试状态

```
最終実行: 2026-03-08
コマンド: python -m pytest tests/ -q
結果:   284 passed ✅
```

### テストカバレッジ（主要領域）

| カテゴリ | テストファイル | 件数 |
|---------|--------------|------|
| Dispatch | `test_dispatch_feasibility.py`, `test_dispatch_graph.py`, `test_dispatch_validator.py`, `test_dispatch_pipeline.py`, `test_dispatch_context_builder.py`, `test_dispatch_problemdata_adapter.py` | 6 |
| BFF Routers | `test_bff_graph_router.py`, `test_bff_scenario_store.py`, `test_bff_gtfs_import.py`, `test_bff_odpt_*.py`, `test_bff_optimization_router.py`, `test_bff_runtime_capabilities.py`, `test_bff_scenario_to_problemdata.py` | 8 |
| Simulator | `test_simulator.py` | 1 |
| Route Cost | `test_route_cost_simulator.py` | 1 |
| Optimization | `test_optimization_engine.py` | 1 |
| Data Loader | `test_data_loader_dispatch_preprocess.py` | 1 |
| Energy Model | `test_energy_model.py` | 1 |
| Engine Bus | `test_engine_bus_extractor.py`, `test_engine_bus_loader.py` | 2 |
| Pipeline | `test_pipeline_solve_dispatch_report.py` | 1 |
| Jobs | `test_job_store.py` | 1 |

> ⚠️ コード変更時は、既存テストがすべて通ることを確認してください。
>
> EN: Keep all pre-existing tests green when making code changes.
>
> 中文：进行任何代码修改时，必须保持现有测试全部通过。

---

## 14. 10 KPI 定義 / 10 KPI Definitions / 10 KPI 定义

全ソルバーモード共通の評価指標です。

| KPI | 説明 | 単位 |
|-----|------|------|
| `objective_value` | ソルバー目的関数値 | 円 |
| `total_energy_cost` | 電力量料金合計 | 円 |
| `total_demand_charge` | デマンド料金合計 | 円 |
| `total_fuel_cost` | ICE 燃料費合計 | 円 |
| `vehicle_fixed_cost` | 使用車両の固定費合計 | 円 |
| `unmet_trips` | 未割当タスク数 | 件 |
| `soc_min_margin_kwh` | SOC 下限余裕（最小 SOC − 下限閾値） | kWh |
| `charger_utilization` | 充電器平均稼働率 | % |
| `peak_grid_power_kw` | 系統ピーク受電電力 | kW |
| `solve_time_sec` | ソルバー計算時間 | 秒 |

---

## 15. データ構成 / Data Structure / 数据结构

### 実験ケースデータ

| ケース | 車両構成 | タスク数 | 検証状態 |
|-------|---------|---------|---------|
| `mode_A_case01` | 3 BEV | 6 タスク, 64 スロット (15分/スロット) | ✅ VERIFIED |
| `mode_B_case01` | 3 BEV + 1 ICE | 8 タスク | ✅ VERIFIED |
| `toy_mode_A_case01` | 2 BEV | 5 タスク, 20 スロット (60分/スロット) | ✅ VERIFIED (手計算一致) |

### 外部データ

| データ | 格納先 | 説明 |
|-------|-------|------|
| GTFS | `GTFS/ToeiBus-GTFS/` | 都営バス GTFS データ |
| Tokyu Bus GTFS | `GTFS/TokyuBus-GTFS/` | Tokyu Bus layered pipeline の出力 GTFS + sidecars (`service_profile` / `route_family_map` / `pattern_role_map` / `depot_candidate_map`) + `feed_metadata.json` + `validation_report.json` |
| Tokyu Canonical | `data/tokyubus/canonical/` | Tokyu Bus canonical JSONL + `canonical_summary.json` |
| Tokyu Features | `data/tokyubus/features/` | Tokyu Bus research feature store |
| ODPT | `data/odpt_tokyu.db` 等 | 公共交通 Open Data |
| 車両カタログ | `data/vehicle_catalog.json` | BEV/ICE 車両仕様 |
| エンジンバス参照 | `data/engine_bus/` + `constant/*.xlsx` | JH25 年式バス性能データ |
| 路線マスタ | `data/route_master/` | 路線定義 CSV |
| 運行データ | `data/operations/` | 運行実績 CSV |

### JSON Schema

`schema/` ディレクトリに 12 の JSON Schema 定義があります：

- `canonical-problem.schema.json` — 正規化問題
- `dispatch_input.schema.json` — Dispatch 入力 (8.6KB)
- `scenario.schema.json` — シナリオ
- `vehicle.schema.json`, `trip.schema.json`, `depot.schema.json`, `charger.schema.json` 等

---

## 16. Git ポリシー / Git Policy / Git 策略

生成物は追跡しません（`.gitignore` で管理）。

| 除外対象 | 理由 |
|---------|------|
| `outputs/`, `derived/`, `results/` | 実行時生成物 |
| `__pycache__/`, `*.pyc` | Python バイトコード |
| `frontend/node_modules/`, `frontend/dist/` | Frontend ビルド成果物 |
| `*.db`, `*.sqlite3` | インポート時生成 DB |
| `.venv/`, `.env` | 環境固有設定 |

`GTFS/TokyuBus-GTFS/feed_metadata.json`、`GTFS/TokyuBus-GTFS/validation_report.json`、`GTFS/TokyuBus-GTFS/sidecar_*.json` も通常は生成物として扱います。

> 明示的にリリースパッケージに含める必要がない限り、生成物をコミットしないでください。
>
> EN: Do not commit generated artifacts unless explicitly required for release packaging.
>
> 中文：除非发布流程明确要求，否则不要提交构建/运行生成物。

---

## 17. 関連ドキュメント / Related Documents / 相关文档

| ドキュメント | 内容 |
|------------|------|
| [`AGENTS.md`](AGENTS.md) | アーキテクチャ制約 / 非交渉点 / 最適化エンジン設計 |
| [`DEVELOPMENT_NOTES.md`](DEVELOPMENT_NOTES.md) | 研究実験ログ / 実験結果 / バグ修正履歴 |
| [`DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md`](DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md) | 運用者向けデータガバナンス / ブランチ戦略 |
| [`frontend/README.md`](frontend/README.md) | Frontend 詳細ドキュメント |
| [`constant/README.md`](constant/README.md) | 研究仕様書・文書インデックス |
| [`docs/dispatch_preprocess_config.md`](docs/dispatch_preprocess_config.md) | Dispatch 前処理設定ガイド |
| [`docs/dispatch_contracts.md`](docs/dispatch_contracts.md) | Dispatch API 契約 |
| [`docs/reproduction_spec.md`](docs/reproduction_spec.md) | 先行研究再現仕様 |

---

## 18. 現在の制約と優先事項 / Limitations & Priorities / 当前限制与优先事项

### 未完了の主要タスク

1. **シナリオ保存の原子性向上** — split artifact を temp dir → rename で丸ごと切り替える
2. **Frontend lint backlog の解消** — hook / setState-in-effect / perf utility の整理
3. **Catalog quality dashboard の拡充** — linkage / warning trend / low-confidence breakdown の可視化
4. **Experiment reproducibility の明示** — dataset fingerprint / snapshot / seed を compare/export UI でさらに強調
5. **Simulation 設定画面** — 実データ接続の細部改善
6. **Editor Drawer / compare / results の磨き込み** — 導線と比較UXの最終調整

### 前提のある機能

- **完全な最適化機能**: Gurobi のインストールとライセンスが必要
- **ODPT データ取得**: インターネット接続と API キーが必要

EN: Full optimization requires Gurobi installation and license.

中文：完整优化功能依赖 Gurobi 安装与许可证。

---

## 19. メンテナー向けメモ / Maintainer Notes / 维护者说明

1. **研究ロジックは `src/` に集約** — UI 層 (`frontend/`) や API 層 (`bff/`) に研究ロジックを埋め込まない
2. **BFF は薄いオーケストレーション + DTO 整形** を維持
3. **`constant/` は読み取り専用** — 明示的な指示がない限り変更しない
4. **Dispatch モジュールは Timetable-driven** を維持し、物理的に実行不可能な出力を禁止
5. **時刻変換は `hhmm_to_min()`** を正式関数とし、整数分（midnight 基準）で比較
6. **デッドヘッドは有向** （from → to）で、対称性を仮定しない
7. **依存関係の方向**: `src/dispatch/` は `frontend/`, `bff/`, `src/constraints/`, `src/pipeline/` をインポートしない

EN: Keep the dispatch module timetable-driven and physically feasible by construction.

中文：保持调度模块“时刻表优先”，并确保输出在物理约束上始终可行。

---

*Last updated: 2026-03-08*
