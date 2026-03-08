// ── API response / request DTOs ───────────────────────────────
import type {
  Scenario,
  Depot,
  Vehicle,
  VehicleTemplate,
  Route,
  Stop,
  Trip,
  TimetableRow,
  ServiceCalendar,
  CalendarDate,
  DepotRoutePermission,
  VehicleRoutePermission,
  DeadheadRule,
  TurnaroundRule,
  ConnectionGraph,
  VehicleDuty,
  DutyValidationResult,
  DispatchScope,
  SimulationResult,
  SimulationConfig,
  OptimizationResult,
  Job,
  RunCapabilities,
} from "./domain";

// ── Generic wrappers ──────────────────────────────────────────

export interface ApiListResponse<T> {
  items: T[];
  total: number;
}

export interface ApiError {
  detail: string;
  status: number;
}

// ── Scenario ──────────────────────────────────────────────────

export type ScenarioListResponse = ApiListResponse<Scenario>;
export type ScenarioDetailResponse = Scenario;

export interface CreateScenarioRequest {
  name: string;
  description: string;
  mode: Scenario["mode"];
}

export interface UpdateScenarioRequest {
  name?: string;
  description?: string;
  mode?: Scenario["mode"];
}

// ── Depots ────────────────────────────────────────────────────

export type DepotsResponse = ApiListResponse<Depot>;
export type DepotDetailResponse = Depot;

export interface CreateDepotRequest {
  name: string;
  location: string;
  lat?: number;
  lon?: number;
  normalChargerCount?: number;
  normalChargerPowerKw?: number;
  fastChargerCount?: number;
  fastChargerPowerKw?: number;
  hasFuelFacility?: boolean;
  parkingCapacity?: number;
  overnightCharging?: boolean;
  notes?: string;
}

export type UpdateDepotRequest = Partial<CreateDepotRequest>;

// ── Vehicles ──────────────────────────────────────────────────

export type VehiclesResponse = ApiListResponse<Vehicle>;
export type VehicleDetailResponse = Vehicle;
export type VehicleTemplatesResponse = ApiListResponse<VehicleTemplate>;
export type VehicleTemplateDetailResponse = VehicleTemplate;

export interface CreateVehicleRequest {
  depotId: string;
  type: Vehicle["type"];
  modelName: string;
  capacityPassengers: number;
  batteryKwh?: number | null;
  fuelTankL?: number | null;
  energyConsumption: number;
  chargePowerKw?: number | null;
  minSoc?: number | null;
  maxSoc?: number | null;
  acquisitionCost?: number;
  enabled?: boolean;
}

export type UpdateVehicleRequest = Partial<CreateVehicleRequest>;

export interface CreateVehicleBatchRequest extends CreateVehicleRequest {
  quantity: number;
}

export interface DuplicateVehicleBatchRequest {
  quantity: number;
  targetDepotId?: string;
}

export interface CreateVehicleTemplateRequest {
  name: string;
  type: Vehicle["type"];
  modelName: string;
  capacityPassengers: number;
  batteryKwh?: number | null;
  fuelTankL?: number | null;
  energyConsumption: number;
  chargePowerKw?: number | null;
  minSoc?: number | null;
  maxSoc?: number | null;
  acquisitionCost?: number;
  enabled?: boolean;
}

export type UpdateVehicleTemplateRequest = Partial<CreateVehicleTemplateRequest>;

// ── Routes ────────────────────────────────────────────────────

export type ImportSource = "odpt" | "gtfs" | string;

export interface RouteImportQuality {
  routeCount: number;
  warningCount: number;
  zeroDurationCount: number;
  zeroDistanceCount: number;
  noTripCount: number;
  durationSources: Record<string, number>;
  distanceSources: Record<string, number>;
}

export interface RouteImportMeta {
  operator?: string;
  dump?: boolean;
  requestedDump?: boolean;
  feedPath?: string;
  agencyName?: string;
  source: ImportSource;
  resourceType?: string;
  generatedAt?: string;
  warnings: string[];
  snapshotKey?: string;
  snapshotMode?: string;
  cache?: {
    stops?: boolean;
    patterns?: boolean;
    stopTimetables?: boolean;
    timetables?: boolean;
    timetableChunks?: number;
  };
  quality: RouteImportQuality;
}

export interface RoutesResponse extends ApiListResponse<Route> {
  meta?: {
    imports?: Partial<Record<string, RouteImportMeta>>;
  };
}

export type RouteDetailResponse = Route;

export interface CreateRouteRequest {
  name: string;
  startStop: string;
  endStop: string;
  distanceKm: number;
  durationMin: number;
  color?: string;
  enabled?: boolean;
}

export type UpdateRouteRequest = Partial<CreateRouteRequest>;

export interface ImportOdptRoutesRequest {
  operator?: string;
  dump?: boolean;
  forceRefresh?: boolean;
  ttlSec?: number;
}

