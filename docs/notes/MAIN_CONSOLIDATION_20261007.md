# main集約とブランチ整理（2026-10-07）

ユーザーの依頼は、現在のローカル変更をmainへ同期し、main以外のローカル・GitHubブランチを削除すること。開始時のmain、origin/main、作業ブランチは同じ57e959173635643394bc694a4773404bf0976b49だった。

## 同期する内容

- 先生コメントを反映した発表資料、13・14・16ページの説明と仮説、12代表週84日の天候付録。
- 資料の原CSV、原本hash、AIなし再生成スクリプトとPPT-maker.md。
- 研究シナリオの引き継ぎ、運用ガイド、進捗・締切の計画と開発記録。
- 取得済みSolcast2023年9〜12月の保存原本・request・manifest。追加API取得はしない。

Office一時ロック、chart-data展開キャッシュ、SQLite WAL/SHMは.gitignoreへ追加し、実ファイルを残す。core.autocrlf=trueのWindowsでも凍結資料のhashを保つため、今回追加する資料と引き継ぎ文書には元バイト列を保持する.gitattributesを適用する。

## 整理前の保全

作業前は70ローカルブランチ、6GitHubブランチ（mainを含む）、79worktree。他の78worktreeの追跡済みファイルに変更はなかった。

復元用保存先：`C:\master-course-backups\git-sync-20261007-145457`。

- `all-refs.bundle`：全Git参照。git bundle verifyを通過。SHA-256は`2a955b4becc437cea949bdb1fe1ce0a3f48a292e49df143ddbf8f53b63a80af2`。
- `inventory.json`／`remote-heads.txt`：枝名・元SHA・worktreeの対応。
- `working-tree.patch`／`staged.patch`と`files/`／`files-manifest.json`：未コミット変更と未追跡の原本362ファイル、各hash。

ignoredの実験出力・DB・認証情報はGitへ追加しない。作業フォルダそのものを削除・移動せず、各HEADも保つ。main以外の枝をチェックアウトしているworktreeは同じSHAのdetached HEADへ切り替える。既存研究計算のコードを最新へ差し替える操作ではない。

## 別履歴の枝の扱い

mainから到達できない12ブランチを差分確認した。既に反映済み・発展済みの旧実装や診断設定を再適用せず、現在のファイルtreeを保持する履歴集約で各commitをmainから到達可能にする。これは旧ブランチの全ファイルを現行版へ採用したという意味ではない。

|旧ブランチ|元SHA|内容の扱い|
|---|---|---|
|`codex/cluster-ui-dynamic-20260924`|`396cc0e0193c6ca3ca8285d7e0fc78b94db4a455`|旧配置の開発記録を履歴保全。最新記録は保持。|
|`codex/fixed-solution-stress`|`23ca015e1fdfe1305ff8c6750e47a6be93743545`|固定計画検算と回帰は現行版に存在し、会計等は拡張済み。|
|`codex/manual-odpt-snapshot-20260924`|`e9073e7737583c64621d42ba1044618a59919a17`|手動取得・不変snapshotの実装と回帰は現行版に存在。日付来歴等は拡張済み。|
|`codex/monthly-numerical-stability-20260922`|`c5c1eff7f28dea47f545762b15b23c4334e50946`|旧診断・設定の履歴を保全。後続修正版を維持。|
|`codex/monthly-proof-budget-20260922`|`7cb468942d9ec2526d8afc92dc3fa8b7c51b56eb`|旧診断・設定の履歴を保全。後続修正版を維持。|
|`codex/monthly-rolling-budget-20260922`|`b1916e560afd7e81f3289890c53d3745daeed275`|旧診断・設定の履歴を保全。後続修正版を維持。|
|`codex/monthly-seed-diagnosis-20260922`|`c022ece753fad8121a54dc54c2b3a4de8b96b3df`|旧診断・設定の履歴を保全。後続修正版を維持。|
|`codex/monthly-session-time-20260922`|`e5ad8b3be479da98ddd1066541d7b66a1822a42d`|session-time制約・回帰は同一。後続のソルバー・運用変更を維持。|
|`codex/monthly-stage2-quality-20260922`|`4b1cbbb73f65996e7036339a7866cca6a35c9732`|旧診断・設定の履歴を保全。後続修正版を維持。|
|`codex/shibu21-23-contract-policy-20260912`|`653cde4a97fefa0a15680a3d15d7efd0c01376c9`|契約超過回帰は現行版で拡張済み。|
|`codex/shibu24-terminal-mail-20260924`|`46e1a4e8fd05760d421a004448f5fc91ca8573e6`|旧渋24段階専用CLIは復活させず履歴を保全。現行運用はweekly_terminal_observer。|
|`codex/weekly-cluster-ui-dynamic-20260925`|`fbcea598ee7c4cc4f4d109fd220681b0de0f0342`|旧配置の開発記録を履歴保全。最新記録は保持。|

