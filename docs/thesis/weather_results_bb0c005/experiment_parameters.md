# experiment_parameters

| 区分 | 項目 | 共通値 | SUNNY | RAIN | 単位 | 正本 |
| --- | --- | --- | --- | --- | --- | --- |
| 運行 | 営業所 | tsurumaki |  |  | - | result_summary.json |
| 運行 | 時刻表 | WEEKDAY |  |  | - | result_summary.json |
| 運行 | 運行日 | 2025-08-05 |  |  | 日付 | result_summary.json |
| 運行 | 便数 | 264 |  |  | 便 | result_summary.json |
| 運行 | 路線数 | 16 |  |  | 路線 | optimization_parameters.json |
| 運行 | 内部時間刻み | 15 |  |  | 分 | result_summary.json |
| 運行 | Rolling実行間隔 | 60 |  |  | 分 | result_summary.json |
| 反実仮想 | 気象・PV条件 |  | 2025-08-05由来のPV曲線 | 2025-08-10由来の低PV曲線 | - | optimization_parameters.json |
| 車両 | 有効車両数 | 60 |  |  | 台 | scenario_fleet_contract_v2 |
| 車両 | BEV／ICE在庫 | 35／25 |  |  | 台 | scenario_fleet_contract_v2 |
| 車両 | BEV初期SOC範囲 | 21.9452～77.4330 |  |  | % | scenario_fleet_contract_v2 |
| 車両 | BEV電池容量 | 314 |  |  | kWh/台 | scenario_fleet_contract_v2 |
| 車両 | BEV電費 | 1.316 |  |  | kWh/km | scenario_fleet_contract_v2 |
| 車両 | BEV最大充電電力 | 90 |  |  | kW/台 | scenario_fleet_contract_v2 |
| 車両 | BEV SOC範囲 | 20～90 |  |  | % | scenario_fleet_contract_v2 |
| 車両 | ICE燃料タンク | 160 |  |  | L/台 | scenario_fleet_contract_v2 |
| 車両 | ICE燃費 | 4.52 |  |  | km/L | scenario_fleet_contract_v2 |
| 車両 | ICE初期燃料 | 144 |  |  | L/台 | scenario_fleet_contract_v2 |
| 充電 | 充電器数 | 10 |  |  | 基 | result_summary.json |
| 充電 | BEVごとの互換充電器数 | 10 |  |  | 基 | scenario_fleet_contract_v2 |
| 充電 | 受電上限 | 正本bundleに明示値なし |  |  | - | 欠落を明示 |
| PV | 実行日PV発電量 |  | 6056.25 | 996.2 | kWh | executed_day_accounting.json |
| PV | PV定格容量 | 正本bundleに明示値なし |  |  | - | 欠落を明示 |
| BESS | 初期／終端SOC | 3000／3000 |  |  | kWh | executed_day_accounting.json |
| BESS | 観測された充放電比 | 90.25 |  |  | % | executed_day_accounting.jsonから算出 |
| BESS | 定格容量／出力 | 正本bundleに明示値なし |  |  | - | 欠落を明示 |
| 料金 | 系統購入単価 | 30 |  |  | 円/kWh | executed_day_accounting.jsonから算出 |
| 料金 | 軽油単価 | 150 |  |  | 円/L | optimization_parameters.json |
| 料金 | 車両使用費 | 20000 |  |  | 円/台日 | optimization_parameters.json |
| 料金 | CO₂価格 | 1 |  |  | 円/kg | optimization_parameters.json |
| 料金 | 需要料金（on/off peak） | 0／0 |  |  | 円/kW | optimization_parameters.json |
| Solver | 方式 | phase3_two_stage |  |  | - | optimization_parameters.json |
| Solver | 総／Stage 1／Stage 2上限 | 585／435／30 |  |  | 秒 | optimization_parameters.json |
| Solver | 要求MIP gap | 10 |  |  | % | optimization_parameters.json |
| Solver | seed | 42 |  |  | - | optimization_parameters.json |
| Solver | Gurobi threads | 1 |  |  | thread | optimization_parameters.json |
| Solver | BestObjStop | OFF |  |  | - | optimization_parameters.json |
| Solver | powertrain selector strengthening | OFF |  |  | - | optimization_parameters.json |
| Solver | Stage 1→2候補上限（実効） | 22 |  |  | 候補 | optimization_parameters.json |
