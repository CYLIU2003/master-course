import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { scenarioApi } from "@/api";
import type {
  CreateScenarioRequest,
  UpdateScenarioRequest,
  UpdateTimetableRequest,
} from "@/types";

// ── Query keys ────────────────────────────────────────────────

export const scenarioKeys = {
  all: ["scenarios"] as const,
  detail: (id: string) => ["scenarios", id] as const,
  timetable: (id: string) => ["scenarios", id, "timetable"] as const,
  deadheadRules: (id: string) => ["scenarios", id, "deadhead-rules"] as const,
  turnaroundRules: (id: string) => ["scenarios", id, "turnaround-rules"] as const,
};

// ── Queries ───────────────────────────────────────────────────

export function useScenarios() {
  return useQuery({
    queryKey: scenarioKeys.all,
    queryFn: scenarioApi.list,
  });
}

export function useScenario(id: string) {
  return useQuery({
    queryKey: scenarioKeys.detail(id),
    queryFn: () => scenarioApi.get(id),
    enabled: !!id,
  });
}

export function useTimetable(scenarioId: string) {
  return useQuery({
    queryKey: scenarioKeys.timetable(scenarioId),
    queryFn: () => scenarioApi.getTimetable(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useDeadheadRules(scenarioId: string) {
  return useQuery({
    queryKey: scenarioKeys.deadheadRules(scenarioId),
    queryFn: () => scenarioApi.getDeadheadRules(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useTurnaroundRules(scenarioId: string) {
  return useQuery({
    queryKey: scenarioKeys.turnaroundRules(scenarioId),
    queryFn: () => scenarioApi.getTurnaroundRules(scenarioId),
    enabled: !!scenarioId,
  });
}

// ── Mutations ─────────────────────────────────────────────────

export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateScenarioRequest) => scenarioApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: scenarioKeys.all }),
  });
}

export function useUpdateScenario(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateScenarioRequest) => scenarioApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.detail(id) });
      qc.invalidateQueries({ queryKey: scenarioKeys.all });
    },
  });
}

export function useDeleteScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => scenarioApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: scenarioKeys.all }),
  });
}

export function useUpdateTimetable(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateTimetableRequest) =>
      scenarioApi.updateTimetable(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.timetable(scenarioId) });
    },
  });
}
