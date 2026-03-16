import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useRouteFamiliesScoped,
  useDepotRouteFamilyPermissionsForDepot,
  useUpdateDepotRouteFamilyPermissions,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import { usePlanningDraftStore } from "@/stores/planning-draft-store";
import type { RouteFamilySummary, DepotRouteFamilyPermission } from "@/types";
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
  const { data: familiesData, isLoading: loadingFamilies } = useRouteFamiliesScoped(
    scenarioId,
    undefined,
    depotId,
  );
  const { data: permsData, isLoading: loadingPerms } =
    useDepotRouteFamilyPermissionsForDepot(scenarioId, depotId ?? "");
  const updatePerms = useUpdateDepotRouteFamilyPermissions(scenarioId);
  const setDepotPermissionsDirty = usePlanningDraftStore((s) => s.setDepotPermissionsDirty);

  const families: RouteFamilySummary[] = familiesData?.items ?? [];
  const permissions = useMemo<DepotRouteFamilyPermission[]>(() => permsData?.items ?? [], [permsData?.items]);

  const displayDepots = useMemo(
    () => (depotId ? [{ id: depotId, name: depotId }] : []),
    [depotId],
  );

  const permissionMap = useMemo(() => {
    const map = new Map<string, DepotRouteFamilyPermission>();
    for (const item of permissions) {
      map.set(`${item.depotId}:${item.routeFamilyId}`, item);
    }
    return map;
  }, [permissions]);

  const [draftAllowedByFamily, setDraftAllowedByFamily] = useState<Record<string, boolean>>({});

  const effectiveSelectedFamilyId =
    selectedFamilyId && families.some((item) => item.routeFamilyId === selectedFamilyId)
      ? selectedFamilyId
      : families[0]?.routeFamilyId ?? null;

  if (loadingFamilies || loadingPerms) {
    return <LoadingBlock message={t("matrix.loading")} />;
  }

  if (!depotId || displayDepots.length === 0 || families.length === 0) {
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
    const hasDraft = Object.prototype.hasOwnProperty.call(
      draftAllowedByFamily,
      family.routeFamilyId,
    );
    const currentAllowed = hasDraft
      ? Boolean(draftAllowedByFamily[family.routeFamilyId])
      : Boolean(current?.allowed ?? false);
    const nextAllowed = current?.partiallyAllowed && !hasDraft ? true : !currentAllowed;
    setDraftAllowedByFamily((prev) => ({
      ...prev,
      [family.routeFamilyId]: nextAllowed,
    }));
    setDepotPermissionsDirty(scenarioId, true);
  };

  const hasDirty = Object.keys(draftAllowedByFamily).length > 0;

  const handleReset = () => {
    setDraftAllowedByFamily({});
    setDepotPermissionsDirty(scenarioId, false);
  };

  const handleSave = () => {
    if (!depotId) {
      return;
    }
    const payload = Object.keys(draftAllowedByFamily).map((routeFamilyId) => ({
      depotId,
      routeFamilyId,
      allowed: Boolean(draftAllowedByFamily[routeFamilyId]),
    }));
    if (payload.length === 0) {
      return;
    }
    updatePerms.mutate(
      { permissions: payload },
      {
        onSuccess: () => {
          setDraftAllowedByFamily({});
          setDepotPermissionsDirty(scenarioId, false);
        },
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-2">
        {hasDirty ? (
          <span className="text-xs font-medium text-amber-600">未保存の変更あり</span>
        ) : (
          <span className="text-xs text-slate-400">保存済み</span>
        )}
        <button
          type="button"
          onClick={handleReset}
          disabled={!hasDirty || updatePerms.isPending}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          破棄
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!hasDirty || updatePerms.isPending}
          className="rounded bg-primary-600 px-2 py-0.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {updatePerms.isPending ? "保存中..." : "保存"}
        </button>
      </div>
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
          {displayDepots.map((depot) => (
            <tr
              key={depotId}
              className={
                "bg-primary-50/50"
              }
            >
              <td className="px-3 py-2 font-medium text-slate-700">
                <div>{depot.name}</div>
                <div className="text-xs text-slate-500">route family 単位で一括許可</div>
              </td>
              {families.map((family) => {
                const permission = getPermission(depotId, family.routeFamilyId);
                const hasDraft = Object.prototype.hasOwnProperty.call(
                  draftAllowedByFamily,
                  family.routeFamilyId,
                );
                return (
                  <td key={family.routeFamilyId} className="px-2 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <FamilyPermissionCheckbox
                        checked={hasDraft ? Boolean(draftAllowedByFamily[family.routeFamilyId]) : (permission?.allowed ?? false)}
                        indeterminate={hasDraft ? false : (permission?.partiallyAllowed ?? false)}
                        disabled={updatePerms.isPending}
                        onChange={() => handleToggle(depotId, family)}
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
    </div>
  );
}
