import { useTranslation } from "react-i18next";
import { PageSection } from "@/features/common";

export function DispatchResultsPage() {
  const { t } = useTranslation();
  return (
    <PageSection title={t("dispatch_results.title")} description={t("dispatch_results.description")}>
      <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
        {t("dispatch_results.placeholder")}
      </div>
    </PageSection>
  );
}
