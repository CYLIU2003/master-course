import { useEffect, useState } from "react";
import { isPerfDebugEnabled, subscribePerfEntries, type PerfEntry } from "./perf-store";

export function DebugPerfOverlay() {
  const [entries, setEntries] = useState<PerfEntry[]>([]);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const unsubscribe = subscribePerfEntries(setEntries);
    return () => {
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    setEnabled(isPerfDebugEnabled());
  }, []);

  if (!import.meta.env.DEV || !enabled || entries.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[70] w-80 rounded-xl border border-slate-800 bg-slate-950/90 p-3 text-[11px] text-slate-100 shadow-2xl">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold uppercase tracking-wide text-slate-400">Perf</span>
        <span className="text-slate-500">{entries.length} entries</span>
      </div>
      <div className="max-h-64 space-y-1 overflow-auto">
        {entries.map((entry) => (
          <div key={entry.id} className="rounded bg-slate-900/80 px-2 py-1">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate">{entry.label}</span>
              <span className="font-mono text-slate-400">{entry.durationMs.toFixed(1)}ms</span>
            </div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{entry.kind}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
