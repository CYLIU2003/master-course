import { useParams } from "react-router-dom";
import { useUIStore } from "@/stores/ui-store";
import { PageSection } from "@/features/common";
import { DepotListPanel, DepotDetailPanel, RouteTable, VehicleRouteMatrix } from "@/features/planning";

export function MasterPlanningPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const selectedDepotId = useUIStore((s) => s.selectedDepotId);

  if (!scenarioId) return null;

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          Master Planning
        </h1>
        <p className="text-sm text-slate-500">
          Manage depots, vehicles, and routes
        </p>
      </div>

      {/* Main 2-column layout: depot list + detail */}
      <div className="flex gap-4" style={{ minHeight: "400px" }}>
        {/* Left: Depot list */}
        <div className="w-56 shrink-0 rounded-lg border border-border bg-surface-raised">
          <DepotListPanel scenarioId={scenarioId} />
        </div>

        {/* Right: Depot detail or placeholder */}
        <div className="flex-1 rounded-lg border border-border bg-surface-raised">
          {selectedDepotId ? (
            <DepotDetailPanel
              scenarioId={scenarioId}
              depotId={selectedDepotId}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              Select a depot to view details
            </div>
          )}
        </div>
      </div>

      {/* Routes section (not depot-scoped) */}
      <PageSection
        title="Routes"
        description="All routes in the bus network"
      >
        <RouteTable scenarioId={scenarioId} />
      </PageSection>

      {/* Vehicle-Route permission matrix */}
      {selectedDepotId && (
        <PageSection
          title="Vehicle-Route Permissions"
          description="Which vehicles can operate on which routes"
        >
          <VehicleRouteMatrix
            scenarioId={scenarioId}
            depotId={selectedDepotId}
          />
        </PageSection>
      )}
    </div>
  );
}
