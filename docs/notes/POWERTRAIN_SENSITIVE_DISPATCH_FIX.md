# Powertrain-sensitive dispatch fix

## Status

The 2026-07-31 flat-tariff sunny/rainy pair is **not evidence that the
model endogenously selected the same BEV/ICE fleet composition**.

The result bundle reports code SHA
`da26b06c617256f27b08b4123a46169e185a833a`, while the current GitHub
`main` branch ends at an older commit.  The exact solver implementation used
for the pair must therefore be pushed before this document's Stage-1/Stage-2
changes are merged into the execution path.

## What the pair actually shows

The two final runs use the following common scenario inputs:

- flat grid energy price: 30 JPY/kWh;
- demand-charge weight: 0;
- BEV traction energy: 1.316 kWh/km;
- charging efficiency used for the static audit: 0.95;
- ICE fuel efficiency: 4.52 km/L;
- diesel price: 150 JPY/L;
- grid emission factor: 0.5 kg-CO2/kWh;
- diesel emission factor: 2.585895 kg-CO2/L;
- used-vehicle charge: 20,000 JPY per vehicle-day.

These values imply:

- grid-powered BEV energy cost: about 41.56 JPY/km;
- ICE fuel cost: about 33.19 JPY/km;
- energy-only break-even grid price: about 23.96 JPY/kWh;
- grid-powered BEV emissions: about 0.693 kg-CO2/km;
- ICE emissions: about 0.572 kg-CO2/km.

Consequently, a 30 JPY/kWh tariff does **not** make grid-powered BEV
operation cheaper under the current vehicle parameters.  Removing the demand
charge affects peak-power economics; it does not reverse the per-kilometre
energy-cost ordering.  With the current grid-emission factor, a positive carbon
price also does not make grid-only BEV operation preferable.  Sunny-day PV and
PV-charged BESS energy can still make individual BEV duties attractive.

The larger structural problem is candidate coverage.  Each run contains 21
Stage-1/Stage-2 candidates, but every candidate uses 13 BEVs and 19 ICE buses.
Trip counts vary only between 43/221 and 44/220.  The search therefore changes
which trips are assigned to each powertrain while keeping the used fleet
composition fixed.

## Required solver changes

### 1. Represent vehicle activation explicitly

Add a binary variable for each vehicle and service day:

```text
used[v,d] in {0,1}
```

Link assignment to activation:

```text
y[v,i] <= used[v,day(i)]
used[v,d] <= sum_{i in day d} y[v,i]
```

Charge `vehicle_usage_cost_jpy_per_used_bus` once per active vehicle-day in the
same solver objective used to rank Stage-1 candidates.  Do not multiply this
cost by trip count.  The canonical accounting ledger must use the same
activation semantics.

### 2. Put powertrain-sensitive operating cost in Stage 1

Stage 1 must not rank assignments using only a distance proxy or a fixed
powertrain bias.  For each BEV duty, include either:

1. assignment-linked time-indexed charging/PV/BESS recourse; or
2. a certified lower-bound approximation that depends on duty energy,
   charging windows, initial SOC, available PV/BESS energy, and grid price.

ICE duty cost must use the same trip/deadhead distance and the canonical fuel
consumption coefficient.  Any approximation must be recorded separately from
the exact Stage-2 canonical cost.

### 3. Generate count-changing candidates

The candidate pool must contain feasible alternatives with different aggregate
fleet compositions.  After the incumbent is found, solve additional bounded
problems such as:

```text
sum_{v in BEV} used[v] >= incumbent_used_bev + 1
sum_{v in BEV} used[v] <= incumbent_used_bev - 1
```

Repeat for at least two deltas when feasible and within the global time budget.
Also add neighbourhood moves that activate an unused BEV and retire an ICE
vehicle, rather than only swapping duties one-for-one between already-used
vehicles.

A result may claim endogenous fleet-composition choice only when the exported
candidate table contains at least two feasible `(used_bev, used_ice)` pairs, or
when infeasibility of all adjacent compositions is certified.

### 4. Break vehicle symmetry without hiding SOC differences

Within groups of truly equivalent vehicles, order activation variables to
reduce symmetric solutions.  Vehicles with different initial SOC, battery
capacity, charging power, availability, or depot must not be treated as
symmetric.  A practical ordering is descending usable initial energy, then
vehicle ID.

### 5. Align solver and accounting objectives

For a research run with `objective_mode=total_cost`, release must fail closed
when any of the following is true:

- `solver_objective_matches_accounting_total` is false;
- `objective_is_actual_cost` is false without an explicitly documented
  surrogate-objective claim scope;
- the selected Stage-2 canonical cost differs from the exported total beyond
  the accounting tolerance.

The rainy run in the supplied pair has an objective/accounting difference of
about 22.29 JPY and must remain blocked until reconciled.

### 6. Keep policy scenarios explicit

Do not add an undocumented BEV preference coefficient.  Compare at least these
controlled scenarios instead:

- tariff sensitivity: 20, 24, and 30 JPY/kWh;
- used-vehicle cost sensitivity: 0, 5,000, and 20,000 JPY/vehicle-day;
- optional policy case with an explicitly named ICE externality or carbon cost;
- sunny/rainy PV profiles with all non-weather inputs frozen.

At 30 JPY/kWh, a higher BEV share should not be assumed in advance.  It must be
supported by PV/BESS availability, charging feasibility, or an explicit policy
cost.

## Acceptance tests

1. A synthetic instance with one feasible ICE-to-unused-BEV replacement must
   export candidates with at least two used-powertrain compositions.
2. At 30 JPY/kWh with the current vehicle coefficients and no PV, the model must
   not assert that BEV has lower marginal energy cost.
3. At a grid tariff below the calculated break-even value, the cost ordering
   must reverse when all other inputs are held constant.
4. Changing only the PV profile must be sufficient to alter the preferred
   powertrain mix in a constructed instance where PV energy is binding.
5. Vehicle-day cost must equal `used vehicle-days × configured unit cost` in
   both solver objective and canonical accounting.
6. Research release must be blocked when candidate fleet composition is frozen
   without an adjacent-composition infeasibility certificate.
7. Research release must be blocked on solver/accounting objective mismatch.

## Audit command

After extracting a pair of run directories:

```bash
python scripts/audit_flat_tariff_powertrain_pair.py \
  output/run_sunny \
  output/run_rainy \
  --output-dir output/powertrain_pair_audit
```

A non-zero exit status means that research-release blockers remain.
