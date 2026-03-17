# master-course バックエンド仕様書 v1.2 実装タスク分解書

## 0. 目的

本書は、`master-course` バックエンド仕様書 v1.2 をそのまま実装へ移すための正式タスク分解書である。
対象は `bff/`, `src/dispatch/`, `src/pipeline/`, `src/data_loader.py`, scenario JSON, audit/export であり、優先順位は以下で固定する。

1. `mode_milp_only` を scenario 起点で動かす
2. dispatch hard constraint を scenario 管理へ寄せる
3. simulation/export/audit を研究再現可能な形で結合する

## 1. 現状差分の要約

2026-03-08 時点の repo では、以下が確認できている。

- `src/dispatch/` は graph build, greedy duty generation, validation, `problemdata_adapter` を持つ
- `bff/routers/graph.py` は `build-trips`, `build-graph`, `generate-duties` を持つ
- `bff/routers/optimization.py` は stub
- `bff/routers/simulation.py` は stub
- `bff/store/scenario_store.py` は scenario の基礎構造を持つが、v1.2 追加項目は未整備
- `src/pipeline/solve.py` と `src/pipeline/simulate.py` は config/CSV 起点の実行を前提としている

したがって、v1.2 実装の本質は「dispatch は既存資産を保ちながら、scenario -> ProblemData -> solve/simulate という正式経路を新設する」ことにある。

## 2. 実装方針

- dispatch は `Timetable first, dispatch second` を維持する
- `src/dispatch/` に BFF 依存を入れない
- scenario を BFF の唯一の入力源とし、solver 用 CSV/config は内部互換レイヤとして扱う
- 3月前半は `mode_milp_only` と最小 audit/export までを完成条件にする
- `docs/constant/` は触らない

## 3. フェーズ別タスク

### Phase 1: scenario schema 固定

#### MC-BE-01 scenario store の v1.2 項目追加

- 目的: scenario JSON を v1.2 の唯一の真実源として固定する
- 対象ファイル:
  - `bff/store/scenario_store.py`
  - `tests/test_bff_scenario_store.py`
- 実装内容:
  - 以下のトップレベル既定値を追加する
  - `deadhead_rules`
  - `turnaround_rules`
  - `charger_sites`
  - `chargers`
  - `pv_profiles`
  - `energy_price_profiles`
  - `experiment_case_type`
  - `problemdata_build_audit`
  - `optimization_audit`
  - `simulation_audit`
  - dispatch 成果物無効化時に audit/result も適切にクリアする
  - `dispatch_scope`, `calendar`, `vehicles`, `routes`, `timetable_rows` と同様に load 時の後方互換 `setdefault` を入れる
- 受け入れ条件:
  - 新規 scenario 作成時に v1.2 項目が全て存在する
  - 既存 scenario JSON 読込時に KeyError を出さない
  - 既存 store テストが通る

#### MC-BE-02 scenario schema の API 境界固定

- 目的: optimization/simulation/dispatch から参照する必須フィールドを揃える
- 対象ファイル:
  - `bff/routers/scenarios.py`
  - `frontend/src/types/*` は必要最小限のみ追随
- 実装内容:
  - `experiment_case_type` を scenario payload で保持可能にする
  - rules/charger/pv/tariff の CRUD を後続実装に耐える形で格納できるようにする
  - フロント未対応項目は hidden field 扱いでよいが、BFF 側では破棄しない
- 受け入れ条件:
  - scenario 更新で v1.2 項目が消えない
  - 既存 CRUD フローが壊れない

### Phase 2: dispatch 前処理の v1.2 化

#### MC-BE-03 `graph.py` で scenario rules を hard feasibility に接続

- 目的: deadhead/turnaround を空実装から正式データ参照へ切り替える
- 対象ファイル:
  - `bff/routers/graph.py`
  - `bff/mappers/dispatch_mappers.py`
  - `tests/test_dispatch_graph.py`
  - `tests/test_dispatch_pipeline.py`
  - `tests/test_dispatch_validator.py`
