import { haversineKm } from "../geo";
import { RoutePattern, RouteSegment, Stop } from "./index";

type RawRecord = Record<string, unknown>;
type RawOrder = Record<string, unknown>;

export function normalizeRoutePatterns(
  raw: unknown[],
  stops: Record<string, Stop>
): Record<string, RoutePattern> {
  const out: Record<string, RoutePattern> = {};

  for (const item of raw) {
    const r = item as RawRecord;
    const pattern_id = (r["owl:sameAs"] ?? r["@id"]) as string | undefined;
    if (!pattern_id) continue;

    const orders = (r["odpt:busstopPoleOrder"] as RawOrder[] | undefined) ?? [];

    // Sort by odpt:index (ascending) then extract odpt:busstopPole refs
    const stop_sequence = orders
      .slice()
      .sort(
        (a, b) =>
          Number((a["odpt:index"] as number | string | undefined) ?? 0) -
          Number((b["odpt:index"] as number | string | undefined) ?? 0)
      )
      .map((o) => o["odpt:busstopPole"] as string | undefined)
      .filter((s): s is string => Boolean(s));

    const segments: RouteSegment[] = [];
    for (let i = 0; i < stop_sequence.length - 1; i++) {
      const from_stop_id = stop_sequence[i];
      const to_stop_id = stop_sequence[i + 1];
      const fromStop = stops[from_stop_id];
      const toStop = stops[to_stop_id];

      let distance_km: number | undefined;
      if (
        fromStop?.lat != null &&
        fromStop?.lon != null &&
        toStop?.lat != null &&
        toStop?.lon != null
      ) {
        distance_km = haversineKm(
          fromStop.lat,
          fromStop.lon,
          toStop.lat,
          toStop.lon
        );
      }

      segments.push({ from_stop_id, to_stop_id, distance_km });
    }

    out[pattern_id] = {
      pattern_id,
      title: r["dc:title"] as string | undefined,
      note: r["odpt:note"] as string | undefined,
      busroute: r["odpt:busroute"] as string | undefined,
      stop_sequence,
      segments,
    };
  }

  return out;
}
