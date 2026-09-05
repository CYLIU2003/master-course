# 発表者ノート・説明練習

## 1. 研究の一文説明

固定平日時刻表を守りながら、BEVとICEの担当便を選び、その配車で可能な充電・PV・BESS運用を比較する研究です。今日は8月に得た二つの実行可能な結果と、優位性の検証に足りない証拠を分けて説明します。改訂によって新しい最適化結果が出たわけではありません。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json

## 2. 背景と決定のつながり

BEVは安価な電源を使えるだけでは足りず、次便に間に合う場所と時間で充電できる必要があります。充電設備・受電上限・SOCを守ると、どの便をBEVにするかと充電の時刻が結び付きます。「まとめて考える」はシステム全体の意味で、現行法が一体型の大域最適解を求めるという意味ではありません。

出典：

- docs/thesis/authoring_v1/03_mathematical_formulation.md

## 3. 三つの問いを別々に答える

RQ1は選択済み計画の記述的結果まで進んでいます。RQ2/RQ3は未実験です。結果を見てから都合よく仮説を作らず、比較の対象・費用尺度・失敗時の扱いを固定します。単純方式への性能優位や天候一般への因果効果は現在の二条件からは言えません。

出典：

- docs/thesis/authoring_v1/01_research_questions_and_contributions.md
- outcome/2026-09-05_literature_review/02_adoption_protocol.md
- https://research.chalmers.se/en/publication/538305

## 4. 比較対象は晴雨の観測二日ではない

SUNNY 771d115b-75b0-49f7-a7f0-25f259a2cd21、RAIN b23fd26c-1233-4c73-bb9e-bdb8b1584760。両者ともservice_dateは2025-08-05、WEEKDAY、弦巻264便で固定し、RAINには8月10日由来の低PV曲線を与えます。日曜ダイヤや電費まで変えた晴雨比較ではありません。60台はこの凍結Prepareの有効集合であり、一般設定の固定台数ではありません。入力ハッシュの一致はresult_summary.input_contractに記録されています。充電器・PV・BESS設備はケース設定で、実際の営業所の設置実績と確認した値ではありません。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- outcome/2026-09-05_research_progress/04_parameter_sources.csv

## 5. 二段階法を正しく説明する

Stage 1には時刻別エネルギーrecourseの緩和があり、電力を全く考えない配車ではありません。しかしStage 2の厳密な電力スケジュールとは異なります。候補ごとに配車を固定して電力計画を求め、canonicalな前日評価額、使用車両数、物理割当hashの辞書順で選択します。その後のRollingは配車を変えず残りの電力計画を更新します。最終費用の唯一の正本はrolling_hourly_chain/executed_day_accounting.jsonです。

出典：

- docs/thesis/authoring_v1/03_mathematical_formulation.md
- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json

## 6. パラメータは変更せず弱点を開示する

元版のパラメータを維持して、効率・SOC上下限・終端条件を補いました。充電設備やBESSの設定が実在設備として確認されたとは言いません。文献の図表構成を参考にしたことと、その文献から数値を採用したことは別です。感度分析や車両仕様の原典確認は今後の課題です。

出典：

- docs/thesis/authoring_v1/05_assumptions_parameters_units.md
- outcome/2026-09-05_research_progress/04_parameter_sources.csv

## 7. 設定と実測を混同しない

585秒は要求された上限の値で、22候補と24回Rollingを含む全工程wall timeが585秒以内だったという意味ではありません。実効上限は22候補・radius4であり、frontierの15–35台以外の生成経路も含むため候補全体は14–35台です。元版の設定表を残しつつ意味を修正しました。solver timeは補足20に出典の定義のまま示します。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- docs/thesis/authoring_v1/05_assumptions_parameters_units.md
- docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis_summary.json

## 8. 先行研究を公平に評価する

Cuiらは著者所属機関の要旨を確認した範囲です。本文未読の部分を欠陥と断定しません。Huのsolution gapはGurobiとの費用差であり本研究のcertified MIP gapとは同一ではありません。Zhouの約0.7%は50便例で、418便の保証ではありません。Manzolliの約12%はBAUとの比較で、頑健解が名目解より必ず安いという意味ではありません。Soltanpourらは混成車両・分散電源・天候も既に扱うため、その単なる組合せを未開拓とは書きません。詳細は補足22。

出典：

- https://research.chalmers.se/en/publication/538305
- https://doi.org/10.1016/j.apenergy.2025.125714
- https://doi.org/10.1080/21680566.2025.2506689
- https://doi.org/10.1016/j.apenergy.2024.125137
- https://journals.sagepub.com/doi/10.1177/03611981221112405
- outcome/2026-09-05_literature_review/01_critical_review.md

## 9. 前回との差を研究の到達点で示す

