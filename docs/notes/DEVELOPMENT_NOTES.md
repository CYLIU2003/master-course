# E-Bus Scheduling Optimization — Research Experiment Log

> **目的**: 電気バス運行・充電スケジューリング最適化の修士論文研究実験ログ。
> GUI変更履歴は `app/CHANGELOG.md` へ移動済み。本ファイルは実験・結果・設計判断のみ記録する。

---

## アーキテクチャ方針

```
src/         研究コア (schema / loader / optimizer / simulator / analysis / exporter)
app/         可視化・観察レイヤー (GUIはsrc.pipeline.*を呼ぶのみ、ソルバーロジックなし)
config/      実験設定JSON (ExperimentConfig)
data/        入力データ CSV (cases/ = 実験用, toy/ = 検証用)
results/     出力KPI (kpi.json, kpi.csv, report.md)
tests/       回帰テスト
```

**優先実装順**: `mode_A_journey_charge` → `mode_B_resource_assignment` → optimizer/simulator一貫性検証 → thesis_mode 拡張

---

## 10 KPI (全モード共通)

| KPI | 説明 |
|-----|------|
| `objective_value` | ソルバー目的関数値 [円] |
| `total_energy_cost` | 電力購入コスト [円] |
| `total_demand_charge` | デマンド料金 [円] |
| `total_fuel_cost` | 燃料コスト [円] |
| `vehicle_fixed_cost` | 車両固定使用コスト [円] |
| `unmet_trips` | 未対応タスク数 |
| `soc_min_margin_kwh` | 全車両・全スロットでのSOC下限余裕の最小値 [kWh] |
| `charger_utilization` | 充電器稼働率 [%] |
| `peak_grid_power_kw` | グリッドピーク電力 [kW] |
| `solve_time_sec` | ソルバー求解時間 [s] |

---

## 実験記録

### [DEV-2026-03-13] Tokyu-only two-app data contract baseline

- **目的**:
  - `main` を Tokyu Bus 専用の research consumer とし、runtime ETL / explorer 責務を切り離す。
  - `data/seed/` と `data/built/` を明示し、seed-only 起動でも app が落ちない基盤を先に固める。

- **対応（data contract）**:
  - `data/seed/tokyu/depots.json`
  - `data/seed/tokyu/route_to_depot.csv`
  - `data/seed/tokyu/version.json`
  - `data/seed/tokyu/datasets/tokyu_core.json`
  - `data/seed/tokyu/datasets/tokyu_full.json`
  - を追加し、`.gitignore` に `data/built/` を追加。
  - ルートの `tokyu_bus_depots_master.json` / `tokyu_bus_route_to_depot.csv` は
    `data/seed/tokyu/sources/` に移動。

- **対応（schema / loader）**:
  - `src/scenario_overlay.py` を追加し、`ScenarioOverlay` / `FleetConfig` /
    `ChargingConfig` / `CostConfig` / `SolverConfig` を Pydantic で定義。
  - `schema/scenario.schema.json` に `ScenarioOverlay` 関連定義を追加。
  - `src/research_dataset_loader.py` を追加し、seed master 読込・built dataset status・
    seed-only bootstrap を `src/` に集約。

- **対応（BFF main / startup）**:
  - `bff/services/research_catalog.py` と `bff/routers/app_state.py` を追加し、
    `GET /api/app/datasets` / `GET /api/app/data-status` を追加。
  - `bff/main.py` から `catalog` / `public_data` router を外し、main runtime の公開面を
    planning / dispatch / simulation / optimization に絞った。
  - `bff/services/app_cache.py` の startup warm-up を ODPT / GTFS refresh 前提から
    dataset catalog / built status 前提へ変更。
  - `bff/routers/scenarios.py` の scenario 作成時に dataset bootstrap を適用し、
    Tokyu Core を seed-only でも生成できるようにした。

- **対応（frontend）**:
  - Scenario list を Tokyu dataset 選択 UI に変更し、`tokyu_core` / `tokyu_full` の
    built readiness を表示。
  - Overview に `datasetId` / `datasetVersion` / `randomSeed` を表示。
  - public-data route と `/odpt-explorer` redirect を main router から外し、
    Header / Sidebar / MasterDataHeader も main app 向け文言に整理。
  - `TimetablePage` では runtime ETL を無効化し、data-prep 先行を案内。

- **対応（data-prep / docs）**:
  - `data-prep/api/main.py` を追加し、catalog API を producer-side entrypoint として分離。
  - `data-prep/README.md` を追加。
  - root の dated notes / governance / development notes を `docs/notes/` へ移動。
  - `README.md` の architecture / startup / docs link を新しい two-app 方針に更新。

- **検証結果**:
  - `python -m pytest` → **294 passed**
  - `cd frontend && npm run build` → **pass**

### [DEV-2026-03-14] Incomplete artifact 500エラー修正 / Explorer ローディング修正 / Depot assignment 改善

- **問題①: Incomplete artifact が全 API で 500 を返す**
  - `bff/store/scenario_store.py` の `_load()` が `_INCOMPLETE` マーカーを検出して `RuntimeError` を上げるが、
    複数の router が `RuntimeError` を `HTTPException` に変換していなかったため HTTP 500 が返っていた。
  - `graph.py`・`master_data.py`・`optimization.py`・`public_data.py` の既存 `_require_scenario` は対応済みだったが、
    `scenarios.py` の `update_scenario` / `get_dispatch_scope` / `update_dispatch_scope` /
    `get_depot_scope_trips` / `duplicate_scenario` / `activate_scenario` /
    `get_timetable` / `get_timetable_summary` / `update_timetable` が未対応だった。

