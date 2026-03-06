// ── Route Graph Store (Zustand) ────────────────────────────────
// Shared state for the route node-graph editor.
// Nodes = stops on a route direction; edges = segments between stops.
// State is persisted to localStorage keyed by routeId.

import { create } from "zustand";
import { nanoid } from "@/lib/ids";
import type { Id } from "@/types/master";

// ── Data model ──────────────────────────────────────────────────

export interface GraphNode {
  id: Id;
  name: string;
  x: number;
  y: number;
  lat: number | null;
  lng: number | null;
}

export interface GraphEdge {
  id: Id;
  fromId: Id;
  toId: Id;
  distanceKm: number | null;
  travelTimeMin: number | null;
}

// ── Store shape ─────────────────────────────────────────────────

interface RouteGraphState {
  /** The routeId whose graph is currently loaded (null = no route open). */
  routeId: Id | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface RouteGraphActions {
  /** Load (or initialise) the graph for a route from localStorage. */
  loadRoute: (routeId: Id) => void;
  /** Unload and clear (does not delete localStorage). */
  unloadRoute: () => void;

  addNode: (name: string, x: number, y: number) => GraphNode;
  updateNode: (id: Id, patch: Partial<Omit<GraphNode, "id">>) => void;
  removeNode: (id: Id) => void;

  addEdge: (fromId: Id, toId: Id) => GraphEdge;
  updateEdge: (id: Id, patch: Partial<Omit<GraphEdge, "id">>) => void;
  removeEdge: (id: Id) => void;

  clearGraph: () => void;
}

// ── localStorage helpers ────────────────────────────────────────

function storageKey(routeId: Id): string {
  return `route-graph:${routeId}`;
}

interface PersistedGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

function loadFromStorage(routeId: Id): PersistedGraph {
  try {
    const raw = localStorage.getItem(storageKey(routeId));
    if (raw) {
      const parsed = JSON.parse(raw) as PersistedGraph;
      return {
        nodes: Array.isArray(parsed.nodes) ? parsed.nodes : [],
        edges: Array.isArray(parsed.edges) ? parsed.edges : [],
      };
    }
  } catch {
    // ignore malformed data
  }
  return { nodes: [], edges: [] };
}

function saveToStorage(routeId: Id, nodes: GraphNode[], edges: GraphEdge[]): void {
  try {
    localStorage.setItem(storageKey(routeId), JSON.stringify({ nodes, edges }));
  } catch {
    // ignore (e.g. private-browsing quota)
  }
}

// ── Store implementation ────────────────────────────────────────

const initialState: RouteGraphState = {
  routeId: null,
  nodes: [],
  edges: [],
};

export const useRouteGraphStore = create<RouteGraphState & RouteGraphActions>(
  (set, get) => ({
    ...initialState,

    loadRoute: (routeId) => {
      const { nodes, edges } = loadFromStorage(routeId);
      set({ routeId, nodes, edges });
    },

    unloadRoute: () => set(initialState),

    // ── Nodes ──────────────────────────────────────────────────

    addNode: (name, x, y) => {
      const node: GraphNode = {
        id: nanoid("node_"),
        name,
        x,
        y,
        lat: null,
        lng: null,
      };
      set((s) => {
        const nodes = [...s.nodes, node];
        if (s.routeId) saveToStorage(s.routeId, nodes, s.edges);
        return { nodes };
      });
      return node;
    },

    updateNode: (id, patch) => {
      set((s) => {
        const nodes = s.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n));
        if (s.routeId) saveToStorage(s.routeId, nodes, s.edges);
        return { nodes };
      });
    },

    removeNode: (id) => {
      set((s) => {
        const nodes = s.nodes.filter((n) => n.id !== id);
        // Cascade-delete edges that reference this node
        const edges = s.edges.filter((e) => e.fromId !== id && e.toId !== id);
        if (s.routeId) saveToStorage(s.routeId, nodes, edges);
        return { nodes, edges };
      });
    },

    // ── Edges ──────────────────────────────────────────────────

    addEdge: (fromId, toId) => {
      // Prevent duplicate edges between the same two nodes
      const existing = get().edges.find(
        (e) => e.fromId === fromId && e.toId === toId,
      );
      if (existing) return existing;

      const edge: GraphEdge = {
        id: nanoid("edge_"),
        fromId,
        toId,
        distanceKm: null,
        travelTimeMin: null,
      };
      set((s) => {
        const edges = [...s.edges, edge];
        if (s.routeId) saveToStorage(s.routeId, s.nodes, edges);
        return { edges };
      });
      return edge;
    },

    updateEdge: (id, patch) => {
      set((s) => {
        const edges = s.edges.map((e) => (e.id === id ? { ...e, ...patch } : e));
        if (s.routeId) saveToStorage(s.routeId, s.nodes, edges);
        return { edges };
      });
    },

    removeEdge: (id) => {
      set((s) => {
        const edges = s.edges.filter((e) => e.id !== id);
        if (s.routeId) saveToStorage(s.routeId, s.nodes, edges);
        return { edges };
      });
    },

    // ── Clear ──────────────────────────────────────────────────

    clearGraph: () => {
      set((s) => {
        if (s.routeId) saveToStorage(s.routeId, [], []);
        return { nodes: [], edges: [] };
      });
    },
  }),
);
