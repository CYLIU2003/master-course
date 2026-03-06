"use strict";
/**
 * Introspect a sample of ODPT API records and produce a field-level summary:
 * - path: dot-notated field path
 * - types: count per JS typeof value ("string", "number", "object", "array", "null", "boolean")
 * - present: how many records contained this field
 * - presentRate: present / sampleCount (1.0 = always present)
 *
 * Results are sorted by presentRate DESC so "almost required" fields float to the top.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.introspectRecords = introspectRecords;
function typeOf(v) {
    if (v === null)
        return "null";
    if (Array.isArray(v))
        return "array";
    return typeof v;
}
function walk(obj, prefix, out) {
    if (obj === null || typeof obj !== "object" || Array.isArray(obj))
        return;
    for (const [k, v] of Object.entries(obj)) {
        const path = prefix ? `${prefix}.${k}` : k;
        const t = typeOf(v);
        const stat = out.get(path) ?? { path, types: {}, present: 0 };
        stat.types[t] = (stat.types[t] ?? 0) + 1;
        stat.present += 1;
        out.set(path, stat);
        if (t === "object") {
            walk(v, path, out);
        }
        // For arrays: only inspect the first element to avoid blowup
        if (t === "array") {
            const arr = v;
            if (arr.length > 0 && typeof arr[0] === "object" && arr[0] !== null) {
                walk(arr[0], `${path}[0]`, out);
            }
        }
    }
}
function introspectRecords(records, sampleLimit = 200) {
    const sample = records.slice(0, sampleLimit);
    const stats = new Map();
    for (const r of sample) {
        walk(r, "", stats);
    }
    const fields = [...stats.values()].map((s) => ({
        ...s,
        presentRate: s.present / sample.length,
    }));
    // High presentRate → "probably required"
    fields.sort((a, b) => b.presentRate - a.presentRate);
    return { sampleCount: sample.length, fields };
}
