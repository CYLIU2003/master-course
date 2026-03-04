import type { HHMMTime, MinutesFromMidnight } from "@/types";

/**
 * Convert HH:MM string to minutes from midnight.
 * Mirrors Python backend's hhmm_to_min().
 */
export function hhmmToMin(hhmm: HHMMTime): MinutesFromMidnight {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

/**
 * Convert minutes from midnight to HH:MM string.
 * Mirrors Python backend's min_to_hhmm().
 */
export function minToHhmm(minutes: MinutesFromMidnight): HHMMTime {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/**
 * Format duration in minutes as "Xh Ym" or "Ym".
 */
export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/**
 * Validate HH:MM format. Returns true if valid.
 */
export function isValidHhmm(value: string): boolean {
  return /^\d{2}:\d{2}$/.test(value) && hhmmToMin(value) < 1440;
}
