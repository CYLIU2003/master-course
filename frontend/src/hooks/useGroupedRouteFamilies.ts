import { useEffect, useMemo, useRef, useState } from "react";
import type { Route } from "@/types";
import { compareRouteCodeLike } from "@/lib/route-code";
import { pushPerfEntry } from "@/utils/perf/perf-store";
import { useMeasuredMemo } from "@/utils/perf/useMeasuredMemo";

export type RouteFamilyGroup = {
  familyId: string;
  familyCode: string;
  familyLabel: string;
  members: Route[];
};

function groupRoutes(routes: Route[]): RouteFamilyGroup[] {
  const groups = new Map<string, RouteFamilyGroup>();
  for (const route of routes) {
    const familyId = route.routeFamilyId ?? `raw:${route.id}`;
    const familyCode = route.routeFamilyCode ?? route.routeCode ?? route.name;
    const familyLabel = route.routeFamilyLabel ?? familyCode;
    const current = groups.get(familyId);
    if (current) {
      current.members.push(route);
      continue;
    }
    groups.set(familyId, {
      familyId,
      familyCode,
      familyLabel,
      members: [route],
    });
  }

  return Array.from(groups.values()).map((group) => ({
    ...group,
    members: [...group.members].sort((left, right) => {
      const familyOrderCmp =
        Number(left.familySortOrder ?? 999) - Number(right.familySortOrder ?? 999);
      if (familyOrderCmp !== 0) {
        return familyOrderCmp;
      }
      const codeCmp = compareRouteCodeLike(
        left.routeCode ?? left.routeFamilyCode ?? left.name,
        right.routeCode ?? right.routeFamilyCode ?? right.name,
      );
      if (codeCmp !== 0) {
        return codeCmp;
      }
      return `${left.routeLabel ?? left.name}|${left.id}`.localeCompare(
        `${right.routeLabel ?? right.name}|${right.id}`,
        "ja",
      );
    }),
  })).sort((left, right) => compareRouteCodeLike(left.familyCode, right.familyCode));
}

export function useGroupedRouteFamilies(routes: Route[]) {
  const fallbackGroups = useMeasuredMemo("selector:route-family-group-fallback", () => groupRoutes(routes), [routes]);
  const [workerGroups, setWorkerGroups] = useState<RouteFamilyGroup[]>([]);
  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (typeof Worker === "undefined" || routes.length < 100) {
      return;
    }
    if (!workerRef.current) {
      workerRef.current = new Worker(
        new URL("../workers/route-family-group.worker.ts", import.meta.url),
        { type: "module" },
      );
    }
    const startedAt = performance.now();
    requestIdRef.current += 1;
    const requestId = String(requestIdRef.current);
    const worker = workerRef.current;
    const handleMessage = (
      event: MessageEvent<{ requestId: string; groups: RouteFamilyGroup[] }>,
    ) => {
      if (event.data.requestId !== requestId) {
        return;
      }
      pushPerfEntry({
        kind: "async",
        label: "worker:route-family-group",
        durationMs: performance.now() - startedAt,
      });
      setWorkerGroups(event.data.groups);
      worker.removeEventListener("message", handleMessage);
    };
    worker.addEventListener("message", handleMessage);
    worker.postMessage({ requestId, routes });
    return () => {
      worker.removeEventListener("message", handleMessage);
    };
  }, [routes]);

  useEffect(() => {
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  return useMemo(
    () => (routes.length < 100 || workerGroups.length === 0 ? fallbackGroups : workerGroups),
    [fallbackGroups, routes.length, workerGroups],
  );
}
