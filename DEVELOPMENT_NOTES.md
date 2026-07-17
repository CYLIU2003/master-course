# Development Notes

このファイルは、今後の編集内容をメイン直下で日時付き管理するための開発ノートです。

既存の研究実験ログは `docs/notes/DEVELOPMENT_NOTES.md` に残し、このファイルでは現在の編集判断、検証結果、残課題を短く追記します。

## 2026-07-16 BESS終端条件の整理と「日次計画→毎時充電再最適化」

- BESS終端条件を明示的な3方針へ分離した。`minimum_only`は通常SOC上下限と終端SOC下限だけをhard constraintとして守り、`return_to_initial`は終端を初期SOCへ一致、`fixed_target`は指定値へ一致させる。旧scenarioは、正の終端目標があれば`fixed_target`、なければ`minimum_only`として再現する。方針解決はcore共通関数へ集約し、builder、MILP、独立feasibility、会計・BFF出力が同じ意味を使う。Phase 3 Stage 2は従来から目標をhard制約としていたが、統合MILP側は偏差penaltyだけだったため、選択方針どおり目標±許容幅のhard制約へ修正した。この点は統合MILPの数学的意味を変えるため、旧Phase 4成果物との費用比較を無効にする一方、現行Phase 3成果物の比較条件は変えない。
- Tkフロントの営業所設備・充電インフラ画面と詳細設備画面の双方に終端方針を追加した。`minimum_only`選択時は古い目標値を0へクリアし、初期SOCへ戻す場合は初期SOCを監査可能な目標値として保存し、任意目標は終端下限〜SOC上限内だけを許可する。SOCの%入力を画面上の正本とし、kWh換算値は読取表示にした。
- 点在していた主要入口を画面上部の設定ハブ（営業所設備・BESS、車両・テンプレート、ソルバー・実験条件）へ集約し、営業所設備タブを主パラメータ群へ追加した。`DESIGN.md`に色、文字、余白、部品、導線、アクセシビリティ、研究入力の表示規則をdesign.md形式で記録し、`@google/design.md lint DESIGN.md`を通過した。
- 毎時再最適化結果から、次slot開始EV SOC、最終実行slot終了BESS SOC、実行済みslotのon/off-peak最大受電kWを抽出する状態引継ぎを追加した。欠損時に初期値へ戻さず停止する。CLIは`--end-time`で1時間ずつ連鎖し、各stepの状態と全体summaryを保存する。残り時間目的値は重複区間を含むため加算しない。
- 予測誤差実験用に、毎時のfull-horizon PV予測を`--pv-forecast-updates-json`で差し替える経路を追加した。営業所ID、slot数、非負kWhを検証し、profile hashと日量を各stepへ保存する。長時間solveはユーザーが手動実行する方針のため、この変更では1500秒run、24時間連鎖、予測誤差、複数日、seed感度を実行していない。実行コマンドと受理条件は`docs/notes/phase3_manual_validation_runbook_20260716.md`に固定した。
- 文献上、定置型蓄電池の終端SOCは一律に初期SOCへ戻す物理条件ではない。代表日を繰り返す研究では初期・終端を一致させる一方、終端を初期値の近傍に置く方法、終端SOCを翌日の初期SOCへ引き継ぐ逐次計画も確認した。現行晴雨比較の`300 kWh → 300 kWh`は、日間在庫を同条件にして費用比較するための**シナリオ境界条件**として説明する。
- 曖昧だったStage 1用語を実装・metadata・資料で改称した。`EV外部充電量の下界`は、便・回送・終端SOCに必要なエネルギーから初期EV SOCを引き、充電効率で割った「時刻・設備を無視した最低充電器入力」であり、実現充電計画ではない。`初期BESS余剰`は`max(初期BESS SOC − 終端要求SOC, 0) × 放電効率`であり、現行比較では`max(300−300,0)×0.95=0 kWh`である。PV控除も日量集約の費用代理であり、実際のPV→busフローではない。
- `OptimizationConfig`へStage別制限時間とrolling-horizon設定を追加した。1500秒指定の従来挙動はStage 1/2各750秒のまま保存し、明示指定時だけ段階別時間を変更する。120/30秒の短縮runは可行だがStage 1 gap 100%、晴雨ともBEV/ICE担当便54/210となり、天候差が消えたため研究比較には採用しない。
- `DayAheadHourlyOptimizer`と毎時再最適化CLI/BFF経路を追加した。最初にPhase 3の日次割当を一度求め、その割当を固定して、毎正時に実測EV SOC・BESS SOC・当日既発生ピークを初期状態として、当日末までの充電・PV・BESS・系統運用だけを再最適化し、先頭60分のみ実行する。運行割当、接続条件、時刻表は書き換えない。
- 保存済み日次解の再利用契約を厳格化した。BFFはscenario、prepared input、service/depot scopeの一致を必須とし、CLIは日次解と同じディレクトリの`input_audit.json`からservice date、trip hash、vehicle hashまで照合する。復元したduty、trip、vehicle、served/unserved集合の不整合、未知の実測EV/BESS IDは黙って無視せず停止する。canonical tripを再利用するため`operator_id`と時刻表由来属性は保持する。
- 自己レビューで、BFFの最初の毎時結果が`optimization_result`を上書きし、2回目に元の日次割当を参照できないP1を検出した。毎時結果へ検証済み`canonical_solver_result`とscenario/prepared scopeを引き継ぐよう修正し、同じ固定日次割当で2回連続更新できる回帰テストを追加した。
- 接続・回送検査まで含む契約確認後の5:00固定割当再最適化は晴天1.964秒、雨天2.021秒（Stage 2 solve 0.064/0.062秒）でoptimalとなり、終端300 kWh条件では1500秒runと同じ電力運用・費用を再現した。終端下限のみ120 kWhにした感度では晴天費用が3,934円低下したが、初期BESS在庫180 kWhを消費した差であり、翌日価値を入れない限り「経済性改善」とは扱わない。
- 5:00結果のslot 1開始EV SOC・BESS SOC・既発生需要ピークを6:00へ引き継ぐ試験で、最初はMILP optimalにもかかわらず独立SOC検証が過去slotを再計上し、2台を終端不足として誤拒否した。rolling検証は実測SOCの時点より前の便energy・完了済み回送を再控除せず、進行中便の残余部分と未完了回送だけを評価するよう修正した。再実行は晴天2.032秒、雨天2.006秒、Stage 2 optimal、264便、違反0、BESS終端300 kWhで可行となった。これで5:00→6:00の1回連鎖は両天候で確認済みだが、24回連鎖と予測誤差試験は未実施である。
- 詳細な文献対応、数式、実験結果、適用範囲は`docs/notes/phase3_literature_and_two_level_optimization_20260716.md`に記録した。残課題は、運行中の各時刻で実測状態を与える逐次検証、予測誤差ケース、複数日終端価値、正式なclean-worktree再計算である。
- 文献準拠の表現、日次／毎時の二階層、BESS終端方針、修正内容、計算・費用・設備条件を反映した教員向け18枚版を`docs/presentations/phase3_weather_energy_balance_progress_20260716_revised.pptx`へ保存した。全スライドにカンペを残し、overflow検査とテンプレート忠実度検査（issue 0）を通過した。
- 文献PDFの抽出テキストとページ画像は再生成可能な作業用成果物なので、誤コミット防止のため`.gitignore`へ`tmp/`を追加した。文献から採用した根拠は上記ノートへ出典付きで固定した。
- 最終自己レビューではP0=0、未解決P1=0。途中で検出したP1（毎時2回目の日次割当参照喪失、rolling独立SOC検証の過去energy再計上、統合MILPだけ終端目標がsoftだった不一致）は修正・回帰化した。`GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic`でcompileall、`python -m pytest -q --ignore=test_multiday_phase1.py`を実行し`717 passed, 8 skipped`、`git diff --check`、design.md lint、Tk実画面確認、PPT overflow、テンプレート忠実度issue 0を確認した。除外testはlocalhost BFFを要求する手動E2Eである。

