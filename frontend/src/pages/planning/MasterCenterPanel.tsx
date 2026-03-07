// ── MasterCenterPanel ─────────────────────────────────────────
// Renders the appropriate content based on activeTab + viewMode.

import { useMasterUiStore } from "@/stores/master-ui-store";
import { DepotTableNew } from "@/features/planning/DepotTableNew";
import { VehicleTableNew } from "@/features/planning/VehicleTableNew";
import { RouteTableNew } from "@/features/planning/RouteTableNew";
import { StopTable } from "@/features/planning/StopTable";
import { RouteNodeGraphPanel } from "@/features/planning/RouteNodeGraphPanel";
import { RouteMapPanel } from "@/features/planning/RouteMapPanel";

interface Props {
  scenarioId: string;
}

export function MasterCenterPanel({ scenarioId }: Props) {
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);

  // Node graph mode — routes tab only
  if (viewMode === "node" && activeTab === "routes") {
    return <RouteNodeGraphPanel scenarioId={scenarioId} />;
  }

  // Map mode — all tabs
  if (viewMode === "map" && activeTab !== "stops") {
    return <RouteMapPanel scenarioId={scenarioId} />;
  }

  // Split mode — table + map side by side
  if (viewMode === "split") {
    if (activeTab === "stops") {
      return (
        <div className="p-4">
          <StopTable scenarioId={scenarioId} />
        </div>
      );
    }
    return (
      <div className="flex h-full">
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
          <RouteMapPanel scenarioId={scenarioId} />
        </div>
      </div>
    );
  }

  // Table mode (default)
  switch (activeTab) {
    case "depots":
      return (
        <div className="p-4">
          <DepotTableNew scenarioId={scenarioId} />
        </div>
      );
    case "vehicles":
      return (
        <div className="p-4">
          <VehicleTableNew
            scenarioId={scenarioId}
            depotId={selectedDepotId ?? undefined}
          />
        </div>
      );
    case "routes":
      return (
        <div className="p-4">
          <RouteTableNew scenarioId={scenarioId} />
        </div>
      );
    case "stops":
      return (
        <div className="p-4">
          <StopTable scenarioId={scenarioId} />
        </div>
      );
  }
}
