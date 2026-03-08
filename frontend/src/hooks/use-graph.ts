import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { graphApi } from "@/api";
import type {
  BuildTripsRequest,
  BuildGraphRequest,
  BuildBlocksRequest,
  GenerateDutiesRequest,
  BuildDispatchPlanRequest,
} from "@/types";
import { scenarioKeys } from "./use-scenario";

// ── Query keys ────────────────────────────────────────────────

export const graphKeys = {
  trips: (scenarioId: string) => ["scenarios", scenarioId, "trips"] as const,
  graph: (scenarioId: string) => ["scenarios", scenarioId, "graph"] as const,
  blocks: (scenarioId: string) => ["scenarios", scenarioId, "blocks"] as const,
  duties: (scenarioId: string) => ["scenarios", scenarioId, "duties"] as const,
  dispatchPlan: (scenarioId: string) => ["scenarios", scenarioId, "dispatch-plan"] as const,
  validation: (scenarioId: string) =>
    ["scenarios", scenarioId, "duties", "validate"] as const,
};

// ── Queries ───────────────────────────────────────────────────

export function useTrips(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.trips(scenarioId),
    queryFn: () => graphApi.getTrips(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useGraph(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.graph(scenarioId),
    queryFn: () => graphApi.getGraph(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useDuties(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.duties(scenarioId),
    queryFn: () => graphApi.getDuties(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useBlocks(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.blocks(scenarioId),
    queryFn: () => graphApi.getBlocks(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useDispatchPlan(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.dispatchPlan(scenarioId),
    queryFn: () => graphApi.getDispatchPlan(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useDutyValidation(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.validation(scenarioId),
    queryFn: () => graphApi.validateDuties(scenarioId),
    enabled: !!scenarioId,
  });
}

// ── Mutations ─────────────────────────────────────────────────

export function useBuildTrips(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: BuildTripsRequest) =>
      graphApi.buildTrips(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: graphKeys.trips(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function useBuildGraph(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: BuildGraphRequest) =>
      graphApi.buildGraph(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: graphKeys.graph(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function useGenerateDuties(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: GenerateDutiesRequest) =>
      graphApi.generateDuties(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: graphKeys.duties(scenarioId) });
      qc.invalidateQueries({ queryKey: graphKeys.validation(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function useBuildBlocks(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: BuildBlocksRequest) =>
      graphApi.buildBlocks(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: graphKeys.blocks(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}

export function useBuildDispatchPlan(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: BuildDispatchPlanRequest) =>
      graphApi.buildDispatchPlan(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: graphKeys.blocks(scenarioId) });
      qc.invalidateQueries({ queryKey: graphKeys.duties(scenarioId) });
      qc.invalidateQueries({ queryKey: graphKeys.dispatchPlan(scenarioId) });
      qc.invalidateQueries({ queryKey: graphKeys.validation(scenarioId) });
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
    },
  });
}
