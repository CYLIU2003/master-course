import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTurnaroundRules } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function RulesPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useTurnaroundRules(scenarioId!);

  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error.message} />;

  const rules = data?.items ?? [];

  return (
    <PageSection title={t("rules.title")} description={t("rules.description")}>
      {rules.length === 0 ? (
        <EmptyState title={t("rules.no_rules")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("rules.col_stop")}</th>
                <th className="px-3 py-2">{t("rules.col_turnaround")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.map((r, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-xs">{r.stop_id}</td>
                  <td className="px-3 py-2 font-mono text-xs">{r.turnaround_min}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageSection>
  );
}
