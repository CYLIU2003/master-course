// ── RouteMapPanel ─────────────────────────────────────────────
// MapLibre GL JS map panel.
// - Depots tab: shows a marker for every depot that has lat/lon.
// - Vehicles tab: shows depot markers (same view).
// - Routes tab: shows route start/end stop markers where data exists.
//   (Full route-geometry rendering is Phase 3B.)
//
// Free tile style: https://demotiles.maplibre.org/style.json
// No API key required.

import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useDepots, useRoute, useRoutes, useStops } from "@/hooks";
import type { Depot, Route, Stop } from "@/types";

const FREE_STYLE = "https://demotiles.maplibre.org/style.json";
const DEFAULT_CENTER: [number, number] = [139.7671, 35.6812]; // Tokyo
const DEFAULT_ZOOM = 10;
const ROUTE_SOURCE_ID = "selected-route-source";
const ROUTE_LAYER_ID = "selected-route-line";

interface Props {
  scenarioId: string;
}

export function RouteMapPanel({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);
  const selectedDepotId = useMasterUiStore((s) => s.selectedDepotId);
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  const { data: depotsData } = useDepots(scenarioId);
  const { data: routesData } = useRoutes(scenarioId, {
    depotId: selectedDepotId ?? undefined,
    groupByFamily: true,
  });
  const { data: routeDetail } = useRoute(scenarioId, selectedRouteId ?? "");
  const { data: stopsData } = useStops(scenarioId);
  const depots = useMemo<Depot[]>(() => depotsData?.items ?? [], [depotsData]);
  const routes = useMemo<Route[]>(() => routesData?.items ?? [], [routesData]);
  const stops = useMemo<Stop[]>(() => stopsData?.items ?? [], [stopsData]);
  const stopByName = useMemo(() => {
    const normalized = (value: string | null | undefined) =>
      String(value ?? "")
        .normalize("NFKC")
        .replace(/\s+/g, "")
        .trim();
    const index = new Map<string, Stop>();
    for (const stop of stops) {
      if (stop.lat == null || stop.lon == null) {
        continue;
      }
      const key = normalized(stop.name);
      if (!key || index.has(key)) {
        continue;
      }
      index.set(key, stop);
    }
    return { get: (name: string | null | undefined) => index.get(normalized(name)) };
  }, [stops]);
  const visibleRoute = useMemo(
    () => routeDetail ?? routes.find((route) => route.id === selectedRouteId) ?? null,
    [routeDetail, routes, selectedRouteId],
  );
  const routeCoordinates = useMemo(() => {
    if (!visibleRoute) {
      return [] as [number, number][];
    }
    const resolved = (visibleRoute.resolvedStops ?? [])
      .filter((stop) => stop.lat != null && stop.lon != null)
      .sort((left, right) => left.sequence - right.sequence)
      .map((stop) => [stop.lon!, stop.lat!] as [number, number]);
    if (resolved.length >= 2) {
      return resolved;
    }
    return (visibleRoute.stopSequence ?? [])
      .map((stopName) => stopByName.get(stopName))
      .filter((stop): stop is Stop => stop != null && stop.lat != null && stop.lon != null)
      .map((stop) => [stop.lon!, stop.lat!] as [number, number]);
  }, [visibleRoute, stopByName]);

  // ── Map lifecycle ───────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: FREE_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      if (map.getLayer(ROUTE_LAYER_ID)) {
        map.removeLayer(ROUTE_LAYER_ID);
      }
      if (map.getSource(ROUTE_SOURCE_ID)) {
        map.removeSource(ROUTE_SOURCE_ID);
      }
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ── Update depot markers when data changes ──────────────────

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Remove old markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    if (map.getLayer(ROUTE_LAYER_ID)) {
      map.removeLayer(ROUTE_LAYER_ID);
    }
    if (map.getSource(ROUTE_SOURCE_ID)) {
      map.removeSource(ROUTE_SOURCE_ID);
    }

    if (activeTab === "routes") {
      if (!visibleRoute) {
        return;
      }
      const startStop = stopByName.get(visibleRoute.startStop);
      const endStop = stopByName.get(visibleRoute.endStop);
      const geoStops = [startStop, endStop].filter(
        (stop): stop is Stop => stop != null && stop.lat != null && stop.lon != null,
      );

      for (const [index, stop] of geoStops.entries()) {
        const el = document.createElement("div");
        el.style.cssText = `
          width: 18px;
          height: 18px;
          border-radius: 9999px;
          border: 2px solid white;
          background: ${index === 0 ? "#0f766e" : "#b91c1c"};
          box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        `;
        const label = index === 0 ? "Start" : "End";
        const popup = new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(`
          <div style="font-size:12px;font-weight:600;color:#1e293b;">${label}: ${stop.name}</div>
          <div style="font-size:10px;color:#94a3b8;margin-top:1px;">${visibleRoute.routeCode || visibleRoute.routeFamilyCode || visibleRoute.name}</div>
        `);
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([stop.lon!, stop.lat!])
          .setPopup(popup)
          .addTo(map);
        markersRef.current.push(marker);
      }

      if (routeCoordinates.length >= 2) {
        map.addSource(ROUTE_SOURCE_ID, {
          type: "geojson",
          data: {
            type: "Feature",
            properties: {
              routeId: visibleRoute.id,
            },
            geometry: {
              type: "LineString",
              coordinates: routeCoordinates,
            },
          },
        });
        map.addLayer({
          id: ROUTE_LAYER_ID,
          type: "line",
          source: ROUTE_SOURCE_ID,
          paint: {
            "line-color": visibleRoute.color || "#2563eb",
            "line-width": 5,
            "line-opacity": 0.85,
          },
        });
      }

      if (routeCoordinates.length >= 2) {
        const bounds = new maplibregl.LngLatBounds();
        for (const [lon, lat] of routeCoordinates) {
          bounds.extend([lon, lat]);
        }
        map.fitBounds(bounds, { padding: 80, maxZoom: 14 });
      } else if (geoStops.length === 1) {
        map.flyTo({ center: [geoStops[0].lon!, geoStops[0].lat!], zoom: 13 });
      } else if (geoStops.length > 1) {
        const bounds = new maplibregl.LngLatBounds();
        for (const stop of geoStops) {
          bounds.extend([stop.lon!, stop.lat!]);
        }
        map.fitBounds(bounds, { padding: 80, maxZoom: 14 });
      }
      return;
    }

    if (activeTab !== "depots" && activeTab !== "vehicles") return;

    const sourceDepots = selectedDepotId
      ? depots.filter((depot) => depot.id === selectedDepotId)
      : depots;
    const geoDepots = sourceDepots.filter(
      (d) => typeof d.lat === "number" && typeof d.lon === "number",
    );

    if (geoDepots.length === 0) return;

    // Add markers
    for (const depot of geoDepots) {
      const el = document.createElement("div");
      el.className = "depot-marker";
      el.style.cssText = `
        width: 32px;
        height: 32px;
        background: #2563eb;
        border: 2px solid white;
        border-radius: 50% 50% 50% 0;
        transform: rotate(-45deg);
        cursor: pointer;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
      `;

      const popup = new maplibregl.Popup({ offset: 20, closeButton: false }).setHTML(`
        <div style="font-size:12px;font-weight:600;color:#1e293b;">${depot.name}</div>
        <div style="font-size:11px;color:#64748b;margin-top:2px;">${depot.location || ""}</div>
        <div style="font-size:10px;color:#94a3b8;margin-top:1px;">${depot.lat.toFixed(4)}, ${depot.lon.toFixed(4)}</div>
      `);

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([depot.lon, depot.lat])
        .setPopup(popup)
        .addTo(map);

      markersRef.current.push(marker);
    }

    // Fly to fit all markers
    if (geoDepots.length === 1) {
      map.flyTo({ center: [geoDepots[0].lon, geoDepots[0].lat], zoom: 13 });
    } else {
      const bounds = new maplibregl.LngLatBounds();
      for (const d of geoDepots) bounds.extend([d.lon, d.lat]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 14 });
    }
  }, [depots, activeTab, routeCoordinates, selectedDepotId, stopByName, visibleRoute]);

  // ── Routes tab: clear depot markers ────────────────────────
  useEffect(() => {
    if (activeTab === "routes") {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
    }
  }, [activeTab]);

  // ── Count depots without geo (for info banner) ──────────────
  const noGeoCount = depots.filter(
    (d) => typeof d.lat !== "number" || typeof d.lon !== "number" || (d.lat === 0 && d.lon === 0),
  ).length;

  return (
    <div className="relative flex h-full flex-col">
      {/* Info banner */}
      {(activeTab === "depots" || activeTab === "vehicles") && noGeoCount > 0 && (
        <div className="z-10 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
          {t(
            "map.no_location_hint",
            `${noGeoCount} 件の営業所に位置情報がありません。営業所エディタで緯度・経度を設定してください。`,
          ).replace("${noGeoCount}", String(noGeoCount))}
        </div>
      )}

      {/* Routes tab hint */}
      {activeTab === "routes" && (
        <div className="z-10 border-b border-border bg-slate-50 px-3 py-1.5 text-xs text-slate-400">
          {visibleRoute
            ? t(
                "map.routes_selected_only",
                "選択中 route の stop sequence から polyline を描画しています。",
              )
            : t("map.routes_placeholder", "route を選択すると selected-only で描画します")}
        </div>
      )}

      {/* Map container */}
      <div ref={containerRef} className="flex-1" />
    </div>
  );
}
