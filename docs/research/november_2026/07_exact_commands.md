# Exact commands

## 現Goalで許可する確認

以下はPrepare、HTTP、solverを呼ばない。

```powershell
python tools/november_2026/run_small_oracle_matrix.py --plan-only `
  --scenario-code RAIN --prepare-request <fresh-rain-prepare-request.json> `
  --optimization-template <canonical-optimization-template.json> `
  --trip-counts 8 12 24 --output-dir <new-empty-plan-dir>

python tools/november_2026/run_rain_candidate_sensitivity.py --plan-only `
  --prepare-request <fresh-rain-prepare-request.json> `
  --optimization-request <canonical-common-request.json> `
  --profiles config/research/november_2026/rain_candidate_profiles_v2.json `
  --output-dir <new-empty-plan-dir>
```

placeholderを埋める正本requestは、adapter freeze commit後にFrontendと同じFresh Prepare経路から保存する。過去Prepared ID `prepared-a6c5...` は構造確認専用で、defaultにもformal commandにも使用しない。

## 指導教員承認後の順序

1. adapter commitをfreezeし、clean SHAをmanifestへ記録する。
2. そのSHAでFresh Prepareを1回だけ実施し、scenario ID、Prepared ID、source SHA、complete request SHAを封印する。
3. oracle plan-onlyで8/12/24便、`P3_DEPLOYED`と`P4_SCALAR`の6 case commandを生成する。各caseは別process。
4. RAIN 2×2は同じPrepared IDを共有する。共有不能ならFresh Prepareごとの非profile canonical hash完全一致を検証し、不一致なら停止する。

oracle実行時のcase CLIは次の形に固定する（現在は実行禁止）。

```powershell
python scripts/audit_small_integrated_weather_milp.py `
  --scenario-id b23fd26c-1233-4c73-bb9e-bdb8b1584760 `
  --prepared-input-id <fresh-prepared-id> --trip-count <8|12|24> `
  --vehicles-per-type 5 --depot-id tsurumaki --service-id WEEKDAY `
  --time-limit-sec 300 --random-seed 42 --gurobi-threads 1 `
  --skip-five-minute --output <new-immutable-output.json>
```

P3-SCALAR commandは存在しない。既存configでは`P3_SCALAR_UNSUPPORTED`である。generic `build_thesis_experiment_matrix.py` / `run_thesis_sensitivity_matrix.py`は60分・145円/L・車両日費0円のdefaultが正本と異なるため使用禁止。

## PV

LOW/MEDIUM/HIGH adapterは未実装。必要interfaceはslot-wise curve、source/provenance、curve SHA、非PV canonical hash、Fresh Prepare responseである。MEDIUM生成と実行commandは`BLOCKED_PV_MEDIUM_INTERFACE_NOT_IMPLEMENTED`。
