// ── Master Data UI Store (Zustand) ────────────────────────────
// Manages all ephemeral UI state for the MasterData page:
// active tab, view mode, selection, drawer open/close, dirty flag.

import { create } from "zustand";
import type { Id, MasterTabKey, ViewMode } from "@/types/master";

// ── Operator options (per-operator SQLite DBs) ───────────────
export type OperatorKey = "tokyu" | "toei";

export const OPERATOR_OPTIONS: {
  key: OperatorKey;
  label_ja: string;
  label_en: string;
}[] = [
  { key: "tokyu", label_ja: "東急バス", label_en: "Tokyu Bus" },
  { key: "toei", label_ja: "都営バス", label_en: "Toei Bus" },
];

interface MasterDataUiState {
  // Operator selection
  selectedOperator: OperatorKey;

  // Tab & mode
  activeTab: MasterTabKey;
  viewMode: ViewMode;

  // Selection
  selectedDepotId: Id | null;
  selectedVehicleId: Id | null;
  selectedRouteId: Id | null;
  selectedStopId: Id | null;

  // Editor drawer
  isEditorDrawerOpen: boolean;
  isCreateMode: boolean;
  /** Vehicle sub-type when creating (for VehicleCreateMenu) */
  createVehicleType: "ev_bus" | "engine_bus" | null;
  createVehicleTemplateId: Id | null;

  // Dirty tracking
  isDirty: boolean;
}

interface MasterDataUiActions {
  setSelectedOperator: (op: OperatorKey) => void;
  setActiveTab: (tab: MasterTabKey) => void;
  setViewMode: (mode: ViewMode) => void;

  selectDepot: (id: Id | null) => void;
  selectVehicle: (id: Id | null) => void;
  selectRoute: (id: Id | null) => void;
  selectStop: (id: Id | null) => void;

  openDrawer: (opts?: {
    isCreate?: boolean;
    vehicleType?: "ev_bus" | "engine_bus";
    vehicleTemplateId?: Id | null;
  }) => void;
  closeDrawer: () => void;

  setDirty: (dirty: boolean) => void;
  reset: () => void;
}

const initialState: MasterDataUiState = {
  selectedOperator: "tokyu",
  activeTab: "depots",
  viewMode: "table",
  selectedDepotId: null,
  selectedVehicleId: null,
  selectedRouteId: null,
  selectedStopId: null,
  isEditorDrawerOpen: false,
  isCreateMode: false,
  createVehicleType: null,
  createVehicleTemplateId: null,
  isDirty: false,
};

export const useMasterUiStore = create<MasterDataUiState & MasterDataUiActions>(
  (set) => ({
    ...initialState,

    setSelectedOperator: (op) =>
      set({
        selectedOperator: op,
        // Reset sub-selections when changing operator
        selectedDepotId: null,
        selectedVehicleId: null,
        selectedRouteId: null,
        selectedStopId: null,
        isEditorDrawerOpen: false,
        isCreateMode: false,
        isDirty: false,
      }),

    setActiveTab: (tab) =>
      set({
        activeTab: tab,
        isEditorDrawerOpen: false,
        isCreateMode: false,
        selectedVehicleId: null,
        selectedRouteId: null,
        selectedStopId: null,
        isDirty: false,
        createVehicleTemplateId: null,
      }),

    setViewMode: (mode) => set({ viewMode: mode }),

    selectDepot: (id) =>
      set({
        selectedDepotId: id,
        // When changing depot filter, close drawer and clear sub-selections
        selectedVehicleId: null,
        selectedRouteId: null,
        selectedStopId: null,
        isEditorDrawerOpen: false,
        isCreateMode: false,
        isDirty: false,
        createVehicleTemplateId: null,
      }),

    selectVehicle: (id) =>
      set({
        selectedVehicleId: id,
        selectedRouteId: null,
        selectedStopId: null,
        isEditorDrawerOpen: id !== null,
        isCreateMode: false,
        isDirty: false,
        createVehicleTemplateId: null,
      }),

    selectRoute: (id) =>
      set({
        selectedRouteId: id,
        selectedVehicleId: null,
        selectedStopId: null,
        isEditorDrawerOpen: id !== null,
        isCreateMode: false,
        isDirty: false,
        createVehicleTemplateId: null,
      }),

    selectStop: (id) =>
      set({
        selectedStopId: id,
        selectedVehicleId: null,
        selectedRouteId: null,
        isEditorDrawerOpen: id !== null,
        isCreateMode: false,
        isDirty: false,
        createVehicleTemplateId: null,
      }),

    openDrawer: (opts) =>
      set({
        isEditorDrawerOpen: true,
        isCreateMode: opts?.isCreate ?? false,
        createVehicleType: opts?.vehicleType ?? null,
        createVehicleTemplateId: opts?.vehicleTemplateId ?? null,
      }),

    closeDrawer: () =>
      set({
        isEditorDrawerOpen: false,
        isCreateMode: false,
        createVehicleType: null,
        createVehicleTemplateId: null,
        isDirty: false,
      }),

    setDirty: (dirty) => set({ isDirty: dirty }),

    reset: () => set(initialState),
  }),
);
