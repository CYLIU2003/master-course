# EV Bus Scheduling — Frontend

EV バススケジューリング・充電・電力最適化シミュレーションの React フロントエンドです。

## Tech Stack

- **React 19** + **TypeScript**
- **Vite 7** (dev server & build)
- **React Router 7** (SPA routing)
- **TanStack Query** (server state management)
- **Zustand** (client state management)
- **Tailwind CSS v4** (utility-first styling, CSS `@theme` config)

## Getting Started

`npm` is bundled with Node.js. If PowerShell shows `npm is not recognized`,
install Node.js first and reopen the terminal.

```powershell
node -v
npm -v
```

If either command fails, install Node.js 18+ (LTS recommended) from
[nodejs.org](https://nodejs.org/) and verify the commands again before running
`npm install`.

```bash
npm install
npm run dev
npm run dev:open # ローカル利用時のみブラウザ自動起動
npm run build    # production build -> dist/
```

Frontend は `/api` を BFF にプロキシします。別ターミナルで `bff.main:app` を起動してください。

```bash
# repository root
python -m uvicorn bff.main:app --reload --host 0.0.0.0 --port 8000
```

Remote SSH や別ホスト構成では、`.env.example` をコピーして接続先を明示してください。

```bash
cp .env.example .env.development.local
```

同一ホスト上で frontend と BFF を動かす標準設定:

```dotenv
VITE_DEV_HOST=0.0.0.0
VITE_DEV_PORT=5173
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
```

main app の標準構成では `VITE_API_PROXY_TARGET` のみ設定してください。catalog / explorer を別プロセスで動かす場合は `data-prep/api` を独立ポートで起動します。

frontend から別ホストの BFF を直接呼ぶ場合:

```dotenv
VITE_API_BASE_URL=http://<backend-host>:8000/api
```

この場合、BFF 側でも `BFF_CORS_ALLOW_ORIGINS` または `BFF_CORS_ALLOW_ORIGIN_REGEX`
を設定して、frontend のオリジンを許可してください。

起動後は `http://localhost:5173/` または VS Code の port forwarding URL からアクセスします。

- 初期表示は `/scenarios` のシナリオ一覧
- 既存シナリオを選択して開く（シナリオがない場合は新規作成）

## Architecture

### 2-Tab Structure (depot-centric)

フロントエンドは **2 つの主タブ** で構成されます：

| Tab | 名称 | 内容 |
|-----|------|------|
| **Tab 1** | Planning (営業所・車両・路線) | マスタデータ管理 |
| **Tab 2** | Simulation (シミュレーション環境) | シミュレーション設定 |

加えて **Dispatch** (配車パイプライン) と **Results** (結果表示) セクションが常時表示されます。

### Design Principle

> **Depot (営業所) が親概念。Vehicle は必ず 1 つの Depot に所属。Route は独立だが Permission テーブルで紐付く。**

- 旧「Vehicle Fleet」タブは廃止 — fleet = depot の vehicles
- Permission は 2 層: `DepotRoutePermission` と `VehicleRoutePermission`

### Directory Structure

```
src/
├── api/                    # API client layer
│   ├── client.ts           # Generic fetch wrapper
│   ├── master-data.ts      # Depot / Vehicle / Route / Permission APIs
│   ├── scenario.ts         # Scenario / Timetable / Rules APIs
│   ├── graph.ts            # Trips / Graph / Duties APIs
│   ├── simulation.ts       # Simulation APIs
│   └── optimization.ts     # Optimization APIs
├── app/
│   ├── Router.tsx           # SPA routing (2-tab structure)
│   └── QueryProvider.tsx    # TanStack Query provider
├── features/
│   ├── common/             # Shared UI: PageSection, EmptyState, LoadingBlock, ErrorBlock
│   ├── layout/             # AppLayout, Header, Sidebar (2-tab nav)
│   └── planning/           # Planning feature components
│       ├── DepotListPanel.tsx       # Depot list with selection
│       ├── DepotDetailPanel.tsx     # Depot detail (Info / Vehicles / Routes tabs)
│       ├── VehicleTable.tsx         # Vehicle data table (BEV/ICE)
│       ├── RouteTable.tsx           # Route data table
│       ├── DepotRouteMatrix.tsx     # Depot×Route permission checkbox grid
│       └── VehicleRouteMatrix.tsx   # Vehicle×Route permission checkbox grid
├── hooks/
│   ├── use-scenario.ts     # Scenario/Timetable/Rules queries & mutations
│   ├── use-master-data.ts  # Depot/Vehicle/Route/Permission queries & mutations
│   ├── use-graph.ts        # Trips/Graph/Duties queries & mutations
│   └── use-run.ts          # Simulation/Optimization run hooks
├── pages/
│   ├── planning/
│   │   ├── MasterPlanningPage.tsx        # Tab 1: depot list + detail + routes
│   │   └── SimulationEnvironmentPage.tsx # Tab 2: simulation config
│   ├── inputs/             # Timetable, Deadhead, Rules pages
│   ├── dispatch/           # Trips, Graph, Duties, Precheck, Simulation, Optimization
│   ├── results/            # Dispatch, Energy, Cost results
│   ├── scenario/           # Scenario list & overview
│   └── compare/            # Cross-scenario comparison
├── stores/
│   ├── ui-store.ts         # Sidebar, activeTab, selectedDepotId
│   └── compare-store.ts    # Scenario comparison selection
├── types/
│   ├── domain.ts           # Domain types (Depot, Vehicle, Route, Trip, etc.)
│   ├── api.ts              # API DTOs (request/response types)
│   └── index.ts            # Barrel re-exports
└── utils/
    ├── format.ts           # Number/string formatting
    └── time.ts             # Time utilities
```

### Routes

```
/scenarios                          → ScenarioListPage
/scenarios/:id                      → ScenarioOverviewPage
/scenarios/:id/planning             → MasterPlanningPage (Tab 1)
/scenarios/:id/timetable            → TimetablePage
/scenarios/:id/deadhead             → DeadheadPage
/scenarios/:id/rules                → RulesPage
/scenarios/:id/simulation-env       → SimulationEnvironmentPage (Tab 2)
/scenarios/:id/trips                → TripsPage
/scenarios/:id/graph                → GraphPage
/scenarios/:id/duties               → DutiesPage
/scenarios/:id/precheck             → PrecheckPage
/scenarios/:id/simulation           → SimulationRunPage
/scenarios/:id/optimization         → OptimizationRunPage
/scenarios/:id/results/dispatch     → DispatchResultsPage
/scenarios/:id/results/energy       → EnergyResultsPage
/scenarios/:id/results/cost         → CostResultsPage
/compare                            → ComparePage
```

### Domain Model

```
Depot ──1:N──> Vehicle (vehicle.depotId)
Depot ──M:N──> Route   (via DepotRoutePermission)
Vehicle ──M:N──> Route  (via VehicleRoutePermission)
Route ──1:N──> Trip
```

### User Workflow

1. **Create depots** → 2. **Add vehicles to depots** → 3. **Create routes** →
4. **Set depot→route permissions** → 5. **Set vehicle→route permissions** →
6. **Configure simulation environment** → 7. **Run dispatch pipeline** → 8. **View results**

## Status

### Completed
- Domain types (depot-centric model)
- API client layer (master-data, scenario, graph, simulation, optimization)
- TanStack Query hooks (18 hooks with full CRUD mutations)
- Zustand store (activeTab, selectedDepotId)
- 2-tab sidebar navigation
- Planning page (depot list + detail + routes + permission matrices)
- Simulation environment page (placeholder config cards)
- Dispatch pipeline pages (trips, graph, duties, precheck, simulation, optimization)
- Results pages (dispatch, energy, cost)
- FastAPI BFF base implementation (`bff/`) and job polling endpoint

### Not Yet Started
- Zod form validation schemas
- Editor drawers (inline edit for depot/vehicle/route)
- SimulationEnvironmentPage wired to real data
- Full simulation/optimization engine integration in BFF
- Lazy loading of heavy page components

## Performance Rules

- Heavy pages (`public-data`, `compare`, detailed results) are route-level lazy loaded.
- Public Data Explorer only loads overview on entry; route/stops/timetable details are fetched per tab.
- Route / stop / dispatch detail lists use pagination and virtualization.
- Depot selection is required before loading heavy dispatch trip / graph / duty detail.
- Scenario persistence is refs-based on the backend; large dispatch artifacts live outside the lightweight scenario meta JSON.
