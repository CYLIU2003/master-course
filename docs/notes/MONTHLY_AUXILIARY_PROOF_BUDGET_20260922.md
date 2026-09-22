# 毎時の精度証明時間と監視理由の引継ぎ

固定4b1cbbb73f65996e7036339a7866cca6a35c9732は局所hour155・旧保存状態からの42時間連続検証・独立物理・BESS168区間を通過した。2026-09-22 8:43 JSTに新規Prepareから全月を開始したが、新配車の1月hour49（50時間目）でStage2 gap1.1743479800%となり、目標1%の実行前検査が拒否した。49時間受理、完了週0/12。hour49のexecution_state.jsonはなく、拒否候補の実行・費用採用はしていない。旧保存配車の連続診断は、新しい前日配車と初期からの実行経路の全週成立を証明しない。

## 原因の根拠

監視自体の障害ではなく、計算がHOURLY_QUALITY_FAILEDになったため停止。script_observer/failure.jsonのreasonsが空なのは、品質判定がfailed_stage2_qualityに保存されている一方、監視側がday_ahead_reasons/hourly_reasonsだけを読んでいたため。commands.logは独立監査/報告helperが一度も実行されなかったので存在しない。無いログをソルバーの異常終了と扱わない。旧state/failure/native log/queueを保存した。

入力と配車を保存された新規1月の原本から再構成し、native fingerprint 0xdb96ce92が一致。MPS SHA256はe02b96087259e0c634bbe35def62aa3ac0769599c667c84ea04b72979d800904。変えたのはTimeLimitだけで、別の新規ソルバーインスタンスから各条件を実行した。MIPFocus2/NumericFocus3/Method0/Presolve0/Aggregate0/4threads/seed42/FeasibilityTol・IntFeasTol各1e-9は共通。

| 同じモデルの上限 | 終了 | 実秒 | 候補目的値 JPY | 下界 JPY | gap |
|---|---|---:|---:|---:|---:|
| 120秒 | TIME_LIMIT | 120.052 | 23,645.652509 | 23,367.970267 | 1.174348% |
| 600秒 | OPTIMAL（1%基準） | 167.368 | 23,645.652509 | 23,420.341827 | 0.952863% |

両条件の目的値は同額。改善は下界52.371560円で、費用削減ではない。双方の最大native制約違反7.0273e-11、bound/integrality違反0。Stage2の充電窓目的値であり、週間総費用でも統合最適性でもない。証拠: output/monthly_auxiliary_quality_20260922/hour49_budget_diagnosis/summary.json、model_capture.json、各native log。

## 最小の修正

config/shibu21_23_monthly_auxiliary_proof_budget_20260922.jsonでは、全12月・全168時間で毎時の最大時間を120→600秒にする。167秒ちょうどへ合わせず余裕を持たせ、目標に達すれば早期終了。失敗時間だけの再試行はしない。前日Stage1 1800秒/Stage2 120秒/主wall2400秒、探索設定、目標1%、SOC/BESS条件、物理許容差は不変。BESS20～80%、バスPV優先、余剰蓄電、追加予備・終端復元なし。

ソルバーの数式・変数・実行ロジックは変更しない。有限時間の探索経路と解が変わり得るため、新しいclean固定版から全12週を再計算し、旧成功時間/旧週の費用は使わない。observerの元失敗理由引継ぎを修正し、failed_hour、充電目的値・下界・native/recomputed gap・native statusを保存する。engineのfeasible表示とnativeのtime_limitを混同しない。

## スクリプトの実行と受入れ

新制御先: output/monthly_auxiliary_proof_budget_20260922/。一度きりの制御スクリプトが保存hour49/50を新固定版で検証し、同一初回モデル・厳密数値品質・gap1%・実行引継ぎ・Prepared設備に基づくBESS8区間収支が通過した場合だけ、新規Prepareから全12週を開始する。局所2時間は診断専用で、旧49時間と結合した新週・費用は作らない。新規週間の168時間の実行、全週独立物理、確定会計照合、169原本監査は月別計算内で別途必須とする。時間予算以外の数値設定/物理実装を変えていないため、旧配車の42時間診断をもう一度新週の代用品として回さない。

0/12時点の起動記録は完了を表さない。失敗時は停止してこの既存タスクへ1回通知。全12週が監査を通過し、最終図の表示・hash・Gmail重複確認後だけ承認済み宛先へ完了通知を送る。今回の失敗診断ではメールを送らない。実行中の固定コードは変更せず、通常監視でAIを呼ばない。

## 検証と残る限界

関連152 tests通過（7ファイル）。変更する設定の限定、全12月への共通適用、600秒の原本監査、gap拒否、失敗時にprefixを進めない実呼出し経路、元停止理由の転記、通知/完了の分離を検証。ソルバー実装は前版と同じため、既に通過した保存native境界回帰を無目的に再実行していない。自己レビューP0/P1残件なし。独立レビューは未実施。

600秒でも全時間の成立は保証されない。新規週間物理/会計は未完了。今回の前日Stage1はmemory_limit・認証gap3.56749%で1%未達。Phase3二段階の週間総費用の統合最適性、入力仮定、独立研究承認は依然未達。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKEDを維持する。
