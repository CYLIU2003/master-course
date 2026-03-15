import { create } from "zustand";
import type {
  EditorBootstrap,
  SimulationBuilderSettings,
  SimulationPrepareResult,
} from "@/types";

function defaultsFromBootstrap(
  bootstrap: EditorBootstrap,
): SimulationBuilderSettings {
  const defaults = bootstrap.builderDefaults;
  return {
    vehicleTemplateId: defaults.vehicleTemplateId ?? null,
    vehicleCount: defaults.vehicleCount,
    initialSoc: defaults.initialSoc,
    batteryKwh: defaults.batteryKwh ?? null,
    fleetTemplates: defaults.fleetTemplates ?? [],
    chargerCount: defaults.chargerCount,
    chargerPowerKw: defaults.chargerPowerKw,
    solverMode: defaults.solverMode,
    objectiveMode: defaults.objectiveMode ?? "total_cost",
    allowPartialService: defaults.allowPartialService ?? false,
    unservedPenalty: defaults.unservedPenalty ?? 10000,
    gridFlatPricePerKwh: defaults.gridFlatPricePerKwh ?? null,
    gridSellPricePerKwh: defaults.gridSellPricePerKwh ?? null,
    demandChargeCostPerKw: defaults.demandChargeCostPerKw ?? null,
    dieselPricePerL: defaults.dieselPricePerL ?? null,
    gridCo2KgPerKwh: defaults.gridCo2KgPerKwh ?? null,
    co2PricePerKg: defaults.co2PricePerKg ?? null,
    depotPowerLimitKw: defaults.depotPowerLimitKw ?? null,
    touPricing: defaults.touPricing ?? [],
    timeLimitSeconds: defaults.timeLimitSeconds,
    mipGap: defaults.mipGap,
    alnsIterations: defaults.alnsIterations,
    randomSeed: defaults.randomSeed ?? null,
    experimentMethod: defaults.experimentMethod ?? null,
    experimentNotes: defaults.experimentNotes ?? null,
    includeDeadhead: defaults.includeDeadhead,
    serviceDate: defaults.serviceDate ?? null,
    startTime: defaults.startTime ?? "05:00",
    planningHorizonHours: defaults.planningHorizonHours ?? 20,
  };
}

function scopeFlagsFromBootstrap(bootstrap: EditorBootstrap): {
  includeShortTurn: boolean;
  includeDepotMoves: boolean;
  allowIntraDepotRouteSwap: boolean;
  allowInterDepotSwap: boolean;
} {
  const scope = bootstrap.dispatchScope;
  return {
    includeShortTurn: scope?.tripSelection?.includeShortTurn ?? true,
    includeDepotMoves: scope?.tripSelection?.includeDepotMoves ?? true,
    allowIntraDepotRouteSwap: scope?.allowIntraDepotRouteSwap ?? false,
    allowInterDepotSwap: scope?.allowInterDepotSwap ?? false,
  };
}

interface SimulationBuilderState {
  scenarioId: string | null;
  bootstrap: EditorBootstrap | null;
  selectedDepotIds: string[];
  selectedRouteIds: string[];
  dayType: string;
  serviceDate: string;
  settings: SimulationBuilderSettings;
  // Trip selection overrides (null = use scope default)
  includeShortTurn: boolean;
  includeDepotMoves: boolean;
  // Vehicle swap permissions
  allowIntraDepotRouteSwap: boolean;
  allowInterDepotSwap: boolean;
  preparedResult: SimulationPrepareResult | null;
  activeJobId: string | null;
  hydrateFromBootstrap: (bootstrap: EditorBootstrap, force?: boolean) => void;
  setSelectedDepotIds: (ids: string[]) => void;
  setSelectedRouteIds: (ids: string[]) => void;
  setDayType: (value: string) => void;
  setServiceDate: (value: string) => void;
  updateSettings: (patch: Partial<SimulationBuilderSettings>) => void;
  setIncludeShortTurn: (v: boolean) => void;
  setIncludeDepotMoves: (v: boolean) => void;
  setAllowIntraDepotRouteSwap: (v: boolean) => void;
  setAllowInterDepotSwap: (v: boolean) => void;
  setPreparedResult: (result: SimulationPrepareResult | null) => void;
  setActiveJobId: (jobId: string | null) => void;
  reset: () => void;
}

