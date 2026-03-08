import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { graphApi } from "@/api/graph";
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
  trips: (scenarioId: string, limit?: number, offset?: number) =>
    ["scenarios", scenarioId, "trips", limit ?? "all", offset ?? 0] as const,
  tripsSummary: (scenarioId: string) => ["scenarios", scenarioId, "trips", "summary"] as const,
  graph: (scenarioId: string) => ["scenarios", scenarioId, "graph"] as const,
  graphSummary: (scenarioId: string) => ["scenarios", scenarioId, "graph", "summary"] as const,
  graphArcs: (scenarioId: string, reasonCode?: string, limit?: number, offset?: number) =>
    ["scenarios", scenarioId, "graph", "arcs", reasonCode ?? "all", limit ?? "all", offset ?? 0] as const,
  blocks: (scenarioId: string) => ["scenarios", scenarioId, "blocks"] as const,
  duties: (scenarioId: string, limit?: number, offset?: number) =>
    ["scenarios", scenarioId, "duties", limit ?? "all", offset ?? 0] as const,
  dutiesSummary: (scenarioId: string) => ["scenarios", scenarioId, "duties", "summary"] as const,
  dispatchPlan: (scenarioId: string) => ["scenarios", scenarioId, "dispatch-plan"] as const,
  validation: (scenarioId: string) =>
    ["scenarios", scenarioId, "duties", "validate"] as const,
};

// ── Queries ───────────────────────────────────────────────────

export function useTrips(scenarioId: string, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: graphKeys.trips(scenarioId, params?.limit, params?.offset),
    queryFn: () => graphApi.getTrips(scenarioId, params),
    enabled: !!scenarioId,
  });
}

export function useTripsSummary(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.tripsSummary(scenarioId),
    queryFn: () => graphApi.getTripsSummary(scenarioId),
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

export function useGraphSummary(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.graphSummary(scenarioId),
    queryFn: () => graphApi.getGraphSummary(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useGraphArcs(
  scenarioId: string,
  params?: { reasonCode?: string; limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: graphKeys.graphArcs(
      scenarioId,
      params?.reasonCode,
      params?.limit,
      params?.offset,
    ),
    queryFn: () => graphApi.getGraphArcs(scenarioId, params),
    enabled: !!scenarioId,
  });
}

export function useDuties(scenarioId: string, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: graphKeys.duties(scenarioId, params?.limit, params?.offset),
    queryFn: () => graphApi.getDuties(scenarioId, params),
    enabled: !!scenarioId,
  });
}

export function useDutiesSummary(scenarioId: string) {
  return useQuery({
    queryKey: graphKeys.dutiesSummary(scenarioId),
    queryFn: () => graphApi.getDutiesSummary(scenarioId),
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
      qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "trips"], exact: false });
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
      qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "graph"], exact: false });
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
      qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "duties"], exact: false });
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
