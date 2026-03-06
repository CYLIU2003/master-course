"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.fetchJson = fetchJson;
/**
 * Generic JSON fetcher with AbortController timeout.
 * Throws a descriptive Error on HTTP errors or network failures.
 */
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
async function fetchJson(url, timeoutMs = 120_000) {
    const maxAttempts = 4;
    let lastError = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), timeoutMs);
        try {
            const res = await fetch(url, { signal: ctrl.signal });
            if (!res.ok) {
                const text = await res.text().catch(() => "");
                if (res.status === 429 && attempt < maxAttempts) {
                    await sleep(1000 * attempt);
                    continue;
                }
                throw new Error(`ODPT HTTP ${res.status}: ${text.slice(0, 500)}`);
            }
            return (await res.json());
        }
        catch (error) {
            lastError = error;
            if (attempt < maxAttempts) {
                await sleep(1000 * attempt);
                continue;
            }
            throw error;
        }
        finally {
            clearTimeout(timer);
        }
    }
    const message = lastError instanceof Error ? lastError.message : String(lastError);
    throw new Error(`ODPT fetch failed after retries: ${message}`);
}
