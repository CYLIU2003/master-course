import express, { Request, Response } from "express";
import dotenv from "dotenv";
import fs from "node:fs";
import path from "node:path";
import { writeFile, mkdir } from "node:fs/promises";

import { odptProxy } from "./odpt/proxy";
import { introspectRecords } from "./odpt/introspect";
import { enrichOperationalData } from "./odpt/enrich";
import { normalizeAll } from "./odpt/normalize/index";
import type { NormalizedDataset } from "./odpt/normalize/index";

dotenv.config();

const app = express();
app.use(express.json({ limit: "10mb" }));

// ── Token guard ───────────────────────────────────────────────────────────────
const token = process.env.ODPT_TOKEN;
if (!token) {
  console.error(
    "ERROR: ODPT_TOKEN environment variable is missing.\n" +
      "Copy backend/.env.example to backend/.env and set your token."
  );
  process.exit(1);
}

// ── Config ────────────────────────────────────────────────────────────────────
const cfgPath = path.join(process.cwd(), "config", "odpt_sources.json");
const _cfg = JSON.parse(fs.readFileSync(cfgPath, "utf-8")); // loaded for future use
const DEFAULT_OPERATOR = "odpt.Operator:TokyuBus";

// ── CORS (allow Vite dev server) ──────────────────────────────────────────────
app.use((_req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  next();
});

// ── Routes ────────────────────────────────────────────────────────────────────

type NormalizedRequestOptions = {
  dump: boolean;
  operator: string;
  forceRefresh: boolean;
  ttlSec: number;
  includeBusTimetables: boolean;
  includeStopTimetables: boolean;
  chunkBusTimetables: boolean;
  chunkStopTimetables: boolean;
  busTimetableCursor: number;
  busTimetableBatchSize: number;
  stopTimetableCursor: number;
  stopTimetableBatchSize: number;
};

type FetchProgressMeta = {
  cursor: number;
  nextCursor: number;
  totalChunks: number;
  complete: boolean;
};

type ProxyAggregateMeta = {
  cacheHit: boolean;
  maybeTruncated: boolean;
  chunkCount: number;
  truncatedChunkCount: number;
  fallbackUsed?: boolean;
  failedChunkCount?: number;
  progress?: FetchProgressMeta;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toTtlSec(value: unknown, fallback = 3600): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function toPositiveInt(value: unknown, fallback: number, max = 1000): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.min(Math.floor(parsed), max);
}

function toNonNegativeInt(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback;
  }
  return Math.floor(parsed);
}

