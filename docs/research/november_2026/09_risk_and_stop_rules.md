# Risk and stop rules

## 実験前stop

- dirty worktree、空SHA、想定branch/SHA不一致
- adapterのfocused testまたはreview未完了
- Prepared input、scenario、calendar、fleet、operator、distance provenance不一致
- 指導教員が費用改善許容値とStage 1 gap採用線を未決定
- 5 GB未満の空き容量

## 実験中stop

- 2件連続で同じ原因により失敗
- fallback、repair、proxy、synthetic代替（承認済みMEDIUM以外）の発生
- 264便caseで未担当、物理、Rolling、会計gateのいずれかが失敗
- request/effective control、code SHA、input hashが不一致
- Phase 4 oracleがOPTIMAL/zero-gap exact gateを満たさない
- solver累積6時間、top-level 18件、wall 24時間の最初の到達

## 禁止する救済

- 便、seed、profile、閾値を結果を見て選び直す
- time limitを延長して都合のよい結果を待つ
- 失敗runを削除する
- 正本artifactを上書きまたは再ラベルする
- core constraint、SOC tolerance、cost definition、validationを弱める
- RAINを実日曜運行または一般的雨天として記述する

## negative result

RAIN winnerが変わり事前許容値を超えた場合は `SELECTION_UNSTABLE_WITHIN_TESTED_PROFILES`。oracleがexactでPhase 3差が大きい場合は、その差を主要結果として保存する。どちらも失敗runではなく、事前登録に答えた研究結果である。

## Phase 1 blocker

現時点では3つの非core adapterが未実装なので `PARTIAL_WITH_EXACT_BLOCKERS`。この判定を無視してPhase 2を開始しない。
