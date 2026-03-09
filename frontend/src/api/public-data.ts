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
};
