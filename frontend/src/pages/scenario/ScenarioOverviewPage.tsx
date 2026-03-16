import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  BackendJobPanel,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageSection,
} from "@/features/common";
import { ScenarioQuickParamGuide } from "@/features/planning";
import {
  useDeleteScenario,
  useEditorBootstrap,
  useJob,
  usePrepareSimulation,
  useRunOptimization,
  useRunPreparedSimulation,
  useScenarioRunReadiness,
} from "@/hooks";
import { isIncompleteArtifactError } from "@/api/client";
import { runKeys } from "@/hooks/use-run";
import { useHasPlanningDraftChanges } from "@/stores/planning-draft-store";
import { useSimulationBuilderStore } from "@/stores/simulation-builder-store";
import { useScenarioDraftStore } from "@/stores/scenario-draft-store";
import type { Route, SimulationBuilderSettings } from "@/types";

const SOLVER_MODES: Array<{
  value: SimulationBuilderSettings["solverMode"];
  label: string;
}> = [
  { value: "mode_milp_only", label: "MILP only" },
  { value: "mode_alns_only", label: "ALNS only" },
  { value: "mode_alns_milp", label: "ALNS + MILP" },
  { value: "hybrid", label: "Hybrid" },
  { value: "ga", label: "GA (ALNS fallback)" },
  { value: "abc", label: "ABC (ALNS fallback)" },
];

const OBJECTIVE_MODES: Array<{
  value: NonNullable<SimulationBuilderSettings["objectiveMode"]>;
  label: string;
}> = [
  { value: "total_cost", label: "Total cost" },
  { value: "co2", label: "CO2" },
  { value: "balanced", label: "Cost + CO2" },
];

const EXPERIMENT_METHOD_SUGGESTIONS = [
  "MILP",
  "ALNS",
  "MILP+ALNS",
  "ABC",
  "GA",
];

function formatTouHour(value: number) {
  const hour = Math.max(0, Math.min(24, Number.isFinite(value) ? value : 0));
  return `${String(hour).padStart(2, "0")}:00`;
}

