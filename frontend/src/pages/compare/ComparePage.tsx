import { Link } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCompareStore } from "@/stores/compare-store";
import { PageSection, EmptyState, LoadingBlock, ErrorBlock } from "@/features/common";
import { scenarioApi } from "@/api/scenario";
import { simulationApi } from "@/api/simulation";
import { optimizationApi } from "@/api/optimization";
import { formatCurrency } from "@/utils/format";
import { downloadCsvRows } from "@/utils/download";
import type { OptimizationResult, Scenario, SimulationResult } from "@/types";
import { exportAuditCsv, exportAuditJson, type AuditExportEnvelope } from "@/utils/audit-export";

type ComparedScenarioRow = {
  scenario: Scenario;
  simulation: SimulationResult | null;
  optimization: OptimizationResult | null;
};

type SortMetric =
  | "simulation_energy"
  | "simulation_violations"
  | "optimization_cost"
  | "optimization_objective"
  | "optimization_solve_time";

const KPI_METRICS = [
  {
    key: "simulation_energy",
    label: "Simulation energy",
    better: "lower" as const,
    getValue: (row: ComparedScenarioRow) => row.simulation?.total_energy_kwh ?? null,
    format: (value: number) => `${value.toFixed(1)} kWh`,
  },
  {
    key: "simulation_violations",
    label: "Simulation violations",
    better: "lower" as const,
    getValue: (row: ComparedScenarioRow) => row.simulation?.feasibility_violations.length ?? null,
    format: (value: number) => String(value),
  },
  {
    key: "optimization_cost",
    label: "Optimization total cost",
    better: "lower" as const,
    getValue: (row: ComparedScenarioRow) => row.optimization?.cost_breakdown.total_cost ?? null,
    format: (value: number) => formatCurrency(value),
  },
  {
    key: "optimization_objective",
    label: "Optimization objective",
    better: "lower" as const,
    getValue: (row: ComparedScenarioRow) => row.optimization?.objective_value ?? null,
    format: (value: number) => value.toFixed(2),
  },
  {
    key: "optimization_solve_time",
    label: "Optimization solve time",
    better: "lower" as const,
    getValue: (row: ComparedScenarioRow) => row.optimization?.solve_time_seconds ?? null,
    format: (value: number) => `${value.toFixed(1)}s`,
  },
] as const;

function buildKpiDiffExportRows(rows: ComparedScenarioRow[]) {
  if (rows.length === 0) return [];
  const baseline = rows[0];
  return KPI_METRICS.flatMap((metric) => {
    const baselineValue = metric.getValue(baseline);
    return rows.map((row, index) => {
      const value = metric.getValue(row);
      const diff = index === 0 || value == null || baselineValue == null ? null : value - baselineValue;
      const diffPct =
        index === 0 || value == null || baselineValue == null || baselineValue === 0
          ? null
          : (diff! / baselineValue) * 100;
      return {
        metric: metric.label,
        scenario_id: row.scenario.id,
        scenario_name: row.scenario.name,
        baseline_scenario_id: baseline.scenario.id,
        raw_value: value,
        formatted_value: value == null ? "-" : metric.format(value),
        diff_from_baseline: diff,
        diff_pct_from_baseline: diffPct == null ? null : Number(diffPct.toFixed(3)),
      };
    });
  });
}

async function safeSimulation(id: string): Promise<SimulationResult | null> {
  try {
    return await simulationApi.getResult(id);
  } catch (error) {
    if (error instanceof Error && error.message.includes("404")) {
      return null;
    }
    throw error;
  }
}

async function safeOptimization(id: string): Promise<OptimizationResult | null> {
  try {
    return await optimizationApi.getResult(id);
  } catch (error) {
    if (error instanceof Error && error.message.includes("404")) {
      return null;
    }
    throw error;
  }
}

