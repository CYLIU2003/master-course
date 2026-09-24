# AIなしで週次計算を運転する

2026-09-24。対象は既存の凍結入力・週次キャンペーン・分散キュー。
渋21〜23の計算版0964b783を変更せず、別の操作ツールから状態を読み取る。
操作ツールの版と、結果を生成したsolver SHAは区別する。

## 最初に開くもの

このPCの `C:\master-course\output\weekly_seasonal_20260924\operator` に操作用CMDを用意した。

|入口|動作|
|---|---|
|01_CHECK.cmd|固定ソース・Python/依存・設定を検査。求解・ライセンス取得なし|
|02_STATUS.cmd|週ごとの準備／計算／検算率、担当PC、待機理由、attempt、原本場所|
|03_CONTROLLER.cmd|指定の既存コントローラーを起動。応答中なら二重起動しない|
|04_RUN_OR_RESUME.cmd|同じ設定・保存先で実行／再開。稼働中キャンペーンやbatch clientがあれば開始しない|
|05_COLLECT_EXISTING.cmd|既存attemptだけをGETして回収・hash監査・週次図表出力。新規投入なし|
|06_WATCH.cmd|30秒ごとの状態記録と、停止した回収クライアントの代わりの回収。AI呼出しなし|

端末再起動後は01→03→02の順に開く。03のウィンドウはコントローラー稼働中は残す。
既存workerの計算は独立して継続し得るため、親機が落ちたことだけを理由に新しい計算を作らない。
02で同じattemptを確認し、05/06で回収する。未投入週の続行が必要なら04を使う。
04は元のbatch ID・idempotency keyを再利用する。停止済み／失敗済み求解を勝手に別attemptで再実行しない。
06の停止はCtrl+C。workerの計算を終了する操作ではない。

汎用CLI（既存operation設定を指定）:

```powershell
powershell -NoProfile -File tools/research/weekly_operations.ps1 -Operation <weekly-operation.local.json> -Action status
```

Actionは `check / controller / status / run / collect / watch`。
operation JSONには `settings`, `campaign`, `git_sha`, `parent`, `weeks`, `workers` を指定する。
settingsは既存 `serve_controller.py` の設定ファイル。手で環境変数を組み立てる必要はない。
再開時に週・親シナリオ・worker指定・SHAがbindingと異なれば停止する。
新しい実験は新しい保存先を使う。ODPTの再取得や入力DBの再構築はこの操作に含まない。

## 状態の意味と復旧

- READYは端末の状態。特定の週次ジョブを今すぐ投入できる保証ではない。
  `INSUFFICIENT_OR_UNKNOWN_RAM`なら、OS予約分を差し引いた空きRAMと要求を比較する。
  安全余裕や要求値を成功のために黙って下げない。
- QUEUEDは待機。RAM・PCの使用中枠・Gurobi予約・解放待ちを区別する。
- LOST / STATE_UNKNOWNは通信または照合待ち。失敗・不可行と読み替えない。
  既存schedulerが同じattemptを照合し、PC・ライセンス枠を保持する。
- SSH_TIMEOUTは既存transportで同じ内容・同じattemptの再試行が1回だけ許可される。
  SSH_AUTHENTICATION_FAILED、host key不一致は再試行対象ではない。
  鍵を無断置換せず、端末名・ユーザー・登録host keyを確認する。
- PREPARED_INPUT_STALEは入力不一致。自動で再Prepareしない。比較条件を固定し直した別実験にする。
- FAILED_OR_UNVERIFIEDは親機側クライアント／集計失敗を含む。02で実際のworker状態を再確認する。
- COMPLETEDは求解プロセスの終了。検算済み・正式研究採用・統合最適性とは別。

2026-09-24に5月週の回収クライアントで `batch-state.tmp -> batch-state.json` の
WinError 5を確認。workerの求解は同じattemptで継続していた。
新しい保存処理は一意の一時ファイルを使い、PermissionErrorだけを最大7回・合計最大1.55秒待って再試行する。
原本を削除しない。永続的な権限拒否では元ファイルと一時ファイルを残して停止する。
これは既存排他ロック内の保存補強であり、DBトランザクションの代わりではない。

操作ツールは固定計算版のファイルを書き換えない。実行中キャンペーンが既に回収失敗と記録した
ケースのみ、停止したbatch clientの排他ロックを確認したうえで代理回収する。
元の失敗監査は保存し、再監査は各週の `operations/recovery-audit.json` に置く。
回収成功の原本・図表hashを記録し、同じ成果物を毎回描き直さない。

## 記録と通知

- `campaign/operations/STATUS.md`：日本語の現在状況。
- `campaign/operations/status.json`：機械可読の進捗・資源待機理由。
- `campaign/operations/collection.json`：代理回収の状態（元state.jsonは改変しない）。
- `campaign/<week>/results/`：検算通過後の費用、計画、SOC、電力図表。
- `campaign/operations/terminal-notice.eml`：終端時の未送信メールファイル。

**メールのPC単独認証は未設定。PENDING_MANUAL_SENDは送信成功ではない。**
Gmailコネクタを呼ぶためにCodexへ復帰する経路はこのツールにはない。
Gmail OAuthをPCに設定するか、当面は画面／通知ファイルで確認する。秘密値をチャットへ貼らない。
通常の監視はAI/APIトークンを使わない。自動起動タスクは今回追加していない。
無限再投入・自動OS再起動・SSH鍵上書き・有償ライセンス追加は行わない。

## 検証範囲

Windows実機の一時ファイル共有ロックを生成し、解除後の置換成功を確認。
一時拒否・永続拒否・ディスク不足、二重起動防止、同一attempt照合、切断時のunknown扱い、
未監査結果の誤認防止、未送信通知の重複防止を関連テストで確認した。
稼働中APIで固定版チェック、状況表示、二重起動拒否、停止clientの既存attempt照会を確認した。
意図的な実機SSH切断、PC再起動、現在条件の7日完走、メール自動送信、独立コードレビューは未確認。
ZIP配布／SSH疎通だけで全18台が現在の大規模求解可能とは判定しない。