- **対応①**:
  - `bff/routers/scenarios.py` に `_runtime_err_to_http(e)` ヘルパーを追加。
    `"artifacts are incomplete"` を含む RuntimeError → HTTP 409 `INCOMPLETE_ARTIFACT`、
    それ以外の RuntimeError → re-raise (FastAPI が 500 扱い) に統一。
  - 上記の全 9 エンドポイントに `except RuntimeError as e: raise _runtime_err_to_http(e)` を追加。
  - `get_app_context` は `except (KeyError, RuntimeError):` に統合し、incomplete な active scenario を
    静かに deactivate する（500 にしない）。

- **対応①-frontend**:
  - `frontend/src/api/client.ts`
    - `extractErrorMessage` が `{"detail": {"code": "INCOMPLETE_ARTIFACT", "message": "..."}}` 形式の
      object detail を正しく取り出せるよう修正。
    - `isIncompleteArtifactError(error)` 関数を export 追加。
  - `frontend/src/types/api.ts`
    - `ApiError.detail` を `string | Record<string, unknown>` に拡張。
  - `frontend/src/hooks/use-scenario.ts`
    - `useScenarioIsIncomplete(id)` 便利フックを追加。
  - `frontend/src/hooks/index.ts`
    - `useScenarioIsIncomplete` を export に追加。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - `IncompleteArtifactBanner` コンポーネントを追加。
      409 INCOMPLETE_ARTIFACT を受け取った場合に「削除して一覧に戻る」バナーを表示。

- **問題②: orphan legacy ファイルの残留**
  - `outputs/scenarios/74aa5521-..._timetable.json` と `_stop_timetables.json` が残留していた。

- **対応②**:
  - `outputs/scenarios/74aa5521-5492-495f-9421-c35d0a5fb0e6_timetable.json` を削除。
  - `outputs/scenarios/74aa5521-5492-495f-9421-c35d0a5fb0e6_stop_timetables.json` を削除。

- **問題③: Public Data Explorer が「準備しています」から進まない**
  - `AppBootstrapManager` が `explorer` タブの warm status を `"idle"` のまま残す 2 パターンがあった:
    1. `scenarioId` が null/undefined のとき `resetWarmTabs()` 後に return するが、
       `explorer` を `"ready"` にセットしないため永遠に `"idle"` のまま。
    2. bootstrap が失敗（catch ブロック）したとき `planning/timetable/dispatch` は `"error"` にセットされるが
       `explorer` は `"idle"` のまま残る。
  - `explorer` タブは active scenario に依存しないのに、scenario lifecycle に連動していた。

- **対応③**:
  - `frontend/src/app/AppBootstrapManager.tsx`
    - `!scenarioId` の early-return パスで `setTabStatus("explorer", "ready", "Explorer はいつでも利用可能")` を追加。
    - catch ブロックにも `setTabStatus("explorer", "ready", "Explorer はいつでも利用可能")` を追加。

- **問題④: depot assignment が name string 比較のみで精度が低い**
  - `bff/services/depot_assignment.py` の `calculate_assignment_scores()` は
    depot 名が terminal stop 文字列に含まれるかどうかの heuristic のみだった。
  - stop ID レベルの geographic マッチングや sidecar depot_candidate_map が活用されていなかった。

- **対応④**:
  - `bff/services/depot_assignment.py` を全面改修:
    - `DepotAssignmentScore` dataclass を追加（depot_id, route_id, score, reasons, tier プロパティ）。
    - `compute_depot_route_scores(depots, routes, sidecar_depot_candidate_map)` を新規追加。
      スコアリング: geographic(3pt) + sidecar_map(2pt) + operator_match(1pt) の加算式。
    - `auto_assign_depots(depots, routes, sidecar_map, min_score, allow_multi_depot)` を新規追加。
    - 既存 `calculate_assignment_scores()` は legacy wrapper として維持（後方互換）。
  - `bff/routers/master_data.py`
    - `AutoAssignDepotsBody` (minScore / applyNow / operatorId / sidecarDepotCandidateMap) を追加。
    - `POST /scenarios/{id}/auto-assign-depots` を `compute_depot_route_scores` ベースに刷新:
      - tier / reasons / candidates を含むレスポンスを返す。
      - `applyNow=true` の場合は depot_route_permissions に即時保存。
      - `appliedCount` / `meta` を含む構造化レスポンスに変更。

- **テスト修正**:
  - `tests/test_bff_scenario_store.py`
    - `test_feed_context_roundtrip_is_exposed_in_scenario_meta` を修正:
      `_normalize_feed_context` に追加された `datasetFingerprint` / `manualRouteFamilyMapHash` フィールドを
      期待値に追加（既存の store 変更により生じた pre-existing failure を解消）。

- **確認結果**:
  - Python tests: `tests/test_bff_scenario_store.py` 他主要テスト群 pass（20 + 59 tests）。
  - TypeScript: `npx tsc --noEmit` → 0 errors。
  - orphan ファイル削除確認済み。

### [DEV-2026-03-14] Scenario 非依存 master preload と dataset-backed scenario 自己修復

- **問題**:
  - 既存 scenario の一部は `feed_context.datasetId` を持っていても `depots/routes/route_depot_assignments/depot_route_permissions` が空のまま残っていた。
  - `vehicle_templates` は dataset bootstrap に含まれておらず、scenario ごとに毎回手動で作る必要があった。
  - app 起動時に scenario 非依存で参照できる depot / route / template の基準 master がなかった。

