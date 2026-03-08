import { compareRouteCodeLike } from "@/lib/route-code";

type WorkerRoute = {
  id: string;
  name: string;
  routeCode?: string;
  routeLabel?: string;
  routeFamilyId?: string;
  routeFamilyCode?: string;
  routeFamilyLabel?: string;
  familySortOrder?: number;
};

type RouteFamilyGroup = {
  familyId: string;
  familyCode: string;
  familyLabel: string;
  members: WorkerRoute[];
};

function groupRoutes(routes: WorkerRoute[]): RouteFamilyGroup[] {
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

self.onmessage = (
  event: MessageEvent<{ requestId: string; routes: WorkerRoute[] }>,
) => {
  self.postMessage({
    requestId: event.data.requestId,
    groups: groupRoutes(event.data.routes),
  });
};
