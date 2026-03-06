# EV Bus Dispatch Planning System (Master Course) / EV Bus Dispatch Planning System / 电动公交调度规划系统（硕士研究）

このリポジトリは、修士研究向けの **EVバス配車・充電計画・運行最適化** プロジェクトです。現行 `main` ブランチは **React Frontend + FastAPI BFF + Python Core (`src/`)** を前提に開発しています。

This repository is a master's research project for **EV bus dispatch, charging planning, and operations optimization**. The current `main` branch follows a **React Frontend + FastAPI BFF + Python Core (`src/`)** architecture.

本仓库是一个面向硕士研究的 **电动公交调度、充电计划与运营优化** 项目。当前 `main` 分支采用 **React 前端 + FastAPI BFF + Python Core (`src/`)** 架构。

---

## 1. ブランチ方針 / Branch Policy / 分支策略

- `main`: 現行開発ブランチ（frontend-first + API-driven）
- `old`: 旧 Streamlit 資産の退避ブランチ（原則更新しない）

Related docs:

- `DATA_GOVERNANCE_AND_BRANCH_STRATEGY.md`: operator-oriented data governance and branch role guidance
- `constant/README.md`: index for overlapping research/spec markdown files under `constant/`

EN: Develop new features on `main`. `old` is archival for legacy Streamlit references.

中文：新功能请在 `main` 开发；`old` 仅用于保留旧版 Streamlit 参考。

---

## 2. アーキテクチャ / Architecture / 架构

```text
React Frontend (frontend/)
  -> HTTP /api
FastAPI BFF (bff/)
  -> src.dispatch (timetable-first dispatch)
  -> src.pipeline (build_inputs / solve / simulate / report)
  -> src.* (schema / constraints / simulator / optimizer)
```

- Frontend は `/api` のみ呼び出し、研究ロジックを直接持たない
- BFF は UI 向け DTO とジョブ制御を提供
- コア計算は `src/` に集約

EN: Frontend only calls `/api`, BFF orchestrates APIs/jobs, and core research logic stays in `src/`.

中文：前端仅调用 `/api`，BFF 负责编排与任务管理，核心研究逻辑集中在 `src/`。

---

## 3. 技術スタック / Tech Stack / 技术栈

### Backend (Python)

- Python 3.11+
- FastAPI, Uvicorn
- pandas, scipy, plotly
- Optional: `gurobipy` (最適化実行時のみ、別途ライセンス必須)

### Frontend

- React 19 + TypeScript
- Vite 7
- React Router 7
- TanStack Query
- Zustand
- Zod
- Tailwind CSS v4
- MapLibre GL

---

## 4. クイックスタート / Quick Start / 快速开始

### 4.1 前提 / Prerequisites / 前置条件

- Python 3.11+
- Node.js 18+
- npm 9+

### 4.2 依存関係インストール / Install Dependencies / 安装依赖

```bash
python -m pip install -r requirements.txt
```

```bash
cd frontend
npm install
```

### 4.3 起動 / Run / 启动

ターミナル1（BFF）:

```bash
python -m uvicorn bff.main:app --reload --port 8000
```

ターミナル2（Frontend）:

```bash
cd frontend
npm run dev
```

- BFF API base: `http://localhost:8000/api`
- Health: `http://localhost:8000/health`
- Frontend: `http://localhost:5173/`

EN: On startup, the app calls `GET /api/scenarios/default`; it opens the latest scenario or auto-creates a default one.

中文：启动后会调用 `GET /api/scenarios/default`；若无场景会自动创建默认场景并进入操作页面。

---

## 5. 開発コマンド / Dev Commands / 开发命令

Python テスト:

```bash
python -m pytest tests/ -q
```

Frontend ビルド確認:

```bash
cd frontend
npm run build
```

BFF import 確認:

```bash
python -c "from bff.main import app; print(len(app.routes))"
```

---

## 6. BFF API の責務 / BFF API Scope / BFF API 职责

`bff/` は UI から見た操作単位で API を提供します。

- Scenario CRUD
- Depot / Vehicle / Route CRUD
- Depot-Route / Vehicle-Route permissions
- Timetable + Calendar CRUD
- Dispatch pipeline jobs
  - `POST /api/scenarios/{id}/build-trips`
  - `POST /api/scenarios/{id}/build-graph`
  - `POST /api/scenarios/{id}/generate-duties`
  - `GET /api/scenarios/{id}/duties/validate`
- Job polling
  - `GET /api/jobs/{job_id}`

現時点で暫定（stub）:

- `POST /api/scenarios/{id}/run-simulation`
- `POST /api/scenarios/{id}/run-optimization`

