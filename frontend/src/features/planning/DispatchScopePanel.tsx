import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchJson } from "@/api/client";
import {
  useCalendar,
  useDepots,
  useDispatchScope,
  useRoutes,
  useUpdateDispatchScope,
} from "@/hooks";
import { EmptyState, LoadingBlock } from "@/features/common";
import type { Depot, DispatchScope, Route } from "@/types";

interface DispatchScopePanelProps {
  scenarioId: string;
  editableRoutes?: boolean;
}

type DispatchSubsetExportResponse = {
  item: {
    summary: {
      selectedDepotCount: number;
      selectedRouteFamilyCount: number;
      selectedRouteCount: number;
      timetableRowCount: number;
      dispatchTripCount: number;
      vehicleCount: number;
    };
    simulationInputPreview: {
      routeFamilyIds: string[];
      routeIds: string[];
      tripIds: string[];
      vehicleIds: string[];
    };
  };
  savedTo?: string | null;
};

export function DispatchScopePanel({
  scenarioId,
  editableRoutes = false,
}: DispatchScopePanelProps) {
  const { t } = useTranslation();
  const [exportingSubset, setExportingSubset] = useState(false);
  const [subsetExport, setSubsetExport] = useState<DispatchSubsetExportResponse | null>(null);
  const [subsetExportError, setSubsetExportError] = useState<string | null>(null);
  const { data: scope, isLoading: loadingScope } = useDispatchScope(scenarioId);
  const { data: depotsData, isLoading: loadingDepots } = useDepots(scenarioId);
  const { data: routesData, isLoading: loadingRoutes } = useRoutes(scenarioId);
  const { data: calendarData, isLoading: loadingCalendar } = useCalendar(scenarioId);
  const updateScope = useUpdateDispatchScope(scenarioId);

  const depots: Depot[] = depotsData?.items ?? [];
  const routes: Route[] = routesData?.items ?? [];
  const normalizedScope = useMemo<NormalizedDispatchScope>(
    () => normalizeScope(scope),
    [scope],
  );

  const selectedDepotIds = normalizedScope.depotSelection.depotIds;
  const selectedDepotId = normalizedScope.depotSelection.primaryDepotId;
  const serviceOptions =
    calendarData?.items?.map((entry) => ({
      value: entry.service_id,
      label: entry.name || entry.service_id,
    })) ?? [
      { value: "WEEKDAY", label: t("timetable.filter_weekday", "平日") },
      { value: "SAT", label: t("timetable.filter_sat", "土曜") },
      { value: "SUN_HOL", label: t("timetable.filter_sun_hol", "日曜・休日") },
    ];
  const effectiveRouteIds = new Set(normalizedScope.effectiveRouteIds);
  const candidateRouteIds = new Set(normalizedScope.candidateRouteIds);
  const effectiveRouteFamilyIds = useMemo(
    () =>
      Array.from(
        new Set(
          routes
            .filter((route) => effectiveRouteIds.has(route.id))
            .map((route) => route.routeFamilyId ?? route.id),
        ),
      ),
    [effectiveRouteIds, routes],
  );

  const routeRows = useMemo(
    () =>
      routes.map((route) => ({
        route,
        isCandidate: candidateRouteIds.has(route.id),
        isSelected: effectiveRouteIds.has(route.id),
      })),
    [candidateRouteIds, effectiveRouteIds, routes],
  );

  if (loadingScope || loadingDepots || loadingRoutes || loadingCalendar) {
    return <LoadingBlock message={t("dispatch.scope_loading", "実行条件を読み込み中...")} />;
  }

  const selectedDepotNames = depots
    .filter((depot) => selectedDepotIds.includes(depot.id))
    .map((depot) => depot.name);
  const selectedServiceId = normalizedScope.serviceSelection.serviceIds[0] ?? "WEEKDAY";
  const selectedServiceLabel =
    serviceOptions.find((option) => option.value === selectedServiceId)?.label ??
    selectedServiceId;
  const tripSelection = normalizedScope.tripSelection;

  const saveScope = (patch: {
    scopeId?: string | null;
    operatorId?: string | null;
    datasetVersion?: string | null;
    depotId?: string | null;
    serviceId?: string;
    depotSelection?: Partial<NormalizedDispatchScope["depotSelection"]>;
    routeSelection?: Partial<NormalizedDispatchScope["routeSelection"]>;
    serviceSelection?: Partial<NormalizedDispatchScope["serviceSelection"]>;
    tripSelection?: Partial<NormalizedDispatchScope["tripSelection"]>;
  }) => {
    updateScope.mutate({
      scopeId: normalizedScope.scopeId,
      operatorId: normalizedScope.operatorId,
      datasetVersion: normalizedScope.datasetVersion,
      depotSelection: {
        ...normalizedScope.depotSelection,
        ...(patch.depotSelection ?? {}),
      },
      routeSelection: {
        ...normalizedScope.routeSelection,
        ...(patch.routeSelection ?? {}),
      },
      serviceSelection: {
        ...normalizedScope.serviceSelection,
        ...(patch.serviceSelection ?? {}),
      },
      tripSelection: {
        ...normalizedScope.tripSelection,
        ...(patch.tripSelection ?? {}),
      },
      depotId: patch.depotId ?? normalizedScope.depotId,
      serviceId: patch.serviceId ?? normalizedScope.serviceId,
    });
  };

  const handlePrimaryDepotChange = (value: string) => {
    const nextPrimary = value || null;
    const nextDepotIds = nextPrimary
      ? [nextPrimary, ...selectedDepotIds.filter((id) => id !== nextPrimary)]
      : [];
    saveScope({
      depotId: nextPrimary,
      depotSelection: {
        mode: "include",
        depotIds: nextDepotIds,
        primaryDepotId: nextPrimary,
      },
    });
  };

  const handleDepotToggle = (depotId: string) => {
    const nextDepotIds = selectedDepotIds.includes(depotId)
      ? selectedDepotIds.filter((id) => id !== depotId)
      : [...selectedDepotIds, depotId];
    const nextPrimary =
      nextDepotIds.length === 0
        ? null
        : nextDepotIds.includes(selectedDepotId ?? "")
          ? selectedDepotId
          : nextDepotIds[0];
    saveScope({
      depotId: nextPrimary ?? null,
      depotSelection: {
        mode: "include",
        depotIds: nextDepotIds,
        primaryDepotId: nextPrimary ?? null,
      },
    });
  };

  const handleServiceChange = (value: string) => {
    saveScope({
      serviceId: value,
      serviceSelection: { serviceIds: [value] },
    });
  };

  const handleTripFlagChange = (
    key: keyof NonNullable<DispatchScope["tripSelection"]>,
    value: boolean,
  ) => {
    saveScope({
      tripSelection: {
        ...tripSelection,
        [key]: value,
      },
    });
  };

  const handleRouteToggle = (routeId: string) => {
    const includeRouteIds = new Set(normalizedScope.routeSelection.includeRouteIds);
    const excludeRouteIds = new Set(normalizedScope.routeSelection.excludeRouteIds);
    const isCandidate = candidateRouteIds.has(routeId);
    const isSelected = effectiveRouteIds.has(routeId);

    if (isSelected) {
      if (isCandidate) {
        excludeRouteIds.add(routeId);
      } else {
        includeRouteIds.delete(routeId);
      }
    } else if (isCandidate) {
      excludeRouteIds.delete(routeId);
    } else {
      includeRouteIds.add(routeId);
    }

    saveScope({
      routeSelection: {
        mode: "refine",
        includeRouteIds: Array.from(includeRouteIds),
        excludeRouteIds: Array.from(excludeRouteIds),
      },
    });
  };

  const handleExportSubset = async () => {
    setExportingSubset(true);
    setSubsetExportError(null);
    try {
      const body = await fetchJson<DispatchSubsetExportResponse>(
        `/api/scenarios/${scenarioId}/subset-export`,
        {
          method: "POST",
          body: JSON.stringify({ save: true }),
          headers: { "Content-Type": "application/json" },
        },
      );
      setSubsetExport(body);
    } catch (e: unknown) {
      setSubsetExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExportingSubset(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border border-border bg-surface-raised p-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {t("dispatch.depot_label", "主営業所")}
          </span>
          <select
            value={selectedDepotId ?? ""}
            onChange={(event) => handlePrimaryDepotChange(event.target.value)}
            disabled={updateScope.isPending}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-slate-700"
          >
            <option value="">{t("dispatch.depot_placeholder", "営業所を選択")}</option>
            {depots.map((depot) => (
              <option key={depot.id} value={depot.id}>
                {depot.name}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {t("dispatch.service_label", "運行日種別")}
          </span>
          <select
            value={selectedServiceId}
            onChange={(event) => handleServiceChange(event.target.value)}
            disabled={updateScope.isPending}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-slate-700"
          >
            {serviceOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="rounded-lg border border-border bg-white px-3 py-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Analysis Scope
          </p>
          <p className="mt-1 truncate text-sm font-medium text-slate-700">
            {normalizedScope.scopeId ?? `${selectedDepotId ?? "no-depot"}:${selectedServiceId}`}
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-5">
        <ScopeStat
          label={t("dispatch.selected_depot", "対象営業所")}
          value={selectedDepotNames.length > 0 ? selectedDepotNames.join(", ") : t("common.not_configured", "未設定")}
        />
        <ScopeStat
          label={t("dispatch.selected_service", "対象サービス")}
          value={selectedServiceLabel}
        />
        <ScopeStat
          label="対象 family"
          value={`${effectiveRouteFamilyIds.length}`}
        />
        <ScopeStat
          label={t("dispatch.allowed_routes", "対象路線")}
          value={`${normalizedScope.effectiveRouteIds.length} / ${routes.length}`}
        />
        <ScopeStat
          label="Trip filters"
          value={`${tripSelection.includeShortTurn ? "短区間含む" : "短区間除外"} / ${tripSelection.includeDepotMoves ? "入出庫含む" : "入出庫除外"}`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-white px-3 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-slate-700">Research subset export</div>
          <div className="text-xs text-slate-500">
            現在の営業所 + route family / route 選択を、dispatch/simulation 入力確認用 JSON として保存します。
          </div>
        </div>
        <button
          type="button"
          onClick={() => void handleExportSubset()}
          disabled={exportingSubset || updateScope.isPending}
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {exportingSubset ? "Exporting..." : "Subset Export"}
        </button>
      </div>

      {subsetExportError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {subsetExportError}
        </div>
      )}

      {subsetExport && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          <div className="font-medium">Subset export completed</div>
          <div className="mt-1 text-xs">
            family {subsetExport.item.summary.selectedRouteFamilyCount} / route {subsetExport.item.summary.selectedRouteCount} / trip {subsetExport.item.summary.dispatchTripCount} / vehicle {subsetExport.item.summary.vehicleCount}
          </div>
          {subsetExport.savedTo && (
            <div className="mt-1 text-xs text-emerald-800">
              saved: {subsetExport.savedTo}
            </div>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-3 rounded-lg border border-border bg-white p-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">対象営業所群</h3>
            <p className="text-xs text-slate-500">
              主営業所に加えて候補 route 抽出に使う営業所を選択します。
            </p>
          </div>
          {depots.length === 0 ? (
            <EmptyState
              title={t("dispatch.depots_missing", "営業所がありません")}
              description={t("dispatch.depots_missing_description", "先に営業所を登録してください")}
            />
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {depots.map((depot) => {
                const checked = selectedDepotIds.includes(depot.id);
                return (
                  <label
                    key={depot.id}
                    className="flex items-start gap-3 rounded-lg border border-border px-3 py-2"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => handleDepotToggle(depot.id)}
                      disabled={updateScope.isPending}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-primary-600"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-slate-700">
                        {depot.name}
                      </span>
                      <span className="block text-xs text-slate-500">
                        {selectedDepotId === depot.id ? "主営業所" : "補助スコープ"}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-lg border border-border bg-white p-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Trip 種別</h3>
            <p className="text-xs text-slate-500">
              route variant metadata に基づいて対象便種を切り替えます。
            </p>
          </div>
          <TripFlag
            checked={tripSelection.includeShortTurn}
            disabled={updateScope.isPending}
            label="短区間便を含める"
            description="`routeVariantType=short_turn` を対象に残します。"
            onChange={(value) => handleTripFlagChange("includeShortTurn", value)}
          />
          <TripFlag
            checked={tripSelection.includeDepotMoves}
            disabled={updateScope.isPending}
            label="入出庫便を含める"
            description="`routeVariantType=depot_in/depot_out` を対象に残します。"
            onChange={(value) => handleTripFlagChange("includeDepotMoves", value)}
          />
          <TripFlag
            checked={tripSelection.includeDeadhead}
            disabled={updateScope.isPending}
            label="deadhead を許可"
            description="回送接続ルールを使う前提フラグとして保存します。"
            onChange={(value) => handleTripFlagChange("includeDeadhead", value)}
          />
        </div>
      </div>

      {editableRoutes && selectedDepotIds.length === 0 && (
        <EmptyState
          title={t("dispatch.select_depot_first", "先に営業所を選択してください")}
          description={t(
            "dispatch.select_depot_first_description",
            "営業所群を決めると、自動候補 route に対して追加・除外を保存できます。",
          )}
        />
      )}

      {editableRoutes && selectedDepotIds.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-800">路線 refinement</h3>
              <p className="text-xs text-slate-500">
                営業所由来の候補 route を基準に、追加・除外を上書きします。
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">
              {normalizedScope.effectiveRouteIds.length} routes in scope
            </span>
          </div>

          {routeRows.length === 0 ? (
            <EmptyState
              title={t("dispatch.no_routes", "路線がありません")}
              description={t("dispatch.no_routes_description", "先に路線を取り込んでください")}
            />
          ) : (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {routeRows.map(({ route, isCandidate, isSelected }) => (
                <label
                  key={route.id}
                  className="flex items-start gap-3 rounded-lg border border-border bg-white px-3 py-2"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => handleRouteToggle(route.id)}
                    disabled={updateScope.isPending}
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 text-primary-600"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      {route.color && (
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: route.color }}
                        />
                      )}
                      <span className="truncate">{route.name}</span>
                    </span>
                    <span className="block text-xs text-slate-500">
                      {route.startStop} - {route.endStop}
                    </span>
                    <span className="block text-[11px] text-slate-400">
                      {isCandidate ? "営業所候補" : "明示追加候補"} / {route.routeVariantType ?? "unknown"}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface NormalizedDispatchScope extends DispatchScope {
  depotSelection: {
    mode: "include";
    depotIds: string[];
    primaryDepotId: string | null;
  };
  routeSelection: {
    mode: "all" | "include" | "exclude" | "refine";
    includeRouteIds: string[];
    excludeRouteIds: string[];
  };
  serviceSelection: {
    serviceIds: string[];
  };
  tripSelection: {
    includeShortTurn: boolean;
    includeDepotMoves: boolean;
    includeDeadhead: boolean;
  };
  candidateRouteIds: string[];
  effectiveRouteIds: string[];
}

function normalizeScope(scope?: DispatchScope | null): NormalizedDispatchScope {
  return {
    scopeId: scope?.scopeId ?? null,
    operatorId: scope?.operatorId ?? null,
    datasetVersion: scope?.datasetVersion ?? null,
    depotSelection: {
      mode: "include",
      depotIds: scope?.depotSelection?.depotIds ?? (scope?.depotId ? [scope.depotId] : []),
      primaryDepotId: scope?.depotSelection?.primaryDepotId ?? scope?.depotId ?? null,
    },
    routeSelection: {
      mode: scope?.routeSelection?.mode ?? "refine",
      includeRouteIds: scope?.routeSelection?.includeRouteIds ?? [],
      excludeRouteIds: scope?.routeSelection?.excludeRouteIds ?? [],
    },
    serviceSelection: {
      serviceIds: scope?.serviceSelection?.serviceIds ?? [scope?.serviceId ?? "WEEKDAY"],
    },
    tripSelection: {
      includeShortTurn: scope?.tripSelection?.includeShortTurn ?? true,
      includeDepotMoves: scope?.tripSelection?.includeDepotMoves ?? true,
      includeDeadhead: scope?.tripSelection?.includeDeadhead ?? true,
    },
    candidateRouteIds: scope?.candidateRouteIds ?? [],
    effectiveRouteIds: scope?.effectiveRouteIds ?? [],
    depotId: scope?.depotId ?? null,
    serviceId: scope?.serviceId ?? "WEEKDAY",
  };
}

function ScopeStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-sunken px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-medium text-slate-700">{value}</p>
    </div>
  );
}

function TripFlag({
  checked,
  disabled,
  label,
  description,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  description: string;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 rounded-lg border border-border px-3 py-2">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-primary-600"
      />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-700">{label}</span>
        <span className="block text-xs text-slate-500">{description}</span>
      </span>
    </label>
  );
}
