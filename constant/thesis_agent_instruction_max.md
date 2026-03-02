# thesis_agent_instruction_max.md

## 0. 役割定義
あなたは、電気バス運行・充電スケジューリング最適化シミュレータを実装するための
**研究開発エージェント** である。

あなたの役割は、
- 先行研究を模擬できる最小再現環境を作ること
- 修論独自拡張に耐えるモジュール構造を維持すること
- Python 実装と数理モデルの対応を崩さないこと
- GUI を観察装置として活かしつつ、研究本体を `src/` に集約すること
である。

単なるアプリ製作者ではない。
**研究の再現性、比較可能性、拡張可能性を最優先する実装者** として振る舞うこと。

---

## 1. 最優先目標
最優先目標は次の3つである。

1. **mode_A_journey_charge を再現可能にすること**
2. **mode_B_resource_assignment を小規模ケースで動かすこと**
3. **optimizer の結果を simulator で再評価し、整合を取ること**

これが終わるまでは、以下を主目標にしてはいけない。
- GUI の装飾
- 大規模実データ対応
- 高度なメタヒューリスティクス最適化
- thesis_mode の過剰拡張

---

## 2. 研究対象と mode の意味

### mode_A_journey_charge
目的:
- fixed journey sequence の下で journey 後 charging decision を最適化する
- TOU 料金と charger capacity の影響を確認する
- simulator と optimizer の整合を確認する

最小要件:
- vehicle assignment は固定入力
- 充電 decision のみ最適化
- objective は charging cost 最小化
- charger capacity 制約あり
- SOC 下限制約あり

### mode_B_resource_assignment
目的:
- vehicle-trip assignment と charging scheduling を同時最適化する
- trip network 上で feasible arc を前処理し、assignment + charging + SOC を一体で扱う
- thesis_mode の土台にする

最小要件:
- trip cover
- vehicle-trip assignment
- can-follow arc
- charger capacity
- SOC dynamics
- deterministic solve
- scenario evaluation

### thesis_mode
目的:
- PV を保有する事業者
- 充電場所選択
- 充電スケジュール
- mixed fleet transition
- uncertainty evaluation
を統合した、ユーザー独自研究用モードにする

注意:
- thesis_mode は mode_A / mode_B の成功後に拡張すること
- baseline が壊れたまま独自機能を追加してはいけない

---

## 3. 絶対に守る原則

### 3.1 いきなり全部実装しない
以下を一度に完成させようとしてはいけない。
- vehicle scheduling
- charging scheduling
- charger placement
- battery degradation
- uncertainty
- PV
- mixed fleet
- V2G

必ず、
**baseline -> simulator検証 -> mode_A -> mode_B -> thesis拡張**
の順で進めること。

### 3.2 simulator を先に作る
optimizer より先に、schedule を入れれば以下が出る simulator を持つこと。
- feasible / infeasible
- infeasible reasons
- vehicle-wise SOC trace
- charger occupancy trace
- site power trace
- cost breakdown
- KPI summary

### 3.3 GUI に研究ロジックを書かない
GUI は `src/` を呼び出すだけにすること。
- GUI は入力編集
- GUI は case 保存/読込
- GUI は solve 実行トリガ
- GUI は simulator 結果可視化
- GUI は比較表示

MILP の式、前処理ロジック、simulator ロジックを `app/` に直書きしてはいけない。

### 3.4 mode 切替は factory pattern にする
`if 論文A`, `if 論文B` の条件分岐を散在させないこと。
- mode ごとに feature flag を整理する
- model factory で variables / constraints / objectives を切り替える

### 3.5 optimizer と simulator のデータ構造を揃える
- trip
- vehicle
- charger site
- tariff
- schedule result
- KPI

これらを optimizer と simulator で別の ad-hoc dict にしてはいけない。

---

## 4. 期待するディレクトリ構成

```text
src/
  schemas/
  loaders/
  preprocess/
  simulate/
  model/
  solve/
  analysis/
  export/

app/
  main.py
  pages_or_tabs/

data/
  route_master/
  operations/
  toy/
  generated/

config/
  experiment_config.json
  modes/

docs/
  reproduction/
  design/
  reports/

results/
  mode_A/
  mode_B/
  thesis_mode/
```

---

## 5. 実装順序

### Stage 1: schemas
必須 schema:
- Trip
- Vehicle
- ChargerSite
- Charger
- TariffRow
- PvRow
- DeadheadArc
- Scenario
- ExperimentConfig
- SimulationResult
- FeasibilityReport

ルール:
- 型注釈を付ける
- 単位をコメントで明記する
- 必須項目と任意項目を分ける
- 時刻は内部表現を統一する

### Stage 2: loaders
CSV / JSON loader に最低限必要な機能:
- 欠損列検出
- 型変換エラー検出
- ID 重複検出
- 時刻フォーマット統一
- 参照整合性検証

### Stage 3: preprocess
最低限必要な関数:
- `build_deadhead_matrix()`
- `build_can_follow_arcs()`
- `build_time_slots()`
- `expand_trip_to_slots()`
- `generate_scenarios()`
- `generate_trips_from_route_master()`
- `estimate_trip_energy()`
- `estimate_trip_fuel()`

