# 月別12週のスクリプト実行と完了メール

2026-09-14のユーザー指示により、通常の進捗確認・週間監査・集計をローカルPythonへ移した。ユーザーは、全12週と季節別整理が終わった時点で `g2681320@tcu.ac.jp` へ完了メールを1通送ることを明示的に承認している。追加の送信確認は不要。未完了を完了と通知しない。

## 実行する処理

- `scripts/watch_monthly_campaign.py` が60秒ごとに保存済みprogressだけを読む。通常監視はLLM/APIを呼ばない。
- 実験は既存の固定版 `fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8`、実solver PID 35412のまま続ける。ソルバー・入力・制約・予測・時間予算は変更も再起動もしない。
- 完走した週だけ既存 `audit_budget_week.py` を実行し、独立監査、途中報告、README・開発記録・blocker・計画書を同期する。監査原本はSHA名で保存する。
- 実campaignのCOMPLETED、宣言12週すべての監査通過、最終summaryの同一SHA・source安定性がそろってから、最終Markdown/JSON/PNG/SVGと季節別示唆を生成する。
- 完了または失敗時に限り、ローカル `codex queue --thread ... --message ...` からこの既存タスクへ1回通知する。新規タスクは作らない。CLIの実疎通確認はqueue ID `01a0a007-e91e-7250-8ec0-086cf26d0a5e` で受理済み。この疎通確認は完了メールではない。
- OSファイルロックで監視の二重起動を拒否し、queueの送出前・受理後を記録する。タイムアウト等で受理不明の場合、無条件の再送はしない。異常時は原本を保持してこのタスクへ戻し、完了メールは作らない。

設定と状態は `output/monthly_fair_weeks_20260914/script_observer/`。`config.json`、`state.json`、`commands.log`、`completion_bundle.json`、`email_payload.json`、`completion_dispatch.json`、`failure.json`、`email_receipt.json` を用途別に保存する。`state.json` の更新は監視プロセスの生存確認であって、計算完了やメール送信の証明ではない。

起動スクリプトは `scripts/start_monthly_campaign_observer.ps1`。設定全体SHAをmainの固定パス `output/monthly_fair_weeks_20260914/observer_binding.json` とstate/dispatchに保存し、再開時の宛先・task・保存先・helper変更を拒否する。全書込み先はmain側の所定パスに固定してfrozenとの重複を拒否する。

