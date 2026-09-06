# 2026-09-05 ファイル整理記録

## 追加の構成簡略化（現在の配置）

- ルートの操作・教員ガイドを `docs/guides/`、デザインを `docs/frontend/`、
  過去の実装指示を `docs/archive/implementation_notes/` へ移動。
  正本への案内だけだったルートMarkdown2本を削除し、全参照を正本へ付け替えました。
  ルートの文書は計6ファイル減りました。
- docs直下18ファイルを用途別に配置し、直下は `README.md`・`REPOSITORY_LAYOUT.md`・
  本記録の3ファイルだけに整理しました。案内の正本は [docs/README](README.md) です。
- `tools/catalog/` と `scripts/fleet/` の本体4本を `scripts/catalog/` に統合。
  `tools/validation/` の1本は `scripts/validate_output_consistency.py` へ移動しました。
  空になった3フォルダはbytecodeキャッシュとともにOS一時領域へ退避しました。
- 元からの `tools/fast_catalog_ingest.py`、`scripts/extract_engine_bus.py` などの旧CLI/importは維持。
  中間配置の `tools/catalog/`・`scripts/fleet/`・`tools/validation/` は廃止しました。
  実装本体と内部参照は集約後の配置へ統一しています。
- Markdownの相対リンク・コード参照・起動処理・テストを追随させました。
  凍結資料・成果物・solver実体・既存実行データはこの追加整理で移動していません。

今回の移動は25ファイル（文書20本・Python5本）、削除は不要な案内・パッケージ定義8本です。
全体テストは **1,859 passed / 1 failed**（129.30秒）。失敗は以前からの発表資料ソースの
ハッシュ不一致だけで、新規失敗はありません。移動文書のリンク、旧入口の互換性、CLIヘルプ、
凍結weather bundleのstrict検証、差分検査を確認しました。
簡略化に関する自己レビューの未解決P0/P1は0件です。既存の研究provenance blockerは維持します。
過去の本文は移動先で保持し、古い案内はGit履歴から回収可能です。
後段は以前の配置に対する作業記録であり、現行の配置一覧ではありません。

## constantとdocsの統合

旧 `constant/` の全7ファイルを既存の `docs/constant/` に統合し、ルートのconstantはなくなりました。
移動前後のSHA-256は全件一致。Excel抽出・既定JSONテンプレート・出典表示・EXE梱包先を更新しました。
空ディレクトリの削除操作はポリシーで拒否されたため、空になった旧フォルダだけOS一時領域へ移動しています。
既存docsと研究成果は保持しました。過去の記録のパスは歴史的な参照として扱います。
関連テスト373件と差分検査が成功。実際の3社分Excel抽出もテスト用一時領域で確認しました。
EXEビルド自体は未実施です。統合に関する自己レビューでは未解決P0/P1はありません。

## 追加の欠陥監査

以下は整理後の監査結果です。後段の189 passed・3 xfailedは修正前の履歴です。

- P1 修正: 旧BFF importでカタログCLIがヘルプ表示前に落ちる。分離済みETLを遅延ロードし、欠落時は処理開始前に説明付きで停止。
- P1 修正: GTFS同期で入力ロード失敗前に空シナリオを作成し得る。依存確認・bundle取得後に作成する順序へ変更。
- P2 修正: 更新アプリが互換ファイルを独自moduleとしてロード。正規moduleへのimportに統一し、設定・monkeypatchの参照先を同一化。
- P1 部分修正: 発表資料の原本ハッシュ不一致。16ファイルはLFへ戻すだけで記録済みSHA-256に完全一致し、`.gitattributes`で固定。

未解決P1は1件です。`scripts/build_thesis_weather_result_package.py` の記録された
SHA-256 `48e7d5419f7dfb466036cace4eb78be901fa37578903aa3c9abd8c37ff9ff4b5` に一致する原本が
現ファイル・Git全refの当該ファイル履歴（LF/CRLF）・ローカルの同名コピー探索で見つかりませんでした。
manifest・期待ハッシュ・検証条件は変更していません。元の作成時ソースの回収、または別版としての
資料再生成と再検証が必要です。現在のvalidatorを過去版へ巻き戻すこともしていません。

追加回帰テスト6件と互換性テスト60件は全件成功。旧xfail3件も成功へ移行しました。
全体テストは **1,855 passed / 1 failed**（81.02秒）。失敗は上記原本ハッシュ不一致のみです。
凍結weather bundleのstrict検証・`git diff --check` はPASS。独立レビュー・release承認は未実施です。

### Code Review Summary（修正後）

Reviewer: Codex、Date: 2026-09-05、Base: `d50d3ea3`。
依存欠落時の副作用を防ぎ、互換性ケースのxfailを解消しました。
未解決はP0 0件、P1 1件（発表資料の作成時ソース）、P2 0件、P3 0件です。
次の対応は作成時原本の回収、または別版資料の再生成・検証です。現状はApproveではありません。

配置・保管方針の正本は [REPOSITORY_LAYOUT.md](REPOSITORY_LAYOUT.md) です。
本書は追加整理の変更点・検証・制限を記録します。

## 変更

- カタログ9本・車両データ2本・取り込み2本・GUIと共通処理5本・プロファイル1本・検証1本の実体を用途別に配置。
- 旧20入口をmodule aliasとして維持し、CLI終了コードも維持。内部import、ルート計算、起動処理、EXE梱包の参照を更新。
- READMEと用途別案内のリンクを追加。直接ロードするテストの参照先を新しい実体へ更新。
- スライド中間生成物4ファイル・6フォルダをリポジトリ外へ退避。削除操作は自動承認レビューに拒否されたため、復元可能な移動を使用。

退避先: `C:\Users\RTDS_admin\AppData\Local\Temp\master-course-housekeeping-7f64f6839503429eb36de9f177109d3f`。
戻す場合は同名の各項目を `output/august_brushup_20260905/` へ戻します。
OSの一時ファイル清掃が行われるまでは復元可能です。
先行整理で削除済みの `nul`・`output_multiday_test.log` の記録はDEVELOPMENT_NOTESに保持しています。

## 検証

- 関連回帰テスト: 189 passed、3 xfailed。xfailは下記の同一既存不具合に対する3ケース。
- 10 CLIの旧パス・新パス・`python -m` の計30通りで `--help` 成功。
- README・整理資料・用途別案内のリンクを検査。
- 全1,850テストの収集に成功（全件実行ではありません）。`git diff --check` PASS。
- 凍結 `weather_dispatch_rerun_bb0c005` のstrict bundle検証PASS。
- 全テスト実行・GUIの対話操作・EXEビルド・正式solver実行・外部サービス実行は未実施。

## 整理直後の自己レビュー（修正前の記録）

Reviewer: Codex（自己レビュー）、Date: 2026-09-05、Base: `d50d3ea3`。
実体を用途別に配置しつつ、旧importの同一module・CLI終了コード・研究根拠の検証経路を保全しています。
今回の整理に起因するP0/P1の未解決指摘はありません。
P2は1件、P3は0件です。

P2 / 既存の依存欠落: `fast_catalog_ingest.py` は整理前から削除済みBFFモジュールをimportし、起動できません。
詳細と影響経路は [catalog案内](../scripts/catalog/README.md) を参照してください。
取得・正規化の再実装はこの配置変更の範囲外として扱い、動作確認済みとはしません。
Claude Code・担当者による独立レビューと研究release承認は未実施です。
