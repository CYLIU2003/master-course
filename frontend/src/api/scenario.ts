import { api } from "./client";
import type {
  ScenarioListResponse,
  ScenarioDetailResponse,
  CreateScenarioRequest,
  UpdateScenarioRequest,
  TimetableResponse,
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

// ── Scenarios ─────────────────────────────────────────────────

export const scenarioApi = {
  list: () => api.get<ScenarioListResponse>("/scenarios"),

  get: (id: string) => api.get<ScenarioDetailResponse>(`/scenarios/${id}`),

  create: (data: CreateScenarioRequest) =>
    api.post<ScenarioDetailResponse>("/scenarios", data),

  update: (id: string, data: UpdateScenarioRequest) =>
    api.put<ScenarioDetailResponse>(`/scenarios/${id}`, data),

  getDispatchScope: (id: string) =>
    api.get<DispatchScopeResponse>(`/scenarios/${id}/dispatch-scope`),

  updateDispatchScope: (id: string, data: UpdateDispatchScopeRequest) =>
    api.put<DispatchScopeResponse>(`/scenarios/${id}/dispatch-scope`, data),

  delete: (id: string) => api.delete<void>(`/scenarios/${id}`),

  // ── Timetable ───────────────────────────────────────────────

  getTimetable: (id: string, serviceId?: string) => {
    const qs = serviceId ? `?service_id=${encodeURIComponent(serviceId)}` : "";
    return api.get<TimetableResponse>(`/scenarios/${id}/timetable${qs}`);
  },

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

  getStopTimetables: (id: string, stopId?: string, serviceId?: string) => {
    const params = new URLSearchParams();
    if (stopId) params.set("stop_id", stopId);
    if (serviceId) params.set("service_id", serviceId);
    const qs = params.toString();
    return api.get<StopTimetablesResponse>(
      `/scenarios/${id}/stop-timetables${qs ? `?${qs}` : ""}`,
    );
  },

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
