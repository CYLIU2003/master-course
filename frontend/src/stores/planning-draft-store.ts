import { create } from "zustand";

type ScenarioDraftFlags = {
  scope: boolean;
  depotPermissions: boolean;
  vehiclePermissions: boolean;
  depotEditor: boolean;
  vehicleEditor: boolean;
};

interface PlanningDraftStoreState {
  byScenario: Record<string, ScenarioDraftFlags>;
  setScopeDirty: (scenarioId: string, dirty: boolean) => void;
  setDepotPermissionsDirty: (scenarioId: string, dirty: boolean) => void;
  setVehiclePermissionsDirty: (scenarioId: string, dirty: boolean) => void;
  setDepotEditorDirty: (scenarioId: string, dirty: boolean) => void;
  setVehicleEditorDirty: (scenarioId: string, dirty: boolean) => void;
  clearScenarioDraftFlags: (scenarioId: string) => void;
}

const EMPTY_FLAGS: ScenarioDraftFlags = {
  scope: false,
  depotPermissions: false,
  vehiclePermissions: false,
  depotEditor: false,
  vehicleEditor: false,
};

function withScenarioUpdate(
  state: PlanningDraftStoreState,
  scenarioId: string,
  updater: (prev: ScenarioDraftFlags) => ScenarioDraftFlags,
): Record<string, ScenarioDraftFlags> {
  const prev = state.byScenario[scenarioId] ?? EMPTY_FLAGS;
  const next = updater(prev);
  return {
    ...state.byScenario,
    [scenarioId]: next,
  };
}

export const usePlanningDraftStore = create<PlanningDraftStoreState>((set) => ({
  byScenario: {},
  setScopeDirty: (scenarioId, dirty) =>
    set((state) => ({
      byScenario: withScenarioUpdate(state, scenarioId, (prev) => ({
        ...prev,
        scope: dirty,
      })),
    })),
  setDepotPermissionsDirty: (scenarioId, dirty) =>
    set((state) => ({
      byScenario: withScenarioUpdate(state, scenarioId, (prev) => ({
        ...prev,
        depotPermissions: dirty,
      })),
    })),
  setVehiclePermissionsDirty: (scenarioId, dirty) =>
    set((state) => ({
      byScenario: withScenarioUpdate(state, scenarioId, (prev) => ({
        ...prev,
        vehiclePermissions: dirty,
      })),
    })),
  setDepotEditorDirty: (scenarioId, dirty) =>
    set((state) => ({
      byScenario: withScenarioUpdate(state, scenarioId, (prev) => ({
        ...prev,
        depotEditor: dirty,
      })),
    })),
  setVehicleEditorDirty: (scenarioId, dirty) =>
    set((state) => ({
      byScenario: withScenarioUpdate(state, scenarioId, (prev) => ({
        ...prev,
        vehicleEditor: dirty,
      })),
    })),
  clearScenarioDraftFlags: (scenarioId) =>
    set((state) => {
      const next = { ...state.byScenario };
      delete next[scenarioId];
      return { byScenario: next };
    }),
}));

export function useHasPlanningDraftChanges(scenarioId?: string): boolean {
  return usePlanningDraftStore((state) => {
    if (!scenarioId) {
      return false;
    }
    const flags = state.byScenario[scenarioId];
    return Boolean(
      flags?.scope
      || flags?.depotPermissions
      || flags?.vehiclePermissions
      || flags?.depotEditor
      || flags?.vehicleEditor,
    );
  });
}
