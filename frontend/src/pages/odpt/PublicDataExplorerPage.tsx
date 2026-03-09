import { useCallback, useEffect } from "react";
import { fetchJson } from "@/api/client";
import { TabWarmBoundary, VirtualizedList } from "@/features/common";
import {
  usePublicDataExplorerStore,
  selectSelectedMapOverview,
  selectComparisonRows,
} from "@/stores/public-data-explorer-store";
import type { OperatorId } from "@/api/public-data";

// ── DB Visualization Types (reused from OdptExplorerPage) ─────────────────

type DbRoute = {
  route_id: string;
  route_code: string;
  route_name: string;
  direction?: string;
  stop_count: number;
  trip_count: number;
  distance_km?: number;
  first_departure?: string;
  last_arrival?: string;
};

type DbStop = {
  stop_id: string;
  stop_name: string;
  stop_name_en?: string;
  lat?: number;
  lon?: number;
  kind?: string;
  source?: string;
};

type TimetableSummary = {
  by_service: Array<{
    service_id: string;
    trip_count: number;
    route_count: number;
    earliest_departure?: string;
    latest_arrival?: string;
  }>;
  total: number;
};

// ── Helpers ───────────────────────────────────────────────────

const OPERATOR_META: Record<
  OperatorId,
  { label: string; labelEn: string; sourceLabel: string; color: string; bgColor: string; borderColor: string }
> = {
  tokyu: {
    label: "東急バス",
    labelEn: "Tokyu Bus",
    sourceLabel: "ODPT",
    color: "text-red-700",
    bgColor: "bg-red-50",
    borderColor: "border-red-200",
  },
  toei: {
    label: "都営バス",
    labelEn: "Toei Bus",
    sourceLabel: "GTFS",
    color: "text-blue-700",
    bgColor: "bg-blue-50",
    borderColor: "border-blue-200",
  },
};

function formatCount(n: number): string {
  return n.toLocaleString();
}

// ── Operator Summary Card ─────────────────────────────────────

function OperatorCard({ operatorId }: { operatorId: OperatorId }) {
  const summary = usePublicDataExplorerStore(
    (s) => s.summaries.itemsByOperator[operatorId],
  );
  const selectedOperator = usePublicDataExplorerStore(
    (s) => s.selectedOperator,
  );
  const setSelectedOperator = usePublicDataExplorerStore(
    (s) => s.setSelectedOperator,
  );
  const loadMapOverview = usePublicDataExplorerStore(
    (s) => s.loadMapOverview,
  );
  const meta = OPERATOR_META[operatorId];
  const isSelected = selectedOperator === operatorId;

  const handleSelect = useCallback(() => {
    if (isSelected) {
      setSelectedOperator("all");
    } else {
      setSelectedOperator(operatorId);
      void loadMapOverview(operatorId);
    }
  }, [isSelected, setSelectedOperator, operatorId, loadMapOverview]);

  if (!summary) {
    return (
      <div className="rounded-xl border border-border bg-surface-raised p-6 animate-pulse">
        <div className="h-5 w-24 rounded bg-slate-200" />
        <div className="mt-4 space-y-2">
          <div className="h-4 w-32 rounded bg-slate-100" />
          <div className="h-4 w-28 rounded bg-slate-100" />
          <div className="h-4 w-20 rounded bg-slate-100" />
        </div>
      </div>
    );
  }

  return (
    <div
      className={`rounded-xl border-2 p-6 transition-all cursor-pointer hover:shadow-md ${
        isSelected
          ? `${meta.borderColor} ${meta.bgColor} shadow-sm`
          : "border-border bg-surface-raised hover:border-slate-300"
      }`}
      onClick={handleSelect}
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className={`text-lg font-bold ${isSelected ? meta.color : "text-slate-800"}`}>
            {meta.label}
          </h3>
          <p className="text-xs text-slate-500">
            {meta.sourceLabel}ベースの公開情報
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            summary.dbExists
              ? "bg-emerald-100 text-emerald-700"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {summary.dbExists ? "DB Ready" : "No DB"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <CountItem label="路線数" value={summary.counts.routes} />
        <CountItem label="停留所数" value={summary.counts.stops} />
        <CountItem label="trip数" value={summary.counts.timetableRows} />
        <CountItem label="停留所時刻表" value={summary.counts.stopTimetables} />
        <CountItem label="trip stop times" value={summary.counts.tripStopTimes} />
        <CountItem label="calendar" value={summary.counts.calendar} />
      </div>

      {summary.updatedAt && (
        <p className="mt-3 text-[10px] text-slate-400">
          最終更新: {new Date(summary.updatedAt).toLocaleString("ja-JP")}
        </p>
      )}

      <button
        onClick={(e) => {
          e.stopPropagation();
          handleSelect();
        }}
        className={`mt-4 w-full rounded-lg py-2 text-sm font-medium transition-colors ${
          isSelected
            ? `${meta.bgColor} ${meta.color} border ${meta.borderColor}`
            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
        }`}
      >
        {isSelected ? "概要に戻る" : `${meta.label}を表示`}
      </button>
    </div>
  );
}

function CountItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-white/60 border border-slate-100 px-3 py-2">
      <div className="text-base font-bold text-slate-800">
        {formatCount(value)}
      </div>
      <div className="text-[10px] text-slate-500">{label}</div>
    </div>
  );
}

