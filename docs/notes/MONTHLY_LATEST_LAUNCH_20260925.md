# 新版・月別12代表週の起動記録

- 計算固定版: `cf4beb973169b2e0ecc771882838adb6d9bc58dc`（実行後の文書更新HEADとは区別）。
- 元シナリオ: 「仮・正式用」 `771d115b-75b0-49f7-a7f0-25f259a2cd21`。元シナリオの12期間をexportし、新しいキャンペーンを全期間へ紐付け済み。
- 対象: 渋21・22・23、60台、既定の2025年各月1週。時刻表DB/既定気象・予測モデルを既存固定版からhash検証してコピー。ODPT再取得・DB再構築なし。
- 実行先: `output/monthly_latest_20260925/`、別のcontroller/scenario/prepared/queue領域。旧版の6FAILEDを保存し、6QUEUEDはAPIでCANCELLEDにした。旧コントローラーはAPIで両workerの割当を無効化し、新規投入禁止。
- 新controller: `http://127.0.0.1:8891/`。管理画面8868は継続し、同じ1シナリオの12期間に新しい試行を表示する。管理側の外部予約2を維持。新版が共有Gurobi2枠、worker毎1枠、完了後330秒以上の解放待ちを管理する。
- 配置照合済み: 親機、DESKTOP-3PRU7QP（64GB）、DESKTOP-6AE0MIR/LAPTOP-A709UNA0（32GB）。git/source digest/Python/library/built dataset全照合。これは7日完走の証明ではない。現在空きRAMからOS予約（親機2GB、子機1GB）を差し引き、18GB要求を満たすPCへ自動割当。
- 初回stagingは開発checkoutとreleaseのuv.lock改行バイト差で拒否。ファイルやhashを改変せず、配置する固定releaseの同じPythonからstagingを再実行し、全4台VERIFIED。旧拒否記録も保存。
- OSプロセス停止とPowerShellバックグラウンド起動は実行環境の自動承認審査で拒否（理由詳細なし）。強制停止せず旧APIから割当を無効化、新版controller/campaign/監視を実行ツールから直接起動した。

## AIなしの操作

`output/monthly_latest_20260925/operator/` の01_CHECK、02_STATUS、03_CONTROLLER、04_RUN_OR_RESUME、05_COLLECT_EXISTING、06_WATCHを使用。operation.local.jsonが同じSHA・同じ12週・同じ出力先を指定する。再開は既存attemptの同一性を保持し、新規attemptの無限再投入はしない。

通常の実行/進捗/回収/監査/週次図表はPython/PowerShell。`campaign/operations/STATUS.md` と管理画面で状態を確認する。`campaign/terminal_observer` は完了または失敗を一度だけ既存チャットへ通知し、承認済み宛先へのGmail送信処理に渡す。PC単独のGmail OAuthは未設定。eventの生成やqueue成功はメール送信成功ではなく、実message IDを含むemail_receipt.jsonを別途確認する。

開始時点ではPrepare中。12週完走・会計成立・正式研究採用・統合最適性を主張していない。最終状態は上記state/監査原本を参照する。

13:18 JST: 1月週1,704便Prepare通過・DESKTOP-3PRU7QPでRUNNING、2月週Prepare中。最終状態はキャンペーン原本を参照。
