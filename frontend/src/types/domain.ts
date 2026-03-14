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
  operatorId: "tokyu" | "toei";
  createdAt: string;
  updatedAt: string;
  status: ScenarioStatus;
  datasetId?: string;
  datasetVersion?: string;
  randomSeed?: number;
  scenarioOverlay?: ScenarioOverlay | null;
  datasetStatus?: ResearchDatasetStatus | null;
  feedContext?: FeedContext | null;
}

export interface FleetConfig {
  n_bev: number;
  n_ice: number;
}

export interface ChargingConfig {
  max_simultaneous_sessions?: number | null;
  overnight_window_start?: string | null;
  overnight_window_end?: string | null;
  depot_power_limit_kw?: number | null;
  charger_power_limit_kw?: number | null;
}

export interface TimeOfUseBand {
  start_hour: number;
  end_hour: number;
  price_per_kwh: number;
}

export interface CostConfig {
  tou_pricing: TimeOfUseBand[];
  demand_charge_cost_per_kw: number;
  pv_enabled: boolean;
  pv_scale: number;
  diesel_price_per_l: number;
}

export interface SolverConfig {
  mode:
    | "milp"
    | "alns"
    | "hybrid"
    | "mode_milp_only"
    | "mode_alns_only"
    | "mode_alns_milp";
  time_limit_seconds: number;
  mip_gap: number;
  alns_iterations: number;
}

export interface ScenarioOverlay {
  scenario_id: string;
  dataset_id: string;
  dataset_version: string;
  random_seed: number;
  depot_ids: string[];
  route_ids: string[];
  fleet: FleetConfig;
  charging_constraints: ChargingConfig;
  cost_coefficients: CostConfig;
  solver_config: SolverConfig;
}

export interface ResearchDatasetStatus {
  datasetId: string;
  description: string;
  note?: string | null;
  includedDepots: string[];
  includedRoutes: string[] | "ALL";
  seedVersion?: string | null;
  datasetVersion: string;
  seedReady?: boolean;
  builtReady?: boolean;
  builtAvailable: boolean;
  warning?: string | null;
  missingArtifacts?: string[];
  integrityError?: string | null;
  producerVersion?: string | null;
  schemaVersion?: string | null;
  runtimeVersion?: string | null;
  contractErrorCode?: string | null;
  manifest?: Record<string, unknown> | null;
  paths?: Record<string, string>;
}

export interface FeedContext {
  feedId?: string | null;
  snapshotId?: string | null;
  datasetId?: string | null;
  datasetFingerprint?: string | null;
  manualRouteFamilyMapHash?: string | null;
  source?: string | null;
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

/** A stop that has been resolved against the stop catalog */
export type RouteResolvedStop = {
  id: string;
  name: string;
  kana?: string | null;
  lat?: number | null;
  lon?: number | null;
  platformCode?: string | null;
  sequence: number;
  timetableSummary?: {
    tripCount?: number;
    firstDeparture?: string | null;
    lastDeparture?: string | null;
  };
};

/** Describes how many cross-references have been resolved */
export type RouteLinkStatus = {
  stopsResolved: number;
  stopsMissing: number;
  missingStopIds?: string[];
  tripsLinked: number;
  stopTimetableEntriesLinked: number;
  warnings: string[];
};

/** Trip count / first-last departure aggregated by service */
export type RouteServiceSummary = {
  serviceId: string;
  tripCount: number;
  firstDeparture?: string | null;
  lastDeparture?: string | null;
};

export type RouteLinkState = "unlinked" | "partial" | "linked" | "error";

export type RouteVariantType =
  | "main"
  | "main_outbound"
  | "main_inbound"
  | "short_turn"
  | "branch"
  | "depot_out"
  | "depot_in"
  | "unknown";

export type RouteCanonicalDirection =
  | "outbound"
  | "inbound"
  | "circular"
  | "unknown";

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
  /** Link state: how completely this route is linked to stops/trips */
  linkState?: RouteLinkState;
  /** Resolved stop objects (populated by route detail API) */
  resolvedStops?: RouteResolvedStop[];
  /** Link status summary (populated by route detail API) */
  linkStatus?: RouteLinkStatus;
  /** Service-level trip summary (populated by route detail API) */
  serviceSummary?: RouteServiceSummary[];
  /** Import provenance metadata */
  importMeta?: {
    source?: string;
    snapshotKey?: string;
    generatedAt?: string;
    warnings?: string[];
  };

