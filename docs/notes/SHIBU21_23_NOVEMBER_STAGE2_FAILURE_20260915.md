# 11月の前日充電求解の停止と予算診断

固定版 `fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8` の月別比較は、1〜10月の各168時間・672 slotが完走し、週間物理検証・確定会計・169 native求解の監査が通過した。11月10日開始週のday-ahead Stage 2で実行可能解が得られず、2026-09-15 01:30 JSTまでにcampaignと監視が停止した。12月は未実行である。全12週の完了メールは送信していない。

## 確認した原本

原本は `C:/master-course-worktrees/shibu21-23-monthly-budget-20260914/output/monthly_budget_campaign_20260914/cases/2025-11-10/diagnostic/2025-11-10/`。`summary.json` は `DAY_AHEAD_FAILED`、受理時間0。`canonical_solver_result.json` のnative metadataはStage 1 incumbentあり、Stage 2 incumbentなし、`time_limit`、有効上限120秒、記録されたStage 2 runtime 129.7578096秒である。前後のGit SHAは同じでclean。IISは生成されておらず、今回の状態だけで実行不能が証明されたとはいえない。

共有day-ahead上限900秒のうち、metadataの累積は525.5874507秒、残り374.4125487秒である。したがって、記録上は共有900秒を使い切った停止ではなく、Stage 2の120秒上限でincumbentなしとなった停止である。失敗結果内の費用0円は有効な週間費用ではなく、集計表へ入れていない。

campaignの `completed_weeks` は成功週だけではなく、失敗で終了した11月も含む11ケースを列挙する。成功は10週。監査JSONに11月を `FAILED_CASE_DIAGNOSTIC_ONLY`、`fully_audited=false` として追加し、case summary SHAと停止理由を保持した。集計CLIで10週の途中表を再生成し、README・blocker・計画書・launchをSTOPPEDに更新した。checkpoint helperも「終了ケース数」と「成功週数」を別に保存する。誤って11/12成功や通常計算中と表示しない。

## 実行中の診断

`output/monthly_fair_weeks_20260914/november_budget_diagnosis_20260915.py` は、既存の1月予算診断v2の経路を用い、同じ固定ソースとPrepared入力から11月の主Stage 2を捕捉する。候補車両の5秒検査は対象にしない。保存済み `stage1_candidate_assignment.csv` と新たに捕捉したStage 1の車両別便順を照合し、一致しなければ診断を停止する。元の主Stage 2の563,616制約とも照合する。

配車が一致した場合のみ、同じ割当の主モデルを最大120秒と600秒で求解し、双方のMPS SHAを照合する。変更は診断の時間上限だけで、SOC許容差、Aggregate/Presolve、seed、threads、gap、料金、PV入力、制約を保持する。得られた計画を独立物理検証する。診断用出力はmainの別ディレクトリに置き、停止した原本・固定ソースへ書き込まない。

この診断は週間結果や再試行成功として扱わない。600秒で解が得られるか、同じ配車が再現するかは未確定。結果を確認して全月共通の計算予算を判断する。条件を変更する場合は新しいclean固定版から全12週を新規実行し、旧版の成功10週と新条件の週を混ぜない。

診断の実Python PIDは11896（2026-09-15 01:33:10 JST開始）。`notify_november_diagnosis.py` がプロセスIDと開始時刻を照合してローカルで待ち、終了時だけ既存タスクへqueueする。通知設定・実受理記録は `november_diagnosis_notification_20260915.json` と `november_diagnosis_dispatch_20260915.json` に保存する。通常のLLM監視ループは起動しない。診断終了の通知は完了メールではない。

## 変更の検証と主張範囲

停止ケースを成功数から除外するcheckpoint回帰テストを追加し、observer・月別集計・証拠収集の48 testsが通過した（1.84秒）。実際の10週監査と11月失敗記録でも文書同期のdry-runと適用が成功した。Stage 2の数学モデルは変更していない。

研究採用は引き続きBLOCKED。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSであり、各季節の最終集計は全12週がそろうまで行わない。
