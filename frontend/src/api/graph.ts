import { api } from "./client";
import type {
  TripsResponse,
  BuildTripsRequest,
  GraphResponse,
  BuildGraphRequest,
  BlocksResponse,
  BuildBlocksRequest,
  DutiesResponse,
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
  graphResponseSchema,
  tripsListResponseSchema,
} from "@/schemas/dispatch";

export const graphApi = {
  // ── Trips ───────────────────────────────────────────────────
  getTrips: async (scenarioId: string) =>
    tripsListResponseSchema.parse(
      await api.get<TripsResponse>(`/scenarios/${scenarioId}/trips`),
    ),

  buildTrips: (scenarioId: string, data?: BuildTripsRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-trips`, data),

  // ── Graph ───────────────────────────────────────────────────
  getGraph: async (scenarioId: string) =>
    graphResponseSchema.parse(
      await api.get<GraphResponse>(`/scenarios/${scenarioId}/graph`),
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

  getDuties: async (scenarioId: string) =>
    dutiesResponseSchema.parse(
      await api.get<DutiesResponse>(`/scenarios/${scenarioId}/duties`),
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
