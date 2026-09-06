# デスクトップGUIとレポート共通処理

本体の正規配置です。旧 `tools/<名前>.py` は互換入口として残しています。
リポジトリルートで `python -m tools.gui.<名前>` を実行します。
GUIはウィンドウを開き、構築・更新CLIは入力や指定出力を変更するため、目的を確認して実行してください。
`_` で始まるファイルと `tokyu_subset_config.py` は実行CLIではありません。

- [scenario_backup_tk.py](scenario_backup_tk.py)
- [route_variant_labeler_tk.py](route_variant_labeler_tk.py)
- [bus_operation_visualizer_tk.py](bus_operation_visualizer_tk.py)
- [multi_run_visualizer_tk.py](multi_run_visualizer_tk.py)
- [_visualizer_report_utils.py](_visualizer_report_utils.py)

[全体の配置](../../docs/REPOSITORY_LAYOUT.md) · [tools案内](../README.md)
