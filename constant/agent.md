# agent.md - 修論用 電気バス最適化・シミュレーションツール実装指示書

## 0. この文書の役割
この文書は、Vibe Coding Agent が **修論用の電気バス運行・配車・充電スケジューリング研究環境** を理解し、
過不足なく実装を進めるための実装指示書である。

あなた(Agent)は、単にコードを書くのではなく、
**先行研究の再現実験ができ、その上で研究独自拡張ができる土台** を作る必要がある。

参照すべき中心文書は `masters_thesis_simulation_spec_v2.md` である。
この `agent.md` は、それを実装に変換するための行動規範を与える。

---

## 1. 実装ゴール
最終ゴールは、以下を満たす Python プロジェクトを構築することである。

1. 電気バスの trip / vehicle / charger / tariff / PV データを読み込める
2. 指定 mode に応じて最適化モデルを構築できる
3. Gurobi を用いて解ける
4. 生成したスケジュールを simulator で再評価できる
5. 先行研究再現ケースと thesis_case を同じ入出力形式で比較できる
6. infeasible 時の原因切り分けが可能である

---

## 2. 重要原則

### 2.1 いきなり全部実装しない
次を一度に完成させようとしてはいけない。
- vehicle scheduling
- charging scheduling
- charger placement
- battery degradation
- uncertainty
- PV
- mixed fleet

必ず **baseline -> 拡張** の順で進めること。

### 2.2 simulator を先に作る
最適化モデルより先に、簡易スケジュールを入力すると
- SOC が追跡できる
- charger occupancy が追跡できる
- cost が計算できる
- infeasible なら理由が出る
という simulator を作ること。

### 2.3 先行研究再現を意識する
このプロジェクトは「ゼロからオリジナルモデルをいきなり作る」のではない。
以下を再現可能にすることが重要である。

- journey 後充電 decision モデル
- resource assignment + charging station capacity モデル
- joint charger placement + fleet configuration モデル
- infrastructure + vehicle scheduling + charging management モデル

### 2.4 mode 切替型にする
コードの分岐を `if 論文A`, `if 論文B` と散らばらせてはいけない。
`mode` に基づいて model factory が変数・制約・目的関数を切り替える構造にすること。

---

## 3. 実装優先順位