- **対応**:
  - `data/seed/tokyu/datasets/tokyu_dispatch_ready.json` を追加し、目黒・瀬田・淡島・弦巻の 4営業所 / 43 route code を preload 用 dataset として固定。
  - `src/research_dataset_loader.py`
    - `default_vehicle_templates()` を追加。
    - `build_dataset_bootstrap()` が `vehicle_templates` を返すよう変更。
  - `bff/services/master_defaults.py` を追加。
    - `GET /api/app/master-data` 用の scenario 非依存 master blueprint を構築。
    - dataset-backed scenario の欠落 master data を埋める repair helper を追加。
  - `bff/store/scenario_store.py`
    - `_load()` 時に `scenario_overlay/feed_context.datasetId` を見て
      `depots/routes/route_depot_assignments/depot_route_permissions/vehicle_templates`
      を自己修復するよう変更。
    - `apply_dataset_bootstrap()` が `vehicle_templates` を保存するよう変更。
  - `bff/services/app_cache.py`
    - startup warm-up で preloaded master blueprint をキャッシュするよう変更。
  - `bff/routers/app_state.py`
    - `GET /api/app/master-data` を追加。

- **確認結果**:
  - `tokyu_dispatch_ready` で 4営業所 / 46 route rows / default vehicle templates を app-level に返却できることを確認。
  - dataset-backed だが master が空の scenario は `_load()` 一発目で自己修復されることをテスト追加で確認。

### [DEV-2026-03-13] 起動画面で既存シナリオを選択できない問題を修正

- **問題**:
  - 起動時に `/` から最後に開いたシナリオへ自動リダイレクトされ、既存シナリオ一覧を最初に選べない。

- **対応**:
  - `/` の起動 loader を廃止し、初期表示は常に `/scenarios` へ統一。
  - 既存シナリオは一覧から選択して開く導線へ変更。
  - `frontend/README.md` の起動時挙動を更新。

### [DEV-2026-03-13] シナリオ一覧に「開く」ボタンを追加

- **問題**:
  - 既存シナリオを開く導線が行クリックに依存し、ボタンが欲しいという要望が出た。

- **対応**:
  - シナリオ一覧カード右側に「開く」ボタンを追加。
  - 既存の削除ボタンは維持。

### [DEV-2026-03-08] Frontend boot pipeline + timetable summary/page + perf instrumentation

- **目的**:
  - `Maximum update depth exceeded` の温床になっていた大型ページの state/effect 連鎖を減らす。
  - 数万件規模の ODPT / GTFS timetable を summary-first + page access で扱う。
  - 起動時・tab 切替時・import 中の状態を可視化し、固まって見える時間を減らす。

- **実装（BFF）**:
  - `bff/routers/scenarios.py`
    - `GET /scenarios/{id}/timetable` と `GET /scenarios/{id}/stop-timetables` に `limit/offset` を追加。
    - `GET /scenarios/{id}/timetable/summary`
    - `GET /scenarios/{id}/stop-timetables/summary`
    - service / route / stop 単位の lightweight summary を返す helper を追加。
  - `tests/test_bff_scenario_timetable_summary.py`
    - summary 集計 helper の回帰テストを追加。

- **実装（Frontend 基盤）**:
  - `frontend/src/app/AppBootstrapManager.tsx`
    - app context / scenario / dispatch scope を確認後、依存のない master data / timetable summary / explorer overview を並列 prefetch。
  - `frontend/src/app/BootSplashOverlay.tsx`
    - boot 進捗オーバーレイ + 完了時フェードアウトを実装。
  - `frontend/src/stores/boot-store.ts`
    - boot step registry と weighted progress を Zustand 化。
  - `frontend/src/stores/tab-warm-store.ts`
    - planning / timetable / explorer / dispatch の warm state を管理。
  - `frontend/src/stores/import-job-store.ts`
    - import job の stage progress / logs を共通管理。
  - `catalog_update_app.py`
    - ODPT / GTFS の catalog refresh と scenario sync を行う standalone updater CLI を追加。

- **実装（Frontend 表示最適化）**:
  - `frontend/src/pages/inputs/TimetablePage.tsx`
    - 全件取得をやめ、summary + page 読みへ移行。
    - import progress / logs を panel で表示。
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - header summary を full timetable query から summary query へ切替。
  - `frontend/src/pages/dispatch/PrecheckPage.tsx`
    - timetable 全件 filter ではなく `routeServiceCounts` ベース集計へ変更。
  - `frontend/src/pages/odpt/OdptExplorerPage.tsx`
    - DB/API tab を hidden 切替にして unmount 再初期化を回避。
    - public-data sync / catalog refresh に import job progress を接続。
  - `frontend/src/pages/dispatch/TripsPage.tsx`
  - `frontend/src/pages/dispatch/DutiesPage.tsx`
    - VirtualizedList 化。
  - `frontend/src/features/common/TabWarmBoundary.tsx`
    - warm 中 placeholder を共通化。

- **実装（Catalog / Import 運用分離）**:
  - `bff/services/transit_catalog.py`
    - source + dataset_ref から保存済み snapshot を引く helper を追加。
  - `bff/routers/master_data.py`
  - `bff/routers/scenarios.py`
  - `bff/routers/public_data.py`
    - import / public-data fetch を「保存済み snapshot 優先、明示時だけ refresh」に変更。
    - snapshot 不在時は `catalog_update_app.py` を案内するエラーを返す。

