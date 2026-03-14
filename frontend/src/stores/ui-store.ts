import { create } from "zustand";

export type ActiveTab = "planning" | "simulation";

interface UIState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;

  /** Currently selected scenario ID (from URL param, mirrored here for global access) */
  activeScenarioId: string | null;
  setActiveScenarioId: (id: string | null) => void;

  /** Scenario activation request currently in flight */
  activatingScenarioId: string | null;
  setActivatingScenarioId: (id: string | null) => void;

  /** Active main tab */
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;

  /** Selected depot in Tab 1 — scopes vehicles/routes below */
  selectedDepotId: string | null;
  setSelectedDepotId: (id: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),

  activeScenarioId: null,
  setActiveScenarioId: (id) => set({ activeScenarioId: id }),

  activatingScenarioId: null,
  setActivatingScenarioId: (id) => set({ activatingScenarioId: id }),

  activeTab: "planning",
  setActiveTab: (tab) => set({ activeTab: tab }),

  selectedDepotId: null,
  setSelectedDepotId: (id) => set({ selectedDepotId: id }),
}));
