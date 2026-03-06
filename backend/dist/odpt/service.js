"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeService = normalizeService;
function normalizeService(calendarRaw) {
    if (!calendarRaw) {
        return "unknown";
    }
    const normalized = calendarRaw.toLowerCase();
    if (normalized.includes("weekday")) {
        return "weekday";
    }
    if (normalized.includes("saturday")) {
        return "saturday";
    }
    if (normalized.includes("holiday") ||
        normalized.includes("sunday") ||
        normalized.includes("sundayholiday")) {
        return "holiday";
    }
    return "unknown";
}