- **実装（Fast ingest 追加）**:
  - `tools/fast_catalog_ingest.py`
    - ODPT の raw JSON を async + http2 + retry/backoff で取得する別 CLI を追加。
    - `raw/*.json` と `raw/*.ndjson`、checkpoint、benchmark、`bundle.json`、`operational_dataset.json` を生成。
    - 途中中断後は resource 単位で resume 可能。
  - `tests/test_fast_catalog_ingest.py`
    - 最小 raw snapshot から bundle/operational_dataset を再構築できることを確認する回帰テストを追加。

- **実装（Perf / Worker）**:
  - `frontend/src/utils/perf/`
    - `useRenderTrace`, `useMeasuredMemo`, `measureAsyncStep`, `useTabSwitchTrace`, `DebugPerfOverlay`
  - `frontend/src/features/common/VirtualizedList.tsx`
    - visible slice 計算の selector timing を記録。
  - `frontend/src/workers/assignment-sort.worker.ts`
  - `frontend/src/hooks/useSortedAssignments.ts`
    - explorer の depot assignment sort を worker 化。
  - `frontend/src/workers/route-family-group.worker.ts`
  - `frontend/src/hooks/useGroupedRouteFamilies.ts`
    - routes tab の route family grouping / variant sort を worker 化。
  - `frontend/src/workers/public-diff-preview.worker.ts`
  - `frontend/src/hooks/usePreparedPublicDiffItems.ts`
    - public-data diff preview の field diff 要約と sort を worker 化。

- **実装（追加の code split / dispatch summary-first / backend job UI）**:
  - `bff/routers/graph.py`
    - `GET /scenarios/{id}/trips` / `duties` / `blocks` に `limit/offset` を追加。
    - `GET /scenarios/{id}/trips/summary`
    - `GET /scenarios/{id}/graph/summary`
    - `GET /scenarios/{id}/graph/arcs`
    - `GET /scenarios/{id}/duties/summary`
    - graph build 系 job metadata に stage / count を付与。
  - `frontend/src/pages/dispatch/TripsPage.tsx`
  - `frontend/src/pages/dispatch/GraphPage.tsx`
  - `frontend/src/pages/dispatch/DutiesPage.tsx`
    - dispatch 一覧を summary-first + page access に移行。
    - backend job panel を表示。
  - `frontend/src/pages/results/DispatchResultsPage.tsx`
  - `frontend/src/pages/results/EnergyResultsPage.tsx`
  - `frontend/src/pages/results/CostResultsPage.tsx`
    - placeholder をやめ、既存 result summary を表示。
  - `frontend/src/api/jobs.ts`
  - `frontend/src/hooks/use-job.ts`
  - `frontend/src/features/common/BackendJobPanel.tsx`
    - `/jobs/{job_id}` poll で backend async job progress を表示。
  - `frontend/src/app/Router.tsx`
    - route-level lazy loading を適用。
  - `frontend/vite.config.ts`
    - manual chunk 設定を追加し、main chunk の肥大化を抑制。

- **確認結果**:
  - `cd frontend && npm run build` → **pass**

- **未確認 / 制約**:
  - この実行環境には `pytest` と `fastapi` が入っていないため、Python 側の新規テストは未実行。
  - main chunk warning は解消したが、`MapLibre GL` 由来の大きい地図 chunk warning は継続。地図依存をさらに細かく split するなら map provider 周辺の import 境界を再整理する必要がある。

### [DEV-2026-03-04] 設定タブ再設計 + Dispatch前処理統合

- **目的**:
  - GUIの設定導線を「時刻表ファースト」に再編し、設定ロジックの分散を解消する。
  - backend 側で `ProblemData` から `dispatch` の接続グラフを生成し、`travel_connections` を再構築できるようにする。

- **実装（UI）**:
  - `app/main.py` の巨大な設定タブ実装を分離し、`render_settings_tab()` 呼び出しに集約。
  - `app/settings_page.py` 新設:
    - サブタブ順をワークフロー順へ変更
      (`🗺️ 路線・時刻表` → `🚌 車両フリート` → `🏢 営業所・配車` → `⚙️ システム設定・適用`)
  - `app/system_config_editor.py` 新設:
    - 計画軸、便データソース、フォールバック車両、電力設定を集約
    - 「時刻表→接続グラフ」プレビューを追加
    - `build_problem_config_from_session_state()` を使って `ProblemConfig` を構築
  - `app/config_builder.py` 新設:
    - 手動設定の便生成を timetable ベースへ切り替え
    - `timetable.csv` / `segments.csv` / `routes.csv` を使って `TripSpec` を構築
  - `app/depot_profile_editor.py`:
    - `show_energy_settings` フラグを追加し、電力設定の重複表示を抑制可能に。

- **実装（dispatch / pipeline）**:
  - `src/dispatch/context_builder.py` 新設:
    - CSV (`route_master` / `operations`) から `DispatchContext` を構築。
  - `src/dispatch/dispatcher.py`:
    - greedy配車が precomputed graph を直接利用する API を追加。
  - `src/dispatch/pipeline.py`:
    - `uncovered_trip_ids` / `duplicate_trip_ids` を追加。
    - `all_valid` は duty妥当性 + カバレッジ妥当性を反映。
  - `src/dispatch/problemdata_adapter.py` 新設:
    - `ProblemData.tasks` を dispatch graph へ変換し、
      `TravelConnection` 全ペア行列を生成。
  - `src/data_loader.py`:
    - `dispatch_preprocess` 設定を追加。
    - `travel_connection_csv` がない場合、dispatch graph 由来で
      `travel_connections` を再構築可能に。
  - `src/pipeline/solve.py`:
    - dispatch 前処理レポートをログ出力し、戻り値にも含める。

