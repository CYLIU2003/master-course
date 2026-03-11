// ── MasterCenterPanel ─────────────────────────────────────────
// Renders the appropriate content based on activeTab + viewMode.

import { Suspense, lazy } from "react";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { DepotTableNew } from "@/features/planning/DepotTableNew";
import { VehicleTableNew } from "@/features/planning/VehicleTableNew";
import { RouteTableNew } from "@/features/planning/RouteTableNew";
import { StopTable } from "@/features/planning/StopTable";
import { useTabSwitchTrace } from "@/utils/perf/useTabSwitchTrace";

const RouteNodeGraphPanel = lazy(() =>
  import("@/features/planning/RouteNodeGraphPanel").then((module) => ({
    default: module.RouteNodeGraphPanel,
  })),
);
const RouteMapPanel = lazy(() =>
  import("@/features/planning/RouteMapPanel").then((module) => ({
    default: module.RouteMapPanel,
  })),
);

interface Props {
  scenarioId: string;
}

export function MasterCenterPanel({ scenarioId }: Props) {
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);
  useTabSwitchTrace("master-center", `${activeTab}:${viewMode}`);
  const shouldLoadMapPanel =
    (activeTab === "routes" && !!selectedRouteId) ||
    ((activeTab === "depots" || activeTab === "vehicles") && !!selectedDepotId);

  // Node graph mode — routes tab only
  if (viewMode === "node" && activeTab === "routes") {
    return (
      <Suspense fallback={<PanelFallback />}>
        <RouteNodeGraphPanel scenarioId={scenarioId} />
      </Suspense>
    );
  }

  // Map mode — all tabs
  if (viewMode === "map" && activeTab !== "stops") {
    return (
      shouldLoadMapPanel ? (
        <Suspense fallback={<PanelFallback />}>
          <RouteMapPanel scenarioId={scenarioId} />
        </Suspense>
      ) : (
        <MapGatePlaceholder activeTab={activeTab} />
      )
    );
  }

  // Split mode — table + map side by side
  if (viewMode === "split") {
    if (activeTab === "stops") {
      return (
        <div className="min-h-0 p-4">
          <StopTable scenarioId={scenarioId} />
        </div>
      );
    }
    return (
      <div className="flex h-full min-h-0">
        <div className="flex-1 overflow-y-auto border-r border-border p-4">
          {activeTab === "depots" && <DepotTableNew scenarioId={scenarioId} />}
          {activeTab === "vehicles" && (
            <VehicleTableNew
              scenarioId={scenarioId}
              depotId={selectedDepotId ?? undefined}
            />
          )}
          {activeTab === "routes" && <RouteTableNew scenarioId={scenarioId} />}
        </div>
        <div className="flex-1">
          {shouldLoadMapPanel ? (
            <Suspense fallback={<PanelFallback />}>
              <RouteMapPanel scenarioId={scenarioId} />
            </Suspense>
          ) : (
            <MapGatePlaceholder activeTab={activeTab} />
          )}
        </div>
      </div>
    );
  }

  // Table mode (default)
  switch (activeTab) {
    case "depots":
      return (
        <div className="min-h-0 p-4">
          <DepotTableNew scenarioId={scenarioId} />
        </div>
      );
    case "vehicles":
      return (
        <div className="min-h-0 p-4">
          <VehicleTableNew
            scenarioId={scenarioId}
            depotId={selectedDepotId ?? undefined}
          />
        </div>
      );
    case "routes":
      return (
        <div className="min-h-0 p-4">
          <RouteTableNew scenarioId={scenarioId} />
        </div>
      );
    case "stops":
      return (
        <div className="min-h-0 p-4">
          <StopTable scenarioId={scenarioId} />
        </div>
      );
  }
}

function PanelFallback() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      Loading panel...
    </div>
  );
}

function MapGatePlaceholder({ activeTab }: { activeTab: "depots" | "vehicles" | "routes" | "stops" }) {
  const message =
    activeTab === "routes"
      ? "route を選択すると地図を遅延読み込みします。"
      : "営業所を選択すると地図を遅延読み込みします。";
  return (
    <div className="flex h-full items-center justify-center border border-dashed border-border bg-slate-50 text-sm text-slate-500">
      {message}
    </div>
  );
}
