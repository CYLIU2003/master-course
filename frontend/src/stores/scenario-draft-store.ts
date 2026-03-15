import { create } from "zustand";

interface ScenarioDraftState {
  selectedDepotIdByScenario: Record<string, string | null>;
  setSelectedDepotId: (scenarioId: string, depotId: string | null) => void;
  clearScenarioDraft: (scenarioId: string) => void;
}

export const useScenarioDraftStore = create<ScenarioDraftState>((set) => ({
  selectedDepotIdByScenario: {},
  setSelectedDepotId: (scenarioId, depotId) =>
    set((state) => ({
      selectedDepotIdByScenario: {
        ...state.selectedDepotIdByScenario,
        [scenarioId]: depotId,
      },
    })),
  clearScenarioDraft: (scenarioId) =>
    set((state) => {
      const next = { ...state.selectedDepotIdByScenario };
      delete next[scenarioId];
      return { selectedDepotIdByScenario: next };
    }),
}));

export function useSelectedDepotId(scenarioId?: string): string | null {
  return useScenarioDraftStore((state) =>
    scenarioId ? (state.selectedDepotIdByScenario[scenarioId] ?? null) : null,
  );
}
