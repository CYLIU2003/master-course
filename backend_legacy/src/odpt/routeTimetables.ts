import type { OperationalDataset } from "./enrich";
import type { NormalizedService } from "./service";

export type RouteStopRef = {
  stop_id: string;
  stop_name: string;
};

export type RouteTimetablePattern = {
  pattern_id: string;
  title?: string;
  note?: string;
  direction: "outbound" | "inbound" | "loop";
  stop_sequence: RouteStopRef[];
  total_distance_km?: number;
  distance_coverage_ratio?: number;
};

export type RouteTimetableStopTime = {
  index: number;
  stop_id: string;
  stop_name: string;
  arrival?: string;
  departure?: string;
  time?: string;
};

export type RouteTimetableTrip = {
  trip_id: string;
  pattern_id: string;
  service_id: NormalizedService;
  direction: "outbound" | "inbound" | "loop";
  origin_stop_id?: string;
  origin_stop_name?: string;
  destination_stop_id?: string;
  destination_stop_name?: string;
  departure?: string;
  arrival?: string;
  estimated_distance_km?: number;
  distance_source?: string;
  is_partial: boolean;
  stop_times: RouteTimetableStopTime[];
};

export type RouteTimetableServiceSummary = {
  service_id: NormalizedService;
  trip_count: number;
  first_departure?: string;
  last_arrival?: string;
};

export type RouteTimetableGroup = {
  busroute_id: string;
  route_code: string;
  route_label: string;
  trip_count: number;
  first_departure?: string;
  last_arrival?: string;
  patterns: RouteTimetablePattern[];
  services: RouteTimetableServiceSummary[];
  trips: RouteTimetableTrip[];
};

type PatternDirection = "outbound" | "inbound" | "loop";

type RouteTimetableGroupBuilder = {
  busroute_id: string;
  route_code: string;
  route_label: string;
  patterns: Map<string, RouteTimetablePattern>;
  serviceSummaries: Map<NormalizedService, RouteTimetableServiceSummary>;
  trips: RouteTimetableTrip[];
  first_departure?: string;
  last_arrival?: string;
};

const SERVICE_ORDER: Record<NormalizedService, number> = {
  weekday: 0,
  saturday: 1,
  saturdayholiday: 2,
  holiday: 3,
  unknown: 4,
};

function compareOptionalTime(a?: string, b?: string): number {
  if (!a && !b) {
    return 0;
  }
  if (!a) {
    return 1;
  }
  if (!b) {
    return -1;
  }
  return a.localeCompare(b);
}

function minTime(current: string | undefined, candidate: string | undefined): string | undefined {
  if (!candidate) {
    return current;
  }
  if (!current) {
    return candidate;
  }
  return candidate.localeCompare(current) < 0 ? candidate : current;
}

function maxTime(current: string | undefined, candidate: string | undefined): string | undefined {
  if (!candidate) {
    return current;
  }
  if (!current) {
    return candidate;
  }
  return candidate.localeCompare(current) > 0 ? candidate : current;
}

function shortId(value: string | undefined, fallback = "UNKNOWN"): string {
  if (!value) {
    return fallback;
  }

  const afterColon = value.split(":").pop() ?? value;
  const afterDot = afterColon.split(".").pop() ?? afterColon;
  return afterDot || fallback;
}

function routeCode(busrouteId: string | undefined, patternId: string): string {
  return shortId(busrouteId, shortId(patternId, patternId));
}

function stopName(stops: OperationalDataset["stops"], stopId: string | undefined): string {
  if (!stopId) {
    return "";
  }

  const stop = stops[stopId];
  const name = typeof stop?.name === "string" ? stop.name.trim() : "";
  return name || shortId(stopId, stopId);
}

function effectiveTime(stopTime: { arrival?: string; departure?: string }): string | undefined {
  return stopTime.departure || stopTime.arrival;
}

function firstTripTime(
  stopTimes: Array<{ arrival?: string; departure?: string }>,
): string | undefined {
  for (const stopTime of stopTimes) {
    const value = effectiveTime(stopTime);
    if (value) {
      return value;
    }
  }
  return undefined;
}

