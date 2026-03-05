import { useTranslation } from "react-i18next";
import { PageSection } from "@/features/common";

export function CostResultsPage() {
  const { t } = useTranslation();
  return (
    <PageSection title={t("cost_results.title")} description={t("cost_results.description")}>
      <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
        {t("cost_results.placeholder")}
      </div>
    </PageSection>
  );
}