async function fetchNormalizedDataset(options: NormalizedRequestOptions) {
  const query = `odpt:operator=${options.operator}`;

  const [stopsResult, patternsResult] = await Promise.all([
    odptProxy({
      resource: "odpt:BusstopPole",
      query,
      dump: options.dump,
      token: token!,
      forceRefresh: options.forceRefresh,
      ttlSec: options.ttlSec,
    }),
    odptProxy({
      resource: "odpt:BusroutePattern",
      query,
      dump: options.dump,
      token: token!,
      forceRefresh: options.forceRefresh,
      ttlSec: options.ttlSec,
    }),
  ]);

  const stopTimetablesResult = options.includeStopTimetables
    ? await fetchStopTimetablesDataset(query, stopsResult.data, options)
    : {
        data: [],
        meta: {
          cacheHit: false,
          maybeTruncated: false,
          chunkCount: 0,
          truncatedChunkCount: 0,
          fallbackUsed: false,
        },
      };
  const timetablesResult = options.includeBusTimetables
    ? await fetchTimetablesDataset(query, patternsResult.data, options)
    : {
        data: [],
        meta: {
          cacheHit: false,
          maybeTruncated: false,
          chunkCount: 0,
          truncatedChunkCount: 0,
          fallbackUsed: false,
          failedChunkCount: 0,
        },
      };

  const normalized = normalizeAll({
    stopsRaw: stopsResult.data,
    patternsRaw: patternsResult.data,
    timetablesRaw: timetablesResult.data,
    stopTimetablesRaw: stopTimetablesResult.data,
  });

  const warnings: string[] = [
    stopsResult.meta.maybeTruncated
      ? "BusstopPole maybe truncated (1000 limit) - try dump=1"
      : null,
    patternsResult.meta.maybeTruncated
      ? "BusroutePattern maybe truncated (1000 limit) - try dump=1"
      : null,
    stopTimetablesResult.meta.maybeTruncated
      ? "BusstopPoleTimetable maybe truncated (1000 limit) - try dump=1"
      : null,
    stopTimetablesResult.meta.fallbackUsed
      ? "BusstopPoleTimetable fetched with fallback strategy"
      : null,
    (stopTimetablesResult.meta.failedChunkCount ?? 0) > 0
      ? `BusstopPoleTimetable skipped ${stopTimetablesResult.meta.failedChunkCount} chunk(s)`
      : null,
    timetablesResult.meta.maybeTruncated
      ? `BusTimetable maybe truncated in ${timetablesResult.meta.truncatedChunkCount}/${timetablesResult.meta.chunkCount} chunks`
      : null,
    timetablesResult.meta.fallbackUsed
      ? "BusTimetable fetched with fallback operator query"
      : null,
    (timetablesResult.meta.failedChunkCount ?? 0) > 0
      ? `BusTimetable skipped ${timetablesResult.meta.failedChunkCount} chunk(s)`
      : null,
  ].filter((warning): warning is string => warning !== null);

  const meta = {
    generatedAt: new Date().toISOString(),
    operator: options.operator,
    dump: options.dump,
    cache: {
      stops: stopsResult.meta.cacheHit,
      patterns: patternsResult.meta.cacheHit,
      stopTimetables: stopTimetablesResult.meta.cacheHit,
      timetables: timetablesResult.meta.cacheHit,
      timetableChunks: timetablesResult.meta.chunkCount,
    },
    progress: {
      busTimetables: timetablesResult.meta.progress,
      stopTimetables: stopTimetablesResult.meta.progress,
    },
    warnings,
    counts: {
      stops: Object.keys(normalized.stops).length,
      routePatterns: Object.keys(normalized.routePatterns).length,
      trips: Object.keys(normalized.trips).length,
      stopTimetables: Object.keys(normalized.stopTimetables).length,
    },
  };

  return { meta, normalized };
}

function getRawRecordId(record: unknown): string | null {
  if (!record || typeof record !== "object") {
    return null;
  }

  const candidate = record as Record<string, unknown>;
  const value = candidate["owl:sameAs"] ?? candidate["@id"];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function uniqueStringValues(values: Iterable<string | undefined | null>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];

  for (const value of values) {
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    out.push(value);
  }

  return out;
}

function buildTimetableQueries(baseQuery: string, patternsRaw: unknown[]): string[] {
  if (!Array.isArray(patternsRaw) || patternsRaw.length === 0) {
    return [baseQuery];
  }

  const records = patternsRaw.filter(
    (item): item is Record<string, unknown> => !!item && typeof item === "object",
  );
  const patternQueries = uniqueStringValues(
    records.map((record) => {
      const patternId = record["owl:sameAs"] ?? record["@id"];
      return typeof patternId === "string" ? patternId : undefined;
    }),
  ).map((patternId) => `${baseQuery}&odpt:busroutePattern=${patternId}`);

  return patternQueries.length > 0 ? patternQueries : [baseQuery];
}

function buildStopTimetableQueries(baseQuery: string, stopsRaw: unknown[]): string[] {
  if (!Array.isArray(stopsRaw) || stopsRaw.length === 0) {
    return [baseQuery];
  }

  const stopIds = uniqueStringValues(
    stopsRaw.map((record) => getRawRecordId(record)),
  );
  return stopIds.length > 0
    ? stopIds.map((stopId) => `${baseQuery}&odpt:busstopPole=${stopId}`)
    : [baseQuery];
}

function sliceQueries(
  queries: string[],
  cursor: number,
  batchSize: number,
): { selected: string[]; progress: FetchProgressMeta } {
  const safeCursor = Math.min(Math.max(cursor, 0), queries.length);
  const safeBatchSize = Math.max(batchSize, 1);
  const nextCursor = Math.min(safeCursor + safeBatchSize, queries.length);
  return {
    selected: queries.slice(safeCursor, nextCursor),
    progress: {
      cursor: safeCursor,
      nextCursor,
      totalChunks: queries.length,
      complete: nextCursor >= queries.length,
    },
  };
}

