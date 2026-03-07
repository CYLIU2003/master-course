import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useImportOdptRoutes,
  useImportOdptStops,
  useImportOdptStopTimetables,
  useImportOdptTimetable,
  useRoutes,
  useStopTimetables,
  useStops,
  useTimetable,
} from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import type { ViewMode, MasterTabKey } from "@/types/master";

interface Props {
  scenarioId: string;
}

type ModeSpec = { key: ViewMode; label: string };

const ODPT_OPERATOR = "odpt.Operator:TokyuBus";

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
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);

  const importOdptRoutes = useImportOdptRoutes(scenarioId);
  const importOdptStops = useImportOdptStops(scenarioId);
  const importOdptTimetable = useImportOdptTimetable(scenarioId);
  const importOdptStopTimetables = useImportOdptStopTimetables(scenarioId);

  const { data: routesData } = useRoutes(scenarioId);
  const { data: stopsData } = useStops(scenarioId);
  const { data: timetableData } = useTimetable(scenarioId);
  const { data: stopTimetablesData } = useStopTimetables(scenarioId);

  const routeImportMeta = routesData?.meta?.imports?.odpt;
  const stopImportMeta = stopsData?.meta?.imports?.odpt;
  const timetableImportMeta = timetableData?.meta?.imports?.odpt;
  const stopTimetableImportMeta = stopTimetablesData?.meta?.imports?.odpt;

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

  const importBadges = [
    routeImportMeta && {
      key: "routes",
      label: t("master.import_badge_routes", "路線"),
      value: `${routeImportMeta.quality.routeCount}`,
      warningCount: routeImportMeta.warnings.length,
      generatedAt: routeImportMeta.generatedAt,
    },
    stopImportMeta && {
      key: "stops",
      label: t("master.import_badge_stops", "停留所"),
      value: `${stopImportMeta.quality.stopCount}`,
      warningCount: stopImportMeta.warnings.length,
      generatedAt: stopImportMeta.generatedAt,
    },
    timetableImportMeta && {
      key: "timetable",
      label: t("master.import_badge_timetable", "バス時刻表"),
      value: `${timetableImportMeta.quality.rowCount}`,
      warningCount: timetableImportMeta.warnings.length,
      generatedAt: timetableImportMeta.generatedAt,
    },
    stopTimetableImportMeta && {
      key: "stop-timetables",
      label: t("master.import_badge_stop_timetable", "バス停時刻表"),
      value: `${stopTimetableImportMeta.quality.stopTimetableCount}`,
      warningCount: stopTimetableImportMeta.warnings.length,
      generatedAt: stopTimetableImportMeta.generatedAt,
    },
  ].filter(Boolean) as Array<{
    key: string;
    label: string;
    value: string;
    warningCount: number;
    generatedAt?: string;
  }>;

  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("master.title", "営業所・車両・路線・停留所")}
        </h1>
        <p className="text-xs text-slate-500">
          {t(
            "master.description",
            "ODPT 由来の運行データを含めてマスタデータを一元管理します",
          )}
        </p>
        {importBadges.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
            {importBadges.map((badge) => (
              <span
                key={badge.key}
                className="rounded-full border border-border bg-surface-sunken px-2.5 py-1"
              >
                {badge.label}: {badge.value}
                {badge.generatedAt ? ` / ${badge.generatedAt}` : ""}
                {badge.warningCount > 0 ? ` / warning ${badge.warningCount}` : ""}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleImportOdptAll}
          disabled={isImportingAll}
          className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
        >
          {isImportingAll
            ? t("master.importing_odpt_all", "ODPT一式取込中…")
            : t("master.import_odpt_all", "ODPTデータ一式を取込")}
        </button>

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
  );
}
