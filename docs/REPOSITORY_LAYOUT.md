# ファイル配置と保管ルール

全体の入口は [文書案内](README.md)、実行方法は [ルートREADME](../README.md) です。

## 正規配置

| 用途 | 場所 |
|---|---|
| アプリ起動 | `run_app.py` |
| 最適化モデル | `src/` |
| UI・API | `tools/gui/`、`bff/` |
| カタログ・車両データ整備 | [scripts/catalog](../scripts/catalog/README.md) |
| 天候データ整備 | [scripts/weather](../scripts/weather/README.md) |
| 実験・監査CLI | [scripts](../scripts/README.md) |
| 性能計測・資料作成などの補助 | [tools](../tools/README.md) |
| 回帰テスト | `tests/` |
| 利用・開発ガイド | [運用](guides/operations.md)、[教員レビュー](guides/professor_review.md)など `docs/guides/` |
| 画面設計 | [frontend](frontend/README.md) |
| 監査・レビュー記録 | `docs/reviews/` |
| 進行記録・正式手順 | [blocker](notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md)、[runbook](notes/FORMAL_RUNBOOK_CURRENT.md)など `docs/notes/` |
| 原資料・仕様・テンプレート | [constant](constant/README.md) |
| 過去の実装メモ | [archive](archive/implementation_notes/README.md) |
| 再現条件 | [reproduction](reproduction/reproduction_spec.md) |
| 凍結根拠・修論執筆資料 | `docs/evidence/`、`docs/thesis/` |
| 発表・提出物 | [outcome](../outcome/README.md) |

## 配置を増やさないためのルール

新しいファイルは上表の既存の置き場を優先します。
1〜2本のためだけに別フォルダを作らず、同じ用途は一か所へまとめます。
文書は `docs/`、日付付きの提出物は `outcome/` へ置き、ルートへ追加しません。
ルートのREADMEと、この文書・文書案内を入口として維持します。

元から公開されているPython/CLIの旧入口は互換性のため残しています。
修正するのは用途別フォルダの実体です。今回の中間配置だった `tools/catalog/`、
`scripts/fleet/`、`tools/validation/` は統合済みで、今後は使いません。
古いMarkdownの移動案内だけのファイルは削除し、リンクを正本へ付け替えています。

## 実行データと凍結成果

`output/` は現行の生成先です。`outputs/`、`results/`、`scenarios/`、
`data/`、`tmp/`、`先行文献/` の既存内容は名前だけで削除・移動しません。
保存済みの実行結果や凍結manifestにはパス・ハッシュの契約があります。
原データの移動には個別の参照確認が必要です。正式実験CLIの固定パスも維持します。

移動履歴・退避先・検証結果・未解決事項は [整理記録](FILE_ORGANIZATION.md) を参照してください。
