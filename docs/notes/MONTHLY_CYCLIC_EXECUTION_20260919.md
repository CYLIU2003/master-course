# BESS週末復元条件の月別12週・スクリプト実行

<!-- monthly-cyclic-status -->
最新の月別再実行: 固定 `2ff239e1`、独立監査 3/12週、状態 `STOPPED_AFTER_FAILED_CASE`。全月共通MIPFocus=1・前日Method=1・rolling Method=0、物理許容差1e-9。BESS週末復元条件。旧7c7c2334の12週は旧条件の記録として保持し、新版には混ぜない。研究採用BLOCKED。結果: `docs/notes/SHIBU21_23_MONTHLY_CYCLIC_RESULTS_20260919.md`。
<!-- /monthly-cyclic-status -->


2026-09-19、ユーザーが再開始と `g2681320@tcu.ac.jp` への完了メールを承認した。前の実行保留指示は、この新しい実行について解除された。

18:09 JSTに起動。固定SHAは `2ff239e1dc488409e8cf215bff918953fd36346f`、作業場所は `C:/Users/RTDS_admin/.codex/worktrees/monthly-cyclic-20260919/master-course`。campaign実PID42140、observer実PID30992。開始確認時は1月のPrepare、完了0/12週、監視RUNNING。固定版の関連70テスト、入力47件・metadata refs11件、helper hash・Gmail接続を確認した。現在の進捗は以下のstateを参照する。

- 設定: `config/shibu21_23_monthly_cyclic_20260919.json`。編集保留版は別に保存したまま、実行用だけ `execution_enabled=true` とする。
- 全12週を新しいclean固定版から新規Prepare・day-ahead・168時間rollingの順で逐次実行。旧 `7c7c2334` の12週や失敗版の週を流用しない。元の親シナリオ、入力47ファイルと予測はハッシュ照合してコピーし、親metadataのrefsだけ新しい作業場所へ移す。
- 新条件はBESS週末の初期残量復元と、中間rolling窓の固定day-ahead予測境界。20–80%範囲、全接続、物理許容差、共通時間予算、車両・時刻表・単価は前の修正案を維持する。実行中にコードや条件を変更しない。
- 制御・ログ: `output/monthly_cyclic_20260919/`。固定SHA・実PID・開始時刻・計算場所は `budget_rerun_launch.json`、監視設定は `script_observer/config.json`、現在状態は `script_observer/state.json`。
- 通常は `watch_monthly_campaign.py` が60秒ごとに保存progressだけを読み、完走週だけスクリプトで独立検算する。定期AI起動、新しいAIタスク、AIの常時伴走は行わない。
- 全12週の受理、固定SHA、独立物理・会計・BESS週末復元の照合後に、専用結果表 `SHIBU21_23_MONTHLY_CYCLIC_RESULTS_20260919` と専用図を生成する。旧版の表・図・メール受領記録は保持する。
- 終了時だけ既存タスクへ一度queueする。完了ならbundleのhashと実図を確認し、接続済みGmailで承認済み宛先へ1通送る。Python監視がGmail認証情報を取り出すことはない。異常終了では完了メールを送らず、失敗原本を保存して一度通知する。自動再試行で実験条件を変更しない。
- 重複防止: 新SHAの件名 `MC2025-<新SHA先頭8文字>`、専用receipt、Gmail送信済み検索を照合する。送信成功の実message IDを新 `email_receipt.json` へ保存する。旧メール `1a0a32dde20e11bc` は別条件の配信済み記録。
- 最終配信の詳細は [既存手順](MONTHLY_COMPLETION_DELIVERY_20260914.md) を使用し、パスは今回のcyclic専用、source SHAは新launch/bundleの一致を必須とする。

準備検証は、監視・報告・証拠収集・月別BESS設定・campaignの関連89テスト通過。前回のモデル修正128テストは同じ内容として再利用した。独立した研究承認は未取得であり、今回もDIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKED。BESS放電0の原因や費用・ピーク削減効果を実行前に断定しない。

計算はローカルPC上で進む。最終結果・完了メールが実際に成立するまでは、起動を完了と表記しない。


## 2026-09-19 20:14 JSTの停止

現在は3/12週通過、4月hour158で停止、5〜12月は未実行。既存solver PID42140とobserver PID30992は終了を確認した。失敗イベントは処理済みで、同じ通知から監視再開やメール再送を行わない。系統からBESSへ充電できず、残り予測PVによる終端上界が目標に54.411 kWh届かないことを確認。次のモデル条件選択待ちで、計算・監視は停止のまま。詳細は[4月停止原因](SHIBU21_23_APRIL_BESS_TERMINAL_FAILURE_20260919.md)、対応記録は `script_observer/failure_handling_april_20260919.json`。新条件を採用する場合は全12週を新clean固定版で実行する。
