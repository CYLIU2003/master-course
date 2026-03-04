import { useParams } from "react-router-dom";
import { useDeadheadRules } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function DeadheadPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useDeadheadRules(scenarioId!);

  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error.message} />;

  const rules = data?.items ?? [];

  return (
    <PageSection title="Deadhead Rules" description="Non-revenue travel times and distances between stops">
      {rules.length === 0 ? (
        <EmptyState title="No deadhead rules" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Origin</th>
                <th className="px-3 py-2">Destination</th>
                <th className="px-3 py-2">Time (min)</th>
                <th className="px-3 py-2">Distance (km)</th>
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
