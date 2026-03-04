import { useParams } from "react-router-dom";
import { useTrips, useBuildTrips } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function TripsPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useTrips(scenarioId!);
  const buildMutation = useBuildTrips(scenarioId!);

  if (isLoading) return <LoadingBlock message="Loading trips..." />;
  if (error) return <ErrorBlock message={error.message} />;

  const trips = data?.items ?? [];

  return (
    <PageSection
      title="Trips"
      description="Generated revenue trips from the timetable"
      actions={
        <button
          onClick={() => buildMutation.mutate(undefined)}
          disabled={buildMutation.isPending}
          className="rounded bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {buildMutation.isPending ? "Building..." : "Build Trips"}
        </button>
      }
    >
      {trips.length === 0 ? (
        <EmptyState title="No trips built yet" description="Click 'Build Trips' to generate from timetable" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Trip ID</th>
                <th className="px-3 py-2">Route</th>
                <th className="px-3 py-2">Origin</th>
                <th className="px-3 py-2">Dest</th>
                <th className="px-3 py-2">Depart</th>
                <th className="px-3 py-2">Arrive</th>
                <th className="px-3 py-2">Dist (km)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {trips.map((t) => (
                <tr key={t.trip_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{t.trip_id}</td>
                  <td className="px-3 py-2 text-xs">{t.route_id}</td>
                  <td className="px-3 py-2 text-xs">{t.origin}</td>
                  <td className="px-3 py-2 text-xs">{t.destination}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.departure}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.arrival}</td>
                  <td className="px-3 py-2 text-xs">{t.distance_km}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageSection>
  );
}