EN: Scenario documents are persisted as JSON files under `outputs/scenarios/`. Job status is stored in-memory (ephemeral).

中文：场景数据以 JSON 文件保存到 `outputs/scenarios/`；任务状态为内存存储（服务重启后不保留）。

---

## 7. Dispatch コア不変条件 / Dispatch Invariants / 调度核心不变条件

`src/dispatch/` は **Timetable first, dispatch second** を厳守します。

接続可否は次の 3 条件を全て満たす必要があります。

1. 位置連続性（`destination -> origin` の deadhead ルール）
2. 時刻連続性（`arrival + turnaround + deadhead <= next departure`）
3. 車種制約（`allowed_vehicle_types`）

EN: Physically impossible chains are hard-infeasible and must never appear in output.

中文：任何物理上不可行的班次连接都属于硬约束违规，禁止出现在输出中。

---

## 8. ディレクトリ構成 / Directory Structure / 目录结构

```text
master-course/
|- AGENTS.md
|- README.md
|- requirements.txt
|
|- frontend/                    # React 19 + TS + Vite 7
|  |- src/
|  |  |- api/
|  |  |- app/
|  |  |- features/
|  |  |- hooks/
|  |  |- pages/
|  |  |- schemas/
|  |  |- stores/
|  |  `- types/
|  `- README.md
|
|- bff/                         # FastAPI BFF
|  |- main.py
|  |- routers/
|  |  |- scenarios.py
|  |  |- timetable.py
|  |  |- master_data.py
|  |  |- graph.py
|  |  |- simulation.py
|  |  |- optimization.py
|  |  `- jobs.py
|  |- store/
|  `- mappers/
|
|- src/                         # Research core
|  |- dispatch/
|  |  |- models.py
|  |  |- feasibility.py
|  |  |- graph_builder.py
|  |  |- dispatcher.py
|  |  |- validator.py
|  |  |- pipeline.py
|  |  |- context_builder.py
|  |  `- problemdata_adapter.py
|  |- pipeline/
|  |  |- build_inputs.py
|  |  |- solve.py
|  |  |- simulate.py
|  |  |- report.py
|  |  |- gap_analysis.py
|  |  |- delay_resilience.py
|  |  `- sensitivity_runner.py
|  |- constraints/
|  |- preprocess/
|  `- schemas/
|
|- tests/                       # Python test suite
|- data/                        # Input datasets
|- config/                      # Experiment configurations
|- constant/                    # Read-only constants/spec artifacts
|- docs/
|- GTFS/
`- outputs/
```

---

## 9. テスト状況 / Test Status / 测试状态

- 最新実行（`python -m pytest -q`）: **180 passed**
- 実行日: 2026-03-06
- 主要カバレッジ:
  - dispatch feasibility / graph / validator / pipeline
  - data_loader dispatch preprocess
  - simulator checks
  - route cost and energy model

EN: Keep all pre-existing tests green when making code changes.

中文：进行任何代码修改时，必须保持现有测试全部通过。

---

## 10. 現在の制約と優先実装 / Current Limitations & Priorities / 当前限制与优先事项

1. BFF `run-simulation` の本結合（`src/pipeline/simulate.py`）
2. BFF `run-optimization` の本結合（`src/pipeline/solve.py`）
3. Simulation 設定画面の実データ接続
4. Zod バリデーションと編集 UX 改善

EN: Full optimization requires Gurobi installation and license.

中文：完整优化功能依赖 Gurobi 安装与许可证。

---

## 11. Git ポリシー / Git Policy / Git 策略

生成物は追跡しません（`.gitignore` 管理）。

- `outputs/`
- `derived/`
- `results/`
- `__pycache__/`, `*.pyc`
- `frontend/node_modules/`, `frontend/dist/`

EN: Do not commit generated artifacts unless explicitly required for release packaging.

中文：除非发布流程明确要求，否则不要提交构建/运行生成物。

---

## 12. 旧 Streamlit 資産 / Legacy Streamlit Assets / 旧版 Streamlit 资产

- `main` には旧 UI を置いていません
- 参照が必要な場合のみ `old` ブランチを利用してください

```bash
git checkout old
```

---

## 13. Maintainer メモ / Maintainer Notes / 维护者说明

- 研究ロジックは `src/` に集約し、UI 層へ埋め込まない
- BFF は「薄いオーケストレーション + DTO 整形」を維持する
- `constant/` は読み取り専用として扱う

EN: Keep the dispatch module timetable-driven and physically feasible by construction.

中文：保持调度模块“时刻表优先”，并确保输出在物理约束上始终可行。
