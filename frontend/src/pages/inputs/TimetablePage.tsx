import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useTimetable,
  useStopTimetables,
  useImportTimetableCsv,
  useImportOdptTimetable,
  useImportOdptStopTimetables,
  useExportTimetableCsv,
  useUpdateTimetable,
} from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { TimetableGeneratorDrawer } from "@/features/planning/TimetableGeneratorDrawer";
import type { TimetableRow } from "@/types";
import type { ImportProgress } from "@/types/api";

// ── Service-ID filter tabs ─────────────────────────────────────

const SERVICE_TABS = [
  { key: undefined, labelKey: "timetable.filter_all" },
  { key: "WEEKDAY",  labelKey: "timetable.filter_weekday" },
  { key: "SAT",      labelKey: "timetable.filter_sat" },
  { key: "SUN_HOL",  labelKey: "timetable.filter_sun_hol" },
] as const;

type ServiceFilter = (typeof SERVICE_TABS)[number]["key"];

type ImportRunState = {
  active: boolean;
  progress: ImportProgress | null;
  rounds: number;
};

type ImportHistoryEntry = {
  id: string;
  resource: "BusTimetable" | "BusstopPoleTimetable";
  generatedAt?: string;
  summary: string;
  warnings: string[];
};

// ── Empty new row factory ──────────────────────────────────────

function emptyRow(serviceId: string): TimetableRow {
  return {
    route_id: "",
    service_id: serviceId,
    direction: "outbound",
    trip_index: 0,
    origin: "",
    destination: "",
    departure: "06:00",
    arrival: "07:00",
    distance_km: 0,
    allowed_vehicle_types: ["BEV", "ICE"],
  };
}

// ── Component ─────────────────────────────────────────────────

