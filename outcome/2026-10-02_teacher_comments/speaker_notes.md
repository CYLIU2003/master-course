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
2026-10-02先生コメントへの回答：コメント1：どのデータから降水量を持って来ていますか？
回答：降水はSolcastのhistoric radiation_and_weatherに保存されたprecipitation_rate（mm/h）の履歴推定で、雨量計の観測ではない。15分強度×0.25hを合算する。出典：https://docs.solcast.com.au/docs/output-parameters。2025年35,040区間の固定データを用いた。

コメント2：「雨以外で」は必要な条件ですか？何の何に対する比かが不明瞭な書き方のように見えます
回答：雨を優先して分類するので「雨に当たらない日」が必要。分子は昼間積算GHI、分母は同じ昼間の積算晴天時GHI。昼間の判定はGHIではなくclearsky_ghi>=20 W/m²。雨と高日射は両立し得る。R>=0.7を晴れ、それ未満をくもりとする研究用の固定閾値。

コメント3：これはどういう意味でしょうか？雪の日ですか？
回答：雪の日と確認したわけではない。3/3の気温2℃以下の昼間区間の降水量が2.775mmで、降水形態未判定として分類のみ除外。週次計算には3/3の気象・運行を含めている。

コメント4：何がどう判別困難か不明瞭です
回答：判別できない対象は雨/雪等の降水形態。今回の取得項目は気温と降水強度を含むが、雪の観測・降水形態は含まない。2℃以下だけで雪とは断定しない。

コメント5：この項目全体が不明瞭です
回答：各時刻の同じ分類の日の日射値を並べた経験分布の平均、10%点、90%点。P10/P90は実在する1日の曲線でも予測区間/信頼区間でもない。全セル10日以上は件数の確認であり精度保証ではない。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 8. 春（3～5月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ45日、くもり17日、雨29日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 9. 夏（6～8月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ57日、くもり15日、雨20日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。
2026-10-02先生コメントへの回答：コメント6：P90はかなり大きな値に見えますが、日中は晴れていて午後に夕立があったというようなケースが多いのでしょうか
回答：夏雨20日中、10〜14時のGHI/晴天時GHI積算比>=0.7は6日。その中で15時以降の昼間降水が1mm以上は2日。例7/10は比0.879、15時前0.30mm、15時以降1.10mm。雨分類にも明るい時間が含まれることがP90の高い時刻を説明するが、「夕立が多い」は支持しない。事後の探索集計で、対流性降水を同定したものではない。補足37と日別CSVを参照。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 10. 秋（9～11月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ41日、くもり22日、雨28日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。

## 11. 冬（12～2月）の天候別日射カーブ

出典：evidence/weather/seasonal_curves.csv。晴れ70日、くもり10日、雨10日。分類ルールは前ページ。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。
2026-10-02先生コメントへの回答：コメント7：晴れの日で、夏と冬にこれだけの差があるとすると、さすがに傾斜面日射量を採用する必要があるように考えます。（事業者もこのような設置をするとは考えにくいため）
回答：傾斜面日射が必要という指摘を受け入れ、現行が水平面GHIの記述統計・GHI比例PV換算であることを明記。設置角・方位の実条件確認と、直達/散乱から設置面日射を得る別入力版での再評価が必要。現状の12週を補正済みの結果へ改称しない。補足38。未完了：傾斜面を用いたPV再計算・再求解。公式参照：https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 12. 12代表週の運行・充電・費用を確認

全12週の原本ZIPとPrepared hash、physical accepted、account eligible、missing/duplicate slotsなし、全便充足と日別台帳を再照合した。1・11・12月は原FAILEDを残した図表復旧。図の生成だけを計算完了と数えていない。
計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。独立した正式研究採用は未承認。
2026-10-02先生コメントへの回答：コメント8：意味が取れません。
自分のメモ書きではなく、他の人に見せるものということを意識して、表などきちんと修正しましょう。他の行も同様です
回答：聴衆向けの表を全便の担当、車両/充電制約、電力収支、翌朝/費用、解の位置付けへ書き直した。1/11/12月の図表復旧や原FAILEDは元ノートと別紙に保持し、計算失敗と図表失敗を混同しない。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 13. 月別代表週のPV供給と購入電力量

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
PV→BESSと、その後のBESS→バスを同じ発電量として二重計上しない。

## 14. 週次費用は車両日費と電力関連費に分けて読む

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
単位：万円。設備投資・保守・劣化・運転士費等は未計上。超過モデル費は実請求額ではない。

