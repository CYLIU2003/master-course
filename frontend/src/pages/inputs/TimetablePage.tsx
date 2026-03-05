import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTimetable } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function TimetablePage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useTimetable(scenarioId!);

  if (isLoading) return <LoadingBlock message={t("timetable.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const rows = data?.items ?? [];

  return (
    <PageSection
      title={t("timetable.title")}
      description={t("timetable.description")}
      actions={
        <div className="flex gap-2">
          <button className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
            {t("timetable.import_csv")}
          </button>
          <button className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
            {t("timetable.export_csv")}
          </button>
          <button className="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700">
            {t("timetable.add_row")}
          </button>
        </div>
      }
    >
      {rows.length === 0 ? (
        <EmptyState title={t("timetable.no_rows")} description={t("timetable.no_rows_description")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("timetable.col_route")}</th>
                <th className="px-3 py-2">{t("timetable.col_dir")}</th>
                <th className="px-3 py-2">{t("timetable.col_index")}</th>
                <th className="px-3 py-2">{t("timetable.col_origin")}</th>
                <th className="px-3 py-2">{t("timetable.col_dest")}</th>
                <th className="px-3 py-2">{t("timetable.col_depart")}</th>
                <th className="px-3 py-2">{t("timetable.col_arrive")}</th>
                <th className="px-3 py-2">{t("timetable.col_dist")}</th>
                <th className="px-3 py-2">{t("timetable.col_vehicle_types")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{row.route_id}</td>
                  <td className="px-3 py-2 text-xs">{row.direction}</td>
                  <td className="px-3 py-2 text-xs">{row.trip_index}</td>
                  <td className="px-3 py-2 text-xs">{row.origin}</td>
                  <td className="px-3 py-2 text-xs">{row.destination}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.departure}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.arrival}</td>
                  <td className="px-3 py-2 text-xs">{row.distance_km}</td>
                  <td className="px-3 py-2 text-xs">{row.allowed_vehicle_types.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageSection>
  );
}
