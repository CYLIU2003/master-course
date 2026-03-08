import { create } from "zustand";

export type WarmStatus = "idle" | "warming" | "ready" | "error";
export type WarmTabKey = "planning" | "timetable" | "dispatch" | "explorer";

interface WarmTabState {
  status: WarmStatus;
  detail?: string;
  updatedAt?: string;
}

interface TabWarmState {
  tabs: Record<WarmTabKey, WarmTabState>;
  setTabStatus: (tab: WarmTabKey, status: WarmStatus, detail?: string) => void;
  reset: () => void;
}

const initialTabs: Record<WarmTabKey, WarmTabState> = {
  planning: { status: "idle" },
  timetable: { status: "idle" },
  dispatch: { status: "idle" },
  explorer: { status: "idle" },
};

export const useTabWarmStore = create<TabWarmState>((set) => ({
  tabs: initialTabs,
  setTabStatus: (tab, status, detail) =>
    set((state) => ({
      tabs: {
        ...state.tabs,
        [tab]: {
          status,
          detail,
          updatedAt: new Date().toISOString(),
        },
      },
    })),
  reset: () => set({ tabs: initialTabs }),
}));
