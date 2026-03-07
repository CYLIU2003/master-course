// ── Enhanced Master Data types for the new MasterData page ────
// These types represent the target-state data model.
// The existing domain.ts types remain for API compatibility.
// Mappers convert between API responses and these rich types.

// ── Common ────────────────────────────────────────────────────

export type Id = string;

export type RecordStatus = "draft" | "active" | "archived";

export type ViewMode = "table" | "map" | "node" | "split";

export type MasterTabKey = "depots" | "vehicles" | "routes" | "stops";

// ── Geo ───────────────────────────────────────────────────────

export type LngLat = {
  lng: number;
  lat: number;
};

export type PointGeometry = {
  type: "Point";
  coordinates: [number, number]; // [lng, lat]
};

export type LineStringGeometry = {
  type: "LineString";
  coordinates: [number, number][];
};

export type FeatureProperties = Record<string, unknown>;

export type GeoFeature<
  TGeometry,
  TProps = FeatureProperties,
> = {
  type: "Feature";
  geometry: TGeometry;
  properties: TProps;
};

export type FeatureCollection<TFeature> = {
  type: "FeatureCollection";
  features: TFeature[];
};

// ── Depot (enhanced) ──────────────────────────────────────────

export type DepotPowerSpec = {
  contractPowerKw: number | null;
  chargerCount: number;
  chargerMaxPowerKw: number | null;
  hasSolar: boolean;
  solarCapacityKw: number | null;
  hasBatteryStorage: boolean;
  batteryStorageCapacityKWh: number | null;
};

export type MasterDepot = {
  id: Id;
  name: string;
  address: string;
  location: LngLat | null;
  maxVehicleCapacity: number | null;
  normalChargerCount: number;
  normalChargerPowerKw: number;
  fastChargerCount: number;
  fastChargerPowerKw: number;
  hasFuelFacility: boolean;
  parkingCapacity: number;
  overnightCharging: boolean;
  notes: string;
  status: RecordStatus;
};

export type DepotMapFeature = GeoFeature<
  PointGeometry,
  { depotId: Id; name: string }
>;

// ── Vehicle (discriminated union) ─────────────────────────────

export type VehicleType = "ev_bus" | "engine_bus";

export type VehicleBase = {
  id: Id;
  depotId: Id;
  type: VehicleType;
  modelName: string;
  capacityPassengers: number;
  vehicleMassKg: number | null;
  acquisitionCost: number;
  notes: string;
  enabled: boolean;
};

export type EvVehicleSpec = {
  batteryCapacityKWh: number | null;
  initialSocPercent: number | null;
  minSocPercent: number | null;
  maxSocPercent: number | null;
  chargingEfficiency: number | null;
  maxChargingPowerKw: number | null;
  energyConsumptionKWhPerKm: number | null;
  regenerativeEfficiency: number | null;
  hvacCorrectionFactor: number | null;
};

export type EngineVehicleSpec = {
  fuelType: "diesel" | "gasoline" | "cng" | "lng" | "other";
  fuelTankCapacityL: number | null;
  initialFuelL: number | null;
  minReserveFuelL: number | null;
  fuelEconomyKmPerL: number | null;
  co2KgPerL: number | null;
};

export type EvVehicle = VehicleBase & {
  type: "ev_bus";
  evSpec: EvVehicleSpec;
  engineSpec: null;
};

export type EngineVehicle = VehicleBase & {
  type: "engine_bus";
  evSpec: null;
  engineSpec: EngineVehicleSpec;
};

export type MasterVehicle = EvVehicle | EngineVehicle;

// ── Stop ──────────────────────────────────────────────────────

export type StopKind = "real_stop" | "abstract_node";

export type MasterStop = {
  id: Id;
  code: string;
  name: string;
  location: LngLat | null; // null for abstract nodes
  kind: StopKind;
  depotId: Id | null;
  notes: string;
  status: RecordStatus;
};

// ── Route ─────────────────────────────────────────────────────

export type RouteDirectionKind = "outbound" | "inbound" | "loop";

export type StopSequenceItem = {
  stopId: Id;
  order: number;
  dwellTimeMin: number | null;
  isTimingPoint: boolean;
};

export type RouteEdge = {
  id: Id;
  routeId: Id;
  directionId: Id;
  fromStopId: Id;
  toStopId: Id;
  distanceKm: number | null;
  travelTimeMin: number | null;
  isDirected: boolean;
};

export type NodeLayout = { x: number; y: number };

export type RouteDirectionUiLayout = {
  nodes: Record<Id, NodeLayout>;
  viewport?: { panX: number; panY: number; zoom: number };
};

export type RouteDirection = {
  id: Id;
  routeId: Id;
  direction: RouteDirectionKind;
  isOneWayOnly: boolean;
  isCircular: boolean;
  startStopId: Id | null;
  endStopId: Id | null;
  stopSequence: StopSequenceItem[];
  edges: RouteEdge[];
  distanceKm: number | null;
  scheduledTravelTimeMin: number | null;
  uiLayout?: RouteDirectionUiLayout;
};

export type MasterRoute = {
  id: Id;
  name: string;
  depotId: Id;
  color: string | null;
  notes: string;
  enabled: boolean;
  directions: RouteDirection[];
};

export type RouteGeometry = {
  id: Id;
  routeId: Id;
  directionId: Id;
  geometry: LineStringGeometry;
};

export type RouteMapFeature = GeoFeature<
  LineStringGeometry,
  {
    routeId: Id;
    directionId: Id;
    name: string;
    color?: string | null;
  }
>;

// ── UI State ──────────────────────────────────────────────────

export type MasterDataUiState = {
  activeTab: MasterTabKey;
  viewMode: ViewMode;
  selectedDepotId: Id | null;
  selectedVehicleId: Id | null;
  selectedRouteId: Id | null;
  selectedStopId: Id | null;
  isEditorDrawerOpen: boolean;
  isCreateMode: boolean;
  isDirty: boolean;
};
