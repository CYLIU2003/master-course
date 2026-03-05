import { useTranslation } from "react-i18next";
import { PageSection } from "@/features/common";

export function PrecheckPage() {
  const { t } = useTranslation();
  return (
    <PageSection title={t("precheck.title")} description={t("precheck.description")}>
      <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
        {t("precheck.placeholder")}
      </div>
    </PageSection>
  );
}
