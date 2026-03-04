import { useParams } from "react-router-dom";
import { useRunSimulation, useSimulationResult } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function SimulationRunPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useSimulationResult(scenarioId!);
  const runMutation = useRunSimulation(scenarioId!);

  if (isLoading) return <LoadingBlock message="Loading simulation result..." />;
  if (error && !error.message.includes("404")) return <ErrorBlock message={error.message} />;

  return (
    <PageSection
      title="Simulation"
      description="Run energy simulation on generated duties"
      actions={
        <button
          onClick={() => runMutation.mutate(undefined)}
          disabled={runMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {runMutation.isPending ? "Running..." : "Run Simulation"}
        </button>
      }
    >
      {!result ? (
        <EmptyState title="No simulation results" description="Generate duties first, then run simulation" />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Total Energy</p>
              <p className="mt-1 text-lg font-bold text-slate-700">{result.total_energy_kwh.toFixed(1)} kWh</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Total Distance</p>
              <p className="mt-1 text-lg font-bold text-slate-700">{result.total_distance_km.toFixed(1)} km</p>
            </div>
            <div className="rounded-lg border border-border bg-surface-raised p-3 text-center">
              <p className="text-[10px] font-semibold uppercase text-slate-400">Violations</p>
              <p className={`mt-1 text-lg font-bold ${result.feasibility_violations.length > 0 ? "text-red-600" : "text-green-600"}`}>
                {result.feasibility_violations.length}
              </p>
            </div>
          </div>
          <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
            SOC trace chart placeholder
          </div>
        </div>
      )}
    </PageSection>
  );
}
