"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ALLOWED_RESOURCES = exports.ODPT_BASE = void 0;
// ODPT API base URL and SSRF-guard allowlist
exports.ODPT_BASE = "https://api.odpt.org/api/v4/";
exports.ALLOWED_RESOURCES = new Set([
    "odpt:BusroutePattern",
    "odpt:BusstopPole",
    "odpt:BusTimetable",
    "odpt:BusstopPoleTimetable",
]);
