# 第5章 実験条件と基礎結果

## 5.0 実験条件の固定

本章の数値は正本実験SHA `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` から取得する。対象は弦巻営業所、WEEKDAY時刻表、264便・16路線、BEV/ICE合計60台のprepared fleet、90 kW充電器10基、PV 1,000 kW、BESS 6,000 kWh/900 kW、受電上限200 kWである。内部時間刻みは15分、Rolling実行幅は60分である。

SUNNY scenario IDは `771d115b-75b0-49f7-a7f0-25f259a2cd21`、RAINは `b23fd26c-1233-4c73-bb9e-bdb8b1584760` である。両者は2025-08-05の同一WEEKDAY運行を用い、RAINだけを日曜ダイヤへ変えない。固定入力hashは一致し、PV hashだけが異なることをconfirmation contractで確認した。

solverはGurobi 13.0.1、seed 42、1 thread、全体585秒、Stage 1 435秒、Stage 2 30秒、requested MIP gap 10%である。候補frontierはBEV 15～35台、radius 4、上限120秒、実効候補22である。新しいsolver runを追加せず、保存済みrunとcross-weather matrixを再集計した。

## 5.1 正当性ゲート

SUNNY、RAINの両ケースで264便すべてが割り当てられ、未担当便は0であった。独立物理検算はVALID、Rollingは24/24 accepted、会計照合はPASSであった。したがって、両結果は当該固定入力下の物理的・会計的に妥当な実行可能解として扱える。

## 5.2 配車結果

SUNNYでは28台のBEVと4台のICEを使用し、BEVが199便、ICEが65便を担当した。RAINでは21台のBEVと11台のICEを使用し、BEVが91便、ICEが173便を担当した。低PV条件では、評価された候補集合内でICE依存の大きい配車が選択された。

## 5.3 エネルギーフロー

SUNNYのPV利用可能量は6,056.25 kWhであり、PV直接利用110.051799 kWh、PVからBESSへの充電2,572.977431 kWh、PV抑制3,373.220769 kWh、系統購入0 kWhであった。RAINのPV利用可能量は996.2 kWh、PV直接利用230.567726 kWh、PVからBESSへ765.632274 kWh、抑制はほぼ0、系統購入130.851943 kWh、最大系統電力122.301666 kWであった。両ケースともBESSは初期3,000 kWhから終端3,000 kWhへ戻った。

## 5.4 評価額

canonical実行日評価額はSUNNY 660,983.7838045002 JPY、RAIN 698,598.6286431606 JPYであり、差は37,614.8448386603 JPYであった。差額は燃料費+33,054.0321902655 JPY、電力費+3,925.5582995972 JPY、CO2費+635.2543487976 JPYから構成される。車両使用費は両ケース640,000 JPYで等しい。

## 5.5 候補集合の分析

22候補のSUNNY/RAIN費用順位のSpearman相関は0.7843026539であった。SUNNY選択候補と次点の差は5,180.298562 JPY、RAINは566.622470 JPYである。選択された使用BEV台数は評価範囲端ではないが、RAINの小さい次点差は候補生成範囲に対する結果の安定性が未確認であることを示す。

## 5.6 gap

Stage 1 certified gapはSUNNY 9.5213476%、RAIN 1.6563581%である。これはStage 1近似目的の値であり、上述したStage 2評価額が同じ割合で最適値に近いことを意味しない。

## 5.7 day-aheadとRolling

SUNNYのday-ahead選択費とexecuted-day評価額は660,983.7838045002 JPYで一致した。RAINのday-ahead選択費は698,296.465283954 JPY、executed-day評価額は698,598.6286431606 JPYであり、Rolling後が302.1633592066 JPY高い。したがって候補選択時の費用と最終報告費用を同じ列へ混在させない。

Rolling差は、実行時の状態引継ぎを反映した結果であるが、予測誤差による差とは限らない。最終比較では、24/24 accepted後の `executed_day_accounting.json` を唯一の費用源とする。day-ahead費用は候補選択過程の説明にのみ用いる。

## 5.8 96スロット系列

各ケースの24個のhourly solver resultから4スロットの実行prefixを抽出し、0～95の系列を構成した。SUNNYの再構成hashは `162f3ab9f51ac50303bb240c36a16f09a1e0bbcbf0b1cf451b87973ef44f2730`、RAINは `8de0222ff9034a04251d55a87a3202f931c81ec55f1146d295de4ee0969159a9` であり、正本hashと一致した。

系列にはmissingとduplicateがなく、PV、PV直接、PVからBESS、BESSからbus、抑制、系統、peak、終端SOCを日会計へ1e-6以内で照合した。したがって `FOUND_AND_VERIFIED` とする。ただしraw hourly resultはローカル正本runに依存するため、Git管理済みbundle単独での再生成可能性とは区別する。

## 5.9 費用差の独立照合

RAIN-SUNNYの燃料費差33,054.0321902655 JPY、系統電力費差3,925.5582995972 JPY、CO2費差635.2543487976 JPYを合計すると37,614.8448386603 JPYとなり、総評価額差と1e-6 JPY以内で一致する。車両使用費差は0である。

この分解は、差の大部分がICE燃料利用の増加と関連することを示す。一方、設備費や劣化費がないため、PV/BESS投資を含めた費用便益ではない。費用成分を増やした場合に順位が維持されるかは感度分析を要する。

## 5.10 計算時間とモデル規模

solve timeはSUNNY 380.9823秒、RAIN 380.0188秒であった。Stage 1 modelは両ケースで825,858変数、726,240二値変数、151,574制約、16,316,201 nonzerosである。同じ非PV入力とsolver controlsを使うため構造規模は一致する。

計算時間がほぼ同じであることを、天候に対するsolver性能の一般結論とはしない。各ケース一回の保存runであり、wall-clock変動を評価する反復がない。認証gapが異なるため、同じ時間で得られたbound品質は異なる。

## 5.11 最小SOC指標

正本に記録されたminimum executed BEV SOCは両ケース68.91 kWhである。ただし集計には使用BEVだけでなく初期状態を持つ全BEVが含まれる。この数値だけから、実際に便を担当した車両の最小余裕や安全marginを評価しない。車両別event timelineは物理検算の証拠として保持する。

## 5.12 基礎結果の受理

全便割当、物理VALID、24/24 Rolling、会計PASS、入力contract一致、hash照合が成立したため、両ケースを実行可能な研究ケースとして受理する。これはoptimality acceptanceではない。SUNNYはrequested 10% gapの範囲にあるが1%ではなく、RAINも1%を超える。指導教員が両ケース1%を要求する場合は追加実験が必要である。
