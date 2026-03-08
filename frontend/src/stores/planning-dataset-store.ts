import { create } from "zustand";
import type { ConnectionArc, ConnectionGraph, Depot, Route, Trip, VehicleDuty } from "@/types";

type EntityMap<T> = Record<string, T>;

function asArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function toEntityState<T>(
  items: T[],
  getId: (item: T, index: number) => string,
): { byId: EntityMap<T>; ids: string[] } {
  const byId: EntityMap<T> = {};
  const ids: string[] = [];
  for (const [index, item] of items.entries()) {
    const id = getId(item, index);
    if (!id) {
      continue;
    }
    byId[id] = item;
    ids.push(id);
  }
  return { byId, ids };
}

type PlanningDatasetState = {
  depotsById: EntityMap<Depot>;
  depotIds: string[];
  routesById: EntityMap<Route>;
  routeIds: string[];
  tripsById: EntityMap<Trip>;
  tripIds: string[];
  arcsById: EntityMap<ConnectionArc>;
  arcIds: string[];
  dutiesById: EntityMap<VehicleDuty>;
  dutyIds: string[];
  activeDepotId: string | null;
  selectedRouteId: string | null;
  showAllRoutes: boolean;
  syncDepots: (items: Depot[] | null | undefined) => void;
  syncRoutes: (items: Route[] | null | undefined) => void;
  syncTrips: (items: Trip[] | null | undefined) => void;
  syncGraph: (graph: ConnectionGraph | null | undefined) => void;
  syncDuties: (items: VehicleDuty[] | null | undefined) => void;
  setActiveDepotId: (depotId: string | null) => void;
  setSelectedRouteId: (routeId: string | null) => void;
  setShowAllRoutes: (showAll: boolean) => void;
};

export const usePlanningDatasetStore = create<PlanningDatasetState>((set) => ({
  depotsById: {},
  depotIds: [],
  routesById: {},
  routeIds: [],
  tripsById: {},
  tripIds: [],
  arcsById: {},
  arcIds: [],
  dutiesById: {},
  dutyIds: [],
  activeDepotId: null,
  selectedRouteId: null,
  showAllRoutes: false,
  syncDepots: (items) => {
    const next = toEntityState(asArray(items), (item) => String(item.id ?? ""));
    set({ depotsById: next.byId, depotIds: next.ids });
  },
  syncRoutes: (items) => {
    const next = toEntityState(asArray(items), (item) => String(item.id ?? ""));
    set({ routesById: next.byId, routeIds: next.ids });
  },
  syncTrips: (items) => {
    const next = toEntityState(asArray(items), (item) => String(item.trip_id ?? ""));
    set({ tripsById: next.byId, tripIds: next.ids });
  },
  syncGraph: (graph) => {
    const safeGraph = graph ?? null;
    const trips = toEntityState(asArray(safeGraph?.trips), (item) => String(item.trip_id ?? ""));
    const arcs = toEntityState(
      asArray(safeGraph?.arcs),
      (item, index) => `${item.from_trip_id}:${item.to_trip_id}:${item.vehicle_type}:${index}`,
    );
    set({
      tripsById: trips.byId,
      tripIds: trips.ids,
      arcsById: arcs.byId,
      arcIds: arcs.ids,
    });
  },
  syncDuties: (items) => {
    const next = toEntityState(asArray(items), (item) => String(item.duty_id ?? ""));
    set({ dutiesById: next.byId, dutyIds: next.ids });
  },
  setActiveDepotId: (activeDepotId) => set({ activeDepotId }),
  setSelectedRouteId: (selectedRouteId) => set({ selectedRouteId }),
  setShowAllRoutes: (showAllRoutes) => set({ showAllRoutes }),
}));

export const selectVisibleDepots = (state: PlanningDatasetState): Depot[] =>
  state.depotIds.map((id) => state.depotsById[id]).filter(Boolean);

export const selectVisibleRoutes = (state: PlanningDatasetState): Route[] => {
  const routes = state.routeIds.map((id) => state.routesById[id]).filter(Boolean);
  if (state.showAllRoutes || !state.activeDepotId) {
    return routes;
  }
  return routes.filter((route) => route.depotId === state.activeDepotId);
};

export const selectVisibleTrips = (state: PlanningDatasetState): Trip[] => {
  const trips = state.tripIds.map((id) => state.tripsById[id]).filter(Boolean);
  if (state.selectedRouteId) {
    return trips.filter((trip) => trip.route_id === state.selectedRouteId);
  }
  const visibleRouteIds = new Set(selectVisibleRoutes(state).map((route) => route.id));
  if (visibleRouteIds.size === 0) {
    return trips;
  }
  return trips.filter((trip) => visibleRouteIds.has(trip.route_id));
};

export const selectVisibleArcs = (state: PlanningDatasetState): ConnectionArc[] => {
  const arcs = state.arcIds.map((id) => state.arcsById[id]).filter(Boolean);
  const visibleTripIds = new Set(selectVisibleTrips(state).map((trip) => trip.trip_id));
  if (visibleTripIds.size === 0) {
    return arcs;
  }
  return arcs.filter(
    (arc) =>
      visibleTripIds.has(arc.from_trip_id) && visibleTripIds.has(arc.to_trip_id),
  );
};

export const selectVisibleDuties = (state: PlanningDatasetState): VehicleDuty[] => {
  const duties = state.dutyIds.map((id) => state.dutiesById[id]).filter(Boolean);
  const visibleTripIds = new Set(selectVisibleTrips(state).map((trip) => trip.trip_id));
  if (visibleTripIds.size === 0) {
    return duties;
  }
  return duties.filter((duty) =>
    asArray(duty.legs).some((leg) => visibleTripIds.has(leg.trip.trip_id)),
  );
};
