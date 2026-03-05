import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useCompareStore } from "@/stores/compare-store";
import { PageSection, EmptyState } from "@/features/common";

export function ComparePage() {
  const { t } = useTranslation();
  const { selectedIds, clearSelection } = useCompareStore();

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
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
      >
        {selectedIds.length < 2 ? (
          <EmptyState
            title={t("compare.select_two")}
            description={t("compare.select_two_description")}
          />
        ) : (
          <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
            Comparison table placeholder for: {selectedIds.join(", ")}
          </div>
        )}
      </PageSection>
    </div>
  );
}
