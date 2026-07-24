# Phase 3 残課題の手動計算・受理手順（2026-07-23更新）

## 1. この手順の目的

本書は、計算時間の長いGurobi実行を手動で行い、実装済みの研究課題を同じ受理基準で判定するための手順である。コード変更時にはsolverを自動実行せず、入力契約、状態引継ぎ、成果物検査だけを自動化する。

入力候補は次の2件である。ただし、この2件をそのまま正式なweather-only比較へ使ってはならない。

| 天候 | scenario ID | service date | 暦日契約 | 使用条件 |
|---|---|---|---|---|
| 晴天 | `771d115b-75b0-49f7-a7f0-25f259a2cd21` | 2025-08-05 | 火曜=`WEEKDAY` | 同日比較の基準候補 |
| 雨天実績 | `b23fd26c-1233-4c73-bb9e-bdb8b1584760` | 2025-08-10 | 日曜=`SUN_HOL` | 日曜別ダイヤ分析。平日晴天とのweather-only比較には使わない |

旧prepared inputはICE25台なので正式条件には使用しない。実在する26台目の車両ID・諸元・利用可否を登録し、必ずPrepareを再実行する。25台で試す場合は`--expected-ice-count 25`を明示し、「旧在庫感度」と表示する。

正式な晴雨比較は、同じservice date、同じ`service_id`、同じ`timetable_rows`、同じ車両・設備・料金・seedへ、晴天曲線と雨天曲線だけを与える反実仮想実験とする。推奨は2025-08-05火曜のprepared scopeを共通化し、雨天代表曲線を持つ別scenarioを作る方法である。現行の2025-08-10雨天scenarioを使う場合は`SUN_HOL`で再Prepareし、「日曜雨天ケース」として別に報告する。日付やservice IDを偽って264便へ合わせない。

`solcast_pv_proxy_v1`は対象日実PV形状を用いるため、検証用・Oracle寄りのproxyである。この結果だけから実運用の予報性能を主張しない。予報誤差への頑健性は5節のrolling更新ケースで別に評価する。

## 2. BESS終端方針

営業所設備画面では、次の3方針を選択できる。

| 画面表示 | 保存値 | 数理的意味 |
|---|---|---|
| 運用範囲のみ | `minimum_only` | 全slotのSOC上下限と終端SOC下限をhard constraintとして守る。終端目標は置かない。 |
| 初期SOCへ戻す目標 | `return_to_initial` | 上記に加え、終端SOCを初期SOCへ一致させる。代表日比較の在庫条件を揃える場合に使う。 |
| 終端SOC目標を指定 | `fixed_target` | 上記に加え、入力した終端SOC目標へ一致させる。 |

`minimum_only`でもBESS SOC下限・上限、容量、出力、充放電効率、終端SOC下限は緩和されない。終端SOCを初期値へ戻さない単日結果は、初期在庫の取り崩しを含む可能性があるため、`return_to_initial`の単日費用とそのまま経済性比較しない。

## 3. 正式な同日晴天・雨天計算（Stage 1: 240秒、Stage 2: 60秒）

以下は同日・同一平日scopeを用意できた後のPowerShell例である。baseline と PV-counterfactual は同じ `scenario-id`、同じ `prepared-input-id`、同じ `service-id` を使い、後者にだけ雨天代表PV曲線JSONを渡す。用意できるまでは雨天コマンドを実行せず、2025-08-10を`WEEKDAY`に偽装しない。

