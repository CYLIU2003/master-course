import { useParams } from "react-router-dom";
import { useTurnaroundRules } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function RulesPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useTurnaroundRules(scenarioId!);

  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorBlock message={error.message} />;

  const rules = data?.items ?? [];

  return (
    <PageSection title="Turnaround Rules" description="Minimum turnaround times at terminal stops">
      {rules.length === 0 ? (
        <EmptyState title="No turnaround rules" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-surface-sunken text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Stop</th>
                <th className="px-3 py-2">Turnaround (min)</th>
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
