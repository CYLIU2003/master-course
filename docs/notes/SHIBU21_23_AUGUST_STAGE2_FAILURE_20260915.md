# 8月hour 48の停止と保存モデル診断

固定版 `10a40c9faa00d0a4725ae0062d6dbaa223f82bfd` の1〜7月は独立監査済み。8月4日開始週はday-ahead物理検証を通過し、48/168時間を受理した後、hour 48のStage 2がinfeasible・incumbentなしとなった。2026-09-15 06:15 JSTにcampaignと監視が停止。9〜12月は未実行で、完了メールは未送信。前後のソースSHAは同一でclean。

失敗原本は `C:/master-course-worktrees/shibu21-23-monthly-search-20260915/output/monthly_search_campaign_20260915/cases/2025-08-04/diagnostic/2025-08-04/`。当該hourの有効上限14.9275585秒、Stage 2記録時間21.3609555秒（IIS等の処理を含む経路）、初期BESS3163.138945341848 kWh。物理通過や週間費用成立とは扱わない。保存済みIISは65,521制約・38,402変数境界を含む大きな部分モデルで、元モデルは80,780制約。

`diagnose_august_iis.py` は元ILPをhash保存し、変更せず別モデルとしてLP緩和と整数求解を診断した。元と同じPresolve/Aggregate=0、許容差1e-9、seed42、threads12、MIPFocus=1、Method=1。LPは1.006秒、整数モデルは1.755秒で実行可能解が得られ、整数モデルの最大制約違反5.596e-11、境界違反0。これは保存された部分モデルの診断で、元の目的関数を持つ全モデルの実行可能性や実運行の物理通過を意味しない。保存IISだけから物理的な矛盾を断定する根拠は得られていない。

続いて `replay_august_hour_048.py` で固定版の元Prepared入力・day-ahead配車・hour48開始状態から全rollingモデルを再構成する。実行時の経路は、元campaignと同じ `RollingReoptimizer.reoptimize_charging_hour` → 捕捉したrolling problem → `OptimizationEngine.solve`。MIPFocus=1を維持しMethod=1/0をそれぞれ既存15秒枠で診断、全モデルのMPS SHAを相互照合し、解が出れば独立物理検証する。入力problem/configのpickle、native MPS、ログ、結果、物理検証を別フォルダへ保存する。診断は再試行で成功週を補う目的ではない。変更を採用する場合は新clean固定版から全12週を再実行し、旧結果を混ぜない。

結果表・README・開発記録・blockerは7/12成功・8月停止へ同期。監査JSONに8月の原本summary hashと `FAILED_CASE_DIAGNOSTIC_ONLY / fully_audited=false` を保存。checkpointは、成功条件を満たす週だけを数え、保存済み失敗原本のhash/status/case rootが一致する失敗行を別に保持できるよう修正した。報告関連67 tests通過（2.10秒）。数式・ソルバー・固定コード・原本結果は変更していない。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKEDを維持する。


## 全モデルで確認した数値問題と採用方針

同じMPS SHA `adfebf2064710c318c2a0f3efa7f528453f983bb04c2ee1ddee4498059b28117` の80,780制約について、Method=1は4.093秒でinfeasible、Method=0は1.042秒で実行可能解を返した。Method=0の最大制約違反1.176e-10、境界違反6.139e-12、整数違反0。固定原本の初期状態とday-ahead配車を再利用し、探索以外のモデル差はない。

最初の `method_0_physical.json` は、部分rolling計画を全7日イベント検証へ渡した診断コード側のスコープ誤用である。現在SOCから過去の全便を再消費するため、INVALIDを実運行の物理違反と解釈してはならない。原ファイルは残し、`validation_scope_correction.json` に訂正理由を明記した。代わりに元の運用経路の実PV slot192〜195反映・次状態作成を適用し、PREFIX_ACCEPTEDを確認。`validate_august_prefix.py` で保存候補のhashを照合して再現した。全週の物理検証は新しい12週実行の終了時に別途行う。

全月共通の新しい探索規則は、前日Method=1、`rolling_horizon_policy=remaining_day_fixed_assignment` の毎時更新はMethod=0、双方MIPFocus=1。日付や失敗結果による切替・再試行はなく、宣言された実行段階だけから選ぶ。11月の前日成功条件を保ち、8月の毎時数値問題を避ける。全ての時間予算、料金、制約、許容差1e-9、Aggregate/Presolve=0、入力を維持する。監査はday-aheadとhourlyの原本Method値を別々に必須照合する。旧7週は診断校正の過去版であり、新しいclean固定版の全12週には流用しない。

境界テストは両段階で実行し、真のSOC超過は引き続き拒否。3月の累積SOC再現モデルはMethod=0でも通過した。関連49 tests通過（6.21秒）、報告と合わせた72 tests通過（3.40秒）。独立診断レビューP0/P1残件0。新しい記録先は `output/monthly_phase_search_20260915/`、結果表は `SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.md/.json`、図名は `shibu21_23_monthly_phase_search_20260915`。旧版の停止・監査・メール重複防止記録は保存する。

全体回帰は2343 passed / 既存PPT資料2 failed（110.10秒）。実装の独立レビューはP0/P1残件0、起動時の最終SHA固定を条件に確認済み。ソース版を固定してから新規実行する。
