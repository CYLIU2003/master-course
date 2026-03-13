/**
 * Generic JSON fetcher with AbortController timeout.
 * Throws a descriptive Error on HTTP errors or network failures.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchJson<T>(url: string, timeoutMs = 120_000): Promise<T> {
  const maxAttempts = 4;
  let lastError: unknown = null;

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
      return (await res.json()) as T;
    } catch (error) {
      lastError = error;
      if (attempt < maxAttempts) {
        await sleep(1000 * attempt);
        continue;
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  const message = lastError instanceof Error ? lastError.message : String(lastError);
  throw new Error(`ODPT fetch failed after retries: ${message}`);
}
