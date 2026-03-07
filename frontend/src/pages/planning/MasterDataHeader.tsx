import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useImportGtfsRoutes,
  useImportGtfsStops,
  useImportGtfsStopTimetables,
  useImportGtfsTimetable,
  useImportOdptRoutes,
  useImportOdptStops,
  useImportOdptStopTimetables,
  useImportOdptTimetable,
  useRoutes,
  useStopTimetables,
  useStops,
  useTimetable,
  useCalendar,
  useCalendarDates,
} from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import type { ViewMode, MasterTabKey } from "@/types/master";

interface Props {
  scenarioId: string;
}

type ModeSpec = { key: ViewMode; label: string };

const ODPT_OPERATOR = "odpt.Operator:TokyuBus";
const GTFS_FEED_PATH = "GTFS/ToeiBus-GTFS";

const MODES_DEPOTS_VEHICLES: ModeSpec[] = [
  { key: "table", label: "表" },
  { key: "map", label: "地図" },
  { key: "split", label: "分割" },
];

const MODES_ROUTES: ModeSpec[] = [
  { key: "table", label: "表" },
  { key: "node", label: "ノード" },
  { key: "map", label: "地図" },
  { key: "split", label: "分割" },
];

const MODES_STOPS: ModeSpec[] = [{ key: "table", label: "表" }];

