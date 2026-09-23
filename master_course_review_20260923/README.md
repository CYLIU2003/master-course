# 厳格レビューと分離再現資料

対象はGitHub main `5d790ea16329eda22e3ceb9930548f9d33de1bb3`です。
9月22日以降のローカル版を確認したものではありません。

まず `REVIEW.md` を読んでください。

- `sources/`：GitHub blob SHAと一致する確認用ソース3件。
- `source_integrity.json`：取得コピーの照合記録。
- `reproduce_findings.py`：分離再現スクリプト。標準ライブラリのみ。
- `reproduction_results.json` / `reproduction_stdout.txt`：実行済み結果。
- `source_manifest.json`：確認対象と外部仕様への参照。

再現スクリプトはプロジェクト依存・OS応答を分離して実行します。
`os.kill`はmockで、実際のプロセスにシグナルを送りません。
実ファイルI/Oは一時ディレクトリ内だけです。
ログを再出力するため、この資料のフォルダーには書き込み権限が必要です。

実行：`python reproduce_findings.py`

「REPRODUCED」は指摘した挙動の再現成功であり、製品の正しさの合格ではありません。
Windows・SSH・Gurobi・Electron・リポジトリ全体のテストではありません。
