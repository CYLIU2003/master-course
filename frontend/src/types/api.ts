// ── API response / request DTOs ───────────────────────────────
import type {
  Scenario,
  ResearchDatasetStatus,
  Depot,
  Vehicle,
  VehicleTemplate,
  Route,
  RouteFamilySummary,
  RouteFamilyDetail,
  Stop,
  Trip,
  TimetableRow,
  ServiceCalendar,
  CalendarDate,
  DepotRoutePermission,
  DepotRouteFamilyPermission,
  VehicleRoutePermission,
  VehicleRouteFamilyPermission,
  DeadheadRule,
  TurnaroundRule,
  ConnectionGraph,
  ConnectionArc,
  VehicleBlock,
  VehicleDuty,
  DutyValidationResult,
  DispatchPlanResponse,
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
  limit?: number | null;
  offset?: number;
}

export interface ApiError {
  detail: string | Record<string, unknown>;
  status: number;
}

// ── Scenario ──────────────────────────────────────────────────

export type ScenarioListResponse = ApiListResponse<Scenario>;
export type ScenarioDetailResponse = Scenario;

export interface CreateScenarioRequest {
  name: string;
  description: string;
  mode: Scenario["mode"];
  operatorId?: Scenario["operatorId"];
  datasetId?: string;
  randomSeed?: number;
}

export interface UpdateScenarioRequest {
  name?: string;
  description?: string;
  mode?: Scenario["mode"];
  operatorId?: Scenario["operatorId"];
}

export interface ResearchDatasetsResponse {
  items: ResearchDatasetStatus[];
  total: number;
  defaultDatasetId?: string | null;
}

export interface AppDataStatusResponse {
  item: ResearchDatasetStatus;
  seed_ready?: boolean;
  built_ready?: boolean;
  missing_artifacts?: string[];
  integrity_error?: string | null;
}

export interface AppStateResponse {
  dataset_id: string;
  dataset_version?: string | null;
  seed_ready: boolean;
  built_ready: boolean;
  missing_artifacts: string[];
  integrity_error?: string | null;
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

export type UpdateVehicleTemplateRequest =
  Partial<CreateVehicleTemplateRequest>;

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
    groupedByFamily?: boolean;
  };
}

