# 第4章 提案手法と実験条件

## 4.1 Phase 3二段階法

Stage 1では各便一意割当、車両フロー、接続可能性、重複禁止、車両使用連結を満たす配車候補を生成する。近似的な時刻別エネルギーrecourseを目的へ含めるが、これは最終費用ではない。候補生成後、Stage 2が候補ごとのBEV SOC、充電、PV・BESS・系統、ICE燃料を15分刻みで最適化する。

## 4.2 候補frontierと選択

BEV候補範囲15～35、radius 4、frontier時間上限120秒の凍結設定から22候補を得た。各候補をSUNNYとRAINの両方で評価し、canonical実行日評価額、使用台数、assignment hashで決定論的に順序付ける。これは有限候補内の選択であり、全実行可能領域の最小値ではない。

## 4.3 Rolling

日初計画の後、60分ごとに再計画し、直近1時間の4スロットを実行prefixとして確定する。この処理を24回行うことで96スロットの実行系列を得る。過去に確定した状態を変更せず、SOCとBESS状態を次stepへ引き継ぐ。

## 4.4 検算

solver statusとは別に、264便割当、時刻接続、turnaround、deadhead、SOC等を物理検算する。Rollingは各stepの受理条件を満たす必要がある。最終費用はcanonical executed-day ledgerを唯一の正本とし、JSON、要約、表との誤差を1e-6 JPY以内で照合する。

## 4.5 シナリオと入力固定

実験SHAは `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` である。SUNNY scenario IDは `771d115b-75b0-49f7-a7f0-25f259a2cd21`、RAINは `b23fd26c-1233-4c73-bb9e-bdb8b1584760` である。弦巻営業所、264便、WEEKDAY、15分刻み、60分Rolling、fleet contract、充電器、BESS、料金、solver controlsを固定する。

## 4.6 評価指標

配車は使用BEV/ICE台数と担当便数、エネルギーはPV直接利用、PVからBESS、BESSからbus、抑制、系統、peak、SOC、燃料、費用は実行日評価額と内訳で評価する。Stage 1 incumbent、bound、certified gapは計算状態として別に報告する。

## 4.7 再現性

Prepared ID、source SHA-256、artifact hashを保存し、正本と派生物を分離する。96スロット系列はraw hourly resultsから実装と同じprefix規則で復元し、正本hashと日合計に一致する場合だけ使用する。fallback、repair、proxy、推測補完は認めない。

## 4.8 Stage 1の定式化

Stage 1は、各便の一意割当、車両フロー、接続可能性、重複禁止、車両使用を満たす。便 $i$ が車両 $v$ に割り当てられる変数を $y_{vi}$ とすれば、各便について $\sum_v y_{vi}=1$ とする。前便 $i$ から次便 $j$ への接続変数 $x_{vij}$ は $(i,j)\in\mathcal A$ の場合だけ存在する。開始・終了変数とともに入出フローを一致させる。

目的は、車両使用やStage 1で評価可能な費用に加え、時刻別エネルギーrecourseの近似を用いる。これはStage 2のPV・BESS・系統・Rollingを完全に同時決定する目的ではない。Gurobiのincumbentとbest boundから計算されるgapはこのStage 1目的に対するものである。

## 4.9 候補生成手順

候補生成はBEV使用構成のfrontierを探索し、選択解周辺のradiusを用いて複数の物理配車を保存する。凍結設定ではBEV候補15～35、composition radius 4、frontier時間上限120秒、実効候補22である。同一の物理assignment hashを重複候補として数えない。

各候補はStage 2へ渡され、エネルギー運用が実行可能かを評価する。Stage 2 infeasible、物理検算失敗、会計不適格の候補を研究結論へ使わない。22候補が全配車空間を覆うという仮定は置かない。

## 4.10 Stage 2の定式化

Stage 2では配車を固定する。BEVのスロットSOC、充電量、充電器占有、PVからbus、PVからBESS、BESSからbus、系統供給、PV抑制、BESS SOCを決定する。各スロットでBEV充電需要と供給を一致させ、PV分配とBESS状態遷移を満たす。受電上限200 kW、BESS電力900 kW、SOC上下限を課す。

