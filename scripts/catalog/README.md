# カタログ・車両データの整備

本体の正規配置です。旧 `scripts/<名前>.py` は互換入口として残しています。
リポジトリルートで `python -m scripts.catalog.<名前>` を実行します。
構築・更新CLIは入力や指定出力を変更するため、目的を確認して実行してください。
`_` で始まるファイルと `tokyu_subset_config.py` は実行CLIではありません。

- [build_tokyu_bus_data.py](build_tokyu_bus_data.py)
- [build_tokyu_full_db.py](build_tokyu_full_db.py)
- [build_tokyu_gtfs_db.py](build_tokyu_gtfs_db.py)
- [build_tokyu_subset_db.py](build_tokyu_subset_db.py)
- [export_tokyu_sqlite_to_built.py](export_tokyu_sqlite_to_built.py)
- [rebuild_built_from_normalized.py](rebuild_built_from_normalized.py)
- [_odpt_runtime.py](_odpt_runtime.py)
- [_stop_timetable_fallback.py](_stop_timetable_fallback.py)
- [tokyu_subset_config.py](tokyu_subset_config.py)
- [extract_engine_bus.py](extract_engine_bus.py): JH25車両データの抽出
- [query_engine_bus.py](query_engine_bus.py): 車両データの検索
- [fast_catalog_ingest.py](fast_catalog_ingest.py): カタログ取り込み
- [update_tokyu_depots.py](update_tokyu_depots.py): 営業所データ更新

旧 `scripts/extract_engine_bus.py`、`scripts/query_engine_bus.py`、
`tools/fast_catalog_ingest.py`、`tools/update_tokyu_depots.py` は互換入口です。
本体の変更はこのフォルダで行います。中間配置だった `scripts/fleet/` と `tools/catalog/` は統合済みです。

## 任意の取り込み依存

fast取り込みのimportとヘルプはcore構成でも使用できます。
実際の取得・正規化・同期には別途 `data-prep/lib/catalog_builder` が必要です。
欠落時は具体的な依存エラーを表示し、出力フォルダ・新規シナリオの作成前に停止します。
GTFS同期では入力bundleの読み込みも新規シナリオ作成より前に行います。

[全体の配置](../../docs/REPOSITORY_LAYOUT.md) · [scripts案内](../README.md)