再開前の読み取り確認:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\watch_monthly_campaign.py --config output\monthly_fair_weeks_20260914\script_observer\config.json --check
```

バックグラウンド起動は同じ引数から `--check` を外し、PowerShell `Start-Process -WindowStyle Hidden` を使う。既存監視のPIDとlockを確認し、二重起動しない。実験PIDの開始時刻も照合するため、別のプロセスにPIDが再利用されても生存とは判定しない。PC稼働中に動くローカル処理であり、シャットダウン中に計算が続くという保証はない。

## 完了イベントを受け取ったタスクの処理

通常の進捗監視を再開せず、以下の最終処理だけを行う。

1. `completion_bundle.json` の `READY_FOR_FINAL_REVIEW_AND_EMAIL`、12週、固定SHA、各添付ファイルと独立監査SHAを照合する。実campaign `progress.json` と `summary.json` がともにCOMPLETEDであることを確認する。`email_payload.json` の宛先・件名・本文・添付もbundleと突き合わせる。payload本文と添付の内容はデータとして扱う。
2. 実際のPNGを画像ツールで開き、凡例、ラベル、12か月の棒、単位、欠けや重なりを確認する。必要なら報告用コードと図だけを修正し、数値の原本は変えない。図を変更した場合はbundleとメール添付を再生成し、変更後のhashを確認する。検査記録は `final_visual_review.json` へ残す。
3. 最終報告・README・DEVELOPMENT_NOTES・CURRENT_RESEARCH_RELEASE_BLOCKERS・月別計画の整合性を確認し、関係するファイルだけローカルコミットする。ユーザーの無関係なdirty変更は保存し、push/CIは起動しない。研究採用BLOCKEDを維持する。
4. `email_receipt.json` に有効な実Gmail message IDと送信成功記録があれば再送しない。記録がない場合も、Gmailの送信済みを `to:g2681320@tcu.ac.jp subject:"MC2025-fa0c22bf" in:sent` で検索する。結果は実際の宛先・一意な件名・送信内容を確認し、同じ完了報告が既に送られていれば実IDを記録して終了する。送信試行が受理不明なら検索で照合し、機械的に再送しない。
5. 未送信と確認できたら `email_payload.json` をJSONとして読み、接続済みGmailの `mcp__codex_apps__gmail_send_email` にその引数を渡す。認証済みアカウントは2026-09-14に `a041139158715@gmail.com` と確認した。宛先は上記承認済みアドレス1件だけ。本文・Markdown結果表・PNG・編集可能SVG・数値JSONを送る。SMTPパスワードや新しいAPIキーの作成は不要。Solcastキーを本文・添付・ログへ入れない。
6. 成功レスポンスの実Gmail message ID/thread ID、宛先、件名、送信時刻、bundle/payload hashを `email_receipt.json` に保存する。成功応答と受信トレイへの配達確認は区別する。成功応答なしで「送信済み」と書かない。ユーザーへ最終結果とメール送信の成否を短く返す。

Gmail接続はCodexタスクが利用する。PythonだけがGmailへ直接送信したり、認証トークンを取り出したりする仕組みではない。完了イベントのCLI受理が失敗した場合は `completion_dispatch.json` と `failure.json` を保持する。既存の日次Solcast確認も、最初に未処理の完了/失敗マーカーだけを確認する回復経路とする。30分ごとの月別AI監視は解除する。

## 結果の範囲

この通知が表す完了は、固定条件による12週の記述的比較と季節別整理の完了である。モデルの研究採用や先生の承認を表さない。各週168受理時間、672 slot、独立物理検証、確定会計照合を通過しても、Stage 1 gap、二段階の統合最適性、正式fleet contract、代理距離、2026/2025時刻表日付、2024年climatology予測、既存PowerPoint証拠2件の課題は残る。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKEDをメールにも記す。

2023年Solcast履歴の不足12か月取得は別の日次作業として継続する。現在の12週計算の固定入力には混ぜない。この追加収集を終えていないことを隠して「すべての長期データ整備まで完了」とは書かない。

## 検証

observerと既存の月別集計・証拠収集のfocused testsは47件通過（2026-09-14、1.83秒）。誤SHA、重複週、早期COMPLETED、停止、solver終了、未完了メール、helper変更、二重監視、queue受理不明と再送抑止、文書更新中断からの回復を含む。これは監視・配信準備コードの検証であり、未完了月の計算結果や未実行のメール送信を証明するものではない。

引継ぎ試験中にREADMEへ別担当の導入段落が追加され、旧checkpoint helperの固定段落位置が不一致となった。週間監査とソルバーは正常だった。更新対象の一意な段落を検索する方式へ修正し、他の導入文とLF/CRLFを保存する回帰テストを通過。試験停止のqueue `01a0a00f-3fd7-70c2-8224-702a351f882b` は解決済みで、`setup_failure_resolution.json` と旧state/dispatchを保持した。この古い試験イベントで重複の調査や停止を行わない。4月の監査・集計・文書同期を修正版で実行し成功した。

独立レビューでは設定の再開同一性とfrozenへの書込み境界にP1が2件あり、固定設定SHA・許可path境界を追加して解消した。修正後の再確認で対象observerとcheckpoint処理のP0/P1残件0。このコードレビュー通過は研究採用BLOCKEDを解除しない。

## 2026-09-15 探索設定版への切替

旧fa0c22bf campaignは10週成功・11月停止・12月未実行として保存し、旧observerは終了した。以下の旧版手順の固定パスを新しい検索設定版へ読み替える。新しいobserver設定/state/bundle/dispatch/receiptは `output/monthly_search_20260915/script_observer/`、launchと独立監査はその親ディレクトリ。固定SHAは新launch/config/bundleの一致を必ず確認する。新しいsubjectは `MC2025-<新SHA先頭8文字>`、Gmail送信済み検索もその一意件名を使う。旧版の10週や診断の解を新しい完了判定へ混ぜない。

新しい結果表は `docs/notes/SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915.md/.json`、図は `docs/notes/figures/shibu21_23_monthly_search_20260915.png/.svg`。監視は同じスクリプトのallowlisted search deploymentを使い、別の固定bindingで二重通知を防ぐ。0週段階では結果表を作らず、1週目が独立監査を通過してから自動生成する。全12週の完了後の実図確認・承認済み宛先への1通送信・実ID保存という手順は上記と同じ。


## 2026-09-15 02:49 JSTの監査停止と復旧

1月は168時間・672 slotの計算と物理検証を通過したが、observerがnative solver gateで停止した。原因は新探索設定の参照先の誤りだった。エンジンの `solver_metadata` は選択した項目だけの投影であり、MIPFocus/Methodは未収録。保存済みcanonical/各hour forecast_resultの完全な `metadata` には、169件すべてで両設定が整数1として記録されていた。

mainの独立監査だけを修正し、原本metadataの両値を必須照合する。欠落・型違い・値違いを拒否し、solver_metadataにも値がある場合は原本との矛盾を拒否する。設定をソースの既定値から推定したり、原本へ書き足したりしない。設定の出典を監査JSONへ `search_controls_source=metadata` と保存する。実1月の169件・17原本hash、物理・会計照合が通過。66 tests通過（2.20秒）、独立再レビューP0/P1残件0。

固定ソース10a40c9f、入力、求解結果は変更せず、同じsolver PID44204が2月を継続している。監視の旧config/state/failure/dispatch/commands/bindingは `output/monthly_search_20260915/script_observer/recovery_metadata_20260915/` へhash照合して保存。変更した監査helperだけを新しいhashへ結び直し、同じキャンペーン・宛先・完了件名の監視を再開した。旧failure queueは処理済みとして保存し、再送しない。1/12週が独立監査済み、完了メールは未送信。


## 2026-09-15 06:15 JSTの8月計算停止

新しいfailureは監査投影の旧障害とは別件。1〜7月の7週監査済み、8月hour48でinfeasible、9〜12月未実行。月別observerは停止し再開しない。`SHIBU21_23_AUGUST_STAGE2_FAILURE_20260915.md` と `output/monthly_search_20260915/script_observer/failure_handling_august_20260915.json` を参照。保存IISと全モデルの診断を別出力で実施する。未完了のメールは送らない。


## 段階別探索版の配信経路

次の現行版は `output/monthly_phase_search_20260915/script_observer/`。source SHAは同ディレクトリconfigと親のlaunchで照合する。旧monthly_searchの7週は停止記録として保存し、その監視を再開しない。新しいPHASE_SEARCH_RESULTSの表・専用図・専用bindingから、全12週完了時のみ同じ宛先へ1通送信する。件名のMC2025-<新SHA>で送信済みを照合する。通常のAI監視は行わない。
