import { useTranslation } from "react-i18next";
import { PageSection } from "@/features/common";

export function EnergyResultsPage() {
  const { t } = useTranslation();
  return (
    <PageSection title={t("energy_results.title")} description={t("energy_results.description")}>
      <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
        {t("energy_results.placeholder")}
      </div>
    </PageSection>
  );
}
