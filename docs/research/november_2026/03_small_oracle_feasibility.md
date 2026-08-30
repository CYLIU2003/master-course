# 小規模統合oracleの実行可能性

## 判定

`REQUIRES_SMALL_ADAPTER`

core modelは不要である。`scripts/audit_small_integrated_weather_milp.py` は既に以下を実装する。

- Prepared inputと現行scenarioをmaterializeし、calendar counterfactual contractをfail-closedで復元する。
- `milp_max_successors_per_trip=0`、15分刻み、同一のcanonical problemを作る。
- departure順の先頭・末尾を含む等間隔のday-spanning subsetを、8/12/24の任意の `--trip-count` で生成する。
- 各powertrainからcanonical ID順に最大5台を選び、選定規則をmetadataへ残す。
- Phase 3と、scalar canonical actual costを直接最小化するPhase 4を同じ入力で解く。
- Phase 4のOPTIMAL、zero gap、actual-cost contract、会計一致、energy inventory、validationをfail-closedで検査する。

既存test `tests/test_small_integrated_weather_audit.py` はsubset両端、fleet選択、exact gate、actual-cost contract、zero-cost時の相対gap非識別を検証している。過去のclean SHA `93e31b0` でも8/12/24/40便がbounded verificationを通っているが、その結果を新しいexecution SHAの結果へ再ラベルしない。

## 足りない出力

現行case JSONは総費用、vehicle type mix、配車hash、SOC全系列、runtime、gapを持つ。一方、今回の必須比較表に直接必要な次の2項目が正規化されていない。

1. `cost_breakdown` のcanonical内訳（electricity、fuel、vehicle usage、CO2、demand、degradation等）
2. `minimum_bev_soc_kwh` と、そのvehicle/slot

SOCは `used_vehicle_trace[*].solver_soc_kwh_by_slot` から後処理可能だが、費用内訳は現行JSONへ保存されない。したがって実行前にaudit scriptだけへ狭いoutput adapterを追加する。solver、数式、制約、目的関数、subset規則は変更しない。

## adapter受入条件

- 変更対象は `scripts/audit_small_integrated_weather_milp.py` とfocused testのみ。
- `cost_breakdown` をそのまま保存し、総和と `accounted_total_cost_jpy` の差が `<=1e-6 JPY`。
- BEVがないcaseはminimum SOCを `null` とし、0を捏造しない。
- 既存exact gateと既存testを弱めない。
- adapter commit後、clean SHAをfreezeして初めてsolver実験を行う。

## case設計

| case | 便数 | 抽出規則 | vehicle pool | phase solves | per-phase上限 |
| --- | ---: | --- | --- | ---: | ---: |
| ORACLE_08 | 8 | day-spanning等間隔 | BEV最大5 + ICE最大5 | 2 | 300 s |
| ORACLE_12 | 12 | 同上 | 同上 | 2 | 300 s |
| ORACLE_24 | 24 | 同上 | 同上 | 2 | 300 s |

得られる主張は「この3つの決定論的小規模caseで測った近似差」である。264便の誤差上限や一般的性能保証は得られない。
