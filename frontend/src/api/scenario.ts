import { api } from "./client";
import type {
  ScenarioListResponse,
  ScenarioDetailResponse,
  CreateScenarioRequest,
  UpdateScenarioRequest,
  TimetableResponse,
  UpdateTimetableRequest,
  DeadheadRulesResponse,
  TurnaroundRulesResponse,
} from "@/types";

// ── Scenarios ─────────────────────────────────────────────────

export const scenarioApi = {
  list: () => api.get<ScenarioListResponse>("/scenarios"),

  get: (id: string) => api.get<ScenarioDetailResponse>(`/scenarios/${id}`),

  create: (data: CreateScenarioRequest) =>
    api.post<ScenarioDetailResponse>("/scenarios", data),

  update: (id: string, data: UpdateScenarioRequest) =>
    api.put<ScenarioDetailResponse>(`/scenarios/${id}`, data),

  delete: (id: string) => api.delete<void>(`/scenarios/${id}`),

  // ── Timetable ───────────────────────────────────────────────
  getTimetable: (id: string) =>
    api.get<TimetableResponse>(`/scenarios/${id}/timetable`),

  updateTimetable: (id: string, data: UpdateTimetableRequest) =>
    api.put<TimetableResponse>(`/scenarios/${id}/timetable`, data),

  // ── Rules ───────────────────────────────────────────────────
  getDeadheadRules: (id: string) =>
    api.get<DeadheadRulesResponse>(`/scenarios/${id}/deadhead-rules`),

  getTurnaroundRules: (id: string) =>
    api.get<TurnaroundRulesResponse>(`/scenarios/${id}/turnaround-rules`),
};
