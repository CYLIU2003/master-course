# 仮定・パラメータ・単位

## 固定条件

| 区分 | 値 | 単位 | 意味 | 正本 / JSON field | 性格 | 感度候補 |
| --- | ---: | --- | --- | --- | --- | --- |
| 営業所 | tsurumaki | - | 対象営業所 | `result_summary.protocol.depot_id` | 実験固定 | 複数営業所はP2 |
| service | WEEKDAY | - | 固定平日時刻表 | `protocol.service_id` | 実データ | 非対象 |
| 運行日 | 2025-08-05 | 日付 | 両ケース共通のservice date | `protocol.service_date` | 実データ | 複数日はP2 |
| 便・路線 | 264・16 | 便・路線 | 全便と路線数 | `trip_count`; `optimization_parameters` | 実データ | 非対象 |
| 内部刻み | 15 | 分 | 96スロット | `time_step_minutes` | モデル仮定 | 30/60分はP1 |
| Rolling | 60 | 分 | 1回に実行する時間 | `rolling_execution_minutes` | モデル仮定 | P1 |
| active fleet | BEV 35 / ICE 25 | 台 | Prepare時の60台 | `scenario_fleet_contract_v2` | 実入力 | BEV比率はP1 |
| BEV電池 | 314 | kWh/台 | 定格容量 | fleet contract | 実入力 | P1 |
| BEV電費 | 1.316 | kWh/km | 走行消費率 | fleet contract | 仮定値 | +10/+20%はP1 |
| BEV初期SOC | 21.9452～77.4330 | % | 車両別初期値の範囲 | fleet contract | 実入力 | -5ptはP2 |
| BEV SOC | 20～90 | % | 許容範囲 | fleet contract | 仮定 | 指導教員確認 |
| BEV終端 | return_to_initial | - | 車両別初期値へ戻す | `summary.interactive_terminal_soc_controls` | 比較公平性条件 | P1 |
| ICE tank | 160 | L/台 | 燃料タンク | fleet contract | 実入力 | 非対象 |
| ICE初期燃料 | 144 | L/台 | 初期量 | fleet contract | 仮定/入力 | P2 |
| ICE燃費 | 4.52 | km/L | 燃料消費換算 | fleet contract | 実入力 | +10%消費はP1 |
| 充電器 | 90×10 | kW・基 | 各1ポート | `scenario_input_snapshot.chargers` | 設備仮定 | 6/8/10基はP1 |
| 双方向充放電 | OFF | - | V2Gなし | charger `bidirectional=false` | 設備条件 | V2GはP2 |
| 受電上限 | 200 | kW | 営業所受電上限 | depot `import_limit_kw` | 設備仮定 | P1 |
| PV定格 | 1000 | kW | installed rating | energy asset | 設備仮定 | -20%はP1 |
| BESS | 6000 / 900 | kWh / kW | 容量・出力 | energy asset | 設備仮定 | BESSなしはP1 |
| BESS SOC | 1200～4800 | kWh | 許容範囲 | energy asset | 設備仮定 | P1 |
| BESS初期・終端 | 3000 / 3000 | kWh | 代表日境界 | energy asset | 比較仮定 | P1 |
| BESS効率 | 95 / 95 | % | 充電・放電効率 | energy asset | 仮定 | P2 |
| 電力単価 | 30 | 円/kWh | flat tariff | tariff | 仮定 | +20%はP1 |
| 軽油単価 | 150 | 円/L | 燃料費換算 | scenario snapshot | 仮定 | +20%はP1 |
| 車両使用費 | 20000 | 円/台日 | 使用車両日費用 | scenario snapshot | 仮定 | P1 |
| CO2価格 | 1 | 円/kg | 貨幣換算 | scenario snapshot | 仮定 | P2 |
| 需要料金 | 0 / 0 | 円/kW | on/off peak | scenario snapshot | ゼロ設定 | 将来追加 |
| solver | Gurobi 13.0.1 | - | backend | `result_summary.environment` | 実環境 | 非対象 |
| total / S1 / S2上限 | 585 / 435 / 30 | 秒 | solver limits | optimization parameters | 実験固定 | P1 |
| requested gap | 10 | % | Stage 1要求値 | `requested_mip_gap_ratio` | 実験固定 | 1%は判断事項 |
| seed / threads | 42 / 1 | - / thread | 再現条件 | optimization parameters | 実験固定 | seed反復はP1 |
| 候補 / radius | 22 / 4 | 件 / 台 | 実効候補探索 | optimization parameters | 探索仮定 | P0/P1 |
| BEV frontier | 15～35, ON | 台 | composition探索 | optimization parameters | 探索仮定 | P0/P1 |
| frontier上限 | 120 | 秒 | 候補探索時間 | optimization parameters | 探索仮定 | P1 |

## SUNNYとRAINで異なる入力

SUNNYは2025-08-05由来のPV曲線（hash `65213b...`）、RAINは2025-08-10由来の低PV曲線（hash `0d0711...`）を2025-08-05のWEEKDAY運行へ適用する。RAINは日曜ダイヤの観測運行ではない。固定非PV入力hashは一致する。

## 費用に含まれないもの

設備投資、PV/BESS資本費、運転士費、電池劣化費、保守費、需要料金は正本評価額へ実質的に含まれない。このため評価額を実支出、LCC、導入採算と解釈しない。
