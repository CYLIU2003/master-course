import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useGraph, useBuildGraph, useDispatchScope } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";
import type { FeasibilityReason } from "@/types";

export function GraphPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scope } = useDispatchScope(scenarioId!);
  const { data: graph, isLoading, error } = useGraph(scenarioId!);
  const buildMutation = useBuildGraph(scenarioId!);
  const [reasonFilter, setReasonFilter] = useState<FeasibilityReason | "all">("all");

  const handleBuild = () => {
    buildMutation.mutate({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
  };

  const filteredArcs =
    graph?.arcs.filter((arc) => reasonFilter === "all" || arc.reason_code === reasonFilter) ?? [];

  const displayedArcs = filteredArcs.slice(0, 12);

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />

      <PageSection
        title={t("graph.title")}
        description={t("graph.description")}
        actions={
          <button
            onClick={handleBuild}
            disabled={buildMutation.isPending}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {buildMutation.isPending ? t("graph.building") : t("graph.build")}
          </button>
        }
      >
        {isLoading ? (
          <LoadingBlock message={t("graph.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : !graph ? (
          <EmptyState title={t("graph.no_graph")} description={t("graph.no_graph_description")} />
        ) : (
          <>
            <div className="mb-4 grid grid-cols-3 gap-4">
              <StatCard label={t("graph.total_arcs")} value={graph.total_arcs} />
              <StatCard label={t("graph.feasible")} value={graph.feasible_arcs} color="green" />
              <StatCard label={t("graph.infeasible")} value={graph.infeasible_arcs} color="red" />
            </div>

            <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
              <div className="rounded-lg border border-border bg-surface-raised p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-800">Reason breakdown</h3>
                  <select
                    value={reasonFilter}
                    onChange={(event) =>
                      setReasonFilter(event.target.value as FeasibilityReason | "all")
                    }
                    className="rounded border border-border bg-white px-2 py-1 text-xs"
                  >
                    <option value="all">all</option>
                    {Object.keys(graph.reason_counts).map((reasonCode) => (
                      <option key={reasonCode} value={reasonCode}>
                        {reasonCode}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  {Object.entries(graph.reason_counts).map(([reasonCode, count]) => (
                    <div
                      key={reasonCode}
                      className="flex items-center justify-between rounded border border-border px-3 py-2 text-xs"
                    >
                      <span className="font-mono text-slate-600">{reasonCode}</span>
                      <span className="font-semibold text-slate-900">{count}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-border bg-surface-raised">
                <div className="border-b border-border px-4 py-3">
                  <h3 className="text-sm font-semibold text-slate-800">Analyzed connections</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    {filteredArcs.length} arcs match the current filter. Showing the first {displayedArcs.length}.
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-xs">
                    <thead className="bg-surface-sunken text-slate-500">
                      <tr>
                        <th className="px-4 py-2 font-medium">Vehicle</th>
                        <th className="px-4 py-2 font-medium">From</th>
                        <th className="px-4 py-2 font-medium">To</th>
                        <th className="px-4 py-2 font-medium">Reason</th>
                        <th className="px-4 py-2 font-medium">Turn</th>
                        <th className="px-4 py-2 font-medium">Deadhead</th>
                        <th className="px-4 py-2 font-medium">Slack</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayedArcs.map((arc) => (
                        <tr key={`${arc.vehicle_type}:${arc.from_trip_id}:${arc.to_trip_id}`} className="border-t border-border">
                          <td className="px-4 py-2 font-mono">{arc.vehicle_type}</td>
                          <td className="px-4 py-2 font-mono">{arc.from_trip_id}</td>
                          <td className="px-4 py-2 font-mono">{arc.to_trip_id}</td>
                          <td className="px-4 py-2">
                            <div className="font-mono text-slate-700">{arc.reason_code}</div>
                            <div className="mt-1 text-slate-500">{arc.reason}</div>
                          </td>
                          <td className="px-4 py-2">{arc.turnaround_time_min}</td>
                          <td className="px-4 py-2">{arc.deadhead_time_min}</td>
                          <td className={`px-4 py-2 font-semibold ${arc.feasible ? "text-green-700" : "text-red-600"}`}>
                            {arc.slack_min}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </PageSection>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  const textColor = color === "green" ? "text-green-600" : color === "red" ? "text-red-600" : "text-slate-700";
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className={`mt-1 text-xl font-bold ${textColor}`}>{value}</p>
    </div>
  );
}
