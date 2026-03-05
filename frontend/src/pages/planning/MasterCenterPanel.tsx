// ── MasterCenterPanel ─────────────────────────────────────────
// Renders the appropriate content based on activeTab + viewMode.

import { useMasterUiStore } from "@/stores/master-ui-store";
import { DepotTableNew } from "@/features/planning/DepotTableNew";
import { VehicleTableNew } from "@/features/planning/VehicleTableNew";
import { RouteTableNew } from "@/features/planning/RouteTableNew";
import { RouteNodeGraphPanel } from "@/features/planning/RouteNodeGraphPanel";

interface Props {
  scenarioId: string;
}

export function MasterCenterPanel({ scenarioId }: Props) {
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);

  // Table mode (default for all tabs)
  if (viewMode === "table" || activeTab !== "routes") {
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
    }
  }

  // Node mode (routes only)
  if (viewMode === "node" && activeTab === "routes") {
    return <RouteNodeGraphPanel scenarioId={scenarioId} />;
  }

  // Map mode (placeholder for Phase 3)
  if (viewMode === "map") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        地図モードは Phase 3 で実装予定
      </div>
    );
  }

  // Split mode (placeholder)
  return (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      分割表示は Phase 3 で実装予定
    </div>
  );
}
