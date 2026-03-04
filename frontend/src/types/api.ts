// ── API response / request DTOs ───────────────────────────────
import type {
  Scenario,
  Depot,
  Vehicle,
  Route,
  Trip,
  TimetableRow,
  DepotRoutePermission,
  VehicleRoutePermission,
  DeadheadRule,
  TurnaroundRule,
  ConnectionGraph,
  VehicleDuty,
  DutyValidationResult,
  SimulationResult,
  SimulationConfig,
  OptimizationResult,
  Job,
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

// ── Routes ────────────────────────────────────────────────────

export type RoutesResponse = ApiListResponse<Route>;
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

// ── Timetable / Trips ────────────────────────────────────────

export type TimetableResponse = ApiListResponse<TimetableRow>;

export interface UpdateTimetableRequest {
  rows: TimetableRow[];
}

export type TripsResponse = ApiListResponse<Trip>;

export interface BuildTripsRequest {
  force?: boolean;
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
}

// ── Duties ────────────────────────────────────────────────────

export type DutiesResponse = ApiListResponse<VehicleDuty>;
export type DutyValidationResponse = ApiListResponse<DutyValidationResult>;

export interface GenerateDutiesRequest {
  vehicle_type?: string;
  strategy?: "greedy" | "milp";
}

// ── Simulation ────────────────────────────────────────────────

export type SimulationResultResponse = SimulationResult;
export type SimulationConfigResponse = SimulationConfig;

export interface RunSimulationRequest {
  force?: boolean;
}

// ── Optimization ──────────────────────────────────────────────

export type OptimizationResultResponse = OptimizationResult;

export interface RunOptimizationRequest {
  mode: Scenario["mode"];
  time_limit_seconds?: number;
  mip_gap?: number;
}

// ── Jobs ──────────────────────────────────────────────────────

export type JobResponse = Job;