export function ScenarioOverviewPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const queryClient = useQueryClient();
  const [optimizationJobId, setOptimizationJobId] = useState<string | null>(null);
  const {
    data: bootstrap,
    isLoading,
    error,
  } = useEditorBootstrap(scenarioId!);
  const {
    canRun,
    reason: runReadinessReason,
  } = useScenarioRunReadiness();
  const prepareMutation = usePrepareSimulation(scenarioId!);
  const runPreparedMutation = useRunPreparedSimulation(scenarioId!);
  const runOptimizationMutation = useRunOptimization(scenarioId!);
  const {
    scenarioId: builderScenarioId,
    selectedDepotIds,
    selectedRouteIds,
    dayType,
    serviceDate,
    settings,
    includeShortTurn,
    includeDepotMoves,
    allowIntraDepotRouteSwap,
    allowInterDepotSwap,
    preparedResult,
    activeJobId,
    hydrateFromBootstrap,
    setSelectedDepotIds,
    setSelectedRouteIds,
    setDayType,
    setServiceDate,
    updateSettings,
    setIncludeShortTurn,
    setIncludeDepotMoves,
    setAllowIntraDepotRouteSwap,
    setAllowInterDepotSwap,
    setPreparedResult,
    setActiveJobId,
  } = useSimulationBuilderStore();
  const setDraftSelectedDepotId = useScenarioDraftStore((s) => s.setSelectedDepotId);
  const { data: activeJob } = useJob(activeJobId);
  const { data: optimizationJob } = useJob(optimizationJobId);
  const hasPlanningDraftChanges = useHasPlanningDraftChanges(scenarioId);

  useEffect(() => {
    if (!bootstrap) {
      return;
    }
    hydrateFromBootstrap(bootstrap, builderScenarioId !== bootstrap.scenario.id);
  }, [bootstrap, builderScenarioId, hydrateFromBootstrap]);

  useEffect(() => {
    if (activeJob?.status === "completed" && scenarioId) {
      void queryClient.invalidateQueries({
        queryKey: runKeys.simulation(scenarioId),
      });
    }
  }, [activeJob?.status, queryClient, scenarioId]);

  useEffect(() => {
    if (optimizationJob?.status === "completed" && scenarioId) {
      void queryClient.invalidateQueries({
        queryKey: runKeys.optimization(scenarioId),
      });
    }
  }, [optimizationJob?.status, queryClient, scenarioId]);

  const routesById = useMemo(() => {
    const map = new Map<string, Route & { displayName?: string }>();
    for (const route of bootstrap?.routes ?? []) {
      map.set(route.id, route);
    }
    return map;
  }, [bootstrap?.routes]);
  const selectedDepotId = selectedDepotIds[0] ?? "";
  const visibleRouteIds = useMemo(() => {
    const depotRouteIndex = bootstrap?.depotRouteIndex ?? {};
    const ids = selectedDepotId ? depotRouteIndex[selectedDepotId] ?? [] : [];
    return ids.filter((routeId) => routesById.has(routeId));
  }, [bootstrap?.depotRouteIndex, routesById, selectedDepotId]);
  const visibleRoutes = useMemo(
    () =>
      visibleRouteIds
        .map((routeId) => routesById.get(routeId))
        .filter((route): route is Route & { displayName?: string } => Boolean(route))
        .sort((left, right) =>
          String(left.displayName ?? left.routeCode ?? left.name).localeCompare(
            String(right.displayName ?? right.routeCode ?? right.name),
            "ja",
          ),
        ),
    [routesById, visibleRouteIds],
  );
  const topTripRouteIds = useMemo(() => {
    return [...visibleRoutes]
      .sort((left, right) => {
        const tripDiff = Number(right.tripCount ?? 0) - Number(left.tripCount ?? 0);
        if (tripDiff !== 0) {
          return tripDiff;
        }
        return String(left.displayName ?? left.routeCode ?? left.name).localeCompare(
          String(right.displayName ?? right.routeCode ?? right.name),
          "ja",
        );
      })
      .slice(0, 3)
      .map((route) => route.id);
  }, [visibleRoutes]);

  useEffect(() => {
    if (!visibleRouteIds.length) {
      return;
    }
    const allowed = new Set(visibleRouteIds);
    const filtered = selectedRouteIds.filter((routeId) => allowed.has(routeId));
    if (filtered.length !== selectedRouteIds.length) {
      setSelectedRouteIds(filtered);
    }
  }, [selectedRouteIds, setSelectedRouteIds, visibleRouteIds]);

  useEffect(() => {
    if (!scenarioId) {
      return;
    }
    setDraftSelectedDepotId(scenarioId, selectedDepotId || null);
  }, [scenarioId, selectedDepotId, setDraftSelectedDepotId]);

  if (isLoading) {
    return <LoadingBlock />;
  }
  if (error && isIncompleteArtifactError(error)) {
    return <IncompleteArtifactBanner scenarioId={scenarioId!} message={error.message} />;
  }
  if (error) {
    return <ErrorBlock message={error.message} />;
  }
  if (!bootstrap) {
    return null;
  }

  const templateOptions = bootstrap.vehicleTemplates ?? [];
  const usingMixedFleet = Boolean(settings.fleetTemplates?.length);

  function updateFleetTemplateRow(
    index: number,
    patch: Partial<NonNullable<SimulationBuilderSettings["fleetTemplates"]>[number]>,
  ) {
    const next = [...(settings.fleetTemplates ?? [])];
    next[index] = { ...next[index], ...patch };
    updateSettings({ fleetTemplates: next });
  }

  function addFleetTemplateRow() {
    const fallbackTemplateId =
      settings.vehicleTemplateId ?? templateOptions[0]?.id ?? "";
    if (!fallbackTemplateId) {
      return;
    }
    updateSettings({
      fleetTemplates: [
        ...(settings.fleetTemplates ?? []),
        {
          vehicleTemplateId: fallbackTemplateId,
          vehicleCount: 1,
          initialSoc: settings.initialSoc,
          batteryKwh: settings.batteryKwh ?? null,
          chargePowerKw: settings.chargerPowerKw ?? null,
        },
      ],
    });
  }

  function removeFleetTemplateRow(index: number) {
    const next = [...(settings.fleetTemplates ?? [])];
    next.splice(index, 1);
    updateSettings({ fleetTemplates: next });
  }

  function enableMixedFleetMode() {
    if (usingMixedFleet) {
      return;
    }
    const fallbackTemplateId =
      settings.vehicleTemplateId ?? templateOptions[0]?.id ?? "";
    if (!fallbackTemplateId) {
      return;
    }
    updateSettings({
      fleetTemplates: [
        {
          vehicleTemplateId: fallbackTemplateId,
          vehicleCount: settings.vehicleCount,
          initialSoc: settings.initialSoc,
          batteryKwh: settings.batteryKwh ?? null,
          chargePowerKw: settings.chargerPowerKw ?? null,
        },
      ],
    });
  }

  function addTouBand() {
    updateSettings({
      touPricing: [
        ...(settings.touPricing ?? []),
        { start_hour: 0, end_hour: 24, price_per_kwh: 0 },
      ],
    });
  }

  function updateTouBand(
    index: number,
    patch: Partial<NonNullable<SimulationBuilderSettings["touPricing"]>[number]>,
  ) {
    const next = [...(settings.touPricing ?? [])];
    next[index] = { ...next[index], ...patch };
    updateSettings({ touPricing: next });
  }

  function removeTouBand(index: number) {
    const next = [...(settings.touPricing ?? [])];
    next.splice(index, 1);
    updateSettings({ touPricing: next });
  }

  const scenario = bootstrap.scenario;
  const selectedRouteCount = selectedRouteIds.length;
  const selectedTripCount = selectedRouteIds.reduce((sum, routeId) => {
    const route = routesById.get(routeId);
    const tripCount = Number(route?.tripCount ?? 0);
    return sum + (Number.isFinite(tripCount) ? tripCount : 0);
  }, 0);
  const prepareDisabled =
    prepareMutation.isPending ||
    !selectedDepotIds.length ||
    !selectedRouteIds.length ||
    hasPlanningDraftChanges;
  const runDisabled =
    runPreparedMutation.isPending ||
    !preparedResult?.preparedInputId ||
    !preparedResult.ready ||
    !canRun;
  const runOptimizationDisabled =
    runOptimizationMutation.isPending ||
    !preparedResult?.preparedInputId ||
    !preparedResult.ready ||
    !canRun;

  async function handlePrepare() {
    if (hasPlanningDraftChanges) {
      window.alert("Planning 画面に未保存の変更があります。先に保存してから入力データ作成を実行してください。");
      return;
    }
    const result = await prepareMutation.mutateAsync({
      selected_depot_ids: [...selectedDepotIds],
      selected_route_ids: [...selectedRouteIds],
      day_type: dayType,
      service_date: serviceDate || undefined,
      // Trip selection: control which variant types enter the dispatch pipeline
      include_short_turn: includeShortTurn,
      include_depot_moves: includeDepotMoves,
      // Vehicle swap permissions
      allow_intra_depot_route_swap: allowIntraDepotRouteSwap,
      allow_inter_depot_swap: allowInterDepotSwap,
      simulation_settings: {
        vehicle_template_id: settings.vehicleTemplateId ?? undefined,
        vehicle_count: settings.vehicleCount,
        initial_soc: settings.initialSoc,
        battery_kwh: settings.batteryKwh ?? undefined,
        fleet_templates: (settings.fleetTemplates ?? []).map((item) => ({
          vehicle_template_id: item.vehicleTemplateId,
          vehicle_count: item.vehicleCount,
          initial_soc: item.initialSoc ?? undefined,
          battery_kwh: item.batteryKwh ?? undefined,
          charge_power_kw: item.chargePowerKw ?? undefined,
        })),
        charger_count: settings.chargerCount,
        charger_power_kw: settings.chargerPowerKw,
        solver_mode: settings.solverMode,
        objective_mode: settings.objectiveMode ?? "total_cost",
        allow_partial_service: settings.allowPartialService ?? false,
        unserved_penalty: settings.unservedPenalty ?? 10000,
        time_limit_seconds: settings.timeLimitSeconds,
        mip_gap: settings.mipGap,
        include_deadhead: settings.includeDeadhead,
        grid_flat_price_per_kwh: settings.gridFlatPricePerKwh ?? undefined,
        grid_sell_price_per_kwh: settings.gridSellPricePerKwh ?? undefined,
        demand_charge_cost_per_kw: settings.demandChargeCostPerKw ?? undefined,
        diesel_price_per_l: settings.dieselPricePerL ?? undefined,
        grid_co2_kg_per_kwh: settings.gridCo2KgPerKwh ?? undefined,
        co2_price_per_kg: settings.co2PricePerKg ?? undefined,
        depot_power_limit_kw: settings.depotPowerLimitKw ?? undefined,
        tou_pricing: (settings.touPricing ?? []).map((item) => ({
          start_hour: item.start_hour,
          end_hour: item.end_hour,
          price_per_kwh: item.price_per_kwh,
        })),
        service_date: serviceDate || undefined,
        start_time: settings.startTime ?? undefined,
        planning_horizon_hours: settings.planningHorizonHours ?? undefined,
        alns_iterations: settings.alnsIterations,
        random_seed: settings.randomSeed ?? undefined,
        experiment_method: settings.experimentMethod ?? undefined,
        experiment_notes: settings.experimentNotes ?? undefined,
      },
    });
    setPreparedResult(result);
  }

  async function handleRun() {
    if (!preparedResult?.preparedInputId) {
      return;
    }
    const job = await runPreparedMutation.mutateAsync({
      prepared_input_id: preparedResult.preparedInputId,
      source: "duties",
    });
    setActiveJobId(job.job_id);
  }

  async function handleRunOptimization() {
    if (!preparedResult?.ready) {
      return;
    }
    const job = await runOptimizationMutation.mutateAsync({
      mode: settings.solverMode,
      time_limit_seconds: settings.timeLimitSeconds,
      mip_gap: settings.mipGap,
      service_id: preparedResult.serviceIds[0] ?? dayType,
      depot_id: selectedDepotId || preparedResult.primaryDepotId || undefined,
      rebuild_dispatch: true,
      use_existing_duties: false,
      alns_iterations: settings.alnsIterations,
    });
    setOptimizationJobId(job.job_id);
  }

  return (
    <div className="space-y-6">
      <PageSection title={scenario.name} description={scenario.description}>
        <div className="grid gap-4 md:grid-cols-4">
          <InfoCard label="Operator" value={scenario.operatorId} />
          <InfoCard label="Dataset" value={scenario.datasetId ?? "tokyu_core"} />
          <InfoCard label="Dataset Version" value={scenario.datasetVersion ?? "unknown"} />
          <InfoCard label="Random Seed" value={String(scenario.randomSeed ?? 42)} />
        </div>
        {bootstrap.warning ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {bootstrap.warning}
          </div>
        ) : null}
      </PageSection>

      <PageSection
        title="Step 1 Target Selection"
        description="初期表示では営業所・路線の index だけを使います。時刻表本体は prepare まで読みません。"
      >
        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="space-y-3">
            {(bootstrap.depotRouteSummary ?? []).map((item) => {
              const active = selectedDepotId === item.depotId;
              return (
                <button
                  key={item.depotId}
                  type="button"
                  onClick={() => setSelectedDepotIds([item.depotId])}
                  className={`w-full rounded-xl border p-4 text-left transition ${
                    active
                      ? "border-primary-300 bg-primary-50"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold text-slate-800">{item.name}</p>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                      {item.routeCount} routes
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    trip estimate {item.tripCount.toLocaleString()} / selected {item.selectedRouteCount}
                  </p>
                </button>
              );
            })}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-800">
                  {selectedDepotId ? `${selectedDepotId} routes` : "Select a depot"}
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  route summary のみ表示。trip 明細は prepare 後に canonical input へ入ります。
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedRouteIds([...visibleRouteIds])}
                  className="rounded border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Select all
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedRouteIds([...topTripRouteIds])}
                  disabled={topTripRouteIds.length === 0}
                  className="rounded border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  Top 3 by tripCount
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedRouteIds([])}
                  className="rounded border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Clear
                </button>
              </div>
            </div>

            {/* Trip selection toggles — control which variant types enter dispatch */}
            <div className="mt-3 flex flex-wrap gap-3 border-t border-slate-100 pt-3">
              <span className="text-xs font-medium text-slate-500">便種フィルタ:</span>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={includeShortTurn}
                  onChange={(e) => setIncludeShortTurn(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600"
                />
                区間便 (short turn)
              </label>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={includeDepotMoves}
                  onChange={(e) => setIncludeDepotMoves(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-primary-600"
                />
                入出庫便 (depot in/out)
              </label>
            </div>

            {/* Swap permission toggles */}
            <div className="mt-2 flex flex-wrap gap-3">
              <span className="text-xs font-medium text-slate-500">車両トレード:</span>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={allowIntraDepotRouteSwap}
                  onChange={(e) => setAllowIntraDepotRouteSwap(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-amber-500"
                />
                <span className={allowIntraDepotRouteSwap ? "font-semibold text-amber-700" : ""}>
                  路線内トレード許可
                </span>
              </label>
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={allowInterDepotSwap}
                  onChange={(e) => setAllowInterDepotSwap(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-red-500"
                />
                <span className={allowInterDepotSwap ? "font-semibold text-red-700" : ""}>
                  営業所間トレード許可
                </span>
              </label>
              {allowInterDepotSwap && (
                <p className="w-full text-[11px] text-red-600">
                  ⚠ 複数営業所の trips が1つの DispatchContext に統合されます。計算コストが増加します。
                </p>
              )}
            </div>

            {!visibleRoutes.length ? (
              <EmptyState
                title="路線がありません"
                description="営業所を選択すると対象 route の summary がここに表示されます。"
              />
            ) : (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {visibleRoutes.map((route) => {
                  const checked = selectedRouteIds.includes(route.id);
                  return (
                    <label
                      key={route.id}
                      className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition ${
                        checked
                          ? "border-primary-300 bg-primary-50"
                          : "border-slate-200 bg-slate-50 hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checked}
                        onChange={() => {
                          if (checked) {
                            setSelectedRouteIds(
                              selectedRouteIds.filter((routeId) => routeId !== route.id),
                            );
                            return;
                          }
                          setSelectedRouteIds([...selectedRouteIds, route.id]);
                        }}
                      />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-800">
                          {route.displayName ?? route.routeCode ?? route.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {route.startStop || "-"} → {route.endStop || "-"}
                        </p>
                        {/* Direction & variant badges */}
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {route.canonicalDirection && route.canonicalDirection !== "unknown" && (
                            <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              route.canonicalDirection === "outbound"
                                ? "bg-blue-100 text-blue-700"
                                : route.canonicalDirection === "inbound"
                                ? "bg-purple-100 text-purple-700"
                                : "bg-slate-100 text-slate-500"
                            }`}>
                              {route.canonicalDirection === "outbound" ? "↗ 上り" : "↙ 下り"}
                            </span>
                          )}
                          {route.routeVariantType && route.routeVariantType !== "unknown" && route.routeVariantType !== "main" && (
                            <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              route.routeVariantType === "depot_in" || route.routeVariantType === "depot_out"
                                ? "bg-orange-100 text-orange-700"
                                : route.routeVariantType === "short_turn"
                                ? "bg-yellow-100 text-yellow-700"
                                : "bg-slate-100 text-slate-600"
                            }`}>
                              {route.routeVariantType === "depot_in" ? "入庫"
                                : route.routeVariantType === "depot_out" ? "出庫"
                                : route.routeVariantType === "short_turn" ? "区間"
                                : route.routeVariantType}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">
                          tripCount {Number(route.tripCount ?? 0).toLocaleString()}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </PageSection>

      <PageSection
        title="Step 2 Simulation Settings"
        description="営業所・路線に対して、車両構成、料金、solver、実験メタデータをここで確定します。prepare に渡る値はこの画面の入力だけです。"
      >
        <ScenarioQuickParamGuide
          settings={settings}
          onPatch={updateSettings}
          solverOptions={SOLVER_MODES}
          objectiveOptions={OBJECTIVE_MODES}
          selectedDepotId={selectedDepotId}
          selectedRouteCount={selectedRouteCount}
          selectedTripCount={selectedTripCount}
        />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Day Type">
            <select
              value={dayType}
              onChange={(event) => setDayType(event.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              {(bootstrap.availableDayTypes ?? []).map((item) => (
                <option key={item.serviceId} value={item.serviceId}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Service Date">
            <input
              type="date"
              value={serviceDate}
              onChange={(event) => setServiceDate(event.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Vehicle Template">
            <select
              value={settings.vehicleTemplateId ?? ""}
              onChange={(event) =>
                updateSettings({ vehicleTemplateId: event.target.value || null })
              }
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              {(bootstrap.vehicleTemplates ?? []).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Vehicle Count">
            <NumberInput
              value={settings.vehicleCount}
              min={1}
              onChange={(value) => updateSettings({ vehicleCount: value })}
            />
          </Field>
          <Field label="Initial SOC">
            <NumberInput
              value={settings.initialSoc}
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => updateSettings({ initialSoc: value })}
            />
          </Field>
          <Field label="Battery kWh">
            <NumberInput
              value={settings.batteryKwh ?? 0}
              min={0}
              step={1}
              onChange={(value) => updateSettings({ batteryKwh: value || null })}
            />
          </Field>
          <Field label="Charger Count">
            <NumberInput
              value={settings.chargerCount}
              min={0}
              onChange={(value) => updateSettings({ chargerCount: value })}
            />
          </Field>
          <Field label="Charger Power kW">
            <NumberInput
              value={settings.chargerPowerKw}
              min={0}
              step={5}
              onChange={(value) => updateSettings({ chargerPowerKw: value })}
            />
          </Field>
          <Field label="Solver Mode">
            <select
              value={settings.solverMode}
              onChange={(event) =>
                updateSettings({
                  solverMode: event.target.value as SimulationBuilderSettings["solverMode"],
                })
              }
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              {SOLVER_MODES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Objective">
            <select
              value={settings.objectiveMode ?? "total_cost"}
              onChange={(event) =>
                updateSettings({
                  objectiveMode: event.target.value as NonNullable<
                    SimulationBuilderSettings["objectiveMode"]
                  >,
                })
              }
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              {OBJECTIVE_MODES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Time Limit (sec)">
            <NumberInput
              value={settings.timeLimitSeconds}
              min={1}
              onChange={(value) => updateSettings({ timeLimitSeconds: value })}
            />
          </Field>
          <Field label="MIP Gap">
            <NumberInput
              value={settings.mipGap}
              min={0}
              max={1}
              step={0.01}
              onChange={(value) => updateSettings({ mipGap: value })}
            />
          </Field>
          <Field label="ALNS Iterations">
            <NumberInput
              value={settings.alnsIterations}
              min={1}
              step={50}
              onChange={(value) => updateSettings({ alnsIterations: value })}
            />
          </Field>
          <Field label="Random Seed">
            <input
              type="number"
              value={settings.randomSeed ?? ""}
              onChange={(event) =>
                updateSettings({
                  randomSeed:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Unserved Penalty">
            <NumberInput
              value={settings.unservedPenalty ?? 10000}
              min={0}
              step={100}
              onChange={(value) => updateSettings({ unservedPenalty: value })}
            />
          </Field>
          <Field label="Deadhead">
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={settings.includeDeadhead}
                onChange={(event) =>
                  updateSettings({ includeDeadhead: event.target.checked })
                }
              />
              include deadhead edges
            </label>
          </Field>
          <Field label="Allow Partial Service">
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={Boolean(settings.allowPartialService)}
                onChange={(event) =>
                  updateSettings({ allowPartialService: event.target.checked })
                }
              />
                enable unserved penalty
              </label>
            </Field>
          <Field label="Start Time">
            <input
              type="time"
              value={settings.startTime ?? "05:00"}
              onChange={(event) => updateSettings({ startTime: event.target.value })}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Planning Horizon (h)">
            <NumberInput
              value={settings.planningHorizonHours ?? 20}
              min={1}
              step={1}
              onChange={(value) => updateSettings({ planningHorizonHours: value })}
            />
          </Field>
          <Field label="Grid Flat Price (JPY/kWh)">
            <NumberInput
              value={settings.gridFlatPricePerKwh ?? 0}
              min={0}
              step={0.1}
              onChange={(value) => updateSettings({ gridFlatPricePerKwh: value })}
            />
          </Field>
          <Field label="Grid Sell Price (JPY/kWh)">
            <NumberInput
              value={settings.gridSellPricePerKwh ?? 0}
              min={0}
              step={0.1}
              onChange={(value) => updateSettings({ gridSellPricePerKwh: value })}
            />
          </Field>
          <Field label="Demand Charge (JPY/kW)">
            <NumberInput
              value={settings.demandChargeCostPerKw ?? 0}
              min={0}
              step={10}
              onChange={(value) => updateSettings({ demandChargeCostPerKw: value })}
            />
          </Field>
          <Field label="Diesel Price (JPY/L)">
            <NumberInput
              value={settings.dieselPricePerL ?? 0}
              min={0}
              step={1}
              onChange={(value) => updateSettings({ dieselPricePerL: value })}
            />
          </Field>
          <Field label="Depot Power Limit (kW)">
            <NumberInput
              value={settings.depotPowerLimitKw ?? 0}
              min={0}
              step={10}
              onChange={(value) =>
                updateSettings({ depotPowerLimitKw: value > 0 ? value : null })
              }
            />
          </Field>
          <Field label="Grid CO2 (kg/kWh)">
            <NumberInput
              value={settings.gridCo2KgPerKwh ?? 0}
              min={0}
              step={0.01}
              onChange={(value) => updateSettings({ gridCo2KgPerKwh: value })}
            />
          </Field>
          <Field label="CO2 Price (JPY/kg)">
            <NumberInput
              value={settings.co2PricePerKg ?? 0}
              min={0}
              step={0.1}
              onChange={(value) => updateSettings({ co2PricePerKg: value })}
            />
          </Field>
          <Field label="Experiment Method">
            <div className="space-y-2">
              <input
                type="text"
                list="experiment-method-options"
                value={settings.experimentMethod ?? ""}
                onChange={(event) =>
                  updateSettings({ experimentMethod: event.target.value || null })
                }
                placeholder="MILP / ALNS / MILP+ALNS / ABC / GA"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
              <datalist id="experiment-method-options">
                {EXPERIMENT_METHOD_SUGGESTIONS.map((method) => (
                  <option key={method} value={method} />
                ))}
              </datalist>
            </div>
          </Field>
        </div>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Fleet Templates
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  単一テンプレートでも混成 fleet でも同じ prepare API に渡します。
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => updateSettings({ fleetTemplates: [] })}
                  className={`rounded border px-3 py-1.5 text-xs ${
                    !usingMixedFleet
                      ? "border-primary-300 bg-primary-50 text-primary-700"
                      : "border-slate-200 bg-white text-slate-600"
                  }`}
                >
                  Single
                </button>
                <button
                  type="button"
                  onClick={() => enableMixedFleetMode()}
                  className={`rounded border px-3 py-1.5 text-xs ${
                    usingMixedFleet
                      ? "border-primary-300 bg-primary-50 text-primary-700"
                      : "border-slate-200 bg-white text-slate-600"
                  }`}
                >
                  Mixed
                </button>
              </div>
            </div>

            {!usingMixedFleet ? (
              <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700">
                <p>
                  {templateOptions.find((item) => item.id === settings.vehicleTemplateId)?.name ??
                    settings.vehicleTemplateId ??
                    "template not selected"}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  count {settings.vehicleCount} / initial SOC {settings.initialSoc}
                </p>
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                {(settings.fleetTemplates ?? []).map((item, index) => (
                  <div
                    key={`${item.vehicleTemplateId}-${index}`}
                    className="rounded-lg border border-slate-200 bg-white p-3"
                  >
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                      <Field label="Template">
                        <select
                          value={item.vehicleTemplateId}
                          onChange={(event) =>
                            updateFleetTemplateRow(index, {
                              vehicleTemplateId: event.target.value,
                            })
                          }
                          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                        >
                          {templateOptions.map((template) => (
                            <option key={template.id} value={template.id}>
                              {template.name}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Count">
                        <NumberInput
                          value={item.vehicleCount}
                          min={0}
                          onChange={(value) =>
                            updateFleetTemplateRow(index, { vehicleCount: value })
                          }
                        />
                      </Field>
                      <Field label="Initial SOC">
                        <NumberInput
                          value={item.initialSoc ?? settings.initialSoc}
                          min={0}
                          max={1}
                          step={0.05}
                          onChange={(value) =>
                            updateFleetTemplateRow(index, { initialSoc: value })
                          }
                        />
                      </Field>
                      <Field label="Battery kWh">
                        <NumberInput
                          value={item.batteryKwh ?? 0}
                          min={0}
                          step={1}
                          onChange={(value) =>
                            updateFleetTemplateRow(index, {
                              batteryKwh: value > 0 ? value : null,
                            })
                          }
                        />
                      </Field>
                      <Field label="Charge Power kW">
                        <div className="flex gap-2">
                          <NumberInput
                            value={item.chargePowerKw ?? 0}
                            min={0}
                            step={5}
                            onChange={(value) =>
                              updateFleetTemplateRow(index, {
                                chargePowerKw: value > 0 ? value : null,
                              })
                            }
                          />
                          <button
                            type="button"
                            onClick={() => removeFleetTemplateRow(index)}
                            className="rounded border border-rose-200 px-3 py-2 text-xs text-rose-700 hover:bg-rose-50"
                          >
                            Remove
                          </button>
                        </div>
                      </Field>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => addFleetTemplateRow()}
                  className="rounded border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-slate-50"
                >
                  Add vehicle template row
                </button>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  TOU Pricing
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  空なら flat price を使います。時刻は 0-24 時の整数で扱います。
                </p>
              </div>
              <button
                type="button"
                onClick={() => addTouBand()}
                className="rounded border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-slate-50"
              >
                Add band
              </button>
            </div>

            <div className="mt-3 space-y-3 text-sm text-slate-700">
              {(settings.touPricing ?? []).length === 0 ? (
                <p className="rounded-lg border border-slate-200 bg-white p-3 text-slate-600">
                  flat/default pricing
                </p>
              ) : (
                (settings.touPricing ?? []).map((item, index) => (
                  <div
                    key={`${item.start_hour}-${item.end_hour}-${item.price_per_kwh}-${index}`}
                    className="rounded-lg border border-slate-200 bg-white p-3"
                  >
                    <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
                      <Field label="Start Hour">
                        <NumberInput
                          value={item.start_hour}
                          min={0}
                          max={24}
                          step={1}
                          onChange={(value) =>
                            updateTouBand(index, { start_hour: value })
                          }
                        />
                      </Field>
                      <Field label="End Hour">
                        <NumberInput
                          value={item.end_hour}
                          min={0}
                          max={24}
                          step={1}
                          onChange={(value) =>
                            updateTouBand(index, { end_hour: value })
                          }
                        />
                      </Field>
                      <Field label="Price JPY/kWh">
                        <NumberInput
                          value={item.price_per_kwh}
                          min={0}
                          step={0.1}
                          onChange={(value) =>
                            updateTouBand(index, { price_per_kwh: value })
                          }
                        />
                      </Field>
                      <div className="flex items-end">
                        <button
                          type="button"
                          onClick={() => removeTouBand(index)}
                          className="rounded border border-rose-200 px-3 py-2 text-xs text-rose-700 hover:bg-rose-50"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      {formatTouHour(item.start_hour)} - {formatTouHour(item.end_hour)} /{" "}
                      {item.price_per_kwh} JPY/kWh
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <Field label="Experiment Notes">
            <textarea
              value={settings.experimentNotes ?? ""}
              onChange={(event) =>
                updateSettings({ experimentNotes: event.target.value || null })
              }
              rows={4}
              placeholder="論文・報告用に、仮説、比較条件、備考を記録します。"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </Field>
        </div>
      </PageSection>

      <PageSection
        title="Step 3 Prepare and Run"
        description="prepare で selected shard だけを canonical input 化し、ready になったら simulation を開始します。"
        actions={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void handlePrepare()}
              disabled={prepareDisabled}
              className="rounded bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {prepareMutation.isPending ? "Preparing..." : "入力データ作成"}
            </button>
            <button
              type="button"
              onClick={() => void handleRun()}
              disabled={runDisabled}
              className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {runPreparedMutation.isPending ? "Starting..." : "シミュレーション開始"}
            </button>
            <button
              type="button"
              onClick={() => void handleRunOptimization()}
              disabled={runOptimizationDisabled}
              className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-50"
            >
              {runOptimizationMutation.isPending ? "Starting..." : "最適化開始"}
            </button>
          </div>
        }
      >
        <BackendJobPanel job={activeJob} />
        <BackendJobPanel job={optimizationJob} className="mt-3" />

        {!canRun ? (
          <div className="mb-4 rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
            {runReadinessReason ?? "Built dataset が未準備のため simulation を実行できません。"}
          </div>
        ) : null}

        {runOptimizationMutation.error ? (
          <div className="mt-3">
            <ErrorBlock message={runOptimizationMutation.error.message} />
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-4">
          <InfoCard label="Selected Depot" value={selectedDepotId || "-"} />
          <InfoCard label="Selected Routes" value={String(selectedRouteCount)} />
          <InfoCard label="Estimated Trips" value={selectedTripCount.toLocaleString()} />
          <InfoCard label="Prepared" value={preparedResult?.preparedInputId ?? "not yet"} />
        </div>

        {prepareMutation.error ? (
          <div className="mt-4">
            <ErrorBlock message={prepareMutation.error.message} />
          </div>
        ) : null}

        {preparedResult ? (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="grid gap-4 md:grid-cols-3">
              <InfoCard label="Trip Count" value={preparedResult.tripCount.toLocaleString()} />
              <InfoCard label="Timetable Rows" value={preparedResult.timetableRowCount.toLocaleString()} />
              <InfoCard label="Ready" value={preparedResult.ready ? "yes" : "no"} />
            </div>
            {preparedResult.warnings.length ? (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {preparedResult.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2 text-xs">
              <Link
                to={`/scenarios/${scenario.id}/simulation`}
                className="rounded border border-slate-200 bg-white px-3 py-2 text-slate-600 hover:bg-slate-50"
              >
                Legacy simulation view
              </Link>
              <Link
                to={`/scenarios/${scenario.id}/results/dispatch`}
                className="rounded border border-slate-200 bg-white px-3 py-2 text-slate-600 hover:bg-slate-50"
              >
                Results
              </Link>
              <Link
                to={`/scenarios/${scenario.id}/optimization`}
                className="rounded border border-slate-200 bg-white px-3 py-2 text-slate-600 hover:bg-slate-50"
              >
                Optimization view
              </Link>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState
              title="まだ prepared input はありません"
              description="営業所・路線・条件を確定したら「入力データ作成」を押してください。"
            />
          </div>
        )}
      </PageSection>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      {children}
    </div>
  );
}

function NumberInput({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={Number.isFinite(value) ? value : 0}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
    />
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-700 break-all">
        {value}
      </p>
    </div>
  );
}

function IncompleteArtifactBanner({
  scenarioId,
  message,
}: {
  scenarioId: string;
  message: string;
}) {
  const navigate = useNavigate();
  const deleteMutation = useDeleteScenario();

  async function handleDelete() {
    if (!window.confirm("このシナリオを削除して一覧に戻りますか？")) {
      return;
    }
    try {
      await deleteMutation.mutateAsync(scenarioId);
      navigate("/scenarios");
    } catch {
      navigate("/scenarios");
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-xl text-amber-500" aria-hidden>
            ⚠️
          </span>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-amber-900">
              シナリオの保存が中断されました
            </h2>
            <p className="mt-1 text-sm text-amber-800">
              前回の保存処理が途中で中断されたため、このシナリオは使用できない状態です。削除して再作成してください。
            </p>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-amber-700 hover:text-amber-900">
                技術的な詳細
              </summary>
              <pre className="mt-2 overflow-auto rounded bg-amber-100 px-3 py-2 text-xs text-amber-800">
                {message}
              </pre>
            </details>
          </div>
        </div>
        <div className="mt-5 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={deleteMutation.isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleteMutation.isPending ? "削除中..." : "削除して一覧に戻る"}
          </button>
          <button
            type="button"
            onClick={() => navigate("/scenarios")}
            className="rounded-md border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-50"
          >
            一覧に戻る
          </button>
        </div>
      </div>
    </div>
  );
}
