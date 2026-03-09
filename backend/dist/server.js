"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const dotenv_1 = __importDefault(require("dotenv"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const promises_1 = require("node:fs/promises");
const proxy_1 = require("./odpt/proxy");
const introspect_1 = require("./odpt/introspect");
const enrich_1 = require("./odpt/enrich");
const routeTimetables_1 = require("./odpt/routeTimetables");
const index_1 = require("./odpt/normalize/index");
const runtimePaths_1 = require("./runtimePaths");
dotenv_1.default.config({ path: node_path_1.default.resolve(__dirname, "../.env") });
dotenv_1.default.config();
const app = (0, express_1.default)();
app.use(express_1.default.json({ limit: "10mb" }));
// ── Token guard ───────────────────────────────────────────────────────────────
const token = process.env.ODPT_TOKEN ?? process.env.ODPT_CONSUMER_KEY;
if (!token) {
    console.error("ERROR: ODPT_TOKEN / ODPT_CONSUMER_KEY environment variable is missing.\n" +
        "Set it in backend/.env, repo .env, or your shell environment.");
    process.exit(1);
}
// ── Config ────────────────────────────────────────────────────────────────────
const cfgPath = node_path_1.default.join(process.cwd(), "config", "odpt_sources.json");
const _cfg = JSON.parse(node_fs_1.default.readFileSync(cfgPath, "utf-8")); // loaded for future use
const DEFAULT_OPERATOR = "odpt.Operator:TokyuBus";
// ── CORS (allow Vite dev server) ──────────────────────────────────────────────
app.use((_req, res, next) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
    next();
});
function getSnapshotStatus() {
    const snapshotDir = (0, runtimePaths_1.resolveRuntimePath)("odpt_snapshot_dir");
    const operationalPath = node_path_1.default.join(snapshotDir, "operational_dataset.json");
    const routeTimetablesPath = node_path_1.default.join(snapshotDir, "route_timetables_dataset.json");
    const available = node_fs_1.default.existsSync(operationalPath);
    return {
        available,
        snapshotDir,
        files: {
            operational_dataset_json: node_fs_1.default.existsSync(operationalPath),
            route_timetables_dataset_json: node_fs_1.default.existsSync(routeTimetablesPath),
        },
    };
}
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
function toTtlSec(value, fallback = 3600) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
function toPositiveInt(value, fallback, max = 1000) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
        return fallback;
    }
    return Math.min(Math.floor(parsed), max);
}
function toNonNegativeInt(value, fallback = 0) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return fallback;
    }
    return Math.floor(parsed);
}
async function fetchNormalizedDataset(options) {
    const query = `odpt:operator=${options.operator}`;
    const [stopsResult, patternsResult] = await Promise.all([
        (0, proxy_1.odptProxy)({
            resource: "odpt:BusstopPole",
            query,
            dump: options.dump,
            token: token,
            forceRefresh: options.forceRefresh,
            ttlSec: options.ttlSec,
        }),
        (0, proxy_1.odptProxy)({
            resource: "odpt:BusroutePattern",
            query,
            dump: options.dump,
            token: token,
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
    const normalized = (0, index_1.normalizeAll)({
        stopsRaw: stopsResult.data,
        patternsRaw: patternsResult.data,
        timetablesRaw: timetablesResult.data,
        stopTimetablesRaw: stopTimetablesResult.data,
    });
    const warnings = [
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
    ].filter((warning) => warning !== null);
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
function getRawRecordId(record) {
    if (!record || typeof record !== "object") {
        return null;
    }
    const candidate = record;
    const value = candidate["owl:sameAs"] ?? candidate["@id"];
    return typeof value === "string" && value.length > 0 ? value : null;
}
function uniqueStringValues(values) {
    const seen = new Set();
    const out = [];
    for (const value of values) {
        if (!value || seen.has(value)) {
            continue;
        }
        seen.add(value);
        out.push(value);
    }
    return out;
}
function buildTimetableQueries(baseQuery, patternsRaw) {
    if (!Array.isArray(patternsRaw) || patternsRaw.length === 0) {
        return [baseQuery];
    }
    const records = patternsRaw.filter((item) => !!item && typeof item === "object");
    const patternQueries = uniqueStringValues(records.map((record) => {
        const patternId = record["owl:sameAs"] ?? record["@id"];
        return typeof patternId === "string" ? patternId : undefined;
    })).map((patternId) => `${baseQuery}&odpt:busroutePattern=${patternId}`);
    return patternQueries.length > 0 ? patternQueries : [baseQuery];
}
function buildStopTimetableQueries(baseQuery, stopsRaw) {
    if (!Array.isArray(stopsRaw) || stopsRaw.length === 0) {
        return [baseQuery];
    }
    const stopIds = uniqueStringValues(stopsRaw.map((record) => getRawRecordId(record)));
    return stopIds.length > 0
        ? stopIds.map((stopId) => `${baseQuery}&odpt:busstopPole=${stopId}`)
        : [baseQuery];
}
function sliceQueries(queries, cursor, batchSize) {
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
async function fetchSingleProxyDataset(resource, query, options) {
    const result = await (0, proxy_1.odptProxy)({
        resource,
        query,
        dump: options.dump,
        token: token,
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
async function fetchChunkedProxyDataset({ resource, queries, cursor, batchSize, delayMs, options, fallbackQuery, cacheHitMode, }) {
    const { selected, progress } = sliceQueries(queries, cursor, batchSize);
    const results = [];
    let failedChunkCount = 0;
    for (const query of selected) {
        try {
            const result = await (0, proxy_1.odptProxy)({
                resource,
                query,
                dump: false,
                token: token,
                forceRefresh: options.forceRefresh,
                ttlSec: options.ttlSec,
            });
            results.push(result);
        }
        catch {
            failedChunkCount += 1;
        }
        await sleep(delayMs);
    }
    if (results.length === 0 && selected.length > 0 && fallbackQuery) {
        const fallback = await fetchSingleProxyDataset(resource, fallbackQuery, {
            ...options,
            dump: false,
        });
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
    const seenIds = new Set();
    const merged = [];
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
    const cacheHit = results.length === 0
        ? false
        : cacheHitMode === "all"
            ? results.every((result) => result.meta.cacheHit)
            : results.some((result) => result.meta.cacheHit);
    return {
        data: merged,
        meta: {
            cacheHit,
            maybeTruncated: truncatedChunkCount > 0,
            chunkCount: selected.length,
            truncatedChunkCount,
            fallbackUsed: false,
            failedChunkCount,
            progress,
        },
    };
}
async function fetchTimetablesDataset(baseQuery, patternsRaw, options) {
    if (options.dump) {
        return fetchSingleProxyDataset("odpt:BusTimetable", baseQuery, options);
    }
    if (!options.chunkBusTimetables) {
        return fetchSingleProxyDataset("odpt:BusTimetable", baseQuery, { ...options, dump: false });
    }
    const queries = buildTimetableQueries(baseQuery, patternsRaw);
    return fetchChunkedProxyDataset({
        resource: "odpt:BusTimetable",
        queries,
        cursor: options.busTimetableCursor,
        batchSize: options.busTimetableBatchSize,
        delayMs: 150,
        options,
        fallbackQuery: baseQuery,
        cacheHitMode: "all",
    });
}
async function fetchStopTimetablesDataset(baseQuery, stopsRaw, options) {
    if (!options.chunkStopTimetables) {
        try {
            return await fetchSingleProxyDataset("odpt:BusstopPoleTimetable", baseQuery, options);
        }
        catch {
            // Fall through to chunked stop-level retrieval.
        }
    }
    const queries = buildStopTimetableQueries(baseQuery, stopsRaw);
    try {
        const result = await fetchChunkedProxyDataset({
            resource: "odpt:BusstopPoleTimetable",
            queries,
            cursor: options.stopTimetableCursor,
            batchSize: options.stopTimetableBatchSize,
            delayMs: 100,
            options,
            cacheHitMode: "any",
        });
        return {
            data: result.data,
            meta: {
                ...result.meta,
                fallbackUsed: true,
            },
        };
    }
    catch {
        const { selected, progress } = sliceQueries(queries, options.stopTimetableCursor, options.stopTimetableBatchSize);
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
async function fetchOperationalDataset(options) {
    const { meta, normalized } = await fetchNormalizedDataset(options);
    const operational = (0, enrich_1.enrichOperationalData)(normalized);
    const routeTimetables = (0, routeTimetables_1.buildRouteTimetables)(operational);
    return { meta, normalized, operational, routeTimetables };
}
function filterNormalizedForOperationalStage(normalized) {
    const patternIds = new Set();
    const stopIds = new Set();
    for (const trip of Object.values(normalized.trips)) {
        patternIds.add(trip.pattern_id);
        for (const stopTime of trip.stop_times) {
            stopIds.add(stopTime.stop_id);
        }
    }
    const routePatterns = Object.fromEntries(Object.entries(normalized.routePatterns).filter(([patternId]) => patternIds.has(patternId)));
    for (const pattern of Object.values(routePatterns)) {
        for (const stopId of pattern.stop_sequence) {
            stopIds.add(stopId);
        }
    }
    const stops = Object.fromEntries(Object.entries(normalized.stops).filter(([stopId]) => stopIds.has(stopId)));
    return {
        stops,
        routePatterns,
        trips: normalized.trips,
        stopTimetables: {},
    };
}
function filterNormalizedForStopTimetableStage(normalized) {
    const stopIds = new Set();
    for (const item of Object.values(normalized.stopTimetables)) {
        stopIds.add(item.stop_id);
    }
    return {
        stops: Object.fromEntries(Object.entries(normalized.stops).filter(([stopId]) => stopIds.has(stopId))),
        routePatterns: {},
        trips: {},
        stopTimetables: normalized.stopTimetables,
    };
}
function parseNormalizedRequest(req) {
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
app.get("/api/odpt/proxy", async (req, res) => {
    try {
        const resource = String(req.query["resource"] ?? "");
        const query = String(req.query["query"] ?? "");
        const dump = String(req.query["dump"] ?? "0") === "1";
        const forceRefresh = String(req.query["forceRefresh"] ?? "0") === "1";
        const ttlSec = toTtlSec(req.query["ttlSec"]);
        const result = await (0, proxy_1.odptProxy)({
            resource,
            query,
            dump,
            token: token,
            forceRefresh,
            ttlSec,
        });
        res.json(result);
    }
    catch (e) {
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
app.post("/api/odpt/introspect", (req, res) => {
    try {
        const records = req.body?.records;
        if (!Array.isArray(records)) {
            throw new Error("`records` must be an array");
        }
        res.json((0, introspect_1.introspectRecords)(records));
    }
    catch (e) {
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
app.post("/api/odpt/export/normalized", async (req, res) => {
    try {
        const { meta, normalized } = await fetchNormalizedDataset(parseNormalizedRequest(req));
        res.json({
            meta,
            ...normalized,
        });
    }
    catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.status(400).json({ error: msg });
    }
});
/**
 * POST /api/odpt/export/operational
 *
 * Fetches and normalizes ODPT data, then enriches it with route totals,
 * trip distance estimates, service/pattern indexes, and route timetable groups.
 */
app.post("/api/odpt/export/operational", async (req, res) => {
    try {
        const { meta, operational, routeTimetables } = await fetchOperationalDataset(parseNormalizedRequest(req));
        res.json({
            meta,
            ...operational,
            routeTimetables,
        });
    }
    catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.status(400).json({ error: msg });
    }
});
app.post("/api/odpt/export/operational-stage", async (req, res) => {
    try {
        const options = parseNormalizedRequest(req);
        const { meta, normalized } = await fetchNormalizedDataset({
            ...options,
            includeBusTimetables: true,
            chunkBusTimetables: true,
            includeStopTimetables: false,
        });
        const filtered = filterNormalizedForOperationalStage(normalized);
        const operational = (0, enrich_1.enrichOperationalData)(filtered);
        const routeTimetables = (0, routeTimetables_1.buildRouteTimetables)(operational);
        res.json({
            meta,
            ...operational,
            routeTimetables,
        });
    }
    catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.status(400).json({ error: msg });
    }
});
app.post("/api/odpt/export/stop-timetables-stage", async (req, res) => {
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
    }
    catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.status(400).json({ error: msg });
    }
});
/**
 * POST /api/odpt/export/save
 *
 * Fetches, normalizes, enriches, and writes normalized / operational /
 * route_timetables datasets to data/odpt/tokyu relative to the project root.
 */
app.post("/api/odpt/export/save", async (req, res) => {
    try {
        const { meta, normalized, operational, routeTimetables } = await fetchOperationalDataset(parseNormalizedRequest(req));
        const normalizedDataset = { meta, ...normalized };
        const operationalDataset = { meta, ...operational, routeTimetables };
        const routeTimetableDataset = {
            meta,
            total: routeTimetables.length,
            items: routeTimetables,
        };
        // Write route exports under <project-root>/data/odpt/tokyu/.
        // cwd when running via `npm run dev` from backend/ is backend/,
        // so we go up one level to reach the project root.
        const outDir = (0, runtimePaths_1.resolveRuntimePath)("odpt_snapshot_dir");
        await (0, promises_1.mkdir)(outDir, { recursive: true });
        const normalizedOutPath = node_path_1.default.join(outDir, "normalized_dataset.json");
        const operationalOutPath = node_path_1.default.join(outDir, "operational_dataset.json");
        const routeTimetablesOutPath = node_path_1.default.join(outDir, "route_timetables_dataset.json");
        await Promise.all([
            (0, promises_1.writeFile)(normalizedOutPath, JSON.stringify(normalizedDataset, null, 2), "utf-8"),
            (0, promises_1.writeFile)(operationalOutPath, JSON.stringify(operationalDataset, null, 2), "utf-8"),
            (0, promises_1.writeFile)(routeTimetablesOutPath, JSON.stringify(routeTimetableDataset, null, 2), "utf-8"),
        ]);
        res.json({
            savedTo: operationalOutPath,
            normalizedSavedTo: normalizedOutPath,
            routeTimetablesSavedTo: routeTimetablesOutPath,
            meta,
        });
    }
    catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.status(400).json({ error: msg });
    }
});
// ── Health check ──────────────────────────────────────────────────────────────
app.get("/health", (_req, res) => {
    res.json({ status: "ok", service: "odpt-explorer-bff" });
});
app.get("/healthz", (_req, res) => {
    res.json({ ok: true, service: "odpt-explorer-backend", timestamp: new Date().toISOString() });
});
app.get("/api/odpt/healthz", (_req, res) => {
    res.json({ ok: true, service: "odpt-explorer-backend", timestamp: new Date().toISOString() });
});
app.get("/api/odpt/health", (_req, res) => {
    res.json({ status: "ok", service: "odpt-explorer-bff" });
});
app.get("/api/status/snapshot", (_req, res) => {
    try {
        res.json({ ok: true, snapshot: getSnapshotStatus() });
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        res.status(500).json({ ok: false, error: message });
    }
});
app.get("/api/odpt/status/snapshot", (_req, res) => {
    try {
        res.json({ ok: true, snapshot: getSnapshotStatus() });
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        res.status(500).json({ ok: false, error: message });
    }
});
// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = Number(process.env.PORT ?? 3001);
app.listen(PORT, () => {
    console.log(`ODPT Explorer BFF listening on http://localhost:${PORT}`);
});
