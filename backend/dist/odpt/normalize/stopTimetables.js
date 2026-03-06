"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeStopTimetables = normalizeStopTimetables;
const service_1 = require("../service");
function normalizeStopTimetables(raw) {
    const out = {};
    for (const item of raw) {
        const record = item;
        const timetable_id = (record["owl:sameAs"] ?? record["@id"]);
        const stop_id = record["odpt:busstopPole"];
        if (!timetable_id || !stop_id) {
            continue;
        }
        const calendar = record["odpt:calendar"];
        const service_id = (0, service_1.normalizeService)(calendar);
        const objects = record["odpt:busstopPoleTimetableObject"] ??
            [];
        const items = objects
            .slice()
            .sort((a, b) => Number(a["odpt:index"] ?? 0) -
            Number(b["odpt:index"] ?? 0))
            .map((obj) => ({
            index: Number(obj["odpt:index"] ?? 0),
            arrival: obj["odpt:arrivalTime"],
            departure: obj["odpt:departureTime"],
            busroutePattern: obj["odpt:busroutePattern"],
            busTimetable: obj["odpt:busTimetable"],
            destinationSign: obj["odpt:destinationSign"],
        }));
        out[timetable_id] = {
            timetable_id,
            stop_id,
            calendar,
            service_id,
            items,
        };
    }
    return out;
}
