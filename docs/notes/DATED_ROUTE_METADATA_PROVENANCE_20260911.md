# 日付付き入力の路線情報を再読込で保持する

## 検出した不具合

凍結SHA `0132e319` の冬週Prepareは930.1375秒で完了し、遷移・折返し・車種互換性の監査を通過した。一方、路線カタログには22件の便数不一致が残った。保存済みSQLiteとcanonical入力を照合すると、全22パターンの正値距離が0へ、曜日別便数が空の辞書へ置き換わっていた。13パターンでは `canonicalDirection` も変わっていた。3,182便の個別距離はすべて正値を保持していたが、これを路線情報の来歴が保持された証拠とは扱わない。

原因は `scenario_store._repair_route_metadata_from_preload` が、読み込んだ日付付きシナリオの路線情報をglobal preloadで上書きすることだった。保存済みSQLite自体は正しく、観測前後のSHA-256も一致した。詳細は `output/four_route_runtime_observation/dated_route_metadata_drift.json` に保存した。旧canonical入力のSHA-256は `a358f13d9e8915a751a790e54b6ee381cf656348882419a6d53bca354a25aa76`。

## 修正と検査

`multi_day_input_mode=dated_timetable_and_pv_v1` では、scenario storeがglobal preloadを補完元として使わない。対象は路線metadataの補完、欠けたmaster dataの補完、runtimeへの自動付替え、未保存の時刻表・件数のfallbackである。欠損を別の入力で埋めず、通常の入力検証に渡す。日付付きモードを使わない既存シナリオの補完は維持する。

4系統の準備スクリプトは、取得済み路線情報の全フィールドをID別にハッシュ化し、保存・再読込・canonical Prepareの各段階で一致を検査する。並べ替えるのはハッシュ用のキーだけで、入力の路線・便・停留所列は書き換えない。失敗は完全Prepareへ進む前、またはcanonical出力確認時に明示的な例外として記録する。

診断runnerは従来のstrict監査に加え、路線ハッシュ一致、重複しないID、正値かつ有限な路線距離、全路線を確認したカタログ監査のissue 0を要求する。旧成果物のように路線の保存証拠がないケースも `BLOCKED_ROUTE_METADATA_PROVENANCE` とする。

## 数学・比較可能性

接続時間の式、回送・折返しルール、SOC、料金、フリート、取得済み時刻表は変更していない。一方で、モデル構築へ渡る路線距離・方向・variantの実値を取得済み入力へ戻すため、旧SHAのPrepareやsolver出力を修正後の結果へ転用しない。修正後のclean commitから、4週とも新規シナリオ・出力で完全Prepareを行う。

旧 `0132e319` は冬週完了・春週処理中で停止し、solverは開始しなかった。`SUPERSEDED_FOR_DATED_ROUTE_METADATA_PROVENANCE` として元worktreeの `output/old_control_status_superseded_dated_route_metadata_20260911.json` に保管した。旧冬週の監査通過は、修正後入力の採用判定には使用しない。

## 検証

保存後の公開full/shallow/field読取、カタログ件数、欠損時にglobal時刻表を補充しないこと、通常シナリオの補完維持を検査した。新規5テストは修正前に失敗、修正後に通過した。strict監査が通っていても、ハッシュ欠損・方向変更・ゼロ距離・カタログ警告を拒否する回帰も追加し、関連58テストが9.26秒で通過した。

研究採用・統合大域最適性の承認ではない。全体回帰、独立レビュー、修正後の診断結果は別に記録する。

Reviewer: GPT-5.6 Luna、2026-09-11。scenario storeの補完停止、producerのハッシュ照合、runnerの路線来歴ゲートと追加テストを独立した読取りレビューで確認し、P0/P1指摘0件。完全な研究モデルの採用レビューではない。

全体回帰は `python -X utf8 -m pytest -q` で **2,051 passed / 2 failed、88.59秒**。残る2件は既存PowerPointのハッシュ・部品同一性の不整合である。

修正後の4週の候補を新たに保存・再読込して確認し、各22路線の正値距離、カタログ22路線確認・issue 0、取得済み情報とcanonical情報のハッシュ一致、親不変、日付付き時刻表契約を確認した。記録は `output/shibu21_24_route_metadata_candidate_check_20260911/route_metadata_verification.json`。これは完全strict監査を伴わない短い入力確認で、全4件ともcandidate namespace・`formal_prepared=false` のままである。次の完全Prepareの代用にはしない。
