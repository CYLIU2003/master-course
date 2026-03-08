import { api } from "./client";
import type {
  OptimizationResultResponse,
  OptimizationCapabilitiesResponse,
  ReoptimizeRequest,
  RunOptimizationRequest,
  JobResponse,
} from "@/types";

export const optimizationApi = {
  getResult: (scenarioId: string) =>
    api.get<OptimizationResultResponse>(`/scenarios/${scenarioId}/optimization`),

  getCapabilities: (scenarioId: string) =>
    api.get<OptimizationCapabilitiesResponse>(
      `/scenarios/${scenarioId}/optimization/capabilities`,
    ),

  run: (scenarioId: string, data: RunOptimizationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/run-optimization`, data),

  reoptimize: (scenarioId: string, data: ReoptimizeRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/reoptimize`, data),
};
