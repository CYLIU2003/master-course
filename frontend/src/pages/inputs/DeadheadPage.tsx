import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDeadheadRules } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function DeadheadPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useDeadheadRules(scenarioId!);

  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error.message} />;

  const rules = data?.items ?? [];

  return (
    <PageSection title={t("deadhead.title")} description={t("deadhead.description")}>
      {rules.length === 0 ? (
        <EmptyState title={t("deadhead.no_rules")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("deadhead.col_origin")}</th>
                <th className="px-3 py-2">{t("deadhead.col_destination")}</th>
                <th className="px-3 py-2">{t("deadhead.col_time")}</th>
                <th className="px-3 py-2">{t("deadhead.col_dist")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.map((r, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-xs">{r.origin}</td>
                  <td className="px-3 py-2 text-xs">{r.destination}</td>
                  <td className="px-3 py-2 font-mono text-xs">{r.time_min}</td>
                  <td className="px-3 py-2 text-xs">{r.distance_km}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageSection>
  );
}
