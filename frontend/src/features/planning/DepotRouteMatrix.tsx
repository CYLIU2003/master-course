import { useTranslation } from "react-i18next";
import {
  useDepots,
  useRoutes,
  useDepotRoutePermissions,
  useUpdateDepotRoutePermissions,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import type { Depot, Route, DepotRoutePermission } from "@/types";

interface DepotRouteMatrixProps {
  scenarioId: string;
  /** When provided, highlight / filter this depot's row */
  depotId?: string;
}

export function DepotRouteMatrix({
  scenarioId,
  depotId,
}: DepotRouteMatrixProps) {
  const { t } = useTranslation();
  const { data: depotsData, isLoading: loadingDepots } = useDepots(scenarioId);
  const { data: routesData, isLoading: loadingRoutes } = useRoutes(scenarioId);
  const { data: permsData, isLoading: loadingPerms } =
    useDepotRoutePermissions(scenarioId);
  const updatePerms = useUpdateDepotRoutePermissions(scenarioId);

  if (loadingDepots || loadingRoutes || loadingPerms) {
    return <LoadingBlock message={t("matrix.loading")} />;
  }

  const depots: Depot[] = depotsData?.items ?? [];
  const routes: Route[] = routesData?.items ?? [];
  const permissions: DepotRoutePermission[] = permsData?.items ?? [];

  // Filter to current depot if provided
  const displayDepots = depotId
    ? depots.filter((d) => d.id === depotId)
    : depots;

  if (displayDepots.length === 0 || routes.length === 0) {
    return (
      <EmptyState
        title={t("matrix.no_data")}
        description={t("matrix.depot_create_first")}
      />
    );
  }

  // Build lookup: `depotId:routeId` → allowed
  const permMap = new Map<string, boolean>();
  for (const p of permissions) {
    permMap.set(`${p.depotId}:${p.routeId}`, p.allowed);
  }

  const isAllowed = (dId: string, rId: string) =>
    permMap.get(`${dId}:${rId}`) ?? false;

  const handleToggle = (dId: string, rId: string) => {
    const current = isAllowed(dId, rId);
    const key = `${dId}:${rId}`;

    // Optimistic: build the full new permission list
    const updated = new Map(permMap);
    updated.set(key, !current);

    const newPerms: DepotRoutePermission[] = [];
    for (const d of depots) {
      for (const r of routes) {
        const k = `${d.id}:${r.id}`;
        if (updated.has(k)) {
          newPerms.push({
            depotId: d.id,
            routeId: r.id,
            allowed: updated.get(k)!,
          });
        }
      }
    }

    updatePerms.mutate({ permissions: newPerms });
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-slate-50">
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">
              {t("matrix.depot_route_header")}
            </th>
            {routes.map((r) => (
              <th
                key={r.id}
                className="px-2 py-2 text-center text-xs font-medium text-slate-500"
              >
                <div className="flex flex-col items-center gap-0.5">
                  {r.color && (
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: r.color }}
                    />
                  )}
                  <span className="max-w-16 truncate">{r.name}</span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {displayDepots.map((d) => (
            <tr
              key={d.id}
              className={
                depotId === d.id ? "bg-primary-50/50" : "hover:bg-slate-50/50"
              }
            >
              <td className="px-3 py-2 font-medium text-slate-700">
                {d.name}
              </td>
              {routes.map((r) => (
                <td key={r.id} className="px-2 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={isAllowed(d.id, r.id)}
                    onChange={() => handleToggle(d.id, r.id)}
                    className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
