import { api } from "./client";

// ── Types ────────────────────────────────────────────────────

export type OperatorId = "tokyu" | "toei";
export type SourceType = "odpt" | "gtfs";

export type PublicDataCounts = {
  routes: number;
  stops: number;
  timetableRows: number;
  stopTimetables: number;
  stopTimetableEntries: number;
  tripStopTimes: number;
  calendar: number;
  calendarDates: number;
};

export type PublicDataSummary = {
  operatorId: OperatorId;
  operatorLabel: string;
  sourceType: SourceType;
  datasetVersion: string;
  counts: PublicDataCounts;
  dbExists: boolean;
  updatedAt: string | null;
};

export type MapOverviewBounds = {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
};

export type StopCluster = {
  id: string;
  lat: number;
  lon: number;
  count: number;
};

export type DepotPoint = {
  id: string;
  label: string;
  lat: number;
  lon: number;
};

export type MapOverviewResponse = {
  operatorId: string;
  bounds: MapOverviewBounds | null;
  stopClusters: StopCluster[];
  depotPoints: DepotPoint[];
  updatedAt: string | null;
};

export type OperatorOverview = {
  operatorId: string;
  routeCount: number;
  stopCount: number;
  serviceCount: number;
  tripCount: number;
  depotCount: number;
  updatedAt: string | null;
};

export type RouteFamilyListItem = {
  routeFamilyId: string;
  routeFamilyCode: string;
  routeFamilyLabel: string;
  variantCount: number;
  patternCount: number;
  directionCount: number;
  tripCount: number;
  stopCount: number;
  firstDeparture?: string;
  lastArrival?: string;
  serviceIds: string[];
  hasShortTurn: boolean;
  hasBranch: boolean;
  hasDepotVariant: boolean;
};

export type StopListItem = {
  stop_id: string;
  stop_name: string;
  stop_name_en?: string;
  lat?: number;
  lon?: number;
  kind?: string;
  source?: string;
};

export type TimetableSummaryResponse = {
  by_service: Array<{
    service_id: string;
    trip_count: number;
    route_count: number;
    earliest_departure?: string;
    latest_arrival?: string;
  }>;
  total: number;
};

export type TimetableRowItem = {
  trip_id: string;
  route_id: string;
  service_id: string;
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  direction?: string;
  distance_km?: number;
};

// ── API ──────────────────────────────────────────────────────

export const publicDataApi = {
  /** Get summaries for all operators */
  getAllSummaries: () =>
    api.get<{ items: PublicDataSummary[]; total: number }>("/catalog/summary"),

  /** Get summary for a single operator */
  getSummary: (operatorId: OperatorId) =>
    api.get<{ item: PublicDataSummary }>(
      `/catalog/summary?operatorId=${operatorId}`,
    ),

  /** Get lightweight map overview (operatorId required) */
  getMapOverview: (operatorId: OperatorId) =>
    api.get<MapOverviewResponse>(
      `/catalog/map-overview?operatorId=${operatorId}`,
    ),

  getOperatorOverview: (operatorId: OperatorId) =>
    api.get<{ item: OperatorOverview }>(`/catalog/operators/${operatorId}/overview`),

  listRouteFamilies: (operatorId: OperatorId, params?: { q?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<{ items: RouteFamilyListItem[]; total: number }>(
      `/catalog/operators/${operatorId}/route-families${suffix}`,
    );
  },

  listStops: (operatorId: OperatorId, params?: { q?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<{ items: StopListItem[]; total: number }>(
      `/catalog/operators/${operatorId}/stops${suffix}`,
    );
  },

  getTimetableSummary: (operatorId: OperatorId, params?: { routeId?: string; serviceId?: string }) => {
    const query = new URLSearchParams();
    if (params?.routeId) query.set("routeId", params.routeId);
    if (params?.serviceId) query.set("serviceId", params.serviceId);
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<{ item: TimetableSummaryResponse }>(
      `/catalog/operators/${operatorId}/timetable-summary${suffix}`,
    );
  },

  listTimetableRows: (
    operatorId: OperatorId,
    params?: { routeId?: string; serviceId?: string; limit?: number; offset?: number },
  ) => {
    const query = new URLSearchParams();
    if (params?.routeId) query.set("routeId", params.routeId);
    if (params?.serviceId) query.set("serviceId", params.serviceId);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<{ items: TimetableRowItem[]; total: number; limit: number; offset: number }>(
      `/catalog/operators/${operatorId}/timetable-rows${suffix}`,
    );
  },
};
