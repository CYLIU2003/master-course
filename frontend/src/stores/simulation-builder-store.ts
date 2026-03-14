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
    includeDeadhead: defaults.includeDeadhead,
    serviceDate: defaults.serviceDate ?? null,
    startTime: "05:00",
    planningHorizonHours: 20,
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
  preparedResult: SimulationPrepareResult | null;
  activeJobId: string | null;
  hydrateFromBootstrap: (bootstrap: EditorBootstrap, force?: boolean) => void;
  setSelectedDepotIds: (ids: string[]) => void;
  setSelectedRouteIds: (ids: string[]) => void;
  setDayType: (value: string) => void;
  setServiceDate: (value: string) => void;
  updateSettings: (patch: Partial<SimulationBuilderSettings>) => void;
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
  preparedResult: null,
  activeJobId: null,
};

export const useSimulationBuilderStore = create<SimulationBuilderState>(
  (set, get) => ({
    ...initialState,
    hydrateFromBootstrap: (bootstrap, force = false) => {
      const current = get();
      const scenarioId = bootstrap.scenario.id;
      if (!force && current.scenarioId === scenarioId) {
        set({ bootstrap });
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
    setPreparedResult: (result) => set({ preparedResult: result }),
    setActiveJobId: (jobId) => set({ activeJobId: jobId }),
    reset: () => set({ ...initialState }),
  }),
);
