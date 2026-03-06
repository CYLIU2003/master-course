// ODPT API base URL and SSRF-guard allowlist
export const ODPT_BASE = "https://api.odpt.org/api/v4/";

export const ALLOWED_RESOURCES = new Set([
  "odpt:BusroutePattern",
  "odpt:BusstopPole",
  "odpt:BusTimetable",
  "odpt:BusstopPoleTimetable",
]);