async function fetchSingleProxyDataset(
  resource: string,
  query: string,
  options: NormalizedRequestOptions,
): Promise<{ data: unknown[]; meta: ProxyAggregateMeta }> {
  const result = await odptProxy({
    resource,
    query,
    dump: options.dump,
    token: token!,
    forceRefresh: options.forceRefresh,
    ttlSec: options.ttlSec,
  });
  return {
    data: result.data,
    meta: {
      cacheHit: result.meta.cacheHit,
      maybeTruncated: result.meta.maybeTruncated,
      chunkCount: 1,
      truncatedChunkCount: result.meta.maybeTruncated ? 1 : 0,
      fallbackUsed: false,
      failedChunkCount: 0,
    },
  };
}

async function fetchTimetablesDataset(
  baseQuery: string,
  patternsRaw: unknown[],
  options: NormalizedRequestOptions,
): Promise<{ data: unknown[]; meta: ProxyAggregateMeta }> {
  if (options.dump) {
    return fetchSingleProxyDataset("odpt:BusTimetable", baseQuery, options);
  }

  if (!options.chunkBusTimetables) {
    return fetchSingleProxyDataset(
      "odpt:BusTimetable",
      baseQuery,
      { ...options, dump: false },
    );
  }

  const queries = buildTimetableQueries(baseQuery, patternsRaw);
  const { selected, progress } = sliceQueries(
    queries,
    options.busTimetableCursor,
    options.busTimetableBatchSize,
  );
  const results = [];
  let failedChunkCount = 0;
  for (const query of selected) {
    try {
      const result = await odptProxy({
        resource: "odpt:BusTimetable",
        query,
        dump: false,
        token: token!,
        forceRefresh: options.forceRefresh,
        ttlSec: options.ttlSec,
      });
      results.push(result);
    } catch {
      failedChunkCount += 1;
    }
    await sleep(150);
  }

  if (results.length === 0 && selected.length > 0) {
    const fallback = await fetchSingleProxyDataset(
      "odpt:BusTimetable",
      baseQuery,
      { ...options, dump: false },
    );
    return {
      data: fallback.data,
      meta: {
        ...fallback.meta,
        fallbackUsed: true,
        failedChunkCount,
        progress,
      },
    };
  }

  const seenTripIds = new Set<string>();
  const merged: unknown[] = [];
  let truncatedChunkCount = 0;

  for (const result of results) {
    if (result.meta.maybeTruncated) {
      truncatedChunkCount += 1;
    }
    for (const record of result.data) {
      const recordId = getRawRecordId(record);
      if (!recordId) {
        merged.push(record);
        continue;
      }
      if (seenTripIds.has(recordId)) {
        continue;
      }
      seenTripIds.add(recordId);
      merged.push(record);
    }
  }

  return {
    data: merged,
    meta: {
      cacheHit: results.every((result) => result.meta.cacheHit),
      maybeTruncated: truncatedChunkCount > 0,
      chunkCount: selected.length,
      truncatedChunkCount,
      fallbackUsed: false,
      failedChunkCount,
      progress,
    },
  };
}

async function fetchStopTimetablesDataset(
  baseQuery: string,
  stopsRaw: unknown[],
  options: NormalizedRequestOptions,
): Promise<{ data: unknown[]; meta: ProxyAggregateMeta }> {
  if (!options.chunkStopTimetables) {
    try {
      return await fetchSingleProxyDataset(
        "odpt:BusstopPoleTimetable",
        baseQuery,
        options,
      );
    } catch {
      // Fall through to chunked stop-level retrieval.
    }
  }

  const queries = buildStopTimetableQueries(baseQuery, stopsRaw);
  const { selected, progress } = sliceQueries(
    queries,
    options.stopTimetableCursor,
    options.stopTimetableBatchSize,
  );
  const results = [];
  let failedChunkCount = 0;
  try {
    for (const query of selected) {
      try {
        const result = await odptProxy({
          resource: "odpt:BusstopPoleTimetable",
          query,
          dump: false,
          token: token!,
          forceRefresh: options.forceRefresh,
          ttlSec: options.ttlSec,
        });
        results.push(result);
      } catch {
        failedChunkCount += 1;
      }
      await sleep(100);
    }

    const seenIds = new Set<string>();
    const merged: unknown[] = [];
    let truncatedChunkCount = 0;
    for (const result of results) {
      if (result.meta.maybeTruncated) {
        truncatedChunkCount += 1;
      }
      for (const record of result.data) {
        const recordId = getRawRecordId(record);
        if (!recordId) {
          merged.push(record);
          continue;
        }
        if (seenIds.has(recordId)) {
          continue;
        }
        seenIds.add(recordId);
        merged.push(record);
      }
    }

    return {
      data: merged,
      meta: {
        cacheHit: results.length > 0 && results.every((result) => result.meta.cacheHit),
        maybeTruncated: truncatedChunkCount > 0,
        chunkCount: selected.length,
        truncatedChunkCount,
        fallbackUsed: true,
        failedChunkCount,
        progress,
      },
    };
  } catch {
    return {
      data: [],
      meta: {
        cacheHit: false,
        maybeTruncated: false,
        chunkCount: selected.length,
        truncatedChunkCount: 0,
        fallbackUsed: true,
        failedChunkCount: selected.length,
        progress,
      },
    };
  }
}

