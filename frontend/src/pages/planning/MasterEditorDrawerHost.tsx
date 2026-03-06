// ── MasterEditorDrawerHost ────────────────────────────────────
// Decides which drawer to render based on activeTab and selection.

import { useMasterUiStore } from "@/stores/master-ui-store";
import { DepotEditorDrawer } from "@/features/planning/DepotEditorDrawer";
import { VehicleEditorDrawer } from "@/features/planning/VehicleEditorDrawer";
import { RouteEditorDrawer } from "@/features/planning/RouteEditorDrawer";
import { VehicleCreateMenu } from "@/features/planning/VehicleCreateMenu";

interface Props {
  scenarioId: string;
}

export function MasterEditorDrawerHost({ scenarioId }: Props) {
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const isOpen = useMasterUiStore((s) => s.isEditorDrawerOpen);
  const isCreate = useMasterUiStore((s) => s.isCreateMode);
  const createVehicleType = useMasterUiStore((s) => s.createVehicleType);
  const createVehicleTemplateId = useMasterUiStore(
    (s) => s.createVehicleTemplateId,
  );

  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedVehicleId = useMasterUiStore((s) => s.selectedVehicleId);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);

  if (!isOpen) return null;

  // Vehicle tab: show create menu first if creating without a type selected
  if (activeTab === "vehicles" && isCreate && !createVehicleType) {
    return <VehicleCreateMenu scenarioId={scenarioId} />;
  }

  switch (activeTab) {
    case "depots":
      return (
        <DepotEditorDrawer
          scenarioId={scenarioId}
          depotId={isCreate ? null : selectedDepotId}
          isCreate={isCreate}
        />
      );
    case "vehicles":
      return (
        <VehicleEditorDrawer
          scenarioId={scenarioId}
          vehicleId={isCreate ? null : selectedVehicleId}
          isCreate={isCreate}
          vehicleType={createVehicleType}
          templateId={createVehicleTemplateId}
          depotId={selectedDepotId}
        />
      );
    case "routes":
      return (
        <RouteEditorDrawer
          scenarioId={scenarioId}
          routeId={isCreate ? null : selectedRouteId}
          isCreate={isCreate}
        />
      );
    default:
      return null;
  }
}
