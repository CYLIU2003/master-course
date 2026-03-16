import { api } from "./client";
import type {
  ScenarioListResponse,
  ScenarioDetailResponse,
  EditorBootstrapResponse,
  EditorBootstrapLiteResponse,
  QuickSetupResponse,
  UpdateQuickSetupRequest,
  CreateScenarioRequest,
  UpdateScenarioRequest,
  TimetableResponse,
  TimetableSummaryResponse,
  UpdateTimetableRequest,
  ImportOdptTimetableRequest,
  ImportOdptTimetableResponse,
  ImportGtfsTimetableRequest,
  ImportGtfsTimetableResponse,
  ImportOdptStopTimetableRequest,
  ImportOdptStopTimetableResponse,
  ImportGtfsStopTimetableRequest,
  ImportGtfsStopTimetableResponse,
  StopTimetablesResponse,
  StopTimetableSummaryResponse,
  ImportCsvRequest,
  ExportCsvResponse,
  CalendarResponse,
  CalendarDatesResponse,
  UpdateCalendarRequest,
  UpsertCalendarEntryRequest,
  UpdateCalendarDatesRequest,
  UpsertCalendarDateRequest,
  DeadheadRulesResponse,
  TurnaroundRulesResponse,
  DispatchScopeResponse,
  UpdateDispatchScopeRequest,
} from "@/types";

let lastActivatedScenarioId: string | null = null;
const activationRequests = new Map<string, Promise<void>>();

export async function ensureScenarioActivated(id: string): Promise<void> {
  if (!id) {
    return;
  }
  if (lastActivatedScenarioId === id) {
    return;
  }
  const existing = activationRequests.get(id);
  if (existing) {
    return existing;
  }
  const request = api
    .post(`/scenarios/${id}/activate`)
    .then(() => {
      lastActivatedScenarioId = id;
    })
    .finally(() => {
      activationRequests.delete(id);
    });
  activationRequests.set(id, request);
  return request;
}

// ── Scenarios ─────────────────────────────────────────────────

