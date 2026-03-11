import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useGraphArcs, useGraphSummary, useBuildGraph, useDispatchScope, useJob } from "@/hooks";
import { BackendJobPanel, PageSection, LoadingBlock, ErrorBlock, EmptyState, TabWarmBoundary, VirtualizedList } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";
import type { FeasibilityReason } from "@/types";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";

const PAGE_SIZE = 120;

export function GraphPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  useRenderTrace("GraphPage");
  const { data: scope } = useDispatchScope(scenarioId!);
  const scopeReady = Boolean(scope?.depotId);
  const buildMutation = useBuildGraph(scenarioId!);
  const [reasonFilter, setReasonFilter] = useState<FeasibilityReason | "all">("all");
  const [pageOffset, setPageOffset] = useState(0);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const { data: summary, isLoading, error } = useGraphSummary(scenarioId!, scopeReady);
  const { data: arcsData } = useGraphArcs(scenarioId!, {
    reasonCode: reasonFilter === "all" ? undefined : reasonFilter,
    limit: PAGE_SIZE,
    offset: pageOffset,
    enabled: scopeReady,
  });
  const { data: activeJob } = useJob(activeJobId);

  useEffect(() => {
    setPageOffset(0);
  }, [reasonFilter]);

  const handleBuild = async () => {
    const job = await buildMutation.mutateAsync({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
    setActiveJobId(job.job_id);
  };
  const arcs = arcsData?.items ?? [];
  const total = arcsData?.total ?? 0;
  const pageStart = total === 0 ? 0 : pageOffset + 1;
  const pageEnd = Math.min(pageOffset + arcs.length, total);

  return (
    <TabWarmBoundary tab="dispatch" title="Dispatch tab を準備しています">
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />
      <BackendJobPanel job={activeJob} />

      <PageSection
        title={t("graph.title")}
        description={t("graph.description")}
        actions={
          <button
            onClick={handleBuild}
            disabled={buildMutation.isPending || !scopeReady}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {buildMutation.isPending ? t("graph.building") : t("graph.build")}
          </button>
        }
      >
        {!scopeReady ? (
          <EmptyState title="営業所を選択してください" description="接続グラフを作る前に、対象営業所を 1 つ選択してください。" />
        ) : isLoading ? (
          <LoadingBlock message={t("graph.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : !summary ? (
          <EmptyState title={t("graph.no_graph")} description={t("graph.no_graph_description")} />
        ) : (
          <>
            <div className="mb-4 grid grid-cols-3 gap-4">
              <StatCard label={t("graph.total_arcs")} value={summary.item.totalArcs} />
              <StatCard label={t("graph.feasible")} value={summary.item.feasibleArcs} color="green" />
              <StatCard label={t("graph.infeasible")} value={summary.item.infeasibleArcs} color="red" />
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
                    {Object.keys(summary.item.reasonCounts).map((reasonCode) => (
                      <option key={reasonCode} value={reasonCode}>
                        {reasonCode}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  {Object.entries(summary.item.reasonCounts).map(([reasonCode, count]) => (
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
                    {pageStart}-{pageEnd} / {total} arcs for the current filter.
                  </p>
                </div>
                <div className="grid grid-cols-[0.7fr_1fr_1fr_1.3fr_0.45fr_0.55fr_0.45fr] gap-3 border-b border-border bg-surface-sunken px-4 py-2 text-[11px] font-medium uppercase text-slate-500">
                  <span>Vehicle</span>
                  <span>From</span>
                  <span>To</span>
                  <span>Reason</span>
                  <span>Turn</span>
                  <span>Deadhead</span>
                  <span>Slack</span>
                </div>
                <VirtualizedList
                  items={arcs}
                  height={520}
                  itemHeight={56}
                  className="bg-white"
                  perfLabel="graph-arcs"
                  getKey={(arc) => `${arc.vehicle_type}:${arc.from_trip_id}:${arc.to_trip_id}`}
                  renderItem={(arc) => (
                    <div className="grid h-full grid-cols-[0.7fr_1fr_1fr_1.3fr_0.45fr_0.55fr_0.45fr] gap-3 border-b border-slate-100 px-4 py-2 text-xs">
                      <div className="font-mono">{arc.vehicle_type}</div>
                      <div className="truncate font-mono">{arc.from_trip_id}</div>
                      <div className="truncate font-mono">{arc.to_trip_id}</div>
                      <div>
                        <div className="font-mono text-slate-700">{arc.reason_code}</div>
                        <div className="truncate text-slate-500">{arc.reason}</div>
                      </div>
                      <div>{arc.turnaround_time_min}</div>
                      <div>{arc.deadhead_time_min}</div>
                      <div className={arc.feasible ? "font-semibold text-green-700" : "font-semibold text-red-600"}>
                        {arc.slack_min}
                      </div>
                    </div>
                  )}
                />
                <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-slate-500">
                  <span>
                    {pageStart}-{pageEnd} / {total}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setPageOffset((current) => Math.max(0, current - PAGE_SIZE))}
                      disabled={pageOffset === 0}
                      className="rounded border border-border px-3 py-1 disabled:opacity-40"
                    >
                      Prev
                    </button>
                    <button
                      type="button"
                      onClick={() => setPageOffset((current) => current + PAGE_SIZE)}
                      disabled={pageOffset + PAGE_SIZE >= total}
                      className="rounded border border-border px-3 py-1 disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </PageSection>
    </div>
    </TabWarmBoundary>
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