function lastTripTime(
  stopTimes: Array<{ arrival?: string; departure?: string }>,
): string | undefined {
  for (let index = stopTimes.length - 1; index >= 0; index -= 1) {
    const stopTime = stopTimes[index];
    const value = stopTime.arrival || stopTime.departure;
    if (value) {
      return value;
    }
  }
  return undefined;
}

function hintedPatternDirection(patternId: string): PatternDirection | null {
  const normalized = patternId.toLowerCase();
  if (
    normalized.includes(".out") ||
    normalized.endsWith("out") ||
    normalized.includes("outbound")
  ) {
    return "outbound";
  }
  if (
    normalized.includes(".in") ||
    normalized.endsWith("in") ||
    normalized.includes("inbound")
  ) {
    return "inbound";
  }
  return null;
}

function buildPatternDirections(dataset: OperationalDataset): Record<string, PatternDirection> {
  const grouped = new Map<
    string,
    Array<{ patternId: string; startStopId: string; endStopId: string }>
  >();

  for (const [patternId, pattern] of Object.entries(dataset.routePatterns)) {
    if (pattern.stop_sequence.length < 2) {
      continue;
    }

    const busrouteId = pattern.busroute ?? patternId;
    const items = grouped.get(busrouteId) ?? [];
    items.push({
      patternId,
      startStopId: pattern.stop_sequence[0],
      endStopId: pattern.stop_sequence[pattern.stop_sequence.length - 1],
    });
    grouped.set(busrouteId, items);
  }

  const directions: Record<string, PatternDirection> = {};
  for (const patterns of grouped.values()) {
    const terminalPairs = new Map<string, string>();
    for (const pattern of patterns) {
      terminalPairs.set(`${pattern.startStopId}->${pattern.endStopId}`, pattern.patternId);
    }

    for (const pattern of patterns) {
      if (pattern.startStopId === pattern.endStopId) {
        directions[pattern.patternId] = "loop";
        continue;
      }

      const hintedDirection = hintedPatternDirection(pattern.patternId);
      if (hintedDirection) {
        directions[pattern.patternId] = hintedDirection;
        continue;
      }

      const reversePatternId = terminalPairs.get(
        `${pattern.endStopId}->${pattern.startStopId}`,
      );
      if (reversePatternId && pattern.patternId > reversePatternId) {
        directions[pattern.patternId] = "inbound";
      } else {
        directions[pattern.patternId] = "outbound";
      }
    }
  }

  return directions;
}

function ensureGroup(
  groups: Map<string, RouteTimetableGroupBuilder>,
  busrouteId: string,
  patternId: string,
  routeLabelCandidate?: string,
): RouteTimetableGroupBuilder {
  const existing = groups.get(busrouteId);
  if (existing) {
    if (
      routeLabelCandidate &&
      (!existing.route_label || existing.route_label === existing.route_code)
    ) {
      existing.route_label = routeLabelCandidate;
    }
    return existing;
  }

  const created: RouteTimetableGroupBuilder = {
    busroute_id: busrouteId,
    route_code: routeCode(busrouteId, patternId),
    route_label: routeLabelCandidate || routeCode(busrouteId, patternId),
    patterns: new Map(),
    serviceSummaries: new Map(),
    trips: [],
  };
  groups.set(busrouteId, created);
  return created;
}

