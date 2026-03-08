import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchJson } from "@/api/client";
import { ImportLogPanel } from "@/features/explorer/ImportLogPanel";
import { ImportProgressPanel } from "@/features/explorer/ImportProgressPanel";
import { TabWarmBoundary, VirtualizedList } from "@/features/common";
import { usePreparedPublicDiffItems } from "@/hooks/usePreparedPublicDiffItems";
import { useSortedAssignments } from "@/hooks/useSortedAssignments";
import { normalizeRouteCode } from "@/lib/route-code";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useImportJobStore } from "@/stores/import-job-store";
import { useUIStore } from "@/stores/ui-store";
import { measureAsyncStep } from "@/utils/perf/measureAsyncStep";
import { useMeasuredMemo } from "@/utils/perf/useMeasuredMemo";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";
import { useTabSwitchTrace } from "@/utils/perf/useTabSwitchTrace";

/**
 * ODPT Explorer Page
 *
 * Communicates with the Node/TS BFF at :3001 (proxied via Vite as /api/odpt/*):
 *   GET  /api/odpt/proxy?resource=...&query=...&dump=0|1&forceRefresh=0|1&ttlSec=...
 *   POST /api/odpt/introspect   { records: [...] }
 *   POST /api/odpt/export/normalized
 *   POST /api/odpt/export/operational
 *   POST /api/odpt/export/save
 */

// ── Types ─────────────────────────────────────────────────────────────────────

type ProxyMeta = {
  url: string;
  count: number;
  maybeTruncated: boolean;
  dump: boolean;
  cacheHit: boolean;
  cacheKey: string;
};

type ProxyResponse = {
  meta: ProxyMeta;
  data: unknown[];
};

type FieldStat = {
  path: string;
  types: Record<string, number>;
  present: number;
  presentRate: number;
};

type IntrospectResponse = {
  sampleCount: number;
  fields: FieldStat[];
};

type RouteTimetablePattern = {
  pattern_id: string;
  title?: string;
  note?: string;
  direction: "outbound" | "inbound" | "loop";
  stop_sequence: Array<{
    stop_id: string;
    stop_name: string;
  }>;
};

type RouteTimetableStopTime = {
  index: number;
  stop_id: string;
  stop_name: string;
  arrival?: string;
  departure?: string;
  time?: string;
};

type RouteTimetableTrip = {
  trip_id: string;
  pattern_id: string;
  service_id: string;
  direction: "outbound" | "inbound" | "loop";
  origin_stop_name?: string;
  destination_stop_name?: string;
  departure?: string;
  arrival?: string;
  estimated_distance_km?: number;
  is_partial: boolean;
  stop_times: RouteTimetableStopTime[];
};

type RouteTimetableService = {
  service_id: string;
  trip_count: number;
  first_departure?: string;
  last_arrival?: string;
};

type CatalogSnapshot = {
  snapshotKey: string;
  source: string;
  datasetRef: string;
  generatedAt?: string;
  refreshedAt?: string;
  meta?: {
    warnings?: string[];
    counts?: Record<string, number>;
    [key: string]: unknown;
  };
};

type CatalogRouteSummary = {
  route_id: string;
  route_code: string;
  route_label: string;
  trip_count: number;
  first_departure?: string;
  last_arrival?: string;
  services: RouteTimetableService[];
};

type CatalogRouteTimetable = CatalogRouteSummary & {
  patterns: RouteTimetablePattern[];
  trips: RouteTimetableTrip[];
  source?: string;
};

type CatalogSnapshotsResponse = {
  items: CatalogSnapshot[];
  total: number;
};

type CatalogRoutesResponse = {
  items: CatalogRouteSummary[];
  total: number;
  meta?: {
    snapshot?: CatalogSnapshot;
  };
};

type CatalogRouteResponse = {
  item: CatalogRouteTimetable;
  meta?: {
    snapshot?: CatalogSnapshot;
  };
};

type OperationalExportResponse = {
  meta?: unknown;
  routeTimetables?: Array<{
    busroute_id: string;
    route_code: string;
    route_label: string;
    trip_count: number;
    first_departure?: string;
    last_arrival?: string;
    patterns: RouteTimetablePattern[];
    services: RouteTimetableService[];
    trips: RouteTimetableTrip[];
  }>;
  [key: string]: unknown;
};

type Depot = {
  id: string;
  name: string;
};

type ExplorerOverview = {
  routeCount: number;
  routeWithDepotCount: number;
  routeWithStopsCount: number;
  routeWithTimetableCount: number;
  unresolvedDepotAssignmentCount: number;
  warningCount: number;
  imports: Record<string, Record<string, { warnings?: string[]; generatedAt?: string }>>;
};

type ExplorerDepotAssignment = {
  routeId: string;
  routeName: string;
  routeCode: string;
  routeFamilyCode?: string;
  routeVariantType?: string;
  familySortOrder?: number;
  startStop?: string;
  endStop?: string;
  source?: string;
  tripCount: number;
  stopCount: number;
  depotId?: string | null;
  depotName?: string | null;
  assignmentType?: string | null;
  confidence?: number | null;
  reason?: string;
  updatedAt?: string | null;
};

type PublicDiffSummary = {
  new_count: number;
  changed_count: number;
  deleted_candidate_count: number;
  conflict_count: number;
};