- **テスト追加**:
  - `tests/test_dispatch_pipeline.py`
  - `tests/test_dispatch_context_builder.py`
  - `tests/test_dispatch_problemdata_adapter.py`
  - `tests/test_data_loader_dispatch_preprocess.py`

- **検証結果**:
  - `python -m pytest -q` → **178 passed**

- **追補 (同日)**:
  - `config/cases/mode_B_case01.json` と
    `config/cases/toy_mode_A_case01.json` に
    `dispatch_preprocess` ブロックを追加し、case 単位で前処理挙動を明示化。
  - `src/data_loader.py` の `build_inputs` 経路レポートを
    `edge_count` / `generated_connections` 形式に揃え、
    `src/pipeline/solve.py` で dict / dataclass の双方を安全にログ表示できるよう改善。
  - `docs/dispatch_preprocess_config.md` を追加し、
    `dispatch_preprocess` キーの意味・推奨プリセット・ログ形式を明文化。
  - `tests/test_pipeline_solve_dispatch_report.py` を追加し、
    `connection_source=build_inputs` 相当の dict レポートが
    `solve.py` で正しく表示・返却されることを確認。
  - `config/cases/mode_B_case01_build_inputs.json` を新設し、
    `dispatch_preprocess.connection_source=build_inputs` を case 単位で実配線。
  - `src/preprocess/energy_model.py` の HVAC 合算式を修正
    (`None` を含む場合に `TypeError` が出る優先順位バグを解消)。
  - `tests/test_energy_model.py` を追加し、
    Level 1 電費推定で `hvac_power_kw_heating=None` のときも
    例外なく推定できることを回帰テスト化。
  - **E2E 比較 (dispatch_graph vs build_inputs)**:
    - Baseline: `python run_case.py --case config/cases/mode_B_case01.json`
      - status=OPTIMAL, objective=9,594.05, unmet=0
    - build_inputs case:
      `python run_case.py --case config/cases/mode_B_case01_build_inputs.json`
      - status=OPTIMAL, objective=7,411.22, unmet=0
      - dispatch report: `source=build_inputs, trips=29, edges=812, connections=812`
    - 同一 task 集合上での接続差分（build_inputs case を再評価）:
      - build_inputs: feasible 812 / 812
      - dispatch_graph: feasible 0 / 812
      - 差分: `build_inputs-only true = 812`（全ペアで不一致）
    - 参考: baseline 8-task ケースでも
      `travel_connection.csv` と dispatch_graph は完全一致せず
      (`true`: 9 vs 10, csv-only 4, dispatch-only 5)。
  - 回帰確認: `python -m pytest -q` → **180 passed**

---

### [EXP-001] mode_A_case01 — 先行研究再現ベースライン

- **日付**: 2026年初頭
- **目的**: He et al. 2023 (TRD 115) 型「行路後充電決定」の再現
- **設定**: `config/cases/mode_A_case01.json`
- **データ**: `data/cases/mode_A_case01/` — 3台BEV, 6タスク, 64スロット(15分/スロット)

**結果:**
```
status         : OPTIMAL
objective_value: 20,172 円
solve_time_sec : 0.039 s
unmet_trips    : 0
```

**判定**: ✅ PASS — mode_A パイプライン動作確認。固定割当前提の充電最適化が正常動作。

---

### [EXP-002] toy_mode_A_case01 — 手計算検証トイケース

- **日付**: 2026-03-02
- **目的**: mode_A ソルバーの正しさを手計算で検証
- **設定**: `config/cases/toy_mode_A_case01.json`
- **データ**: `data/toy/mode_A_case01/` — 2台BEV, 5タスク, 1充電器(C1:50kW), 20スロット(60分/スロット)

**設定詳細:**
- V1 → {T1(20kWh), T2(20kWh), T3(20kWh)} 固定割当、合計消費60kWh
- V2 → {T4(20kWh), T5(10kWh)} 固定割当、合計消費30kWh
- TOU料金: t=0–7: **10円/kWh** (安価), t=8–19: 30円/kWh (高価)
- 各車両: soc_init=80kWh, soc_min=20kWh, soc_target_end=50kWh, fixed_use_cost=3,000円

**手計算 (修正版):**
- V1: 80 → (60消費) → 20kWh。target=50 → 充電必要量 = **30kWh**
- V2: 80 → (30消費) → 50kWh = target → 追加充電 **不要**
- 最適行動: 安価スロット(t=0–7)に30kWhを充電 → **30 × 10 = 300円**
- 固定コスト: 2台 × 3,000 = **6,000円**
- **期待合計: 6,300円**

**実際の結果:**
```
status             : OPTIMAL
objective_value    : 6,300 円
total_energy_cost  :   300 円
vehicle_fixed_cost : 6,000 円
unmet_trips        : 0
peak_grid_power_kw : 20.0 kW
solve_time_sec     : 0.017 s
```

**判定**: ✅ PASS — ソルバー結果が手計算と完全一致。

> **NOTE (修正)**: 当初の手計算では soc_init=80 と soc_target_end=50 を無視して「90kWh × 10円 = 900円」と誤推定していた。正しくは V2 が充電不要であり合計は 300円。

---

### [EXP-003] mode_B_case01 — 車両割当＋充電同時最適化

