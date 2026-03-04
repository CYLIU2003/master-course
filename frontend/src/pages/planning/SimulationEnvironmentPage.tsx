import { useParams } from "react-router-dom";
import { PageSection, EmptyState } from "@/features/common";

export function SimulationEnvironmentPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();

  if (!scenarioId) return null;

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          Simulation Environment
        </h1>
        <p className="text-sm text-slate-500">
          Configure simulation parameters and pricing
        </p>
      </div>

      {/* Period & dates */}
      <PageSection title="Simulation Period" description="Date range and service dates">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label="Start Date" value="(not configured)" />
          <FieldCard label="End Date" value="(not configured)" />
          <FieldCard label="Service Date" value="(not configured)" />
        </div>
      </PageSection>

      {/* Electricity pricing */}
      <PageSection title="Electricity Pricing" description="Flat rate and TOU schedule">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label="Flat Price (JPY/kWh)" value="(not configured)" />
          <FieldCard label="Contract Demand (kW)" value="(not configured)" />
          <FieldCard label="Demand Penalty Mode" value="(not configured)" />
          <FieldCard label="Demand Charge (JPY/kW)" value="(not configured)" />
        </div>
        <div className="mt-4">
          <EmptyState
            title="No TOU pricing slots"
            description="Add time-of-use pricing to override flat rate"
          />
        </div>
      </PageSection>

      {/* Energy sources */}
      <PageSection title="Energy Sources" description="PV and diesel configuration">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label="PV Enabled" value="No" />
          <FieldCard label="PV Scale Factor" value="1.0" />
          <FieldCard label="Diesel Price (JPY/L)" value="(not configured)" />
        </div>
      </PageSection>

      {/* Solver settings */}
      <PageSection title="Solver Settings" description="Optimization parameters">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FieldCard label="Initial SOC" value="1.0" />
          <FieldCard label="Random Seed" value="None" />
          <FieldCard label="Optimization Mode" value="(not configured)" />
          <FieldCard label="Time Limit (s)" value="300" />
          <FieldCard label="MIP Gap" value="0.01" />
        </div>
      </PageSection>
    </div>
  );
}

// ── Helper component for read-only field display ──────────────

function FieldCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-700">{value}</p>
    </div>
  );
}
