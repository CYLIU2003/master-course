import { useTranslation } from "react-i18next";
import {
  useVehicles,
  useRoutes,
  useVehicleRoutePermissions,
  useUpdateVehicleRoutePermissions,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import type { Vehicle, Route, VehicleRoutePermission } from "@/types";

interface VehicleRouteMatrixProps {
  scenarioId: string;
  /** Optional: scope to vehicles belonging to this depot */
  depotId?: string;
}

export function VehicleRouteMatrix({
  scenarioId,
  depotId,
}: VehicleRouteMatrixProps) {
  const { t } = useTranslation();
  const { data: vehiclesData, isLoading: loadingVehicles } = useVehicles(
    scenarioId,
    depotId,
  );
  const { data: routesData, isLoading: loadingRoutes } = useRoutes(scenarioId);
  const { data: permsData, isLoading: loadingPerms } =
    useVehicleRoutePermissions(scenarioId);
  const updatePerms = useUpdateVehicleRoutePermissions(scenarioId);

  if (loadingVehicles || loadingRoutes || loadingPerms) {
    return <LoadingBlock message={t("matrix.loading")} />;
  }

  const vehicles: Vehicle[] = vehiclesData?.items ?? [];
  const routes: Route[] = routesData?.items ?? [];
  const permissions: VehicleRoutePermission[] = permsData?.items ?? [];

  if (vehicles.length === 0 || routes.length === 0) {
    return (
      <EmptyState
        title={t("matrix.no_data")}
        description={t("matrix.vehicle_create_first")}
      />
    );
  }

  // Build lookup
  const permMap = new Map<string, boolean>();
  for (const p of permissions) {
    permMap.set(`${p.vehicleId}:${p.routeId}`, p.allowed);
  }

  const isAllowed = (vId: string, rId: string) =>
    permMap.get(`${vId}:${rId}`) ?? false;

  const handleToggle = (vId: string, rId: string) => {
    const current = isAllowed(vId, rId);
    const key = `${vId}:${rId}`;

    const updated = new Map(permMap);
    updated.set(key, !current);

    // Rebuild full list for the API
    const allVehicleIds = new Set(vehicles.map((v) => v.id));
    const newPerms: VehicleRoutePermission[] = [];
    for (const [k, allowed] of updated) {
      const [vehicleId, routeId] = k.split(":");
      // Only include vehicles in current scope
      if (allVehicleIds.has(vehicleId)) {
        newPerms.push({ vehicleId, routeId, allowed });
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
              {t("matrix.vehicle_route_header")}
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
          {vehicles.map((v) => (
            <tr key={v.id} className="hover:bg-slate-50/50">
              <td className="px-3 py-2">
                <div>
                  <span className="font-medium text-slate-700">
                    {v.modelName}
                  </span>
                  <span
                    className={`ml-2 inline-block rounded px-1 py-0.5 text-[10px] font-medium ${
                      v.type === "BEV"
                        ? "bg-green-50 text-green-700"
                        : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {v.type}
                  </span>
                </div>
              </td>
              {routes.map((r) => (
                <td key={r.id} className="px-2 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={isAllowed(v.id, r.id)}
                    onChange={() => handleToggle(v.id, r.id)}
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
