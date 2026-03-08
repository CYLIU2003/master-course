import type { Route } from "@/types";

export const LOW_CONFIDENCE_VARIANT_THRESHOLD = 0.6;

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

  const labels: Record<NonNullable<Route["routeVariantType"]>, string> = {
    main: "本線",
    main_outbound: "本線 上り",
    main_inbound: "本線 下り",
    short_turn: "区間便",
    branch: "枝線",
    depot_out: "出庫便",
    depot_in: "入庫便",
    unknown: "要確認",
  };

  return labels[variantType];
}