export function ComparePage() {
  const { t } = useTranslation();
  const { selectedIds, clearSelection } = useCompareStore();
  const [sortMetric, setSortMetric] = useState<SortMetric>("optimization_cost");
  const [sortDirection, setSortDirection] = useState<"desc" | "asc">("desc");

  const queryResults = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["compare", id],
      queryFn: async () => ({
        scenario: await scenarioApi.get(id),
        simulation: await safeSimulation(id),
        optimization: await safeOptimization(id),
      }),
      enabled: selectedIds.length >= 2,
      staleTime: 60_000,
    })),
  });

  const isLoading = queryResults.some((query) => query.isLoading);
  const firstError = queryResults.find((query) => query.error)?.error;
  const rows = queryResults
    .map((query) => query.data)
    .filter(Boolean) as ComparedScenarioRow[];
  const sortedRows = useMemo(() => {
    if (rows.length <= 1) return rows;
    const baseline = rows[0];
    const metric = KPI_METRICS.find((item) => item.key === sortMetric) ?? KPI_METRICS[0];
    const baseValue = metric.getValue(baseline);
    const rest = [...rows.slice(1)].sort((left, right) => {
      const leftValue = metric.getValue(left);
      const rightValue = metric.getValue(right);
      const leftDelta = leftValue == null || baseValue == null ? Number.NEGATIVE_INFINITY : leftValue - baseValue;
      const rightDelta = rightValue == null || baseValue == null ? Number.NEGATIVE_INFINITY : rightValue - baseValue;
      const leftScore = Math.abs(leftDelta);
      const rightScore = Math.abs(rightDelta);
      return sortDirection === "desc" ? rightScore - leftScore : leftScore - rightScore;
    });
    return [baseline, ...rest];
  }, [rows, sortDirection, sortMetric]);
  const auditEnvelopes: AuditExportEnvelope[] = rows.flatMap(({ scenario, simulation, optimization }) => {
    const datasetFingerprint =
      scenario.feedContext?.datasetId ||
      [scenario.feedContext?.feedId, scenario.feedContext?.snapshotId].filter(Boolean).join(":") ||
      null;
    return [
      {
        scenarioId: scenario.id,
        scenarioName: scenario.name,
        auditType: "simulation",
        datasetFingerprint,
        snapshotId: scenario.feedContext?.snapshotId ?? null,
        sourceType: scenario.feedContext?.source ?? null,
        scope: simulation?.scope,
        highlights: simulation
          ? {
              total_energy_kwh: simulation.total_energy_kwh,
              total_distance_km: simulation.total_distance_km,
              violations: simulation.feasibility_violations.length,
            }
          : {},
        audit: (simulation?.audit as Record<string, unknown> | undefined) ?? null,
      },
      {
        scenarioId: scenario.id,
        scenarioName: scenario.name,
        auditType: "optimization",
        datasetFingerprint,
        snapshotId: scenario.feedContext?.snapshotId ?? null,
        sourceType: scenario.feedContext?.source ?? null,
        scope: optimization?.scope,
        highlights: optimization
          ? {
              mode: optimization.mode,
              total_cost: optimization.cost_breakdown.total_cost,
              objective_value: optimization.objective_value,
              solve_time_seconds: optimization.solve_time_seconds,
            }
          : {},
        audit: (optimization?.audit as Record<string, unknown> | undefined) ?? null,
      },
    ];
  });

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-4 flex items-center justify-between">
        <Link to="/scenarios" className="text-sm text-primary-600 hover:underline">
          {t("compare.back_to_scenarios")}
        </Link>
        {selectedIds.length > 0 && (
          <button
            onClick={clearSelection}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            {t("compare.clear_selection")}
          </button>
        )}
      </div>

      <PageSection
        title={t("compare.title")}
        description={t("compare.description")}
        actions={
          rows.length > 0 ? (
            <>
              <button
                onClick={() => exportAuditJson("scenario-compare-audits.json", auditEnvelopes)}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                Export JSON
              </button>
              <button
                onClick={() => exportAuditCsv("scenario-compare-audits.csv", auditEnvelopes)}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                Export CSV
              </button>
              <button
                onClick={() =>
                  downloadCsvRows(
                    "scenario-compare-kpi-diff.csv",
                    buildKpiDiffExportRows(sortedRows),
                  )
                }
                className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                Export KPI CSV
              </button>
              <select
                value={sortMetric}
                onChange={(event) => setSortMetric(event.target.value as SortMetric)}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-600"
              >
                {KPI_METRICS.map((metric) => (
                  <option key={metric.key} value={metric.key}>
                    sort: {metric.label}
                  </option>
                ))}
              </select>
              <select
                value={sortDirection}
                onChange={(event) => setSortDirection(event.target.value as "desc" | "asc")}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-600"
              >
                <option value="desc">largest diff first</option>
                <option value="asc">smallest diff first</option>
              </select>
            </>
          ) : null
        }
      >
        {selectedIds.length < 2 ? (
          <EmptyState title={t("compare.select_two")} description={t("compare.select_two_description")} />
        ) : isLoading ? (
          <LoadingBlock message="比較対象シナリオを読み込んでいます..." />
        ) : firstError ? (
          <ErrorBlock message={firstError instanceof Error ? firstError.message : String(firstError)} />
        ) : (
          <div className="space-y-4">
            <KpiDiffTable rows={sortedRows} />
            <div className="grid gap-4 xl:grid-cols-2">
              {sortedRows.map(({ scenario, simulation, optimization }) => (
                <div key={scenario.id} className="rounded-xl border border-border bg-surface-raised p-5">
                  <div className="mb-4 flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-lg font-semibold text-slate-800">{scenario.name}</h3>
                      <p className="text-xs text-slate-500">
                        {scenario.operatorId} / {scenario.status} / updated {new Date(scenario.updatedAt).toLocaleString("ja-JP")}
                      </p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600">
                      {scenario.feedContext?.datasetId ?? scenario.feedContext?.snapshotId ?? "no dataset"}
                    </span>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <MetricCard label="simulation energy" value={simulation ? `${simulation.total_energy_kwh.toFixed(1)} kWh` : "-"} />
                    <MetricCard label="simulation violations" value={simulation ? simulation.feasibility_violations.length : "-"} />
                    <MetricCard label="optimization status" value={optimization?.solver_status ?? "-"} />
                    <MetricCard label="optimization cost" value={optimization ? formatCurrency(optimization.cost_breakdown.total_cost) : "-"} />
                    <MetricCard label="optimization mode" value={optimization?.mode ?? "-"} />
                    <MetricCard label="scope" value={`${optimization?.scope?.depotId ?? simulation?.scope?.depotId ?? "-"} / ${optimization?.scope?.serviceId ?? simulation?.scope?.serviceId ?? "-"}`} />
                  </div>

                  <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    <AuditPanel
                      title="Simulation Audit"
                      audit={simulation?.audit as Record<string, unknown> | undefined}
                    />
                    <AuditPanel
                      title="Optimization Audit"
                      audit={optimization?.audit as Record<string, unknown> | undefined}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </PageSection>
    </div>
  );
}

function KpiDiffTable({ rows }: { rows: ComparedScenarioRow[] }) {
  if (rows.length === 0) return null;
  const baseline = rows[0];

  return (
    <div className="rounded-xl border border-border bg-surface-raised p-5">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-700">KPI diff table</h3>
        <p className="text-xs text-slate-400">最初の scenario を baseline として差分を表示します。</p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">metric</th>
              {rows.map((row, index) => (
                <th key={row.scenario.id} className="px-3 py-2">
                  <div>{row.scenario.name}</div>
                  <div className="text-[10px] font-normal normal-case text-slate-400">
                    {index === 0 ? "baseline" : `vs ${baseline.scenario.name}`}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {KPI_METRICS.map((metric) => {
              const baseValue = metric.getValue(baseline);
              return (
                <tr key={metric.key} className="border-b border-slate-100 align-top">
                  <td className="px-3 py-3 text-xs font-medium text-slate-600">{metric.label}</td>
                  {rows.map((row, index) => {
                    const value = metric.getValue(row);
                    return (
                      <td key={`${metric.key}-${row.scenario.id}`} className="px-3 py-3">
                        <div className="font-semibold text-slate-800">
                          {value == null ? "-" : metric.format(value)}
                        </div>
                        {index > 0 && value != null && baseValue != null && (
                          <DeltaBadge current={value} baseline={baseValue} better={metric.better} />
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DeltaBadge({ current, baseline, better }: { current: number; baseline: number; better: "lower" | "higher" }) {
  const diff = current - baseline;
  const pct = baseline !== 0 ? (diff / baseline) * 100 : null;
  const improved = better === "lower" ? diff <= 0 : diff >= 0;
  const tone = diff === 0 ? "bg-slate-100 text-slate-600" : improved ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700";
  return (
    <div className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${tone}`}>
      {`${diff >= 0 ? "+" : ""}${diff.toFixed(2)}${pct == null ? "" : ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`}`}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-800">{value}</div>
    </div>
  );
}

function AuditPanel({ title, audit }: { title: string; audit?: Record<string, unknown> }) {
  const inputCounts = audit?.input_counts as Record<string, unknown> | undefined;
  const outputCounts = audit?.output_counts as Record<string, unknown> | undefined;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
      <div className="mb-2 text-sm font-semibold text-slate-700">{title}</div>
      {!audit ? (
        <div className="text-slate-400">未実行</div>
      ) : (
        <div className="space-y-1">
          <div>depot: {String(audit.depot_id ?? "-")}</div>
          <div>service: {String(audit.service_id ?? "-")}</div>
          <div>case: {String(audit.case_type ?? "-")}</div>
          <div>inputs: {JSON.stringify(inputCounts ?? {})}</div>
          <div>outputs: {JSON.stringify(outputCounts ?? {})}</div>
        </div>
      )}
    </div>
  );
}
