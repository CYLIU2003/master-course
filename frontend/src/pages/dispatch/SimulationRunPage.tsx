import { useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { useIsMutating } from "@tanstack/react-query";
import {
  useJob,
  useRunSimulation,
  useSimulationResult,
  useSimulationCapabilities,
  useDispatchScope,
} from "@/hooks";
import { BackendJobPanel, PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";
import { runKeys } from "@/hooks/use-run";

export function SimulationRunPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { data: scope } = useDispatchScope(scenarioId!);
  const scopeReady = Boolean(scope?.depotId);
  const dispatchScopePending = useIsMutating({ mutationKey: ["scenarios", scenarioId, "dispatch-scope", "mutation"] }) > 0;
  const { data: result, isLoading, error } = useSimulationResult(scenarioId!);
  const { data: capabilities } = useSimulationCapabilities(scenarioId!);
  const runMutation = useRunSimulation(scenarioId!);
  const { data: activeJob } = useJob(activeJobId);

  useEffect(() => {
    if (activeJob?.status === "completed") {
      void queryClient.invalidateQueries({ queryKey: runKeys.simulation(scenarioId!) });
    }
  }, [activeJob?.status, queryClient, scenarioId]);

  const handleRun = async () => {
    const job = await runMutation.mutateAsync({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
    setActiveJobId(job.job_id);
  };

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />
      <BackendJobPanel job={activeJob} />

      <PageSection
        title={t("simulation.title")}
        description={t("simulation.description")}
        actions={
          <button
            onClick={handleRun}
            disabled={runMutation.isPending || dispatchScopePending || !scopeReady}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {runMutation.isPending ? t("simulation.running") : t("simulation.run")}
          </button>
        }
      >
        {capabilities && (
          <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <p className="font-semibold">Operational boundary</p>
            <p className="mt-1">{capabilities.job_persistence.warning}</p>
            <p className="mt-1">Sources: {(capabilities.supported_sources ?? []).join(", ")}</p>
          </div>
        )}
        {!scopeReady ? (
          <EmptyState title="営業所を選択してください" description="Simulation 実行前に、対象営業所を 1 つ選択してください。" />
        ) : isLoading ? (
          <LoadingBlock message={t("simulation.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : !result ? (
          <EmptyState title={t("simulation.no_results")} description={t("simulation.no_results_description")} />
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <div>source: {result.source}</div>
              <div>depot: {result.scope?.depotId ?? "-"}</div>
              <div>service: {result.scope?.serviceId ?? "-"}</div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
                <p className="text-[10px] font-semibold uppercase text-slate-400">{t("simulation.total_energy")}</p>
                <p className="mt-1 text-lg font-bold text-slate-700">{result.total_energy_kwh.toFixed(1)} kWh</p>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
                <p className="text-[10px] font-semibold uppercase text-slate-400">{t("simulation.total_distance")}</p>
                <p className="mt-1 text-lg font-bold text-slate-700">{result.total_distance_km.toFixed(1)} km</p>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
                <p className="text-[10px] font-semibold uppercase text-slate-400">{t("simulation.violations")}</p>
                <p className={`mt-1 text-lg font-bold ${result.feasibility_violations.length > 0 ? "text-red-600" : "text-green-600"}`}>
                  {result.feasibility_violations.length}
                </p>
              </div>
            </div>
            <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
              {t("simulation.soc_placeholder")}
            </div>
          </div>
        )}
      </PageSection>
    </div>
  );
}
