// ── ID generation utilities ───────────────────────────────────

/**
 * Generate a prefixed pseudo-random ID.
 * For production use crypto.randomUUID() — this is fine for
 * client-side draft objects that will be replaced by server IDs.
 */
export function nanoid(prefix = ""): string {
  const rnd = Math.random().toString(16).slice(2, 10);
  const t = Date.now().toString(16);
  return `${prefix}${t}_${rnd}`;
}
