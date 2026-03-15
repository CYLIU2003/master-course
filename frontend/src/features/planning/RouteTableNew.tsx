// ── RouteTableNew ─────────────────────────────────────────────
// Table view for the routes tab. Clicking a row selects the route
// and opens the editor drawer.
//
// IMPORTANT: All hooks MUST be called unconditionally at the top
// of this component, BEFORE any early returns. This prevents the
// "Rendered more hooks than during the previous render" error.

import { useTranslation } from "react-i18next";
import { useEffect, useMemo } from "react";
import { useRoutes } from "@/hooks";
import { useGroupedRouteFamilies } from "@/hooks/useGroupedRouteFamilies";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { LoadingBlock, ErrorBlock, EmptyState, VirtualizedList } from "@/features/common";
import type { Route } from "@/types";
import { getRouteVariantLabel } from "./route-family-display";
import { normalizeRouteCode } from "@/lib/route-code";

interface Props {
  scenarioId: string;
}

type RouteTableRow =
  | {
      key: string;
      kind: "family";
      familyCode: string;
      familyLabel: string;
      variantCount: number;
    }
  | {
      key: string;
      kind: "route";
      route: Route;
    };

export function RouteTableNew({ scenarioId }: Props) {
  // ── ALL HOOKS: called unconditionally at the top ──────────
  const { t } = useTranslation();
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedOperator = useMasterUiStore((s) => s.selectedOperator);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);
  const selectRoute = useMasterUiStore((s) => s.selectRoute);

  const operatorFilter = useMemo(
    () => (selectedOperator === "tokyu" ? "tokyu" : "toei"),
    [selectedOperator],
  );

  const { data, isLoading, isFetching, error, refetch } = useRoutes(scenarioId, {
    depotId: selectedDepotId ?? undefined,
    operator: operatorFilter,
    groupByFamily: true,
  });

  const routes = useMemo<Route[]>(() => data?.items ?? [], [data]);
  const total = data?.total ?? routes.length;
  const familyGroups = useGroupedRouteFamilies(routes);
  const rows = useMemo<RouteTableRow[]>(
    () =>
      familyGroups.flatMap((group) => [
        {
          key: `family:${group.familyId}`,
          kind: "family",
          familyCode: normalizeRouteCode(group.familyCode),
          familyLabel: group.familyLabel,
          variantCount: group.members.length,
        } satisfies RouteTableRow,
        ...group.members.map((route) => ({
          key: `route:${route.id}`,
          kind: "route" as const,
          route,
        })),
      ]),
    [familyGroups],
  );

  useEffect(() => {
    // Only clear selection if filter results are loaded (not loading)
    // and the selected route is genuinely absent from the results.
    if (
      !isLoading &&
      selectedRouteId &&
      !routes.some((route) => route.id === selectedRouteId)
    ) {
      selectRoute(null);
    }
  }, [routes, selectedRouteId, selectRoute, isLoading]);

  // ── END OF HOOKS — early returns below ────────────────────

  const handleRowClick = (routeId: string) => {
    selectRoute(routeId);
  };

  if (isLoading) {
    return <LoadingBlock message={t("routes.loading", "路線データを読み込んでいます")} />;
  }

  if (error) {
    return (
      <div className="space-y-3">
        <ErrorBlock message={error.message} />
        <div className="flex justify-center">
          <button
            onClick={() => refetch()}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            {t("common.retry", "再読み込み")}
          </button>
        </div>
      </div>
    );
  }

  if (routes.length === 0) {
    return (
      <EmptyState
        title={t("routes.no_routes", "条件に一致する路線がありません")}
        description={t(
          "routes.no_routes_description",
          "営業所・事業者フィルタを確認するか、「+ 路線追加」ボタンで追加してください",
        )}
      />
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{total} 件の路線</span>
        {isFetching && <span className="animate-pulse">更新中…</span>}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <div className="grid min-w-[1100px] grid-cols-[2.2fr_1fr_1fr_0.8fr_0.9fr_0.8fr_0.8fr_0.9fr_0.4fr] border-b border-border bg-slate-50 text-left text-sm">
          <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_name", "路線名")}</div>
          <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_start", "始点")}</div>
          <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_end", "終点")}</div>
          <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("routes.col_distance", "距離 (km)")}</div>
          <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("routes.col_duration", "所要時間 (分)")}</div>
          <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("routes.col_stops", "停留所数")}</div>
          <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("routes.col_trips", "便数")}</div>
          <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_assignment", "所属")}</div>
          <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_status", "状態")}</div>
        </div>
        <VirtualizedList
          items={rows}
          height={560}
          itemHeight={72}
          className="min-w-[1100px] bg-white"
          perfLabel="master-routes-table"
          getKey={(row) => row.key}
          renderItem={(row) => {
            if (row.kind === "family") {
              return (
                <div className="border-b border-border bg-slate-100/80 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full border border-slate-300 bg-white px-2 py-0.5 text-xs font-semibold text-slate-700">
                          {row.familyCode}
                        </span>
                        <span className="truncate text-sm font-medium text-slate-700">
                          {row.familyLabel}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {row.variantCount} variant
                        {row.variantCount === 1 ? "" : "s"} / raw route を保持
                      </p>
                    </div>
                  </div>
                </div>
              );
            }

            const r = row.route;
            const variantLabel = getRouteVariantLabel(r);
            return (
              <div
                onClick={() => handleRowClick(r.id)}
                className={`grid h-full cursor-pointer grid-cols-[2.2fr_1fr_1fr_0.8fr_0.9fr_0.8fr_0.8fr_0.9fr_0.4fr] border-b border-border text-sm transition-colors ${
                  selectedRouteId === r.id ? "bg-primary-50" : "hover:bg-slate-50/50"
                }`}
              >
                <div className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    {r.color && (
                      <span
                        className="inline-block h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: r.color }}
                      />
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium text-slate-700">{r.name}</span>
                        {variantLabel && (
                          <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
                            {variantLabel}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500">
                        {r.routeLabel || `${r.startStop || "-"} -> ${r.endStop || "-"}`}
                      </div>
                    </div>
                  </div>
                </div>
                <div className="px-3 py-2 text-slate-600">{r.startStop || "-"}</div>
                <div className="px-3 py-2 text-slate-600">{r.endStop || "-"}</div>
                <div className="px-3 py-2 text-right text-slate-600">{r.distanceKm ?? "-"}</div>
                <div className="px-3 py-2 text-right text-slate-600">{r.durationMin ?? "-"}</div>
                <div className="px-3 py-2 text-right text-slate-600">{r.stopCount ?? r.stopSequence?.length ?? "-"}</div>
                <div className="px-3 py-2 text-right text-slate-600">{r.tripCount ?? "-"}</div>
                <div className="px-3 py-2 text-slate-600">
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
                </div>
                <div className="px-3 py-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      r.enabled ? "bg-green-400" : "bg-slate-300"
                    }`}
                  />
                </div>
              </div>
            );
          }}
        />
      </div>
    </div>
  );
}
