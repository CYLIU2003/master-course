import type { Route } from "@/types";

export const LOW_CONFIDENCE_VARIANT_THRESHOLD = 0.6;
export const ROUTE_VARIANT_LABELS: Record<NonNullable<Route["routeVariantType"]>, string> = {
  main: "本線",
  main_outbound: "本線",
  main_inbound: "本線",
  short_turn: "区間便",
  branch: "枝線",
  depot_out: "入出庫便",
  depot_in: "入出庫便",
  depot: "入出庫便",
  unknown: "要確認",
};

export function getCanonicalDirectionLabel(direction?: string | null): string {
  const value = String(direction ?? "").trim().toLowerCase();
  if (["outbound", "out", "up", "上り", "上り便", "↗"].includes(value)) {
    return "上り";
  }
  if (["inbound", "in", "down", "下り", "下り便", "↙"].includes(value)) {
    return "下り";
  }
  if (["circular", "loop", "循環", "循環線"].includes(value)) {
    return "循環線";
  }
  return "要確認";
}

export function getDisplayRouteVariantType(
  route: Pick<Route, "routeVariantType" | "classificationConfidence">,
): Route["routeVariantType"] {
  if (!route.routeVariantType) {
    return undefined;
  }
  if ((route.classificationConfidence ?? 1) < LOW_CONFIDENCE_VARIANT_THRESHOLD) {
    return "unknown";
  }
  return route.routeVariantType;
}

export function getRouteVariantLabel(
  route: Pick<Route, "routeVariantType" | "classificationConfidence">,
): string | null {
  const variantType = getDisplayRouteVariantType(route);
  if (!variantType) {
    return null;
  }
  return ROUTE_VARIANT_LABELS[variantType];
}

export function getRouteVariantLabelByValue(value?: string | null): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (["main", "main_outbound", "main_inbound", "本線"].includes(normalized)) {
    return ROUTE_VARIANT_LABELS.main;
  }
  if (["short_turn", "区間", "区間便"].includes(normalized)) {
    return ROUTE_VARIANT_LABELS.short_turn;
  }
  if (["depot", "depot_in", "depot_out", "入出庫", "入出庫便", "入庫", "出庫"].includes(normalized)) {
    return ROUTE_VARIANT_LABELS.depot;
  }
  if (["branch", "枝線"].includes(normalized)) {
    return ROUTE_VARIANT_LABELS.branch;
  }
  return ROUTE_VARIANT_LABELS.unknown;
}