const emptySettings: SimulationBuilderSettings = {
  vehicleTemplateId: null,
  vehicleCount: 10,
  initialSoc: 0.8,
  batteryKwh: null,
  fleetTemplates: [],
  chargerCount: 4,
  chargerPowerKw: 90,
  solverMode: "mode_milp_only",
  objectiveMode: "total_cost",
  allowPartialService: false,
  unservedPenalty: 10000,
  gridFlatPricePerKwh: null,
  gridSellPricePerKwh: null,
  demandChargeCostPerKw: null,
  dieselPricePerL: null,
  gridCo2KgPerKwh: null,
  co2PricePerKg: null,
  depotPowerLimitKw: null,
  touPricing: [],
  timeLimitSeconds: 300,
  mipGap: 0.01,
  alnsIterations: 500,
  randomSeed: null,
  experimentMethod: null,
  experimentNotes: null,
  includeDeadhead: true,
  serviceDate: null,
  startTime: "05:00",
  planningHorizonHours: 20,
};

const initialState = {
  scenarioId: null,
  bootstrap: null,
  selectedDepotIds: [],
  selectedRouteIds: [],
  dayType: "WEEKDAY",
  serviceDate: "",
  settings: emptySettings,
  // Default: include everything (matches BFF _default_dispatch_scope)
  includeShortTurn: true,
  includeDepotMoves: true,
  allowIntraDepotRouteSwap: false,
  allowInterDepotSwap: false,
  preparedResult: null,
  activeJobId: null,
};

export const useSimulationBuilderStore = create<SimulationBuilderState>(
  (set, get) => ({
    ...initialState,
    hydrateFromBootstrap: (bootstrap, force = false) => {
      const current = get();
      const scenarioId = bootstrap.scenario.id;
      const scopeFlags = scopeFlagsFromBootstrap(bootstrap);
      if (!force && current.scenarioId === scenarioId) {
        set({
          bootstrap,
          includeShortTurn: scopeFlags.includeShortTurn,
          includeDepotMoves: scopeFlags.includeDepotMoves,
          allowIntraDepotRouteSwap: scopeFlags.allowIntraDepotRouteSwap,
          allowInterDepotSwap: scopeFlags.allowInterDepotSwap,
        });
        return;
      }
      set({
        scenarioId,
        bootstrap,
        selectedDepotIds: [...bootstrap.builderDefaults.selectedDepotIds],
        selectedRouteIds: [...bootstrap.builderDefaults.selectedRouteIds],
        dayType: bootstrap.builderDefaults.dayType,
        serviceDate: bootstrap.builderDefaults.serviceDate ?? "",
        settings: defaultsFromBootstrap(bootstrap),
        includeShortTurn: scopeFlags.includeShortTurn,
        includeDepotMoves: scopeFlags.includeDepotMoves,
        allowIntraDepotRouteSwap: scopeFlags.allowIntraDepotRouteSwap,
        allowInterDepotSwap: scopeFlags.allowInterDepotSwap,
        preparedResult: null,
        activeJobId: null,
      });
    },
    setSelectedDepotIds: (ids) =>
      set({
        selectedDepotIds: [...ids],
        preparedResult: null,
      }),
    setSelectedRouteIds: (ids) =>
      set({
        selectedRouteIds: [...ids],
        preparedResult: null,
      }),
    setDayType: (value) =>
      set({
        dayType: value,
        preparedResult: null,
      }),
    setServiceDate: (value) =>
      set({
        serviceDate: value,
        settings: { ...get().settings, serviceDate: value || null },
        preparedResult: null,
      }),
    updateSettings: (patch) =>
      set({
        settings: { ...get().settings, ...patch },
        preparedResult: null,
      }),
    setIncludeShortTurn: (v) => set({ includeShortTurn: v, preparedResult: null }),
    setIncludeDepotMoves: (v) => set({ includeDepotMoves: v, preparedResult: null }),
    setAllowIntraDepotRouteSwap: (v) => set({ allowIntraDepotRouteSwap: v, preparedResult: null }),
    setAllowInterDepotSwap: (v) => set({ allowInterDepotSwap: v, preparedResult: null }),
    setPreparedResult: (result) => set({ preparedResult: result }),
    setActiveJobId: (jobId) => set({ activeJobId: jobId }),
    reset: () => set({ ...initialState }),
  }),
);