export function TimetablePage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();

  // Filter state
  const [activeFilter, setActiveFilter] = useState<ServiceFilter>(undefined);

  // Data
  const { data, isLoading, error } = useTimetable(scenarioId!, activeFilter ?? undefined);
  const { data: stopTimetablesData } = useStopTimetables(scenarioId!);

  // Mutations
  const importCsvMutation = useImportTimetableCsv(scenarioId!);
  const importOdptMutation = useImportOdptTimetable(scenarioId!);
  const importOdptStopTimetablesMutation = useImportOdptStopTimetables(scenarioId!);
  const exportCsvMutation = useExportTimetableCsv(scenarioId!);
  const updateTimetable = useUpdateTimetable(scenarioId!);
  const odptImportMeta = data?.meta?.imports?.odpt;
  const odptStopTimetableImportMeta = stopTimetablesData?.meta?.imports?.odpt;

  // File input ref for import
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Add-row inline form state
  const [showAddRow, setShowAddRow] = useState(false);
  const [newRow, setNewRow] = useState<TimetableRow>(() =>
    emptyRow(activeFilter ?? "WEEKDAY"),
  );

  // Generator drawer state
  const [showGenerator, setShowGenerator] = useState(false);
  const [busImportState, setBusImportState] = useState<ImportRunState>({
    active: false,
    progress: null,
    rounds: 0,
  });
  const [stopImportState, setStopImportState] = useState<ImportRunState>({
    active: false,
    progress: null,
    rounds: 0,
  });
  const [importHistory, setImportHistory] = useState<ImportHistoryEntry[]>([]);

  function describeProgress(progress?: ImportProgress | null) {
    if (!progress) {
      return t("timetable.import_progress_preparing", "準備中...");
    }
    return t(
      "timetable.import_progress_chunks",
      "chunk {{current}} / {{total}}",
      {
        current: Math.min(progress.nextCursor, progress.totalChunks),
        total: progress.totalChunks,
      },
    );
  }

  function appendImportHistory(entry: Omit<ImportHistoryEntry, "id">) {
    setImportHistory((prev) => [
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        ...entry,
      },
      ...prev,
    ].slice(0, 8));
  }

  // ── Import CSV ────────────────────────────────────────────

  function handleImportClick() {
    fileInputRef.current?.click();
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    importCsvMutation.mutate(
      { content: text },
      {
        onError: (err) => alert(t("timetable.import_error") + "\n" + String(err)),
        onSuccess: () => alert(t("timetable.imported")),
      },
    );
    // Reset so same file can be re-imported
    e.target.value = "";
  }

  // ── Export CSV ────────────────────────────────────────────

  async function handleExport() {
    exportCsvMutation.mutate(activeFilter ?? undefined, {
      onSuccess: (res) => {
        const blob = new Blob([res.content], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = res.filename;
        a.click();
        URL.revokeObjectURL(url);
        alert(t("timetable.exported", { count: res.rows }));
      },
      onError: (err) => alert(String(err)),
    });
  }

  async function handleImportOdpt() {
    if (
      !confirm(
        t(
          "timetable.import_odpt_confirm",
          "ODPT から東急バス時刻表を取り込み、現在の時刻表を置き換えます。続行しますか？",
        ),
      )
    ) {
      return;
    }

    try {
      let cursor = 0;
      let rounds = 0;
      let lastResult: Awaited<ReturnType<typeof importOdptMutation.mutateAsync>> | null = null;
      setBusImportState({ active: true, progress: null, rounds: 0 });

      while (rounds < 100) {
        lastResult = await importOdptMutation.mutateAsync({
          operator: "odpt.Operator:TokyuBus",
          dump: false,
          chunkBusTimetables: true,
          busTimetableCursor: cursor,
          busTimetableBatchSize: 25,
          reset: cursor === 0,
        });
        const progress = lastResult.meta.progress;
        setBusImportState({ active: true, progress: progress ?? null, rounds: rounds + 1 });
        if (!progress || progress.complete || progress.nextCursor <= cursor) {
          break;
        }
        cursor = progress.nextCursor;
        rounds += 1;
      }

      if (!lastResult) {
        setBusImportState({ active: false, progress: null, rounds: 0 });
        return;
      }

      const details = [
        t("timetable.import_odpt_success", "{{count}} 件の時刻表行を取り込みました。", {
          count: lastResult.total,
        }),
        t("timetable.import_odpt_routes", "対象路線: {{count}} 件", {
          count: lastResult.meta.quality.routeCount,
        }),
      ];
      if (lastResult.meta.warnings.length > 0) {
        details.push("", lastResult.meta.warnings.join("\n"));
      }
      appendImportHistory({
        resource: "BusTimetable",
        generatedAt: lastResult.meta.generatedAt,
        summary: t(
          "timetable.import_history_bus_summary",
          "{{count}} 行 / 対象路線 {{routeCount}} 件",
          {
            count: lastResult.total,
            routeCount: lastResult.meta.quality.routeCount,
          },
        ),
        warnings: lastResult.meta.warnings,
      });
      setBusImportState({
        active: false,
        progress: lastResult.meta.progress ?? null,
        rounds: rounds + 1,
      });
      alert(details.join("\n"));
    } catch (err) {
      setBusImportState({ active: false, progress: null, rounds: 0 });
      alert(String(err));
    }
  }

  async function handleImportOdptStopTimetables() {
    if (
      !confirm(
        t(
          "timetable.import_odpt_stop_timetable_confirm",
          "ODPT のバス停時刻表を段階取得し、シナリオに保存します。続行しますか？",
        ),
      )
    ) {
      return;
    }

    try {
      let cursor = 0;
      let rounds = 0;
      let lastResult: Awaited<
        ReturnType<typeof importOdptStopTimetablesMutation.mutateAsync>
      > | null = null;
      setStopImportState({ active: true, progress: null, rounds: 0 });

      while (rounds < 100) {
        lastResult = await importOdptStopTimetablesMutation.mutateAsync({
          operator: "odpt.Operator:TokyuBus",
          dump: false,
          stopTimetableCursor: cursor,
          stopTimetableBatchSize: 50,
          reset: cursor === 0,
        });
        const progress = lastResult.meta.progress;
        setStopImportState({ active: true, progress: progress ?? null, rounds: rounds + 1 });
        if (!progress || progress.complete || progress.nextCursor <= cursor) {
          break;
        }
        cursor = progress.nextCursor;
        rounds += 1;
      }

      if (!lastResult) {
        setStopImportState({ active: false, progress: null, rounds: 0 });
        return;
      }

      const details = [
        t(
          "timetable.import_odpt_stop_timetable_success",
          "{{count}} 件のバス停時刻表を保存しました。",
          { count: lastResult.meta.quality.stopTimetableCount },
        ),
        t("timetable.import_odpt_stop_timetable_entries", "時刻表エントリ: {{count}} 件", {
          count: lastResult.meta.quality.entryCount,
        }),
      ];
      if (lastResult.meta.warnings.length > 0) {
        details.push("", lastResult.meta.warnings.join("\n"));
      }
      appendImportHistory({
        resource: "BusstopPoleTimetable",
        generatedAt: lastResult.meta.generatedAt,
        summary: t(
          "timetable.import_history_stop_summary",
          "{{count}} 件 / エントリ {{entryCount}} 件",
          {
            count: lastResult.meta.quality.stopTimetableCount,
            entryCount: lastResult.meta.quality.entryCount,
          },
        ),
        warnings: lastResult.meta.warnings,
      });
      setStopImportState({
        active: false,
        progress: lastResult.meta.progress ?? null,
        rounds: rounds + 1,
      });
      alert(details.join("\n"));
    } catch (err) {
      setStopImportState({ active: false, progress: null, rounds: 0 });
      alert(String(err));
    }
  }

  // ── Add Row ───────────────────────────────────────────────

  function handleAddRowOpen() {
    setNewRow(emptyRow(activeFilter ?? "WEEKDAY"));
    setShowAddRow(true);
  }

  function handleAddRowCancel() {
    setShowAddRow(false);
  }

  async function handleAddRowSave() {
    const current = data?.items ?? [];
    const updated = [...current, { ...newRow, trip_index: current.length }];
    updateTimetable.mutate(
      { rows: updated },
      {
        onSuccess: () => setShowAddRow(false),
      },
    );
  }

  // ── Render ────────────────────────────────────────────────

  if (isLoading) return <LoadingBlock message={t("timetable.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const rows = data?.items ?? [];

  return (
    <>
      {/* Hidden file input for CSV import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Generator drawer */}
      <TimetableGeneratorDrawer
        open={showGenerator}
        scenarioId={scenarioId!}
        defaultServiceId={activeFilter ?? "WEEKDAY"}
        existingRows={data?.items ?? []}
        onClose={() => setShowGenerator(false)}
      />

      <PageSection
        title={t("timetable.title")}
        description={t("timetable.description")}
        actions={
          <div className="flex gap-2">
            <button
              className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
              onClick={handleImportOdpt}
              disabled={importOdptMutation.isPending}
            >
              {importOdptMutation.isPending
                ? t("timetable.importing_odpt", "ODPT取込中…")
                : t("timetable.import_odpt", "ODPTから取込")}
            </button>
            <button
              className="rounded border border-cyan-300 bg-cyan-50 px-2 py-1 text-xs text-cyan-700 hover:bg-cyan-100 disabled:opacity-50"
              onClick={handleImportOdptStopTimetables}
              disabled={importOdptStopTimetablesMutation.isPending}
            >
              {importOdptStopTimetablesMutation.isPending
                ? t("timetable.importing_odpt_stop_timetables", "バス停時刻表取込中…")
                : t("timetable.import_odpt_stop_timetables", "バス停時刻表を取込")}
            </button>
            <button
              className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              onClick={handleImportClick}
              disabled={importCsvMutation.isPending}
            >
              {importCsvMutation.isPending
                ? t("common.loading")
                : t("timetable.import_csv")}
            </button>
            <button
              className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              onClick={handleExport}
              disabled={exportCsvMutation.isPending}
            >
              {exportCsvMutation.isPending
                ? t("common.loading")
                : t("timetable.export_csv")}
            </button>
            <button
              className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
              onClick={() => setShowGenerator(true)}
            >
              {t("timetable.generate")}
            </button>
            <button
              className="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700"
              onClick={handleAddRowOpen}
            >
              {t("timetable.add_row")}
            </button>
          </div>
        }
      >
        {odptImportMeta && (
          <div className="mb-3 rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-900">
            {t(
              "timetable.import_odpt_status",
              "BusTimetable 最終取込: {{generatedAt}} / {{count}} 行 / 対象路線 {{routeCount}} 件",
              {
                generatedAt: odptImportMeta.generatedAt ?? "-",
                count: odptImportMeta.quality.rowCount,
                routeCount: odptImportMeta.quality.routeCount,
              },
            )}
            {odptImportMeta.progress && (
              <span className="ml-2 text-emerald-700">
                {describeProgress(odptImportMeta.progress)}
              </span>
            )}
            {odptImportMeta.warnings.length > 0 && (
              <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
                {t("timetable.import_odpt_warning_badge", "warning {{count}}", {
                  count: odptImportMeta.warnings.length,
                })}
              </span>
            )}
          </div>
        )}
        {odptStopTimetableImportMeta && (
          <div className="mb-3 rounded-lg border border-cyan-100 bg-cyan-50/60 px-3 py-2 text-xs text-cyan-900">
            {t(
              "timetable.import_odpt_stop_timetable_status",
              "BusstopPoleTimetable 最終取込: {{generatedAt}} / {{count}} 件 / エントリ {{entryCount}} 件",
              {
                generatedAt: odptStopTimetableImportMeta.generatedAt ?? "-",
                count: odptStopTimetableImportMeta.quality.stopTimetableCount,
                entryCount: odptStopTimetableImportMeta.quality.entryCount,
              },
            )}
            {odptStopTimetableImportMeta.progress && (
              <span className="ml-2 text-cyan-700">
                {describeProgress(odptStopTimetableImportMeta.progress)}
              </span>
            )}
            {odptStopTimetableImportMeta.warnings.length > 0 && (
              <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
                {t("timetable.import_odpt_warning_badge", "warning {{count}}", {
                  count: odptStopTimetableImportMeta.warnings.length,
                })}
              </span>
            )}
          </div>
        )}
        {(busImportState.active || stopImportState.active) && (
          <div className="mb-3 grid gap-2 md:grid-cols-2">
            {busImportState.active && (
              <div className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-xs text-slate-700">
                <p className="font-semibold text-emerald-800">
                  {t("timetable.import_odpt", "ODPTから取込")}
                </p>
                <p>{describeProgress(busImportState.progress)}</p>
                <p className="text-slate-500">
                  {t("timetable.import_rounds", "リクエスト回数: {{count}}", {
                    count: busImportState.rounds,
                  })}
                </p>
              </div>
            )}
            {stopImportState.active && (
              <div className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs text-slate-700">
                <p className="font-semibold text-cyan-800">
                  {t("timetable.import_odpt_stop_timetables", "バス停時刻表を取込")}
                </p>
                <p>{describeProgress(stopImportState.progress)}</p>
                <p className="text-slate-500">
                  {t("timetable.import_rounds", "リクエスト回数: {{count}}", {
                    count: stopImportState.rounds,
                  })}
                </p>
              </div>
            )}
          </div>
        )}
        {importHistory.length > 0 && (
          <div className="mb-3 rounded-lg border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <p className="text-xs font-semibold text-slate-700">
                {t("timetable.import_history_title", "Import 履歴 / warning")}
              </p>
              <span className="text-[11px] text-slate-400">{importHistory.length}</span>
            </div>
            <div className="divide-y divide-border">
              {importHistory.map((entry) => (
                <div key={entry.id} className="px-3 py-2 text-xs text-slate-700">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
                      {entry.resource}
                    </span>
                    <span>{entry.summary}</span>
                    <span className="text-slate-400">{entry.generatedAt ?? "-"}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 ${
                        entry.warnings.length > 0
                          ? "bg-amber-50 text-amber-700"
                          : "bg-emerald-50 text-emerald-700"
                      }`}
                    >
                      {entry.warnings.length > 0
                        ? t("timetable.import_odpt_warning_badge", "warning {{count}}", {
                            count: entry.warnings.length,
                          })
                        : t("timetable.import_history_no_warning", "warning 0")}
                    </span>
                  </div>
                  {entry.warnings.length > 0 && (
                    <div className="mt-2 space-y-1 text-amber-700">
                      {entry.warnings.map((warning, index) => (
                        <p key={`${entry.id}-${index}`}>{warning}</p>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {/* Service-ID filter tabs */}
        <div className="mb-3 flex gap-1 border-b border-border">
          {SERVICE_TABS.map((tab) => (
            <button
              key={String(tab.key)}
              onClick={() => setActiveFilter(tab.key)}
              className={[
                "px-3 py-1.5 text-xs font-medium transition-colors",
                activeFilter === tab.key
                  ? "border-b-2 border-primary-600 text-primary-700"
                  : "text-slate-500 hover:text-slate-700",
              ].join(" ")}
            >
              {t(tab.labelKey)}
            </button>
          ))}
          {/* Row count badge */}
          <span className="ml-auto self-center pr-1 text-xs text-slate-400">
            {rows.length} {rows.length === 1 ? "row" : "rows"}
          </span>
        </div>

        {/* Inline add-row form */}
        {showAddRow && (
          <div className="mb-3 rounded-lg border border-primary-300 bg-primary-50 p-3">
            <p className="mb-2 text-xs font-semibold text-primary-700">
              {t("timetable.add_row")}
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
              {/* route_id */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_route")}</span>
                <input
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.route_id}
                  onChange={(e) => setNewRow({ ...newRow, route_id: e.target.value })}
                />
              </label>
              {/* service_id */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_service_id")}</span>
                <select
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.service_id}
                  onChange={(e) => setNewRow({ ...newRow, service_id: e.target.value })}
                >
                  <option value="WEEKDAY">WEEKDAY</option>
                  <option value="SAT">SAT</option>
                  <option value="SUN_HOL">SUN_HOL</option>
                </select>
              </label>
              {/* direction */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_dir")}</span>
                <select
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.direction}
                  onChange={(e) =>
                    setNewRow({
                      ...newRow,
                      direction: e.target.value as "outbound" | "inbound",
                    })
                  }
                >
                  <option value="outbound">outbound</option>
                  <option value="inbound">inbound</option>
                </select>
              </label>
              {/* origin */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_origin")}</span>
                <input
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.origin}
                  onChange={(e) => setNewRow({ ...newRow, origin: e.target.value })}
                />
              </label>
              {/* destination */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_dest")}</span>
                <input
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.destination}
                  onChange={(e) =>
                    setNewRow({ ...newRow, destination: e.target.value })
                  }
                />
              </label>
              {/* departure */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_depart")}</span>
                <input
                  className="rounded border border-border px-2 py-1 font-mono text-xs"
                  value={newRow.departure}
                  placeholder="HH:MM"
                  onChange={(e) =>
                    setNewRow({ ...newRow, departure: e.target.value })
                  }
                />
              </label>
              {/* arrival */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_arrive")}</span>
                <input
                  className="rounded border border-border px-2 py-1 font-mono text-xs"
                  value={newRow.arrival}
                  placeholder="HH:MM"
                  onChange={(e) =>
                    setNewRow({ ...newRow, arrival: e.target.value })
                  }
                />
              </label>
              {/* distance_km */}
              <label className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium text-slate-600">{t("timetable.col_dist")}</span>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  className="rounded border border-border px-2 py-1 text-xs"
                  value={newRow.distance_km}
                  onChange={(e) =>
                    setNewRow({ ...newRow, distance_km: parseFloat(e.target.value) || 0 })
                  }
                />
              </label>
            </div>
            <div className="mt-2 flex gap-2">
              <button
                className="rounded bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                onClick={handleAddRowSave}
                disabled={updateTimetable.isPending}
              >
                {updateTimetable.isPending ? t("common.loading") : "Save"}
              </button>
              <button
                className="rounded border border-border px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
                onClick={handleAddRowCancel}
              >
                {t("node_graph.cancel")}
              </button>
            </div>
          </div>
        )}

        {/* Table */}
        {rows.length === 0 ? (
          <EmptyState
            title={t("timetable.no_rows")}
            description={t("timetable.no_rows_description")}
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">{t("timetable.col_route")}</th>
                  <th className="px-3 py-2">{t("timetable.col_service_id")}</th>
                  <th className="px-3 py-2">{t("timetable.col_dir")}</th>
                  <th className="px-3 py-2">{t("timetable.col_index")}</th>
                  <th className="px-3 py-2">{t("timetable.col_origin")}</th>
                  <th className="px-3 py-2">{t("timetable.col_dest")}</th>
                  <th className="px-3 py-2">{t("timetable.col_depart")}</th>
                  <th className="px-3 py-2">{t("timetable.col_arrive")}</th>
                  <th className="px-3 py-2">{t("timetable.col_dist")}</th>
                  <th className="px-3 py-2">{t("timetable.col_vehicle_types")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row, i) => (
                  <tr key={i} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-xs">{row.route_id}</td>
                    <td className="px-3 py-2 text-xs">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">
                        {row.service_id ?? "WEEKDAY"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs">{row.direction}</td>
                    <td className="px-3 py-2 text-xs">{row.trip_index}</td>
                    <td className="px-3 py-2 text-xs">{row.origin}</td>
                    <td className="px-3 py-2 text-xs">{row.destination}</td>
                    <td className="px-3 py-2 font-mono text-xs">{row.departure}</td>
                    <td className="px-3 py-2 font-mono text-xs">{row.arrival}</td>
                    <td className="px-3 py-2 text-xs">{row.distance_km}</td>
                    <td className="px-3 py-2 text-xs">
                      {row.allowed_vehicle_types.join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageSection>
    </>
  );
}
