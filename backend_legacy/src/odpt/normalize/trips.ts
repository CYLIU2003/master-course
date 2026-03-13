import { Trip, TripStopTime, RoutePattern } from "./index";
import { normalizeService } from "../service";

type RawRecord = Record<string, unknown>;
type RawTimeObj = Record<string, unknown>;

/**
 * Returns true if `tripStops` is a contiguous subsequence of `patternStops`.
 * Used to flag short-working / part-route trips as is_partial.
 */
function isContiguousSubsequence(
  patternStops: string[],
  tripStops: string[]
): boolean {
  if (!patternStops.length || !tripStops.length) return false;
  if (tripStops.length > patternStops.length) return false;

  for (let i = 0; i + tripStops.length <= patternStops.length; i++) {
    let ok = true;
    for (let j = 0; j < tripStops.length; j++) {
      if (patternStops[i + j] !== tripStops[j]) {
        ok = false;
        break;
      }
    }
    if (ok) return true;
  }
  return false;
}

export function normalizeTrips(
  raw: unknown[],
  patterns: Record<string, RoutePattern>
): Record<string, Trip> {
  const out: Record<string, Trip> = {};

  for (const item of raw) {
    const r = item as RawRecord;
    const trip_id = (r["owl:sameAs"] ?? r["@id"]) as string | undefined;
    if (!trip_id) continue;

    const pattern_id = r["odpt:busroutePattern"] as string | undefined;
    const calendar = r["odpt:calendar"] as string | undefined;
    const service_id = normalizeService(calendar);

    const objs = (r["odpt:busTimetableObject"] as RawTimeObj[] | undefined) ?? [];

    const stop_times: TripStopTime[] = objs
      .slice()
      .sort(
        (a, b) =>
          Number((a["odpt:index"] as number | string | undefined) ?? 0) -
          Number((b["odpt:index"] as number | string | undefined) ?? 0)
      )
      .map((o) => ({
        index: Number((o["odpt:index"] as number | string | undefined) ?? 0),
        stop_id: o["odpt:busstopPole"] as string,
        arrival: o["odpt:arrivalTime"] as string | undefined,
        departure: o["odpt:departureTime"] as string | undefined,
      }))
      .filter((x) => Boolean(x.stop_id));

    const tripStops = stop_times.map((x) => x.stop_id);
    const patternStops = pattern_id
      ? (patterns[pattern_id]?.stop_sequence ?? [])
      : [];

    const is_partial =
      patternStops.length > 0 &&
      tripStops.length > 0 &&
      tripStops.length < patternStops.length &&
      isContiguousSubsequence(patternStops, tripStops);

    out[trip_id] = {
      trip_id,
      pattern_id: pattern_id ?? "UNKNOWN_PATTERN",
      calendar,
      service_id,
      stop_times,
      ...(is_partial ? { is_partial: true } : {}),
    };
  }

  return out;
}