```powershell
$env:GRB_LICENSE_FILE = 'C:\Users\RTDS_admin\gurobi.lic'
Set-Location C:\master-course

python scripts\run_research_phase3_frontend_weather.py `
  --case-name sunny_formal_current `
  --scenario-id 771d115b-75b0-49f7-a7f0-25f259a2cd21 `
  --prepared-input-id <SUNNY_PREPARED_INPUT_ID> `
  --expected-service-date 2025-08-05 `
  --output-dir C:\master-course\output\research_phase3_sunny_formal_current `
  --comparison-design same_service_date_pv_counterfactual `
  --comparison-role baseline `
  --expected-bev-count 35 --expected-ice-count 26 `
  --time-step-min 15 --time-limit-sec 300 `
  --stage1-time-limit-sec 240 --stage2-time-limit-sec 60 `
  --stage1-candidate-time-limit-sec 0 `
  --mip-gap 0.025 --random-seed 42

python scripts\run_research_phase3_frontend_weather.py `
  --case-name rain_pv_counterfactual_formal_current `
  --scenario-id 771d115b-75b0-49f7-a7f0-25f259a2cd21 `
  --prepared-input-id <SUNNY_PREPARED_INPUT_ID> `
  --expected-service-date 2025-08-05 `
  --output-dir C:\master-course\output\research_phase3_rain_pv_counterfactual_formal_current `
  --service-id WEEKDAY `
  --comparison-design same_service_date_pv_counterfactual `
  --comparison-role pv_curve_counterfactual `
  --counterfactual-pv-curve-file <RAIN_PV_PROXY_OR_TYPICAL_CURVE_JSON> `
  --expected-bev-count 35 --expected-ice-count 26 `
  --time-step-min 15 --time-limit-sec 300 `
  --stage1-time-limit-sec 240 --stage2-time-limit-sec 60 `
  --stage1-candidate-time-limit-sec 0 `
  --mip-gap 0.025 --random-seed 42
```

各runの`input_audit.json`で、`calendar_service_contract.matches=true`、`weather_pv_forecast_applied=true`、`weather_pv_forecast_skip_reason=null`、`git_state_available=true`、空でない`git_sha`を先に確認する。晴天runは`weather_comparison_contract.comparison_role=baseline`、雨天曲線runは`pv_curve_counterfactual`、両者の`comparison_control_hash`が一致することを要求する。`weather_decision_policy.policy_scope=pv_curve_only`なら、結果はPV曲線差の反実仮想であり、天候に応じた配車方策差を証明するものではない。続いて、比較契約と電力・燃料帳尻を検査する。ここでの監査は日次計画の暫定監査であり、rollingを含む最終受理は4節の後に行う。

フロントから通常の手動実行を行ったdated runでは、次の入力provenanceも確認する。

```powershell
python scripts\verify_run_input_provenance.py `
  --run-dir C:\master-course\output\<YYYY-MM-DD>\<run_YYYYMMDD_HHMM>
```

`run_input_validation.json.valid=true`を要求する。`scenario_input_snapshot.json`でscenario/inventory、`prepare_input_audit.json`でPrepare profile/scopeと元prepared JSONのSHA-256、`optimization_parameters.json`でフロント要求値とcanonical実効値、`code_provenance.json`で実行開始前のGit SHA/dirty状態を照合する。既存の古いrunへこれらを推測で後付けせず、新規手動実行で生成されたbundleだけを正式な入力証跡として扱う。

```powershell
python scripts\compare_research_phase3_weather.py `
  --sunny-summary C:\master-course\output\research_phase3_sunny_formal_current\summary.json `
  --rain-summary C:\master-course\output\research_phase3_rain_pv_counterfactual_formal_current\summary.json `
  --output-dir C:\master-course\output\research_phase3_weather_formal_comparison

python scripts\audit_phase3_weather_energy_balance.py `
  --sunny-run C:\master-course\output\research_phase3_sunny_formal_current `
  --rain-run C:\master-course\output\research_phase3_rain_pv_counterfactual_formal_current `
  --audit-dir C:\master-course\output\research_phase3_weather_formal_audit
