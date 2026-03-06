"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeAll = normalizeAll;
const stops_1 = require("./stops");
const routePatterns_1 = require("./routePatterns");
const trips_1 = require("./trips");
const stopTimetables_1 = require("./stopTimetables");
function normalizeAll(input) {
    const stops = (0, stops_1.normalizeStops)(input.stopsRaw);
    const routePatterns = (0, routePatterns_1.normalizeRoutePatterns)(input.patternsRaw, stops);
    const trips = (0, trips_1.normalizeTrips)(input.timetablesRaw, routePatterns);
    const stopTimetables = (0, stopTimetables_1.normalizeStopTimetables)(input.stopTimetablesRaw);
    return { stops, routePatterns, trips, stopTimetables };
}
