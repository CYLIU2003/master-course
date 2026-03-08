import { api } from "./client";
import type {
  TripsResponse,
  BuildTripsRequest,
  GraphResponse,
  BuildGraphRequest,
  DutiesResponse,
  GenerateDutiesRequest,
  DutyValidationResponse,
  JobResponse,
} from "@/types";
import {
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
};
