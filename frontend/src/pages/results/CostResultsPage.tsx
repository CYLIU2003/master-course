import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useOptimizationResult } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatCurrency } from "@/utils/format";

export function CostResultsPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useOptimizationResult(scenarioId!);

  if (isLoading) {
    return <LoadingBlock message={t("cost_results.description")} />;
  }
  if (error && !error.message.includes("404")) {
    return <ErrorBlock message={error.message} />;
  }
  if (!result) {
    return (
      <PageSection title={t("cost_results.title")} description={t("cost_results.description")}>
        <EmptyState
          title={t("cost_results.placeholder")}
          description="Optimization を実行すると cost breakdown が表示されます。"
        />
      </PageSection>
    );
  }

  const entries = [
    ["Energy", result.cost_breakdown.energy_cost],
    ["Peak demand", result.cost_breakdown.peak_demand_cost],
    ["Vehicle", result.cost_breakdown.vehicle_cost],
    ["Deadhead", result.cost_breakdown.deadhead_cost],
    ["Total", result.cost_breakdown.total_cost],
  ];

  return (
    <PageSection title={t("cost_results.title")} description={t("cost_results.description")}>
      <div className="grid gap-3 md:grid-cols-4">
        <StatCard label="Solver" value={result.solver_status} />
        <StatCard label="Objective" value={result.objective_value.toFixed(2)} />
        <StatCard label="Solve time" value={`${result.solve_time_seconds.toFixed(1)}s`} />
        <StatCard label="Total cost" value={formatCurrency(result.cost_breakdown.total_cost)} tone="ok" />
      </div>
      <div className="mt-4 rounded-lg border border-border bg-white">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold text-slate-700">
          Cost breakdown
        </div>
        <div className="divide-y divide-border">
          {entries.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between px-4 py-3 text-sm">
              <span className="text-slate-600">{label}</span>
              <span className="font-semibold text-slate-800">{formatCurrency(Number(value))}</span>
            </div>
          ))}
        </div>
      </div>
    </PageSection>
  );
}

function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number | string;
  tone?: "default" | "ok";
}) {
  const toneClass = tone === "ok" ? "text-emerald-600" : "text-slate-800";
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