ICE側では固定配車から距離と燃料消費を確定し、燃料状態と費用を会計する。Stage 2のcanonical costは、後続候補選択に利用されるday-ahead値と、Rolling後に確定するexecuted-day値を区別する。RAINでは両者が302.163359 JPY異なり、この区別が必要である。

## 4.11 候補選択規則

実行可能候補をcanonical day-ahead costの昇順に並べ、同値の場合は使用車両数とassignment hashで順序を確定する。この規則は再実行時のwinnerを決定論的にする。費用差が小さい候補でもhash tie-breakによる順序を再現できるが、候補集合を変えた場合のwinner安定性を保証するものではない。

SUNNYでは選択候補と次点の差が5,180.30 JPY、RAINでは566.62 JPYである。後者は、Stage 1探索、候補範囲または係数の小さな変化でwinnerが変わる可能性を示す。したがって候補選択規則の再現性と、研究結論の頑健性を区別する。

## 4.12 Rollingアルゴリズム

Rolling step $h$ は、その時点の車両SOCとBESS SOCを初期状態として残余時間を再最適化する。解が受理された場合、直近60分に対応する4スロットだけを実行prefixとして確定し、次stepへ状態を渡す。将来部分は次回に更新されるため、24個のsolver resultを単純連結してはならない。

96スロット系列の再構成でも同じ原則を使う。stepごとに実行prefixだけを抽出し、slot 0～95が一度ずつ存在することを検査する。将来tailや重複slotを含めると日合計が誤るため、正本 `executed_energy_flow_hash` との一致を必須とする。

## 4.13 正当性ゲート

第一のゲートは264便割当と未担当0である。第二は、solver外の独立物理検算であり、接続、回送、重複、SOCを確認する。第三は24個のRolling step全ての受理である。第四はexecuted-day accountingと各報告物の1e-6 JPY以内の一致である。さらに、SHA、dirty state、scenario、Prepared input、固定入力hashを確認する。

これらのゲートは代替関係にない。例えば、物理VALIDでもRollingが23/24なら日全体の研究結果に採用しない。Gurobiが解を返してもaccountingが一致しなければ費用比較を行わない。fallback、repair、synthetic PV、proxyを用いた場合は診断へ降格する。

## 4.14 実験環境と停止条件

凍結runはWindows 11、Intel Core i7-12700、RAM約32 GiB、Python 3.14.6、Gurobi/gurobipy 13.0.1で実行された。seed 42、thread 1、全体585秒、Stage 1 435秒、Stage 2 30秒、requested gap 10%である。Stage 1 best-object stopとpowertrain selector strengtheningはOFFである。

time limitで終了したincumbentは、物理・会計ゲートを通れば実行可能解として保持するが、gap条件を満たさない場合は最適性結果としない。今回の執筆作業では新しいsolver runを開始せず、凍結証拠の分析に限定した。

## 4.15 比較の内的妥当性

SUNNYとRAINは、同一service date、WEEKDAY時刻表、fleet、初期状態、充電器、BESS、料金、目的、solver controlを使う。PV hashは異なる。cross-weather matrixは同一物理配車を両条件へ適用するため、配車そのものとPV条件の相互関係を候補単位で観察できる。

一方、比較日は確率標本ではなく、気象と消費電力量の全交絡を統計的に分離していない。「SUNNY」「RAIN」は実験コードとして維持し、本文では高PV条件、低PV反実仮想と併記する。一般的な晴雨差の検定は本実験の対象外である。

## 4.16 目的関数と会計の分離

Stage 1は配車探索を導くsurrogate objectiveを持つ。Stage 2 day-ahead costは固定配車に対する24時間エネルギー運用の候補選択値である。Rolling executed-day costは、24回の実行prefixを確定した後の最終会計である。三者は同じ通貨単位を含み得るが、同じ最適化問題の目的値ではない。

