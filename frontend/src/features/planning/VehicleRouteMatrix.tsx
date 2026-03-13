import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useVehicles,
  useRouteFamilies,
  useDepotRouteFamilyPermissions,
  useVehicleRouteFamilyPermissions,
  useUpdateVehicleRouteFamilyPermissions,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import type {
  Vehicle,
  RouteFamilySummary,
  VehicleRouteFamilyPermission,
} from "@/types";
import { RouteFamilyInspectorCard } from "./RouteFamilyInspectorCard";

interface VehicleRouteMatrixProps {
  scenarioId: string;
  depotId?: string;
}

interface FamilyPermissionCheckboxProps {
  checked: boolean;
  indeterminate: boolean;
  disabled?: boolean;
  onChange: () => void;
}

function FamilyPermissionCheckbox({
  checked,
  indeterminate,
  disabled,
  onChange,
}: FamilyPermissionCheckboxProps) {
  const ref = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
    />
  );
}

export function VehicleRouteMatrix({
  scenarioId,
  depotId,
}: VehicleRouteMatrixProps) {
  const { t } = useTranslation();
  const [selectedFamilyId, setSelectedFamilyId] = useState<string | null>(null);
  const { data: vehiclesData, isLoading: loadingVehicles } = useVehicles(
    scenarioId,
    depotId,
  );
  const { data: familiesData, isLoading: loadingFamilies } = useRouteFamilies(scenarioId);
  const { data: depotFamilyPermsData, isLoading: loadingDepotFamilyPerms } =
    useDepotRouteFamilyPermissions(scenarioId);
  const { data: permsData, isLoading: loadingPerms } =
    useVehicleRouteFamilyPermissions(scenarioId);
  const updatePerms = useUpdateVehicleRouteFamilyPermissions(scenarioId);

  const vehicles: Vehicle[] = vehiclesData?.items ?? [];
  const families: RouteFamilySummary[] = familiesData?.items ?? [];
  const depotFamilyPermissions = useMemo(() => depotFamilyPermsData?.items ?? [], [depotFamilyPermsData?.items]);
  const permissions = useMemo<VehicleRouteFamilyPermission[]>(() => permsData?.items ?? [], [permsData?.items]);

  const visibleFamilies = useMemo(() => {
    if (!depotId) {
      return families;
    }
    const scoped = depotFamilyPermissions.filter((item) => item.depotId === depotId);
    if (scoped.length === 0) {
      return families;
    }
    const allowedFamilyIds = new Set(
      scoped
        .filter((item) => item.allowed || item.partiallyAllowed)
        .map((item) => item.routeFamilyId),
    );
    return families.filter((family) => allowedFamilyIds.has(family.routeFamilyId));
  }, [depotFamilyPermissions, depotId, families]);

  const permissionMap = useMemo(() => {
    const map = new Map<string, VehicleRouteFamilyPermission>();
    for (const item of permissions) {
      map.set(`${item.vehicleId}:${item.routeFamilyId}`, item);
    }
    return map;
  }, [permissions]);

  const effectiveSelectedFamilyId =
    selectedFamilyId && visibleFamilies.some((item) => item.routeFamilyId === selectedFamilyId)
      ? selectedFamilyId
      : visibleFamilies[0]?.routeFamilyId ?? null;

  if (loadingVehicles || loadingFamilies || loadingDepotFamilyPerms || loadingPerms) {
    return <LoadingBlock message={t("matrix.loading")} />;
  }

  if (vehicles.length === 0 || visibleFamilies.length === 0) {
    return (
      <EmptyState
        title={t("matrix.no_data")}
        description={t(
          "matrix.vehicle_family_create_first",
          depotId
            ? "車両を登録するか、営業所-路線許可で対象 route family を選んでください。"
            : "車両と route family を先に整備してください。",
        )}
      />
    );
  }

  const getPermission = (vehicleId: string, routeFamilyId: string) =>
    permissionMap.get(`${vehicleId}:${routeFamilyId}`);

  const handleToggle = (vehicleId: string, family: RouteFamilySummary) => {
    const current = getPermission(vehicleId, family.routeFamilyId);
    const nextAllowed = current?.partiallyAllowed ? true : !(current?.allowed ?? false);

    updatePerms.mutate({
      permissions: [
        {
          vehicleId,
          routeFamilyId: family.routeFamilyId,
          allowed: nextAllowed,
        },
      ],
    });
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-slate-50">
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">
              {t("matrix.vehicle_route_header", "車両 / route family")}
            </th>
            {visibleFamilies.map((family) => (
              <th
                key={family.routeFamilyId}
                className="px-2 py-2 text-center text-xs font-medium text-slate-500"
              >
                <button
                  type="button"
                  onClick={() => setSelectedFamilyId(family.routeFamilyId)}
                  className={`flex w-full flex-col items-center gap-0.5 rounded px-1 py-1 text-center ${
                    effectiveSelectedFamilyId === family.routeFamilyId ? "bg-primary-50" : "hover:bg-slate-100"
                  }`}
                >
                  {family.primaryColor && (
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: family.primaryColor }}
                    />
                  )}
                  <span className="max-w-20 truncate font-semibold text-slate-700">
                    {family.routeFamilyCode}
                  </span>
                  <span className="max-w-24 truncate text-[10px] text-slate-500">
                    {family.variantCount} variants
                  </span>
                  <span className="max-w-24 truncate text-[10px] text-slate-400">
                    {family.hasShortTurn ? "short-turn" : family.hasBranch ? "branch" : family.hasDepotVariant ? "depot" : "main"}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {vehicles.map((vehicle) => (
            <tr key={vehicle.id} className="hover:bg-slate-50/50">
              <td className="px-3 py-2">
                <div>
                  <span className="font-medium text-slate-700">{vehicle.modelName}</span>
                  <span
                    className={`ml-2 inline-block rounded px-1 py-0.5 text-[10px] font-medium ${
                      vehicle.type === "BEV"
                        ? "bg-green-50 text-green-700"
                        : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {vehicle.type}
                  </span>
                </div>
                <div className="text-xs text-slate-500">route family 単位で一括許可</div>
              </td>
              {visibleFamilies.map((family) => {
                const permission = getPermission(vehicle.id, family.routeFamilyId);
                return (
                  <td key={family.routeFamilyId} className="px-2 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <FamilyPermissionCheckbox
                        checked={permission?.allowed ?? false}
                        indeterminate={permission?.partiallyAllowed ?? false}
                        disabled={updatePerms.isPending}
                        onChange={() => handleToggle(vehicle.id, family)}
                      />
                      <span className="text-[10px] text-slate-400">
                        {permission?.allowedRouteCount ?? 0}/{permission?.totalRouteCount ?? family.variantCount}
                      </span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {effectiveSelectedFamilyId && (
        <div className="border-t border-border p-3">
          <RouteFamilyInspectorCard
            scenarioId={scenarioId}
            routeFamilyId={effectiveSelectedFamilyId}
            onClose={() => setSelectedFamilyId(null)}
          />
        </div>
      )}
    </div>
  );
}
