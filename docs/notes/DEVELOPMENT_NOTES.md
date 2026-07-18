# E-Bus Scheduling Optimization — Research Experiment Log

> **目的**: 電気バス運行・充電スケジューリング最適化の修士論文研究実験ログ。
> GUI変更履歴は `app/CHANGELOG.md` へ移動済み。本ファイルは実験・結果・設計判断のみ記録する。

---

## 2026-07-18 — 7月月間進捗資料と7月17日run限定の可視化監査

### 追補：専門外の聴衆向け説明への改訂

- 月間進捗資料の冒頭を、社会背景、研究背景、研究目的、手法の順に変更した。説明の中心を数式やsolver用語ではなく、「何を入力するか」「何を決めるか」「どの条件を確認するか」へ置いた。
- 本研究で説明する運用手順は、(1) 運行開始前に一日分の担当車両と充電の基本計画を作る、(2) 毎正時に実際のEV電池残量、営業所蓄電池残量、太陽光予測、その日ここまでの最大受電を更新する、(3) 担当車両を固定したまま当日残り時間の充電計画を作り直す、(4) 次の1時間だけ実行して繰り返す、の四段階である。「1時間の最適化」は1時間先だけを見る意味ではなく、毎時間、その日残りの計画を更新する意味で用いる。
- `external_charge_input_lower_bound_kwh`は資料上で「走り切るために、少なくとも必要と見積もった充電量」と説明する。便の走行、始発・便間・帰庫の移動、終業時に残す車両電池量を合計し、朝の車両電池を差し引いて見積もる。ただし、充電する時刻、車両が営業所にいるか、充電器の混雑、受電上限、PV発電時刻との一致をまだ確認していないため、実際の充電量又は実行可能な充電計画とは扱わない。
- `bess_initial_dischargeable_energy_credit_kwh`は資料上で「朝の営業所蓄電池のうち、終業時に残す目標を超える部分」と説明する。例えば朝300 kWhで終業時にも300 kWhを残す条件なら、朝の蓄電池から使える余分は0 kWhである。終業時目標を120 kWhへ下げた場合の180 kWhは、無料の省エネ効果ではなく翌日へ残す在庫を取り崩した量である。
- `pv_energy_credit_kwh`は「一日合計では太陽光でまかなえる可能性がある量」と説明する。バスが営業所にいる時間と発電時刻の一致を見ていないため、実際の`PV→bus`又は`PV→BESS`とは呼ばない。
- 7月17日の2 runは日次計画側の不具合確認であり、毎正時の充電見直しによる効果を評価した結果ではない。資料では、研究の目標手法と今回の保存runの結果を別の章で説明し、逐次最適化の有効性を示したとは記述しない。

### 結果データの境界

- 月間進捗資料の定量図は、依頼どおり`C:\master-course\output\2026-07-17\run_20260717_0003`と`run_20260717_1240`だけを読み取る。7月16日の暫定晴雨結果、別の15分baseline、IIS成果物、ほかの出力フォルダは月間資料の結果図へ混ぜない。
- 2 runはいずれもcommit`8730505`、60分刻み、264便、60台、time limit 1,500秒、要求gap 10%である。Stage 1は264便の割当候補を持つが`time_limit`、MIP gap 48.367%、runtime約750.3秒。Stage 2は`infeasible`で、canonical最終結果は担当0便・未充足264便、`research_kpi_eligible=false`である。
- 保存済み`summary.json`と`kpi_summary.json`は未充足0便を記録し、`summary.json`は費用0円をactual costとして扱うため、canonicalとのP0級矛盾を監査証拠として示す。PV入力は高見込み614.709kWh/日・最大81.271kW、低見込み101.114kWh/日・最大12.941kWだが、`weather_pv_forecast_applied=false`かつStage 2不可行なので、PV→bus/BESS、抑制、系統購入、費用、SOC、CO₂の天候効果は主張しない。
- successor上限8により、候補arcは678,600本から113,712本へ削減され、564,888本、83.2%が除外された。保存metadataの`supports_exact_milp=true`をそのまま研究主張へ使わず、「縮約ネットワーク上のMILP」として記述し、8/16/32/無制限の感度分析を残課題とする。

### 文献から逆算した図表と資料構成

- No55の車両運用＋SOC、No51の充電イベント・ピーク需要、No16/No62の電源別時系列・費用・不確実性、中野ほかのPV配分・逐次最適化、上條ほかの時間別充電需要を図表要件として整理した。対応表は`output/monthly_progress_202607/literature_visual_catalog.csv`に保存した。
- 7月17日runから正当に掲載できるのは、solver品質、便カバレッジ監査、PV入力時系列の3種類である。正式割当、充電、SOCのledgerは0行なので、車両ダイヤ、EV SOC、電源別需給、費用、CO₂は「0」ではなく「掲載不可」とした。IISも`stage2_diagnostics_written=false`のため、別runの根因図を流用しない。
- `scripts/build_july_progress_evidence_20260718.py`は2 run以外のsource拡張を拒否し、9図、`run_audit_20260717.csv`、`artifact_row_counts_20260717.csv`、`audit_summary_20260717.json`を生成する。
- `scripts/build_july_monthly_progress_20260718.mjs`は`@oai/artifact-tool`で既存18枚の東京都市大学資料から作成した`template-starter.pptx`をimportし、全slideを一対一で再利用する。ロゴ、白背景、濃青見出し、下部要点帯、ページ番号、既存image frameを保持し、7月16日の暫定結果図だけを7月17日限定監査図へ置換した。speaker notesには各slideの話すポイントと根拠pathを保存した。
- 成果物は`docs/presentations/monthly_progress_20260718.pptx`。18/18枚をPNGへrenderして全体montageと重点slideを目視確認し、`slides_test.py`はoverflow 0、template fidelity checkerはissue 0でpassした。数値監査scriptも再実行し、2 runのみ、Stage 1候補264、canonical担当0/未充足264を確認した。

### 次の実験

- 最優先は、Stage 2不可行時のIIS自動保存、15分・系統のみ・設備緩和条件での264便baseline、制約の段階的復元、clean commit・固定input・違反0・KPI整合の確認である。正式baselineが受理gateを通るまで、費用・エネルギー・CO₂の比較図は解禁しない。

### 残り2週間の不足整理と優先計画（2026-07-19～2026-07-31）

- 自分から上げた問題として、今後の作業候補をすべて同じ優先度で並べると、不可行原因の特定、15分baseline、24回の毎正時更新、晴雨比較、予測誤差、successor感度を2週間で同時に進めることになり、どれも受理条件を満たさないまま月末を迎える危険がある。新機能の追加ではなく、研究結果を信頼できる証拠の不足を先に潰す。
- 現在足りない証拠は、(1) Stage 2が不可行になった制約を特定できるIIS又は同等の診断記録、(2) 15分刻みで264/264便を運行できる正式baseline、(3) SOC・充電器・受電・接続・電力収支の違反0、会計値一致、fallbackなしを示す独立検証、(4) EV SOC・BESS SOC・既発生最大受電を引き継ぐ24回の毎正時連鎖、(5) PV予測誤差、晴雨、successor上限による影響の比較、の5点である。
- 必須作業（7月19日～25日）は、不可行時の診断記録を自動保存し、系統電力のみ・設備緩和条件から開始して、充電器台数、充電出力、受電上限、BESS、PV、終端SOC条件を一つずつ戻すことである。15分刻み、全264便担当、未担当0便、独立違反0、fallback=false、postsolve repair=false、会計値一致を満たす1 runを、clean commit、input hash、設定、seed、time limit、gapとともに固定する。
- 次点作業（7月26日～31日）は、固定した日次割当を使い、毎正時にEV SOC、BESS SOC、既発生最大受電、PV予測を引き継いで24回完走することである。実行済み区間の二重計上がなく、各時刻で可行であることを確認し、一日計画との費用、系統購入量、最大受電、PV利用、EV/BESS SOCを比較する。
- 余力がある場合だけ、PV予測誤差0%・±10%・±20%、晴雨比較、successor上限8・16・32・無制限の順に感度分析を追加する。正式baseline又は24回連鎖が未完了なら、これらを先に実施しない。
- 2週間の完了条件は「15分刻みの正式baseline 1本」と「毎正時更新を24回つないだ1ケース」の二つである。この二つを満たした後に限り、先行文献に対応する車両運用、EV/BESS SOC、電源別需給、費用、CO₂、solver品質の図を正式結果として追加する。

### 追補：不足点の実装確認と最初のモデル修正

- 実際の画面実行経路を、BFFの`_run_optimization`から`ProblemBuilder`、`OptimizationEngine`、GurobiのStage 1、固定割当を受け取るStage 2まで追跡した。ここで、研究結果を増やす前に直すべき不足として、(1) 画面からのPhase 3実行ではStage 2不可行時の診断保存先が渡されない、(2) Stage 2が候補接続の削減情報を引き継ぐ処理に未定義変数があり、終了経路で例外になり得る、(3) Stage 1が同じ車両・同じ15分枠の充電機会を複数回数え得る、(4) 実行可能解があっても厳密性の受理条件を満たさないだけで`NO_VALID_INCUMBENT`（有効な解なし）へ書き換える、の4点を確認した。
- BFFはPhase 3実行時に`<run output>/diagnostics`をcanonical problemへ明示的に渡すようにした。今後Stage 2が不可行になった場合、既存の割当候補、車両別エネルギー事前確認、IIS、診断要約を画面実行でも同じrun配下へ保存できる。この追補の短時間runはStage 2が可行だったため、IISが新たに生成されたとは主張しない。
- Stage 2はStage 1 planに保存された`arc_pruning_summary`を読み、候補接続を1本でも削っていれば`supports_exact_milp=false`を維持するようにした。これにより、Gurobiが作成済みモデルを解けたことと、削減前の全候補に対する厳密解であることを区別する。未定義変数による例外も回帰テストで再現して修正した。
- Stage 1のSOC事前確認は、便を担当したという情報だけから便の前後を一律に充電可能とは数えない。選ばれた車両の流れに対応する「出庫前」「営業所へ戻って次便まで待機している時間」「帰庫後」だけを充電候補とし、同じ車両・同じ時間枠の充電は最大1回分に制限する。例えば100 kWの充電器、15分枠、効率95%なら、Stage 1が1枠で見込める車両への充電は最大23.75 kWhであり、同じ枠を複数便の窓として重複加算しない。
- このStage 1制約は、明らかに充電が間に合わない割当をStage 2へ渡しにくくするための事前確認である。営業所全体の充電器台数、受電上限、PV・BESS、実際の充電量は引き続きStage 2が確認する。運行接続条件`arrival + turnaround + deadhead <= next departure`、時刻表、`operator_id`、距離、Stage 2のSOC・電力制約は変更していない。
- 最初の素朴な重複防止案は、各便と各時間枠の重なりを個別に禁止したため、264便・15分ケースでStage 1の追加制約が155,575件まで増えた。この性能問題を自分で検出し、その案は採用せず、選択された車両経路が作る充電候補だけを1枠1回へまとめた。再診断では追加制約6,755件となり、同じ目的のまま約95.7%削減した。
- 30秒制限の診断run`output/model_fix_probe2_20260718`は、264/264便担当、未担当0、Stage 1は時間制限内の実行可能解、Stage 2はoptimal、SOC・接続・充電器・受電等の独立検証違反0だった。表示も`NO_VALID_INCUMBENT`ではなく`feasible`を保持する。一方、successor上限8で564,888本の候補接続を削っており、worktreeもdirtyなので、`research_run_accepted=false`、研究KPI掲載不可のままとした。このrunはモデル動作確認であり、7月の正式結果又は晴雨比較には使わない。
- テストは、同じ15分枠を重複して充電できない小ケース、Stage 2の削減情報引継ぎ、画面実行の診断保存先、実行可能解のstatus保持を追加した。対象回帰は`85 passed`、全回帰は`python -m pytest -q --ignore=test_multiday_phase1.py`で`733 passed`。`test_multiday_phase1.py`はlocalhost BFFを前提とする手動E2Eのため除外した。
- 次に足りないものは、モデル機能ではなく正式な証拠である。最優先はclean commitと固定inputで15分baselineを再実行し、264/264便、全独立検証違反0、fallbackなし、会計整合、設定・hash・gapを保存すること。その後、同じ日次割当を固定した毎正時更新を24回つなぐ。PV予測誤差、晴雨、successor上限8/16/32/無制限の感度分析は、この2点が完了した後に行う。

### 追補：正式15分baselineの実行契約

- `scripts/run_research_phase3_minimal.py`に`--milp-max-successors-per-trip`を追加した。正式baselineの既定値は`0`で、候補接続を削らず全候補を保持する。8、16、32は後続の感度分析で明示指定する。候補上限はinput auditとexperiment hashへ含め、異なる上限のrunを同一実験として扱わない。
- 固定入力はscenario`b23fd26c-1233-4c73-bb9e-bdb8b1584760`、prepared input`prepared-789ce8197d83c758-0b337aa1f091e729`、prepared SHA-256`5f133b1dddabd7295a5e60e429ad008d966c690e70e19c2bcb6327d288094913`、service date`2025-08-10`、264便、BEV35台・ICE25台、15分96枠、初期EV SOC一律80%、PV/BESS/天候運用なし、seed 42、要求gap 10%、time limit 1,500秒とする。
- 最終planを`CostEvaluator`でもう一度評価し、電力量料金、燃料費、需要料金、車両費、運転手費、各種追加費用、総費用の差がすべて`1e-6円`以下かを`accounting_recalculation`へ保存する。これはStage 1とStage 2が一つの総費用を大域最小化したという意味ではなく、取得した最終planから会計値を再計算して同じ金額になることの確認である。
- `scripts/verify_research_phase3_baseline.py`は、clean commit、prepared input hash、15分96枠、264/264便、独立検証違反0、Stage 1 incumbent、Stage 2 optimal、fallbackなし、postsolve repairなし、候補接続削減0、会計再計算一致、研究可行性受理を一括確認し、`formal_baseline_verification.json`をrun配下へ保存する。
- コミット前レビューで、候補接続を削ったMILPにも`eligible_for_main_benchmark=true`と`Exact core solver`が残るP1表示矛盾を検出した。`supports_exact_milp=false`のMILPはmain benchmark対象外、appendix又は感度分析用とし、candidate generationも`successor_pruned_branch_and_cut`と表示する。全候補を保持した場合だけ`full_network_branch_and_cut`としてmain benchmark候補にする。
- build-onlyで上記固定入力をmaterializeし、`milp_max_successors_per_trip=null`（無制限）、prepared SHA、trip/vehicle/charger/initial SOC hashを確認した。正式solver runはcore_newへコミット後のclean worktreeで実行し、結果は次の追補へ記録する。

### 追補：正式15分baselineの受理結果

- `core_new` commit`1b5deeb31fcaddeffea4b78caf59655b6df2a603`のclean worktreeから、`MC_OUTPUTS_DIR=C:\master-course\output`を明示し、固定prepared inputを使って15分grid-only baselineを実行した。成果物は`C:\master-course\output\research_phase3_grid_only_15min_formal_20260718_full_network`、experiment hashは`86dca0a3c94d9e86366ea467e04e25d28095931beff99a5d2f071e2f21c0d4de`である。
- 候補接続は678,600本をすべて保持し、削減0本、`supports_exact_milp=true`、`git_dirty=false`となった。Stage 1は750.265秒でtime limit、有効な全便割当を取得した。目的値640,597.893円相当、best bound 560,000円相当、gap 12.582%で、要求gap 10%には届いていない。そのため、この結果を「最適解」又は「総費用の大域最小解」とは呼ばない。
- Stage 2は0.265秒でoptimalとなり、264/264便、未担当0、重複0、時間重複0、接続違反0、EV SOC上下限違反0、BESS違反0、受電上限違反0、充電器同時使用違反0、最大fragment数1を確認した。使用車両は32台で、`vehicle_schedule.csv`は264行・重複しない264便である。
- `fallback_applied=false`、`postsolve_assignment_rebuilt=false`、`postsolve_charging_recomputed=false`、SOC repairなし、機会充電top-upなしであり、solver解を別の計画へ差し替えていない。研究可行性gateは`research_run_accepted=true`、`research_feasibility_eligible=true`で受理された。
- 最終planの会計総額は707,747.004円である。最終planをもう一度評価した結果、電力量料金、燃料費、需要料金、車両費、運転手費、各追加費用、総費用の全16項目で残差0円となり、許容値`1e-6円`を満たした。ただしPhase 3はStage 1とStage 2を一つの会計総費用で同時最小化していないため、`research_cost_kpi_eligible=false`であり、この金額を大域最小費用とは扱わない。
- `scripts/verify_research_phase3_baseline.py`による確認は14項目すべてpassし、failed checkは0件だった。証拠は`formal_baseline_verification.json`、`summary.json`、`solver_result.json`、`controlled_model_validation_input.json`、`research_run_manifest.json`、`vehicle_schedule.csv`に固定した。
- 次の感度分析は、この正式baselineと同じprepared SHA、15分刻み、初期SOC、設備、単価、seed、time limitを維持する。独立変数は、(1) successor上限8/16/32/無制限、(2) 晴天/雨天のPV時系列、(3) 毎正時のPV予測誤差0%・±10%・±20%とする。まずsuccessor感度で計算量と割当差を確認し、その後に同一候補設定で晴雨、最後に24回連鎖上で予測誤差を評価する。

---

## 2026-07-17 — Result-validity gate and strict core_new review

- 2026-07-17 UI runsをcurrent call pathで再監査した。canonical resultは両方`infeasible`、未担当264便、objective非有限、`research_kpi_eligible=false`である一方、旧reader-facing summary/KPIは未担当0便・0円・会計一致trueだった。
- BFF保存とcanonical reporting再構築の双方にsolution-validity gateを追加した。不可行/fallback/未検証結果は費用、PV→bus/BESS、grid import、CO₂、SOC統計を`null`にし、canonical担当数とfailure stageを出す。backfill時の`results.xlsx`と`experiment_report.md`にも無効状態を反映する。solver resultとledgerは診断証拠として保持する。
- successor pruningが1本でも実行されたMILPについて`supports_exact_milp=false`とした。Gurobiのconstructed-model optimalityは、削減前の候補接続網に対するglobal optimalityを意味しない。
- `scripts/audit_core_new_review_20260717.py`は、不可行KPI矛盾、15分clean baselineと60分dirty weather runのgap、Stage 2 IIS、暫定晴雨エネルギー/費用を別証拠層として再描画する。詳細は`docs/reviews/core_new_strict_review_20260717.md`。
- 回帰検証は`python -m pytest -q --ignore=test_multiday_phase1.py`で`730 passed`。変更対象Pythonファイルの構文、差分whitespace、不可行run複製のJSON/CSV/Excel gate再構築も確認した。除外testはlocalhost BFFを前提とする手動E2Eである。

---

## 2026-07-16 — BESS terminal policy and day-ahead/hourly charging re-optimization

### 追補: 終端方針UI・状態連鎖・研究受理手順

- 定置型BESSの終端方針を`minimum_only` / `return_to_initial` / `fixed_target`としてdomain modelへ追加した。SOC上下限と終端下限は全方針でhard constraintである。目標なしの場合に終端SOCを初期SOCへ戻す意味は持たせない。正のlegacy目標は`fixed_target`へ移行して既存実験の意味を保存する。
- `ProblemBuilder`、Gurobi Stage 2、独立feasibility、rolling override、BFF scenario normalization、研究出力・監査が共通resolverを使う。`minimum_only`では目標偏差を計算せず、終端下限不足だけを違反とする。Phase 3 Stage 2の目標hard制約は維持し、偏差penaltyだけだった統合MILPにも目標±許容幅のhard制約を追加した。従って旧統合Phase 4成果物は数学的に同条件ではないが、旧300kWh固定Phase 3成果物を自動的に運用範囲のみケースへ読み替えることもしない。
- Tkフロントでは営業所設備・充電インフラ画面に3方針と任意目標%を追加し、詳細設備画面では設備容量・PV、SOC・終端方針、電力経路・費用、データ確認へ分割した。設定入口を上部ハブへ集約し、画面規則は`DESIGN.md`へ保存した。
- `build_next_execution_state()`は、solver resultの`vehicle_soc=slot start`と`bess_soc=slot end`の違いを保持し、実行済み受電から需要ピークを更新する。欠損SOCをscenario初期値で補完しない。毎時CLIは`--end-time`による連鎖と`--pv-forecast-updates-json`による時刻別予測更新に対応した。
- 1500秒晴雨再計算、24時間連鎖、PV予測誤差、終端3方針、2日連続評価、seed感度は手動計算待ちであり、完了扱いにしない。scenario/prepared ID、コマンド、成果物、受理gateは`phase3_manual_validation_runbook_20260716.md`を正本とする。

### Literature-based interpretation

- 定置型蓄電池の`initial SOC = terminal SOC`は物理法則ではなく、評価期間外のエネルギー持ち出しを防ぐ境界条件である。上條ほか（2024）とQin et al.（2016）は代表日を同条件で反復するため同値条件を採用する。中野ほか（2024）は終端を初期値±充電器1枠相当に制限し、中野ほか（2025）は2日先まで計画して1日だけ実行し、終端SOCを翌日の初期SOCへ引き継ぐ。
- 本研究の晴雨比較では、初期・終端とも300 kWhに固定することで、天候間でBESS在庫の持ち出し量を揃える。この条件を「理想」又は設備上の必須条件とは表現しない。`minimum_only`は運用範囲だけを守る感度条件であり、複数日又は終端エネルギー価値を入れない単日費用とは直接比較しない。
- 参考: 上條ほか「電気自動車バスのマクロな充電需要推定に関する検討」（2024）、中野ほか「都市の太陽光地域余剰電力活用と運行の低炭素化を目的とした電気バス充電計画法の検討」（2024）、中野ほか「電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価」（2025）、九蘭和樹 修士論文（2025）、Qin et al., *Transportation Research Part A*, 94 (2016)。

### Terms made explicit

- `external_charge_input_lower_bound_kwh`は、選択したBEV便・始発/便間/帰庫回送・実効終端SOCに必要なエネルギーから初期EV SOCを差し引き、充電効率0.95で割った正部分である。時間帯、所在地、充電器競合、契約電力、需要料金を含まないため、Stage 1割当探索用の楽観的必要条件であり、実現充電量ではない。
- `pv_energy_credit_kwh`は、その最低入力に対する営業所別・日量集約のPV控除である。PVと車両滞在時間の一致を表さず、実際の`PV→bus`はStage 2で決める。
- `bess_initial_dischargeable_energy_credit_kwh = max(initial_bess_soc_kwh - terminal_bess_requirement_kwh, 0) × discharge_efficiency`とした。現行晴雨比較は初期/終端300 kWh、効率0.95なので0 kWhであり、「初期BESS余剰」という曖昧な語だけで説明しない。

### Two-level optimization and runtime evidence

- 運用階層を、(1) 前日/日初にPhase 3で日次の車両割当を決定、(2) 毎正時に割当を固定したまま当日残り時間の充電・PV・BESS・系統運用を再最適化、(3) 先頭60分だけ実行、に分けた。中野ほか（2025）のreceding-horizon原理を1日計画・1時間更新へ適用した本研究の実装であり、同論文と同じ時間幅とは主張しない。
- 毎時経路はcanonical tripを再利用し、時刻表、`operator_id`、運行接続、割当を変更しない。開始時刻がslot境界であることを検査し、開始後は割当EV全車の実測SOC、実測BESS SOC、on/off-peak既発生最大需要を必須にする。過去の走行・充電・PVは目的関数へ再計上せず、現在時刻から当日末だけを解く。
- 1500秒の日次runは晴天775.530秒、雨天776.519秒。120/30秒の日次短縮は晴天146.035秒、雨天144.979秒だが、Stage 1 gap 100%かつ両日BEV/ICE担当便54/210となり、天候別構成差を失ったため不採用。scenario/prepared input/service/depot/trip hash/vehicle hashと接続・回送の入力契約確認を追加した後の日次割当固定5:00再最適化は晴天1.964秒、雨天2.021秒（Stage 2 solve 0.064/0.062秒）でoptimalとなり、終端300 kWhでは元の電力運用と会計費用を再現した。
- 保存済み割当の復元時は、空/重複duty、未知/重複trip、served/unserved不一致、未知vehicle、vehicle type不一致を拒否する。実測EV SOCとBESS SOCも現在scopeに存在しないIDを拒否する。これにより、別scenario又は古いprepared inputの日次解を毎時制御へ混入させない。
- BFFの毎時結果は、次回更新でも同じ日次割当を参照できるよう、検証済み`canonical_solver_result`、scenario、prepared input、service/depot scopeを保持する。初回結果による日次解上書きで2回目が失敗する問題を回帰テストで防止した。
- 5:00結果のEV/BESS実状態と既発生需要ピークを6:00へ渡す実シナリオ試験で、独立SOC検証が実測時点より前の走行を再控除するP1を検出した。rolling時は`rolling_start_slot_index`より前を除外し、進行中便は残りslotだけ、便間回送は現在時刻以降の未完了割合だけを検証する。修正後の6:00再計算は晴天2.032秒、雨天2.006秒、両方Stage 2 optimal・264/264便・違反0・BESS終端300 kWhとなった。
- 最終回帰はGurobiライセンスを明示して`717 passed, 8 skipped`。compileall、`git diff --check`、design.md lint、Tk実画面確認、PPT 18枚のoverflow検査、テンプレート忠実度検査issue 0もpassした。未解決P0/P1は0件である。
- 晴天で終端下限だけを120 kWhにした感度は709,097.774円で、300 kWh終端の713,032.185円より3,934.411円低い。ただし180 kWhのBESS在庫減少を翌日に引き継いでいないため、この差を運用費削減効果として採用しない。

### Implementation and remaining validation

- 実装: `src/optimization/common/problem.py`、`src/optimization/milp/solver_adapter.py`、`src/optimization/milp/engine.py`、`src/optimization/rolling/reoptimizer.py`、`src/optimization/rolling/day_ahead_hourly.py`、`bff/routers/optimization.py`、`scripts/run_research_phase3_frontend_weather.py`、`scripts/run_hourly_charging_reoptimization.py`。
- 追加検証: Stage別時間配分、絶対時刻PV参照、残り時間slot、固定割当、BESS実測状態、終端policy、SOC serializerを回帰テスト化した。未完了なのは5:00以外の逐次状態での24回連鎖run、予測誤差感度、複数日終端価値、clean-worktreeでの正式比較である。
- 数式、成果物path、文献と実装の対応は`docs/notes/phase3_literature_and_two_level_optimization_20260716.md`を正本とする。

---

## 2026-07-16 — Advisor-facing BESS, power-balance, and fuel audit deck

### Verified evidence path

- `scripts/audit_phase3_weather_energy_balance.py`は、`C:\master-course\output\research_phase3_sunny_final_1500s_20260716`と`research_phase3_rain_final_1500s_20260716`のimmutable resultを読み、solverを再実行せず、persisted scenario / prepared scope → `ProblemBuilder.build_from_scenario()` → weather policyのcanonical inputだけを再構築する。recorded `trip_input_hash` / `vehicle_input_hash`と一致しない場合は停止する。
- auditは60分24slotについて、PV生成と3行先、bus charging inputと3電源、grid import、BESS slot-start/slot-end SOC、BESS効率式、営業中EV/ICE台数、ICE営業/便間回送距離と燃料を再計算する。JSON/CSVは`C:\master-course\output\phase3_weather_energy_audit_20260716`に保存した。

### BESS and electrical balance results

| 指標 | 晴天 | 雨天 |
|---|---:|---:|
| BESS初期 / 終端SOC [kWh] | 300 / 300 | 300 / 300 |
| BESS観測範囲 [kWh] | 120–480 | 226.950–322.025 |
| BESS入力 / bus供給 [kWh] | 378.947 / 342.000 | 100.079 / 90.321 |
| BESS往復損失 [kWh] | 36.947 | 9.758 |
| PV発電 [kWh] | 614.709 | 101.114 |
| PV→bus / BESS / curtail [kWh] | 163.827 / 378.947 / 71.935 | 1.035 / 100.079 / 0.000 |
| grid import / peak [kWh, kW] | 1,015.594 / 95.445 | 1,000.679 / 120.245 |
| bus charging input [kWh] | 1,521.421 | 1,092.035 |
| 最大帳尻残差 [kWh] | 3.41e-12 | 1.98e-12 |

- BESS式は`SOC_end = SOC_start + 0.95*(PV→BESS + grid→BESS) - (BESS→bus)/0.95`で再照合した。grid→BESSはfrontend設定どおり両日0kWh。PV式、bus charging source式、BESS式は各slotで`1e-6 kWh`以下を満たす。
- BESS終端SOC同値は自然に得た結果ではなく、frontend由来の`bess_terminal_soc_target_kwh=300`をハード制約として満たした結果である。出力`bess_soc_kwh_by_depot_slot[0]`は第1slot終了値であり初期値ではないため、図ではmetadataのslot-start 300kWhを明示してから各slot-endへ接続した。

### Vehicle use and fuel consistency

- 実入力在庫は両日ともBEV35/ICE25であり、依頼文のBEV35/ICE26とは1台不一致。現在のrunからICE26条件を主張せず、正本が26台ならscenario修正後に両日を再計算する。
- 使用BEV/ICEと担当便は晴天16/16台・141/123便、雨天15/17台・119/145便。晴天でもEV19台が未使用で、PV限界費用0円だけでは全車使用にならない。接続可能性、SOC、充電時刻、車両使用費とStage 1 incumbentが同時に決める。
- ICE fuel ledgerを評価器と同じ定義で再構成した。晴天は営業1,162.675km + 便間回送124.500km = 284.773L、雨天は営業1,404.047km + 便間回送134.400km = 340.364L。150円/Lを掛けた燃料費はsolver resultとの差がそれぞれ`6.55e-11円`、`1.46e-10円`で一致する。
- `fuel_cost_final_source=provisional_distance_based`、`refueling_schedule=[]`、realized refuel cost=0円である。従って「割当運行距離と燃料費は整合」と報告できるが、燃料タンク残量、給油時間、給油設備容量を満たす実現給油計画とは報告しない。

### Presentation and visual QA

- `scripts/audit_phase3_weather_energy_balance.py`の監査JSONへ`scenario_parameters`を追加した。総制限1500秒、段階別最大750秒、実測solver時間、MIPGap 10%、seed 42、60分×24枠、TOU 18/22/19円/kWh、需要料金1日換算40円/kW、軽油150円/L、CO₂ 1円/kg、使用車両費20,000円/台日、充電器90kW×5+50kW×5、受電上限1000kW、PV/BESS、SOC方針、費用flags/weightsを保存済み入力から抽出する。
- `scripts/build_phase3_energy_balance_presentation.py`は監査JSONだけを数値源とし、`刘承洋_9月発表用.pptx`の白背景、濃青タイトル、青罫線、東京都市大学マーク、Meiryo、比較図、下部要点帯を参照して18枚のPPTを生成する。成果物は`docs/presentations/phase3_weather_energy_balance_progress_20260716.pptx`。
- 新たに、最適化システムの6修正、Stage 1/2の役割、EV外部充電量下界式、計算/設備条件、費用/環境条件を4枚で明示した。UI風の角丸カードと装飾矢印を排し、研究発表用の表・数式・角形パネルへ統一した。全定量図は晴天・雨天を同一スライドで比較し、全18枚のnotes欄に`目標xx秒`と読み上げ原稿を保存した。
- PowerPoint COMで18/18枚を1600×900 PNGへ個別renderし、notes本文も18/18枚で非空を確認した。モデル式、パラメータ表、比較図、凡例、文字切れを目視確認した。
- 本PPTは未コミット変更を含む二段階モデルの暫定可行解で、Stage 1 gapは晴天13.109%、雨天12.942%。大域最適、正式研究KPI、一意な車両構成という主張はしていない。正式化には変更内容を整理した版での同条件再実行、ICE在庫正本確認、燃料給油モデル化、複数seed / gap縮小が必要。

---

## 2026-07-16 — Weather-aware Stage 1 assignment proxy and final provisional 1500-second pair

### Verified call chain and root cause

- actual research pathは`scripts/run_research_phase3_frontend_weather.py` → persisted frontend scenario / prepared scope materialize → `ProblemBuilder.build_from_scenario()` → `apply_weather_policy_to_problem()` → `OptimizationEngine.solve()` → `GurobiMILPAdapter`のStage 1割当 → 固定割当Stage 2充電dispatch → 独立validation / accounting exportである。fallbackとpostsolve repairは無効のまま維持した。
- 2026-07-14の受理済み95ade40結果は、晴雨とも使用BEV/ICE=17/15、BEV/ICE担当便=54/210だった。Stage 2ではPV・買電・ピーク・会計費用に天候差が出たが、Stage 1目的はICE燃料・ICE CO₂・使用車両費だけで、天候別PV量・BEV充電費用を含まなかった。このため割当探索から見た晴天と雨天が同一であり、同じ車両構成はsolverの異常ではなくモデル分離の帰結だった。

### Mathematical change: aggregate Stage 1 charging-cost lower bound

- `src/optimization/milp/solver_adapter.py`に`Stage1EnergyCostProxy`を追加した。各BEVについて、`trip + startup deadhead + inter-trip deadhead + return deadhead + effective terminal SOC − initial SOC`の正部分を充電効率0.95で割り、必要な外部充電入力を表す。営業所別に集約し、PV、usable initial BESS surplus、gridを単価順に配分する。PV限界費用はフロント設定の`pv_marginal_charge_cost_yen_per_kwh=0`、gridは最安TOUとgrid CO₂費の和を使う。
- この項はStage 1の割当探索へ天候差を渡す**下界代理**である。PV/BESS/充電の時刻整合、充電器競合、系統上限、需要料金、battery headroomは含めず、Stage 2が引き続き厳密に決める。従って`stage1_energy_cost_proxy_result.objective_jpy`を実現電気料金又は会計総費用として報告しない。`objective_semantics=two_stage_assignment_energy_proxy_then_fixed_charging_not_global_total_cost`でglobal同時最適化との違いを明示した。
- `stage1_energy_cost_proxy_configuration`、天候別`stage1_energy_cost_proxy_weather_input`、割当後の`stage1_energy_cost_proxy_result`をplan metadata、engine solver metadata、research summary、比較reportへ伝播した。source変数がPV 0円区間で退化しても成果物値が任意にならないよう、選択割当の正味必要量から単価順に決定論的再構成する。
- 120秒probeでは同じ使用BEV/ICE=17/15、BEV/ICE担当便=54/210、外部充電必要量616.397kWhに対し、晴天はPV614.709kWh・grid1.687kWh・代理費用31.216円、雨天はPV101.114kWh・grid515.282kWh・代理費用9,532.725円となった。これはPV 0円と天候別PV量がStage 1目的へ入ったことの診断証拠であり、最適割当差の証拠ではない。

### Self-detected infeasibility and performance correction

- 初回の晴天1500秒proxy run（`output/research_phase3_sunny_energy_proxy_1500s_20260716`）はStage 1でBEV190便 / ICE74便を選んだがStage 2 infeasibleとなった。IIS車両`e0772317-52e2-4e70-bfc8-1eb486f0f75c`は、始発回送後にslot 1–18でhome depotにおらず、slot 19のSOC下限を満たせなかった。旧Stage 1 time relaxationがidle slotなら所在地を問わず充電可能としていたため、営業所外充電を発明したことが根本原因である。このrunは研究結果に不採用。
- 第1修正はslot別の所在地対応SOC必要条件69,300本を追加し、偽充電を除いた。しかし`output/research_phase3_sunny_energy_proxy_location_1500s_20260716`ではStage 1が750秒でbound 0・gap 100%となり、性能退行が大きいため不採用とした。
- 採用実装は、各BEV・各slot境界で、累積した便/始発/便間/帰庫energyを、初期reserve余剰と割当に裏付けられたhome-depot充電窓の累積上限以下にする必要条件である。共有充電器・系統・PV/BESS競合とwindow重複は楽観側に緩和するためStage 2の代替ではない。制約数は875本で、slot別案から98.7%削減した。最終source metadataは`optimistic_cumulative_home_depot_energy_necessary_condition`である。provisional 1500秒pairはmetadata-only改名直前に起動したためsummary内に旧labelが残るが、実行した数理制約は875本の累積版である。clean rerunでは新labelへ統一する。

### Provisional 1500-second results

| 指標 | 晴天 2025-08-05 | 雨天 2025-08-10 | 雨天 − 晴天 |
|---|---:|---:|---:|
| 使用BEV / ICE [台] | 16 / 16 | 15 / 17 | −1 / +1 |
| BEV / ICE担当便 | 141 / 123 | 119 / 145 | −22 / +22 |
| Stage 1 objective [JPY] | 698,606.160 | 708,180.587 | +9,574.427 |
| Stage 1 best bound [JPY] | 607,025.881 | 616,527.390 | +9,501.509 |
| Stage 1 gap | 13.109% | 12.942% | −0.167pp |
| Stage 1 proxy外部入力 [kWh] | 1,521.421 | 1,092.035 | −429.386 |
| Stage 1 proxy PV / grid [kWh] | 614.709 / 906.712 | 101.114 / 990.921 | −513.595 / +84.209 |
| Stage 1 proxy費用 [JPY] | 16,774.166 | 18,332.040 | +1,557.874 |
| Stage 2実現grid import [kWh] | 1,015.594 | 1,000.679 | −14.916 |
| Stage 2実現peak [kW] | 95.445 | 120.245 | +24.801 |
| 電力費 / 需要料金 [JPY] | 25,254.232 / 3,817.780 | 25,266.405 / 4,809.813 | +12.173 / +992.032 |
| 燃料費 [JPY] | 42,715.982 | 51,054.642 | +8,338.660 |
| 会計総費用 [JPY] | 713,032.185 | 722,511.345 | +9,479.160 (+1.329%) |

- 出力は`C:\master-course\output\research_phase3_sunny_final_1500s_20260716`と`C:\master-course\output\research_phase3_rain_final_1500s_20260716`。両方ともGurobi 13.0.1、`GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic`、264/264便、60分24slot、BEV35/ICE25、actual inventory SOC、90kW×5 + 50kW×5、1500秒、gap要求0.1、seed 42、Stage 1=`time_limit`、Stage 2=`optimal`、fallback/postsolve repairなし、最大fragment 1、全hard validation違反0である。
- 晴天は雨天よりBEVを1台多く使用し、BEV担当便が22便多い。これはユーザー仮説「PV発電が多く0円なら晴天でEVをより使う」と整合する。ただしStage 1 gapは約13%で、global optimum、一意な最適構成、又は差の統計的頑健性は主張しない。
- 雨天はPVが513.595kWh少ないが、BEV担当便も22便少ないため、Stage 2実現grid importは晴天より14.916kWh少ない。一方、ピークは24.801kW高く、燃料費と需要料金の増加で会計総費用が9,479.160円高い。「PV減少なら総買電が必ず増える」という単純説明ではなく、割当変更との内生的な相互作用として説明する。
- 両summaryは`git_dirty=true`のcommit候補worktreeで得たprovisional evidenceである。strict comparatorを実行し、`sunny.git_dirty must be false`で拒否されることを確認した。guardを弱めていない。commit後にclean worktreeから両ケースを再実行し、正式comparison artifactを生成する必要がある。

### Documentation, presentation, and validation

- `README_core_professor.md`はStage 1費用代理の含有/除外項、PV 0円の入力、Stage 2との責任分離、global optimum非主張へ更新した。
- `scripts/build_phase3_progress_presentation.py`を追加し、旧受理済みbaselineと今回のimmutable summaryから13枚の教員向けPPTを生成する。成果物は`docs/presentations/phase3_weather_model_progress_20260716.pptx`。PowerPoint自身で13枚をPNGへrenderし、比較契約、数式、IIS修正、割当、会計、研究限界、結論スライドを目視確認した。
- focused metadata/comparator regressionは`21 passed`。`GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic python -m pytest -q --ignore=test_multiday_phase1.py`は`683 passed, 8 skipped`。除外した`test_multiday_phase1.py`はlocalhost:8000のBFFを要求する手動E2Eである。compileall、PPTのPowerPoint render 13/13枚、`git diff --check`もpassした。
- MIT-style self reviewはCorrectness / Security / Performance / Maintainability / Testabilityと研究妥当性を確認し、P0=0、P1=0、P2=2とした。P2は、(1) dirty成果物をclean commitから再実行してstrict comparisonへ昇格すること、(2) 集約下界がPV/BESS時刻整合・需要料金を含まないためPhase 4同時最適化又はablationで代理精度を検証すること、である。外部`claude` CLIはこの環境に存在せず、Claude Codeレビューは実行できなかった。

---

## 2026-07-15 — BEV availability sensitivity and return-deadhead SOC boundary correction

### 研究上の問いと実装

- 晴天・雨天の既存Phase 3で車両割当が同一だったため、天候差を恣意的な車両biasへ変換せず、「当日運用可能なBEV台数」を独立変数とする感度ケースを追加した。
- `scripts/run_research_phase3_frontend_weather.py` に `--available-bev-count N` を追加した。永続scenarioのBEV35/ICE25在庫は変更せず、materialize後のdeep copy上で、保存済み初期SOCが高い順・同値時vehicle ID順にN台だけをavailableとする。これは整備・充電準備等を表す、決定論的かつ楽観的なreadinessケースである。選択方針、選択/非選択ID、変更前後のavailable台数、`persisted_scenario_modified=false`をinput audit・summary・experiment hashへ保存する。
- summaryへ`fleet_available`、`used_vehicle_count_by_type`、`served_trip_count_by_vehicle_type`を追加した。使用台数比率と担当便比率を混同しないためである。旧`batch_sensitivity.py`と`src.pipeline.sensitivity_runner`はそれぞれ簡易RouteSimulator/旧model factory経路であり、Phase 3の研究結果には流用していない。

### 自己検出したP1と修正

- 最初のBEV10台・120秒probeは全264便をBEV8/ICE24で割り当てたが、独立validationが1台の帰庫直後SOCを`61.46 < 62.80 kWh`として拒否した。Stage 2は帰庫完了時刻をceilしたslotへ帰庫回送energyを載せ、同slot充電との合算後SOCだけを制約していた。このためslot-start semanticsに反し、帰庫直後の一時的な下限割れを同slot充電が隠せた。
- 帰庫回送energyを「最初の帰庫後slotへ至る直前のSOC transition」で控除するよう変更した。これにより帰庫後slotの`SOC >= lower bound`が、同slot充電前の帰庫直後SOCにも適用される。帰庫がhorizon外の場合は従来どおりterminal out-of-horizon loadへ計上する。metadataへ`stage2_return_deadhead_soc_semantics=return_energy_subtracted_in_transition_ending_at_first_post_return_slot`を記録する。
- 同じ入力を再実行し、SOC上下限・BESS・充電器・契約電力・便重複・接続違反がすべて0、Stage 2=`optimal`、全264便担当となることを確認した。fallbackとpostsolve repairは使用していない。

### 120秒探索結果（正式な最適費用比較には不採用）

| 利用可能BEV | 使用BEV/ICE | BEV担当便/全便 | 会計総費用 | Stage 1 gap |
|---:|---:|---:|---:|---:|
| 35 | 17 / 15 | 54 / 264 (20.45%) | 717,249.318 JPY | 100.00% |
| 10 | 8 / 24 | 86 / 264 (32.58%) | 718,059.017 JPY | 15.68% |

- 出力は`output/research_phase3_fleet_mix_sunny_bev35_probe_120s_return_fix`と`output/research_phase3_fleet_mix_sunny_bev10_probe_120s_return_fix`。両方とも晴天2025-08-05、同一prepared input、60分24slot、seed 42、time limit 120秒、PV/BESS/TOU/契約電力・軽油・CO₂単価同一である。
- BEV使用台数は53.125%から25.000%へ変化し、ユーザーが求めた異なる車両構成の可行例は得られた。ただしBEV10台ケースの方がBEV担当便数が多い。これは車両台数比率が電動化便数を直接表さないことに加え、Stage 1の未収束incumbent品質がケース間で異なるためである。
- 利用可能集合10台は35台集合の部分集合なので、厳密最適値は35台ケースが10台ケース以下になるべきである。今回の35台ケースのincumbent objective/会計費用が高い又は同等であることを最適性の知見として解釈してはならない。正式な感度分析には、nested fleet間のincumbent共有、1500秒run、gap/dual boundの併記が必要である。

### 検証と自己レビュー

- `GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic python -m pytest -q tests/test_phase3_controlled_validation.py tests/test_post_return_soc_target.py` → `41 passed`。
- `GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic python -m pytest -q --ignore=test_multiday_phase1.py` → `680 passed, 8 skipped`。除外testはlocalhost BFFを要求する手動E2Eである。
- unit regressionは、BEV availabilityの決定論的選択、永続在庫数不変、範囲外count拒否、帰庫event slotの直前transition選択を確認する。`python -m py_compile`と`git diff --check`もpassした。
- MIT-style self reviewでは、P0=0、P1=0、P2=1（正式感度分析には複数のBEV選択seed又はnested incumbent共有が必要）、P3=0。現時点の成果物は可行性と構成差の探索結果であり、global total-cost optimumの証拠ではない。
- 外部`claude` CLIはこの環境に存在しないため、Claude Codeによる独立レビューは実行できなかった。

---

## 2026-07-14 17:50 JST — Accepted frontend weather runs and guarded accounting comparison

### 実測した受理済み結果

- clean commit 95ade40、Gurobi 13.0.1、GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.licで、実フロントエンド由来の60分・24slot・Phase 3二段階モデルを本実行した。晴天はscenario 771d115b-75b0-49f7-a7f0-25f259a2cd21 / 2025-08-05、雨天はb23fd26c-1233-4c73-bb9e-bdb8b1584760 / 2025-08-10である。どちらもtime_limit_sec=1500、mip_gap=0.1、seed 42、postsolve repairなし、fallbackなしである。
- 両結果ともresearch_run_accepted=true、research_feasibility_eligible=true、264/264便担当、使用32台、最大fragment数1、SOC上下限・BESS SOC/終端・充電器同時使用・契約電力・接続可否の独立validation違反0件となった。晴天/雨天のsummaryはそれぞれoutput/research_phase3_frontend_weather_60min_sunny_95ade40、output/research_phase3_frontend_weather_60min_rain_95ade40に保存した。
- 両ケースのStage 1は約750.3秒でtime_limit、同じincumbent objective 708,727.541、best bound 560,000、gap 20.985%で終了した。Stage 2は固定割当の充電/PV/BESS dispatchをそれぞれ0.062秒・0.067秒でoptimalにした。設定した1500秒は上限であり、二段階実装はStageごとに時間を配分するため、常に1500秒を使い切る設定ではない。

### 比較契約・結果

- scripts/compare_research_phase3_weather.pyを追加した。summaryを直接比較する前に、1500秒・264便・BEV35/ICE25・60分24slotの研究scope、受理gate、完全担当、fragment、全validation、git clean、会計totalと現行研究scopeの正規加算項（electricity/demand/fuel/CO2/vehicle usage）の和の一致を検証する。さらにgit SHA、phase、time limit/gap/seed、SOC semantics、trip/fleet/hash、初期SOC全値、terminal SOC、charger構成、TOU、需要料金、軽油/CO2/使用車両費、cost flags、objective weights、BESSを含むasset設定、Stage 1の必要条件の意味・件数を完全一致させる。不一致なら比較結果を出さずに停止する。
- 許容する差はcase identity、service date、weather/PV provenance、PV case・PV発電量・PV hashだけである。したがって雨天と晴天でコストが同値になるような既存の比較不備は使用していない。実測比較artifactはoutput/research_phase3_weather_comparison_95ade40/weather_comparison.jsonおよびweather_comparison_report.mdに保存した。
- 会計上、雨天は晴天に対して総費用が+10,387.354 JPY（+1.448%）、grid importが+496.502 kWh、peak gridが+26.132 kWとなった。PV生成は614.709375 kWhから101.114300 kWhへ-513.595 kWh（-83.551%）、PV→busは-338.286 kWh、BESS→busは-158.216 kWhである。費用差の主因はgrid purchase +9,093.834 JPYとdemand charge +1,045.268 JPYであり、燃料費・使用車両費は同値である。
- これは「同じ固定条件で得た受理済み可行スケジュールの会計・制約条件比較」である。Phase 3はStage 1の車両割当をStage 2で固定しており、しかもStage 1はtime-limit/gap 20.985%であるため、global total-cost optimum、車両割当の一意性、又は天候による最適解の優劣を主張してはならない。
- 比較script実装中に、grid_purchase_costはelectricity_costの追跡用内訳であり、会計総額に別途足すと二重加算になることを検出した。正規合計式へ直し、reportでは会計主加算項と電力フロー由来の補助指標を別表にした。この修正は既存の費用計算を変更せず、監査式・表示の誤解だけを除去した。

### weather operation profile の監査強化

- 自己レビューで、weather_operation_modeをweather provenanceとしてだけ許容する比較では、将来そのmodeに実効SOC/コスト/運用biasが追加された際に交絡を見逃すP1を見つけた。scripts/run_research_phase3_frontend_weather.pyは今後、canonical problemに実際に適用されたweather_operation_profileをinput audit/summaryへ保存し、experiment hashにも含める。profileが空ならrunを停止する。
- 比較scriptは新しいsummaryではprofileのoperation_modeラベル以外をhard equalityで照合する。片方だけ欠損なら拒否し、両方欠損する旧summaryはlegacyとして明示する。今回の95ade40 summaryはこのnew field導入前なのでlegacy表記となるが、当該commitのWeatherOperationProfileをsourceから監査した結果、晴天/雨天の有効値はoperation_mode以外すべてNone又は0で一致した。current sourceで両caseのbuild-onlyを再実行して同じprofile payloadを保存することも確認した。この追補は数理制約・目的係数を変更せず、provenanceと再現性を強化する。
- 同じ自己レビューで、旧summaryが契約電力の料金単価だけを保存し、import upper limitを保存していないことをP1として検出した。runnerはdepot別raw import limit、nonpositive時は有限contractなしという解釈、contract overage penaltyをinput audit/summary/experiment hashへ追加した。current sourceの同一prepared input build-only auditでは、晴天・雨天とも鶴巻のimport limitは1000 kW、overage penaltyは0 JPY/kWhで一致した。旧95ade40 full summaryはこのfield導入前なのでcomparison reportではlegacyとして明示し、将来のsummaryでは片方でも欠損又は値不一致なら拒否する。

### 検証・レビュー

- python -m pytest -q tests/test_research_phase3_weather_comparison.py tests/test_phase3_controlled_validation.py → 34 passed, 4 skipped。新規testは、PV差だけの正常比較、TOU差の拒否、未受理結果の拒否、未分類weather setting差の拒否、有効weather profile knob差の拒否、契約電力上限差の拒否を確認する。
- python -m pytest -q --ignore=test_multiday_phase1.py → 665 passed, 20 skipped。除外したtest_multiday_phase1.pyはlocalhost BFFを必要とする外部結合testであり、本変更の最適化core regressionではない。
- python -m py_compile scripts/compare_research_phase3_weather.py scripts/run_research_phase3_frontend_weather.py tests/test_research_phase3_weather_comparison.py、git diff --check、晴天/雨天summaryに対する実comparison CLIを通した。MIT-style self reviewでは、比較対象の固定条件、legacy provenance、ゼロ除算を含む差分表示、会計totalの内部整合、global-optimum誤主張を確認した。外部claude CLIはこの環境に存在しないため、Claude Codeによる独立レビューは実行できない。

---

## 2026-07-14 16:50 JST — Phase 3 early-SOC relaxation from frontend-weather Stage 2 IIS

### 実測した現象（研究結果には不採用）

- clean commit `e1f4fb3`、Gurobi `13.0.1`、`time_limit_sec=1500`（Stage 1/2に各750秒）で、実フロントエンド経路の晴天入力 `771d115b-75b0-49f7-a7f0-25f259a2cd21` / `2025-08-05` を実行した。フロントエンドの60分・24slot、実在庫35台別SOC、90kW×5 + 50kW×5、PV 614.709375kWh、BESS 600kWh、TOU、需要料金、軽油・CO2価格を保持した。
- Stage 1は750.238秒で264便を覆うcandidateを得たが、Stage 2は0.156秒で`infeasible`となった。`research_run_accepted=false`であり、最終成果物は候補を公開せず0便担当・264便未担当に隔離した。したがって、当該runの0円費用・PV使用量・candidate運行表は研究結果ではない。
- IISは`builder-bev-tsurumaki-001`について、初期SOC 78.114kWh、最小SOC 62.8kWh、slot 0--2の運行中充電禁止、slot 3のSOC下限で構成された。始発単体は既存のstartup precheckを通るが、最初の空きslotより前に連続する便の合計走行量でSOC下限を割る。これは実行成果物の`stage2_infeasible.ilp`と`stage2_iis_constraints.csv`から確認した事実である。

### 修正内容・数理的意味

- `src/optimization/milp/solver_adapter.py` に、Stage 1の`stage1_soc_relax_*`を追加した。BEVごとにslot-start SOCを持たせ、Stage 2と同じ便エネルギーのslot配分と「運行中slotは充電不可」だけをhard constraintにする。
- ただしこれはStage 2の再実装ではない。idle slotでは所在地に関係なく最大充電を許し、charger port、営業所滞在、回送、系統/PV/BESS制約、deadhead消費をすべて緩和する。このためStage 2で可行な解を排除しない**楽観的な必要条件**であり、低SOC車両の早朝連続便のように、それでもSOC下限を守れない割当だけをStage 1で除外する。
- `stage1_time_indexed_soc_relaxation_constraint_count` と `stage1_time_indexed_soc_relaxation_semantics=optimistic_cumulative_home_depot_energy_necessary_condition` をsolver metadataおよび両research runnerのsummaryへ追加した。既存のall-day energy envelope、連続1 duty方針、fallback/postsolve repair禁止は維持する。

### 晴雨比較の入力監査

- 雨天 `b23fd26c-1233-4c73-bb9e-bdb8b1584760` / `2025-08-10` をbuild-onlyで再確認した。車両、trip、初期SOC、充電器、TOU、需要料金、軽油・CO2、BESS・終端SOC、cost flags、objective weights、seed、time limit、fragment policyは晴天と同一である。実効的な差はPV時系列（晴天614.709375kWh、雨天101.1143kWh）である。
- weather labelは晴天`aggressive`、雨天`conservative`だが、現行`WeatherOperationProfile`のそれらの制御値は全て`None`または0であり、`apply_weather_policy_to_problem()`はモデル上PV曲線とmetadataを更新するだけである。このため本比較でこのlabelを「別の運用方針を最適化した」と解釈してはならない。比較成果物にはこの限界を明記する。

### 回帰確認・次の検証

- `GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic python -m pytest -q tests/test_phase3_controlled_validation.py tests/test_optimization_engine_postsolve.py` → `44 passed`。新規Gurobi regressionは、最初のidle slot前にSOCを下回る2便連鎖をStage 1で不可行にし、一方でoff-depot充電を楽観的に許してStage 2の営業所制約を持ち込まないことを確認する。
- MIT-style self reviewでは、correctness（slot-start遷移・terminal slot）、research validity（必要条件の緩和方向）、performance（vehicle×slotの連続変数のみ）、metadata/export、testabilityを確認した。terminal slot後のSOC下限を追加してP1を解消し、既知P0/P1は残していない。外部`claude` CLIはこの環境に存在しないため、Claude Codeによる独立レビューは実行できない。
- 次はclean commitから同じ晴天実フロント入力を1500秒で再実行し、Stage 2まで受理された場合に限り、同じ入力契約で雨天も実行する。不採用runは比較・コスト考察に使用しない。

---

## 2026-07-14 15:29 JST — Phase 3 Stage 1 energy-envelope correction from an actual Stage 2 IIS

### 実測した現象（研究結果には不採用）

- clean commit `24c3952`、Gurobi `13.0.1`（academic license、期限2027-02-27）で、frontendと同じprepared-scope/BFF経路の晴天入力（`2025-08-05`、60分、実在庫35台別SOC、PV/BESS有効）を実行した。
- Stage 1は750.252秒で264便をすべて覆うcandidateを持ったが、固定割当のStage 2は0.169秒で`infeasible`となった。最終成果物は0便担当・264便未担当、`research_run_accepted=false`であり、Stage 1 candidateや0円費用を研究結果として公開していない。
- IISはBEV `89d3f73a-7cd0-421c-8e62-45a073264f6c` の`SOC initial/transition`、slot 1–15の運行・回送中充電禁止、及び21:29便の`departure_soc`で構成された。当該勤務列は始発前に有効な完全充電slotが1つしかなく、その後連続運行のため、終盤の出発SOCを物理的に満たせない。これはIISと候補scheduleから確認した事実である。

### 修正内容・数理的意味

- `src/optimization/milp/solver_adapter.py` にStage 1の`stage1_energy_envelope__<vehicle>` hard constraintを追加した。BEVごとに、便・便間回送・帰庫回送・終端SOC要求の合計を、初期SOCとStage 2が認める可能な充電窓の**楽観的上限**以下に制限する。始発回送は既存の`StartupEnergyPrecheck`で別途除外する。energy envelope自身では、legacyの複数fragment callerを過剰に除外しないため始発回送を控除しない。
- 充電窓は始発前、確認済み営業所滞在、営業所発着便の窓、帰庫後/翌日境界の窓を数える。一方で充電器port・系統電力競合・battery headroom・窓の重複、及び上記の始発回送は緩和して上限側に数えるため、この制約はStage 2の代替ではなく「それでも不足する勤務列だけを除く必要条件」である。Stage 2のSOC下限、便数、車両数、充電器能力、消費電力量は緩和していない。
- Stage 2 failure diagnosticsも、`allowed_charge_slots`から運行・回送と重なるslotを除外して出発前最大SOCを時系列で計算するよう修正した。従来の診断は、回送で一部重なるslotを始発前充電として数え、実際には不可行な候補を`shortage=0`と過大表示し得た。
- 追加metadata: `stage1_energy_envelope_constraint_count`、`stage1_energy_envelope_semantics=optimistic_vehicle_local_necessary_condition`。IIS、candidate-only隔離、fallback禁止、postsolve repair禁止の契約は維持した。
- 追加監査で、両シナリオのフロント設定が`max_start_fragments_per_vehicle=max_end_fragments_per_vehicle=100`、same-day depot cycle上限3であることを確認した。Stage 2は断片間の暗黙帰庫・再出庫のSOCをまだモデル化していないため、この設定のままPhase 3を研究結果として受理してはいけない。`research_phase3_policy.py`を追加し、研究用runnerだけが永続ストアを変更せずに「車両ごとに連続1 duty」（start/end/daily=1、same-day cycle禁止）を明示的に適用し、元設定・上書き理由・実効値を成果物に残す。さらにengineのresearch acceptance gateは複数断片のPhase 3結果を不受理にする。
- energy envelopeはlegacyの複数fragment callerでも必要条件であり続けるよう、start arcごとのstartup deadhead控除を削除した。Stage 2がstartup deadheadを時系列上の最初のfragmentだけに計上するためである。これはStage 1を楽観側に緩めるだけで、SOCの最終判定をStage 2から外さない。

### 回帰確認と次の検証

- `GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic python -m pytest -q tests/test_phase3_controlled_validation.py tests/test_milp_fragment_pairwise_reset_cut.py tests/test_milp_engine_lightweight_stats.py` → `33 passed`。新規Gurobi regressionは、初期50kWh・終端20kWh・充電機会なしで合計80kWhを走るBEV勤務列をStage 1のhard constraintが不可行にすることを確認する。
- 本追補では、focused regression（Phase 3・engine postsolve・fragment cut・MILP lightweight）`48 passed`、全回帰（`test_multiday_phase1.py`はlocalhost BFF依存のため除外）`668 passed, 8 skipped`を確認した。晴天の実フロント入力をbuild-onlyで通し、実在庫SOC hash `4e135b…`、90kW×5+50kW×5 charger、PV 614.709375kWh、BESS 600kWh、TOU/需要料金設定を保持したうえで、research artifactにのみfragment policyの元値・理由・実効値が記録されることを確認した。
- 次はdirtyでないcommitから、指示済みの`CONTROLLED_MODEL_VALIDATION_CASE`（2025-08-10、264便、BEV35/ICE25、15分、全BEV SOC80%、PV/BESS/weather off、grid-only）を1500秒で再実行する。この統制runが可行であることを確認した後にのみ、実在庫SOC・PV/BESSありの晴天/雨天比較へ進む。

---

## 2026-07-14 01:34 JST — Phase 3 Stage 1/2 energy and service-day consistency hardening

### 対象

Phase 3 Stage 2可行性復旧の継続。対象は鶴巻営業所、渋21/22/23、264便、service date `2025-08-10`、BEV35/ICE25、grid-only、15分刻み、全BEV初期SOC 80%の `CONTROLLED_MODEL_VALIDATION_CASE` である。PV/BESS/晴雨比較には進んでいない。

### 修正前の現象・確認した原因

- Stage 1の始発可否は位置・時間だけを見ており、初期SOC、始発前に完了できる充電slot、始発回送エネルギー、当該便エネルギー、SOC下限から決まる明白な必要条件を見ていなかった。そのため、Stage 2で必ずSOC不足になる始発組合せを候補にできた。
- Stage 2は始発回送と便間回送のエネルギーをSOCへ載せる一方、回送中slotを車両占有として扱っていなかった。また、便間に確認できる営業所滞在全体ではなく、便前後の固定長窓に依存していた。
- 05:00開始のservice-dayにおける04時台便を、slot indexは翌日側へ写す一方、運行重複・走行エネルギー分配はwall-clockの04時台のまま比較していた。この不一致により、04時台便の走行エネルギーが96-slot SOC式から欠落し得た。
- 回送エネルギーを次便の出発slotで減算するslot-start表現に対し、2便目以降の出発時SOC必要量が当該回送分を含まなかった。これは出発直前の実SOC不足を許し得る。
- 不可行診断の最大充電量がhorizon外slotを数え、候補の充電余力を過大表示し得た。stage metadata、experiment hash、非有限objectiveのnull契約も不足していた。
- 上記は現行コードパスから確認したモデル構築上の欠陥である。Gurobi licenseが失効しているため、今回IISを取得した、または旧0.05秒 infeasibleの唯一原因を確定した、とは主張しない。

### 変更内容・数理的効果

- `src/optimization/milp/solver_adapter.py`
  - `StartupEnergyPrecheck` を追加し、Stage 1のstart arcについて `initial SOC + 完全始発前slotでの楽観最大充電 >= 始発回送 + 便エネルギー + SOC下限` を満たさない組合せを0に固定する。これは十分条件ではなく、Stage 2で必ず不可行な組合せだけを除く必要条件である。
  - 始発回送・便間回送の時間slotを充電禁止にし、回送エネルギーをSOC loadと出発時必要SOCの双方で同じslot-start意味に整合させた。走行エネルギーそのものを減らす緩和、SOC clamp、postsolve修正は追加していない。
  - `arrival + turnaround + deadhead <= next departure` は変更せず、接続済み便間でのみ営業所滞在区間を復元した。別地点間のdeadhead=0を営業所滞在の根拠にはしない。
  - Stage 1 candidateを車両内時系列で診断保存し、始発/便間/帰庫回送、horizon内充電slot、出発時不足を分離した。Stage 1 status/objective/bound/gap/runtime/candidate hashと、Stage 2制約prefix別件数を成果物へ追加した。
  - SOC式を `_vehicle_soc_transition_kwh` に一本化し、`SOC[k+1] = SOC[k] + 0.95 * charge[kW] * 0.25[h] - drive[kWh]` を手計算テスト可能にした。
- `src/optimization/common/soc_helpers.py`: service-day開始前の時刻を翌日絶対分へ正規化してから、半開区間の運行重複と走行エネルギー分配を行う。04:20–04:50便の全slot配分和が1になる。
- `scripts/run_research_phase3_minimal.py`: trip/fleet/route/date/96-slot/research phase/PV/BESS/weather/postsolveのhard-check、入力・車両・充電器・SOC方針・時間刻み・資産・天候・solver control・git SHAを含むexperiment hash、stage別ratio/percent/null metadataを追加した。非有限objective/costは0へ変換せずnullにする。git dirty runは研究受入不可とする。
- `tests/test_phase3_controlled_validation.py`: uniform/actual inventory SOC、始発必要条件、回送、service-day境界、営業所滞在、運行中充電禁止、SOC手計算、gap変換、非有限objective、experiment hash差分の回帰テストを追加した。

### 初期SOC方針・時間刻み

- `initial_soc_policy=uniform_scenario_value`, `initial_soc_percent=80`。全35 BEVでmodel inputは `251.2 kWh / 314.0 kWh = 80%`、minimumは `31.4 kWh` である。
- `time_step_min=15`、1日96slot、SOC変数は `slot_start`。terminal policyは単日物理検証用の `SOC >= minimum SOC` であり、翌日同一運用の継続可能性は保証しない。

### 追加テスト・結果

- `python -m pytest tests/test_phase3_controlled_validation.py -q` → `23 passed`。
- Phase 3/SOC/postsolve/solution validity focused suite → `94 passed`。
- 全体 `python -m pytest -q` → `641 passed, 6 skipped, 1 failed`。失敗は既知の `test_multiday_phase1.py::test_multiday_scenario` が未起動の `localhost:8000` BFFへ接続できない外部結合要因であり、最適化コアのassertion failureではない。
- build-only → `264 trips / BEV35 / ICE25 / 2025-08-10 / 96 slots / PV off / BESS off / weather off / uniform SOC 80%` をCanonical Problemと入力監査JSONで確認した。

### 最適化結果・研究契約

- 環境: branch `fix/phase3-stage2-feasibility-20260712`、開始HEAD `435a223a4e3735980764eeeb09835173e3966f89`、Python `3.14.0`、Gurobi `13.0.1`。Gurobi licenseは失効している。
- 通常runは `ENVIRONMENT_BLOCKED_GUROBI_LICENSE`, `solver_invoked=false` で停止した。Stage 1/2 status=`not_run_gurobi_unavailable`、incumbent=false、objective/bound/gap/runtime=null、solver/accounting/validated cost=nullである。
- `research_run_accepted=false`, `research_feasibility_eligible=false`, `research_cost_kpi_eligible=false`。Stage 1/2の可行性、担当便数、使用BEV/ICE、最低SOC、総充電量、IIS原因は未判定である。

### 自己レビューと未解決事項

- MIT-style reviewでP1として、04時台energy欠落、2便目以降の回送前SOC不足、非有限objectiveのJSON誤表現を上げ、修正と回帰テストを追加した。P0/P1の既知残件はない。
- 有効なGurobi licenseで同一commit・clean worktreeから1500秒runを行う必要がある。Stage 2が不可行なら、生成されるIIS、車両別energy shortage、departure SOC不足の実測値に基づいてのみ、path energy envelopeまたはlogic-based feasibility cutを追加する。
- ユーザー所有の `README.md` 変更は本作業で変更・stageしていない。これがdirtyのままでは厳密な研究受入gateはfalseになるため、solver実行時は別途cleanなworktreeが必要である。

---

## 2026-07-13 00:xx JST — Phase 3 Stage 2 feasibility recovery (environment-blocked)

### 対象

Phase 3 Stage 2 可行性復旧。対象は鶴巻、渋21/22/23、264便、2025-08-10、BEV35/ICE25である。晴雨/PV/BESS比較には進んでいない。

### 実行環境・基線

- branch: `fix/phase3-stage2-feasibility-20260712`（`core_new` の祖先 `e39f9b1` と既存の厳密化コミットを含む）。開始HEAD: `70ca8ebdfece0b3b559d53dc33e7d773c68d61f9`。既存のユーザー変更 `README.md` は未変更のまま dirty である。
- Python `3.14.0`、Gurobi `13.0.1`。WLS license `2785206` が expired のため、`ENVIRONMENT_BLOCKED_GUROBI_LICENSE` と判定した。この環境でsolverの可行/不可行、IIS、264便の成立可否は主張しない。
- 修正前の `scripts/run_research_phase3_minimal.py --time-step-min 15` 相当の入力構築は、`normalize_timestep_min` が15分を拒否して停止した。したがって旧Stage 2の0.05秒 infeasible を今回の統制条件で再現・比較してはいない。
- 基線 `pytest -q`: `621 passed, 6 skipped, 1 failed`。失敗は `test_multiday_phase1.py::test_multiday_scenario` が `localhost:8000` の外部BFFへ接続できないためであり、最適化コアの失敗ではない。

### 原因（確認済みのモデル構築上の欠陥）

- 15分刻みは共通time-axis/data schemaが30/60分しか許可せず、Phase 3モデルを構築できなかった。
- Stage 2の始発前充電窓は直前2スロットに固定されていた。15分刻みの05:51発では、車両が営業所に存在する05:00–05:45の完全な3スロットを使えない。
- `allow_overnight_depot_moves=forbid` が夜間の車両移動ではなく、営業所に停車している車両の充電まで禁止していた。
- Stage 2の最終slotはSOC変数をslot-startとして扱う一方、同slotの充電・走行を終端SOC制約に反映していなかった。また、最終slot出発便、horizon外へ跨る便の残余消費、horizon外帰庫deadheadを見落とし得た。今回、終端式・全出発SOC制約・horizon外負荷を明示した。これらはIIS推測ではなく、実装経路から直接確認した事実である。
- 複日ケースでは、Stage 1が日末の帰庫を常に強制しないのに全BEVへ夜間デポ充電slotを付与していた。Stage 1 candidateの車両・日別最終便について、帰庫deadheadが存在し、帰庫完了した後の完全slotだけを夜間充電可能とした。出発SOC不足診断にも便間deadheadを加えた。
- 05:00境界を跨ぐ04:50到着便に帰庫時間を足すと、wall-clock値が05:00を超えるため、旧式は同日slotとして誤認していた。trip到着・最終便比較・帰庫後slotをservice-day絶対分（horizon start基準）へ正規化し、horizon外の帰庫消費を終端式へ入れるよう修正した。初期SOCがreserve未満の場合もreserveへ自動で引き上げず、SOC下限制約により不可行として検出する。
- Stage 1 dutyの列挙はraw時刻順のため、日跨ぎfragmentの「最初のduty」を初期在庫位置とみなしてはならない。Stage 1 candidateのvehicle pathからservice-day時刻で最初のtripを事前に一意に選び、そのtripだけへhorizon開始時の初期デポ充電窓を与える。

### 変更内容

- `src/optimization/common/time_axis.py`、`src/data_schema.py`: 15/30/60分を正式に許可した。
- `scripts/run_research_phase3_minimal.py`: `--time-step-min 15`、initial SOC policy enum、uniform 80%、PV/BESS/weather off、terminal `SOC >= minimum`、96 slot hard-check、`CONTROLLED_MODEL_VALIDATION_CASE`、SOC input hash、build-only、license-blocked manifestを追加した。inherited terminal floor/target/toleranceはすべて解除し、車両別の実効terminal minimumも入力成果物へ保存する。uniform 80%は実在庫SOC結果と混同しない。
- `src/optimization/common/initial_soc_policy.py`: `actual_vehicle_inventory` / `uniform_scenario_value` / `per_vehicle_scenario_override` と、solverへ渡る車両別SOC hashを追加した。
- `src/optimization/milp/solver_adapter.py`: 始発前の全完全slot、夜間移動と充電の分離、帰庫確認後の夜間slot、slot-start SOC遷移と最終slot/horizon外 energy balance、名前付きSOC/出発/充電器/系統制約、Stage 2失敗時のcandidate-only CSV・IIS出力を追加した。IISは有効なGurobi環境でのみ生成される。

### 初期SOC方針・時間刻み

- controlled case: `uniform_scenario_value`, 80%、`15 min`、96 slots、grid-only、terminal `SOC >= minimum SOC`。これは翌日連続運用を保証しない単日物理可行性検証である。
- `output/research_phase3_grid_only_15min_soc80/controlled_model_validation_input.json` と `summary.json` に input hash・車両別SOC・設定を保存した。通常runはライセンス失効を検出し `solver_invoked=false` で停止する。

### テスト結果

- `python -m pytest tests/test_phase3_controlled_validation.py tests/test_time_axis_timestep.py tests/test_soc_midtrip_feasibility.py tests/test_feasibility_soc_consistency.py tests/test_milp_engine_lightweight_stats.py tests/test_solution_validity.py tests/test_feasibility_metrics.py -q` → `42 passed`。
- `python -m py_compile src/optimization/milp/solver_adapter.py src/optimization/common/initial_soc_policy.py scripts/run_research_phase3_minimal.py src/optimization/common/time_axis.py src/data_schema.py` → pass。
- `python scripts/run_research_phase3_minimal.py --build-only --time-step-min 15 --initial-soc-policy uniform_scenario_value --initial-soc-percent 80 --output-dir output/research_phase3_grid_only_15min_soc80` → target input構築・96 slots・vehicle別SOC/terminal lower bound保存を確認。
- 独立コードレビュー: 15分slot、terminal SOC、service-day境界の帰庫、複数duty初期充電窓、initial SOCのsilent clampをP1として指摘・修正後、P0/P1なしと再確認された。実Gurobi solve/IISのみライセンス失効で未検証。
- `python scripts/run_research_phase3_minimal.py --time-limit-sec 1500 --time-step-min 15 --initial-soc-policy uniform_scenario_value --initial-soc-percent 80 --output-dir output/research_phase3_grid_only_15min_soc80` → `ENVIRONMENT_BLOCKED_GUROBI_LICENSE`。solver未実行であり、Stage 1/Stage 2 status、担当便、IIS、費用は未判定/nullである。

### 研究契約・未解決事項

- research acceptance: 未判定（solver未実行）。`research_run_accepted`、`research_feasibility_eligible`、`research_cost_kpi_eligible` をtrueとして報告していない。
- 有効なGurobiライセンスで同一コマンドを実行し、Stage 2が失敗した場合に `diagnostics/stage2_infeasible.ilp`、IIS制約CSV、車両別不足量、出発前SOC不足を取得する。その実測結果を用いてのみ、Stage 1 energy envelope / feasibility cut の要否と原因車両・便・時刻を確定する。

---

## 2026-07-12 Weather-case comparability alignment (2025-08-05 vs 2025-08-10)

- 問題: 晴天 `771d115b-75b0-49f7-a7f0-25f259a2cd21`（2025-08-05）と雨天 `b23fd26c-1233-4c73-bb9e-bdb8b1584760`（2025-08-10）は、いずれも Phase 3 / time limit 1500 s で実行されたが、前者は Stage 1 が 750.315 s の time-limit、後者は 40.074 s で optimal となった。実行上の 1500 s は二段階モデルの各 Stage に最大 750 s を割り当てる上限であり、必ず 1500 s 実行する設定ではない。
- 原因監査: 雨天ケースだけ `simulation_config.cost_component_flags.vehicle_usage_cost=false` だった。一方、晴天ケースは同項が true で、使用車両 20,000 JPY/vehicle-day を Stage 1 目的へ入れていた。加えて雨天ケースの BESS終端目標は 0 kWh / 0 %、晴天ケースは 300 kWh / 50 % だった。これらは天候以外の交絡条件である。
- 対応: `bff.services.weather_comparison` を追加し、基準ケースの運用・コスト・SOC・solver control を target へ同期しつつ、target の `service_date`、PV profile/slot series、forecast path・station・reference date・issue date を保存する。比較前に timestep、開始/終了時刻、horizon、planning days、PV kWh/容量係数系列の1日slot数を hard-check し、不一致なら resample せずエラーにする。`scripts/align_weather_comparison_scenarios.py` は dry-run 監査と `--apply` の両方を提供する。
- 適用: 雨天シナリオへ `--apply` を実行した。`vehicle_usage_cost=true`、BESS終端 target=300 kWh / 0.5 / 50 %（simulation config / overlay 両方）を確認した。雨天の 2025-08-10、`tsurumaki_2025-08-10_60min`、雨天PV系列、forecast `44132_2025-08-10` は保持した。監査結果は `output/weather_comparison_alignment_audit.json` に保存する。
- 研究妥当性: `replace_scenario_experiment_configuration()` は simulation config と overlay を原子的に置換し、target の trips / duties / optimization result を無効化して status を `draft` に戻す。したがって旧設定で作られた active result を新設定の雨天結果として解釈できない。履歴 run `output/2026-07-12/run_20260712_2040` は変更せず、比較対象から除外する。
- 限界: 両旧 run は Stage 2 charging dispatch が infeasible であり、有効な晴天/雨天比較結果ではない。また weather proxy audit は `missing_capacity_factor_by_slot` により forecast curve 未適用だった。新しい比較では、同一 prepared scope を再構築し、Stage 2 の infeasibility を別途診断して受入条件を満たすまで、PV/コスト差を研究結果として主張しない。
- 検証: `python -m pytest tests/test_weather_comparison_alignment.py tests/test_scenario_store_atomic_mutations.py tests/optimization/test_weather_policy_problem_integration.py tests/test_problem_builder_depot_energy_asset_controls.py -q` → `44 passed`。`python -m py_compile bff/services/weather_comparison.py bff/store/scenario_store.py scripts/align_weather_comparison_scenarios.py`、`python scripts/align_weather_comparison_scenarios.py` を実行し、control mismatch が 0 件であることを確認する。独立レビューで指摘された time-axis/PV-slot とweather provenanceのP1/P2をこのhard-checkと回帰テストで解消した。

---

## 2026-07-11 Strict Phase 3 Recovery: candidate isolation, chronology, and provenance

- 既存 `output/2026-07-11/run_20260711_2046` / `run_20260711_2107` を再監査した。solver status は `infeasible` なのに summary/assignment は 264便 served として保存され、Stage 1 assignment candidate が Stage 2 charging/SOC failure 後も最終出力へ流れていた。これは「MILP が解いた問題」と「公開した運行表」が一致しない P1 の研究妥当性欠陥である。
- 対応: Phase 3 の Stage 2 に feasible incumbent が無い場合、research run は Stage 1 candidate を `assignment_candidate_*` metadata / `assignment_candidate.json` に診断用として隔離し、最終 plan の duties・charging・SOC・served IDs は空、全便は unserved とする。`supports_two_stage_milp` は Stage 2 成功時だけ true、Stage 1/Stage 2 status・objective・bound・gap・incumbent を別々に保存する。fallback / postsolve repair で infeasible を feasible に変えない。
- 対応: `requested_phase` / `resolved_phase` / `executed_phase` を BFF・engine・solver settings・run manifest へ伝播し、research acceptance は3値の完全一致を要求する。Phase 3 の `supports_integrated_exact_milp` は false とし、二段階法を統合MILPとして表示しない。
- 追加監査: raw の `requested_phase_token`（例: `mode_milp_only`）を canonical phase と分離して保存し、gate は `normalize(raw) == requested == resolved == adapter-executed` を検証する。Stage 2 が失敗した Phase 3 は research/non-research を問わず最終 plan を空にし、Stage 1 は診断 candidate としてのみ保持する。
- 対応: `AssignmentPlan.duties_by_vehicle()` と validator の共通 chronological key を導入した。trip ID の辞書順ではなく departure→arrival→ID で fragment を並べ、canonical `trip_assignment.csv` に車両内 sequence を付ける。これは時刻順を正規化するだけであり、timetable_rows や solver の duty legs を書き換えない。重複・接続不可は独立 validator が不合格にする。
- 追加監査: horizon start（例 `05:00`）を基準に 23:30→00:10→00:30 を同一 service-day の絶対分へ写像し、重複判定・fragment 判定・出力 sequence が日跨ぎで逆転しないようにした。元の HH:MM は変更しない。
- 対応: service date は `simulation_config.service_date` を最優先し、research canonical builder は欠損時に実行日を代入せずエラーにする。scenario meta の `operatorId`（本対象では `tokyu`）を dispatch Trip へ明示伝播し、空/`UNKNOWN_OPERATOR`、複数 operator は research acceptance を不合格にする。`service_id` を operator の代用にはしない。
- 対応: `solver_objective_value`、`accounting_total_cost_jpy`、`validated_operating_cost_jpy` を分離した。solver status または独立検証が infeasible の場合、validated operating cost は `null` とする。incumbent が無い場合、MIP gap は ratio/percent とも `null`（0ではない）。
- 追加監査: Phase 2 assignment-only は充電/SOC未検証のため `validated_operating_cost_jpy` を出さない。research では受入 gate と full operational validation の両方を満たした場合だけ値を設定する。invalid/missing research service date は canonical export 時に実行日へフォールバックせずエラーにする。
- 再現スクリプト: `scripts/run_research_phase3_minimal.py` は prepared scope `b23fd26c-1233-4c73-bb9e-bdb8b1584760 / prepared-789ce8197d83c758-0b337aa1f091e729` をメモリ上で materialize し、鶴巻・渋21/22/23・264便・BEV35/ICE25・2025-08-10・grid-only（PV/BESS/weather policy off）を hard-check してから Phase 3 を実行する。受入 gate を通らない場合、最終 schedule は書き出さず candidate だけを診断保存する。
- 実行検証: 入力構築は `264 trips / BEV35 + ICE25 / available BEV35 + ICE25 / service_date=2025-08-10 / operator=tokyu / PV=off / BESS=off` を確認した。clean commit `ee4260e3ceda1b0f0b3d8c41ea6767847f826990` で `--time-limit-sec 1500` の target run を試行したが、ローカル Gurobi license が無いため約3秒で `NO_VALID_INCUMBENT` となった。`trip_count_served=0`、`trip_count_unserved=264`、`validated_operating_cost_jpy=null`、MIP gap null、final schedule 未出力、`git_dirty=false` を確認した。これは solver 成功結果ではなく、厳密 gate が誤って成功扱いしないことの検証である。
- 検証: focused suite `39 passed`、builder/dispatch/accounting/weather suite `47 passed`、全 pytest は `613 passed, 6 skipped` と integration test 1件（localhost:8000 未起動）を除き pass。Gurobi license が利用可能な環境で `python scripts/run_research_phase3_minimal.py --time-limit-sec 1500 --output-dir output/research_phase3_minimal` を実行し、`research_run_accepted=true` かつ全 acceptance checks true になるまで、264便の研究成立結果は主張しない。

---

## 2026-07-11 Research-Run Integrity Gate and Assignment Diagnostics

- 問題: solver が出した candidate と、postsolve repair / baseline fallback 後に公開する運行・充電・SOC が異なり得た。このため、`MILP が解いた可行集合` と `研究結果として集計した可行集合` が一致せず、最適性・成立条件のどちらも主張できない危険があった。
- 対応: 公開 BFF と `OptimizationEngine` の双方に `research_run` を追加した。研究 run は coverage を strict に強制し、postsolve repair、opportunistic top-up、baseline substitution、partial-service relaxation を使わない。diagnostic/debug 指定は実行記録には残るが研究用受入を必ず不合格にする。Gurobi 不可、実行可能 incumbent なし、時間切れで有効解なし、又は最終検証不合格は、それぞれ `NO_VALID_INCUMBENT`、`INFEASIBLE`、`TIME_LIMIT_WITHOUT_VALID_SOLUTION` として返し、KPI を研究結果に用いない。
- 受入条件: 共通で `fallback なし`、`postsolve による解変更なし`、`全便担当`、`FeasibilityChecker が可行`、debug/diagnostic でないことを確認する。Phase 1 は充電/SOC MILP、Phase 2 は assignment MILP、Phase 3 は二段階 MILP、Phase 4 は統合 MILP と exact source provenance を追加で要求し、成立条件実験として `research_run_accepted=true` にできる。総費用 KPI の解放候補は明示的に Phase 4 だけとし、会計総コストと solver objective の同値性はまだ監査未完了のため、現時点ではどの phase も `research_cost_kpi_eligible=true`（従来名 `research_kpi_eligible`）にならない。
- 目的関数: 研究 run では非会計的な `return_leg_bonus` をゼロに固定する。weather policy の運用バイアスに加え、統合 MILP には既定で充電優先・早充電・セッション開始等の会計外内部ペナルティがある。このため、会計上の再計算値と solver objective が同じに見えても `objective_is_actual_cost=false` とし、総コスト KPI を不受理にする。Phase 3 の二段階法は成立条件比較の有効な実験だが、大域的総コスト最小化とは主張しない。`research_run=false` の通常 thesis run も、研究 KPI としては出力しない。将来の経済性実験は、全会計項の objective 実装、内部ペナルティの削除又は会計化、時刻単位/需要料金の一致を検証してから解放する。
- 診断: `ConnectionGraphBuilder`、MILP arc enumeration、`DutyValidator` は通常便接続について同じ `FeasibilityEngine.can_connect` を使用している。最終 validator は `assignment_validation_diagnostics.json` に、未担当便、車両、前後便、deadhead/turnaround/slack、rejection reason を出力する。車両の複数 fragment 間については、同じ `fragment_transition_diagnostic` の depot/direct-connectivity 制約を追加で検証する。
- 出力区分: Phase 2 の受理済み結果は `research_assignment_eligible=true` として出力し、`research_feasibility_eligible` / `research_kpi_eligible` とは区別する。これにより、車両割当が validator を通った事実を使いつつ、充電/SOCまで可行であるか、又は経済性が成立するかを誤って主張しない。
- 限界: 現行の統合 Phase 4 は 30/60 分スロットを主に前提とし、一部 SOC はイベント終端表現である。15 分または event-based SOC を導入し、validator と同一の連続時間エネルギー遷移を実装・検証するまでは、Phase 4 を主研究の確証結果として使わない。天候比較は、天候/PV profile 以外（fleet、ダイヤ、充電器、契約電力、価格、初期SOC、目的関数、seed、time limit）を同一の run manifest で固定する。
- 検証: research fallback 禁止、二段階 objective claim gate、return-leg bonus 無効化、接続 rejection diagnostics の回帰テストを追加する。

---

## 2026-07-11 Phase Contract and Objective-Claim Closure

- 問題: `phase3_two_stage` の「postsolve repair 禁止」は BFF の通常最適化経路でしか設定されず、`OptimizationEngine` 直呼びと rolling re-optimization では既定 `allow_postsolve_repair=True` に戻り得た。この状態では、MILP が決めた運行・充電・SOC を最終化で変更し、研究用の Phase 3 結果を後処理解として出力する危険があった。
- 対応: `OptimizationEngine` が明示 phase token を正規化し、Phase 1/2/3/4/diagnostic の postsolve repair を一律禁止する phase contract を適用する。Phase 3 は同時に thesis two-stage として固定し、diagnostic だけを debug semantics にする。rolling re-optimization も同じ solver-mode→phase/config mapping を渡す。
- 問題: strict Phase 4 integrated MILP は `unserved` バイナリを生成してから `== 0` に固定していた。数理的には coverage を守るが、研究契約の「strict は未担当 decision variable を持たない」と一致しないうえ、不要な変数を増やしていた。
- 対応: strict run は直接 `sum(assignments) == 1` を追加し、`unserved` は penalized/debug の診断 run に限って生成する。
- 目的関数の表現: Phase 3 は Stage 1 の車両運用目的と Stage 2 の充電・PV・BESS目的を順に解く二段階法であり、全会計費目を単一の大域目的で最小化するモデルではない。したがって `solver_objective_matches_accounting_total=false` と stage別の raw objective を出力し、会計上 `objective_value == total_cost` でも `objective_is_actual_cost=true` / 「総コスト最適」とは表示・主張しない。総コストは比較用 KPI として扱う。
- 検証: focused phase/coverage/postsolve/validity suite を実行し、追加した direct Phase 3 no-repair と二段階 objective-claim guard の回帰テストを含める。

---

## 2026-07-09 Phase 1/2/Diagnostic Public Contract

- Phase 1/2/3/4/diagnostic tokens were re-exposed through the BFF public mode API after adding minimal safety contracts. Aliases `phase1`, `phase2`, `phase3`, `phase4`, and `diagnostic_mode` normalize to their canonical phase tokens.
- Phase 1 now rejects fixed assignments that only contain `served_trip_ids` without concrete `AssignmentPlan.duties`. This prevents charging-only Stage 2 from treating an empty vehicle path as a valid “no charging required” result.
- Phase 2 is explicitly tagged as `assignment_only_result`: it may be useful for assignment research, but charging dispatch and SOC feasibility are not evaluated, so full research KPI eligibility is false.
- diagnostic now routes to the existing integrated debug MILP path with unserved/SOC/contract softening hooks enabled where available. The exported `binding_constraint_report` is based on diagnostic slacks plus postsolve validation metrics and is not an IIS proof.
- Phase/result metadata is propagated from `AssignmentPlan.metadata` into `solver_metadata`, so BFF result classification uses the actual phase contract instead of losing it during finalization.

---

## 2026-07-07 Thesis Phase Routing Guardrail Correction

- 研究方針として、最適化を「最適スケジュール生成器」ではなく、EVバス運用成立条件を調べる実験装置として整理する方針を確認した。Phase 1=固定割当で充電のみ、Phase 2=車両割当のみ、Phase 3=2段階MILP、Phase 4=統合MILP、diagnostic=制約ボトルネック診断という構成を canonical `src/optimization/` 側に寄せる設計にした。
- 直近の試作で `phase1_charging_only` / `phase2_assignment_only` / `diagnostic` を公開 `supported_modes` に出してしまったが、実装が未完成で既存 `normalize_solver_mode()` 契約と `OptimizationConfig()` 既定経路を壊したため、公開面からは取り下げた。
- `normalize_solver_mode()` は既存の `thesis_mode`, `debug_mode`, `mode_milp_only`, `mode_alns_only`, `mode_ga_only`, `mode_abc_only`, `mode_hybrid` をそのまま返す契約へ戻した。明示 phase token は内部実験フックとして残し、BFF capabilities ではまだ supported として表示しない。
- `OptimizationConfig.phase` は空文字を既定値に変更し、明示 phase が指定されない通常 `OptimizationConfig()` では既存 integrated MILP fallback 経路を保つようにした。これにより Gurobi 不可時の `gurobi_unavailable_strict_infeasible` / `gurobi_unavailable_baseline` の既存契約を回復した。
- `debug_mode` は未完成の `diagnostic` phase へ自動変換しない方針に戻した。公開済み debug mode は従来どおり integrated MILP の `unserved` 診断用途として扱い、研究KPI不可とする。
- Phase 1/2/diagnostic の本格実装は未完了。特に Phase 1 は `fixed_assignment` に `duties` が無い場合に Stage 2 の `vehicle_paths()` が空になり得るため、研究利用前に `AssignmentPlan.duties` 生成または canonical fixed-assignment contract を明確化する必要がある。diagnostic は SOC/契約電力/充電器 slack の読出しと binding constraint report が未実装。
- 未完成 phase token (`phase1`, `phase1_charging_only`, `phase2`, `phase2_assignment_only`, `phase3`, `phase3_two_stage`, `phase4`, `phase4_integrated`, `diagnostic`, `diagnostic_mode`) は BFF の公開 `mode` API では `ValueError` とし、内部実験では `OptimizationConfig.phase` を直接指定する方針にした。これにより「capabilities には出していないが直接 mode 指定なら実行できる」状態を防ぐ。
- 検証: `python -m py_compile src/optimization/common/problem.py src/optimization/milp/solver_adapter.py bff/services/optimization_run/execute.py bff/routers/optimization.py` → pass。
- 検証: `pytest tests/test_milp_strict_coverage.py tests/test_solver_path_routing.py tests/test_milp_engine_lightweight_stats.py -q` → `13 passed`。
- 検証: `pytest tests/test_solver_path_routing.py tests/test_solver_identity_metadata.py tests/test_solution_validity.py tests/test_solver_maturity_gating.py -q` → `18 passed`。
- 検証: `pytest tests` → `592 passed, 6 skipped`。skip はローカル Gurobi runtime/license が利用不可なための Gurobi 必須テスト。

---

## 2026-05-12 BESS終端SOC・PV会計保存則・CO2内訳の契約強化

- 問題として、営業所BESS設定は `simulation_config.depot_energy_assets` 寄りで、`scenario_overlay.depot_energy_assets` が主経路として十分に強くなかった。BFF保存時に camelCase / snake_case の両方を正規化し、SOC `%` 入力は容量 [kWh] へ変換して、後方互換の `simulation_config` と優先経路の `scenario_overlay` の両方へ保存する契約にした。
- 問題として、postsolve / derived source split は BESS 終端 SOC 下限を破る可能性があった。`src/optimization/engine.py` で終端不足時に後方スロットの `bess_to_bus` を `grid_to_bus` へ戻す repair を追加し、`bess_terminal_soc_violation_kwh` と `bess_terminal_soc_repair_shifted_to_grid_kwh` を metadata に残す。
- 問題として、レポート側の `pv_curtail_kwh` は plan 値をそのまま読むため、`pv_to_bess` と curtail の二重・混同が起きうる。`pv_curtail_kwh = max(0, pv_generation_kwh - pv_to_bus_kwh - pv_to_bess_kwh)` に再整合し、`pv_balance_residual_kwh` と `pv_utilization_rate` を出力する。
- CO2は `ice_bus_co2_kg`, `grid_electricity_co2_kg`, `pv_operational_co2_kg=0`, `bess_storage_operational_co2_kg=0` に分離した。ICE由来は軽油消費量 x `ice_co2_kg_per_l`、Grid由来は実際の Grid import x slot別 CO2係数であり、BESSを単独排出源にはしない。
- `src/preprocess/emission_factor_loader.py` を追加し、国交省燃費・CO2候補は `data/vehicle_catalog.json` を優先し、次に `data/engine_bus/output/engine_bus_simulation_library.json` を参照する。既存の手入力値や scenario overlay の値は引き続き上書き優先。
- これは出力会計と postsolve repair の数学的意味を変えるため、旧 run の PV curtail / BESS discharge / CO2 KPI とは比較条件が一致しない可能性がある。

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

### 2026-04-30 Solcast Typical PV Proxy Forecast v1

- 問題: `solcast_pv_proxy_v1` は `data/derived/pv_profiles/*_YYYY-MM-DD_60min.json` の実日PV形状を使うため、通常の「当日朝の予報」ではなく検証用/Oracle寄りである。晴れ・曇り・雨を大まかに仮定して運用戦略を比較するには、過去Solcast profileから代表的な24h capacity factor曲線を作り、運行日の実PV形状を見ない入口が必要だった。
- 対応:
  - `src/preprocess/weather/solcast_typical/` を追加し、loader / classify / aggregate / forecast に分割した。分類指標は `daily_cf_hours = sum(capacity_factor_by_slot) * slot_hours` とし、`nonzero_slots < 3` または `daily_cf_hours <= 0.1` の日は代表曲線から除外する。
  - 有効日が15日以上なら33%/67%分位点で rainy/cloudy/sunny を分類し、不足時は固定閾値（rainy `< 4.0`, sunny `>= 5.5`, それ以外 cloudy）へフォールバックする。代表曲線JSONには平均24h capacity factor、標準偏差、source dates、excluded dates、thresholdを残す。
  - `WeatherProxyForecast` に `solcast_typical_pv_proxy_v1` を追加した。後方互換の `analog_date` は `forecast_issue_date` とし、`forecast_issue_date < service_date` と、選択代表クラスの source dates が service date より過去であることを検証する。
  - `scripts/weather/build_solcast_typical_curves.py` と `scripts/weather/build_solcast_typical_proxy_forecast.py` を追加した。Tk の `PV/予報` タブにも「代表カーブ生成」「代表PVから予報JSON生成」、および `solcast_typical_sunny/cloudy/rainy/auto` を追加した。
  - BFF は weather policy 有効時に代表PV曲線を canonical `depot_energy_assets` の capacity factor / PV発電列へ反映する。PV容量は従来どおり `depot_area_m2 * 0.35 * 0.20` で、Solcastは形状だけに使う。
  - `weather_strategy_objective_term_jpy_equivalent` を追加した。`base * (1 - bias)` を BEV/PHEV/FCEV には `bev_duty_bias`、ICE系には `ice_backup_bias` で評価し、MILP objective、ALNS/GA/ABC evaluator、fallback baseline の車種順序へ soft bias として入れる。ただし `allowed_vehicle_types` は変更せず、`total_cost` / `electricity_cost` / `fuel_cost` / `total_cost_with_assets` には混ぜない。
  - `weather_pv_representative_curve.json` を run 出力に追加し、`weather_policy_audit.json` と `run_manifest.json` に typical class、source dates、threshold、PV curve適用有無を残す。
  - `graph/vehicle_timeline.csv` と `vehicle_operation_diagrams/all_vehicles.svg` は duties だけでなく charging/refuel slots の vehicle_id も union し、運用便がなく充電または給油だけ行った車両を出す。
- 自分で上げて潰した追加問題:
  - 代表カーブを単純に先頭slotへ詰めると、05:00開始 horizon で深夜PVが朝PVとして入るため、`horizon_start` と `timestep_min` に基づいて24h代表曲線を時刻対応で切り出すようにした。
  - 天気 bias を実コストへ混ぜると EV電力費・ICE燃料費の ledger 分離を壊すため、目的関数専用の監査項目として独立出力する設計にした。
  - weather policy 無効時に strategy metadata が残ると既存実験比較を汚すため、BFF/Builder 側で有効時だけ `bev_duty_bias` / `ice_backup_bias` / `weather_strategy_bias_base_jpy_per_trip` を渡すようにした。
- 検証:
  - `python -m compileall src/preprocess/weather src/optimization/common/weather_strategy.py src/optimization/common/evaluator.py src/optimization/milp/solver_adapter.py bff/routers/optimization.py bff/services/optimization_run tools/scenario_backup_tk.py scripts/weather/build_solcast_typical_curves.py scripts/weather/build_solcast_typical_proxy_forecast.py` → pass
  - `$env:PYTHONPATH='.'; pytest -q tests/preprocess/test_solcast_typical.py tests/preprocess/test_solcast_pv_proxy.py tests/optimization/test_weather_policy_problem_integration.py tests/test_graph_export_vehicle_operation_diagrams.py` → `18 passed`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_bev_energy_accounting.py tests/test_evaluator_provisional_overwrite.py tests/test_optimization_result_serializer.py tests/test_objective_modes.py tests/test_problem_builder_cost_component_toggles.py tests/preprocess/test_weather_daily_schema.py` → `24 passed`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_canonical_graph_export_parity.py tests/test_scenario_backup_tk_dataset_options.py` → `43 passed`

### 2026-04-30 EV Electricity / ICE Fuel Cost Ledger Separation

- 問題: 最新run `output/2026-04-29/run_20260429_1657` では、`cost_breakdown_detail.json` の `energy_cost=79211.7827` にICEの暫定燃料費が含まれている一方で `fuel_cost=0` だった。`objective_breakdown.json` では `provisional_ice_drive_cost=61829.5672` と `leftover_ice_provisional_cost=61829.5672` が確認できたため、ICE燃料費が電力費表示へ混入していた。
- 対応:
  - `OptimizationObjectiveWeights` に `fuel` を追加し、MILP のICE燃料 objective term は `electricity_cost` 重みではなく `fuel_cost` 重みで評価するようにした。ALNS/GA/ABC/MILP の solver metadata にも `objective_weights.fuel_cost` を出す。
  - `CostBreakdown` に `electricity_cost` と `fuel_cost` を追加した。`electricity_cost` はEV電力商品費のみ、`fuel_cost` は液体燃料費のみ、`energy_cost` は後方互換の推進費合計（`electricity_cost + fuel_cost`）とする。
  - 燃料側にも電力側と同じ監査粒度を追加し、`fuel_cost_provisional_jpy`（走行量から推定した暫定燃料費）、`fuel_cost_refueled_jpy`（実給油イベントで確定した燃料費）、`fuel_cost_provisional_leftover_jpy`（まだ実給油で置換されていない暫定残）、`fuel_cost_final_jpy`（最終燃料ledger）を rich output / KPI / serializer / Tk summary に出すようにした。
  - `contract_overage_cost` は電力商品費に加算せず、需要料金・契約超過ペナルティと同じく別費目として `total_cost` に加える。これにより `electricity_cost_jpy` は「EVが買った電気代」を表す。
  - BFF rich output / canonical graph output / Tk summary を更新し、`charging_summary.json` と `kpi_summary.json` の `electricity_cost_jpy` からICE燃料を除外し、`fuel_cost_jpy` と `propulsion_energy_cost_jpy` を明示出力する。
  - `simulation_conditions_vehicle_costs.csv` は ICE 車両の `fuelCostPerL` または scenario の `diesel_price_per_l` を拾うようにし、燃料単価が 0 に見える出力を防いだ。
  - `ResultSerializer` の weighted component 出力で weight=0 を `1.0` に戻す既存バグを修正した。これにより cost flag OFF / CO2 mode の監査出力が目的重みと一致する。
- 自分で上げて潰した追加問題:
  - `energy_cost` だけを見て「電力費」と表示する旧UI/CSVが残ると同じ誤読が再発するため、表示名を `推進費合計(EV電力+ICE燃料)` に変更し、`EV電力コスト` と `燃料コスト` を先に出すようにした。
  - BFF で車両コストCSV用の `cost_cfg` を誤った helper scope に置くと実行時 `NameError` になるため、`_persist_rich_run_outputs()` 内へ移動した。
- 検証:
  - `python -m py_compile src\optimization\common\evaluator.py src\optimization\common\result.py src\optimization\common\problem.py src\objective_modes.py src\optimization\common\builder.py src\optimization\milp\solver_adapter.py src\optimization\abc\engine.py src\optimization\alns\engine.py src\optimization\ga\engine.py src\optimization\milp\engine.py bff\routers\optimization.py tools\scenario_backup_tk.py` → pass
  - `python -m pytest tests\test_objective_modes.py tests\test_bev_energy_accounting.py tests\test_problem_builder_cost_component_toggles.py tests\test_canonical_result_to_simulation_bridge.py tests\test_canonical_graph_export_parity.py tests\test_optimization_result_serializer.py -q` → `46 passed`

### 2026-04-29 Solcast PV Proxy Forecast

- 問題: `data/derived/pv_profiles/*_YYYY-MM-DD_60min.json` には Solcast 由来の発電形状があるが、従来は PV 充電フロー用の時系列としてのみ使っていた。天気運用ポリシーへ入れるには、PV発電形状を「当日朝に見えている発電見込み proxy」として `WeatherProxyForecast` に変換する入口が必要だった。
- 対応:
  - `src/preprocess/weather/solcast_pv_proxy.py` を追加し、Solcast PV profile JSON の `capacity_factor_by_slot` または `pv_generation_kwh_by_slot` から `sun_score`、低PV回復リスクとしての `rain_risk`、`midday_recovery_expectation`、`operation_mode` を作るようにした。
  - `WeatherProxyForecast` の `forecast_type` / `version` に `solcast_pv_proxy_v1` を追加した。後方互換のため既存フィールド `analog_date` は残し、Solcast版では `forecast_issue_date` と同じ日付を入れる。
  - 未来情報リーク防止として、`forecast_issue_date < service_date` を必須にした。service date 当日のPV形状を使う場合でも、予報として扱うには issue date が前日以前である必要がある。issue date を証明できない ex-post データは optimizer 入力ではなく oracle/reference 扱いに分ける。
  - Python dataclass 側でも `version` / `forecast_type` の許可値と一致を検証し、JSON schema を通らないロード経路でも forecast 種別の混線を拒否する。
  - `scripts/weather/build_solcast_pv_proxy_forecast.py` を追加し、ローカルPV profile JSONから WeatherProxyForecast JSON を生成できるようにした。optimizer 実行中のWebアクセスは行わない。
  - Tk の `PV/予報` タブに「Solcast PVから予報JSON生成」を追加し、選択営業所と運行日から `data/derived/pv_profiles/{depot_id}_{service_date}_60min.json` を探して forecast JSON を生成し、既存の weather policy 反映導線に接続する。
- 自分で上げて潰した追加問題:
  - PV発電量[kWh]と capacity factor を混同すると営業所面積によるPV規模が weather policy を過剰に左右するため、`sun_score` は capacity factor の日積算から計算し、面積/容量は最適化のPV供給量側に残した。
  - `rain_risk` は実降雨ではなく「低PV回復リスク」の proxy であるため、metadata に `rain_risk_source=inferred_from_low_pv_recovery` と `rain_risk_basis` を残すようにした。
  - 既存BFFの未来情報リーク診断は `analog_date` だけを名指ししていたため、`analog_date/forecast_issue_date` という表現に更新した。
- 検証:
  - `python -m py_compile src\preprocess\weather\daily_weather_schema.py src\preprocess\weather\solcast_pv_proxy.py src\preprocess\weather\operation_policy.py scripts\weather\build_solcast_pv_proxy_forecast.py scripts\weather\inspect_weather_proxy.py tools\scenario_backup_tk.py bff\routers\optimization.py` → pass
  - `python -m pytest tests\preprocess\test_solcast_pv_proxy.py tests\preprocess\test_weather_daily_schema.py tests\preprocess\test_weather_proxy_builder.py tests\optimization\test_weather_policy_problem_integration.py tests\test_scenario_backup_tk_dataset_options.py -q` → `47 passed`
  - PowerShell で `$out = Join-Path $env:TEMP 'solcast_pv_proxy_forecast.json'; python scripts\weather\build_solcast_pv_proxy_forecast.py --service-date 2025-08-21 --station-id aobadai --station-name Aobadai --pv-profile-json data\derived\pv_profiles\aobadai_2025-08-21_60min.json --forecast-issue-date 2025-08-20 --out $out; python scripts\weather\inspect_weather_proxy.py --forecast-json $out` を実行し、`forecast_type=solcast_pv_proxy_v1`, `sun_score=0.90`, `operation_mode=aggressive`, `no_future_leakage=true` を確認
  - `python -m pytest tests -q` → `483 passed`

### 2026-04-29 Weather Proxy MILP Runtime Guard

- 問題: Solcast PV proxy を有効にして `mode_milp_only` を実行した直近 run は、`time_limit_seconds_requested=3000`、`solve_time_seconds=3107.75` で時間上限まで走った。job は `completed` だが、UI上は「最適化計算が終わらない」に見える。対象 run は `output/2026-04-29/run_20260429_1555`、job は `output/jobs/46c05c82-2e9b-405b-bde0-75916c756cc3.json`。
- 検証した実行経路:
  - `tools/scenario_backup_tk.py` の `run_selected_execution()` が `time_limit_var=3000` を `run-optimization` payload へ渡す。
  - BFF の `bff/routers/optimization.py` は weather proxy を読み、`final_soc_floor_percent` / `final_soc_target_percent` を scenario `simulation_config` へ注入する。
  - `ProblemBuilder` は `final_soc_target_percent != None` を契機に単日でも 24h power/PV horizon と post-return SOC target を有効化する。
  - solver は `mode_milp_only` のまま `time_limit=3000` で走り、最終的に `truthful_baseline_guardrail` で export された。
- 対応:
  - Tk の `_effective_optimization_time_limit_seconds()` に runtime guard を追加し、Weather proxy 有効かつ `mode_milp_only` で `time_limit > 300` の場合、既定では 300 秒に制限する。
  - 長時間MILPを研究目的で明示実行したい場合は、環境変数 `MC_ALLOW_LONG_WEATHER_MILP=1` を設定するとユーザー指定の time limit をそのまま通す。
  - 通常の `mode_alns_only` はこの guard の対象外とし、Weather proxy enabled の比較実験でも heuristic 系の探索時間は壊さない。
- 自分で上げて潰した追加問題:
  - 通常実行だけでなく `再最適化` 分岐も直接 `time_limit_var` を読んでいたため、同じ `_effective_optimization_time_limit_seconds()` を使うようにした。
- 検証:
  - `python -m py_compile tools\scenario_backup_tk.py` → pass
  - `python -m pytest tests\test_scenario_backup_tk_dataset_options.py -q` → `37 passed`
  - `python -m pytest tests -q` → `486 passed`

### 2026-04-28 Weather Proxy Frontend Integration

- 問題: backend / BFF には Historical Analog Weather Proxy v1 が入ったが、Tk フロントでは既存の `weather_mode` が PV 形状/係数用の「天気モード」に見え、擬似予報を運用ポリシーとして最適化へ渡す導線がなかった。ユーザーは予報JSONを生成・選択しても、SOC floor/target へどう反映されるかを画面上で確認できなかった。
- 対応:
  - `tools/scenario_backup_tk.py` の `PV・天候` セクションで既存項目を `PV天気モード` と明示し、`Historical analog予報 → 最適化ポリシー` を別枠に分離した。
  - ローカル `WeatherProxyForecast` JSON の選択、検証、`operation_mode` からの `final_soc_floor_percent` / `final_soc_target_percent` 画面反映、日別気象CSVからの forecast JSON 生成を追加した。optimizer 実行中の Web アクセスは行わない。
  - Quick Setup 保存、Solver対応 Prepare、run-optimization payload へ `enableWeatherOperationPolicy` / `weatherProxyForecastPath` を伝播する。prepare 側には監査用に `weather_proxy_daily_csv_path` / station 情報も保存する。
  - BFF の scenario / quick-setup / prepare モデルに weather proxy UI フィールドを追加し、prepared input materialize でも current scenario 側の weather proxy 設定を保持する。
- 自分で上げて潰した追加問題:
  - `weather_mode` という既存ラベルはPVプロファイル補助と運用ポリシーを混同させるため、UI表示と stale reason を `PV天気モード` / `PV天気係数` に変更した。
  - Quick Setup 読込で `finalSocFloorPercent=0`、`finalSocTargetPercent=0`、`weatherFactorScalar=0` など明示ゼロが `or default` で潰れる箇所があった。`None` のみ fallback する helper に置き換えた。
  - Prepare ボタンが入力検証前に「開始」ログ/ダイアログを出していた。weather proxy 不正や運行日未入力では開始表示を出さず止まるよう、payload 構築を先に移した。
  - 実行直前の自動 weather policy 反映で `StringVar` trace が prepared state を消す可能性があったため、内部検証時のSOC表示同期は prepare watcher を一時停止する。
- 検証:
  - `python -m py_compile tools\scenario_backup_tk.py bff\routers\scenarios.py bff\routers\simulation.py bff\services\simulation_builder.py bff\services\run_preparation.py`
  - `python -m pytest tests\test_scenario_backup_tk_dataset_options.py tests\test_scenario_update_simulation_settings.py tests\test_simulation_builder_prepare_scope.py tests\optimization\test_weather_policy_problem_integration.py -q`

### 2026-04-28 Run Parameter UI/UX Redesign

- 問題: Tk の実行パラメータ欄は `基本パラメータ` と `詳細パラメータ` の縦積みで、料金、SOC、ICE燃料、CO2、PV、weather proxy、目的関数 cost flags、ソルバー詳細が長い一画面に混在していた。最適化前に何を順番に確認すべきかが分かりにくく、編集対象を探すためのスクロール量も大きかった。
- 対応:
  - `tools/scenario_backup_tk.py` の実行パラメータ欄を `よく使う` / `SOC/燃料` / `料金/CO2` / `PV/予報` / `目的/詳細` の Notebook タブへ再配置した。
  - 既存の `StringVar` / `BooleanVar`、Quick Setup 保存、Prepare payload、run-optimization payload は変更せず、同じ編集欄を見つけやすい単位に移動した。編集可能なパラメータの削除や意味変更は行っていない。
  - `PV天気モード` と `Historical analog予報` は `PV/予報` タブへ集約し、PV発電形状用の天気指定と最適化ポリシー用の擬似予報を同じ文脈で確認できるようにした。
  - 長い設定画面でも mouse wheel が子ウィジェット上で効くよう、実行パネルの canvas scroll binding を再帰的に張った。
- 自分で上げて潰した追加問題:
  - タブラベルを UI 内の散在文字列にすると将来の回帰検知が難しいため、`_RUN_PARAMETER_TAB_LABELS` として定数化し、テストから主要カテゴリを固定確認できるようにした。
  - cost flags は「目的関数に含める」編集項目なので、料金/CO2タブへ移して、費用評価とCO2評価をまとめて確認できるようにした。
  - `enableWeatherOperationPolicy=false` でも run-optimization payload に stale な `weatherProxyForecastPath` を残せていたため、無効時は実行 payload から予報パスを落とすよう修正した。
- 検証:
  - `python -m py_compile tools\scenario_backup_tk.py` → pass
  - `python -m pytest tests\test_scenario_backup_tk_dataset_options.py tests\test_scenario_update_simulation_settings.py tests\test_simulation_builder_prepare_scope.py tests\optimization\test_weather_policy_problem_integration.py -q` → `42 passed`
  - `python -m pytest tests -q` → `477 passed`

### 2026-04-24 Historical Analog Weather Proxy v1

- 問題: 既存の `weather_mode` は天気カテゴリや PV プロファイル選択の周辺情報に留まり、過去実気象を「当日朝に得られた擬似予報」として最適化入力へ再現可能に渡す構造がなかった。天気ラベルを BEV/ICE 台数へ直接 hard 変換すると研究上の説明が弱く、対象日当日の実績を見てしまうと未来情報リークになる。
- 対応:
  - `src/preprocess/weather/` を追加し、`DailyWeatherObservation`、Kishojin diary HTML parser、JMA/標準日別CSV loader、historical analog selector、operation policy mapper、forecast builder を分離した。
  - `schema/weather_daily_observation.schema.json`、`schema/weather_proxy_forecast.schema.json`、`schema/weather_operation_policy.schema.json` を追加し、forecast JSON は `version/source/station/analog_date/selection_score/no_future_leakage` を保持する。
  - `scripts/weather/build_weather_daily_csv.py`、`build_weather_proxy_forecast.py`、`inspect_weather_proxy.py` を追加した。parser/loader はローカル HTML/CSV だけを読み、optimizer 実行中の Web アクセスは行わない。
  - BFF canonical optimization は `weatherProxyForecastPath` と `enableWeatherOperationPolicy=true` を受けた場合、forecast JSON を検証し、`ProblemBuilder` の前に `final_soc_floor_percent` / `final_soc_target_percent` を scenario へ注入する。これにより SOC target が必要な場合の horizon contract を builder が正しく見られる。
  - `apply_weather_policy_to_problem()` は frozen `CanonicalOptimizationProblem` を破壊せず、BEV/PHEV/FCEV の `initial_soc` を seed 固定の ratio でランダム化し、`weather_proxy` / `weather_operation_profile` / `weather_initial_soc_policy` / soft bias metadata を追加する。ICE の SOC は変更しない。
  - run 出力に `weather_proxy_forecast.json`、`weather_operation_policy.json`、`weather_policy_audit.json` を追加し、`run_manifest.json` に `weather_proxy_enabled`、`weather_proxy_version`、`weather_operation_mode`、`weather_analog_date` を追加した。
- 自分で上げて潰した追加問題:
  - 最初に `ProblemBuilder` 後の metadata 注入だけで済ませると、weather policy が設定する `final_soc_target_percent` を builder が見られず、単日 24h horizon 拡張が発火しない。forecast/profile を builder 前に読み込み、scenario `simulation_config` に SOC target を注入してから canonical problem を作る形に修正した。
  - analog selector で target 前日が存在するのに candidate 前日が欠ける候補が calendar-only と同じ扱いになり、前日特徴を使う候補より不自然に有利になり得た。candidate 前日または比較可能特徴が欠ける場合は penalty を入れ、D-1 が存在しないときだけ `analog_fallback_reason=missing_previous_day_actual` の calendar-only mode に落とすようにした。
  - `pytest` 直接実行ではこの環境の import path が root を含まず `src` / `bff` import で collection error になるため、検証コマンドは既存運用どおり `python -m pytest ...` を正とした。
- 研究上の影響:
  - weather proxy v1 は天気ラベルを hard constraint に変換しない。`operation_mode` は SOC 余裕、初期SOC分布、昼充電優先度、BEV/ICE soft bias 用 metadata へ変換する。
  - 対象日当日の実績値は類似日選択に使わない。`analog_date >= service_date` または `no_future_leakage=false` は schema/BFF/apply helper で拒否する。
  - PV の運用限界費用は `pv_marginal_charge_cost_yen_per_kwh=0.0` と明示するが、PV 設備費・保守費・減価償却費を会計 KPI から消す変更ではない。資産費は `total_cost_with_assets` など別 KPI で扱う。
  - 予報誤差分布、午後の天候急変、確率的/ロバスト最適化、rolling horizon 再最適化は v1 では未実装で、今後の展望として残す。
- 検証:
  - `python -m py_compile src\preprocess\weather\daily_weather_schema.py src\preprocess\weather\jma_daily_csv_loader.py src\preprocess\weather\kishojin_diary_parser.py src\preprocess\weather\historical_analog.py src\preprocess\weather\operation_policy.py src\preprocess\weather\weather_proxy_builder.py scripts\weather\build_weather_daily_csv.py scripts\weather\build_weather_proxy_forecast.py scripts\weather\inspect_weather_proxy.py bff\routers\optimization.py`
  - `python -m pytest tests\preprocess tests\optimization\test_weather_policy_problem_integration.py -q`
  - `python -m pytest tests -q` → `472 passed`

### 2026-04-17 Main SOC Bulk Apply and Template Randomization

- 問題: `initialSoc` の個別編集と営業所単位ランダム化は車両管理タブに入っていたが、メイン設定画面の `初期SOC比` は詳細パラメータの奥に残っており、主操作として見つけにくかった。また template 経由の車両追加は `initialSoc` を main 画面の固定値でしか渡せず、template workflow 内でランダム化できなかった。
- 対応:
  - `tools/scenario_backup_tk.py` の `充電・SOC` セクションへ `初期SOC比` を移し、`選択営業所の全BEVへ Save/Prepare 時に一斉反映` チェックボックスを追加した。
  - Save/Prepare 前に、チェックが有効なら選択営業所の BEV `vehicles[].initialSoc` を一括更新してから処理を続ける helper を追加した。適用成功後は checkbox を自動で OFF に戻す。
  - `SOC詳細` から重複していた `初期SOC比` 入力は外し、見える start SOC 入力を一本化した。
  - `テンプレートから営業所へ車両追加` と `テンプレート追加 -> 作成後に営業所へ追加` に `固定値/ランダム` の初期SOC設定を追加した。random mode は batch create 後に各 BEV を `update_vehicle(initialSoc=...)` で振り直す形にし、ICE は対象外にした。
- 自分で上げて潰した追加問題:
  - `create_vehicle_batch` は単一 payload の複製なので per-vehicle random SOC をそのまま渡せない。作成後 update に切り替えて解消した。
  - Save/Prepare 本体が失敗した場合でも、先に成功した SOC 一括反映が UI 上で分からなくなる恐れがあったため、exception path でも checkbox clear / stale mark / log を走らせるようにした。
- 検証:
  - `python -m pytest tests/test_scenario_backup_tk_dataset_options.py -q`
  - 既存の UI helper 回帰に加え、`_main_initial_soc_ratio`, `_initial_soc_values_for_mode`, `_apply_initial_soc_to_bev_vehicles`, `_finalize_main_initial_soc_bulk_apply` をテストした。

### 2026-04-18 Vehicle Batch Selection and Frontend Cleanup

- 問題: 車両管理は単一選択前提で、複数車両をまとめて扱うには営業所全件 batch しかなく、対象を絞れなかった。また `on_vehicle_select()` は一覧取得済み row があるのに毎回 `get_vehicle()` を叩いており、車両一覧 refresh が重なったとき stale response が UI を巻き戻す余地もあった。
- 対応:
  - `tools/scenario_backup_tk.py` の車両一覧に checkbox 列を追加し、表示中の全選択/選択数表示/選択車両の有効化・無効化・削除を追加した。
  - `初期SOC一括設定...` は営業所全件 BEV ではなく、checkbox で選んだ BEV だけへ固定値/ランダム値を適用するよう変更した。checkbox が空のときは表示中の BEV 全件へフォールバックする。
  - `on_vehicle_select()` は `vehicle_row_by_id` cache から form を埋めるようにし、一覧 row に既にある情報では追加 API を呼ばないようにした。
  - `refresh_vehicles()` には request token を入れ、遅れて返った古いレスポンスを捨てるようにした。checkbox 列は rowheight/font/幅を上げ、ヘッダクリックで全選択/全解除できるようにした。
  - `_submit_execution_job()` と job polling は payload/start_response/job snapshot のログを圧縮し、成功ポップアップを抑え、poll interval を緩めて最適化実行中の UI ノイズと負荷を下げた。
- 自分で上げて潰した追加問題:
  - row checkbox と form selection が同じ click に乗ると編集対象が意図せず変わるので、checkbox 列クリック時は `TreeviewSelect` を止めるようにした。
  - batch action 後に checked state が残ったまま別営業所へ切り替わると誤操作につながるため、visible rows と checked ids を都度 intersection して summary を更新するようにした。
- 検証:
  - `python -m pytest tests/test_scenario_backup_tk_dataset_options.py tests/test_problemdata_soc_overrides.py tests/test_scenario_update_simulation_settings.py tests/test_run_preparation_scope_audit.py -q` → pass
  - `python -m py_compile C:\\master-course\\tools\\scenario_backup_tk.py` → pass

### 2026-04-17 Per-vehicle Initial SOC Editing

- `vehicles[].initialSoc` を BEV 車両ごとの開始 SOC の正本に切り替えた。canonical builder と problemdata mapper の両方で、車両に明示値がある場合はそれを最優先し、未設定時のみ `initial_soc_percent` → `initial_soc` → full-battery fallback の順で補完する。
- `bff/routers/master_data.py` / `bff/store/scenario_store.py` は車両 create/update/bulk-create で `initialSoc` を受け取り、ICE への型切替時は `initialSoc` を明示的にクリアできるようにした。
- `tools/scenario_backup_tk.py` の車両管理 UI に `initialSoc` 入力欄、一覧列、営業所単位の固定値 / ランダム一括設定を追加した。車両変更後は prepared input を stale 扱いに戻す。
- 回帰テスト: `tests/test_problemdata_soc_overrides.py`, `tests/test_master_data_vehicle_initial_soc.py`, `tests/test_scenario_backup_tk_vehicle_soc.py`, `tests/test_scenario_store_atomic_mutations.py`

### 2026-04-17 Negative Total Cost Semantics Fix

- 問題: `CostEvaluator` が `return_leg_bonus` を `total_cost` から直接差し引いていたため、UI / API / experiment report 上の `総コスト` が実費ではなく「報酬込みの目的関数値」になっていた。`BASELINE_FALLBACK` の不正解でも `objective_value=-49,718円` のような表示が出て、会計値と solver score の意味が混ざっていた。
- 対応: `src/optimization/common/evaluator.py` で `accounting_total_cost` と `objective_cost_term` を分離した。`cost_breakdown.total_cost` / `total_cost_with_assets` は純粋な会計コスト、`objective_value` は `accounting_total_cost - return_leg_bonus` をベースに各 objective mode へ渡すよう変更した。`return_leg_bonus` 自体は cost breakdown の独立キーとして残す。
- 付随修正:
  - `bff/routers/optimization.py` は top-level `cost_breakdown.total_cost` 生成時に `objective_value` を優先しないよう修正し、`return_leg_bonus` と canonical `cost_breakdown.json` の component 出力を追加した。
  - `bff/services/experiment_reports.py` は `return_leg_bonus_jpy` を report payload に追加し、`demand_charge_jpy` が存在しない `peak_demand_cost` を見ていた不整合も修正した。
  - `tools/scenario_backup_tk.py` / `tools/bus_operation_visualizer_tk.py` は `総コスト` と `目的関数値` を分離表示し、`solution_validity.validated_feasible=false` の結果を `暫定/無効` として明示するようにした。
- 自分で上げて潰した追加問題: canonical result payload の `objective_components_raw/weighted` に `driver_cost` と `return_leg_bonus` が載っておらず、目的関数の分解が不完全だったため追加した。`solver_metadata.objective_weights` にも `return_leg_bonus` を通した。
- 検証:
  - `python -m pytest tests/test_evaluator_provisional_overwrite.py tests/test_scenario_backup_tk_dataset_options.py tests/test_negative_total_cost_semantics.py tests/test_solution_validity.py -q` → `33 passed`
  - `python -m pytest tests/test_visualizer_report_utils.py tests/test_optimization_canonical_metaheuristics.py tests/test_optimization_result_serializer.py tests/test_solver_identity_metadata.py -q` → `16 passed`
  - `python -m py_compile src/optimization/common/evaluator.py src/optimization/common/result.py src/optimization/engine.py src/optimization/milp/engine.py src/optimization/alns/engine.py src/optimization/ga/engine.py src/optimization/abc/engine.py bff/routers/optimization.py bff/services/experiment_reports.py tools/scenario_backup_tk.py tools/bus_operation_visualizer_tk.py` → pass

### [DEV-2026-04-11] dated run output layout and mandatory route-band manifest

- 背景:
  - canonical / simulation / exporter の run 保存先が `output/<service_date>/scenario/...` や feed/snapshot 系の深い階層に分散しており、run 単位の成果物確認がしづらかった。
  - `graph/route_band_diagrams` は条件付き生成だったため、SVG が出ない run で manifest が欠けることがあった。

- 対応:
  - `src/run_output_layout.py` を追加し、`output/<YYYY-MM-DD>/run_YYYYMMDD_HHMM[/_02]` の collision-safe な割当を共通化した。
  - `bff/routers/optimization.py` / `bff/routers/simulation.py` の保存先を新 layout に統一し、optimization は `raw/` 配下に `optimization_result.json` / `optimization_audit.json` / `solver_result.json` / `canonical_solver_result.json` / `assignment.csv` / `unserved_trips.csv` を残すようにした。
  - `src/result_exporter.py` は `graph/route_band_diagrams/manifest.json` を常時出力し、`run_manifest.json` に graph artifact 参照を載せるようにした。
  - `tools/_visualizer_report_utils.py` は新 run 形式の読み取りへ寄せ、simulation_result は run 直下の同名ファイルを優先参照するようにした。

- 研究上の影響:
  - output の正本は run 直下に一本化され、旧 scenario/deep-feed 階層を正本として使わない。
  - route-band 図は「出せるときだけ」ではなく run の標準成果物になった。SVG が 0 件でも manifest は残る。

- 回帰テスト:
  - `tests/test_run_output_layout.py`
  - `tests/test_graph_export_route_band_diagrams.py`
  - `tests/test_canonical_graph_export_parity.py`
  - `tests/test_visualizer_report_utils.py`

### [DEV-2026-04-11] strict precheck の route-family 欠落による偽 infeasible 修正

- 背景:
  - `tsurumaki` の strict coverage 実行で `strict_coverage_precheck_infeasible` が solver 呼び出し前に返り、MILP に到達しないケースがあった。
  - call chain を追うと `bff/routers/optimization.py` → `ProblemBuilder.build_from_scenario()` → `OptimizationEngine.solve()` → `evaluate_strict_coverage_precheck()` の順に実行され、停止点は precheck だった。
  - 根因は、dispatch `Trip` が持つ `route_family_code`（例: `渋21` / `渋22`）を canonical `ProblemTrip` に渡していなかったこと。`fixed_route_band_mode=true` 時に route-band key が family ではなく `route_id` fallback になり、緩和 lower bound が過大化していた。

- 対応:
  - `src/optimization/common/problem.py`
    - `ProblemTrip` に `route_family_code: str = ""` を末尾フィールドとして追加（既存位置引数呼び出し互換を維持）。
  - `src/optimization/common/builder.py`
    - dispatch `Trip` → canonical `ProblemTrip` 変換で `route_family_code` を伝播。
    - multi-day 複製時も `route_family_code` を保持。
  - strict precheck アルゴリズム本体は変更せず、`trip_route_band_key()` が canonical family metadata を参照できる状態へ戻した。
  - 低リスク追従として、baseline materialize 時の startup rejection 監査を `optimization_result.summary` / `optimization_audit` に追加（`startup_rejected_*` 集計と `startup_rejected_vehicle_ids_by_duty`）。

- 研究上の影響:
  - `fixed_route_band_mode=true` の数学的意味（family ベースの route-band 固定）を保ったまま誤検知のみ除去。
  - `fixed_route_band_mode=false` へ落として回避する運用は可行性ワークアラウンドとしてのみ扱い、benchmark 比較の正本には使わない。
  - dispatch feasibility 条件 `arrival + turnaround + deadhead <= next departure`、depot-reset 可否ロジック、目的関数の意味は変更していない。

- 回帰テスト:
  - `tests/test_strict_coverage_precheck.py`
    - fixed route-band かつ同一 family の複数 variant で、family metadata あり/なしの lower bound 差分を検証。
    - prepared-input 相当形状（variant 混在）で family metadata ありなら `relaxed_vehicle_lower_bound <= available_vehicle_count` となり、偽 infeasible にならないことを検証。
  - `tests/test_problem_builder_route_family_metadata.py`
    - canonical 変換時の `route_family_code` 伝播と multi-day 複製保持を検証。

### [DEV-2026-04-11] Windows job persistence retry/fallback

- 背景:
  - Windows で `bff/store/job_store.py` の `temp_path.replace(path)` が `PermissionError [WinError 5]` を返し、job 永続化が落ちることがあった。
  - 同じ BFF プロセス内で background task や graph build job を poll する経路では、`get_job()` が毎回 disk を再読込して self-contention を起こしやすかった。

- 対応:
  - `bff/store/job_store.py`
    - `_persist_job()` に retry/backoff を追加し、Windows の一時ロック時に即死せず再試行するようにした。
    - `create_job()` に `execution_model` を追加し、job metadata に `thread` / `process` を保存できるようにした。
    - `get_job()` は `execution_model=thread` の job では disk reload を避け、disk read が失敗した場合も既存の in-memory job を返すようにした。
  - `bff/routers/optimization.py` / `bff/routers/simulation.py`
    - executor 実行モードを job metadata に付与した。
  - `bff/routers/graph.py` / `scripts/run_build_graph.py`
    - background task / standalone graph build job も `execution_model=thread` として統一した。

- 研究上の影響:
  - dispatch feasibility、`timetable_rows`、route-family strict precheck の数学的意味は変更していない。
  - これは Windows 上の job 永続化・polling の競合を減らす実装上の耐障害化であり、solver 結果の比較可否には影響しない。

- 回帰テスト:
  - `tests/test_job_store_windows_persistence.py`

### [DEV-2026-04-11] Depot startup deadhead inference

- 背景:
  - `tsurumaki / WEEKDAY / prepared-ca500b7c95b16ca9` では startup assignment が全件 `startup_deadhead_missing` になり、Gurobi が routing / charging に入る前に止まっていた。
  - 既存の route-family terminal inference は stop→stop の deadhead しか作らず、depot→first origin と last destination→depot が抜けていた。

- 対応:
  - `src/route_family_runtime.py`
    - `merge_deadhead_metrics()` に `depots` を追加し、depot 座標と stop 座標から startup / return deadhead を推論するようにした。
    - 既存の stop-platform alias と route-family terminal inference は維持し、`arrival + turnaround + deadhead <= next departure` の strict feasibility は変えない。
  - `src/optimization/common/builder.py`
    - canonical problem 生成時に scenario の `depots` を deadhead merge に渡すようにした。
  - `bff/mappers/scenario_to_problemdata.py`
    - BFF の problem-data 生成でも `depots` を deadhead merge に渡すようにした。
  - `bff/routers/graph.py`
    - graph/debug path でも同じ depot deadhead inference を使うようにした。

- 研究上の影響:
  - これは欠けていた depot-stop connectivity を復元する修正であり、startup feasibility の意味を弱めていない。
  - route-band の意味、strict coverage、dispatch feasibility 条件は変更していない。

- 回帰テスト:
  - `tests/test_depot_deadhead_inference.py`

### [DEV-2026-04-10] Strict coverage infeasibility precheck

- 自分で上げた問題:
  - strict coverage の fixed prepared scope で feasible incumbent が存在しない条件でも、各 solver が 900 秒級で探索して `Infinity` を返すだけになり、ユーザーには「solver が回っていない」のか「入力が数学的に infeasible」なのか判別しづらかった。
  - `prepared-37586d60b9c53eba` を確認したところ、598 trips に対して available vehicles は 40 台だった。SOC・燃料・型別台数制約を無視した緩和 path-cover 下限でも 46 台以上が必要で、strict full coverage はこの snapshot では feasible incumbent を持てない。

- 対応:
  - `src/optimization/common/strict_precheck.py` を追加し、strict coverage のみ solver 前に緩和 vehicle lower bound を計算するようにした。
  - 緩和問題でも `required vehicles > available vehicles` なら、元問題は infeasible と証明できるため、`OptimizationEngine` が solver を呼ばずに `SOLVED_INFEASIBLE` を返す。
  - 結果 metadata には `strict_coverage_precheck`、`strict_coverage_relaxed_vehicle_lower_bound`、`available_vehicle_count_total`、`termination_reason=strict_coverage_precheck_infeasible` を残す。

- 研究上の影響:
  - strict feasibility 条件、dispatch feasibility 条件、`timetable_rows` は変更していない。
  - 今回の変更は「解けない入力を feasible に見せる」ものではなく、「緩和下限で infeasible と証明できる入力を早期に比較対象外へ分類する」ための監査強化である。

- 回帰テスト:
  - `tests/test_strict_coverage_precheck.py`

- 確認:
  - `python -m pytest tests/test_strict_coverage_precheck.py tests/test_benchmark_metrics_schema.py tests/test_benchmark_cost_min_strict_schema.py tests/test_benchmark_prepare_snapshot_match.py tests/test_benchmark_prepare_mismatch_excluded.py tests/test_benchmark_fail_flag_for_unserved_with_unused_available.py tests/test_problem_service_coverage_mode.py tests/test_evaluator_strict_vs_penalized_coverage.py tests/test_evaluator_strict_unserved_is_infeasible.py -q`
  - `python -m py_compile src/optimization/common/strict_precheck.py src/optimization/engine.py`

### [DEV-2026-04-09] Strict coverage / same-day depot cycle repair

- 背景:
  - `OptimizationScenario` には `allow_same_day_depot_cycles` / `max_depot_cycles_per_vehicle_per_day` が既に入っていたが、builder / assignment / feasibility / MILP / benchmark summary まで一貫して伝播していなかった。
  - `service_coverage_mode=strict` のつもりでも、実 solver path では `allow_partial_service` と有限 `unserved_penalty` が残り、unused vehicle があっても欠便を合法的に返せる穴があった。
  - fixed prepared scope 比較でも `prepared_input_id` 以外に scope fingerprint が残っておらず、同一 snapshot 監査が弱かった。

- 対応:
  - `src/optimization/common/problem.py`
    - `normalize_service_coverage_mode()` / `service_coverage_allows_partial_service()` を追加し、coverage mode の正規化を共通化。
  - `src/optimization/common/builder.py`
    - `build_from_dispatch()` に `service_coverage_mode` を追加し、`allow_partial_service` は coverage mode から mirror する形へ変更。
    - same-day fragment metadata (`daily_fragment_limit`, `service_coverage_mode`, `fixed_route_band_mode`) を canonical problem metadata へ明示保存。
  - `src/scenario_overlay.py`
    - `SolverConfig.fixed_route_band_mode` の既定値を `False` へ変更。未指定 scenario で暗黙に route band 固定が有効になる drift を止めた。
  - `src/dispatch/feasibility.py`
    - `evaluate_startup_feasibility()` を追加し、`startup_alias_missing` / `startup_deadhead_missing` を reason code として返すようにした。
  - `src/optimization/common/vehicle_assignment.py`
    - startup feasibility helper を流用し、day-aware fragment cap helper を追加。
  - `src/optimization/common/feasibility.py`
    - `service_coverage_mode=strict` では uncovered trip を error、`penalized` では warning に分離。
    - same-day per-day fragment cap を `fragment_count` まで含めて検証。
  - `src/optimization/common/evaluator.py`
    - strict mode かつ `plan.unserved_trip_ids` 非空なら `objective_value=inf` を返し、`unserved_penalty` は penalized mode でのみ加算。
  - `src/optimization/milp/solver_adapter.py`
    - strict mode では `u[i]==0` を強制し、auto relax を停止。
    - vehicle × day の `start_arc` / `end_arc` 上限を追加。
    - startup feasibility を alias-aware helper へ統一。
    - `MILPSolverOutcome` に benchmark/audit 用 runtime metadata を追加。
    - strict mode で unserved baseline を fallback として返さないよう修正。
  - `src/optimization/milp/model_builder.py`
    - arc enumeration でも unavailable vehicle を除外。
    - strict / penalized で `cover_trip` description を分岐。
  - `bff/services/run_preparation.py`
    - prepared input に `scope_hash` を追加し、materialized scenario の `prepared_scope_summary` にも反映。
  - `bff/routers/optimization.py`
    - `optimization_result.summary` / `optimization_audit` に `service_coverage_mode`, `fixed_route_band_mode`, `daily_fragment_limit`, `scenario_hash`, `scope_hash` を追加。
  - `scripts/benchmark_solver_modes.py`
    - `objective_mode`, `service_coverage_mode`, `scenario_hash`, `scope_hash` を row schema に追加。
    - `random_seed` を run request body へ送るよう修正。
    - fixed snapshot 4 solver 比較では prototype maturity の GA / ABC も main comparison group に残せるよう grouping を補強。

- テスト:
  - 追加:
    - `tests/test_builder_same_day_and_coverage_wiring.py`
    - `tests/test_vehicle_assignment_per_day_fragment_cap.py`
    - `tests/test_route_band_depot_reset_flag.py`
    - `tests/test_dispatch_feasibility_startup_reason_codes.py`
    - `tests/test_milp_strict_coverage.py`
    - `tests/test_milp_same_day_vehicle_day_caps.py`
    - `tests/test_feasibility_strict_service.py`
    - `tests/test_feasibility_day_fragment_caps.py`
    - `tests/test_model_builder_vehicle_available_and_successor_cap.py`
    - `tests/test_optimization_audit_common_snapshot.py`
    - `tests/test_benchmark_cost_min_strict_schema.py`
  - 回帰:
    - `python -m pytest tests/test_problem_service_coverage_mode.py tests/test_evaluator_strict_vs_penalized_coverage.py tests/test_same_day_depot_cycles.py tests/test_milp_route_band_settings.py tests/test_milp_baseline_fallbacks.py tests/test_benchmark_search_profile_export.py tests/test_benchmark_metrics_schema.py tests/test_builder_same_day_and_coverage_wiring.py tests/test_vehicle_assignment_per_day_fragment_cap.py tests/test_route_band_depot_reset_flag.py tests/test_dispatch_feasibility_startup_reason_codes.py tests/test_milp_strict_coverage.py tests/test_milp_same_day_vehicle_day_caps.py tests/test_feasibility_strict_service.py tests/test_feasibility_day_fragment_caps.py tests/test_model_builder_vehicle_available_and_successor_cap.py tests/test_optimization_audit_common_snapshot.py tests/test_benchmark_cost_min_strict_schema.py tests/test_problem_builder_depot_energy_asset_controls.py -q` → `59 passed`
    - `python -m compileall src bff scripts` は touched file 群は通過。既存の `scripts/unzip_and_rename_solcast.py` に unicode escape の SyntaxError が残っているため full pass にはなっていない

### [DEV-2026-04-10] 営業所面積由来PV容量とSolcast形状の分離

- 背景:
  - 従来は `pv_capacity_kw` を営業所エネルギー資産に直接持たせていたため、「PV規模」と「Solcast実日プロファイルの形状」が同じ入力欄に混ざっていた。
  - 自分で確認した問題として、旧 `pv_generation_kwh_by_slot` だけを持つ行をそのまま面積モデルへ通すと、面積変更時に発電量が2倍にならず、旧固定容量の発電列が残り得た。

- 対応:
  - `src/optimization/common/pv_area.py`
    - `depot_area_m2 * usable_area_ratio(0.35) * panel_power_density_kw_m2(0.20)` の共通計算を追加。
    - `depot_area_m2` が null / 0 以下の場合はPV容量0として扱う。
  - `tools/scenario_backup_tk.py`
    - `営業所別充電器管理` に `営業所面積 [m²]`、`推定PV設置可能面積 [m²]`、`推定PV設備容量 [kW]` を追加。
    - 営業所エネルギー資産の行編集では `pv_capacity_kw` を読取専用の推定値にし、入力は `depot_area_m2` へ寄せた。
  - `bff/routers/master_data.py` / `bff/routers/scenarios.py`
    - 営業所CRUDとQuick Setup payloadに `depotAreaM2` を通す。
  - `bff/services/run_preparation.py`
    - Prepare時に `depot_energy_assets` へ `depot_area_m2`、`estimated_installable_area_m2`、`derived_pv_capacity_kw`、面積由来の `pv_capacity_kw` を埋める。
    - 旧 `pv_generation_kwh_by_slot` + `pv_capacity_kw` は `legacy_pv_capacity_kw` から容量係数へ戻してから、面積由来容量で再スケールする。
  - `src/optimization/common/builder.py`
    - canonical problemでは固定 `pv_capacity_kw` をPV有効条件に使わず、`depot_area_m2 > 0` のみでPV規模を決める。
    - Solcast由来の `pv_capacity_factor_by_date` / `capacity_factor_by_slot` を形状として扱い、`pv_generation_kwh_by_slot = derived_capacity_kw * capacity_factor * Δt[h]` で再構築する。
  - `src/optimization/common/solcast_pv_profiles.py`
    - Solcast容量係数を `min(1, irradiance/1000 * performance_ratio)` に変更し、既定 `performance_ratio=0.85` を出力メタデータへ保存。
  - `schema/depot.schema.json` / `schema/energy.schema.json` / `schema/canonical-problem.schema.json`
    - `depotAreaM2` と `DepotEnergyAsset` の面積・容量係数フィールドを追加。

- 数理・互換性:
  - この変更はPV容量の数学的意味を変更する。旧固定容量PVのKPIとは直接比較しない。
  - 旧シナリオに `depot_area_m2` が無い場合はPV無効として落ちずに動く。
  - Solcastは天候・時刻の形状、営業所面積はPV規模という役割分担を維持する。

- テスト:
  - 追加/更新:
    - `tests/test_run_preparation_depot_area_pv_assets.py`
    - `tests/test_problem_builder_depot_energy_asset_controls.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_scenario_backup_tk_pv_sync.py`
    - `tests/test_solcast_pv_profiles.py`
    - `tests/test_depot_energy_asset_schema.py`
  - 回帰:
    - `python -m pytest tests/test_solcast_pv_profiles.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_depot_energy_asset_schema.py tests/test_scenario_backup_tk_pv_sync.py tests/test_run_preparation_depot_area_pv_assets.py -q` → `24 passed`
    - `python -m pytest tests/test_simulation_builder_prepare_scope.py tests/test_quick_setup_advanced_persistence.py tests/test_scenario_backup_tk_pv_sync.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_case_comparison_pv_bess.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_demand_charge_unit_contract.py -q` → `28 passed`
    - `python -m compileall src\optimization\common\pv_area.py src\optimization\common\solcast_pv_profiles.py src\optimization\common\builder.py src\optimization\common\problem.py bff\routers\master_data.py bff\routers\scenarios.py bff\routers\pv_management.py bff\services\run_preparation.py tools\scenario_backup_tk.py` → passed

### [DEV-2026-04-10] Availability-aware strict benchmark guard v2

- 背景:
  - same-day / strict coverage の配線後も、`ProblemVehicle.available` が比較母数と solver candidate で完全に統一されていなかった。
  - fixed prepared input を使い回す比較は stale snapshot の不安が残るため、各 solver run 前に scenario から再 prepare し、prepare 後の canonical snapshot が一致した row だけを主比較に載せる方針へ更新した。

- 対応:
  - `src/optimization/common/problem.py`
    - `ProblemVehicle.available` の契約を docstring に明記。
    - `AssignmentPlan.count_used_available_vehicles(problem)` / `unused_available_vehicle_ids(problem)` を追加。
  - `src/optimization/common/builder.py`
    - available / unavailable vehicle count と id を metadata に出力。
    - baseline materialize / greedy baseline には available vehicle のみを渡す。
    - scenario vehicle の `available` / `enabled` を読み、`available=False` を維持したまま audit 可能にした。
  - `src/optimization/common/vehicle_assignment.py`
    - unavailable vehicle を候補から除外。
    - startup rejection を `debug_metadata["startup_rejected_vehicle_ids_by_duty"]` に記録可能にした。
  - `src/dispatch/route_band.py`
    - `FragmentTransitionDiagnostic` と `fragment_transition_diagnostic()` を追加し、`direct_ok` / `depot_reset_ok` / `route_band_blocked` / `deadhead_missing` / `location_alias_missing` を区別。
  - `src/dispatch/feasibility.py`
    - startup reason に `startup_time_insufficient` / `startup_route_band_blocked` を追加。既定では horizon 前 deadhead を許容し、`earliest_available_min` が明示された場合だけ時間不足を判定。
  - `src/optimization/milp/solver_adapter.py`
    - unavailable vehicle の `used_vehicle` を 0 固定。
    - strict coverage metadata (`service_coverage_mode`, `allow_partial_service`, `strict_coverage_enforced`) を出力。
    - startup infeasible assignment の trip / vehicle summary を plan metadata へ出力。
    - Gurobi callback で初 incumbent 時刻を記録し、`first_feasible_sec=0.0` の fake 値をやめた。
    - 同一日 fragment の `end_arc + start_arc <= 1` depot-reset incompatibility cut を追加。
  - `src/optimization/milp/model_builder.py`
    - assignment / arc pair の両方で unavailable vehicle を除外。
    - successor cap 未指定時の default は後続の 237d dense graph 対応で `8` に戻している。exact 比較が必要な場合は `milp_max_successors_per_trip` を明示的に大きくする。
  - `src/optimization/common/feasibility.py`
    - unavailable vehicle に duty が載った場合は hard error。
    - strict uncovered message を `strict coverage violated with N uncovered trips` に変更。
    - fragment transition error に reason code を含める。
  - `src/optimization/common/evaluator.py`
    - `evaluation_feasible` を cost breakdown に追加。
    - utilization denominator を available vehicle count に変更。
  - `bff/services/run_preparation.py`
    - `get_or_build_run_preparation(..., force_rebuild=True)` を追加。
  - `bff/routers/optimization.py`
    - `RunOptimizationBody.force_reprepare` を追加。
    - summary / audit / canonical_problem_summary に availability と startup infeasible audit を追加。
  - `scripts/benchmark_solver_modes.py`
    - prepared input 未指定時は各 solver run で `force_reprepare=true` を送る。
    - availability / startup / strict / prepare snapshot audit columns を追加。
    - `mark_prepare_snapshot_matches()` を追加し、snapshot mismatch row を `appendix_prepare_mismatch` へ隔離。

- テスト:
  - 追加:
    - `tests/test_problem_vehicle_available_contract.py`
    - `tests/test_builder_available_vehicle_metadata.py`
    - `tests/test_vehicle_assignment_excludes_unavailable.py`
    - `tests/test_vehicle_assignment_startup_rejection_trace.py`
    - `tests/test_route_band_transition_reason_codes.py`
    - `tests/test_startup_feasibility_reason_codes.py`
    - `tests/test_feasibility_rejects_unavailable_vehicle_usage.py`
    - `tests/test_feasibility_strict_message.py`
    - `tests/test_evaluator_strict_unserved_is_infeasible.py`
    - `tests/test_model_builder_respects_available.py`
    - `tests/test_model_builder_successor_cap_default.py`
    - `tests/test_milp_strict_coverage_metadata.py`
    - `tests/test_milp_first_feasible_time_not_fake_zero.py`
    - `tests/test_milp_fragment_pairwise_reset_cut.py`
    - `tests/test_benchmark_availability_audit_columns.py`
    - `tests/test_benchmark_prepare_snapshot_match.py`
    - `tests/test_benchmark_prepare_mismatch_excluded.py`
    - `tests/test_benchmark_fail_flag_for_unserved_with_unused_available.py`
  - 回帰:
    - `python -m pytest tests/test_problem_service_coverage_mode.py tests/test_evaluator_strict_vs_penalized_coverage.py tests/test_same_day_depot_cycles.py tests/test_milp_route_band_settings.py tests/test_milp_baseline_fallbacks.py tests/test_benchmark_search_profile_export.py tests/test_benchmark_metrics_schema.py tests/test_problem_vehicle_available_contract.py tests/test_builder_available_vehicle_metadata.py tests/test_vehicle_assignment_excludes_unavailable.py tests/test_vehicle_assignment_startup_rejection_trace.py tests/test_route_band_transition_reason_codes.py tests/test_startup_feasibility_reason_codes.py tests/test_feasibility_rejects_unavailable_vehicle_usage.py tests/test_feasibility_strict_message.py tests/test_evaluator_strict_unserved_is_infeasible.py tests/test_model_builder_respects_available.py tests/test_model_builder_successor_cap_default.py tests/test_milp_strict_coverage_metadata.py tests/test_milp_first_feasible_time_not_fake_zero.py tests/test_milp_fragment_pairwise_reset_cut.py tests/test_benchmark_availability_audit_columns.py tests/test_benchmark_prepare_snapshot_match.py tests/test_benchmark_prepare_mismatch_excluded.py tests/test_benchmark_fail_flag_for_unserved_with_unused_available.py -q` → `60 passed`

### [DEV-2026-03-28] MILP重大バグ7件の一括修正（core_pv）

- **背景**:
  - コードレビューで、目的関数のデマンド料金換算、割当制約の計算量、SOCモデリング注記不足、logger import 破損、PV KPI 不足、冗長制約、既知制限の明示不足が指摘された。

- **対応**:
  - `src/objective.py`
    - デマンド料金を月額 [円/kW/月] からホライズン日数換算（`horizon_days/30.0`）へ修正。
  - `src/constraints/assignment.py`
    - `no_overlap` ペア列挙を削除し、`one_task_per_slot[k,t]` の時刻ベース実装へ置換。
    - `y_follow` 直前に depot 仮想ノード未実装の既知制限コメント（TODO）を追記。
  - `src/constraints/charging.py`
    - `add_soc_constraints()` docstring 冒頭へ、イベントベースSOC計上の仮定と安全マージン推奨を追記。
  - `src/milp_model.py`
    - `MILPResult` に `soc_modeling_note` と `pv_to_bus_kwh` を追加。
    - `pre_solve_check()` に SOC 安全マージン警告（最大単一トリップ消費の50%基準）を追加。
    - `extract_result()` で `pv_to_bus_kwh`（kWh換算）を集計。
  - `src/constraints/energy_balance.py`
    - 冗長な `pv_self_consume` 制約を削除し、`power_balance` 由来で上限制約される旨の NOTE を追記。
  - `src/experiment_logger.py`
    - 壊れた自己参照 import を廃止し、`src/pipeline/logger.py` からの公開エントリポイントへ置換。

- **検証**:
  - AC-1 ～ AC-6: すべて PASS（import確認、属性確認、換算係数、旧制約除去、冗長制約除去、py_compile）。
  - AC-7: `pytest tests/ -q` 実行で `148 passed`。
  - PR: `core_pv <- fix/milp-bugs-7items` として作成済み（#2）。

### [DEV-2026-03-27] Quick Setup保存整合 / SOC override / prepared stop coordinates

- **背景**:
  - 237d シナリオの cost-min 再実行で、Quick Setup の詳細設定と実ソルバー入力の間にドリフトが残っていた。
  - legacy ProblemData 側では `final_soc_target_percent` が車両 `soc_target_end` に反映されず、既定 `targetEndSoc=0.6` が優先されるケースがあった。
  - prepared input の `stops` が座標なし推論停止 (`prepared_input_inferred`) に落ちると、deadhead 距離/時間が 0 の接続が残り物理説明性が弱くなった。

- **対応**:
  - `bff/mappers/scenario_to_problemdata.py`
    - legacy `Vehicle` 生成時に `initial_soc_percent` / `soc_min` / `final_soc_floor_percent` / `final_soc_target_percent` を優先反映するよう修正。
  - `src/optimization/common/builder.py`
    - canonical vehicle state でも `initial_soc_percent` / `final_soc_floor_percent` / ICE燃料比 override を実車両へ反映し、ALNS/GA/ABC と MILP の初期条件差を縮小。
  - `bff/services/run_preparation.py`
    - scoped trip / timetable から参照 stop_id を収集し、`tokyu_bus_data.load_stops()` の座標付き stop を優先採用するよう変更。
    - 座標付き stop と inferred stop をマージし、missing name は補いながら deadhead 推論に必要な緯度経度を保持。
  - `bff/routers/scenarios.py` / `tools/scenario_backup_tk.py`
    - Quick Setup で `objectiveWeights` と `randomSeed` を保存・再読込。
    - frontend では `slack_penalty` / `degradation` を専用欄と JSON 欄で分解・再構成し、保存後のドリフトを抑制。

- **テスト**:
  - `tests/test_problemdata_soc_overrides.py`
  - `tests/test_run_preparation_stop_coords.py`
  - `tests/test_quick_setup_advanced_persistence.py`

### [DEV-2026-03-27] 充電物理妥当性の強化: timetable-based home-depot charging windows

- **背景**:
  - 既存 MILP は `home depot` 接続便の前後1スロット近傍に依存した proxy 拘束が中心で、
    発表時に「実際にその時刻に充電可能窓だったか」の説明が弱かった。
  - 学会向け説明では、厳密扱い領域と近似領域の切り分けをコード・README双方で一致させる必要があった。

- **対応**:
  - `src/optimization/common/builder.py`
    - `charging_window_mode`（`timetable_layover` / `home_depot_proxy`）を metadata へ保存。
    - `home_depot_charge_pre_window_min` / `home_depot_charge_post_window_min` を追加。
  - `src/optimization/milp/solver_adapter.py`
    - `timetable_layover` 時、trip の出発前/到着後ウィンドウを時刻ベースで列挙し、
      そのスロットでのみ充電・給油を許可する制約へ更新。
    - 互換性のため `home_depot_proxy` を残し、窓列挙が空になるケースには proxy へフォールバック。
    - `_slot_indices_for_interval()` の日跨ぎ処理を補強（`arrival <= departure` 時の 24h 補正）。
  - `README.md`
    - 充電窓モードの説明を追加。
    - デマンド料金の単日 proxy 前提を明記。

- **テスト**:
  - `tests/test_milp_route_band_settings.py`
    - builder metadata 反映（`charging_window_mode` と window 幅）を追加検証。
    - timetable-based 窓列挙ヘルパーのスロット整合テストを追加。

### [DEV-2026-03-26] MILP妥当性修正: ICE燃料上限・売電変数・課金/デマンド定義を実測整合へ

- **背景**:
  - MILPにおいて、ICEの燃料状態が制約化されておらず、タンク容量超過の割当が理論上許容される。
  - 電力収支は系統受電のみで表現され、PV余剰/V2G時の逆潮流を扱えない。
  - 電力料金が「走行消費」課金になっており、充電時刻最適化やPV自家消費効果が反映されない。
  - デマンド料金制約が走行エネルギーを需要電力に加算していた。

- **対応**:
  - `src/constraints/assignment.py`
    - ICE車両に `fuel_tank_cap` 制約を追加（`sum(task_fuel_ice * x) <= fuel_tank_capacity`）。
    - `use_link` を車両ごとの集約制約へ変更（制約本数削減）。
  - `src/milp_model.py`
    - `p_grid_export` 変数を追加（非負連続）。
    - `slack_cover` を `CONTINUOUS` から `BINARY` へ変更。
    - ICE向け `fuel[k,t]` 変数を追加し、燃料時系列制約を組み込み。
  - `src/constraints/energy_balance.py`
    - 電力収支式に `p_grid_export` を導入し、逆潮流を表現可能化。
    - デマンド追跡を `p_grid_import <= peak_demand` に統一（走行消費の混入を除去）。
  - `src/objective.py`
    - 電力量料金を「メーター課金」へ変更：`buy_price * p_grid_import * delta_h`。
    - 売電時は `sell_back_price * p_grid_export * delta_h` を控除。
    - `energy_balance` 非使用時は旧ロジックをフォールバックとして保持。
  - `src/constraints/charging.py`
    - SOC遷移の充電項を `charger_efficiency * vehicle.charge_efficiency` で換算するよう明示。
    - ICE燃料遷移 `fuel[k,t+1] = fuel[k,t] - burn[k,t]` と上下限制約を追加。

- **テスト**:
  - `pytest tests/test_objective_modes.py tests/test_milp_route_band_settings.py -q`
  - 結果: `12 passed`
  - `pytest tests/test_bev_energy_accounting.py -q`
  - 結果: `3 passed`

- **追加対応（同日）**:
  - `src/simulator.py`
    - 仮電力量の算定を改善し、BEVは `soc[t]-soc[t+1]` の放電量を優先利用（SOC系列がある場合）。
    - これにより長時間便・深夜跨ぎ時のスロット課金整合を改善。
    - `total_grid_export_kwh` / `grid_export_kw_series` を `SimulationResult` に追加。
  - `src/milp_model.py`
    - `MILPResult` に `grid_export_kw` を追加し、`p_grid_export` の抽出を実装。
    - `y_follow[k,r1,r2]` 変数を実際に生成するよう更新。
  - `src/constraints/assignment.py`
    - `y_follow` の連結パス制約を追加（in/out次数上限、edge_count整合）。
    - これにより回送コスト・回送エネルギーで参照する遷移弧が有効化。
  - `src/constraints/charging.py`
    - SOC遷移式に回送消費項（`deadhead_energy_kwh * y_follow`）を追加。
    - 後続便の出発直前スロットへ回送消費を計上する方式で反映。
  - `src/objective.py`
    - 回送コスト計算を全ペア総当たりから `y_follow` 既存弧のみ走査へ最適化。

- **追加対応（同日・本格実装）**:
  - `src/milp_model.py`
    - `x_assign` を feasible `(k,r)` のみ生成するスパース化へ変更。
    - `z_charge` / `p_charge` / `p_discharge` を feasible `(k,c,t)` のみ生成へ変更。
    - 結果抽出部をスパースkey存在チェック対応に更新。
  - `src/constraints/assignment.py`
    - 不適合ペア `x==0` 制約を削除（変数未生成で表現）。
  - `src/constraints/charging.py`
    - スパース `z/p` 前提で制約生成を更新（互換性0固定ループを廃止）。
  - `src/constraints/charger_capacity.py`
    - スパース `z_charge` での容量制約に対応。
  - `src/constraints/optional_v2g.py`
    - スパース `z_charge/p_discharge` 参照に対応。
  - `src/constraints/battery_degradation.py`
    - スパース `p_charge/p_discharge` 参照に対応。
  - `src/model_factory.py`
    - `mode_A_journey_charge` の固定割当をスパース変数対応に更新。

- **テスト**:
  - `pytest tests/test_objective_modes.py tests/test_milp_route_band_settings.py tests/test_bev_energy_accounting.py -q`
  - 結果: `15 passed`
  - `pytest -q`
  - 結果: `113 passed`

### [DEV-2026-03-27] ALNS/Rolling 本格修正（論文前提の致命ギャップ解消）

- **背景**:
  - ALNS の多くの repair operator が `charging_slots` を更新せず、
    評価関数の電力コスト/需要料金がダミー化するリスクがあった。
  - rolling reoptimize で API 入力 `actual_soc` が canonical problem の車両初期SOCへ反映されていなかった。
  - `peak_hour_removal` が 7-9 時ハードコード、`worst_trip_removal` が経験式スコアのまま。

- **対応**:
  - `src/optimization/rolling/reoptimizer.py`
    - `reoptimize(..., actual_soc=...)` を追加。
    - `actual_soc` を車両 `initial_soc` へ適用してから再最適化する実装を追加。
  - `bff/routers/optimization.py`
    - reopt worker から `RollingReoptimizer.reoptimize()` へ `actual_soc` を明示伝播。
  - `src/optimization/alns/operators_repair.py`
    - `greedy_trip_insertion` / `baseline_dispatch_repair` / `partial_milp_repair` / `regret_k_insertion` の返却時に
      充電スロット再計算を実行する `_with_recomputed_charging()` を追加。
    - 簡易SOC追跡で不足時に idle 窓へ充電を挿入する `_recompute_charging_slots()` を追加。
  - `src/optimization/alns/operators_destroy.py`
    - `peak_hour_removal` をデータ駆動化（`classify_peak_slots(price_slots)` を優先、fallback は設定窓）。
    - `worst_trip_removal` に `objective_fn` を導入し、限界改善量ベース除去を実装。
  - `src/optimization/alns/engine.py`
    - `peak_hour_removal` に問題データ（price slots）と設定を渡す。
    - `worst_trip_removal` に `CostEvaluator` ベースの限界改善スコア関数を渡す。
  - `src/optimization/common/feasibility.py`
    - `charging_slots` と trip energy に基づく SOC 妥当性チェックを追加（出発時必要SOC/下限違反を errors 化）。
  - `src/optimization/common/problem.py`
    - `OptimizationConfig` に `use_data_driven_peak_removal`, `peak_hour_windows_min`, `worst_trip_scoring` を追加。
  - `src/parameter_builder.py`
    - BEV 電費 fallback 既定値を `1.2 -> 1.8 kWh/km` へ上方修正。

- **テスト**:
  - 追加: `tests/test_reopt_alns_critical_fixes.py`
    - rolling actual_soc 伝播
    - data-driven peak removal
    - marginal-cost worst trip removal
    - feasibility SOC shortage 検出
  - 実行:
    - `pytest tests/test_reopt_alns_critical_fixes.py -q` → `4 passed`
    - `pytest tests/test_milp_route_band_settings.py tests/test_bev_energy_accounting.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py -q` → `17 passed`

### [DEV-2026-03-27] 再レビュー対応（reopt 安全化 + BFF実経路テスト）

- **背景**:
  - `RollingReoptimizer.reoptimize()` の baseline lock 分岐が `CanonicalOptimizationProblem(...)` 手組み再構築だったため、
    将来のフィールド追加時に情報欠落リスクがあった。
  - `actual_soc` は BFF 実装で伝播済みだが、BFF worker 経路を直接検証する回帰テストが未整備だった。
  - capabilities note が process 固定の文言で、Windows 既定 thread 実装と説明が不整合だった。

- **対応**:
  - `src/optimization/rolling/reoptimizer.py`
    - baseline lock 分岐を `replace(problem, baseline_plan=locked_plan, metadata=dict(problem.metadata))` に変更。
    - 問題定義フィールドを保ったまま lock 済み baseline だけ差し替える形へ統一。
  - `tests/test_reopt_alns_critical_fixes.py`
    - baseline lock 時に `routes/depots/vehicle_types/depot_energy_assets/metadata` が保持される回帰テストを追加。
  - `tests/test_bff_reoptimization_actual_soc_forwarding.py`（新規）
    - `_run_reoptimization()` worker 経路で `actual_soc` が `RollingReoptimizer.reoptimize(..., actual_soc=...)` へ渡ることを検証。
  - `bff/routers/optimization.py`
    - capabilities note を "dedicated executor (thread or process)" へ修正。

- **連続実行安定性チェック（Windows 実測）**:
  - full suite を 5 連続実行:
    - 各回 `122 passed`（失敗 0）
    - 実行時間: 約 23 秒/回
  - 最適化関連ターゲットを 10 連続実行:
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_reopt_alns_critical_fixes.py`
    - `tests/test_bff_reoptimization_actual_soc_forwarding.py`
    - 各回 `18 passed`（失敗 0）
    - 実行時間: 約 0.82-0.92 秒/回

### [DEV-2026-03-27] EV/ICE 共通 ledger 化 + 補給イベント再設計

- **背景**:
  - 既存は EV 電力のみ provisional/final 分離があり、ICE 燃料の同等会計と
    vehicle/day ledger の統一構造が不足していた。
  - ALNS の補給再計算は前倒し補給寄りで、必要時遅延補給に寄せる改善余地があった。

- **対応**:
  - `src/optimization/common/problem.py`
    - `VehicleCostLedgerEntry`, `DailyCostLedgerEntry` を追加。
    - `AssignmentPlan` に `vehicle_cost_ledger`, `daily_cost_ledger` を追加。
    - `OptimizationScenario` に multi-day / overnight 制御パラメータを追加。
  - `src/optimization/common/evaluator.py`
    - EV: provisional/final/leftover を ledger 指標として明示。
    - ICE: `_evaluate_liquid_fuel_with_overwrite()` を追加し、
      provisional fuel debt → refuel event で rollback/realize を実装。
    - `CostBreakdown` を provisional/realized/leftover の運用コスト系列で拡張。
    - `build_plan_ledgers()` を追加し、車両別・日別 ledger を生成。
  - `src/optimization/milp/engine.py`, `src/optimization/alns/engine.py`, `src/optimization/hybrid/hybrid_engine.py`
    - evaluator 生成 ledger を `AssignmentPlan` へ注入して返却。
  - `src/optimization/common/result.py`
    - `vehicle_cost_ledger`, `daily_cost_ledger` を API payload へ出力。
    - operating/EV/ICE provisional-realized-leftover のトップレベル出力を追加。
  - `src/optimization/alns/operators_repair.py`
    - `_recompute_charging_slots()` を「遅いスロット優先の必要量補給」に更新。
    - depot/port/slot電力の簡易上限制御を追加。
    - overnight window を見た補給禁止（forbid）ゲートを追加。
    - `_recompute_refuel_slots()` を追加し ICE の補給イベント再生成を実装。
  - `bff/mappers/solver_results.py`
    - simulator 出力にも operating/EV/ICE provisional-realized-leftover キーを追加（互換拡張）。

- **テスト**:
  - `tests/test_evaluator_provisional_overwrite.py`
    - ICE 補給なし leftover 検証
    - ICE 補給あり rollback + realized 検証
  - `tests/test_optimization_result_serializer.py`
    - ledger payload と operating split のシリアライズ検証
  - 実行結果:
    - `pytest tests/test_evaluator_provisional_overwrite.py tests/test_optimization_result_serializer.py tests/test_reopt_alns_critical_fixes.py tests/test_bff_reoptimization_actual_soc_forwarding.py -q` → `12 passed`
    - `pytest tests/test_milp_route_band_settings.py tests/test_case_comparison_pv_bess.py tests/test_bev_energy_accounting.py -q` → `16 passed`
    - `pytest -q` → `125 passed`

### [DEV-2026-03-27] 残タスク完了（MILP補給挙動ペナルティ + multi-day carryover）

- **背景**:
  - 前段で未着手だった 2 点:
    - MILP objective における全台同時/早期充電の抑制ペナルティ
    - multi-day ledger の day 間 carryover 継続性

- **対応**:
  - `src/optimization/milp/solver_adapter.py`
    - 追加した soft penalty フック:
      - `charge_session_start_penalty_yen`
      - `slot_concurrency_penalty_yen`
      - `early_charge_penalty_yen_per_kwh`
      - `charge_to_upper_buffer_penalty_yen_per_kwh`
    - 追加変数/制約:
      - charge session start binary
      - slot concurrency excess
      - SOC upper-buffer excess
    - metadata へ penalty 設定値を書き戻し。
  - `src/optimization/common/evaluator.py`
    - `build_plan_ledgers()` を multi-day 対応強化。
    - `planning_days > 1` のとき vehicle ledger を day ごとに展開し、
      `end(day n) == start(day n+1)` を満たす carryover 連鎖を生成。

- **テスト**:
  - 追加: `tests/test_milp_solver_penalty_helpers.py`
    - soft concurrency limit と early-charge weight の挙動を検証。
  - 追加: `tests/test_evaluator_multiday_ledger.py`
    - 3日 ledger の件数と day 間 carryover 継続性を検証。
  - 実行結果:
    - `pytest tests/test_milp_solver_penalty_helpers.py tests/test_evaluator_multiday_ledger.py tests/test_evaluator_provisional_overwrite.py tests/test_milp_route_band_settings.py -q` → `18 passed`
    - `pytest -q` → `128 passed`

  - `src/result_exporter.py`
    - `summary.json` の `kpi` に `total_grid_export_kwh` を追加。
  - `tools/bus_operation_visualizer_tk.py`
    - サマリー表示に以下を追加:
      - 電力コスト基準（provisional/charged）
      - 電力コスト(仮) / 電力コスト(充電実績)
      - 系統受電量 / 系統売電量

### [DEV-2026-03-25] 出力先ディレクトリを output に統一（output/outputs 混在解消）

- **背景**:
  - 実行経路によって `output/` と `outputs/` が混在し、成果物・ジョブ・prepared inputs の参照先が分散していた。

- **対応**:
  - 新規: `bff/store/output_paths.py`
    - `outputs_root()` を追加し、既定を `output/` に統一（`MC_OUTPUTS_DIR` があれば優先）。
    - `scenarios_root()` を追加し、既定を `output/scenarios/` に統一（`SCENARIO_STORE_PATH` があれば優先）。
  - 更新:
    - `run_app.py`（bundled mode 既定出力を `output/` に変更）
    - `bff/store/scenario_store.py`（scenario/app_context の既定ルートを共通ヘルパー経由へ）
    - `bff/store/job_store.py`（ジョブ保存先を `output/jobs` に変更）
    - `bff/routers/optimization.py`（prepared_inputs と最適化出力ルートを共通化）
    - `bff/routers/simulation.py`（prepared_inputs とシミュレーション出力ルートを共通化）
    - `bff/routers/graph.py`（subset export 先を共通化）
    - `bff/services/experiment_reports.py`（experiment report 出力先を共通化）

- **テスト**:
  - `pytest tests/test_prepared_scope_execution.py tests/test_run_preparation_hash.py -q`
  - 結果: `3 passed`

### [DEV-2026-03-25] Route Family runtime に公式根拠ベース override 層を追加（東98/渋41/渋42）

- **背景**:
  - runtime repair 後の真値に対し、Quick Setup 側で scenario ごとに見え方が揺れる課題が残っていた。
  - 複雑系統（東98/渋41/渋42）は heuristic 単独より、公式公開情報に沿った固定タグ層を持つ方が再現性が高い。

- **対応**:
  - `bff/services/runtime_route_family.py`
    - `official_manual_override` 層を追加（user manual override より下位、derived より上位）。
    - family code + terminal pair で以下を固定:
      - 東98: `main_outbound/main_inbound/depot_out/depot_in`
      - 渋41: `main_outbound/main_inbound/branch/short_turn`
      - 渋42: `main_outbound/main_inbound/branch`
    - 公式対象 family の `routeFamilyLabel` を固定補完:
      - 東98: `東京駅南口 ⇔ 清水`
      - 渋41: `渋谷駅 ⇔ 大井町駅`
      - 渋42: `渋谷駅 ⇔ 大崎駅西口`
    - user manual が存在する route は従来通り最優先で保持。

- **テスト**:
  - `tests/test_runtime_route_family.py`
    - 公式 override 回帰（東98/渋41/渋42の variant と source）を追加。
    - user manual override 優先の回帰を追加。
  - `tests/test_quick_setup_route_selection.py`
    - Quick Setup payload で公式 family label が露出する回帰を追加。

### [DEV-2026-03-24] 目黒1営業所で PVなし / PVあり / PV+BESSあり の3比較を試行

- **対象シナリオ**:
  - ベース: `outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-bb5102a730db115c.json`
  - 生成: `outputs/scenario_meguro_pv_bess_sat.json`

- **設定した基本パラメータ（目黒）**:
  - `timestep_min = 60`
  - `service_id = SAT`
  - `pv_capacity_kw = 480.8`
  - `pv_generation_kwh_by_slot` は `meguro_2025-08-01_60min.json` を基に、運行 horizon に合わせて 19 要素へ整合
  - `bess_energy_kwh = 1000.0`
  - `bess_power_kw = 250.0`
  - `bess_initial_soc_kwh = 500.0`
  - `bess_soc_min_kwh = 100.0`
  - `bess_soc_max_kwh = 1000.0`
  - `bess_terminal_soc_min_kwh = 300.0`
  - `allow_grid_to_bess = false`（case matrix 側で case ごとに切替）

- **実行コマンド**:
  - `python scripts/run_depot_energy_case_matrix.py --scenario outputs/scenario_meguro_pv_bess_sat.json --depot-id meguro --service-id SAT --output-dir outputs/case_matrix_meguro_sat --mode milp --time-limit-sec 180 --mip-gap 0.05 --random-seed 42 --alns-iterations 120`

- **出力**:
  - `outputs/case_matrix_meguro_sat/case_matrix_summary.csv`
  - `outputs/case_matrix_meguro_sat/case_matrix_results.json`

- **結果要約**:
  - case0 (PVなし): objective `3030546.0138`, `solver_status=optimal`, `feasible=false`
  - case1 (PVあり): objective `3030546.0138`, `solver_status=optimal`, `feasible=false`
  - case2 (PV+BESS): objective `2949002.7571`, `solver_status=optimal`, `feasible=false`
  - 注: `allow_partial_service=true` のため未充足便が残り、`feasible=false`。比較は目的値ベースで実施。

### [DEV-2026-03-24] Solcast CSV実投入: 全営業所日別JSON生成と台帳自動同期コマンド追加

- **背景**:
  - `data/external/solcast_raw/` に 12 営業所分の `*_2025_08_60min.csv` が配置されたため、
    全営業所一括で日別JSON生成と台帳ステータス更新を実行した。

- **実行内容**:
  - 日別JSON一括生成
    - コマンド: `python scripts/build_pv_profiles.py --raw-dir data/external/solcast_raw --out-dir data/derived/pv_profiles --slot-minutes 60 --mode gti --overwrite`
    - 結果: `JSON files written: 372`（12営業所 × 31日）
    - 出力: `data/derived/pv_profiles/{depot_id}_2025-08-XX_60min.json`
  - 台帳自動同期（新規補助コマンド）
    - 新規: `scripts/sync_solcast_registry.py`
    - コマンド: `python scripts/sync_solcast_registry.py --registry data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json --raw-dir data/external/solcast_raw --timezone +09:00 --fallback-period-min 60`
    - 結果: `updated=12, cached=12, missing=0`

- **更新された台帳情報**:
  - ファイル: `data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json`
  - `last_synced_at`: `2026-03-24T10:02:31.731615+00:00`
  - 各営業所に以下を自動付与:
    - `acquisition_status=cached`
    - `acquired_at`（CSV更新時刻UTC）
    - `record_count`
    - `available_dates`
    - `min_period_end`, `max_period_end`
    - `time_column`, `irradiance_column`

- **追記（同日）**:
  - `build_pv_profiles.py` の `period_end` 解釈を修正（区間終端を直前スロットへ割当）。
  - `pv_generation_kwh_by_slot` / `capacity_factor_by_slot` を 24 要素固定化。
  - 修正後に 12営業所 × 31日（372件）を再生成し、`meguro_2025-08-01_60min.json` の 24 要素を確認。

### [DEV-2026-03-24] フェーズ2着手: 実車両優先生成 + depot_energy_assets 編集導線（BFF/Schema/UI）

- **目的**:
  - canonical problem 生成時の車両IDを、タイプ別カウント由来の合成IDから「営業所別実車両情報」優先へ移行。
  - `depot_energy_assets` を Quick Setup/Prepare から編集・保存できる経路を確立。

- **対応**:
  - `src/optimization/common/builder.py`
    - `build_from_scenario()` で選択営業所スコープの実車両レコードを抽出し `build_from_dispatch()` に受け渡し。
    - `build_from_dispatch()` に `scenario_vehicles` / `disable_vehicle_acquisition_cost` 引数を追加。
    - 実車両レコード優先の `_build_vehicles_from_records()` を追加（`vehicle_id`, `depotId`, `enabled` を反映）。
    - 既存のタイプ別カウント生成 `_build_vehicles()` はフォールバックとして維持。
  - `bff/routers/scenarios.py`
    - `UpdateQuickSetupBody` に `depotEnergyAssets` を追加。
    - `GET /quick-setup` の `simulationSettings` に `depotEnergyAssets` を返却。
    - `PUT /quick-setup` で `simulation_config.depot_energy_assets` へ保存。
  - `bff/routers/simulation.py` / `bff/services/simulation_builder.py`
    - `PrepareSimulationSettingsBody` に `depot_energy_assets` を追加。
    - Prepare 適用時に `simulation_config.depot_energy_assets` へ保存。
  - `tools/scenario_backup_tk.py`
    - 詳細パラメータに `depot_energy_assets(JSON)` 入力欄を追加。
    - Quick Setup 読込/保存で JSON 往復を実装。
    - Prepare payload に `depot_energy_assets` を追加。

- **テスト**:
  - 更新: `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - 実車両優先（`bev-1`）と所属営業所（`dep-1`）を検証。
  - 更新: `tests/test_simulation_builder_prepare_scope.py`
    - `depot_energy_assets` が `simulation_config` に保存されることを検証。

### [DEV-2026-03-24] フェーズ1着手: timestep可変化とPV換算のslot幅連動、depot_default依存の縮小

- **目的**:
  - 30分固定前提を外し、Solcast 1時間データと整合する基盤へ移行する。
  - 単一営業所（安全側）で `depot_default` 依存を下げる。

- **対応**:
  - `src/optimization/common/builder.py`
    - `simulation_config.timestep_min` / `scenario_overlay.solver_config.timestep_min` を受け取り、未指定時 60 分を既定化。
    - `OptimizationScenario.timestep_min` の固定 30 分を撤廃し、可変 `timestep_min` を適用。
    - `pv_available_kw * 0.5` 固定換算を廃止し、`slot_h = timestep_min / 60` で `pv_generation_kwh_by_slot` を構成。
    - canonical problem の depot id を選択営業所 ID（単一営業所）で生成し、車両 `home_depot_id` も同一 ID で統一。
    - `depot_energy_assets` の fallback 読み込みで `depot_default` と canonical depot id の互換を保持。
    - 時刻スロット生成・TOU展開・tariff展開の `delta_t_min` を `timestep_min` 連動化。

- **テスト**:
  - 追加: `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - 60分設定で `pv_generation_kwh_by_slot == (2.0, 4.0)`
    - 30分設定で `pv_generation_kwh_by_slot == (1.0, 2.0)`
  - 更新: `tests/test_problem_builder_depot_energy_asset_controls.py`
    - canonical depot id を `dep-1` 前提へ再整合。
  - 実行:
    - `pytest tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_optimization_result_serializer.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `11 passed`

### [DEV-2026-03-24] 充電地点を営業所固定として座標を出力に連携

- **方針**:
  - 充電地点は営業所とみなし、車両別の推定滞在地点推論は導入せず、まず営業所経緯度を確実に出力へ流す。

- **対応**:
  - `src/optimization/common/problem.py`
    - `ProblemDepot` に `latitude` / `longitude` を追加。
    - `ChargingSlot` に `charging_depot_id` / `charging_latitude` / `charging_longitude` を追加。
  - `src/optimization/common/builder.py`
    - scenario の `depots` から営業所座標を読み取り、`metadata.depot_coordinates_by_id` に保持。
    - 選択営業所情報を `ProblemDepot` の name/座標へ反映。
  - `src/optimization/milp/solver_adapter.py`
    - `ChargingSlot` 生成時に営業所IDと営業所経緯度を付与。
  - `src/optimization/common/result.py`
    - `charging_schedule` に営業所IDと経緯度をシリアライズ。

- **テスト**:
  - 追加: `tests/test_optimization_result_serializer.py` に営業所座標出力検証を追加。
  - 実行:
    - `pytest tests/test_optimization_result_serializer.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `9 passed`

### [DEV-2026-03-24] core_pv フォローアップ: BESS終端・同時充放電・CO2会計・Grid→BESS価格条件を修正

- **背景**:
  - 営業所別 PV/BESS フロー導入後、終端スロットの BESS 物理整合性と CO2 会計の厳密性を強化する必要があった。

- **対応**:
  - `src/optimization/milp/solver_adapter.py`
    - BESS 充放電の同時成立を禁止（スロットごと binary mode 制約）。
    - 充放電出力上限を全スロットに適用（終端スロット含む）。
    - 終端 SOC 下限制約（`bess_terminal_soc_min_kwh`）を導入し、最終時刻の過放電抜け穴を抑止。
    - `allow_grid_to_bess=True` 時でも、価格閾値・許可スロットに応じて `g2bess=0` を課すゲートを追加。
    - CO2 目的項を BEV 走行電力量ベースから、`Grid→Bus + Grid→BESS` 実フローベースへ変更。
  - `src/optimization/common/evaluator.py`
    - CO2 評価を実フロー（`grid_to_bus + grid_to_bess`）優先へ変更（fallback は従来方式）。
  - `src/optimization/common/problem.py` / `src/optimization/common/builder.py`
    - `DepotEnergyAsset` に以下を追加し scenario から取り込み:
      - `grid_to_bess_price_threshold_yen_per_kwh`
      - `grid_to_bess_allowed_slot_indices`
      - `bess_terminal_soc_min_kwh`
  - `scripts/build_depot_energy_case.py`
    - 上記パラメータを CLI から生成可能に拡張。

- **テスト**:
  - 追加: `tests/test_evaluator_co2_from_actual_grid_import.py`
  - 追加: `tests/test_problem_builder_depot_energy_asset_controls.py`
  - 実行:
    - `pytest tests/test_problem_builder_depot_energy_asset_controls.py tests/test_evaluator_co2_from_actual_grid_import.py tests/test_evaluator_provisional_overwrite.py tests/test_case_comparison_pv_bess.py tests/test_depot_energy_asset_schema.py -q`
    - 結果: `7 passed`

### [DEV-2026-03-24] BFF/Tk/exporter に最終電力費・仮残高と営業所フロー出力を反映

- **目的**:
  - 最適化で導入した `electricity_cost_final` / provisional 残高を API・UI・レポートに貫通させる。
  - solver 出力に営業所フロー列 (`grid_to_bus`, `bess_to_bus`, `pv_to_bess`, `grid_to_bess`) を追加する。
  - 実データで Case0〜3 を一括比較する runner を追加する。

- **主変更**:
  - `bff/mappers/solver_results.py`
    - simulation payload に `electricity_cost_basis` / `electricity_cost_provisional_jpy` /
      `electricity_cost_charged_jpy` / `electricity_cost_provisional_leftover_jpy` を追加。
  - `bff/routers/optimization.py`
    - `cost_breakdown` に `electricity_cost_final` / provisional 残高 / depot energy flow 集計キーを追加。
  - `bff/services/experiment_reports.py`
    - 実験ログ用 payload で `electricity_cost_jpy` を最終値ベース化し、
      provisional 残高とフロー KPI を追加。
  - `tools/scenario_backup_tk.py`
    - Summary/Compare に `electricity_cost_final` と `electricity_cost_provisional_leftover` を表示。
  - `src/result_exporter.py`
    - `depot_energy_flows.csv` / `depot_energy_flows.json` を追加。
    - `experiment_report.md` に最終/仮/充電実績/仮残高の電力費行を追加。
  - `scripts/run_depot_energy_case_matrix.py`（新規）
    - scenario JSON を入力に Case0〜3 を連続実行し、
      `case_matrix_summary.csv` / `case_matrix_results.json` を出力。

### [DEV-2026-03-24] core_pv B案: 営業所別 PV→BESS→EV 充電モデルと仮コスト上書き会計を導入

- **目的**:
  - 従来の `系統 + PV = 充電需要` 1本モデルを、営業所別の `PV→BESS→Bus` / `Grid→Bus` / `Grid→BESS` フローへ拡張。
  - 電力費を「走行時仮計上」から「充電実績 source ベース上書き」へ移行。

- **主変更**:
  - `src/optimization/common/problem.py`
    - `DepotEnergyAsset` 追加。
    - `CanonicalOptimizationProblem.depot_energy_assets` 追加。
    - `AssignmentPlan` に営業所×スロットのエネルギーフロー出力（grid_to_bus, bess_to_bus, pv_to_bess, grid_to_bess, pv_curtail, bess_soc）追加。
    - slot 長不一致・BESS初期SOC境界のバリデーション追加。
  - `src/optimization/milp/solver_adapter.py`
    - C15-C21 相当を営業所別フロー制約へ置換。
    - Grid→BESS フラグ (`allow_grid_to_bess`) を制約化。
    - O2 を実充電源ベース（Grid/BESS/c Curtail penalty）へ変更。
    - 解から営業所フロー時系列と source 付き `charging_slots` を復元して `AssignmentPlan` に出力。
  - `src/optimization/common/evaluator.py`
    - 仮計上→充電時FIFO上書きの台帳評価を追加。
    - `electricity_cost_final` / `electricity_cost_provisional_leftover` / `grid_purchase_cost` などを `CostBreakdown` に追加。
    - BESS/PV 資産費（日割）計算と `total_cost_with_assets` 追加。
  - `src/optimization/common/builder.py`
    - シナリオから `depot_energy_assets` を canonical problem へ橋渡し。

- **補助スクリプト追加**:
  - `scripts/build_pv_profiles.py`（Solcast風 CSV から営業所別 slot kWh 作成）
  - `scripts/build_depot_energy_case.py`（Case JSON 雛形生成）

- **ドキュメント更新**:
  - `docs/constant/implementation_status.md` に C22-C27 / O2 実充電源化 を追記。
  - `docs/constant/formulation.md` に B案追補（PV→BESS→Bus, Grid→BESSフラグ）を追記。

- **テスト**:
  - 追加: `tests/test_depot_energy_asset_schema.py`
  - 追加: `tests/test_evaluator_provisional_overwrite.py`
  - 回帰実行:
    - `pytest tests/test_depot_energy_asset_schema.py tests/test_evaluator_provisional_overwrite.py tests/test_bev_energy_accounting.py tests/test_objective_modes.py -q`
    - 結果: `10 passed`

### [DEV-2026-03-24] EV電力コストを「仮計算→充電実績上書き」に変更

- **背景**:
  - BEVが走行していても充電が発生しないケースで、日次報告の電力コスト解釈が分かりにくかった。
  - 充電が発生した場合は、走行時刻ではなく「実際に充電した時刻帯のTOU単価」で評価したい要件がある。

- **対応**:
  - `src/simulator.py` にて、電力コストを二段階で算出する方式へ変更。
    - 1) 走行電力量ベースの仮コストを常時計算 (`provisional_*`)
    - 2) 充電電力量が存在する場合は、充電時刻TOUで再計算した実コスト (`charged_*`) で上書き
  - 採用された計算根拠を `energy_cost_basis` (`provisional_drive` / `charged_energy_override`) として保持。
  - `src/result_exporter.py` の `summary.json` / KPI系JSONに、仮値・実値・採用basisを出力する項目を追加。

- **検証**:
  - `tests/test_bev_energy_accounting.py` に充電実績あり時の上書きテストを追加。
  - `python -m pytest tests/test_bev_energy_accounting.py -q` で `3 passed` を確認。

### [DEV-2026-03-22] Tokyu Bus の route-scoped trip 生成を追加し、21万件 overcount の代替データを分離

- **問題**:
  - `data/catalog-fast/raw/bus_timetable.json` / `busstop_pole_timetable.json` は ODPT top-level 取得の 1000件打ち切り状態で、`catalog-fast` 正規化データ単体では全量 trip を復元できなかった。
  - 一方で既存 `data/built/tokyu_full/trips.parquet` は GTFS family 展開起点の重複を含み、`tripCount` 合計が約 210,704 件まで膨らんでいた。
  - そのまま route 単位選択に使うと、Quick Setup / Prepare / 最適化の対象 trip 数が実運用とかけ離れる。

- **対応**:
  - `scripts/build_tokyu_bus_data.py` を追加し、`data/tokyubus/canonical/<snapshot>/` の完全 snapshot から `data/catalog-fast/tokyu_bus_data/` を生成できるようにした。
  - 出力は global JSONL に加えて route-scoped JSONL を持つ:
    - `route_trips/<route_id>.jsonl`
    - `route_stop_times/<route_id>.jsonl`
    - `route_stop_timetables/<route_id>.jsonl`
  - `route_index.json` / `family_index.json` / `summary.json` も生成し、将来 route 単位ロードへ切り替えやすい補助メタデータを追加した。
  - 再生成時に route-scoped ディレクトリが追記で二重化しないよう、出力ディレクトリ全体を clean してから rebuild するようにした。
  - `src/tokyu_bus_data.py` を追加し、`tokyu_bus_data` から route 別 trip / stop_times / stop timetables / day type 集計を読む補助ローダーを実装した。
  - 既存システムの参照元はこの時点では変更せず、別 agent による `data/catalog-fast` 修正と独立に比較できる状態を維持した。

- **実データ生成結果**:
  - `python scripts/build_tokyu_bus_data.py`
    - source snapshot: `data/tokyubus/canonical/20260311T044200Z`
    - generated counts: `routes=764`, `routesWithTrips=757`, `families=184`, `stops=3084`, `trips=33360`, `stopTimes=583165`
  - route 側 `tripCount` 合計も `33360` で一致し、route file 数は `764` を確認した。
  - 今回は既存参照元維持のため `data/built/tokyu_full` は再生成していない。

- **検証**:
  - `tests/test_tokyu_bus_data.py` を追加し、route-scoped 生成・再実行時の非重複・補助ローダー読込を固定した。
  - `PYTHONPATH=C:\\master-course pytest tests/test_tokyu_bus_data.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py -q`
    で `10 passed` を確認。
  - `.gitignore` に `data/catalog-fast/tokyu_bus_data/` を追加し、生成キャッシュが GitHub に同期されないようにした。
  - 既存参照元維持のため、`src/runtime_scope.py` / `bff/store/trip_store.py` / `bff/services/run_preparation.py` 側でも `trip_id` の `__vN` 重複除外が効くことを追加テストで固定した。
  - `src/tokyu_bus_data.py` / `scripts/build_tokyu_bus_data.py` にも同じ `__vN` 除外を追加し、代替 route-scoped データ経路でも重複 trip が混入しないようにした。

### [DEV-2026-03-22] Gurobi import の誤検知を緩和し、Windows 実行時の runtime bootstrap を追加

- **問題**:
  - `mode_milp_only` 実行時に `solver_result.infeasibility_info = "Gurobi が必要です"` で落ちるケースがあり、`gurobipy` / ライセンス自体は shell から正常でも、BFF 実行時だけ誤って unavailable 扱いになることがあった。
  - `src/model_factory.py` に solver 構築前の不要な `import gurobipy` があり、ここで失敗すると `src.milp_model.build_milp_model()` 側の retry に到達しなかった。

- **対応**:
  - `src/model_factory.py` の不要な `import gurobipy` を削除し、Gurobi import は `src.milp_model.build_milp_model()` 側に一本化した。
  - `src/milp_model.py` に runtime bootstrap を追加し、Windows では `GUROBI_HOME` 候補配下の `bin` を `PATH` / `os.add_dll_directory()` に補完し、`GRB_LICENSE_FILE` も既定候補から自動解決するようにした。
  - さらに `site.getsitepackages()` / `getusersitepackages()` / `sys.prefix` 由来の `site-packages` を solve 時に再探索して `sys.path` へ補完し、`run_app.py` 経由で `No module named 'gurobipy'` になるケースも潰した。
  - `src/pipeline/solve.py` は solver 例外時に例外クラス名を含めて記録するようにし、将来 `GUROBI_UNAVAILABLE` が出ても原因追跡しやすくした。

- **検証**:
  - shell から `gurobipy 13.0.1` import と簡易モデル optimize が通ることを確認した。
  - 弦巻 `WEEKDAY` 実データでも BFF と同じ ProblemData 経路から solver 実行に入り、`GUROBI_UNAVAILABLE` ではなく `TIME_LIMIT` まで進むことを確認した。
  - `tests/test_model_factory_gurobi_import.py` を追加し、`build_model_by_mode()` が直接 `gurobipy` import に依存しないこと、および solve 時の `site-packages` 補完が効くことを固定した。

### [DEV-2026-03-22] Quick Setup が全 route を誤表示し、Prepare が `tripCount=0` になりやすい問題を修正

- **問題**:
  - `tools/scenario_backup_tk.py` の `load_quick_setup()` が `GET /quick-setup` で返した depot-scoped route 一覧を捨てて、
    `GET /routes` の全件一覧で上書きしていた。
  - `bff/store/scenario_store.py` の `candidateRouteIds` が full-matrix `depot_route_permissions` を使っており、
    営業所選択後でも全 route が候補に残りやすかった。
  - その結果、UI では選べるが `trips.parquet` と link していない route を既定選択しやすく、
    Prepare が `tripCount=0` になっていた。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - Quick Setup 読込時に `/quick-setup` の route payload をそのまま使うよう修正し、
      global route 一覧で上書きしないようにした。
    - backend から返る `availableDayTypes` で day type 候補を同期し、
      link 済み route が 0 件のときはログで明示するようにした。
    - Prepare 未完了メッセージも `route / day type / timetable linkage` を確認する文面へ更新した。
  - `bff/store/scenario_store.py`
    - `candidateRouteIds` / `effectiveRouteIds` は selected depot 配下の route を基準に計算するよう修正し、
      full-matrix permission で候補を拡張しないようにした。
  - `bff/routers/scenarios.py`, `bff/services/simulation_builder.py`, `bff/services/route_linking.py`
    - `trips.parquet` の route link 数を読み、Quick Setup の `tripCount` と既定選択を trip-linked subset に揃えた。
    - builder 側も未リンク route を自動採用しないようにし、false positive な route 選択を避けるようにした。

- **検証**:
  - `tests/test_quick_setup_route_selection.py`
    - selected depot assignment で route list が絞られる回帰
    - Quick Setup payload が trip-linked route だけを既定選択する回帰
    を追加。
  - `tests/test_scenario_store_dispatch_scope_overlay.py`
    - full-matrix permission が candidate route を全件化しない回帰
    を追加。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `28 passed` を確認。

### [DEV-2026-03-22] Quick Setup の路線選択を系統単位 UI に変更し、variant 個別除外を保持

- **問題**:
  - `tools/scenario_backup_tk.py` の Quick Setup 路線一覧は営業所配下に raw route をフラット表示しており、
    同じ系統番号でも本線・区間便・入出庫便の関係が見えにくかった。
  - family 単位でまとめて見たい一方、将来的には特定シナリオで「入出庫便だけ外す」「区間便だけ外す」を保存したかった。
  - `PUT /quick-setup` は `selectedRouteIds` をそのまま `includeRouteIds` へ入れていたため、
    `refine` モードでは営業所配下の route が再び全部有効になりやすく、
    個別 route の除外が保持されにくかった。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - 営業所配下の route を `routeFamilyCode` 単位で折りたたみ表示する family grouping を追加。
    - family header は NFKC 正規化で系統番号の数字を半角表示。
    - family header のチェックで系統内 variant を一括選択/解除、展開後は raw variant を個別選択/解除できるようにした。
    - `include` モードで読み込んだ初期選択は、同一 family の route をまとめて既定選択へ展開するようにした。
  - `bff/routers/scenarios.py`
    - Quick Setup payload の `dispatchScope` に `routeSelectionMode` を追加。
    - `update_quick_setup()` は `selectedRouteIds` を `refine + excludeRouteIds` へ変換する helper を使うよう変更し、
      営業所の既定 family 全選択を維持しながら、個別 variant の除外を保存できるようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py`
    - half-width family code 展開
    - family grouping
    を追加。
  - `tests/test_quick_setup_route_selection.py`
    - unchecked route が `excludeRouteIds` に落ちる回帰
    - selected depot 外の route が `includeRouteIds` として保持される回帰
    を追加。
  - `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_quick_setup_route_selection.py tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `28 passed` を確認。

### [DEV-2026-03-22] route family を dispatch / Prepare / 最適化の terminal deadhead 補完へ反映

- **問題**:
  - route family 派生情報は route DTO には載っていたが、実行系では主に表示メタデータ扱いで、
    上り下り・本線・区間便・入出庫便の接続可否や回送候補生成に十分反映されていなかった。
  - さらに dispatch の `Trip` は `origin` / `destination` に stop 名を持ち、
    `deadhead_rules` は `from_stop` / `to_stop` として stop_id を持っていたため、
    明示 deadhead rule も一致しにくかった。

- **対応**:
  - `src/route_family_runtime.py` を追加し、
    detailed variant 正規化（`main_outbound`, `main_inbound`, `depot_out`, `depot_in` など）と
    same-family terminal stop の座標ベース deadhead 補完を共通化した。
  - `src/dispatch/models.py`, `src/data_schema.py`
    - `Trip` / `Task` に `origin_stop_id`, `destination_stop_id` を追加。
  - `src/dispatch/feasibility.py`
    - 接続判定は stop 名より stop_id を優先して参照するよう変更。
  - `bff/routers/graph.py`, `bff/mappers/scenario_to_problemdata.py`,
    `src/optimization/common/builder.py`
    - same-family terminal deadhead 補完を dispatch / Prepare / optimization builder 全経路へ適用。
    - route family / variant 情報を Trip/Task に詳細値のまま保持するよう修正。
  - `src/dispatch/problemdata_adapter.py`
    - `TravelConnection.deadhead_distance_km` に推定 deadhead 距離を載せるよう変更。
  - `bff/routers/master_data.py`, `bff/routers/scenarios.py`, `tools/scenario_backup_tk.py`
    - variant 正規化の collapse をやめ、manual label / API 応答でも detailed variant を保持するよう修正。
  - `src/tokyu_shard_loader.py`
    - dispatch trip rows に `origin_stop_id` / `destination_stop_id` を残すよう修正。

- **検証**:
  - `tests/test_route_family_deadhead_inference.py` を追加。
    - detailed variant 正規化
    - Prepare 経由の same-family terminal deadhead 補完
    - graph context での stop_id ベース接続
    を回帰化した。
  - `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_scenario_backup_tk_dataset_options.py -q`
    で `24 passed` を確認。

### [DEV-2026-03-22] `python run_app.py` 起動直後の Tk callback crash 修正

- **問題**:
  - `tools/scenario_backup_tk.py` は scenario 一覧更新直後に `on_scenario_changed()` を呼んでいたが、
    車両・テンプレート管理ウィンドウをまだ開いていない状態でも
    `refresh_vehicles()` / `refresh_templates()` を実行していた。
  - そのため `fleet_depot_var` / `template_tree` 未生成のままアクセスし、
    `AttributeError` で Tk callback が繰り返し落ちていた。
  - さらに background thread の完了通知が root close 後に `root.after()` へ戻ると、
    `RuntimeError: main thread is not in main loop` が出る経路があった。

- **対応**:
  - `tools/scenario_backup_tk.py`
    - fleet/template 関連 widget を `None` 初期化し、
      `_fleet_window_ready()` / `_vehicle_panel_ready()` / `_template_panel_ready()` を追加。
    - `on_scenario_changed()` は fleet window が開いている場合だけ
      `refresh_vehicles()` / `refresh_templates()` を呼ぶよう修正。
    - `refresh_vehicles()` / `refresh_templates()` の実行前後で
      widget 生存確認を行い、遅延 callback でも destroyed widget に触れないよう修正。
    - fleet window close 時に widget 参照をリセットする `WM_DELETE_WINDOW` ハンドラを追加。
    - プログラム起動直後の自動 scenario 選択では `messagebox.showinfo()` を出さないようにした。
    - `run_bg()` の UI 戻しを `_queue_on_ui_thread()` 経由に変更し、
      root close 後の `after()` 失敗を握りつぶすようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py` に
    fleet window 未生成時の `refresh_*()` / `on_scenario_changed()` が no-op で落ちない回帰を追加。
  - 同テストに `_queue_on_ui_thread()` の closed root / broken after 回帰を追加。
  - `python run_app.py` 起動時に `fleet_depot_var` / `template_tree` の `AttributeError` が出ないことを確認。

### [DEV-2026-03-22] Quick Setup の路線一覧を catalog-fast 優先へ変更

- **問題**:
  - `build_dataset_bootstrap("tokyu_full")` は `routes.parquet` と trip-backed route ids を基準に route inventory を作っており、
    Quick Setup の路線一覧が 21 路線程度に縮んでいた。
  - 一方で `data/catalog-fast/normalized/routes.jsonl` には 764 route pattern があり、
    UI ではこの inventory を常時見られる必要があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - `data/catalog-fast/normalized/routes.jsonl` を読む `_read_jsonl_rows()` /
      `_load_catalog_fast_routes()` を追加。
    - dataset bootstrap の route inventory は catalog-fast normalized routes を優先し、
      `dispatch_scope.routeSelection.includeRouteIds` / `scenario_overlay.route_ids` は
      trip-backed subset のみに絞るようにした。
    - これにより Quick Setup は catalog-fast 全 route を表示しつつ、
      初期選択は現行 timetable/trip が存在する route に限定される。
  - `bff/services/master_defaults.py`, `bff/store/scenario_store.py`
    - 既存 scenario の runtime alignment 判定を拡張し、
      現在の route/depot master が preload runtime master の proper subset の場合も自動補正するようにした。
  - `README.md`
    - 路線一覧は `data/catalog-fast/normalized/routes.jsonl` 優先であること、
      一覧件数と初期選択件数が一致しない場合があることを追記。

- **検証**:
  - `build_dataset_bootstrap("tokyu_full")` が `routes > selectedRouteIds` を返すことを確認。
  - `tests/test_research_dataset_bootstrap_alignment.py` に
    catalog-fast route inventory 回帰を追加。
  - `tests/test_scenario_store_dispatch_scope_overlay.py` に
    runtime master superset 差分で alignment が必要になるケースを追加。

### [DEV-2026-03-22] Quick Setup の営業所一覧が一部しか出ない問題を修正

- **問題**:
  - `build_dataset_bootstrap("tokyu_full")` が trip-backed route 文脈に合わせて `depots` 自体を削っており、
    Quick Setup の営業所一覧が `ebara / aobadai / nijigaoka` など一部しか出なくなっていた。
  - ただし実データの seed 定義では `tokyu_full` は 12 営業所を持っており、
    UI で営業所管理や選択確認をするには一覧自体は全件見える必要があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - bootstrap の `depots` は dataset 定義どおり保持し、
      route 文脈で絞った depot 集合は `dispatch_scope.depotSelection.depotIds` /
      `scenario_overlay.depot_ids` の既定選択だけに使うよう修正。
  - `bff/services/master_defaults.py`
    - stale scenario 補正時の `valid_depot_ids` を
      bootstrap の `dispatch_scope.depotSelection.depotIds` 優先に変更し、
      表示対象 depot は広く保ちつつ、実行不能な旧選択 depot は引き続き自動解除されるようにした。
  - `README.md`
    - Quick Setup の営業所一覧は全営業所を表示し、
      `routeCount=0` の営業所は runtime で route 未展開であることを追記。

- **検証**:
  - `build_dataset_bootstrap("tokyu_full")` で `depots` が dataset 定義の全営業所を返し、
    `dispatch_scope.depotSelection.depotIds` はその部分集合になることを確認。
  - `tests/test_research_dataset_bootstrap_alignment.py` に営業所表示回帰を追加。
  - `tests/test_master_defaults_runtime_repair.py` に
    「表示対象 depot は残すが stale selection は解除される」ケースを追加。

### [DEV-2026-03-21] README 使用方法更新と Tk dataset 候補の runtime-ready 化

- **問題**:
  - `README.md` の早見表が下位章の並びと 1 対 1 で対応しておらず、使用方法の参照導線が実装現況とずれていた。
  - README 内に `Quick Setup 保存 -> scenario_overlay に保存` とある箇所が残っており、
    実装済みの `dispatch_scope` 同期保存と食い違っていた。
  - `tools/scenario_backup_tk.py` の dataset 候補は `/api/app/datasets` の全件をそのまま表示しており、
    runtime 未整備 dataset をユーザーが新規 scenario に選べてしまっていた。

- **対応**:
  - `README.md`
    - 早見表を「要約 + 1章〜11章」の各節対応に更新。
    - `4.4 初回接続時の使い方` を追加し、`接続確認`、dataset 候補、Quick Setup 読込、
      stale scenario 補正後の選び直し手順を明記。
    - Quick Setup 保存先を `dispatch_scope / scenario_overlay` の同期保存に修正。
    - データセット配置の説明を `data/built/{dataset_id}/` 基準へ更新し、
      既定 runtime dataset が `tokyu_full` であることを追記。
    - API 導線に `GET /api/app/datasets` と `GET /api/app/data-status` を追加。
  - `tools/scenario_backup_tk.py`
    - `/api/app/datasets` の `runtimeReady` / `builtReady` / `shardReady` を見て、
      runtime 実行可能な dataset を優先表示するよう修正。
    - runtime-ready dataset が 1 件もない場合だけ全候補へ fallback するようにした。
    - scenario 作成ログに requested / effective datasetId を表示し、
      backend の fallback を確認しやすくした。
    - Quick Setup 読込時に depot/route の総数と選択数をログへ表示するようにした。

- **検証**:
  - `tests/test_scenario_backup_tk_dataset_options.py` を追加し、
    `runtimeReady` 優先と全候補 fallback の 2 ケースを確認できるようにした。
  - README の記述が 2026-03-21 時点の runtime 補正挙動と一致することを目視確認。

### [DEV-2026-03-21] Prepared実行 timeout の原因修正（simulation job submit の自己デッドロック）

- **問題**:
  - `POST /api/scenarios/{id}/simulation/run` が `job_id` を返す前に長時間停止し、
    Tk の `Prepared実行` が timeout していた。
  - `bff/routers/simulation.py` の `_submit_simulation_job()` は
    `_SIMULATION_FUTURE_LOCK` を保持したまま `_get_simulation_executor()` を呼び、
    `threading.Lock` の自己再取得でデッドロックしていた。
  - prepared run 前の再検証が `get_scenario_document()` を読んでいたため、
    heavy artifact 差分で `prepared_input_id` hash が不安定になりやすく、
    前段処理も不要に重かった。
  - `tools/scenario_backup_tk.py` の `/simulation/run` は明示 timeout 未設定で、
    既定 45 秒待ちに依存していた。

- **対応**:
  - `bff/routers/simulation.py`
    - `_SIMULATION_FUTURE_LOCK` を `threading.RLock` へ変更し、job submit の自己デッドロックを解消。
    - simulation executor に `BFF_SIM_EXECUTOR` を追加し、
      Windows 既定を `thread` モードへ変更。
    - `run_prepared_simulation()` / `run_simulation()` の prepared validation を
      `get_scenario_document_shallow()` 基準へ変更。
  - `bff/services/simulation_builder.py`
    - `apply_builder_configuration()` を shallow load 基準に変更し、
      prepare 時に timetable / graph / result artifact を読まないようにした。
  - `bff/routers/optimization.py`
    - `run_optimization()` / `reoptimize()` でも
      `get_or_build_run_preparation()` 呼び出し前に shallow doc を使うよう統一した。
  - `bff/services/run_preparation.py`
    - `prepared_input_id` hash の volatile key に
      `timetable_rows` / `stop_timetables` / `trips` / `graph` / `blocks` / `duties` /
      `dispatch_plan` / `simulation_result` / `optimization_result` / `meta` / `stats` / `refs`
      を追加し、shallow/full load 差分で hash が揺れないようにした。
  - `tools/scenario_backup_tk.py`
    - `/simulation/run` の client timeout を `180` 秒へ明示した。

- **検証**:
  - ローカル実測で `_submit_simulation_job` は `0.001s` で返ることを確認。
  - `run_prepared_simulation()` は `job_id` を約 `1.5s` で返すことを確認。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py -q`
    で `4 passed` を確認。

### [DEV-2026-03-21] 最適化/Prepare の front-run mismatch 修正（stale dataset bootstrap + dispatch_scope 優先）

- **問題**:
  - `tokyu_dispatch_ready` はこの clone では runtime 用 `trips.parquet` を持たず、scenario bootstrap が seed-only (`44 routes / 0 trips`) になっていた。
  - その状態で作られた既存 scenario は、フロントで選べる route/depot と runtime 実行時の built dataset (`tokyu_full`) が食い違い、Prepare/最適化が `trip_count=0` になりやすかった。
  - さらに `src/runtime_scope.py` は `dispatch_scope` より `scenario_overlay.route_ids / depot_ids` を優先していたため、Quick Setup 保存後の route 選択が実行時に無視される条件があった。

- **対応**:
  - `src/research_dataset_loader.py`
    - `build_dataset_bootstrap()` を修正し、要求 dataset が runtime 未整備で trip-backed data を返せない場合は、
      `tokyu_full` へ自動フォールバックするようにした。
    - `feed_context.requestedDatasetId` / `dataset_status.fallbackDatasetId` を付与し、fallback 発生を追跡可能にした。
  - `bff/services/master_defaults.py`
    - preloaded master data の `datasetId` を bootstrap の実効 dataset から返すよう修正。
    - `repair_missing_master_data()` を拡張し、runtime に存在しない stale route/depot master を
      実効 dataset の master へリベースしつつ、solver config などの scenario overlay は保持するようにした。
  - `bff/store/scenario_store.py`
    - `ensure_runtime_master_data()` を追加し、既存 scenario の stale master を必要時に永続補正できるようにした。
    - `set_dispatch_scope()` で `scenario_overlay.depot_ids / route_ids` も同期し、
      実行時 scope と UI 保存状態が乖離しないようにした。
  - `src/runtime_scope.py`
    - `resolve_scope()` を修正し、`scenario_overlay` より `dispatch_scope` の選択 route/depot を優先するようにした。
  - `bff/routers/scenarios.py`, `bff/routers/master_data.py`, `bff/routers/simulation.py`, `bff/routers/optimization.py`
    - editor bootstrap / quick setup / master-data read / prepare / simulation / optimization の入口で
      `ensure_runtime_master_data()` を通すようにし、フロントから stale master を見えないようにした。

- **効果**:
  - 新規 scenario 作成時に runtime 未整備 dataset を選んでも、実行可能な runtime master に揃う。
  - 既存 stale scenario を開いた際も、フロントが runtime に存在しない route/depot を出さなくなる。
  - Quick Setup 保存後の route/depot 選択が Prepare / Prepared実行 / 最適化にそのまま反映される。

- **検証**:
  - `build_dataset_bootstrap("tokyu_dispatch_ready")` が
    `feed_context.datasetId="tokyu_full"`, `routes=21`, `depots=3`, `trips=1000` を返すことを確認。
  - `get_preloaded_master_data("tokyu_dispatch_ready")` が `datasetId="tokyu_full"` を返すことを確認。
  - `python -m pytest tests/test_run_preparation_hash.py tests/test_simulation_executor_mode.py tests/test_runtime_scope_route_mapping.py tests/test_research_dataset_bootstrap_alignment.py tests/test_master_defaults_runtime_repair.py tests/test_scenario_store_dispatch_scope_overlay.py -q`
    で `12 passed` を確認。

### [DEV-2026-03-18] Prepare時の台数決定を営業所在庫ベースへ変更（Basic Parameters廃止）

- **背景課題**:
  - Tk の `Basic Parameters` で手入力した車両台数/充電器台数が、営業所に既に設定した実在庫と乖離しやすかった。
  - SOC関連が `Cost / Tariff` と別枠で分かれており、運用上の入力導線が分散していた。

- **対応**:
  - `bff/routers/simulation.py` の `PrepareSimulationSettingsBody` に以下を追加:
    - `soc_min`, `soc_max`
    - `use_selected_depot_vehicle_inventory`
    - `use_selected_depot_charger_inventory`
  - `bff/services/simulation_builder.py` を更新し、Prepare時に
    - 選択営業所の既存 `vehicles` を優先採用
    - 選択営業所の既存 `chargers`（無い場合は depot charger 設定から生成）を優先採用
    - BEVへ `initial_soc` と `soc_min/soc_max` を反映
    するロジックへ変更。
  - `tools/scenario_backup_tk.py` を更新し、
    - `Basic Parameters` セクションを削除
    - `Cost / Tariff Parameters` 内に `initial_soc`, `soc_min`, `soc_max` を移設
    - Prepare payload で営業所在庫利用フラグを常時 `true` 送信
    するよう変更。

- **効果**:
  - シミュレーション車両台数・充電器台数は「選択営業所に設定済みの実在庫」に自動一致。
  - 初期SOCとバッファSOC下限/上限を同一UI群で設定でき、運用が単純化。

- **追加対応（同日）**:
  - `POST /scenarios/{id}/simulation/prepare` のレスポンスに
    `vehicleCount` / `chargerCount` を追加。
  - Tk の Prepare完了ログに `Prepare採用台数: vehicles=... / chargers=...` を表示。
  - Tk 実行パネルに推奨手順（保存→Prepare→最適化）を明記し、Prepare未実行で最適化画面を開く際はログで注意を表示。

### [DEV-2026-03-18] BUILT_DATASET_REQUIRED の復旧導線を catalog-fast 基準へ更新

- **背景課題**:
  - 他PC clone 環境で `BUILT_DATASET_REQUIRED` が発生した際、`tokyu_core` 固定の案内だけでは復旧が遅れた。
  - 実際には `data/catalog-fast` に再構築元が存在するケースがある。

- **対応**:
  - `bff/dependencies.py` の 503メッセージを更新し、
    `data/catalog-fast` からの built 再生成コマンドを明示。
  - `tools/scenario_backup_tk.py` のエラーダイアログにも同コマンドを表示。
  - `README.md` の 503対処手順に catalog-fast 起点の再生成手順を追加。

- **効果**:
  - `tokyu_core` が未配置でも、`data/catalog-fast` があれば復旧手順を即実行できる。

- **追加対応（同日）**:
  - coreパッケージに `data-prep` / `tokyubus_gtfs` が同梱されていない環境で
    `python catalog_update_app.py refresh gtfs-pipeline --source-dir data/catalog-fast ...` が
    `ModuleNotFoundError: tokyubus_gtfs` で停止する問題を修正。
  - `catalog_update_app.py` に fallback を実装し、
    `data/catalog-fast/normalized/*.jsonl` から `data/built/{dataset}` の parquet + manifest を
    直接再生成できるようにした。
  - 実行結果に `pipeline_fallback=true` を付与して、fallback経路での成功を判別可能にした。
  - 既定datasetを `tokyu_core` 依存から外すため、
    `src/research_dataset_loader.py` と `bff/services/app_cache.py` の default を `tokyu_full` へ変更。

### [DEV-2026-03-18] Tkinter UI/UX 改善 + Tk/BFF 不整合の解消

- **背景課題**:
  - Tkで新規シナリオ作成時に `POST /api/scenarios` が 404 となるケースがあり、実体は datasetId 不一致由来だった。
  - タグ付与アプリで見える路線数に対し、Tkの路線表示が欠けるケースがあった（`quick-setup` の routeLimit 依存）。
  - 車両管理、営業所充電器設定、ソルバー設定が分散し、操作導線が重かった。

- **対応**:
  - `tools/scenario_backup_tk.py` で datasetId を `/api/app/datasets` 候補選択化。
  - 新規シナリオ作成時の既定datasetを `tokyu_full`（東急バス全体）優先へ変更。
  - シナリオ作成エラー表示を改善し、dataset候補を提示。
  - 路線表示を `/api/scenarios/{id}/routes` 優先に変更し、欠落率を低減。
  - 営業所/路線選択UIを営業所折りたたみ + 実Checkbuttonへ置換。
  - メインに `営業所別車両管理` ボタンを追加し、専用画面で営業所充電器設定を編集可能化。
  - スコープの `day_type`（運行種別）をプルダウン選択へ変更。
  - 右側車両管理の営業所選択・複製先営業所をプルダウン選択へ変更。
  - `詳細設定画面を開く` を追加し、旧 Advanced 設定とソルバー設定を別画面へ集約。
  - 設定画面でソルバーモード別にパラメータ表示を切替。
  - 車両/テンプレートの新規追加は専用ダイアログ（別画面）へ分離。
  - テンプレート作成時に「作成後に営業所へ何台追加するか」を同ダイアログで指定可能化。
  - 車両編集フォームとテンプレート編集フォームを日本語ラベル化。
  - 車両編集・テンプレート編集で EV/ICE に応じて該当パラメータのみ表示。
  - シナリオ選択時に完了メッセージを表示。
  - 画面上部に `シナリオ設定を保存` ボタンを追加し、編集内容の保存導線を明確化。
  - Prepare / Prepared / 最適化の開始時メッセージを追加。
  - 最適化実行は専用モニター画面へ遷移し、進捗%・ステータス・PowerShell風ログを表示。
  - `シミュレーション実行(legacy)` ボタンを通常運用画面から非表示化。
  - 最適化設定に `終了まで待つ` オプションを追加（長時間タイムリミットを適用）。
  - 最適化設定に `dispatch再構築（重い）` オプションを追加し、軽量起動を選択可能化。
  - 最適化開始APIのクライアント側タイムアウトを延長し、開始時タイムアウトを低減。
  - `PUT /quick-setup` 保存時、Windowsのファイルロックにより rename が失敗するケースに対し、
    `bff/store/scenario_store.py` に WinError 5/32 用の非原子的フォールバック保存を追加。
  - 他PC clone 環境での `simulation/prepare`・`run-optimization` の 503 は
    `BUILT_DATASET_REQUIRED` が主因になり得るため、READMEに `built_ready` 確認手順を追記。
  - READMEに Gurobi (MILP) の最小動作確認コマンドを追記。

- **確認**:
  - `python -m py_compile tools/scenario_backup_tk.py` で構文エラーなし。

### [DEV-2026-03-18] Timetable整合監査の自動化（第三者追試向け）

- **背景課題**:
  - 教員レビュー用に、`timetable_rows` 件数・`unserved_trip_ids` 件数・採用便の departure/arrival 一致率を実測値で提示する必要があった。
  - 既存のログ確認だけでは、入力ファイルと結果ファイルの突合根拠が散在していた。

- **対応**:
  - `scripts/audit_timetable_alignment.py` を追加し、prepared input と optimization result を突合する監査を自動化。
  - JSON/CSV/Markdown の3形式で監査成果物を出力。
  - 追加指標として `checked_coverage_rate` と `day_tag_match` を導入し、曜日不整合ケースを品質判定から除外可能にした。
  - 提出用文書 `docs/reproduction/timetable_alignment_audit_20260318.md` を作成。

- **出力先**:
  - `outputs/audit/bbe1e1bd/timetable_alignment_audit.{json,csv,md}`（WEEKDAY）
  - `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.{json,csv,md}`（SAT比較）

- **主結果（WEEKDAY）**:
  - `timetable_rows_count = 1010`
  - `unserved_trip_count = 0`
  - `departure_arrival_match_rate = 100.0%`
  - `checked_coverage_rate = 100.0%`
  - `day_tag_match = true`

- **注意（SAT比較）**:
  - `day_tag_match = false`（prepared=Weekday, result=Saturday）
  - このため SAT 側の一致率は品質判定に使わず、入力不整合検知の証跡として扱う。

### [DEV-2026-03-15] Simulation Input Builder 化の第1段（lite bootstrap + depot-scoped 権限 + invalidate 範囲縮小）

- **背景課題**:
  - Planning 画面の初期ロードが `editor-bootstrap` 前提で広すぎ、summary-first 設計と乖離していた。
  - DepotRouteMatrix が depot 単位 UI にもかかわらず、全 depots / 全 route-families / 全 permissions を取得していた。
  - 営業所・車両・permission 更新で dispatch/graph/simulation/optimization まで即 invalidate しており、
    微小編集でも待ち時間が増える構造だった。

- **対応（Backend）**:
  - `bff/routers/scenarios.py`
    - `GET /scenarios/{id}/editor-bootstrap-lite` を追加。
    - 共通 builder `_build_editor_bootstrap_payload()` を導入し、
      - full: `editor-bootstrap`
      - lite: `editor-bootstrap-lite`
      を同じ整形ロジックで返す構成に変更。
    - lite では `routes`, `vehicleTemplates`, `depotRouteIndex`, `availableDayTypes`, `builderDefaults` を返さず、
      `scenario + dispatchScope + depots + depotRouteSummary` 中心の summary payload に限定。
  - `bff/routers/master_data.py`
    - `GET /scenarios/{id}/route-families` に `depotId` query を追加（depot-scoped route family 取得）。
    - `GET /scenarios/{id}/depots/{depotId}/route-family-permissions` を追加。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - 初期取得を `useEditorBootstrapLite()` へ切替。
  - `frontend/src/hooks/use-scenario.ts`, `frontend/src/api/scenario.ts`
    - `editor-bootstrap-lite` 用の query key / API client / hook を追加。
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - 全体取得をやめ、`depotId` スコープの
      - route families
      - depot route-family permissions
      のみ取得するよう変更。
  - `frontend/src/hooks/use-master-data.ts`, `frontend/src/api/master-data.ts`
    - `useRouteFamiliesScoped(...)` と depot-scoped permissions API を追加。
    - 既存 update mutation（depot/vehicle/route/permission/stop import 等）から
      `invalidateDispatchOutputs(...)` を除去し、即時の重い再同期を停止。

- **型更新**:
  - `frontend/src/types/domain.ts`
    - `EditorBootstrapLite` 型を追加。
  - `frontend/src/types/api.ts`, `frontend/src/types/index.ts`
    - `EditorBootstrapLiteResponse` を追加。

- **期待効果**:
  - Planning 初期表示時の payload と query 本数を削減。
  - 営業所タブの詳細操作が depot 単位に閉じ、全体取得を回避。
  - 微小な master 編集で dispatch/optimization 系キャッシュを揺らさないため、
    体感の待ち時間を大幅に減らす基盤を確立。

### [DEV-2026-03-15] Simulation Input Builder 化の第2段（Dispatch Scope を draft→保存に変更）

- **背景課題**:
  - Planning の「配車スコープ設定」がトグル変更のたびに即 `PATCH /dispatch-scope` を発行していた。
  - 微小編集でも network + invalidation が発生し、Builder 操作の連続性を損なっていた。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - Dispatch Scope を即時保存から **local draft + 明示保存** に変更。
    - トグルはローカル state (`scopeDraft`) のみ更新。
    - `保存` ボタン押下時のみ `useUpdateDispatchScope().mutate(...)` を実行。
    - `破棄` ボタンで bootstrap 起点値へ復元。
    - `未保存の変更あり` / `保存済み` 表示を追加。

- **関連改善**:
  - `frontend/src/hooks/use-master-data.ts`
    - `routeKeys.families` の key を `{ operator, depotId }` へ正規化。
  - `bff/routers/master_data.py` + `frontend/src/api/master-data.ts`
    - route family の depot filter (`depotId`) を利用する depot-scoped 流れに統一。

- **期待効果**:
  - スコープ調整中に不要な即時同期を発生させず、入力体験を builder 型に近づける。
  - 保存タイミングをユーザー主導にし、1操作ごとの待ち時間を抑制。

### [DEV-2026-03-15] Simulation Input Builder 化の第3段（Permission Matrix を draft→保存に変更）

- **背景課題**:
  - 営業所-路線許可 / 車両-路線許可の行列が、チェック1回ごとに即 mutation されていた。
  - 「行列調整中に毎回保存」が発生し、操作体験が重くなる要因だった。

- **対応（Frontend）**:
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - チェック操作を local draft に反映する方式へ変更。
    - `保存` で dirty family 分だけ一括送信。
    - `破棄` でサーバ状態へ復元。
  - `frontend/src/features/planning/VehicleRouteMatrix.tsx`
    - 同様に vehicle x routeFamily 行列を draft 方式へ変更。
    - dirty pair（vehicleId:routeFamilyId）単位で保存 payload を構成。

- **対応（API / Hook）**:
  - `bff/routers/master_data.py`
    - `GET /scenarios/{id}/depots/{depotId}/vehicle-route-family-permissions` 追加。
  - `frontend/src/api/master-data.ts`
    - depot-scoped vehicle-family permissions API client を追加。
  - `frontend/src/hooks/use-master-data.ts`
    - `useVehicleRouteFamilyPermissionsForDepot(...)` 追加。
  - `frontend/src/hooks/index.ts`
    - 上記 hook を export。

- **期待効果**:
  - permission matrix 編集中の即時同期を止め、入力の連続性を改善。
  - depot-scoped 取得で読み込み範囲を局所化し、タブ体感速度を改善。

### [DEV-2026-03-15] Simulation Input Builder 化の第4段（未保存変更の可視化と離脱ガード）

- **背景課題**:
  - scope / permission の draft 方式は導入済みだが、画面全体で「未保存状態」を横断把握しづらかった。
  - ページ離脱時に未保存編集が失われるリスクがあった。

- **対応（Frontend）**:
  - `frontend/src/stores/planning-draft-store.ts` を新規追加。
    - scenario 単位で以下の dirty flag を保持。
      - `scope`
      - `depotPermissions`
      - `vehiclePermissions`
    - `useHasPlanningDraftChanges(scenarioId)` を追加。
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - ページ上部に「未保存の変更があります」バナーを表示。
    - `beforeunload` で未保存時の離脱ガードを追加。
    - scope 保存/破棄で dirty flag を更新。
  - `frontend/src/features/planning/DepotRouteMatrix.tsx`
    - toggle/save/reset で `depotPermissions` dirty flag を更新。
  - `frontend/src/features/planning/VehicleRouteMatrix.tsx`
    - toggle/save/reset で `vehiclePermissions` dirty flag を更新。

- **期待効果**:
  - Builder 画面で draft が残っているかを常に把握できる。
  - 誤離脱による設定ロストを防止できる。

### [DEV-2026-03-15] Simulation Input Builder 化の第5段（DispatchScopePanel の draft-save 統一 + prepare 直前ガード）

- **背景課題**:
  - `DispatchScopePanel` は checkbox/select 変更ごとに `updateDispatchScope` を即時発火していた。
  - ScenarioOverview 側の prepare 実行時に Planning の未保存 draft を見ずに進められてしまう状態だった。

- **対応（Frontend）**:
  - `frontend/src/features/planning/DispatchScopePanel.tsx`
    - 即時 mutation を廃止し、panel 内 `scopeDraft` で編集。
    - `保存` / `破棄` ボタンを追加。
    - dirty 判定中は `planning-draft-store` の `scope` flag を更新。
    - route/family の candidate + include/exclude から、表示用 effective 集合を draft ベースで再計算。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - `useHasPlanningDraftChanges(scenarioId)` を参照。
    - 未保存 draft がある場合は prepare を無効化し、実行時も alert でブロック。

- **Drawer dirty 集約（可能な範囲）**:
  - `frontend/src/features/planning/DepotEditorDrawer.tsx`
    - 入力変更時に `depotEditor` dirty を立てる。
    - 保存/削除成功時に dirty を解除。
  - `frontend/src/features/planning/VehicleEditorDrawer.tsx`
    - 入力変更時に `vehicleEditor` dirty を立てる。
    - 保存/削除成功時に dirty を解除。
  - `frontend/src/stores/planning-draft-store.ts`
    - `depotEditor` / `vehicleEditor` フラグを追加。

- **期待効果**:
  - DispatchScopePanel でも Builder の「下書き→保存」方針を一貫適用。
  - 未保存入力のまま prepare へ進む事故を防止。
  - drawer 編集を含め、未保存状態を横断的に把握可能。

### [DEV-2026-03-15] Master tab の追加軽量化（不要 query 抑制 + summary API 呼び出し削減）

- **背景課題**:
  - backend 側の高速化後も、実ブラウザでは「depots / vehicles / routes」タブで体感遅延が残るケースがあった。
  - 初期表示や tab 遷移時に、一覧操作に不要な query が走る余地が残っていた。

- **対応（Frontend）**:
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - `useTimetableSummary` を削除。
    - Header の時刻表件数は `useScenario().stats.timetableRowCount` を使用。
    - これにより master tab 表示時の `/timetable/summary` 呼び出しを削減。
  - `frontend/src/hooks/use-master-data.ts`
    - `useVehicles` に `enabled` オプションを追加。
    - `useDepots/useVehicles/useRoutes/useStops` に `refetchOnWindowFocus: false` を設定し、
      フォーカス復帰時の再取得バーストを抑制。
  - `frontend/src/features/planning/VehicleTableNew.tsx`
    - 営業所未選択時は `useVehicles(..., { enabled: false })` で車両一覧 query を停止。
    - 「営業所を選択してから車両表示」の UX と fetch 条件を一致させた。
  - `frontend/src/pages/planning/MasterLeftPanel.tsx`
    - `activeTab` に応じて depots query を条件実行（stops タブでは読み込まない）。

- **検証**:
  - `npx eslint "src/pages/planning/MasterDataHeader.tsx" "src/hooks/use-master-data.ts" "src/pages/planning/MasterLeftPanel.tsx" "src/features/planning/VehicleTableNew.tsx"` → pass
  - `npm run build` (frontend) → pass

### [DEV-2026-03-15] Master Data の体感速度を改善（営業所編集の即時反映 + ルート一覧軽量化）

- **背景課題**:
  - 「営業所・車両・路線」画面で、営業所編集後の一覧反映が遅い。
  - Header / map 周辺で重い query が先に走り、初期表示と切り替えが重い。
  - `/scenarios/{id}/routes` が一覧用途に対して過剰な enrich 経路を通っていた。

- **対応（Backend）**:
  - `bff/store/scenario_store.py`
    - master-data 操作（depot/vehicle/route update 系）向けに `_save_master_only()` を追加。
      - master DB (`master_data.sqlite`) と slim meta のみ更新。
      - dispatch 無効化が必要な場合は artifact 側をクリアして整合を維持。
      - full `_save()` を回避し、編集応答を短縮。
    - `summarize_route_service_trip_counts()` を追加。
      - timetable sqlite から `route_id x service_id` 集計のみ取得（軽量）。
      - `list_routes()` に `stopCount` を付与。
  - `bff/store/trip_store.py`
    - `summarize_timetable_routes()` を追加（SQL GROUP BY 集計）。
  - `bff/routers/master_data.py`
    - `GET /depots`: `list_routes()` を depot ごとに N 回呼ばない構成へ変更（N+1 解消）。
    - `GET /routes`: 一覧専用の軽量 summary payload に変更。
      - route family 派生情報は保持。
      - `tripCount/serviceTypes/stopCount` は軽量集計で補完。
      - route detail (`GET /routes/{id}`) 側の link 詳細は維持。

- **対応（Frontend）**:
  - `frontend/src/hooks/use-master-data.ts`
    - `useDepots/useStops/useRoute` に `enabled` オプションを追加。
    - `useUpdateDepot` に optimistic update を追加。
      - 保存直後に depots list/detail を即時更新し、反映遅延を解消。
  - `frontend/src/features/planning/RouteMapPanel.tsx`
    - tab / view / selection 条件で query を遅延。
      - route 未選択時に route detail + stops を読まない。
      - depots/vehicles tab で route 系 query を読まない。
  - `frontend/src/pages/planning/MasterDataHeader.tsx`
    - route/stop 件数を `useScenario().stats` 参照に切替。
      - 起動時の `useRoutes/useStops` を除去し、ヘッダ描画を軽量化。
    - import progress/log を routes/stops タブ時のみ描画（depots/vehicles の不要描画を回避）。
  - `frontend/src/pages/planning/MasterDataPage.tsx`
    - planning tab の warm gate を外して即時描画に変更。
  - `frontend/src/features/planning/RouteTableNew.tsx`
    - 停留所数表示を `stopCount` 優先にし、一覧 API の軽量化に追従。
  - `frontend/src/types/domain.ts`
    - `Route.stopCount`, `Route.serviceTypes`, `Scenario.stats` を型定義に追加。

- **追加高速化（第二段）**:
  - `bff/services/master_defaults.py`
    - dataset bootstrap 補完処理に guard + cache を導入し、既に master が揃っている scenario で
      毎回重い bootstrap 再構築を走らせないよう改善。
  - `bff/store/master_data_store.py`
    - `load_master_collection()` / `save_master_collections()` を追加して collection 単位 I/O を可能化。
  - `bff/store/scenario_store.py`
    - `_save_master_subset()` を追加し、depot/vehicle/route 等の変更で必要 collection のみ更新。
    - `list_*` 系は master_data.sqlite の単一 collection 直接ロードを優先。
    - timetable route集計は row_artifacts fallback まで対応し、summary計算で full load を回避。
  - `bff/routers/scenarios.py`
    - `GET /app/context` の active scenario 名取得を軽量化（meta fallback）。

- **ローカル実測（代表シナリオ）**:
  - `_load_shallow()`:
    - 改善前: 約 4.0-4.5 秒
    - 改善後: 約 0.008 秒
  - `master_data.list_routes()`:
    - 改善後: 約 0.36 秒（136 routes）
  - `scenarios.get_editor_bootstrap()`:
    - 改善後: 約 0.019 秒
  - `scenarios.get_app_context()`:
    - 改善後: 約 0.010 秒

- **検証**:
  - `python -m pytest tests/test_bff_route_family.py tests/test_bff_scenario_store.py tests/test_architecture.py tests/test_performance_contracts.py -q`
    - 結果: `79 passed`
  - `npx eslint "frontend/src/hooks/use-master-data.ts" "frontend/src/pages/planning/MasterDataHeader.tsx" "frontend/src/features/planning/RouteMapPanel.tsx" "frontend/src/features/planning/RouteTableNew.tsx" "frontend/src/types/domain.ts"`
    - 結果: pass
  - `npm run build` (frontend)
    - 結果: pass

### [DEV-2026-03-15] Scenario 一覧で dataset 表示名と複数削除を追加

- **目的**:
  - `Tokyu Bus Research Cases` 画面で dataset ID だけでは判別しにくいため、
    人間向けの表示名を追加して選択しやすくする。
  - scenario 運用時に不要ケースをまとめて整理できるよう、複数同時削除を可能にする。

- **対応** (`frontend/src/pages/scenario/ScenarioListPage.tsx`):
  - Dataset カードに `datasetDisplayName` を導入。
    - 例: `tokyu_core` → `Tokyu Core (4 depots)`
    - 例: `tokyu_full` → `Tokyu Full (all depots)`
    - 生ID (`datasetId`) も副表示として残し、技術的識別子も確認可能にした。
  - Create 時の scenario 名も dataset ごとに自然なタイトルへ調整。
  - Scenario 一覧に選択チェックボックスを追加。
  - 上部に bulk action bar を追加:
    - `Select all`
    - `Clear selected`
    - `Delete selected`
  - 複数削除は `Promise.allSettled` で並列実行し、失敗IDのみ選択を維持して再試行しやすくした。

- **性能配慮**:
  - 選択状態は ID 配列 + `Set` (`useMemo`) で管理し、行単位の `includes` 連発を回避。
  - 複数削除はネットワークI/Oを並列化し、一覧再取得は最後に 1 回の invalidate のみ。
  - 追加した表示名マップは dataset 一覧から `useMemo` で計算。

### [DEV-2026-03-15] Scenario 一覧でシナリオ表示名編集と初期日本語化

- **要望反映**:
  - 「複数削除」だけでなく、Scenario 一覧で **シナリオ表示名を編集可能** にした。
  - `Tokyu Bus Research Cases` 画面の初期表示文言を日本語優先に変更。

- **対応**:
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 各 scenario 行に `表示名を編集` ボタンを追加。
    - 上部に rename editor を表示し、`scenarioApi.update(id, { name })` で保存。
    - 保存後は scenario query を invalidate して一覧へ即反映。
    - 入力が空のときは保存不可。
  - `frontend/src/i18n/index.ts`
    - 初期言語フォールバックを `ja` に変更（保存済み言語がない場合に日本語で起動）。
    - `fallbackLng` も `ja` に設定。
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 見出し/サブテキストを日本語化:
      - `東急バス研究ケース`
      - `Step 1: 事前に用意した Tokyu dataset を選択し、シナリオを作成または開きます。`

- **確認**:
  - `npx eslint "src/pages/scenario/ScenarioListPage.tsx" "src/i18n/index.ts"`
  - `npm run build`
  - いずれも成功。


### [DEV-2026-03-15] Scenario builder に ParamEditor 風クイック導線を統合（最適化実行まで短縮）

- **目的**:
  - シナリオ作成後、初見ユーザーでも `目黒営業所 -> 路線選択 -> prepare -> 最適化` まで迷わず到達できる導線を作る。
  - 既存 Step2 の詳細設定は保持しつつ、性能負荷を増やさない範囲で ParamEditor モックの要点だけを統合する。

- **対応**:
  - `frontend/src/features/planning/ScenarioQuickParamGuide.tsx` を新規追加。
    - 軽量なクイック設定カード（Solver/Object/TimeLimit/ALNS/MIPGap/Fleet/Charger/Demand）を実装。
    - `Balanced / Quick / Robust` のプリセットを追加し、`updateSettings` に patch 適用。
    - selected depot / route / trip の要約と、推定 fleet / charge capacity を同時表示。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - Step1 に `Top 3 by tripCount` 選択ボタンを追加（目黒3路線実行を即時化）。
    - Step2 上部に `ScenarioQuickParamGuide` を配置（詳細フォームは保持）。
    - Step3 に `最適化開始` ボタンを追加し、prepare 済み scope を使って
      `POST /scenarios/{id}/run-optimization` を直接起動する導線を追加。
    - simulation job と optimization job の両方を同画面で表示。
    - prepare後カードから `Optimization view` へのリンクを追加。
  - `frontend/src/features/planning/index.ts`
    - `ScenarioQuickParamGuide` の export を追加。

- **性能配慮**:
  - route 一覧は既存の `visibleRoutes`（summaryベース）を再利用し、追加 API fetch はなし。
  - Top3 選択は `useMemo` 内の既存配列ソートのみ（小規模 index データ対象）。
  - クイックガイドは controlled input + patch 更新のみで、重い計算や副作用は追加しない。


### [DEV-2026-03-15] run-optimization タイムアウトの原因を修正（最適化ジョブ投入の自己デッドロック）

- **問題**:
  - `POST /api/scenarios/{id}/run-optimization` 実行時、job を返す前に API 応答がタイムアウトする事象を確認。
  - 原因は `bff/routers/optimization.py` のロック構造で、
    `_submit_optimization_job()` が `_OPTIMIZATION_FUTURE_LOCK` を保持したまま
    `_get_optimization_executor()` を呼び、同じロックを再取得しようとして自己デッドロックしていた。

- **対応**:
  - `bff/routers/optimization.py`
    - `_OPTIMIZATION_FUTURE_LOCK` を `threading.Lock()` から `threading.RLock()` に変更。
    - 同一スレッドでの再入ロックを許可し、job submit 経路のブロッキングを解消。

- **テスト追加**:
  - `tests/test_bff_optimization_router.py`
    - `test_optimization_future_lock_is_reentrant`
      - 最適化ロックが再入可能ロックであることを確認。
    - `test_submit_optimization_job_does_not_deadlock_on_nested_lock`
      - `submit` を別スレッドで実行し、短時間で復帰することを確認して
        自己デッドロック再発を防止。

- **確認**:
  - `python -m pytest tests/test_bff_optimization_router.py tests/test_bff_simulation_builder.py tests/test_bff_scenario_store.py -q`
  - 結果: `33 passed`

### [DEV-2026-03-15] Simulation Builder の dispatch scope 初期同期を修正

- **問題**:
  - `ScenarioOverviewPage` の builder store は `includeShortTurn` / `includeDepotMoves` /
    `allowIntraDepotRouteSwap` / `allowInterDepotSwap` を固定初期値で持っていた。
  - 既存 scenario の `dispatch_scope` を編集しても、ページ再表示時に builder 側へ反映されず、
    UI表示と backend の scope が乖離する可能性があった。

- **対応**:
  - `frontend/src/stores/simulation-builder-store.ts`
    - `scopeFlagsFromBootstrap()` を追加。
    - `hydrateFromBootstrap()` で `bootstrap.dispatchScope` から以下の初期値を同期するよう修正。
      - `tripSelection.includeShortTurn`
      - `tripSelection.includeDepotMoves`
      - `allowIntraDepotRouteSwap`
      - `allowInterDepotSwap`

- **効果**:
  - シナリオ保存済み `dispatch_scope` を開いたときに、builder のトグル表示と prepare payload が
    scope 実態と一致する。

### [DEV-2026-03-15] Dispatch scope を source-of-truth とする UI/Backend 同期を追加整理

- **問題**:
  - `PUT /scenarios/{id}/dispatch-scope` で `allowIntraDepotRouteSwap` /
    `allowInterDepotSwap` が body schema に定義されておらず、UI から保存しても
    `scenario_store.set_dispatch_scope()` まで値が届かない。
  - builder 画面を開いたまま別画面で scope 更新した場合、同一 scenario 再hydrate時に
    scope フラグが store 側へ再同期されない。
  - `MasterPlanningPage` の tripSelection 更新は `includeDeadhead` を固定 `true` で送っており、
    scope の既存値を上書きしてしまう。

- **対応（scope source-of-truth）**:
  - `bff/routers/scenarios.py`
    - `UpdateDispatchScopeBody` に
      `allowIntraDepotRouteSwap`, `allowInterDepotSwap` を追加。
    - `body.model_dump(exclude_unset=True)` を使用し、未指定項目を不要上書きしない。
  - `bff/store/scenario_store.py`
    - `set_dispatch_scope()` の `next_scope` に swap フラグをマージする処理を追加。
  - `frontend/src/stores/simulation-builder-store.ts`
    - 同一 scenario の再hydrate時にも `dispatchScope` 由来フラグを再同期。
  - `frontend/src/pages/planning/MasterPlanningPage.tsx`
    - `includeDeadhead` を scope から読み取り、tripSelection patch で保持。

- **対応（state責務分離フェーズ1）**:
  - `frontend/src/stores/scenario-draft-store.ts` を新規追加。
    - scenario 別ドラフト state として `selectedDepotIdByScenario` を保持。
  - `frontend/src/features/planning/DepotListPanel.tsx` と
    `frontend/src/pages/planning/MasterPlanningPage.tsx` を
    `ui-store` 依存から `scenario-draft-store` 依存へ移行。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx` で
    builder の選択営業所を scenario draft へ同期。
  - `frontend/src/stores/ui-store.ts` から `selectedDepotId` を除去し、
    global UI state と scenario draft state の責務を分離。

- **テスト追加**:
  - `tests/test_bff_scenario_store.py`
    - `test_dispatch_scope_setter_persists_swap_flags` を追加。
  - `tests/test_bff_simulation_builder.py`
    - `test_prepare_keeps_existing_scope_flags_when_body_does_not_override` を追加。

### [DEV-2026-03-14] `.claude/worktrees/magical-elgamal` の残差分を main へ吸収

- **確認した状態**:
  - `claude/magical-elgamal` branch 自体は `main` と同一 commit で、
    worktree 側には未コミット差分だけが残っていた。
  - 差分の大半は既に main 側へ別経路で反映済みだったため、
    丸ごと checkout すると current main を後退させる恐れがあった。

- **吸収したもの**:
  - `frontend/src/pages/planning/SimulationBuilderPage.tsx`
    - dedicated route wrapper を main 側へ追加し、
      `/simulation-builder` の実体を明示した。
  - `scripts/simulation_profile_cli.py`
    - `_build_parser()` を追加し、CLI parser を個別テスト可能にした。
  - `tests/test_experiment_reports.py`
    - experiment report payload と simulation profile CLI parser の
      最小回帰テストを main 側へ追加した。
  - `README.md`
    - 上記 test の位置を追記。

- **吸収しなかったもの**:
  - `.claude/settings.local.json`
    - ローカル開発設定なので main には取り込まない。
  - worktree 内の旧 `simulation.py` / TS 型差分
    - main 側で既により新しい実装へ再整列済みのため、
      そのままは採用しなかった。

### [DEV-2026-03-14] Simulation builder / experiment logger の実装実態を再整列

- **確認した問題**:
  - 共有された完了報告と実ワークツリーに差分があり、専用 `SimulationBuilderPage` は存在しなかった。
  - simulation 側は `experiment_reports.py` があるにもかかわらず、
    `bff/routers/simulation.py` で実験ログ出力と取得 endpoint が未配線だった。
  - frontend builder defaults と TypeScript 型に
    `alnsIterations`, `randomSeed`, `experimentMethod`, `experimentNotes`
    が無く、backend に保存済みでも UI 側が保持できなかった。
  - `simulation_profile_cli show` は raw JSON をそのまま出すだけで、
    frontend fallback としては条件確認性が弱かった。
  - builder UI の TOU 表示は hour を `/2` しており、0-24 時間帯の表示として誤っていた。

- **対応**:
  - `bff/routers/scenarios.py`
    - builder defaults に `alnsIterations`, `randomSeed`,
      `experimentMethod`, `experimentNotes`, `startTime`,
      `planningHorizonHours` を追加。
  - `bff/routers/simulation.py`
    - simulation 完了時に `log_simulation_experiment()` を呼び、
      `simulation_result.experiment_report` と
      `simulation_audit.experiment_report` を保存するようにした。
    - `GET /api/scenarios/{id}/simulation/experiment-log` を追加。
    - simulation result に `vehicle_count_by_type`, `trip_count_by_type`,
      `trip_count_served` summary を付与した。
  - `bff/services/experiment_reports.py`
    - simulation report に BEV / ICE / total trip counts を含めるよう修正。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - 既存 builder UI を拡張し、
      mixed fleet 編集、TOU band add/remove、grid flat/sell、
      ALNS iterations、random seed、experiment method、
      experiment notes、start time、planning horizon を編集可能にした。
    - TOU 表示を 0-24 hour 表記に修正した。
  - `frontend/src/app/Router.tsx`, `frontend/src/features/layout/Sidebar.tsx`
    - `/scenarios/:id/simulation-builder` alias と
      「シミュレーション設定」サイドバー導線を追加。
  - `frontend/src/types/domain.ts`, `frontend/src/types/api.ts`,
    `frontend/src/stores/simulation-builder-store.ts`
    - 上記 builder パラメータの型・store hydrate を追加。
  - `scripts/simulation_profile_cli.py`
    - `show` を人間向け summary 表示へ変更し、
      depots / routes / fleet / charging / solver / costs / experiment を
      一目で確認できるようにした。
  - `README.md`
    - builder で編集できる条件、experiment logging、CLI fallback の実態を追記。

- **メモ**:
  - この worktree では専用新規 page を別実装するのではなく、
    既存 `ScenarioOverviewPage` を simulation builder 本体として拡張し、
    `simulation-builder` route alias を追加する方針で整えた。
  - full test / build はこのターンでは実施していない。ユーザー指示に合わせ、
    実装整合と説明資料の整備を優先した。

### [DEV-2026-03-14] frontend fallback 用 simulation profile CLI を追加

- **問題**:
  - main frontend が起動できない場合、営業所・路線・車両・料金・solver 条件を
    安全に差し替える手段が scenario JSON 直編集しか無かった。
  - 直編集対象が `dispatch_scope` / `scenario_overlay` / `simulation_config` に分散しており、
    手作業では壊しやすかった。
  - builder 内の charger 生成で `charger_power_kw=0` 分岐時に
    未定義 `template` を参照する latent bug があった。

- **対応**:
  - `bff/services/simulation_builder.py`
    - builder apply ロジックを router から切り出し、CLI からも共通利用可能にした。
    - `random_seed`, `alns_iterations`, `experiment_method`, `experiment_notes`
      を simulation profile から反映可能にした。
    - charger 生成の未定義参照 bug を解消した。
  - `scripts/simulation_profile_cli.py`
    - `export`, `show`, `apply` を追加。
    - export JSON に `_meta.depots`, `_meta.routes_by_depot`,
      `_meta.vehicle_templates` を埋め、frontend 不在でも選択可能にした。
  - `README.md`
    - fallback CLI の使い方を追記。

- **最小確認**:
  - `python -m py_compile ...` で関連 Python 変更の構文確認を実施。
  - `python -m scripts.simulation_profile_cli --help` を確認。
  - smoke として新規 scenario で `export -> JSON 編集 -> apply` を実行し、
    `experiment_method`, `experiment_notes`, `dispatch_scope` が保存されることを確認。

### [DEV-2026-03-14] Meguro 3-route shard runtime / Gurobi 実走確認と cost parameter surfaced

- **実施条件**:
  - depot: `meguro`
  - routes: `tokyu:meguro:さんまバス`, `tokyu:meguro:東98`, `tokyu:meguro:渋72`
  - runtime source: `tokyu_shards`
  - solver: Gurobi (`mode_milp_only`)
  - tariffs: `constant/input_template.json` 相当
    - TOU `00:00-08:00=18`, `08:00-22:00=32`, `22:00-24:00=20`
    - diesel `150 JPY/L`
    - demand charge `1200 JPY/kW`
    - depot power limit `200 kW`

- **確認した問題**:
  - 3路線 scope の最大同時運行は 19 本で、16台 fleet では MILP が infeasible。
    これは shard runtime 不具合ではなく fleet shortage だった。
  - fresh scenario の builder defaults が `constant/input_template.json` を見ず、
    diesel / demand / TOU / depot limit が 0 扱いになっていた。
  - `simulation.prepare` が TOU band を dict のまま overlay へ入れており、
    Pydantic serializer warning を出していた。
  - frontend builder store / prepare payload が
    `objectiveMode`, `allowPartialService`, `unservedPenalty`,
    `fleetTemplates`, cost / CO2 / depot limit / TOU を drop していた。

- **対応**:
  - `src/scenario_overlay.py`
    - `constant/input_template.json` から overlay default を構築する loader を追加。
    - TOU / diesel / demand charge / depot power limit を fresh scenario default に反映。
  - `bff/routers/simulation.py`
    - TOU band を `TimeOfUseBand` として overlay に格納し、serializer warning を解消。
  - `data-prep/pipeline/build_tokyu_shards.py`
    - `distance_hint_km` が trip / pattern に無い場合でも、
      route row の `distance_km` を fallback に使って shard へ残すよう修正。
  - `frontend/src/stores/simulation-builder-store.ts`
    - builder defaults の cost / objective / mixed-fleet / TOU を hydrate するよう修正。
  - `frontend/src/pages/scenario/ScenarioOverviewPage.tsx`
    - prepare payload に `fleet_templates`, `objective_mode`,
      `allow_partial_service`, `unserved_penalty`,
      `demand_charge_cost_per_kw`, `diesel_price_per_l`,
      `grid_co2_kg_per_kwh`, `co2_price_per_kg`,
      `depot_power_limit_kw`, `tou_pricing` を追加。
    - Step 2 に objective / cost / CO2 / depot limit の入力と、
      fleet / TOU summary 表示を追加。

- **Gurobi 実測結果**:
  - `total_cost` mode
    - status: `OPTIMAL`
    - objective: `18592.2765`
    - total operating cost: `18592.23 JPY`
    - fuel: `18589.068 JPY`
    - electricity: `0.6485 JPY`
    - demand: `2.56 JPY`
    - total CO2: `319.7433 kg`
  - `co2` mode
    - status: `OPTIMAL`
    - objective: `243.8922 kg-CO2`
    - total operating cost: `229294.96 JPY`
    - fuel: `6331.1 JPY`
    - electricity: `6963.86 JPY`
    - demand: `216000.0 JPY`
    - total CO2: `243.8922 kg`

- **現時点の示唆**:
  - shard runtime で prepare / optimization は end-to-end に成立した。
  - `total_cost` と `co2` で fuel / electricity / demand の構成差は明確に出た。
  - ただし `vehicle_fixed_cost = 0` 設定では使用台数に tie-break が無く、
    solver が全 vehicle を使う解を返しやすい。これは secondary objective
    ないし fixed-use cost 設計の課題として残る。

### [DEV-2026-03-14] Tokyu shard build 基盤と runtime shard fallback を追加

- **問題**:
  - scenario open / simulation prepare が `data/built/<dataset>/timetables.parquet` と
    `trips.parquet` を広く読むため、Tokyu 全体時刻表の読み込みコストが高すぎた。
  - `build_dataset_bootstrap()` が built dataset を見つけると scenario document に
    full `timetable_rows` / `trips` を preload しており、保存サイズと open latency を押し上げていた。
  - Tokyu 向けに必要な `depot x route x day_type` の build-time shard / index / summary /
    schema / validation CLI が存在しなかった。

- **対応**:
  - `data-prep/pipeline/build_tokyu_shards.py`
    - canonical Tokyu data から `outputs/built/tokyu/` を生成する Tokyu-only shard builder を追加。
    - `manifest.json` / `depots.json` / `routes.json` / `depot_route_index.json` /
      `depot_route_summary.json` / `shard_manifest.json` と
      `trip_shards` / `timetable_shards` / `stop_time_shards` を出力。
    - `python -m data_prep.pipeline.build_tokyu_shards --dataset ...`
      `--validate-only` `--depot ...` をサポート。
    - build 時の整合性チェック
      （trip shard 所属、manifest 件数、summary/index 整合、trip/timetable 対応、
      stop sequence 昇順、schema validation）を追加。
  - `schema/tokyu_shards/*.schema.json`
    - manifest / index / summary / shard manifest / trip shard /
      timetable shard / stop_time shard の JSON Schema を追加。
  - `data-prep/pipeline/build_all.py`
    - `build_tokyu_shards` stage を追加し、通常 build で shard も生成するよう変更。
  - `src/tokyu_shard_loader.py`
    - runtime 専用 shard loader を拡張し、trip rows / dispatch trip rows /
      stop-time rows / timetable summary / stop timetable summary を scope 指定でロード可能にした。
  - `src/runtime_scope.py` / `bff/routers/graph.py` / `bff/routers/scenarios.py`
    - scenario に full `timetable_rows` / `trips` が無い場合でも、
      shard manifest があれば scope 限定で fallback 読み込みするよう変更。
  - `src/research_dataset_loader.py`
    - shard manifest が ready の場合は `feed_context.source = "tokyu_shards"` を返し、
      bootstrap では route/depot/calendar のみ materialize、full timetable/trips preload を停止。
  - `bff/store/scenario_store.py`
    - bootstrap payload の `runtime_features` を永続化対象に追加。

- **検証結果**:
  - `python -m pytest tests/test_build_tokyu_shards.py tests/test_research_dataset_loader.py tests/test_bff_research_scenario_bootstrap.py tests/test_run_preparation_parity.py tests/test_bff_scenario_timetable_summary.py tests/test_bff_graph_router.py -q` → pass
  - `python -m pytest tests/test_architecture.py tests/test_performance_contracts.py -q` →
    `test_app_bootstrap_manager_prewarms_setup_and_execute_tabs` が既存 frontend 差分起因で fail
    （今回変更の Python shard 経路とは無関係）

### [DEV-2026-03-14] Scenario UI を viewer から simulation input builder へ再設計

- **問題**:
  - scenario open 時に timetable summary / detail を先読みする viewer 寄りの構成が残っており、
    「subset を選んで simulation input を作る」主目的に対して無駄な read が多かった。
  - frontend store は閲覧用 cache と builder state が混在しており、
    depot / route / day type / solver 条件の確定前に重い payload を抱えやすかった。
  - `run_preparation` は built parquet filter 前提だったため、
    Tokyu shard runtime artifact が存在しても prepare がそれを優先利用していなかった。
  - prepared input hash には `scenario_store._scope_summary()` が meta へ注入する
    `selectedDepotIds` / `selectedRouteIds` / `serviceIds` まで含まれ、
    prepare 直後の run でも stale 判定になるケースがあった。

- **対応**:
  - `bff/routers/scenarios.py`
    - `GET /api/scenarios/{id}/editor-bootstrap` を追加。
    - scenario metadata / depots / routes / vehicle templates / depotRouteIndex /
      depotRouteSummary / availableDayTypes / builderDefaults だけを返す pure-read endpoint にした。
  - `bff/routers/simulation.py`
    - `POST /api/scenarios/{id}/simulation/prepare` を追加し、
      builder で選ばれた depot / route / day type / vehicle / charger / solver 条件を
      scenario overlay / dispatch scope / generated vehicles / chargers に反映して一度だけ保存。
    - `POST /api/scenarios/{id}/simulation/run` を追加し、
      prepared input id を検証した上で simulation job を起動する構成にした。
    - request body は `Field(default_factory=...)` に変更し、mutable default を排除。
  - `bff/services/run_preparation.py`
    - prepared input に `dataset_id` / `random_seed` / `depot_ids` / `route_ids` /
      `service_ids` / `trip_count` などの top-level compatibility key を追加。
    - `outputs/prepared_inputs/<scenario_id>/...` を新 API 用の標準保存先に整理し、
      旧 `.../<scenario_id>/prepared_inputs/...` caller との互換も維持。
    - Tokyu shard runtime artifact が存在する場合は `src/tokyu_shard_loader.py` を優先し、
      `trip_shard` / `stop_time_shard` から prepared input を組み立てるよう変更。
    - built stops が無い場合でも stop-time rows から最小 stop list を推定して canonical input に含めるようにした。
    - hash の volatile key に `selectedDepotIds` / `selectedRouteIds` / `serviceIds` を追加し、
      prepare 後の即 run が stale 判定される問題を解消。
  - `src/tokyu_shard_loader.py`
    - `load_stop_time_rows_for_scope()` を追加し、
      stop-time shard を canonical stop-time sequence へ変換できるようにした。
  - `frontend`
    - `ScenarioOverviewPage` を 3-step builder UI に置換。
    - `simulation-builder-store` を追加し、
      selected depots / routes / day type / settings / prepared result / active job を一元管理。
    - `useEditorBootstrap` / `usePrepareSimulation` / `useRunPreparedSimulation` を追加。
    - `AppBootstrapManager` は open 時に editor-bootstrap だけを warm し、
      timetable / dispatch 系は lazy load 優先に変更。

- **回帰テスト**:
  - `tests/test_run_preparation_parity.py`
    - prepared input の `random_seed` / scope key 互換を検証。
    - Tokyu shard runtime artifact がある場合に shard を優先することを検証。
  - `tests/test_bff_simulation_builder.py`
    - editor-bootstrap の軽量 payload を検証。
    - prepare → run prepared simulation の builder flow を検証。

### [DEV-2026-03-14] Scenario activate/open の bootstrap/save 競合を緊急修正

- **問題**:
  - `GET /api/scenarios/{id}` や `GET /api/scenarios/{id}/dispatch-scope` の read path が
    bootstrap 保存を誘発していた。
  - `bff/routers/scenarios.py` の bootstrap 判定は `store.get_scenario()` の meta payload を見ており、
    `depots/routes` を持たないため高確率で「未bootstrap」と誤判定していた。
  - `POST /activate` と複数の GET が短時間に重なると、
    同じ scenario の `.staging/artifacts.sqlite` を並行保存・削除し、
    Windows で `WinError 32` が発生していた。
  - frontend では `ScenarioListPage` と `AppLayout` の両方が `/activate` を叩き、
    open 直後に request burst を作っていた。

- **対応**:
  - `bff/routers/scenarios.py`
    - GET 系から bootstrap 保存を除去し、`get_scenario` / `get_dispatch_scope` を pure read 化。
    - activate 専用の `_ensure_scenario_bootstrap_persisted()` を追加し、
      raw scenario document を見て bootstrap 要否を判定するよう修正。
  - `bff/store/scenario_store.py`
    - `_load(..., repair_missing_master=True)` に分離し、read path の self-heal が `_save()` しないよう変更。
    - `get_scenario_document(..., repair_missing_master=False)` を追加し、
      persisted state と in-memory repaired view を使い分け可能にした。
    - scenario 単位 `RLock` を `_save()` と `apply_dataset_bootstrap()` に導入。
    - `apply_dataset_bootstrap()` を dataset/version/fingerprint ベースで idempotent 化し、
      同一 bootstrap 再適用では `_save()` を skip。
    - `_remove_tree_with_retries()` は retry 後に quarantine rename を試すようにし、
      Windows の cleanup 衝突に強くした。
  - `frontend/src/features/layout/AppLayout.tsx`
    - route 遷移後の child render / boot prewarm を、activate 完了まで待つ構成へ変更。
  - `frontend/src/pages/scenario/ScenarioListPage.tsx`
    - 同一 scenario の activate 二重送信を抑止し、open 中はボタンを disable。
  - `frontend/src/api/scenario.ts`
    - in-flight dedupe 付き `ensureScenarioActivated()` を追加。
  - `frontend/src/app/AppBootstrapManager.tsx`
    - open 直後の一斉 prewarm を削減し、scenario detail / dispatch scope 確認後は
      timetable / dispatch / explorer を lazy load 優先に変更。

- **確認結果**:
  - `python -m pytest tests/test_bff_research_scenario_bootstrap.py tests/test_bff_scenario_store.py -q` → pass
  - `cd frontend && npx tsc --noEmit` → pass

### [DEV-2026-03-14] Vehicle template catalog を実車カタログ値へ更新

- **問題**:
  - `src/research_dataset_loader.py` の `default_vehicle_templates()` が汎用ダミー値のままで、
    `data/vehicle_catalog.json` や `config/ebus_asset_factors.json` の車両カタログとも乖離していた。
  - BYD K8 2.0 / エルガEV / ブルーリボン Z EV / エルガ / ブルーリボン / エアロスターの
    大型路線バス実車テンプレートが scenario 初期値に出てこなかった。
  - HEV 参考車種を保持したくても、現行 template 層は `BEV` / `ICE` 二値前提だった。

- **対応**:
  - `data/vehicle_catalog.json`
    - 大型路線バスカタログ値 dataset として全面更新。
    - `ev_presets` / `engine_presets` を実車ベースへ差し替え、
      scenario template seed の正本に位置づけた。
    - HEV は `hybrid_reference_presets` に reference-only で保持。
  - `src/research_dataset_loader.py`
    - `default_vehicle_templates()` を `data/vehicle_catalog.json` 読み込みに変更。
    - scenario bootstrap / master preload の vehicle templates が catalog 連動になった。
  - `config/ebus_asset_factors.json`
    - `vehicle_catalog` を同じカタログ値へ更新し、研究設定側とのズレを解消。
  - `README.md`
    - `data/vehicle_catalog.json` を seed asset として明記。

- **制約メモ**:
  - 現行 runtime の vehicle template は `BEV` / `ICE` のみ自動 seed。
  - `isuzu_erga_hybrid_swb` は catalog reference として保持し、HEV template 自動投入は将来拡張扱い。

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

- 2026-03-28 (237d total_cost canonical rerun hardening)
  - 対象 scenario `237d5623-aa94-4f72-9da1-17b9070264be` / prepared input `prepared-c954365437b0f8f6` の total_cost 再実行で、canonical path の main blockers を順に潰した。
  - `bff/services/run_preparation.py`
    - `materialize_scenario_from_prepared_input()` でも catalog stop を再参照し、prepared JSON 側 `stops` が stale / inferred-only でも座標を backfill するよう修正した。
    - これにより 237d scoped case で `ConnectionGraphBuilder().build(..., "BEV")` の outgoing edge が `0` 件しか出ない状態を解消した（座標 backfill 後は多数の feasible successor を再獲得）。
    - `_scenario_hash()` から `optimization_audit` / `simulation_audit` / `problemdata_build_audit` / `__unloaded_artifact_fields__` も除外し、Prepare 直後に `prepared_input_id` が即 stale 化するドリフトを止めた。
  - `src/route_family_runtime.py`
    - `BusstopPole` の番線 suffix 違いを同一 stop family とみなし、`stop_platform_alias` の 0 分 deadhead rule を双方向に自動補完するよう変更した。
    - `...00240050.` / `...00240050.4`、`...00240324.` / `...00240324.1` のような terminal bay 差分で location continuity が壊れていたのを是正した。
  - `src/optimization/milp/model_builder.py`
    - MILP arc enumeration を `milp_max_successors_per_trip`（既定 8）で pruning するよう変更し、237d の dense feasible graph で Gurobi が極端に重くなる問題を抑えた。
  - `src/optimization/milp/solver_adapter.py`
    - MILP 解の duty 復元を `y` の単純 departure sort から、選択 `x/start_arc` をたどる fragment 復元へ変更した。
    - これで solver 自体は full service でも、post validation で「存在しない trip 直結」を拾って infeasible 扱いになる問題を除去した。
  - `src/optimization/common/problem.py`, `src/optimization/common/feasibility.py`, `src/optimization/milp/solver_adapter.py`
    - `required_soc_departure_percent` の小数値 (`0.939` = 0.939%) を 93.9% ratio と誤解する経路を修正した。
    - builder-generated canonical problem では `required_soc_departure_unit="percent_0_100"` を明示し、feasibility / MILP の両方で同じ解釈を使うようにした。
  - `src/optimization/common/evaluator.py`
    - actual charging flow が無い provisional-only plan では fake demand charge / fake grid import を立てないよう修正した。
    - `grid_purchase_cost=0`, `demand_cost=0`, `pv_curtailed_kwh=total PV` を返す fallback に整理し、metaheuristic result の cost breakdown を物理的に誤解しにくい形へ寄せた。
  - `src/optimization/common/feasibility.py`
    - vehicle fragment overlap 判定を duty envelope ベースから actual trip interval ベースへ変更し、同一車両の sparse fragment を false positive で弾かないようにした。
  - `bff/routers/scenarios.py`, `bff/store/scenario_store.py`, `tools/scenario_backup_tk.py`
    - `fixedRouteBandMode=true` / `enableVehicleDiagramOutput=true` を標準デフォルトへ寄せ、route-band diagram を基本出力にした。
    - fragment 上限は scenario 互換性と solve stability を優先して configurable のまま維持した。
  - `bff/routers/optimization.py`
    - canonical solve 完了後に `graph/vehicle_timeline.csv` と `graph/route_band_diagrams/manifest.json` / `*.svg` を直接生成する helper を追加した。
    - これにより BFF/Tk 経由の `mode_milp_only` でも route-band diagram を確認できるようになった。
  - 追加/更新テスト:
    - `tests/test_run_preparation_stop_coords.py`
    - `tests/test_route_family_deadhead_inference.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_reopt_alns_critical_fixes.py`
    - `tests/test_evaluator_provisional_overwrite.py`
    - `tests/test_bev_energy_accounting.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
  - 確認:
    - `python -m pytest tests/test_milp_route_band_settings.py tests/test_reopt_alns_critical_fixes.py tests/test_run_preparation_stop_coords.py tests/test_route_family_deadhead_inference.py tests/test_optimization_canonical_metaheuristics.py tests/test_evaluator_provisional_overwrite.py tests/test_bev_energy_accounting.py` → `38 passed`
    - canonical direct rerun (`output/tmp_canonical_237d/*_cap100.json`):
      - `MILP`: `OPTIMAL`, `served=488/488`, `objective=1640378.9059`
      - `ALNS`: `feasible`, `served=488/488`, `objective=1843087.2393`
      - `GA`: `feasible`, `served=488/488`, `objective=1843520.5726`
      - `ABC`: `feasible`, `served=488/488`, `objective=1827362.2393`
    - いずれも `disable_vehicle_acquisition_cost=true`, `objective_mode=total_cost`, `fixed_route_band_mode=true` で再現した。
    - BFF route sync smoke (`run_optimization()` を同期 submit patch で直実行): `solver_status=optimal`, `served=488/488`, `graph_artifacts.enabled=true`, `diagram_count=4` を確認
    - Tk E2E smoke（withdrawn Tk root + sync run_bg + TestClient 経由）: `Quick Setup保存 -> Prepare -> run-optimization` の一連で `prepared_id_stable=true`, `solver_status=optimal`, `served=488`, `route_band_diagrams=4` を確認

- 2026-03-14 (Catalog-backed dispatch scope for runtime route selection)
  - `bff/services/local_db_catalog.py` に depot / route-family summary 読み出しを追加し、`/api/catalog/depots`, `/api/catalog/depots/{depot_id}/routes`, `/api/catalog/route-families/{route_family_id}/patterns` を `bff/routers/catalog_local.py` から公開した。
  - 軽量 summary は既存 SQLite schema をそのまま使い、追加 catalog table は作らずに `route_families`, `route_patterns`, `route_pattern_depots`, `timetable_trips` を集計する方式にした。
  - `東98` は summary 分類で `東京駅南口 ↔ 等々力操車所` を mainline 固定にし、昼間 split を `short_turn`, `清水` / `目黒郵便局` 端点を Meguro depot-related note として返すようにした。
  - `bff/store/scenario_store.py` の `dispatch_scope` 正規化は `includeRouteFamilyCodes` / `excludeRouteFamilyCodes` を受け付け、runtime では既存どおり route ids に展開するよう拡張した。
  - `frontend/src/features/planning/DispatchScopePanel.tsx` は local SQLite catalog summary を優先表示し、catalog が使えないときだけ scenario master routes へフォールバックするよう変更した。
  - GTFS 未収録路線は runtime scope UI に出さない方針とし、catalog summary 上は「存在しない route family は選択不可」として扱う。
  - 追加確認:
    - `python -m pytest tests/test_catalog_local.py tests/test_bff_scenario_store.py -q` → 29 passed
    - `cd frontend && npm run build` → pass

- 2026-03-14 (Scenario open regression on Windows)
  - `bff/store/master_data_store.py` と `bff/store/trip_store.py` の SQLite artifact connection を `journal_mode=WAL` から `journal_mode=DELETE` に変更した。
  - `bff/store/scenario_store.py` の staging cleanup に retry 付き削除を追加し、直前の SQLite close と競合した `PermissionError [WinError 32]` を吸収するようにした。
  - Windows では scenario save の staging cleanup 時に `master_data.sqlite` / `artifacts.sqlite` の `-wal` / `-shm` 系ハンドルが残り、`GET /api/scenarios/{id}` や `POST /api/scenarios/{id}/activate` が `PermissionError [WinError 32]` で落ちるケースがあったため。
  - 確認:
    - `python -m pytest tests/test_bff_scenario_store.py tests/test_bff_research_scenario_bootstrap.py -q` → 26 passed
    - `TestClient(bff.main:app)` 経由の `GET /api/scenarios/e2379614-2885-40c4-b064-6982bdf57e31` → 200

- 2026-03-17 (Solver mode benchmark script + Tk compare/results parity)
  - `scripts/benchmark_solver_modes.py` を追加し、`mode_milp_only` / `mode_alns_only` / `ga` / `abc` をBFF API経由で順次実行して、runtime/objective比較をJSON/CSV出力できるようにした。
  - 比較値は top-level だけでなく `solver_result.objective_value` / `solver_result.solve_time_seconds` を優先参照する実装にした。
  - `tools/scenario_backup_tk.py` に以下を追加した。
    - 結果詳細ビュー: Simulation/Optimization結果を Summary/Details/Raw JSON で表示。
    - シナリオ比較ビュー: Scenario A/B の Optimization比較・Simulation比較を表示し、主要指標の `delta(B-A)` を確認可能にした。
  - 運用手順書として `readme_operation.md` を追加し、比較実行コマンドと確認項目を明文化した。

- 2026-03-17 (MILP only ERROR pinpoint fix)
  - `mode_milp_only` 実行時の `solver_result.infeasibility_info = "Name too long (maximum name length is 255 characters)"` を確認。
  - 原因は `src/optimization/milp/solver_adapter.py` の Gurobi 変数名に `vehicle_id/trip_id` を長文字列で埋め込んでいたこと。
  - 対策として MILP変数生成時の `name=...` 指定を除去し、自動命名へ変更して名称長制限を回避した。

- 2026-03-22 (Gurobi late-import stabilization across MILP/ALNS/constraints)
  - `run_app.py` 再起動後の `mode_milp_only` で `solver_result.infeasibility_info = "NameError: name 'gp' is not defined"` を確認。
  - 原因は `src/constraints/*` と `src/objective.py` がモジュール読込時の `try: import gurobipy as gp` に失敗したまま `gp` 未定義で残り、`src/milp_model.py` 側だけ solve 時に import 復旧しても stale import が解消されなかったこと。
  - `src/gurobi_runtime.py` を追加し、Gurobi site-packages / DLL path / license 補完と `ensure_gurobi()` を共通化した。
  - `src/milp_model.py`, `src/objective.py`, `src/solver_runner.py`, `src/solver_alns.py`, `src/optimization/milp/solver_adapter.py`, `src/constraints/assignment.py`, `src/constraints/battery_degradation.py`, `src/constraints/charger_capacity.py`, `src/constraints/charging.py`, `src/constraints/duty_assignment.py`, `src/constraints/energy_balance.py`, `src/constraints/optional_v2g.py`, `src/constraints/pv_grid.py`, `src/constraints/soc_threshold_charging.py` を修正し、Gurobi 参照をすべて呼び出し時の `ensure_gurobi()` 経由へ統一した。
  - `tests/test_model_factory_gurobi_import.py` に constraints / objective の late-binding 回帰テストを追加した。
  - 確認:
    - `python -m pytest tests -q` → `50 passed`
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を同じ `tsurumaki` / `WEEKDAY` / `mode_milp_only` で direct smoke 実行 → Gurobi ライセンス読込成功、`status='OPTIMAL'`, `infeasibility_info=''`

- 2026-03-23 (Quick Setup trip counts now use `tokyu_bus_data` when shard runtime is unavailable)
  - Quick Setup の運行種別サマリーと営業所路線選択で `routes=0 / trips=0` になる原因は、`bff/routers/scenarios.py` が `shard_runtime_ready(dataset_id)` を満たさないと day-type summary を一切作らず、route list 側だけ `route.tripCount` 総数にフォールバックしていたこと。
  - `bff/routers/scenarios.py` に `build_timetable_summary_for_scope()` ラッパーを追加し、`data/catalog-fast/tokyu_bus_data` を優先、次に legacy shard runtime を使う順へ変更した。
  - `_route_trip_inventory_for_quick_setup()` は shard readiness に依存せず dataset summary を引くよう修正し、`_shard_scope_params()` も dataset が分かれば summary endpoint から `tokyu_bus_data` に到達できるようにした。
  - これにより Quick Setup の `dayTypeSummaries` と route list の `tripCount/tripCountSelectedDay/tripCountTotal` が同じ day-type 別集計を使うようになった。
  - 実データ確認: scenario `2b0a60cf-61ad-4094-807c-f766641984c6` / depot `tsurumaki` で `dayTypeSummaries = SAT 714 / SUN_HOL 754 / WEEKDAY 974`、route list 先頭も `tripCountSelectedDay` が非 0 で返ることを確認。
  - 追加テスト: `tests/test_quick_setup_route_selection.py` に `tokyu_bus_data` fallback ケースを追加。
  - 確認:
    - `python -m pytest tests -q` → `51 passed`

- 2026-03-23 (Tokyu 全体便数の presentation 向け network scale を `tokyu_bus_data` に追加)
  - 問題は `data/catalog-fast/tokyu_bus_data/summary.json` の `counts.trips=33360` が「平日便数」に見えやすいことだった。実際にはこれは `WEEKDAY/SAT/SUN_HOL` を全部足した総 trip 数で、weekday-only の値ではない。
  - `scripts/build_tokyu_bus_data.py` を修正し、summary に `countSemantics` と `networkScale` を追加した。`networkScale` には day-type 別総便数、day-type 別 active route 数、weekday 比率、route-variant / route-family の分布統計、day-type 別の上位 route variants を持たせた。
  - `data/catalog-fast/tokyu_bus_data/network_summary.json` も追加生成するようにし、presentation 用の規模感だけを summary 本体から独立して読みやすくした。
  - `src/tokyu_bus_data.py` に `load_network_scale_summary()` を追加し、将来 UI/API 側が `summary.json` のネスト構造に直接依存しなくてよいようにした。
  - 実データ再集計結果:
    - route variants: `764`
    - families: `184`
    - weekday trips: `14,437`
    - saturday trips: `8,477` (`58.72%` of weekday)
    - sunday/holiday trips: `10,446` (`72.36%` of weekday)
    - weekday active route variants: `698`
    - weekday average trips per route variant: `18.90` across all 764 variants / `20.68` across active weekday variants
  - これで `33360` は「全 day-type 合計」、発表で使う weekday 規模感は `14437` と明示的に区別できるようになった。

- 2026-03-23 (BEV の電気コスト集計を charging-centric から operating-centric へ修正)
  - 問題は BEV の `energy_cost` / `demand_charge` が「充電したときだけ」発生する設計になっていたことだった。初期 SOC だけで走り切れる解では、BEV が多数運行していても `energy_cost=0`, `demand_charge=0` になり、ICE の fuel cost と対称でなかった。
  - `src/objective.py` を修正し、legacy MILP の電力量料金と電力由来 CO2 を `p_grid_import` / `p_charge` ではなく `x_assign * task_energy_per_slot` ベースで計上するよう変更した。充電は SOC feasibility のためだけに残し、追加コストは課さない。
  - `src/constraints/energy_balance.py` の peak tracking も `p_grid_import` ではなく BEV の走行電力需要ベースへ変更し、`demand_charge_cost` が operating demand を見るようにした。
  - `src/simulator.py` は simulation summary の `total_energy_cost`, `total_demand_charge`, `total_grid_kwh`, `peak_demand_kw` を BEV の走行消費プロファイルから再計算するように変更した。これで solver 後の可視化でも `充電しなかったので電気代 0` にならない。
  - canonical path とのズレも防ぐため、`src/optimization/common/evaluator.py`, `src/optimization/milp/solver_adapter.py`, `src/solver_alns.py` も同じ operating-centric 基準へ揃えた。ALNS heuristic 側には「全 assigned task を BEV energy に混ぜる」退行もあり、あわせて修正した。
  - 回帰テスト `tests/test_bev_energy_accounting.py` を追加し、
    - BEV が charge import に依存せず走行消費分だけ電気代・デマンド料金を持つこと
    - canonical `CostEvaluator` でも charging slot 無しで BEV energy cost が立つこと
    を固定した。
  - 確認:
    - `python -m pytest tests -q` → `53 passed`
    - synthetic smoke: `energy_cost=300.0`, `demand_charge=1000.0`, `grid_kwh=20.0`, `peak_kw=10.0`

- 2026-03-31 (実日 PV / 複数日 planning_days / prepared-input optimization 実行の整備)
  - 問題として、営業所 PV は 2025/08 月平均へ潰してから `depot_energy_assets` へ同期しており、`serviceDate` を変えても実日に応じた日射差が solver 入力へ入っていなかった。加えて、Tk / Quick Setup / Prepare / canonical optimizer の間で `planning_days` と `service_dates` の受け渡しも分断されていた。
  - `tools/scenario_backup_tk.py` を更新し、`運行日 + 計画日数` から `service_dates` を生成して `data/derived/pv_profiles/{depot}_{YYYY-MM-DD}_60min.json` を実日読み込みするよう変更した。PV 同期は `pv_generation_kwh_by_date` / `pv_capacity_factor_by_date` / `pv_profile_dates` / `pv_slot_minutes` を保持し、`pv_capacity_kw` を編集した時は capacity factor から日別発電列を再生成する。UI も `天気モード` を手入力からプルダウンへ変更し、営業所エネルギー資産表で `pv_capacity_kw`, `bess_energy_kwh`, `bess_power_kw` を編集できる前提へ整理した。
  - `bff/routers/scenarios.py`, `bff/routers/simulation.py`, `bff/services/simulation_builder.py`, `bff/services/run_preparation.py`, `src/optimization/common/builder.py` を通して `service_dates`, `planning_days`, `planning_horizon_hours` を保持するようにし、canonical builder は multi-day trip / tariff / PV slot を正しく複製できるよう修正した。途中で自分から上げた不具合として `ProblemBuilder.build_from_scenario()` が `planning_days` を受けておらず、さらに multi-day price slot 複製で存在しない `co2_kg_per_kwh` を参照していたため、両方修正して回帰テストを追加した。
  - 追加で、MILP engine が solver metadata 用に `MILPModelBuilder.build()` を一度回し、その後 adapter 側で同じ巨大モデルを Gurobi 用に再構築していた。これでは 974 trip case の `mode_milp_only` 比較が極端に重くなるため、metadata は lightweight count 集計へ置き換え、重複 model build を除去した。
  - 最適化 API 実行ではさらに 2 段階の lock 問題を自分から確認した。1 つ目は `prepared_input` から materialize した scope artifact を `rebuild_dispatch=false` でも SQLite へ書き戻していたことで、background job から `timetable_rows` 保存時に `database is locked` を起こした。2 つ目は solve 完了後の `optimization_result` 保存でも同じ lock が起きたことだった。
  - 対策として `bff/routers/optimization.py` は `rebuild_dispatch=false` の prepared-input solve では scope artifact を scenario DB へ戻さず、materialized scenario をそのまま canonical optimizer へ渡すよう変更した。さらに `bff/store/scenario_store.py` では scalar artifact (`optimization_result` / `simulation_result` / `dispatch_plan`) の SQLite 保存が lock した場合、既存 refs の JSON sidecar へフォールバック保存し、読取側 `get_field()` も sidecar を見に行くようにした。これで background optimization job が結果保存で落ちず、`GET /api/scenarios/{id}/optimization` から結果取得できる。
  - 実行確認として `FastAPI TestClient` 経由で scenario `237d5623-aa94-4f72-9da1-17b9070264be` を対象に、`serviceDate=2025-08-04`, `serviceDates=["2025-08-04"]`, `planningDays=1`, `fixedRouteBandMode=true`, `disableVehicleAcquisitionCost=true`, `objectiveMode=total_cost`, `weatherMode=actual_date_profile`, `pvProfileId=tsurumaki_2025-08-04_60min` を Quick Setup へ反映したうえで、既存 BFF API (`/simulation/prepare` → `/run-optimization` → `/jobs/{id}` → `/optimization`) を 4 モードで実行した。
  - 比較結果は `output/optimization_comparison_api_237d_actual_pv_2025-08-04_final.json` に保存した。要約は以下の通り。
    - `mode_milp_only`: `solver_status=time_limit`, `objective_value=9740000.0`, `trip_count_served=0`, `trip_count_unserved=974`, `solve_time_seconds=97.6972`
    - `mode_alns_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=65.7632`
    - `mode_ga_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=62.1353`
    - `mode_abc_only`: `solver_status=infeasible_candidate`, `objective_value=6052927.3224609075`, `trip_count_served=638`, `trip_count_unserved=336`, `solve_time_seconds=63.2371`
  - 回帰テスト:
    - `tests/test_scenario_backup_tk_pv_sync.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_problem_builder_depot_energy_asset_controls.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_bff_reoptimization_actual_soc_forwarding.py`
    - `tests/test_milp_engine_lightweight_stats.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py bff/routers/scenarios.py bff/routers/simulation.py bff/services/simulation_builder.py bff/services/run_preparation.py bff/routers/optimization.py bff/store/scenario_store.py src/optimization/common/builder.py src/optimization/milp/engine.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_scenario_backup_tk_pv_sync.py tests/test_simulation_builder_prepare_scope.py tests/test_problem_builder_depot_energy_asset_controls.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_bff_reoptimization_actual_soc_forwarding.py tests/test_milp_engine_lightweight_stats.py tests/test_prepared_scope_execution.py tests/test_optimization_canonical_metaheuristics.py tests/test_scenario_store_dispatch_scope_overlay.py -q` → pass
  - 2026-04-02 rerun では、`simulation/prepare` を先に通して `tripCount=974`, `timetableRowCount=24064`, `primaryDepotId=tsurumaki` の prepared scope を再生成したうえで、同一 scenario `237d5623-aa94-4f72-9da1-17b9070264be` に対する 4 モード比較を再実行した。
  - 比較結果は `outputs/mode_compare_repaired_237d.json` / `outputs/mode_compare_repaired_237d.csv` に保存した。要約は以下の通り。
    - `mode_milp_only`: `status=optimal`, `objective_value=8601528.00406182`, `solve_time_seconds=11.5635`
    - `mode_alns_only`: `status=infeasible_candidate`, `objective_value=8928701.710007224`, `solve_time_seconds=95.4759`
    - `ga`: `status=infeasible_candidate`, `objective_value=8928701.710007224`, `solve_time_seconds=106.3408`
    - `abc`: `status=infeasible_candidate`, `objective_value=8928701.710007224`, `solve_time_seconds=106.9087`
  - 追記所見: 修正版の warm start により MILP は time limit 落ちではなく optimal 到達し、同一 prepared scope では MILP が 3 つのヒューリスティックより低い objective を返した。一方で ALNS / GA / ABC は同値の infeasible_candidate 解に収束しており、現行探索設定では MILP が最良基準になっている。
  - 追加の計算ロジック確認: 今回の MILP が文献で言われる「exact は重い」挙動になりにくい主因は、`fixed_route_band_mode=true` に加えて、`milp_max_successors_per_trip` で successor arc を上位候補に剪定している点だった。文献レベルの strict exact 比較をしたい場合は、route band 固定を外しつつこの上限を大きくする必要がある。
  - 2026-04-03 strict rerun では、`fixedRouteBandMode=false` / `milpMaxSuccessorsPerTrip=1000` に切り替えたうえで同じ 4 モード比較を再実行した。比較結果は `outputs/mode_compare_strict_237d.json` / `outputs/mode_compare_strict_237d.csv` に保存し、`mode_milp_only` は `optimal`, `objective_value=8424185.3198152`, `solve_time_seconds=104.8655`, `trip_count_unserved=803`、`mode_alns_only` は `feasible`, `objective_value=8928701.710007224`, `solve_time_seconds=108.3484`, `trip_count_unserved=850`、`ga` は `feasible`, `objective_value=8928701.710007224`, `solve_time_seconds=126.7963`, `trip_count_unserved=850`、`abc` は `feasible`, `objective_value=8928701.710007224`, `solve_time_seconds=114.3111`, `trip_count_unserved=850` だった。
  - 追記所見: `FeasibilityChecker` を「未配車は warning 扱い」に修正した後は、ヒューリスティック 3 手法が `infeasible_candidate` ではなく `feasible` を返すようになった。これは hard constraint の違反が無い限り候補解として扱うという、目的関数の罰則設計と整合する。MILP は依然として最良 objective を維持するが、現行比較では heuristic 側も least-surprise な status で返るようになった。

- 2026-04-05 (route24 近傍の欠便集中を切り分け、baseline/repair と MILP fallback を補修)
  - 問題として、scenario `237d5623-aa94-4f72-9da1-17b9070264be` / `prepared-11efb997690030ef` の弦巻 `WEEKDAY` 単日 scope では、旧 run `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260404_1611/optimization_result.json` に `trip_count_unserved=56` が残り、その内訳が `渋24=49`, `渋23=7` に集中していた。まず IIS よりも route24 / route23 近傍の朝ピーク縮小問題として切り分けた。
  - 追加で自分から上げた問題として、canonical baseline と repair が shared trip を `allowed_vehicle_types[0]` 優先で消費しており、`('BEV','ICE')` 許可 trip が BEV duty に偏る一方、後段で actual fleet materialize した時に duty が崩れていた。さらに MILP は `TIME_LIMIT` かつ `SolCount==0` のとき空の全欠便 plan を返しており、baseline fallback でも `supports_exact_milp=True` になっていた。
  - `src/optimization/common/builder.py` では baseline 構築を actual fleet 台数順に変更し、vehicle type ごとの greedy duty を即時に `assign_duty_fragments_to_vehicles()` で実車両へ materialize しながら trip を確定するよう修正した。これにより baseline 自体が `served=974`, `unserved=0`, `vehicle_count_used=91` になった。
  - `src/optimization/alns/operators_repair.py` でも `greedy_trip_insertion()` を actual fleet 台数順へ変更し、shared trip を BEV-first で抱え込まないようにした。回帰用に `tests/test_baseline_vehicle_type_priority.py` を追加し、baseline / repair の両方が overflow 先 vehicle type を使えることを固定した。
  - `src/optimization/milp/solver_adapter.py` には baseline fallback helper を追加し、`auto_relaxed_baseline` と `time_limit_baseline` のどちらでも `supports_exact_milp=False` になるよう修正した。`TIME_LIMIT && SolCount==0` の no-incumbent 経路では `dispatch_baseline_after_time_limit_no_incumbent` を返すようにし、`src/optimization/milp/engine.py` で termination reason も `time_limit` / `baseline_after_relax` として読めるよう揃えた。
  - ついでに `scripts/benchmark_solver_modes.py` も補修し、比較時は `job.metadata.dated_run_dir` から `optimization_result.json` を優先読取するようにした。これで API 比較時に `unmet_trips=null` のまま集計される問題を避けられる。
  - 固定 scope の再実行を人手差分なしで再現するため、`scripts/benchmark_fixed_prepared_scope.py` を追加した。`scenario/prepared_input/depot/service/objective/planning_days` を固定し、prepared input から materialize した `timetable_rows` をそのまま使って 4 ソルバーを sequential 実行し、comparison JSON / CSV と per-solver JSON、verdict、consistency check をまとめて出す。
  - 4 ソルバー再実行は current call path と同じ builder / engine を prepared input 固定で直接呼ぶ形で行い、結果を `outputs/mode_compare_route24_fix_rerun_20260405.json` / `outputs/mode_compare_route24_fix_rerun_20260405.csv` に保存した。結果は以下の通り。
    - `milp`: `solver_status=time_limit_baseline`, `objective_value=2979501.013850968`, `trip_count_served=974`, `trip_count_unserved=0`, `vehicle_count_used=91`, `supports_exact_milp=false`
    - `alns`: `solver_status=feasible`, `objective_value=2955072.402034295`, `trip_count_served=974`, `trip_count_unserved=0`, `vehicle_count_used=93`
    - `ga`: `solver_status=feasible`, `objective_value=2979501.013850968`, `trip_count_served=974`, `trip_count_unserved=0`, `vehicle_count_used=91`
    - `abc`: `solver_status=feasible`, `objective_value=2976786.2860787963`, `trip_count_served=974`, `trip_count_unserved=0`, `vehicle_count_used=91`
  - comparison row には `supports_exact_milp`, `termination_reason`, `warnings`, `incumbent_history_count`, `plan_source`, `plan_status`, `milp_status`, `route24/23` の未担当件数、shared trip の BEV/ICE 割当内訳を持たせた。`consistency_check.json` では comparison と per-solver JSON の `solver_status/objective/served/unserved/vehicle_count_used` が 4 モードすべて一致することを確認した。
  - 追記所見: 欠便抑止の観点では 4 モードとも route24 / route23 の未担当を 0 まで戻せた。一方で MILP は exact incumbent を 300 秒以内に得ておらず、現時点の改善は「全欠便へ落ちない安全化」である。先生向けの説明資料は `docs/route24_solver_report_20260405.md` にまとめた。
  - 回帰テスト:
    - `tests/test_milp_baseline_fallbacks.py`
    - `tests/test_baseline_vehicle_type_priority.py`
    - `tests/test_route_family_deadhead_inference.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
  - 確認:
    - `python -m py_compile src/optimization/milp/solver_adapter.py src/optimization/milp/engine.py tests/test_milp_baseline_fallbacks.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_milp_baseline_fallbacks.py tests/test_baseline_vehicle_type_priority.py tests/test_route_family_deadhead_inference.py tests/test_problem_builder_timestep_and_pv_scaling.py -q` → `14 passed`

- 2026-03-23 (Prepared-scope optimization と scenario artifact の整合を修正)
  - 問題は Tk/BFF の既定フローで `rebuild_dispatch=false` のまま最適化を完了すると、`optimization_result` だけは更新される一方で scenario 側の `trips` / `timetable_rows` / `stats` が古いまま残り、フロント・BFF・最適化監査で見える件数が食い違うことだった。
  - さらに `scenario_store.set_field(..., invalidate_dispatch=True)` の direct row-artifact 更新経路は `timetable_rows` / `stop_timetables` 更新時に stale な `trips` / `duties` / `optimization_result` を落としておらず、timetable-first なのに古い dispatch/optimization が残り得た。
  - `bff/routers/optimization.py` では prepared input 直実行でも `trips` / `timetable_rows` / `stops` / `stop_timetables` を scenario artifact へ同期するようにし、dispatch 再構築を省く run では stale `graph` / `blocks` / `duties` / `dispatch_plan` を明示クリアするよう修正した。
  - 同時に `optimization_result` と `optimization_audit` に `prepared_input_id` / `prepared_scope_summary` を保存し、どの prepared scope で solve したかを追跡できるようにした。
  - `bff/store/scenario_store.py` では direct row-artifact 更新後も meta を更新し、`invalidate_dispatch=True` 時は scenario status を `draft` に戻し、`tripCount` / `dutyCount` を 0 リセットしたうえで stale dispatch/optimization artifact を削除するよう修正した。
  - ドキュメントも現行保存先 `outputs/prepared_inputs/<scenario_id>/<prepared_input_id>.json` に合わせて README / run prep contract / reproduction note を更新した。
  - 回帰テスト:
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m pytest tests/test_prepared_scope_execution.py tests/test_scenario_store_dispatch_scope_overlay.py` → pass
    - `python -m pytest tests` → `62 passed`
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を `tsurumaki` / `WEEKDAY` / `mode_milp_only` / `rebuild_dispatch=false` で再実行し、`prepared_input_id=prepared-e0fb1e07bb3635d8`, `trip_count_served=702`, `tripCount=702`, `timetableRowCount=702`, `solver_status=OPTIMAL` を確認

- 2026-03-23 (Graph Exports に route-band 別の車両ダイヤ SVG を追加)
  - 要件は「固定路線バンドで路線間車両トレードを許可しない run では、鉄道ダイヤグラム風に route ごとの車両位置推移を見たい」というものだった。
  - `src/result_exporter.py` を拡張し、optimization run 配下の `graph/vehicle_timeline.csv` に `vehicle_type` / `band_id` / `route_family_code` / `route_series_code` / `event_route_band_id` を追加した。
  - 同じ情報から `graph/route_band_diagrams/manifest.json` と `graph/route_band_diagrams/*.svg` を生成するようにし、1 band 1 図で `vehicle_id [ICE/BEV]` 凡例付きの time-space diagram を出せるようにした。
  - 初版は「車両の主担当 band」で grouping していたため、同じ車両が他路線を担当した stop が route graph に混入する欠陥があった。
  - 2026-03-23 夜に `bff/mappers/scenario_to_problemdata.py` から route `stopSequence` を graph export context として渡し、SVG 側は actual `band_id` 単位で再 grouping するよう修正した。これで route 軸は当該路線の stop だけになり、上り/下り/区間便/入出庫便は同一路線グラフへ統合、ICE/BEV は色系統と type legend で識別できる。
  - その後、prepared payload 内の `stop_time_sequences` が stop-level ではなく trip-level 行だったため、中間 stop 時刻が取れていない問題を追加で確認した。`data/catalog-fast/tokyu_bus_data/route_stop_times/{route_id}.jsonl` から selected trip の stop-time を補完するよう変更し、catalog-fast に無い trip だけ route `stopSequence` 上の線形補間へフォールバックするようにした。
  - さらに、stop 軸の順番を adjacency 推定で並べ替えていたため、variant stop が末尾へ落ちる問題を追加で確認した。route `stopSequence` を本線基準でマージする方式へ変更し、区間便は本線の間へ差し込み、本線外 terminal は top/bottom side lane として分離した。
  - 2026-03-23 18:30 頃、Graph SVG だけ夕方便が欠けて見える問題を追加で確認した。原因は slot index を `00:00` 起点として ISO 化していたことで、実際には `simulation_config.start_time=05:00` 起点の `vehicle_timeline.csv` / `trip_assignment.csv` が stop-time polyline と 5 時間ずれていた点だった。`src/result_exporter.py` で planning start を graph export builder に通し、slot->時刻変換を補正した。
  - 同時に、route-band SVG の時間軸を常に `00:00-23:59` の full-day 固定へ変更し、plot width を拡大、clip-path を導入して path がフレーム外へ飛んでも表示破綻しないようにした。
  - さらに、営業所入出庫の条件緩和が図に出ていなかったため、band 図の row 生成を `vehicle_timeline.csv` 全体から vehicle ごとに再構成する方式へ変更した。これにより、その日最初の便の前の `depot_out`、最後の便の後の `depot_in`、同一 band 内の長い空き時間や charge row を挟む temporary depot stay を `弦巻営業所` などの depot side lane として推定描画できるようにした。
  - side lane label を top/bottom に二重登録して同じ depot 名が軸に 2 回出る不具合も追加で確認し、`_diagram_location_labels()` で重複抑止を入れた。
  - `mixed_event_route_band_detected=true` は「その route graph に出てくる車両が同日に他 band も担当した」ことを示す警告値へ意味を変更した。
  - 回帰テスト `tests/test_graph_export_route_band_diagrams.py` を拡張し、SVG の生成、ICE/BEV 凡例、full-day 軸、slot 時刻補正、depot stay 推定、manifest 出力を固定した。
  - 実データ確認:
    - scenario `2b0a60cf-61ad-4094-807c-f766641984c6` を `prepared_input_id=prepared-23163ca5b3496ca1`, `tsurumaki`, `WEEKDAY`, `mode_milp_only`, `rebuild_dispatch=false` で再実行し、`outputs/tokyu/2026-03-22/optimization/2b0a60cf-61ad-4094-807c-f766641984c6/tsurumaki/WEEKDAY/run_20260323_1833/graph/route_band_diagrams/` に `黒06.svg`, `黒07.svg`, `渋21.svg`, `渋22.svg`, `渋23.svg`, `渋24.svg` が生成されることを確認
    - `run_20260323_1833/graph/vehicle_timeline.csv` は `min_start=2026-03-22T05:30:00+09:00`, `max_end=2026-03-22T23:15:00+09:00` で、夕方便が CSV / SVG ともに落ちていないことを確認
    - `渋22.svg` は `viewBox width=3556`, `plot width=2880`, 軸 `00:00-23:59`, stop 軸末尾 `弦巻営業所`, `stroke-dasharray="8 5"` の depot deadhead と `stroke-dasharray="2 6"` の depot stay を含むことを確認
    - `python -m pytest tests` → `66 passed`

- 2026-03-23 (UI: 営業所別充電器管理・充電器出力グローバルパラメータ廃止・バス導入費無効化チェックボックス追加)
  - **変更内容**:
    - `tools/scenario_backup_tk.py` の基本パラメータ欄から「充電器出力(kW)」グローバル入力を削除。充電器出力は `営業所充電器設定`（`normalChargerPowerKw` / `fastChargerPowerKw`）から参照するように統一。`use_selected_depot_charger_inventory=True` は既に有効だったため、mapper 側の動作変更はなし。
    - `simulation_settings` dict から `charger_power_kw` 送信も廃止（`PrepareSimulationSettingsBody.charger_power_kw` フィールドは残存、デフォルト 90 kW）。
    - トップバーのボタン名「営業所別車両管理」→「**営業所別充電器管理**」に変更。ウィンドウタイトルも同様に更新。車両管理は「車両・テンプレート管理」ボタンに集約。
    - 「営業所別充電器管理」画面の「選択営業所を車両タブへ反映」ボタンを削除し、「保存」ボタンのみ残した。
    - 基本パラメータ欄に **「バス導入費の日割り計算を無効化 (disable_vehicle_acquisition_cost)」チェックボックス**を追加（デフォルト OFF）。
  - **バックエンド対応**:
    - `bff/routers/simulation.py` の `PrepareSimulationSettingsBody` に `disable_vehicle_acquisition_cost: bool = False` を追加。
    - `bff/services/simulation_builder.py` の `simulation_config` dict に `disable_vehicle_acquisition_cost` を追加で渡すよう変更。
    - `bff/mappers/scenario_to_problemdata.py` の `build_problem_data_from_scenario` で `simulation_cfg.get("disable_vehicle_acquisition_cost", False)` を読み、`True` のとき全車両の `fixed_use_cost` を `dataclasses.replace` で 0.0 に上書きするよう変更。
  - **ドキュメント反映**: `docs/constant/formulation.md` O4 節・`docs/constant/implementation_status.md` O4 行を更新。
  - **既存テスト**: `tests/test_problem_builder_disable_acquisition_cost.py` が既に存在し pass 確認済み。

- 2026-03-23 (Tokyu route-family trip replication を全系統で除去し、front/back/最適化の入力 source を統一)
  - 問題は `data/built/tokyu_full/trips.parquet` / `timetables.parquet` の再生成ロジックが、GTFS trip を `routeFamilyCode + depotId` に一致する全 route variant へ複製していたことだった。代表例の `meguro / 黒01` では 587 便が family 内 9 route に複写され、`__vN` 除外後も base trip 群が先頭 route に偏って残るため、営業所路線選択・backend summary・最適化入力が route variant と一致しなかった。
  - `scripts/rebuild_built_from_normalized.py` を修正し、trip-to-route mapping を family-based replication から `trip_id` に埋め込まれた `odptPatternId` の exact match へ変更した。fallback は `(routeFamilyCode, depotId, first_stop_id, last_stop_id)` の単一候補だけに限定し、1 便を複数 route に複写しないようにした。
  - これにより `data/built/tokyu_full` を上書き再生成し、`trips.parquet=33354`, `timetables.parquet=33354`, `__vN=0` になった。`黒01` は `31 / 22 / 28 / 10 / 495 / 1` の route-variant 別 count に戻り、`587 x 9` の増殖は解消した。
  - ただし built GTFS export と `data/catalog-fast/tokyu_bus_data` の間に route-level で 4 件だけ残差（`あ28`, `空港` 2 variant, `自02`）があり得るため、現在系では `src/runtime_scope.py`, `src/research_dataset_loader.py`, `bff/services/run_preparation.py`, `bff/routers/graph.py`, `bff/routers/scenarios.py` を修正し、Tokyu 系 timetable/trip scope load は `tokyu_shards` の次に `data/catalog-fast/tokyu_bus_data` を優先するよう揃えた。これで front/back/最適化計算は built の stale/misaligned route trip count に依存しない。
  - 追加で、day-type 分離が route list 表示で落ちないよう `src/research_dataset_loader.py` の bootstrap route metadata に `tripCountsByDayType` / `tripCountTotal` を埋め込み、`bff/routers/master_data.py` の `/scenarios/{id}/routes` は `serviceId` 指定時、または scenario の現在 `dispatch_scope.serviceId` を既定 selected day として `tripCountSelectedDay` を返すよう修正した。これで route list API も total count ではなく selected day count を既定表示できる。
  - 監査として `data/catalog-fast/tokyu_bus_data` の全 764 route variant を再走査し、同一 service 内で `origin + destination + departure + arrival` が重複する route は `0`、別 route 間で exact stop-time sequence まで一致する duplicate も `0` を確認した。terminal/time だけ同じ cross-route signature は 8 件あったが、すべて stop sequence が異なる別系統だった。
  - 回帰テスト:
    - `tests/test_rebuild_built_from_normalized.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_research_dataset_bootstrap_alignment.py`
  - 確認:
    - `python -m pytest tests -q` → `78 passed`
    - `python scripts/rebuild_built_from_normalized.py` 実行済み
    - `src.runtime_scope.load_scoped_trips()` で `odpt-route-9e1a26bc3c19` は `WEEKDAY=11`、residual mismatch route `odpt-route-ff937d39d487` も runtime では `WEEKDAY=7, SUN_HOL=7` を返し、`tokyu_bus_data` 側 count と一致することを確認

- 2026-03-23 (再起動・再読込後に route trip count が壊れる問題を修正し、Tokyu route/day-type count を scenario reload でも維持)
  - 実シナリオ `2b0a60cf-61ad-4094-807c-f766641984c6` を確認すると、`outputs/scenarios/.../master_data.sqlite` の `routes` に古い `tripCount=587` が残ったまま、`artifacts.sqlite` の `timetable_rows` / `trips` が 0 件へ上書きされるケースがあった。これにより、アプリ再起動後は route list / Quick Setup が stale route metadata へフォールバックし、`黒01` をはじめ高本数系統が「平日・土曜・休日で分別されず 587 が何個もある」表示になっていた。
  - 根本原因は `bff/store/scenario_store.py` の `_load_shallow()` が heavy artifact を空既定値で埋めた doc を返し、その doc を `_save()` する経路が row/parquet artifact を丸ごと空で再保存していたことだった。`set_public_data_state()` など master-only 更新でも dispatch artifact を消し得る状態だった。
  - 対策として `scenario_store._save()` に unloaded artifact 保護を追加し、`_load_shallow()` 由来の未ロード artifact は既存 `artifacts.sqlite` / parquet / json を staging へコピーして保持するよう修正した。逆に `_invalidate_dispatch_artifacts()` で明示的に無効化した `trips` / `graph` / `duties` / result artifact は unloaded マーカーから外し、意図した invalidation はそのまま効くようにした。
  - 同時に `scenario_store._load_shallow()` / `_load()` で Tokyu の route metadata を preload master から自動補修するようにし、既存 scenario の `routes.tripCount`, `tripCountTotal`, `tripCountsByDayType` が stale でも request ごとに現行 `tokyu_bus_data` ベースの値へ戻るようにした。
  - `get_field()`, `count_field_rows()`, `page_field_rows()`, `page_timetable_rows()`, `count_timetable_rows()`, `get_field_summary()`, `summarize_route_service_trip_counts()` も、scenario artifact が空のときは `data/catalog-fast/tokyu_bus_data` へフォールバックして件数・行・route/service summary を返すよう修正した。これで stale / missing artifact があっても front/back の count 表示は current Tokyu dataset に揃う。
  - Quick Setup には追加の穴があり、summary 側が `0 便 route` を返さないため、`黒01` の 0 便 variant が `tripCountsByDayType={}` 扱いで route list に残っていた。`bff/routers/scenarios.py` で route metadata の `tripCountsByDayType` を事前 seed し、summary count は上書きマージに変更したことで、0 便 variant は非表示、正の count variant だけが selected day 別本数で残るようにした。
  - 実データ確認:
    - `bff.routers.master_data.list_routes('2b0a60cf-61ad-4094-807c-f766641984c6', service_id='WEEKDAY')` で `黒01` は `11 / 8 / 12 / 2 / 191 / 1`、`tripCountTotal` は `31 / 22 / 28 / 10 / 495 / 1` を返すことを確認
    - 同じ scenario を `meguro + WEEKDAY` 相当に正規化した Quick Setup payload では、`黒01` の 0 便 variant 3 件が消え、残る 6 variant が source 通りの day-type count を返すことを確認
  - 回帰テスト:
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_master_data_route_counts.py`
  - 確認:
    - `python -m pytest tests -q` → `82 passed`

- 2026-03-24 (固定路線バンド UI 整理・全 route family/便数監査・営業所別 PV 平均自動同期)
  - 問題として、Quick Setup 画面に「営業所内車両トレード」と「車両固定バンド」で意味の重なる操作が残っており、route 固定の要件が UI 上で曖昧だった。また route family のひも付けずれや day-type 便数ずれが front 表示だけでなく最適化入力へ混入するリスクが残っていた。
  - `tools/scenario_backup_tk.py` では営業所内 route trade の単独チェックを見せない構成に変更し、`日次路線固定（車両固定バンド）` を ON にすると `allowIntraDepotRouteSwap=False` と `enable_vehicle_diagram_output=True` を自動適用するよう整理した。最適化結果を確認しやすいよう `ダイヤグラム表示` ボタンも追加した。
  - 追加で自分から見つけた問題として、途中で `配車済み路線のみ` という別チェックを足すと既存 optimize 結果依存の分岐が増え、今回要件の route 固定と責務が混ざる状態だったため、その UI と処理は削除した。
  - `bff/services/route_catalog_audit.py` を追加し、scenario の全 route を対象に `routeFamilyCode` 欠落、派生 family code との不一致、同一営業所内の family 分裂、`data/catalog-fast/tokyu_bus_data` 実便数との差分を監査するようにした。`bff/services/run_preparation.py` は prepare 時にこの監査を必ず実行し、warning と `scope_summary.route_catalog_audit` へ結果を残すよう変更した。これにより、便数や family の不整合を黙って solver へ流さない。
  - 営業所別 PV は `data/derived/pv_profiles/*_2025-08-*_60min.json` を読み、選択営業所ごとに 2025/08 の 1 か月平均を自動生成して `depot_energy_assets` へ同期するようにした。weather mode は自由入力をやめて readonly のプルダウンに変更し、既定値を `solcast_avg_2025_08_60min` に揃えた。
  - `bff/routers/simulation.py` / `bff/services/simulation_builder.py` も更新し、prepare payload から `fixed_route_band_mode`, `enable_vehicle_diagram_output`, `objective_preset`, `pv_profile_id`, `weather_mode`, `weather_factor_scalar` を保持できるようにした。
  - 回帰テスト:
    - `tests/test_route_catalog_audit.py`
    - `tests/test_run_preparation_audit_warnings.py`
    - `tests/test_scenario_backup_tk_pv_sync.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_run_preparation_hash.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_solcast_pv_profiles.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_problem_builder_depot_energy_asset_controls.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
  - 確認:
    - `python -m py_compile bff/services/route_catalog_audit.py bff/services/run_preparation.py bff/routers/simulation.py bff/services/simulation_builder.py tools/scenario_backup_tk.py` → pass
    - 上記回帰テストの対象実行合計 → `49 passed`

- 2026-03-24 (全営業所・全 route の family 分類ロジックを再設計し、day-type trip count 欠落を補修)
  - 追加で自分から上げた問題として、`routeFamilyCode` の元ロジックが `高速` / `空港` / `直行` / `急行` / `出入庫` の generic code をそのまま family code にしており、無関係な長距離路線や直行便まで 1 family に束ねていた。その結果、`routeVariantTypeManual=main` の legacy override も相まって、`東98` のような入出庫便だけでなく、高速・空港系も正しい本線/区間便/入出庫便に落ちない状態だった。
  - `bff/services/route_family.py` では stopSequence が stop ID のまま比較されていた問題を修正し、`data/catalog-fast/tokyu_bus_data/stops.jsonl` / `normalized/stops.jsonl` から stop name を解決してから corridor 判定するよう変更した。あわせて terminal 比較は `日吉駅` と `日吉駅東口`、`溝の口駅` と `溝の口駅南口` のような駅出口差分を吸収する coarse normalization を追加した。
  - `bff/services/runtime_route_family.py` を中心に runtime 再分類を強化し、legacy `classificationSource=manual_override` は user manual override でない限り無視、同 family の depot feeder corridor まで見て `depot_in/depot_out` を判定するよう見直した。これで `東98` は `東京駅南口->清水` 系を本線、`等々力操車所` 発着や `目黒郵便局->等々力操車所` を入出庫便として正しく再分類できるようにした。
  - family code 抽出も見直し、generic code は terminal pair ベースの family code (`高速:河口湖駅⇔渋谷駅(マークシティ)` など) に再分解した。これにより `高速` 46 variant は 11 family、`空港` 79 variant は 23 family、`直行` 10 variant は 5 family、`急行` 3 variant は 2 family、`出入庫` 7 variant は 4 family に正しく分かれた。最終監査では runtime route variant count が `main_inbound=203, main_outbound=199, short_turn=134, main=94, depot_in=47, depot_out=44, branch=43, unknown=0` になり、generic code の素通し family は 0 件になった。
  - 便数側では `src/research_dataset_loader.py` の `_apply_route_day_type_counts()` に穴があり、Tokyu catalog の route index を `depot_ids` 付きで引くと営業所未割当 route の `tripCountsByDayType` だけ落ち、`tripCountTotal` だけ残る route が 254 件あった。ここは route 単位で `depot_ids=None` の fallback lookup を追加し、全 route が authoritative `tokyu_bus_data.route_trip_counts_by_day_type()` と一致するよう補修した。
  - さらに `bff/services/master_defaults.py` と `bff/store/scenario_store.py` も更新し、preload master data と既存 scenario repair の両方で全 route を `reclassify_routes_for_runtime()` に通してから保存・返却するようにした。これで API 表示だけでなく、保存済み scenario の `routes` 自体が補修済み family/variant metadata を持つ。user manual override は `classificationSource/manualClassificationLocked` ごと保持したまま再適用する。
  - 影響範囲として `bff/routers/master_data.py`, `bff/routers/scenarios.py`, `bff/routers/graph.py`, `bff/mappers/scenario_to_problemdata.py`, `src/research_dataset_loader.py` を runtime 再分類前提へ統一し、front 表示・Quick Setup・scope export・最適化入力が同じ family/variant 判定を使うよう揃えた。
  - 回帰テスト:
    - `tests/test_runtime_route_family.py`
    - `tests/test_master_defaults_runtime_repair.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_research_dataset_bootstrap_alignment.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_route_catalog_audit.py`
  - 確認:
    - `python -m py_compile bff/services/route_family.py bff/services/runtime_route_family.py src/research_dataset_loader.py tests/test_runtime_route_family.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_runtime_route_family.py tests/test_master_data_route_counts.py tests/test_quick_setup_route_selection.py tests/test_research_dataset_bootstrap_alignment.py -q` → `20 passed`
    - `PYTHONPATH=C:\master-course pytest tests/test_runtime_scope_route_mapping.py tests/test_prepared_scope_execution.py tests/test_milp_route_band_settings.py tests/test_simulation_builder_prepare_scope.py tests/test_route_catalog_audit.py -q` → `18 passed`

- 2026-03-25 (Quick Setup front に route truth を出すため、運行種別サマリと営業所路線選択 UI を再設計)
  - 問題として、route family / trip count の backend 補修後も `Quick Setup` payload が痩せており、`運行種別サマリ` は `routeCount` / `tripCount` しか持たず、`営業所・路線選択` も family label と運行種別内訳が見えなかった。そのため、`東98` のような再分類済み line でも front では「何が本線で、何が入出庫便か」が読みにくかった。
  - 追加で自分から上げた問題として、検索を掛けた状態で family の一部 variant だけを出す UI は件数と便数の誤読を生みやすかった。ここは filter を「表示対象の depot / family を絞るだけ」に限定し、表示した family の route / trip 集計は常に full truth を返す方針に直した。
  - `bff/routers/scenarios.py` の quick setup 集計を拡張し、`dayTypeSummaries` に `familyCount` と `main / shortTurn / depot / branch / unknown` の route / trip 内訳を追加した。`build_timetable_summary_for_scope()` が使えない fallback 時でも、current scenario の route metadata から selected day の summary が 0 固定にならないよう補修した。
  - 同時に depot payload も拡張し、`familyCount`, `visibleFamilyCount`, `visibleRouteCount`, `tripCountSelectedDay`, `selectedTripCount`, variant 別 route / trip count を返すよう変更した。route list は route_limit のまま返しつつ、depot summary は full visible route set から集計するため、front の総量表示が route_limit に引きずられない。
  - 2026-03-25 夜に追加で確認した問題として、Quick Setup payload が `selectedDepotIds` で route 一覧自体を絞っていたため、シナリオごとに front で見える路線が変わっていた。要件は「シナリオで変わってよいのは選択状態と曜日別便数だけ」であり、表示母集団は固定であるべきなので、payload 生成は常に全営業所・全 route を対象にし、`selectedDepotIds` / `selectedRouteIds` は check state だけへ使うよう修正した。
  - さらに `東98 / 渋41 / 渋42` を確認すると、runtime では正しく main / branch / short_turn / depot へ再分類されている一方、family header は `routeFamilyLabel=東98` のような code-only 表示のままだった。`bff/routers/scenarios.py` に family terminal label 補完を追加し、同営業所・同 family の全 variant から主系統の terminal pair を拾って `東京駅南口 ⇔ 清水`, `渋谷駅 ⇔ 大井町駅`, `渋谷駅 ⇔ 大崎駅西口` のような表示へ置き換えた。
  - `tools/scenario_backup_tk.py` では `運行種別サマリ` を `service / 種別 / familyCount / variantCount / tripCount / 運行種別内訳` 表示へ拡張した。`営業所・路線選択` には検索ボックス、表示/選択サマリ、family label の `code | label` 表示、depot/family 行の `本線 / 区間 / 入出庫 / 枝線` 便数内訳を追加した。
  - route filter は `routeFamilyCode`, `routeFamilyLabel`, `routeLabel`, `variantLabel`, `depotId` などを対象に全文検索しつつ、open した family の child route は full family variant を見せるようにした。これで `東98` と打った時も、該当 family を見つけたあとに本線・入出庫便の全 variant をそのまま確認できる。
  - 回帰テスト:
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_master_data_route_counts.py`
    - `tests/test_runtime_scope_route_mapping.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_route_catalog_audit.py`
  - 確認:
    - `python -m py_compile bff/routers/scenarios.py tools/scenario_backup_tk.py tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py` → pass
    - `PYTHONPATH=C:\master-course pytest tests/test_quick_setup_route_selection.py tests/test_scenario_backup_tk_dataset_options.py -q` → `20 passed`
    - `PYTHONPATH=C:\master-course pytest tests/test_master_data_route_counts.py tests/test_runtime_scope_route_mapping.py tests/test_simulation_builder_prepare_scope.py tests/test_route_catalog_audit.py -q` → `10 passed`

- 2026-03-26 (Quick Setup「設定保存」で基本パラメータ一式が保存されない不具合を修正)
  - 問題として、`tools/scenario_backup_tk.py` の `設定保存`（`save_quick_setup`）が `initial_soc / soc_min / soc_max / disable_vehicle_acquisition_cost / tou_pricing / no_improvement_limit / destroy_fraction` を API へ送っておらず、再読込時に基本パラメータ欄と ALNS 関連が既定値へ戻る状態だった。
  - 追加で backend 側でも `bff/routers/scenarios.py` の `UpdateQuickSetupBody` が上記キーを受理しておらず、フロントで送っても保存できない経路があった。
  - 対応として、Quick Setup API の request/response を拡張し、`solverSettings` と `simulationSettings` の双方で `noImprovementLimit / destroyFraction / initialSoc / socMin / socMax / disableVehicleAcquisitionCost / touPricing` を往復できるようにした。
  - `update_quick_setup()` では `scenario_overlay`（solver/cost）と `simulation_config` へ同キーを保存する処理を追加し、`load_quick_setup()` は TOU 配列を UI テキストへ復元するフォーマッタを追加して再表示できるようにした。
  - これにより、`バス導入費の日割り計算を無効化` を含む基本パラメータの保存漏れが解消され、再Prepare時の設定ドリフトを抑制した。

- 2026-03-31 (結果画面で非ゼロの最適化内訳を前面表示し、API 保存済み結果と UI の見え方を一致させた)
  - 問題として、BFF の `optimization_result` には `driver_cost / vehicle_cost / penalty_unserved / total_cost` が非ゼロで保存されている一方、`tools/scenario_backup_tk.py` の Summary タブは `energy_cost` など一部しか拾わず、`summary.trip_count_served / trip_count_unserved / vehicle_count_used` も表示していなかった。そのため「結果は出ているのに、フロントでは内訳が見えない」状態になっていた。
  - 追加で自分から上げた問題として、cost breakdown の表示順が未定義で、payload に存在しない primary key まで空行で出す余地があり、非ゼロ項目を素早く確認しにくかった。
  - 対応として `tools/scenario_backup_tk.py` に結果表示用ラベル・数値整形・cost breakdown 並び替え helper を追加し、Summary タブで `総コスト / 担当便数 / 未担当便数 / 使用車両数 / 電力コスト / 車両コスト / 乗務員コスト / 未担当ペナルティ` を非ゼロ強調付きで表示するようにした。
  - さらに `Cost Breakdown` タブを新設し、`total_cost` を先頭に非ゼロ項目を上段へ並べ、`share` 列で構成比も見えるようにした。`Details` タブも `summary` ブロックを含めて表示し、`cost_breakdown` は同じ並び順で確認できるよう揃えた。比較画面も同じメトリクス群に拡張している。
  - 実データ確認として、`GET /api/scenarios/237d5623-aa94-4f72-9da1-17b9070264be/optimization` の最新結果から `total_cost=6052927.3224609075`, `served_trips=638`, `unserved_trips=336`, `vehicle_count_used=55`, `energy_cost=202796.50054309692`, `vehicle_cost=483447.4885844756`, `driver_cost=2006683.333333335`, `penalty_unserved=3360000.0` を UI helper が正しく抽出できることを確認した。
  - 回帰テスト:
    - `tests/test_scenario_backup_tk_dataset_options.py`
    - `tests/test_scenario_backup_tk_pv_sync.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py tests/test_scenario_backup_tk_dataset_options.py` → pass
    - `$env:PYTHONPATH='C:\master-course'; pytest tests\test_scenario_backup_tk_dataset_options.py tests\test_scenario_backup_tk_pv_sync.py -q` → `15 passed`

- 2026-03-31 (フロントのコスト UI 重複整理、粒度の細かい cost flags、day type 切替時の route 母集団固定)
  - 問題として、`tools/scenario_backup_tk.py` には `disable_vehicle_acquisition_cost` 単独チェックと `車両コスト / 運転士コスト / その他コスト` の表が同居しており、同じ責務が二重化していた。さらに `その他コスト` は中身が曖昧で、UI 上 OFF にしても solver 側で何が止まるのか説明できなかった。
  - 追加で自分から上げた問題として、MILP 側の `unserved_penalty_weight = max(..., 10000)` により、未配車ペナルティを OFF にしても MILP では効き続ける実装ズレがあった。また左パネルは day type 切替時に route 一覧そのものを絞っており、以前の要件「変わってよいのは便数だけ」に反していた。
  - `src/optimization/common/cost_components.py` を新設し、front / BFF / common builder / evaluator / MILP adapter が共有する `cost_component_flags` 定義を追加した。公開するチェック項目は `vehicle_fixed_cost`, `driver_cost`, `electricity_cost`, `fuel_cost`, `demand_charge_cost`, `co2_cost`, `unserved_penalty`, `switch_cost`, `battery_degradation_cost`, `deviation_cost`, `contract_overage_penalty` と、MILP 専用の `charge_session_start_penalty`, `slot_concurrency_penalty`, `early_charge_penalty`, `soc_upper_buffer_penalty`, `final_soc_target_penalty`, `grid_to_bus_priority_penalty`, `grid_to_bess_priority_penalty` である。
  - `tools/scenario_backup_tk.py` は重複していた単独 acquisition checkbox と 3 分類トグルを削除し、単一の `目的関数に含めるコスト項目` 表へ置き換えた。Quick Setup load/save/prepare は `costComponentFlags` で round-trip し、旧シナリオの `disableVehicleAcquisitionCost / enableVehicleCost / enableDriverCost / enableOtherCost` は互換変換して読み込む。あわせて route 検索文字列を cache 化し、day type 切替では route 一覧を再フィルタせず便数表示だけ更新するよう変更した。
  - `bff/routers/scenarios.py`, `bff/routers/simulation.py`, `bff/services/simulation_builder.py` は `costComponentFlags` / `cost_component_flags` を保存・prepare payload へ通すよう更新した。旧 booleans も読み書き互換は残しているが、正本は `simulation_config.cost_component_flags` とした。
  - `src/optimization/common/builder.py` は granular flags を canonical problem metadata に載せ、objective weights と MILP metadata penalty を項目単位で 0 化するように変更した。legacy `disable_vehicle_acquisition_cost` の挙動も見直し、表示どおり acquisition cost を本当に 0 にするよう修正した。`src/optimization/common/evaluator.py` は `electricity_cost` と `fuel_cost`、`contract_overage_penalty` などを個別に 0 化する。`src/optimization/milp/solver_adapter.py` も同 flags を見て各 objective term を条件付けし、`unserved_penalty=OFF` で未配車項目が残らないよう修正した。
  - 回帰テスト:
    - `tests/test_quick_setup_advanced_persistence.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_problem_builder_cost_component_toggles.py`
    - `tests/test_problem_builder_disable_acquisition_cost.py`
    - `tests/test_quick_setup_route_selection.py`
    - `tests/test_scenario_backup_tk_dataset_options.py`
  - 確認:
    - `python -m py_compile tools/scenario_backup_tk.py bff/routers/scenarios.py bff/routers/simulation.py bff/services/simulation_builder.py src/optimization/common/cost_components.py src/optimization/common/builder.py src/optimization/common/evaluator.py src/optimization/milp/solver_adapter.py tests/test_quick_setup_advanced_persistence.py tests/test_simulation_builder_prepare_scope.py tests/test_problem_builder_cost_component_toggles.py tests/test_scenario_backup_tk_dataset_options.py` → pass
    - `$env:PYTHONPATH='C:\master-course'; pytest tests\test_quick_setup_advanced_persistence.py tests\test_simulation_builder_prepare_scope.py tests\test_problem_builder_cost_component_toggles.py tests\test_scenario_backup_tk_dataset_options.py -q` → `18 passed`
    - `$env:PYTHONPATH='C:\master-course'; pytest tests\test_problem_builder_disable_acquisition_cost.py tests\test_quick_setup_route_selection.py -q` → `12 passed`
- 2026-04-05 (fixed scope の code-caused unserved 17 便を修理し、actual BFF path で `974/974 served` を回復)
  - 問題として、deadhead alias 修理後の actual canonical run では `957 served / 17 unserved` が再現していた。unserved は `黒06`, `渋21`, `反12`, `都立34` に出ていたが、各便は depot から到達可能で前後接続数も十分あり、aggregate feasible graph の最小 duty 数も `87` で scope fleet `95` 台以下だった。したがって fleet infeasibility ではなく baseline duty cover の組み方が原因と判断した。
  - さらに自分から上げた問題として、`tsurumaki` のような depot id と `odpt.BusstopPole:...Tsurumakieigyousho...` のような depot stop id が alias 同値でも、0 分 deadhead を「同地点」ではなく「missing deadhead」と扱う箇所が残っていた。これが startup reachability と path cover の start 判定を落としていた。
  - `src/dispatch/models.py` に `DispatchContext.locations_equivalent()` を追加し、alias 展開後の location 集合が交差していれば同地点とみなせるようにした。`src/dispatch/feasibility.py` の location continuity もこの helper を使うよう変更し、alias 同値の 0 分 deadhead を missing 扱いしないよう揃えた。
  - `src/optimization/common/builder.py` は fully shared scope 判定を追加し、その場合は per-type greedy duty ではなく pooled shared path-cover baseline を使って actual fleet 全体で duty cover を構築するようにした。scope が fully shared でない場合は既存 per-type fallback を残しているため、数学的意味を広く変えずに current bug を潰している。
  - これにより scoped baseline は `dispatch_pooled_shared_path_cover_baseline`, `served=974`, `unserved=0`, `vehicle_count_used=87` へ改善した。actual BFF rerun でも `mode_milp_only=time_limit_baseline`, `mode_alns_only=feasible`, `mode_ga_only=feasible`, `mode_abc_only=feasible` の全てで `974/974 served` を確認した。objective は `ALNS=3453137.5192`, `GA=3490088.7734`, `ABC=3508589.5957`, `MILP fallback=3536498.7170` だった。
  - 出力 parity も合わせて確認し、旧 `output/run_20260324_2210` に対する generic artifact missing は 4 モードとも 0 件だった。比較 bundle は `output/reports/20260405_fixed_scope_237d5623_unserved_fix/`、報告書は `docs/fixed_scope_unserved_fix_report_20260405.md` に保存した。
  - 回帰テスト:
    - `tests/test_dispatch_context_location_aliases.py`
    - `tests/test_pooled_shared_baseline.py`
    - `tests/test_baseline_vehicle_type_priority.py`
    - `tests/test_vehicle_assignment_startup_deadhead.py`
    - `tests/test_canonical_graph_export_parity.py`
    - `tests/test_milp_baseline_fallbacks.py`
    - `tests/test_route_family_deadhead_inference.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_optimization_result_serializer.py`
  - 確認:
    - `python -m pytest tests/test_dispatch_context_location_aliases.py tests/test_pooled_shared_baseline.py tests/test_baseline_vehicle_type_priority.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_canonical_graph_export_parity.py tests/test_milp_baseline_fallbacks.py tests/test_route_family_deadhead_inference.py tests/test_problem_builder_timestep_and_pv_scaling.py -q` → `21 passed`
    - `python -m pytest tests/test_optimization_canonical_metaheuristics.py tests/test_prepared_scope_execution.py tests/test_optimization_result_serializer.py -q` → `9 passed`

- 2026-04-05 (report bundle に route-band 図と solver 比較表を明示出力)
  - 問題として、fixed-scope rerun の source run には `graph/route_band_diagrams/*.svg` が生成されているのに、`output/reports/20260405_fixed_scope_237d5623_unserved_fix/` 側には `solver_comparison.svg` と bus operation 図しかなく、旧 `output/run_20260324_2210/graph/route_band_diagrams/` に相当する路線バンド図の参照先が bundle 内に無かった。
  - 追加で自分から上げた問題として、比較 bundle には `comparison.csv` があっても、「solver ごとの計算時間・objective・served/unserved を 1 枚の表で見る」用途に対して列名と保存先が明示されておらず、教授向け確認で辿りにくかった。
  - `tools/_visualizer_report_utils.py` に solver 比較表 writer と route-band asset exporter を追加し、`solver_comparison_table.csv/.md` を出力できるようにした。route-band は best objective run を `graph/route_band_diagrams/` へ旧 run 互換で複製し、各 solver run の原本も `solver_route_band_diagrams/<mode>_<run_id>/` へ束ねる。どの run から複製したかは `solver_route_band_diagrams_manifest.json` に残す。
  - `tools/multi_run_visualizer_tk.py` の `Export Selected` も同 helper を呼ぶよう更新し、比較表・教授向けレポート・比較図に加えて route-band 図一式を export するようにした。`professor_report.md` には best run の source `route_band_diagrams` 位置も追記している。
  - actual bundle も再生成し、`output/reports/20260405_fixed_scope_237d5623_unserved_fix/graph/route_band_diagrams/` に ALNS best run の band 図、`output/reports/20260405_fixed_scope_237d5623_unserved_fix/solver_comparison_table.csv` と `.md` に 4 solver の計算時間・objective・served/unserved 表、`output/reports/20260405_fixed_scope_237d5623_unserved_fix/solver_route_band_diagrams/` に per-solver 図一式を置いた。
  - README も更新し、current report 出力 root が `output/` であることと、fixed-scope rerun bundle / route-band 図 / solver 比較表の保存先を明記した。
  - 回帰テスト:
    - `tests/test_visualizer_report_utils.py`
  - 確認:
    - `python -m pytest tests/test_visualizer_report_utils.py -q` → `5 passed`
    - `python -m py_compile tools/_visualizer_report_utils.py tools/multi_run_visualizer_tk.py` → pass

- 2026-04-06 (fixed scope 237d の startup deadhead / speed-cap / route-band 標準出力 / metaheuristic mode 反映をまとめて補修)
  - 問題として、actual canonical path にはまだ 4 つの未修整点が残っていた。`bff/routers/optimization.py` が `warm_start=opt_mode != MILP` だったため MILP warm start が実 run では無効、startup deadhead は baseline/assignment では注入しても MILP `start_arc` には depot 到達不能を止める制約が無く、deadhead merge は configured `deadhead_speed_kmh` を全 call path で受け取っておらず、`fixedRouteBandMode=true` でも canonical export は `enable_vehicle_diagram_output` が false だと route-band 図を落としていた。
  - 追加で自分から上げた問題として、GA/ABC wrapper が distinct mode config を設定しても ALNS engine 側が simulated annealing + adaptive roulette を固定で使っており、wrapper の `genetic_like` / `bee_colony_like` が実際には solver metadata へ反映されていなかった。
  - `src/route_family_runtime.py` の `merge_deadhead_metrics()` は `deadhead_speed_kmh` を上限に既存・推論 metric を再拘束するよう更新し、`bff/mappers/scenario_to_problemdata.py`、`bff/routers/graph.py`、`src/optimization/common/builder.py` から同 speed を必ず渡すよう揃えた。これにより deadhead speed parameter を strict upper bound として使う current call path が成立した。
  - `src/optimization/common/builder.py` の pooled shared baseline から「初便への startup deadhead が departure より長いと候補から除外する」条件を外し、simulation horizon 前からの回送開始を許容した。これは feasibility の本体 `arrival + turnaround + deadhead <= next departure` は変えず、初便前の horizon 外 deadhead を禁止しないだけなので dispatch 数学条件自体は維持している。
  - `src/dispatch/models.py`, `src/optimization/common/vehicle_assignment.py`, `src/optimization/common/feasibility.py`, `src/optimization/milp/solver_adapter.py` を通して、depot alias 等価を使った startup path existence 判定を追加した。既知 missing path の vehicle/start trip 組は baseline assignment でも MILP `start_arc` でも禁止し、逆に path が存在する限りは「05:00 より前からの回送」「23:00 後の帰庫」を horizon 外として許容する。
  - `bff/routers/optimization.py` は canonical export 条件を見直し、`fixedRouteBandMode=true` なら route-band SVG を標準出力するようにした。同時に canonical run path の MILP `warm_start=True` も回復させた。`src/optimization/alns/acceptance.py`, `src/optimization/alns/selection.py`, `src/optimization/alns/engine.py`, `src/optimization/ga/engine.py`, `src/optimization/abc/engine.py` では acceptance / operator-selection factory を追加し、GA=`genetic_like`, ABC=`bee_colony_like` が実 metadata に出るよう修正した。
  - fixed scope rerun は actual canonical BFF path で再実行し、run directory は `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260406_0110/`, `.../mode_alns_only/.../run_20260406_0114/`, `.../mode_ga_only/.../run_20260406_0119/`, `.../mode_abc_only/.../run_20260406_0125/` に保存した。comparison bundle は `output/reports/20260406_fixed_scope_237d5623_model_fix/`、教授向けレポートは `docs/fixed_scope_model_fix_report_20260406.md` に保存している。
  - rerun 結果は `MILP=time_limit_baseline, objective=3548573.795919167, served=974, unserved=0, vehicles=87`, `ALNS=feasible, objective=3534994.692990817, served=974, unserved=0, vehicles=88`, `GA=feasible, objective=3542971.744454992, served=974, unserved=0, vehicles=88`, `ABC=feasible, objective=3542971.744454992, served=974, unserved=0, vehicles=88` だった。4 solver とも欠便は 0 だが、MILP は `supports_exact_milp=false`, `termination_reason=time_limit`, `incumbent_history_count=0` の fallback であり、exact MILP とは言えない。
  - 出力 parity は `output/reports/20260406_fixed_scope_237d5623_model_fix/artifact_parity_vs_run_20260324_2210.json` で確認し、旧 `output/run_20260324_2210` に対する generic artifact missing は 0 件だった。新 run は `canonical_solver_result.json`, `optimization_result.json`, `optimization_audit.json`, `solver_result.json`, `run_manifest.json`, `kpi_summary.json` を追加で持つ。
  - 回帰テスト:
    - `tests/test_route_family_deadhead_inference.py`
    - `tests/test_vehicle_assignment_startup_deadhead.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_canonical_graph_export_parity.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_metaheuristic_mode_configs.py`
    - `tests/test_milp_baseline_fallbacks.py`
    - `tests/test_baseline_vehicle_type_priority.py`
    - `tests/test_pooled_shared_baseline.py`
    - `tests/test_problem_builder_timestep_and_pv_scaling.py`
    - `tests/test_visualizer_report_utils.py`
  - 確認:
    - `python -m pytest tests/test_route_family_deadhead_inference.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_milp_route_band_settings.py tests/test_canonical_graph_export_parity.py tests/test_optimization_canonical_metaheuristics.py tests/test_metaheuristic_mode_configs.py -q` → `34 passed`
    - `python -m pytest tests/test_milp_baseline_fallbacks.py tests/test_baseline_vehicle_type_priority.py tests/test_pooled_shared_baseline.py tests/test_problem_builder_timestep_and_pv_scaling.py tests/test_visualizer_report_utils.py tests/test_route_family_deadhead_inference.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_milp_route_band_settings.py tests/test_canonical_graph_export_parity.py tests/test_optimization_canonical_metaheuristics.py tests/test_metaheuristic_mode_configs.py -q` → `49 passed`
    - `python -m py_compile bff/mappers/scenario_to_problemdata.py bff/routers/graph.py bff/routers/optimization.py src/dispatch/models.py src/optimization/abc/engine.py src/optimization/alns/acceptance.py src/optimization/alns/engine.py src/optimization/alns/selection.py src/optimization/common/builder.py src/optimization/common/feasibility.py src/optimization/common/vehicle_assignment.py src/optimization/ga/engine.py src/optimization/milp/solver_adapter.py src/route_family_runtime.py` → pass

- 2026-04-06 (charging breakdown 出力の標準化と補助出力 failure の隔離)
  - 問題として、canonical optimizer は plan/evaluator の内部には `grid_to_bus`, `pv_to_bus`, `bess_to_bus`, `pv_to_bess`, `grid_to_bess`, `contract_over_limit_kwh` を持っていても、run 出力では `site_power_balance.csv` が集約不足、`canonical_solver_result.json` は depot-slot ごとの flow map を保持せず、heuristic plan では `graph/depot_power_timeseries_5min.csv` も source split が空になり得た。これでは「いくら系統から買って、PV/BESS から何をもらい、契約上限超過で罰金を食ったか」を run artifact だけで説明できなかった。
  - 追加で自分から上げた問題として、`_run_optimization()` が charging summary の補助 payload を組み立てる途中で例外を起こすと、最適化自体は終わっていても `optimization_result` 保存全体が止まっていた。補助出力の失敗が solver result の保存を巻き込むのは current call path 上の設計不備だった。
  - `src/optimization/common/result.py` は assignment plan の `grid_to_bus_kwh_by_depot_slot`, `pv_to_bus_kwh_by_depot_slot`, `bess_to_bus_kwh_by_depot_slot`, `pv_to_bess_kwh_by_depot_slot`, `grid_to_bess_kwh_by_depot_slot`, `pv_curtail_kwh_by_depot_slot`, `bess_soc_kwh_by_depot_slot`, `contract_over_limit_kwh_by_depot_slot` を `canonical_solver_result.json` へ直列化するよう修正した。
  - `bff/routers/optimization.py` には canonical charging flow 正規化 helper を追加し、explicit per-source flow が plan にある場合はそれを使い、無い場合だけ `charging_slots` から grid-origin bus charging を診断的に再構成するようにした。この場合は `source_provenance_exact=false` と note を残すため、PV/BESS split を捏造しない。
  - `socMax` / `soc_max` は canonical metadata の `charge_upper_buffer_ratio` に接続し、postsolve で追加された営業所待機充電は `charging_slots` に実体化される。これにより `electricity_cost_final`, `realized_ev_charge_cost`, `grid_import_total_kwh`, `demand_charge_cost` が変わり、`vehicle_timeline.csv` / `all_vehicles.svg` も変化するため、旧 KPI とは比較条件が一致しない。
  - rich run 出力は `charging_summary.(json/csv)`, `depot_energy_flows.(json/csv)`, 拡張 `site_power_balance.csv`, 拡張 `graph/depot_power_timeseries_5min.csv` を標準で書くようにした。出力には `grid_to_bus_kwh`, `pv_to_bus_kwh`, `bess_to_bus_kwh`, `pv_to_bess_kwh`, `grid_to_bess_kwh`, `pv_curtail_kwh`, `grid_import_total_kwh`, `peak_grid_import_kw`, `contract_limit_kw`, `contract_over_limit_kwh`, `contract_limit_exceeded`, `contract_overage_cost_jpy`, `demand_charge_cost_jpy`, `grid_purchase_cost_jpy`, `electricity_cost_jpy` を含める。
  - `contract_over_limit_kwh_by_depot_slot` が plan に無い場合でも、`grid_import_kw > contract_limit_kw` なら slot 幅から over-limit energy を診断的に再導出するようにした。これにより「契約上限超過は起きているのに CSV 上 0」の矛盾を防いでいる。
  - `_run_optimization()` は charging payload 生成を defensive に包み、補助出力だけが失敗した場合は `charging_summary_warning` と `solver_metadata.warnings[]` を残して optimization result 本体は保存するようにした。これは補助 export 経路の堅牢化であり、最適化モデルの数学的意味は変えていない。
  - 回帰テスト:
    - `tests/test_optimization_result_serializer.py`
    - `tests/test_canonical_graph_export_parity.py`
    - `tests/test_canonical_result_to_simulation_bridge.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_visualizer_report_utils.py`
  - 確認:
    - `python -m pytest tests/test_prepared_scope_execution.py tests/test_optimization_canonical_metaheuristics.py tests/test_visualizer_report_utils.py tests/test_optimization_result_serializer.py tests/test_canonical_graph_export_parity.py tests/test_canonical_result_to_simulation_bridge.py -q` → `44 passed`
    - `python -m py_compile bff/routers/optimization.py src/optimization/common/result.py` → pass

- 2026-04-06 (車両別の運用・回送・充電を横棒で出す標準 SVG を追加)
  - 問題として、`graph/route_band_diagrams/*.svg` は route family 単位の time-space 図なので、「各バスがいつ運用・回送・充電しているか」を車両単位に横棒で一望したい用途には向いていなかった。`vehicle_timeline.csv` は持っていても、先生向け確認にそのまま出せる標準 SVG が無かった。
  - 追加で自分から上げた問題として、multi-day 用の `_filter_timeline_rows_for_day()` が ISO datetime を day offset 付きで処理できず、日跨ぎ run で day ごとの図を切ると誤選別する可能性があった。
  - `src/result_exporter.py` に `vehicle_operation_diagrams/manifest.json` と `all_vehicles.svg` を生成する asset builder / writer を追加した。縦軸は車両、横軸は時刻で、`service` は路線ラベル付きバー、`deadhead` は回送、`charge` は充電、`refuel` は給油として色分けしている。legacy graph export と canonical BFF graph export の両方から同 helper を呼ぶようにしたため、今後の標準出力で同じ図が揃う。
  - `bff/routers/optimization.py` は `enableVehicleDiagramOutput=false` でも `vehicle_operation_diagrams` は常時 graph export へ含めるようにした。route-band は従来どおり flag 依存だが、車両別横棒図は `vehicle_timeline.csv` から直接出せるため標準 artifact とした。
  - `tools/bus_operation_visualizer_tk.py` も更新し、`図A` を「車両別 運用・回送・充電タイムライン」に差し替えた。loader は `charge/refuel` 行も取り込み、運用バー内に route label を載せる。
  - `_filter_timeline_rows_for_day()` は base date を ISO timestamp から推定し、absolute minute で day 切り分けるよう修正した。これは graph export の day 別 SVG 切り出しの正しさを改善するもので、dispatch feasibility や最適化モデルの数学的意味は変えていない。
  - 回帰テスト:
    - `tests/test_graph_export_vehicle_operation_diagrams.py`
    - `tests/test_graph_export_route_band_diagrams.py`
    - `tests/test_canonical_graph_export_parity.py`
    - `tests/test_bus_operation_visualizer_tk.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_visualizer_report_utils.py`
  - 確認:
    - `python -m pytest tests/test_prepared_scope_execution.py tests/test_optimization_canonical_metaheuristics.py tests/test_visualizer_report_utils.py tests/test_canonical_graph_export_parity.py tests/test_graph_export_route_band_diagrams.py tests/test_graph_export_vehicle_operation_diagrams.py tests/test_bus_operation_visualizer_tk.py -q` → `21 passed`
    - `python -m py_compile src/result_exporter.py bff/routers/optimization.py tools/bus_operation_visualizer_tk.py` → pass

- 2026-04-06 (route-band truthfulness fix: prepared scope flag propagation, fragment transition repair, latest 4-solver rerun)
  - 問題として、fixed prepared scope の actual BFF run では `fixedRouteBandMode=true` を UI/Scenario 側で保存していても、`materialize_scenario_from_prepared_input()` が stale prepared payload の `fixedRouteBandMode=false` を runtime 側へ再注入していた。そのため `run_20260406_0110` 系の結果は route-band が事実上 OFF のまま 974/974 を出し、同一車両が同日中に多数の route family を行き来していた。
  - 追加で自分から上げた問題として、route-band を ON に戻したあとも、同一車両に複数 fragment を積む際に「前 fragment の終点から次 fragment の始点へ物理的に行けるか」を十分に見ていなかった。same-band でも fragment ごとに depot から再出発したように扱われ、見かけ上は 974/974 でも `vehicle_timeline.csv` 上は同一車両が重複して depot から出ている truthfulness bug があった。これは previous KPI claims を無効化し得る種類の欠陥である。
  - `bff/store/scenario_store.py`, `bff/routers/simulation.py`, `src/optimization/common/builder.py`, `bff/services/run_preparation.py`, `bff/routers/graph.py` を修正し、route-band flag と diagram flag を current scenario runtime 設定から必ず引き継ぐようにした。prepared trip/vehicle/stops は固定するが、solver/simulation runtime flags は stale prepared payload で上書きしない。
  - `src/dispatch/route_band.py` を拡張し、fragment 間の直接接続 feasibility (`direct`) と depot-reset feasibility を分離した。same-band fragment は `arrival + turnaround + deadhead <= next departure` を満たす direct connection なら duty 結合を許可し、cross-band change は depot-reset feasible な場合だけ許可する。
  - `src/optimization/common/vehicle_assignment.py` は fragment insertion 時に direct/depot transition feasibility を見るようにし、`src/optimization/common/feasibility.py` は車両別 fragment 連続性を same-band direct/depot・cross-band depot-reset のルールで再検証するよう更新した。`src/optimization/engine.py` には common post-solve truthfulness repair を追加し、solver 出力 duty を一度 vehicle fragment reassignment に掛け直し、same-band で直接つなげられる fragment は 1 duty に結合したうえで charging/SOC を再計算してから export する。
  - この修理は数学的意味を厳しくする。以前の 974/974 served は current route-band semantics に対して過大だった可能性が高く、今後の比較はこの fix 後の run を正本とする。
  - fixed scope `237d5623-aa94-4f72-9da1-17b9070264be` / `prepared-11efb997690030ef` を actual canonical BFF path で再実行し、run directory は `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260406_1117/`, `.../mode_alns_only/.../run_20260406_1122/`, `.../mode_ga_only/.../run_20260406_1128/`, `.../mode_abc_only/.../run_20260406_1133/` に保存した。comparison/report bundle は `output/reports/20260406_route_band_standard_rerun/` にまとめ、`comparison.json/csv`, `solver_comparison_table.md/csv`, `verdict.md`, `professor_report.md`, per-solver `route_band_diagrams` / `vehicle_operation_diagrams` を配置した。
  - rerun 結果は `MILP=optimal, served=880, unserved=94, objective=3541278.159964823`, `ALNS=feasible, served=889, unserved=85, objective=4246492.788347095`, `GA=infeasible_candidate(backend) -> exported feasible, served=887, unserved=87, objective=4259515.117011707`, `ABC=infeasible_candidate(backend) -> exported feasible, served=887, unserved=87, objective=4259515.117011707` だった。4 solver とも exported plan の infeasibility count は 0、all 95 vehicles were used、route-band SVG は `15-16` ファイル生成された。MILP backend status は `optimal` だが、exported objective は post-solve repaired plan の値であることを `solver_metadata.backend_objective_value_raw` と `postsolve_*` flags に残している。
  - 回帰テスト:
    - `tests/test_vehicle_assignment_startup_deadhead.py`
    - `tests/test_optimization_engine_postsolve.py`
    - `tests/test_milp_route_band_settings.py`
    - `tests/test_prepared_scope_execution.py`
    - `tests/test_scenario_store_dispatch_scope_overlay.py`
    - `tests/test_simulation_builder_prepare_scope.py`
    - `tests/test_optimization_canonical_metaheuristics.py`
    - `tests/test_canonical_graph_export_parity.py`
  - 確認:
    - `python -m pytest tests/test_vehicle_assignment_startup_deadhead.py tests/test_optimization_engine_postsolve.py tests/test_milp_route_band_settings.py -q` → `26 passed`
    - `python -m pytest tests/test_prepared_scope_execution.py tests/test_scenario_store_dispatch_scope_overlay.py tests/test_simulation_builder_prepare_scope.py tests/test_vehicle_assignment_startup_deadhead.py tests/test_milp_route_band_settings.py tests/test_optimization_canonical_metaheuristics.py tests/test_canonical_graph_export_parity.py tests/test_optimization_engine_postsolve.py -q` → `48 passed`
    - `python -m py_compile src/dispatch/route_band.py src/optimization/common/vehicle_assignment.py src/optimization/common/feasibility.py src/optimization/engine.py` → pass

- 2026-04-06 (BYD K8 2.0 を 20 台追加した fixed-scope variant の 4-solver rerun)
  - 追加確認として、truthful route-band fix 後の fixed scope `237d5623-aa94-4f72-9da1-17b9070264be` に対し、prepared input `prepared-11efb997690030ef` を複製した variant `prepared-11efb997690030ef-byd20` を作成し、`BYD K8 2.0 x 20` を vehicle list へ追加した。trip/stops/timetable_rows は変えず、fleet のみ 95 台→115 台へ増やした。
  - actual canonical BFF path で rerun し、run directory は `output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_milp_only/tsurumaki/WEEKDAY/run_20260406_1316/`, `.../mode_alns_only/.../run_20260406_1322/`, `.../mode_ga_only/.../run_20260406_1327/`, `.../mode_abc_only/.../run_20260406_1332/` に保存した。comparison/report bundle は `output/reports/20260406_route_band_standard_rerun_byd20/` にまとめた。
  - 結果は `MILP=879/974 served, objective=3808291.7437037476, backend optimal`, `ALNS=974/974 served, objective=3735779.2658425607`, `GA=974/974 served, objective=3759781.965055769`, `ABC=974/974 served, objective=3759781.965055769` だった。4 solver とも exported plan の infeasibility count は 0 で、route-band 図と vehicle-operation 図を標準出力している。
  - 95 台 truthful baseline との比較では `ALNS +85 served`, `GA +87 served`, `ABC +87 served` と改善し、metaheuristics は full service を回復した。一方で MILP は backend `optimal` でも exported plan は `879/974` に留まり、exact backend model が fragment-transition truthfulness をまだ完全には内包していないことが再確認された。
  - 実験 artifact:
    - `output/reports/20260406_route_band_standard_rerun_byd20/comparison.json`
    - `output/reports/20260406_route_band_standard_rerun_byd20/solver_comparison_table.md`
    - `output/reports/20260406_route_band_standard_rerun_byd20/verdict.md`
    - `output/reports/20260406_route_band_standard_rerun_byd20/professor_report.md`

- 2026-04-07 (BYD+20 direct prepared-scope MILP rebuild / quantitative re-evaluation)
  - 自分で追加確認した問題として、MILP だけが service occupancy を `price_slots` 単位で `sum(y)<=1` にしており、1 時間 timestep では同じ hour slot 内の back-to-back trip まで重複扱いしていた。これは dispatch hard rule ではなく MILP 側だけの粗い近似で、truthful baseline warm start 自体を model-infeasible にしていた。
  - `src/optimization/milp/solver_adapter.py` でこの coarse occupancy を廃止し、exact minute interval から maximal overlap clique を作って vehicle ごとに `sum(y)<=1` を掛ける方式へ置き換えた。これで hard feasibility `arrival + turnaround + deadhead <= next departure` は維持したまま、同一 slot 内の sequential trip を不当に落とさない。
  - 併せて `src/optimization/engine.py` に `truthful_baseline_guardrail` を追加した。MILP candidate を postsolve truthfulness repair 後に評価し、repaired baseline より served が少ない、または served 同数で objective が悪い場合は baseline 側を final export とし、`supports_exact_milp=false` / `termination_reason=truthful_baseline_guardrail` を明示する。これにより「本来担当可能なのに weaker MILP candidate を採用する」退行を止めた。
  - direct rerun は Flask/BFF endpoint を通さず `scripts/benchmark_fixed_prepared_scope.py` と同じ prepared-scope materialize + `OptimizationEngine` 直実行経路で確認した。単独 MILP check は `output/reports/20260407_byd20_direct_milp_rebuild_check/`、4 solver comparison bundle は `output/reports/20260407_byd20_direct_solver_comparison/` に保存した。
  - direct 4 solver 結果は `MILP=974/974 served, objective=3759781.965055769, solver_status=truthful_baseline_guardrail, supports_exact_milp=false, solve_time=751.411s`, `ALNS=974/974 served, objective=3740426.089000456, solve_time=300.118s`, `GA=974/974 served, objective=3759781.965055769, solve_time=306.311s`, `ABC=974/974 served, objective=3759781.965055769, solve_time=302.657s` だった。旧 direct rerun `output/reports/20260407_route_band_standard_rerun_byd20_milp_fix_warmstart/summary.json` の `MILP=200/974 served, objective=8646880.138339324` から大幅に改善した。
  - MILP metadata では backend candidate 自体はまだ弱く、`milp_candidate_solver_status=time_limit`, `milp_candidate_trip_count_served=210`, `milp_candidate_postsolve_objective_value=8572253.873564899` が残っている。したがって 이번の成果は「truthful export が no-regression で full service に戻った」ことであり、「MILP backend exact incumbent が強くなった」とはまだ主張しない。
  - regression:
    - `python -m pytest tests/test_milp_route_band_settings.py tests/test_optimization_engine_postsolve.py -q` → `23 passed`
    - `python -m pytest tests/test_milp_baseline_fallbacks.py tests/test_prepared_scope_execution.py tests/test_optimization_canonical_metaheuristics.py tests/test_optimization_engine_postsolve.py tests/test_milp_route_band_settings.py -q` → `33 passed`
    - `python -m py_compile src/optimization/milp/solver_adapter.py src/optimization/engine.py scripts/benchmark_fixed_prepared_scope.py` → pass
  - ついでに再現性上の問題として、`scripts/benchmark_fixed_prepared_scope.py` を repo root から直接実行すると `bff` import に失敗していたため、script 自身が repo root を `sys.path` に足す self-bootstrap を入れた。現在は `python scripts/benchmark_fixed_prepared_scope.py ...` をそのまま実行できる。

- 2026-07-14 (Phase 3 dual-date controlled rerun: false incumbent removal and validated MIP start)
  - 対象は雨天ラベル scenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760` / 2025-08-10 と晴天ラベル scenario `771d115b-75b0-49f7-a7f0-25f259a2cd21` / 2025-08-05。`C:\Users\RTDS_admin\gurobi.lic` を `GRB_LICENSE_FILE` で明示し、Gurobi 13.0.1 / academic license（期限 2027-02-27）を actual invocation path で確認した。ライセンス本文は記録・出力していない。
  - 比較条件は Phase 3 two-stage、全264便、BEV 35台 + ICE 25台、15分 timestep、BEV初期SOC 80%、終端SOCは最低SOC以上、PV/BESS/weather policy無効、fallback無効、postsolve repair無効で固定した。両 prepared input の trip / vehicle / charger hash は一致する。このため本比較は「同一入力に対するモデル・solver挙動の再現性検証」であり、晴雨によるPV・運用影響を測る実験ではない。
  - 最初の同条件1500秒 run（`output/research_phase3_comparison_grid_only_15min_soc80/`）は両ケースとも Stage 1 incumbent `1,089,565.7919762484`、bound `360,000`、gap `66.959315%`、Stage 2 objective `31,610.64760896963` まで同一だったが、postsolve feasibility が不成立で research acceptance は棄却された。雨天 elapsed `854.988s`、晴天 `854.519s` であり、入力差に起因する有意な速度差は確認できなかった。
  - 根本原因は、同一車両に対して長い接続arcの時間区間内へ別fragmentを入れられる Stage 1 の占有制約欠落だった。trip単位の重複禁止だけでは、選択した `from_trip -> to_trip` 間の待機・回送区間を保護できず、nested/disconnected fragmentを含む偽 incumbent が成立していた。`53adc20` で service-day-awareなfragment時間占有制約を追加し、`arrival + turnaround + deadhead <= next departure` は一切緩和していない。
  - fragment修正後の同条件run（`output/research_phase3_comparison_grid_only_15min_soc80_fragment_fixed/`）は、雨天・晴天とも Stage 1がtime limitまで incumbentなし、Stage 2未実行となった。雨天 elapsed `859.382s`、晴天 `861.961s`、boundはいずれも約`360,000`。これは「不可行の証明」ではなく「修正後の大規模モデルで時間内に初期可行解を見つけられなかった」という結果である。
  - 独立診断では、同じcanonical problemに含まれる pooled shared path-cover baselineが264/264便を32台、最大1 fragment/vehicleで担当し、`FeasibilityChecker`でも違反0だった。したがって60台条件の物理的不可行は否定された。一方、generic successor cap=8 によりbaseline接続232本中12本がStage 1 arc集合から落ち、基準解をモデル上で表現できなかった。
  - `MILPModelBuilder` は、full feasible-connection集合に実在するbaseline接続だけをsuccessor pruning後も保存するよう変更した。これは元の完全グラフにない枝を発明せず、近似的枝刈りで落とした枝を12本戻すだけで、dispatch hard constraintや完全モデルの可行領域を緩めない。車種不適合successorをcap計数へ混入させていた列挙/診断の不一致も同時に修正した。
  - Stage 1は、全対象便をちょうど一度覆い、vehicle/trip/connection/boundary/day変数がすべてモデル上に存在するbaselineだけをGurobi MIP startへ設定する。重複便、欠落便、未表現arc、欠落vehicle/dayは理由付きで拒否する。これはfallbackやsolver結果の差し替えではなく、Gurobiが検証・改善する初期解である。warm-start有無とbaseline assignment hashをexperiment identityへ追加し、適用元・arc pruning・使用台数・fragment数もsummaryへ出す。
  - 60秒診断run（`output/research_phase3_diagnostic_warm_start_60s/`）では、Stage 1は30秒allocation内で264/264便・32台・最大1 fragmentのincumbentを保持し、Stage 2は`optimal`（`0.470s`）、全postsolve validation違反0となった。Stage 1 gapは100%であり最適性は示していない。research acceptanceがfalseなのはdirty worktreeだけが理由で、最終1500秒比較はclean detached worktreeから実行する。
  - 研究上の注意として、Phase 3の`time_limit_sec=1500`はtwo-stage全体の上限で、現実装はStage 1/Stage 2へ750秒ずつ割り当てる。Stage 1がtime limitで終わった場合、全便可行性は主張できても総費用の大域最適性は主張せず、cost KPIを最適値として扱わない。
  - clean detached worktree / commit `336139f5c1a67118aaad39e8bfbb9f5bc3b1d9ab` から両ケースの最終1500秒runを完了した。出力は `output/research_phase3_comparison_grid_only_15min_soc80_warm_start/`。両ケースともresearch feasibility acceptance=true、264/264便、使用32台、最大1 fragment、Stage 1=`time_limit` + valid incumbent、Stage 2=`optimal`、全validation違反0だった。
  - 数値結果は両ケースで完全一致し、Stage 1 objective `662,824.651312606`、best bound `360,000.00000001054`、gap `45.686993%`、Stage 2 objective `11,298.960951571578`、accounting total `708,743.864890862 JPY`。`vehicle_schedule.csv` も同一SHA-256 `D0B421D178BC6C61EE1C2FDF992EC0A01219EE40D5C58CBBE71BC5B40369952E` だった。
  - solver runtimeは雨天ラベル Stage 1 `750.250s` / Stage 2 `0.256856s`、晴天ラベル Stage 1 `750.259s` / Stage 2 `0.255650s` で実質同一。wall timeは雨天 `930.968s`、晴天 `859.040s`（雨天+`71.929s`）だが、差のほぼ全量がsolver外のmodel-build/serialization overhead（雨天`180.461s`、晴天`108.525s`）であり、scheduleとsolver数値は同一である。したがってscenario固有の難しさではなく、run order、cache、machine load等の実行時揺らぎと解釈する。
  - 比較表・機械可読集計は `output/research_phase3_comparison_grid_only_15min_soc80_warm_start/comparison.md` と `comparison.json` に保存した。Stage 1 gapが要求10%へ未達なのでcost optimumは主張しない。一方、hard constraints下の全便運行可行性は、fallback/postsolve変更なしのactual Gurobi pathで確認できた。
  - 回帰確認:
    - `python -m pytest tests/test_model_builder_vehicle_available_and_successor_cap.py tests/test_milp_stage1_warm_start.py tests/test_milp_fragment_pairwise_reset_cut.py tests/test_milp_same_day_vehicle_day_caps.py tests/test_phase3_controlled_validation.py -q` -> `35 passed`
    - MILP / route-band / same-day depot / model-builder / Phase 3 controlled群 -> `80 passed`

- 2026-07-14 (frontend晴天・雨天比較の料金契約修正と実入力preflight)
  - actual BFF call pathは `run-optimization` → `_run_optimization()` → prepared scope materialize → weather policy準備 → `ProblemBuilder.build_from_scenario()` → `apply_weather_policy_to_problem()` → `OptimizationEngine.solve()` であることを再確認した。2026-07-12の旧frontend runは両ケースともsolver infeasible、objective=`Infinity`、realized cost=0であり、「晴雨コストが同じ」という有効な比較結果ではなかった。一方、直前のgrid-only比較は意図的にPV/BESS/weatherを切った再現性試験なので同一コストが正しい。
  - frontend保存値を監査した。晴天scenario `771d115b-75b0-49f7-a7f0-25f259a2cd21`（2025-08-05）と雨天scenario `b23fd26c-1233-4c73-bb9e-bdb8b1584760`（2025-08-10）は、BEV35/ICE25、depot上限1000kW、BESS 600kWh/300kW、TOU、燃料、CO2、契約電力、solver 1500秒/gap10%が一致している。重要な実入力上の補足として、画面のlegacy summaryは`charger_count=10`・`charger_power_kw=90`だが、selected depot inventoryを正本としてMILPへ渡る充電器は90kW×5基+50kW×5基である。また画面のinitial SOC=80%は一律SOC方針ではなく、selected vehicle inventoryの35台別SOCが使われる。天候依存PV入力は晴天`614.709375 kWh`、雨天`101.1143 kWh`で異なる。alignment dry auditは `output/weather_comparison_alignment_audit.json` に保存し、control mismatchは0件だった。
  - P1として、`start_hour/end_hour`をfrontend・master dataは0..24の実時刻として保存しているのに、common builderとlegacy ProblemData mapperが30分slot番号として比較していた。たとえば16時開始を08:00開始として誤適用していた。`src/optimization/common/tou_pricing.py`へclock-hour評価を一元化し、Pydantic/BFF schemaも`0 <= start < end <= 24`へ統一した。`default_overlay_seed()`で時刻を30分slotへ変換していた処理も実時刻のまま保持するよう修正した。不正なlegacy 0..48 bandは黙って値付けせず明示エラーにする。
  - P1として、`ProblemBuilder`がdepot assetの明示`pv_enabled=false`を無視し、面積またはmanual capacityがあればPVを再有効化していた。asset-level flagを正本として尊重し、値が存在しないlegacy inputだけ従来のcapacity推定を使う。PV管理保存時は`scenario_overlay.cost_coefficients.pv_enabled`もasset群から同期し、frontend表示用legacy summary flagとの矛盾を今後作らない。既存2scenarioにはlegacy flag=false / asset=trueの食い違いがあるが、モデル入力の正本はasset=trueである。
  - P1として、PV→busとPV→BESSへBESS cycle costを課し、設定済み`pv_marginal_charge_cost_yen_per_kwh`を目的関数で使っていなかった。共通評価器、integrated MILP、Phase 3 Stage 2を `grid flow = TOU`, `PV flow = PV marginal cost`, `BESS discharge = BESS cycle cost`, `PV curtail = configured penalty` に統一した。設定0のcurtail penaltyを内部で1000円以上へ自動置換するhidden penaltyも除去した。curtail costは`pv_curtail_cost_jpy`としてcost breakdownへ明示する。
  - P1として、契約電力単価はfrontend/既存仕様では月額JPY/kW/monthで、評価器は計画期間へ日割りしていたがMILP目的関数は月額をそのまま掛けていた。`OptimizationScenario`に共通のhorizon換算propertyを追加し、integrated/Phase 3 MILPと評価器を同じ式 `(planning_horizon_hours / 24) / 30` へ統一した。現在の1日比較では1200 JPY/kW/month → 40 JPY/kW/horizonである。
  - Phase 3 Stage 1にはICE燃料費に加えて有効なCO2費を含め、Stage 2にはgrid electricity由来CO2費を含めた。Stage 2はcost component flagsも尊重する。ただしPhase 3は依然として二段階lexicographic modelであり、`solver_objective_matches_accounting_total=false`、global simultaneous total-cost optimumとは主張しない。
  - 修正後のactual input build preflightは両ケースとも264便、60分×24slot、PV/BESS有効となった。TOUは08:00=`18`, 16:00=`22`, 18:00=`19` JPY/kWh、契約電力horizon rate=`40` JPY/kW、diesel=`150` JPY/L、CO2 price=`1` JPY/kgで一致し、PV生成量だけが上記のとおり異なる。
  - 自分で追加検出した既存問題として、`scripts/unzip_and_rename_solcast.py`のdocstring内Windows pathが`\U` escapeとして解釈されcompile不能だったため、raw docstringへ変更した。実行ロジックは不変。
  - 回帰確認:
    - focused cost/TOU/PV/demand tests → `54 passed`
    - `python -m pytest -q --ignore=test_multiday_phase1.py` → `661 passed, 8 skipped`
    - 除外した`test_multiday_phase1.py`はlocalhost:8000で起動済みBFFを要求する手動E2Eであり、サーバ未起動時はconnection refusedになる。コード単体失敗ではない。
    - `python -m compileall -q src bff scripts` → pass
  - `scripts/run_research_phase3_frontend_weather.py` を追加した。このrunnerはscenario documentを更新せず、BFFと同じprepared materialize / weather policy / canonical builder / engineを通す。実行前に264便、BEV35+ICE25、60分×24slot、PV/BESS/weather policy有効、service dateをhard checkし、`input_audit.json`、`solver_result.json`、`summary.json`、scheduleを出力する。晴天・雨天のbuild-only auditではtrip input hashは一致し、PV generation hashと総量だけが異なることを確認した。最終1500秒run結果はこのrunnerから同じartifact rootへ追記する。

- 2026-07-14 (Phase 3 frontend weather run: execution-contract and construction-performance hardening)
  - 1500秒の本run前の10秒probeで、Phase 3 Stage 2が `component_flags` を参照する一方で同変数を初期化しておらず、PV/BESSありの実行が `NameError` で停止するP1を再現した。`_solve_thesis_stage2_charging_dispatch()` の入力metadataから明示的に正規化するよう修正した。制約・目的係数は変更していない。
  - 同probeで、10秒solver limitの外側でStage 1 model constructionが長くなる問題を計測した。264便×60台の同一 `fragment_transition_diagnostic()` を車両ごとに再計算していたためである。車種・home depot・便対・route-band/same-day設定をkeyに診断結果だけをcacheし、各車両の禁止制約 `end_arc + start_arc <= 1` は従来どおり全件追加するよう修正した。したがって `arrival + turnaround + deadhead <= next departure` を含むdispatch可行性条件・可行領域は緩和していない。
  - cacheの回帰testは同一診断を2台で1回だけ評価しつつ、車両別cutが2本残ることを確認する。Gurobi有効環境で `test_fragment_reset_cuts_cache_diagnostic_but_keep_per_vehicle_cuts` がpassした。
  - 報告契約のP1として、Phase 3は二段階lexicographic（Stage 1車両割当 + 固定割当Stage 2 energy dispatch）であり、global simultaneous total-cost optimumではないにもかかわらず、nested `plan.metadata` の一部が `research_kpi_eligible=true` としていた。adapter側もfalseへ統一し、engine側の `research_cost_kpi_eligible=false` と矛盾させない。可行性研究としてのacceptedと、総費用最適KPIを混同しない。
  - Gurobiが有効incumbentを持つが有限dual boundをまだ持たない場合、`MIPGap=Infinity` / `ObjBound=-Infinity` をJSONへ出していた。`_model_gap()` と `_model_bound()` は非有限値を`null`へ正規化する。これはgap=0への偽装ではなく、「有限な最適性証明が未取得」を明示する変更である。
  - frontend weather runnerのinput auditへcost component flags、vehicle usage cost、objective weights、BESS cycle cost/efficiencyを追加した。result summaryは `accounting_total_cost_jpy` と `cost_comparison_scope=feasible_schedule_accounting_not_global_total_cost_optimum` を分けて出力する。これにより晴雨比較で、フロント設定・会計値・最適性主張の範囲を混同しない。
  - dirty worktree上の短時間probe（研究結果には不採用）は、晴天入力で264/264便、使用32台、最大fragment=1、Stage 1=`time_limit`（5.123秒、有限gap未取得）、Stage 2=`optimal`（0.050秒）、SOC/充電器/契約電力/重複/接続違反すべて0を確認した。PVは614.709375kWhのうち614.709375kWhが利用され、grid importは22.941362kWhだった。本計算はclean commit後に同一runnerで行う。
  - 回帰確認:
    - `python -m pytest -q tests/test_milp_fragment_pairwise_reset_cut.py tests/test_phase3_controlled_validation.py tests/test_optimization_engine_postsolve.py tests/test_solution_validity.py tests/test_research_contracts.py`（`GRB_LICENSE_FILE=C:\Users\RTDS_admin\gurobi.lic`）→ `56 passed`
    - `python -m py_compile src/optimization/milp/solver_adapter.py scripts/run_research_phase3_frontend_weather.py tests/test_milp_fragment_pairwise_reset_cut.py tests/test_phase3_controlled_validation.py` → pass
  - frontend sunny build-only preflight → 264便、BEV35/ICE25、60分×24slot、TOU 08:00=18/16:00=22/18:00=19 JPY/kWh、demand=40 JPY/kW/horizon、PV/BESS有効を確認。
  - frontend weather runnerを拡張し、exact initial-SOC policy/source/hashと35台別SOC、terminal SOC raw policy、charger inventory/hash、vehicle/trip hash、weather provenance、PV/BESS asset snapshot、experiment hashを`input_audit.json`へ記録する。policy未指定かつselected vehicle inventoryも無効な場合は、SOCを数値から推測せずrunを拒否する。
  - strict preflightでは晴天・雨天のfleet/SOC hash/vehicle hash/charger hash/cost flags/TOU/BESS configurationはすべて一致した。差分はservice date、PV profile/energy/hash、forecast由来のweather operation mode（晴天=`aggressive`、雨天=`conservative`）だけである。現在の3 profileはSOC、assignment bias、grid risk penaltyをいずれも`None`としており、mode自体はprovenanceのみで数理係数を変更しない。従って現在の比較でPV energy以外に隠れた運用係数の差はない。
