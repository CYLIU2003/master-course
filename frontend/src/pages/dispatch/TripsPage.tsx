import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTrips, useTripsSummary, useBuildTrips, useDispatchScope, useJob } from "@/hooks";
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
import { useRenderTrace } from "@/utils/perf/useRenderTrace";

const PAGE_SIZE = 120;

export function TripsPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  useRenderTrace("TripsPage");
  const [pageOffset, setPageOffset] = useState(0);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const { data: scope } = useDispatchScope(scenarioId!);
  const scopeReady = Boolean(scope?.depotId);
  const { data, isLoading, error } = useTrips(scenarioId!, {
    limit: PAGE_SIZE,
    offset: pageOffset,
    enabled: scopeReady,
  });
  const { data: summary } = useTripsSummary(scenarioId!, scopeReady);
  const buildMutation = useBuildTrips(scenarioId!);
  const { data: activeJob } = useJob(activeJobId);
  const trips = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageStart = total === 0 ? 0 : pageOffset + 1;
  const pageEnd = Math.min(pageOffset + trips.length, total);

  const handleBuild = async () => {
    const job = await buildMutation.mutateAsync({
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
        title={t("trips.title")}
        description={t("trips.description")}
        actions={
          <button
            onClick={handleBuild}
            disabled={buildMutation.isPending || !scopeReady}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {buildMutation.isPending ? t("trips.building") : t("trips.build")}
          </button>
        }
      >
        {!scopeReady ? (
          <EmptyState title="営業所を選択してください" description="Dispatch trip を生成する前に、対象営業所を 1 つ選択してください。" />
        ) : isLoading ? (
          <LoadingBlock message={t("trips.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : trips.length === 0 ? (
          <EmptyState title={t("trips.no_trips")} description={t("trips.no_trips_description")} />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <SummaryCard label="Trips" value={summary?.item.totalTrips ?? total} />
              <SummaryCard label="Routes" value={summary?.item.routeCount ?? 0} />
              <SummaryCard
                label="Service span"
                value={`${summary?.item.firstDeparture ?? "--:--"} - ${summary?.item.lastArrival ?? "--:--"}`}
              />
            </div>

            <div className="rounded-lg border border-border">
              <div className="grid grid-cols-[1.2fr_0.7fr_1fr_1fr_0.7fr_0.7fr_0.5fr] gap-3 border-b border-border bg-surface-sunken px-3 py-2 text-[11px] font-semibold uppercase text-slate-500">
                <span>{t("trips.col_trip_id")}</span>
                <span>{t("trips.col_route")}</span>
                <span>{t("trips.col_origin")}</span>
                <span>{t("trips.col_dest")}</span>
                <span>{t("trips.col_depart")}</span>
                <span>{t("trips.col_arrive")}</span>
                <span>{t("trips.col_dist")}</span>
              </div>
              <VirtualizedList
                items={trips}
                height={520}
                itemHeight={38}
                className="bg-white"
                perfLabel="trips-table"
                getKey={(trip) => trip.trip_id}
                renderItem={(trip) => (
                  <div className="grid h-full grid-cols-[1.2fr_0.7fr_1fr_1fr_0.7fr_0.7fr_0.5fr] gap-3 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                    <div className="truncate font-mono" title={trip.trip_id}>{trip.trip_id}</div>
                    <div className="truncate">{trip.route_id}</div>
                    <div className="truncate">{trip.origin}</div>
                    <div className="truncate">{trip.destination}</div>
                    <div className="font-mono">{trip.departure}</div>
                    <div className="font-mono">{trip.arrival}</div>
                    <div>{trip.distance_km}</div>
                  </div>
                )}
              />
            </div>

            <div className="flex items-center justify-between text-xs text-slate-500">
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