// ── Comparison Bar Chart (simple CSS bars) ────────────────────

function ComparisonSection() {
  const rows = usePublicDataExplorerStore(selectComparisonRows);

  if (rows.length === 0) return null;

  const metrics = [
    { key: "routes", label: "路線数" },
    { key: "stops", label: "停留所数" },
    { key: "timetableRows", label: "trip数" },
    { key: "stopTimetables", label: "停留所時刻表数" },
  ] as const;

  return (
    <div className="rounded-xl border border-border bg-surface-raised p-6">
      <h2 className="text-sm font-semibold text-slate-700 mb-1">
        事業者比較（概要）
      </h2>
      <p className="text-xs text-slate-400 mb-4">
        事業者ごとの概要件数のみを比較します。詳細は事業者を選択してください。
      </p>
      <div className="space-y-5">
        {metrics.map((metric) => {
          const max = Math.max(...rows.map((r) => r[metric.key]), 1);
          return (
            <div key={metric.key}>
              <div className="text-xs font-medium text-slate-600 mb-1.5">
                {metric.label}
              </div>
              <div className="space-y-1.5">
                {rows.map((row) => {
                  const value = row[metric.key];
                  const pct = (value / max) * 100;
                  const meta = OPERATOR_META[row.operatorId as OperatorId];
                  return (
                    <div key={row.operatorId} className="flex items-center gap-2">
                      <span className="w-16 text-[11px] text-slate-500 text-right shrink-0">
                        {meta?.label ?? row.operatorId}
                      </span>
                      <div className="flex-1 h-5 rounded-full bg-slate-100 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            row.operatorId === "tokyu"
                              ? "bg-red-400"
                              : "bg-blue-400"
                          }`}
                          style={{ width: `${Math.max(pct, 2)}%` }}
                        />
                      </div>
                      <span className="w-16 text-xs font-mono text-slate-700 shrink-0">
                        {formatCount(value)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Map Overview Panel (lightweight) ──────────────────────────

function MapOverviewPanel() {
  const overview = usePublicDataExplorerStore(selectSelectedMapOverview);
  const selectedOperator = usePublicDataExplorerStore(
    (s) => s.selectedOperator,
  );
  const loading = usePublicDataExplorerStore(
    (s) =>
      selectedOperator !== "all" &&
      (s.mapOverviewLoading[selectedOperator as OperatorId] ?? false),
  );

  if (selectedOperator === "all") return null;
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-surface-raised p-6">
        <p className="text-sm text-slate-400 animate-pulse">
          {OPERATOR_META[selectedOperator as OperatorId]?.label ?? selectedOperator}{" "}
          の概要地図を読み込んでいます…
        </p>
      </div>
    );
  }
  if (!overview) return null;

  return (
    <div className="rounded-xl border border-border bg-surface-raised p-6 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-700">概要地図</h2>
        <p className="text-xs text-slate-400">
          軽量化したプレビュー情報のみを表示。詳細データは必要時のみ読込。
        </p>
      </div>

      {overview.bounds && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-center">
            <div className="text-xs text-slate-400">minLat</div>
            <div className="text-sm font-mono">{overview.bounds.minLat.toFixed(4)}</div>
          </div>
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-center">
            <div className="text-xs text-slate-400">maxLat</div>
            <div className="text-sm font-mono">{overview.bounds.maxLat.toFixed(4)}</div>
          </div>
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-center">
            <div className="text-xs text-slate-400">minLon</div>
            <div className="text-sm font-mono">{overview.bounds.minLon.toFixed(4)}</div>
          </div>
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-center">
            <div className="text-xs text-slate-400">maxLon</div>
            <div className="text-sm font-mono">{overview.bounds.maxLon.toFixed(4)}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h3 className="text-xs font-semibold text-slate-600 mb-2">
            停留所クラスタ ({overview.stopClusters.length})
          </h3>
          {overview.stopClusters.length > 0 ? (
            <div className="max-h-48 overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="py-1.5 px-2 text-left font-semibold text-slate-500">lat</th>
                    <th className="py-1.5 px-2 text-left font-semibold text-slate-500">lon</th>
                    <th className="py-1.5 px-2 text-right font-semibold text-slate-500">count</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.stopClusters.slice(0, 20).map((c) => (
                    <tr key={c.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-1 px-2 font-mono">{c.lat.toFixed(3)}</td>
                      <td className="py-1 px-2 font-mono">{c.lon.toFixed(3)}</td>
                      <td className="py-1 px-2 text-right">{c.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {overview.stopClusters.length > 20 && (
                <p className="px-2 py-1 text-[10px] text-slate-400">
                  ... 他{overview.stopClusters.length - 20}件
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-400">クラスタデータなし</p>
          )}
        </div>

        <div>
          <h3 className="text-xs font-semibold text-slate-600 mb-2">
            営業所・車庫候補 ({overview.depotPoints.length})
          </h3>
          {overview.depotPoints.length > 0 ? (
            <div className="max-h-48 overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="py-1.5 px-2 text-left font-semibold text-slate-500">名前</th>
                    <th className="py-1.5 px-2 text-left font-semibold text-slate-500">lat</th>
                    <th className="py-1.5 px-2 text-left font-semibold text-slate-500">lon</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.depotPoints.map((d) => (
                    <tr key={d.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-1 px-2">{d.label}</td>
                      <td className="py-1 px-2 font-mono">{d.lat.toFixed(4)}</td>
                      <td className="py-1 px-2 font-mono">{d.lon.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-slate-400">depot候補なし</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Detail Panel (loaded only when operator selected) ──────────

function DetailPanel({ operatorId }: { operatorId: OperatorId }) {
  const pageSize = 200;
  const [routes, setRoutes] = React.useState<DbRoute[]>([]);
  const [routesTotal, setRoutesTotal] = React.useState(0);
  const [routeOffset, setRouteOffset] = React.useState(0);
  const [routeQuery, setRouteQuery] = React.useState("");
  const [stops, setStops] = React.useState<DbStop[]>([]);
  const [stopsTotal, setStopsTotal] = React.useState(0);
  const [stopOffset, setStopOffset] = React.useState(0);
  const [stopQuery, setStopQuery] = React.useState("");
  const [ttSummary, setTtSummary] = React.useState<TimetableSummary | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [detailTab, setDetailTab] = React.useState<"routes" | "stops" | "timetable">("routes");

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [routesRes, stopsRes, summaryRes] = await Promise.all([
        fetchJson<{ items: DbRoute[]; total: number }>(
          `/api/catalog/operators/${operatorId}/routes?limit=${pageSize}&offset=0`,
        ),
        fetchJson<{ items: DbStop[]; total: number }>(
          `/api/catalog/operators/${operatorId}/stops?limit=${pageSize}&offset=0`,
        ),
        fetchJson<{ item: TimetableSummary }>(
          `/api/catalog/operators/${operatorId}/timetable/summary`,
        ),
      ]);
      setRoutes(routesRes.items ?? []);
      setRoutesTotal(routesRes.total ?? 0);
      setStops(stopsRes.items ?? []);
      setStopsTotal(stopsRes.total ?? 0);
      setTtSummary(summaryRes.item ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [operatorId]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  async function loadRoutesPage(offset: number, q: string) {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      if (q.trim()) params.set("q", q.trim());
      const body = await fetchJson<{ items: DbRoute[]; total: number }>(
        `/api/catalog/operators/${operatorId}/routes?${params.toString()}`,
      );
      setRoutes(body.items ?? []);
      setRoutesTotal(body.total ?? 0);
      setRouteOffset(offset);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadStopsPage(offset: number, q: string) {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      if (q.trim()) params.set("q", q.trim());
      const body = await fetchJson<{ items: DbStop[]; total: number }>(
        `/api/catalog/operators/${operatorId}/stops?${params.toString()}`,
      );
      setStops(body.items ?? []);
      setStopsTotal(body.total ?? 0);
      setStopOffset(offset);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const meta = OPERATOR_META[operatorId];

  return (
    <div className="rounded-xl border border-border bg-surface-raised p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-sm font-semibold ${meta.color}`}>
            {meta.label} 詳細データ
          </h2>
          <p className="text-xs text-slate-400">
            現在は{meta.label}のみを表示。他事業者データは混在させません。
          </p>
        </div>
        {loading && <span className="text-xs text-slate-400 animate-pulse">Loading...</span>}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-slate-200">
        {(["routes", "stops", "timetable"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setDetailTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              detailTab === tab
                ? "border-primary-500 text-primary-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab === "routes" ? `路線 (${formatCount(routesTotal)})` : tab === "stops" ? `停留所 (${formatCount(stopsTotal)})` : `時刻表 (${formatCount(ttSummary?.total ?? 0)})`}
          </button>
        ))}
      </div>

      {/* Routes tab */}
      {detailTab === "routes" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="block text-xs font-medium text-slate-500">route search</label>
              <input
                type="text"
                value={routeQuery}
                onChange={(e) => setRouteQuery(e.target.value)}
                placeholder="route_id / route_code / name"
                className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm w-64"
              />
            </div>
            <button
              onClick={() => void loadRoutesPage(0, routeQuery)}
              disabled={loading}
              className="rounded-lg border border-border bg-surface px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Search
            </button>
            <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
              <button
                onClick={() => void loadRoutesPage(Math.max(0, routeOffset - pageSize), routeQuery)}
                disabled={loading || routeOffset === 0}
                className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40"
              >
                Prev
              </button>
              <span>
                {routes.length > 0 ? routeOffset + 1 : 0}-
                {Math.min(routeOffset + routes.length, routesTotal)} / {formatCount(routesTotal)}
              </span>
              <button
                onClick={() => void loadRoutesPage(routeOffset + pageSize, routeQuery)}
                disabled={loading || routeOffset + routes.length >= routesTotal}
                className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
          {routes.length > 0 ? (
            <div className="rounded-lg border border-slate-200">
              <div className="grid grid-cols-[1.4fr_1.4fr_0.7fr_0.6fr_0.6fr_0.8fr_0.8fr] gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500">
                <span>route_id</span><span>name</span><span>dir</span>
                <span className="text-right">stops</span><span className="text-right">trips</span>
                <span>first</span><span>last</span>
              </div>
              <VirtualizedList
                items={routes}
                height={400}
                itemHeight={40}
                className="bg-white"
                getKey={(r) => r.route_id}
                renderItem={(route) => (
                  <div className="grid h-full grid-cols-[1.4fr_1.4fr_0.7fr_0.6fr_0.6fr_0.8fr_0.8fr] gap-3 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                    <div className="truncate font-mono" title={route.route_id}>{route.route_code || route.route_id}</div>
                    <div className="truncate" title={route.route_name}>{route.route_name}</div>
                    <div>{route.direction ?? "-"}</div>
                    <div className="text-right">{route.stop_count}</div>
                    <div className="text-right">{route.trip_count}</div>
                    <div className="font-mono">{route.first_departure ?? "-"}</div>
                    <div className="font-mono">{route.last_arrival ?? "-"}</div>
                  </div>
                )}
              />
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
              条件に一致する route はありません。
            </div>
          )}
        </div>
      )}

      {/* Stops tab */}
      {detailTab === "stops" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="block text-xs font-medium text-slate-500">stop search</label>
              <input
                type="text"
                value={stopQuery}
                onChange={(e) => setStopQuery(e.target.value)}
                placeholder="stop_id / stop_name"
                className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm w-64"
              />
            </div>
            <button
              onClick={() => void loadStopsPage(0, stopQuery)}
              disabled={loading}
              className="rounded-lg border border-border bg-surface px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Search
            </button>
            <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
              <button
                onClick={() => void loadStopsPage(Math.max(0, stopOffset - pageSize), stopQuery)}
                disabled={loading || stopOffset === 0}
                className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40"
              >
                Prev
              </button>
              <span>
                {stops.length > 0 ? stopOffset + 1 : 0}-
                {Math.min(stopOffset + stops.length, stopsTotal)} / {formatCount(stopsTotal)}
              </span>
              <button
                onClick={() => void loadStopsPage(stopOffset + pageSize, stopQuery)}
                disabled={loading || stopOffset + stops.length >= stopsTotal}
                className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
          {stops.length > 0 ? (
            <div className="rounded-lg border border-slate-200">
              <div className="grid grid-cols-[1.2fr_1.6fr_0.8fr_0.8fr_0.6fr] gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500">
                <span>stop_id</span><span>name</span><span>lat</span><span>lon</span><span>kind</span>
              </div>
              <VirtualizedList
                items={stops}
                height={320}
                itemHeight={38}
                className="bg-white"
                getKey={(s) => s.stop_id}
                renderItem={(stop) => (
                  <div className="grid h-full grid-cols-[1.2fr_1.6fr_0.8fr_0.8fr_0.6fr] gap-3 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                    <div className="truncate font-mono" title={stop.stop_id}>{stop.stop_id}</div>
                    <div className="truncate" title={stop.stop_name}>{stop.stop_name}</div>
                    <div className="font-mono">{stop.lat ?? "-"}</div>
                    <div className="font-mono">{stop.lon ?? "-"}</div>
                    <div>{stop.kind ?? "-"}</div>
                  </div>
                )}
              />
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
              条件に一致する stop はありません。
            </div>
          )}
        </div>
      )}

      {/* Timetable tab */}
      {detailTab === "timetable" && ttSummary && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">
            Timetable Summary ({formatCount(ttSummary.total)} total trips)
          </h3>
          {ttSummary.by_service.length > 0 ? (
            <div className="overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="py-2 pr-4 text-left font-semibold text-slate-500">service_id</th>
                    <th className="py-2 pr-4 text-right font-semibold text-slate-500">trips</th>
                    <th className="py-2 pr-4 text-right font-semibold text-slate-500">routes</th>
                    <th className="py-2 pr-4 text-left font-semibold text-slate-500">earliest</th>
                    <th className="py-2 text-left font-semibold text-slate-500">latest</th>
                  </tr>
                </thead>
                <tbody>
                  {ttSummary.by_service.map((s) => (
                    <tr key={s.service_id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-1.5 pr-4 font-mono">{s.service_id}</td>
                      <td className="py-1.5 pr-4 text-right">{formatCount(s.trip_count)}</td>
                      <td className="py-1.5 pr-4 text-right">{s.route_count}</td>
                      <td className="py-1.5 pr-4 font-mono">{s.earliest_departure ?? "-"}</td>
                      <td className="py-1.5 font-mono">{s.latest_arrival ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-500">時刻表データなし</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

import React from "react";

export function PublicDataExplorerPage() {
  const selectedOperator = usePublicDataExplorerStore(
    (s) => s.selectedOperator,
  );
  const summariesLoading = usePublicDataExplorerStore(
    (s) => s.summaries.loading,
  );
  const summariesError = usePublicDataExplorerStore(
    (s) => s.summaries.error,
  );
  const loadSummaries = usePublicDataExplorerStore((s) => s.loadSummaries);

  // Load summaries on mount (lightweight)
  useEffect(() => {
    void loadSummaries();
  }, [loadSummaries]);

  return (
    <TabWarmBoundary tab="explorer" title="Public Data Explorer を準備しています">
      <div className="mx-auto max-w-7xl space-y-6 p-6">
        {/* Header */}
        <div>
          <h1 className="text-xl font-bold text-slate-800">
            公開情報エクスプローラー
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            東急バス・都営バスの公開交通データを、事業者ごとに分離して確認できます。
            比較表示では概要統計のみを扱い、詳細データは選択した事業者に限定して読み込みます。
          </p>
        </div>

        {summariesError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {summariesError}
          </div>
        )}

        {/* 1段目: Operator Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <OperatorCard operatorId="tokyu" />
          <OperatorCard operatorId="toei" />
        </div>

        {/* 2段目: Map Overview (operator selected only) */}
        <MapOverviewPanel />

        {/* 3段目: Comparison (all mode) */}
        {selectedOperator === "all" && <ComparisonSection />}

        {/* 4段目: Detail (operator fixed) */}
        {selectedOperator !== "all" && (
          <DetailPanel operatorId={selectedOperator} />
        )}

        {/* No operator selected hint */}
        {selectedOperator === "all" && !summariesLoading && (
          <div className="rounded-xl border border-dashed border-border p-6 text-center">
            <p className="text-sm text-slate-500">
              詳細データを表示するには、東急バスまたは都営バスを選択してください。
            </p>
            <p className="text-xs text-slate-400 mt-1">
              比較表示では詳細一覧を読み込みません。
            </p>
          </div>
        )}
      </div>
    </TabWarmBoundary>
  );
}