  // ── Route family / variant (derived by BFF) ───────────────
  /** Derived stable family identifier */
  routeFamilyId?: string;
  /** Normalized public-facing line code (e.g. "園01") */
  routeFamilyCode?: string;
  /** Display label for grouped family row */
  routeFamilyLabel?: string;
  /** Derived variant identifier within the family */
  routeVariantId?: string;
  /** Variant classification */
  routeVariantType?: RouteVariantType;
  /** Canonical direction grouping */
  canonicalDirection?: RouteCanonicalDirection;
  /** Whether this is the primary variant in the family */
  isPrimaryVariant?: boolean;
  /** Sort order within the family display */
  familySortOrder?: number;
  /** Classification confidence [0-1] */
  classificationConfidence?: number;
  /** Explanation of classification decision */
  classificationReasons?: string[];
  /** Classification source shown by BFF */
  classificationSource?: "derived" | "manual_override";
  /** Persisted manual override for route variant classification */
  routeVariantTypeManual?: RouteVariantType | null;
  /** Optional persisted manual override for direction */
  canonicalDirectionManual?: RouteCanonicalDirection | null;
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

// ── Route Family Summary (derived by BFF) ─────────────────────

export interface RouteFamilySummary {
  routeFamilyId: string;
  routeFamilyCode: string;
  routeFamilyLabel: string;
  primaryColor?: string;
  variantCount: number;
  mainVariantCount: number;
  hasShortTurn: boolean;
  hasBranch: boolean;
  hasDepotVariant: boolean;
  startStopCandidates: string[];
  endStopCandidates: string[];
  aggregatedLinkState: RouteLinkState;
  aggregatedLinkStatus: {
    stopsResolved: number;
    stopsMissing: number;
    tripsLinked: number;
    stopTimetableEntriesLinked: number;
    warnings: string[];
  };
  serviceSummary?: RouteServiceSummary[];
}

export interface RouteFamilyDetail {
  routeFamilyId: string;
  routeFamilyCode: string;
  routeFamilyLabel: string;
  summary: RouteFamilySummary;
  variants: Route[];
  canonicalMainPair?: {
    outboundRouteId?: string | null;
    inboundRouteId?: string | null;
    outboundStartStop?: string | null;
    outboundEndStop?: string | null;
    inboundStartStop?: string | null;
    inboundEndStop?: string | null;
  };
  timetableDiagnostics?: {
    rawRouteCount: number;
    rawRoutesWithTrips: number;
    rawRoutesWithStopTimetables: number;
    totalTripsLinked: number;
    totalStopTimetableEntriesLinked: number;
    warnings: string[];
  };
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

export interface DepotRouteFamilyPermission {
  depotId: string;
  routeFamilyId: string;
  routeFamilyCode: string;
  routeFamilyLabel: string;
  primaryColor?: string;
  memberRouteIds: string[];
  totalRouteCount: number;
  allowedRouteCount: number;
  allowed: boolean;
  partiallyAllowed: boolean;
}

/** Which vehicles can operate on which routes */
export interface VehicleRoutePermission {
  vehicleId: string;
  routeId: string;
  allowed: boolean;
}

export interface VehicleRouteFamilyPermission {
  vehicleId: string;
  routeFamilyId: string;
  routeFamilyCode: string;
  routeFamilyLabel: string;
  primaryColor?: string;
  memberRouteIds: string[];
  totalRouteCount: number;
  allowedRouteCount: number;
  allowed: boolean;
  partiallyAllowed: boolean;
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

export interface VehicleBlock {
  block_id: string;
  vehicle_type: string;
  trip_ids: string[];
}

export interface DispatchPlanArtifact {
  plan_id: string;
  vehicle_type: string;
  blocks: VehicleBlock[];
  duties: VehicleDuty[];
  charging_plan: unknown[];
}

export interface DispatchPlanResponse {
  plans: DispatchPlanArtifact[];
  total_plans: number;
  total_blocks: number;
  total_duties: number;
}

export interface DutyValidationResult {
  duty_id: string;
  valid: boolean;
  errors: string[];
}

export interface DispatchScope {
  scopeId?: string | null;
  operatorId?: string | null;
  datasetVersion?: string | null;
  depotSelection?: {
    mode: "include";
    depotIds: string[];
    primaryDepotId: string | null;
  };
  routeSelection?: {
    mode: "all" | "include" | "exclude" | "refine";
    includeRouteIds: string[];
    excludeRouteIds: string[];
  };
  serviceSelection?: {
    serviceIds: string[];
  };
  tripSelection?: {
    includeShortTurn: boolean;
    includeDepotMoves: boolean;
    includeDeadhead: boolean;
  };
  candidateRouteIds?: string[];
  effectiveRouteIds?: string[];
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
  source?: string;
  audit?: Record<string, unknown>;
  feed_context?: FeedContext | null;
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
  scope?: DispatchScope;
  mode?: string;
  audit?: Record<string, unknown>;
  feed_context?: FeedContext | null;
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
