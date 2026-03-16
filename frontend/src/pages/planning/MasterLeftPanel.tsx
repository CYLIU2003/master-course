// ── MasterLeftPanel ───────────────────────────────────────────
// Left pane: depot list for filtering.
// Selecting a depot scopes vehicles/routes below.

import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useDepots } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import type { Depot } from "@/types";

interface Props {
  scenarioId: string;
}

export function MasterLeftPanel({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const shouldLoadDepots = activeTab === "depots" || activeTab === "vehicles" || activeTab === "routes";
  const { data, isLoading, error } = useDepots(scenarioId, { enabled: shouldLoadDepots });
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectDepot = useMasterUiStore((s) => s.selectDepot);

  if (activeTab === "stops") {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-slate-500">
        {t("master.depot_filter_not_used_in_stops", "停留所タブでは営業所フィルタを使用しません")}
      </div>
    );
  }

  if (isLoading) return <LoadingBlock message={t("depots.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const depots: Depot[] = data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {t("master.depot_filter", "営業所フィルタ")}
        </h3>
        <button
          onClick={() => selectDepot(null)}
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            selectedDepotId === null
              ? "bg-primary-50 text-primary-700"
              : "text-slate-500 hover:bg-slate-50"
          }`}
        >
          {t("master.all", "すべて")}
        </button>
      </div>

      {/* Depot list */}
      <div className="flex-1 overflow-y-auto">
        {depots.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={t("depots.no_depots")}
              description={t("depots.no_depots_description")}
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {depots.map((depot) => (
              <li key={depot.id}>
                <button
                  onClick={() => selectDepot(depot.id)}
                  className={`flex w-full items-center px-3 py-2.5 text-left transition-colors ${
                    selectedDepotId === depot.id
                      ? "bg-primary-50 text-primary-700"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {depot.name}
                    </p>
                    <p className="truncate text-xs text-slate-400">
                      {depot.location || t("depots.no_location")}
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Summary */}
      <div className="border-t border-border px-3 py-2 text-xs text-slate-400">
        {depots.length} {t("master.depots_count_suffix", "営業所")}
      </div>
    </div>
  );
}
