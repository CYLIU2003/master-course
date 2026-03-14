import { api } from "./client";
import type { CatalogDepotSummary, CatalogPatternSummary, CatalogRouteSummary } from "@/types";

export const catalogApi = {
  listDepots: (calendarType = "平日") =>
    api.get<CatalogDepotSummary[]>(
      `/catalog/depots?calendar_type=${encodeURIComponent(calendarType)}`,
    ),

  listDepotRoutes: (
    depotId: string,
    options?: { includeDepotMoves?: boolean },
  ) => {
    const query = new URLSearchParams();
    if (options?.includeDepotMoves) {
      query.set("include_depot_moves", "true");
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<CatalogRouteSummary[]>(
      `/catalog/depots/${encodeURIComponent(depotId)}/routes${suffix}`,
    );
  },

  getRouteFamilyPatterns: (routeFamilyId: string, depotId?: string) => {
    const query = new URLSearchParams();
    if (depotId) {
      query.set("depot_id", depotId);
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<CatalogPatternSummary[]>(
      `/catalog/route-families/${encodeURIComponent(routeFamilyId)}/patterns${suffix}`,
    );
  },
};
