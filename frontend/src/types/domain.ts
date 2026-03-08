// ── Domain types — depot-centric model ─────────────────────────
// Design principle: Depot is the parent concept. Vehicles belong to
// depots. Routes exist independently but are linked to depots and
// vehicles via permission tables.

/** HH:MM time string — the canonical time format in the backend */
export type HHMMTime = string;

/** Minutes from midnight — integer, used for comparisons */
export type MinutesFromMidnight = number;

// ── Scenario ──────────────────────────────────────────────────

export interface Scenario {
  id: string;
  name: string;
  description: string;
  mode: SolverMode;
  createdAt: string;
  updatedAt: string;
  status: ScenarioStatus;
}

export type ScenarioStatus =
  | "draft"
  | "trips_built"
  | "graph_built"
  | "duties_generated"
  | "simulated"
  | "optimized";

export type SolverMode =
  | "thesis_mode"
  | "mode_milp_only"
  | "mode_alns_only"
  | "mode_alns_milp"
  | "mode_A_journey_charge"
  | "mode_B_resource_assignment";

// ── Master Data: Depot ────────────────────────────────────────

export interface Depot {
  id: string;
  name: string;
  location: string;
  lat: number;
  lon: number;
  /** Number of normal chargers at this depot */
  normalChargerCount: number;
  /** Normal charger power output [kW] */
  normalChargerPowerKw: number;
  /** Number of fast chargers at this depot */
  fastChargerCount: number;
  /** Fast charger power output [kW] */
  fastChargerPowerKw: number;
  /** Whether fuel facilities exist */
  hasFuelFacility: boolean;
  /** Parking capacity (number of buses) */
  parkingCapacity: number;
  /** Whether overnight charging is available */
  overnightCharging: boolean;
  notes: string;
}

// ── Master Data: Vehicle ──────────────────────────────────────

export type VehiclePowerType = "BEV" | "ICE";

export interface Vehicle {
  id: string;
  /** Required: every vehicle belongs to exactly one depot */
  depotId: string;
  type: VehiclePowerType;
  modelName: string;
  /** Passenger capacity */
  capacityPassengers: number;
  /** Battery capacity [kWh] — BEV only */
  batteryKwh: number | null;
  /** Fuel tank capacity [L] — ICE only */
  fuelTankL: number | null;
  /** Energy consumption [kWh/km] for BEV, [L/km] for ICE */
  energyConsumption: number;
  /** Max charging power [kW] — BEV only */
  chargePowerKw: number | null;
  /** Minimum SOC constraint [0-1] — BEV only */
  minSoc: number | null;
  /** Maximum SOC constraint [0-1] — BEV only */
  maxSoc: number | null;
  /** Acquisition cost [JPY] */
  acquisitionCost: number;
  /** Whether this vehicle is active/available */
  enabled: boolean;
}

export interface VehicleTemplate {
  id: string;
  name: string;
  type: VehiclePowerType;
  modelName: string;
  capacityPassengers: number;
  batteryKwh: number | null;
  fuelTankL: number | null;
  energyConsumption: number;
  chargePowerKw: number | null;
  minSoc: number | null;
  maxSoc: number | null;
  acquisitionCost: number;
  enabled: boolean;
}

// ── Master Data: Route ────────────────────────────────────────

export interface Route {
  id: string;
  name: string;
  routeCode?: string;
  routeLabel?: string;
  startStop: string;
  endStop: string;
  distanceKm: number;
  durationMin: number;
  /** Display color for charts/maps */
  color: string;
  enabled: boolean;
  source?: string;
  depotId?: string | null;
  assignmentType?: string | null;
  assignmentConfidence?: number | null;
  assignmentReason?: string | null;
  odptPatternId?: string;
  odptBusrouteId?: string;
  distanceCoverageRatio?: number;
  stopSequence?: string[];
  tripCount?: number;
  durationSource?: string;
  distanceSource?: string;
}

export interface Stop {
  id: string;
  code: string;
  name: string;
  lat: number | null;
  lon: number | null;
  poleNumber?: string | null;
  source?: string;
}

