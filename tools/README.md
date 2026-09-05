# 補助ツールの配置

| 用途 | 入口 |
|---|---|
| 研究説明・図表・発表資料 | [thesis_authoring](thesis_authoring/README.md) |
| 手動BFF実験（状態変更あり） | [manual_experiments](manual_experiments/README.md) |
| 11月の実験準備 | `november_2026/`（既存の承認条件を維持） |
| カタログ更新・プロファイル | `fast_catalog_ingest.py`、`profile_catalog_ingest.py` |
| API/BFF・カタログ計測 | [benchmarks](benchmarks/README.md)（本体を集約、旧入口は互換用） |
| GUI補助 | `*_tk.py` |
| 出力の整合性検査 | `validate_output_consistency.py` |

既存ツールの移動はimportと保存済みコマンドを壊し得るため、移動時は互換入口を維持する。
新しい補助処理は用途別フォルダへ配置し、使い捨てスクリプトをルートに追加しない。
正式実験・監査CLIは `scripts/` と区別する。
詳しくは [全体の配置と保管ルール](../docs/REPOSITORY_LAYOUT.md) を参照。