元版の月内作業一覧を、現在の証拠が答える問いへ置き換えました。コード変更の前後を別SHAのまま性能比較することはしません。RAINのraw best boundは640000円ですがcertified best boundは695632.938124円です。両方を残し、同じStage 1 incumbent707349.173370円に対するgapの定義を説明します。最終実行日費用のgapではありません。teacher_release_statusはBLOCKEDのままです。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- docs/evidence/weather_dispatch_rerun_bb0c005/RAIN/solver_metrics.json

## 10. 同じ便を照合して違いを説明する

単に使用台数を比べず同じtrip IDを対応づけました。変更108便は渋22が78便、渋23が30便です。BEV担当便比は75.38%/34.47%ですが営業距離比は72.78%/29.73%で、便数だけでは輸送仕事量の違いを十分に表せません。営業距離は実測オドメータではなく停留所座標を結んだ推定で回送を含みません。なぜこの便が選ばれたかの因果分解は未完了です。

出典：

- outcome/2026-09-05_research_progress/analysis/summary.json
- outcome/2026-09-05_research_progress/analysis/trip_powertrain_changes.csv
- outcome/2026-09-05_research_progress/analysis/dispatch_assignments.csv

## 11. 候補図の読み方と限界

同じBEV台数を同じ配車とみなすのではなく、physical_assignment_sha256で22候補を対応づけた表を用いています。候補図は固定配車の前日recourse評価で、24/24 Rollingを通った選択計画の実行日費用とは区別します。診断表でfeasible/selectableであっても全候補のformal acceptanceを意味しません。低PVの選択698296.465284円と次点698863.087754円の差は566.622470円です。差が小さいことは安定性検証の動機で、不安定性の証明そのものではありません。大きなBEV台数で高費用になる点は総使用車両数も変わる候補であり、BEVを増やす単一介入の因果曲線ではありません。

出典：

- docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis.csv
- docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis_summary.json
- docs/evidence/weather_dispatch_rerun_bb0c005/cross_weather_fixed_dispatch_matrix.csv

## 12. 費用の比較対象を必ず言う

比較は同一の非PV入力に対して得た二つの選択済み運用です。高PV660983.7838045円、低PV698598.6286432円で差37614.8448387円です。車両使用費がたまたま両方64万円なので差額は燃料・系統・CO2で説明できますが、異なる台数の候補比較で車両使用費を落としてはいけません。設備投資、劣化、運転士等を含む実際の総運用費ではありません。費用差は入力PVの比較であり手法の優位性の比較ではありません。

出典：

- outcome/2026-09-05_research_progress/analysis/summary.json
- docs/evidence/weather_dispatch_rerun_bb0c005/SUNNY/executed_day_accounting.json
- docs/evidence/weather_dispatch_rerun_bb0c005/RAIN/executed_day_accounting.json

## 13. 電力フローの図は維持し、因果の言い過ぎを除く

PVの発電は高PV6056.25、低PV996.2 kWhです。高PVは直接110.0518、BESSへ2572.9774、抑制3373.2208 kWh。低PVは直接230.5677、BESSへ765.6323 kWhです。BESSからbusへ2322.1121/690.9831 kWh、系統から0/130.8519 kWh。BESS境界が等しいため充放電の差250.8653/74.6491 kWhはこの会計境界の損失です。bus充電後の車載電池効率とは別です。高PVなのに直接充電が少ない理由や抑制原因は、この日合計図だけでは特定できません。元版の「時間と合わず」という断定を除きました。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- outcome/2026-09-05_research_progress/analysis/executed_slots.csv

## 14. 区間電力量から平均電力へ変換する

24回Rollingで実行された各1時間のprefixを接続した96区間の値を用います。kWhの区間電力量を0.25時間で割りkWの平均電力としました。横軸は区間開始時刻、線は点を結んだ表示であり15分内の瞬時変動を測ったものではありません。高PVと低PVは同一軸です。発電・充電・抑制を重ねても帰庫状況や終端SOCによる原因分離はまだできません。BESS残量は補足21で確認できます。

出典：

- outcome/2026-09-05_research_progress/analysis/executed_slots.csv

## 15. 相関する状態を原因と呼ばない

全ポート使用は充電電力1e-6 kW超で数え、tiny powerの影響を1 kW以上という別指標でも開示しています。抑制枠末のBESS SOC最大は3644.33 kWhで、上限4800に達していません。ただし区間末の状態だけをもって設備制約が一切効かないとは言えません。車両不在か、不要な充電をしない最適行動か、PV抑制と同じ費用になる別解かを判定するには配車固定の比較や一因子変更が必要です。

出典：

- outcome/2026-09-05_research_progress/analysis/charging_and_curtailment_summary.csv
- outcome/2026-09-05_research_progress/analysis/executed_slots.csv

## 16. 弱点は次に解ける問いへ変える

