import { Stop } from "./index";

type RawRecord = Record<string, unknown>;

export function normalizeStops(raw: unknown[]): Record<string, Stop> {
  const out: Record<string, Stop> = {};

  for (const item of raw) {
    const r = item as RawRecord;
    const stop_id = (r["owl:sameAs"] ?? r["@id"]) as string | undefined;
    if (!stop_id) continue;

    out[stop_id] = {
      stop_id,
      name: r["dc:title"] as string | undefined,
      lat: r["geo:lat"] as number | undefined,
      lon: r["geo:long"] as number | undefined,
      poleNumber: (r["odpt:busstopPoleNumber"] as string | null | undefined) ?? null,
    };
  }

  return out;
}
