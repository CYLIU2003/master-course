import { Outlet, useParams } from "react-router-dom";
import { useEffect } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/ui-store";
import { fetchMaybeJson } from "@/api/client";
import { AppBootstrapManager } from "@/app/AppBootstrapManager";
import { BootSplashOverlay } from "@/app/BootSplashOverlay";
import { DataReadinessBanner } from "@/components/DataReadinessBanner";
import { DebugPerfOverlay } from "@/utils/perf/debugPerfOverlay";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";

export function AppLayout() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setActiveScenarioId = useUIStore((s) => s.setActiveScenarioId);
  useRenderTrace("AppLayout");

  useEffect(() => {
    setActiveScenarioId(scenarioId ?? null);
    if (scenarioId) {
      void fetchMaybeJson(`/api/scenarios/${scenarioId}/activate`, {
        method: "POST",
      });
    }
    return () => setActiveScenarioId(null);
  }, [scenarioId, setActiveScenarioId]);

  return (
    <div className="flex h-screen min-h-0 flex-col overflow-hidden">
      <AppBootstrapManager scenarioId={scenarioId ?? null} />
      <BootSplashOverlay />
      <Header />
      <DataReadinessBanner />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} scenarioId={scenarioId ?? ""} />
        <main className="min-h-0 flex-1 overflow-y-auto bg-surface p-6">
          <Outlet />
        </main>
      </div>
      <DebugPerfOverlay />
    </div>
  );
}
