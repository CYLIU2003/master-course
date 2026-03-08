import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useImportOdptRoutes,
  useImportOdptStops,
  useImportOdptStopTimetables,
  useImportOdptTimetable,
  useRoutes,
  useStopTimetablesSummary,
  useStops,
  useTimetableSummary,
} from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useImportJobStore } from "@/stores/import-job-store";
import { useTabWarmStore } from "@/stores/tab-warm-store";
import { ImportLogPanel } from "@/features/explorer/ImportLogPanel";
import { ImportProgressPanel } from "@/features/explorer/ImportProgressPanel";
import { measureAsyncStep } from "@/utils/perf/measureAsyncStep";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";
import type { ViewMode, MasterTabKey } from "@/types/master";

interface Props {
  scenarioId: string;
}

type ModeSpec = { key: ViewMode; label: string };

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
  useRenderTrace("MasterDataHeader");
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const setViewMode = useMasterUiStore((s) => s.setViewMode);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);
  const { data: routesData } = useRoutes(scenarioId);
  const { data: stopsData } = useStops(scenarioId);
  const { data: timetableSummary } = useTimetableSummary(scenarioId);
  const { data: stopTimetablesSummary } = useStopTimetablesSummary(scenarioId);
  const importOdptRoutes = useImportOdptRoutes(scenarioId);
  const importOdptStops = useImportOdptStops(scenarioId);
  const importOdptTimetable = useImportOdptTimetable(scenarioId);
  const importOdptStopTimetables = useImportOdptStopTimetables(scenarioId);
  const startJob = useImportJobStore((state) => state.startJob);
  const updateStage = useImportJobStore((state) => state.updateStage);
  const appendLog = useImportJobStore((state) => state.appendLog);
  const completeJob = useImportJobStore((state) => state.completeJob);
  const failJob = useImportJobStore((state) => state.failJob);
  const warmTabs = useTabWarmStore((state) => state.tabs);

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
  const importBusy =
    importOdptRoutes.isPending ||
    importOdptStops.isPending ||
    importOdptTimetable.isPending ||
    importOdptStopTimetables.isPending;

  const summaryCards = [
    { label: t("master.summary_routes", "路線"), value: routesData?.total ?? 0 },
    { label: t("master.summary_stops", "停留所"), value: stopsData?.total ?? 0 },
    {
      label: t("master.summary_timetable", "時刻表"),
      value: timetableSummary?.item.totalRows ?? 0,
    },
    {
      label: t("master.summary_stop_timetables", "バス停時刻表"),
      value: stopTimetablesSummary?.item.totalTimetables ?? 0,
    },
  ];

  async function runOdptImport(
    resource: "stops" | "routes" | "timetable" | "stop-timetables",
  ) {
    const messages = {
      stops: "ODPT から停留所を取り込みます。続行しますか？",
      routes: "ODPT から路線を取り込みます。続行しますか？",
      timetable: "ODPT からバス時刻表を取り込みます。続行しますか？",
      "stop-timetables": "ODPT からバス停時刻表を取り込みます。続行しますか？",
    } as const;
    if (!window.confirm(messages[resource])) {
      return;
    }

    const jobId = `master-import-${resource}`;
    startJob({
      jobId,
      source: "odpt",
      label: `ODPT ${resource} import`,
      stages: [
        { id: "request", label: "ODPT fetch", weight: 50 },
        { id: "persist", label: "Normalize / save", weight: 35 },
        { id: "refresh", label: "Refresh UI cache", weight: 15 },
      ],
    });
    appendLog(jobId, { level: "info", message: `${resource} import started` });

    try {
      if (resource === "stops") {
        updateStage(jobId, "request", { status: "running", progress: 30 });
        const result = await measureAsyncStep("master:import-stops", () =>
          importOdptStops.mutateAsync({
            operator: "odpt.Operator:TokyuBus",
            dump: true,
          }),
        );
        updateStage(jobId, "request", { status: "success", progress: 100 });
        updateStage(jobId, "persist", {
          status: "success",
          progress: 100,
          currentCount: result.total,
          totalCount: result.total,
          message: `${result.total} stops imported`,
        });
        updateStage(jobId, "refresh", { status: "success", progress: 100 });
        completeJob(jobId, `停留所を ${result.total} 件取り込みました。`);
        return;
      }
      if (resource === "routes") {
        updateStage(jobId, "request", { status: "running", progress: 30 });
        const result = await measureAsyncStep("master:import-routes", () =>
          importOdptRoutes.mutateAsync({
            operator: "odpt.Operator:TokyuBus",
            dump: true,
          }),
        );
        updateStage(jobId, "request", { status: "success", progress: 100 });
        updateStage(jobId, "persist", {
          status: "success",
          progress: 100,
          currentCount: result.total,
          totalCount: result.total,
          message: `${result.total} routes imported`,
        });
        updateStage(jobId, "refresh", { status: "success", progress: 100 });
        completeJob(jobId, `路線を ${result.total} 件取り込みました。`);
        return;
      }
      if (resource === "timetable") {
        updateStage(jobId, "request", { status: "running", progress: 30 });
        const result = await measureAsyncStep("master:import-timetable", () =>
          importOdptTimetable.mutateAsync({
            operator: "odpt.Operator:TokyuBus",
            dump: true,
            reset: true,
          }),
        );
        updateStage(jobId, "request", { status: "success", progress: 100 });
        updateStage(jobId, "persist", {
          status: "success",
          progress: 100,
          currentCount: result.total,
          totalCount: result.total,
          message: `${result.total} timetable rows imported`,
        });
        updateStage(jobId, "refresh", { status: "success", progress: 100 });
        completeJob(jobId, `時刻表を ${result.total} 件取り込みました。`);
        return;
      }
      updateStage(jobId, "request", { status: "running", progress: 30 });
      const result = await measureAsyncStep("master:import-stop-timetables", () =>
        importOdptStopTimetables.mutateAsync({
          operator: "odpt.Operator:TokyuBus",
          dump: true,
          reset: true,
        }),
      );
      updateStage(jobId, "request", { status: "success", progress: 100 });
      updateStage(jobId, "persist", {
        status: "success",
        progress: 100,
        currentCount: result.meta.quality.stopTimetableCount,
        totalCount: result.meta.quality.stopTimetableCount,
        message: `${result.meta.quality.entryCount} stop timetable entries imported`,
      });
      updateStage(jobId, "refresh", { status: "success", progress: 100 });
      completeJob(
        jobId,
        `バス停時刻表を ${result.meta.quality.stopTimetableCount} 件取り込みました。`,
      );
    } catch (error) {
      failJob(jobId, error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="border-b border-border px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">
            {t("master.title", "営業所・車両・路線・停留所")}
          </h1>
          <p className="text-xs text-slate-500">
            {t(
              "master.description",
              "確定済みの運行モデルを編集します。公開データ取込・所属補正・品質確認は Explorer で行います。",
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/odpt-explorer"
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            {t("nav.odpt_explorer", "公開情報収集エクスプローラー")}
          </Link>
          <Link
            to={`/scenarios/${scenarioId}/timetable`}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            {t("master.open_timetable", "時刻表タブへ")}
          </Link>
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
              onClick={() => openDrawer({ isCreate: true })}
              className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
            >
              {addLabel[activeTab]}
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600">
          <div className="flex flex-wrap items-center gap-2">
            <span>
              {t(
                "master.explorer_note",
                "公開データの取込、warning、完全性、所属営業所割当は Explorer と各タブから実行できます。",
              )}
            </span>
            <span className="font-mono text-slate-500">{scenarioId}</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {summaryCards.map((card) => (
              <div
                key={card.label}
                className="rounded-md border border-slate-200 bg-white px-3 py-2"
              >
                <div className="text-[11px] text-slate-500">{card.label}</div>
                <div className="mt-1 text-base font-semibold text-slate-800">
                  {card.value}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(
              Object.entries(warmTabs) as Array<
                [keyof typeof warmTabs, { status: string; detail?: string }]
              >
            ).map(([tab, state]) => (
              <span
                key={tab}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600"
                title={state.detail}
              >
                {tab}: {state.status}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">
            {t("master.quick_import", "ODPT クイック取込")}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              onClick={() => void runOdptImport("stops")}
              disabled={importBusy}
              className="rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 disabled:opacity-50"
            >
              {t("master.import_stops", "停留所")}
            </button>
            <button
              onClick={() => void runOdptImport("routes")}
              disabled={importBusy}
              className="rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 disabled:opacity-50"
            >
              {t("master.import_routes", "路線")}
            </button>
            <button
              onClick={() => void runOdptImport("timetable")}
              disabled={importBusy}
              className="rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 disabled:opacity-50"
            >
              {t("master.import_timetable", "時刻表")}
            </button>
            <button
              onClick={() => void runOdptImport("stop-timetables")}
              disabled={importBusy}
              className="rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 disabled:opacity-50"
            >
              {t("master.import_stop_timetables", "バス停時刻表")}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ImportProgressPanel />
        <ImportLogPanel />
      </div>
    </div>
  );
}
