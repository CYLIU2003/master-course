# 翌朝SOC目標の安定化（2026-09-26）

- 固定実行版 ea72251a7ec69341ccad4e2dc698e500a8bcc7e8。目標は時間短縮より完走と正しい状態継承。
- 前版0b433705は29時間目に充電不可行。原本は `output/prefix_memory_20260926/february_campaign` とattempt06809186。最大working set13.1665GiBで、今回の停止理由はメモリではない。
- 旧Stage2は翌朝SOCにも24時間先の終端参照を使用。日別目標が122→190→204→240→282.6kWhへ変動し、直前に必要量を補給できなくなった。Stage2と可行性検査で日別目標を車両運用上限へ固定し、窓の終端目標とは分離。
- BEVだけのループ内で `vehicle_maximum_soc_kwh` を使い、検査側と同じ定義。試験車両は容量100kWh・運用上限80kWh。BESS、便、回送、初期状態、刻み、料金、機器別メモリ制限は変更なし。
- 55件回帰通過。clean ea72251aで共有broker下の実Gurobi4件通過。さらに実rolling/day_ahead_boundary_state経路1件も通過し、窓終端参照30kWhに対し翌朝80kWhを保つことを確認。この追加試験を恒久テストへ移植。これは週次完走の証明ではない。
- 独立レビュー: Claude Code claude-opus-5-5、今回の差分にP1なし。配布範囲外の全モデルや研究採用は未承認。指摘されたBEVループ・上限定義は現行ソースで照合し、rolling経路は追加実求解で確認。今後も長期間の残差、前日配車との充電可行性を実行原本で確認する。
- 新版を親機＋4従機へ配置しsource/runtime/lock/datasetを5/5照合。旧試行のプロセス終了・active job0を確認して8891コントローラーを更新。2月週は新Prepareから開始。旧版で準備した他月は新版の成果と混ぜない。
- 安定性: 32GB級Gurobi機器はtask16GiB/native hard14GiB/soft12.6GiB、OS空きRAMとcommit余裕の投入判定、共有2枠と解放待ちを継続。準備も親機の空きRAMを見て直列化し、失敗した窓をSOCリセットで飛ばさない。

## 検証原本
- `output/daily_soc_20260926/native-regression-v2/verification.json`
- `output/daily_soc_20260926/native-rolling-regression/verification.json`
- `output/daily_soc_20260926/stage-frozen/report.json`
- `output/daily_soc_20260926/claude-review/response.json`
- `output/daily_soc_20260926/operation.local.json`

レビューJSON SHA256: 77d8957d1c1b4d793c5ce2911dba537a3d821df1f52bcfc8cacf7705341f123e