- **日付**: 2026-03-02
- **目的**: mode_B (vehicle-trip assignment + charging) の動作確認
- **設定**: `config/cases/mode_B_case01.json`
- **データ**: `data/cases/mode_B_case01/` — 3台BEV + 1台ICE, 8タスク

**結果:**
```
status             : OPTIMAL
objective_value    : 9,594 円
total_energy_cost  : 2,796 円
total_fuel_cost    : 1,798 円  (ICE使用: 約12.4L × 145円/L)
vehicle_fixed_cost : 5,000 円  (BEV 1台使用)
unmet_trips        : 0
charger_utilization:   6.25%
peak_grid_power_kw : 35.0 kW
solve_time_sec     : 0.093 s
```

**判定**: ✅ PASS — mode_B 動作確認。ICE 車両の燃料コストが非ゼロで整合。充電器稼働率 6.25% は BEV 使用台数が少ないため妥当。

---

## テスト状況

```
tests/test_simulator.py  — 6テスト全通過
  test_soc_lower_limit_violation        ✅
  test_simultaneous_charger_overload    ✅
  test_task_sequence_time_overlap       ✅
  test_end_of_day_soc_violation         ✅
  test_grid_capacity_violation          ✅
  test_ok_schedule_passes_all_checks    ✅
```

実行コマンド: `python -m pytest tests/test_simulator.py -v`

---

## バグ修正履歴

| 日付 | ファイル | 修正内容 |
|------|----------|----------|
| 初期 | `src/data_loader.py` | `_find_project_root()` 追加 — `.git/` or `src/` を上位探索し、`config/cases/*.json` パス解決を修正 |
| 初期 | `src/pipeline/solve.py` | `run_gap_analysis()` 引数順序修正 (result, sim_result, data, ms, dp → data, ms, dp, result, sim_result) |
| 初期 | `src/pipeline/solve.py` | `run_delay_resilience_test()` の `duties` / `trips` 引数を `getattr` で安全取得 |

---

## 次のステップ (優先度順)

1. **mode_B vs mode_A 比較実験**: 同一トリップセットで両モードを解き、mode_B の目的関数値 ≤ mode_A を確認 (緩和方向の理論的保証)
2. **Simulator 一貫性検証**: optimizer の充電スケジュールを simulator に通してフィジビリティ確認 (SOC violationがゼロであること)
3. **thesis_mode 設計**: デマンド料金・PV統合・V2G の追加検討
4. **感度分析**: TOU料金比 (安価/高価)、充電器容量、soc_target_end を変えたパラメータスイープ

---

## ファイル構成 (研究関連のみ)

```
master-course/
├── src/
│   ├── pipeline/solve.py     ← 正規パイプライン入口 solve(config_path, mode)
│   ├── data_loader.py        ← load_problem_data() + _find_project_root()
│   ├── milp_model.py         ← MILPResult, build_milp_model()
│   ├── simulator.py          ← SimulationResult, simulate(), check_schedule_feasibility()
│   ├── model_sets.py         ← build_model_sets()
│   └── parameter_builder.py  ← build_derived_params()
├── config/cases/
│   ├── mode_A_case01.json         ← EXP-001 [VERIFIED]
│   ├── mode_B_case01.json         ← EXP-003 [VERIFIED]
│   └── toy_mode_A_case01.json     ← EXP-002 [VERIFIED]
├── data/
│   ├── cases/mode_A_case01/       ← 3BEV, 6tasks, 64slots
│   ├── cases/mode_B_case01/       ← 3BEV+1ICE, 8tasks
│   └── toy/mode_A_case01/         ← 2BEV, 5tasks, 20slots (手計算検証用)
├── results/
│   ├── mode_A_case01/             ← kpi.json, kpi.csv, report.md
│   ├── mode_B_case01/             ← kpi.json, kpi.csv, report.md
│   └── toy_mode_A_case01/         ← kpi.json, kpi.csv, report.md
├── tests/test_simulator.py        ← 6 tests, all PASS
├── docs/reproduction/mode_A_reproduction_spec.md
└── run_case.py                    ← CLI実行ハーネス
```
- 2026-03-09
  - `catalog_update_app.py` の `--fast-path` 運用を README に明記し、`tools/benchmark_catalog_ingest.py` / `tools/profile_catalog_ingest.py` の使用例を追記。
  - 開発用 perf は明示 opt-in に変更。`?debugPerf=1` か `localStorage["debug-perf"]="1"` が無い限り observer / entry push を止め、通常の開発表示負荷を下げた。
  - `RouteTableNew` を family group 付きの virtualized list へ切り替え、planning の route 一覧でも全件 DOM 描画を避ける構成にした。

- 2026-03-13
  - `schema/parquet/*.schema.json` を追加し、`src/research_dataset_loader.py` で built parquet 読み込み時に schema 検証を強制。
  - `src/dataset_integrity.py` を追加し、seed/built/manifest 整合性チェックを実装。
  - `GET /api/app/data-status` に `seed_ready` / `built_ready` / `missing_artifacts` / `integrity_error` を追加し、`GET /api/app-state` を新設。
  - simulation / optimization / reoptimize 実行前に built dataset readiness を必須化（不足時は HTTP 503, `BUILT_DATASET_REQUIRED`）。
  - frontend の Simulation / Optimization ページに seed-only banner と実行ボタン disable を追加。
  - `backend/` を `backend_legacy/` へリネームし、README と関連注記を更新。
  - 構造回帰テスト `tests/test_architecture.py`（12件）と built guard テスト `tests/test_bff_run_guards.py` を追加。

