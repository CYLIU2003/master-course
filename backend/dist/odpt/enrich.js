"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.findSubsequenceRange = findSubsequenceRange;
exports.enrichOperationalData = enrichOperationalData;
function createTripsByServiceIndex() {
    return {
        weekday: [],
        saturday: [],
        holiday: [],
        unknown: [],
    };
}
function firstTripTime(trip) {
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
function sortTripIds(ids, trips) {
    ids.sort((a, b) => {
        const timeA = firstTripTime(trips[a]);
        const timeB = firstTripTime(trips[b]);
        return timeA.localeCompare(timeB) || a.localeCompare(b);
    });
}
function sumDistanceSegments(segments) {
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
function findSubsequenceRange(patternStops, tripStops) {
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
function enrichRoutePatterns(routePatterns) {
    const out = {};
    for (const [patternId, pattern] of Object.entries(routePatterns)) {
        const summary = sumDistanceSegments(pattern.segments);
        const distance_coverage_ratio = summary.totalSegments === 0
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
function estimateTripDistance(trip, pattern) {
    if (!pattern) {
        return { distance_source: "unknown" };
    }
    const tripStops = trip.stop_times.map((stopTime) => stopTime.stop_id);
    const range = findSubsequenceRange(pattern.stop_sequence, tripStops);
    if (!range) {
        return { distance_source: "unknown" };
    }
    const relevantSegments = pattern.segments.slice(range.startStopIndex, range.endStopIndex);
    const hasMissingDistance = relevantSegments.some((segment) => segment.distance_km == null);
    if (hasMissingDistance) {
        return { distance_source: "unknown" };
    }
    const estimated_distance_km = relevantSegments.reduce((sum, segment) => sum + (segment.distance_km ?? 0), 0);
    const distance_source = range.startStopIndex === 0 &&
        range.endStopIndex === pattern.stop_sequence.length - 1
        ? "pattern_segments"
        : "partial_pattern_segments";
    return {
        estimated_distance_km,
        distance_source,
    };
}
function enrichTrips(trips, routePatterns) {
    const out = {};
    for (const [tripId, trip] of Object.entries(trips)) {
        out[tripId] = {
            ...trip,
            ...estimateTripDistance(trip, routePatterns[trip.pattern_id]),
        };
    }
    return out;
}
function buildIndexes(trips) {
    const tripsByService = createTripsByServiceIndex();
    const tripsByPattern = {};
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
function enrichOperationalData(dataset) {
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
