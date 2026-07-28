# AI Agent向け修正指示書: 日次最適化後の1時間Rollingを最優先で成立させる

> **Status: IMPLEMENTED; retained as historical specification (2026-07-28).**
> 日次配車固定、60分×24 step、state handoff、実行prefix会計、
> acceptance auditのproduction pathは成立した。最新の提出可否と残課題は
> [`CURRENT_RESEARCH_RELEASE_BLOCKERS.md`](CURRENT_RESEARCH_RELEASE_BLOCKERS.md)
> に集約する。

## 目的と完了条件

有効な日次Phase 3結果を入力として、日次で決めた車両・便割当を変更せず、残り運行日を1時間ごとに充電・PV・BESS再最適化する。これは再配車ではなく、固定配車に対するreceding-horizon charging controllerである。日次＋rollingを統合MILPの大域最適解とは表現しない。

代表日の受理条件は、実効エネルギー地平の開始から終了まで全stepを実行し、`rolling_chain_summary.json.chain_accepted=true`、全step可行、state handoff、slot accounting、BEV/BESS終端SOC、固定配車hashがすべて検証済みであることである。

## 実験上の前提

- 日曜サービス日にWEEKDAY時刻表を固定する比較は、`fixed_weekday_timetable_pv_counterfactual`と明記したPV-only反実仮想に限り許容する。実際の日曜運行とは呼ばない。
- waiver成果物には、`timetable_service_id: "WEEKDAY"`、`weather_profile_date`、`calendar_policy`、`calendar_validation_status: "WAIVED_BY_EXPERIMENT_POLICY"`、waiver理由、固定control hashを保存する。
- waiverは日曜／平日不一致だけに限定する。trip、fleet、初期SOC、充電器、BESS、TOU、seed、solver設定、日次配車の変更を正当化しない。
- `timetable_rows`、`operator_id`、および`arrival + turnaround + deadhead <= next departure`を変更しない。
- 実在庫がICE 25台なら26台目を作らない。35 BEV / 26 ICEを主張するには、正規に26台目を入れたprepared inputを作り直す。

## 実装契約

1. 日次呼出しは`run_research_phase3_frontend_weather.py`から`ProblemBuilder`、`OptimizationEngine`へ至る既存経路を使う。
2. rollingは`RollingChainRequest`と`run_rolling_chain()`を使う。BFFからCLI subprocessを起動しない。
3. rollingは受理済み日次結果からのみ開始する。日次の`solver_result.json`、`summary.json`、`input_audit.json`、実効scenarioとPV成果物をhash照合する。
4. 日次実効PV時系列は`effective_pv_profiles.json`へ保存する。rollingはこの時系列を必ず再読込してから、明示された予測更新を適用する。
5. full chainはハードコードされた05:00–23:00ではなく、日次ProblemBuilderが確定した実効エネルギー地平を全走査する。短縮chainは診断用に保存しても受理しない。
6. 次stepの入力状態は前stepの実行prefixの出力だけから作る。BEV SOCは次slot開始値、BESS SOCは実行slot終了値、on/off-peak需要は実行済み最大値を引き継ぐ。
7. 一stepでもinfeasible、handoff失敗、hash不一致、配車hash変更、slot欠落／重複、終端SOC不一致があれば`chain_accepted=false`とする。
8. `executed_and_accepted`には、全step可行、全地平、slot accounting、Git clean、Gurobi、固定配車、runtime errorなしを含む必須9チェックの全通過を要求する。JSONの`chain_accepted`値だけを信用しない。

## 終端SOC数値契約

- `return_to_initial`では、MILPの上限は科学的許容値（既定`1e-6 kWh`）を使う。
- 後処理は同じ科学的許容値にGurobi由来の数値marginだけを加える。生の偏差、両許容値、受理limit、理由を保存する。
- 単なる丸めによる境界直上と、実質的な終端SOC持ち越しを区別する。報告側だけでsolver違反を隠してはならない。

## 必須成果物

同じrun directoryの`rolling_hourly_chain/`へ、少なくとも以下を保存する。

- `rolling_chain_summary.json`: 全step、所要時間、hash、受理チェック、rejection reason。
- `executed_day_accounting.json`: 実行prefixを一度だけ接続して再計算した会計。残り地平の目的値を加算しない。
- `day_ahead_vs_rolling_summary.json`: 同一単位で比較できる費目だけの差分。比較不能な値は理由付き`null`。
- `hourly_energy_flow_chart.csv`: PV発電、PV→bus、PV→BESS、BESS→bus、grid→bus、curtailment、BESS SOC、BEV SOC min/mean、charger kW、on/off-peak最大需要。
- `charging_schedule.csv`: `energy_source`と車両別電源由来の精度を含む。`(vehicle_id, slot_index, charger_id)`が物理充電枠であり、source別行はその配分である。

## 研究提出ゲート

- rolling未実行、chain不受理、fleet未宣言、終端SOC不成立、provenance不一致では、レポート先頭に`EXPLORATORY — RESEARCH SUBMISSION BLOCKED`を表示する。
- `input_provenance_ready`は入力整合性であり、`research_submission_ready`と同義ではない。
- 固定平日時刻表のwaiverが完全な場合だけ、反実仮想としての提出候補になる。actual service dayの表記は禁止する。

## 必須テストと実行

- 日次配車固定、2step以上のstate handoff、全slotの一回限りstitch、PV/grid/BESS収支、終端SOCを検証する。
- hash不一致、途中SOC欠落、PV予測不足、step infeasible、未受理日次、chain summary欠落、必須チェック欠落を負例として検証する。
- mockのみで完了にせず、clean commitから264便の日次run、少なくとも2step、最終的には全時間chainを手動実行する。

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q src bff scripts
git diff --check
```

## 非目標

- rolling実装のためにdispatch hard constraintを緩めない。
- 日次time limit、gap、入力規模、threadsをケース間で変えて計算時間をよく見せない。
- metadataやレポート文言だけを追加して、実step chainを省略しない。