export function buildRouteTimetables(
  dataset: OperationalDataset,
): RouteTimetableGroup[] {
  const patternDirections = buildPatternDirections(dataset);
  const groups = new Map<string, RouteTimetableGroupBuilder>();

  for (const [patternId, pattern] of Object.entries(dataset.routePatterns)) {
    const busrouteId = pattern.busroute ?? patternId;
    const group = ensureGroup(
      groups,
      busrouteId,
      patternId,
      typeof pattern.title === "string" && pattern.title.trim()
        ? pattern.title.trim()
        : undefined,
    );

    group.patterns.set(patternId, {
      pattern_id: patternId,
      title: pattern.title,
      note: pattern.note,
      direction: patternDirections[patternId] ?? "outbound",
      stop_sequence: pattern.stop_sequence.map((stopId) => ({
        stop_id: stopId,
        stop_name: stopName(dataset.stops, stopId),
      })),
      total_distance_km: pattern.total_distance_km,
      distance_coverage_ratio: pattern.distance_coverage_ratio,
    });
  }

  for (const [tripId, trip] of Object.entries(dataset.trips)) {
    const pattern = dataset.routePatterns[trip.pattern_id];
    const busrouteId = pattern?.busroute ?? trip.pattern_id;
    const routeLabelCandidate =
      typeof pattern?.title === "string" && pattern.title.trim()
        ? pattern.title.trim()
        : undefined;
    const group = ensureGroup(groups, busrouteId, trip.pattern_id, routeLabelCandidate);

    const stopTimes = trip.stop_times.map((stopTime) => ({
      index: stopTime.index,
      stop_id: stopTime.stop_id,
      stop_name: stopName(dataset.stops, stopTime.stop_id),
      arrival: stopTime.arrival,
      departure: stopTime.departure,
      time: effectiveTime(stopTime),
    }));

    const firstStop = stopTimes[0];
    const lastStop = stopTimes[stopTimes.length - 1];
    const departure = firstTripTime(stopTimes);
    const arrival = lastTripTime(stopTimes);
    const direction = patternDirections[trip.pattern_id] ?? "outbound";

    const tripItem: RouteTimetableTrip = {
      trip_id: tripId,
      pattern_id: trip.pattern_id,
      service_id: trip.service_id,
      direction,
      origin_stop_id: firstStop?.stop_id,
      origin_stop_name: firstStop?.stop_name,
      destination_stop_id: lastStop?.stop_id,
      destination_stop_name: lastStop?.stop_name,
      departure,
      arrival,
      estimated_distance_km: trip.estimated_distance_km,
      distance_source: trip.distance_source,
      is_partial: Boolean(trip.is_partial),
      stop_times: stopTimes,
    };

    group.trips.push(tripItem);
    group.first_departure = minTime(group.first_departure, departure);
    group.last_arrival = maxTime(group.last_arrival, arrival);

    const serviceSummary = group.serviceSummaries.get(trip.service_id) ?? {
      service_id: trip.service_id,
      trip_count: 0,
    };
    serviceSummary.trip_count += 1;
    serviceSummary.first_departure = minTime(serviceSummary.first_departure, departure);
    serviceSummary.last_arrival = maxTime(serviceSummary.last_arrival, arrival);
    group.serviceSummaries.set(trip.service_id, serviceSummary);
  }

  return Array.from(groups.values())
    .map((group) => ({
      busroute_id: group.busroute_id,
      route_code: group.route_code,
      route_label: group.route_label || group.route_code,
      trip_count: group.trips.length,
      first_departure: group.first_departure,
      last_arrival: group.last_arrival,
      patterns: Array.from(group.patterns.values()).sort((a, b) => {
        return (
          a.direction.localeCompare(b.direction) ||
          (a.title ?? "").localeCompare(b.title ?? "") ||
          a.pattern_id.localeCompare(b.pattern_id)
        );
      }),
      services: Array.from(group.serviceSummaries.values()).sort((a, b) => {
        return (
          SERVICE_ORDER[a.service_id] - SERVICE_ORDER[b.service_id] ||
          a.service_id.localeCompare(b.service_id)
        );
      }),
      trips: group.trips.sort((a, b) => {
        return (
          compareOptionalTime(a.departure, b.departure) ||
          compareOptionalTime(a.arrival, b.arrival) ||
          a.pattern_id.localeCompare(b.pattern_id) ||
          a.trip_id.localeCompare(b.trip_id)
        );
      }),
    }))
    .filter((group) => group.trip_count > 0)
    .sort((a, b) => {
      return (
        a.route_code.localeCompare(b.route_code) ||
        a.route_label.localeCompare(b.route_label) ||
        a.busroute_id.localeCompare(b.busroute_id)
      );
    });
}
