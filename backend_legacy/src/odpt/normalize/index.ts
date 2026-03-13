import { normalizeStops } from "./stops";
import { normalizeRoutePatterns } from "./routePatterns";
import { normalizeTrips } from "./trips";
import { normalizeStopTimetables } from "./stopTimetables";
import type { NormalizedService } from "../service";
import type { StopTimetable } from "./stopTimetables";

export type { StopTimetable, StopTimetableItem } from "./stopTimetables";

// ── Canonical normalized types ────────────────────────────────────────────────

export type Stop = {
  stop_id: string;
  name?: string;
  lat?: number;
  lon?: number;
  poleNumber?: string | null;
};

export type RouteSegment = {
  from_stop_id: string;
  to_stop_id: string;
  distance_km?: number;
};

export type RoutePattern = {
  pattern_id: string;
  title?: string;
  note?: string;
  busroute?: string;
  stop_sequence: string[];
  segments: RouteSegment[];
};

export type TripStopTime = {
  index: number;
  stop_id: string;
  arrival?: string;
  departure?: string;
};

export type Trip = {
  trip_id: string;
  pattern_id: string;
  calendar?: string;
  service_id: NormalizedService;
  stop_times: TripStopTime[];
  is_partial?: boolean;
};

export interface NormalizeInput {
  stopsRaw: unknown[];
  patternsRaw: unknown[];
  timetablesRaw: unknown[];
  stopTimetablesRaw: unknown[];
}

export interface NormalizedDataset {
  stops: Record<string, Stop>;
  routePatterns: Record<string, RoutePattern>;
  trips: Record<string, Trip>;
  stopTimetables: Record<string, StopTimetable>;
}

export function normalizeAll(input: NormalizeInput): NormalizedDataset {
  const stops = normalizeStops(input.stopsRaw);
  const routePatterns = normalizeRoutePatterns(input.patternsRaw, stops);
  const trips = normalizeTrips(input.timetablesRaw, routePatterns);
  const stopTimetables = normalizeStopTimetables(input.stopTimetablesRaw);
  return { stops, routePatterns, trips, stopTimetables };
}
