import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { scenarioApi } from "@/api";
import type {
  CreateScenarioRequest,
  UpdateScenarioRequest,
  UpdateTimetableRequest,
  ImportOdptTimetableRequest,
  ImportOdptStopTimetableRequest,
  ImportCsvRequest,
  UpdateCalendarRequest,
  UpsertCalendarEntryRequest,
  UpdateCalendarDatesRequest,
  UpsertCalendarDateRequest,
} from "@/types";

// ── Query keys ────────────────────────────────────────────────

export const scenarioKeys = {
  all: ["scenarios"] as const,
  detail: (id: string) => ["scenarios", id] as const,
  timetable: (id: string, serviceId?: string) =>
    ["scenarios", id, "timetable", serviceId ?? "all"] as const,
  calendar: (id: string) => ["scenarios", id, "calendar"] as const,
  calendarDates: (id: string) => ["scenarios", id, "calendar-dates"] as const,
  stopTimetables: (id: string, stopId?: string, serviceId?: string) =>
    ["scenarios", id, "stop-timetables", stopId ?? "all", serviceId ?? "all"] as const,
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

export function useTimetable(scenarioId: string, serviceId?: string) {
  return useQuery({
    queryKey: scenarioKeys.timetable(scenarioId, serviceId),
    queryFn: () => scenarioApi.getTimetable(scenarioId, serviceId),
    enabled: !!scenarioId,
  });
}

export function useCalendar(scenarioId: string) {
  return useQuery({
    queryKey: scenarioKeys.calendar(scenarioId),
    queryFn: () => scenarioApi.getCalendar(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useCalendarDates(scenarioId: string) {
  return useQuery({
    queryKey: scenarioKeys.calendarDates(scenarioId),
    queryFn: () => scenarioApi.getCalendarDates(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useStopTimetables(
  scenarioId: string,
  stopId?: string,
  serviceId?: string,
) {
  return useQuery({
    queryKey: scenarioKeys.stopTimetables(scenarioId, stopId, serviceId),
    queryFn: () => scenarioApi.getStopTimetables(scenarioId, stopId, serviceId),
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
      // Invalidate all timetable variants (any service_id filter)
      qc.invalidateQueries({
        queryKey: ["scenarios", scenarioId, "timetable"],
        exact: false,
      });
    },
  });
}

export function useImportTimetableCsv(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ImportCsvRequest) =>
      scenarioApi.importCsv(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["scenarios", scenarioId, "timetable"],
        exact: false,
      });
    },
  });
}

export function useImportOdptTimetable(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportOdptTimetableRequest) =>
      scenarioApi.importOdptTimetable(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["scenarios", scenarioId, "timetable"],
        exact: false,
      });
    },
  });
}

export function useImportOdptStopTimetables(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportOdptStopTimetableRequest) =>
      scenarioApi.importOdptStopTimetables(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["scenarios", scenarioId, "stop-timetables"],
        exact: false,
      });
    },
  });
}

export function useExportTimetableCsv(scenarioId: string) {
  return useMutation({
    mutationFn: (serviceId?: string) =>
      scenarioApi.exportCsv(scenarioId, serviceId),
  });
}

// ── Calendar mutations ────────────────────────────────────────

export function useUpdateCalendar(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateCalendarRequest) =>
      scenarioApi.updateCalendar(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendar(scenarioId) });
    },
  });
}

export function useUpsertCalendarEntry(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      serviceId,
      data,
    }: {
      serviceId: string;
      data: UpsertCalendarEntryRequest;
    }) => scenarioApi.upsertCalendarEntry(scenarioId, serviceId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendar(scenarioId) });
    },
  });
}

export function useDeleteCalendarEntry(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serviceId: string) =>
      scenarioApi.deleteCalendarEntry(scenarioId, serviceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendar(scenarioId) });
    },
  });
}

export function useUpdateCalendarDates(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateCalendarDatesRequest) =>
      scenarioApi.updateCalendarDates(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendarDates(scenarioId) });
    },
  });
}

export function useUpsertCalendarDate(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      date,
      data,
    }: {
      date: string;
      data: UpsertCalendarDateRequest;
    }) => scenarioApi.upsertCalendarDate(scenarioId, date, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendarDates(scenarioId) });
    },
  });
}

export function useDeleteCalendarDate(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (date: string) =>
      scenarioApi.deleteCalendarDate(scenarioId, date),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scenarioKeys.calendarDates(scenarioId) });
    },
  });
}