export interface ImportOdptRoutesResponse extends ApiListResponse<Route> {
  allRoutesTotal: number;
  meta: RouteImportMeta;
}

export interface ImportGtfsRoutesRequest {
  feedPath?: string;
}

export interface ImportGtfsRoutesResponse extends ApiListResponse<Route> {
  allRoutesTotal: number;
  meta: RouteImportMeta;
}

export interface StopImportQuality {
  stopCount: number;
  namedCount: number;
  geoCount: number;
  poleNumberCount: number;
  warningCount: number;
}

export interface StopImportMeta {
  operator?: string;
  dump?: boolean;
  requestedDump?: boolean;
  feedPath?: string;
  agencyName?: string;
  source: ImportSource;
  resourceType?: string;
  generatedAt?: string;
  warnings: string[];
  snapshotKey?: string;
  snapshotMode?: string;
  cache?: {
    stops?: boolean;
    patterns?: boolean;
    stopTimetables?: boolean;
    timetables?: boolean;
    timetableChunks?: number;
  };
  quality: StopImportQuality;
}

export interface StopsResponse extends ApiListResponse<Stop> {
  meta?: {
    imports?: Partial<Record<string, StopImportMeta>>;
  };
}

export type StopDetailResponse = Stop;

export interface ImportOdptStopsRequest {
  operator?: string;
  dump?: boolean;
  forceRefresh?: boolean;
  ttlSec?: number;
}

export interface ImportOdptStopsResponse extends ApiListResponse<Stop> {
  allStopsTotal: number;
  meta: StopImportMeta;
}

export interface ImportGtfsStopsRequest {
  feedPath?: string;
}

export interface ImportGtfsStopsResponse extends ApiListResponse<Stop> {
  allStopsTotal: number;
  meta: StopImportMeta;
}

// ── Timetable / Trips ────────────────────────────────────────

export interface TimetableImportQuality {
  rowCount: number;
  routeCount: number;
  serviceCounts: Record<string, number>;
  stopTimetableCount: number;
  warningCount: number;
}

export interface ImportProgress {
  cursor: number;
  nextCursor: number;
  totalChunks: number;
  complete: boolean;
}

export interface TimetableImportMeta {
  operator?: string;
  dump?: boolean;
  requestedDump?: boolean;
  feedPath?: string;
  agencyName?: string;
  source: ImportSource;
  resourceType?: string;
  generatedAt?: string;
  warnings: string[];
  snapshotKey?: string;
  snapshotMode?: string;
  cache?: {
    stops?: boolean;
    patterns?: boolean;
    stopTimetables?: boolean;
    timetables?: boolean;
    timetableChunks?: number;
  };
  progress?: ImportProgress;
  quality: TimetableImportQuality;
}

export interface TimetableResponse extends ApiListResponse<TimetableRow> {
  meta?: {
    imports?: Partial<Record<string, TimetableImportMeta>>;
  };
}

export interface UpdateTimetableRequest {
  rows: TimetableRow[];
}

export interface ImportOdptTimetableRequest {
  operator?: string;
  dump?: boolean;
  forceRefresh?: boolean;
  ttlSec?: number;
  chunkBusTimetables?: boolean;
  busTimetableCursor?: number;
  busTimetableBatchSize?: number;
  reset?: boolean;
}

export interface ImportOdptTimetableResponse extends ApiListResponse<TimetableRow> {
  meta: TimetableImportMeta;
}

export interface ImportGtfsTimetableRequest {
  feedPath?: string;
  reset?: boolean;
}

export interface ImportGtfsTimetableResponse extends ApiListResponse<TimetableRow> {
  meta: TimetableImportMeta;
}

export interface StopTimetableItem {
  index: number;
  arrival?: string;
  departure?: string;
  busroutePattern?: string;
  busTimetable?: string;
  destinationSign?: string;
}

export interface StopTimetable {
  id: string;
  source?: string;
  stopId: string;
  stopName: string;
  calendar?: string;
  service_id: string;
  items: StopTimetableItem[];
}

export interface StopTimetableImportQuality {
  stopTimetableCount: number;
  entryCount: number;
  serviceCounts: Record<string, number>;
  warningCount: number;
}

export interface StopTimetableImportMeta {
  operator?: string;
  dump?: boolean;
  requestedDump?: boolean;
  feedPath?: string;
  agencyName?: string;
  source: ImportSource;
  resourceType?: string;
  generatedAt?: string;
  warnings: string[];
  snapshotKey?: string;
  snapshotMode?: string;
  cache?: {
    stops?: boolean;
    patterns?: boolean;
    stopTimetables?: boolean;
    timetables?: boolean;
    timetableChunks?: number;
  };
  progress?: ImportProgress;
  quality: StopTimetableImportQuality;
}

export interface StopTimetablesResponse extends ApiListResponse<StopTimetable> {
  meta?: {
    imports?: Partial<Record<string, StopTimetableImportMeta>>;
  };
}

