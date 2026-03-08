import { useEffect, useMemo, useRef, useState } from "react";
import { pushPerfEntry } from "@/utils/perf/perf-store";
import { useMeasuredMemo } from "@/utils/perf/useMeasuredMemo";

type PublicDiffItem = {
  id: string;
  entity_type: string;
  display_name: string;
  change_type: string;
  suggested_action: string;
  field_diff?: Record<string, unknown>;
};

export type PreparedPublicDiffItem = PublicDiffItem & {
  changedFieldCount: number;
  changedFieldPreview: string;
};

function prepare(items: PublicDiffItem[]): PreparedPublicDiffItem[] {
  return [...items]
    .map((item) => {
      const fields = Object.keys(item.field_diff ?? {});
      return {
        ...item,
        changedFieldCount: fields.length,
        changedFieldPreview: fields.slice(0, 3).join(", "),
      };
    })
    .sort((left, right) => {
      const leftScore =
        left.suggested_action === "conflict"
          ? 0
          : left.change_type === "new"
            ? 1
            : left.change_type === "changed"
              ? 2
              : 3;
      const rightScore =
        right.suggested_action === "conflict"
          ? 0
          : right.change_type === "new"
            ? 1
            : right.change_type === "changed"
              ? 2
              : 3;
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      const typeCmp = left.entity_type.localeCompare(right.entity_type, "ja");
      if (typeCmp !== 0) {
        return typeCmp;
      }
      return left.display_name.localeCompare(right.display_name, "ja");
    });
}

export function usePreparedPublicDiffItems(items: PublicDiffItem[]) {
  const fallbackItems = useMeasuredMemo("selector:public-diff-preview-fallback", () => prepare(items), [items]);
  const [workerItems, setWorkerItems] = useState<PreparedPublicDiffItem[]>(fallbackItems);
  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (typeof Worker === "undefined" || items.length < 40) {
      setWorkerItems(fallbackItems);
      return;
    }
    if (!workerRef.current) {
      workerRef.current = new Worker(
        new URL("../workers/public-diff-preview.worker.ts", import.meta.url),
        { type: "module" },
      );
    }
    const startedAt = performance.now();
    requestIdRef.current += 1;
    const requestId = String(requestIdRef.current);
    const worker = workerRef.current;
    const handleMessage = (
      event: MessageEvent<{ requestId: string; items: PreparedPublicDiffItem[] }>,
    ) => {
      if (event.data.requestId !== requestId) {
        return;
      }
      pushPerfEntry({
        kind: "async",
        label: "worker:public-diff-preview",
        durationMs: performance.now() - startedAt,
      });
      setWorkerItems(event.data.items);
      worker.removeEventListener("message", handleMessage);
    };
    worker.addEventListener("message", handleMessage);
    worker.postMessage({ requestId, items });
    return () => {
      worker.removeEventListener("message", handleMessage);
    };
  }, [fallbackItems, items]);

  useEffect(() => {
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  return useMemo(
    () => (items.length < 40 ? fallbackItems : workerItems),
    [fallbackItems, items.length, workerItems],
  );
}
