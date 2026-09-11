# Tkinter主要操作のElectron移行（2026-09-11）

対象は `run_app.py → tools/gui/scenario_backup_tk.py` で使っていた主要操作群。
新しい入口は `run_desktop.py → frontend/electron/main.ts → React → localhost BFF`。
Prepare・ソルバー・報告finalizerは既存の経路を使用する。

| 操作群 | 新しい画面 | 保存・実行経路 |
|---|---|---|
| シナリオ作成・名前/説明・複製・既定化・削除 | シナリオ選択/設定 | 既存 scenarios API |
| 対象営業所・路線・運行日・期間・料金・SOC・solver/objective | 運行・計算設定 | desktop configuration → UpdateQuickSetupBody |
| 車両/テンプレートのCRUD・一括作成/複製・初期SOC/営業所/使用可否の一括変更 | 車両 | 既存 master_data API |
| 営業所・充電器の数/電力・路線variant/方向 | 営業所・路線 | 既存 master_data API |
| PV有効化・容量/面積、BESS容量・残量・効率・流入出・終端方針 | PV・BESS設備 | 既存設備normalizer → Prepare/ProblemBuilder |
| 気象CSV、PV proxy、代表曲線、典型気象proxy、日付別PV生成 | 気象・PVデータ | Tkinterと同じpreprocess関数・既存PV API |
| 時刻表CSV入出力・calendar/例外/permission・派生データ生成 | データを確認 | 既存store/graph/calendar API |
| Prepare・最適化・simulation・観測値から再最適化・rolling・job監視 | 実行 | 既存 prepared-input/optimization/rolling API |
| 車両ダイヤ・SOC・営業所電源フロー・費用明細・simulation summary | グラフ・費用明細 | 保存済みresultとvehicle_timelines.jsonのbounded投影 |
| Excel/CSV/PDF/PNG/JSON/Markdown成果物の取得 | グラフ・費用明細 | 保存済みrun output内の限定ファイル |
| A/Bの保存済み指標・条件・採用判定の差分 | シナリオ比較 | 2シナリオのread projection |

## UIとデータの扱い

左メニューを用途別に整理し、シナリオ選択を検索付きダイアログへ移した。
編集中の画面を保持し、未保存の設定があるとシナリオ切替・実行を止める。
保存時は変更項目だけを渡し、revisionが違う場合は409で再読込みを要求する。
同じBFFプロセス内では既存scenario RLockを共有する。別プロセスとの完全な
トランザクション保証ではなく、最終的なPrepare/実行契約は既存ゲートで確認する。

一覧は最大250行/ページと仮想スクロール。SOC・電源フロー・ledgerも250件/ページ。
車両/営業所系列の選択候補、テンプレート/営業所フォーム候補は先頭250件まで。
結果ダイヤは保存済みイベントを表示し、配車を再生成しない。系列の欠損や非有限値を
ゼロへ補正せず、非有限値は文字として残す。図の横軸は時間枠番号、ダイヤは保存時刻。
画面の図表はsolver計画であり、実行済みrolling会計と同一視しない。

CSVは全列を保ち、各セルをJSONで符号化する。互換alias行も含むSQLiteの全行を
read transactionで書き出す。取込みは20 MBまでで、列・ID重複・時刻・事業者ID・
正の距離を検査し、previewの入力revision/hashが一致する時だけ明示的に置換する。
置換前のCSVを別名保存する。欠落operatorや距離の生成、時刻の自動補正はしない。
これは構造の検査であり、CSV取込みだけでは研究provenanceの成立を認定しない。

気象ファイルはUTF-8のCSV/JSONを選択でき、別名のlocal outputへ複製する。
ローカルdata/output外のパスをサーバーが直接読むことは許可しない。
結果ファイルは保存済みauditのoutput配下、許可された拡張子、100 MB以内に制限する。
画面からファイルを実行しない。新しいAPI・CI・外部データの有料呼出しは追加しない。

## BESSの数学的な変更範囲

20〜80%ボタンは容量Cに対して下限0.2C、上限0.8C、期間末floor 0.2C、
`minimum_only`、`evaluation_period`、目標SOCなし、目標逸脱費用0を保存する。
容量・初期残量・充放電能力・効率・電力単価は維持する。保存されたBESS rolling方針を
production rolling requestへ転送する。日付別Prepareは明示されたasset終端方針を
保持し、未指定の旧ケースだけ従来のreturn_to_initialを使う。
BEVの初期SOC復元やday-ahead境界状態、接続条件、fleet/距離/事業者の契約は緩めない。
期間末に初期蓄電量を使い切れる条件なので、完全補充を要求するケースの費用と
同条件比較したり、蓄電量の差を金額の補正へ転換したりしない。

## 検証と残る制限

BFF編集・入出力の24テスト、Reactの13テストを実行。既存APIを使う車両/テンプレート
CRUD・複製・calendar保存、設定revision、SOC単位、BESS policy、CSV全行/型往復、
出力範囲外アクセス拒否、simulation/optimizationの分離を含む。
Electronの全10メニュー、旧parent結果、900px幅のoverflow検査とnative artifact
ダウンロードも確認した。証拠は `output/desktop-smoke/`。

UTF-8を明示した全体回帰は2,124件通過・2件失敗（101.97秒）。失敗は既存の
PowerPoint原本hash不一致とspeaker-notes版の部品集合不一致であり、資料を
書き換えて検査を通すことはしていない。JUnitは
`output/desktop_parity_validation/pytest-final.xml`。TypeScriptと配布ビルドも通過した。
portable EXE（101,661,135 bytes、SHA-256
`3e18e2d60527ce4858ba606cf9ec3104860162ced4c8dbb73010622159925267`）
でも18:57 JSTのsmokeが終了コード0。全10メニュー、900px幅4画面、旧parent結果の
表示と54,437 bytesのnative downloadを確認した。非表示窓の撮影ではCSS transition
を停止し、通常表示には影響させない。検証記録は `output/desktop_parity_validation/`。

独立コードレビューの確認範囲は `desktop_store` のsummary/paging/artifacts/timeline、
`desktop_configuration`、時刻表/気象service、ResultDetails/VehicleBulkEditor/WeatherPanel。
確認済みP0/P1は0件。SQLite CSVの二回走査に関する候補指摘は、現行factoryが毎回
新cursorを作ることと実SQLiteの往復テストにより非該当と確認した。認証境界の以前の
独立レビューと今回の検査は範囲を区別する。全成果物種類の目視やモデル全体の承認ではない。
全Tkinterメニューの逐語的な一致や研究レポートの新規再生成を意味しない。
既存の生成済みレポートを取得できる。外部認証が必要な取得処理は別管理である。
正式研究リリースは既存PowerPoint証拠、fresh clean-commit正式実行、研究採用等の
未解消ゲートによりBLOCKEDを維持する。

4季節診断は別のclean frozen SHA `e8bd9d6c` で4週の完全Prepareまで完了した。
冬週のモデル構築をPCのメモリー逼迫により停止し、他3週は未実行である。
[資源不足の証拠と未完了ゲート](SHIBU21_24_RESOURCE_BLOCK_20260911.md)を参照。
MAINの画面追加・BESS保存経路・統計用リスト生成の変更後SHAのsolver証拠へ付け替えない。
