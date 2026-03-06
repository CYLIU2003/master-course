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
import { useDepots } from "@/hooks";
import type { Depot } from "@/types";

const FREE_STYLE = "https://demotiles.maplibre.org/style.json";
const DEFAULT_CENTER: [number, number] = [139.7671, 35.6812]; // Tokyo
const DEFAULT_ZOOM = 10;

interface Props {
  scenarioId: string;
}

export function RouteMapPanel({ scenarioId }: Props) {
  const { t } = useTranslation();
  const activeTab = useMasterUiStore((s) => s.activeTab);

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  const { data: depotsData } = useDepots(scenarioId);
  const depots = useMemo<Depot[]>(() => depotsData?.items ?? [], [depotsData]);

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

    if (activeTab !== "depots" && activeTab !== "vehicles") return;

    const geoDepots = depots.filter(
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
  }, [depots, activeTab]);

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
          {t("map.routes_placeholder", "路線ジオメトリ表示は Phase 3B で実装予定")}
        </div>
      )}

      {/* Map container */}
      <div ref={containerRef} className="flex-1" />
    </div>
  );
}
