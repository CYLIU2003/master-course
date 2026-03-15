import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Suspense, lazy } from "react";
import { LoadingBlock, EmptyState } from "@/features/common";
import type { Depot } from "@/types";

// Lazy load heavy components
const VehicleTable = lazy(() => 
  import("./VehicleTable").then(m => ({ default: m.VehicleTable }))
);
const DepotRouteMatrix = lazy(() =>
  import("./DepotRouteMatrix").then(m => ({ default: m.DepotRouteMatrix }))
);

interface DepotDetailPanelProps {
  scenarioId: string;
  depotId: string;
  depotData?: Depot;
}

type DetailSection = "info" | "vehicles" | "routes";

export function DepotDetailPanel({
  scenarioId,
  depotId,
  depotData,
}: DepotDetailPanelProps) {
  const { t } = useTranslation();
  const [activeSection, setActiveSection] = useState<DetailSection>("info");

  // Use provided depot data from bootstrap; if not available, show placeholder
  const depot = depotData;

  if (!depot) {
    return <EmptyState title={t("depots.not_found")} />;
  }

  const tabs: { key: DetailSection; label: string }[] = [
    { key: "info", label: t("depots.tab_info") },
    { key: "vehicles", label: t("depots.tab_vehicles") },
    { key: "routes", label: t("depots.tab_routes") },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Depot header */}
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-slate-800">{depot.name}</h2>
        <p className="text-xs text-slate-400">
          {depot.location || t("depots.no_location_set")}
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
          />
        )}
        {activeSection === "vehicles" && (
          <Suspense fallback={<LoadingBlock message={t("depots.loading")} />}>
            <VehicleTable scenarioId={scenarioId} depotId={depotId} />
          </Suspense>
        )}
        {activeSection === "routes" && (
          <Suspense fallback={<LoadingBlock message={t("depots.loading")} />}>
            <DepotRouteMatrix scenarioId={scenarioId} depotId={depotId} />
          </Suspense>
        )}
      </div>
    </div>
  );
}

// ── Inline info section ───────────────────────────────────────

function DepotInfoSection({
  depot,
}: {
  depot: Depot;
}) {
  const { t } = useTranslation();

  const fields: { label: string; key: string; value: string | number | boolean }[] = [
    { label: t("depots.field_name"), key: "name", value: depot.name },
    { label: t("depots.field_location"), key: "location", value: depot.location },
    { label: t("depots.field_lat"), key: "lat", value: depot.lat },
    { label: t("depots.field_lon"), key: "lon", value: depot.lon },
    {
      label: t("depots.field_normal_chargers"),
      key: "normalChargerCount",
      value: depot.normalChargerCount,
    },
    {
      label: t("depots.field_normal_charger_power"),
      key: "normalChargerPowerKw",
      value: depot.normalChargerPowerKw,
    },
    {
      label: t("depots.field_fast_chargers"),
      key: "fastChargerCount",
      value: depot.fastChargerCount,
    },
    {
      label: t("depots.field_fast_charger_power"),
      key: "fastChargerPowerKw",
      value: depot.fastChargerPowerKw,
    },
    { label: t("depots.field_parking"), key: "parkingCapacity", value: depot.parkingCapacity },
    { label: t("depots.field_fuel_facility"), key: "hasFuelFacility", value: depot.hasFuelFacility ? t("common.yes") : t("common.no") },
    { label: t("depots.field_overnight"), key: "overnightCharging", value: depot.overnightCharging ? t("common.yes") : t("common.no") },
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
