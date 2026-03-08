// ── RouteEditorDrawer ─────────────────────────────────────────
// Editor drawer for creating / editing a route.
// Tabs: basic info, stops/edges, timetable, link status.

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
import type { Route, RouteResolvedStop } from "@/types";
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
  { key: "stops", label: "停留所・エッジ" },
  { key: "timetable", label: "時刻表" },
  { key: "link", label: "リンク状態" },
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
          {!isCreate && route && (
            <RouteMetaBadges route={route} />
          )}
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
        <StopsEdgeEditor
          routeId={routeId}
          importedStops={route?.stopSequence ?? []}
          resolvedStops={route?.resolvedStops ?? []}
        />
      )}

      {activeTab === "timetable" && (
        <TimetableTab route={route ?? null} />
      )}

      {activeTab === "link" && (
        <LinkStatusTab route={route ?? null} />
      )}
    </EditorDrawer>
  );
}

// ── RouteMetaBadges ──────────────────────────────────────────
// Shows metadata badges at the top of the basic info tab.

function RouteMetaBadges({ route }: { route: Route }) {
  const linkStateColors: Record<string, string> = {
    linked: "bg-green-100 text-green-700 border-green-200",
    partial: "bg-amber-50 text-amber-700 border-amber-200",
    unlinked: "bg-slate-100 text-slate-500 border-slate-200",
    error: "bg-red-50 text-red-600 border-red-200",
  };
  const linkStateLabels: Record<string, string> = {
    linked: "全リンク済",
    partial: "一部未リンク",
    unlinked: "未リンク",
    error: "エラー",
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
      <div className="flex flex-wrap gap-2">
        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5">
          {route.source?.toUpperCase() ?? "MANUAL"}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5">
          {route.stopSequence?.length ?? 0} 停留所
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5">
          {route.tripCount ?? 0} 便
        </span>
        {route.linkState && (
          <span
            className={`rounded-full border px-2 py-0.5 ${linkStateColors[route.linkState] ?? linkStateColors.unlinked
              }`}
          >
            {linkStateLabels[route.linkState] ?? route.linkState}
          </span>
        )}
        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5">
          {route.depotId ? `営業所: 所属済` : "営業所: 未所属"}
        </span>
      </div>
      <p className="mt-2 text-slate-500">
        所属営業所の編集は Public Data Collection Explorer で行います。
      </p>
    </div>
  );
}

// ── StopsEdgeEditor ──────────────────────────────────────────
// Shows resolved stops, the node/edge graph, and generates
// nodes and edges from the imported stop sequence.

interface StopsEdgeEditorProps {
  routeId: string | null;
  importedStops: string[];
  resolvedStops: RouteResolvedStop[];
}

