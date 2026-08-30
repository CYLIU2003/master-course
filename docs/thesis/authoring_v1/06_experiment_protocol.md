# 実験プロトコル

## 比較設計

同一の2025-08-05 WEEKDAY運行へ、SUNNY曲線と2025-08-10由来の低PV曲線を与える固定入力反実仮想である。独立変数はPV曲線、従属変数は有限候補内の配車、車両構成、電力フロー、燃料、評価額、gapである。

## 入力固定gate

- Scenario ID: SUNNY `771d115b-75b0-49f7-a7f0-25f259a2cd21`、RAIN `b23fd26c-1233-4c73-bb9e-bdb8b1584760`
- Fresh Prepared IDとprepared source SHA-256を保存する。
- timetable、vehicle、fleet contract、charger、BESS、tariff、objective、seed、threads、time limitを比較する。
- `fixed_weekday_timetable_pv_counterfactual`を維持する。
- fallback、repair、synthetic PV、optimization proxyを許さない。

## 実行順

1. clean SHA `bb0c005...`をtag固定する。
2. 両ScenarioをFresh Prepareする。
3. public BFF `run-optimization`から`phase3_two_stage`を別processで実行する。
4. Stage 1で候補を作り、各固定配車へStage 2 recourseを適用する。
5. day-ahead選択後、固定配車で24回Rollingする。
6. 24個の実行prefixを96スロットへつなぎ、費用を1回だけ再計算する。
7. 物理、Rolling、会計、provenance gateを独立に判定する。

## 正当性受理条件

- 264/264便、未担当0
- `arrival + turnaround + deadhead <= next departure`
- BEV/ICE状態、充電器、受電、PV/BESS収支の物理検算PASS
- Rolling 24/24 accepted
- accounting reconciliationが1e-6円以内
- Git SHA、Prepared ID、source hashが一致
- fallback/repairなし

## 評価指標

配車、使用BEV/ICE、担当便、day-ahead cost、Rolling実行日評価額、燃料、系統購入、PV利用・抑制、BESS充放電と終端SOC、Stage 1 incumbent/bound/gap、solve time、候補順位を報告する。

## 候補行列の事後分析

公開済み22候補の物理配車を両PV条件へ固定し、Stage 2 recourseだけを再評価した既存行列を使用する。候補は全てselectable・physical feasible・accounting reconciledである。順位相関と費用差は有限22候補に限定する。

## 96スロット系列

各Rolling stepの`hourly_solver_result.json`から、`rolling_start_slot_index`以降の最初の4スロットだけを取得する。96スロットのmissing/duplicateを拒否し、8種のslot mapをcanonical JSON hash化して`executed_day_accounting.executed_energy_flow_hash`と照合する。日合計、peak、終端BESS SOCも会計と照合する。

## 追加実験gate

本ベースラインでは新規solver runを行っていない。小規模統合oracleや感度実験は、目的、入力hash、停止条件、最大run数を事前登録し、既存ツールで実施可能な場合だけ別実験として行う。bb0c005の正本結果へ混ぜない。
