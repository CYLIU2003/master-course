# 毎時の充電精度不足と実行前検査の修正

2026-09-22 停止更新: 下記の固定4b1cbbb7は局所実行と42時間診断を通過し、8:43 JSTに新規全月を開始したが、1月hour49でgap1.1743%/120秒となり9:21 JSTまでに停止。49時間受理、完了0/12。以下は履歴であり現在稼働中ではない。[毎時600秒の新条件](MONTHLY_AUXILIARY_PROOF_BUDGET_20260922.md)。


2026-09-22 起動確認: clean固定 `4b1cbbb7` で一度きりの検証スクリプトを起動。制御PID23684、入力47ファイル/hashと実モデル0x006d6a65の一致を確認済み。現時点は局所実経路の検証段階で、全月は未開始0/12。局所引継ぎ・連続42時間・gap/数値品質・独立物理/BESSが通過した場合だけ全12週を新規Prepareから開始する。通常処理はスクリプトへ委任、失敗時1回通知、完了メール未送信。記録: `output/monthly_auxiliary_quality_20260922/gate_startup_verification.json`。


固定b1916e560afd7e81f3289890c53d3745daeed275の42時間診断は、hour126～154の29時間を受理後、hour155（156時間目）で止まった。可行解はあるが、Stage2のgapは71.0608837643%で、宣言済み1%を満たさない。失敗hourの実行・次状態保存は行われていない。budget_rerun_launch.jsonはなく、月別計算は未開始0/12。旧failureとnative logを保存し、完了メールは送らない。

## 根拠と同一モデル比較

同じ配車・保存されたhour155開始状態から全MPSを再構成し、native fingerprint 0x006d6a65との一致を確認。43,844行・42,800変数・153,412係数・156 MIN制約。MPS SHA256: 34872afe8f970476a4981d37bddbe433a007a68aa36e62a5a5b1eba3accc7b56。

| 同じ120秒枠の条件 | 候補目的値 JPY | 下界 JPY | gap | native秒 |
|---|---:|---:|---:|---:|
| MIPFocus1（再現） | 17,662.531102 | 5,053.717663 | 71.387353% | 120.033 |
| 同1＋直前充電計画の部分MIP start | 27,262.179155 | 4,442.029150 | 83.706258% | 120.044 |
| MIPFocus0 | 24,646.698097 | 17,010.063537 | 30.984412% | 120.047 |
| MIPFocus2 | 17,662.531102 | 17,490.508751 | 0.973939% | 110.430 |

MIPFocus2だけが事前の1%目標を満たした。これは同じ候補に対する下界改善であり、費用削減額ではない。旧本番停止時の下界5,111.380406円・gap71.060884%との差は有限実時間の探索終了位置によるもので、モデル差ではない。充電部分の目的値を総費用と呼ばない。契約超過量25.000049kWhのペナルティを含む候補なので、gapの大きさをゼロ付近の相対誤差として処理しない。

最大native制約違反はMIPFocus2で9.9043e-11、bound/integrality違反0。設定変更はMIPFocusのみ、Method0/NumericFocus3/Presolve0/Aggregate0/4threads/seed42/FeasibilityTol・IntFeasTol各1e-9を共通にした。全4条件を完了し、通過条件があったため、予定した「全条件未達時のみ600秒」は実施しない。部分初期解は不採用。証拠: output/monthly_auxiliary_budget_20260922/hour155_search_diagnosis/summary.json、identity.json、各native log。

## 見つかった検査不足と修正

P1: 月別実行経路はfeasibleを検査後、毎時のStage2 gapを強制せずprefix実行へ進んでいた。今回の連続診断が先に拒否したため、当該候補を月別成果へ採用した事実はないが、全月経路にも同じゲートが必要だった。

run_exact_seasonal_campaign → run_shibu21_seasonal_diagnostic.solve_week → rolling_config_for_design → RollingReoptimizer → Stage2 _configure_stage2_numerics → 元結果保存 → 実行前品質検査 → execute_pv_prefix → 独立監査、という到達経路を修正した。前日診断専用モードは診断結果を保存できるが、週間実行では前日/毎時ともStage2の可行候補・native gap・目的値/下界の再計算gapを要求する。拒否時は品質理由とhour、元solver status、execution_prefix_applied=falseを保存し、progressも失敗状態にする。169原本の独立監査も新設定のrequire_stage2_execution_quality=trueを必須照合する。旧版の保存済み監査を新条件で書き換えない。

## 新共通条件と実行手順

新設定: config/shibu21_23_monthly_auxiliary_quality_20260922.json。全12月・毎時120秒、NumericFocus3、MIPFocus2を開始前に宣言。前日MIPFocus1/NumericFocus0/120秒、Stage1 1800秒、主wall2400秒、4threads、gap1%は維持。制約・目的関数・SOC・物理許容差・BESS20～80%/バス優先/余剰蓄電/追加予備と終端復元なしは変えない。数学的可行領域は不変だが有限時間の探索結果は変わるため、旧週は再利用しない。

一度きりの制御スクリプトが、新clean固定版でhour155の実経路とBESS4区間・次状態を検査し、次に保存hour126から42時間を検証する。全42時間のgap・数値品質・引継ぎ・BESS168区間と全週の独立物理が通過した場合だけ、新規Prepareから全12週を開始する。初期126時間を組み合わせた物理診断は再現文脈専用で、新週や費用へ計上しない。失敗すれば止まり、この既存タスクへ1回だけ通知する。通常処理はスクリプトで、追加AI監視やメール送信は行わない。

関連188 tests通過。保存native境界の可行性/真の1kWh違反拒否、3月SOC引継ぎ、新MIPFocus値の型検査、前日と毎時の分離、実呼出し経路でのprefix未実行、全原本のgap拒否、observer出力分離を含む。自己レビューP0/P1残件0。独立レビュー未実施。コード検証とMPS上の改善は、局所実行・新規全12週の成立証明ではない。

研究採用BLOCKED、DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。Stage1の目標精度、週間の統合総費用最適性、確定実行会計、入力仮定、独立研究承認は別判定である。
