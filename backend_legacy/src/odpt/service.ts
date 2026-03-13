export type NormalizedService =
  | "weekday"
  | "saturday"
  | "saturdayholiday"
  | "holiday"
  | "unknown";

export function normalizeService(calendarRaw?: string): NormalizedService {
  if (!calendarRaw) {
    return "unknown";
  }

  const normalized = calendarRaw.toLowerCase();

  if (
    normalized.includes("saturdayholiday") ||
    (normalized.includes("saturday") && normalized.includes("holiday"))
  ) {
    return "saturdayholiday";
  }
  if (normalized.includes("weekday")) {
    return "weekday";
  }
  if (normalized.includes("saturday")) {
    return "saturday";
  }
  if (
    normalized.includes("holiday") ||
    normalized.includes("sunday") ||
    normalized.includes("sundayholiday")
  ) {
    return "holiday";
  }

  return "unknown";
}
