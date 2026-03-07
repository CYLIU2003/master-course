import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useCalendar,
  useDepots,
  useDepotRoutePermissions,
  useDispatchScope,
  useRoutes,
  useUpdateDepotRoutePermissions,
  useUpdateDispatchScope,
} from "@/hooks";
import { LoadingBlock, EmptyState } from "@/features/common";
import type { Depot, Route } from "@/types";

interface DispatchScopePanelProps {
  scenarioId: string;
  editableRoutes?: boolean;
}

export function DispatchScopePanel({
  scenarioId,
  editableRoutes = false,
}: DispatchScopePanelProps) {
  const { t } = useTranslation();
  const { data: scope, isLoading: loadingScope } = useDispatchScope(scenarioId);
  const { data: depotsData, isLoading: loadingDepots } = useDepots(scenarioId);
  const { data: routesData, isLoading: loadingRoutes } = useRoutes(scenarioId);
  const { data: calendarData, isLoading: loadingCalendar } = useCalendar(scenarioId);
  const { data: permissionsData, isLoading: loadingPermissions } =
    useDepotRoutePermissions(scenarioId);
  const updateScope = useUpdateDispatchScope(scenarioId);
  const updatePermissions = useUpdateDepotRoutePermissions(scenarioId);

  if (
    loadingScope ||
    loadingDepots ||
    loadingRoutes ||
    loadingCalendar ||
    loadingPermissions
  ) {
    return <LoadingBlock message={t("dispatch.scope_loading", "実行条件を読み込み中...")} />;
  }

  const depots: Depot[] = depotsData?.items ?? [];
  const routes: Route[] = routesData?.items ?? [];
  const selectedDepotId = scope?.depotId ?? null;
  const matchingPermissions = (permissionsData?.items ?? []).filter(
    (item) => item.depotId === selectedDepotId,
  );
  const explicitPermissionMap = new Map(
    matchingPermissions.map((item) => [item.routeId, item.allowed]),
  );
  const hasExplicitPermissions = matchingPermissions.length > 0;

  const serviceOptions =
    calendarData?.items?.map((entry) => ({
      value: entry.service_id,
      label: entry.name || entry.service_id,
    })) ?? [
      { value: "WEEKDAY", label: t("timetable.filter_weekday", "平日") },
      { value: "SAT", label: t("timetable.filter_sat", "土曜") },
      { value: "SUN_HOL", label: t("timetable.filter_sun_hol", "日曜・休日") },
    ];

  const routesForDepot = useMemo(
    () =>
      routes.map((route) => ({
        route,
        allowed: explicitPermissionMap.get(route.id) ?? !hasExplicitPermissions,
      })),
    [explicitPermissionMap, hasExplicitPermissions, routes],
  );

  const selectedDepot = depots.find((depot) => depot.id === selectedDepotId) ?? null;
  const allowedRouteCount = routesForDepot.filter((item) => item.allowed).length;

  const handleDepotChange = (value: string) => {
    updateScope.mutate({
      depotId: value || null,
      serviceId: scope?.serviceId ?? "WEEKDAY",
    });
  };

  const handleServiceChange = (value: string) => {
    updateScope.mutate({
      depotId: selectedDepotId,
      serviceId: value,
    });
  };

  const handleRouteToggle = (routeId: string) => {
    if (!selectedDepotId) {
      return;
    }
    const nextAllowedByRoute = new Map(
      routesForDepot.map(({ route, allowed }) => [route.id, allowed]),
    );
    nextAllowedByRoute.set(routeId, !nextAllowedByRoute.get(routeId));
    updatePermissions.mutate({
      permissions: routes.map((route) => ({
        depotId: selectedDepotId,
        routeId: route.id,
        allowed: nextAllowedByRoute.get(route.id) ?? true,
      })),
    });
  };

  return (
    <div className="space-y-4 rounded-lg border border-border bg-surface-raised p-4">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {t("dispatch.depot_label", "営業所")}
          </span>
          <select
            value={selectedDepotId ?? ""}
            onChange={(event) => handleDepotChange(event.target.value)}
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
            value={scope?.serviceId ?? "WEEKDAY"}
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
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <ScopeStat
          label={t("dispatch.selected_depot", "対象営業所")}
          value={selectedDepot?.name ?? t("common.not_configured", "未設定")}
        />
        <ScopeStat
          label={t("dispatch.selected_service", "対象サービス")}
          value={serviceOptions.find((option) => option.value === (scope?.serviceId ?? "WEEKDAY"))?.label ?? "WEEKDAY"}
        />
        <ScopeStat
          label={t("dispatch.allowed_routes", "対象路線")}
          value={`${allowedRouteCount} / ${routes.length}`}
        />
      </div>

      {editableRoutes && !selectedDepotId && (
        <EmptyState
          title={t("dispatch.select_depot_first", "先に営業所を選択してください")}
          description={t(
            "dispatch.select_depot_first_description",
            "選択した営業所に含める路線をここで保存します。",
          )}
        />
      )}

      {editableRoutes && selectedDepotId && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-800">
                {t("dispatch.route_selection_title", "営業所に含める路線")}
              </h3>
              <p className="text-xs text-slate-500">
                {t(
                  "dispatch.route_selection_description",
                  "この設定はシナリオに保存され、配車計画とシミュレーションに使われます。",
                )}
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">
              {allowedRouteCount} {t("dispatch.routes_selected_suffix", "路線を選択中")}
            </span>
          </div>

          {routesForDepot.length === 0 ? (
            <EmptyState
              title={t("dispatch.no_routes", "路線がありません")}
              description={t("dispatch.no_routes_description", "先に路線を取り込んでください")}
            />
          ) : (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {routesForDepot.map(({ route, allowed }) => (
                <label
                  key={route.id}
                  className="flex items-start gap-3 rounded-lg border border-border bg-white px-3 py-2"
                >
                  <input
                    type="checkbox"
                    checked={allowed}
                    onChange={() => handleRouteToggle(route.id)}
                    disabled={updatePermissions.isPending}
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
