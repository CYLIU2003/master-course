import { useEffect } from "react";
import { completeTimedEntry, startTimedEntry } from "./perf-store";

export function useTabSwitchTrace(scope: string, activeKey: string) {
  useEffect(() => {
    const eventId = `${scope}:${activeKey}:${Date.now()}`;
    startTimedEntry(eventId, "tab", `${scope}:${activeKey}`);
    const raf1 = requestAnimationFrame(() => {
      const raf2 = requestAnimationFrame(() => {
        completeTimedEntry(eventId);
      });
      return () => cancelAnimationFrame(raf2);
    });
    return () => cancelAnimationFrame(raf1);
  }, [activeKey, scope]);
}
