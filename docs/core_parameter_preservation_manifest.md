# Core Parameter Preservation Manifest

Purpose
- Ensure no optimization-relevant parameter is dropped during core packaging.
- Applies to MILP, ALNS, hybrid, route/depot scope, vehicle/template, tariff, emissions, and objective controls.

Critical parameter groups to preserve

1) Solver mode and limits
- mode / solverMode
- time_limit_seconds / timeLimitSeconds
- mip_gap / mipGap
- alns_iterations / alnsIterations
- random_seed / randomSeed

2) Objective and penalty controls
- objective_mode / objectiveMode
- allow_partial_service / allowPartialService
- unserved_penalty / unservedPenalty
- objective_weights (scenario overlay and related config paths)

3) Scope and routing controls
- selectedDepotIds / selected_depot_ids
- selectedRouteIds / selected_route_ids
- dayType / day_type / service_id
- service_date / serviceDate
- include_short_turn / includeShortTurn
- include_depot_moves / includeDepotMoves
- include_deadhead / includeDeadhead
- allow_intra_depot_route_swap / allowIntraDepotRouteSwap
- allow_inter_depot_swap / allowInterDepotSwap

4) Vehicle and template controls
- vehicle_template_id / vehicleTemplateId
- fleet_templates
- vehicle_count / vehicleCount
- initial_soc / initialSoc
- battery_kwh / batteryKwh
- charge_power_kw / chargerPowerKw
- charger_count / chargerCount
- type, modelCode, modelName, capacityPassengers
- energyConsumption, fuelTankL, fuelEfficiencyKmPerL
- co2EmissionGPerKm, co2EmissionKgPerL
- curbWeightKg, grossVehicleWeightKg
- engineDisplacementL, maxTorqueNm, maxPowerKw
- acquisitionCost, enabled
- minSoc, maxSoc

5) Tariff, power, and emissions controls
- grid_flat_price_per_kwh / gridFlatPricePerKwh
- grid_sell_price_per_kwh / gridSellPricePerKwh
- demand_charge_cost_per_kw / demandChargeCostPerKw
- diesel_price_per_l / dieselPricePerL
- grid_co2_kg_per_kwh / gridCo2KgPerKwh
- co2_price_per_kg / co2PricePerKg
- depot_power_limit_kw / depotPowerLimitKw
- tou_pricing

6) Run preparation / execution contracts
- prepared_input_id
- source for prepared simulation run
- optimization capabilities and simulation capabilities payloads

Required files and contracts to keep
- bff/routers/optimization.py
- bff/routers/simulation.py
- bff/routers/scenarios.py
- bff/services/run_preparation.py
- bff/mappers/scenario_to_problemdata.py
- src/pipeline/solve.py
- src/dispatch/**
- src/optimization/**
- config/experiment_config.json
- config/core_master_data.json
- config/objective_flags.json
- data/built/tokyu_core/manifest.json
- data/built/tokyu_core/routes.parquet
- data/built/tokyu_core/trips.parquet
- data/built/tokyu_core/timetables.parquet
- data/built/tokyu_core/stops.parquet

Packaging guardrail
- Any cleanup step must run a grep/contract check confirming all above fields and files remain available.
