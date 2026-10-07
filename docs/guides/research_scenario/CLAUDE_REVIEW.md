# Claudeとの文書レビューと修正

2026-10-06。実際のClaude Codeへ新規7文書を渡し、Opus・high・1回、ツール利用なしでレビューを受けた。実効モデルは `claude-opus-5-5`。レビューは渡した文書の読みやすさ・内部整合・誤操作防止に限定し、コード・SSH・原計画の独立監査や正式研究承認ではない。

| 指摘 | 確認と反映 |
|---|---|
| 「未コミット作業を保存」が無断commit/stashに読める | 開始文を「そのまま保持・一覧記録、依頼なきGit操作なし」へ具体化 |
| 11・12月のSUBMITTEDと原FAILEDが矛盾して見える | 親campaignと原workerの記録階層を区別し、3件の復旧receipt対応表を追加。comparison/evidenceの実パスと照合 |
| 月別再集計の例に1月の復旧しかない | 11・12月の実在する復旧ディレクトリも引数に追加。件数不足から自動再求解しない手順を追加 |
| controller起動がQUEUEDを再開し得る範囲が曖昧 | BFF lifespan→get_scheduler→startの実装を確認。自動復旧supervisorの切替えとは別に、通常の起動もschedulerを起動すると明記。回収専用依頼で起動しない |
| 既存追加分析の上書きとPythonが不明確 | 固定出力で引数なしの実装を確認。既存の保全・hash・差分確認を条件にし、settingsのPythonへ統一 |
| 1%達成なら週統合最適に読める | 対象段階のgapであり、達成しても週統合最適性を示さないと明記 |

最終修正はCodexがソース・保存メタデータと照合した。Claudeによる修正版の再レビューは行っていない。原コメントを研究ゲート解除の理由にはしていない。

このPCのレビュー原文・実効設定receiptは `output/research_scenario_handoff_20261006/claude_review.md` と `claude_receipt.json`。参照・コマンド・syntaxの確認は[文書検証記録](validation.json)を参照する。原計算や入力は変更していない。
