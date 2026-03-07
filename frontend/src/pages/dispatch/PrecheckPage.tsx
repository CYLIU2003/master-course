import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useRoutes,
  useStops,
  useTimetable,
  useDepots,
  useDispatchScope,
  useDepotRoutePermissions,
  useDeadheadRules,
  useTurnaroundRules,
  useVehicles,
} from "@/hooks";
import { PageSection, LoadingBlock } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";

interface CheckItem {
  key: string;
  label: string;
  status: "pass" | "fail" | "warn";
  detail: string;
}

export function PrecheckPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();

  const { data: routesData, isLoading: lr } = useRoutes(scenarioId!);
  const { data: stopsData, isLoading: ls } = useStops(scenarioId!);
  const { data: timetableData, isLoading: lt } = useTimetable(scenarioId!);
  const { data: depotsData, isLoading: ld } = useDepots(scenarioId!);
  const { data: vehiclesData, isLoading: lv } = useVehicles(scenarioId!);
  const { data: scope, isLoading: lsc } = useDispatchScope(scenarioId!);
  const { data: permissionsData, isLoading: lp } = useDepotRoutePermissions(scenarioId!);
  const { data: deadheadData, isLoading: ldh } = useDeadheadRules(scenarioId!);
  const { data: turnaroundData, isLoading: lta } = useTurnaroundRules(scenarioId!);

  const isLoading = lr || ls || lt || ld || lv || lsc || lp || ldh || lta;

  const checks: CheckItem[] = useMemo(() => {
    if (isLoading) return [];

    const routes = routesData?.items ?? [];
    const stops = stopsData?.items ?? [];
    const timetable = timetableData?.items ?? [];
    const depots = depotsData?.items ?? [];
    const vehicles = vehiclesData?.items ?? [];
    const permissions = permissionsData?.items ?? [];
    const deadhead = deadheadData?.items ?? [];
    const turnaround = turnaroundData?.items ?? [];
    const selectedDepotId = scope?.depotId ?? null;
    const selectedServiceId = scope?.serviceId ?? "WEEKDAY";

    const items: CheckItem[] = [];

    // 1. Depots exist
    items.push({
      key: "depots",
      label: t("precheck.check_depots", "営業所"),
      status: depots.length > 0 ? "pass" : "fail",
      detail: depots.length > 0
        ? t("precheck.depots_ok", "{{count}}件の営業所", { count: depots.length })
        : t("precheck.depots_missing", "営業所が登録されていません"),
    });

    // 2. Routes exist
    items.push({
      key: "routes",
      label: t("precheck.check_routes", "路線"),
      status: routes.length > 0 ? "pass" : "fail",
      detail: routes.length > 0
        ? t("precheck.routes_ok", "{{count}}路線", { count: routes.length })
        : t("precheck.routes_missing", "路線が登録されていません"),
    });

    // 3. Stops exist
    items.push({
      key: "stops",
      label: t("precheck.check_stops", "停留所"),
      status: stops.length > 0 ? "pass" : "warn",
      detail: stops.length > 0
        ? t("precheck.stops_ok", "{{count}}件の停留所", { count: stops.length })
        : t("precheck.stops_missing", "停留所がありません（ODPT / GTFS を取り込んでください）"),
    });

    // 4. Vehicles exist
    items.push({
      key: "vehicles",
      label: t("precheck.check_vehicles", "車両"),
      status: vehicles.length > 0 ? "pass" : "fail",
      detail: vehicles.length > 0
        ? t("precheck.vehicles_ok", "{{count}}台の車両", { count: vehicles.length })
        : t("precheck.vehicles_missing", "車両が登録されていません"),
    });

    // 5. Timetable has rows
    items.push({
      key: "timetable",
      label: t("precheck.check_timetable", "時刻表"),
      status: timetable.length > 0 ? "pass" : "fail",
      detail: timetable.length > 0
        ? t("precheck.timetable_ok", "{{count}}行", { count: timetable.length })
        : t("precheck.timetable_missing", "時刻表が空です"),
    });

    // 6. Depot selected
    const selectedDepot = depots.find((d) => d.id === selectedDepotId);
    items.push({
      key: "depot_selected",
      label: t("precheck.check_depot_selected", "営業所選択"),
      status: selectedDepot ? "pass" : "fail",
      detail: selectedDepot
        ? t("precheck.depot_selected_ok", "{{name}}", { name: selectedDepot.name })
        : t("precheck.depot_not_selected", "営業所が選択されていません"),
    });

    // 7. Allowed routes for selected depot > 0
    const allowedRoutes = selectedDepotId
      ? permissions.filter((p) => p.depotId === selectedDepotId && p.allowed)
      : [];
    const allowedRouteCount = selectedDepotId ? allowedRoutes.length : routes.length;
    items.push({
      key: "allowed_routes",
      label: t("precheck.check_allowed_routes", "許可路線"),
      status: allowedRouteCount > 0 ? "pass" : "fail",
      detail: allowedRouteCount > 0
        ? t("precheck.allowed_routes_ok", "{{count}}路線が許可", { count: allowedRouteCount })
        : t("precheck.allowed_routes_missing", "営業所に許可された路線がありません"),
    });

    // 8. Filtered timetable rows (by service_id and allowed routes) > 0
    const allowedRouteIds = new Set(
      selectedDepotId
        ? allowedRoutes.map((p) => p.routeId)
        : routes.map((r) => r.id),
    );
    const filteredTimetable = timetable.filter(
      (row) =>
        row.service_id === selectedServiceId &&
        allowedRouteIds.has(row.route_id),
    );
    items.push({
      key: "filtered_timetable",
      label: t("precheck.check_filtered_timetable", "対象時刻表行"),
      status: filteredTimetable.length > 0 ? "pass" : timetable.length > 0 ? "fail" : "warn",
      detail: filteredTimetable.length > 0
        ? t("precheck.filtered_timetable_ok", "{{count}}行が対象", { count: filteredTimetable.length })
        : t("precheck.filtered_timetable_missing", "選択条件に一致する時刻表行がありません"),
    });

    // 9. Deadhead rules (warn if missing)
    items.push({
      key: "deadhead",
      label: t("precheck.check_deadhead", "回送ルール"),
      status: deadhead.length > 0 ? "pass" : "warn",
      detail: deadhead.length > 0
        ? t("precheck.deadhead_ok", "{{count}}件", { count: deadhead.length })
        : t("precheck.deadhead_missing", "回送ルールがありません（折返し地点が同じ場合のみ接続可能）"),
    });

    // 10. Turnaround rules (warn if missing)
    items.push({
      key: "turnaround",
      label: t("precheck.check_turnaround", "折返し規則"),
      status: turnaround.length > 0 ? "pass" : "warn",
      detail: turnaround.length > 0
        ? t("precheck.turnaround_ok", "{{count}}件", { count: turnaround.length })
        : t("precheck.turnaround_missing", "折返し規則がありません（折返し時間0分として扱われます）"),
    });

    // 11. Vehicles assigned to selected depot
    if (selectedDepotId) {
      const depotVehicles = vehicles.filter((v) => v.depotId === selectedDepotId);
      items.push({
        key: "depot_vehicles",
        label: t("precheck.check_depot_vehicles", "営業所の車両"),
        status: depotVehicles.length > 0 ? "pass" : "fail",
        detail: depotVehicles.length > 0
          ? t("precheck.depot_vehicles_ok", "{{count}}台", { count: depotVehicles.length })
          : t("precheck.depot_vehicles_missing", "選択営業所に車両が割り当てられていません"),
      });
    }

    return items;
  }, [
    isLoading, routesData, stopsData, timetableData, depotsData, vehiclesData,
    scope, permissionsData, deadheadData, turnaroundData, t,
  ]);

  const failCount = checks.filter((c) => c.status === "fail").length;
  const warnCount = checks.filter((c) => c.status === "warn").length;
  const allPass = failCount === 0;

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} editableRoutes />

      <PageSection
        title={t("precheck.title")}
        description={t("precheck.description")}
      >
        {isLoading ? (
          <LoadingBlock message={t("precheck.loading", "確認中...")} />
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                  allPass
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
                }`}
              >
                {allPass
                  ? t("precheck.all_pass", "全項目OK")
                  : t("precheck.has_errors", "{{count}}件のエラー", { count: failCount })}
              </span>
              {warnCount > 0 && (
                <span className="inline-flex items-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
                  {t("precheck.has_warnings", "{{count}}件の警告", { count: warnCount })}
                </span>
              )}
            </div>

            <div className="divide-y divide-border rounded-lg border border-border">
              {checks.map((check) => (
                <div
                  key={check.key}
                  className="flex items-center gap-3 px-4 py-3"
                >
                  <span
                    className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${
                      check.status === "pass"
                        ? "bg-green-500"
                        : check.status === "fail"
                          ? "bg-red-500"
                          : "bg-amber-500"
                    }`}
                  >
                    {check.status === "pass" ? "\u2713" : check.status === "fail" ? "\u2717" : "!"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <span className="text-sm font-medium text-slate-700">
                      {check.label}
                    </span>
                    <p className="text-xs text-slate-500">{check.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </PageSection>
    </div>
  );
}
