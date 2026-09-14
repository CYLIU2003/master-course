# 4月の毎時充電計画停止と数値計算設定

2026-09-14。初回の月別12週試行（固定SHA `4c5c5d86`）は1〜3月が完走し、4月7日開始週のhour 023でStage 2が `infeasible` を返した。4月の23時間分を週間費用へ換算せず、5〜12月は未実行として保存した。

## 確認した原因

実行経路は `run_exact_seasonal_campaign` → `run_shibu21_24_seasonal_diagnostic` → `run_shibu21_seasonal_diagnostic.solve_week` → `RollingReoptimizer.reoptimize_charging_hour` → `OptimizationEngine` → `GurobiMILPAdapter` の充電専用Stage 2。

前時刻の実行状態とhour 023の初期状態は一致していた。保存された不整合制約から、車両 `8270c9a2-ed1f-4508-81a0-0903ddc4924c` のslot 187/188境界を抽出した。継続充電により `charge_on_187 = 1`、充電電力は最低 `0.0001 kW`、境界SOCは `73.07487625000005 kWh` と一致する条件である。

既定のpresolve aggregationでは抽出モデルがINFEASIBLEになったが、終端SOC上限を外して同じSOC式を最小化すると `73.07487624999841 kWh` を得た。目標との差は `-1.634e-12 kWh`。上限を含む同一モデルでも `Aggregate=0`、`Presolve=0`、`NumericFocus=3` の各診断で実行可能となり、最大制約残差は `6.37e-12` 以下だった。これは物理量を書き換える根拠ではなく、数値的な偽の実行不能判定を疑う証拠である。

さらに、元のcanonical Prepared・day-ahead計画・hour 023の全引き継ぎ状態から、完全な充電問題を再構築した。変更した求解設定は `Aggregate=0` のみで、同じ15秒予算・12 threads・seed 42・FeasibilityTol/IntFeasTolとも `1e-9` のまま `feasible=true` を得た。この1時間の検査は原因確認であり、停止した週間chainの継ぎ足しや正式結果への置換には使用しない。

## 修正と比較への影響

Stage 2の最初の求解から一律に `Aggregate=0` を適用し、成功時・失敗時のmetadataに `stage2_gurobi_aggregate` を記録する。選択的な再試行・fallback・修復は追加しない。SOC・電力・燃料・会計式・制約・許容誤差は維持する。presolveでの式の集約を止めるため、計算時間や時間制限内に得られる解は変わり得る。

変更後の結果は新しいclean固定版で1〜12月すべてを再実行する。初回1〜3月の値は初回試行の記録として保持し、新版の月別・季節別集計には混ぜない。7日間の選択日、時刻表、fleet、PV/予測原本、初期状態、seed、threads、時間予算は同じ条件を引き継ぐ。

## 証拠と検証

- 初回試行: `C:/master-course-worktrees/shibu21-23-monthly-fair-20260914/output/monthly_fair_weeks_campaign_20260914`。
- 抽出モデルの診断: `output/monthly_fair_weeks_20260914/april_iis_recheck/`。`full_aggregate_0.json` は保存IISの全サブシステムを指し、元のStage 2全制約とは区別する。
- 完全なhour 023の再検査: `output/monthly_fair_weeks_20260914/replay_april_hour_023.py`、`april_hour_023_aggregate_0/summary.json` と `result.json`。
- 独立検査: `output/monthly_fair_weeks_20260914/april_failure_independent_review.json`。
- 回帰fixture `tests/fixtures/stage2_exact_terminal_boundary.ilp` は上記車両の保存制約から得た117行の再現用サブシステムで、最小IISとの主張はしない。元の浮動小数係数を保持する。
- 実ソルバー回帰で境界解を残差 `1e-9` 以下で受理し、初期SOCを1 kWh増やした真の終端超過はINFEASIBLEとして拒否する。関連75テストが通過。
- 全体回帰は **2,271 passed / 既存PowerPoint証拠2 failed、106.66秒**。`output/monthly_fair_weeks_20260914/pytest-numeric-release.xml` と同名logへ保存した。独立コードレビューは別途記録する。

現時点の研究採用は引き続き **BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**。この修正は最適性gap、正式fleet contract、時刻表年次や予測モデルの制限を解消しない。
