# 渋24ダミー分散試験（2026-09-23）

旧渋21〜23の長時間2週計算は利用者指示で停止し、元の出力を保持した。正式週実験は再開していない。新たに実行したのは、路線IDだけ渋24とした架空4便・各1日・1 BEVと予備ICEの疎通試験である。公式渋24時刻表、実車両、PV/BESS効果、連続週を再現しない。

## 判定

| 項目 | 実測 | 判定範囲 |
|---|---:|---|
| 当初登録PC | 親機+従機11台 | 12台 |
| 同一固定版のコード・runtime・dataset照合 | 12/12台 | 元の12台 |
| 独立ジョブ終了・ZIP回収hash | 12/12件 | 元の12台 |
| 4便充足・独立物理検査・BEV終端一致 | 12/12件 | 架空1日 |
| BEV初期→終端 | 各160→160 kWh | BFF実効`return_to_initial` |
| Gurobi Env/Model/optimize | 各0回 | `alns_no_gurobi_v1` |
| 研究採用・統合最適性 | 0件 | BLOCKED |

固定実行SHAは `2e2333b3d27aa49f62a16e5387a1df39897ce26f`、source digestは `02737f513d0354c63c6a21151200813877d41f7389ebec06d6f2a0a0ba3de823`。全件の`physical_validation_status=VALID`、未充足便0、`bev_terminal_soc_balance_source=independent_feasibility_checker`を回収ZIPから照合した。初回の11件の非公開原本は `output/cluster-deployment/shibu24-dummy-fixed-2e2333b3-run11/`、復帰した1台の原本は `shibu24-dummy-fixed-2e2333b3-a709-run/`。それぞれの`audit11.json`と`a709-audit.json`で回収hashを検証し、`shibu24-dummy-fixed-2e2333b3-physical-audit12.json`で同じSHA/source digestの12件を横断検査した。回収ZIPと入力manifestを削除・再ラベルしない。

初回固定版 `a594b6f6` は11台への配布・回収だけは通過したが、計画受理は0/11件だった。BFFがBEV終端を比較用の`return_to_initial`へ強制する一方、ALNSにはMILP専用の終端SOC metadataがなく、物理再計算で160 kWhへ戻っても最終結果は`terminal_soc_balance_failed`となった。初回ZIPは `shibu24-dummy-a594b6f6-run11/` に保持。修正版では、ヒューリスティック側の明示flagがない場合だけ、独立FeasibilityCheckerの全体可行判定を引き継ぐ。明示失敗は上書きしない。入力のBEV境界を緩めて見かけ上通した結果ではない。

当初オフラインだった `laptop-a709una0` は復帰後、同じSHAの配置照合、固有の`month-12`、ZIP hash、物理検査まで通過し、元の12台は12/12となった。先行11件のbatchを変更せず、12件目を別batchで投入した。正式週の研究結果へは転用しない。

追加登録した4台は、利用者指定のTailscale IPv4とnode ID・SSH host keyを保存し、**監視のみ・投入無効・本人確認未完了**として元の12台と区別する。`POWERSYSTEM`と同名の新node `100.107.38.117` は、旧登録 `100.88.215.76` とnode ID・host keyが異なり、別worker ID `powersystem-1` とした。4台ともTailscale online、SSHポート到達、公開鍵認証は`Permission denied`。既存の`cluster-worker-access-setup-v3.zip`を4台へTailscale file cpで送信済み。ただしZIP内の`workers.json`は旧11台用なので、そのままでは新3台が登録名検査に通らない。4台用`workers.add4.json`と`README-ADD4.txt`を別送し、展開後の置換を案内した。配布CLIの成功は受信側の実行を証明しない。受信側のセットアップ後にSSHログイン名・端末名・Tailnet IP・固定版runtime/datasetを再検査し、初めて短い固有ジョブを投入する。元12台の12/12を新4台まで含む16/16とは呼ばない。

親機のloopback監視画面は `http://127.0.0.1:8868/#cluster`。`MasterCourseClusterMonitor` のログオンタスクを登録し、現時点で起動・HTTP応答・同じ設定での二重起動回避を確認した。ログオン後の実際の再起動試験は未実施。画面はworkerを4秒、jobを3秒ごとに更新し、AI監視やメール送信は行わない。