- 実装内容:
  - `scenario.deadhead_rules` から ordered deadhead を構築
  - `scenario.turnaround_rules` から stop ごとの turnaround を構築
  - `vehicle_route_permissions` を dispatch candidate から除外する
  - `build-trips -> build-graph -> generate-duties` の audit 下書きを返せるようにする
- 受け入れ条件:
  - deadhead rule 不在時に infeasible edge が生成されない
  - turnaround 不足時に infeasible edge が生成されない
  - vehicle type 制約違反の edge/duty が出ない
  - `PipelineResult.warnings`, `invalid_duties`, `uncovered_trip_ids`, `duplicate_trip_ids` が保持される

#### MC-BE-04 infeasible reason の監査出力追加

- 目的: 学会・現場説明のため、arc 不可理由を追跡可能にする
- 対象ファイル:
  - `src/dispatch/feasibility.py`
  - `src/dispatch/graph_builder.py`
  - `bff/routers/graph.py`
  - 新規: `bff/mappers/dispatch_audit.py` または同等機能
- 実装内容:
  - feasible 判定 API を壊さずに reason 収集経路を追加する
  - `missing_deadhead_rule`, `insufficient_turnaround_time`, `vehicle_type_not_allowed` などのコードを返せるようにする
  - `graph_build_audit.json` 相当を scenario に保存する
- 受け入れ条件:
  - 不可 edge に対して reason 配列が取得できる
  - Graph endpoint の既存レスポンス互換を維持する

### Phase 3: `scenario_to_problemdata` 新設

#### MC-BE-05 正式 mapper の新設

- 目的: scenario から solver 入力を作る唯一の正式入口を作る
- 対象ファイル:
  - 新規 `bff/mappers/scenario_to_problemdata.py`
  - `src/data_loader.py` または `src/data_schema.py` の補助変更
  - `tests/test_dispatch_problemdata_adapter.py`
  - 新規 `tests/test_bff_scenario_to_problemdata.py`
- 実装内容:
  - 入力: scenario, `depot_id`, `service_id`, `mode`, `use_existing_duties`
  - 出力: `ProblemData`, `ScenarioBuildReport`
  - `vehicles`, `trips`/`duties`, `graph`, `chargers`, `charger_sites`, `pv_profiles`, `energy_price_profiles` を変換
  - `src/dispatch/problemdata_adapter.py` の graph-to-connection 発想を再利用する
  - `travel_connection_count`, `graph_edge_count`, `vehicle_count` などを build report に入れる
- 受け入れ条件:
  - scenario だけで `ProblemData` が構築できる
  - task/travel connection/vehicle count が report に整合する
  - trips 利用と duties 利用の両モードを切り替えられる

#### MC-BE-06 solve/simulate 向け一時 config 生成または直接実行 API の整備

- 目的: 既存 `src.pipeline.solve` と BFF をつなぐ
- 対象ファイル:
  - `src/pipeline/solve.py`
  - `src/pipeline/simulate.py`
  - 新規 `bff/mappers/problemdata_runtime.py` も可
- 実装内容:
  - 最小改修案: scenario mapper が一時入力セットを作り、既存 pipeline を呼ぶ
  - 推奨案: `solve()` / `simulate_from_outputs()` に `ProblemData` 直受け口を追加する
  - どちらでも外部 API は `scenario -> ProblemData -> pipeline` に統一する
- 受け入れ条件:
  - config/CSV のみでなく、BFF 実行経路から solver/simulator が呼べる
  - 既存 CLI 利用は維持される

### Phase 4: `run-optimization` 本結合

#### MC-BE-07 optimization router の stub 廃止

