# 追加実験の事前登録

## 固定事項

- executionの起点は、承認後に作るcleanな実験commitとする。正本solver execution `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` のartifactを上書きしない。
- depot `tsurumaki`、service `WEEKDAY`、内部15分、seed 42、Gurobi 1 thread、BestObjStop OFF、powertrain selector OFF、fallback/repair OFFを固定する。
- RAINはscenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`。日曜ダイヤへ変更しない。
- 小規模oracleは同一Prepared inputから決定論的にサービス日の両端を含む等間隔便を選ぶ。便を結果を見て選び直さない。
- top-level experiment jobを「run」と数え、各job内部のGurobi `optimize` 回数と累積solver秒も別に保存する。

## P0-A: RAIN候補範囲×計算予算の2×2感度

仮説:

- H0: 探索範囲拡張によりwinnerまたは主要なBEV/ICE構成が実質的に変わる。
- H1: 2段階の拡張でもwinnerが不変、または変更による改善が事前許容値以下で主要結論が不変である。

profileはBASE、RANGE_ONLY、BUDGET_ONLY、FULL_EXPANDEDの4つ。候補範囲と探索時間を直交させ、Stage 2は全profileで30秒に固定する。旧3-profile案は複合search-profile感度のhistorical proposalに降格する。二値安定判定は指導教員が閾値を事前承認した場合だけ行う。

成功条件:

- 全profileが264/264、物理VALID、Rolling 24/24、会計PASS、no fallback/repairを満たす。
- 要求制御と実効制御がprofile定義と一致する。
- 安定性は (a) winner hash不変、または (b) 事前許容値内かつ主要結論不変のどちらか。

失敗条件:

- profileごとの非探索入力hashが不一致。
- 正当性gateが1件でも失敗。
- EXPANDEDが要求値どおり実効化されない。
- winnerが変わり改善率が許容値を超える、または主要なBEV/ICE解釈が反転する。この場合は負の結果として「選択不安定」と報告する。

## P0-B: 小規模統合reference距離

caseは8、12、24便の3つ。各caseでPhase 3とPhase 4を1回ずつ解くため、3 top-level jobs、6 phase solvesである。

調査判定は`P3_SCALAR_UNSUPPORTED`。Phase 3は配車energy proxyと固定配車Stage 2の二目的であり、scalar canonical actual-cost契約はPhase 4だけに適用される。したがって主指標名は`deployed_phase3_to_scalar_integrated_reference_distance`とする。`ApproxGap`およびpure decomposition gapは禁止する。reference費用が`1e-9 JPY`以下なら相対差をnullとする。

成功条件:

- Phase 4がOPTIMAL、raw status OPTIMAL、integrated exact support true、zero gap、actual-cost contract applied、objective/accounting residual `<=1e-5 JPY`。
- 両方式が全便担当、SOC・物理・会計gateを通過。
- 費用内訳、最低SOC、配車hash、vehicle type mix、runtime、gapをartifactへ保存。

失敗条件:

- 1caseでもPhase 4がtime limitまたはexact gate失敗。
- 同一入力hashを確認できない。
- Phase 3費用がoracle費用より `1e-5 JPY`を超えて低い。

3caseは母集団からの無作為標本ではないため、信頼区間やp値を出さない。平均・最大は記述統計としてのみ報告する。

## generic sensitivity runnerの禁止

`scripts/build_thesis_experiment_matrix.py`のdefaultは60分、軽油145円/L、車両日費0円で、正本15分、150円/L、20,000円/台日と一致しない。P0/P1では`run_thesis_sensitivity_matrix.py`と共に使用禁止とし、adapter freeze commitで作るFresh Prepare requestへallowlist fieldだけをoverlayする。

## P1: PV利用可能量三水準

P0-AまたはP0-Bが承認・完了するまで開始しない。LOW/HIGHは正本曲線を参照し、MEDIUMは各15分slotの `0.5 * (LOW + HIGH)` として事前定義したsynthetic curveとする。曲線以外のhash一致が必要である。

成功条件と失敗条件は `05_pv_availability_sensitivity_plan.md` に従う。
