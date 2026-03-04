import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
  redirect,
} from "react-router-dom";
import { AppLayout } from "@/features/layout/AppLayout";

// ── Page imports ──────────────────────────────────────────────
import { ScenarioListPage } from "@/pages/scenario/ScenarioListPage";
import { ScenarioOverviewPage } from "@/pages/scenario/ScenarioOverviewPage";

// Tab 1: Planning
import { MasterPlanningPage } from "@/pages/planning/MasterPlanningPage";
import { TimetablePage } from "@/pages/inputs/TimetablePage";
import { DeadheadPage } from "@/pages/inputs/DeadheadPage";
import { RulesPage } from "@/pages/inputs/RulesPage";

// Tab 2: Simulation environment
import { SimulationEnvironmentPage } from "@/pages/planning/SimulationEnvironmentPage";

// Dispatch pipeline
import { TripsPage } from "@/pages/dispatch/TripsPage";
import { GraphPage } from "@/pages/dispatch/GraphPage";
import { DutiesPage } from "@/pages/dispatch/DutiesPage";
import { PrecheckPage } from "@/pages/dispatch/PrecheckPage";
import { SimulationRunPage } from "@/pages/dispatch/SimulationRunPage";
import { OptimizationRunPage } from "@/pages/dispatch/OptimizationRunPage";

// Results
import { DispatchResultsPage } from "@/pages/results/DispatchResultsPage";
import { EnergyResultsPage } from "@/pages/results/EnergyResultsPage";
import { CostResultsPage } from "@/pages/results/CostResultsPage";

// Compare
import { ComparePage } from "@/pages/compare/ComparePage";

async function startupLoader() {
  try {
    const res = await fetch("/api/scenarios/default");
    if (!res.ok) {
      return redirect("/scenarios");
    }

    const scenario = (await res.json()) as { id?: string };
    if (!scenario.id) {
      return redirect("/scenarios");
    }

    return redirect(`/scenarios/${scenario.id}/planning`);
  } catch {
    return redirect("/scenarios");
  }
}

const router = createBrowserRouter([
  {
    path: "/",
    loader: startupLoader,
    element: <Navigate to="/scenarios" replace />,
  },
  {
    path: "/scenarios",
    element: <ScenarioListPage />,
  },
  {
    path: "/scenarios/:scenarioId",
    element: <AppLayout />,
    children: [
      { index: true, element: <ScenarioOverviewPage /> },

      // ── Tab 1: Planning (master data) ─────────────────────
      { path: "planning", element: <MasterPlanningPage /> },
      { path: "timetable", element: <TimetablePage /> },
      { path: "deadhead", element: <DeadheadPage /> },
      { path: "rules", element: <RulesPage /> },

      // ── Tab 2: Simulation environment ─────────────────────
      { path: "simulation-env", element: <SimulationEnvironmentPage /> },

      // ── Dispatch pipeline ─────────────────────────────────
      { path: "trips", element: <TripsPage /> },
      { path: "graph", element: <GraphPage /> },
      { path: "duties", element: <DutiesPage /> },
      { path: "precheck", element: <PrecheckPage /> },
      { path: "simulation", element: <SimulationRunPage /> },
      { path: "optimization", element: <OptimizationRunPage /> },

      // ── Results ───────────────────────────────────────────
      { path: "results/dispatch", element: <DispatchResultsPage /> },
      { path: "results/energy", element: <EnergyResultsPage /> },
      { path: "results/cost", element: <CostResultsPage /> },
    ],
  },
  {
    path: "/compare",
    element: <ComparePage />,
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
