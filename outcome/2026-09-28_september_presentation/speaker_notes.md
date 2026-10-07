## 1. 修士論文研究　2026年9月進捗報告

9月19日版の構成と用語を継承し、結果はf524eca2の12週に更新した。旧版の数値と混ぜない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
診断結果の条件付き週次評価。統合最適性・独立した正式研究採用は未確認。

## 2. 研究の目的と、前回MTGからの進捗

前回の宿題は7日間への拡張、季節4区分と晴れ・くもり・雨の標準曲線、天候によるばらつき。最適化ケース数は12で、4季節は気象の分類である。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
月1週の記述的比較。手法の優越性・PVだけの因果効果は今回の結論に含めない。

## 3. 対象システムと用語


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
PVは総発電入力。走行以外の営業所負荷を0とするモデル上の仮定。

## 4. 車両・設備・境界条件

出典：DAY_WEEK_PARAMETER_COMPARISON_20260927.mdと各週のPrepared。BEVとBESSのSOC上限を混同しない。1日実験から終端方針とPV境界等が変わり、単純な費用比較はしない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
設備定格の実証ではなく設定条件の検算。200 kWは有料超過の課金閾値。

## 5. 計画・実行と、評価期間

Phase 3は配車と固定配車下の充電を分ける。各段階のgapは週間統合gapではない。予測は学習年のみのclimatology、評価は2025年の履歴推定。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
実車運行の観測ではなく計算上の実行。重複する計画窓を合算しない。

## 6. 2025年の各月から選んだ12代表週


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
2026年の固定ダイヤを2025年の気象で評価する仮想実験。各月平均への外挿はしない。

## 7. 天候カーブの分類とデータ範囲

昼間は晴天時GHIが20 W/m²以上。昼間降水1 mm以上を雨、その他は日射/晴天時日射の比0.7以上を晴れ、未満をくもり。2℃以下で昼間降水1 mm以上は降水形態を識別できず除外。3月3日の1日を除き364日を分類。P10とP90は各時刻の経験分位点で、一つの実際の日の曲線でも信頼区間でもない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
公式の天気分類・長期平年値・予測区間ではない。2025年評価の予測学習には使わない。

## 8. 春（3～5月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ45日、くもり17日、雨29日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 9. 夏（6～8月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ57日、くもり15日、雨20日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 10. 秋（9～11月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ41日、くもり22日、雨28日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 11. 冬（12～2月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ70日、くもり10日、雨10日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 12. 12週で運行・電力収支・費用の照合が成立

全12週の原本ZIPとPrepared hash、physical accepted、account eligible、missing/duplicate slotsなし、全便充足と日別台帳を再照合した。1・11・12月は原FAILEDを残した図表復旧。図の生成だけを計算完了と数えていない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。独立した正式研究採用は未承認。

## 13. 月別代表週のPV供給と購入電力量


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
PV→BESSと、その後のBESS→バスを同じ発電量として二重計上しない。

## 14. 週次費用は車両日費と電力関連費に分けて読む


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
単位：万円。設備投資・保守・劣化・運転士費等は未計上。超過モデル費は実請求額ではない。

## 15. 3月と11月の受電時系列


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
15分平均受電電力。ピークの高さだけで、購入電力量や超過費用は決まらない。

## 16. 3月と11月：購入量・時間・最大値の違い


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
超過時間は200 kW+0.001 kWを超えた区間を数える。電力量は原値を積算。

## 17. 受電ピークの周辺を同じ時間幅で確認


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
同時に観測した計画の説明。ピークを回避できたかの対照計算は未実施。

## 18. 3月と11月の費用差を費目へ分解


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
超過モデル費＝200 kWを超える電力量×500円/kWh。実請求差・手法の削減効果ではない。

## 19. BESSの初期・終端在庫と解釈


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
BESSは余剰PVで充電。原本のbalancedは終端方針の充足であり、初終端一致ではない。

## 20. 今回の結論と、主張できる範囲

今回の価値は週次成立と費用の説明。対照実験がないので削減額や優越性は言わない。電費一定で空調季節変動を評価していない。各月1週と2025年1年の記述統計から月平均・長期傾向を断定しない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
正式研究採用BLOCKEDを保持。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。

## 21. 補足：費用と単位当たり費用（1～6月）


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
燃料費は消費在庫の評価を含む。営業距離は停留所列に基づく代理距離。

## 22. 補足：費用と単位当たり費用（7～12月）


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
燃料費は消費在庫の評価を含む。営業距離は停留所列に基づく代理距離。

## 23. 補足：代表週の日射量と、月全体との差


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
GHI [kWh/m²/日]とPV発電量[kWh]は別量。分類除外日も日射量の記述集計には含む。

## 24. 補足：求解品質と検証の範囲


計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
原本・入力・会計・各CSVのhashと再生成手順を同梱。最適化の再実行なし。

## 25. 補足：1月代表週の電力需給と車両SOC

出典：evidence/2025-01-06/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点697は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 26. 補足：2月代表週の電力需給と車両SOC

出典：evidence/2025-02-03/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 27. 補足：3月代表週の電力需給と車両SOC

出典：evidence/2025-03-03/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 28. 補足：4月代表週の電力需給と車両SOC

出典：evidence/2025-04-07/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 29. 補足：5月代表週の電力需給と車両SOC

出典：evidence/2025-05-12/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 30. 補足：6月代表週の電力需給と車両SOC

出典：evidence/2025-06-02/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 31. 補足：7月代表週の電力需給と車両SOC

出典：evidence/2025-07-07/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 32. 補足：8月代表週の電力需給と車両SOC

出典：evidence/2025-08-04/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点697は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 33. 補足：9月代表週の電力需給と車両SOC

出典：evidence/2025-09-01/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 34. 補足：10月代表週の電力需給と車両SOC

出典：evidence/2025-10-06/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点697は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 35. 補足：11月代表週の電力需給と車両SOC

出典：evidence/2025-11-10/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。

## 36. 補足：12月代表週の電力需給と車両SOC

出典：evidence/2025-12-01/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点695は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。
