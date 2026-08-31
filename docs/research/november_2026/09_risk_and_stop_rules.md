# Risk and stop rules

## 実験前stop

- dirty worktree、空SHA、想定branch/SHA不一致
- adapterのfocused testまたはreview未完了
- Prepared input、scenario、calendar、fleet、operator、distance provenance不一致
- 指導教員が費用改善許容値とStage 1 gap採用線を未決定
- adapter freeze commit後のFresh Prepare ID/source SHA/complete request SHAが未封印
- 5 GB未満の空き容量

## 実験中stop

- 2件連続で同じ原因により失敗
- fallback、repair、proxy、synthetic代替（承認済みMEDIUM以外）の発生
- 264便caseで未担当、物理、Rolling、会計gateのいずれかが失敗
- request/effective control、code SHA、input hashが不一致
- Phase 4 oracleがOPTIMAL/zero-gap exact gateを満たさない
- generic thesis sensitivity runner（60分・145円/L・車両日費0円）の使用
- solver累積6時間、top-level 18件、wall 24時間の最初の到達

## 禁止する救済

- 便、seed、profile、閾値を結果を見て選び直す
- time limitを延長して都合のよい結果を待つ
- 失敗runを削除する
- 正本artifactを上書きまたは再ラベルする
- core constraint、SOC tolerance、cost definition、validationを弱める
- RAINを実日曜運行または一般的雨天として記述する

## negative result

RAIN winnerが変わり事前許容値を超えた場合は `SELECTION_UNSTABLE_WITHIN_TESTED_PROFILES`。oracleがexactでPhase 3差が大きい場合は、`deployed_phase3_to_scalar_integrated_reference_distance`として保存する。pure decomposition gapやApproxGapへ改名しない。どちらも失敗runではなく、事前登録に答えた研究結果である。

## Phase 1 blocker

P0 adapterは実装したが、Phase 2は指導教員承認、adapter freeze SHA、Fresh Prepare、事前manifestの非null化まで開始しない。PV MEDIUM interfaceは未実装のままP1 blockerである。