export interface ImportOdptStopTimetableRequest {
  operator?: string;
  dump?: boolean;
  forceRefresh?: boolean;
  ttlSec?: number;
  stopTimetableCursor?: number;
  stopTimetableBatchSize?: number;
  reset?: boolean;
}

export interface ImportOdptStopTimetableResponse
  extends ApiListResponse<StopTimetable> {
  meta: StopTimetableImportMeta;
}

export interface ImportGtfsStopTimetableRequest {
  feedPath?: string;
  reset?: boolean;
}

export interface ImportGtfsStopTimetableResponse
  extends ApiListResponse<StopTimetable> {
  meta: StopTimetableImportMeta;
}

/** Import CSV: send raw CSV text as JSON envelope */
export interface ImportCsvRequest {
  content: string;
}

/** Export CSV response: JSON envelope containing the CSV text */
export interface ExportCsvResponse {
  content: string;
  filename: string;
  rows: number;
}

export type TripsResponse = ApiListResponse<Trip>;

export interface BuildTripsRequest {
  force?: boolean;
  service_id?: string;
  depot_id?: string;
}

// ── Calendar ──────────────────────────────────────────────────

export type CalendarResponse = ApiListResponse<ServiceCalendar>;
export type CalendarDatesResponse = ApiListResponse<CalendarDate>;

export interface UpdateCalendarRequest {
  entries: ServiceCalendar[];
}

export interface UpsertCalendarEntryRequest {
  service_id: string;
  name?: string;
  mon?: 0 | 1;
  tue?: 0 | 1;
  wed?: 0 | 1;
  thu?: 0 | 1;
  fri?: 0 | 1;
  sat?: 0 | 1;
  sun?: 0 | 1;
  start_date?: string;
  end_date?: string;
}

export interface UpdateCalendarDatesRequest {
  entries: CalendarDate[];
}

export interface UpsertCalendarDateRequest {
  date: string;
  service_id: string;
  exception_type?: "ADD" | "REMOVE";
}

// ── Permissions ───────────────────────────────────────────────

export type DepotRoutePermissionsResponse = ApiListResponse<DepotRoutePermission>;
export type VehicleRoutePermissionsResponse = ApiListResponse<VehicleRoutePermission>;

export interface UpdateDepotRoutePermissionsRequest {
  permissions: DepotRoutePermission[];
}

export interface UpdateVehicleRoutePermissionsRequest {
  permissions: VehicleRoutePermission[];
}

// ── Rules ─────────────────────────────────────────────────────

export type DeadheadRulesResponse = ApiListResponse<DeadheadRule>;
export type TurnaroundRulesResponse = ApiListResponse<TurnaroundRule>;

// ── Graph ─────────────────────────────────────────────────────

export type GraphResponse = ConnectionGraph;

export interface BuildGraphRequest {
  force?: boolean;
  service_id?: string;
  depot_id?: string;
}

// ── Duties ────────────────────────────────────────────────────

export type DutiesResponse = ApiListResponse<VehicleDuty>;
export type DutyValidationResponse = ApiListResponse<DutyValidationResult>;

export interface GenerateDutiesRequest {
  vehicle_type?: string;
  strategy?: "greedy" | "milp";
  service_id?: string;
  depot_id?: string;
}

// ── Simulation ────────────────────────────────────────────────

export type SimulationResultResponse = SimulationResult;
export type SimulationConfigResponse = SimulationConfig;
export type DispatchScopeResponse = DispatchScope;
export type SimulationCapabilitiesResponse = RunCapabilities;

export interface UpdateDispatchScopeRequest {
  depotId?: string | null;
  serviceId?: string;
}

export interface RunSimulationRequest {
  force?: boolean;
  service_id?: string;
  depot_id?: string;
}

// ── Optimization ──────────────────────────────────────────────

export type OptimizationResultResponse = OptimizationResult;
export type OptimizationCapabilitiesResponse = RunCapabilities;

export interface RunOptimizationRequest {
  mode: Scenario["mode"];
  time_limit_seconds?: number;
  mip_gap?: number;
  service_id?: string;
  depot_id?: string;
  rebuild_dispatch?: boolean;
  use_existing_duties?: boolean;
  alns_iterations?: number;
}

export interface DelayEventRequest {
  trip_id: string;
  delay_min: number;
}

export interface ReoptimizeRequest {
  mode?: string;
  current_time: string;
  time_limit_seconds?: number;
  mip_gap?: number;
  alns_iterations?: number;
  service_id?: string;
  depot_id?: string;
  actual_soc?: Record<string, number>;
  actual_location_node_id?: Record<string, string>;
  delays?: DelayEventRequest[];
  updated_pv_profile?: Array<Record<string, unknown>>;
}

// ── Jobs ──────────────────────────────────────────────────────

export type JobResponse = Job;
