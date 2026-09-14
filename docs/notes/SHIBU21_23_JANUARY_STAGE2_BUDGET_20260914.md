# 月別12週: 1月の前日充電計算の予算診断

固定 `829e3983` の月別計算は1月day-aheadのStage 2で時間切れとなり、完走0/12週で停止した。同じ本体モデルの計算時間を延ばすと実行可能解が得られ、SOC再計算・物理検証も通過した。全12週の新規実行では、Stage 2の最大時間を一律30秒から120秒へ変更する。週の選択、数学モデル、料金、SOC許容誤差は変更しない。

## 原本と再現

停止原本は `C:/master-course-worktrees/shibu21-23-monthly-presolve-20260914/output/monthly_presolve_campaign_v3_20260914/cases/2025-01-06/diagnostic/2025-01-06/`。新規に保存した診断はmainの `output/monthly_fair_weeks_20260914/january_presolve_budget_diagnosis_v2/` にある。いずれもソースSHAは `829e39835327b75c227737f9a5f4d3a76670adf1`、前後clean。

同じPrepared入力を既存materialization・ProblemBuilder・OptimizationEngine経路へ渡し、主Stage 2の直前にStage 1割当とnative MPSを保存した。23回の5秒の車両別候補検査を除外し、唯一の主Stage 2を確認した。32 duties・1,704便、Stage 1目的値4,245,071.589723584、固定割当は旧 `8acd8beb` の成功した1月day-aheadのvehicle_pathsとも一致した。これは元の30秒失敗結果を修復したものではない。

| 同一モデルでの診断 | 最大30秒 | 最大120秒 |
|---|---:|---:|
| 実測native求解時間（秒） | 30.187 | 36.752 |
| 最初のincumbent（秒） | なし | 36.537 |
| 実行可能解数 | 0 | 2 |
| Stage 2目的値（円、週間実行費用ではない） | 未成立 | 101,587.67091536222 |
| Stage 2 MIP gap | 未成立 | 0.448099% |
| 最大制約違反 | 解なし | 4.982752e-10 |
| 最大bound / integer違反 | 解なし | 0 / 0 |
| 保存計画の独立再計算・物理検証 | 解なし | 通過 |

両モデルは549,700変数・280,896二値変数・563,814制約。MPS SHA256はともに `dd21e880a51a0c69d78f0efcd0b451262d43bbed91169b96310ac9299292255a` で、係数・制約・目的関数が一致する。変更はStage 2時間上限と診断用の出力先・計時情報だけである。Aggregate=0、Presolve=0、FeasibilityTol/IntFeasTol=1e-9、MIPGap=0.1、seed42、12 threadsを保持した。fallback・解後修復・successor pruningは使わない。

保存ファイルは `summary.json`、`stage2_calls.json`、`stage1_fixed_assignment.json`、`full_stage2_30s.json`、`full_stage2_120s.json`、`physical_validation.json`、`post_run_audit.json`。MPS・パラメータ・trusted-local pickleも同じ診断ディレクトリに保持した。再現用スクリプトはその親の `january_presolve_budget_diagnosis_v2.py`、求解を伴わない追加監査は `audit_january_budget_diagnosis_v2.py`。

最初の診断v1は5秒の候補検査モデルを誤捕捉していたため無効とした。`january_presolve_budget_diagnosis/review_invalid_capture.json` に理由を保存し、v1の120秒infeasible結果は今回の予算判断に使用していない。

## 全月共通の再実行条件

新しい凍結版で12週すべてを新規Prepareから実行する。Stage 1最大120秒、day-ahead共有900秒（構築時間を含む）、rolling最大15秒は保持し、前日Stage 2最大120秒を初月から一律適用する。追加予算は計算上限であり、毎回120秒を使い切る指定ではない。1月の診断で予算を決定した経緯を開示し、月ごとの結果に合わせた時間変更や選択週の変更は行わない。

PV曲線・2024年学習モデルは同一hashで移設する。予測manifest内のdesignは予測生成時の来歴として保持し、今回の求解時間設定は新campaignのdesign・Prepared監査・solver metadataに記録する。予測生成時の時間設定を実行時設定と読み替えない。

この診断だけでは週間168時間・672 slotの実行会計も、全12月の完走も成立しない。旧版の成功週や診断のStage 2目的値を月別費用表へ流用しない。Stage 1 gap未達、正式fleet契約、2026時刻表の2025年適用、2024年climatologyの限界、温度/HVAC季節需要の欠如、既存PPT証拠2件などの研究採用条件は残る。全結果は `DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS` として扱う。

変更後の月別週選択・予測契約・campaign設定検査は25 passed（2.34秒）。既存のモデル全体検証は2,297 passed / 既存PPT証拠2 failedであり、今回の変更は設定・文書だけ。独立診断監査のP0/P1は0件、詳細記録に関するP2は追加監査で解消した。将来の呼出しグラフ変更への防御的改善1件は現固定SHAの妨げではない。レビュー記録はmainの `output/monthly_fair_weeks_20260914/january_presolve_budget_diagnosis_v2_review.json`。
