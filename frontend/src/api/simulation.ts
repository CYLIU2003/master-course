import { api } from "./client";
import type {
  SimulationResultResponse,
  SimulationCapabilitiesResponse,
  RunSimulationRequest,
  PrepareSimulationRequest,
  SimulationPrepareResponse,
  RunPreparedSimulationRequest,
  JobResponse,
} from "@/types";

export const simulationApi = {
  getResult: (scenarioId: string) =>
    api.get<SimulationResultResponse>(`/scenarios/${scenarioId}/simulation`),

  getCapabilities: (scenarioId: string) =>
    api.get<SimulationCapabilitiesResponse>(
      `/scenarios/${scenarioId}/simulation/capabilities`,
    ),

  prepare: (scenarioId: string, data: PrepareSimulationRequest) =>
    api.post<SimulationPrepareResponse>(
      `/scenarios/${scenarioId}/simulation/prepare`,
      data,
    ),

  runPrepared: (scenarioId: string, data: RunPreparedSimulationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/simulation/run`, data),

  run: (scenarioId: string, data?: RunSimulationRequest) =>
    api.post<JobResponse>(`/scenarios/${scenarioId}/run-simulation`, data),
};