// ── Master Data: Trip (belongs to Route) ──────────────────────

export interface Trip {
  trip_id: string;
  route_id: string;
  direction: "outbound" | "inbound";
  origin: string;
  destination: string;
  departure: HHMMTime;
  arrival: HHMMTime;
  departure_min: MinutesFromMidnight;
  arrival_min: MinutesFromMidnight;
  distance_km: number;
  allowed_vehicle_types: string[];
}

export interface TimetableRow {
  trip_id?: string;
  route_id: string;
  service_id: string;  // e.g. "WEEKDAY" | "SAT" | "SUN_HOL"
  direction: "outbound" | "inbound";
  trip_index: number;
  origin: string;
  destination: string;
  departure: HHMMTime;
  arrival: HHMMTime;
  distance_km: number;
  allowed_vehicle_types: string[];
  source?: string;
}

// ── Service Calendar ──────────────────────────────────────────

/** One service_id definition (analogous to GTFS calendar.txt) */
export interface ServiceCalendar {
  service_id: string;
  name: string;
  mon: 0 | 1;
  tue: 0 | 1;
  wed: 0 | 1;
  thu: 0 | 1;
  fri: 0 | 1;
  sat: 0 | 1;
  sun: 0 | 1;
  start_date: string;  // YYYY-MM-DD
  end_date: string;    // YYYY-MM-DD
}

/** Single date exception override (analogous to GTFS calendar_dates.txt) */
export interface CalendarDate {
  date: string;        // YYYY-MM-DD
  service_id: string;
  exception_type: "ADD" | "REMOVE";
}

// ── Permission Tables ─────────────────────────────────────────

/** Which depots can serve which routes */
export interface DepotRoutePermission {
  depotId: string;
  routeId: string;
  allowed: boolean;
}

/** Which vehicles can operate on which routes */
export interface VehicleRoutePermission {
  vehicleId: string;
  routeId: string;
  allowed: boolean;
}

// ── Dispatch Rules ────────────────────────────────────────────

export interface DeadheadRule {
  origin: string;
  destination: string;
  time_min: number;
  distance_km: number;
}

export interface TurnaroundRule {
  stop_id: string;
  turnaround_min: number;
}

// ── Connection Graph ──────────────────────────────────────────

export type FeasibilityReason =
  | "feasible"
  | "missing_deadhead"
  | "insufficient_time"
  | "vehicle_type_mismatch";

export interface ConnectionArc {
  from_trip_id: string;
  to_trip_id: string;
  vehicle_type: string;
  deadhead_time_min: number;
  deadhead_distance_km: number;
  turnaround_time_min: number;
  slack_min: number;
  idle_time_min: number;
  feasible: boolean;
  reason_code: FeasibilityReason;
  reason: string;
}

export interface ConnectionGraph {
  trips: Trip[];
  arcs: ConnectionArc[];
  total_arcs: number;
  feasible_arcs: number;
  infeasible_arcs: number;
  reason_counts: Partial<Record<FeasibilityReason, number>>;
}

// ── Duties ────────────────────────────────────────────────────

export interface DutyLeg {
  trip: Trip;
  deadhead_time_min: number;
  deadhead_distance_km: number;
}

export interface VehicleDuty {
  duty_id: string;
  vehicle_type: string;
  legs: DutyLeg[];
  total_distance_km: number;
  total_deadhead_km: number;
  total_service_time_min: number;
  start_time: HHMMTime;
  end_time: HHMMTime;
}

export interface DutyValidationResult {
  duty_id: string;
  valid: boolean;
  errors: string[];
}

export interface DispatchScope {
  depotId: string | null;
  serviceId: string;
}

// ── Simulation Config ─────────────────────────────────────────