- 2026-03-13 (Phase 3.5 hard cut)
  - `bff/` と `src/` の runtime から ODPT/GTFS/catalog ingest 依存を除去し、関連モジュールを `data-prep/lib/` へ移設。
  - `bff/routers/scenarios.py` から feed import/runtime snapshot import 経路を削除し、runtime-safe な CRUD/timetable 系に限定。
  - `bff/routers/master_data.py` から feed import エンドポイントを削除し、seed/built 前提の master CRUD のみに整理。
  - `bff/routers/catalog.py` / `bff/routers/public_data.py` を削除。
  - legacy runtime テスト群（ODPT/GTFS ingest 前提）を削除し、architecture boundary テストを強化。
  - `data-prep/README.md` を producer 契約に合わせて更新し、`data-prep/pipeline/*.py` の入口スクリプトを追加。

- 2026-03-14 (Phase 5-6 changes summary)
  - contract state cleanup: app-state judgment を `src/artifact_contract.py` + `bff/services/app_cache.py` に集中し、loader 側の重複 metadata 判定を削除。
  - producer pipeline: `data-prep/pipeline/build_all.py` を canonical build entry point として追加し、stale manifest 削除・manifest write・post-build contract validation を統合。
  - performance baseline tooling: `bff/middleware/timing.py`, `bff/services/metrics.py`, `tools/benchmark_api.py`, `docs/notes/performance_baseline.md`, `docs/notes/api_inventory_phase5.md` を追加。
  - API/runtime efficiency: scenario list summary 化、route/depot list summary 化、`tests/test_performance_contracts.py` を追加。
  - scoped runtime loading: `src/runtime_scope.py` を追加し、simulation/optimization run 前に `bff/services/run_preparation.py` で scoped solver_input を生成する構成へ拡張。
  - operational docs: `docs/notes/run_prep_contract.md` を追加。
  - `data-prep/` をカレントディレクトリにして `python -m data_prep.pipeline.build_all` を実行すると
    `ModuleNotFoundError` になる問題を確認。`data-prep/data_prep/` に互換 shim package を追加し、
    root の `data_prep.pipeline.build_all` へ委譲する形で、root / `data-prep/` どちらからでも同じ
    モジュールパスで起動できるよう修正。
  - `data-prep/README.md` に上記の実行方法を追記。

- 2026-03-14 (Tokyu subset emergency recovery)
  - `scripts/tokyu_subset_config.py` を追加し、目黒・瀬田・淡島・弦巻の default depot subset を1か所で編集できるようにした。
  - `scripts/build_tokyu_subset_db.py` を追加し、権威データ `tokyu_bus_depots_master.json` / `tokyu_bus_route_to_depot.csv` を正本にした depot-scoped SQLite subset builder を実装。
  - shared route code を単一 `depot_id` 列で潰さないため、subset DB schema に `route_pattern_depots` / `route_family_depots` / `route_code_depots` bridge を追加した。
  - `bff/services/local_db_catalog.py` を short depot id (`meguro`) / canonical depot id (`tokyu:depot:meguro`) 両対応にし、複数営業所 union・midnight rollover・optimizer-ready trip shape を実装。
  - `bff/routers/catalog_local.py` の `/api/catalog/milp-trips` を複数営業所対応のまま canonical depot ids を返す形へ調整。
  - `src/research_dataset_loader.py` は built manifest があっても routes / timetables / trips が空なら seed bootstrap にフォールバックするよう修正し、研究 bootstrap が止まらないようにした。
  - `README.md` に subset builder の使い方、`TOKYU_DB_PATH=data/tokyu_subset.sqlite`、short depot id API 例を追記。
  - 追加テスト: `tests/test_build_tokyu_subset_db.py`, `tests/test_local_db_catalog_subset.py`, `tests/test_catalog_local_subset.py`

- 2026-03-14 (ODPT key resolution cleanup)
  - `scripts/_odpt_runtime.py` を追加し、ODPT キー解決を共通化した。
  - `scripts/build_tokyu_full_db.py` / `scripts/build_tokyu_subset_db.py` は `--api-key` 未指定時でも `.env` / 環境変数の `ODPT_CONSUMER_KEY` / `ODPT_API_KEY` / `ODPT_TOKEN` を自動参照するよう修正。
  - `data-prep/lib/catalog_builder/odpt_fetch.py` と `tools/fast_catalog_ingest.py` も同じキー名セットを参照するよう揃えた。
  - `README.md` と `bff/services/local_db_catalog.py` の案内文を更新し、`YOUR_ODPT_KEY` がプレースホルダである点と `.env` 自動読込を明記した。

