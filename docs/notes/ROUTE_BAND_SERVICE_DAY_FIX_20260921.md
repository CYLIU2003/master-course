# 2026-09-21 NoRel候補の路線固定検査を営業日へ統一

固定 `48ffb3745156ea4c692046f5a17dcdf62669942c` のNoRel診断は
11:23 JSTに `DAY_AHEAD_FAILED` で終了した。月別12週の完了ではなくメールは送らない。
元のcompletion/failure SHA、native log、canonical結果を照合した。
原本と読取り検査は `output/bess_norel_20260921/` に保存する。

## 原因と修正

配車グラフの `FeasibilityEngine.can_connect` とfragment遷移は、同じ車両・営業日内の
路線固定を要求し、翌営業日の路線変更を許す。nativeの経路抽出は複数営業日を
1つのVehicleDutyに保存できる。一方 `FeasibilityChecker._evaluate_route_band_integrity`
はDuty全体を1路線に制限しており、NoRelが見つけた渋21/渋23の日別変更を2件拒否した。
同じ計画でもDutyの分割形式で検査結果が変わるP1不具合である。

全Dutyの便を車両・営業日ごとに集計し、正規化路線群が1つか確認する。
`trip_service_day_index` をグラフと共有し、24時超の便もservice_date/day_indexの営業日を保つ。
同日の路線変更は帰庫やDuty分割の有無によらず禁止。
帰庫経路、折返し・回送所要時間、車両SOC、給電・燃料の検査は別途引き続き実行する。
数理モデル、後続候補、目的関数、入力便、車両、BESS条件は変更しない。

到達経路は `run_planning_consistency_diagnosis` → `run_exact_seasonal_campaign` →
`run_shibu21_seasonal_diagnostic.solve_week` → `OptimizationEngine` → Phase3 MILP →
canonical planのfeasibility → 独立physical検査・quality保存。
診断wrapperが `day_ahead_reasons` / `day_ahead.reasons` を拾わず、最上位failureで
理由が空になるP1不具合も修正した。元理由を重複なく保存し、generic停止状態で隠さない。

## 元候補の観測値（拒否された診断結果）

| 項目 | 観測 |
|---|---:|
| Stage1初期解 | 4,157,098.222019495円 |
| Stage1最終候補 | 4,156,965.705701730円 |
| 初期解からの目的値差 | 132.516317765円 |
| native/認証下界 | 4,000,000円 |
| native/認証gap | 3.775968% |
| Stage1時間 | 600.589秒、時間制限 |
| 根LP | 474,063反復、OPTIMAL MIPNODEなし |
| nativeメモリ・前/後/最大 | 2.185 / 8.010 / 24.097 GB |
| Stage2充電目的値/gap | 0円 / 0% |
| 最終計画の総費用（予測） | 4,156,638.428391963円 |

132.52円は拒否候補のStage1目的値差であり、採用済み削減額ではない。
Stage2の0円を総費用と扱わない。206車両日×20,000円=4,120,000円に燃料・CO2等が加わる。
旧BESS保護条件との費用差も探索改善とは扱わない。根LP未完了・1%目標未達を維持する。
18GBはソフト上限であり、最大24.097GBを上限内通過とは報告しない。

Prepared設備値（充放電効率各0.95）で672区間を独立再計算した。
BESSは初期3,000→最終1,200 kWh、正味取り崩し1,800 kWh。
最小1,200、最大4,159.625671 kWh、境界・出力・充放電モード違反0件。
収支最大残差2.60e-10 kWh、PV収支最大残差4.08e-11 kWh。
PV発電31,515.091250、直接利用3,799.028050、BESS充電15,990.494690、
BESS→バス16,141.421457、PV抑制11,725.568511、系統買電0、貯蔵損失1,649.073232 kWh。
初期在庫の取り崩しとPV利用を区別する。最終在庫1,200 kWhは設備の下限で、0 kWhではない。
修正版のFeasibilityCheckerによる同じ保存候補の再検査もfeasible=true、errors空。

## 検証と次の診断

焦点テスト60件と周辺テスト74件（合計134件）が通過。
同日混在拒否、翌日変更許可、Duty分割の不変性、24時超とhorizon offset、路線表記正規化、
翌日路線変更時も帰庫経路欠落・時間不足を拒否、失敗理由の引継ぎを確認した。
保存候補を変更せず再読込みした独立physical検査はaccepted=true、違反0件。
再読込みによる確認は修正版の新規求解や研究採用ではない。旧failureと固定コードを保持する。

新しい設計 `config/shibu21_23_route_band_service_day_diagnosis_20260921.json` で、
新clean固定版・新規Prepareから5月day-aheadを1回だけ実行する。
NoRelHeurWork120、双対単体法、4threads、18GB、Stage1 600/Stage2 120秒、gap1%、seed42は維持。
BESSは `minimum_only/physical_floor_only`、初期3,000kWh、設備1,200–4,800kWh、900kW。
初期在庫の追加保護・終端復元を再導入しない。端点表現、全後続網、事後修復禁止を維持する。
通常処理はscript、終了時だけ既存タスクへ1回通知。全12週・rolling・メールは開始しない。

自己レビューで上記P1を修正。独立研究レビューPENDING、研究採用BLOCKED。
CI追加や有料サービスは使わない。全体テストは直近実行済みのため繰り返さず、変更経路を検証した。

## 開始記録

2026-09-21 11:38 JST、clean固定 `e79476d93131803a26d4e1a0ed1cb2092b740700`、
branch `codex/route-band-service-day-20260921` から新規Prepareを開始した。
固定版で焦点16 tests通過。元入力47ファイルSHAと親scenario11参照の移設、caseのsource3参照、
BESSと探索設定を確認。実runner PID33728、venv launcher7232、起動時RUNNING。
制御先 `output/route_band_service_day_20260921` の `startup_verification.json` に記録した。
出力は新worktreeの `output/route_band_service_day_diagnosis_20260921`。
通常処理はscript、終了時だけ既存タスクへqueue。診断の完了・最適性達成はまだ確認していない。

## 11:59 JSTの完了確認

固定e79476d9は新規求解でも日別路線検査と独立physicalを通過した。
BESS672区間収支も通過、3000→1200kWh・買電0。Stage1目的値差132.52円は確認できたが、
初期解の固定Stage2総費用が未保存のため、実総費用の改善額としては未確認。
gap3.775968%・根LP未完了・最大23.718GBで品質課題は継続する。
[結果と次のbarrier限定診断](ENDPOINT_BARRIER_DIAGNOSIS_20260921.md)。