最適性、安定性、単純方策への優位性は別の不足です。実行可能性の監査だけを増やしてもそれらは埋まりません。二日分のPV入力にsolver seedを増やしても天候サンプル数は増えません。入力電費と設備値の出典やSOC境界が結果へ与える影響も課題です。性能が改善しなかった場合も効果が成立しない範囲として報告します。

出典：

- outcome/2026-09-05_literature_review/02_adoption_protocol.md
- docs/research/november_2026/signoff/01_decision_sheet.md

## 17. 次の実験を勝手に開始しない

E0は既存の11月P0契約を再利用し、8/12/24便の各subsetだけを比較します。Phase 3とscalar統合目的には違いがあるため評価額差を純粋な分解誤差としません。既存M0全ICE、M1混成PV/BESSなし、M2現行Phase3、M3scalar参照は単純先着順充電baselineではありません。既存P0の安定性比較はE2ストレスとは別です。E1の方策ルールは未定義の部分があり、実装済みと書きません。安定性の実用同等閾値等も人間の承認事項です。コマンドは既存exact_execution_commands.ps1の該当コマンドを承認後に個別実行します。PS1全体を実行してはいけません。

出典：

- docs/research/november_2026/signoff/01_decision_sheet.md
- docs/research/november_2026/signoff/exact_execution_commands.ps1
- outcome/2026-09-05_literature_review/02_adoption_protocol.md

## 18. 本人の言葉で締める

30秒の要約：この研究は、固定時刻表の全便を守りながら、混成車両の担当と充電電源を組み合わせて考えます。二つの固定PV条件で違う実行可能計画が選ばれました。ですが最も安い保証や先行研究への優位性はまだありません。次に小規模統合参照と比べ、二段階法の判断を評価します。自分で答える三問は、何を固定し何を決めるか、gapは何に対する値か、どんな結果なら自分の期待が否定されるか、です。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- outcome/2026-09-05_literature_review/02_adoption_protocol.md

## 19. 数式の説明で外してはいけない点

これは実装全体を置き換える簡略モデルではなく説明用抜粋です。SはkWh、qはkWで、qに0.25時間と充電効率を掛けます。運行中・回送中・home depot不在時の充電は禁止です。Stage 1はエネルギーrecourse緩和を含む別の目的J1を用い、Stage 2は配車を固定して電力変数を選びます。車両別電源帰属の推定をsolver-nativeと主張しないため、ここではPV収支を営業所レベルで書いています。

出典：

- docs/thesis/authoring_v1/03_mathematical_formulation.md

## 20. 不足する計測値を作らない

数値はresult_summaryとsolver_metricsの記録欄をそのまま表にしたものです。solve_time_secondsはStage1+Stage2の記録値で、24回Rollingを含むエンドツーエンド時間ではありません。Stage2の記録値を22候補の総評価時間と呼びません。peak RSSは正本のper-run指標として残っておらず、約2.9GBというBFFサンプルをpeakに流用しません。最低SOC68.91kWhは214ではなく314kWh容量との比で約21.95%です。外部人間レビュー、承認、再開実験は別ゲートです。

出典：

- docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json
- docs/evidence/weather_dispatch_rerun_bb0c005/SUNNY/solver_metrics.json
- docs/evidence/weather_dispatch_rerun_bb0c005/RAIN/solver_metrics.json

## 21. SOC境界と情報条件

t=0の3000kWhに96区間末のSOCを加えた97点です。許容範囲と初期・終端条件は高低PVで一致します。残量を翌日へ持ち越す条件やhorizonを変えれば結果は変わり得ます。中野2025は2日horizon・日次更新であり、本研究の毎時更新と同じ設定ではありません。将来情報、更新間隔、予測と実績、終端条件を揃えずRollingのみの効果と解釈しないことを学びます。

出典：

- outcome/2026-09-05_research_progress/analysis/executed_slots.csv
- docs/thesis/authoring_v1/05_assumptions_parameters_units.md
- 先行文献/電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価.pdf

## 22. 参考文献の確認範囲と追加候補

本改訂は網羅的systematic reviewではなく、提供文献の再レビューと近接研究の追補です。2026-09-05にCuiのChalmers所属機関ページ、SoltanpourのSAGE要旨を確認しました。Cuiの著者公開PDFへのリンクも発見しましたが、本資料では要旨範囲の確認とし本文精読を偽りません。元版のFei、Najafi、Zhang等を否定したわけではなく、図表番号やパラメータの由来を確認せず本研究の実測根拠にしないためです。文献の長所・限界の詳細と他の23提供PDFの目録はOutcomeの文献レビューを参照してください。

出典：

- https://research.chalmers.se/en/publication/538305
- https://research.chalmers.se/publication/538305/file/538305_Fulltext.pdf
- https://journals.sagepub.com/doi/10.1177/03611981221112405
- outcome/2026-09-05_literature_review/01_critical_review.md
- outcome/2026-09-05_literature_review/source_inventory.json
