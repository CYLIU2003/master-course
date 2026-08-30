# システム全体像

## 非専門向け要約

本システムは、時刻表、車両、充電器、PV、BESS、料金を入力し、まず各便を担当する車両を決め、次にその担当を変えずに充電と営業所内電力の流れを決める。得られた日次計画を1時間ごとに見直し、実行した最初の1時間だけを状態として次時刻へ渡す。最後に、運行、SOC、充電器、電力、費用、入力由来を別々に検査する。

## 1. システム全体構成

```mermaid
flowchart LR
  A[時刻表・距離・operator] --> S[Scenario]
  V[車両・初期SOC・燃料] --> S
  E[充電器・PV・BESS・料金] --> S
  S --> P[Fresh Prepare]
  P --> O[Phase 3二段階計算]
  O --> R[24時間Rolling]
  R --> G[物理・会計・provenance検算]
  G --> F[正本artifact]
  F --> T[修論用表・図・主張]
```

## 2. データフロー

```mermaid
flowchart TD
  I1[timetable_rows] --> H1[trip hash]
  I2[active fleet] --> H2[fleet contract hash]
  I3[charger/BESS/tariff] --> H3[equipment hash]
  I4[PV curve] --> H4[PV hash]
  H1 --> C[Prepared input]
  H2 --> C
  H3 --> C
  H4 --> C
  C --> D[day-ahead result]
  D --> X[24 Rolling step results]
  X --> L[executed_day_accounting]
  L --> Q[result_summary / thesis tables]
```

SUNNYとRAINではtimetable、vehicle、fleet contract、tariff、objective、solver controlを固定し、PV hashだけを分離している。RAINの日付を日曜ダイヤへ置換していない。

## 3. Phase 3二段階計算

```mermaid
flowchart TD
  A[Stage 1: 便・車両割当と近似エネルギーrecourse] --> B[有限候補生成]
  B --> C{候補ごとにStage 2 feasible?}
  C -- no --> D[候補棄却・診断]
  C -- yes --> E[固定配車で充電・PV・BESS・系統を最適化]
  E --> F[canonical costと物理配車hash]
  F --> G[評価済み候補内で決定論的選択]
```

Stage 2はStage 1へ一般的な最適化情報を返して全体を反復する統合手法ではない。評価済み候補の中からcanonical cost、使用車両数、物理割当hashの順で決定論的に選択する。

## 4. day-aheadとRolling

```mermaid
sequenceDiagram
  participant D as day-ahead
  participant R as Rolling solver
  participant S as state
  D->>R: 固定した車両・便割当
  loop 24回
    S->>R: 現在SOC・BESS SOC・既発生peak
    R->>R: 残余時刻の充電を再最適化
    R->>S: 最初の60分だけ実行
  end
  S->>S: 96スロットを一度だけ再会計
```

各stepの目的値は残余時間の値であり、24個を加算しない。`executed_day_accounting.json`は24個の実行prefixを15分×96スロットへ重複なくつなぎ、1回だけ費用を再計算した正本である。

## 5. artifactと主張

```mermaid
flowchart LR
  A[result_summary.json] --> C1[配車・gap・実験scope]
  B[executed_day_accounting.json] --> C2[Rolling評価額・費用・日合計]
  P[physical_schedule_validation.json] --> C3[物理実行可能性]
  R[rolling_chain_summary.json] --> C4[24/24と状態連鎖]
  M[cross_weather matrix] --> C5[22候補内の順位・費用]
  S[scenario snapshots] --> C6[設備・料金・入力由来]
  C1 --> T[修論主張]
  C2 --> T
  C3 --> T
  C4 --> T
  C5 --> T
  C6 --> T
```

## 実行経路

`Fresh Prepare -> public BFF run-optimization -> phase3_two_stage -> 24-step Rolling -> physical/accounting finalization`である。主要実装は`bff/routers/optimization.py`、`bff/services/optimization_run/execute.py`、`src/optimization/milp/solver_adapter.py`、`scripts/run_hourly_charging_reoptimization.py`、`bff/services/optimization_run/rolling_chain.py`に分かれる。