export type RouteFamiliesResponse = ApiListResponse<RouteFamilySummary>;
export interface RouteFamilyDetailResponse {
  item: RouteFamilyDetail;
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

export interface UpdateRouteRequest extends Partial<CreateRouteRequest> {
  routeVariantTypeManual?: Route["routeVariantType"] | null;
  canonicalDirectionManual?: Route["canonicalDirection"] | null;
}

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
  forceRefresh?: boolean;
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
  forceRefresh?: boolean;
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

export interface TimetableServiceSummary {
  serviceId: string;
  rowCount: number;
  routeCount: number;
  firstDeparture?: string | null;
  lastArrival?: string | null;
}

export interface TimetableRouteSummary {
  routeId: string;
  rowCount: number;
  serviceCount: number;
  firstDeparture?: string | null;
  lastArrival?: string | null;
  sampleTripIds: string[];
}

export interface TimetableSummaryItem {
  totalRows: number;
  serviceCount: number;
  routeCount: number;
  stopCount: number;
  updatedAt?: string | null;
  byService: TimetableServiceSummary[];
  byRoute: TimetableRouteSummary[];
  routeServiceCounts: Record<string, Record<string, number>>;
  previewTripIds: string[];
  imports?: Partial<Record<string, TimetableImportMeta>>;
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

export interface TimetableSummaryResponse {
  item: TimetableSummaryItem;
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
  forceRefresh?: boolean;
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

export interface StopTimetableServiceSummary {
  serviceId: string;
  timetableCount: number;
  entryCount: number;
  stopCount: number;
}

export interface StopTimetableStopSummary {
  stopId: string;
  stopName: string;
  timetableCount: number;
  entryCount: number;
  serviceCount: number;
}

export interface StopTimetableSummaryItem {
  totalTimetables: number;
  totalEntries: number;
  serviceCount: number;
  stopCount: number;
  updatedAt?: string | null;
  byService: StopTimetableServiceSummary[];
  byStop: StopTimetableStopSummary[];
  imports?: Partial<Record<string, StopTimetableImportMeta>>;
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

export interface StopTimetableSummaryResponse {
  item: StopTimetableSummaryItem;
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

export interface ImportOdptStopTimetableResponse extends ApiListResponse<StopTimetable> {
  meta: StopTimetableImportMeta;
}

export interface ImportGtfsStopTimetableRequest {
  feedPath?: string;
  forceRefresh?: boolean;
  reset?: boolean;
}

export interface ImportGtfsStopTimetableResponse extends ApiListResponse<StopTimetable> {
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

export type DepotRoutePermissionsResponse =
  ApiListResponse<DepotRoutePermission>;
export type VehicleRoutePermissionsResponse =
  ApiListResponse<VehicleRoutePermission>;
export type DepotRouteFamilyPermissionsResponse =
  ApiListResponse<DepotRouteFamilyPermission>;
export type VehicleRouteFamilyPermissionsResponse =
  ApiListResponse<VehicleRouteFamilyPermission>;

export interface UpdateDepotRoutePermissionsRequest {
  permissions: DepotRoutePermission[];
}

export interface UpdateDepotRouteFamilyPermissionsRequest {
  permissions: Pick<
    DepotRouteFamilyPermission,
    "depotId" | "routeFamilyId" | "allowed"
  >[];
}

export interface UpdateVehicleRoutePermissionsRequest {
  permissions: VehicleRoutePermission[];
}

export interface UpdateVehicleRouteFamilyPermissionsRequest {
  permissions: Pick<
    VehicleRouteFamilyPermission,
    "vehicleId" | "routeFamilyId" | "allowed"
  >[];
}

// ── Rules ─────────────────────────────────────────────────────

export type DeadheadRulesResponse = ApiListResponse<DeadheadRule>;
export type TurnaroundRulesResponse = ApiListResponse<TurnaroundRule>;

// ── Graph ─────────────────────────────────────────────────────

export interface TripsSummaryByRoute {
  route_id: string;
  trip_count: number;
}

export interface TripsSummaryResponse {
  item: {
    totalTrips: number;
    routeCount: number;
    firstDeparture?: string | null;
    lastArrival?: string | null;
    byRoute: TripsSummaryByRoute[];
  };
}

export interface GraphSummaryResponse {
  item: {
    totalTrips: number;
    totalArcs: number;
    feasibleArcs: number;
    infeasibleArcs: number;
    reasonCounts: Record<string, number>;
  };
}

export type GraphResponse = ConnectionGraph;
export type GraphArcsResponse = ApiListResponse<ConnectionArc>;

export interface BuildGraphRequest {
  force?: boolean;
  service_id?: string;
  depot_id?: string;
}

// ── Duties ────────────────────────────────────────────────────

export type BlocksResponse = ApiListResponse<VehicleBlock>;
export type DutiesResponse = ApiListResponse<VehicleDuty>;
export type DutyValidationResponse = ApiListResponse<DutyValidationResult>;
export type DispatchPlanArtifactResponse = DispatchPlanResponse;
export interface DutiesSummaryResponse {
  item: {
    totalDuties: number;
    totalLegs: number;
    averageLegsPerDuty: number;
    totalDistanceKm: number;
    vehicleTypeCounts: Record<string, number>;
  };
}

export interface BuildBlocksRequest {
  vehicle_type?: string;
  strategy?: "greedy" | "milp";
  service_id?: string;
  depot_id?: string;
}

export interface GenerateDutiesRequest {
  vehicle_type?: string;
  strategy?: "greedy" | "milp";
  service_id?: string;
  depot_id?: string;
}

export interface BuildDispatchPlanRequest {
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
  scopeId?: string | null;
  operatorId?: string | null;
  datasetVersion?: string | null;
  depotId?: string | null;
  serviceId?: string;
  depotSelection?: {
    mode?: "include";
    depotIds?: string[];
    primaryDepotId?: string | null;
  };
  routeSelection?: {
    mode?: "all" | "include" | "exclude" | "refine";
    includeRouteIds?: string[];
    excludeRouteIds?: string[];
  };
  serviceSelection?: {
    serviceIds?: string[];
  };
  tripSelection?: {
    includeShortTurn?: boolean;
    includeDepotMoves?: boolean;
    includeDeadhead?: boolean;
  };
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