### Stage 0: project skeleton
作成すべきディレクトリ

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
```

### Stage 1: schemas
以下の dataclass または pydantic model を作成する。

- Trip
- Vehicle
- ChargerSite
- Charger
- TariffRow
- PvRow
- DeadheadArc
- Scenario
- ExperimentConfig

必要条件:
- 型注釈を付ける
- 単位をフィールド定義コメントに書く
- 必須項目と任意項目を明確に分ける

### Stage 2: loaders
CSV / JSON を読み込み、schema インスタンスに変換する loader を作る。

必要機能:
- 欠損列の検出
- 型変換エラーの検出
- ID 重複の検出
- 時刻フォーマットの統一

### Stage 3: preprocess
以下を実装する。

1. `build_deadhead_matrix()`
2. `build_can_follow_arcs()`
3. `build_time_slots()`
4. `expand_trip_to_slots()`
5. `generate_scenarios()`

### Stage 4: simulator
最重要。

必須関数:
- `simulate_schedule(schedule, inputs, config)`
- `check_schedule_feasibility(...)`
- `compute_soc_trace(...)`
- `compute_site_power_trace(...)`
- `compute_cost_breakdown(...)`

simulator が返すべきもの:
- feasible/infeasible
- infeasible reasons
- vehicle-wise SOC trace
- charger occupancy trace
- site power trace
- cost breakdown
- KPI summary

### Stage 5: baseline optimization
最初に `mode_A_journey_charge` を実装する。

最小要件:
- vehicle assignment は固定入力
- 充電 decision のみ最適化
- objective は energy cost 最小化
- 同時充電台数制約あり
- SOC下限制約あり

### Stage 6: core optimization
次に `mode_B_resource_assignment` を実装する。

要件:
- vehicle-trip assignment
- charger capacity
- nonlinear charging の簡易近似
- deterministic solve
- scenario evaluation

### Stage 7: advanced planning
最後に以下を順次追加する。
- charger placement
- fleet composition
- battery degradation
- PV
- mixed fleet
- robust / stochastic extensions

---

## 4. 期待するコード品質

### 4.1 命名規則
- 変数名は短すぎず意味が分かる名前を使う
- `x`, `y`, `z` だけではなく、Python 側では `assign_trip`, `charge_power`, `soc` のように意味的名称を使う
- 数理モデル上の記号名との対応表を comments または docs に残す

### 4.2 拡張しやすさ
- constraint をファイル分割する
- objective も分離する
- mode の切替は factory pattern にする
- simulator と optimizer のデータ構造はできるだけ共通化する

### 4.3 デバッグ性
必ず以下をログ出力できるようにする。
- 変数数
- 制約数
- solve status
- objective value
- IIS 取得可否
- infeasible reason summary
- active constraints summary

---

## 5. Mode ごとの実装意図

### 5.1 mode_A_journey_charge
これは「最初に動かすための最小モデル」である。

目的:
- SOC と charging cost の基本処理を確認する
- TOU 料金と charger capacity の動作確認をする
- 最適化器と simulator の整合確認をする

Agent がやること:
- fixed journey sequence を持つ車両群に対して、journey 後に充電するかを最適化する
- 充電量は full charge 固定でもよいし、簡易連続変数でもよい

### 5.2 mode_B_resource_assignment
これは「修論の中心に近い基盤モデル」である。

目的:
- vehicle-trip assignment と charging scheduling を連動させる
- charger capacity と resource assignment の相互作用を出す
- 論文再現と thesis 拡張のベースラインにする

Agent がやること:
- trip network を構築する
- feasible arc を前処理で作る
- assignment + charging + SOC を同時最適化する
- solution を simulator で再評価する

### 5.3 mode_C_joint_planning
これは戦略変数を含む上位モデルである。

目的:
- charger placement
- fleet configuration
- battery degradation
を追加し、戦略計画と運用計画をつなぐ

Agent がやること:
- 設置 decision と運用 decision を別レイヤとして実装する
- 可能であれば outer-inner 構造も検討する

### 5.4 mode_D_joint_tco
これは TCO ベースの統合 planning モードである。

目的:
- infrastructure + schedule + charging management の同時最適化

Agent がやること:
- daily operating cost と annualized capex を分離する
- case study comparison をしやすくする

### 5.5 thesis_mode
これはユーザー独自研究用モードである。

目的:
- PVを保有する事業者
- 充電場所選択
- 充電スケジュール
- mixed fleet transition
- uncertainty evaluation
を組み込む

Agent がやること:
- 既存モードを無理に一体化せず、feature flags で積み上げる
- 研究で必要な比較実験を簡単に回せるようにする

---

## 6. 実装時に必ず守ること

### 6.1 Toy dataset を必ず付ける
mode ごとに最低1つ、手計算で妥当性確認しやすい toy dataset を付けること。

例:
- 車両3台
- trip 6本
- charger 2台
- depot 1箇所
- terminal 1箇所
- TOU 2区分

### 6.2 optimizer の出力だけを信用しない
最適化結果は必ず simulator に通すこと。
以下が一致するか確認する。
- SOC
- 充電時刻
- charger 占有
- site power
- total cost

### 6.3 infeasible handling を作る
解けないときに、ただ `INFEASIBLE` を返して終わってはいけない。
最低限、以下のどれが原因かを推定する。
- trip coverage impossible
- time connection impossible
- SOC shortage
- charger shortage
- site grid limit too tight
- end-of-day SOC target too strict

### 6.4 評価指標を最初から出す
少なくとも以下は毎回出力すること。
- total cost
- energy cost
- demand charge
- unmet trips
- fleet utilization
- charger utilization
- min SOC margin
- peak power

---

## 7. 推奨実装タスク分解

### Task 1
- schema 定義
- loader 定義
- validation 実装

### Task 2
- deadhead / can_follow の前処理
- time slot 展開

### Task 3
- simulator 実装
- cost evaluator 実装

### Task 4
- mode_A の MILP 実装
- toy data で動作確認

### Task 5
- mode_B の MILP 実装
- vehicle-trip assignment 追加

### Task 6
- scenario evaluator 実装
- uncertainty の後評価

### Task 7
- thesis_mode に PV, mixed fleet, demand charge を追加

---

## 8. ユーザーに返すべき成果物

Agent は最終的に以下を返せる状態にする。

1. 実行可能な Python プロジェクト
2. サンプルデータ一式
3. 実験設定 JSON 一式
4. 実行手順 README
5. mode ごとの最小再現ケース
6. 出力例(CSV/JSON/MD)
7. 結果比較テーブル

---

## 9. 実装禁止事項

- 先に巨大な monolithic script を書くこと
- schema を作らずに ad-hoc な dict を乱用すること
- optimizer と simulator で別々のロジックを持って整合が取れなくなること
- いきなり大規模実データ前提で作ること
- infeasible 時のデバッグ手段を用意しないこと

---

## 10. 最初の一歩
Agent はまず次を行うこと。

1. `schemas/` を作る
2. `loaders/` を作る
3. `simulate/` の最小 event simulator を作る
4. `data/toy/mode_A/` に最小データを置く
5. `mode_A_journey_charge` を解く
6. 結果を CSV/JSON/MD で出力する

この順を守ると、研究開発が破綻しにくい。


注意:readme.mdは必要なたびに更新すること。最初は簡単な実行手順だけでよい。わかりやすく可読性もかねて書いてください
注意:コードは常にコメントをつけること。特に数理モデルの制約や目的関数は、数式上の記号と対応させて説明すること。
注意:jsonファイルは常にconstantフォルダに格納、かつconstantフォルダ内のものは参照は可能だが、なるべく編集しないこと。もし編集が必要な場合は、constantフォルダ内のファイルをコピーして、data/inputs/などの別の場所に置いてから編集すること。