type PublicDiffItem = {
  id: string;
  entity_type: string;
  entity_key: string;
  display_name: string;
  change_type: string;
  suggested_action: string;
  conflict_flags?: Record<string, unknown>;
  field_diff?: Record<string, unknown>;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function prettyJson(x: unknown): string {
  try {
    return JSON.stringify(x, null, 2);
  } catch {
    return String(x);
  }
}

function typesSummary(types: Record<string, number>): string {
  return Object.entries(types)
    .sort((a, b) => b[1] - a[1])
    .map(([t, n]) => `${t}:${n}`)
    .join(", ");
}

const SERVICE_LABELS: Record<string, string> = {
  weekday: "平日",
  saturday: "土曜",
  holiday: "日祝",
  unknown: "不明",
  WEEKDAY: "平日",
  SAT: "土曜",
  SUN_HOL: "日祝",
};

function serviceLabel(serviceId: string): string {
  return SERVICE_LABELS[serviceId] ?? serviceId;
}

function routeOptionLabel(route: CatalogRouteSummary): string {
  const base = route.route_code ? `${route.route_code} · ${route.route_label}` : route.route_label;
  return `${base} (${route.trip_count} trips)`;
}

function snapshotLabel(snapshot: CatalogSnapshot): string {
  const source = snapshot.source.toUpperCase();
  return `${source} · ${snapshot.datasetRef}`;
}

function patternSummary(pattern: RouteTimetablePattern): string {
  const firstStop = pattern.stop_sequence[0]?.stop_name ?? "";
  const lastStop = pattern.stop_sequence[pattern.stop_sequence.length - 1]?.stop_name ?? "";
  const title = pattern.title?.trim();
  if (title) {
    return `${title} · ${pattern.direction}`;
  }
  return `${firstStop} -> ${lastStop} · ${pattern.direction}`;
}

const RESOURCE_OPTIONS = [
  "odpt:BusroutePattern",
  "odpt:BusstopPole",
  "odpt:BusTimetable",
  "odpt:BusstopPoleTimetable",
] as const;

// ── DB Visualization Types ────────────────────────────────────────────────────

type OperatorInfo = {
  operator_id: string;
  operator_name: string;
  source: string;
  db_path?: string;
  exists: boolean;
  tables?: Record<string, number>;
  metadata?: Record<string, string>;
};

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

type DbTimetableRow = {
  trip_id: string;
  route_id: string;
  service_id: string;
  direction?: string;
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  distance_km: number;
  allowed_vehicle_types: string[];
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

// ── DB Visualization Panel ───────────────────────────────────────────────────

function DbVisualizationPanel() {
  useRenderTrace("OdptExplorerPage.DbVisualizationPanel");
  const pageSize = 200;
  const [operators, setOperators] = useState<OperatorInfo[]>([]);
  const [selectedOp, setSelectedOp] = useState("");
  const [routes, setRoutes] = useState<DbRoute[]>([]);
  const [routesTotal, setRoutesTotal] = useState(0);
  const [routeQuery, setRouteQuery] = useState("");
  const [routeOffset, setRouteOffset] = useState(0);
  const [stops, setStops] = useState<DbStop[]>([]);
  const [stopsTotal, setStopsTotal] = useState(0);
  const [stopQuery, setStopQuery] = useState("");
  const [stopOffset, setStopOffset] = useState(0);
  const [ttSummary, setTtSummary] = useState<TimetableSummary | null>(null);
  const [ttRows, setTtRows] = useState<DbTimetableRow[]>([]);
  const [ttFilter, setTtFilter] = useState({ serviceId: "", routeId: "" });
  const [ttTotal, setTtTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOperators = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await fetchJson<{ items: OperatorInfo[] }>("/api/catalog/operators");
      setOperators(body.items ?? []);
      setSelectedOp((current) => current || body.items?.[0]?.operator_id || "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOperators();
  }, [loadOperators]);

  useEffect(() => {
    if (!selectedOp) return;
    setRoutes([]);
    setRoutesTotal(0);
    setStops([]);
    setStopsTotal(0);
    setTtSummary(null);
    setTtRows([]);
    setTtTotal(0);
    setRouteOffset(0);
    setStopOffset(0);
    setTtFilter({ serviceId: "", routeId: "" });
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [routesRes, stopsRes, summaryRes] = await Promise.all([
          fetchJson<{ items: DbRoute[]; total: number }>(
            `/api/catalog/operators/${selectedOp}/routes?limit=${pageSize}&offset=0`,
          ),
          fetchJson<{ items: DbStop[]; total: number }>(
            `/api/catalog/operators/${selectedOp}/stops?limit=${pageSize}&offset=0`,
          ),
          fetchJson<{ item: TimetableSummary }>(`/api/catalog/operators/${selectedOp}/timetable/summary`),
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
    })();
  }, [pageSize, selectedOp]);

  async function loadRoutesPage(nextOffset = routeOffset, nextQuery = routeQuery) {
    if (!selectedOp) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(nextOffset));
      if (nextQuery.trim()) params.set("q", nextQuery.trim());
      const body = await fetchJson<{ items: DbRoute[]; total: number }>(
        `/api/catalog/operators/${selectedOp}/routes?${params.toString()}`,
      );
      setRoutes(body.items ?? []);
      setRoutesTotal(body.total ?? 0);
      setRouteOffset(nextOffset);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadStopsPage(nextOffset = stopOffset, nextQuery = stopQuery) {
    if (!selectedOp) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(nextOffset));
      if (nextQuery.trim()) params.set("q", nextQuery.trim());
      const body = await fetchJson<{ items: DbStop[]; total: number }>(
        `/api/catalog/operators/${selectedOp}/stops?${params.toString()}`,
      );
      setStops(body.items ?? []);
      setStopsTotal(body.total ?? 0);
      setStopOffset(nextOffset);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadTimetableRows() {
    if (!selectedOp) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (ttFilter.serviceId) params.set("serviceId", ttFilter.serviceId);
      if (ttFilter.routeId) params.set("routeId", ttFilter.routeId);
      params.set("limit", "200");
      const body = await fetchJson<{ items: DbTimetableRow[]; total: number }>(
        `/api/catalog/operators/${selectedOp}/timetable?${params.toString()}`
      );
      setTtRows(body.items ?? []);
      setTtTotal(body.total ?? 0);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const selectedOpInfo = operators.find((o) => o.operator_id === selectedOp);

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Operator selector */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
        <div className="flex items-center gap-4">
          <h2 className="text-sm font-semibold text-slate-700">Operator</h2>
          <div className="flex gap-2">
            {operators.map((op) => (
              <button
                key={op.operator_id}
                onClick={() => setSelectedOp(op.operator_id)}
                className={`rounded-lg px-4 py-2 text-sm font-medium border transition-colors ${
                  selectedOp === op.operator_id
                    ? "border-primary-500 bg-primary-50 text-primary-700"
                    : "border-border bg-surface text-slate-600 hover:bg-slate-50"
                }`}
              >
                {op.operator_name}
                {op.exists ? (
                  <span className="ml-1.5 text-xs text-emerald-600">DB</span>
                ) : (
                  <span className="ml-1.5 text-xs text-slate-400">No DB</span>
                )}
              </button>
            ))}
          </div>
          <button
            onClick={loadOperators}
            disabled={loading}
            className="ml-auto rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        {selectedOpInfo && selectedOpInfo.exists && (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
            {Object.entries(selectedOpInfo.tables ?? {}).map(([table, count]) => (
              <div key={table} className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                <div className="text-lg font-bold text-slate-800">{count.toLocaleString()}</div>
                <div className="text-xs text-slate-500">{table}</div>
              </div>
            ))}
          </div>
        )}

        {selectedOpInfo && !selectedOpInfo.exists && (
          <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-700">
            DB file not found. Import data via the Master Data tab first.
          </div>
        )}
      </div>

      {/* Timetable Summary */}
      {ttSummary && ttSummary.by_service.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Timetable Summary ({ttSummary.total.toLocaleString()} total trips)
          </h2>
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200">
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
                    <td className="py-1.5 pr-4 text-right">{s.trip_count.toLocaleString()}</td>
                    <td className="py-1.5 pr-4 text-right">{s.route_count}</td>
                    <td className="py-1.5 pr-4 font-mono">{s.earliest_departure ?? "-"}</td>
                    <td className="py-1.5 font-mono">{s.latest_arrival ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Routes table */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
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
            disabled={loading || !selectedOp}
            className="rounded-lg border border-border bg-surface px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Search routes
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
              {Math.min(routeOffset + routes.length, routesTotal)} / {routesTotal.toLocaleString()}
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
        <h2 className="text-sm font-semibold text-slate-700">
          Routes ({routesTotal.toLocaleString()} total)
        </h2>
        {routes.length > 0 ? (
          <div className="rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1.4fr_1.4fr_0.7fr_0.6fr_0.6fr_0.8fr_0.8fr] gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500">
              <span>route_id</span>
              <span>name</span>
              <span>dir</span>
              <span className="text-right">stops</span>
              <span className="text-right">trips</span>
              <span>first</span>
              <span>last</span>
            </div>
            <VirtualizedList
              items={routes}
              height={400}
              itemHeight={40}
              className="bg-white"
              getKey={(route) => route.route_id}
              renderItem={(route) => (
                <div className="grid h-full grid-cols-[1.4fr_1.4fr_0.7fr_0.6fr_0.6fr_0.8fr_0.8fr] gap-3 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                  <div className="truncate font-mono" title={route.route_id}>
                    {route.route_code || route.route_id}
                  </div>
                  <div className="truncate" title={route.route_name}>
                    {route.route_name}
                  </div>
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

      {/* Stops table */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
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
            disabled={loading || !selectedOp}
            className="rounded-lg border border-border bg-surface px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Search stops
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
              {Math.min(stopOffset + stops.length, stopsTotal)} / {stopsTotal.toLocaleString()}
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
        <h2 className="text-sm font-semibold text-slate-700">
          Stops ({stopsTotal.toLocaleString()} total)
        </h2>
        {stops.length > 0 ? (
          <div className="rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1.2fr_1.6fr_0.8fr_0.8fr_0.6fr] gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500">
              <span>stop_id</span>
              <span>name</span>
              <span>lat</span>
              <span>lon</span>
              <span>kind</span>
            </div>
            <VirtualizedList
              items={stops}
              height={320}
              itemHeight={38}
              className="bg-white"
              getKey={(stop) => stop.stop_id}
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

      {/* Timetable rows query */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">Timetable Rows (Dispatch-Ready Trips)</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-500">service_id</label>
            <input
              type="text"
              value={ttFilter.serviceId}
              onChange={(e) => setTtFilter((f) => ({ ...f, serviceId: e.target.value }))}
              placeholder="e.g. WEEKDAY"
              className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm w-40"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-500">route_id</label>
            <input
              type="text"
              value={ttFilter.routeId}
              onChange={(e) => setTtFilter((f) => ({ ...f, routeId: e.target.value }))}
              placeholder="filter by route"
              className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm w-48"
            />
          </div>
          <button
            onClick={loadTimetableRows}
            disabled={loading || !selectedOp}
            className="rounded-lg bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {loading ? "Loading..." : "Query"}
          </button>
          {ttTotal > 0 && (
            <span className="text-xs text-slate-500">
              Showing {ttRows.length} of {ttTotal.toLocaleString()} rows
            </span>
          )}
        </div>
        {ttRows.length > 0 && (
          <div className="rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1fr_1fr_0.7fr_0.9fr_0.9fr_0.6fr_0.6fr_0.5fr_1fr] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-500">
              <span>trip_id</span>
              <span>route_id</span>
              <span>service</span>
              <span>origin</span>
              <span>dest</span>
              <span>dep</span>
              <span>arr</span>
              <span className="text-right">km</span>
              <span>types</span>
            </div>
            <VirtualizedList
              items={ttRows}
              height={500}
              itemHeight={36}
              className="bg-white"
              getKey={(row, index) => `${row.trip_id}-${index}`}
              renderItem={(row) => (
                <div className="grid h-full grid-cols-[1fr_1fr_0.7fr_0.9fr_0.9fr_0.6fr_0.6fr_0.5fr_1fr] gap-2 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                  <div className="truncate font-mono" title={row.trip_id}>{row.trip_id}</div>
                  <div className="truncate font-mono" title={row.route_id}>{row.route_id}</div>
                  <div>{row.service_id}</div>
                  <div className="truncate" title={row.origin}>{row.origin}</div>
                  <div className="truncate" title={row.destination}>{row.destination}</div>
                  <div className="font-mono">{row.departure}</div>
                  <div className="font-mono">{row.arrival}</div>
                  <div className="text-right">{row.distance_km?.toFixed(1) ?? "-"}</div>
                  <div className="truncate font-mono text-[11px]">
                    {Array.isArray(row.allowed_vehicle_types)
                      ? row.allowed_vehicle_types.join(",")
                      : "-"}
                  </div>
                </div>
              )}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OdptExplorerPage() {
  useRenderTrace("OdptExplorerPage");
  const { scenarioId: routeScenarioId } = useParams<{ scenarioId: string }>();
  const [tabMode, setTabMode] = useState<"db" | "api">("db");
  useTabSwitchTrace("explorer-tab", tabMode);
  const storeScenarioId = useUIStore((s) => s.activeScenarioId);
  const setSelectedDepotId = useUIStore((s) => s.setSelectedDepotId);
  const selectMasterDepot = useMasterUiStore((s) => s.selectDepot);
  const startJob = useImportJobStore((state) => state.startJob);
  const updateStage = useImportJobStore((state) => state.updateStage);
  const appendLog = useImportJobStore((state) => state.appendLog);
  const completeJob = useImportJobStore((state) => state.completeJob);
  const failJob = useImportJobStore((state) => state.failJob);
  const activeScenarioId = routeScenarioId ?? storeScenarioId;
  const [selectedScenarioOperator, setSelectedScenarioOperator] = useState<"tokyu" | "toei">("tokyu");
  const [latestDiffSessionId, setLatestDiffSessionId] = useState("");
  const [latestDiffSummary, setLatestDiffSummary] = useState<PublicDiffSummary | null>(null);
  const [latestDiffItems, setLatestDiffItems] = useState<PublicDiffItem[]>([]);
  const preparedDiffItems = usePreparedPublicDiffItems(latestDiffItems);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [depots, setDepots] = useState<Depot[]>([]);
  const [explorerOverview, setExplorerOverview] = useState<ExplorerOverview | null>(null);
  const [assignmentRows, setAssignmentRows] = useState<ExplorerDepotAssignment[]>([]);
  const [assignmentSavingRouteId, setAssignmentSavingRouteId] = useState("");
  const [showUnresolvedOnly, setShowUnresolvedOnly] = useState(false);
  const [resource, setResource] = useState<string>(RESOURCE_OPTIONS[0]);
  const [dump, setDump] = useState(false);
  const [query, setQuery] = useState("odpt:operator=odpt.Operator:TokyuBus");
  const [forceRefresh, setForceRefresh] = useState(false);
  const [ttlSec, setTtlSec] = useState(3600);
  const [includeStopTimetables, setIncludeStopTimetables] = useState(false);

  const [loading, setLoading] = useState(false);
  const [proxyRes, setProxyRes] = useState<ProxyResponse | null>(null);

  const [introspecting, setIntrospecting] = useState(false);
  const [introRes, setIntroRes] = useState<IntrospectResponse | null>(null);

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogRefreshing, setCatalogRefreshing] = useState<"" | "odpt" | "gtfs">("");
  const [catalogSnapshots, setCatalogSnapshots] = useState<CatalogSnapshot[]>([]);
  const [catalogRoutes, setCatalogRoutes] = useState<CatalogRouteSummary[]>([]);
  const [catalogRoute, setCatalogRoute] = useState<CatalogRouteTimetable | null>(null);
  const [selectedSnapshotKey, setSelectedSnapshotKey] = useState("");
  const [selectedRouteId, setSelectedRouteId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("all");
  const [selectedCatalogTripId, setSelectedCatalogTripId] = useState("");

  const [exporting, setExporting] = useState(false);
  const [exportRes, setExportRes] = useState<OperationalExportResponse | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveRes, setSaveRes] = useState<{
    savedTo: string;
    normalizedSavedTo?: string;
    routeTimetablesSavedTo?: string;
    meta: unknown;
  } | null>(null);
  const [odptBackendHealthy, setOdptBackendHealthy] = useState<boolean | null>(null);
  const sortedAssignmentRows = useSortedAssignments(assignmentRows);

  const [error, setError] = useState<string | null>(null);

  // Reset downstream state when controls change
  useEffect(() => {
    setIntroRes(null);
    setExportRes(null);
    setSaveRes(null);
    setError(null);
  }, [resource, dump, query, forceRefresh, ttlSec, includeStopTimetables]);

  const exportRouteTimetables = useMemo(
    () => exportRes?.routeTimetables ?? [],
    [exportRes],
  );

  useEffect(() => {
    if (!catalogSnapshots.length) {
      setSelectedSnapshotKey("");
      setCatalogRoutes([]);
      setCatalogRoute(null);
      setSelectedRouteId("");
      setSelectedServiceId("all");
      return;
    }
    setSelectedSnapshotKey((current) =>
      catalogSnapshots.some((snapshot) => snapshot.snapshotKey === current)
        ? current
        : catalogSnapshots[0].snapshotKey,
    );
  }, [catalogSnapshots]);

  useEffect(() => {
    setCatalogRoute(null);
    setCatalogRoutes([]);
    setSelectedRouteId("");
    setSelectedServiceId("all");
  }, [selectedSnapshotKey]);

  useEffect(() => {
    setSelectedServiceId("all");
  }, [selectedRouteId]);

  useEffect(() => {
    let cancelled = false;

    async function probeOdptBackend() {
      try {
        await fetchJson<{ status: string }>("/api/odpt/health");
        if (!cancelled) {
          setOdptBackendHealthy(true);
        }
      } catch {
        if (!cancelled) {
          setOdptBackendHealthy(false);
        }
      }
    }

    void probeOdptBackend();
    return () => {
      cancelled = true;
    };
  }, []);

  function buildExportPayload() {
    return {
      dump,
      forceRefresh,
      ttlSec,
      includeStopTimetables,
    };
  }

  const loadScenarioExplorerData = useCallback(async () => {
    if (!activeScenarioId) {
      setDepots([]);
      setExplorerOverview(null);
      setAssignmentRows([]);
      return;
    }
    try {
      const operator = selectedScenarioOperator;
      const [depotsRes, overviewRes, assignmentsRes] = await Promise.all([
        fetchJson<{ items: Depot[] }>(`/api/scenarios/${activeScenarioId}/depots`),
        fetchJson<{ item: ExplorerOverview }>(
          `/api/scenarios/${activeScenarioId}/explorer/overview?operator=${operator}`,
        ),
        fetchJson<{ items: ExplorerDepotAssignment[] }>(
          `/api/scenarios/${activeScenarioId}/explorer/depot-assignments?operator=${operator}&unresolvedOnly=${showUnresolvedOnly ? "true" : "false"}`,
        ),
      ]);
      setDepots(depotsRes.items ?? []);
      setExplorerOverview(overviewRes.item ?? null);
      setAssignmentRows(assignmentsRes.items ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [activeScenarioId, selectedScenarioOperator, showUnresolvedOnly]);

  // ── Actions ────────────────────────────────────────────────────────────────

  async function loadCatalogSnapshots() {
    setCatalogLoading(true);
    try {
      const body = await fetchJson<CatalogSnapshotsResponse>("/api/catalog/snapshots");
      setCatalogSnapshots(body.items ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCatalogLoading(false);
    }
  }

  async function loadCatalogRoutes(snapshotKey: string) {
    if (!snapshotKey) {
      setCatalogRoutes([]);
      return;
    }
    setCatalogLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("snapshotKey", snapshotKey);
      const body = await fetchJson<CatalogRoutesResponse>(
        `/api/catalog/routes?${params.toString()}`,
      );
      setCatalogRoutes(body.items ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCatalogLoading(false);
    }
  }

  async function loadCatalogRoute(snapshotKey: string, routeId: string) {
    if (!snapshotKey || !routeId) {
      setCatalogRoute(null);
      return;
    }
    setCatalogLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("snapshotKey", snapshotKey);
      const body = await fetchJson<CatalogRouteResponse>(
        `/api/catalog/routes/${encodeURIComponent(routeId)}?${params.toString()}`,
      );
      setCatalogRoute(body.item ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCatalogLoading(false);
    }
  }

  async function refreshCatalog(source: "odpt" | "gtfs") {
    const jobId = `catalog-refresh-${source}`;
    startJob({
      jobId,
      source,
      label: `Catalog refresh (${source.toUpperCase()})`,
      stages: [
        { id: "snapshot", label: "Build snapshot", weight: 80 },
        { id: "ui", label: "Refresh explorer cache", weight: 20 },
      ],
    });
    setCatalogRefreshing(source);
    setError(null);
    try {
      updateStage(jobId, "snapshot", { status: "running", progress: 20 });
      if (source === "odpt") {
        const body = await measureAsyncStep("explorer:refresh-catalog-odpt", () =>
          fetchJson<{ item?: CatalogSnapshot }>("/api/catalog/refresh/odpt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              operator: "odpt.Operator:TokyuBus",
              dump: true,
              forceRefresh: true,
              ttlSec,
            }),
          }),
        );
        await loadCatalogSnapshots();
        if (body.item?.snapshotKey) {
          setSelectedSnapshotKey(body.item.snapshotKey);
        }
      } else {
        const body = await measureAsyncStep("explorer:refresh-catalog-gtfs", () =>
          fetchJson<{ item?: CatalogSnapshot }>("/api/catalog/refresh/gtfs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              feedPath: "GTFS/ToeiBus-GTFS",
            }),
          }),
        );
        await loadCatalogSnapshots();
        if (body.item?.snapshotKey) {
          setSelectedSnapshotKey(body.item.snapshotKey);
        }
      }
      updateStage(jobId, "snapshot", { status: "success", progress: 100 });
      updateStage(jobId, "ui", { status: "success", progress: 100 });
      completeJob(jobId, "Catalog refresh completed");
    } catch (e: unknown) {
      failJob(jobId, e instanceof Error ? e.message : String(e));
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCatalogRefreshing("");
    }
  }

  async function importScenarioSource(source: "odpt" | "gtfs") {
    if (!activeScenarioId) {
      setError("先に scenario を選択してください。");
      return;
    }
    const jobId = `scenario-sync-${source}`;
    startJob({
      jobId,
      source,
      label: `Public data sync (${source.toUpperCase()})`,
      stages: [
        { id: "fetch", label: "Fetch public snapshot", weight: 35 },
        { id: "normalize", label: "Normalize snapshot", weight: 20 },
        { id: "diff", label: "Build diff session", weight: 30 },
        { id: "refresh", label: "Refresh explorer state", weight: 15 },
      ],
    });
    setAssignmentSavingRouteId(`import:${source}`);
    setError(null);
    setSyncMessage(null);
    try {
      updateStage(jobId, "fetch", { status: "running", progress: 10 });
      appendLog(jobId, { level: "info", message: `Fetching ${source} public data snapshot` });
      const fetchRes = await measureAsyncStep(`explorer:public-fetch-${source}`, () =>
        fetchJson<{
          id: string;
          snapshot_id?: string;
        }>(`/api/scenarios/${activeScenarioId}/public-data/fetch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_type: source,
            operator_id:
              source === "odpt" ? "odpt.Operator:TokyuBus" : "GTFS/ToeiBus-GTFS",
            fetch_mode: "incremental",
            resource_targets:
              source === "odpt"
                ? ["odpt:BusroutePattern", "odpt:BusstopPole", "odpt:BusTimetable"]
                : ["routes", "stops", "trips"],
          }),
        }),
      );
      updateStage(jobId, "fetch", { status: "success", progress: 100 });
      const rawSnapshotId = fetchRes.snapshot_id ?? fetchRes.id;
      updateStage(jobId, "normalize", { status: "running", progress: 20 });
      appendLog(jobId, { level: "info", message: `Normalizing snapshot ${rawSnapshotId}` });
      const normalizeRes = await measureAsyncStep(`explorer:public-normalize-${source}`, () =>
        fetchJson<{ normalized_snapshot_id: string }>(
          `/api/scenarios/${activeScenarioId}/public-data/normalize`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_snapshot_id: rawSnapshotId }),
          },
        ),
      );
      updateStage(jobId, "normalize", { status: "success", progress: 100 });
      updateStage(jobId, "diff", { status: "running", progress: 20 });
      const diffRes = await measureAsyncStep(`explorer:public-diff-${source}`, () =>
        fetchJson<{
          diff_session_id: string;
          summary: PublicDiffSummary;
        }>(`/api/scenarios/${activeScenarioId}/public-data/diff`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            normalized_snapshot_id: normalizeRes.normalized_snapshot_id,
            compare_mode: "new_and_update",
            compare_targets: ["routes", "stops", "trips", "stop_times", "service_calendars"],
          }),
        }),
      );
      const diffItemsRes = await fetchJson<{ items: PublicDiffItem[] }>(
        `/api/scenarios/${activeScenarioId}/public-data/diff/${diffRes.diff_session_id}/items?limit=50`,
      );
      updateStage(jobId, "diff", {
        status: "success",
        progress: 100,
        currentCount: diffItemsRes.items?.length ?? 0,
        totalCount: diffRes.summary.changed_count + diffRes.summary.new_count,
      });
      setLatestDiffSessionId(diffRes.diff_session_id);
      setLatestDiffSummary(diffRes.summary);
      setLatestDiffItems(diffItemsRes.items ?? []);
      setSyncMessage("差分を取得しました。内容を確認してから反映できます。");
      updateStage(jobId, "refresh", { status: "running", progress: 20 });
      await loadScenarioExplorerData();
      await loadCatalogSnapshots();
      updateStage(jobId, "refresh", { status: "success", progress: 100 });
      completeJob(jobId, "差分取得が完了しました。");
    } catch (e: unknown) {
      failJob(jobId, e instanceof Error ? e.message : String(e));
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssignmentSavingRouteId("");
    }
  }

  async function applyLatestDiff() {
    if (!activeScenarioId || !latestDiffSessionId) {
      return;
    }
    const jobId = "scenario-sync-apply";
    startJob({
      jobId,
      source: "system",
      label: "Apply diff session",
      stages: [
        { id: "sync", label: "Sync scenario", weight: 75 },
        { id: "refresh", label: "Refresh explorer view", weight: 25 },
      ],
    });
    setAssignmentSavingRouteId("sync:apply");
    setError(null);
    setSyncMessage(null);
    try {
      updateStage(jobId, "sync", { status: "running", progress: 20 });
      const syncRes = await measureAsyncStep("explorer:apply-diff", () =>
        fetchJson<{
          inserted_count: number;
          updated_count: number;
          skipped_count: number;
          conflict_count: number;
        }>(`/api/scenarios/${activeScenarioId}/public-data/sync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            diff_session_id: latestDiffSessionId,
            sync_mode: "insert_and_update",
          }),
        }),
      );
      updateStage(jobId, "sync", {
        status: "success",
        progress: 100,
        currentCount: syncRes.inserted_count + syncRes.updated_count,
        totalCount:
          syncRes.inserted_count +
          syncRes.updated_count +
          syncRes.skipped_count +
          syncRes.conflict_count,
      });
      setSyncMessage(
        `反映完了: +${syncRes.inserted_count} / 更新 ${syncRes.updated_count} / スキップ ${syncRes.skipped_count} / conflict ${syncRes.conflict_count}`,
      );
      updateStage(jobId, "refresh", { status: "running", progress: 20 });
      await loadScenarioExplorerData();
      updateStage(jobId, "refresh", { status: "success", progress: 100 });
      completeJob(jobId, "差分反映が完了しました。");
    } catch (e: unknown) {
      failJob(jobId, e instanceof Error ? e.message : String(e));
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssignmentSavingRouteId("");
    }
  }

  async function updateDepotAssignment(routeId: string, depotId: string) {
    if (!activeScenarioId) {
      return;
    }
    setAssignmentSavingRouteId(routeId);
    setError(null);
    try {
      await fetchJson(`/api/scenarios/${activeScenarioId}/explorer/depot-assignments/${encodeURIComponent(routeId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          depotId: depotId || null,
          assignmentType: depotId ? "manual_override" : "manual_clear",
          confidence: depotId ? 1.0 : 0.0,
          reason: depotId ? "Assigned from Public Data Collection Explorer." : "Cleared from Public Data Collection Explorer.",
        }),
      });
      setSelectedDepotId(depotId || null);
      selectMasterDepot(depotId || null);
      await loadScenarioExplorerData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssignmentSavingRouteId("");
    }
  }

  async function runProxy() {
    setLoading(true);
    setError(null);
    setProxyRes(null);
    setIntroRes(null);
    try {
      const params = new URLSearchParams();
      params.set("resource", resource);
      params.set("query", query.trim());
      params.set("dump", dump ? "1" : "0");
      params.set("forceRefresh", forceRefresh ? "1" : "0");
      params.set("ttlSec", String(ttlSec));
      const body = await fetchJson<ProxyResponse>(
        `/api/odpt/proxy?${params.toString()}`,
      );
      setProxyRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runIntrospect() {
    if (!proxyRes?.data?.length) {
      setError("先に Proxy Fetch を実行してください。");
      return;
    }
    setIntrospecting(true);
    setError(null);
    setIntroRes(null);
    try {
      const body = await fetchJson<IntrospectResponse>("/api/odpt/introspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records: proxyRes.data }),
      });
      setIntroRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIntrospecting(false);
    }
  }

  async function runExportOperational() {
    setExporting(true);
    setError(null);
    setExportRes(null);
    try {
      const body = await fetchJson<OperationalExportResponse>(
        "/api/odpt/export/operational",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildExportPayload()),
        },
      );
      setExportRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  async function runSaveToDisk() {
    setSaving(true);
    setError(null);
    setSaveRes(null);
    try {
      const body = await fetchJson<{
        savedTo?: string;
        normalizedSavedTo?: string;
        routeTimetablesSavedTo?: string;
        meta?: unknown;
      }>("/api/odpt/export/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildExportPayload()),
      });
      setSaveRes({
        savedTo: body.savedTo ?? "",
        normalizedSavedTo: body.normalizedSavedTo,
        routeTimetablesSavedTo: body.routeTimetablesSavedTo,
        meta: body.meta,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  // ── Derived ────────────────────────────────────────────────────────────────

  const preview = useMemo(() => {
    if (!proxyRes?.data) return "";
    return prettyJson(proxyRes.data.slice(0, 20));
  }, [proxyRes]);

  useEffect(() => {
    loadCatalogSnapshots();
  }, []);

  useEffect(() => {
    void loadScenarioExplorerData();
  }, [loadScenarioExplorerData]);

  useEffect(() => {
    setLatestDiffSessionId("");
    setLatestDiffSummary(null);
    setLatestDiffItems([]);
    setSyncMessage(null);
  }, [selectedScenarioOperator, activeScenarioId]);

  useEffect(() => {
    if (!selectedSnapshotKey) {
      return;
    }
    loadCatalogRoutes(selectedSnapshotKey);
  }, [selectedSnapshotKey]);

  useEffect(() => {
    if (!catalogRoutes.length) {
      setSelectedRouteId("");
      return;
    }
    setSelectedRouteId((current) =>
      catalogRoutes.some((route) => route.route_id === current)
        ? current
        : catalogRoutes[0].route_id,
    );
  }, [catalogRoutes]);

  useEffect(() => {
    if (!selectedSnapshotKey || !selectedRouteId) {
      setCatalogRoute(null);
      return;
    }
    loadCatalogRoute(selectedSnapshotKey, selectedRouteId);
  }, [selectedSnapshotKey, selectedRouteId]);

  const filteredTrips = useMeasuredMemo("selector:catalog-filtered-trips", () => {
    if (!catalogRoute) {
      return [];
    }
    if (selectedServiceId === "all") {
      return catalogRoute.trips;
    }
    return catalogRoute.trips.filter((trip) => trip.service_id === selectedServiceId);
  }, [catalogRoute, selectedServiceId]);

  useEffect(() => {
    if (!filteredTrips.length) {
      setSelectedCatalogTripId("");
      return;
    }
    setSelectedCatalogTripId((current) =>
      filteredTrips.some((trip) => trip.trip_id === current)
        ? current
        : filteredTrips[0].trip_id,
    );
  }, [filteredTrips]);

  const selectedCatalogTrip = useMemo(
    () => filteredTrips.find((trip) => trip.trip_id === selectedCatalogTripId) ?? null,
    [filteredTrips, selectedCatalogTripId],
  );

  const exportPreview = useMeasuredMemo("selector:export-preview", () => {
    if (!exportRes) {
      return "";
    }
    if (!exportRouteTimetables.length) {
      return prettyJson(exportRes);
    }

    const routePreview = exportRouteTimetables.slice(0, 2).map((route) => ({
      busroute_id: route.busroute_id,
      route_code: route.route_code,
      route_label: route.route_label,
      trip_count: route.trip_count,
      first_departure: route.first_departure,
      last_arrival: route.last_arrival,
      patterns: route.patterns.map((pattern) => ({
        pattern_id: pattern.pattern_id,
        direction: pattern.direction,
        stop_count: pattern.stop_sequence.length,
      })),
      services: route.services,
      sample_trip: route.trips[0],
    }));

    const rest = { ...exportRes };
    delete rest.routeTimetables;
    return prettyJson({
      ...rest,
      routeTimetables: {
        total: exportRouteTimetables.length,
        sample: routePreview,
      },
    });
  }, [exportRes, exportRouteTimetables]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <TabWarmBoundary tab="explorer" title="Public Data Explorer を準備しています">
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">Public Data Explorer</h1>
          <p className="mt-1 text-sm text-slate-500">
            scenario 配下の公開情報同期、差分確認、所属営業所補正を集約します。
          </p>
        </div>
        <Link
          to={activeScenarioId ? `/scenarios/${activeScenarioId}/planning` : "/scenarios"}
          className="text-sm text-primary-600 hover:underline"
        >
          &larr; Back to Planning
        </Link>
      </div>

      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Active scenario
            </p>
            <p className="text-sm font-medium text-slate-700">
              {activeScenarioId ?? "No scenario selected"}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedScenarioOperator("tokyu")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                selectedScenarioOperator === "tokyu"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              Tokyu / ODPT
            </button>
            <button
              onClick={() => setSelectedScenarioOperator("toei")}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                selectedScenarioOperator === "toei"
                  ? "bg-sky-100 text-sky-700"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              Toei / GTFS
            </button>
            <button
              onClick={() =>
                importScenarioSource(selectedScenarioOperator === "tokyu" ? "odpt" : "gtfs")
              }
              disabled={!activeScenarioId || assignmentSavingRouteId !== ""}
              className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 disabled:opacity-50"
            >
              {assignmentSavingRouteId.startsWith("import:")
                ? "同期中..."
                : "公開情報から同期更新"}
            </button>
            <button
              onClick={applyLatestDiff}
              disabled={!activeScenarioId || !latestDiffSessionId || assignmentSavingRouteId !== ""}
              className="rounded-lg border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-700 disabled:opacity-50"
            >
              {assignmentSavingRouteId === "sync:apply" ? "反映中..." : "差分を反映"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span>現在ソース: {selectedScenarioOperator === "tokyu" ? "Tokyu / ODPT" : "Toei / GTFS"}</span>
          <button
            onClick={() =>
              importScenarioSource(selectedScenarioOperator === "tokyu" ? "odpt" : "gtfs")
            }
            disabled={!activeScenarioId || assignmentSavingRouteId !== ""}
            className="rounded border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 disabled:opacity-50"
          >
            差分確認を更新
          </button>
          {syncMessage && <span className="text-emerald-700">{syncMessage}</span>}
        </div>

        {odptBackendHealthy === false && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            ODPT Explorer backend (`localhost:3001`) に接続できません。Scenario 同期は FastAPI 側で続行できますが、
            Proxy Fetch / Introspect / Export Operational / Save to Disk は無効になります。
          </div>
        )}

        {explorerOverview && (
          <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            {[
              ["Routes", explorerOverview.routeCount],
              ["Assigned", explorerOverview.routeWithDepotCount],
              ["Stops linked", explorerOverview.routeWithStopsCount],
              ["Timetable linked", explorerOverview.routeWithTimetableCount],
              ["Unresolved", explorerOverview.unresolvedDepotAssignmentCount],
              ["Warnings", explorerOverview.warningCount],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-xs text-slate-500">{label}</div>
                <div className="mt-1 text-lg font-semibold text-slate-800">{value}</div>
              </div>
            ))}
          </div>
        )}

        {latestDiffSummary && (
          <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-700">差分サマリー</p>
                <p className="text-xs text-slate-500">
                  反映前に entity 単位の差分を確認できます。
                </p>
              </div>
              <span className="text-xs text-slate-500">session: {latestDiffSessionId}</span>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              {[
                ["新規", latestDiffSummary.new_count],
                ["変更", latestDiffSummary.changed_count],
                ["削除候補", latestDiffSummary.deleted_candidate_count],
                ["Conflict", latestDiffSummary.conflict_count],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded border border-amber-200 bg-white px-3 py-2">
                  <div className="text-[11px] text-slate-500">{label}</div>
                  <div className="text-lg font-semibold text-slate-800">{value}</div>
                </div>
              ))}
            </div>
            <div className="overflow-auto rounded border border-amber-200 bg-white">
              <table className="w-full text-left text-xs">
                <thead className="bg-amber-50">
                  <tr>
                    <th className="px-3 py-2 font-medium text-slate-500">Entity</th>
                    <th className="px-3 py-2 font-medium text-slate-500">Name</th>
                    <th className="px-3 py-2 font-medium text-slate-500">Type</th>
                    <th className="px-3 py-2 font-medium text-slate-500">Action</th>
                    <th className="px-3 py-2 font-medium text-slate-500">Changed fields</th>
                  </tr>
                </thead>
                <tbody>
                  {preparedDiffItems.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-3 text-slate-500">
                        差分はありません。
                      </td>
                    </tr>
                  ) : (
                    preparedDiffItems.map((item) => (
                      <tr key={item.id} className="border-t border-slate-100">
                        <td className="px-3 py-2 text-slate-600">{item.entity_type}</td>
                        <td className="px-3 py-2 text-slate-700">{item.display_name}</td>
                        <td className="px-3 py-2 text-slate-600">{item.change_type}</td>
                        <td className="px-3 py-2 text-slate-600">{item.suggested_action}</td>
                        <td className="px-3 py-2 text-slate-500">
                          {item.changedFieldCount > 0 ? item.changedFieldPreview : "-"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-700">Depot assignments</p>
            <p className="text-xs text-slate-500">
              所属営業所の確定・補正はここで行います。
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={showUnresolvedOnly}
              onChange={(e) => setShowUnresolvedOnly(e.target.checked)}
            />
            unresolved only
          </label>
        </div>

        {!activeScenarioId ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            scenario を開いてから利用してください。
          </div>
        ) : sortedAssignmentRows.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
            表示対象の route がありません。
          </div>
        ) : (
          <div className="rounded-lg border border-border">
            <div className="grid grid-cols-[1.8fr_0.5fr_0.5fr_1fr_1fr_1.2fr] gap-3 border-b border-border bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
              <span>Route</span>
              <span>Stops</span>
              <span>Trips</span>
              <span>Current depot</span>
              <span>Assign</span>
              <span>Reason</span>
            </div>
            <VirtualizedList
              items={sortedAssignmentRows}
              height={420}
              itemHeight={72}
              className="bg-white"
              getKey={(row) => row.routeId}
              renderItem={(row) => (
                <div className="grid h-full grid-cols-[1.8fr_0.5fr_0.5fr_1fr_1fr_1.2fr] gap-3 border-b border-slate-100 px-3 py-2 text-xs">
                  <div>
                    <div className="font-medium text-slate-700">
                      {normalizeRouteCode(row.routeCode) || row.routeName}
                    </div>
                    <div className="text-slate-500">
                      {row.routeName}{" "}
                      {row.startStop || row.endStop
                        ? `(${row.startStop ?? "-"} -> ${row.endStop ?? "-"})`
                        : ""}
                    </div>
                  </div>
                  <div className="text-slate-600">{row.stopCount}</div>
                  <div className="text-slate-600">{row.tripCount}</div>
                  <div className="text-slate-600">
                    {row.depotName ?? <span className="text-amber-700">unassigned</span>}
                  </div>
                  <div>
                    <select
                      value={row.depotId ?? ""}
                      disabled={assignmentSavingRouteId === row.routeId}
                      onChange={(e) => updateDepotAssignment(row.routeId, e.target.value)}
                      className="w-full rounded border border-border bg-white px-2 py-1"
                    >
                      <option value="">未所属</option>
                      {depots.map((depot) => (
                        <option key={depot.id} value={depot.id}>
                          {depot.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="text-slate-500">{row.reason || row.assignmentType || "-"}</div>
                </div>
              )}
            />
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        <button
          onClick={() => setTabMode("db")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tabMode === "db"
              ? "border-primary-600 text-primary-700"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          DB Visualization
        </button>
        <button
          onClick={() => setTabMode("api")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tabMode === "api"
              ? "border-primary-600 text-primary-700"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          API Debug
        </button>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ImportProgressPanel />
        <ImportLogPanel />
      </div>

      {/* DB Visualization tab */}
      <section className={tabMode === "db" ? "block" : "hidden"}>
        <DbVisualizationPanel />
      </section>

      {/* API Debug tab (original explorer content) */}
      <section className={tabMode === "api" ? "block" : "hidden"}>
      <>
      {/* Controls card */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-6">
          {/* Resource selector */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Resource
            </label>
            <select
              value={resource}
              onChange={(e) => setResource(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {RESOURCE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          {/* Dump mode */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Dump mode
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={dump}
                onChange={(e) => setDump(e.target.checked)}
                className="accent-primary-500"
              />
              <span>.json（全量側）</span>
            </label>
            <p className="text-xs text-slate-400">
              1000 件上限に当たるなら ON
            </p>
          </div>

          {/* Cache controls */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Cache
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={forceRefresh}
                onChange={(e) => setForceRefresh(e.target.checked)}
                className="accent-primary-500"
              />
              <span>Force refresh</span>
            </label>
            <input
              type="number"
              value={ttlSec}
              min={60}
              step={60}
              onChange={(e) => setTtlSec(Number(e.target.value) || 60)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <p className="text-xs text-slate-400">
              TTL 秒。例: 3600 = 1 時間
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Optional data
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={includeStopTimetables}
                onChange={(e) => setIncludeStopTimetables(e.target.checked)}
                className="accent-primary-500"
              />
              <span>BusstopPoleTimetable を含める</span>
            </label>
            <p className="text-xs text-slate-400">
              OFF 推奨。ON は取得件数が多く、時間がかかることがあります。
            </p>
          </div>

          {/* Proxy / Introspect actions */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Actions
            </label>
            <button
              onClick={runProxy}
              disabled={loading || odptBackendHealthy === false}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              {loading ? "Fetching…" : "Proxy Fetch"}
            </button>
            <button
              onClick={runIntrospect}
              disabled={introspecting || !proxyRes?.data?.length || odptBackendHealthy === false}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              {introspecting ? "Introspecting…" : "Introspect"}
            </button>
          </div>

          {/* Export operational + Save to disk */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Master-course 用
            </label>
            <button
              onClick={runExportOperational}
              disabled={exporting || odptBackendHealthy === false}
              className="w-full rounded-lg border border-primary-300 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-40 transition-colors"
            >
              {exporting ? "Exporting…" : "Export Operational"}
            </button>
            <button
              onClick={runSaveToDisk}
              disabled={saving || odptBackendHealthy === false}
              className="w-full rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40 transition-colors"
            >
              {saving ? "Saving…" : "Save to Disk"}
            </button>
            <p className="text-xs text-slate-400">
              Stop / Pattern / Trip / Index に加えて、路線別の全便時刻も返す
              <br />
              Save to Disk は normalized / operational / route_timetables を書き込む
            </p>
          </div>
        </div>

        {/* Query textarea */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
            Query（そのまま送る）
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="例: odpt:operator=odpt.Operator:TokyuBus"
          />
          <p className="text-xs text-slate-400">
            例:{" "}
            <code className="rounded bg-slate-100 px-1">
              odpt:operator=odpt.Operator:TokyuBus
            </code>{" "}
            /{" "}
            <code className="rounded bg-slate-100 px-1">
              odpt:busroutePattern=odpt.BusroutePattern:TokyuBus.XXX
            </code>{" "}
            （&amp; 区切りで追加可）
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <span className="font-semibold">Error: </span>
            {error}
          </div>
        )}

        {/* Proxy meta */}
        {proxyRes?.meta && (
          <div className="rounded-lg border border-border bg-surface px-4 py-3 space-y-1 text-sm">
            <div className="flex flex-wrap gap-4 text-slate-700">
              <span>
                <span className="font-semibold">count:</span>{" "}
                {proxyRes.meta.count}
              </span>
              <span>
                <span className="font-semibold">dump:</span>{" "}
                {String(proxyRes.meta.dump)}
              </span>
              <span>
                <span className="font-semibold">maybeTruncated:</span>{" "}
                {String(proxyRes.meta.maybeTruncated)}
              </span>
              <span>
                <span className="font-semibold">cacheHit:</span>{" "}
                {String(proxyRes.meta.cacheHit)}
              </span>
            </div>
            <p className="truncate text-xs text-slate-400">
              <span className="font-semibold">URL: </span>
              <code>{proxyRes.meta.url}</code>
            </p>
            <p className="truncate text-xs text-slate-400">
              <span className="font-semibold">cacheKey: </span>
              <code>{proxyRes.meta.cacheKey}</code>
            </p>
            {proxyRes.meta.maybeTruncated && !proxyRes.meta.dump && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                取得件数が 1000 件です。検索 API の上限で欠損している可能性があります。
                Dump mode を ON にして再取得してください。
              </div>
            )}
          </div>
        )}
      </div>

      {/* Results: Proxy preview + Introspect */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* JSON Preview */}
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Proxy 結果プレビュー（先頭 20 件）
          </h2>
          <pre className="overflow-auto rounded-lg border border-border bg-slate-50 p-3 text-xs leading-relaxed max-h-[520px]">
            {preview || "（まだ取得していません）"}
          </pre>
        </div>

        {/* Introspect */}
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Introspect（フィールド一覧）
          </h2>
          {!introRes ? (
            <p className="text-sm text-slate-400">
              Introspect を実行すると、必須っぽいフィールドや型が出ます。
            </p>
          ) : (
            <>
              <p className="text-xs text-slate-500">
                sampleCount:{" "}
                <span className="font-semibold">{introRes.sampleCount}</span>（先頭サンプルで解析）
              </p>
              <div className="overflow-auto rounded-lg border border-border max-h-[460px]">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="sticky top-0 bg-slate-50 text-left text-slate-600">
                      <th className="px-3 py-2 font-semibold border-b border-border">
                        path
                      </th>
                      <th className="px-3 py-2 font-semibold border-b border-border w-20">
                        rate
                      </th>
                      <th className="px-3 py-2 font-semibold border-b border-border">
                        types
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {introRes.fields.slice(0, 200).map((f) => (
                      <tr
                        key={f.path}
                        className="border-b border-slate-50 hover:bg-slate-50"
                      >
                        <td className="px-3 py-1.5 font-mono text-slate-700">
                          {f.path}
                        </td>
                        <td className="px-3 py-1.5 text-slate-600">
                          {(f.presentRate * 100).toFixed(0)}%
                        </td>
                        <td className="px-3 py-1.5 text-slate-500">
                          {typesSummary(f.types)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400">
                上位ほど「ほぼ必須」。
                <code className="rounded bg-slate-100 px-1">owl:sameAs</code>,{" "}
                <code className="rounded bg-slate-100 px-1">odpt:*</code>,{" "}
                <code className="rounded bg-slate-100 px-1">dc:title</code>,{" "}
                <code className="rounded bg-slate-100 px-1">geo:*</code>{" "}
                の出現率を見ると把握が速い。
              </p>
            </>
          )}
        </div>
      </div>

      {/* Export operational */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">
          Export Operational（Stop / RoutePattern / Trip / Index / RouteTimetables）
        </h2>
        {!exportRes ? (
          <p className="text-sm text-slate-400">
            「Export Operational」を押すと、配車準備に使う operational JSON が返ります。
          </p>
        ) : (
          <pre className="overflow-auto rounded-lg border border-border bg-slate-50 p-3 text-xs leading-relaxed max-h-[520px]">
            {exportPreview}
          </pre>
        )}
      </div>

      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">
              Transit Catalog
            </h2>
            <p className="text-sm text-slate-500">
              ODPT と GTFS を共通 SQLite カタログに保持し、route-wise API で便と停留所時刻を読む。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => refreshCatalog("odpt")}
              disabled={catalogRefreshing !== ""}
              className="rounded-lg border border-primary-300 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-40"
            >
              {catalogRefreshing === "odpt" ? "Refreshing ODPT…" : "Refresh Tokyu ODPT"}
            </button>
            <button
              onClick={() => refreshCatalog("gtfs")}
              disabled={catalogRefreshing !== ""}
              className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40"
            >
              {catalogRefreshing === "gtfs" ? "Refreshing GTFS…" : "Refresh Toei GTFS"}
            </button>
          </div>
        </div>

        {!catalogSnapshots.length ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
            {catalogLoading
              ? "カタログを読み込み中..."
              : "まだ snapshot がありません。上の refresh ボタンか、scenario import を実行してください。"}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {catalogSnapshots.map((snapshot) => (
                <button
                  key={snapshot.snapshotKey}
                  onClick={() => setSelectedSnapshotKey(snapshot.snapshotKey)}
                  className={`rounded-lg border px-4 py-3 text-left transition-colors ${
                    snapshot.snapshotKey === selectedSnapshotKey
                      ? "border-primary-400 bg-primary-50"
                      : "border-border bg-surface hover:bg-slate-50"
                  }`}
                >
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {snapshot.source}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-slate-800">
                    {snapshotLabel(snapshot)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    generated: {snapshot.generatedAt ?? "-"}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    refreshed: {snapshot.refreshedAt ?? "-"}
                  </p>
                </button>
              ))}
            </div>

            {selectedSnapshotKey && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Snapshot Route
                  </span>
                  <select
                    value={selectedRouteId}
                    onChange={(e) => setSelectedRouteId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    {catalogRoutes.map((route) => (
                      <option key={route.route_id} value={route.route_id}>
                        {routeOptionLabel(route)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Service
                  </span>
                  <select
                    value={selectedServiceId}
                    onChange={(e) => setSelectedServiceId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    <option value="all">All services</option>
                    {(catalogRoute?.services ?? []).map((service) => (
                      <option key={service.service_id} value={service.service_id}>
                        {serviceLabel(service.service_id)} ({service.trip_count})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </>
        )}
      </div>

      {catalogRoute && (
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-700">
                Route Timetables
              </h2>
              <p className="text-sm text-slate-500">
                東98のような路線単位で、全便と各停留所の通過時刻を確認できます。
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="space-y-1.5">
                <span className="block text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Route
                </span>
                <select
                  value={selectedRouteId}
                  onChange={(e) => setSelectedRouteId(e.target.value)}
                  className="min-w-[320px] rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  {catalogRoutes.map((route) => (
                    <option key={route.route_id} value={route.route_id}>
                      {routeOptionLabel(route)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="block text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Service
                </span>
                <select
                  value={selectedServiceId}
                  onChange={(e) => setSelectedServiceId(e.target.value)}
                  className="rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="all">All services</option>
                  {catalogRoute.services.map((service) => (
                    <option key={service.service_id} value={service.service_id}>
                      {serviceLabel(service.service_id)} ({service.trip_count})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Route
              </p>
              <p className="mt-1 text-base font-semibold text-slate-800">
                {catalogRoute.route_code} · {catalogRoute.route_label}
              </p>
              <p className="mt-1 text-xs text-slate-500 break-all">
                {catalogRoute.route_id}
              </p>
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Trips
              </p>
              <p className="mt-1 text-base font-semibold text-slate-800">
                {catalogRoute.trip_count}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                表示中: {filteredTrips.length}
              </p>
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Patterns
              </p>
              <p className="mt-1 text-base font-semibold text-slate-800">
                {catalogRoute.patterns.length}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                停留所系統ごとに内訳を保持
              </p>
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Span
              </p>
              <p className="mt-1 text-base font-semibold text-slate-800">
                {(catalogRoute.first_departure ?? "--:--") +
                  " -> " +
                  (catalogRoute.last_arrival ?? "--:--")}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                始発から最終到着まで
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {catalogRoute.patterns.map((pattern) => (
              <span
                key={pattern.pattern_id}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600"
                title={pattern.pattern_id}
              >
                {patternSummary(pattern)}
              </span>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div className="rounded-lg border border-border bg-white">
              <div className="border-b border-border px-4 py-3 text-xs text-slate-500">
                {filteredTrips.length} trips
              </div>
              <VirtualizedList
                items={filteredTrips}
                height={520}
                itemHeight={72}
                className="bg-white"
                getKey={(trip) => trip.trip_id}
                renderItem={(trip) => (
                  <button
                    type="button"
                    onClick={() => setSelectedCatalogTripId(trip.trip_id)}
                    className={`grid h-full w-full gap-1 border-b border-slate-100 px-4 py-3 text-left hover:bg-slate-50 ${
                      trip.trip_id === selectedCatalogTripId ? "bg-primary-50" : ""
                    }`}
                  >
                    <span className="text-sm font-semibold text-slate-800">
                      {(trip.departure ?? "--:--") +
                        " -> " +
                        (trip.arrival ?? "--:--")}
                    </span>
                    <span className="truncate text-xs text-slate-500">
                      {(trip.origin_stop_name ?? "Unknown") +
                        " -> " +
                        (trip.destination_stop_name ?? "Unknown")}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {serviceLabel(trip.service_id)} / {trip.direction} / {trip.pattern_id}
                    </span>
                  </button>
                )}
              />
            </div>

            {selectedCatalogTrip ? (
              <div className="overflow-hidden rounded-lg border border-border bg-surface">
                <div className="border-b border-border px-4 py-3">
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <p className="text-sm font-semibold text-slate-800">
                        {(selectedCatalogTrip.departure ?? "--:--") +
                          " -> " +
                          (selectedCatalogTrip.arrival ?? "--:--") +
                          " · " +
                          (selectedCatalogTrip.origin_stop_name ?? "Unknown") +
                          " -> " +
                          (selectedCatalogTrip.destination_stop_name ?? "Unknown")}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {serviceLabel(selectedCatalogTrip.service_id)} / {selectedCatalogTrip.direction} / {selectedCatalogTrip.pattern_id}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>{selectedCatalogTrip.stop_times.length} stops</span>
                      {typeof selectedCatalogTrip.estimated_distance_km === "number" && (
                        <span>{selectedCatalogTrip.estimated_distance_km.toFixed(2)} km</span>
                      )}
                      {selectedCatalogTrip.is_partial && (
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-amber-700">
                          partial
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="overflow-auto px-4 py-3">
                  <table className="w-full border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-50 text-left text-slate-600">
                        <th className="border-b border-border px-3 py-2 font-semibold">#</th>
                        <th className="border-b border-border px-3 py-2 font-semibold">Stop</th>
                        <th className="border-b border-border px-3 py-2 font-semibold">Arrival</th>
                        <th className="border-b border-border px-3 py-2 font-semibold">Departure</th>
                        <th className="border-b border-border px-3 py-2 font-semibold">Pass time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedCatalogTrip.stop_times.map((stopTime) => (
                        <tr
                          key={`${selectedCatalogTrip.trip_id}-${stopTime.index}-${stopTime.stop_id}`}
                          className="border-b border-slate-100"
                        >
                          <td className="px-3 py-2 text-slate-500">{stopTime.index}</td>
                          <td className="px-3 py-2 text-slate-700">{stopTime.stop_name}</td>
                          <td className="px-3 py-2 text-slate-600">{stopTime.arrival ?? ""}</td>
                          <td className="px-3 py-2 text-slate-600">{stopTime.departure ?? ""}</td>
                          <td className="px-3 py-2 font-mono text-slate-700">{stopTime.time ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-slate-500">
                この条件に一致する便はありません。
              </p>
            )}
          </div>
        </div>
      )}

      {/* Save to disk result */}
      {saveRes && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 space-y-2">
          <h2 className="text-sm font-semibold text-emerald-800">
            Saved to Disk
          </h2>
          <p className="text-xs text-emerald-700">operational_dataset.json</p>
          <p className="text-xs font-mono text-emerald-700 break-all">
            {saveRes.savedTo}
          </p>
          {saveRes.normalizedSavedTo && (
            <>
              <p className="text-xs text-emerald-700">normalized_dataset.json</p>
              <p className="text-xs font-mono text-emerald-700 break-all">
                {saveRes.normalizedSavedTo}
              </p>
            </>
          )}
          {saveRes.routeTimetablesSavedTo && (
            <>
              <p className="text-xs text-emerald-700">route_timetables_dataset.json</p>
              <p className="text-xs font-mono text-emerald-700 break-all">
                {saveRes.routeTimetablesSavedTo}
              </p>
            </>
          )}
          <pre className="overflow-auto rounded-lg border border-emerald-200 bg-white p-3 text-xs leading-relaxed max-h-[200px]">
            {prettyJson(saveRes.meta)}
          </pre>
        </div>
      )}
      </>
      </section>
    </div>
    </TabWarmBoundary>
  );
}
