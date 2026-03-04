import { Link } from "react-router-dom";
import { useCompareStore } from "@/stores/compare-store";
import { PageSection, EmptyState } from "@/features/common";

export function ComparePage() {
  const { selectedIds, clearSelection } = useCompareStore();

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-4 flex items-center justify-between">
        <Link to="/scenarios" className="text-sm text-primary-600 hover:underline">
          &larr; Back to scenarios
        </Link>
        {selectedIds.length > 0 && (
          <button
            onClick={clearSelection}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            Clear selection
          </button>
        )}
      </div>

      <PageSection
        title="Compare Scenarios"
        description="Side-by-side comparison of optimization results"
      >
        {selectedIds.length < 2 ? (
          <EmptyState
            title="Select at least 2 scenarios"
            description="Go to the scenario list and select scenarios to compare"
          />
        ) : (
          <div className="rounded-lg border border-border bg-surface-sunken p-8 text-center text-sm text-slate-400">
            Comparison table placeholder for: {selectedIds.join(", ")}
          </div>
        )}
      </PageSection>
    </div>
  );
}