async function fetchOperationalDataset(options: NormalizedRequestOptions) {
  const { meta, normalized } = await fetchNormalizedDataset(options);
  const operational = enrichOperationalData(normalized);
  return { meta, normalized, operational };
}

function filterNormalizedForOperationalStage(
  normalized: NormalizedDataset,
): NormalizedDataset {
  const patternIds = new Set<string>();
  const stopIds = new Set<string>();

  for (const trip of Object.values(normalized.trips)) {
    patternIds.add(trip.pattern_id);
    for (const stopTime of trip.stop_times) {
      stopIds.add(stopTime.stop_id);
    }
  }

  const routePatterns = Object.fromEntries(
    Object.entries(normalized.routePatterns).filter(([patternId]) =>
      patternIds.has(patternId),
    ),
  );

  for (const pattern of Object.values(routePatterns)) {
    for (const stopId of pattern.stop_sequence) {
      stopIds.add(stopId);
    }
  }

  const stops = Object.fromEntries(
    Object.entries(normalized.stops).filter(([stopId]) => stopIds.has(stopId)),
  );

  return {
    stops,
    routePatterns,
    trips: normalized.trips,
    stopTimetables: {},
  };
}

function filterNormalizedForStopTimetableStage(
  normalized: NormalizedDataset,
): NormalizedDataset {
  const stopIds = new Set<string>();
  for (const item of Object.values(normalized.stopTimetables)) {
    stopIds.add(item.stop_id);
  }

  return {
    stops: Object.fromEntries(
      Object.entries(normalized.stops).filter(([stopId]) => stopIds.has(stopId)),
    ),
    routePatterns: {},
    trips: {},
    stopTimetables: normalized.stopTimetables,
  };
}

function parseNormalizedRequest(req: Request): NormalizedRequestOptions {
  return {
    dump: Boolean(req.body?.dump ?? true),
    operator: String(req.body?.operator ?? DEFAULT_OPERATOR),
    forceRefresh: Boolean(req.body?.forceRefresh ?? false),
    ttlSec: toTtlSec(req.body?.ttlSec),
    includeBusTimetables: Boolean(req.body?.includeBusTimetables ?? true),
    includeStopTimetables: Boolean(req.body?.includeStopTimetables ?? false),
    chunkBusTimetables: Boolean(req.body?.chunkBusTimetables ?? false),
    chunkStopTimetables: Boolean(req.body?.chunkStopTimetables ?? false),
    busTimetableCursor: toNonNegativeInt(req.body?.busTimetableCursor),
    busTimetableBatchSize: toPositiveInt(req.body?.busTimetableBatchSize, 25, 250),
    stopTimetableCursor: toNonNegativeInt(req.body?.stopTimetableCursor),
    stopTimetableBatchSize: toPositiveInt(req.body?.stopTimetableBatchSize, 25, 250),
  };
}

/**
 * GET /api/odpt/proxy
 *
 * Query params:
 *   resource  — ODPT resource name (must be in ALLOWED_RESOURCES)
 *   query     — raw query string forwarded to ODPT (e.g. "odpt:operator=...")
 *   dump      — "1" to use the .json full-dump endpoint
 *   forceRefresh — "1" to bypass local cache
 *   ttlSec    — cache TTL in seconds
 */
app.get("/api/odpt/proxy", async (req: Request, res: Response) => {
  try {
    const resource = String(req.query["resource"] ?? "");
    const query = String(req.query["query"] ?? "");
    const dump = String(req.query["dump"] ?? "0") === "1";
    const forceRefresh = String(req.query["forceRefresh"] ?? "0") === "1";
    const ttlSec = toTtlSec(req.query["ttlSec"]);

    const result = await odptProxy({
      resource,
      query,
      dump,
      token: token!,
      forceRefresh,
      ttlSec,
    });
    res.json(result);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    res.status(400).json({ error: msg });
  }
});

