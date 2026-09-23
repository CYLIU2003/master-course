# 2026-09-23 旧mainレビューと現行ローカル版の照合

対象レビューは `master_course_review_20260923/REVIEW.md`。その検証対象は GitHub main `5d790ea16329eda22e3ceb9930548f9d33de1bb3` であり、現行ローカル `main` の祖先である。照合時のローカルHEADは `c98f792b25ffe90bcd3f4827240f1d06dd87a1ec`。作業ツリーには多数の未commit変更があるため、以下の「修正済み」は**ローカル作業ツリーの状態**を意味し、clean frozen release・第三者承認を意味しない。旧レビューの再現スクリプトは旧GitHub blob用であり、現行版の合否判定には流用しない。

## 実装指摘の現状

| ID | 現行判定 | 根拠・残件 |
|---|---|---|
| C01 ジョブ原本削除 | ローカル修正、回帰通過 | `bff/store/job_store.py` は読取／形式不正／復旧保存失敗を別扱いし、原本を自動削除しない。破損JSON、一時的な読取拒否、保存失敗を `tests/test_job_store_recovery_safety.py` で確認。エラーの画面表示は実機未確認。 |
| C02 Windows PID確認 | ローカル修正、範囲限定 | 同ファイルは `bff/services/cluster/runner.py::process_identity` の読取専用Windows照会と生成時刻を利用。PID再利用と照会不能を区別する回帰を追加。権限・コンソール形態の全実機組合せは未検証。 |
| C03 保存競合 | ローカル修正、範囲限定 | 旧JSON storeはジョブ別OS lock、一意tmp、version検査、更新全体の直列化を採用。保存失敗時にオブジェクトのversionを先進させない修正を追加した。分散正本は別の `bff/services/cluster/store.py` のSQLite transaction。実端末の通信断・同時操作の全故障試験は未完了。 |
| C04 未知solver | ローカル修正 | `parse_optimization_mode`/`normalize_solver_mode` は未知値に `UNKNOWN_SOLVER_MODE` を返し、HYBRIDへ暗黙変換しない。`tests/test_cluster_solver_policy.py` で誤記を確認。 |
| C05 ALNS内Gurobi | 限定profileを実装 | 既存ALNSにはexact repairが残る。明示 `alns_no_gurobi_v1` はcanonical ALNS・1日・BESSなし等に範囲を絞り、禁止入口をguardする。既存ALNSとの解品質同等性、7日正式運用は未証明。 |
| C06 repair予算 | ALNS修正、GA/ABC残件 | canonical ALNSは全体残時間・累積repair残量・1回配分の最小を下位MILPへ渡す。GA/ABCにも同じrepair関数への入口があり、現在のlambdaは外側の残時間を渡さない。これらを正式運用候補にする前に同等の制御とcancel検証が必要。 |
| C07 下位Config継承 | ローカル修正、実求解未検証 | `partial_milp_repair` は `dataclasses.replace` で親の `research_run`、postsolve方針、threadsを保持し、下位部分問題に不適切なphase/固定割当のみ明示解除。mock下位solverで回帰。 |
| C08 監視によるlicense取得 | cluster監視では回避 | 通常worker probeはライセンス取得を行わず、明示試験を共有枠経由にした。一方、既存 `is_gurobi_available()` 自体はEnvを開始するため、別の監視経路へ流用しない。アプリ外使用を含む実契約枠は保証外。 |
| C09 遠隔復旧 | 基盤実装、故障実機試験残件 | 独立runner、attempt別成果物、SQLite永続queueとreconcileを追加済み。実11台への診断配置・hash回収の記録は `CLUSTER_VERIFICATION_20260923.md`。求解中の従機再起動・Electron終了など全故障注入は未完了。 |

今回の追加回帰は `tests/test_job_store_persist_retry_state.py`。既存の原本保持・同時更新回帰と合わせ、`python -m pytest -q tests -k 'cluster or job_store or partial_milp'` は162 passed / 17 skippedだった（その他2681件は選択対象外）。旧レビューの8分離チェックと、この現行版の回帰は対象・意味が異なる。ジョブJSONの状態を遠隔分散の正本へ昇格させず、SQLite側のattempt照合を維持する。

## 研究指摘の現状

旧レビューが引用した固定 `7c7c2334` の値を、新しい固定 `7cb46894` の結果に転記しない。後者の全12週・各168時間/672区間、独立物理検査と会計照合は[現行結果](SHIBU21_23_MONTHLY_AUXILIARY_PROOF_BUDGET_RESULTS_20260922.md)に記録されている。これは実行と検査の成果であり、**研究採用はBLOCKED**。

| ID | 現行の説明・未解決条件 |
|---|---|
| R01 | 新12週のStage1 gapは3.264〜4.274%で宣言目標1%未達。二段階解法の週間統合総費用最適性も未証明。旧版の約85%を現行版の値として示さない。 |
| R02 | 現行週のBESS初期−終端は−598.1〜1,800.0kWh。各週が初期状態をリセットするため、連続週の節約・補充可能性は未証明。 |
| R03 | 新12週の最大15分平均受電は最大767.6kW。200kWは有料超過基準であり、設備hard limitの根拠は未確定。 |
| R04 | 車両日費2万円が総費用を支配。設備費ゼロの運用比較を投資採算に拡張しない。費目根拠・感度分析が残る。 |
| R05 | 距離は停留所座標による代理値。実道路・回送距離との照合が残る。 |
| R06–R08 | 2026年時刻表×2025年気象×2024年climatology、固定の車両消費、月1週の選択は現行報告で明示済み。実運行再現・予報技能・月年平均への外挿は行わない。 |
| R09 | 同日・同一fleetでPVだけを変えるpaired比較と複数seedの可行率・分布は未実施。月の費用順位をPV因果効果としない。 |
| R10 | 観測された60台のパラメータ一致と、正式research fleet contractの宣言は別。後者は未完了。 |
| R11 | hash付き月別記録がある一方、第三者へ渡せる自己完結bundleとGurobi不要の原本再検算入口は別途検証が必要。絶対パスだけを再現性と呼ばない。 |
| R12 | 物理、会計、BESS終端方針、研究採用、最適性を分けて表示する。PowerPoint証拠2件の残件と独立レビューは継続。 |

研究実験を再開する条件は[現行blocker](CURRENT_RESEARCH_RELEASE_BLOCKERS.md)に従う。数理条件や費用係数を変えた場合、旧12週と新条件の週を混ぜない。今回のジョブ保存・テストの修正で新しい正式研究計算、全月再実行、メール送信は行っていない。
