# Master Course - EV Bus Dispatch Planning

電気バスの配車・充電・電力コスト最適化を扱う研究用プロジェクトです。

## Branch Policy

- `main`: 現行開発ブランチ。**React frontend + FastAPI BFF + Python最適化コア** を対象に開発。
- `old`: 旧 Streamlit UI を凍結保存するためのブランチ（参照専用）。

> 以後のUI開発は `frontend/` を主系として進めます。

## Current Architecture

```text
frontend (React + TS)
   -> /api
bff (FastAPI BFF)
   -> src/dispatch (timetable-driven dispatch)
   -> src/pipeline (solve/simulate/report)
   -> src/* core modules
```

## Quick Start (main)

### 1) Backend BFF

```bash
python -m pip install -r requirements.txt
python -m uvicorn bff.main:app --reload --port 8000
```

- API base: `http://localhost:8000/api`
- Health check: `http://localhost:8000/health`

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

- UI: `http://localhost:5173`
- Vite proxy: `/api` -> `http://localhost:8000`

### 3) Verification

```bash
python -m pytest tests/ -q
cd frontend && npm run build
```

## Frontend Concept (Depot-Centric)

- タブ構成は `Planning` と `Simulation` の2軸
- `Depot` が親概念、`Vehicle` は必ず1つの `depotId` に所属
- `Route` は独立、許可は2層で管理
  - `DepotRoutePermission`
  - `VehicleRoutePermission`
- 重い処理はジョブ化
  - `POST` で `job_id` を返す
  - `GET /api/jobs/{job_id}` で進捗ポーリング

## BFF Scope

実装済み（`bff/`）:

- Scenario CRUD
- Depot / Vehicle / Route CRUD
- Depot-Route / Vehicle-Route permission API
- Timetable API
- Dispatch pipeline API (`build-trips`, `build-graph`, `generate-duties`, `validate`)
- Job polling API

現時点で簡易実装（stub）:

- `run-simulation`
- `run-optimization`

## Directory Structure

```text
master-course/
|- frontend/                  # React 19 + TypeScript + Vite 7
|  |- src/
|  |  |- api/                 # /api client
|  |  |- hooks/               # TanStack Query hooks
|  |  |- features/            # UI components
|  |  |- pages/               # route pages
|  |  |- stores/              # Zustand stores
|  |  `- types/               # domain/api types
|  `- README.md
|- bff/                       # FastAPI BFF
|  |- main.py                 # app entry
|  |- routers/                # scenarios/master-data/graph/simulation/optimization/jobs
|  |- store/                  # scenario_store(JSON), job_store(in-memory)
|  `- mappers/                # Python dataclass <-> API DTO mapping
|- src/
|  |- dispatch/               # timetable-driven dispatch core
|  `- pipeline/               # build_inputs / solve / simulate / report
|- data/                      # route_master, operations, etc.
|- outputs/                   # generated artifacts, scenario JSON storage
|- tests/                     # python tests
`- AGENTS.md                  # dispatch implementation rules
```

## Legacy Streamlit

- 旧UI (`app/`) は `old` ブランチで凍結運用します。
- `main` では frontend + bff を中心に更新します。
