import type { NormalizedService } from "./service";
import type {
  NormalizedDataset,
  RoutePattern,
  RouteSegment,
  Stop,
  StopTimetable,
  Trip,
} from "./normalize";

export type TripDistanceSource =
  | "pattern_segments"
  | "partial_pattern_segments"
  | "unknown";

export type OperationalRoutePattern = RoutePattern & {
  total_distance_km?: number;
  distance_coverage_ratio: number;
};

export type OperationalTrip = Trip & {
  estimated_distance_km?: number;
  distance_source: TripDistanceSource;
};

export type TripsByService = Record<NormalizedService, string[]>;

export type OperationalIndexes = {
  tripsByService: TripsByService;
  tripsByPattern: Record<string, string[]>;
};

export type OperationalDataset = {
  stops: Record<string, Stop>;
  routePatterns: Record<string, OperationalRoutePattern>;
  trips: Record<string, OperationalTrip>;
  stopTimetables: Record<string, StopTimetable>;
  indexes: OperationalIndexes;
};

type SubsequenceRange = {
  startStopIndex: number;
  endStopIndex: number;
};

function createTripsByServiceIndex(): TripsByService {
  return {
    weekday: [],
    saturday: [],
    holiday: [],
    unknown: [],
  };
}

function firstTripTime(trip: Trip): string {
  for (const stopTime of trip.stop_times) {
    if (stopTime.departure) {
      return stopTime.departure;
    }
    if (stopTime.arrival) {
      return stopTime.arrival;
    }
  }
  return "";
}

function sortTripIds(ids: string[], trips: Record<string, Trip>): void {
  ids.sort((a, b) => {
    const timeA = firstTripTime(trips[a]);
    const timeB = firstTripTime(trips[b]);
    return timeA.localeCompare(timeB) || a.localeCompare(b);
  });
}

function sumDistanceSegments(segments: RouteSegment[]): {
  total_distance_km?: number;
  coveredSegments: number;
  totalSegments: number;
} {
  let total = 0;
  let coveredSegments = 0;

  for (const segment of segments) {
    if (segment.distance_km != null) {
      total += segment.distance_km;
      coveredSegments += 1;
    }
  }

  if (segments.length === 0) {
    return {
      total_distance_km: 0,
      coveredSegments: 0,
      totalSegments: 0,
    };
  }

  return {
    total_distance_km: coveredSegments > 0 ? total : undefined,
    coveredSegments,
    totalSegments: segments.length,
  };
}

export function findSubsequenceRange(
  patternStops: string[],
  tripStops: string[]
): SubsequenceRange | null {
  if (!patternStops.length || !tripStops.length) {
    return null;
  }
  if (tripStops.length > patternStops.length) {
    return null;
  }

  for (let startStopIndex = 0; startStopIndex + tripStops.length <= patternStops.length; startStopIndex += 1) {
    let matches = true;
    for (let offset = 0; offset < tripStops.length; offset += 1) {
      if (patternStops[startStopIndex + offset] !== tripStops[offset]) {
        matches = false;
        break;
      }
    }
    if (matches) {
      return {
        startStopIndex,
        endStopIndex: startStopIndex + tripStops.length - 1,
      };
    }
  }

  return null;
}

function enrichRoutePatterns(
  routePatterns: Record<string, RoutePattern>
): Record<string, OperationalRoutePattern> {
  const out: Record<string, OperationalRoutePattern> = {};

  for (const [patternId, pattern] of Object.entries(routePatterns)) {
    const summary = sumDistanceSegments(pattern.segments);
    const distance_coverage_ratio =
      summary.totalSegments === 0
        ? 1
        : summary.coveredSegments / summary.totalSegments;

    out[patternId] = {
      ...pattern,
      total_distance_km: summary.total_distance_km,
      distance_coverage_ratio,
    };
  }

  return out;
}

function estimateTripDistance(
  trip: Trip,
  pattern: OperationalRoutePattern | undefined
): Pick<OperationalTrip, "estimated_distance_km" | "distance_source"> {
  if (!pattern) {
    return { distance_source: "unknown" };
  }

  const tripStops = trip.stop_times.map((stopTime) => stopTime.stop_id);
  const range = findSubsequenceRange(pattern.stop_sequence, tripStops);
  if (!range) {
    return { distance_source: "unknown" };
  }

  const relevantSegments = pattern.segments.slice(
    range.startStopIndex,
    range.endStopIndex
  );

  const hasMissingDistance = relevantSegments.some(
    (segment) => segment.distance_km == null
  );
  if (hasMissingDistance) {
    return { distance_source: "unknown" };
  }

  const estimated_distance_km = relevantSegments.reduce(
    (sum, segment) => sum + (segment.distance_km ?? 0),
    0
  );

  const distance_source =
    range.startStopIndex === 0 &&
    range.endStopIndex === pattern.stop_sequence.length - 1
      ? "pattern_segments"
      : "partial_pattern_segments";

  return {
    estimated_distance_km,
    distance_source,
  };
}

function enrichTrips(
  trips: Record<string, Trip>,
  routePatterns: Record<string, OperationalRoutePattern>
): Record<string, OperationalTrip> {
  const out: Record<string, OperationalTrip> = {};

  for (const [tripId, trip] of Object.entries(trips)) {
    out[tripId] = {
      ...trip,
      ...estimateTripDistance(trip, routePatterns[trip.pattern_id]),
    };
  }

  return out;
}

function buildIndexes(trips: Record<string, OperationalTrip>): OperationalIndexes {
  const tripsByService = createTripsByServiceIndex();
  const tripsByPattern: Record<string, string[]> = {};

  for (const [tripId, trip] of Object.entries(trips)) {
    tripsByService[trip.service_id].push(tripId);

    if (!tripsByPattern[trip.pattern_id]) {
      tripsByPattern[trip.pattern_id] = [];
    }
    tripsByPattern[trip.pattern_id].push(tripId);
  }

  for (const ids of Object.values(tripsByService)) {
    sortTripIds(ids, trips);
  }
  for (const ids of Object.values(tripsByPattern)) {
    sortTripIds(ids, trips);
  }

  return { tripsByService, tripsByPattern };
}

export function enrichOperationalData(
  dataset: NormalizedDataset
): OperationalDataset {
  const routePatterns = enrichRoutePatterns(dataset.routePatterns);
  const trips = enrichTrips(dataset.trips, routePatterns);
  const indexes = buildIndexes(trips);

  return {
    stops: dataset.stops,
    routePatterns,
    trips,
    stopTimetables: dataset.stopTimetables,
    indexes,
  };
}