最終費用表ではexecuted-day accountingだけを用いる。Stage 1 incumbentとboundはgap表に、day-ahead costは候補選択表に置く。RAINでday-aheadとexecuted-dayが異なることは、この分離が形式上だけでないことを示す。値の出典列を持たない表を作らない。

## 4.17 エネルギー収支の検算

PV収支は、PV生成がPV直接、PVからBESS、抑制の和に一致するかを確認する。bus充電収支は、PV直接、BESSからbus、系統からbusの供給とBEV充電負荷を照合する。BESS収支は、初期SOC、充電、放電、効率、終端SOCの関係を確認する。

日合計だけでなく96スロットを検査する理由は、日合計が一致しても時刻別上限やSOC遷移に誤りがあり得るからである。受電peakは各15分slotのkWhをkWへ換算した系列から求め、保存済みpeakへ一致させる。

## 4.18 物理検算の独立性

最適化モデルと同じ制約名を再表示するだけでは独立検算にならない。出力assignmentと時刻表を読み、車両ごとの便順を再構成し、到着、turnaround、deadhead、次出発を検算する。便重複、未担当、operator、距離、SOC eventも確認する。

この検算は、候補生成時の変数やGurobi statusに依存せず、最終artifactを入力とする。最適化側の制約生成に欠陥があっても、出力の物理違反を発見できる経路を維持する。検算許容差を結果に合わせて緩めない。

## 4.19 計算手順

実験手順は次の通りである。第一にcleanな実験SHAでFresh Prepareを行い、入力hashを固定する。第二にStage 1で候補を生成する。第三に各候補をStage 2で評価し、実行可能候補を決定論的に順位付ける。第四に選択候補を24回Rollingする。第五に物理、会計、provenanceを最終化する。

執筆用派生手順ではsolverを呼ばない。公開cross-weather matrixとローカル正本runを読み、候補統計と96スロットを再構成する。再構成値が正本hashまたは会計に一致しなければ出力を受理しない。図はCSVから生成し、PNGとSVGを同じデータで保存する。

## 4.20 統計分析の範囲

候補集合では、記述統計、順位、Pearson相関、Spearman順位相関を計算する。22候補はランダム標本ではなく探索で得た候補であるため、p値や母集団推定を行わない。Pearson相関は変数間の線形な記述関係、Spearmanは候補順位の共通性としてのみ用いる。

選択候補と次点の差は局所的な順位marginとして報告する。marginが大きくても未評価候補への優越を示さず、小さい場合は候補範囲感度の必要性を示す。range edge判定も同様に、探索境界へ張り付いたかを診断するだけで候補十分性を証明しない。

## 4.21 追加実験のgate

追加実験は自動的に開始しない。既存モデル・スクリプトを再利用でき、core変更が不要で、入力・出力をhash化でき、fallbackやrepairがなく、事前停止条件を定められる場合だけ行う。今回の凍結結果は既に章作成に必要な基礎証拠を持つため、新規runを0件とした。

不足証拠はP0～P2へ分類した。小規模統合oracle、RAIN候補範囲、Stage 1 gap採用判断が優先である。価格や電費感度は説得力を高めるが、主張を変える必要がある場合だけ実施する。実験を増やすこと自体を目的にしない。

## 4.22 再現性脅威への対策

実行環境差、乱数、solver version、threadによる差を減らすため、環境、seed、thread、limitsを保存する。formal runの開始・終了SHAとdirty stateを一致させる。出力にはscenarioとPrepared IDを埋め込み、別runのartifact混入を検出する。

図生成も再現対象とする。SVGのelement ID saltと日時metadataを固定し、派生manifestが連続2回の生成で同一SHAとなることを確認する。これは数値正当性の代わりではなく、同じ正本から同じ執筆成果を得るための補助条件である。

## 4.23 本章のまとめ

提案法は有限候補二段階法であり、配車、エネルギー、Rolling、検算、会計を順に接続する。完全な統合最適化ではないため、gapと費用の対象を分離する。実験は固定2ケースの内部比較として設計し、入力hash、独立ゲート、派生再現性によって研究証拠を保護する。
