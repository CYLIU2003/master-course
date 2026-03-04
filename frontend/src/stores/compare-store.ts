import { create } from "zustand";

interface CompareState {
  /** Scenario IDs selected for comparison */
  selectedIds: string[];
  toggleScenario: (id: string) => void;
  clearSelection: () => void;
}

export const useCompareStore = create<CompareState>((set) => ({
  selectedIds: [],
  toggleScenario: (id) =>
    set((s) => ({
      selectedIds: s.selectedIds.includes(id)
        ? s.selectedIds.filter((x) => x !== id)
        : [...s.selectedIds, id],
    })),
  clearSelection: () => set({ selectedIds: [] }),
}));
