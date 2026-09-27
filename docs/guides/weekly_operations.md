# AIなしで週次計算を運用する

更新: 2026-09-27。この文書が現在の操作手順です。`docs/notes/` の日付付き起動記録は履歴です。

## このPCで最初に開く場所

`C:\master-course\output\operations\weekly_20260927\00_MENU.cmd`

対象は「仮・正式用」の2025年各月1代表週です。2月と残り11週は内部の管理単位が違うため、入口で選びます。
シナリオを月別に作り直す必要はありません。計算固定版は `f524eca2552a4386bd033a15bbe046c14dc09281`。
操作ツールの修正と計算版は別です。入口の設置は新規ジョブ投入を行いません。

|ファイル|操作|使うとき|
|---|---|---|
|00_MENU.cmd|対象期間と操作を選択|ブラウザー・手順書・成果物フォルダもここから開く|
|01_STATUS.cmd|現在状態・担当PC・待機理由・検算率|最初に実行。0終了は計算完了の意味ではない|
|02_CHECK.cmd|固定版・依存環境・設定の検査|求解なし。ライセンス取得試験なし|
|03_CONTROLLER.cmd|登録済み管理サーバーを起動|応答中なら追加起動しない。稼働中は窓を残す|
|04_RUN_OR_RESUME.cmd|同じ設定で開始・続行|既存キャンペーンが動いていればALREADY_ACTIVEで終了|
|05_COLLECT_EXISTING.cmd|同じ試行の回収・検算・集計|新規投入なし。失敗した求解の再実行ではない|
|06_WATCH.cmd|30秒間隔の確認・代理回収|AIなし。Ctrl+Cで監視だけ終了|

対象を間違えた場合はQで戻ります。各入口は終了コードを残して停止するため、エラーを読めます。
操作の終了コードは0=操作成功、3=未完了・通信不明、2=設定／操作エラー、130=中断です。
`run` / `check` は下位プロセスの終了コードを引き継ぎます。計算完了数は必ずSTATUSまたは画面で確認します。

## 起動と親機再起動後の復旧

1. 01_STATUSで対象を確認。通信不明なら、02_CHECKを実行する。
2. CHECKがPASSなら03_CONTROLLERを開く。操作メニュー7のブラウザーは当該コントローラーのURLへ接続する。
3. 01_STATUSで以前と同じjob/attempt IDを照合する。SSH接続が切れていても、子機では求解が続く場合がある。
4. 05_COLLECT_EXISTINGまたは06_WATCHで既存結果を回収する。
5. 未投入の週を続行するときだけ04_RUN_OR_RESUME。同じcampaign、batch、idempotency keyを利用する。

Pythonが見つからない場合は設定に記録した環境を復元します。任意の別Pythonやソルバーへ切り替えません。
CHECKのSHA/依存/入力不一致は、固定releaseや元設定を保全して原因を調べます。稼働releaseを`git pull`しません。
新条件は別のclean固定版・新しいPrepare・新しい実験保存先で扱います。

## 停止・取消・通信障害

### 管理サーバーの自動復旧（明示的に有効化する）

`tools/research/install_controller_supervisor.ps1` は同じ固定版・設定・既存キューの管理サーバーを監督します。
求解の再実行や新しいbatch/attemptの作成は行いません。ただし復旧したschedulerは、**既存キューのQUEUEDの割当も再開**します。
これは回収専用モードではありません。適格PC、RAM、ライセンスの既存判定は維持します。

```powershell
# まず登録内容を検査（起動・登録なし）
& .\tools\research\install_controller_supervisor.ps1 -Operation .\output\executed_soc_20260926\operation.remaining.local.json -CheckOnly
# 登録・有効化。同じ利用者のログオン後にも起動する
& .\tools\research\install_controller_supervisor.ps1 -Operation .\output\executed_soc_20260926\operation.remaining.local.json -Start
```

