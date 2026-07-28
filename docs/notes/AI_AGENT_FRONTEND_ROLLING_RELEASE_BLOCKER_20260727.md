# AI Agent 修正指示書: フロント実行を日次→1時間Rollingまで完結させる

## 0. このタスクの判定

これは「rolling のコードがある」ことを確認するタスクではない。通常のフロント画面から最適化を開始したとき、日次最適化、1時間rolling、監査、帳票までが一つのジョブとして完結し、失敗時に成功結果として見えないようにする**リリース阻止（release-blocker）修正**である。

`output/2026-07-27/0727改.zip` の2 runは日次解自体は可行だが、`rolling_hourly_chain/` が存在しない。`research_claim_scope.json` も `hourly_rolling_reoptimization_performance` を禁止している。原因は、研究CLIには `--run-hourly-rolling` がある一方、通常の BFF `POST /scenarios/{scenario_id}/run-optimization` が `OptimizationEngine().solve()` の後に rolling を起動しないことである。

### 今回のスコープ外（絶対に回避・緩和してはならない）

`research_vehicle_inventory_contract`（車両在庫契約の未宣言）だけは今回修正しない。これを `accepted` から外したり、未宣言を自動的に OK と見なしたりしてはならない。今回の修正完了後も、この契約が未解決なら研究提出可否は `false` のままでよい。重要なのは、**それ以外の理由で rolling 実行と提出判定が壊れないこと**である。

## 1. 修正対象と真の実行経路

必ず下記の実経路を直す。CLIだけを直して完了としない。

```text
Frontend
  -> POST /api/scenarios/{scenario_id}/run-optimization
  -> bff/routers/optimization.py: run_optimization
  -> _run_optimization
  -> ProblemBuilder().build_from_scenario(...)
  -> OptimizationEngine().solve(problem, config)             # 日次解
  -> 【今回追加する本番orchestrator】RollingChainRequest
  -> run_rolling_chain(...)                                  # 60分ごとの実行
  -> rolling_chain_acceptance_audit(...)
  -> report / claim scope / result persistence
```

既存の `scripts/run_research_phase3_frontend_weather.py --run-hourly-rolling` は参照実装として利用してよい。ただし、BFFから subprocess や別CLIを起動してはならない。同一プロセス、同一ジョブ、同一の `prepared_input_id`、入力hash、PV profile、日次結果を使って直接呼び出すこと。

## 2. 受入仕様（実装前に固定すること）

### 2.1 フロントからの通常実行

1. `RunOptimizationBody` に `run_hourly_rolling: bool = True` と `rolling_execution_minutes: int = 60` を追加する。フロントも明示的に `true` と `60` を送る。
2. サーバ側で既定値を強制し、古いフロントや手書きリクエストで rolling が抜けないようにする。通常の画面実行は必ず日次→rollingを実行する。
3. 開発診断用に日次だけを許す必要がある場合は、別の明示的な `run_profile=day_ahead_exploratory` を設ける。この場合は `research_submission_ready=false`、`teacher_release_status=BLOCKED`、`experiment_report.md` の先頭に `DAY-AHEAD ONLY — NOT A ROLLING RESULT` を必ず書く。通常UIの既定経路にしてはならない。
4. 日次が不可行ならrollingを開始しない。日次が可行でもrollingの1 stepでも不成立なら、ジョブを最終的に `failed` とし、日次解を「研究提出可能」「rolling実行済み」と表示してはならない。診断用に日次成果物と失敗理由は保存する。

### 2.2 rolling の正しい意味

- 日次の**配車・運行順序は固定**し、残り日について充電・PV・BESSだけを60分ごとに再最適化する。
- 各stepは前stepの**実行済みprefixだけ**を確定し、EV SOC、BESS SOC、ピーク需要、実行済み充放電、実効PV profileを次stepへ渡す。
- 残り地平の目的値をstep数だけ加算してはならない。会計は実行prefixを一度だけ接続した `executed_day_accounting` を正本とする。
- `arrival + turnaround + deadhead <= next departure`、`operator_id`、`timetable_rows`、サービス範囲を変更・再生成・緩和してはならない。
- `RollingChainRequest` の生成に必要な日次成果物が欠ける場合は推測して補完せず、失敗理由を保存して停止する。

### 2.3 成功の定義

以下を**すべて**満たすときだけ、`rolling_execution.status="executed_and_accepted"` とする。

