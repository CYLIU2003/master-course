// ── VehicleTableNew ───────────────────────────────────────────
// Table view for the vehicles tab. Clicking a row selects the
// vehicle and opens the editor drawer.

import { useTranslation } from "react-i18next";
import { useVehicles } from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { LoadingBlock, ErrorBlock, EmptyState, VirtualizedList } from "@/features/common";
import type { Vehicle } from "@/types";

interface Props {
  scenarioId: string;
  depotId?: string;
}

export function VehicleTableNew({ scenarioId, depotId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useVehicles(scenarioId, depotId, {
    enabled: !!depotId,
  });
  const selectedVehicleId = useMasterUiStore((s) => s.selectedVehicleId);
  const selectVehicle = useMasterUiStore((s) => s.selectVehicle);

  if (isLoading) return <LoadingBlock message={t("vehicles.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const vehicles: Vehicle[] = data?.items ?? [];

  const handleRowClick = (vehicleId: string) => {
    selectVehicle(vehicleId);
    // selectVehicle already opens the drawer via the store
  };

  if (vehicles.length === 0) {
    return (
      <EmptyState
        title={t("vehicles.no_vehicles", "車両がありません")}
        description={
          depotId
            ? t("vehicles.no_vehicles_depot", "この営業所に車両がありません。右上の「+ 車両追加」で追加してください")
            : t("vehicles.no_vehicles_all", "左パネルで営業所を選択してから車両を追加してください")
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="grid grid-cols-[1.4fr_0.8fr_0.6fr_0.8fr_0.8fr_0.8fr_0.5fr] border-b border-border bg-slate-50 text-left text-sm">
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("vehicles.col_model", "車両名")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("vehicles.col_type", "種別")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("vehicles.col_capacity", "定員")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("vehicles.col_battery", "バッテリー (kWh)")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("vehicles.col_fuel_tank", "燃料タンク (L)")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("vehicles.col_consumption", "消費")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("vehicles.col_status", "状態")}</div>
      </div>
      <VirtualizedList
        items={vehicles}
        height={560}
        itemHeight={46}
        className="bg-white"
        perfLabel="master-vehicles-table"
        getKey={(vehicle) => vehicle.id}
        renderItem={(v) => (
          <div
            onClick={() => handleRowClick(v.id)}
            className={`grid h-full cursor-pointer grid-cols-[1.4fr_0.8fr_0.6fr_0.8fr_0.8fr_0.8fr_0.5fr] border-b border-border text-sm transition-colors ${
              selectedVehicleId === v.id ? "bg-primary-50" : "hover:bg-slate-50/50"
            }`}
          >
            <div className="px-3 py-2 font-medium text-slate-700">{v.modelName}</div>
            <div className="px-3 py-2">
              <span
                className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                  v.type === "BEV" ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"
                }`}
              >
                {v.type === "BEV" ? "EV" : "エンジン"}
              </span>
            </div>
            <div className="px-3 py-2 text-right text-slate-600">{v.capacityPassengers}</div>
            <div className="px-3 py-2 text-right text-slate-600">{v.batteryKwh ?? "-"}</div>
            <div className="px-3 py-2 text-right text-slate-600">{v.fuelTankL ?? "-"}</div>
            <div className="px-3 py-2 text-right text-slate-600">{v.energyConsumption}</div>
            <div className="px-3 py-2">
              <span className={`inline-block h-2 w-2 rounded-full ${v.enabled ? "bg-green-400" : "bg-slate-300"}`} />
            </div>
          </div>
        )}
      />
    </div>
  );
}
