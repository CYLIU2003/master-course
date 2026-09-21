# 2026-09-21 日別路線検査の修正後の結果と根LP診断

## 確認結果

clean固定 `e79476d93131803a26d4e1a0ed1cb2092b740700` は11:59 JSTに
`DIAGNOSIS_COMPLETE` で終了した。completion/summaryと5原本SHA、固定版cleanを照合した。
日別路線検査の失敗は解消し、独立physicalはaccepted=true、違反0件。
確認記録は `output/route_band_service_day_20260921/review.json`、
再現用読取りscriptは同フォルダ `review_completion.py`。

| 指標 | 値 |
|---|---:|
| Stage1最初の目的値 | 4,157,098.222019495円 |
| Stage1終了時目的値 | 4,156,965.705701730円 |
| Stage1目的値改善 | 132.516317765円（約0.00319%） |
| native/認証下界 | 4,000,000円 |
| native/認証gap | 3.775968%（目標1%未達） |
| 根LP | 476,447反復で時間制限、OPTIMAL MIPNODEなし |
| 前処理最終callback / 最初のMIP callback | 167.136 / 174.352秒 |
| nativeメモリ 前 / 後 / 最大 | 2.185 / 8.010 / 23.718 GB |
| Stage2充電目的値 / gap | 0円 / 0% |
| 最終計画総費用（予測） | 4,156,638.428391963円 |

最終総費用は車両206日×20,000円=4,120,000円、燃料36,087.193706円、
CO2 551.234686円等からなる。Stage2の0円を総費用0円としない。
最初のincumbentについて固定配車Stage2を解いた総費用は保存されていないため、
132.52円を「初期解からの実総費用削減」とは断定できない。旧534aba0bや旧12週の値で
この欠落を埋めない。実PVの168時間rollingと実績会計は未実行。

今回の終了理由は時間制限であり、メモリ停止ではない。ただし最大23.718 GBは
soft18 GBを超えているため、メモリ上限内通過とはしない。根LPが完了しなかった点と、
物理検査の通過、解の品質を分ける。日別路線検査の修正を新たな費用改善と扱わない。

## BESSとPV

Prepared設備値（6000kWh、900kW、充放電効率各0.95、物理1200–4800kWh）を使い、
全672区間を保存traceから独立計算した。収支最大残差2.595e-10kWh、
PV収支残差4.072e-11kWh、SOC・電力・同時充放電の違反0件。

- 初期3000→最終1200kWh、正味取り崩し1800kWh。最小1200、最大4159.625671kWh。
- PV発電31515.091250kWh、直接バス利用3799.028050kWh。
- PV→BESS15990.494690kWh、BESS→バス16141.421457kWh、損失1649.073232kWh。
- PV抑制11725.568511kWh、系統買電0kWh、系統→BESS0kWh。

初期在庫の取り崩しをPV発電として数えない。空は利用可能量の下限1200kWh、
満杯は4800kWhという設備定義を維持する。追加在庫保護・終端復元は再導入しない。

## 次の限定診断

双対単体法はNoRel有無の双方で根LPを600秒以内に解き終えていない。
次は既存 `bounded_presolve_barrier` を使用する。Method=2、NoRelHeurWork=0。
根LPの解法切替は[Gurobi公式の指針](https://docs.gurobi.com/projects/optimizer/en/current/concepts/parameters/guidelines.html#speeding-up-the-root-relaxation)に沿うが、改善を保証しない。
旧barrierはdense表現・12threadsで根LP前にメモリ停止した。今は端点表現で係数が約1/3になり、
4threadsへ制限しているため、この組合せで実測する価値がある。旧条件との単独要因比較ではない。

設計は `config/shibu21_23_endpoint_barrier_diagnosis_20260921.json`。
solverコード・目的関数・実行可能領域は変更せず、既存profileを明示選択する。
NoRel比較ではMethodとNoRelWorkの2パラメータが変わるため、Methodだけの効果とはしない。
新clean固定版と新規Prepareで5月前日計画だけ1回実行する。
4threads・soft18GB・Stage1 600/Stage2 120秒・wall1200秒・gap1%・seed42、
端点表現、全後続網、同日路線固定、帰庫・時間・SOC、料金、BESS最低残量のみの方針を保つ。
ソルバーやライセンスを更新せず、現在のGurobi13.0.1を使用する。

判定項目は根LPのOPTIMAL MIPNODE、native下界/gap、初期Stage1目的値との差、
最終予測総費用、物理、BESS収支、最大メモリ。根LPだけ完了しても1%達成・統合最適性とはしない。
NoRelで得た候補を旧データとして上書きせず、悪化・失敗ならそのまま記録して停止する。
通常処理はスクリプト、終了時に既存タスクへ1回通知する。AIの定期監視や自動再試行は追加しない。
月別12週・rolling・メールは実行しない。

## 検証範囲

設定差分を機械確認し、物理・経済条件の変更なし、実効Method2/NoRelWork0/soft18GBを確認。
既存profileのnative小規模求解、日別下界、BESS方針、路線検査、診断wrapperの関連36 tests通過。
モデルのコード変更はなく、全体回帰は繰り返していない。
自己確認完了、独立研究承認PENDING、研究採用BLOCKED。
