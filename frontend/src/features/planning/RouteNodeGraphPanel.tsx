// ── RouteNodeGraphPanel ───────────────────────────────────────
// SVG-based node graph editor for route stop/edge modelling.
// Nodes = stops; edges = directed segments with distance/time.
//
// Interactions:
//   select mode  – double-click canvas → add node
//                  click node → select (shows name editor on dbl-click)
//                  click edge → select (opens distance editor)
//                  drag node → reposition
//                  mouse-down canvas → deselect
//   connect mode – click node #1 → beginConnect
//                  click node #2 → addEdge → open distance editor
//   pan mode     – drag anywhere → pan viewport
//   Delete/Back  – delete selected node (cascades) or edge
//   Escape       – cancel connect / close editors / deselect

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useNodeGraphStore, type NodeGraphTool } from "@/stores/node-graph-store";
import {
  useRouteGraphStore,
  type GraphNode,
  type GraphEdge,
} from "@/stores/route-graph-store";

interface Props {
  scenarioId: string;
}

// ── Geometry helpers ────────────────────────────────────────────

function arrowHead(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  size = 10,
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return "";
  const ux = dx / len;
  const uy = dy / len;
  // Pull tip slightly back from target node centre (r = 24)
  const tipX = x2 - ux * 26;
  const tipY = y2 - uy * 26;
  const wx = -uy * size * 0.45;
  const wy = ux * size * 0.45;
  return `${tipX},${tipY} ${tipX - ux * size + wx},${tipY - uy * size + wy} ${tipX - ux * size - wx},${tipY - uy * size - wy}`;
}

function midpoint(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): { x: number; y: number } {
  return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
}

// ── Sub-components ──────────────────────────────────────────────

interface ToolbarProps {
  tool: NodeGraphTool;
  onTool: (t: NodeGraphTool) => void;
  nodeCount: number;
  edgeCount: number;
  onClear: () => void;
}

