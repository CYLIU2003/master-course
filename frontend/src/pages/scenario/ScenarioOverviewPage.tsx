import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScenario } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock } from "@/features/common";

export function ScenarioOverviewPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scenario, isLoading, error } = useScenario(scenarioId!);

  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error.message} />;
  if (!scenario) return null;

  return (
    <div>
      <PageSection title={scenario.name} description={scenario.description}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <InfoCard label={t("scenarios.mode")} value={scenario.mode} />
          <InfoCard label={t("scenarios.status")} value={scenario.status} />
          <InfoCard label={t("scenarios.created")} value={scenario.createdAt} />
          <InfoCard label={t("scenarios.updated")} value={scenario.updatedAt} />
        </div>
      </PageSection>

      <PageSection
        title={t("scenarios.pipeline_progress")}
        description={t("scenarios.pipeline_description")}
      >
        <div className="rounded-lg border border-border bg-surface-sunken p-4 text-center text-sm text-slate-400">
          {t("scenarios.pipeline_placeholder")}
        </div>
      </PageSection>
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-700 truncate">{value}</p>
    </div>
  );
}