稼働中のコントローラーはPID・生成時刻・実行引数で識別し、そのまま継続します。
API応答時間では停止を判定しません。照会権限不足、他のポート所有者、キューロック保持、複数管理プロセスはHOLDです。
停止を確認した場合だけ固定版の`--check`を実行し、同じ管理サーバーを起動します。
再起動枠は永続記録で最大3回、間隔は60/180/600秒。設定・監督コードの変更、事前検査失敗、起動結果不明ではBLOCKEDになり、人間の確認まで停止します。
全ジョブが終了した状態で管理サーバーが終了しても再起動しません。稼働中の管理画面は閉じません。

**管理サーバーを意図して止める前に、次を実行します。** `disable`は計算やサーバーを強制終了しません。

```powershell
& .\output\cluster-deployment\controller-venv\Scripts\python.exe -X utf8 .\tools\research\controller_supervisor.py disable --operation .\output\executed_soc_20260926\operation.remaining.local.json
```

状態と起動ログは設定のqueue配下`controller-supervision/state.json`と`controller.log`です。
`status`/`tick`の終了コードは0=正常、3=HOLD（状態確認待ち）、2=BLOCKEDまたはエラーです。
停止原因を直した後もBLOCKEDが残る場合は、その記録を別名へ保管したうえで、同じ設定の`-Start`で再有効化します。
不明なPIDを終了させたり、ジョブやライセンス予約を削除して復旧してはいけません。
タスクは同じ利用者のInteractive/Limited権限で動作します。ログオン前の起動や停電からのPC電源復旧は対象外です。
この監督は管理サーバーのみです。回収・図表監視には既存の06_WATCH等を使います。

- STATUSは読取です。WATCHのCtrl+Cは監視のみの停止で、遠隔計算を停止しません。
- コントローラー窓のCtrl+Cで管理を終了すると、新規割当は止まります。受理済みworkerは継続し得ます。
  戻るときは上の復旧手順で照合します。PIDだけを見て別計算を投入しません。
- 特定ジョブを終了させる場合は、そのコントローラーの分散計算画面で対象IDを確認して取消します。
  取消要求の受理とプロセス終了は別です。終了確認まで枠を手動解放しません。
- SSH鍵不一致、認証拒否では、記録されたPC名・ユーザー・host keyを管理者と確認します。
  鍵の上書き、OS再起動、広範囲のPython強制終了で解決しません。

|表示|確認／次の操作|
|---|---|
|QUEUED|空きRAM、OS予約、Windowsコミット余裕、Gurobi予約・解放待ちを確認。計算中とは違う|
|LOST / STATE_UNKNOWN|同じ試行の照合を待つ。新しいattemptへ自動置換しない|
|ALREADY_ACTIVE / CLIENT_ACTIVE|既存の管理プロセスが所有中。STATUSで確認し、二重起動しない|
|PREPARED_INPUT_STALE / Frozen campaign differs|設定・入力の版が不一致。既存入力を勝手に再生成しない|
|FAILED_OR_UNVERIFIED|求解失敗と回収・図表失敗を原ログで分ける。後者なら既存結果を回収／修復する|
|memory_limit / no incumbent|可行性がない証明ではない。元ログ・機器予算を保管し、失敗箇所を特定する|
|COMPLETED|求解プロセス終了。検算・会計成立・正式研究採用・最適性とは別|
|PENDING_MANUAL_SEND|未送信.emlを作成した状態。送信成功ではない|

Gurobiは32GB以上の許可済み端末のみ。32GB機は約16GiB、64GB機は約32GiBを目安とし、
実際の空きRAM・OS予約・コミット余裕・モデル要求を既存schedulerが判定します。
実機で認められたライセンスプールの共有上限を親機brokerが管理します。待機を解除するために上限を変更しません。

## 詳細進捗・結果・通知

画面の「期間別計画」「分散計算」で工程、毎時窓、担当PC、メモリ、待機理由、直近ログを確認します。
ステージ内のgapは週全体の統合gapではありません。

