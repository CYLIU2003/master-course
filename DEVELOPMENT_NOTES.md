# Development Notes

このファイルは、今後の編集内容をメイン直下で日時付き管理するための開発ノートです。

既存の研究実験ログは `docs/notes/DEVELOPMENT_NOTES.md` に残し、このファイルでは現在の編集判断、検証結果、残課題を短く追記します。

## 2026-06-25 14:05:13 +09:00 SOC制約と天候ポリシー修正

- 対象は SOC 制約、天候運用ポリシー、BFF の weather policy 伝播、回帰テストです。
- 通常実行では SOC 下限・上限をハード制約として扱い、SOC 不足をコストで買う運用にはしません。
- `allow_soc_violation_slack` / `use_soft_soc_constraint` は診断用モードとして扱い、通常の研究結果主張には使いません。
- 天候ポリシーに `final_soc_target_tolerance_percent` を含め、終端 SOC 目標の許容幅として扱います。
- `bff/services/optimization_run/weather.py` で `final_soc_target_tolerance_percent` を `simulation_config` へ注入し、`weather_policy_audit.json` にも残すようにしました。
- 雨天 `conservative` は運行中の安全床を `30%`、終端目標を `60%`、終端許容幅を `15%` にしました。
- この設定の実効終端下限は `max(30%, 60% - 15%) = 45%` です。
- 45% は常時 SOC 床ではなく、雨天時の終端実効下限として説明します。
- これはモデルの数学的意味を変えるため、旧 weather policy run と新 run は同一条件として直接比較しません。
- `tests/optimization/test_weather_policy_problem_integration.py` に、BFF の事前注入、audit 出力、雨天 conservative の実効終端下限を確認する回帰テストを追加しました。
- 検証 `python -m pytest -q tests\optimization\test_weather_policy_problem_integration.py tests\test_problemdata_soc_overrides.py tests\test_post_return_soc_target.py` は `24 passed` でした。
- 検証 `python -m pytest -q tests\test_milp_baseline_fallbacks.py tests\test_problem_builder_cost_component_toggles.py tests\test_solution_validity.py` は `9 passed` でした。
- 残課題として、晴天・雨天比較では `BASELINE_FALLBACK`、`vehicle_usage_cost` 条件差、既存 accounting 期待値、Gurobi ライセンス、BFF 起動依存テストを分けて扱う必要があります。
- 残課題として、BESS 終端 SOC 関連差分を今回の SOC 修正と同一変更として扱うか、別変更として分離するか確認が必要です。

## 2026-06-25 15:36:26 +09:00 天候ポリシーのPV-only化

- 雨天 `conservative` の SOC floor / target / tolerance 指定は撤廃しました。
- 理由は、雨天の主要な最適化上の意味は PV 発電見込みの低下であり、SOC 余裕や EV/ICE 選択を天候ポリシーで別途誘導すると、PV・買電・燃料費・需要料金・SOC制約から最適化が判断するという研究説明と重複するためです。
- weather policy は SOC 下限、帰庫後 SOC 目標、SOC 目標許容幅、初期SOC、BEV/ICE soft bias を上書きしない設計へ変更しました。
- `solcast_pv_proxy_v1` / `solcast_typical_pv_proxy_v1` がある場合は、PV 発電見込みだけを canonical problem の PV 列へ渡し、EV/ICE 選択は目的関数と制約に委ねます。
- `bff/services/optimization_run/weather.py` から weather 由来の SOC / strategy bias の `simulation_config` 注入を削除しました。
- `src/preprocess/weather/operation_policy.py` は operation profile を監査用の中立 profile にし、`apply_weather_policy_to_problem()` で車両初期SOCや SOC metadata を変更しないようにしました。
- 旧 `apply_initial_soc_policy` helper と `src/preprocess/weather/__init__.py` の再exportを削除し、weather module から初期SOCランダム化経路をなくしました。
- `src/optimization/common/builder.py` の weather strategy metadata 自動追加を削除し、weather policy enabled だけでは vehicle type sorting / objective bias が変わらないようにしました。
- Tk の weather proxy 反映は SOC 入力欄を書き換えず、summary に `SOC方針=変更なし` と表示するようにしました。
- `schema/weather_operation_policy.schema.json` と `README.md` を PV-only 方針に更新しました。
- 検証 `python -m pytest -q tests\optimization\test_weather_policy_problem_integration.py tests\test_problemdata_soc_overrides.py tests\test_post_return_soc_target.py tests\test_scenario_backup_tk_dataset_options.py tests\preprocess\test_weather_daily_schema.py tests\preprocess\test_weather_proxy_builder.py tests\preprocess\test_solcast_pv_proxy.py tests\preprocess\test_solcast_typical.py` は `85 passed` でした。
- 検証 `python -m pytest -q tests\test_milp_baseline_fallbacks.py tests\test_problem_builder_cost_component_toggles.py tests\test_solution_validity.py` は `9 passed` でした。
- この変更により、以前の weather policy run に含まれていた SOC 余裕・初期SOCランダム化・天気戦略 bias とは比較条件が変わります。今後の晴雨比較は PV 見込み差を主因として説明します。

## 2026-06-26 11:59:16 +09:00 システム全体レビュー対応

厳しめレビューで指摘された全項目に対応しました。

- README: `mode_milp_only` の「厳密解」表記を `supports_exact_milp=true / fallback なし / gap 確認済みのときのみ exact` に修正しました。天気戦略 bias 行を削除し、weather policy は SOC/初期SOC/EV-ICE bias を変更しないと明記しました。Solcast typical の説明から strategy bias 言及を削除しました。
- `docs/constant/formulation.md`: 接続可能条件に turnaround を追加し `arrival + turnaround + deadhead <= next departure` に修正しました。これは `src/dispatch/feasibility.py` の hard constraint と一致します。
- `bff/routers/optimization.py` `_solution_validity_payload`: `gurobi_unavailable_baseline` など非標準 fallback status を包括的に検出するように改善しました。`solver_metadata` から `postsolve_soc_repair_applied` / `postsolve_charging_recomputed` / `fallback_applied` / `supports_exact_milp` を参照し、`exact_or_validated` と `validated_non_exact` を区別します。fallback 時は scenario status を `optimized_provisional` にし、job message に fallback 理由を含めます。
- `src/preprocess/weather/solcast_pv_proxy.py`: `capacity_factor_by_slot` を metadata に保存し、最適化の PV 列適用経路へ乗るようにしました。
- `src/preprocess/weather/operation_policy.py`: `_apply_typical_pv_curve_to_problem` を `_apply_pv_proxy_curve_to_problem` に一般化し、`solcast_pv_proxy_v1` と `solcast_typical_pv_proxy_v1` の両方でPV曲線を適用可能にしました。
- `src/optimization/accounting/validate_outputs.py`: `--strict` 時に必須 ledger（`vehicle_slot_ledger.csv`, `energy_flow_ledger.csv`）の欠損を fail にしました。`UNKNOWN_OPERATOR` または空の `operator_id` がある場合も strict 時は fail にします。
- `docs/constant/README.md`: 正本候補に警告ブロックを追加し、`agent.md` や `masters_thesis_simulation_spec_v2.md` は研究計画段階の文書であり現コード実行経路と完全に一致しないことを明記しました。
- `tests/test_solution_validity.py` に `gurobi_unavailable_baseline` の fallback 分類テストと postsolve repair 検知テストを追加しました。
- `tests/optimization/test_weather_policy_problem_integration.py` に `solcast_pv_proxy_v1` のPV曲線適用テストを追加しました。
- 検証 `python -m pytest -q [全11ファイル]` は `97 passed` でした。
