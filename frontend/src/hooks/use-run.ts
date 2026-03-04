import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simulationApi } from "@/api";
import { optimizationApi } from "@/api";
import type { RunSimulationRequest, RunOptimizationRequest } from "@/types";
import { scenarioKeys } from "./use-scenario";

// ── Query keys ────────────────────────────────────────────────

export const runKeys = {
  simulation: (scenarioId: string) =>
    ["scenarios", scenarioId, "simulation"] as const,
  optimization: (scenarioId: string) =>
    ["scenarios", scenarioId, "optimization"] as const,
};

// ── Queries ───────────────────────────────────────────────────

export function useSimulationResult(scenarioId: string) {
  return useQuery({
    queryKey: runKeys.simulation(scenarioId),
    queryFn: () => simulationApi.getResult(scenarioId),
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