```

受理条件は、両ケース264便担当、fallbackなし、postsolve repairなし、Stage 2可行、全hard validation違反0、晴雨間の`scenario_id`・prepared SHA・service date・fleet・initial SOC・`comparison_control_hash`一致、電力収支残差`1e-6 kWh`以下、燃料費再計算残差`1e-6円`以下である。Stage 1がtime limitの場合はincumbent、bound、gapを必ず併記し、大域最適とは表現しない。`charging_source_provenance.json`で、サイト／営業所×時刻のsource flowが厳密か、車両別splitがsolver-nativeか比例按分かを別々に確認する。車両別の比例按分をサイト電源変数と同じ意味の厳密な車両別決定変数として扱わない。

### 3.1 BEV全数使用と車両日費用の政策感度

基準ケースでは`--minimum-used-bev-count 0`を明示し、費用最小化が選ぶ車種構成を観察する。指導教員の「晴天時にEV35台を全て使う」問いには、別runで`--minimum-used-bev-count 35`を指定する。これはBEV使用台数のhard lower boundを追加する政策ケースであり、基準ケースへ混ぜない。

車両日費用20,000円との競合は、同一入力で例えば0円、10,000円、20,000円を別runとして実行する。

```powershell
# 例: BEV35台を最低1便ずつ使用し、車両日費用20,000円を維持する政策ケース
python scripts\run_research_phase3_frontend_weather.py `
  --case-name sunny_all_bev_policy_20000 `
  --scenario-id 771d115b-75b0-49f7-a7f0-25f259a2cd21 `
  --prepared-input-id <SUNNY_PREPARED_INPUT_ID> `
  --expected-service-date 2025-08-05 --service-id WEEKDAY `
  --output-dir C:\master-course\output\research_phase3_sunny_all_bev_policy_20000 `
  --expected-bev-count 35 --expected-ice-count 26 `
  --minimum-used-bev-count 35 `
  --vehicle-usage-cost-jpy-per-used-bus 20000 `
  --time-step-min 15 --time-limit-sec 300 `
  --stage1-time-limit-sec 240 --stage2-time-limit-sec 60 `
  --stage1-candidate-time-limit-sec 0 `
  --mip-gap 0.025 --random-seed 42
```

各費用水準について、可行性、使用BEV/ICE台数、担当便数、会計総費用、共通固定費を除く運用費、Stage 1 bound/gapを表にする。制約を追加した政策ケースが安い／高いという結果を、無制約基準ケースの大域最適性とは混同しない。

## 4. 日次計画の後に1時間ずつ再最適化する計算

日次結果の車両・便割当を固定し、各時刻で残り1日を見通して充電、PV、BESS、系統受電だけを再最適化する。先頭60分を実行した結果から、次時刻のEV SOC、BESS SOC、既発生の最大需要を自動抽出する。

晴天の24時間連鎖例は次の通りである。開始時刻は固定値を手入力せず、日次結果の電力・SOC horizon開始時刻を使う。これは配車対象便の切捨て条件ではなく、15分slotの基準である。配車はprepared scopeの`264/264`便を対象にする。

```powershell
$dayAheadPath = 'C:\master-course\output\research_phase3_sunny_formal_current\solver_result.json'
$dayAhead = Get-Content $dayAheadPath -Raw | ConvertFrom-Json
$rollingStart = [string]$dayAhead.metadata.horizon_start

python scripts\run_hourly_charging_reoptimization.py `
  --scenario-id 771d115b-75b0-49f7-a7f0-25f259a2cd21 `
  --prepared-input-id <SUNNY_PREPARED_INPUT_ID> `
  --expected-service-date 2025-08-05 `
  --day-ahead-result $dayAheadPath `
  --output-dir C:\master-course\output\research_phase3_sunny_hourly_chain `
  --current-time $rollingStart --end-time $rollingStart `
  --execution-minutes 60 --time-limit-sec 60 `
  --mip-gap 0.1 --random-seed 42 `
  --bess-terminal-policy scenario
```

同日雨天ケースもscenario、prepared input、日次結果、出力先だけを対応する値へ置き換え、日付と`service_id`は共通値を維持する。各`step_*`にsolver result、summary、次時刻用stateを保存し、全体を`rolling_chain_summary.json`へまとめる。残り時間目的値は時間ごとに同じ将来区間を重複して含むため、合計して1日の費用にしない。