function Toolbar({ tool, onTool, nodeCount, edgeCount, onClear }: ToolbarProps) {
  const { t } = useTranslation();

  const tools: { key: NodeGraphTool; label: string; title: string }[] = [
    {
      key: "select",
      label: t("node_graph.tool_select", "選択"),
      title: "選択・移動・追加",
    },
    {
      key: "connect",
      label: t("node_graph.tool_connect", "接続"),
      title: "エッジを引く",
    },
    { key: "pan", label: t("node_graph.tool_pan", "パン"), title: "キャンバスを移動" },
  ];

  return (
    <div className="flex items-center gap-2 border-b border-border bg-white px-3 py-2">
      {/* Tool buttons */}
      <div className="flex rounded-lg border border-border">
        {tools.map((tb) => (
          <button
            key={tb.key}
            title={tb.title}
            onClick={() => onTool(tb.key)}
            className={`px-3 py-1 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
              tool === tb.key
                ? "bg-primary-600 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {/* Node / edge count badge */}
      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
        {t("node_graph.stop_count", "停留所")} {nodeCount}
        {" · "}
        {t("node_graph.edge_count", "エッジ")} {edgeCount}
      </span>

      <div className="flex-1" />

      {/* Clear button */}
      {(nodeCount > 0 || edgeCount > 0) && (
        <button
          onClick={onClear}
          className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-600"
          title={t("node_graph.clear_confirm", "グラフをクリアしますか？")}
        >
          {t("node_graph.clear", "クリア")}
        </button>
      )}
    </div>
  );
}

// ── Distance editor overlay ─────────────────────────────────────

interface DistanceEditorProps {
  edge: GraphEdge;
  x: number; // canvas-space midpoint x (already panned)
  y: number;
  onCommit: (distKm: number | null, travelMin: number | null) => void;
  onCancel: () => void;
}

function DistanceEditor({ edge, x, y, onCommit, onCancel }: DistanceEditorProps) {
  const { t } = useTranslation();
  const [dist, setDist] = useState(edge.distanceKm != null ? String(edge.distanceKm) : "");
  const [time, setTime] = useState(
    edge.travelTimeMin != null ? String(edge.travelTimeMin) : "",
  );

  return (
    <div
      className="pointer-events-auto absolute z-20 min-w-[160px] rounded-lg border border-border bg-white p-3 shadow-lg"
      style={{ left: x + 8, top: y - 40 }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <p className="mb-2 text-xs font-semibold text-slate-700">
        {t("node_graph.dist_editor_title", "距離・所要時間")}
      </p>
      <label className="mb-1 block text-xs text-slate-500">
        {t("node_graph.distance_km", "距離 (km)")}
        <input
          autoFocus
          type="number"
          min="0"
          step="any"
          value={dist}
          onChange={(e) => setDist(e.target.value)}
          className="field-input mt-0.5"
          placeholder="0.0"
        />
      </label>
      <label className="mb-2 block text-xs text-slate-500">
        {t("node_graph.travel_min", "所要時間 (分)")}
        <input
          type="number"
          min="0"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          className="field-input mt-0.5"
          placeholder="0"
        />
      </label>
      <div className="flex gap-1">
        <button
          onClick={() => {
            const d = dist !== "" ? Number(dist) : null;
            const m = time !== "" ? Number(time) : null;
            onCommit(d, m);
          }}
          className="flex-1 rounded bg-primary-600 py-1 text-xs font-medium text-white hover:bg-primary-700"
        >
          {t("node_graph.commit", "確定")}
        </button>
        <button
          onClick={onCancel}
          className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
        >
          {t("node_graph.cancel", "キャンセル")}
        </button>
      </div>
    </div>
  );
}

// ── Node name inline editor overlay ────────────────────────────

interface NodeNameEditorProps {
  node: GraphNode;
  x: number;
  y: number;
  onCommit: (name: string) => void;
  onCancel: () => void;
}

function NodeNameEditor({ node, x, y, onCommit, onCancel }: NodeNameEditorProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(node.name);

  return (
    <div
      className="pointer-events-auto absolute z-20"
      style={{ left: x - 56, top: y + 28 }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <input
        autoFocus
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onCommit(name);
          if (e.key === "Escape") onCancel();
        }}
        placeholder={t("node_graph.node_name_placeholder", "停留所名")}
        className="w-28 rounded border border-primary-400 bg-white px-2 py-1 text-center text-xs shadow-md focus:outline-none focus:ring-1 focus:ring-primary-400"
      />
    </div>
  );
}

// ── Main canvas component ───────────────────────────────────────

export function RouteNodeGraphPanel({ scenarioId }: Props) {
  const { t } = useTranslation();
  void scenarioId;

  // Zustand stores
  const selectedRouteId = useMasterUiStore((s) => s.selectedRouteId);
  const { tool, setTool, connectFromStopId, beginConnect, commitConnect, cancelConnect, closeDistanceEditor } =
    useNodeGraphStore();
  const {
    nodes,
    edges,
    loadRoute,
    unloadRoute,
    addNode,
    updateNode,
    removeNode,
    addEdge,
    updateEdge,
    removeEdge,
    clearGraph,
  } = useRouteGraphStore();

  // ── Viewport pan state ─────────────────────────────────────────
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const panRef = useRef({ x: 0, y: 0 });
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ px: 0, py: 0, ox: 0, oy: 0 });

  // ── Node drag state ────────────────────────────────────────────
  const isDraggingNodeRef = useRef(false);
  const dragNodeIdRef = useRef<string | null>(null);
  const dragStartRef = useRef({ px: 0, py: 0, ox: 0, oy: 0 });

  // ── Connect preview cursor position ───────────────────────────
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // ── Local editor overlays ─────────────────────────────────────
  const [distEdgeId, setDistEdgeId] = useState<string | null>(null);
  const [distPos, setDistPos] = useState({ x: 0, y: 0 });
  const [nameNodeId, setNameNodeId] = useState<string | null>(null);

  // ── Auto-increment node names ──────────────────────────────────
  const nextNodeNumRef = useRef(1);

  const svgRef = useRef<SVGSVGElement>(null);

  // ── Load / unload graph when selected route changes ────────────
  useEffect(() => {
    if (selectedRouteId) {
      loadRoute(selectedRouteId);
      nextNodeNumRef.current = 1;
    } else {
      unloadRoute();
    }
    // Reset pan on route switch
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPan({ x: 0, y: 0 });
    panRef.current = { x: 0, y: 0 };
    setDistEdgeId(null);
    setNameNodeId(null);
    cancelConnect();
  }, [selectedRouteId, loadRoute, unloadRoute, cancelConnect]);

  // ── Keyboard handler ───────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const state = useNodeGraphStore.getState();
      if (e.key === "Escape") {
        state.cancelConnect();
        closeDistanceEditor();
        setDistEdgeId(null);
        setNameNodeId(null);
        state.selectStop(null);
        state.selectEdge(null);
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        const target = e.target as HTMLElement;
        // Don't intercept if user is typing in an input
        if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
        const s = useNodeGraphStore.getState();
        if (s.selectedStopId) {
          removeNode(s.selectedStopId);
          s.selectStop(null);
          setNameNodeId(null);
        } else if (s.selectedEdgeId) {
          removeEdge(s.selectedEdgeId);
          s.selectEdge(null);
          setDistEdgeId(null);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [removeNode, removeEdge, closeDistanceEditor, cancelConnect]);

  // ── SVG coordinate from pointer event ─────────────────────────
  const svgPoint = useCallback((e: { clientX: number; clientY: number }) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  // Canvas-space → world-space (accounting for pan)
  const toWorld = useCallback(
    (sx: number, sy: number) => ({
      x: sx - panRef.current.x,
      y: sy - panRef.current.y,
    }),
    [],
  );

  // ── Pointer down on SVG background ────────────────────────────
  const onSvgPointerDown = useCallback(
    (e: ReactPointerEvent<SVGSVGElement>) => {
      if ((e.target as Element).closest(".node-group, .edge-group")) return;

      if (tool === "pan") {
        isPanningRef.current = true;
        panStartRef.current = {
          px: e.clientX,
          py: e.clientY,
          ox: panRef.current.x,
          oy: panRef.current.y,
        };
        (e.currentTarget as Element).setPointerCapture(e.pointerId);
        return;
      }

      if (tool === "select") {
        // Deselect
        useNodeGraphStore.getState().selectStop(null);
        useNodeGraphStore.getState().selectEdge(null);
        setDistEdgeId(null);
        setNameNodeId(null);
      }
    },
    [tool],
  );

  // ── Double-click on SVG background → add node ─────────────────
  const onSvgDoubleClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if ((e.target as Element).closest(".node-group, .edge-group")) return;
      if (tool !== "select") return;

      const sp = svgPoint(e);
      const world = toWorld(sp.x, sp.y);

      const name = `S${nextNodeNumRef.current++}`;
      const node = addNode(name, world.x, world.y);
      useNodeGraphStore.getState().selectStop(node.id);
      setNameNodeId(node.id);
      setDistEdgeId(null);
    },
    [tool, svgPoint, toWorld, addNode],
  );

  // ── Pointer move on SVG ────────────────────────────────────────
  const onSvgPointerMove = useCallback(
    (e: ReactPointerEvent<SVGSVGElement>) => {
      const sp = svgPoint(e);
      setMousePos(sp);

      if (isPanningRef.current) {
        const dx = e.clientX - panStartRef.current.px;
        const dy = e.clientY - panStartRef.current.py;
        const nx = panStartRef.current.ox + dx;
        const ny = panStartRef.current.oy + dy;
        panRef.current = { x: nx, y: ny };
        setPan({ x: nx, y: ny });
        return;
      }

      if (isDraggingNodeRef.current && dragNodeIdRef.current) {
        const dx = e.clientX - dragStartRef.current.px;
        const dy = e.clientY - dragStartRef.current.py;
        updateNode(dragNodeIdRef.current, {
          x: dragStartRef.current.ox + dx,
          y: dragStartRef.current.oy + dy,
        });
      }
    },
    [svgPoint, updateNode],
  );

  // ── Pointer up on SVG ─────────────────────────────────────────
  const onSvgPointerUp = useCallback(() => {
    isPanningRef.current = false;
    isDraggingNodeRef.current = false;
    dragNodeIdRef.current = null;
  }, []);

  // ── Node pointer down ─────────────────────────────────────────
  const onNodePointerDown = useCallback(
    (e: ReactPointerEvent<SVGGElement>, node: GraphNode) => {
      e.stopPropagation();

      if (tool === "connect") {
        const state = useNodeGraphStore.getState();
        if (!state.connectFromStopId) {
          beginConnect(node.id);
        } else if (state.connectFromStopId !== node.id) {
          // Complete edge
          const fromId = state.connectFromStopId;
          commitConnect(node.id);
          const edge = addEdge(fromId, node.id);
          // Open distance editor at midpoint
          const fromNode = useRouteGraphStore.getState().nodes.find((n) => n.id === fromId);
          if (fromNode) {
            const mid = midpoint(
              fromNode.x + panRef.current.x,
              fromNode.y + panRef.current.y,
              node.x + panRef.current.x,
              node.y + panRef.current.y,
            );
            setDistEdgeId(edge.id);
            setDistPos(mid);
          }
        }
        return;
      }

      if (tool === "select") {
        useNodeGraphStore.getState().selectStop(node.id);
        useNodeGraphStore.getState().selectEdge(null);
        setDistEdgeId(null);
        setNameNodeId(null);
        // Start drag
        isDraggingNodeRef.current = true;
        dragNodeIdRef.current = node.id;
        dragStartRef.current = {
          px: e.clientX,
          py: e.clientY,
          ox: node.x,
          oy: node.y,
        };
        (e.currentTarget.ownerSVGElement as Element | null)?.setPointerCapture(
          e.pointerId,
        );
      }
    },
    [tool, beginConnect, commitConnect, addEdge],
  );

  // ── Node double-click → open name editor ─────────────────────
  const onNodeDoubleClick = useCallback(
    (e: React.MouseEvent<SVGGElement>, node: GraphNode) => {
      e.stopPropagation();
      if (tool !== "select") return;
      setNameNodeId(node.id);
      setDistEdgeId(null);
    },
    [tool],
  );

  // ── Edge click → select + open distance editor ────────────────
  const onEdgeClick = useCallback(
    (e: React.MouseEvent<SVGGElement>, edge: GraphEdge) => {
      e.stopPropagation();
      if (tool !== "select") return;
      useNodeGraphStore.getState().selectEdge(edge.id);
      useNodeGraphStore.getState().selectStop(null);
      setNameNodeId(null);
      // Position editor at click point (already canvas-space)
      const sp = svgPoint(e);
      setDistEdgeId(edge.id);
      setDistPos(sp);
    },
    [tool, svgPoint],
  );

  // ── Helpers for looking up nodes ──────────────────────────────
  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));

  const selectedStopId = useNodeGraphStore((s) => s.selectedStopId);
  const selectedEdgeId = useNodeGraphStore((s) => s.selectedEdgeId);

  const distEdge = distEdgeId ? edges.find((e) => e.id === distEdgeId) ?? null : null;
  const nameNode = nameNodeId ? nodes.find((n) => n.id === nameNodeId) ?? null : null;

  // ── Connect preview from-node ─────────────────────────────────
  const connectFromNode = connectFromStopId
    ? nodes.find((n) => n.id === connectFromStopId) ?? null
    : null;

  // ── Help text ─────────────────────────────────────────────────
  const helpText: Record<NodeGraphTool, string> = {
    select: t(
      "node_graph.dbl_click_hint",
      "キャンバスをダブルクリックで停留所追加 · クリックで選択 · ドラッグで移動",
    ),
    connect: t(
      "node_graph.connect_hint",
      "停留所をクリックして接続元を選択 · 次の停留所をクリックでエッジ作成",
    ),
    pan: t("node_graph.pan_hint", "ドラッグでキャンバスを移動"),
  };

  // ── Cursor ────────────────────────────────────────────────────
  const cursorClass =
    tool === "pan"
      ? "cursor-grab active:cursor-grabbing"
      : tool === "connect"
        ? "cursor-crosshair"
        : "cursor-default";

  // ── Render ────────────────────────────────────────────────────
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Toolbar */}
      <Toolbar
        tool={tool}
        onTool={setTool}
        nodeCount={nodes.length}
        edgeCount={edges.length}
        onClear={() => {
          if (confirm(t("node_graph.clear_confirm", "グラフをクリアしますか？"))) {
            clearGraph();
            setDistEdgeId(null);
            setNameNodeId(null);
            useNodeGraphStore.getState().selectStop(null);
            useNodeGraphStore.getState().selectEdge(null);
            cancelConnect();
          }
        }}
      />

      {/* Help text */}
      <div className="border-b border-border bg-slate-50 px-3 py-1 text-[11px] text-slate-500">
        {connectFromStopId
          ? t("node_graph.connect_hint", "接続先の停留所をクリックしてください")
          : helpText[tool]}
      </div>

      {/* Canvas container */}
      <div className="relative flex-1 overflow-hidden bg-[#fafafa]">
        {/* Empty state */}
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm font-medium text-slate-400">
                {t("node_graph.empty_hint", "停留所がありません")}
              </p>
              <p className="mt-1 text-xs text-slate-300">
                {t(
                  "node_graph.dbl_click_hint_short",
                  "選択モードでキャンバスをダブルクリックして追加",
                )}
              </p>
            </div>
          </div>
        )}

        {/* SVG canvas */}
        <svg
          ref={svgRef}
          className={`h-full w-full select-none ${cursorClass}`}
          onPointerDown={onSvgPointerDown}
          onPointerMove={onSvgPointerMove}
          onPointerUp={onSvgPointerUp}
          onDoubleClick={onSvgDoubleClick}
        >
          <defs>
            {/* Grid dot pattern */}
            <pattern
              id="grid"
              width="24"
              height="24"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="1" fill="#cbd5e1" />
            </pattern>
          </defs>

          {/* Grid background */}
          <rect width="100%" height="100%" fill="url(#grid)" />

          {/* Panned world group */}
          <g transform={`translate(${pan.x},${pan.y})`}>
            {/* Edge layer */}
            {edges.map((edge) => {
              const from = nodeMap[edge.fromId];
              const to = nodeMap[edge.toId];
              if (!from || !to) return null;
              const isSelected = edge.id === selectedEdgeId;
              const mid = midpoint(from.x, from.y, to.x, to.y);
              const arrow = arrowHead(from.x, from.y, to.x, to.y);

              return (
                <g
                  key={edge.id}
                  className="edge-group cursor-pointer"
                  onClick={(e) => onEdgeClick(e, edge)}
                >
                  {/* Wide invisible hit area */}
                  <line
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="transparent"
                    strokeWidth={16}
                  />
                  {/* Visible line */}
                  <line
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke={isSelected ? "#2563eb" : "#64748b"}
                    strokeWidth={isSelected ? 2.5 : 1.5}
                    strokeDasharray={isSelected ? undefined : undefined}
                  />
                  {/* Arrowhead */}
                  {arrow && (
                    <polygon
                      points={arrow}
                      fill={isSelected ? "#2563eb" : "#64748b"}
                    />
                  )}
                  {/* Distance label */}
                  {edge.distanceKm != null && (
                    <text
                      x={mid.x}
                      y={mid.y - 6}
                      textAnchor="middle"
                      fontSize={10}
                      fill={isSelected ? "#2563eb" : "#94a3b8"}
                      className="pointer-events-none"
                    >
                      {edge.distanceKm.toFixed(1)} km
                    </text>
                  )}
                </g>
              );
            })}

            {/* Connect preview line */}
            {connectFromNode && (
              <line
                x1={connectFromNode.x}
                y1={connectFromNode.y}
                x2={mousePos.x - pan.x}
                y2={mousePos.y - pan.y}
                stroke="#3b82f6"
                strokeWidth={1.5}
                strokeDasharray="6 3"
                className="pointer-events-none"
              />
            )}

            {/* Node layer */}
            {nodes.map((node) => {
              const isSelected = node.id === selectedStopId;
              const isConnectFrom = node.id === connectFromStopId;

              return (
                <g
                  key={node.id}
                  className="node-group"
                  transform={`translate(${node.x},${node.y})`}
                  onPointerDown={(e) => onNodePointerDown(e, node)}
                  onDoubleClick={(e) => onNodeDoubleClick(e, node)}
                  style={{ cursor: tool === "connect" ? "crosshair" : "pointer" }}
                >
                  {/* Selection / connect ring */}
                  {(isSelected || isConnectFrom) && (
                    <circle
                      r={30}
                      fill="none"
                      stroke={isConnectFrom ? "#f59e0b" : "#2563eb"}
                      strokeWidth={2}
                      strokeDasharray={isConnectFrom ? "4 2" : undefined}
                    />
                  )}
                  {/* Node circle */}
                  <circle
                    r={24}
                    fill={isConnectFrom ? "#fef3c7" : isSelected ? "#eff6ff" : "white"}
                    stroke={isConnectFrom ? "#f59e0b" : isSelected ? "#2563eb" : "#94a3b8"}
                    strokeWidth={isSelected || isConnectFrom ? 2 : 1.5}
                  />
                  {/* Node label */}
                  <text
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={11}
                    fontWeight={600}
                    fill={isConnectFrom ? "#92400e" : isSelected ? "#1d4ed8" : "#334155"}
                    className="pointer-events-none select-none"
                  >
                    {node.name.length > 6 ? node.name.slice(0, 5) + "…" : node.name}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* ── Overlays (absolute, in canvas-space) ────────────── */}

        {/* Distance editor */}
        {distEdge && (
          <DistanceEditor
            edge={distEdge}
            x={distPos.x}
            y={distPos.y}
            onCommit={(distKm, travelMin) => {
              updateEdge(distEdge.id, { distanceKm: distKm, travelTimeMin: travelMin });
              setDistEdgeId(null);
            }}
            onCancel={() => setDistEdgeId(null)}
          />
        )}

        {/* Node name editor */}
        {nameNode && (
          <NodeNameEditor
            node={nameNode}
            x={nameNode.x + pan.x}
            y={nameNode.y + pan.y}
            onCommit={(name) => {
              updateNode(nameNode.id, { name });
              setNameNodeId(null);
            }}
            onCancel={() => setNameNodeId(null)}
          />
        )}
      </div>
    </div>
  );
}
