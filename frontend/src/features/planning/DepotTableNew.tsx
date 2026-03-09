// ── DepotTableNew ─────────────────────────────────────────────
// Table view for the depots tab. Clicking a row selects the depot
// and opens the editor drawer.

import { useTranslation } from "react-i18next";
import { useDepots } from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { LoadingBlock, ErrorBlock, EmptyState, VirtualizedList } from "@/features/common";
import type { Depot } from "@/types";

interface Props {
  scenarioId: string;
}

export function DepotTableNew({ scenarioId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useDepots(scenarioId);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectDepot = useMasterUiStore((s) => s.selectDepot);

  if (isLoading) return <LoadingBlock message={t("depots.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const depots: Depot[] = data?.items ?? [];

  const handleRowClick = (depotId: string) => {
    // Select depot in the left panel AND open its editor drawer
    selectDepot(depotId);
    // selectDepot closes the drawer, so we re-open it for editing
    useMasterUiStore.setState({
      isEditorDrawerOpen: true,
      isCreateMode: false,
    });
  };

  if (depots.length === 0) {
    return (
      <EmptyState
        title={t("depots.no_depots", "営業所がありません")}
        description={t("depots.no_depots_description", "右上の「+ 営業所追加」ボタンで追加してください")}
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="grid grid-cols-[1.3fr_1.8fr_0.7fr_0.7fr_0.7fr_0.5fr_0.6fr] border-b border-border bg-slate-50 text-left text-sm">
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("depots.col_name", "営業所名")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("depots.col_location", "住所")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("depots.col_normal_chargers", "普通充電器")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("depots.col_fast_chargers", "急速充電器")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("depots.col_parking", "駐車台数")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("depots.col_fuel", "燃料")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("depots.col_overnight", "夜間充電")}</div>
      </div>
      <VirtualizedList
        items={depots}
        height={560}
        itemHeight={46}
        className="bg-white"
        perfLabel="master-depots-table"
        getKey={(depot) => depot.id}
        renderItem={(depot) => (
          <div
            onClick={() => handleRowClick(depot.id)}
            className={`grid h-full cursor-pointer grid-cols-[1.3fr_1.8fr_0.7fr_0.7fr_0.7fr_0.5fr_0.6fr] border-b border-border text-sm transition-colors ${
              selectedDepotId === depot.id ? "bg-primary-50" : "hover:bg-slate-50/50"
            }`}
          >
            <div className="px-3 py-2 font-medium text-slate-700">{depot.name}</div>
            <div className="px-3 py-2 text-slate-600">{depot.location || "-"}</div>
            <div className="px-3 py-2 text-right text-slate-600">{depot.normalChargerCount}</div>
            <div className="px-3 py-2 text-right text-slate-600">{depot.fastChargerCount}</div>
            <div className="px-3 py-2 text-right text-slate-600">{depot.parkingCapacity}</div>
            <div className="px-3 py-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  depot.hasFuelFacility ? "bg-amber-400" : "bg-slate-300"
                }`}
                title={depot.hasFuelFacility ? "あり" : "なし"}
              />
            </div>
            <div className="px-3 py-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  depot.overnightCharging ? "bg-green-400" : "bg-slate-300"
                }`}
                title={depot.overnightCharging ? "あり" : "なし"}
              />
            </div>
          </div>
        )}
      />
    </div>
  );
}
