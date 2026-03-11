import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDuties, useDutiesSummary, useGenerateDuties, useDutyValidation, useDispatchScope, useJob } from "@/hooks";
import {
  BackendJobPanel,
  PageSection,
  LoadingBlock,
  ErrorBlock,
  EmptyState,
  TabWarmBoundary,
  VirtualizedList,
} from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";
import { formatDuration } from "@/utils/time";
import { useRenderTrace } from "@/utils/perf/useRenderTrace";

const PAGE_SIZE = 60;

export function DutiesPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  useRenderTrace("DutiesPage");
  const [pageOffset, setPageOffset] = useState(0);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const { data: scope } = useDispatchScope(scenarioId!);
  const scopeReady = Boolean(scope?.depotId);
  const { data, isLoading, error } = useDuties(scenarioId!, {
    limit: PAGE_SIZE,
    offset: pageOffset,
    enabled: scopeReady,
  });
  const { data: summary } = useDutiesSummary(scenarioId!, scopeReady);
  const { data: validation } = useDutyValidation(scenarioId!);
  const generateMutation = useGenerateDuties(scenarioId!);
  const { data: activeJob } = useJob(activeJobId);
  const duties = data?.items ?? [];
  const total = data?.total ?? 0;
  const validationMap = useMemo(
    () => new Map((validation?.items ?? []).map((v) => [v.duty_id, v])),
    [validation?.items],
  );
  const pageStart = total === 0 ? 0 : pageOffset + 1;
  const pageEnd = Math.min(pageOffset + duties.length, total);

  const handleGenerate = async () => {
    const job = await generateMutation.mutateAsync({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
    setActiveJobId(job.job_id);
  };

  return (
    <TabWarmBoundary tab="dispatch" title="Dispatch tab を準備しています">
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />
      <BackendJobPanel job={activeJob} />

      <PageSection
        title={t("duties.title")}
        description={t("duties.description")}
        actions={
          <button
            onClick={handleGenerate}
            disabled={generateMutation.isPending || !scopeReady}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {generateMutation.isPending ? t("duties.generating") : t("duties.generate")}
          </button>
        }
      >
        {!scopeReady ? (
          <EmptyState title="営業所を選択してください" description="車両 duty を生成する前に、対象営業所を 1 つ選択してください。" />
        ) : isLoading ? (
          <LoadingBlock message={t("duties.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : duties.length === 0 ? (
          <EmptyState title={t("duties.no_duties")} description={t("duties.no_duties_description")} />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <SummaryCard label="Duties" value={summary?.item.totalDuties ?? total} />
              <SummaryCard label="Legs" value={summary?.item.totalLegs ?? 0} />
              <SummaryCard label="Avg legs" value={summary?.item.averageLegsPerDuty ?? 0} />
              <SummaryCard
                label="Distance"
                value={`${(summary?.item.totalDistanceKm ?? 0).toFixed(1)} km`}
              />
            </div>
            <div className="rounded-lg border border-border bg-white">
              <VirtualizedList
                items={duties}
                height={560}
                itemHeight={96}
                className="bg-white"
                perfLabel="duties-list"
                getKey={(duty) => duty.duty_id}
                renderItem={(duty) => {
                  const v = validationMap.get(duty.duty_id);
                  return (
                    <div
                      className={`mx-3 my-2 rounded-lg border p-4 ${
                        v && !v.valid ? "border-red-300 bg-red-50" : "border-border bg-surface-raised"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <span className="font-mono text-xs font-semibold">{duty.duty_id}</span>
                          <span className="ml-2 text-xs text-slate-400">{duty.vehicle_type}</span>
                        </div>
                        <div className="flex flex-wrap gap-4 text-xs text-slate-500">
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
                }}
              />
              <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-slate-500">
                <span>
                  {pageStart}-{pageEnd} / {total}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setPageOffset((current) => Math.max(0, current - PAGE_SIZE))}
                    disabled={pageOffset === 0}
                    className="rounded border border-border px-3 py-1 disabled:opacity-40"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    onClick={() => setPageOffset((current) => current + PAGE_SIZE)}
                    disabled={pageOffset + PAGE_SIZE >= total}
                    className="rounded border border-border px-3 py-1 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </PageSection>
    </div>
    </TabWarmBoundary>
  );
}

function SummaryCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-800">{value}</div>
    </div>
  );
}
