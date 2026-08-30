# Exact commands

## このGoalで実行したコマンドではない

以下はPhase 2承認後の予定コマンドである。現時点ではadapter未実装のため、そのままsolverを開始してはならない。

## 共通preflight

```powershell
git status --short
git rev-parse HEAD
git branch --show-current
```

1行でもdirtyなら停止する。実験commitをfreezeし、`python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000` は別terminalで起動する。GitHub Actions等は使わない。

## 小規模oracle

adapter受入後、clean commitから次をそれぞれ別processで実行する。現在の正本RAIN Prepared inputは存在確認用であり、Phase 2でFresh Prepareを要求された場合は承認済みIDへ置換する。

```powershell
$scenario = 'b23fd26c-1233-4c73-bb9e-bdb8b1584760'
$prepared = 'prepared-a6c5e0a8cdd9b32b-f1e18f252e336f1f-8acc7b3a'
foreach ($trips in 8,12,24) {
  .\.venv\Scripts\python.exe scripts\audit_small_integrated_weather_milp.py `
    --scenario-id $scenario `
    --prepared-input-id $prepared `
    --output "output\november_2026\small_oracle\trips_$('{0:d2}' -f $trips)\audit.json" `
    --depot-id tsurumaki --service-id WEEKDAY `
    --trip-count $trips --vehicles-per-type 5 `
    --time-limit-sec 300 --random-seed 42 --gurobi-threads 1 `
    --skip-five-minute
  if ($LASTEXITCODE -ne 0) { throw "oracle failed at $trips trips" }
}
```

run数は3 top-level、6 phase solves、最大solver累積1,800秒。現行scriptでは費用内訳とminimum SOCが不足するため、adapter前の実行は禁止する。

## RAIN候補感度

既存public endpointとrequest fieldは確定しているが、完全なFresh Prepare/profile/artifact runnerのexact CLIは未実装である。承認済みadapterは既存 `scripts/run_weather_dispatch_diagnosis.py` を拡張し、最低限次のinterfaceに固定する。

```text
python scripts/run_weather_dispatch_diagnosis.py --stage rain-sensitivity \
  --existing-bundle output/diagnostics/pure_ice_weather_ab_453b1d3_20260827 \
  --output-dir <new-empty-dir> --base-url http://127.0.0.1:8000 \
  --rain-profile BASE|EXPANDED_1|EXPANDED_2
```

これは **予定interfaceであり、現時点では存在しない**。実装後に `--help` とfocused testで確定するまでexact commandとして承認しない。APIを推測して手動POSTする代替も許可しない。

各profileの完全requestは、正本requestの共通fieldを保持し、`04_rain_candidate_sensitivity_plan.md` のoverlayを適用する。共通fieldは `mode=phase3_two_stage`、`research_run=true`、15分、1 thread、seed 42、MIP gap 0.1、BestObjStop OFF、selector OFF、full Rolling、WEEKDAY、tsurumaki、rebuild/repair/fallbackなしである。

## PV三水準

MEDIUM生成・hash・添付interfaceが未実装なのでexact solver commandは `NOT AVAILABLE`。P0完了後の別Goalでのみinterfaceを確定する。既存 `run_frontend_controlled_pv_pair.py` をLOW/HIGHだけ先行実行して三水準結果に見せることは禁止する。
