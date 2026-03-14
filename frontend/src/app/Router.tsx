import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
  redirect,
} from "react-router-dom";
import { lazy, Suspense, type ReactNode } from "react";
import { AppLayout } from "@/features/layout/AppLayout";
import { ErrorBoundary, RouteErrorPage } from "@/features/common";

// ODPT Explorer
const ScenarioListPage = lazy(() =>
  import("@/pages/scenario/ScenarioListPage").then((module) => ({
    default: module.ScenarioListPage,
  })),
);
const ScenarioOverviewPage = lazy(() =>
  import("@/pages/scenario/ScenarioOverviewPage").then((module) => ({
    default: module.ScenarioOverviewPage,
  })),
);
const MasterDataPage = lazy(() =>
  import("@/pages/planning/MasterDataPage").then((module) => ({
    default: module.MasterDataPage,
  })),
);
const VehicleTemplatesPage = lazy(() =>
  import("@/pages/planning/VehicleTemplatesPage").then((module) => ({
    default: module.VehicleTemplatesPage,
  })),
);
const TimetablePage = lazy(() =>
  import("@/pages/inputs/TimetablePage").then((module) => ({
    default: module.TimetablePage,
  })),
);
const DeadheadPage = lazy(() =>
  import("@/pages/inputs/DeadheadPage").then((module) => ({
    default: module.DeadheadPage,
  })),
);
const RulesPage = lazy(() =>
  import("@/pages/inputs/RulesPage").then((module) => ({
    default: module.RulesPage,
  })),
);
const SimulationEnvironmentPage = lazy(() =>
  import("@/pages/planning/SimulationEnvironmentPage").then((module) => ({
    default: module.SimulationEnvironmentPage,
  })),
);
const TripsPage = lazy(() =>
  import("@/pages/dispatch/TripsPage").then((module) => ({
    default: module.TripsPage,
  })),
);
const GraphPage = lazy(() =>
  import("@/pages/dispatch/GraphPage").then((module) => ({
    default: module.GraphPage,
  })),
);
const DutiesPage = lazy(() =>
  import("@/pages/dispatch/DutiesPage").then((module) => ({
    default: module.DutiesPage,
  })),
);
const PrecheckPage = lazy(() =>
  import("@/pages/dispatch/PrecheckPage").then((module) => ({
    default: module.PrecheckPage,
  })),
);
const SimulationRunPage = lazy(() =>
  import("@/pages/dispatch/SimulationRunPage").then((module) => ({
    default: module.SimulationRunPage,
  })),
);
const OptimizationRunPage = lazy(() =>
  import("@/pages/dispatch/OptimizationRunPage").then((module) => ({
    default: module.OptimizationRunPage,
  })),
);
const DispatchResultsPage = lazy(() =>
  import("@/pages/results/DispatchResultsPage").then((module) => ({
    default: module.DispatchResultsPage,
  })),
);
const EnergyResultsPage = lazy(() =>
  import("@/pages/results/EnergyResultsPage").then((module) => ({
    default: module.EnergyResultsPage,
  })),
);
const CostResultsPage = lazy(() =>
  import("@/pages/results/CostResultsPage").then((module) => ({
    default: module.CostResultsPage,
  })),
);
const ComparePage = lazy(() =>
  import("@/pages/compare/ComparePage").then((module) => ({
    default: module.ComparePage,
  })),
);
function startupLoader() {
  return redirect("/scenarios");
}

const router = createBrowserRouter([
  {
    path: "/",
    loader: startupLoader,
    element: <Navigate to="/scenarios" replace />,
  },
  {
    path: "/scenarios",
    element: <LazyPage><ScenarioListPage /></LazyPage>,
  },
  {
    path: "/scenarios/:scenarioId",
    element: (
      <ErrorBoundary>
        <AppLayout />
      </ErrorBoundary>
    ),
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <LazyPage><ScenarioOverviewPage /></LazyPage> },
      { path: "simulation-builder", element: <LazyPage><ScenarioOverviewPage /></LazyPage> },

      // ── Tab 1: Planning (master data) ─────────────────────
      { path: "planning", element: <LazyPage><MasterDataPage /></LazyPage> },
      { path: "planning-legacy", element: <Navigate to="../planning" replace /> },
      { path: "vehicle-templates", element: <LazyPage><VehicleTemplatesPage /></LazyPage> },
      { path: "timetable", element: <LazyPage><TimetablePage /></LazyPage> },
      { path: "deadhead", element: <LazyPage><DeadheadPage /></LazyPage> },
      { path: "rules", element: <LazyPage><RulesPage /></LazyPage> },

      // ── Tab 2: Simulation environment ─────────────────────
      { path: "simulation-env", element: <LazyPage><SimulationEnvironmentPage /></LazyPage> },

      // ── Dispatch pipeline ─────────────────────────────────
      { path: "trips", element: <LazyPage><TripsPage /></LazyPage> },
      { path: "graph", element: <LazyPage><GraphPage /></LazyPage> },
      { path: "duties", element: <LazyPage><DutiesPage /></LazyPage> },
      { path: "precheck", element: <LazyPage><PrecheckPage /></LazyPage> },
      { path: "simulation", element: <LazyPage><SimulationRunPage /></LazyPage> },
      { path: "optimization", element: <LazyPage><OptimizationRunPage /></LazyPage> },

      // ── Results ───────────────────────────────────────────
      { path: "results/dispatch", element: <LazyPage><DispatchResultsPage /></LazyPage> },
      { path: "results/energy", element: <LazyPage><EnergyResultsPage /></LazyPage> },
      { path: "results/cost", element: <LazyPage><CostResultsPage /></LazyPage> },
    ],
  },
  {
    path: "/compare",
    element: <LazyPage><ComparePage /></LazyPage>,
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}

function LazyPage({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<RouteSkeleton />}>
      {children}
    </Suspense>
  );
}

function RouteSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <div className="h-7 w-48 animate-pulse rounded bg-slate-200" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
            <div className="mt-3 h-3 w-40 animate-pulse rounded bg-slate-100" />
            <div className="mt-6 space-y-2">
              <div className="h-3 animate-pulse rounded bg-slate-100" />
              <div className="h-3 animate-pulse rounded bg-slate-100" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
