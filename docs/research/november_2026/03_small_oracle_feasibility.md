# 小規模統合oracleの実行可能性

## 判定

`ADAPTER_READY_NO_EXECUTION / P3_SCALAR_UNSUPPORTED`

core modelは変更していない。`scripts/audit_small_integrated_weather_milp.py` は以下を実装する。

- Prepared inputと現行scenarioをmaterializeし、calendar counterfactual contractをfail-closedで復元する。
- `milp_max_successors_per_trip=0`、15分刻み、同一のcanonical problemを作る。
- departure順の先頭・末尾を含む等間隔のday-spanning subsetを、8/12/24の任意の `--trip-count` で生成する。
- 各powertrainからcanonical ID順に最大5台を選び、選定規則をmetadataへ残す。
- deployed Phase 3と、scalar canonical actual costを直接最小化するPhase 4を同じ入力で解く。
- Phase 4のOPTIMAL、zero gap、actual-cost contract、会計一致、energy inventory、validationをfail-closedで検査する。

既存test `tests/test_small_integrated_weather_audit.py` はsubset両端、fleet選択、exact gate、actual-cost contract、zero-cost時の相対gap非識別を検証している。過去のclean SHA `93e31b0` でも8/12/24/40便がbounded verificationを通っているが、その結果を新しいexecution SHAの結果へ再ラベルしない。

## objective比較の限界

Phase 3に`objective_preset=None`を与えてもStage 1/Stage 2の数式はscalar canonical actual costへ統合されない。`integrated_actual_cost_objective`はengineで`phase4_integrated`に限定され、Phase 3 candidateも`objective_is_actual_cost=False`を明示する。metadataだけで整合できないためP3-SCALARは実装していない。pure decomposition gap is unavailable。

## 追加済みoutput adapter

- raw `cost_breakdown`全項目、canonical component sum、total、残差、1e-6円gate
- 使用BEVの全保存solver slotと初期slotからのminimum SOC、reserve margin、vehicle/slot/time
- formulation ID、objective semantics、incumbent/bound/gap/runtime、exact oracle gate
- absolute/relative cost difference、配車一致、powertrain配車一致、費用項目差
- `--plan-only`（problem materializeとhashまで、solveなし）

## adapter受入条件

- 変更対象は `scripts/audit_small_integrated_weather_milp.py` とfocused testのみ。
- `cost_breakdown` をそのまま保存し、総和と `accounted_total_cost_jpy` の差が `<=1e-6 JPY`。
- BEVがないcaseはminimum SOCを `null` とし、0を捏造しない。
- 既存exact gateと既存testを弱めない。
- adapter commit後、clean SHAをfreezeし、そのSHAでFresh Prepareして初めてsolver実験を行う。過去Prepared IDは構造確認専用でdefaultにしない。

## case設計

| case | 便数 | 抽出規則 | vehicle pool | phase solves | per-phase上限 |
| --- | ---: | --- | --- | ---: | ---: |
| ORACLE_08 | 8 | day-spanning等間隔 | BEV最大5 + ICE最大5 | 2 | 300 s |
| ORACLE_12 | 12 | 同上 | 同上 | 2 | 300 s |
| ORACLE_24 | 24 | 同上 | 同上 | 2 | 300 s |

得られる主張は「この3つの決定論的小規模caseで測ったdeployed Phase 3からscalar integrated referenceまでの距離」である。純粋な分解gap、264便の誤差上限、一般的性能保証は得られない。
