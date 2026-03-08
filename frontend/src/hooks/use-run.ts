import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simulationApi } from "@/api/simulation";
import { optimizationApi } from "@/api/optimization";
import type { RunSimulationRequest, RunOptimizationRequest } from "@/types";
import { scenarioKeys } from "./use-scenario";

// ── Query keys ────────────────────────────────────────────────

export const runKeys = {
  simulation: (scenarioId: string) =>
    ["scenarios", scenarioId, "simulation"] as const,
  simulationCapabilities: (scenarioId: string) =>
    ["scenarios", scenarioId, "simulation", "capabilities"] as const,
  optimization: (scenarioId: string) =>
    ["scenarios", scenarioId, "optimization"] as const,
  optimizationCapabilities: (scenarioId: string) =>
    ["scenarios", scenarioId, "optimization", "capabilities"] as const,
};

// ── Queries ───────────────────────────────────────────────────

export function useSimulationResult(scenarioId: string) {
  return useQuery({
    queryKey: runKeys.simulation(scenarioId),
    queryFn: () => simulationApi.getResult(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useSimulationCapabilities(scenarioId: string) {
  return useQuery({
    queryKey: runKeys.simulationCapabilities(scenarioId),
    queryFn: () => simulationApi.getCapabilities(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useOptimizationResult(scenarioId: string) {
  return useQuery({
    queryKey: runKeys.optimization(scenarioId),
    queryFn: () => optimizationApi.getResult(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useOptimizationCapabilities(scenarioId: string) {
  return useQuery({
    queryKey: runKeys.optimizationCapabilities(scenarioId),
    queryFn: () => optimizationApi.getCapabilities(scenarioId),
    enabled: !!scenarioId,
  });
}

// ── Mutations ─────────────────────────────────────────────────

export function useRunSimulation(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: RunSimulationRequest) =>
      simulationApi.run(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKeys.simulation(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function useRunOptimization(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RunOptimizationRequest) =>
      optimizationApi.run(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runKeys.optimization(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}