|保存先（現在の実験ルート `output/executed_soc_20260926/` 以下）|内容|
|---|---|
|operation.local.json / operation.remaining.local.json|2月／残り11週の宣言。対応controller-settings.jsonを参照|
|february_campaign / remaining_campaign|週別state、Prepared、同じ試行の回収結果|
|各campaign/operations/STATUS.md、status.json|操作ツールの最終観測。日時と通信状態を確認|
|各campaign/週開始日/results/|検算後の週次・日別費用、運用・SOC・電力図|
|monthly_report/latest.json|比較表の最新revisionへの参照。included/declaredが採用週数|
|monthly_report/revisions/…/report.md|比較表・CSV・図・原本hash。旧revisionを上書きしない|
|report_recovery/2025-01-06/|1月の図表のみ修復した別出力。週全体の採用済みとはみなさない|

詳細読取を手動起動する場合（既存出力の監視が動いていれば多重起動は拒否されます）:

```powershell
$py = 'C:/master-course/output/cluster-deployment/controller-venv/Scripts/python.exe'
$root = 'C:/master-course/output/executed_soc_20260926'
& $py -X utf8 C:/master-course/tools/research/publish_execution_detail.py `
  --operation "$root/operation.local.json" --operation "$root/operation.remaining.local.json" `
  --output '<画面配信先のexecution-detail.jsonの絶対パス>' --watch
```

画面配信先は稼働サービスの設定を使います。任意の場所へ出力しても画面は更新されません。
現在の親機でのサービス構成は設置時の `output/operations/weekly_20260927/VERIFICATION.md` を参照。
集計だけを別出力へ作る場合は次を使用します。既存求解を再実行しません。

```powershell
& $py -X utf8 C:/master-course/tools/research/monthly_campaign_report.py `
  --operation "$root/operation.local.json" "$root/operation.remaining.local.json" `
  --output "$root/manual_report"
```

メール送信のPC単独認証は未設定です。AIなしでは画面、STATUS、未送信.emlで確認します。
過去のGmailコネクタ経由送信はこのツール単独の機能ではありません。既存email_receipt.jsonと送信済みを確認し、二重送信しません。

## 次の実験でも入口を作る

既存の確定済みoperationファイルを指定して、未使用のフォルダへ生成します。
インストーラーは設定検査と入口作成のみで、求解、外部データ更新、鍵登録、ライセンス取得を行いません。

```powershell
& $py -X utf8 C:/master-course/tools/research/install_operator_kit.py `
  --operation '<operation JSONの絶対パス>' --output '<新しい操作フォルダの絶対パス>'
```

複数operationは`--operation`を繰り返します。既存フォルダは上書きしません。
operationのsettings/campaign相対パスはそのJSONの場所を基準に解決します。
controller-settings内のpython/release/config/frontend/queue/outputs/scenariosは絶対パスを指定します。
古い固定コントローラーとの互換性のため、相対パスは黙って書換えず起動前に拒否します。

## ファイルを整理・保管するとき

- 操作入口は`output/operations/`、日々読む手順は本書、開発判断は`DEVELOPMENT_NOTES.md`。
- `data/external/`は原本、最適化用DBは検証済みsnapshot、Preparedは各runの凍結入力として区別する。
- `output/`の名前の古さだけで削除しない。現在のqueueは過去日付のフォルダを参照している。
- `outcome/`は提出用資料。使用中PowerPoint・他チャットの編集・原図は移動しない。
- 保存する最小単位はoperation/settings、凍結release、入力snapshot/Prepared、queueとattempt成果物、
  週次結果・比較revisionとmanifest。秘密鍵・ライセンスは公開Gitや資料へ入れない。
- 稼働中DBのSQLite本体だけをコピーしない。停止後またはSQLite backupの一貫した方法で保全する。
  `.sqlite-wal` / `.sqlite-shm`は不要ファイルと決めつけて削除しない。

関連: [配置案内](../REPOSITORY_LAYOUT.md)、[整理履歴](../FILE_ORGANIZATION.md)、
[旧週次運転の検証記録](../notes/WEEKLY_OPERATOR_RUNBOOK_20260924.md)。

## 今回確認した範囲

設定パス、終了コード、入口生成、二重起動拒否、既存attempt照合は自動テストで確認。
実際の起動場所を変えたSTATUS/CHECKは設置時記録を参照。
稼働中のPCを意図的に落とす復旧試験、単独メール自動送信、独立レビューは今回実施していません。
本書の整備をもって正式研究採用や全機器の無故障を保証したとは扱いません。
