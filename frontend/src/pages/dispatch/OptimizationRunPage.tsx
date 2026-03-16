import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { useIsMutating } from "@tanstack/react-query";
import {
  useJob,
  useRunOptimization,
  useOptimizationResult,
  useOptimizationCapabilities,
  useScenarioRunReadiness,
  useDispatchScope,
  useScenario,
} from "@/hooks";
import { BackendJobPanel, PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";
import { formatCurrency } from "@/utils/format";
import { runKeys } from "@/hooks/use-run";

export function OptimizationRunPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { data: scope } = useDispatchScope(scenarioId!);
  const { data: scenario } = useScenario(scenarioId!);
  const scopeReady = Boolean(scope?.depotId);
  const dispatchScopePending = useIsMutating({ mutationKey: ["scenarios", scenarioId, "dispatch-scope", "mutation"] }) > 0;
  const { data: result, isLoading, error } = useOptimizationResult(scenarioId!);
  const { data: capabilities } = useOptimizationCapabilities(scenarioId!);
  const { canRun, reason } = useScenarioRunReadiness();
  const runMutation = useRunOptimization(scenarioId!);
  const { data: activeJob } = useJob(activeJobId);
  const runDisabled = runMutation.isPending || dispatchScopePending || !scopeReady || !canRun;

  useEffect(() => {
    if (activeJob?.status === "completed") {
      void queryClient.invalidateQueries({ queryKey: runKeys.optimization(scenarioId!) });
    }
  }, [activeJob?.status, queryClient, scenarioId]);

  if (isLoading) return <LoadingBlock message={t("optimization.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />
      <PageSection
        title={t("optimization.title")}
        description={t("optimization.description")}
        actions={
          <button
            onClick={async () => {
              const job = await runMutation.mutateAsync({
                mode: scenario?.scenarioOverlay?.solver_config.mode ?? "mode_B_resource_assignment",
                time_limit_seconds:
                  scenario?.scenarioOverlay?.solver_config.time_limit_seconds ?? 300,
                mip_gap: scenario?.scenarioOverlay?.solver_config.mip_gap ?? 0.01,
              });
              setActiveJobId(job.job_id);
            }}
            disabled={runDisabled}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {runMutation.isPending ? t("optimization.solving") : t("optimization.run")}
          </button>
        }
      >
        {!canRun && (
          <div className="mb-4 rounded-lg border border-rose-300 bg-rose-50 p-3 text-xs text-rose-900">
            <p className="font-semibold">Seed-only mode</p>
            <p className="mt-1">{reason ?? "Optimization is disabled until built artifacts are generated in data-prep."}</p>
          </div>
        )}
        <BackendJobPanel job={activeJob} className="mb-4" />
        {capabilities && (
          <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <p className="font-semibold">Operational boundary</p>
            <p className="mt-1">{capabilities.job_persistence.warning}</p>
            <p className="mt-1">Modes: {(capabilities.supported_modes ?? []).join(", ")}</p>
          </div>
        )}
        {!scopeReady ? (
          <EmptyState title="営業所を選択してください" description="Optimization 実行前に、対象営業所を 1 つ選択してください。" />
        ) : !result ? (
          <EmptyState title={t("optimization.no_results")} description={t("optimization.no_results_description")} />
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <div>mode: {result.mode ?? "-"}</div>
              <div>objective: {result.objective_mode ?? "-"}</div>
              <div>depot: {String(result.scope?.depotId ?? activeJob?.metadata?.depot_id ?? "-")}</div>
              <div>service: {String(result.scope?.serviceId ?? activeJob?.metadata?.service_id ?? "-")}</div>
            </div>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
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
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
                <p className="text-[10px] font-semibold uppercase text-slate-400">CO2</p>
                <p className="mt-1 text-sm font-bold text-slate-700">
                  {result.cost_breakdown.total_co2_kg?.toFixed(1) ?? "-"} kg
                </p>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
                <p className="text-[10px] font-semibold uppercase text-slate-400">Used vehicles</p>
                <p className="mt-1 text-sm font-bold text-slate-700">
                  {result.summary?.vehicle_count_used ?? "-"}
                </p>
              </div>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-border bg-white p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Cost breakdown
                </div>
                <div className="space-y-2 text-sm text-slate-700">
                  <div className="flex items-center justify-between">
                    <span>Energy</span>
                    <span>{formatCurrency(result.cost_breakdown.energy_cost)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Demand</span>
                    <span>{formatCurrency(result.cost_breakdown.peak_demand_cost)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Vehicle</span>
                    <span>{formatCurrency(result.cost_breakdown.vehicle_cost)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Driver</span>
                    <span>{formatCurrency(result.cost_breakdown.driver_cost)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Fuel</span>
                    <span>{formatCurrency(result.cost_breakdown.fuel_cost ?? 0)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>CO2 shadow cost</span>
                    <span>{formatCurrency(result.cost_breakdown.co2_cost ?? 0)}</span>
                  </div>
                </div>
              </div>
              <div className="rounded-lg border border-border bg-white p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Vehicle mix
                </div>
                <div className="space-y-2 text-sm text-slate-700">
                  {Object.entries(result.summary?.vehicle_count_by_type ?? {}).length === 0 ? (
                    <div>-</div>
                  ) : (
                    Object.entries(result.summary?.vehicle_count_by_type ?? {}).map(([vehicleType, count]) => (
                      <div key={vehicleType} className="flex items-center justify-between">
                        <span>{vehicleType}</span>
                        <span>{count}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </PageSection>
    </div>
  );
}
