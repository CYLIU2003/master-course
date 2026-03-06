// ── RouteEditorDrawer ─────────────────────────────────────────
// Editor drawer for creating / editing a route.
// Supports tabbed sections: basic info, stops/edges.

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { DrawerTabs } from "@/features/common/DrawerTabs";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { useRouteGraphStore } from "@/stores/route-graph-store";
import {
  useRoute,
  useCreateRoute,
  useUpdateRoute,
  useDeleteRoute,
} from "@/hooks";
import type { Route } from "@/types";
import type { CreateRouteRequest, UpdateRouteRequest } from "@/types/api";

interface Props {
  scenarioId: string;
  routeId: string | null;
  isCreate: boolean;
}

type FormData = {
  name: string;
  startStop: string;
  endStop: string;
  distanceKm: string;
  durationMin: string;
  color: string;
  enabled: boolean;
};

const EMPTY_FORM: FormData = {
  name: "",
  startStop: "",
  endStop: "",
  distanceKm: "0",
  durationMin: "0",
  color: "#3b82f6",
  enabled: true,
};

function routeToForm(r: Route): FormData {
  return {
    name: r.name,
    startStop: r.startStop,
    endStop: r.endStop,
    distanceKm: String(r.distanceKm),
    durationMin: String(r.durationMin),
    color: r.color || "#3b82f6",
    enabled: r.enabled,
  };
}

const TABS = [
  { key: "basic", label: "基本情報" },
  { key: "stops", label: "停留所" },
];

