# BESS運転範囲を緩める比較（2026-09-21）

15:06 JST、clean固定 `3dcdbffd72826d82470edb21d07862f1ec0320cc`、
branch `codex/bess-range-sensitivity-20260921` からscriptを開始した。
起動時RUNNING、baseline_20_80の新規Prepare開始を確認。
入力47 SHA・親11参照・case3参照、実効条件とstderr空を照合し、固定版でも関連13 tests通過。
制御先 `output/bess_range_sensitivity_20260921/startup_verification.json`。
比較の費用・精度・物理の実規模結果は未確定。通常処理はscript、終了時のみ既存タスクへ1回通知。

ユーザーの「BESSは多少ゆるくてもよい」に対応し、20–80%に対して10–90%を比較する。
**10–90%は機器仕様が確認済みの範囲ではなく、明示した感度分析の仮定**。
追加予備・週末復元なしを保ち、エネルギー保存・効率・出力・充電器・バスSOC・帰庫・全便を守る。
成果の判断は先生への説明に使える費用と運行の証拠で行い、条件緩和をソルバーの性能向上と混同しない。

## なぜ配車まで比較するのか

直前6aab4424の費用訂正後総額4,149,820.012223円のうち、車両使用費4,120,000円が99.2814%。
既存固定配車の充電目的値は既に0円、Stage2 gap0%。電力費−8.38e−9円は数値残差。
非負の充電費用を使う同じ配車では、BESS範囲を広げても0円よりさらに下げる余地はない。
ただし、BESSの自由度が増えて別の配車が成立する効果はこの議論では否定できない。
そこで配車から作り直し、車両日数・燃料と総費用を確認する。
根拠は `output/bess_range_sensitivity_20260921/motivation.json`。

## 共通条件と変更する条件

| 条件 | baseline_20_80 | expanded_10_90 |
|---|---:|---:|
| BESS容量 / 出力 | 6000kWh / 900kW | 同じ |
| 初期残量 | 3000kWh | 同じ |
| 使用範囲 | 1200～4800kWh | 600～5400kWh |
| 充放電効率 | 各0.95 | 同じ |
| 追加予備 / 終端復元 | なし / なし | 同じ |
| 充電可能な系統→BESS | 禁止 | 同じ |
| 配車/充電予算 | 1800秒 / 120秒 | 同じ |
| threads / softメモリ | 4 / 18GB | 同じ |

両条件ともCO₂訂正を含む新しい同一clean固定版から新規Prepareする。
5月12日開始の7日分予測による前日計画だけ。168時間実績・月別12週は開始しない。
Method2/NodeMethod2/Crossover0/NoRel0、端点表現、seed42、gap1%、完全後続網、
同日路線固定・毎日帰庫、fleet、料金、PV、初期車両SOCは共通。
主wall2400秒、実際に入力したseedの固定Stage2は120秒/別wall180秒。
条件を1つずつ逐次実行し、最初の失敗で停止。自動再試行・メール・AIによる通常監視なし。
終了時だけ既存タスクへ1回通知する。

比較では原本hashと実効条件、両案の独立物理、BESS各672区間、seed配車の保存前後一致、
Stage2 gap、停止理由、メモリ、総費用、車両日数、燃料、買電、PV利用/抑制を照合する。
初期在庫取り崩しが最大600kWh増える条件なので、初期/最終kWhを必ず併記する。
非改善・メモリ停止も結果として残す。1%未達を最適とせず、旧12週や修正前CO₂費と混ぜない。

## 実装と検証

到達経路: paired runner → planning diagnosis → run_campaign → 新規Prepare →
`seasonal_bess_range` / `apply_seasonal_bess_policy` → Prepared contract → solve_week →
ProblemBuilder → Phase3 / CostEvaluator → canonical / independent physical。

既定20–80%の動作を保ち、`expanded_10_90` は
`bess_operating_range_basis=unverified_hardware_sensitivity` の宣言を必須にした。
0–100%等の未定義profileや、範囲と終端下限の不一致を拒否する。
kWh・ratio・percentの表現を揃え、事前検査の20/80固定値も宣言範囲へ揃えた。
旧固定版や稼働するsolver codeを変更しない。

関連122 tests通過。親設備不変、600/5400kWhへの反映、range誤差の事前拒否、
legacy20–80互換、実行禁止設定での無副作用、ペア逐次実行/失敗停止、既存BESS/seed診断を確認。
人工2日間の同配車では追加10kWh在庫×放電効率0.95×買電単価10円に相当する95円減を確認し、
native Stage2 gap0%・独立物理も通過した。人工例の95円を5月の削減見込みとして扱わない。

Code Review Summary: Codex自己レビューの新規未修正P0/P1なし。
独立研究レビューはPENDING。実規模での費用改善・週間統合最適性・実機範囲の妥当性は未確認。
設定: `config/shibu21_23_bess_range_sensitivity_20260921.json`。
