"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeStops = normalizeStops;
function normalizeStops(raw) {
    const out = {};
    for (const item of raw) {
        const r = item;
        const stop_id = (r["owl:sameAs"] ?? r["@id"]);
        if (!stop_id)
            continue;
        out[stop_id] = {
            stop_id,
            name: r["dc:title"],
            lat: r["geo:lat"],
            lon: r["geo:long"],
            poleNumber: r["odpt:busstopPoleNumber"] ?? null,
        };
    }
    return out;
}
