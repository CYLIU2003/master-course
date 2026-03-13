import { useEffect, useRef } from "react";
import { pushPerfEntry } from "./perf-store";

export function useRenderTrace(label: string) {
  const renderCount = useRef(0);

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    renderCount.current += 1;
    pushPerfEntry({
      kind: "render",
      label: `${label} render #${renderCount.current}`,
      durationMs: renderCount.current,
    });
  });
}
