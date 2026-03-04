import { api } from "./client";
import type {
  OptimizationResultResponse,
  RunOptimizationRequest,
  JobResponse,
} from "@/types";

export const optimizationApi = {
  getResult: (scenarioId: string) =>
    api.get<OptimizationResultResponse>(`/scenarios/${scenarioId}/optimization`),

  run: (scenarioId: string, data: RunOptimizationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/run-optimization`, data),
};
