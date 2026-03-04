import {
  useVehicles,
  useCreateVehicle,
  useDeleteVehicle,
} from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import type { Vehicle } from "@/types";

interface VehicleTableProps {
  scenarioId: string;
  depotId?: string;
}

export function VehicleTable({ scenarioId, depotId }: VehicleTableProps) {
  const { data, isLoading, error } = useVehicles(scenarioId, depotId);
  const createVehicle = useCreateVehicle(scenarioId);
  const deleteVehicle = useDeleteVehicle(scenarioId);

  if (isLoading) return <LoadingBlock message="Loading vehicles..." />;
  if (error) return <ErrorBlock message={error.message} />;

  const vehicles: Vehicle[] = data?.items ?? [];

  const handleAdd = () => {
    if (!depotId) return;
    createVehicle.mutate({
      depotId,
      type: "BEV",
      modelName: "New Vehicle",
      capacityPassengers: 70,
      energyConsumption: 1.2,
    });
  };

  const handleDelete = (vehicleId: string) => {
    if (!confirm("Delete this vehicle?")) return;
    deleteVehicle.mutate(vehicleId);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {vehicles.length} vehicle{vehicles.length !== 1 ? "s" : ""}
          {depotId ? " in this depot" : " total"}
        </p>
        {depotId && (
          <button
            onClick={handleAdd}
            disabled={createVehicle.isPending}
            className="rounded bg-primary-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            + Add Vehicle
          </button>
        )}
      </div>

      {vehicles.length === 0 ? (
        <EmptyState
          title="No vehicles"
          description={depotId ? "Add a vehicle to this depot" : "No vehicles in any depot"}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border bg-slate-50">
                <th className="px-3 py-2 text-xs font-medium text-slate-500">Model</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500">Type</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">Capacity</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">Battery (kWh)</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">Consumption</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">Charge (kW)</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500">Status</th>
                <th className="px-3 py-2 text-xs font-medium text-slate-500 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {vehicles.map((v) => (
                <tr key={v.id} className="hover:bg-slate-50/50">
                  <td className="px-3 py-2 font-medium text-slate-700">{v.modelName}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                        v.type === "BEV"
                          ? "bg-green-50 text-green-700"
                          : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {v.type}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-slate-600">{v.capacityPassengers}</td>
                  <td className="px-3 py-2 text-right text-slate-600">{v.batteryKwh ?? "-"}</td>
                  <td className="px-3 py-2 text-right text-slate-600">{v.energyConsumption}</td>
                  <td className="px-3 py-2 text-right text-slate-600">{v.chargePowerKw ?? "-"}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        v.enabled ? "bg-green-400" : "bg-slate-300"
                      }`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => handleDelete(v.id)}
                      className="rounded p-0.5 text-slate-300 hover:bg-red-50 hover:text-red-500"
                      aria-label={`Delete ${v.modelName}`}
                    >
                      <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
