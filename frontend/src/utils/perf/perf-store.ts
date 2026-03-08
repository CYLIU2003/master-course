export interface PerfEntry {
  id: string;
  kind: "render" | "async" | "tab" | "selector";
  label: string;
  durationMs: number;
  at: string;
}

const listeners = new Set<(entries: PerfEntry[]) => void>();
let entries: PerfEntry[] = [];
const pendingEntries = new Map<string, { kind: PerfEntry["kind"]; label: string; startedAt: number }>();

export function pushPerfEntry(
  entry: Omit<PerfEntry, "id" | "at">,
) {
  if (!import.meta.env.DEV) {
    return;
  }
  entries = [
    {
      ...entry,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      at: new Date().toISOString(),
    },
    ...entries,
  ].slice(0, 30);
  listeners.forEach((listener) => listener(entries));
}

export function subscribePerfEntries(listener: (items: PerfEntry[]) => void) {
  listeners.add(listener);
  listener(entries);
  return () => listeners.delete(listener);
}

export function startTimedEntry(
  id: string,
  kind: PerfEntry["kind"],
  label: string,
) {
  if (!import.meta.env.DEV) {
    return;
  }
  pendingEntries.set(id, { kind, label, startedAt: performance.now() });
}

export function completeTimedEntry(id: string) {
  if (!import.meta.env.DEV) {
    return;
  }
  const pending = pendingEntries.get(id);
  if (!pending) {
    return;
  }
  pendingEntries.delete(id);
  pushPerfEntry({
    kind: pending.kind,
    label: pending.label,
    durationMs: performance.now() - pending.startedAt,
  });
}
