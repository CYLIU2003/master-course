import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  usePrepareSimulation,
  useQuickSetup,
  useRunOptimization,
  useRunPreparedSimulation,
  useUpdateQuickSetup,
  useJob,
} from "@/hooks";
import { ErrorBlock, LoadingBlock, PageSection } from "@/features/common";
import { getCanonicalDirectionLabel, getRouteVariantLabelByValue } from "@/features/planning/route-family-display";
import type { SimulationBuilderSettings } from "@/types";

const SOLVER_OPTIONS: Array<{
  value: SimulationBuilderSettings["solverMode"];
  label: string;
}> = [
  { value: "mode_milp_only", label: "MILP only" },
  { value: "mode_alns_only", label: "ALNS only" },
  { value: "mode_alns_milp", label: "ALNS + MILP" },
  { value: "hybrid", label: "Hybrid" },
  { value: "ga", label: "GA" },
  { value: "abc", label: "ABC" },
];

const OBJECTIVE_OPTIONS: Array<{
  value: NonNullable<SimulationBuilderSettings["objectiveMode"]>;
  label: string;
}> = [
  { value: "total_cost", label: "Cost最小" },
  { value: "co2", label: "CO2最小" },
  { value: "balanced", label: "Cost+CO2バランス" },
];

export function ScenarioQuickPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const [selectedDepotIds, setSelectedDepotIds] = useState<string[]>([]);
  const [selectedRouteIds, setSelectedRouteIds] = useState<string[]>([]);
  const [dayType, setDayType] = useState("WEEKDAY");
  const [includeShortTurn, setIncludeShortTurn] = useState(true);
  const [includeDepotMoves, setIncludeDepotMoves] = useState(true);
  const [includeDeadhead, setIncludeDeadhead] = useState(true);
  const [allowIntraDepotRouteSwap, setAllowIntraDepotRouteSwap] = useState(false);
  const [allowInterDepotSwap, setAllowInterDepotSwap] = useState(false);

  const [solverMode, setSolverMode] = useState<SimulationBuilderSettings["solverMode"]>("mode_milp_only");
  const [objectiveMode, setObjectiveMode] = useState<NonNullable<SimulationBuilderSettings["objectiveMode"]>>("total_cost");
  const [timeLimitSeconds, setTimeLimitSeconds] = useState(300);
  const [mipGap, setMipGap] = useState(0.01);
  const [alnsIterations, setAlnsIterations] = useState(500);
  const [allowPartialService, setAllowPartialService] = useState(false);
  const [unservedPenalty, setUnservedPenalty] = useState(10000);
  const [gridFlatPricePerKwh, setGridFlatPricePerKwh] = useState(30);
  const [demandChargeCostPerKw, setDemandChargeCostPerKw] = useState(1200);
  const [dieselPricePerL, setDieselPricePerL] = useState(150);
  const [co2PricePerKg, setCo2PricePerKg] = useState(1);

  const [vehicleCount, setVehicleCount] = useState(10);
  const [chargerCount, setChargerCount] = useState(4);
  const [chargerPowerKw, setChargerPowerKw] = useState(90);

  const [preparedInputId, setPreparedInputId] = useState<string | null>(null);
  const [simulationJobId, setSimulationJobId] = useState<string | null>(null);
  const [optimizationJobId, setOptimizationJobId] = useState<string | null>(null);

  const quickSetupQuery = useQuickSetup(scenarioId ?? "", {
    depotIds: selectedDepotIds.length ? selectedDepotIds : undefined,
    routeLimit: 600,
  });
  const updateQuickSetup = useUpdateQuickSetup(scenarioId ?? "");
  const prepareMutation = usePrepareSimulation(scenarioId ?? "");
  const runPreparedMutation = useRunPreparedSimulation(scenarioId ?? "");
  const runOptimizationMutation = useRunOptimization(scenarioId ?? "");

  const { data: simulationJob } = useJob(simulationJobId);
  const { data: optimizationJob } = useJob(optimizationJobId);

  useEffect(() => {
    const payload = quickSetupQuery.data;
    if (!payload) {
      return;
    }
    setSelectedDepotIds(payload.selectedDepotIds);
    setSelectedRouteIds(payload.selectedRouteIds);
    setDayType(payload.dispatchScope.dayType || "WEEKDAY");
    setIncludeShortTurn(Boolean(payload.dispatchScope.tripSelection.includeShortTurn ?? true));
    setIncludeDepotMoves(Boolean(payload.dispatchScope.tripSelection.includeDepotMoves ?? true));
    setIncludeDeadhead(Boolean(payload.dispatchScope.tripSelection.includeDeadhead ?? true));
    setAllowIntraDepotRouteSwap(Boolean(payload.dispatchScope.allowIntraDepotRouteSwap));
    setAllowInterDepotSwap(Boolean(payload.dispatchScope.allowInterDepotSwap));
    setSolverMode(payload.solverSettings.solverMode || "mode_milp_only");
    setTimeLimitSeconds(payload.solverSettings.timeLimitSeconds || 300);
      setMipGap(payload.solverSettings.mipGap ?? 0.01);
      setObjectiveMode(payload.solverSettings.objectiveMode || "total_cost");
    setAlnsIterations(payload.solverSettings.alnsIterations || 500);
    setVehicleCount(payload.simulationSettings.vehicleCount || 10);
    setChargerCount(payload.simulationSettings.chargerCount || 4);
    setChargerPowerKw(payload.simulationSettings.chargerPowerKw || 90);
      setAllowPartialService(Boolean(payload.simulationSettings.allowPartialService ?? false));
      setUnservedPenalty(payload.simulationSettings.unservedPenalty ?? 10000);
      setGridFlatPricePerKwh(payload.simulationSettings.gridFlatPricePerKwh ?? 30);
      setDemandChargeCostPerKw(payload.simulationSettings.demandChargeCostPerKw ?? 1200);
      setDieselPricePerL(payload.simulationSettings.dieselPricePerL ?? 150);
      setCo2PricePerKg(payload.simulationSettings.co2PricePerKg ?? 1);
  }, [quickSetupQuery.data?.scenario.id]);

  const routeItems = quickSetupQuery.data?.routes ?? [];
  const selectedRouteCount = selectedRouteIds.length;
  const selectedTripCount = useMemo(
    () =>
      routeItems
        .filter((item) => selectedRouteIds.includes(item.id))
        .reduce((sum, item) => sum + Number(item.tripCount || 0), 0),
    [routeItems, selectedRouteIds],
  );

  if (!scenarioId) {
    return null;
  }
  if (quickSetupQuery.isLoading) {
    return <LoadingBlock message="軽量セットアップを読み込み中..." />;
  }
  if (quickSetupQuery.error) {
    return <ErrorBlock message={quickSetupQuery.error.message} />;
  }
  if (!quickSetupQuery.data) {
    return null;
  }

  const depots = quickSetupQuery.data.depots;

  function toggleDepot(depotId: string, checked: boolean) {
    setSelectedDepotIds((prev) => {
      if (checked) {
        return prev.includes(depotId) ? prev : [...prev, depotId];
      }
      return prev.filter((id) => id !== depotId);
    });
  }

  function toggleRoute(routeId: string, checked: boolean) {
    setSelectedRouteIds((prev) => {
      if (checked) {
        return prev.includes(routeId) ? prev : [...prev, routeId];
      }
      return prev.filter((id) => id !== routeId);
    });
  }

  function buildQuickSetupPatch() {
    return {
      selectedDepotIds,
      selectedRouteIds,
      dayType,
      includeShortTurn,
      includeDepotMoves,
      includeDeadhead,
      allowIntraDepotRouteSwap,
      allowInterDepotSwap,
      solverMode,
      objectiveMode,
      timeLimitSeconds,
      mipGap,
      alnsIterations,
      allowPartialService,
      unservedPenalty,
      gridFlatPricePerKwh,
      demandChargeCostPerKw,
      dieselPricePerL,
      co2PricePerKg,
    };
  }

  async function saveQuickSetup() {
    await updateQuickSetup.mutateAsync(buildQuickSetupPatch());
  }

  async function prepareInput() {
    const result = await prepareMutation.mutateAsync({
      selected_depot_ids: selectedDepotIds,
      selected_route_ids: selectedRouteIds,
      day_type: dayType,
      include_short_turn: includeShortTurn,
      include_depot_moves: includeDepotMoves,
      include_deadhead: includeDeadhead,
      allow_intra_depot_route_swap: allowIntraDepotRouteSwap,
      allow_inter_depot_swap: allowInterDepotSwap,
      simulation_settings: {
        vehicle_count: vehicleCount,
        initial_soc: 0.8,
        charger_count: chargerCount,
        charger_power_kw: chargerPowerKw,
        solver_mode: solverMode,
        objective_mode: objectiveMode,
        allow_partial_service: allowPartialService,
        unserved_penalty: unservedPenalty,
        time_limit_seconds: timeLimitSeconds,
        mip_gap: mipGap,
        include_deadhead: includeDeadhead,
        alns_iterations: alnsIterations,
        grid_flat_price_per_kwh: gridFlatPricePerKwh,
        demand_charge_cost_per_kw: demandChargeCostPerKw,
        diesel_price_per_l: dieselPricePerL,
        co2_price_per_kg: co2PricePerKg,
      },
    });
    if (result.preparedInputId) {
      setPreparedInputId(result.preparedInputId);
    }
  }

  async function runSimulation() {
    if (!preparedInputId) {
      return;
    }
    const job = await runPreparedMutation.mutateAsync({
      prepared_input_id: preparedInputId,
      source: "duties",
    });
    setSimulationJobId(job.job_id);
  }

  async function runOptimization() {
    await updateQuickSetup.mutateAsync(buildQuickSetupPatch());
    const job = await runOptimizationMutation.mutateAsync({
      mode: solverMode,
      time_limit_seconds: timeLimitSeconds,
      mip_gap: mipGap,
      alns_iterations: alnsIterations,
      rebuild_dispatch: true,
    });
    setOptimizationJobId(job.job_id);
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-white p-4">
        <h1 className="text-lg font-semibold text-slate-800">軽量シミュレーション実行</h1>
        <p className="mt-1 text-sm text-slate-600">
          シナリオ作成後に必要な設定だけを1画面で完了します。営業所・路線・トレード許可・ソルバーを決めたらすぐ実行できます。
        </p>
        <p className="mt-2 text-xs text-slate-500">
          詳細編集が必要な場合は <Link className="text-primary-600 underline" to={`/scenarios/${scenarioId}/planning`}>Planning</Link> を開いてください。
        </p>
      </div>

      <PageSection title="対象営業所" description="実行対象の営業所を選択します。">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {depots.map((depot) => (
            <label key={depot.id} className="flex items-center justify-between rounded border border-slate-200 px-3 py-2 text-sm">
              <span>
                {depot.name}
                <span className="ml-2 text-xs text-slate-500">車両 {depot.vehicleCount} / 路線 {depot.routeCount}</span>
              </span>
              <input
                type="checkbox"
                checked={selectedDepotIds.includes(depot.id)}
                onChange={(e) => toggleDepot(depot.id, e.target.checked)}
              />
            </label>
          ))}
        </div>
      </PageSection>

      <PageSection title="対象路線" description="選択した営業所に紐づく路線から実行対象を選択します。">
        <div className="mb-2 text-xs text-slate-500">選択: {selectedRouteCount} 路線 / 約 {selectedTripCount} 便</div>
        <div className="max-h-72 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
          {routeItems.map((route) => (
            <label key={route.id} className="flex items-center justify-between rounded px-2 py-1 text-sm hover:bg-slate-50">
              <span className="truncate pr-2">
                {route.displayName}
                <span className="ml-2 text-xs text-slate-500">{getRouteVariantLabelByValue(route.routeVariantType)} / {getCanonicalDirectionLabel(route.canonicalDirection)} / {route.tripCount}便</span>
              </span>
              <input
                type="checkbox"
                checked={selectedRouteIds.includes(route.id)}
                onChange={(e) => toggleRoute(route.id, e.target.checked)}
              />
            </label>
          ))}
        </div>
      </PageSection>

      <PageSection title="運用ルール" description="便種フィルタと車両トレード許可を決めます。">
        <div className="grid gap-2 md:grid-cols-2">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeShortTurn} onChange={(e) => setIncludeShortTurn(e.target.checked)} />区間便を含める</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeDepotMoves} onChange={(e) => setIncludeDepotMoves(e.target.checked)} />入出庫便を含める</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeDeadhead} onChange={(e) => setIncludeDeadhead(e.target.checked)} />回送を含める</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allowIntraDepotRouteSwap} onChange={(e) => setAllowIntraDepotRouteSwap(e.target.checked)} />営業所内の路線間トレード許可</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allowInterDepotSwap} onChange={(e) => setAllowInterDepotSwap(e.target.checked)} />営業所間トレード許可</label>
        </div>
      </PageSection>

      <PageSection title="ソルバー・実行条件" description="何で解くかを最短で指定します。">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-sm">Solver
            <select className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={solverMode} onChange={(e) => setSolverMode(e.target.value as SimulationBuilderSettings["solverMode"])}>
              {SOLVER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">Objective
            <select className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={objectiveMode} onChange={(e) => setObjectiveMode(e.target.value as NonNullable<SimulationBuilderSettings["objectiveMode"]>)}>
              {OBJECTIVE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">Time limit (sec)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={30} value={timeLimitSeconds} onChange={(e) => setTimeLimitSeconds(Number(e.target.value) || 300)} />
          </label>
          <label className="text-sm">MIP gap
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" step={0.001} min={0} value={mipGap} onChange={(e) => setMipGap(Number(e.target.value) || 0.01)} />
          </label>
          <label className="text-sm">ALNS iter
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={10} value={alnsIterations} onChange={(e) => setAlnsIterations(Number(e.target.value) || 500)} />
          </label>
          <label className="text-sm">Vehicle count
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={1} value={vehicleCount} onChange={(e) => setVehicleCount(Number(e.target.value) || 1)} />
          </label>
          <label className="text-sm">Charger count
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={1} value={chargerCount} onChange={(e) => setChargerCount(Number(e.target.value) || 1)} />
          </label>
          <label className="text-sm">Charger power (kW)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={1} value={chargerPowerKw} onChange={(e) => setChargerPowerKw(Number(e.target.value) || 1)} />
          </label>
          <label className="text-sm">Service type
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={dayType} onChange={(e) => setDayType(e.target.value || "WEEKDAY")} />
          </label>
          <label className="text-sm">Allow partial service
            <select className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={allowPartialService ? "1" : "0"} onChange={(e) => setAllowPartialService(e.target.value === "1")}>
              <option value="0">No</option>
              <option value="1">Yes</option>
            </select>
          </label>
          <label className="text-sm">Unserved penalty
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={0} step={1000} value={unservedPenalty} onChange={(e) => setUnservedPenalty(Number(e.target.value) || 10000)} />
          </label>
          <label className="text-sm">Grid flat price (JPY/kWh)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={0} step={0.1} value={gridFlatPricePerKwh} onChange={(e) => setGridFlatPricePerKwh(Number(e.target.value) || 0)} />
          </label>
          <label className="text-sm">Demand charge (JPY/kW)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={0} step={1} value={demandChargeCostPerKw} onChange={(e) => setDemandChargeCostPerKw(Number(e.target.value) || 0)} />
          </label>
          <label className="text-sm">Diesel price (JPY/L)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={0} step={1} value={dieselPricePerL} onChange={(e) => setDieselPricePerL(Number(e.target.value) || 0)} />
          </label>
          <label className="text-sm">CO2 price (JPY/kg)
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" type="number" min={0} step={0.1} value={co2PricePerKg} onChange={(e) => setCo2PricePerKg(Number(e.target.value) || 0)} />
          </label>
        </div>
        <p className="mt-2 text-xs text-slate-500">注: ここで指定した値は quick-setup 保存時と最適化実行直前に scenario 設定へ反映されます。</p>
      </PageSection>

      <div className="rounded-xl border border-border bg-white p-4">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={saveQuickSetup}
            disabled={updateQuickSetup.isPending}
            className="rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {updateQuickSetup.isPending ? "保存中..." : "設定を保存"}
          </button>
          <button
            type="button"
            onClick={prepareInput}
            disabled={prepareMutation.isPending || selectedDepotIds.length === 0 || selectedRouteIds.length === 0}
            className="rounded bg-primary-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {prepareMutation.isPending ? "作成中..." : "入力データ作成"}
          </button>
          <button
            type="button"
            onClick={runSimulation}
            disabled={runPreparedMutation.isPending || !preparedInputId}
            className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {runPreparedMutation.isPending ? "起動中..." : "シミュレーション実行"}
          </button>
          <button
            type="button"
            onClick={runOptimization}
            disabled={runOptimizationMutation.isPending}
            className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {runOptimizationMutation.isPending ? "起動中..." : "最適化実行"}
          </button>
        </div>
        <div className="mt-3 space-y-1 text-xs text-slate-600">
          <div>Prepared Input: {preparedInputId ?? "未作成"}</div>
          <div>Simulation Job: {simulationJobId ?? "未実行"} {simulationJob ? `(${simulationJob.status})` : ""}</div>
          <div>Optimization Job: {optimizationJobId ?? "未実行"} {optimizationJob ? `(${optimizationJob.status})` : ""}</div>
        </div>
      </div>
    </div>
  );
}
