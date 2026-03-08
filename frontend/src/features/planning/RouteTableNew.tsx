// ── RouteTableNew ─────────────────────────────────────────────
// Table view for the routes tab. Clicking a row selects the route
// and opens the editor drawer.

import { useTranslation } from "react-i18next";
import { useEffect, useMemo } from "react";
import { useRoutes } from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import type { Route } from "@/types";

interface Props {
  scenarioId: string;
}

export function RouteTableNew({ scenarioId }: Props) {
  const { t } = useTranslation();
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedOperator = useMasterUiStore((s) => s.selectedOperator);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);
  const selectRoute = useMasterUiStore((s) => s.selectRoute);
  const operatorFilter = useMemo(
    () => (selectedOperator === "tokyu" ? "tokyu" : "toei"),
    [selectedOperator],
  );
  const { data, isLoading, error } = useRoutes(scenarioId, {
    depotId: selectedDepotId ?? undefined,
    operator: operatorFilter,
  });

  if (isLoading) return <LoadingBlock message={t("routes.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const routes: Route[] = data?.items ?? [];

  useEffect(() => {
    if (selectedRouteId && !routes.some((route) => route.id === selectedRouteId)) {
      selectRoute(null);
    }
  }, [routes, selectedRouteId, selectRoute]);

  const handleRowClick = (routeId: string) => {
    selectRoute(routeId);
    // selectRoute already opens the drawer via the store
  };

  if (routes.length === 0) {
    return (
      <EmptyState
        title={t("routes.no_routes", "路線がありません")}
        description={t("routes.no_routes_description", "右上の「+ 路線追加」ボタンで追加してください")}
      />
    );
  }

  return (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border bg-slate-50">
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("routes.col_name", "路線名")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("routes.col_start", "始点")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("routes.col_end", "終点")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">
              {t("routes.col_distance", "距離 (km)")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">
              {t("routes.col_duration", "所要時間 (分)")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("routes.col_assignment", "所属")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("routes.col_status", "状態")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {routes.map((r) => (
            <tr
              key={r.id}
              onClick={() => handleRowClick(r.id)}
              className={`cursor-pointer transition-colors ${
                selectedRouteId === r.id
                  ? "bg-primary-50"
                  : "hover:bg-slate-50/50"
              }`}
            >
              <td className="px-3 py-2">
                <div className="flex items-center gap-2">
                  {r.color && (
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: r.color }}
                    />
                  )}
                  <span className="font-medium text-slate-700">{r.name}</span>
                </div>
              </td>
              <td className="px-3 py-2 text-slate-600">
                {r.startStop || "-"}
              </td>
              <td className="px-3 py-2 text-slate-600">
                {r.endStop || "-"}
              </td>
              <td className="px-3 py-2 text-right text-slate-600">
                {r.distanceKm}
              </td>
              <td className="px-3 py-2 text-right text-slate-600">
                {r.durationMin}
              </td>
              <td className="px-3 py-2 text-slate-600">
                {r.depotId ? (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {r.assignmentType === "manual_override"
                      ? t("common.manual", "手動")
                      : t("common.assigned", "所属済み")}
                  </span>
                ) : (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                    {t("common.unassigned", "未所属")}
                  </span>
                )}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    r.enabled ? "bg-green-400" : "bg-slate-300"
                  }`}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
