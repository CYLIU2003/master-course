# Route Cost Simulation Summary: demo_2ev_1eng

## Simulation Settings
- Time resolution: 30 min
- Horizon: 24.0 hours (48 slots)
- Diesel price: ¥150.0/L
- Flat TOU rate: ¥25.0/kWh

## Fleet

| vehicle_id | type | trips | fuel_L | energy_kWh | soc_min | capex_yen/day |
|---|---|---:|---:|---:|---:|---:|
| ev_01 | ev_bus | 3 | 0.00 | 79.80 | 0.9 | 12,500 |
| ev_02 | ev_bus | 3 | 0.00 | 80.40 | 0.9 | 12,500 |
| eng_hino_rep | engine_bus | 1 | 4.46 | 0.00 | — | 6,389 |

## Trip Assignments

| trip_id | vehicle_id | route_id | start | end | distance_km |
|---|---|---|---|---|---:|
| T001 | ev_01 | R01 | 06:00 | 07:30 | 25.00 |
| T002 | ev_02 | R01 | 06:15 | 07:45 | 25.00 |
| T003 | ev_01 | R02 | 07:30 | 08:30 | 19.50 |
| T004 | ev_01 | R01 | 10:00 | 11:30 | 22.00 |
| T005 | ev_02 | R02 | 11:00 | 12:00 | 18.00 |
| T006 | ev_02 | R01 | 16:30 | 18:00 | 24.00 |
| T007 | eng_hino_rep | R01 | 17:00 | 18:30 | 24.00 |
| T008 | **UNASSIGNED** | R02 | 17:30 | 18:30 | 18.00 |

## Cost Breakdown

| Item | Amount (¥) |
|---|---:|
| Vehicle capex (daily) | 31,389 |
| Fuel cost | 669 |
| Electricity cost (TOU) | 682 |
| Demand charge | 108,000 |
| Contract excess | 0 |
| Grid basic charge | 0 |
| **Total cost** | **140,740** |

- Peak grid demand: 72.0 kW
- Total grid purchase: 37.9 kWh
- Total fuel consumption: 4.5 L
- Unassigned trips: 1