- 目的: `POST /api/scenarios/{scenario_id}/run-optimization` を正式実装へ置換する
- 対象ファイル:
  - `bff/routers/optimization.py`
  - `bff/store/job_store.py`
  - `src/pipeline/solve.py`
  - 新規テスト `tests/test_bff_optimization_router.py`
- 実装内容:
  - request body に以下を追加
  - `service_id`
  - `depot_id`
  - `rebuild_dispatch`
  - `use_existing_duties`
  - scenario 読込 -> scope 解決 -> 必要なら dispatch rebuild -> `scenario_to_problemdata` -> `solve()` 実行へ変更
  - `optimization_result` と `optimization_audit` を scenario に保存する
  - job progress を build/solve/save で更新する
- 受け入れ条件:
  - duties 未生成でも `rebuild_dispatch=true` で自動実行できる
  - `mode_milp_only` で result が返る
  - `solver_status`, `objective_value`, `solve_time_seconds`, `cost_breakdown`, `build_report`, `summary` が保存される

#### MC-BE-08 `mode_milp_only` 最短成立性確認

- 目的: 3月前半の最重要マイルストーンを達成する
- 対象ファイル:
  - `src/pipeline/solve.py`
  - `src/milp_model.py`
  - `src/result_exporter.py`
  - 必要な solver 周辺テスト
- 実装内容:
  - `mode_milp_only` の BFF 起動経路を優先検証する
  - 小規模 mixed fleet ケースで solve 完走を確認する
  - `cost_breakdown.total_cost` と summary を API 返却形へ整える
- 受け入れ条件:
  - 少なくとも 1 ケースで `OPTIMAL`, `TIME_LIMIT`, `FEASIBLE` のいずれかが得られる
  - 学会用比較に必要な cost breakdown が JSON で取得できる

### Phase 5: `run-simulation` 本結合

#### MC-BE-09 simulation router の stub 廃止

- 目的: dispatch または optimization 結果から simulation を正式実行する
- 対象ファイル:
  - `bff/routers/simulation.py`
  - `src/pipeline/simulate.py`
  - `src/simulator.py`
  - 新規テスト `tests/test_bff_simulation_router.py`
- 実装内容:
  - request body に `source: duties|optimization_result` を追加
  - scenario -> ProblemData -> result object -> simulator の流れを作る
  - `simulation_result` と `simulation_audit` を scenario に保存する
  - `soc_trace`, `charger_usage_timeline`, `feasibility_violations`, `total_distance_km` を返す
- 受け入れ条件:
  - optimization 未実行でも `source=duties` で simulation できる
  - optimization 実行後は `source=optimization_result` で再現検証できる
  - SOC 違反や feasibility violation が API から確認できる

### Phase 6: export/audit/reproducibility

#### MC-BE-10 監査情報の標準化

- 目的: build/solve/simulate の再現実験を可能にする
- 対象ファイル:
  - 新規 `bff/mappers/audit_mappers.py`
  - `bff/routers/graph.py`
  - `bff/routers/optimization.py`
  - `bff/routers/simulation.py`
- 実装内容:
  - 以下を scenario に保存する
  - `problemdata_build_audit`
  - `optimization_audit`
  - `simulation_audit`
  - 必須項目:
  - `scenario_id`
  - `depot_id`
  - `service_id`
  - `case_type`
  - input/output counts
  - warnings/errors
  - solver mode
  - time limit
  - mip gap
  - git sha
  - execution timestamp
- 受け入れ条件:
  - 同一 scenario の再実行で build/solve 条件差分を追える
  - audit 欠落時に研究再現が止まらないよう後方互換 default を持つ

#### MC-BE-11 学会図表向け export 追加

- 目的: backend 単体で図表素材を出せるようにする
- 対象ファイル:
  - `src/result_exporter.py`
  - `src/visualization.py`
  - `bff/routers/optimization.py`
  - `bff/routers/simulation.py`