/**
 * POST /api/odpt/introspect
 *
 * Body: { records: any[] }
 *
 * Returns field-level statistics: path, types breakdown, presentRate.
 */
app.post("/api/odpt/introspect", (req: Request, res: Response) => {
  try {
    const records = req.body?.records as unknown;
    if (!Array.isArray(records)) {
      throw new Error("`records` must be an array");
    }
    res.json(introspectRecords(records));
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    res.status(400).json({ error: msg });
  }
});

/**
 * POST /api/odpt/export/normalized
 *
 * Fetches BusstopPole + BusroutePattern + BusTimetable for TokyuBus,
 * normalizes them to Stop / RoutePattern / Trip, and returns the result.
 */
app.post(
  "/api/odpt/export/normalized",
  async (req: Request, res: Response) => {
    try {
      const { meta, normalized } = await fetchNormalizedDataset(
        parseNormalizedRequest(req)
      );
      res.json({
        meta,
        ...normalized,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      res.status(400).json({ error: msg });
    }
  }
);

/**
 * POST /api/odpt/export/operational
 *
 * Fetches and normalizes ODPT data, then enriches it with route totals,
 * trip distance estimates, and service/pattern indexes.
 */
app.post(
  "/api/odpt/export/operational",
  async (req: Request, res: Response) => {
    try {
      const { meta, operational } = await fetchOperationalDataset(
        parseNormalizedRequest(req)
      );
      res.json({
        meta,
        ...operational,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      res.status(400).json({ error: msg });
    }
  }
);

app.post(
  "/api/odpt/export/operational-stage",
  async (req: Request, res: Response) => {
    try {
      const options = parseNormalizedRequest(req);
      const { meta, normalized } = await fetchNormalizedDataset({
        ...options,
        includeBusTimetables: true,
        chunkBusTimetables: true,
        includeStopTimetables: false,
      });
      const filtered = filterNormalizedForOperationalStage(normalized);
      const operational = enrichOperationalData(filtered);
      res.json({
        meta,
        ...operational,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      res.status(400).json({ error: msg });
    }
  }
);

app.post(
  "/api/odpt/export/stop-timetables-stage",
  async (req: Request, res: Response) => {
    try {
      const options = parseNormalizedRequest(req);
      const { meta, normalized } = await fetchNormalizedDataset({
        ...options,
        includeBusTimetables: false,
        includeStopTimetables: true,
        chunkStopTimetables: true,
      });
      const filtered = filterNormalizedForStopTimetableStage(normalized);
      res.json({
        meta,
        ...filtered,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      res.status(400).json({ error: msg });
    }
  }
);

/**
 * POST /api/odpt/export/save
 *
 * Fetches, normalizes, enriches, and writes both normalized and operational
 * datasets to data/odpt/tokyu relative to the project root.
 */
app.post(
  "/api/odpt/export/save",
  async (req: Request, res: Response) => {
    try {
      const { meta, normalized, operational } = await fetchOperationalDataset(
        parseNormalizedRequest(req)
      );

      const normalizedDataset = { meta, ...normalized };
      const operationalDataset = { meta, ...operational };

      // Write to <project-root>/data/odpt/tokyu/{normalized,operational}_dataset.json
      // cwd when running via `npm run dev` from backend/ is backend/,
      // so we go up one level to reach the project root.
      const outDir = path.resolve(process.cwd(), "..", "data", "odpt", "tokyu");
      await mkdir(outDir, { recursive: true });
      const normalizedOutPath = path.join(outDir, "normalized_dataset.json");
      const operationalOutPath = path.join(outDir, "operational_dataset.json");

      await Promise.all([
        writeFile(
          normalizedOutPath,
          JSON.stringify(normalizedDataset, null, 2),
          "utf-8"
        ),
        writeFile(
          operationalOutPath,
          JSON.stringify(operationalDataset, null, 2),
          "utf-8"
        ),
      ]);

      res.json({
        savedTo: operationalOutPath,
        normalizedSavedTo: normalizedOutPath,
        meta,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      res.status(400).json({ error: msg });
    }
  }
);

// ── Health check ──────────────────────────────────────────────────────────────
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "odpt-explorer-bff" });
});

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = Number(process.env.PORT ?? 3001);
app.listen(PORT, () => {
  console.log(`ODPT Explorer BFF listening on http://localhost:${PORT}`);
});
