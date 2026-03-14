import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { simulationApi } from "@/api/simulation";
import { optimizationApi } from "@/api/optimization";
import { isApiErrorStatus } from "@/api/client";
import type {
  RunSimulationRequest,
  PrepareSimulationRequest,
  RunPreparedSimulationRequest,
  RunOptimizationRequest,
} from "@/types";
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
    queryFn: async () => {
      try {
        return await simulationApi.getResult(scenarioId);
      } catch (error) {
        if (isApiErrorStatus(error, 404)) {
          return null;
        }
        throw error;
      }
    },
    enabled: !!scenarioId,
    staleTime: 0,
    refetchOnMount: "always",
    retry: false,
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
    queryFn: async () => {
      try {
        return await optimizationApi.getResult(scenarioId);
      } catch (error) {
        if (isApiErrorStatus(error, 404)) {
          return null;
        }
        throw error;
      }
    },
    enabled: !!scenarioId,
    staleTime: 0,
    refetchOnMount: "always",
    retry: false,
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
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function usePrepareSimulation(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: PrepareSimulationRequest) =>
      simulationApi.prepare(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
      qc.invalidateQueries({
        queryKey: scenarioKeys.dispatchScope(scenarioId),
      });
      qc.invalidateQueries({
        queryKey: scenarioKeys.editorBootstrap(scenarioId),
      });
    },
  });
}

export function useRunPreparedSimulation(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RunPreparedSimulationRequest) =>
      simulationApi.runPrepared(scenarioId, data),
    onSuccess: () => {
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
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}