受理条件は`rolling_chain_summary.json.chain_accepted=true`である。内訳として、全step可行、実行slotの欠落・重複なし、固定割当不変、EV SOCが次slot開始値、BESS SOCが実行slot終了値、on/off-peak最大需要が時間とともに減少しない、BEV終端均衡、BESS終端偏差`1e-6 kWh`以下、日次・rolling双方のGit cleanを要求する。`--bess-terminal-policy minimum_only`は感度分析には使えるが、代表日受入では終了コード2になる。

rolling完了後の最終監査は、日次runとrolling summaryを同時に要求する。

```powershell
python scripts\audit_phase3_weather_energy_balance.py `
  --sunny-run C:\master-course\output\research_phase3_sunny_formal_current `
  --rain-run C:\master-course\output\research_phase3_rain_pv_counterfactual_formal_current `
  --audit-dir C:\master-course\output\research_phase3_weather_formal_audit_final `
  --require-rolling `
  --sunny-rolling-summary C:\master-course\output\research_phase3_sunny_hourly_chain\rolling_chain_summary.json `
  --rain-rolling-summary C:\master-course\output\research_phase3_rain_hourly_chain\rolling_chain_summary.json
```

`weather_energy_balance_audit.json.advisor_acceptance.all_cases_accepted=true`にならない限り、先生提出用の正式結果にしない。

## 5. PV予測誤差の検証

`--pv-forecast-updates-json`を付けると、各再最適化時刻のPV予測を明示的に更新できる。JSONは時刻をkeyとし、営業所ごとに当日全slotの予測発電量を`kWh/slot`で与える。次の0配列はschema説明用であり、実験データとして使わない。

```json
{
  "05:00": {
    "forecast_by_depot": {
      "tsurumaki": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    }
  }
}
```

連鎖する全時刻のkeyとfull-horizon profileが必要である。各stepのsummaryにprofile hashと日量を保存する。検証ケースは少なくとも、完全予測、PVを一貫して20%過大予測、20%過小予測、正午以降の急減を用意する。比較時は、実行済みslotの実現値を変えず、将来slotだけを更新する入力ファイルを作る。

## 6. 終端方針、複数日価値、seed感度

1. 同じ日・同じprepared scopeで、`return_to_initial`、`minimum_only`、`fixed_target`を別々にPrepareして計算する。
2. 報告するのは可行性、終端SOC、初期からのSOC変化、系統受電、PV利用、ピーク、会計費用である。
3. `minimum_only`の1日目終端SOCを2日目初期SOCへ引き継いだ2日連続ケースを別に作り、2日合計で評価する。1日目だけの費用差を効果量にしない。
4. seed 42、43、44で各天候を再計算し、使用BEV/ICE、担当便、会計費用、Stage 1 gapの範囲を示す。time limit、mip gap、車両、価格、設備は固定する。

複数日ケースでは翌日のダイヤ・PV・価格が必要である。入力を用意していない段階では「終端SOC自由化により経済性が改善した」と結論しない。これは計算未実施を隠すためではなく、評価期間外の蓄電価値を無視しないための研究上の受理条件である。

## 7. 完了判定

次の成果物が揃った時点で残課題を完了とする。

- 同日・同一ダイヤ・同一在庫をclean commitから実行した晴天・雨天正式成果物とstrict comparison
- 両天候の毎時連鎖結果
- PV予測誤差4条件
- BESS終端3方針と2日連続評価
- seed 3条件の頑健性表
- 全ケースの入力hash、Gurobi version、license path、time limit、gap、seed、fallback/postsolve repair、validation結果

計算を実行していない項目は「実装済み・未実行」と記載し、完了済みの研究結果には数えない。2025-08-10雨天実績を使う別分析では`SUN_HOL`を指定し、2025-08-05平日晴天とのweather-only効果量には含めない。
