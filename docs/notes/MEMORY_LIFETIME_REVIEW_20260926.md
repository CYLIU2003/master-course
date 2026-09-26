# メモリ寿命の独立レビューと対応（2026-09-26）

- 対象: 0b433705 と、その後のモデル寿命修正差分。Claude Code 2.1.283 / 実応答 `claude-opus-5-5`。利用者が指定した既存Claude認証を使用。
- 方法: 秘密情報を含まないソースコピーのみをRead/Grep/Globで静的確認。独立レビュー側は求解・端末変更・テストを実行していない。
- 最初のP1: 単一候補以外のStage1/統合モデルの終了時解放漏れ、フィードバック再試行中の失敗Stage2保持。公開solve/近傍探索の所有scopeと再試行前解放で修正。
- 続く独立レビュー: 確認差分について新規・未解決P1なし。全体プロセス16GiB内の実機検証を代替しない。
- P2対応: 所有scopeの入れ子とsession所有の再登録を区別、制限設定前のモデル登録、不要な全期間台帳をprefixから除外、None-map互換、全モデルのcleanupを試して失敗を保持。独立追加レビュー後にsession-levelでも元の実行例外とcleanup失敗を併記する修正と回帰2件を加えた。この最後の変更は自己検証済み、再独立レビューは未実施。
- 不採用提案: cleanupが失敗しても無条件でEnv/ライセンス枠を解放すること。ネイティブ資源の消滅が不明な間は枠を保持する。正常cleanupなら元のcancel例外型を維持。cleanup失敗時は原因を含む複合エラーとして終了・照合する。
- 残る限界: native disposeの部分失敗はモックでのみ注入。scopeで失敗したモデルはsession closeで一度再試行し、それも失敗ならgrantを返さない。DLL検索ディレクトリhandleの重複は小規模な別件として保留し、今回の主なGiB級原因とは扱わない。
- 数理・比較影響: 便/距離/車両/SOC/BESS/料金/時間刻み/計算時間/ライセンス数を変更しない。結果保存前の切詰めは行わず、採用区間を集計用に保持するだけ。費用dictと図表CSVの一致をテスト。
- 検証: 対象111件通過、実Gurobiを起動する2件とavailability probe1件は明示的除外。Windowsのメモリ読取10件、画面8件/buildは別変更e6013484で記録。これらは週次完走や研究採用の証拠ではない。
- 実行中: 0b433705 / attempt06809186、2月代表週。candidate_limit1/frontier=false/lookahead24hを実bundleで確認。固定実行コードは変更せず、追加分岐の修正をこの試行へ差し込まない。

## 原本（ローカル、公開資格情報なし）

- `output/prefix_memory_20260926/claude-review/response.json` SHA256 `56ba7662c7ab4aa165a9d767e5d12f48f1284249cb38e14223b7c56d17577066`
- `output/prefix_memory_20260926/claude-review/review.md` SHA256 `05ddfdd46d1c89820fd3f151f35f420226ce09542547a55d39382b4277a61795`
- `output/prefix_memory_20260926/claude-review/review-fix.diff` SHA256 `e47def5cfe74192d100c74991d0f022ffe4f0e4a1f6f06520706b056d30aed08`
- `output/prefix_memory_20260926/claude-review/followup.json` SHA256 `9794a9cc784d5d19f46730acb57ea0efa52e8c00ff276bbab597707c5c2f60d7`
- `output/prefix_memory_20260926/claude-review/followup.md` SHA256 `85c7bd2d419914d072b8bd77dea281081af10eaf8beb9fd400849447643d11b8`
