"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.odptProxy = odptProxy;
const config_1 = require("./config");
const url_1 = require("./url");
const fetch_1 = require("./fetch");
const cache_1 = require("./cache");
async function odptProxy(input) {
    if (!config_1.ALLOWED_RESOURCES.has(input.resource)) {
        throw new Error(`Resource not allowed: ${input.resource}`);
    }
    const ttlSec = typeof input.ttlSec === "number" &&
        Number.isFinite(input.ttlSec) &&
        input.ttlSec > 0
        ? input.ttlSec
        : 3600;
    const cacheKey = (0, cache_1.makeCacheKey)({
        resource: input.resource,
        query: input.query || "",
        dump: input.dump,
    });
    if (!input.forceRefresh) {
        const cached = (0, cache_1.readCache)(cacheKey);
        if (cached) {
            return {
                ...cached,
                meta: {
                    ...cached.meta,
                    cacheHit: true,
                    cacheKey,
                },
            };
        }
    }
    const url = (0, url_1.buildOdptProxyUrl)({
        resource: input.resource,
        query: input.query || "",
        token: input.token,
        dump: input.dump,
    });
    const data = await (0, fetch_1.fetchJson)(url);
    const meta = {
        url,
        count: data.length,
        // 1000 records strongly suggests search API cap was hit
        maybeTruncated: !input.dump && data.length === 1000,
        dump: input.dump,
        cacheHit: false,
        cacheKey,
    };
    const result = { meta, data };
    (0, cache_1.writeCache)(cacheKey, result, ttlSec);
    return result;
}
