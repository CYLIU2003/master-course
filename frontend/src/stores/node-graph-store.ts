// ── Node Graph UI Store (Zustand) ─────────────────────────────
// Manages interaction state for the route node-graph editor:
// tool mode, selection, connect workflow, distance input popup.

import { create } from "zustand";
import type { Id } from "@/types/master";

export type NodeGraphTool = "select" | "connect" | "pan";

interface EdgeDraft {
  fromStopId: Id;
  toStopId: Id;
}

interface DistanceEditorState {
  open: boolean;
  edgeId: Id | null;
  x: number;
  y: number;
}

interface NodeGraphState {
  tool: NodeGraphTool;
  selectedStopId: Id | null;
  selectedEdgeId: Id | null;

  // Connect tool workflow
  connectFromStopId: Id | null;
  pendingEdgeDraft: EdgeDraft | null;

  // Distance input popup
  distanceEditor: DistanceEditorState;
}

interface NodeGraphActions {
  setTool: (t: NodeGraphTool) => void;
  selectStop: (id: Id | null) => void;
  selectEdge: (id: Id | null) => void;
  beginConnect: (fromStopId: Id) => void;
  commitConnect: (toStopId: Id) => void;
  cancelConnect: () => void;
  openDistanceEditor: (edgeId: Id, x: number, y: number) => void;
  closeDistanceEditor: () => void;
  reset: () => void;
}

const initialState: NodeGraphState = {
  tool: "select",
  selectedStopId: null,
  selectedEdgeId: null,
  connectFromStopId: null,
  pendingEdgeDraft: null,
  distanceEditor: { open: false, edgeId: null, x: 0, y: 0 },
};

export const useNodeGraphStore = create<NodeGraphState & NodeGraphActions>(
  (set) => ({
    ...initialState,

    setTool: (t) =>
      set({ tool: t, connectFromStopId: null, pendingEdgeDraft: null }),

    selectStop: (id) => set({ selectedStopId: id, selectedEdgeId: null }),
    selectEdge: (id) => set({ selectedEdgeId: id, selectedStopId: null }),

    beginConnect: (fromStopId) =>
      set({ connectFromStopId: fromStopId, pendingEdgeDraft: null }),

    commitConnect: (toStopId) =>
      set((s) => {
        if (!s.connectFromStopId) return s;
        return {
          pendingEdgeDraft: {
            fromStopId: s.connectFromStopId,
            toStopId,
          },
          connectFromStopId: null,
        };
      }),

    cancelConnect: () =>
      set({ connectFromStopId: null, pendingEdgeDraft: null }),

    openDistanceEditor: (edgeId, x, y) =>
      set({ distanceEditor: { open: true, edgeId, x, y } }),

    closeDistanceEditor: () =>
      set({ distanceEditor: { open: false, edgeId: null, x: 0, y: 0 } }),

    reset: () => set(initialState),
  }),
);
