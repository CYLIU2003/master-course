# 手動の性能計測

4本の計測・プロファイル処理の本体をこのフォルダに集約しています。
リポジトリルートから実行します。正式solver実験用の `scripts/benchmark_*.py` とは別です。

| 本体 | 処理と副作用 |
|---|---|
| [benchmark_api.py](benchmark_api.py) | プロセス内でBFFを読み込み、TestClientで計測。`docs/notes/performance_baseline.md` を上書きする |
| [benchmark_bff.py](benchmark_bff.py) | 起動済みローカルBFFへHTTP GETし、結果を標準出力へ表示 |
| [benchmark_catalog_ingest.py](benchmark_catalog_ingest.py) | カタログ取得の子プロセスを起動。外部通信、データ更新、レポート出力を伴う |
| [profile_catalog_ingest.py](profile_catalog_ingest.py) | 取り込み処理を実行しCPU・メモリを計測。データ更新を伴う。旧fast取り込みの依存欠落は [catalog案内](../../scripts/catalog/README.md) を参照 |

引数のあるカタログ計測は、実行前に次で確認できます。

```powershell
python tools/benchmarks/benchmark_catalog_ingest.py --help
```

API/BFFの2本には引数パーサーがありません。`--help` を渡しても計測が始まるので使わないでください。
今回は移動・互換性確認のみで、計測本体は実行していません。

旧 `tools/benchmark_api.py`、`tools/benchmark_bff.py`、`tools/benchmark_catalog_ingest.py`
は薄い互換入口です。旧コマンドとmodule importを維持します。本体の修正はこのフォルダで行います。
