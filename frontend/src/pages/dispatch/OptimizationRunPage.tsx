import { useParams } from "react-router-dom";
import { useRunOptimization, useOptimizationResult } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatCurrency } from "@/utils/format";

export function OptimizationRunPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useOptimizationResult(scenarioId!);
  const runMutation = useRunOptimization(scenarioId!);

  if (isLoading) return <LoadingBlock message="Loading optimization result..." />;
  if (error && !error.message.includes("404")) return <ErrorBlock message={error.message} />;

  return (
    <PageSection
      title="Optimization"
      description="Run MILP / ALNS solver"
      actions={
        <button
          onClick={() =>
            runMutation.mutate({
              mode: "mode_B_resource_assignment",
              time_limit_seconds: 300,
            })
          }
          disabled={runMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {runMutation.isPending ? "Solving..." : "Run Optimization"}
        </button>
      }
    >
      {!result ? (
        <EmptyState title="No optimization results" description="Run simulation first, then optimize" />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Status</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.solver_status}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Objective</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.objective_value.toFixed(2)}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Solve Time</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.solve_time_seconds.toFixed(1)}s</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Total Cost</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{formatCurrency(result.cost_breakdown.total_cost)}</p>
            </div>
          </div>
        </div>
      )}
    </PageSection>
  );
}
