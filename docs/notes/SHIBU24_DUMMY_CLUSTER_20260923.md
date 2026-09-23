# 渋24ダミー分散試験（2026-09-23）

旧渋21〜23の長時間2週計算は利用者指示で停止し、元の出力を保持した。正式週実験は再開していない。新たに実行したのは、路線IDだけ渋24とした架空4便・各1日・1 BEVと予備ICEの疎通試験である。公式渋24時刻表、実車両、PV/BESS効果、連続週を再現しない。

## 判定

| 項目 | 実測 | 判定範囲 |
|---|---:|---|
| 登録PC | 親機+従機11台 | 12台 |
| 同一固定版のコード・runtime・dataset照合 | 親機+従機10台 | 11/12台 |
| 独立ジョブ終了・ZIP回収hash | 11/11件 | オンライン11台 |
| 4便充足・独立物理検査・BEV終端一致 | 11/11件 | 架空1日 |
| BEV初期→終端 | 各160→160 kWh | BFF実効`return_to_initial` |
| Gurobi Env/Model/optimize | 各0回 | `alns_no_gurobi_v1` |
| 研究採用・統合最適性 | 0件 | BLOCKED |

固定実行SHAは `2e2333b3d27aa49f62a16e5387a1df39897ce26f`、source digestは `02737f513d0354c63c6a21151200813877d41f7389ebec06d6f2a0a0ba3de823`。全件の`physical_validation_status=VALID`、未充足便0、`bev_terminal_soc_balance_source=independent_feasibility_checker`を回収ZIPから照合した。原本は非公開の `output/cluster-deployment/shibu24-dummy-fixed-2e2333b3-run11/`、受領監査は `shibu24-dummy-fixed-2e2333b3-audit11.json`、独立した横断検査は `shibu24-dummy-fixed-2e2333b3-physical-audit11.json`。回収ZIPと入力manifestを削除・再ラベルしない。

初回固定版 `a594b6f6` は11台への配布・回収だけは通過したが、計画受理は0/11件だった。BFFがBEV終端を比較用の`return_to_initial`へ強制する一方、ALNSにはMILP専用の終端SOC metadataがなく、物理再計算で160 kWhへ戻っても最終結果は`terminal_soc_balance_failed`となった。初回ZIPは `shibu24-dummy-a594b6f6-run11/` に保持。修正版では、ヒューリスティック側の明示flagがない場合だけ、独立FeasibilityCheckerの全体可行判定を引き継ぐ。明示失敗は上書きしない。入力のBEV境界を緩めて見かけ上通した結果ではない。

残る `laptop-a709una0` はTailscale/SSHがオフラインで、固定版配置・実計算をしていない。現行private設定では投入無効のまま表示する。起動・通信復帰後に同じSHAの配置照合、1件の固有ジョブ、ZIP/物理監査を通すまで12/12とはしない。現時点の11/12の成功を教員向けの研究結果へ転用しない。

親機のloopback監視画面は `http://127.0.0.1:8868/#cluster`。`MasterCourseClusterMonitor` のログオンタスクを登録し、現時点で起動・HTTP応答・同じ設定での二重起動回避を確認した。ログオン後の実際の再起動試験は未実施。画面はworkerを4秒、jobを3秒ごとに更新し、AI監視やメール送信は行わない。
