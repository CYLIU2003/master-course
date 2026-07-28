# Scenario Fleet Contract v2

Status: **CURRENT**

## Authority

A formal run does not use a global BEV/ICE count. Its authoritative fleet is
the exact active vehicle set obtained from:

```text
materialized prepared scenario
  -> explicitly selected depot / dispatch scope
  -> strict raw-record validation
  -> availability normalization
  -> exact active vehicle records
  -> CanonicalOptimizationProblem.vehicles
```

The mutable scenario store is not the run-time authority after Prepare. A
formal run must be reproducible from its materialized prepared input.

## Required identity and parameter evidence

`scenario_fleet_contract_v2` records:

- selected depot IDs;
- every persisted vehicle ID in scope;
- the exact active vehicle ID set;
- excluded records and exclusion reasons;
- inventory by canonical powertrain and vehicle type;
- active-vehicle-ID hash;
- initial-state hash;
- vehicle-parameter hash;
- complete fleet-contract hash.

Equal BEV/ICE counts do not imply equal experimental input. Different vehicle
IDs, initial SOC/fuel, capacity, consumption, charge limit, compatibility,
depot, or availability produce a different contract.

## Formal validation

Before Canonical vehicle construction, a formal run rejects:

- empty or duplicate vehicle IDs;
- empty vehicle type/powertrain or unsupported powertrain;
- missing depot;
- unparseable availability;
- contradictory `available` / `availability` / `enabled` values;
- BEV records without explicit initial SOC, positive battery capacity,
  positive energy consumption, positive charge power, or a declared charger
  compatibility set;
- ICE records without explicit initial fuel, positive tank capacity, or
  positive fuel consumption;
- count-only fleet input that was not expanded into explicit records during
  Prepare.

Unavailable, disabled, or maintenance vehicles may remain persisted. They are
excluded from the active set with a recorded reason; their mere presence is
not an error. A Prepare/run contract-hash change is an error.

## Canonical normalization

The only supported availability tokens are:

- true: `true`, `1`, `"true"`, `"1"`, `"yes"`, `"on"`;
- false: `false`, `0`, `"false"`, `"0"`, `"no"`, `"off"`.

All other values fail a formal run.

Powertrain resolution is shared by BFF preflight, ProblemBuilder, reporting,
comparison, Rolling, and policy sensitivity. Model-specific vehicle types are
resolved through the scenario vehicle-type catalog. Catalog-provided battery,
consumption, charge-power, and compatibility fields are materialized into the
canonical active record and included in the hash. The optimizer uses the
canonical BEV/ICE powertrain class while the fleet artifact preserves the raw
model/type. Unsupported PHEV/FCEV records are not silently folded into BEV or
ICE.

The persisted formal artifact includes the raw source records and catalog
records used to calculate the parameter hash, so it can be recomputed
independently after the run.

## Optional assertions

`--assert-bev-count` and `--assert-ice-count` only verify counts derived from
the contract. They never generate, delete, select, or redefine vehicles. Their
default is unset.

`--require-all-available-bevs` is a separate policy sensitivity. It derives its
lower bound from the active BEV set and is not the cost-minimizing baseline.

`--available-bev-count` changes the active set and is therefore allowed only
with `--day-ahead-only-exploratory`. It cannot complete a formal release.
