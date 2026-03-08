import { api } from "./client";
import type {
  TripsResponse,
  TripsSummaryResponse,
  BuildTripsRequest,
  GraphResponse,
  GraphSummaryResponse,
  GraphArcsResponse,
  BuildGraphRequest,
  BlocksResponse,
  BuildBlocksRequest,
  DutiesResponse,
  DutiesSummaryResponse,
  GenerateDutiesRequest,
  DispatchPlanArtifactResponse,
  BuildDispatchPlanRequest,
  DutyValidationResponse,
  JobResponse,
} from "@/types";
import {
  blocksResponseSchema,
  dispatchPlanResponseSchema,
  dutyValidationResponseSchema,
  dutiesResponseSchema,
  dutiesSummaryResponseSchema,
  graphArcsResponseSchema,
  graphResponseSchema,
  graphSummaryResponseSchema,
  tripsSummaryResponseSchema,
  tripsListResponseSchema,
} from "@/schemas/dispatch";

export const graphApi = {
  // ── Trips ───────────────────────────────────────────────────
  getTrips: async (
    scenarioId: string,
    params?: { limit?: number; offset?: number },
  ) =>
    tripsListResponseSchema.parse(
      await api.get<TripsResponse>(
        `/scenarios/${scenarioId}/trips${buildQuery(params)}`,
      ),
    ),

  getTripsSummary: async (scenarioId: string) =>
    tripsSummaryResponseSchema.parse(
      await api.get<TripsSummaryResponse>(`/scenarios/${scenarioId}/trips/summary`),
    ),

  buildTrips: (scenarioId: string, data?: BuildTripsRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-trips`, data),

  // ── Graph ───────────────────────────────────────────────────
  getGraph: async (scenarioId: string) =>
    graphResponseSchema.parse(
      await api.get<GraphResponse>(`/scenarios/${scenarioId}/graph`),
    ),

  getGraphSummary: async (scenarioId: string) =>
    graphSummaryResponseSchema.parse(
      await api.get<GraphSummaryResponse>(`/scenarios/${scenarioId}/graph/summary`),
    ),

  getGraphArcs: async (
    scenarioId: string,
    params?: { reasonCode?: string; limit?: number; offset?: number },
  ) =>
    graphArcsResponseSchema.parse(
      await api.get<GraphArcsResponse>(
        `/scenarios/${scenarioId}/graph/arcs${buildQuery({
          reason_code: params?.reasonCode,
          limit: params?.limit,
          offset: params?.offset,
        })}`,
      ),
    ),

  buildGraph: (scenarioId: string, data?: BuildGraphRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-graph`, data),

  // ── Duties ──────────────────────────────────────────────────
  getBlocks: async (scenarioId: string) =>
    blocksResponseSchema.parse(
      await api.get<BlocksResponse>(`/scenarios/${scenarioId}/blocks`),
    ),

  buildBlocks: (scenarioId: string, data?: BuildBlocksRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-blocks`, data),

  getDuties: async (
    scenarioId: string,
    params?: { limit?: number; offset?: number },
  ) =>
    dutiesResponseSchema.parse(
      await api.get<DutiesResponse>(
        `/scenarios/${scenarioId}/duties${buildQuery(params)}`,
      ),
    ),

  getDutiesSummary: async (scenarioId: string) =>
    dutiesSummaryResponseSchema.parse(
      await api.get<DutiesSummaryResponse>(`/scenarios/${scenarioId}/duties/summary`),
    ),

  generateDuties: (scenarioId: string, data?: GenerateDutiesRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/generate-duties`, data),

  validateDuties: async (scenarioId: string) =>
    dutyValidationResponseSchema.parse(
      await api.get<DutyValidationResponse>(
        `/scenarios/${scenarioId}/duties/validate`,
      ),
    ),

  getDispatchPlan: async (scenarioId: string) =>
    dispatchPlanResponseSchema.parse(
      await api.get<DispatchPlanArtifactResponse>(`/scenarios/${scenarioId}/dispatch-plan`),
    ),

  buildDispatchPlan: (scenarioId: string, data?: BuildDispatchPlanRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-dispatch-plan`, data),
};

function buildQuery(params?: Record<string, string | number | undefined>) {
  if (!params) {
    return "";
  }
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}
