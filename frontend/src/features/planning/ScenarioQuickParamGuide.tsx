import type { SimulationBuilderSettings } from "@/types";

type SolverOption = {
  value: SimulationBuilderSettings["solverMode"];
  label: string;
};

type ObjectiveOption = {
  value: NonNullable<SimulationBuilderSettings["objectiveMode"]>;
  label: string;
};

interface ScenarioQuickParamGuideProps {
  settings: SimulationBuilderSettings;
  onPatch: (patch: Partial<SimulationBuilderSettings>) => void;
  solverOptions: SolverOption[];
  objectiveOptions: ObjectiveOption[];
  selectedDepotId: string;
  selectedRouteCount: number;
  selectedTripCount: number;
}

const QUICK_PRESETS: Array<{
  id: string;
  label: string;
  description: string;
  patch: Partial<SimulationBuilderSettings>;
}> = [
  {
    id: "balanced",
    label: "Balanced",
    description: "精度と速度のバランス",
    patch: {
      solverMode: "hybrid",
      objectiveMode: "balanced",
      timeLimitSeconds: 240,
      mipGap: 0.02,
      alnsIterations: 450,
      allowPartialService: false,
      includeDeadhead: true,
    },
  },
  {
    id: "quick",
    label: "Quick",
    description: "探索優先で短時間",
    patch: {
      solverMode: "mode_alns_only",
      objectiveMode: "total_cost",
      timeLimitSeconds: 90,
      mipGap: 0.05,
      alnsIterations: 150,
      allowPartialService: true,
      includeDeadhead: true,
    },
  },
  {
    id: "robust",
    label: "Robust",
    description: "MILP修復を強める",
    patch: {
      solverMode: "mode_alns_milp",
      objectiveMode: "total_cost",
      timeLimitSeconds: 360,
      mipGap: 0.01,
      alnsIterations: 700,
      allowPartialService: false,
      includeDeadhead: true,
    },
  },
];

function parseFiniteNumber(raw: string, fallback: number): number {
  const next = Number(raw);
  return Number.isFinite(next) ? next : fallback;
}

function parseNullableNumber(raw: string): number | null {
  if (raw.trim() === "") {
    return null;
  }
  const next = Number(raw);
  return Number.isFinite(next) ? next : null;
}

function estimateFleetCount(settings: SimulationBuilderSettings): number {
  const fromTemplates = (settings.fleetTemplates ?? []).reduce(
    (sum, item) => sum + Math.max(0, Math.floor(Number(item.vehicleCount) || 0)),
    0,
  );
  return fromTemplates > 0 ? fromTemplates : Math.max(0, Math.floor(settings.vehicleCount));
}

export function ScenarioQuickParamGuide({
  settings,
  onPatch,
  solverOptions,
  objectiveOptions,
  selectedDepotId,
  selectedRouteCount,
  selectedTripCount,
}: ScenarioQuickParamGuideProps) {
  const fleetCount = estimateFleetCount(settings);
  const chargerCapacityKw = Math.max(0, settings.chargerCount) * Math.max(0, settings.chargerPowerKw);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Quick Param Guide</p>
          <p className="mt-1 text-sm text-slate-600">
            最低限の主要パラメータだけ先に決めて、最適化実行までを短く回します。詳細値は下の通常設定で調整できます。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {QUICK_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => onPatch(preset.patch)}
              className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400 hover:bg-slate-100"
              title={preset.description}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-5">
        <GuideCard label="Selected depot" value={selectedDepotId || "-"} />
        <GuideCard label="Selected routes" value={String(selectedRouteCount)} />
        <GuideCard label="Estimated trips" value={selectedTripCount.toLocaleString()} />
        <GuideCard label="Fleet size" value={`${fleetCount} vehicles`} />
        <GuideCard label="Charge capacity" value={`${chargerCapacityKw.toLocaleString()} kW`} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <GuideField label="Solver mode">
          <select
            value={settings.solverMode}
            onChange={(event) =>
              onPatch({
                solverMode: event.target.value as SimulationBuilderSettings["solverMode"],
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          >
            {solverOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </GuideField>

        <GuideField label="Objective">
          <select
            value={settings.objectiveMode ?? "total_cost"}
            onChange={(event) =>
              onPatch({
                objectiveMode: event.target.value as NonNullable<
                  SimulationBuilderSettings["objectiveMode"]
                >,
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          >
            {objectiveOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </GuideField>

        <GuideField label="Time limit (sec)">
          <input
            type="number"
            min={1}
            step={1}
            value={settings.timeLimitSeconds}
            onChange={(event) =>
              onPatch({
                timeLimitSeconds: Math.max(1, Math.floor(parseFiniteNumber(event.target.value, 60))),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="ALNS iterations">
          <input
            type="number"
            min={1}
            step={10}
            value={settings.alnsIterations}
            onChange={(event) =>
              onPatch({
                alnsIterations: Math.max(1, Math.floor(parseFiniteNumber(event.target.value, 100))),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="MIP gap">
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={settings.mipGap}
            onChange={(event) =>
              onPatch({
                mipGap: Math.max(0, Math.min(1, parseFiniteNumber(event.target.value, 0.01))),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="Vehicle count">
          <input
            type="number"
            min={1}
            step={1}
            value={settings.vehicleCount}
            onChange={(event) =>
              onPatch({
                vehicleCount: Math.max(1, Math.floor(parseFiniteNumber(event.target.value, 1))),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="Charger count">
          <input
            type="number"
            min={0}
            step={1}
            value={settings.chargerCount}
            onChange={(event) =>
              onPatch({
                chargerCount: Math.max(0, Math.floor(parseFiniteNumber(event.target.value, 0))),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="Charger power (kW)">
          <input
            type="number"
            min={0}
            step={5}
            value={settings.chargerPowerKw}
            onChange={(event) =>
              onPatch({
                chargerPowerKw: Math.max(0, parseFiniteNumber(event.target.value, 0)),
              })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </GuideField>

        <GuideField label="Demand charge (JPY/kW)">
          <input
            type="number"
            min={0}
            step={10}
            value={settings.demandChargeCostPerKw ?? ""}
            onChange={(event) =>
              onPatch({ demandChargeCostPerKw: parseNullableNumber(event.target.value) })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            placeholder="auto"
          />
        </GuideField>

        <GuideField label="Depot power limit (kW)">
          <input
            type="number"
            min={0}
            step={10}
            value={settings.depotPowerLimitKw ?? ""}
            onChange={(event) =>
              onPatch({ depotPowerLimitKw: parseNullableNumber(event.target.value) })
            }
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            placeholder="no limit"
          />
        </GuideField>
      </div>
    </div>
  );
}

function GuideField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="space-y-1 text-sm">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function GuideCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-800">{value}</div>
    </div>
  );
}
