import { api } from "./client";
import type {
  SimulationResultResponse,
  RunSimulationRequest,
  JobResponse,
} from "@/types";

export const simulationApi = {
  getResult: (scenarioId: string) =>
    api.get<SimulationResultResponse>(`/scenarios/${scenarioId}/simulation`),

  run: (scenarioId: string, data?: RunSimulationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/run-simulation`, data),
};
