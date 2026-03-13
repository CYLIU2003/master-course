import { useEffect, useMemo, useRef, useState } from "react";
import { compareRouteCodeLike } from "@/lib/route-code";
import { pushPerfEntry } from "@/utils/perf/perf-store";
import { useMeasuredMemo } from "@/utils/perf/useMeasuredMemo";

type AssignmentRow = {
  routeId: string;
  routeName: string;
  routeCode: string;
  routeFamilyCode?: string;
  familySortOrder?: number;
  startStop?: string;
  endStop?: string;
};

function sortRows<T extends AssignmentRow>(rows: T[]): T[] {
  return [...rows].sort((left, right) => {
    const familyCmp = compareRouteCodeLike(
      left.routeFamilyCode || left.routeCode || left.routeName,
      right.routeFamilyCode || right.routeCode || right.routeName,
    );
    if (familyCmp !== 0) {
      return familyCmp;
    }
    const familyOrderCmp =
      Number(left.familySortOrder ?? 999) - Number(right.familySortOrder ?? 999);
    if (familyOrderCmp !== 0) {
      return familyOrderCmp;
    }
    const codeCmp = compareRouteCodeLike(
      left.routeCode || left.routeName,
      right.routeCode || right.routeName,
    );
    if (codeCmp !== 0) {
      return codeCmp;
    }
    return `${left.routeName}|${left.startStop ?? ""}|${left.endStop ?? ""}`.localeCompare(
      `${right.routeName}|${right.startStop ?? ""}|${right.endStop ?? ""}`,
      "ja",
    );
  });
}

export function useSortedAssignments<T extends AssignmentRow>(rows: T[]): T[] {
  const fallbackSorted = useMeasuredMemo("selector:assignment-sort-fallback", () => sortRows(rows), [rows]);
  const [workerSorted, setWorkerSorted] = useState<T[]>([]);
  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (typeof Worker === "undefined" || rows.length < 150) {
      return;
    }
    if (!workerRef.current) {
      workerRef.current = new Worker(
        new URL("../workers/assignment-sort.worker.ts", import.meta.url),
        { type: "module" },
      );
    }
    const startedAt = performance.now();
    requestIdRef.current += 1;
    const requestId = String(requestIdRef.current);
    const worker = workerRef.current;
    const handleMessage = (
      event: MessageEvent<{ requestId: string; rows: T[] }>,
    ) => {
      if (event.data.requestId !== requestId) {
        return;
      }
      pushPerfEntry({
        kind: "async",
        label: "worker:assignment-sort",
        durationMs: performance.now() - startedAt,
      });
      setWorkerSorted(event.data.rows);
      worker.removeEventListener("message", handleMessage);
    };
    worker.addEventListener("message", handleMessage);
    worker.postMessage({ requestId, rows });
    return () => {
      worker.removeEventListener("message", handleMessage);
    };
  }, [rows]);

  useEffect(() => {
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  return useMemo(
    () => (rows.length < 150 || workerSorted.length === 0 ? fallbackSorted : workerSorted),
    [fallbackSorted, rows.length, workerSorted],
  );
}
