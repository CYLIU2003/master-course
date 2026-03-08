import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useRunOptimization,
  useOptimizationResult,
  useOptimizationCapabilities,
} from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatCurrency } from "@/utils/format";

export function OptimizationRunPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useOptimizationResult(scenarioId!);
  const { data: capabilities } = useOptimizationCapabilities(scenarioId!);
  const runMutation = useRunOptimization(scenarioId!);

  if (isLoading) return <LoadingBlock message={t("optimization.loading")} />;
  if (error && !error.message.includes("404")) return <ErrorBlock message={error.message} />;

  return (
    <PageSection
      title={t("optimization.title")}
      description={t("optimization.description")}
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
          {runMutation.isPending ? t("optimization.solving") : t("optimization.run")}
        </button>
      }
    >
      {capabilities && (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="font-semibold">Operational boundary</p>
          <p className="mt-1">{capabilities.job_persistence.warning}</p>
          <p className="mt-1">Modes: {(capabilities.supported_modes ?? []).join(", ")}</p>
        </div>
      )}
      {!result ? (
        <EmptyState title={t("optimization.no_results")} description={t("optimization.no_results_description")} />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">{t("optimization.status")}</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.solver_status}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">{t("optimization.objective")}</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.objective_value.toFixed(2)}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">{t("optimization.solve_time")}</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{result.solve_time_seconds.toFixed(1)}s</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">{t("optimization.total_cost")}</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{formatCurrency(result.cost_breakdown.total_cost)}</p>
            </div>
          </div>
        </div>
      )}
    </PageSection>
  );
}