## 2026-07-16 晴雨の電力需給・BESS・燃料監査と教員向けPPT

- `scripts/audit_phase3_weather_energy_balance.py`を追加し、最終1500秒runを再求解せず、保存済みscenario / prepared scopeを同じcanonical build経路で読み直してtrip/vehicle hashを照合した。24時間枠ごとにPV発電、PV→bus/BESS、出力抑制、grid→bus/BESS、BESS→bus、充電入力、BESS SOC開始/終了、EV/ICE運行台数、ICE燃料をCSV/JSONへ再集計する。さらにsolver実測時間、総/段階別制限時間、MIPGap、seed、TOU、需要料金、燃料・CO₂・車両使用単価、充電器、受電上限、PV/BESS、SOC方針、objective flags/weightsを`scenario_parameters`へ保存する。成果物は`C:\master-course\output\phase3_weather_energy_audit_20260716`。
- BESSは両日とも300kWhで開始・終了し、晴天の運用範囲は120–480kWh、雨天は226.950–322.025kWhである。PV式、充電源式、BESS遷移式の最大絶対残差は晴天`3.41e-12 kWh`、雨天`1.98e-12 kWh`で、監査許容値`1e-6 kWh`を満たした。系統→BESSは設定どおり両日0kWh。
- 晴天でもEV35台全数は使用せず、使用EV/ICEは16/16台（141/123便）、雨天は15/17台（119/145便）である。依頼文の在庫`EV35/ICE26`に対し実run入力は`EV35/ICE25`のため、26台条件はscenario修正と再計算なしに主張しない。
- ICE燃料を割当便の営業距離と便間回送距離から再計算した。晴天は`1162.675 + 124.500 km → 284.773 L → 42,715.982円`、雨天は`1404.047 + 134.400 km → 340.364 L → 51,054.642円`で、報告燃料費との差は`2e-10円`未満。ただし`fuel_cost_final_source=provisional_distance_based`かつ給油イベント0件なので、実現給油計画・燃料タンク可行性の証拠ではない。
- `scripts/build_phase3_energy_balance_presentation.py`を追加し、添付9月発表PPTの白地・濃青見出し・青罫線・大学マーク・Meiryo・結論帯を参照した18枚の進捗PPTを生成した。モデル修正一覧、二段階モデルの役割と外部充電量下界式、計算/設備条件、費用/環境条件の4枚を追加した。角丸カードと装飾的な矢印をやめ、表・数式・角形パネル中心へ変更した。全定量グラフで晴天/雨天を同時比較し、全18枚のnotes欄へ目標時間付きカンペを保存した。成果物は`docs/presentations/phase3_weather_energy_balance_progress_20260716.pptx`。
- PowerPoint自身で18/18枚を1600×900 PNGへrenderし、ロゴ、文字切れ、比較軸、凡例、モデル式、パラメータ表、BESS/PV/充電/系統/燃料/費用図、notes本文を確認した。Stage 1 gap約13%、未コミット変更を含む暫定結果、非global-optimumという既存の研究限界は全て資料内に残した。

