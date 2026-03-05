import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PageSection, EmptyState } from "@/features/common";

export function SimulationEnvironmentPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();

  if (!scenarioId) return null;

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("simulation_env.title")}
        </h1>
        <p className="text-sm text-slate-500">
          {t("simulation_env.description")}
        </p>
      </div>

      {/* Period & dates */}
      <PageSection title={t("simulation_env.period_title")} description={t("simulation_env.period_description")}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label={t("simulation_env.start_date")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.end_date")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.service_date")} value={t("common.not_configured")} />
        </div>
      </PageSection>

      {/* Electricity pricing */}
      <PageSection title={t("simulation_env.pricing_title")} description={t("simulation_env.pricing_description")}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label={t("simulation_env.flat_price")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.contract_demand")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.demand_penalty_mode")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.demand_charge")} value={t("common.not_configured")} />
        </div>
        <div className="mt-4">
          <EmptyState
            title={t("simulation_env.no_tou")}
            description={t("simulation_env.no_tou_description")}
          />
        </div>
      </PageSection>

      {/* Energy sources */}
      <PageSection title={t("simulation_env.energy_sources_title")} description={t("simulation_env.energy_sources_description")}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label={t("simulation_env.pv_enabled")} value={t("common.no")} />
          <FieldCard label={t("simulation_env.pv_scale")} value="1.0" />
          <FieldCard label={t("simulation_env.diesel_price")} value={t("common.not_configured")} />
        </div>
      </PageSection>

      {/* Solver settings */}
      <PageSection title={t("simulation_env.solver_title")} description={t("simulation_env.solver_description")}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label={t("simulation_env.initial_soc")} value="1.0" />
          <FieldCard label={t("simulation_env.random_seed")} value="None" />
          <FieldCard label={t("simulation_env.opt_mode")} value={t("common.not_configured")} />
          <FieldCard label={t("simulation_env.time_limit")} value="300" />
          <FieldCard label={t("simulation_env.mip_gap")} value="0.01" />
        </div>
      </PageSection>
    </div>
  );
}

// ── Helper component for read-only field display ──────────────

function FieldCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-700">{value}</p>
    </div>
  );
}
