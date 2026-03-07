import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useGraph, useBuildGraph, useDispatchScope } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";

export function GraphPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scope } = useDispatchScope(scenarioId!);
  const { data: graph, isLoading, error } = useGraph(scenarioId!);
  const buildMutation = useBuildGraph(scenarioId!);

  const handleBuild = () => {
    buildMutation.mutate({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
  };

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
            <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
              {t("graph.viz_placeholder")}
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