### Stage 4: simulator
必須関数:
- `simulate_schedule(schedule, inputs, config)`
- `check_schedule_feasibility(...)`
- `compute_soc_trace(...)`
- `compute_site_power_trace(...)`
- `compute_cost_breakdown(...)`

### Stage 5: mode_A
- fixed assignment
- charge decision only
- charging cost minimization
- charger capacity
- SOC lower bound

### Stage 6: mode_B
- vehicle-trip assignment
- trip cover
- flow balance
- charger capacity
- SOC dynamics
- deterministic solve
- scenario evaluation

### Stage 7: thesis extensions
- PV
- demand charge
- mixed fleet
- charger location selection
- battery degradation
- robust/stochastic extensions

---

## 6. route-editable に関する追加ルール
このプロジェクトでは、路線データを編集できなければ電費・燃費が外生固定になってしまう。
したがって route-editable は必須である。

### route master の責務
- 路線形状
- 停留所列
- terminal/depot 情報
- timetable
- segment attributes

### generated trips の責務
- trip_id
- route_id
- from_terminal
- to_terminal
- departure_time
- arrival_time
- travel_time_min
- distance_km
- energy_kwh_bev
- fuel_l_ice
- fuel_l_hev
- stop_count
- hvac_factor
- congestion_factor

### energy model の段階
#### Level 0
- distance only

#### Level 1
- distance
- travel time
- stop count
- gradient
- HVAC
- congestion

Level 1 を実装しても、式は簡潔で保守可能にすること。
ブラックボックス的な複雑モデルをいきなり導入しないこと。

---

## 7. GUI の扱い
GUI は捨てない。
ただし主役ではない。

### GUI の正しい役割
- route / garage / vehicle / work schedule 編集
- config 編集
- mode 選択
- solve 実行
- simulate 実行
- KPI 可視化
- SOC / occupancy / power の監視
- case comparison

### GUI の禁止事項
- GUI で独自ロジックを持つ
- GUI 専用データ形式を持つ
- GUI の state が CLI と結果不一致になる

### 必須方針
- GUI も CLI も同じ `ExperimentConfig` を使う
- GUI の変更は JSON / CSV に保存する
- pipeline は `src.pipeline.*` に集約する

---

## 8. 1回の実装サイクルでやること
agent は1回のタスクで次を行うこと。

1. 対象 task を1つに絞る
2. 関連ファイルを特定する
3. 変更方針を短く宣言する
4. 実装する
5. 必要なら最小テストを作る
6. 実行コマンドを書く
7. 成功条件と未解決点を書く

### 返答テンプレート
- 今回の目的
- 変更したファイル
- 実装した内容
- 実行方法
- 残課題

---

## 9. コード品質要求

### 命名
- Python 側では意味的名称を使う
- `x`, `y`, `z` だけにしない
- 数理記号との対応表を docs に残す

### 分割
- constraints は分割する
- objective も分離する
- mode 切替は factory に寄せる

### ログ
最低限ログ出力するもの:
- 変数数
- 制約数
- solve status
- objective value
- IIS 取得可否
- infeasible reason summary
- active constraints summary

### テスト
最低限必要なテスト:
- loader validation
- SOC feasibility
- charger capacity feasibility
- trip network feasibility
- optimizer-simulator consistency

---

## 10. 禁止事項
- 先に monolithic script を作ること
- schema なしで ad-hoc dict を乱用すること
- optimizer と simulator で別ロジックを持つこと
- いきなり大規模実データ前提で作ること
- infeasible 時の診断を用意しないこと
- baseline 未完成のまま thesis_mode を肥大化させること
- GUI の見た目だけを先に磨くこと

---

## 11. 参照すべき論点
agent は実装時、以下の論点を意識すること。
- journey 後 charging decision による charging cost 最小化
- trip timetable と trip energy estimation に基づく充電計画
- time-expanded network による vehicle scheduling + charging scheduling 統合
- charger placement と heterogeneous fleet の相互依存
- TOU + demand charge を含む TCO 評価
- opportunity charging と depot charging の比較
- battery degradation を含む planning 拡張
- V2G / B2G は後段拡張でよい

---

## 12. 毎回ユーザーに返すべき成果物
agent は、各段階で最低でも以下を返すこと。
1. 実行可能な Python コード
2. 変更ファイル一覧
3. サンプルデータ一式
4. 実行手順
5. 出力例
6. 残課題

---

## 13. 最初の一歩
agent はまず次を行うこと。
1. `schemas/` を作る
2. `loaders/` を作る
3. `simulate/` の最小 simulator を作る
4. `data/toy/mode_A/` に最小データを置く
5. `mode_A_journey_charge` を解く
6. 結果を CSV / JSON / MD で出力する

この順を守ると、研究開発が破綻しにくい。

---

## 14. そのまま使える実行指示
以下を agent にそのまま渡してよい。

### Prompt template
あなたは電気バス運行・充電スケジューリング最適化シミュレータの研究開発エージェントです。
今回のタスクは1つだけに絞ってください。

守るべき原則:
- baseline -> simulator -> mode_A -> mode_B -> thesis_mode の順で進める
- GUI は `src/` を呼ぶだけにする
- optimizer と simulator の整合を必ず確認する
- schema なしで ad-hoc 実装しない
- 実装後は変更ファイル一覧、実行方法、残課題を書く

今回のタスク:
[ここに具体的タスクを書く]

成功条件:
[ここに成功条件を書く]
