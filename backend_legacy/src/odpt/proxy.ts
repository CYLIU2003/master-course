import { ALLOWED_RESOURCES } from "./config";
import { buildOdptProxyUrl } from "./url";
import { fetchJson } from "./fetch";
import { makeCacheKey, readCache, writeCache } from "./cache";

export interface ProxyInput {
  resource: string;
  query: string;
  dump: boolean;
  token: string;
  forceRefresh?: boolean;
  ttlSec?: number;
}

export interface ProxyMeta {
  url: string;
  count: number;
  /** true when search API 1000-record cap may have been hit */
  maybeTruncated: boolean;
  dump: boolean;
  cacheHit: boolean;
  cacheKey: string;
}

export interface ProxyResult {
  meta: ProxyMeta;
  data: unknown[];
}

export async function odptProxy(input: ProxyInput): Promise<ProxyResult> {
  if (!ALLOWED_RESOURCES.has(input.resource)) {
    throw new Error(`Resource not allowed: ${input.resource}`);
  }

  const ttlSec =
    typeof input.ttlSec === "number" &&
    Number.isFinite(input.ttlSec) &&
    input.ttlSec > 0
      ? input.ttlSec
      : 3600;

  const cacheKey = makeCacheKey({
    resource: input.resource,
    query: input.query || "",
    dump: input.dump,
  });

  if (!input.forceRefresh) {
    const cached = readCache<ProxyResult>(cacheKey);
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

  const url = buildOdptProxyUrl({
    resource: input.resource,
    query: input.query || "",
    token: input.token,
    dump: input.dump,
  });

  const data = await fetchJson<unknown[]>(url);

  const meta: ProxyMeta = {
    url,
    count: data.length,
    // 1000 records strongly suggests search API cap was hit
    maybeTruncated: !input.dump && data.length === 1000,
    dump: input.dump,
    cacheHit: false,
    cacheKey,
  };

  const result = { meta, data };
  writeCache(cacheKey, result, ttlSec);
  return result;
}
