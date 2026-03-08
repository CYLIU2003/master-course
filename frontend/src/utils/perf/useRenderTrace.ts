import { useEffect, useRef } from "react";
import { pushPerfEntry } from "./perf-store";

export function useRenderTrace(label: string) {
  const renderCount = useRef(0);
  renderCount.current += 1;

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    pushPerfEntry({
      kind: "render",
      label: `${label} render #${renderCount.current}`,
      durationMs: renderCount.current,
    });
  });
}
