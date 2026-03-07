import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useTrips, useBuildTrips, useDispatchScope } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { DispatchScopePanel } from "@/features/planning";

export function TripsPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scope } = useDispatchScope(scenarioId!);
  const { data, isLoading, error } = useTrips(scenarioId!);
  const buildMutation = useBuildTrips(scenarioId!);

  const trips = data?.items ?? [];

  const handleBuild = () => {
    buildMutation.mutate({
      depot_id: scope?.depotId ?? undefined,
      service_id: scope?.serviceId ?? undefined,
    });
  };

  return (
    <div className="space-y-6">
      <DispatchScopePanel scenarioId={scenarioId!} />

      <PageSection
        title={t("trips.title")}
        description={t("trips.description")}
        actions={
          <button
            onClick={handleBuild}
            disabled={buildMutation.isPending}
            className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {buildMutation.isPending ? t("trips.building") : t("trips.build")}
          </button>
        }
      >
        {isLoading ? (
          <LoadingBlock message={t("trips.loading")} />
        ) : error ? (
          <ErrorBlock message={error.message} />
        ) : trips.length === 0 ? (
          <EmptyState title={t("trips.no_trips")} description={t("trips.no_trips_description")} />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">{t("trips.col_trip_id")}</th>
                  <th className="px-3 py-2">{t("trips.col_route")}</th>
                  <th className="px-3 py-2">{t("trips.col_origin")}</th>
                  <th className="px-3 py-2">{t("trips.col_dest")}</th>
                  <th className="px-3 py-2">{t("trips.col_depart")}</th>
                  <th className="px-3 py-2">{t("trips.col_arrive")}</th>
                  <th className="px-3 py-2">{t("trips.col_dist")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {trips.map((t_) => (
                  <tr key={t_.trip_id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-xs">{t_.trip_id}</td>
                    <td className="px-3 py-2 text-xs">{t_.route_id}</td>
                    <td className="px-3 py-2 text-xs">{t_.origin}</td>
                    <td className="px-3 py-2 text-xs">{t_.destination}</td>
                    <td className="px-3 py-2 font-mono text-xs">{t_.departure}</td>
                    <td className="px-3 py-2 font-mono text-xs">{t_.arrival}</td>
                    <td className="px-3 py-2 text-xs">{t_.distance_km}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageSection>
    </div>
  );
}