- `rolling_hourly_chain/rolling_chain_summary.json` が存在し、JSONとして読める。
- `chain_accepted=true`。
- 全stepが可行で、step時刻と実行prefixが連続している。
- EV/BESS SOC handoff、terminal SOC、充電器上限、系統ピーク、PV/BESS/系統の時刻別エネルギー収支が合格している。
- `executed_day_accounting.json`、`day_ahead_vs_rolling_summary.json`、`hourly_energy_flow_chart.csv`、`charging_schedule.csv` が存在する。
- 日次とrollingの scenario/prepared-input/hash/PV profile/運行制御が一致し、rolling中に入力を推測・再構築していない。

上記のどれか一つでも満たさなければ `executed_not_accepted` または `not_executed` とし、研究主張は必ずブロックする。

## 3. 実装指示

### P1-A: BFFに本番rolling orchestrationを接続する

対象: `bff/routers/optimization.py`、必要なら新しい小さな本番service。

1. `_run_optimization` の日次 `OptimizationEngine().solve()` が可行であることを確認した直後に、`RollingChainRequest` を組み立て、`run_rolling_chain()` を直接呼ぶ。
2. CLI専用の `argparse.Namespace` をBFFの業務ロジックに漏らさない。必要なら `RollingChainRequest` を完全なDTOにし、CLIとBFFの両方が同じservice APIを利用する。
3. rollingは既存の最適化ジョブ内で実行し、進捗を `day_ahead_solved` → `rolling_running` → `rolling_validating` → `persisting` と更新する。二重起動を禁止する。
4. 日次run directory配下の `rolling_hourly_chain/` にのみ出力する。別の日時ディレクトリ、グローバルな最新結果、前runの残骸を読んではならない。
5. `run_hourly_rolling=false` や例外を成功扱いに変換してはならない。正常終了コード、例外なし、または `chain_accepted=true` のいずれか単独を成功根拠にしてはならない。

### P1-B: 提出可否・帳票生成の順序を直す

現状は `experiment_report.md` を生成・コピーした後に `_rolling_execution_evidence()` と `research_claim_scope` を作っている。この順序では、先生が最初に読む帳票にrolling未実行が表示されない。

以下の順序に変更する。

```text
day-ahead artifacts
  -> rolling artifacts
  -> rolling acceptance audit
  -> research acceptance / claim scope / release status
  -> final accounting integrity checks
  -> experiment_report.md と results.xlsx
  -> optimization_result.json / summary.json の最終書込み
```

帳票の先頭に必ず次を表示する。

- `run_profile`、`rolling_execution.status`、`rolling_execution_minutes`
- `research_submission_ready` と全 `failed_checks`
- `teacher_release_status` (`READY` / `BLOCKED`)
- `BLOCKED` の全理由。車両在庫契約が未宣言なら、その理由も隠さない。
- Stage 1 raw gap、certified gap、要求gap、達成可否、solverの終了理由
- `objective_is_actual_cost` と Phase 3が統合総費用最適解でない旨

過去の `experiment_report.md` をコピーして成功表示を残してはならない。final reportの生成に失敗した場合も、ジョブを成功扱いにしない。

### P1-C: Gitと研究モードの表示を正す

通常フロント実行でも、開始前と終了後のGit SHA、dirty状態、同一性を保存する。dirty runは計算を妨げないが、`research_submission_ready=false` と明記する。clean commitでの再実行なしに、教授提出用のREADYを出してはならない。

`research_run=false` の結果を研究可否のように見せない。表示上は `exploratory` とし、通常結果と研究提出結果を混同しない。

### P1-D: 日曜の固定weekday時刻表は「変更せず」正しくラベル付けする

時刻表は変更しない。この比較では、日曜ケースに以下を明示し、`actual_service_day` と表記してはならない。

```json
{
  "comparison_type": "fixed_weekday_timetable_pv_counterfactual",
  "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
  "calendar_validation_status": "WAIVED_BY_EXPERIMENT_POLICY",
  "waiver": {
    "scope": "weekday_timetable_on_sunday_for_pv_only_counterfactual",
    "reason": "Fixed weekday timetable; only PV profile differs. Not actual Sunday operation."
  }
}
```

このwaiverは比較対照の固定条件hashに含める。waiverなしのweekdays-on-Sundayは従来どおりfail closedとする。

### P1-E: 主張とソース粒度を一致させる

