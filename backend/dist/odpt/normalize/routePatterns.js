"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeRoutePatterns = normalizeRoutePatterns;
const geo_1 = require("../geo");
function normalizeRoutePatterns(raw, stops) {
    const out = {};
    for (const item of raw) {
        const r = item;
        const pattern_id = (r["owl:sameAs"] ?? r["@id"]);
        if (!pattern_id)
            continue;
        const orders = r["odpt:busstopPoleOrder"] ?? [];
        // Sort by odpt:index (ascending) then extract odpt:busstopPole refs
        const stop_sequence = orders
            .slice()
            .sort((a, b) => Number(a["odpt:index"] ?? 0) -
            Number(b["odpt:index"] ?? 0))
            .map((o) => o["odpt:busstopPole"])
            .filter((s) => Boolean(s));
        const segments = [];
        for (let i = 0; i < stop_sequence.length - 1; i++) {
            const from_stop_id = stop_sequence[i];
            const to_stop_id = stop_sequence[i + 1];
            const fromStop = stops[from_stop_id];
            const toStop = stops[to_stop_id];
            let distance_km;
            if (fromStop?.lat != null &&
                fromStop?.lon != null &&
                toStop?.lat != null &&
                toStop?.lon != null) {
                distance_km = (0, geo_1.haversineKm)(fromStop.lat, fromStop.lon, toStop.lat, toStop.lon);
            }
            segments.push({ from_stop_id, to_stop_id, distance_km });
        }
        out[pattern_id] = {
            pattern_id,
            title: r["dc:title"],
            note: r["odpt:note"],
            busroute: r["odpt:busroute"],
            stop_sequence,
            segments,
        };
    }
    return out;
}
