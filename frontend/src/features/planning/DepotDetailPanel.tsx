import { useState } from "react";
import {
  useDepot,
  useUpdateDepot,
  useVehicles,
  useDepotRoutePermissions,
} from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { VehicleTable } from "./VehicleTable";
import { DepotRouteMatrix } from "./DepotRouteMatrix";

interface DepotDetailPanelProps {
  scenarioId: string;
  depotId: string;
}

type DetailSection = "info" | "vehicles" | "routes";

export function DepotDetailPanel({
  scenarioId,
  depotId,
}: DepotDetailPanelProps) {
  const [activeSection, setActiveSection] = useState<DetailSection>("vehicles");
  const { data: depot, isLoading, error } = useDepot(scenarioId, depotId);
  const updateDepot = useUpdateDepot(scenarioId, depotId);

  if (isLoading) return <LoadingBlock message="Loading depot details..." />;
  if (error) return <ErrorBlock message={error.message} />;
  if (!depot) return <EmptyState title="Depot not found" />;

  const tabs: { key: DetailSection; label: string }[] = [
    { key: "info", label: "Info" },
    { key: "vehicles", label: "Vehicles" },
    { key: "routes", label: "Routes" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Depot header */}
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-slate-800">{depot.name}</h2>
        <p className="text-xs text-slate-400">
          {depot.location || "No location set"}
        </p>
      </div>

      {/* Section tabs */}
      <div className="flex border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveSection(tab.key)}
            className={`px-4 py-2 text-xs font-medium transition-colors ${
              activeSection === tab.key
                ? "border-b-2 border-primary-500 text-primary-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeSection === "info" && (
          <DepotInfoSection
            depot={depot}
            onSave={(updates) => updateDepot.mutate(updates)}
            saving={updateDepot.isPending}
          />
        )}
        {activeSection === "vehicles" && (
          <VehicleTable scenarioId={scenarioId} depotId={depotId} />
        )}
        {activeSection === "routes" && (
          <DepotRouteMatrix scenarioId={scenarioId} depotId={depotId} />
        )}
      </div>
    </div>
  );
}

// ── Inline info section ───────────────────────────────────────

function DepotInfoSection({
  depot,
  onSave,
  saving,
}: {
  depot: NonNullable<ReturnType<typeof useDepot>["data"]>;
  onSave: (updates: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const fields: { label: string; key: string; value: string | number | boolean }[] = [
    { label: "Name", key: "name", value: depot.name },
    { label: "Location", key: "location", value: depot.location },
    { label: "Latitude", key: "lat", value: depot.lat },
    { label: "Longitude", key: "lon", value: depot.lon },
    {
      label: "Normal Chargers",
      key: "normalChargerCount",
      value: depot.normalChargerCount,
    },
    {
      label: "Normal Charger Power (kW)",
      key: "normalChargerPowerKw",
      value: depot.normalChargerPowerKw,
    },
    {
      label: "Fast Chargers",
      key: "fastChargerCount",
      value: depot.fastChargerCount,
    },
    {
      label: "Fast Charger Power (kW)",
      key: "fastChargerPowerKw",
      value: depot.fastChargerPowerKw,
    },
    { label: "Parking Capacity", key: "parkingCapacity", value: depot.parkingCapacity },
    { label: "Has Fuel Facility", key: "hasFuelFacility", value: depot.hasFuelFacility ? "Yes" : "No" },
    { label: "Overnight Charging", key: "overnightCharging", value: depot.overnightCharging ? "Yes" : "No" },
  ];

  return (
    <div className="space-y-3">
      {fields.map((f) => (
        <div key={f.key} className="flex items-baseline justify-between text-sm">
          <span className="text-slate-500">{f.label}</span>
          <span className="font-medium text-slate-700">{String(f.value)}</span>
        </div>
      ))}
      {depot.notes && (
        <div className="mt-4 rounded bg-slate-50 p-3 text-xs text-slate-600">
          {depot.notes}
        </div>
      )}
    </div>
  );
}
