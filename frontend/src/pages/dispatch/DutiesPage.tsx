import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDuties, useGenerateDuties, useDutyValidation } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatDuration } from "@/utils/time";

export function DutiesPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useDuties(scenarioId!);
  const { data: validation } = useDutyValidation(scenarioId!);
  const generateMutation = useGenerateDuties(scenarioId!);

  if (isLoading) return <LoadingBlock message={t("duties.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const duties = data?.items ?? [];
  const validationMap = new Map(
    (validation?.items ?? []).map((v) => [v.duty_id, v]),
  );

  return (
    <PageSection
      title={t("duties.title")}
      description={t("duties.description")}
      actions={
        <button
          onClick={() => generateMutation.mutate(undefined)}
          disabled={generateMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {generateMutation.isPending ? t("duties.generating") : t("duties.generate")}
        </button>
      }
    >
      {duties.length === 0 ? (
        <EmptyState title={t("duties.no_duties")} description={t("duties.no_duties_description")} />
      ) : (
        <div className="space-y-3">
          {duties.map((duty) => {
            const v = validationMap.get(duty.duty_id);
            return (
              <div
                key={duty.duty_id}
                className={`rounded-lg border p-4 ${
                  v && !v.valid ? "border-red-300 bg-red-50" : "border-border bg-surface-raised"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-mono text-xs font-semibold">{duty.duty_id}</span>
                    <span className="ml-2 text-xs text-slate-400">{duty.vehicle_type}</span>
                  </div>
                  <div className="flex gap-4 text-xs text-slate-500">
                    <span>{duty.legs.length}{t("duties.trips_suffix")}</span>
                    <span>{duty.start_time} - {duty.end_time}</span>
                    <span>{formatDuration(duty.total_service_time_min)}</span>
                    <span>{duty.total_distance_km.toFixed(1)} km</span>
                  </div>
                </div>
                {v && !v.valid && (
                  <ul className="mt-2 list-inside list-disc text-xs text-red-600">
                    {v.errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </PageSection>
  );
}