## 15. 3月と11月の受電時系列

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
15分平均受電電力。ピークの高さだけで、購入電力量や超過費用は決まらない。
2026-10-02先生コメントへの回答：コメント9：なぜそういう運用になっているかが重要ですが、この後のスライドでもその理由が論理立てて説明はできていないようにも思われます。人間が考えているでしょうか
回答：両ピークでPV供給0、BESS下限1200kWh、8/10台が翌朝目標90%へ同時充電しており、系統が全バス充電を供給した。ピーク開始SOC、次の営業便発車、車両/充電器IDをCSVへ保存。夜間供給源の理由と、04:15へ集中する探索上の理由は別。帰庫時刻ごとの代替充電余地・予測誤差・計画窓・探索品質の寄与は未分離。3月の超過が長く、総費用差101.64万円のうち90.96万円が超過モデル費差。改善可能性を示唆するが最適/不可避とは断定しない。補足39。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 16. 3月と11月：購入量・時間・最大値の違い

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
超過時間は200 kW+0.001 kWを超えた区間を数える。電力量は原値を積算。

## 17. 受電ピークの周辺を同じ時間幅で確認

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
同時に観測した計画の説明。ピークを回避できたかの対照計算は未実施。
2026-10-02先生コメントへの回答：両ピークでPV供給0、BESS下限1200kWh、8/10台が翌朝目標90%へ同時充電しており、系統が全バス充電を供給した。ピーク開始SOC、次の営業便発車、車両/充電器IDをCSVへ保存。夜間供給源の理由と、04:15へ集中する探索上の理由は別。帰庫時刻ごとの代替充電余地・予測誤差・計画窓・探索品質の寄与は未分離。3月の超過が長く、総費用差101.64万円のうち90.96万円が超過モデル費差。改善可能性を示唆するが最適/不可避とは断定しない。補足39。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

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
2026-10-02先生コメントへの回答：コメント10：これは、他の人に示すスライドには含めなくても良いものです。
人間が取捨選択をしてください
回答：BLOCKED等の管理コードはノート/別紙に保持し、本文は診断・条件付きの結果と正式研究採用未承認という意味を日本語で示す。限界自体は消さない。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

## 21. 補足：費用と単位当たり費用（1～6月）

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
燃料費は消費在庫の評価を含む。営業距離は停留所列に基づく代理距離。

## 22. 補足：費用と単位当たり費用（7～12月）

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
燃料費は消費在庫の評価を含む。営業距離は停留所列に基づく代理距離。

## 23. 補足：代表週の日射量と、月全体との差

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
GHI [kWh/m²/日]とPV発電量[kWh]は別量。分類除外日も日射量の記述集計には含む。

## 24. 補足：今回の結果を解釈するための前提

計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。比較revision 6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。
原本・入力・会計・各CSVのhashと再生成手順を同梱。最適化の再実行なし。
2026-10-02先生コメントへの回答：コメント11：これも、他の人に見せるスライドに入れる内容になっていません。人間が取捨選択してください
回答：計算固定SHA、hash、CO₂図表の警告、内部判定を別紙/ノートへ保持。補足24を気象・ダイヤ年、予測、PV設置条件、費用/設備、BESS在庫、解品質の解釈に変更した。
原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。

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

## 37. 補足：雨分類でも日中に日射が高い日がある

先生コメント6への回答。昼間は晴天時GHI>=20W/m²。雨分類は昼間降水積算>=1mm。夏雨20日のうち10:00–14:00積算GHI/晴天時GHI>=0.7は6日、その中で15:00以降の昼間降水>=1mmは2日。7/10は10–14時の比0.879、15時前昼間降水0.30mm、15時以降1.10mm。これは事後の探索的閾値で公式の夕立分類ではない。P90が高いのは雨の日の集合にも日射が高い時間帯が含まれるため。時刻ごとの90%点で、曲線全体が同じ日ではない。原CSV:summer_rain_days.csv、summer_rain_example_20250710.csv。

## 38. 補足：水平面日射と、PVの設置面日射を分ける

先生コメント7への回答。既存データのGHIは水平面全天日射、DNIは法線面直達、DHIは水平面散乱。既存PV換算はcapacity×clamp(GHI/1000×performance_ratio,0,1)×時間刻みで、設置角・方位を反映していない。先生の傾斜面日射採用の指摘を受け入れる。設置角・方位とモデルを確定した別入力版で評価が必要。既存12週へ後付け補正はしない。傾斜により冬季の日射受光が変わり得るが、冬夏差の解消や費用順位の変化は未計算。既存GHIカーブは地点の水平面の記述統計として保持。公式参照:https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html

## 39. 補足：夜間受電が増えた区間の供給と充電需要

先生コメント9への回答。以下は最終実行系列の観測された組合せであり、比較実験による因果効果の証明ではない。BESS下限1200kWh、充電器10基90kW、BEV翌朝目標90%。ピーク開始の状態と次の営業便発車を車両ID別に照合した。各車両の帰庫から出庫までの代替充電余地、予測誤差、ローリング窓制約、探索到達度の寄与は分離していない。200kWは超過モデル料金の閾値で実設備の上限ではない。PV/BESS/初終端在庫の違いを総費用削減と呼ばない。原CSV:peak_vehicle_evidence.csvと既存energy_15min.csv、charging_schedule.csv、vehicle_soc.csv、vehicle_schedule.csv。
