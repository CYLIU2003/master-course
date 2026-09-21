# 毎時充電求解の15秒打切りへの対応

2026-09-22 停止更新: 固定b1916e56の連続検証はhour126～154の29時間を通過後、hour155が120秒time_limit・可行解あり・gap71.0609%で停止。全12週は未開始0/12。以下の起動記録は過去履歴。同じ120秒で毎時MIPFocus2を検証し、新しい固定版へ進む。[次の条件と品質検査](MONTHLY_AUXILIARY_STAGE2_QUALITY_20260922.md)。


2026-09-22 07:30 JST 起動確認: clean固定 `b1916e56` で毎時共通120秒・42時間の連続検証を開始。一度きりの制御PID36772、診断実PID59324、入力47ファイルのhash照合済み。現時点は `CONTINUOUS_TAIL_RUNNING`、全月計算は未開始（0/12）。連続検証・独立物理・BESS・gap・数値品質の全ゲート通過後だけ全12週を新規計算する。通常処理はスクリプト、失敗時は停止して1回通知。完了メール未送信。記録: `output/monthly_auxiliary_budget_20260922/gate_startup_verification.json`。


固定 `c5c1eff7f28dea47f545762b15b23c4334e50946` の連続診断はhour126～137の12時間を通過し、hour138（139時間目）で `STAGE2_NO_INCUMBENT / time_limit` となった。前回hour126のINFEASIBLEとは異なり、不可能と証明された停止ではない。月別計算の起動記録はなく、全12週は未開始、成功0/12。完了メールは送っていない。

## 同一モデルで確認した事実

保存されたhour138開始状態・配車・入力から全モデルを再構成し、失敗native logとのfingerprint `0x699742e9` 一致を確認した。80,477行・79,012変数・282,841係数。MPS SHA256は `b8844096c92a63b3889d9a43006e9cce9f62fae5bb51c503e3d9cc0d184e210b`。

| 唯一変える設定 | native結果 | 実時間 | 解数 | Stage2 gap | 最大制約違反 |
|---|---|---:|---:|---:|---:|
| TimeLimit=15秒 | TIME_LIMIT | 15.047秒 | 0 | 未定義 | 未定義 |
| TimeLimit=120秒 | OPTIMAL | 17.130秒 | 1 | 0% | 6.422e-11 |

同一MPSを用いた比較であり、モデルの制約や数値精度は変更していない。NumericFocus3、Method0、MIPFocus1、Presolve0、Aggregate0、4threads、seed42、FeasibilityTol/IntFeasTol各1e-9は共通。15秒制限で必要な探索が打ち切られていたことを確認した。

実際のrolling経路も同じfingerprintで再実行し、可行性・gap0・厳密数値品質・次状態生成・Prepared設備のBESS実行4区間収支を通過した。ここでStage2目的値0円は当該窓の充電目的関数であり、週間総費用0円や統合最適性ではない。全週の独立物理検証は別途必要。

証拠: `output/monthly_auxiliary_numeric_20260922/hour138_budget_diagnosis/` の `identity.json`、`progress.json`、`summary.json`、各native log、`forecast_result.json`、`execution_state.json`、`pv_execution_audit.json`。旧 `preflight_failure.json` と `tail_diagnosis/failure.json` は保持する。

## 全月共通の修正

新設定 `config/shibu21_23_monthly_auxiliary_budget_20260922.json` では、全12週・全168時間の求解上限を最初から120秒にする。17秒ぴったりに合わせず、前日Stage2と同じ最大120秒の枠を使う。解と目標gapを得れば早期終了するため、毎回120秒待つ設定ではない。失敗時間だけを再試行しない。

変更する計算条件は毎時のtime_limit_secとstage2_time_limit_secだけ。前日1800/120秒・主wall2400秒、4threads、目標1%、NumericFocus前日0/毎時3、24時間lookahead、1時間実行は維持。BEV物理制約、SOC初期値・上下限・終端、BESS20～80%・PVバス優先・余剰蓄電・追加予備/復元なし、完全後続網、時刻表、目的関数も維持する。数式の可行領域は変えないが、有限時間の解は変わり得るため全月の新規Prepare・新規計算が必要。

監査は実際の毎時wall上限も原本effective_limitsから照合する。120秒宣言に旧15秒原本が混入した場合は拒否する。残り時間を差し引いたnative Stage2上限と、宣言された全体のwall上限は別々に検査する。

## 実行・通知と残る課題

制御先は `output/monthly_auxiliary_budget_20260922/`。新しいclean固定版から、保存hour126状態を起点に42時間を新条件で連続検証する。新条件の全42時間について可行性・gap・数値品質・引継ぎ・BESS収支を確認し、過去126時間を診断の文脈として全週の独立物理検証を行う。この結合を新しい月別結果へ流用しない。

すべて通過した場合だけ、同じ固定版と条件で全12週を新規開始する。後続の計算・監査・図表はスクリプトへ任せ、通常処理でAIは呼ばない。失敗時は停止し、既存タスクへ一度だけ通知する。全12週の独立監査・最終図表・送信済み確認より前に完了メールは送らない。

関連81 tests通過。設定差が時間上限だけであること、全月共通条件、原本の旧上限混入拒否、既存の監視・重複通知防止を検証した。ソルバー実装・制約は変えておらず、前版で通過した32件のnative数値回帰は今回は再実行していない。自己レビューP0/P1残件0、独立レビュー未実施。

現在の証拠は局所診断。120秒で全時間が通過する保証ではない。全月完了、確定週間費用比較、Stage1の目標gap、二段階の統合最適性、研究採用は別の判定である。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKEDを維持する。
