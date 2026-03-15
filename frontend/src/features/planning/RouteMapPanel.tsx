import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useDepots, useRoute, useRoutes, useStops } from "@/hooks";
import type { Depot, Route, Stop } from "@/types";

const VIEWBOX_WIDTH = 1000;
const VIEWBOX_HEIGHT = 640;
const VIEWBOX_PADDING = 64;

interface Props {
  scenarioId: string;
}

type PlotPoint = {
  id: string;
  label: string;
  kind: "depot" | "start" | "end" | "stop";
  lon: number;
  lat: number;
  subtitle?: string;
};

type ProjectedPoint = PlotPoint & {
  x: number;
  y: number;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function buildStopIndex(stops: Stop[]) {
  const normalize = (value: string | null | undefined) =>
    String(value ?? "")
      .normalize("NFKC")
      .replace(/\s+/g, "")
      .trim();

  const index = new Map<string, Stop>();
  for (const stop of stops) {
    if (!isFiniteNumber(stop.lat) || !isFiniteNumber(stop.lon)) {
      continue;
    }
    const key = normalize(stop.name);
    if (!key || index.has(key)) {
      continue;
    }
    index.set(key, stop);
  }
  return (name: string | null | undefined) => index.get(normalize(name));
}

function createViewport(points: PlotPoint[]) {
  const lons = points.map((point) => point.lon);
  const lats = points.map((point) => point.lat);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const lonRange = Math.max(maxLon - minLon, 0.001);
  const latRange = Math.max(maxLat - minLat, 0.001);
  const drawableWidth = VIEWBOX_WIDTH - VIEWBOX_PADDING * 2;
  const drawableHeight = VIEWBOX_HEIGHT - VIEWBOX_PADDING * 2;

  return {
    bounds: { minLon, maxLon, minLat, maxLat },
    project(point: PlotPoint): ProjectedPoint {
      const x = VIEWBOX_PADDING + ((point.lon - minLon) / lonRange) * drawableWidth;
      const y = VIEWBOX_HEIGHT - VIEWBOX_PADDING - ((point.lat - minLat) / latRange) * drawableHeight;
      return { ...point, x, y };
    },
  };
}

export function RouteMapPanel({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const viewMode = useMasterUiStore((s) => s.viewMode);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);

  const mapActive = viewMode === "map" || viewMode === "split";
  const shouldLoadDepotData = mapActive && (activeTab === "depots" || activeTab === "vehicles");
  const shouldLoadRoutesData = mapActive && activeTab === "routes";
  const shouldLoadRouteDetail = shouldLoadRoutesData && !!selectedRouteId;
  const shouldLoadStops = shouldLoadRoutesData && !!selectedRouteId;

  const { data: depotsData } = useDepots(scenarioId, {
    enabled: shouldLoadDepotData,
  });
  const { data: routesData } = useRoutes(scenarioId, {
    depotId: selectedDepotId ?? undefined,
    groupByFamily: true,
    enabled: shouldLoadRoutesData,
  });
  const { data: routeDetail } = useRoute(scenarioId, selectedRouteId ?? "", {
    enabled: shouldLoadRouteDetail,
  });
  const { data: stopsData } = useStops(scenarioId, {
    enabled: shouldLoadStops,
  });

  const depots = useMemo<Depot[]>(() => depotsData?.items ?? [], [depotsData]);
  const routes = useMemo<Route[]>(() => routesData?.items ?? [], [routesData]);
  const stops = useMemo<Stop[]>(() => stopsData?.items ?? [], [stopsData]);
  const resolveStopByName = useMemo(() => buildStopIndex(stops), [stops]);

  const visibleRoute = useMemo(
    () => routeDetail ?? routes.find((route) => route.id === selectedRouteId) ?? null,
    [routeDetail, routes, selectedRouteId],
  );

  const routePoints = useMemo<PlotPoint[]>(() => {
    if (!visibleRoute) {
      return [];
    }

    const resolvedStops = (visibleRoute.resolvedStops ?? [])
      .filter((stop) => isFiniteNumber(stop.lat) && isFiniteNumber(stop.lon))
      .sort((left, right) => left.sequence - right.sequence)
      .map((stop, index, all) => ({
        id: String(stop.id ?? `${visibleRoute.id}-${index}`),
        label: stop.name,
        kind: index === 0 ? "start" : index === all.length - 1 ? "end" : "stop",
        lon: Number(stop.lon),
        lat: Number(stop.lat),
        subtitle: visibleRoute.routeCode || visibleRoute.routeFamilyCode || visibleRoute.name,
      } satisfies PlotPoint));

    if (resolvedStops.length > 0) {
      return resolvedStops;
    }

    const derivedPoints: Array<PlotPoint | null> = (visibleRoute.stopSequence ?? []).map((stopName, index, all) => {
        const stop = resolveStopByName(stopName);
        if (!stop || !isFiniteNumber(stop.lat) || !isFiniteNumber(stop.lon)) {
          return null;
        }
        return {
          id: `${visibleRoute.id}:${stop.name}:${index}`,
          label: stop.name,
          kind: index === 0 ? "start" : index === all.length - 1 ? "end" : "stop",
          lon: stop.lon,
          lat: stop.lat,
          subtitle: visibleRoute.routeCode || visibleRoute.routeFamilyCode || visibleRoute.name,
        } satisfies PlotPoint;
      });
    return derivedPoints.filter((point): point is PlotPoint => point !== null);
  }, [resolveStopByName, visibleRoute]);

  const depotPoints = useMemo<PlotPoint[]>(() => {
    const source = selectedDepotId
      ? depots.filter((depot) => depot.id === selectedDepotId)
      : depots;
    return source
      .filter((depot) => isFiniteNumber(depot.lat) && isFiniteNumber(depot.lon))
      .map((depot) => ({
        id: depot.id,
        label: depot.name,
        kind: "depot",
        lon: depot.lon,
        lat: depot.lat,
        subtitle: depot.location || undefined,
      }));
  }, [depots, selectedDepotId]);

  const plotPoints = activeTab === "routes" ? routePoints : depotPoints;
  const viewport = useMemo(() => (plotPoints.length > 0 ? createViewport(plotPoints) : null), [plotPoints]);
  const projectedPoints = useMemo(
    () => (viewport ? plotPoints.map((point) => viewport.project(point)) : []),
    [plotPoints, viewport],
  );
  const routePolyline = useMemo(() => {
    if (activeTab !== "routes" || projectedPoints.length < 2) {
      return "";
    }
    return projectedPoints.map((point) => `${point.x},${point.y}`).join(" ");
  }, [activeTab, projectedPoints]);

  const noGeoCount = depots.filter(
    (depot) => !isFiniteNumber(depot.lat) || !isFiniteNumber(depot.lon) || (depot.lat === 0 && depot.lon === 0),
  ).length;

  const emptyMessage =
    activeTab === "routes"
      ? t("map.routes_placeholder", "route を選択すると selected-only で描画します")
      : t("map.no_location_hint", "営業所を選択すると位置プレビューを表示します");

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-xl bg-slate-950 text-white">
      {(activeTab === "depots" || activeTab === "vehicles") && noGeoCount > 0 && (
        <div className="z-10 border-b border-amber-400/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-100">
          {t(
            "map.no_location_hint",
            `${noGeoCount} 件の営業所に位置情報がありません。営業所エディタで緯度・経度を設定してください。`,
          ).replace("${noGeoCount}", String(noGeoCount))}
        </div>
      )}

      {activeTab === "routes" && (
        <div className="z-10 border-b border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300">
          {visibleRoute
            ? t("map.routes_selected_only", "選択中 route の stop sequence から polyline を描画しています。")
            : emptyMessage}
        </div>
      )}

      <div className="relative flex-1 overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.16),_transparent_42%),linear-gradient(180deg,_#0f172a_0%,_#111827_100%)]">
        {!viewport ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-slate-300">
            {emptyMessage}
          </div>
        ) : (
          <svg viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`} className="h-full w-full">
            <defs>
              <pattern id="map-grid" width="80" height="80" patternUnits="userSpaceOnUse">
                <path d="M 80 0 L 0 0 0 80" fill="none" stroke="rgba(148,163,184,0.16)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect x="0" y="0" width={VIEWBOX_WIDTH} height={VIEWBOX_HEIGHT} fill="url(#map-grid)" />

            {routePolyline && (
              <polyline
                points={routePolyline}
                fill="none"
                stroke={visibleRoute?.color || "#38bdf8"}
                strokeWidth="8"
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity="0.9"
              />
            )}

            {projectedPoints.map((point) => {
              const radius = point.kind === "depot" ? 16 : point.kind === "stop" ? 8 : 12;
              const fill =
                point.kind === "depot"
                  ? "#38bdf8"
                  : point.kind === "start"
                    ? "#14b8a6"
                    : point.kind === "end"
                      ? "#f97316"
                      : "#cbd5e1";
              return (
                <g key={point.id}>
                  <circle cx={point.x} cy={point.y} r={radius + 5} fill="rgba(15,23,42,0.45)" />
                  <circle cx={point.x} cy={point.y} r={radius} fill={fill} stroke="white" strokeWidth="3" />
                  <text x={point.x + 18} y={point.y - 10} fill="white" fontSize="16" fontWeight="600">
                    {point.label}
                  </text>
                  {point.subtitle ? (
                    <text x={point.x + 18} y={point.y + 12} fill="rgba(226,232,240,0.8)" fontSize="12">
                      {point.subtitle}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </svg>
        )}

        {viewport && (
          <div className="pointer-events-none absolute bottom-3 left-3 rounded-lg border border-white/10 bg-slate-950/80 px-3 py-2 text-[11px] text-slate-300">
            <div>lon: {viewport.bounds.minLon.toFixed(4)} - {viewport.bounds.maxLon.toFixed(4)}</div>
            <div>lat: {viewport.bounds.minLat.toFixed(4)} - {viewport.bounds.maxLat.toFixed(4)}</div>
            <div>points: {projectedPoints.length}</div>
          </div>
        )}
      </div>
    </div>
  );
}
