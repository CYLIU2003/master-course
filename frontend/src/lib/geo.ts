// ── Geodesic utilities ────────────────────────────────────────

import type { GraphEdge, GraphNode } from "@/stores/route-graph-store";
import type { Id } from "@/types/master";

export type LatLng = { lat: number; lng: number };

const EARTH_RADIUS_KM = 6371;

/**
 * Haversine distance between two points in kilometres.
 */
export function haversineKm(a: LatLng, b: LatLng): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);

  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);

  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);

  const h =
    sinDLat * sinDLat +
    Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;

  const c = 2 * Math.asin(Math.min(1, Math.sqrt(h)));
  return EARTH_RADIUS_KM * c;
}

/**
 * Round to N decimal places.
 */
export function roundKm(km: number, decimals = 3): number {
  const f = 10 ** decimals;
  return Math.round(km * f) / f;
}

// ── Graph geo-sync helpers ────────────────────────────────────

/**
 * For each edge whose both endpoints have lat/lng set,
 * compute distanceKm from Haversine and return updated edges.
 * Edges where either node is missing geo remain unchanged.
 */
export function syncEdgeDistancesFromGeo(
  edges: GraphEdge[],
  nodes: GraphNode[],
): GraphEdge[] {
  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));
  return edges.map((e) => {
    const from = nodeMap[e.fromId];
    const to = nodeMap[e.toId];
    if (
      from?.lat != null &&
      from?.lng != null &&
      to?.lat != null &&
      to?.lng != null
    ) {
      const km = roundKm(
        haversineKm(
          { lat: from.lat, lng: from.lng },
          { lat: to.lat, lng: to.lng },
        ),
      );
      return { ...e, distanceKm: km };
    }
    return e;
  });
}

/**
 * Project geo coordinates to canvas layout positions.
 * Returns a map of nodeId → {x, y} in canvas pixels.
 * Nodes without geo coords are placed at canvas centre.
 */
export function initNodeLayoutFromGeo(
  nodes: GraphNode[],
  canvasWidth: number,
  canvasHeight: number,
  padding = 60,
): Record<Id, { x: number; y: number }> {
  const geoNodes = nodes.filter((n) => n.lat != null && n.lng != null);

  if (geoNodes.length < 2) {
    // Place everything at centre with a small offset per node
    const cx = canvasWidth / 2;
    const cy = canvasHeight / 2;
    return Object.fromEntries(
      nodes.map((n, i) => [
        n.id,
        { x: cx + i * 40 - (nodes.length * 20) / 2, y: cy },
      ]),
    );
  }

  const lats = geoNodes.map((n) => n.lat as number);
  const lngs = geoNodes.map((n) => n.lng as number);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  const usableW = canvasWidth - padding * 2;
  const usableH = canvasHeight - padding * 2;

  const latRange = maxLat - minLat || 1;
  const lngRange = maxLng - minLng || 1;

  const result: Record<Id, { x: number; y: number }> = {};
  for (const n of nodes) {
    if (n.lat != null && n.lng != null) {
      result[n.id] = {
        x: padding + ((n.lng - minLng) / lngRange) * usableW,
        // Latitude increases upward, so invert y
        y: padding + ((maxLat - n.lat) / latRange) * usableH,
      };
    } else {
      result[n.id] = { x: canvasWidth / 2, y: canvasHeight / 2 };
    }
  }
  return result;
}
