# 研究実行ツールの入口

日常操作は [AIなし運用ガイド](../../docs/guides/weekly_operations.md) から始めます。
日付付き診断スクリプトを新しい本番入口と取り違えないでください。

別agent・研究者への詳しい引き継ぎは[研究シナリオガイド](../../docs/guides/research_scenario/README.md)と[開始メッセージ](../../docs/guides/research_scenario/AGENT_START_PROMPT.md)を使います。今回の入力・パラメータ・12代表週、操作対象の選択、結果の検算と集計、通信・メモリ・描画失敗の切り分けを記載しています。開発版と計算固定版を分け、資料を読んだだけで新規計算を開始しないでください。

|用途|既存の実行入口|
|---|---|
|操作フォルダ生成|`install_operator_kit.py`（既存operationを指定、新規ジョブなし）|
|起動・状態・再開・回収|`weekly_operations.ps1` → `weekly_operator.py`|
|週次キャンペーン|`weekly_campaign.py`（凍結releaseから起動、通常は操作入口経由）|
|フロントの詳細進捗|`publish_execution_detail.py`（読取と配信）|
|週次回収・検算|`weekly_collection.py`（operatorから使用）|
|月別費用比較|`monthly_campaign_report.py`（検算済み原本から集計）|
|既存計算の図表修復|`rebuild_literature_figures.py`（別出力、元の失敗判定は保持）|
|図表失敗した週の再検算・集計|`recover_weekly_reporting.py`（原ZIP照合、別出力。求解なし）|

引数は各Pythonの`--help`で確認します。最適化の物理条件・出典検査・同時枠を迂回する入口ではありません。
この整理では呼出先を維持し、稼働中スクリプトや日付付き証拠は移動していません。
