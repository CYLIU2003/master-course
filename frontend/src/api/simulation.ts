import { api } from "./client";
import type {
  SimulationResultResponse,
  SimulationCapabilitiesResponse,
  RunSimulationRequest,
  JobResponse,
} from "@/types";

export const simulationApi = {
  getResult: (scenarioId: string) =>
    api.get<SimulationResultResponse>(`/scenarios/${scenarioId}/simulation`),

  getCapabilities: (scenarioId: string) =>
    api.get<SimulationCapabilitiesResponse>(
      `/scenarios/${scenarioId}/simulation/capabilities`,
    ),

  run: (scenarioId: string, data?: RunSimulationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/run-simulation`, data),
};
