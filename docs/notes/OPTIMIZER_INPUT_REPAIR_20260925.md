# 最適化入力の距離・経路修正とブランチ整理（2026-09-25）

## 確認した経路と修正

- `/catalog/milp-trips` → `local_db_catalog.build_milp_trips` → dispatch変換で、起終点だけの距離を使っていた。便別 `trip_stops` を一括読み取りし、全隣接停留所の地理的代理距離へ統一。循環便・区間便を元の便ID・起終点のまま扱う。operatorと距離出典、経路hashを保存する。
- 手動SQLite→built→Prepareの出力も同じ便別距離へ変更。同じ系統の方向・区間便を路線群の代表パターンへまとめず、元のODPT pattern IDをroute IDとして維持する。新datasetのみ生成し、既存builtへの上書きを拒否する。
- 存在しない `data-prep/lib/manifest_writer.py` への依存を除き、現在のv1 artifact contractに沿って元DB SHA・出力hashを保存。便別 `stop_times.parquet` とoperatorを出力する。
- Prepareの欠損座標が0へ変換される経路を修正。欠損・非有限値・緯度経度範囲外・列の欠番/重複・便自身の起終点不一致を距離補完で通さない。DB抽出時の不正は便IDと理由を含むHTTP422で返す。
- SQLiteの `with connection` は接続自体を閉じないため、カタログの全読取接続を `closing` で閉じる。Windowsでスモーク確認直後にDBを移動できない問題を実機再現し修正した。取込の読取検査失敗時は正式名のDBを公開しない。
- 地球半径は既存Prepareの6371 kmを維持。初回照合で検出した共通geo既定半径との差を解消し、新しいDB出力とPrepareの距離を一致させた。道路距離へ精度を格上げしたという意味ではない。

## 保存済みデータでの検証

| 対象 | 便数 | 結果 |
|---|---:|---|
| 2026-09-24 Go取得の全社SQLite | 33,484 | 全便の停留所列・座標・便自身の起終点・operatorを検査、失敗0 |
| GTFS参考SQLite | 33,354 | 同上、失敗0。ODPTと混ぜず別の証拠として保存 |
| 旧2026-03-11 ODPT加工済みデータ | 33,360 | 全便の経路距離算出可。代表パターンの終点と違う42便も便自身の停留所列と一致 |
| 新規全社built 747パターン | 33,484 | 距離0/負値0、operator欠損0、manifest照合通過。Prepare距離再算出との差の最大0 km |

旧42便の便別終点はそのまま残す。区間便を代表パターンの終点まで勝手に延長しない。旧路線マスタの距離0を便別距離に代えて読むこともない。原本・既存シナリオ・既存Preparedは上書きしていない。

証拠は `output/optimizer-input-repair-20260925/` の `company/summary.json`、`gtfs/summary.json`、`legacy_path_audit.json`、`legacy_endpoint_differences.json`、`export_prepare_validation_final.json`。最終出力は `built/tokyu_company_trip_paths_final_20260925/`。最初の半径照合用出力は別に残している。

全社元DB SHA: `bcbdc9841710d1de9b3e0fcf3a1c79c6fe9efec8364e8fd9117b08b6da572a1d`。

## 回帰と主張範囲

Python関連101件通過。API422、区間/循環便、座標欠損・NaN・Inf、経路欠番、上書き拒否、原本保全、DB公開失敗、Prepareとの距離一致を含む。依存ライブラリの非推奨警告2件。画面コードは変更していないためフロントの再ビルドは対象外。CI・AI監視・新しい求解は起動していない。

自己レビューの対象P1は上記の修正・関連回帰で解消。独立レビュー、新版での7日間求解、全PCへの新版配布は未実施。全社カタログの欠けた営業所所管、正式fleet、実道路距離、受電設備の物理定格をこの修正で承認したわけではない。元の未割当所管は未割当のまま保存し、正式シナリオのPrepare契約は維持する。旧実験は旧SHAの成果であり、新版の成果へ読み替えない。

## ブランチ整理

mainに到達済みかつworktreeで使用していない12ブランチを `refs/archive/20260925/<元ブランチ名>` へSHA一致確認後に退避し、`git branch -d` で通常一覧から外した。復元は `git branch <元ブランチ名> refs/archive/20260925/<元ブランチ名>`。退避参照はローカル専用、各コミット自体はmainの履歴に含まれる。

`output/optimizer-input-repair-20260925/branch_inventory_before.json` と `branch_archive_receipt.json` に対象・SHA・保持理由を記録。main・現在ブランチ・週別計画ブランチ、未統合作業、worktreeのHEADを指す実験版、PR用の研究ブランチと明示的バックアップは保持した。worktree・実験成果物・ローカル取得原本を削除していない。
