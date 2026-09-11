# Phase 3の週間ICE燃料在庫（2026-09-11）

状態: 燃料不足を許す割当モデルを修正済み。新しいクリーンSHAからの週間再実行は未完了。
研究リリースはBLOCKED。過去の違反結果はDIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。

## 実入力で確認した不成立

凍結 `8a8b32724e19d4ccd87aa10fb1ff452cb5073385` の渋21/22/23・冬週は、
完全Prepareと事前監査を通過した。1,704便、60台、UNKNOWN事業者0、非正距離0、
親シナリオと路線metadataの保持を確認した。

全78,647,760接続候補を保持し、接続変数は明示4,497,240個とfactor incidence
1,228,860個となった。Stage 1全体は6,767,874変数、1,059,433制約、79,816,148非ゼロ係数。
モデル構築253.41秒、Stage 1は120.82秒で2個のincumbentを保持したがgapは86.10%で、
宣言した10%を満たしていない。Stage 2は7.26秒で充電計画を得た。
day-ahead処理全体は421.75秒。これは最適性・物理的成立の証明ではない。

Engineの独立在庫検証がICE燃料違反505件を検出し、`feasible=false` とした。
給油scheduleは空で、初期144 L、タンク160 L、下限16 Lの車両が週後半に下限を割った。
冬週は `DAY_AHEAD_FAILED`、rollingは0/168、他の3季節は
`NOT_EXECUTED_AFTER_FAILURE`。最終会計は不成立であり、表示された費用を週間結果に採用しない。
旧成果物は `C:/master-course-worktrees/shibu21-23-exact-20260911/output/shibu21_23_exact_campaign_20260911/` に保持する。

## 原因と数学的変更

到達経路は `run_exact_seasonal_campaign` → `solve_week` → `OptimizationEngine`
→ `GurobiMILPAdapter._solve_thesis_two_stage` → `_solve_thesis_stage2_charging_dispatch`。
Phase 3のStage 1には燃料費の項があったが、ICE車両ごとの有限燃料制約がなかった。
Stage 2も主にBEV充電を扱い、無給油ICEの週内枯渇を入口で拒否していなかった。
別のintegrated経路に存在する燃料状態式を、この実行の原因として引用しない。

無給油方針の車両vには、営業便・接続回送・各fragmentの出庫/帰庫の消費量をすべて含む
`F_service(v) + F_connection(v) + F_start(v) + F_end(v) <= F_initial(v) - F_reserve(v)`
を追加する。消費が非負で給油0なら燃料は単調減少するため、この終端予算が各時点の
下限保持にも十分である。144 Lと16 Lはmaterialized車両から取得し、metadataの100%で
再計算しない。fuel/CO2費用が無効でも制約は有効。factor表現も同じリットル係数を使う。
旧モデルが許していた物理的に不正な割当を除く変更であり、旧SHAの解は新モデルの証拠へ流用しない。

Stage 2ではdaily-returnの物理event列を実際の窓で切り出し、車両別の残燃料から必要量を検査する。
rollingは引継ぎ済み燃料を初期値に使い、窓より前の消費を二重計上しない。
無BEVで充電不要の早期returnにも燃料検査を適用する。

## 給油と探索初期候補

元depotには `hasFuelFacility=true` があるが、速度・同時処理能力は未登録。
今回は給油なしの計算を進める。毎朝の燃料復元、架空の給油slot、燃料量の増量は行わない。
給油を使う診断には別途明示した方針と設備制約が必要。

探索前のbaselineに燃料不足ICE経路がある場合は、互換性と出庫前条件を満たす未使用BEVへ
経路全体を移したMIP startを用意する。便・順序・車両在庫は変更せず、充電traceは持ち込まない。
full MILPが全割当・充電/SOCを選ぶ。これは探索初期候補であり、固定割当制限、fallback、
post-solve repairではない。変更対応表と未解消経路はmetadataへ記録する。

## 検証と未完了項目

価格/CO2無効時の燃料不足拒否、複数ICEへの分担、144/16 Lの保持、実factorの係数、
Stage 2の無BEV入口、rolling窓、初期候補の原本不変性を対象にnative回帰を実施した。
無効ICE車両は予算と監査から除外し、除外理由を記録する。無効車両を使う旧baselineは
初期候補として拒否し、solver全体をその車両の不正燃料値で停止させない。
availability修正と旧baseline境界を含む最終全体回帰は2,167 passed /
既存PowerPoint証拠2 failed（95.62秒、`output/exact_depot_factor_validation/pytest-finite-fuel-release.xml`）。
対象検証は17 passed（2.63秒）。
対象3経路の独立レビューで発見したavailability P1を解決し、残るP0/P1は0件。
新clean commitからの冬週→168時間rolling→残り3季節の実行が必要。
10%gap未達、正式な時刻表/PV/training来歴、既存PowerPoint証拠2件は別の研究採用ゲートである。
