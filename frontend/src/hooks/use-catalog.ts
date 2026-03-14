import { useQuery } from "@tanstack/react-query";
import { catalogApi } from "@/api/catalog";

export const catalogKeys = {
  depots: (calendarType: string) => ["catalog", "depots", calendarType] as const,
  depotRoutes: (
    depotId: string,
    includeDepotMoves: boolean,
  ) => ["catalog", "depots", depotId, "routes", includeDepotMoves] as const,
  routeFamilyPatterns: (routeFamilyId: string, depotId?: string) =>
    ["catalog", "route-family-patterns", routeFamilyId, depotId ?? null] as const,
};

export function useCatalogDepots(calendarType = "平日") {
  return useQuery({
    queryKey: catalogKeys.depots(calendarType),
    queryFn: () => catalogApi.listDepots(calendarType),
  });
}

export function useCatalogDepotRoutes(
  depotId: string,
  options?: { includeDepotMoves?: boolean; enabled?: boolean },
) {
  const includeDepotMoves = options?.includeDepotMoves ?? false;
  return useQuery({
    queryKey: catalogKeys.depotRoutes(depotId, includeDepotMoves),
    queryFn: () => catalogApi.listDepotRoutes(depotId, { includeDepotMoves }),
    enabled: Boolean(depotId) && (options?.enabled ?? true),
  });
}

export function useCatalogRouteFamilyPatterns(
  routeFamilyId: string,
  options?: { depotId?: string; enabled?: boolean },
) {
  return useQuery({
    queryKey: catalogKeys.routeFamilyPatterns(routeFamilyId, options?.depotId),
    queryFn: () =>
      catalogApi.getRouteFamilyPatterns(routeFamilyId, options?.depotId),
    enabled: Boolean(routeFamilyId) && (options?.enabled ?? true),
  });
}
