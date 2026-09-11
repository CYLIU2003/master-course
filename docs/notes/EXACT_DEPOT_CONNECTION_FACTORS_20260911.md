# 全接続候補を保持する日跨ぎ接続の縮約（2026-09-11）

3路線campaign追加後の全体回帰: 2,154 passed / 2 failed、97.85秒。
失敗2件は既存PowerPoint証拠の原本hash・部品集合不一致であり、
`output/exact_depot_factor_validation/pytest-campaign-full.xml` に記録した。

状態: 実装・差分検証・4路線の規模検査が完了。許可済みの3路線で週間実行を準備中。
実データの週間計算完了や研究リリースを意味しない。
旧 `e8bd9d6c` のメモリー停止記録は旧SHAの証拠として保持する。

## 問題と到達経路

季節runner → 共有 `solve_week` → `ProblemBuilder` → `OptimizationEngine` →
`MILPOptimizer` → `GurobiMILPAdapter._solve_thesis_two_stage` を対象とする。
従来は日をまたぐ全候補を車両ごとの独立二値変数として展開し、Pythonの候補tuple・
索引・Gurobiの列を重複して保持した。さらに消費量helperが毎回全便lookupを再構成した。

新しい明示設定 `stage1_exact_depot_connection_factors=true` は、Phase 3の車両IDを
保持した定式化で、証明条件を満たす日跨ぎ候補だけを共有接続ノードへ置き換える。
設定がない旧ケースは従来表現を使う。季節runnerはdesignの設定値をcanonical metadataに
保存し、最終結果へ完全候補数・独立変数数・縮約数・削除候補0を記録する。

## 数学的な条件

車両vの候補群が完全二部集合 `I × J` であるとき、元の `x[v,i,j]` に代わり、
出側 `u[v,g,i]` と入側 `z[v,g,j]` を二値変数として作り、
`sum_i u[v,g,i] = sum_j z[v,g,j]` を課す。元の便ノードの出入フロー式に、それぞれを
加える。開始・終了・車両利用・1日複数fragment・時刻占有の制約は保持する。

整数の出入次数が同じなら、完全二部グラフ上で選択された出側と入側を対応付けできる。
逆に元の任意のxからu,zの次数を作れる。連続緩和でも同じ周辺和を持つ非負行列が存在する。
したがって、以下の係数分離条件を満たす群では、元の整数集合とLP緩和の射影を保持する。

- 同一車両、同一の正確な後続便集合、帰庫所要時間、SOC計算の実効消費率を使う。
- canonicalな帰庫地点と車両home depotが一致する。異なるケースは元の変数を残す。
- 次便がhomeか否かで分け、slotの端数切上げ/切下げと回送時間除外を保持する。
- 各接続の充電可能slot集合は、出側の共通anchor前のprefixと入側のtailに分解できる。
  anchorの前後関係を満たさない群や、区間に内部の穴がある群は縮約しない。
- 回送電力量・燃料係数は群内で出発側に依存しない。回送の電力量は従来どおり次便の
  departure slotへ置く。物理Stage 2の電力時系列を変更しない。

長い充電窓の係数は、開始・終了slotの増減と補助連続変数の再帰等式で表す。
物理SOC、帰庫、車両ごとの初期値・終端値、充電器、BESSの単位や式は変更しない。
復元は完全群上のフロー分解であり、候補追加・解後修復・便の再割当ではない。
同点の元接続との対応は変わり得るため、特定のx対応そのものを固定するAPIには使わない。

別途、successor iteratorが同車種の候補filter/sortを呼出し内で共有し、消費量helperは
不変のtrip tupleをキーにprivate lookupを1件保持する。public lookupは変更しない。

## 境界と証拠

全候補数は元のcomplete successor domainで集計し、縮約した接続をpruningとは扱わない。
因数分解時は、追加のpowertrain path-cover下界専用モデルの展開を省略する。
既存の独立便の安全な下界と主Stage 1モデルのsolver boundは保持し、省略理由を出力する。
これは補助下界計算の変更であり、主モデルの目的・候補・制約を緩和しない。
事前に宣言したgapを満たさない解を最適解と呼ばない。

原候補集合、全pairの電力/燃料係数、home/away、非整列slot、係数fallback、候補の穴、
複数日、初期解と復元を検査した。native Gurobiでは2日6便について最大fragment数1/100の
両方で元表現・新表現が可行、費用一致、物理スケジュール検証acceptedを確認した。
関連48テストが通過した。全体回帰は2,140件通過・既存PowerPoint証拠2件失敗
（100.98秒、`output/exact_depot_factor_validation/pytest-full.xml`）。対象の独立レビューで
暗黙接続が制約・目的・復元から欠落するP0/P1は0件。実データの計測はこれから記録する。

Phase 3は二段階法であり、縮約後も統合総費用の大域最適解ではない。全4週の168時間
実行・物理検証・最終会計、正式provenance、既存PowerPoint証拠2件等が未成立なら
研究リリースはBLOCKEDとする。ユーザーが許可した渋21〜23への縮小を使う場合は、
4路線ケースと別の明示scope・入力・記録を作成する。

## 実データの規模検査と三路線への切替え

clean `3cfda00d` の読取り専用検査で、旧Prepareの冬週3,182便・60台を入力fixtureとして
使用した。canonical構築330.47秒、候補の分解33.35秒。元候補271,864,980に対し、
独立接続12,651,780、共有群が表す接続259,213,200、共有群の出入変数2,851,800、
合計接続変数15,503,580となった。候補削除0。これは実solver変数を生成した測定でも
最適化結果でもない。旧prepared JSONのSHA-256は読取り前後で一致した。

4路線ではなお1,550万超の接続変数を要するため、ユーザーが明示許可した渋21〜23へ
切り替える。7日間・4季節・有効60台・各車両の初期/終端SOC・帰庫・BESS・全候補を保持する。
`config/shibu21_23_exact_seasonal_20260911.json` に変更理由と範囲を記録した。
`run_exact_seasonal_campaign.py` は各週をfresh完全Prepare→既存preflight→day-ahead→
168時間Rolling→物理/会計の順に実行する。失敗後の週は未実行として止める。
各週前後のGit SHA/clean状態を確認し、旧入力や旧結果を新SHAの実行証拠へ流用しない。

BEV/ICE × 最大fragment数1/100の4ケースで、元表現と新表現のStage 1目的値・最終費用・
物理検証を比較した。係数cacheの車両IDとpowertrain分離、元adapterから独立に求めた
SOC slot集合との一致も追加検査した。週間実行結果は完了後に別記する。
