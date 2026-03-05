// ── Geodesic utilities ────────────────────────────────────────

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