## この同期で行った検証

- 新規再生成ツールの回帰：`python -m pytest tests/test_september_presentation_evidence.py -q`、10件通過。
- 新規JSON89ファイルの構文、Office20ファイルのZIP構造、Solcast4か月のraw SHAを照合。
- 公開対象313ファイルのテキスト・Office XMLに資格情報パターンの該当なし。この検査は外部の独立セキュリティ監査ではない。
- 新規327ファイルのステージと原本のbyte一致、Windowsのgit checkout-indexによる実書出し327ファイルのbyte一致を確認。
- CRLFを正しく扱うcore.whitespace設定で対象ソース・説明文書のgit diff --checkを確認。生成SVGの末尾空白、保存済み再生成スクリプトの末尾空行は元のhashを保持するため変更しない。
- GitHub ActionsはAPIでenabled=falseを確認。CI、自動AI、課金機能を有効化しない。

資料のnative表示・再生成の既存検査記録は各outcomeのREADMEに残す。今回その全検査や求解をやり直したとは扱わない。ソルバー・研究条件・既存12週の採用判定を変更せず、新規研究計算、controller/workerの再起動、実行中のコード更新は行わない。

Git同期は正式な研究採用・教員承認の判定とは別。整理の最終SHAと削除確認はローカルの`output/git_sync_20261007/`の実施記録へ保存する。

## 履歴集約とworktree保全の実施記録

資料・手順書337ファイルの同期commitは`209b20ebcd5c9c8a6c42a893a96c199a6ef1a78c`。別履歴の集約commitは`73410619ce39d250c416590f7a76cf95b16397f2`で、その前後のファイルtreeは一致した。整理前の70ローカル枝の元commitはすべてmainから到達可能になった。

枝をチェックアウトしていた他の60worktreeを元SHAのdetached HEADへ変更し、HEAD不変と追跡済みファイルの差分なしを確認した。既にdetachedだった18worktreeと現在の作業場所を含む全79フォルダを保持。現在の`C:/master-course`はmainをチェックアウトしている。

## 同期・削除の完了確認

- `ddfe6a5c7f7591a13aac719b9cbb6d5a3c4ba010`をmainへpushし、GitHubのmain SHAとの一致を確認してから削除した。
- GitHubのmain以外の5ブランチを期待SHA付きlease・atomic pushで削除。ローカルのmain以外の69ブランチは、mainからの到達を再確認して`git branch -d`で削除した。履歴を捨てる強制削除は使っていない。
- remote追跡参照をpruneし、`git for-each-ref refs/heads`と`git ls-remote --heads origin`でローカル・GitHubともmainのみを確認した。整理後のこの追記もmainへ同期する。
- 現在の作業場所はmain、他の78worktreeは元SHAのdetached HEAD。作業場所・元HEAD・研究出力を保持。実行中のコード更新や新規実験はない。

今後の基準は最新main。既存の固定計算SHAと元成果物を開発mainの実験結果へ読み替えない。旧枝のcommitはこの記録またはバックアップのinventoryで特定できる。必要になれば`git branch codex/recovered-<用途> <元SHA>`で別の枝として戻し、旧設定をmainへ丸ごと適用しない。
