export interface PerfEntry {
  id: string;
  kind: "render" | "async" | "tab" | "selector" | "longtask" | "memory";
  label: string;
  durationMs: number;
  at: string;
}

const listeners = new Set<(entries: PerfEntry[]) => void>();
let entries: PerfEntry[] = [];
const pendingEntries = new Map<string, { kind: PerfEntry["kind"]; label: string; startedAt: number }>();
let observersInitialized = false;

declare global {
  interface Performance {
    memory?: {
      usedJSHeapSize: number;
      totalJSHeapSize: number;
      jsHeapSizeLimit: number;
    };
  }
}

export function pushPerfEntry(
  entry: Omit<PerfEntry, "id" | "at">,
) {
  if (!isPerfDebugEnabled()) {
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
  if (!isPerfDebugEnabled()) {
    return;
  }
  pendingEntries.set(id, { kind, label, startedAt: performance.now() });
}

export function completeTimedEntry(id: string) {
  if (!isPerfDebugEnabled()) {
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

export function isPerfDebugEnabled() {
  if (!import.meta.env.DEV || typeof window === "undefined") {
    return false;
  }
  const params = new URLSearchParams(window.location.search);
  return params.get("debugPerf") === "1" || window.localStorage.getItem("debug-perf") === "1";
}

export function initPerfObservers() {
  if (!isPerfDebugEnabled() || observersInitialized) {
    return;
  }
  observersInitialized = true;

  if ("PerformanceObserver" in window) {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          pushPerfEntry({
            kind: "longtask",
            label: entry.name || "longtask",
            durationMs: entry.duration,
          });
        }
      });
      observer.observe({ entryTypes: ["longtask"] });
    } catch {
      // ignore unsupported observers
    }
  }

  if (performance.memory) {
    window.setInterval(() => {
      const usedMb = performance.memory
        ? performance.memory.usedJSHeapSize / 1024 / 1024
        : 0;
      pushPerfEntry({
        kind: "memory",
        label: `heap ${usedMb.toFixed(1)}MB`,
        durationMs: usedMb,
      });
    }, 15000);
  }
}