export function MasterDataHeader({ scenarioId }: Props) {
  const { t } = useTranslation();
  const [isImportingAll, setIsImportingAll] = useState(false);
  const [isImportingGtfsAll, setIsImportingGtfsAll] = useState(false);
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);

  const importOdptRoutes = useImportOdptRoutes(scenarioId);
  const importOdptStops = useImportOdptStops(scenarioId);
  const importOdptTimetable = useImportOdptTimetable(scenarioId);
  const importOdptStopTimetables = useImportOdptStopTimetables(scenarioId);
  const importGtfsRoutes = useImportGtfsRoutes(scenarioId);
  const importGtfsStops = useImportGtfsStops(scenarioId);
  const importGtfsTimetable = useImportGtfsTimetable(scenarioId);
  const importGtfsStopTimetables = useImportGtfsStopTimetables(scenarioId);

  const { data: routesData } = useRoutes(scenarioId);
  const { data: stopsData } = useStops(scenarioId);
  const { data: timetableData } = useTimetable(scenarioId);
  const { data: stopTimetablesData } = useStopTimetables(scenarioId);
  const { data: calendarData } = useCalendar(scenarioId);
  const { data: calendarDatesData } = useCalendarDates(scenarioId);

  const routeImports = routesData?.meta?.imports ?? {};
  const stopImports = stopsData?.meta?.imports ?? {};
  const timetableImports = timetableData?.meta?.imports ?? {};
  const stopTimetableImports = stopTimetablesData?.meta?.imports ?? {};

  const addLabel: Partial<Record<MasterTabKey, string>> = {
    depots: t("master.add_depot", "+ 営業所追加"),
    vehicles: t("master.add_vehicle", "+ 車両追加"),
    routes: t("master.add_route", "+ 路線追加"),
  };

  const modes =
    activeTab === "routes"
      ? MODES_ROUTES
      : activeTab === "stops"
        ? MODES_STOPS
        : MODES_DEPOTS_VEHICLES;

  const canAdd = activeTab !== "stops";

  const handleAdd = () => {
    if (!canAdd) {
      return;
    }
    openDrawer({ isCreate: true });
  };

  const handleImportOdptAll = async () => {
    if (
      !confirm(
        t(
          "master.import_odpt_full_confirm",
          "ODPT から路線・停留所・バス時刻表・バス停時刻表を順番に取り込みます。既存の ODPT 取込データは更新されます。続行しますか？",
        ),
      )
    ) {
      return;
    }

    setIsImportingAll(true);
    try {
      const routeResult = await importOdptRoutes.mutateAsync({
        operator: ODPT_OPERATOR,
        dump: false,
      });

      const stopResult = await importOdptStops.mutateAsync({
        operator: ODPT_OPERATOR,
        dump: false,
      });

      let busCursor = 0;
      let busRounds = 0;
      let timetableResult: Awaited<
        ReturnType<typeof importOdptTimetable.mutateAsync>
      > | null = null;
      while (busRounds < 100) {
        timetableResult = await importOdptTimetable.mutateAsync({
          operator: ODPT_OPERATOR,
          dump: false,
          chunkBusTimetables: true,
          busTimetableCursor: busCursor,
          busTimetableBatchSize: 25,
          reset: busCursor === 0,
        });
        const progress = timetableResult.meta.progress;
        if (!progress || progress.complete || progress.nextCursor <= busCursor) {
          break;
        }
        busCursor = progress.nextCursor;
        busRounds += 1;
      }

      let stopCursor = 0;
      let stopRounds = 0;
      let stopTimetableResult: Awaited<
        ReturnType<typeof importOdptStopTimetables.mutateAsync>
      > | null = null;
      while (stopRounds < 100) {
        stopTimetableResult = await importOdptStopTimetables.mutateAsync({
          operator: ODPT_OPERATOR,
          dump: false,
          stopTimetableCursor: stopCursor,
          stopTimetableBatchSize: 50,
          reset: stopCursor === 0,
        });
        const progress = stopTimetableResult.meta.progress;
        if (!progress || progress.complete || progress.nextCursor <= stopCursor) {
          break;
        }
        stopCursor = progress.nextCursor;
        stopRounds += 1;
      }

      alert(
        [
          t("master.import_full_success", "ODPT データ一式の取込が完了しました。"),
          t("master.import_full_routes", "路線: {{count}} 件", {
            count: routeResult.total,
          }),
          t("master.import_full_stops", "停留所: {{count}} 件", {
            count: stopResult.total,
          }),
          t("master.import_full_timetable", "バス時刻表: {{count}} 行", {
            count: timetableResult?.total ?? 0,
          }),
          t(
            "master.import_full_stop_timetables",
            "バス停時刻表: {{count}} 件",
            {
              count: stopTimetableResult?.meta.quality.stopTimetableCount ?? 0,
            },
          ),
        ].join("\n"),
      );
    } catch (error) {
      alert(String(error));
    } finally {
      setIsImportingAll(false);
    }
  };

  const handleImportGtfsAll = async () => {
    if (
      !confirm(
        t(
          "master.import_gtfs_full_confirm",
          "GTFS から路線・停留所・時刻表・バス停時刻表を順番に取り込みます。既存の GTFS 取込データは更新されます。続行しますか？",
        ),
      )
    ) {
      return;
    }

    setIsImportingGtfsAll(true);
    try {
      const routeResult = await importGtfsRoutes.mutateAsync({
        feedPath: GTFS_FEED_PATH,
      });
      const stopResult = await importGtfsStops.mutateAsync({
        feedPath: GTFS_FEED_PATH,
      });
      const timetableResult = await importGtfsTimetable.mutateAsync({
        feedPath: GTFS_FEED_PATH,
        reset: true,
      });
      const stopTimetableResult = await importGtfsStopTimetables.mutateAsync({
        feedPath: GTFS_FEED_PATH,
        reset: true,
      });

      alert(
        [
          t("master.import_gtfs_full_success", "GTFS データ一式の取込が完了しました。"),
          t("master.import_full_routes", "路線: {{count}} 件", {
            count: routeResult.total,
          }),
          t("master.import_full_stops", "停留所: {{count}} 件", {
            count: stopResult.total,
          }),
          t("master.import_full_timetable", "バス時刻表: {{count}} 行", {
            count: timetableResult.total,
          }),
          t(
            "master.import_full_stop_timetables",
            "バス停時刻表: {{count}} 件",
            {
              count: stopTimetableResult.meta.quality.stopTimetableCount,
            },
          ),
        ].join("\n"),
      );
    } catch (error) {
      alert(String(error));
    } finally {
      setIsImportingGtfsAll(false);
    }
  };

  // ── Badge helpers ──────────────────────────────────────────

  type Badge = {
    key: string;
    label: string;
    value: string;
    warningCount: number;
    generatedAt?: string;
  };

  function badgesForSource(source: "odpt" | "gtfs"): Badge[] {
    const label = source === "odpt" ? "ODPT" : "GTFS";
    const badges: Badge[] = [];

    const routeMeta = routeImports[source];
    if (routeMeta) {
      badges.push({
        key: `routes-${source}`,
        label: `${label} ${t("master.import_badge_routes", "路線")}`,
        value: `${routeMeta.quality.routeCount}`,
        warningCount: routeMeta.warnings.length,
        generatedAt: routeMeta.generatedAt,
      });
    }

    const stopMeta = stopImports[source];
    if (stopMeta) {
      badges.push({
        key: `stops-${source}`,
        label: `${label} ${t("master.import_badge_stops", "停留所")}`,
        value: `${stopMeta.quality.stopCount}`,
        warningCount: stopMeta.warnings.length,
        generatedAt: stopMeta.generatedAt,
      });
    }

    const ttMeta = timetableImports[source];
    if (ttMeta) {
      badges.push({
        key: `timetable-${source}`,
        label: `${label} ${t("master.import_badge_timetable", "バス時刻表")}`,
        value: `${ttMeta.quality.rowCount}`,
        warningCount: ttMeta.warnings.length,
        generatedAt: ttMeta.generatedAt,
      });
    }

    const stMeta = stopTimetableImports[source];
    if (stMeta) {
      badges.push({
        key: `stop-timetables-${source}`,
        label: `${label} ${t("master.import_badge_stop_timetable", "バス停時刻表")}`,
        value: `${stMeta.quality.stopTimetableCount}`,
        warningCount: stMeta.warnings.length,
        generatedAt: stMeta.generatedAt,
      });
    }

    return badges;
  }

  const odptBadges = badgesForSource("odpt");
  const gtfsBadges = badgesForSource("gtfs");

  // Calendar sync counts (populated by GTFS timetable import)
  const calendarCount = calendarData?.total ?? 0;
  const calendarDatesCount = calendarDatesData?.total ?? 0;

  const hasOdptData = odptBadges.length > 0;
  const hasGtfsData = gtfsBadges.length > 0;

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="border-b border-border px-4 py-3">
      {/* Top row: title + view mode + add button */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">
            {t("master.title", "営業所・車両・路線・停留所")}
          </h1>
          <p className="text-xs text-slate-500">
            {t(
              "master.description",
              "ODPT / GTFS 由来の運行データを含めてマスタデータを一元管理します",
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex rounded-lg border border-border">
            {modes.map((mode) => (
              <button
                key={mode.key}
                onClick={() => setViewMode(mode.key)}
                className={`px-3 py-1 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
                  viewMode === mode.key
                    ? "bg-primary-600 text-white"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {mode.label}
              </button>
            ))}
          </div>

          {canAdd && (
            <button
              onClick={handleAdd}
              className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
            >
              {addLabel[activeTab]}
            </button>
          )}
        </div>
      </div>

      {/* Operator import cards */}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {/* ── 東急バス（ODPT）──────────────────── */}
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 px-3 py-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-emerald-800">
              {t("master.operator_odpt", "東急バス（ODPT）")}
            </h2>
            <button
              onClick={handleImportOdptAll}
              disabled={isImportingAll}
              className="rounded border border-emerald-300 bg-white px-2.5 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              {isImportingAll
                ? t("master.importing_odpt_all", "一式取込中…")
                : t("master.import_odpt_all", "一式取込")}
            </button>
          </div>
          {hasOdptData ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {odptBadges.map((badge) => (
                <span
                  key={badge.key}
                  className="rounded-full border border-emerald-200 bg-white px-2 py-0.5 text-[11px] text-emerald-800"
                >
                  {badge.label}: {badge.value}
                  {badge.generatedAt ? ` / ${badge.generatedAt}` : ""}
                  {badge.warningCount > 0 && (
                    <span className="ml-1 text-amber-600">
                      (warning {badge.warningCount})
                    </span>
                  )}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1.5 text-[11px] text-emerald-600/70">
              {t("master.no_odpt_data", "未取込")}
            </p>
          )}
        </div>

        {/* ── 都営バス（GTFS）──────────────────── */}
        <div className="rounded-lg border border-sky-200 bg-sky-50/50 px-3 py-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-sky-800">
              {t("master.operator_gtfs", "都営バス（GTFS）")}
            </h2>
            <button
              onClick={handleImportGtfsAll}
              disabled={isImportingGtfsAll}
              className="rounded border border-sky-300 bg-white px-2.5 py-1 text-[11px] font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
            >
              {isImportingGtfsAll
                ? t("master.importing_gtfs_all", "一式取込中…")
                : t("master.import_gtfs_all", "一式取込")}
            </button>
          </div>
          {hasGtfsData ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {gtfsBadges.map((badge) => (
                <span
                  key={badge.key}
                  className="rounded-full border border-sky-200 bg-white px-2 py-0.5 text-[11px] text-sky-800"
                >
                  {badge.label}: {badge.value}
                  {badge.generatedAt ? ` / ${badge.generatedAt}` : ""}
                  {badge.warningCount > 0 && (
                    <span className="ml-1 text-amber-600">
                      (warning {badge.warningCount})
                    </span>
                  )}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1.5 text-[11px] text-sky-600/70">
              {t("master.no_gtfs_data", "未取込")}
            </p>
          )}
          {/* Calendar sync status */}
          {(calendarCount > 0 || calendarDatesCount > 0) && (
            <div className="mt-1.5 flex gap-1.5">
              <span className="rounded-full border border-sky-200 bg-sky-100/60 px-2 py-0.5 text-[11px] text-sky-700">
                {t("master.calendar_sync", "運行日定義")}: {calendarCount}
              </span>
              {calendarDatesCount > 0 && (
                <span className="rounded-full border border-sky-200 bg-sky-100/60 px-2 py-0.5 text-[11px] text-sky-700">
                  {t("master.calendar_dates_sync", "日付例外")}: {calendarDatesCount}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
