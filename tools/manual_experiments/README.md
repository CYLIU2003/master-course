# 手動実験（通常のテストではありません）

[複数日BFF実験](test_multiday_phase1.py) は既存の手動スモークスクリプトです。
ローカルBFFにシナリオを作成し、最適化ジョブを開始します。
ファイル整理では実行していません。正式研究実験の承認や検証を代替しません。

実験の実行を明示的に決めた場合のみ、リポジトリルートから実行します。

```powershell
python tools/manual_experiments/test_multiday_phase1.py
```

旧 `python test_multiday_phase1.py` は互換入口として残しています。
両方とも `__test__ = False` とし、pytestによる自動実行を防いでいます。
依存ライブラリは `requests`、接続先はスクリプト内の `BASE_URL` です。
