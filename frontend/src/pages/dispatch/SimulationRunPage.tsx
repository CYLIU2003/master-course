import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  useRunSimulation,
  useSimulationResult,
  useSimulationCapabilities,
  useDispatchScope,
} from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";

export function SimulationRunPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scope } = useDispatchScope(scenarioId!);
  const { data: result, isLoading, error } = useSimulationResult(scenarioId!);
  const { data: capabilities } = useSimulationCapabilities(scenarioId!);
  const runMutation = useRunSimulation(scenarioId!);

  const handleRun = () => {
    runMutation.mutate({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
  };

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />

      <PageSection
        title={t("simulation.title")}
        description={t("simulation.description")}
        actions={
          <button
            onClick={handleRun}
            disabled={runMutation.isPending}
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
        {isLoading ? (
          <LoadingBlock message={t("simulation.loading")} />
        ) : error && !error.message.includes("404") ? (
          <ErrorBlock message={error.message} />
        ) : !result ? (
          <EmptyState title={t("simulation.no_results")} description={t("simulation.no_results_description")} />
        ) : (
          <div className="space-y-4">
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
