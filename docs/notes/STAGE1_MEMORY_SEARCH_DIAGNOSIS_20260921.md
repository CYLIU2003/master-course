# 配車探索の停止原因と次の限定診断

## 結果と判定

固定 `daa9ef5997f7e92b1df18372ad592c8489633d74` の診断は、2026-09-21 08:30 JSTに失敗終了。
2条件の比較は完了していない。completion/failure、barrier summaryと5原本のSHA、固定版のclean状態を照合した。
照合記録は `output/stage1_root_search_20260921/review.json`。

| 指標 | barrier | NoRel-work |
|---|---:|---|
| Stage 1目的値 | 4,297,021.92円 | 求解未実行 |
| 初期解からの費用改善 | 0円 | 未評価 |
| 認証した下界 | 4,000,000円 | 未評価 |
| 認証下界に対するgap | 6.91227%（目標1%未達） | 未評価 |
| native下界 | 取得できず（null） | 未評価 |
| 根LPのOPTIMAL MIPNODE記録 | なし | 未評価 |
| Stage 1終了 | memory_limit、約124.4秒 | 入力保存先の衝突 |
| Stage 2 gap | 0.36796%（目標通過） | 未評価 |
| 物理検証 | 通過 | 未実施 |

日別経路被覆の下界は `[32,32,32,32,32,21,19]`、合計200車両日。
同時運行だけを使う以前の224万円から、400万円の下界へ強まった。
配車目的値は全く変わっていないため、47.87%から6.91%へのgapの縮小を費用削減と解釈しない。
Stage 2は固定配車の充電部分であり、その目的値とStage 1の総目的値を直接差し引かない。
実際の168時間rolling・週間費用削減・全12週は今回評価していない。

## 確認した原因と修正

1. **[P1・修正済み] 条件ごとの入力保存先が分離されていなかった。**
   入口 `run_stage1_root_search_diagnosis` → `run_planning_consistency_diagnosis` →
   `run_exact_seasonal_campaign` → `build_source_candidate` が共通の固定フォルダを使い、
   2条件目でFileExistsErrorになった。campaign直下の専用source_candidateへ変更した。
   既存フォルダの削除・上書き・結果再利用で回避しない。時刻表・operator・距離は維持する。
2. **[未解決] nativeメモリ上限18 GBで、根LPへ到達する前に停止した。**
   barrierログはpresolve112.31秒、0 nodes・0 simplex iterations・最初のMIP callbackなし。
   根LPやbarrier反復そのものがメモリを使い切ったとは、このログから断定しない。
   次は両条件ともMethod=1、4 threadsへ変更し、NoRelHeurWork=0/120だけを比較する。
   メモリ上限は18 GBのまま。削減効果は次の実行で検証する。
3. **メモリの証拠を追加。** optimize前後のMemUsed/MaxMemUsedを記録する。
   これは同じGurobi environment全体のGB（10^9 byte）で、Pythonプロセス全体のRSSとは異なる。
   取得できない場合はnullとし、0 GBとは記録しない。

[Gurobi公式の指針](https://docs.gurobi.com/projects/optimizer/en/current/concepts/parameters/guidelines.html)に沿い、
メモリ制約下で双対単体法とスレッド数削減を試す。
[SoftMemLimitの定義](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html#softmemlimit)上、
停止は上限を一時的に超えることがあり、同じenvironment内の他のモデルも使用量に含まれる。
上限到達は解の最適性や実行不能性の証明ではない。

## 次の実行条件

[新設計](../../config/shibu21_23_stage1_memory_search_diagnosis_20260921.json)を使い、
新しいclean固定版から5月前日計画のみを2条件、別子プロセスで順番に1回ずつ実行する。
各条件で新規Prepare。Stage 1は600秒、Stage 2は120秒、wall budget1200秒、gap目標1%、seed42。
両条件の料金・完全後続網・BESS保護・全車両・物理制約・4 threadsを揃える。
旧barrierの12 threadsの結果は同条件の対照として使わない。
失敗時は自動再試行せず停止。全12週の実行・メール送信・AI定期監視は行わない。

今回、目的関数・実行可能領域・費用単位の変更はない。
研究採用はBLOCKED。解の費用改善、各段階の精度、物理・会計、独立研究レビューを分けて判定する。
各段階のgapを通過しても、二段階手法の統合大域最適性を意味しない。

## 検証

関連57 tests通過。実際のsource builderを使って同一checkout内で2 campaignを続けて実行し、
両方が新しい保存先で完了し、時刻表の内容・artifact hashと既存出力が保全されることを確認した。
新profileは小規模native問題でも有効パラメータ・下界・ログ・メモリ値を確認した。
自己レビューでは保存先衝突を修正済み。独立研究レビューはPENDING。

全体回帰は2434 passed / 既存PowerPoint関連2 failed（103.63秒）。失敗は前回と同じ原本hash・
部品構成の不一致で、最適化関連の新規失敗は0件。資料と期待hashは変更していない。
ログは `output/stage1_memory_search_regression_20260921.log`。自己レビューの新規P0/P1残件0。
