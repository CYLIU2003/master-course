// ── Domain re-exports ─────────────────────────────────────────
export type {
  Scenario,
  ScenarioStatus,
  SolverMode,
  HHMMTime,
  MinutesFromMidnight,
  // Master data
  Depot,
  Vehicle,
  VehicleTemplate,
  VehiclePowerType,
  Route,
  Trip,
  TimetableRow,
  DepotRoutePermission,
  VehicleRoutePermission,
  // Rules
  DeadheadRule,
  TurnaroundRule,
  // Graph
  ConnectionArc,
  ConnectionGraph,
  FeasibilityReason,
  // Duties
  DutyLeg,
  VehicleDuty,
  DutyValidationResult,
  // Simulation config
  SimulationConfig,
  TouPriceSlot,
  // Results
  SimulationResult,
  EnergyRecord,
  SocTracePoint,
  OptimizationResult,
  ChargingSlot,
  CostBreakdown,
  // Jobs
  Job,
  JobStatus,
  // Derived
  DepotSummary,
  RouteSummary,
} from "./domain";

// ── API DTO re-exports ────────────────────────────────────────
export type {
  ApiListResponse,
  ApiError,
  // Scenario
  ScenarioListResponse,
  ScenarioDetailResponse,
  CreateScenarioRequest,
  UpdateScenarioRequest,
  // Depots
  DepotsResponse,
  DepotDetailResponse,
  CreateDepotRequest,
  UpdateDepotRequest,
  // Vehicles
  VehiclesResponse,
  VehicleDetailResponse,
  CreateVehicleRequest,
  CreateVehicleBatchRequest,
  DuplicateVehicleBatchRequest,
  UpdateVehicleRequest,
  VehicleTemplatesResponse,
  VehicleTemplateDetailResponse,
  CreateVehicleTemplateRequest,
  UpdateVehicleTemplateRequest,
  // Routes
  RoutesResponse,
  RouteDetailResponse,
  CreateRouteRequest,
  UpdateRouteRequest,
  ImportOdptRoutesRequest,
  ImportOdptRoutesResponse,
  // Timetable / Trips
  TimetableResponse,
  UpdateTimetableRequest,
  ImportOdptTimetableRequest,
  ImportOdptTimetableResponse,
  ImportOdptStopTimetableRequest,
  ImportOdptStopTimetableResponse,
  StopTimetablesResponse,
  ImportCsvRequest,
  ExportCsvResponse,
  TripsResponse,
  BuildTripsRequest,
  // Calendar
  CalendarResponse,
  CalendarDatesResponse,
  UpdateCalendarRequest,
  UpsertCalendarEntryRequest,
  UpdateCalendarDatesRequest,
  UpsertCalendarDateRequest,
  // Permissions
  DepotRoutePermissionsResponse,
  VehicleRoutePermissionsResponse,
  UpdateDepotRoutePermissionsRequest,
  UpdateVehicleRoutePermissionsRequest,
  // Rules
  DeadheadRulesResponse,
  TurnaroundRulesResponse,
  // Graph
  GraphResponse,
  BuildGraphRequest,
  // Duties
  DutiesResponse,
  DutyValidationResponse,
  GenerateDutiesRequest,
  // Simulation
  SimulationResultResponse,
  SimulationConfigResponse,
  RunSimulationRequest,
  // Optimization
  OptimizationResultResponse,
  RunOptimizationRequest,
  // Jobs
  JobResponse,
} from "./api";
