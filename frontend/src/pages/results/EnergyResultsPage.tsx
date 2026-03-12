import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useSimulationResult } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState, VirtualizedList } from "@/features/common";
import { exportAuditCsv, exportAuditJson } from "@/utils/audit-export";

export function EnergyResultsPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: result, isLoading, error } = useSimulationResult(scenarioId!);

  if (isLoading) {
    return <LoadingBlock message={t("energy_results.description")} />;
  }
  if (error && !error.message.includes("404")) {
    return <ErrorBlock message={error.message} />;
  }
  if (!result) {
    return (
      <PageSection title={t("energy_results.title")} description={t("energy_results.description")}>
        <EmptyState
          title={t("energy_results.placeholder")}
          description="Simulation を実行すると energy summary が表示されます。"
        />
      </PageSection>
    );
  }

  const records = result.energy_consumption ?? [];
  const audit = result.audit as Record<string, unknown> | undefined;
  const auditInputCounts = audit?.["input_counts"] as Record<string, unknown> | undefined;
  const auditOutputCounts = audit?.["output_counts"] as Record<string, unknown> | undefined;
  const datasetFingerprint =
    result.feed_context?.datasetId ||
    [result.feed_context?.feedId, result.feed_context?.snapshotId].filter(Boolean).join(":") ||
    null;

  return (
    <PageSection
      title={t("energy_results.title")}
      description={t("energy_results.description")}
      actions={
        result.audit ? (
          <>
            <button
              onClick={() =>
                exportAuditJson(`simulation-audit-${scenarioId}.json`, [
                  {
                    scenarioId: scenarioId!,
                    auditType: "simulation",
                    datasetFingerprint,
                    snapshotId: result.feed_context?.snapshotId ?? null,
                    sourceType: result.feed_context?.source ?? null,
                    scope: result.scope,
                    highlights: {
                      total_energy_kwh: result.total_energy_kwh,
                      total_distance_km: result.total_distance_km,
                      violations: result.feasibility_violations.length,
                    },
                    audit: result.audit,
                  },
                ])
              }
              className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              Export audit JSON
            </button>
            <button
              onClick={() =>
                exportAuditCsv(`simulation-audit-${scenarioId}.csv`, [
                  {
                    scenarioId: scenarioId!,
                    auditType: "simulation",
                    datasetFingerprint,
                    snapshotId: result.feed_context?.snapshotId ?? null,
                    sourceType: result.feed_context?.source ?? null,
                    scope: result.scope,
                    highlights: {
                      total_energy_kwh: result.total_energy_kwh,
                      total_distance_km: result.total_distance_km,
                      violations: result.feasibility_violations.length,
                    },
                    audit: result.audit,
                  },
                ])
              }
              className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              Export audit CSV
            </button>
          </>
        ) : null
      }
    >
      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="Total energy" value={`${result.total_energy_kwh.toFixed(1)} kWh`} />
        <StatCard label="Total distance" value={`${result.total_distance_km.toFixed(1)} km`} />
        <StatCard
          label="Violations"
          value={result.feasibility_violations.length}
          tone={result.feasibility_violations.length > 0 ? "danger" : "ok"}
        />
      </div>
      {result.audit && (
        <div className="mt-4 rounded-lg border border-border bg-surface-raised p-4 text-xs text-slate-600">
          <div className="mb-2 text-sm font-semibold text-slate-700">Simulation Audit</div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <AuditItem label="depot" value={result.scope?.depotId ?? audit?.["depot_id"]} />
            <AuditItem label="service" value={result.scope?.serviceId ?? audit?.["service_id"]} />
            <AuditItem label="tasks" value={auditInputCounts?.["tasks"]} />
            <AuditItem label="violations" value={auditOutputCounts?.["feasibility_violations"]} />
          </div>
        </div>
      )}
      <div className="mt-4 rounded-lg border border-border bg-white">
        <div className="grid grid-cols-[1fr_1fr_0.7fr_0.6fr_0.6fr] gap-3 border-b border-border bg-surface-sunken px-4 py-2 text-[11px] font-semibold uppercase text-slate-500">
          <span>Duty</span>
          <span>Trip</span>
          <span>Energy</span>
          <span>SOC start</span>
          <span>SOC end</span>
        </div>
        <VirtualizedList
          items={records}
          height={520}
          itemHeight={40}
          className="bg-white"
          perfLabel="energy-records"
          getKey={(item) => `${item.duty_id}:${item.trip_id}`}
          renderItem={(item) => (
            <div className="grid h-full grid-cols-[1fr_1fr_0.7fr_0.6fr_0.6fr] gap-3 border-b border-slate-100 px-4 py-2 text-xs">
              <div className="truncate font-mono">{item.duty_id}</div>
              <div className="truncate font-mono">{item.trip_id}</div>
              <div>{item.energy_kwh.toFixed(2)} kWh</div>
              <div>{Math.round(item.soc_start * 100)}%</div>
              <div>{Math.round(item.soc_end * 100)}%</div>
            </div>
          )}
        />
      </div>
    </PageSection>
  );
}

function AuditItem({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-800">{String(value ?? "-")}</div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number | string;
  tone?: "default" | "ok" | "danger";
}) {
  const toneClass =
    tone === "danger" ? "text-rose-600" : tone === "ok" ? "text-emerald-600" : "text-slate-800";
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
