import { compareRouteCodeLike } from "@/lib/route-code";

type AssignmentRow = {
  routeId: string;
  routeName: string;
  routeCode: string;
  routeFamilyCode?: string;
  familySortOrder?: number;
  startStop?: string;
  endStop?: string;
};

type SortRequest = {
  requestId: string;
  rows: AssignmentRow[];
};

type SortResponse = {
  requestId: string;
  rows: AssignmentRow[];
};

function sortRows(rows: AssignmentRow[]) {
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

self.onmessage = (event: MessageEvent<SortRequest>) => {
  const response: SortResponse = {
    requestId: event.data.requestId,
    rows: sortRows(event.data.rows),
  };
  self.postMessage(response);
};
