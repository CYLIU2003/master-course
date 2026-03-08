import { useMemo, type DependencyList } from "react";
import { pushPerfEntry } from "./perf-store";

export function useMeasuredMemo<T>(
  label: string,
  factory: () => T,
  deps: DependencyList,
): T {
  return useMemo(() => {
    const startedAt = performance.now();
    const value = factory();
    pushPerfEntry({
      kind: "selector",
      label,
      durationMs: performance.now() - startedAt,
    });
    return value;
  }, deps);
}
