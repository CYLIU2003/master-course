# 追加実験の事前登録

## 固定事項

- executionの起点は、承認後に作るcleanな実験commitとする。正本solver execution `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` のartifactを上書きしない。
- depot `tsurumaki`、service `WEEKDAY`、内部15分、seed 42、Gurobi 1 thread、BestObjStop OFF、powertrain selector OFF、fallback/repair OFFを固定する。
- RAINはscenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`。日曜ダイヤへ変更しない。
- 小規模oracleは同一Prepared inputから決定論的にサービス日の両端を含む等間隔便を選ぶ。便を結果を見て選び直さない。
- top-level experiment jobを「run」と数え、各job内部のGurobi `optimize` 回数と累積solver秒も別に保存する。

## P0-A: RAIN候補範囲感度

仮説:

- H0: 探索範囲拡張によりwinnerまたは主要なBEV/ICE構成が実質的に変わる。
- H1: 2段階の拡張でもwinnerが不変、または変更による改善が事前許容値以下で主要結論が不変である。

profileはBASE、EXPANDED_1、EXPANDED_2の3つ。評価指標はwinner physical assignment hash、selected day-ahead canonical cost、selected-to-second margin、使用BEV/ICE、BEV/ICE便数、evaluated/selectable候補数である。Rolling費用をcandidate winner選択費と混ぜない。

成功条件:

- 全profileが264/264、物理VALID、Rolling 24/24、会計PASS、no fallback/repairを満たす。
- 要求制御と実効制御がprofile定義と一致する。
- 安定性は (a) winner hash不変、または (b) 事前許容値内かつ主要結論不変のどちらか。

失敗条件:

- profileごとの非探索入力hashが不一致。
- 正当性gateが1件でも失敗。
- EXPANDEDが要求値どおり実効化されない。
- winnerが変わり改善率が許容値を超える、または主要なBEV/ICE解釈が反転する。この場合は負の結果として「選択不安定」と報告する。

## P0-B: 小規模統合oracle

caseは8、12、24便の3つ。各caseでPhase 3とPhase 4を1回ずつ解くため、3 top-level jobs、6 phase solvesである。

主指標:

`ApproxGap = (J_Phase3 - J_Integrated*) / abs(J_Integrated*) * 100`

ただし `abs(J_Integrated*) <= 1e-5 JPY` では相対gapを定義せず、JPY差、配車一致、使用台数、runtimeだけを報告する。

成功条件:

- Phase 4がOPTIMAL、raw status OPTIMAL、integrated exact support true、zero gap、actual-cost contract applied、objective/accounting residual `<=1e-5 JPY`。
- 両方式が全便担当、SOC・物理・会計gateを通過。
- 費用内訳、最低SOC、配車hash、vehicle type mix、runtime、gapをartifactへ保存。

失敗条件:

- 1caseでもPhase 4がtime limitまたはexact gate失敗。
- 同一入力hashを確認できない。
- Phase 3費用がoracle費用より `1e-5 JPY`を超えて低い。

3caseは母集団からの無作為標本ではないため、信頼区間やp値を出さない。平均・最大は記述統計としてのみ報告する。

## P1: PV利用可能量三水準

P0-AまたはP0-Bが承認・完了するまで開始しない。LOW/HIGHは正本曲線を参照し、MEDIUMは各15分slotの `0.5 * (LOW + HIGH)` として事前定義したsynthetic curveとする。曲線以外のhash一致が必要である。

成功条件と失敗条件は `05_pv_availability_sensitivity_plan.md` に従う。
