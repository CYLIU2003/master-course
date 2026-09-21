# 月別再実行の初期配車チェックにおけるログ設定修正

<!-- monthly-auxiliary-logfix-status -->
最新の月別再実行: 固定 `818e78d0`、独立監査 2/12週、状態 `STOPPED_AFTER_FAILED_CASE`。全月共通MIPFocus=1・前日Method=1・rolling Method=0、物理許容差1e-9。BESSはPVバス優先・余剰蓄電・20～80%内で補助使用。追加予備・終端復元なし。Stage1 1800秒・4threads・目標1%、Stage2 Presolve2。旧結果は混ぜない。研究採用BLOCKED。結果: `docs/notes/SHIBU21_23_MONTHLY_AUXILIARY_LOGFIX_RESULTS_20260921.md`。
<!-- /monthly-auxiliary-logfix-status -->


## 確認した停止原因

固定27253fa8の新規Prepareは完了したが、1月day-aheadの本Stage1開始前に停止した。
内部の有限燃料用MIP-start候補チェックが `phase3_diagnostics_dir=""` としていた一方、
前回追加した `stage2_native_log_enabled=True` を継承していた。Stage2アダプタの
ログ保存先チェックがValueErrorを出した。前回の変更による回帰であり、
BESSの実行不可能性、前処理設定の失敗、求解時間不足を表す結果ではない。

到達経路: 月別campaign → 新規Prepare → `solve_week` → `OptimizationEngine.solve`
→ Phase3 → `_problem_with_finite_fuel_warm_start` → `_finite_fuel_seed_energy_audit`
→ Stage2モデル初期化。原本は旧制御先
`output/monthly_auxiliary_presolve_20260921/script_observer/failure.json` と、
同固定作業場所の `cases/2025-01-06/diagnostic/2025-01-06/summary.json` 内traceback。
最初の週間監査前なので `commands.log` は未作成。監視は元理由を正しく保存した。
成功0/12、rolling0/168、2～12月は未実行。完了メールは送らない。
旧失敗queue `01a0c36b-ef1c-7190-9c7c-1b5342391b69` と旧固定版を保全する。

## 最小修正と検証

内部候補チェックのlocal problemだけ `stage2_native_log_enabled=False` とし、
既存の「内部チェックでは成果物を出さない」方針と整合させる。
親problemは不変、本Stage2と毎時rollingは指定先へnative logを引き続き保存する。
内部チェックの採否/status/秒数は従来どおりpre-solve seed metadataに残る。
目的関数、配車範囲、SOC、BESS、予備・復元、許容差、求解予算、Presolve2は変更しない。

- 本Phase3から内部nativeチェックを経由する回帰テストで、修正前は同じValueErrorを再現。
- 修正後、ログ有効/無効の両条件で内部チェック→本求解が通過。
  fleet/timetable・燃料在庫・便カバーを維持、本求解ログの存在と親設定の不変を確認。
- 有限燃料seed、Stage2数値境界、BESS補助方針、時間予算/rolling、日別帰庫の94 tests通過。
- 新run identity・監視・月別報告の60 testsも通過（合計154）。
- 新configはrun identityの3項目（manifest先・派生元・修正説明）だけが前版と異なる。
  全12週、時間/threads/seed、BESSと物理会計ゲートは共通。

前回の検証は固定配車Stage2と第一時間が中心で、内部seedチェックを含まなかった。
今回その入口からの回帰を追加した。ローカル通過を全月完了と表現しない。

## 新規実行と通知

新しいclean固定版・ブランチを作り、同じ全12週を新規Prepareから開始する。
制御先 `output/monthly_auxiliary_logfix_20260921/`、計算作業場所
`C:/master-course-worktrees/monthly-auxiliary-logfix-20260921`、
設計 `config/shibu21_23_monthly_auxiliary_logfix_20260921.json`。
旧出力を採用せず、新版のlaunch/config/observer bindingと固有件名を使う。
通常処理はスクリプト、全12週の独立監査と図表確認後に承認済み宛先へ1通送信する。
失敗は元理由を保存して既存タスクへ一度だけ通知する。

実行固定 `818e78d05021e0cdf1a62b637c03b1dbfc9a604a`、19:11 JSTに開始。
19:12の一度の起動確認で計算PID44076・監視PID35696とも生存、1月PREPARING_WEEK・完了0/12。
47原本hash/11参照、新旧固定版clean、旧solverの停止を照合した。
証拠: 今回の `startup_verification.json`、`budget_rerun_launch.json`、`script_observer/state.json`。
旧 `script_observer/failure_handling.json` に元failure/dispatch hashと新版への移行先を保存。
旧原本は変更せず、完了メールも送っていない。

起動前に同じ1月保存入力で内部nativeスクリーンを1件だけ実行し、0.483秒でinfeasibleを
返すことを確認した。これは個別候補の不成立を正常に判定できた証拠であり、その候補・
初期案全体・新週間計画の物理通過ではない。`saved_seed_screen.json` に別診断として保存し、
新規12週の結果へ流用しない。

## 自己レビュー

Codex、2026-09-21。対象のログ設定矛盾P1を修正、修正前失敗/修正後通過を確認。
本求解側の保存先必須条件と物理検査を保持。対象変更の未解決P0/P1は0。
独立レビューは未実施。Stage1 gap/メモリ・週間総費用の統合最適性・研究採用は別途未解決で、
研究採用BLOCKEDを維持する。CI/有料サービスの追加起動は行わない。