export const scenarioApi = {
  list: () => api.get<ScenarioListResponse>("/scenarios"),

  get: (id: string) => api.get<ScenarioDetailResponse>(`/scenarios/${id}`),

  getEditorBootstrap: (id: string) =>
    api.get<EditorBootstrapResponse>(`/scenarios/${id}/editor-bootstrap`),

  getEditorBootstrapLite: (id: string) =>
    api.get<EditorBootstrapLiteResponse>(`/scenarios/${id}/editor-bootstrap-lite`),

  getQuickSetup: (
    id: string,
    options?: { depotIds?: string[]; routeLimit?: number },
  ) => {
    const query = new URLSearchParams();
    if (options?.depotIds?.length) {
      query.set("depotIds", options.depotIds.join(","));
    }
    if (typeof options?.routeLimit === "number") {
      query.set("routeLimit", String(options.routeLimit));
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<QuickSetupResponse>(`/scenarios/${id}/quick-setup${suffix}`);
  },

  updateQuickSetup: (id: string, data: UpdateQuickSetupRequest) =>
    api.put<QuickSetupResponse>(`/scenarios/${id}/quick-setup`, data),

  create: (data: CreateScenarioRequest) =>
    api.post<ScenarioDetailResponse>("/scenarios", data),

  update: (id: string, data: UpdateScenarioRequest) =>
    api.put<ScenarioDetailResponse>(`/scenarios/${id}`, data),

  getDispatchScope: (id: string) =>
    api.get<DispatchScopeResponse>(`/scenarios/${id}/dispatch-scope`),

  updateDispatchScope: (id: string, data: UpdateDispatchScopeRequest) =>
    api.put<DispatchScopeResponse>(`/scenarios/${id}/dispatch-scope`, data),

  delete: (id: string) => api.delete<void>(`/scenarios/${id}`),

  activate: (id: string) => ensureScenarioActivated(id),

  // ── Timetable ───────────────────────────────────────────────

  getTimetable: (
    id: string,
    serviceId?: string,
    options?: { limit?: number; offset?: number },
  ) => {
    const params = new URLSearchParams();
    if (serviceId) {
      params.set("service_id", serviceId);
    }
    if (typeof options?.limit === "number") {
      params.set("limit", String(options.limit));
    }
    if (typeof options?.offset === "number") {
      params.set("offset", String(options.offset));
    }
    const qs = params.toString();
    return api.get<TimetableResponse>(
      `/scenarios/${id}/timetable${qs ? `?${qs}` : ""}`,
    );
  },

  getTimetableSummary: (id: string) =>
    api.get<TimetableSummaryResponse>(`/scenarios/${id}/timetable/summary`),

  updateTimetable: (id: string, data: UpdateTimetableRequest) =>
    api.put<TimetableResponse>(`/scenarios/${id}/timetable`, data),

  importCsv: (id: string, data: ImportCsvRequest) =>
    api.post<TimetableResponse>(`/scenarios/${id}/timetable/import-csv`, data),

  importOdptTimetable: (id: string, data?: ImportOdptTimetableRequest) =>
    api.post<ImportOdptTimetableResponse>(
      `/scenarios/${id}/timetable/import-odpt`,
      data,
    ),

  importGtfsTimetable: (id: string, data?: ImportGtfsTimetableRequest) =>
    api.post<ImportGtfsTimetableResponse>(
      `/scenarios/${id}/timetable/import-gtfs`,
      data,
    ),

  getStopTimetables: (
    id: string,
    stopId?: string,
    serviceId?: string,
    options?: { limit?: number; offset?: number },
  ) => {
    const params = new URLSearchParams();
    if (stopId) params.set("stop_id", stopId);
    if (serviceId) params.set("service_id", serviceId);
    if (typeof options?.limit === "number") params.set("limit", String(options.limit));
    if (typeof options?.offset === "number") params.set("offset", String(options.offset));
    const qs = params.toString();
    return api.get<StopTimetablesResponse>(
      `/scenarios/${id}/stop-timetables${qs ? `?${qs}` : ""}`,
    );
  },

  getStopTimetablesSummary: (id: string) =>
    api.get<StopTimetableSummaryResponse>(`/scenarios/${id}/stop-timetables/summary`),

  importOdptStopTimetables: (
    id: string,
    data?: ImportOdptStopTimetableRequest,
  ) => api.post<ImportOdptStopTimetableResponse>(
    `/scenarios/${id}/stop-timetables/import-odpt`,
    data,
  ),

  importGtfsStopTimetables: (
    id: string,
    data?: ImportGtfsStopTimetableRequest,
  ) => api.post<ImportGtfsStopTimetableResponse>(
    `/scenarios/${id}/stop-timetables/import-gtfs`,
    data,
  ),

  exportCsv: (id: string, serviceId?: string) => {
    const qs = serviceId ? `?service_id=${encodeURIComponent(serviceId)}` : "";
    return api.get<ExportCsvResponse>(`/scenarios/${id}/timetable/export-csv${qs}`);
  },

  // ── Calendar (service_id definitions) ───────────────────────

  getCalendar: (id: string) =>
    api.get<CalendarResponse>(`/scenarios/${id}/calendar`),

  updateCalendar: (id: string, data: UpdateCalendarRequest) =>
    api.put<CalendarResponse>(`/scenarios/${id}/calendar`, data),

  upsertCalendarEntry: (id: string, serviceId: string, data: UpsertCalendarEntryRequest) =>
    api.post<CalendarResponse>(`/scenarios/${id}/calendar/${encodeURIComponent(serviceId)}`, data),

  deleteCalendarEntry: (id: string, serviceId: string) =>
    api.delete<void>(`/scenarios/${id}/calendar/${encodeURIComponent(serviceId)}`),

  // ── Calendar dates (exception overrides) ────────────────────

  getCalendarDates: (id: string) =>
    api.get<CalendarDatesResponse>(`/scenarios/${id}/calendar-dates`),

  updateCalendarDates: (id: string, data: UpdateCalendarDatesRequest) =>
    api.put<CalendarDatesResponse>(`/scenarios/${id}/calendar-dates`, data),

  upsertCalendarDate: (id: string, date: string, data: UpsertCalendarDateRequest) =>
    api.post<CalendarDatesResponse>(`/scenarios/${id}/calendar-dates/${encodeURIComponent(date)}`, data),

  deleteCalendarDate: (id: string, date: string) =>
    api.delete<void>(`/scenarios/${id}/calendar-dates/${encodeURIComponent(date)}`),

  // ── Rules ───────────────────────────────────────────────────

  getDeadheadRules: (id: string) =>
    api.get<DeadheadRulesResponse>(`/scenarios/${id}/deadhead-rules`),

  getTurnaroundRules: (id: string) =>
    api.get<TurnaroundRulesResponse>(`/scenarios/${id}/turnaround-rules`),
};
