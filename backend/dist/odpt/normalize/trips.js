"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeTrips = normalizeTrips;
const service_1 = require("../service");
/**
 * Returns true if `tripStops` is a contiguous subsequence of `patternStops`.
 * Used to flag short-working / part-route trips as is_partial.
 */
function isContiguousSubsequence(patternStops, tripStops) {
    if (!patternStops.length || !tripStops.length)
        return false;
    if (tripStops.length > patternStops.length)
        return false;
    for (let i = 0; i + tripStops.length <= patternStops.length; i++) {
        let ok = true;
        for (let j = 0; j < tripStops.length; j++) {
            if (patternStops[i + j] !== tripStops[j]) {
                ok = false;
                break;
            }
        }
        if (ok)
            return true;
    }
    return false;
}
function normalizeTrips(raw, patterns) {
    const out = {};
    for (const item of raw) {
        const r = item;
        const trip_id = (r["owl:sameAs"] ?? r["@id"]);
        if (!trip_id)
            continue;
        const pattern_id = r["odpt:busroutePattern"];
        const calendar = r["odpt:calendar"];
        const service_id = (0, service_1.normalizeService)(calendar);
        const objs = r["odpt:busTimetableObject"] ?? [];
        const stop_times = objs
            .slice()
            .sort((a, b) => Number(a["odpt:index"] ?? 0) -
            Number(b["odpt:index"] ?? 0))
            .map((o) => ({
            index: Number(o["odpt:index"] ?? 0),
            stop_id: o["odpt:busstopPole"],
            arrival: o["odpt:arrivalTime"],
            departure: o["odpt:departureTime"],
        }))
            .filter((x) => Boolean(x.stop_id));
        const tripStops = stop_times.map((x) => x.stop_id);
        const patternStops = pattern_id
            ? (patterns[pattern_id]?.stop_sequence ?? [])
            : [];
        const is_partial = patternStops.length > 0 &&
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
