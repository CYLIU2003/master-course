import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useRunSimulation, useSimulationResult } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function SimulationRunPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useSimulationResult(scenarioId!);
  const runMutation = useRunSimulation(scenarioId!);

  if (isLoading) return <LoadingBlock message={t("simulation.loading")} />;
  if (error && !error.message.includes("404")) return <ErrorBlock message={error.message} />;

  return (
    <PageSection
      title={t("simulation.title")}
      description={t("simulation.description")}
      actions={
        <button
          onClick={() => runMutation.mutate(undefined)}
          disabled={runMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {runMutation.isPending ? t("simulation.running") : t("simulation.run")}
        </button>
      }
    >
      {!result ? (
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
  );
}