- 実装内容:
  - 最低限以下を JSON/CSV で保存する
  - `duty_gantt.json`
  - `charger_schedule.json`
  - `soc_trace.json`
  - `power_flow_trace.json`
  - `cost_breakdown.json`
  - `experiment_summary.csv`
- 受け入れ条件:
  - Case A/B/C 比較に必要な素材が backend 出力だけで揃う
  - export 失敗が solve/simulate 全体失敗にならない

### Phase 7: テストとリリース判定

#### MC-BE-12 v1.2 テスト拡張

- 目的: 既存 180 passing baseline を維持しつつ、v1.2 の回帰を防ぐ
- 対象ファイル:
  - `tests/test_dispatch_feasibility.py`
  - `tests/test_dispatch_graph.py`
  - `tests/test_dispatch_pipeline.py`
  - `tests/test_dispatch_problemdata_adapter.py`
  - 新規 BFF integration tests
- 実装内容:
  - unit:
  - TimetableRow -> Trip
  - deadhead/turnaround resolution
  - graph feasibility reasons
  - scenario_to_problemdata
  - integration:
  - scenario CRUD -> build-trips -> build-graph -> generate-duties
  - duties -> run-optimization
  - optimization -> run-simulation
  - golden:
  - trip count
  - feasible edge count
  - duty count
  - objective value tolerance
- 受け入れ条件:
  - 既存テストが green
  - v1.2 新規テストが green

## 4. 実装順序

3月前半の前倒し実装は、以下の順で固定する。

1. `MC-BE-01`, `MC-BE-03`
2. `MC-BE-05`, `MC-BE-06`
3. `MC-BE-07`, `MC-BE-08`
4. `MC-BE-09`
5. `MC-BE-10`, `MC-BE-11`
6. `MC-BE-12`

理由は単純で、schema と dispatch hard constraint が固まらない限り `ProblemData` が安定せず、`ProblemData` が安定しない限り MILP の成立性確認に進めないためである。

## 5. 3/8-3/16 実装スプリント

### 3/8-3/10

- `MC-BE-01` scenario store 拡張
- `MC-BE-03` rules を dispatch に接続
- `MC-BE-04` infeasible reason の最小 audit
- `MC-BE-05` `scenario_to_problemdata` 骨格

### 3/10-3/12

- `MC-BE-06` pipeline 結合口の追加
- `MC-BE-07` optimization router 本結合
- `MC-BE-08` `mode_milp_only` 初回完走

### 3/12-3/14

- `MC-BE-09` simulation router 本結合
- `MC-BE-10` audit 保存
- `MC-BE-11` cost/duty/SOC export

### 3/14-3/16

- `MC-BE-12` integration/golden test
- Case A/B/C 初回比較
- 学会図表の素材確認

## 6. 完了判定

### v1.2 最低完了条件

- scenario だけで dispatch -> ProblemData -> optimization -> simulation が実行できる
- `deadhead_rules` と `turnaround_rules` が hard feasibility に効いている
- `mode_milp_only` が 1 ケース以上で成立する
- `optimization_result`, `simulation_result`, audit, export が scenario または outputs に残る

### 学会初弾に必要な追加条件

- Case A/B/C の比較結果が取れる
- `cost_breakdown.json`, `soc_trace.json`, `experiment_summary.csv` が安定出力される
- infeasible reason と uncovered trip を説明できる

## 7. v1.2 では後回しにするもの

以下はタスク化しても `blocked/future` 扱いに留め、3月前半のクリティカルパスに入れない。

- ALNS 本格実装
- rolling horizon
- on-route charging
- HEV
- V2G 厳密化
- uncertainty/delay
- battery degradation 高度化

## 8. 次アクション

実装開始順としては、最初の PR/作業単位を次の 3 本に切るのが最も安全である。

1. `scenario_store` v1.2 schema 拡張
2. `graph.py` への deadhead/turnaround 正式接続
3. `bff/mappers/scenario_to_problemdata.py` 新設
