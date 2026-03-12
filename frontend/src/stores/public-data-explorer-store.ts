import { create } from "zustand";
import {
  publicDataApi,
  type OperatorId,
  type PublicDataSummary,
  type MapOverviewResponse,
} from "@/api/public-data";

export type ExplorerDetailTab = "routes" | "stops" | "timetable";

// ── State ────────────────────────────────────────────────────

interface PublicDataExplorerState {
  /** Currently selected operator ("all" = summary comparison mode) */
  selectedOperator: OperatorId | "all";

  /** Per-operator summaries (lightweight counts) */
  summaries: {
    itemsByOperator: Partial<Record<OperatorId, PublicDataSummary>>;
    loading: boolean;
    error: string | null;
  };

  /** Per-operator map overview (bounds, clusters, depots) */
  mapOverviewByOperator: Partial<Record<OperatorId, MapOverviewResponse>>;
  mapOverviewLoading: Partial<Record<OperatorId, boolean>>;
  preferredDetailTab: ExplorerDetailTab | null;

  // ── Actions ──────────────────────────────────────────────

  setSelectedOperator: (operator: OperatorId | "all") => void;
  focusOperatorDetail: (operator: OperatorId, detailTab: ExplorerDetailTab) => void;
  consumePreferredDetailTab: () => ExplorerDetailTab | null;

  /** Load all operator summaries (lightweight, called on mount) */
  loadSummaries: () => Promise<void>;

  /** Load map-overview for a specific operator (operatorId required) */
  loadMapOverview: (operatorId: OperatorId) => Promise<void>;

  /** Clear map overview for an operator (on deselect) */
  clearMapOverview: (operatorId: OperatorId) => void;
}

// ── Store ────────────────────────────────────────────────────

export const usePublicDataExplorerStore = create<PublicDataExplorerState>(
  (set) => ({
    selectedOperator: "all",

    summaries: {
      itemsByOperator: {},
      loading: false,
      error: null,
    },

    mapOverviewByOperator: {},
    mapOverviewLoading: {},
    preferredDetailTab: null,

    setSelectedOperator: (operator) => set({ selectedOperator: operator }),
    focusOperatorDetail: (operator, detailTab) =>
      set({ selectedOperator: operator, preferredDetailTab: detailTab }),
    consumePreferredDetailTab: () => {
      let nextTab: ExplorerDetailTab | null = null;
      set((state) => {
        nextTab = state.preferredDetailTab;
        return { preferredDetailTab: null };
      });
      return nextTab;
    },

    loadSummaries: async () => {
      set((s) => ({
        summaries: { ...s.summaries, loading: true, error: null },
      }));
      try {
        const res = await publicDataApi.getAllSummaries();
        const byOperator: Partial<Record<OperatorId, PublicDataSummary>> = {};
        for (const item of res.items) {
          byOperator[item.operatorId] = item;
        }
        set({
          summaries: {
            itemsByOperator: byOperator,
            loading: false,
            error: null,
          },
        });
      } catch (e) {
        set((s) => ({
          summaries: {
            ...s.summaries,
            loading: false,
            error: e instanceof Error ? e.message : String(e),
          },
        }));
      }
    },

    loadMapOverview: async (operatorId) => {
      set((s) => ({
        mapOverviewLoading: { ...s.mapOverviewLoading, [operatorId]: true },
      }));
      try {
        const data = await publicDataApi.getMapOverview(operatorId);
        set((s) => ({
          mapOverviewByOperator: {
            ...s.mapOverviewByOperator,
            [operatorId]: data,
          },
          mapOverviewLoading: { ...s.mapOverviewLoading, [operatorId]: false },
        }));
      } catch {
        set((s) => ({
          mapOverviewLoading: { ...s.mapOverviewLoading, [operatorId]: false },
        }));
      }
    },

    clearMapOverview: (operatorId) =>
      set((s) => {
        const updated = { ...s.mapOverviewByOperator };
        delete updated[operatorId];
        return { mapOverviewByOperator: updated };
      }),
  }),
);

// ── Selectors (pure functions, not hooks) ────────────────────

export function selectAllSummaries(
  state: PublicDataExplorerState,
): PublicDataSummary[] {
  return Object.values(state.summaries.itemsByOperator).filter(
    Boolean,
  ) as PublicDataSummary[];
}

export function selectSelectedSummary(
  state: PublicDataExplorerState,
): PublicDataSummary | null {
  if (state.selectedOperator === "all") return null;
  return state.summaries.itemsByOperator[state.selectedOperator] ?? null;
}

export function selectSelectedMapOverview(
  state: PublicDataExplorerState,
): MapOverviewResponse | null {
  if (state.selectedOperator === "all") return null;
  return state.mapOverviewByOperator[state.selectedOperator] ?? null;
}

export function selectComparisonRows(state: PublicDataExplorerState) {
  return selectAllSummaries(state).map((item) => ({
    operatorId: item.operatorId,
    operatorLabel: item.operatorLabel,
    routes: item.counts.routes,
    stops: item.counts.stops,
    timetableRows: item.counts.timetableRows,
    stopTimetables: item.counts.stopTimetables,
  }));
}
