import { useParams } from "react-router-dom";
import { useGraph, useBuildGraph } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function GraphPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: graph, isLoading, error } = useGraph(scenarioId!);
  const buildMutation = useBuildGraph(scenarioId!);

  if (isLoading) return <LoadingBlock message="Loading graph..." />;
  if (error) return <ErrorBlock message={error.message} />;

  return (
    <PageSection
      title="Connection Graph"
      description="Feasible trip-to-trip connections"
      actions={
        <button
          onClick={() => buildMutation.mutate(undefined)}
          disabled={buildMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {buildMutation.isPending ? "Building..." : "Build Graph"}
        </button>
      }
    >
      {!graph ? (
        <EmptyState title="No graph built yet" description="Click 'Build Graph' to evaluate feasibility" />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-4">
            <StatCard label="Total Arcs" value={graph.total_arcs} />
            <StatCard label="Feasible" value={graph.feasible_arcs} color="green" />
            <StatCard label="Infeasible" value={graph.infeasible_arcs} color="red" />
          </div>
          <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
            Graph visualization placeholder (React Flow / Cytoscape)
          </div>
        </>
      )}
    </PageSection>
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