## 2026-07-16 Stage 1天候費用代理・所在地SOC必要条件・晴雨1500秒run

- 根本原因は、Phase 3 Stage 1がICE燃料・CO₂・車両費だけで割当を決め、PV量と充電費用をStage 2にしか渡していなかったことです。営業所別に、便・始発/便間/帰庫回送・実効終端SOCから外部充電必要量を求め、PV（フロント設定0円/kWh）・初期BESS余剰・最安系統電力へ単価順に配分する集約費用下界をStage 1へ追加しました。充電時刻・充電器競合・契約電力・需要料金はStage 2の厳密検証に残し、代理費用を実現費用とは扱いません。
- 最初の晴天1500秒候補はBEV190便を選びましたが、Stage 2 IISによりStage 1が営業所外充電を発明していたことを検出しました。slot別所在地制約69,300本は探索性能を失ったため不採用とし、割当に裏付けられたhome-depot充電窓と始発/便間/帰庫loadを累積する必要条件875本へ圧縮しました。hard dispatch条件、SOC、充電器、契約電力、fallback/postsolve repair禁止は緩和していません。
- 同一モデル、Gurobi 13.0.1、1500秒、gap 0.1、seed 42で、晴天は使用BEV/ICE=16/16・BEV/ICE担当便=141/123、雨天は15/17・119/145となりました。晴天は雨天よりBEV担当が22便多く、ユーザー仮説どおりPV 0円の価値が割当に反映されました。全264便担当、Stage 2 optimal、SOC/充電器/契約電力/接続等の独立validation違反は両方0です。
- 会計総費用は晴天713,032.185円、雨天722,511.345円で、雨天が+9,479.160円（+1.329%）です。雨天の燃料費は+8,338.660円、需要料金は+992.032円、ピークは+24.801kWです。一方、BEV担当便が22便減ったため系統買電は雨天の方が14.916kWh少なく、PV減少だけを単純に買電増加へ読み替えられません。
- 成果物は`C:\master-course\output\research_phase3_sunny_final_1500s_20260716`と`C:\master-course\output\research_phase3_rain_final_1500s_20260716`、教員向け13枚PPTは`docs/presentations/phase3_weather_model_progress_20260716.pptx`です。両runはdirty worktree上のprovisional evidenceで、strict comparatorは`git_dirty=true`を正しく拒否しました。commit後のclean rerunが正式比較への残作業です。
- 最終回帰は`683 passed, 8 skipped`（localhost BFFを要求する手動E2E `test_multiday_phase1.py`は除外）で、compileall、PPTのPowerPoint render 13/13枚、`git diff --check`も確認しました。

## 2026-07-15 BEV/ICE構成感度と帰庫SOC境界修正

- 正規Phase 3 frontend-weather runnerへ`--available-bev-count`を追加し、永続在庫を変更せず、初期SOC上位のN台だけを当日利用可能とするreadiness感度ケースを実行可能にしました。選択ID・利用可能台数・車種別使用台数/担当便数を監査成果物へ保存します。
- 晴天・120秒探索で、利用可能BEV35台は使用BEV17/ICE15、利用可能BEV10台は使用BEV8/ICE24となり、全264便・全hard validation通過の異なる構成を確認しました。Stage 1 gapは100%/15.68%のため、費用最適性や構成優劣の結論には使用しません。
- 最初の感度probeが、帰庫回送energyを帰庫完了後slotのtransitionへ1slot遅く計上するP1を露出しました。slot-start SOC定義に合わせ、帰庫完了slotへ至る直前transitionで控除し、同slot充電が帰庫直後SOC下限割れを隠せないよう修正しました。
- focused regressionは`41 passed`、全回帰は`680 passed, 8 skipped`、compileallとgit diff checkも通過しました。詳細・実行artifact・研究上の限界は`docs/notes/DEVELOPMENT_NOTES.md`の2026-07-15項に記録しています。

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
