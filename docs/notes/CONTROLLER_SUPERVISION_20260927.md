# 固定コントローラーの自動復旧

2026-09-27。前回の構成判断から、管理プロセス停止時の復旧を実装・配置した。
求解固定版は `f524eca2552a4386bd033a15bbe046c14dc09281` のまま。
ソルバー、入力、SOC、BESS、時間上限、RAM配分、ライセンス枠は変更していない。

## 原因と変更

管理プロセスが終了した後、遠隔workerが計算を続けていても、親機の管理再開に手動操作が必要だった。
15:52の終了原因自体は未確定。OSタスクによるプロセス監督が未配置である点を補った。

- `tools/research/controller_supervisor.py`: enable/disable/status/tick/watch。既存のoperation/settingsを利用。
- CIMで実行引数を照合し、PIDと生成時刻で同じプロセスを確認する。Windowsのvenv親子は1実行として数える。
- APIのタイムアウトだけで再起動しない。権限不足、別のポート所有者、キューロック保持、複数管理プロセスはHOLD。
- 停止確認後に固定版の既存`--check`を実行し、起動直前にも再照合する。子scheduler自身のOSキューロックも維持。
- 起動前にSTARTINGと回数を原子的に保存。起動結果不明はBLOCKEDとし、自動再試行しない。
- 最大3回、60/180/600秒の間隔。設定または監督コードのhash変更、事前検査失敗は停止する。
- 全ジョブ終了後の管理サーバー終了は再起動しない。意図的な停止には事前のdisableを使う。
- `tools/research/install_controller_supervisor.ps1`: current-user/Interactive/Limited、ログオン時起動、IgnoreNew、有限のタスク再試行。

監督からenqueue/retry/cancelを呼ぶ経路はない。復旧した既存schedulerはQUEUEDの割当を再開し得る。
回収専用モードとは区別する。ライセンス予約を手動解放しない。

## 検証

関連回帰73件通過（supervisor、weekly_operator、cluster service recovery）。
最後に監督コード自身のhash固定を追加し、変更対象19件を再実行して通過。
PowerShell構文検査と実環境CheckOnlyも通過。

対象: 生存・状態不明時の起動抑止、別ポート、実OSロック、PID再利用、同一引数のvenv親子、
途中から現れたcontroller、設定変更、事前検査失敗、保存失敗、起動失敗、回数上限、バックオフ、全件終了。
Windowsの軽い実プロセスを終了させた後の再起動も確認した。Gurobiは起動していない。

さらに、専用の偽コントローラーと試験用SQLiteを使ってWindows Scheduled Taskを実行した。
1回起動後、その試験プロセスだけを終了。約60秒後に2回目の起動となり、別PIDを確認した。
disable後、タスクはReady/終了コード0となり、起動済みの試験プロセスは生存していた。
確認後、そのプロセスと試験タスクだけを終了・登録解除した。証拠は削除していない。

試験は管理プロセスの生存・復旧の検証であり、SSH障害、PC再ログオン、停電、Gurobi実求解の故障試験ではない。
実行中の本番controller/workerを故障注入のために終了させていない。

## Claude Codeとのレビュー

既存Pro認証、`claude-sonnet-5`、safe-mode、ツールなしで2回照会した。
初回は応答待ち240秒を超えたが、同じ生存プロセスが後に返答した。重複依頼を送っていない。
2回目は指摘への対応と根拠を説明した短い再確認。いずれもClaudeがテストを実行したものではない。

|指摘|判断・対応|
|---|---|
|読めない無関係PythonがHOLDを発生させる|可用性の制限として残す。無関係と証明できないプロセスを無視する提案は不採用。Claudeも再確認でP2相当へ再分類|
|観測と起動の競合|事前検査後の再照合を追加。子が取得すべきキューロックを親が保持し続ける提案は不採用。最終的なscheduler重複防止は既存OSロック|
|HOLD時も終了0|単発status/tickは3、BLOCKEDは2。watchはHOLDを保存して照合を継続|
|HOLDで以前のPIDが残る|生成時刻付きの最後の観測を保持する意図をコメント化。ABSENT確認後だけ消去。権限不足で証拠を消さない|

Claudeの再確認は、提示された説明に基づく評価であり、修正コードの独立実行や研究承認ではない。
初回の重大度・説明には誤りが含まれたため、レビュー原文を無条件の不具合認定として扱わない。

## 本番配置の確認

18:15 JST、タスク `MasterCourseControllerSupervisor8891` がRunning、監督状態PROCESS_PRESENT。
既存controller PID52332を生成時刻付きで確認。監督による起動数0。
配置前後のjob ID54件は完全一致。新規ジョブ投入、worker再起動、固定ソースの変更はない。

記録一式: `output/controller_supervisor_20260927/`
（review_response.json、review_followup.json、task_fixture、deployment.json）。
現在状態: queue配下`controller-supervision/state.json`。
[利用者向け手順](../guides/weekly_operations.md#管理サーバーの自動復旧明示的に有効化する)。

この監督は管理サーバーのみを対象にする。回収・図表の監視は既存スクリプトが担当する。
全監視プロセスの自動復旧、再ログオン試験、1月の週次再監査、11・12月の完走、重い毎時窓の時間短縮は残件。
本変更で「12週が無人完走した」「求解速度が改善した」とは主張しない。
