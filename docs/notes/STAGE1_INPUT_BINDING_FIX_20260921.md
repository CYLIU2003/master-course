# 配車診断の入力参照を作成から検査まで統一

## 確認した結果

固定 `4a85de14d7741a33fb6dbf2530978ed00b95fecb` は2026-09-21 08:46 JSTに失敗終了。
双対単体法・NoRelの両方とも求解未実行であり、物理検証・目的値改善・native/認証gap・根LP記録・
nativeメモリ値は全て未評価。旧barrierの6.91%などを今回の値として使わない。
全12週の完了ではなく、メールは送らない。

最初の条件の新規Prepareは1,704便・60台・operator不明0・非正距離0で通過した。
後続のroute-scope検査だけが、旧 `output/shibu21_23_exact_20260911/source_candidate/` を参照し、
渋21/22/23を「verified timetable dataset has zero trips」と誤判定して停止した。
NoRel条件は最初の条件の失敗により未着手。nativeログは生成されていない。

`completion.json` に結びつくfailureのSHA256は
`9a5cc26ff86509f8705412e95e92fb69b4529bd59ecb28940b749fc74ef3c90b`。
固定版がcleanのままであることも照合した。
記録: `output/stage1_memory_search_20260921/review.json`。

## 原因と修正

- **P1: 保存先変更が事前検査まで届いていなかった。**
  `run_stage1_root_search_diagnosis` → `run_planning_consistency_diagnosis` →
  `run_exact_seasonal_campaign` → 新規source作成／Prepare → `run_diagnostic` →
  `discover_route_scope` の最後で古い設計のパスを使っていた。
  campaign作成時にroute_source、route_timetable_audit_sourceとfallbackを同じ新規captureへ束縛し、
  campaign・case・diagnosticの全設計へ引き継ぐ。関係のない旧catalogでは不足を補わない。
- **P1: 元の停止理由がFileNotFoundErrorに置き換わっていた。**
  上位wrapperが、求解前停止にも存在しないprogress.jsonを読もうとしていた。
  campaignの終了状態とcaseのreasonsを先に検査し、失敗JSONへ元の理由・求解有無・原本パスを保存する。
  2条件のcoordinatorにも子failureのSHAと原因を引き継ぐ。
- **P2: 前日計画だけの正常終了をcampaign失敗と扱っていた。**
  宣言されたday-ahead診断には専用の `DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE` を使う。
  月別・rollingの `COMPLETED` とは分ける。全期間実行を意図した設計が途中終了した場合は失敗のまま。

今回の変更は実行・記録の接続であり、目的関数・制約・料金・完全後続網・許容誤差・
車両・operator・距離・時刻表の値を変更していない。前回の保存先修正の後続参照漏れを直した。

## 検証と範囲

関連60 tests通過（24.07秒）。実source builder・実route preflight・実diagnostic runnerを通す
2 campaignの回帰を追加した。旧保存先の時刻表を空にした条件でも、新しいcaptureを読むため通過し、
新規入力と既存ファイルが保全されることを確認した。Prepare本体・solverはこの回帰ではmockであり、
実際の求解やメモリ改善を証明するテストではない。

今回失敗した実データの読み取り検証では、元の設計でBLOCKED、参照先を結び直した設計で
`READY_FOR_FROZEN_RUN`、保存済みPreparedもREADYと確認。検査用scopeのテンプレートは
渋21=72便、渋22=283便、渋23=293便で、週間の展開済み1,704便とは集計範囲が違う。
記録は同じreviewフォルダの `preflight_before_binding/` と `preflight_after_binding/`。
これらは原因確認のための既存Preparedの読み取りで、新しい求解へ流用しない。

自己レビューP0/P1残件0。独立研究レビューPENDING、研究採用BLOCKED。
直前の全体回帰2434 passed／既存PPT2 failedは旧コードの記録として保持し、今回の全体回帰とは呼ばない。
今回はsolver変更がないため、変更経路の60件を実行し全体suiteは繰り返していない。

## 次の診断

新しいclean固定版・新規Prepare・新出力先から両条件を実行する。
設計は `config/shibu21_23_stage1_memory_search_diagnosis_20260921.json` を維持する。
5月12日開始の7日間、Stage1 600秒／Stage2 120秒／wall1200秒、4 threads、18 GB、seed42、gap1%。
双対単体法のNoRelHeurWork=0/120だけを比較し、制約やsolver設定を今回さらに変更しない。
通常処理はスクリプトが実行し、終了時だけ既存タスクへ1回通知する。メール・全12週計算は行わない。

## 起動記録

2026-09-21 08:55 JST、clean固定 `4f9799825ed8af0217575c9ef94a78b90f4137e3`
（branch `codex/stage1-input-binding-20260921`）から開始。
実行先は `C:/Users/RTDS_admin/.codex/worktrees/stage1-input-binding-20260921/master-course`。
固定版の関連22 tests通過、入力47件SHA・参照11件の移設を確認。旧prepared／結果は取り込んでいない。
実coordinator PID30116／venv launcher39172。初回dualのRUNNING、実際のcase設計の検査先が
そのcampaignのsource_candidateに一致し、ファイルが存在することとworktree cleanを確認した。

制御記録: `C:/master-course/output/stage1_input_binding_20260921/launch.json` と
`startup_verification.json`。結果先: 固定worktreeの `output/stage1_input_binding_diagnosis_20260921/`。
起動スクリプトSHA256: `8069f588d0ade6b2dc850ba25259b84826c397a364df57cec7aba9cf1cc9a0e5`。
以後はスクリプトが実行し、完了／失敗で既存タスクへ1回だけqueueする。
