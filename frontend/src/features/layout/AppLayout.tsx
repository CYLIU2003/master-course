import { Outlet, useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/ui-store";
import { AppBootstrapManager } from "@/app/AppBootstrapManager";
import { BootSplashOverlay } from "@/app/BootSplashOverlay";
import { DataReadinessBanner } from "@/components/DataReadinessBanner";
import { DebugPerfOverlay } from "@/utils/perf/debugPerfOverlay";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";
import { ensureScenarioActivated } from "@/api/scenario";
import { LoadingBlock } from "@/features/common";

export function AppLayout() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setActiveScenarioId = useUIStore((s) => s.setActiveScenarioId);
  const activatingScenarioId = useUIStore((s) => s.activatingScenarioId);
  const setActivatingScenarioId = useUIStore((s) => s.setActivatingScenarioId);
  const [readyScenarioId, setReadyScenarioId] = useState<string | null>(null);
  useRenderTrace("AppLayout");

  useEffect(() => {
    let cancelled = false;
    setActiveScenarioId(scenarioId ?? null);
    if (!scenarioId) {
      setReadyScenarioId(null);
      setActivatingScenarioId(null);
      return () => {
        setActiveScenarioId(null);
      };
    }
    setReadyScenarioId(null);
    setActivatingScenarioId(scenarioId);
    void ensureScenarioActivated(scenarioId)
      .catch(() => {
        // Let downstream route loaders/pages surface the actual API error.
      })
      .finally(() => {
        if (cancelled) {
          return;
        }
        setReadyScenarioId(scenarioId);
        setActivatingScenarioId(null);
      });
    return () => {
      cancelled = true;
      setActiveScenarioId(null);
    };
  }, [scenarioId, setActiveScenarioId, setActivatingScenarioId]);

  return (
    <div className="flex h-screen min-h-0 flex-col overflow-hidden">
      <AppBootstrapManager scenarioId={readyScenarioId} />
      <BootSplashOverlay />
      <Header />
      <DataReadinessBanner />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} scenarioId={scenarioId ?? ""} />
        <main className="min-h-0 flex-1 overflow-y-auto bg-surface p-6">
          {scenarioId && readyScenarioId !== scenarioId ? (
            <LoadingBlock
              message={
                activatingScenarioId === scenarioId
                  ? "Scenario を有効化しています..."
                  : "Scenario を準備しています..."
              }
            />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
      <DebugPerfOverlay />
    </div>
  );
}
