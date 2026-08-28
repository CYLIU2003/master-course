# SUNNY/RAIN pure-ICE aggregation comparison

- fixed controls match: `True`
- PV hashes differ: `True`
- scope: descriptive, median over five completed runs per representation.

| Representation | Metric | SUNNY median | RAIN median | RAIN - SUNNY |
|---|---|---:|---:|---:|
| discrete | bev_trip_count | 46.0 | 46.0 | 0.0 |
| discrete | ice_trip_count | 218.0 | 218.0 | 0.0 |
| discrete | used_bev_vehicle_count | 14.0 | 14.0 | 0.0 |
| discrete | used_ice_vehicle_count | 18.0 | 18.0 | 0.0 |
| discrete | total_cost_jpy | 707349.1733696415 | 707349.1733696415 | 0.0 |
| discrete | fuel_liters | 441.3853152654867 | 441.3853152654867 | 0.0 |
| discrete | grid_import_kwh | 0.0 | 0.0 | 0.0 |
| discrete | pv_to_bus_kwh | 3.855033402289651 | 102.6164598316493 | 98.76142642935964 |
| discrete | pv_to_bess_kwh | 582.4895923300704 | 473.0586395871641 | -109.4309527429063 |
| discrete | bess_to_bus_kwh | 525.6968570777005 | 426.93542222729485 | -98.76143485040569 |
| discrete | pv_curtail_kwh | 5469.905374267641 | 420.5249005811866 | -5049.380473686454 |
| discrete | peak_grid_kw | 0.0 | 0.0 | 0.0 |
| discrete | minimum_bev_soc_kwh | 101.772424 | 101.772425 | 9.999999974752427e-07 |
| discrete | terminal_bev_soc_kwh_total | 2738.7111520000003 | 2738.711148 | -4.000000444648322e-06 |
| discrete | terminal_bess_soc_kwh_total | 3000.0 | 3000.0 | 0.0 |
| discrete | incumbent_objective_jpy | 707349.1733696415 | 707349.1733696415 | 0.0 |
| discrete | certified_best_bound_jpy | 640000.0 | 695632.9381236411 | 55632.93812364107 |
| discrete | certified_gap_ratio | 0.09521347575597812 | 0.01656358088352197 | -0.07864989487245615 |
| discrete | total_solver_time_sec | 30.753999948501587 | 31.88700008392334 | 1.133000135421753 |
| pure_aggregate | bev_trip_count | 46.0 | 46.0 | 0.0 |
| pure_aggregate | ice_trip_count | 218.0 | 218.0 | 0.0 |
| pure_aggregate | used_bev_vehicle_count | 14.0 | 14.0 | 0.0 |
| pure_aggregate | used_ice_vehicle_count | 18.0 | 18.0 | 0.0 |
| pure_aggregate | total_cost_jpy | 707349.1733696415 | 707349.1733696415 | 0.0 |
| pure_aggregate | fuel_liters | 441.3853152654867 | 441.3853152654867 | 0.0 |
| pure_aggregate | grid_import_kwh | 0.0 | 0.0 | 0.0 |
| pure_aggregate | pv_to_bus_kwh | 3.855033402289651 | 102.6164598316493 | 98.76142642935964 |
| pure_aggregate | pv_to_bess_kwh | 582.4895923300704 | 473.0586395871641 | -109.4309527429063 |
| pure_aggregate | bess_to_bus_kwh | 525.6968570777005 | 426.93542222729485 | -98.76143485040569 |
| pure_aggregate | pv_curtail_kwh | 5469.905374267641 | 420.5249005811866 | -5049.380473686454 |
| pure_aggregate | peak_grid_kw | 0.0 | 0.0 | 0.0 |
| pure_aggregate | minimum_bev_soc_kwh | 101.772424 | 101.772425 | 9.999999974752427e-07 |
| pure_aggregate | terminal_bev_soc_kwh_total | 2738.7111520000003 | 2738.711148 | -4.000000444648322e-06 |
| pure_aggregate | terminal_bess_soc_kwh_total | 3000.0 | 3000.0 | 0.0 |
| pure_aggregate | incumbent_objective_jpy | 707349.1733696413 | 707349.1733696413 | 0.0 |
| pure_aggregate | certified_best_bound_jpy | 640000.0 | 695632.9381236411 | 55632.93812364107 |
| pure_aggregate | certified_gap_ratio | 0.09521347575597783 | 0.016563580883521646 | -0.07864989487245619 |
| pure_aggregate | total_solver_time_sec | 435.10599994659424 | 435.103000164032 | -0.0029997825622558594 |