function StopsEdgeEditor({ routeId, importedStops, resolvedStops }: StopsEdgeEditorProps) {
  const { t } = useTranslation();
  const { nodes, edges, updateNode, updateEdge, removeNode, removeEdge, addNode, addEdge, clearGraph } =
    useRouteGraphStore();

  const [nodeSubTab, setNodeSubTab] = useState<"resolved" | "nodes" | "edges">("resolved");

  if (!routeId) {
    return (
      <p className="py-4 text-center text-xs text-slate-400">
        {t("node_graph.stops_tab_nodes", "停留所")} —{" "}
        {t("common.not_configured", "（未設定）")}
      </p>
    );
  }

  // ── Generate nodes from resolved stops ────────────────────
  const handleGenerateNodes = () => {
    if (resolvedStops.length === 0 && importedStops.length === 0) return;
    // Clear existing graph first
    clearGraph();

    const stopsToUse = resolvedStops.length > 0 ? resolvedStops : null;
    if (stopsToUse) {
      stopsToUse.forEach((stop, i) => {
        const node = addNode(stop.name, 80, 60 + i * 80);
        // Update lat/lng from resolved stop data
        if (stop.lat != null && stop.lon != null) {
          updateNode(node.id, { lat: stop.lat, lng: stop.lon });
        }
      });
    } else {
      // Fallback: use raw IDs as names
      importedStops.forEach((stopId, i) => {
        addNode(stopId, 80, 60 + i * 80);
      });
    }
  };

  // ── Generate edges from sequential node pairs ─────────────
  const handleGenerateEdges = () => {
    if (nodes.length < 2) return;
    for (let i = 0; i < nodes.length - 1; i++) {
      addEdge(nodes[i].id, nodes[i + 1].id);
    }
  };

  return (
    <div className="space-y-3">
      {/* Resolved stops summary */}
      {resolvedStops.length > 0 ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-emerald-800">
              解決済 停留所シーケンス ({resolvedStops.length} 件)
            </p>
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              ✓ カタログ照合済み
            </span>
          </div>
        </div>
      ) : importedStops.length > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-800">
            インポート済 停留所 ID ({importedStops.length} 件) — 未解決
          </p>
          <p className="mt-1 text-[11px] text-amber-600">
            停留所カタログとの照合が完了していません。停留所インポートを先に実行してください。
          </p>
        </div>
      ) : null}

      {/* Sub-tabs */}
      <div className="flex rounded-lg border border-border">
        {(["resolved", "nodes", "edges"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setNodeSubTab(k)}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${nodeSubTab === k
              ? "bg-primary-600 text-white"
              : "text-slate-600 hover:bg-slate-50"
              }`}
          >
            {k === "resolved"
              ? `解決済 (${resolvedStops.length})`
              : k === "nodes"
                ? `ノード (${nodes.length})`
                : `エッジ (${edges.length})`}
          </button>
        ))}
      </div>

      {/* ── Resolved Stops List ──────────────────────────────── */}
      {nodeSubTab === "resolved" && (
        <div className="space-y-2">
          {resolvedStops.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-xs text-slate-400">
                解決済み停留所がありません
              </p>
              {importedStops.length > 0 && (
                <p className="mt-1 text-[11px] text-slate-400">
                  停留所カタログをインポートすると、ここに停留所が表示されます
                </p>
              )}
            </div>
          ) : (
            <div className="max-h-80 divide-y divide-border overflow-y-auto rounded-lg border border-border">
              {resolvedStops.map((stop) => (
                <div key={`${stop.id}-${stop.sequence}`} className="flex items-center gap-2 px-3 py-1.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-100 text-[10px] font-bold text-primary-700">
                    {stop.sequence}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-700">
                      {stop.name}
                    </p>
                    {(stop.lat != null && stop.lon != null) && (
                      <p className="text-[10px] text-slate-400">
                        {stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}
                        {stop.platformCode && ` (${stop.platformCode})`}
                      </p>
                    )}
                  </div>
                  {stop.lat != null ? (
                    <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[9px] text-green-700">
                      📍
                    </span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-500">
                      —
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Generate buttons */}
          {(resolvedStops.length > 0 || importedStops.length > 0) && (
            <div className="flex gap-2">
              <button
                onClick={handleGenerateNodes}
                className="flex-1 rounded-lg border border-primary-300 bg-primary-50 py-2 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100"
              >
                🔄 ノード自動生成
              </button>
              {nodes.length >= 2 && (
                <button
                  onClick={handleGenerateEdges}
                  className="flex-1 rounded-lg border border-indigo-300 bg-indigo-50 py-2 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
                >
                  🔗 エッジ自動生成
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Nodes View ──────────────────────────────────────── */}
      {nodeSubTab === "nodes" && (
        <div className="space-y-2">
          {nodes.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-xs text-slate-400">
                {t("node_graph.empty_hint", "ノードがありません")}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                「解決済」タブの ノード自動生成 ボタンで停留所から自動作成できます
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              {nodes.map((n, i) => (
                <div
                  key={n.id}
                  className="flex items-center gap-2 rounded border border-border bg-white px-2 py-1.5"
                >
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[9px] font-bold text-slate-600">
                    {i + 1}
                  </span>
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

      {/* ── Edges View ──────────────────────────────────────── */}
      {nodeSubTab === "edges" && (
        <div className="space-y-2">
          {edges.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-xs text-slate-400">
                {t("node_graph.empty_hint", "エッジがありません")}
              </p>
              {nodes.length >= 2 && (
                <button
                  onClick={handleGenerateEdges}
                  className="mt-2 rounded-lg border border-indigo-300 bg-indigo-50 px-4 py-1.5 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
                >
                  🔗 順序でエッジ自動生成
                </button>
              )}
            </div>
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

// ── TimetableTab ─────────────────────────────────────────────
// Shows timetable overview for the route.

function TimetableTab({ route }: { route: Route | null }) {
  if (!route) {
    return (
      <p className="py-6 text-center text-xs text-slate-400">
        路線データを読み込んでいます…
      </p>
    );
  }

  const tripCount = route.tripCount ?? 0;
  const serviceSummary = route.serviceSummary ?? [];

  return (
    <div className="space-y-4">
      {/* Overview card */}
      <div className="rounded-lg border border-border bg-white p-4">
        <div className="flex items-baseline justify-between">
          <span className="text-xs font-medium text-slate-500">総便数</span>
          <span className="text-2xl font-bold text-slate-800">
            {tripCount}
          </span>
        </div>
        {tripCount === 0 && (
          <p className="mt-2 text-[11px] text-slate-400">
            時刻表データがまだインポートされていません。
            「入力データ」→「時刻表」でインポートできます。
          </p>
        )}
      </div>

      {/* Service breakdown */}
      {serviceSummary.length > 0 && (
        <div className="rounded-lg border border-border">
          <div className="border-b border-border px-3 py-2">
            <p className="text-xs font-medium text-slate-600">
              サービス別 便数
            </p>
          </div>
          <div className="divide-y divide-border">
            {serviceSummary.map((svc) => (
              <div
                key={svc.serviceId}
                className="flex items-center justify-between px-3 py-2"
              >
                <div>
                  <span className="text-xs font-medium text-slate-700">
                    {svc.serviceId}
                  </span>
                  {svc.firstDeparture && svc.lastDeparture && (
                    <span className="ml-2 text-[10px] text-slate-400">
                      {svc.firstDeparture} — {svc.lastDeparture}
                    </span>
                  )}
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {svc.tripCount} 便
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data source info */}
      {route.durationSource && (
        <div className="text-[10px] text-slate-400">
          所要時間ソース: {route.durationSource}
          {route.distanceSource && ` / 距離ソース: ${route.distanceSource}`}
        </div>
      )}
    </div>
  );
}

// ── LinkStatusTab ────────────────────────────────────────────
// Shows the data link resolution status for the route.

function LinkStatusTab({ route }: { route: Route | null }) {
  if (!route) {
    return (
      <p className="py-6 text-center text-xs text-slate-400">
        路線データを読み込んでいます…
      </p>
    );
  }

  const linkStatus = route.linkStatus;
  const linkState = route.linkState ?? "unlinked";

  const stateConfig: Record<string, { color: string; bg: string; icon: string; label: string }> = {
    linked: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: "✅", label: "全リンク完了" },
    partial: { color: "text-amber-700", bg: "bg-amber-50 border-amber-200", icon: "⚠️", label: "一部リンク" },
    unlinked: { color: "text-slate-500", bg: "bg-slate-50 border-slate-200", icon: "❌", label: "未リンク" },
    error: { color: "text-red-600", bg: "bg-red-50 border-red-200", icon: "🚫", label: "エラー" },
  };
  const cfg = stateConfig[linkState] ?? stateConfig.unlinked;

  return (
    <div className="space-y-4">
      {/* State banner */}
      <div className={`rounded-lg border p-4 ${cfg.bg}`}>
        <div className="flex items-center gap-2">
          <span className="text-lg">{cfg.icon}</span>
          <span className={`text-sm font-semibold ${cfg.color}`}>
            {cfg.label}
          </span>
        </div>
      </div>

      {/* Detail stats */}
      {linkStatus && (
        <div className="grid grid-cols-2 gap-3">
          <StatCard label="停留所 解決済" value={linkStatus.stopsResolved} color="emerald" />
          <StatCard label="停留所 未解決" value={linkStatus.stopsMissing} color={linkStatus.stopsMissing > 0 ? "amber" : "slate"} />
          <StatCard label="便 リンク済" value={linkStatus.tripsLinked} color="blue" />
          <StatCard label="停留所時刻表" value={linkStatus.stopTimetableEntriesLinked} color="blue" />
        </div>
      )}

      {/* Missing stops */}
      {linkStatus && (linkStatus.missingStopIds?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-800">
            未解決 停留所 ID ({linkStatus.missingStopIds!.length} 件)
          </p>
          <div className="mt-2 flex max-h-24 flex-wrap gap-1 overflow-y-auto">
            {linkStatus.missingStopIds!.map((id) => (
              <span
                key={id}
                className="rounded-full border border-amber-200 bg-white px-2 py-0.5 text-[10px] text-amber-700"
              >
                {id}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {linkStatus && linkStatus.warnings.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="text-xs font-medium text-red-800">
            警告 ({linkStatus.warnings.length} 件)
          </p>
          <ul className="mt-1 list-inside list-disc">
            {linkStatus.warnings.slice(0, 10).map((w, i) => (
              <li key={i} className="text-[11px] text-red-600">
                {w}
              </li>
            ))}
            {linkStatus.warnings.length > 10 && (
              <li className="text-[11px] text-red-500">
                …他 {linkStatus.warnings.length - 10} 件
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Import metadata */}
      {route.importMeta && (
        <div className="rounded-lg border border-border bg-white p-3">
          <p className="text-xs font-medium text-slate-500 mb-2">
            インポート情報
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
            {route.importMeta.source && (
              <>
                <span className="text-slate-400">ソース</span>
                <span className="text-slate-700">{route.importMeta.source.toUpperCase()}</span>
              </>
            )}
            {route.importMeta.generatedAt && (
              <>
                <span className="text-slate-400">生成日時</span>
                <span className="text-slate-700">{route.importMeta.generatedAt}</span>
              </>
            )}
            {route.importMeta.snapshotKey && (
              <>
                <span className="text-slate-400">スナップショット</span>
                <span className="truncate text-slate-700">{route.importMeta.snapshotKey}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── StatCard ─────────────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    emerald: "text-emerald-700 bg-emerald-50",
    amber: "text-amber-700 bg-amber-50",
    blue: "text-blue-700 bg-blue-50",
    red: "text-red-700 bg-red-50",
    slate: "text-slate-500 bg-slate-50",
  };

  return (
    <div className={`rounded-lg border border-border p-3 ${colorMap[color] ?? colorMap.slate}`}>
      <p className="text-[10px] font-medium opacity-70">{label}</p>
      <p className="mt-0.5 text-lg font-bold">{value}</p>
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
