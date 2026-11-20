# 再監査レポート：研究計画改訂案（2026-11-21）の検証

**対象**：[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md)、[監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md)（非編集・非実行・コード/ログ照合に基づく査読）  
**総評**：柱B②の1,920件撤回・`rc44`投入前停止・便割当固定の導入により、致命的な計算破綻は回避された。しかし**① 便割当固定の実行経路がクラスタ規約上未実装、② ローリング窓端BEVの「前日計画SOCへの等式拘束」の放置、③ 実量制デマンド課金・CO₂逆転・`rc42`土台依存の未解消**により、まだ電気系審査員を納得させる筋は通り切っていない。

---

## 1. 前回の重大な指摘に答えているか

前回の[review_hydro.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_hydro.md#L26-L110)の重大7件および[監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md#L12-L22)の主要論点を照合した。

| 前回指摘（根拠） | 判定 | 理由と残存ギャップ |
|---|---|---|
| 1. 基本料外生と690〜768 kW高超過（`review_hydro`重大1 / まとめ#4） | **未対応** | [改訂案L54,58](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L54-L58)は実量制を2027年1月〜に先送りし、12/20原稿は注記で済ませる方針。電気系審査員は「200 kW基本料のまま690 kW受電」を実制度不成立として最初に突く。 |
| 2. LNSシード固着とICEピーク吸収主張の矛盾（重大2 / まとめ#5） | **不十分** | 実験1〜5は便固定で回避したが、12/20原稿土台の`rc42`には冬90 kWの初期解固着（22.0% vs 95.6%）が残り、`vehicle_day`有効化（実験6）は年明け送り。 |
| 3. 車両使用費98%支配・45〜51%ギャップ・24 GiB不統一（重大3 / まとめ#3） | **不十分** | 実験1〜5の便固定＋車両費除外は適切。しかし固定する`rc42`代表解が未定で、12/20土台の`rc42`自体には春±2台日（±4万円）差と200 kW夏の24 GiB例外（[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L2154-L2155)）が残る。 |
| 4. BESS在庫3,410.5 kWh未清算と`rc43`/`rc44`矛盾（重大4 / まとめ#2） | **不十分** | `rc44`停止と$v \in \{0,5,10,15,16.5\}$掃引・両建て表示（[改訂案L9-10](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L9-L10)）は妥当。だが実験1〜3の規則方式は`minimum_only`（3,000→1,200 kWh取り崩し）のまま周期境界がなく、両建ての「約17円」もCO₂込み損益分岐`17.03円`（$0.95\times 17.93$）と`17.43円`の別が未定義。 |
| 5. 中心の問い不在と総花化（重大5 / まとめ3章） | **不十分** | 1文に統合（[改訂案L16](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L16)）したが3手段の並列に留まり、12/20時点で(3)ICE振替の実験が欠けるうえ、実験1（並び順B）は問いの3介入に直接対応しない。 |
| 6. 柱B② 1,920件・12〜31日の破綻（重大6 / まとめ#11） | **対応済み** | 日次連結1,920件を明確に撤回し（[改訂案L44](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L44)）、既存週計画上の少数実験へ縮小。 |
| 7. `DIAGNOSTIC`の`rc42`を12/20原稿に流用（重大7 / まとめ助言5） | **不十分** | 便固定1図を追加（[改訂案L11](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L11)）するが、欠陥付き`rc42`を「土台」に残すため主張と限界注記が食い合う。 |
| 8. 実行層の非対称：`pv_execution.py`閉ループ vs 開ループ（まとめ#1） | **不十分** | 実験1〜3は規則のみで回避するが、最適化側の修正（実験4）は12/1〜10後回し（[改訂案L38,52](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L38-L52)）。また[改訂案L9](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L9)の`rc43`規則完走分は別版かつ比較対象がなく残す意味が薄い。 |
| 9. BEV初期SOCばらつき・毎時窓端の前日軌道固定（まとめ#6,#7） | **未対応** | 初期SOC不均一は放置し（[改訂案L29](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L29)）、まとめ#7で「未確認」のままだった窓端BEV目標が等式か下限かも調べず計画から脱落（実態は**厳密等式**、後述）。 |
| 10. 燃料費二重計上・系統CO₂逆転0.658 vs 0.580 kg/km（まとめ#8,#9） | **不十分** | 燃料費報告補正と仮値CO₂のまま先送り（[改訂案L59-60](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L59-L60)）。`executed_day_accounting.json`単一ソース原則との乖離と「買電EVがICEよりCO₂増」矛盾が未解消。 |

---

## 2. 改訂案に新しく生じた問題（重い順に8件）

1. **【最重】便割当固定のクラスタ実行経路が未実装・禁止されており、固定する代表配車の基準も未定**  
   - **根拠**：[改訂案L24,50](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24-L50)は11/22〜26で「`rc42`の便割当固定でStage 2＋ローリングのみ解く」とするが、[weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L87-L193)は`use_existing_duties=False`かつ既存配車を消去し、[cluster.py](file:///C:/master-course/bff/routers/cluster.py#L195-L196)と[scheduler.py](file:///C:/master-course/bff/services/cluster/scheduler.py#L368-L369)は`use_existing_duties=True`の投入を`ValueError`で拒否する。`phase1_charging_only`（[solver_adapter.py](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L13476-L13486)）は`fixed_assignment`か`baseline_plan`を要するが、外部`rc42`結果からクラスタへ渡す配線はない。さらに`rc42`は同季節でも上限ごとに配車・台日数が異なる（冬`eti090`: BEV 22.0%/201台日、`etb400`: 95.7%/201台日、春`etb400`: 204台日 vs `etb200`: 202台日、[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L40-L320)）のに固定元の選定基準が未定。  
   - **直し方**：`weekly_campaign.py`に外部`canonical_solver_result.json`を`simulation_config`等（[run_preparation.py](file:///C:/master-course/bff/services/run_preparation.py#L160)の`_VOLATILE_HASH_KEYS`である`dispatch_plan`はハッシュ除外されるため不可）経由でSHA検証付き固定入力として渡し、`mode="phase1_charging_only"`・`use_existing_duties=False`で`config.fixed_assignment`へ復元する経路を新設する。固定解は全上限共通で季節ごとの`400 kW`採用解（BEV約94〜96%）に事前確定し、200 kWでの実行可能性を初戦1件で確かめる。

2. **【重】`day_ahead_boundary_state`がローリング窓端BEVを前日計画SOCに厳密等式固定しており、実験2・3を歪める（実験3の罰則仕様も欠落）**  
   - **根拠**：[prepare_shibu21_24_seasonal_inputs.py](file:///C:/master-course/scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py#L409)全件が有効な`day_ahead_boundary_state`では、[reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L559-L565)が24時間先窓端の全BEV目標を前日計画軌道に設定し、[solver_adapter.py](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23182-L23205)が`tolerance_kwh = 0.0`の**厳密等式**（$E_{\text{end}} = E_{\text{day\_ahead}}$）を課す。実験3で前日計画にP10（多めの夜間充電）を作らせても、翌昼に晴れた際ローリングが窓端充電を減らせずP10軌道の拘束を引きずる。さらに実験3は「朝80%許容」と言うだけで、[bev_terminal_policy.py](file:///C:/master-course/src/optimization/common/bev_terminal_policy.py#L45-L49)が必須要求する`next_morning_shortfall_penalty_yen_per_kwh`（無指定で`ValueError`）が未定義であり、その罰則は会計外のため朝80%側が不当に安く見える。  
   - **直し方**：実験2・3でローリング適応を測るなら窓端BEV等式を外し（各朝目標＋最終翌朝目標のみ維持）、それが12/20に間に合わない場合は「前日軌道追従MPC下の前日情報比較」と明記制限する。実験3の罰則単価を事前固定し、朝未達kWhと期末SOC差換算額を必須併記する。

3. **【重】実験1（B：日射の並び順）に対象週・曜日負荷交絡・計画PV種別・POA非線形性・8日目朝の設計穴がある**  
   - **根拠**：[改訂案L35](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L35)はどの季節/週を並べ替えるか未指定。しかも対象ダイヤは平日264便・土203便・日祝181便と日別負荷が大きく異なり（[柱AまとめL16](file:///C:/master-course/outcome/2026-10-30_pillarA_summary/柱Aまとめ.md#L16)）、「晴れ→曇り」では平日が高日射、「曇り→晴れ」では土日が低/高日射に偏る交絡が起きる。さらに「7日平均」は計画PVがF0（平年値）のままなら**予報誤差ほぼゼロ**となり、実波形（誤差大）との差に予報誤差の有無が混ざる。加えて[date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L71)の`min(1, POA/1000*PR)`非線形クリップによりGHI平均とPV電力量平均は一致せず、[shibu21_monthly.py](file:///C:/master-course/tools/research/shibu21_monthly.py#L149-L152)は`forecast`/`actual_hindsight`以外の計画PVを拒否し、8日目朝（`extra_slots`）の実測PVの扱いも未定。  
   - **直し方**：対象週（例：4月`2025-04-07`か冬`2025-01-06`）とF0固定前日計画を事前宣言し、**POA変換後の15分PV出力配列を日単位で並べ替え・平均化**して週間総発電量kWhを厳密一致させ、8日目朝PVは全並びで同一固定する。「7日平均」との予報誤差分離用にF2版（200/400 kW計2本）を添えるか、平日5日のみ並べ替えた感度を確認する。

4. **【重】実験2（A：情報の価値）のF1仕様（学習年数・mean vs P50・ローリング参照・欠測有無）が未確定**  
   - **根拠**：[weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L161)参照の[manifest.json](file:///C:/master-course/output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json#L42)は**2024年単年学習**（例：冬雨10日、[training_model.json](file:///C:/master-course/output/monthly_fair_weeks_20260914/forecast_holdouts/training_model.json#L1920)）である一方、3年分の[cy2022_cy2024_20260927](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2022_cy2024_20260927/README.md#L17-L19)は30〜204日/セルを持つ。また[seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L64)は算術平均（`mean`）、[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L74)は`P50`であり不一致。評価週（3週＋8日目朝）の分類に`unresolved`（[seasonal_irradiance.py](file:///C:/master-course/src/preprocess/weather/seasonal_irradiance.py#L92-L94)）が含まれないかは未確認。さらにF1/F2時に毎時ローリングの残り窓もF1/F2に揃うのかF0(T0)のままかも未記載。  
   - **直し方**：F0・F1(P50)・P10を同一の`cy2022_cy2024`学習集合で統一生成し（F0も更新時は再計算）、2025評価週に`unresolved`が無い事前監査と、前日・毎時とも同一情報（F0/F1/F2）を使う仕様を固定する。

5. **【重】実装スケジュール（11/22〜26の5日集中）と計算時間見積もり（38件＝約13時間）の過小評価**  
   - **根拠**：[改訂案L50-53](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L50-L53)は38件を1件2時間・6並列13時間と置くが、38件中**25件が200 kW**（うちCの12件は低日射P10＋朝80%許容）である。[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L170)の毎時ローリング実測は200 kWが**1.8〜4.8時間**で、[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L1581-L2155)でも200 kW冬で時間上限29回・夏で14 GiBメモリ超過が起きている。また11/22〜26の5日間に4種の未実装改修＋回帰テストを詰め込むと、12/11〜20に原稿執筆と並行予定の実験5（`1上限×1〜2季節×3情報×5値段`＝15〜30件、系統充電可否も未指定）まで連鎖遅延する。  
   - **直し方**：11/22〜26は「便固定経路＋実験B（＋余力時A規則）」に絞り、実験Cは12/20後に回す。時間見積もりは200 kW＝3〜5時間/件で組み、実験5はまず`200 kW 冬`（15件）のみを原稿と分離して進める。

6. **【中】実験1〜3でのBESS初期在庫3,000→1,200 kWh取り崩しと、事後清算単価の基準曖昧さ**  
   - **根拠**：規則方式は[weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L164-L165)で`minimum_only`固定のため、実験1の「晴れ→曇り」と「曇り→晴れ」等で週末BESS残量$E_T$が大きく異なりうる。しかも[改訂案L10](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L10)の「約17円」はCO₂込み損益分岐`17.03円`か`17.43円`か不統一。  
   - **直し方**：実験1〜3でも事後精算の基準単価を`17.03円/kWh`（CO₂込み実効値）と`0円`の両建てに統一し、第1日の初期在庫放出に結果が左右されないかBESS初期1,200 kWhスタート等の確認を添える。

7. **【中】実験6（D：燃料バス振替）の`vehicle_day`粒度・ギャップ45%・規則BESSの残存**  
   - **根拠**：[stage1_lns.py](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L95-L100)の`vehicle_day`は1台日（平均約8〜10便）単位のLNS近傍であり、便数上限$K$制約は未実装。Stage 1を解き直せば45%ギャップと台日数±2万円段差が復活し、しかも規則BESS・外生基本料のまま（[改訂案L40](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L40)）ではICE振替価値が仮の500円/kWh罰金依存に留まる。  
   - **直し方**：Stage 1全再最適化ではなく「基準BEV配車からのBEV稼働台数上限段階下げ（または限定行路振替）」として規模を圧縮し、実験4の修正済み実行層＋内生デマンド課金上で実施する。

8. **【中】12/20原稿「`rc42`柱A土台＋対照実験1図」の2ページ構成が分裂・主張過多を招く**  
   - **根拠**：[原稿の構成.md](file:///C:/master-course/outcome/2026-12-20_ieej_manuscript/原稿の構成.md#L11-L34)の3,000字・2ページに、外生基本料・690 kW超過・LNSシード固着を抱えた`rc42`全12ケースと新対照実験1図を同居させると、前半の限界弁明に紙面が奪われ、後半の対照と問いが噛み合わない。  
   - **直し方**：`rc42`の12ケース総覧は最小限の「現状境界（400 kW未満で超過発生、冬90 kWの探索依存）」1表に圧縮し、対照実験（実験B）の因果分析を論文の主図・主結論に据える。

---

## 3. 中心の問いと実験1〜6で新規性・有用性・創造性は十分か

**結論：近接文献に対する位置づけと電気系審査員の観点からは「まだ不十分」である。**  
理由：① 実験1〜5（便固定・規則/最適化BESS）と実験6（規則BESS・Stage 1再求解）で条件が分断され、問いの「(1)予報・(2)充電/BESS・(3)ICE振替のどれがどれだけ効くか」を一つの土俵で定量比較できない。② 近接文献（[NOVELTY_AND_USEFULNESS.md](file:///C:/master-course/outcome/2026-10-05_literature_novelty/NOVELTY_AND_USEFULNESS.md#L6-L24)のL01/L03/L07/L09/L11等）に対し、実験3（P10＋朝80%）と規則下ICE振替（実験6）は既存要素の適用範囲に留まり、**新規性の核になり得るのは実験1（PV総量同一での序列ヒステリシス）と実験2・5（閉ループ統一＋$v$理論境界×情報価値）**である。③ 電気系審査員は依然として**「実量制デマンド課金（$P_{\max}$内生化）もTOU単価差もない一律17.43円下でBESS最適化やピーク削減を語るな」「系統CO₂ 0.5 kg/kWhでEVがICEよりCO₂増になる条件を放置してGXと呼ぶな」「夏季・冬季の空調電費変動がない」「日をまたぐ計画（途中の朝SOC緩和等）の検証が実験表から落ちた」**と突く。

**何を削り、何を足すか（計3点）**：
1. **【削る】実験3（C：P10＋朝80%）を12/20候補から削り、実験6のStage 1全再求解をやめる**（朝80%許容は修論の「複数日先読み＝途中の朝だけ目標緩和」実験へ吸収し、実験6は基準BEV配車からの限定台数/行路振替へ縮小）。
2. **【足す①：電気系本丸】修論フェーズ（実験5・6の前提）に「内生デマンド課金（[solver_adapter.py](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23572)の既存機構）＋TOU料金＋冬季電費+20%感度」を足す**。これにより初めてBESS最適化とICEピーク吸収が実契約・実負荷上で意味を持ち、L01/L11に対する「日本の実量制契約下の混成バスEMS」としての独自性が生まれる。
3. **【足す②：因果鎖の統合】「同一基準配車・同一モデル上での『電気側（閉ループ＋$v$＋途中朝緩和）vs 交通側（ICE振替上限 $K$）の限界超過削減・実質CO₂削減比較』」を修論の終着点に足す**。これで中心の問いが1本の相図として完結し、CO₂逆転問題も「PV協調＋適正混成のみが真のGXを生む」根拠に転化できる。

---

## 4. 12/20原稿に入れる対照実験の選択（実験1〜3から1つ）

**選択：実験1（B：日射の並び順、8件）を採る。**

- **選ぶ理由**：① [NOVELTY_AND_USEFULNESS.md](file:///C:/master-course/outcome/2026-10-05_literature_novelty/NOVELTY_AND_USEFULNESS.md#L49)が既に掴んでいる「PV総量1%差で超過・費用が大差」という実データの謎に正面から因果回答でき、「1週間合計が同じでも日別の並び（BESS飽和によるPV抑制と枯渇による買電・超過のヒステリシス）が支配する」という**電気工学・EMSとして明快で反証可能な1枚図**が作れる。② 8件と最小規模で11/27〜30に確実に終わり、2ページの限られた紙面で柱A（受電制約別の現状限界）から無理なく1本の論理で繋げられる。
- **実験2・3を採らない理由**：**実験2（A規則）**はF1の学習年数・mean/P50・事後天候オラクルの整理が未了なうえ、**規則BESSは天気予報を一切見ない**（[bess_dispatch_policy.py](file:///C:/master-course/src/optimization/common/bess_dispatch_policy.py#L38-L61)）かつローリング窓端BEVが前日軌道に等式拘束されるため、情報の価値が小さく歪みやすい（F0/F1/F2比較は実験4〜5でBESS最適化と組んで修論・次報で出すべき）。**実験3（C）**は200 kW全12件で最も重く時間切れ・メモリ落ちリスクが高いうえ、朝80%許容の会計外ペナルティとBEV窓端等式拘束が比較を歪める。
- **実験1採用の必須条件**：第2章3・6の通り、① 対象1週とF0固定前日計画の明記（＋F2版2件で予報誤差分離が望ましい）、② POA変換後のPV電力量での並び替えと8日目朝PVの同一固定、③ BESS期末残量差の`17.03円`/`0円`両建てと曜日負荷差の明記、の3点を必ず守ること。
