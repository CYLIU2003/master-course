import { useParams } from "react-router-dom";
import { useTimetable } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function TimetablePage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useTimetable(scenarioId!);

  if (isLoading) return <LoadingBlock message="Loading timetable..." />;
  if (error) return <ErrorBlock message={error.message} />;

  const rows = data?.items ?? [];

  return (
    <PageSection
      title="Timetable"
      description="Revenue trips defined by the operator schedule"
      actions={
        <div className="flex gap-2">
          <button className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
            Import CSV
          </button>
          <button className="rounded border border-border px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
            Export CSV
          </button>
          <button className="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700">
            Add Row
          </button>
        </div>
      }
    >
      {rows.length === 0 ? (
        <EmptyState title="No timetable rows" description="Import a CSV or add rows manually" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Route</th>
                <th className="px-3 py-2">Dir</th>
                <th className="px-3 py-2">#</th>
                <th className="px-3 py-2">Origin</th>
                <th className="px-3 py-2">Dest</th>
                <th className="px-3 py-2">Depart</th>
                <th className="px-3 py-2">Arrive</th>
                <th className="px-3 py-2">Dist (km)</th>
                <th className="px-3 py-2">Vehicle Types</th>
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
