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

export const graphApi = {
  // ── Trips ───────────────────────────────────────────────────
  getTrips: (scenarioId: string) =>
    api.get<TripsResponse>(`/scenarios/${scenarioId}/trips`),

  buildTrips: (scenarioId: string, data?: BuildTripsRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-trips`, data),

  // ── Graph ───────────────────────────────────────────────────
  getGraph: (scenarioId: string) =>
    api.get<GraphResponse>(`/scenarios/${scenarioId}/graph`),

  buildGraph: (scenarioId: string, data?: BuildGraphRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/build-graph`, data),

  // ── Duties ──────────────────────────────────────────────────
  getDuties: (scenarioId: string) =>
    api.get<DutiesResponse>(`/scenarios/${scenarioId}/duties`),

  generateDuties: (scenarioId: string, data?: GenerateDutiesRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/generate-duties`, data),

  validateDuties: (scenarioId: string) =>
    api.get<DutyValidationResponse>(`/scenarios/${scenarioId}/duties/validate`),
};
