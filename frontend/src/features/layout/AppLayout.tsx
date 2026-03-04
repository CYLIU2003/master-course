import { Outlet, useParams } from "react-router-dom";
import { useEffect } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/ui-store";

export function AppLayout() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setActiveScenarioId = useUIStore((s) => s.setActiveScenarioId);

  useEffect(() => {
    setActiveScenarioId(scenarioId ?? null);
    return () => setActiveScenarioId(null);
  }, [scenarioId, setActiveScenarioId]);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} scenarioId={scenarioId ?? ""} />
        <main className="flex-1 overflow-y-auto bg-surface p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
