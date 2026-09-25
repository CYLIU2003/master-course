# 計算の詳細進捗表示 — 2026-09-25

## 変更と適用範囲

- `ExecutionProgress` を「期間別計画」「分散計算」に追加。前者は選択したシナリオ、後者は選択した監視先を参照する。
- `publish_execution_detail.py` は既存weekly operation、controller API、workerの保存済み記録を読み、`execution-detail.json` を原子的に公開する。複数のoperationを指定でき、特定路線や月に固定しない。
- `execution_detail.py` は標準ライブラリのみ。SSHの標準入力で読取処理を送り、workerの固定ソースにファイルを追加しない。Env/Model起動・計算投入・キャンセル・秘密情報取得は行わない。
- attempt IDとmanifest SHAをcontrollerとworker間で照合。複数runの混在、部分書込、照合不一致を現在進捗として採用しない。SSH読取失敗時は直前の証拠を残す。controller障害時も過去の試行を保持し、接続不明とする。
- native logは末尾64 KiBを読み、数値行・既定の求解状況行だけを表示。ライセンス認証情報やSSH設定を配信しない。
- 画面は狭い幅でも文字が縦一列にならないカード表示。詳細ログだけ横スクロールで読める。

## 数値の意味

入力準備・計算終了・検算集計の件数を分離。FAILEDは計算終了の成功件数に含めない。
毎時計算の分子は、保存済みhourly_summaryでfeasibleかつ引継ぎ拒否・PV実行エラーなしの窓数。
分母は投入manifestのexpected_rolling_windows。週の後の充電時間を含む174/175窓などを168で割らない。
この窓率は全週の物理・会計検証、最適性、残り時間を証明しない。chain_acceptedと週次検算も別表示。
Stage 1/Stage 2のgapは当該求解のログ値であり、統合週間費用のgapではない。

## 稼働系への配置

- 管理画面8868と計算画面8891が使う静的frontendへ、新buildのhashed assetsを追加し、indexを最後に差し替えた。旧indexを保管。
- 計算固定SHAは `cf4beb973169b2e0ecc771882838adb6d9bc58dc` のまま。controller・solver・実行中の試行を再起動していない。表示版と計算版は別。
- 読取監視は `output/monthly_latest_20260925/operation.local.json` を参照。AIを呼ばず30秒間隔。停止後は同ディレクトリの `operator/07_DETAIL_WATCH.cmd` で再開可能。OS再ログオン時の自動再開は今回追加・試験していない。
- 14:02 JSTの実表示: 入力準備10/12、計算成功0/12、検算0/12。2月と4月がStage 1。2月はログ1665秒、barrier97反復、native gap46.7%。これは途中経過で、収束・週間成立を意味しない。
- 1月・3月は64GBのdesktop-3pru7qpで `GUROBI_LICENSE_UNAVAILABLE`。メモリ停止とは扱わない。既存のdisable APIで当該workerへの新規割当を止めた。他の2件の実行は継続。ライセンスの原因解消・両失敗の再試行は未実施。

## 検証・レビュー

- Python: `controller-venv/Scripts/python.exe -m pytest tests/test_execution_detail.py tests/test_weekly_operator.py -q`、25 passed。
- frontend: `npm.cmd test -- --run src/components/ExecutionProgress.test.tsx src/components/PeriodPlans.test.tsx`、5 passed。
- 既存の分散画面への影響も確認し、`npm.cmd test -- --run` は13ファイル・60 passed（上記5件を含む）。
- `npm.cmd run build`（TypeScript、Vite、Electron型検査）通過。
- 2台のSSH実読取、attempt/hash照合、実ブラウザーの詳細表示・日本語・狭い幅の表示を確認。
- 自己レビュー: 配車探索を推定％化しない、失敗を成功へ数えない、通信断時の最後の証拠保持、複数run混在の拒否を確認。対象に残るP0/P1の自己検出はなし。独立レビューは未実施。
- ソルバーの数理・入力・SOC・費用・研究採用gateは変更なし。この表示検証は12週完走や研究採用の証明ではない。
