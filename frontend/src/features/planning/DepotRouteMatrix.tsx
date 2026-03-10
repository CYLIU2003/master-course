import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useDepots,
  useRouteFamilies,
  useDepotRouteFamilyPermissions,
  useUpdateDepotRouteFamilyPermissions,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import type { Depot, RouteFamilySummary, DepotRouteFamilyPermission } from "@/types";
import { RouteFamilyInspectorCard } from "./RouteFamilyInspectorCard";

interface DepotRouteMatrixProps {
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

export function DepotRouteMatrix({
  scenarioId,
  depotId,
}: DepotRouteMatrixProps) {
  const { t } = useTranslation();
  const [selectedFamilyId, setSelectedFamilyId] = useState<string | null>(null);
  const { data: depotsData, isLoading: loadingDepots } = useDepots(scenarioId);
  const { data: familiesData, isLoading: loadingFamilies } = useRouteFamilies(scenarioId);
  const { data: permsData, isLoading: loadingPerms } =
    useDepotRouteFamilyPermissions(scenarioId);
  const updatePerms = useUpdateDepotRouteFamilyPermissions(scenarioId);

  const depots: Depot[] = depotsData?.items ?? [];
  const families: RouteFamilySummary[] = familiesData?.items ?? [];
  const permissions: DepotRouteFamilyPermission[] = permsData?.items ?? [];

  const displayDepots = useMemo(
    () => (depotId ? depots.filter((item) => item.id === depotId) : depots),
    [depotId, depots],
  );

  const permissionMap = useMemo(() => {
    const map = new Map<string, DepotRouteFamilyPermission>();
    for (const item of permissions) {
      map.set(`${item.depotId}:${item.routeFamilyId}`, item);
    }
    return map;
  }, [permissions]);

  useEffect(() => {
    if (families.length === 0) {
      setSelectedFamilyId(null);
      return;
    }
    if (selectedFamilyId && families.some((item) => item.routeFamilyId === selectedFamilyId)) {
      return;
    }
    setSelectedFamilyId(families[0]?.routeFamilyId ?? null);
  }, [families, selectedFamilyId]);

  if (loadingDepots || loadingFamilies || loadingPerms) {
    return <LoadingBlock message={t("matrix.loading")} />;
  }

  if (displayDepots.length === 0 || families.length === 0) {
    return (
      <EmptyState
        title={t("matrix.no_data")}
        description={t(
          "matrix.depot_family_create_first",
          "営業所と route family を先に整備してください。",
        )}
      />
    );
  }

  const getPermission = (currentDepotId: string, routeFamilyId: string) =>
    permissionMap.get(`${currentDepotId}:${routeFamilyId}`);

  const handleToggle = (currentDepotId: string, family: RouteFamilySummary) => {
    const current = getPermission(currentDepotId, family.routeFamilyId);
    const nextAllowed = current?.partiallyAllowed ? true : !(current?.allowed ?? false);

    updatePerms.mutate({
      permissions: [
        {
          depotId: currentDepotId,
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
              {t("matrix.depot_route_header", "営業所 / route family")}
            </th>
            {families.map((family) => (
              <th
                key={family.routeFamilyId}
                className="px-2 py-2 text-center text-xs font-medium text-slate-500"
              >
                <button
                  type="button"
                  onClick={() => setSelectedFamilyId(family.routeFamilyId)}
                  className={`flex w-full flex-col items-center gap-0.5 rounded px-1 py-1 text-center ${
                    selectedFamilyId === family.routeFamilyId ? "bg-primary-50" : "hover:bg-slate-100"
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
          {displayDepots.map((depot) => (
            <tr
              key={depot.id}
              className={
                depotId === depot.id ? "bg-primary-50/50" : "hover:bg-slate-50/50"
              }
            >
              <td className="px-3 py-2 font-medium text-slate-700">
                <div>{depot.name}</div>
                <div className="text-xs text-slate-500">route family 単位で一括許可</div>
              </td>
              {families.map((family) => {
                const permission = getPermission(depot.id, family.routeFamilyId);
                return (
                  <td key={family.routeFamilyId} className="px-2 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <FamilyPermissionCheckbox
                        checked={permission?.allowed ?? false}
                        indeterminate={permission?.partiallyAllowed ?? false}
                        disabled={updatePerms.isPending}
                        onChange={() => handleToggle(depot.id, family)}
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

      {selectedFamilyId && (
        <div className="border-t border-border p-3">
          <RouteFamilyInspectorCard
            scenarioId={scenarioId}
            routeFamilyId={selectedFamilyId}
            onClose={() => setSelectedFamilyId(null)}
          />
        </div>
      )}
    </div>
  );
}