export function RouteEditorDrawer({ scenarioId, routeId, isCreate }: Props) {
  const { t } = useTranslation();
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const setDirty = useMasterUiStore((s) => s.setDirty);
  const isDirty = useMasterUiStore((s) => s.isDirty);

  const { data: route } = useRoute(scenarioId, routeId ?? "");
  const createRoute = useCreateRoute(scenarioId);
  const updateRoute = useUpdateRoute(scenarioId, routeId ?? "");
  const deleteRoute = useDeleteRoute(scenarioId);

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");

  useEffect(() => {
    if (isCreate) {
      setForm(EMPTY_FORM);
    } else if (route) {
      setForm(routeToForm(route));
    }
  }, [route, isCreate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setDirty(true);
    },
    [setDirty],
  );

  const handleSave = () => {
    if (isCreate) {
      const req: CreateRouteRequest = {
        name: form.name || "新規路線",
        startStop: form.startStop,
        endStop: form.endStop,
        distanceKm: Number(form.distanceKm) || 0,
        durationMin: Number(form.durationMin) || 0,
        color: form.color,
        enabled: form.enabled,
      };
      createRoute.mutate(req, {
        onSuccess: () => closeDrawer(),
      });
    } else if (routeId) {
      const req: UpdateRouteRequest = {
        name: form.name,
        startStop: form.startStop,
        endStop: form.endStop,
        distanceKm: Number(form.distanceKm) || 0,
        durationMin: Number(form.durationMin) || 0,
        color: form.color,
        enabled: form.enabled,
      };
      updateRoute.mutate(req, {
        onSuccess: () => setDirty(false),
      });
    }
  };

  const handleDelete = () => {
    if (!routeId) return;
    if (!confirm(t("routes.delete_confirm", "この路線を削除しますか？"))) return;
    deleteRoute.mutate(routeId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const isSaving = createRoute.isPending || updateRoute.isPending;

  return (
    <EditorDrawer
      open
      title={isCreate ? t("routes.create_title", "路線を追加") : form.name || "路線"}
      subtitle={routeId ?? undefined}
      onClose={closeDrawer}
      onSave={handleSave}
      onDelete={!isCreate && routeId ? handleDelete : undefined}
      isDirty={isDirty}
      isSaving={isSaving}
    >
      <DrawerTabs tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === "basic" && (
        <div className="space-y-4">
          <Field label={t("routes.field_name", "路線名")}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              className="field-input"
              placeholder="例: 鶴見線"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("routes.field_start", "始点")}>
              <input
                type="text"
                value={form.startStop}
                onChange={(e) => updateField("startStop", e.target.value)}
                className="field-input"
                placeholder="始点停留所"
              />
            </Field>
            <Field label={t("routes.field_end", "終点")}>
              <input
                type="text"
                value={form.endStop}
                onChange={(e) => updateField("endStop", e.target.value)}
                className="field-input"
                placeholder="終点停留所"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("routes.field_distance", "距離 (km)")}>
              <input
                type="number"
                min="0"
                step="any"
                value={form.distanceKm}
                onChange={(e) => updateField("distanceKm", e.target.value)}
                className="field-input"
              />
            </Field>
            <Field label={t("routes.field_duration", "所要時間 (分)")}>
              <input
                type="number"
                min="0"
                value={form.durationMin}
                onChange={(e) => updateField("durationMin", e.target.value)}
                className="field-input"
              />
            </Field>
          </div>
          <Field label={t("routes.field_color", "表示色")}>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={form.color}
                onChange={(e) => updateField("color", e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-border"
              />
              <input
                type="text"
                value={form.color}
                onChange={(e) => updateField("color", e.target.value)}
                className="field-input flex-1"
                placeholder="#3b82f6"
              />
            </div>
          </Field>
          <CheckboxField
            label={t("routes.field_enabled", "有効")}
            checked={form.enabled}
            onChange={(v) => updateField("enabled", v)}
          />
        </div>
      )}

      {activeTab === "stops" && (
        <StopsEdgeEditor routeId={routeId} />
      )}
    </EditorDrawer>
  );
}

// ── StopsEdgeEditor ──────────────────────────────────────────
// Shows the node list and edge table from the route-graph store,
// allowing inline edits without switching to the node graph canvas.

interface StopsEdgeEditorProps {
  routeId: string | null;
}

function StopsEdgeEditor({ routeId }: StopsEdgeEditorProps) {
  const { t } = useTranslation();
  const { nodes, edges, updateNode, updateEdge, removeNode, removeEdge, addNode, addEdge } =
    useRouteGraphStore();

  const [nodeSubTab, setNodeSubTab] = useState<"nodes" | "edges">("nodes");

  if (!routeId) {
    return (
      <p className="py-4 text-center text-xs text-slate-400">
        {t("node_graph.stops_tab_nodes", "停留所")} —{" "}
        {t("common.not_configured", "（未設定）")}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {/* Sub-tab */}
      <div className="flex rounded-lg border border-border">
        {(["nodes", "edges"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setNodeSubTab(k)}
            className={`flex-1 py-1 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
              nodeSubTab === k
                ? "bg-primary-600 text-white"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            {k === "nodes"
              ? t("node_graph.stops_tab_nodes", "停留所") + ` (${nodes.length})`
              : t("node_graph.stops_tab_edges", "エッジ") + ` (${edges.length})`}
          </button>
        ))}
      </div>

      {nodeSubTab === "nodes" && (
        <div className="space-y-2">
          {nodes.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-400">
              {t("node_graph.empty_hint", "停留所がありません")}
            </p>
          ) : (
            <div className="space-y-1">
              {nodes.map((n) => (
                <div
                  key={n.id}
                  className="flex items-center gap-2 rounded border border-border bg-white px-2 py-1.5"
                >
                  <input
                    type="text"
                    value={n.name}
                    onChange={(e) => updateNode(n.id, { name: e.target.value })}
                    className="field-input flex-1 text-xs"
                  />
                  <input
                    type="number"
                    value={n.lat ?? ""}
                    onChange={(e) =>
                      updateNode(n.id, {
                        lat: e.target.value !== "" ? Number(e.target.value) : null,
                      })
                    }
                    placeholder={t("depots.field_lat", "緯度")}
                    className="field-input w-20 text-xs"
                  />
                  <input
                    type="number"
                    value={n.lng ?? ""}
                    onChange={(e) =>
                      updateNode(n.id, {
                        lng: e.target.value !== "" ? Number(e.target.value) : null,
                      })
                    }
                    placeholder={t("depots.field_lon", "経度")}
                    className="field-input w-20 text-xs"
                  />
                  <button
                    onClick={() => removeNode(n.id)}
                    className="shrink-0 rounded px-1.5 py-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
                    title={t("common.delete", "削除")}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
          <button
            onClick={() => addNode(`S${nodes.length + 1}`, 200 + nodes.length * 60, 200)}
            className="w-full rounded border border-dashed border-primary-300 py-1.5 text-xs text-primary-600 hover:bg-primary-50"
          >
            {t("node_graph.add_node", "+ 停留所を追加")}
          </button>
        </div>
      )}

      {nodeSubTab === "edges" && (
        <div className="space-y-2">
          {edges.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-400">
              {t("node_graph.empty_hint", "エッジがありません")}
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-slate-500">
                  <th className="pb-1 text-left font-medium">
                    {t("node_graph.col_from", "始点")}
                  </th>
                  <th className="pb-1 text-left font-medium">
                    {t("node_graph.col_to", "終点")}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t("node_graph.col_dist", "距離 (km)")}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t("node_graph.col_travel", "所要 (分)")}
                  </th>
                  <th className="w-6" />
                </tr>
              </thead>
              <tbody>
                {edges.map((e) => {
                  const fromName =
                    nodes.find((n) => n.id === e.fromId)?.name ?? e.fromId;
                  const toName =
                    nodes.find((n) => n.id === e.toId)?.name ?? e.toId;
                  return (
                    <tr key={e.id} className="border-b border-border/60">
                      <td className="py-1 pr-1 text-slate-700">{fromName}</td>
                      <td className="py-1 pr-1 text-slate-700">{toName}</td>
                      <td className="py-1 pr-1">
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={e.distanceKm ?? ""}
                          onChange={(ev) =>
                            updateEdge(e.id, {
                              distanceKm:
                                ev.target.value !== ""
                                  ? Number(ev.target.value)
                                  : null,
                            })
                          }
                          className="field-input w-16 text-right text-xs"
                          placeholder="0.0"
                        />
                      </td>
                      <td className="py-1 pr-1">
                        <input
                          type="number"
                          min="0"
                          value={e.travelTimeMin ?? ""}
                          onChange={(ev) =>
                            updateEdge(e.id, {
                              travelTimeMin:
                                ev.target.value !== ""
                                  ? Number(ev.target.value)
                                  : null,
                            })
                          }
                          className="field-input w-14 text-right text-xs"
                          placeholder="0"
                        />
                      </td>
                      <td className="py-1">
                        <button
                          onClick={() => removeEdge(e.id)}
                          className="rounded px-1 py-0.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                          title={t("common.delete", "削除")}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {/* Add edge (pick from/to) */}
          {nodes.length >= 2 && (
            <AddEdgeRow nodes={nodes} onAdd={addEdge} />
          )}
        </div>
      )}
    </div>
  );
}

// ── AddEdgeRow ────────────────────────────────────────────────
// Dropdown pair for manually adding an edge in the stops tab.

function AddEdgeRow({
  nodes,
  onAdd,
}: {
  nodes: ReturnType<typeof useRouteGraphStore.getState>["nodes"];
  onAdd: (fromId: string, toId: string) => void;
}) {
  const { t } = useTranslation();
  const [fromId, setFromId] = useState(nodes[0]?.id ?? "");
  const [toId, setToId] = useState(nodes[1]?.id ?? "");

  return (
    <div className="flex items-center gap-1">
      <select
        value={fromId}
        onChange={(e) => setFromId(e.target.value)}
        className="field-input flex-1 text-xs"
      >
        {nodes.map((n) => (
          <option key={n.id} value={n.id}>
            {n.name}
          </option>
        ))}
      </select>
      <span className="text-slate-400">→</span>
      <select
        value={toId}
        onChange={(e) => setToId(e.target.value)}
        className="field-input flex-1 text-xs"
      >
        {nodes.map((n) => (
          <option key={n.id} value={n.id}>
            {n.name}
          </option>
        ))}
      </select>
      <button
        onClick={() => {
          if (fromId && toId && fromId !== toId) onAdd(fromId, toId);
        }}
        className="shrink-0 rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700"
      >
        {t("node_graph.add_edge", "追加")}
      </button>
    </div>
  );
}

// ── Local field helpers ──────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">
        {label}
      </span>
      {children}
    </label>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
      />
      <span className="text-xs font-medium text-slate-600">{label}</span>
    </label>
  );
}
