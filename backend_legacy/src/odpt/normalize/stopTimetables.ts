import type { NormalizedService } from "../service";
import { normalizeService } from "../service";

type RawRecord = Record<string, unknown>;
type RawTimeObj = Record<string, unknown>;

export type StopTimetableItem = {
  index: number;
  arrival?: string;
  departure?: string;
  busroutePattern?: string;
  busTimetable?: string;
  destinationSign?: string;
};

export type StopTimetable = {
  timetable_id: string;
  stop_id: string;
  calendar?: string;
  service_id: NormalizedService;
  items: StopTimetableItem[];
};

export function normalizeStopTimetables(
  raw: unknown[],
): Record<string, StopTimetable> {
  const out: Record<string, StopTimetable> = {};

  for (const item of raw) {
    const record = item as RawRecord;
    const timetable_id =
      (record["owl:sameAs"] ?? record["@id"]) as string | undefined;
    const stop_id = record["odpt:busstopPole"] as string | undefined;
    if (!timetable_id || !stop_id) {
      continue;
    }

    const calendar = record["odpt:calendar"] as string | undefined;
    const service_id = normalizeService(calendar);
    const objects =
      (record["odpt:busstopPoleTimetableObject"] as RawTimeObj[] | undefined) ??
      [];

    const items: StopTimetableItem[] = objects
      .slice()
      .sort(
        (a, b) =>
          Number((a["odpt:index"] as number | string | undefined) ?? 0) -
          Number((b["odpt:index"] as number | string | undefined) ?? 0),
      )
      .map((obj) => ({
        index: Number((obj["odpt:index"] as number | string | undefined) ?? 0),
        arrival: obj["odpt:arrivalTime"] as string | undefined,
        departure: obj["odpt:departureTime"] as string | undefined,
        busroutePattern: obj["odpt:busroutePattern"] as string | undefined,
        busTimetable: obj["odpt:busTimetable"] as string | undefined,
        destinationSign: obj["odpt:destinationSign"] as string | undefined,
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