- 2026-03-14 (Tokyu core/full scope + GTFS reconciliation + updater hardening)
  - `data/seed/tokyu/datasets/tokyu_core.json` を 4営業所コア（目黒・瀬田・淡島・弦巻）へ更新し、`included_routes` を固定リストではなく `ALL` に変更して `route_to_depot.csv` を正本化した。
  - `data/seed/tokyu/datasets/tokyu_dispatch_ready.json` も同じ 4営業所スコープで `ALL` 運用に切り替え、preload dataset と core dataset の route drift を防止した。
  - `data/seed/tokyu/datasets/tokyu_full.json` は全 12 営業所を含む定義に整理し直した。
  - `src/research_dataset_loader.py` は dataset definition の depot 順を保持して bootstrap するよう修正し、`tokyu_core` の primary depot が `meguro` で安定するようにした。
  - `data-prep/pipeline/_gtfs_built_artifacts.py` に `gtfs_reconciliation.json` 生成を追加し、route master と `GTFS/TokyuBus-GTFS` の不一致（missing / extra route codes）を dataset 単位で保存するようにした。
  - `data-prep/pipeline/build_all.py` に `--strict-gtfs-reconciliation` を追加し、必要時は照合不一致で build を失敗させられるようにした。
  - `scripts/_stop_timetable_fallback.py` を追加し、ODPT `BusstopPoleTimetable` が 0件でも `trip_stops` から synthetic `stop_timetables` を再構成する fallback を実装した。
  - `scripts/build_tokyu_full_db.py` / `scripts/build_tokyu_subset_db.py` は上記 fallback を利用し、`pipeline_meta` に synthetic stop timetable 件数を記録するよう修正した。
  - `scripts/export_tokyu_sqlite_to_built.py` は `--depot-ids` 未指定時に dataset definition の `included_depots` を自動適用するよう修正し、`tokyu_core` / `tokyu_full` export が seed scope と一致するようにした。
  - `catalog_update_app.py` の Tokyu 更新導線を修正し、デフォルト GTFS パスを `GTFS/TokyuBus-GTFS` に変更、ODPT/GTFS pipeline 実行後に `tokyu_core` / `tokyu_full` built datasets を再生成できるようにした。
  - 追加・更新テスト: `tests/test_stop_timetable_fallback.py`, `tests/test_catalog_update_app.py`, `tests/test_data_prep_gtfs_built_artifacts.py`, `tests/test_build_tokyu_subset_db.py`, `tests/test_research_dataset_loader.py`, `tests/test_bff_research_scenario_bootstrap.py`
  - 確認:
    - `python -m pytest tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_build_tokyu_subset_db.py tests/test_stop_timetable_fallback.py tests/test_data_prep_gtfs_built_artifacts.py tests/test_catalog_update_app.py tests/test_build_tokyu_full_db.py tests/test_odpt_runtime.py -q` → 20 passed
    - `python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch` → pass, `gtfs_reconciliation.json` 生成
    - `python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch` → pass, `gtfs_reconciliation.json` 生成
    - `python scripts/build_tokyu_subset_db.py --depots meguro --route-codes 黒01 --out data/tokyu_subset_stop_verify.sqlite --no-cache` → `BusstopPoleTimetable=0` でも synthetic `stop_timetables=587`

- 2026-03-14 (Scenario bootstrap hardening + GTFS SQLite recovery)
  - `src/research_dataset_loader.py` の parquet 読み出しを再帰正規化し、`stopSequence` / `stop_timetables.items` が parquet 復元で `numpy.ndarray` になっても scenario bootstrap が落ちないよう修正。
  - `bff/routers/master_data.py`, `bff/services/route_family.py`, `bff/store/scenario_store.py`, `bff/mappers/scenario_to_problemdata.py` を list-like 正規化対応にし、built dataset 境界での配列真偽判定エラーを除去。
  - `data-prep/pipeline/build_all.py` は `stops.parquet` / `stop_timetables.parquet` も生成するよう拡張し、`build_dataset_bootstrap()` が built dataset から stops / stop timetables を初期投入できるようにした。
  - `scripts/build_tokyu_gtfs_db.py` を追加し、`GTFS/TokyuBus-GTFS` から Tokyu local SQLite catalog を直接生成できるようにした。route/depot bridge (`route_family_depots`, `route_pattern_depots`, `route_code_depots`) を保持し、GTFS stops / timetable trips / trip stops / stop timetables を SQLite 化する。
  - `scripts/export_tokyu_sqlite_to_built.py` は routes の `startStop/endStop/stopSequence/tripCount` を戻し、`stops.parquet` / `stop_timetables.parquet` も export するよう拡張。`calendar_type=平日/土曜/日曜・休日` は canonical `service_id` (`WEEKDAY` / `SAT` / `SUN_HOL`) に正規化する。
  - `catalog_update_app.py` に `--build-gtfs-db`, `--gtfs-db-dataset-id`, `--gtfs-db-path` を追加し、ODPT/GTFS refresh 後に GTFS-backed SQLite catalog も同時再生成できるようにした。
  - 確認:
    - `python -m pytest tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_data_prep_gtfs_built_artifacts.py tests/test_build_tokyu_gtfs_db.py tests/test_catalog_update_app.py tests/test_bff_graph_router.py tests/test_bff_scenario_to_problemdata.py tests/test_build_tokyu_subset_db.py tests/test_build_tokyu_full_db.py tests/test_stop_timetable_fallback.py tests/test_odpt_runtime.py -q` → 35 passed
    - `python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch` → pass (`routes=41`, `trips=9174`, `stops=876`, `stop_timetables=2387`)
    - `python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch` → pass
    - `POST /api/scenarios` + `POST /api/scenarios/{id}/activate` の API smoke → 201 / 200
    - small-scope smoke: `tokyu_core` 1 route + 1 BEV で duties 生成後 `simulate_problem_data()` 実行 → pass
    - `python scripts/build_tokyu_gtfs_db.py --dataset-id tokyu_core --out data/tokyu_core_gtfs.sqlite` → pass
    - `python scripts/export_tokyu_sqlite_to_built.py --db data/tokyu_core_gtfs.sqlite --dataset-id tokyu_core --built-root data/gtfs_sqlite_export_test` → pass (`stops.parquet` / `stop_timetables.parquet` も出力)