export interface SimulationConfig {
  /** Simulation period start date */
  startDate: string;
  /** Simulation period end date */
  endDate: string;
  /** Target timetable date(s) */
  serviceDate: string;
  /** Flat electricity price [JPY/kWh] */
  electricityPriceFlat: number;
  /** TOU pricing schedule — overrides flat if non-empty */
  touPricing: TouPriceSlot[];
  /** Contract demand limit [kW] */
  contractDemandKw: number;
  /** Demand charge penalty mode */
  demandPenaltyMode: "soft" | "hard";
  /** Demand charge cost [JPY/kW] */
  demandChargeCostPerKw: number;
  /** Whether PV is enabled */
  pvEnabled: boolean;
  /** PV output scaling factor */
  pvScale: number;
  /** Diesel fuel price [JPY/L] */
  dieselPricePerL: number;
  /** Initial SOC [0-1] */
  initialSoc: number;
  /** Random seed for stochastic elements */
  randomSeed: number | null;
  /** Optimization mode */
  optimizationMode: SolverMode;
  /** MILP time limit [seconds] */
  timeLimitSeconds: number;
  /** MIP gap tolerance */
  mipGap: number;
}

export interface TouPriceSlot {
  startHour: number;
  endHour: number;
  pricePerKwh: number;
}

// ── Simulation & Optimization Results ─────────────────────────

export interface SimulationResult {
  scenario_id: string;
  scope?: DispatchScope;
  duties: VehicleDuty[];
  energy_consumption: EnergyRecord[];
  soc_trace: SocTracePoint[];
  total_energy_kwh: number;
  total_distance_km: number;
  feasibility_violations: string[];
}

export interface EnergyRecord {
  duty_id: string;
  trip_id: string;
  energy_kwh: number;
  soc_start: number;
  soc_end: number;
}

export interface SocTracePoint {
  duty_id: string;
  time_min: MinutesFromMidnight;
  soc_percent: number;
  event: "departure" | "arrival" | "charge_start" | "charge_end";
}

export interface OptimizationResult {
  scenario_id: string;
  solver_status: string;
  objective_value: number;
  solve_time_seconds: number;
  duties: VehicleDuty[];
  charging_schedule: ChargingSlot[];
  cost_breakdown: CostBreakdown;
  feasible?: boolean;
  solver_mode?: string;
  warnings?: string[];
  infeasibility_reasons?: string[];
  vehicle_paths?: Record<string, string[]>;
  operator_stats?: Record<string, { selected: number; accepted: number; rejected: number; reward: number }>;
  incumbent_history?: Array<{ iteration: number; objective_value: number; feasible: boolean }>;
  reoptimized?: boolean;
  reoptimization_request?: Record<string, unknown>;
}

export interface ChargingSlot {
  duty_id: string;
  charger_id: string;
  start_time: HHMMTime;
  end_time: HHMMTime;
  energy_kwh: number;
  power_kw: number;
}

export interface CostBreakdown {
  energy_cost: number;
  peak_demand_cost: number;
  vehicle_cost: number;
  deadhead_cost: number;
  total_cost: number;
}

// ── Job tracking ──────────────────────────────────────────────

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface Job {
  job_id: string;
  status: JobStatus;
  progress: number; // 0-100
  message: string;
  result_key?: string;
  error?: string;
  metadata?: Record<string, unknown>;
  persistence?: {
    store: string;
    survives_restart: boolean;
    warning: string;
  };
}

export interface RunCapabilities {
  implemented: boolean;
  async_job: boolean;
  job_persistence: {
    store: string;
    survives_restart: boolean;
    warning: string;
  };
  primary_inputs?: string[];
  supported_sources?: string[];
  supported_modes?: string[];
  supports_reoptimization?: boolean;
  notes: string[];
}

// ── Derived / Computed (for UI convenience) ───────────────────

/** Summary of a depot with computed aggregates */
export interface DepotSummary extends Depot {
  vehicleCount: number;
  bevCount: number;
  iceCount: number;
  allowedRouteCount: number;
}

/** Summary of a route with its permission info */
export interface RouteSummary extends Route {
  allowedDepotIds: string[];
  allowedVehicleIds: string[];
  tripCount: number;
}
