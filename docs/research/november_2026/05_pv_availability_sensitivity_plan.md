# PV利用可能量感度（P1）

## 目的

天候分類の効果ではなく、同一の2025-08-05 WEEKDAY運行、fleet、chargers、BESS、tariff、solver controlに対するPV利用可能量のモデル応答を記述する。

## 水準

| 水準 | 定義 | provenance |
| --- | --- | --- |
| LOW | 正本2025-08-10由来の低PV曲線 | observed-source counterfactual |
| MEDIUM | 各15分slotで `0.5 * (LOW + HIGH)` | synthetic interpolation |
| HIGH | 正本2025-08-05由来の高PV曲線 | observed-source baseline |

MEDIUMは「典型日」「曇天」「観測日」と呼ばない。LOW/HIGHの原データ、slot順、単位が一致しない場合は生成を停止する。

## 固定hash gate

3水準間で以下を一致させる。

- timetable/trip、service date/id、operator
- active fleet、vehicle parameter、initial state
- charger、BESS、tariff、cost flags/objective
- seed、threads、time limits、MIP gap、Rolling controls

異なってよいのはPV slot列、PV source label、PV hash、Prepared IDだけである。正本scenarioまたは既存Prepared JSONを上書きしない。

## 指標

使用BEV/ICE、BEV/ICE便数、winner hash、day-ahead cost、executed-day accounting cost、grid import、PV direct use、PV-to-BESS、BESS-to-bus、curtailment、peak grid、minimum/terminal SOCを記録する。

## 成功条件

- 3水準すべて264/264、物理VALID、Rolling 24/24、会計PASS、no fallback/repair。
- 固定非PV hashが完全一致。
- MEDIUM生成式と3曲線hashを保存。

失敗条件は、正当性gate失敗、非PV drift、MEDIUMのprovenance欠落、またはgap/terminationを隠した比較である。

## 実行可能性

LOW/HIGHを扱う既存frontend runnerはあるが、MEDIUM 15分曲線の生成・添付・hash照合を同一fail-closed経路で扱わない。したがって `REQUIRES_SMALL_ADAPTER`。P0完了前には実装もしない。実行後も3水準の単調性や天候一般化を保証せず、固定3曲線の記述的感度だけを主張する。
