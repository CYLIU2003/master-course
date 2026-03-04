import { useUIStore } from "@/stores/ui-store";
import { useDepots, useCreateDepot, useDeleteDepot } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import type { Depot } from "@/types";

interface DepotListPanelProps {
  scenarioId: string;
}

export function DepotListPanel({ scenarioId }: DepotListPanelProps) {
  const { data, isLoading, error } = useDepots(scenarioId);
  const selectedDepotId = useUIStore((s) => s.selectedDepotId);
  const setSelectedDepotId = useUIStore((s) => s.setSelectedDepotId);
  const createDepot = useCreateDepot(scenarioId);
  const deleteDepot = useDeleteDepot(scenarioId);

  if (isLoading) return <LoadingBlock message="Loading depots..." />;
  if (error) return <ErrorBlock message={error.message} />;

  const depots: Depot[] = data?.items ?? [];

  const handleAddDepot = () => {
    createDepot.mutate(
      {
        name: `Depot ${depots.length + 1}`,
        location: "",
      },
      {
        onSuccess: (newDepot) => {
          setSelectedDepotId(newDepot.id);
        },
      },
    );
  };

  const handleDelete = (e: React.MouseEvent, depotId: string) => {
    e.stopPropagation();
    if (!confirm("Delete this depot and all its vehicles?")) return;
    deleteDepot.mutate(depotId, {
      onSuccess: () => {
        if (selectedDepotId === depotId) setSelectedDepotId(null);
      },
    });
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Depots
        </h3>
        <button
          onClick={handleAddDepot}
          disabled={createDepot.isPending}
          className="rounded px-2 py-0.5 text-xs font-medium text-primary-600 hover:bg-primary-50 disabled:opacity-50"
        >
          + Add
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {depots.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No depots yet"
              description="Create a depot to get started"
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {depots.map((depot) => (
              <li key={depot.id}>
                <button
                  onClick={() => setSelectedDepotId(depot.id)}
                  className={`flex w-full items-center justify-between px-3 py-2.5 text-left transition-colors ${
                    selectedDepotId === depot.id
                      ? "bg-primary-50 text-primary-700"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {depot.name}
                    </p>
                    <p className="truncate text-xs text-slate-400">
                      {depot.location || "No location"}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, depot.id)}
                    className="ml-2 shrink-0 rounded p-0.5 text-slate-300 hover:bg-red-50 hover:text-red-500"
                    aria-label={`Delete ${depot.name}`}
                  >
                    <svg
                      className="h-3.5 w-3.5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
