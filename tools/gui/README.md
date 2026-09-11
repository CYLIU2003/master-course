# デスクトップGUIとレポート共通処理

本体の正規配置です。旧 `tools/<名前>.py` は互換入口として残しています。
リポジトリルートで `python -m tools.gui.<名前>` を実行します。
GUIはウィンドウを開き、構築・更新CLIは入力や指定出力を変更するため、目的を確認して実行してください。
`_` で始まるファイルと `tokyu_subset_config.py` は実行CLIではありません。

2026-09-10: `scenario_backup_tk` の計画日数を2日以上にすると、複製した弦巻ケースで
検証済み固定ダイヤと日付別PVをPrepareします。先読み24/48時間等、BESSの日次／期間末中立、
履歴推定PVを事前既知とする参照／2024年学習の予測代理を選べます。予測代理の実行PVは毎時の記録へ分離します。
Solcast履歴推定値を使用し、現地計器の実測値とは区別します。
この入力拡張は正式な7日運行受入ではありません。夜間帰庫・燃料・位置の連続検証は未完了で、
正式な複数日実験はコードでブロックされています。[拡張記録](../../docs/notes/SEVEN_DAY_SEASONAL_EXTENSION_20260910.md)を参照してください。
ヘルパーと入出力の回帰試験を行い、画面のウィジェット表示確認は未完了です。

- [scenario_backup_tk.py](scenario_backup_tk.py)
- [route_variant_labeler_tk.py](route_variant_labeler_tk.py)
- [bus_operation_visualizer_tk.py](bus_operation_visualizer_tk.py)
- [multi_run_visualizer_tk.py](multi_run_visualizer_tk.py)
- [_visualizer_report_utils.py](_visualizer_report_utils.py)

[全体の配置](../../docs/REPOSITORY_LAYOUT.md) · [tools案内](../README.md)
