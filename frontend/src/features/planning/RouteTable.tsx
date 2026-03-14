import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useRoutes, useCreateRoute, useDeleteRoute } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import type { Route } from "@/types";
import {
  usePlanningDatasetStore,
} from "@/stores/planning-dataset-store";

interface RouteTableProps {
  scenarioId: string;
  depotId?: string;
  showAll?: boolean;
}

export function RouteTable({ scenarioId, depotId, showAll }: RouteTableProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useRoutes(
    scenarioId,
    showAll ? { enabled: true } : (depotId ? { depotId, enabled: true } : { enabled: false }),
  );
  const setActiveDepotId = usePlanningDatasetStore((s) => s.setActiveDepotId);
  const createRoute = useCreateRoute(scenarioId);
  const deleteRoute = useDeleteRoute(scenarioId);

  const routes: Route[] = data?.items ?? [];

  useEffect(() => {
    setActiveDepotId(depotId ?? null);
  }, [depotId, setActiveDepotId]);

  if (!depotId && !showAll) {
    return (
      <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
        営業所を選択すると、対象 route 一覧を読み込みます。
      </div>
    );
  }

  if (isLoading) return <LoadingBlock message={t("routes.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const handleAdd = () => {
    createRoute.mutate({
      name: `Route ${routes.length + 1}`,
      startStop: "",
      endStop: "",
      distanceKm: 0,
      durationMin: 0,
    });
  };

  const handleDelete = (routeId: string) => {
    if (!confirm(t("routes.delete_confirm"))) return;
    deleteRoute.mutate(routeId);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {t("routes.count", { count: routes.length })}
        </p>
        <button
          onClick={handleAdd}
          disabled={createRoute.isPending}
          className="rounded bg-primary-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {t("routes.add")}
        </button>
      </div>

      {routes.length === 0 ? (
        <EmptyState title={t("routes.no_routes")} description={t("routes.no_routes_description")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border bg-slate-50">
                <th className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_name")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_start")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_end")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">{t("routes.col_distance")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">{t("routes.col_duration")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500">{t("routes.col_status")}</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {routes.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50/50">
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
                  <td className="px-3 py-2 text-slate-600">{r.startStop || "-"}</td>
                  <td className="px-3 py-2 text-slate-600">{r.endStop || "-"}</td>
                  <td className="px-3 py-2 text-right text-slate-600">{r.distanceKm}</td>
                  <td className="px-3 py-2 text-right text-slate-600">{r.durationMin}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        r.enabled ? "bg-green-400" : "bg-slate-300"
                      }`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => handleDelete(r.id)}
                      className="rounded p-0.5 text-slate-300 hover:bg-red-50 hover:text-red-500"
                      aria-label={`Delete ${r.name}`}
                    >
                      <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