`charging_source_provenance.json` が示す通り、営業所・時刻別フローは厳密でも、車両別の `proportional_by_depot_timestep` は事後配分である。帳票とグラフは次を守る。

- PV→bus、PV→BESS、BESS→bus、grid→bus、curtailment、BESS SOCは営業所・時刻別の厳密フローとして表示する。
- 特定車両がPV/BESS由来で充電されたと断定する表示や文章は出さない。
- 日次対rollingの費用差は `executed_day_accounting` のみから出す。目的値をrolling差分へ流用しない。

### P2-A: gapと実行時間の表示を正す

`runtime_comparison_eligible` を「BestObjStopが未適用」だけで `true` にしてはならない。少なくとも、全ケースで時間制限、threads、seed、MIP gap設定、停止規則、実行順、warm start条件が一致し、かつ各ケースの達成条件を明示して初めて比較候補とする。

低PV runのように certified gapが要求値を超えた場合、`mip_gap_target_met=false` を出す。wall-clockの優劣や「高速化」を表示・報告しない。可行な日次/rolling結果の保存と、時間比較の可否は別の判定にする。

## 4. 必須テスト（テスト名・assertまで実装すること）

テストはmockだけで終わらせない。BFFの実経路を通す統合テストを追加する。

1. **通常BFF成功経路**: `POST /run-optimization` 相当のジョブで、日次solve後にrolling serviceが一度だけ呼ばれ、60分、同run directory、同prepared inputで実行されること。
2. **rolling未実行拒否**: 日次が可行でもchainファイルがない場合、最終ジョブは成功ではなく失敗/ブロックとなり、`teacher_release_status=BLOCKED`、report先頭に理由が出ること。
3. **rolling不合格拒否**: `chain_accepted=false`、欠損acceptance check、state handoff不連続、実行日会計なしをそれぞれ拒否すること。
4. **帳票順序**: accepted chainならreportに `executed_and_accepted` があり、未実行ならreportに `BLOCKED` があること。report生成がclaim scopeより先に走らないこと。
5. **日曜反実仮想**: 指定waiverありなら `WAIVED_BY_EXPERIMENT_POLICY`、waiverなしならERRORとなること。時刻表行・operator_id・便数が不変であること。
6. **dirty provenance**: dirty runは探索結果として保存できるが、研究提出READYにならないこと。clean/stable Gitのrunだけがこのゲートを通ること。
7. **gap表示**: certified gapが10%超なら `mip_gap_target_met=false`、時間比較不可となること。
8. **会計**: rollingの実行prefix会計で、kWh/kW・TOU・デマンドピーク・BESS SOC・terminal SOCを検証し、日次目的値の加算が起きないこと。

さらに、clean commit状態で264便の実runをフロントから1回行い、2ケースそれぞれについて上記成果物が実在することをZIPではなくrun directoryから検査する。この実runを行うまで「完了」と報告してはならない。

## 5. 完了条件

AI agentは次の全てを提示して初めて完了とする。

1. 変更ファイルと実際のBFF呼出し経路。
2. 追加したAPI DTOとフロント送信値。
3. 追加・更新したテストとその結果。
4. `python -m pytest -q -p no:cacheprovider`、`python -m compileall -q src bff scripts`、`git diff --check` の結果。
5. clean commitのフロント実runのartifact一覧。両caseに `rolling_hourly_chain/` の必須5ファイル、`executed_and_accepted`、hourly graph、日次対rolling会計があること。
6. 提出可否の最終表。車両在庫契約が未宣言のままなら、それを唯一の残ブロッカーとして正直に残すこと。
7. `README.md` または `docs/notes/DEVELOPMENT_NOTES.md` に、実経路、変更した主張範囲、再現コマンド、未解決の車両在庫契約を記録すること。

## 6. 禁止事項

- CLIでのみrollingを実行して、フロント経路の修正と偽ること。
- `chain_accepted` を手で書く、前runのchainをコピーする、存在だけで成功扱いにすること。
- 車両在庫契約、dispatch feasibility、terminal SOC、calendar contract、Git provenanceのゲートを緩めること。
- 日曜のweekday時刻表を実日曜運行と呼ぶこと。
- Phase 3を統合総費用最適解、比例配分を車両別の厳密電源決定、time-limit runを最適解と表現すること。
- テストだけで実264便フロントrunを省略すること。
