# 研究監査レビュー：GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化

- **査読日**：2026-11-21
- **査読対象**：修士1年（電気系）研究一式（[briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md) および参照ファイル群）
- **重点評価軸**：創造性と実行可能性（12/20 電気学会全国大会原稿目安および2028年2月修論に向けた実験設計と柱B②の見直し）

---

## 1. 一言の総評

**現状は「学術研究」ではなく、「極めて精緻な監査ゲートを備えた運用シミュレータ（デジタルツイン基盤）の構築と試運転」の段階にとどまっている。**

時刻表・気象データの来歴管理、2段階MILPと毎時175回のローリング再計画、会計照合（$10^{-6}$ 円単位）のソフトウェア工学的な完成度は修士1年として異例に高い。しかし、先生から「AIっぽい」「研究の色を」（[briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L54)）と指摘される本質的な理由は、**「どの物理的・情報的制約が、なぜ・どれだけ太陽光（PV）の利用限界と買電ピークを支配するのか」を切り分ける対照実験（Ablation / Counterfactual）と数理的洞察が欠けている点**にある。さらに現在、目的関数の97〜98%を占める車両使用費（402万〜408万円/週）とStage 1の大きな未証明ギャップ（44.8〜49.5%）のノイズの中に数万円のエネルギー費の差が埋もれており、柱B①では蓄電池（BESS）の終端価値評価が $17.43\text{ 円/kWh}$（放電損による死蔵）と $0\text{ 円/kWh}$（初期在庫の無償取り崩し）の両極端に振れ、柱B②では未実装7項目を抱えたまま1,920件のフルグリッド計算を計画して11/16開始予定の日程がすでに破綻している。**大規模な総当たり計算を即座にやめ、既存の固定配車と手元の気象資産（P10/P50/P90・2025年実績）を活かした「少数・高純度の対照実験」へ今すぐ舵を切るべきである。**

---

## 2. 指摘（重大／中／軽 の順に14件）

### 【重大（Major）】

#### 指摘1（重大）：柱B①における蓄電池（BESS）終端残量単価 $v$ の極端な振れ（17.43円→0円）と充放電効率の不整合
- **対象**：モデル・方針（柱B①のBESS目的関数と実験設定）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L34-L37)
  - [柱B_蓄電池最適化_設計.md](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L33-L47)、[同L90-L98](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L90-L98)
  - [weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L129-L138)（`"optimized": {"bess_terminal_energy_value_yen_per_kwh": 17.43}`, `"optimized_pv_cost": {"bess_terminal_energy_value_yen_per_kwh": 0.0}`）
  - [bess_terminal_value.py](file:///C:/master-course/src/optimization/common/bess_terminal_value.py#L38-L42)（目的関数項 `value * (float(asset.bess_initial_soc_kwh or 0.0) - terminal_soc_expr)`）
- **何が問題か**：
  1. rc43（400 kW・冬）で窓終端の残量単価を $v = 17.43\text{ 円/kWh}$（料金Aの電力量単価）とした結果、BESS残量が $3,000 \to 3,425\text{ kWh}$ へ積み上がる一方、買電 $7,369\text{ kWh}$・PV抑制 $6,097\text{ kWh}$ となり、参考のrc42規則方式（買電 $3,955\text{ kWh}$・PV抑制 $4,323\text{ kWh}$）より大幅に悪化した。これは放電効率 $\eta_{\text{dis}} = 0.95$ のもとでバスへ $1\text{ kWh}$ 供給するにはBESS在庫を $1/0.95 = 1.0526\text{ kWh}$ 消費するため、目的関数上の放電コストが $17.43 / 0.95 = 18.35\text{ 円/kWh}$ となり、系統買電（電力量 $17.43\text{ 円/kWh}$ ＋ CO₂評価 $0.5\text{ 円/kWh} = 17.93\text{ 円/kWh}$）より高くなるためである。さらに平年値予報（F0）では24時間窓内で確実に余剰PVで埋め戻せると見込める量しか放電しないため、実際に晴れた日に空き容量が足りずPVを大量に捨てる結果となった。
  2. これに対し、11/21の本人指示で計算中の rc44（`optimized_pv_cost`：$v = 0.0\text{ 円/kWh}$）は**逆方向の誤り**である。24時間ローリング窓の終端残量価値を $v = 0\text{ 円/kWh}$ にすると、各窓のソルバにとって窓終端にBESS在庫を残すインセンティブがゼロになる。その結果、初期在庫 $3,000\text{ kWh}$ を最初の24〜48時間で下限 $1,200\text{ kWh}$ まで使い切る（最大 $1,800\text{ kWh}$ の無償在庫取り崩し）挙動を引き起こす。週終端で取り崩し分を0円と評価すれば、初期在庫をタダで使った見かけの費用削減になり、規則方式との比較が再び歪む。
- **具体的な直し方**：
  - 放電効率 $\eta_{\text{dis}} = 0.95$ を考慮した買電代替の理論損益分岐単価は $v^* = \eta_{\text{dis}} (p_{\text{grid}} + c_{\text{CO2}}) = 0.95 \times (17.43 + 0.50) = 17.03\text{ 円/kWh}$（CO₂を除けば $0.95 \times 17.43 = 16.56\text{ 円/kWh}$）である（[柱B_蓄電池最適化_設計.md](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L90) でも $16.6\text{ 円/kWh}$ に言及しているにもかかわらず、rc44で $0\text{ 円/kWh}$ に飛んでいる）。
  - ローリング窓内で「買電よりはBESS放電をわずかに優先するが、無価値として使い捨てない」ためには、損益分岐点よりわずかに低い **$v \in [15.5, 16.5]\text{ 円/kWh}$** に設定する必要がある。
  - さらに、$v \in \{0.0, 15.5, 16.56, 17.43\}\text{ 円/kWh}$ の感度比較（400 kW冬の1ケースだけでよい）を示し、「BESS終端在庫のシャドウプライス設定が買電とPV抑制のトレードオフを制御する」という電気工学的考察へ昇華させよ。なお、最終的な週次会計比較では、計画時の $v$ によらず、週初 $E_0$ と週末 $E_T$ の在庫差 $\Delta E = E_0 - E_T$ を買電代替価値 $16.56\text{ 円/kWh}$ で同一基準精算した値を必ず併記せよ。

---

#### 指摘2（重大）：柱B②の実験規模（1,920件）と開発日程が11月21日時点で既に破綻している
- **対象**：方針（柱B②の規模・工程・計算時間見積もり）
- **根拠**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L128-L162)（未実装7項目、週計画W 240件＋日計画D 1,680件＝計1,920件）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L173-L199)（同時実行上限 `global_gurobi_slots` = 6、短縮1〜4を入れても約12日、現状のままでは約31日）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L213-L222)（11/1〜2の日計画実測：週割当切り出しでも90 kWは1日分に **2.8時間**、初期解なしでは900秒でルート緩和すら終わらずEV担当43/264便で比較不能）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L226-L235)（日程表では「11/5〜11/15 実装」「11/16ごろ固定版を作り計算開始」「12/1ごろ完了見込み」）
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L41-L43)（11/21時点で「未実装：前の日の実行結果を次の計画の初期状態に渡す連結実行、朝から始まる計画、日ごとの予報」）
- **何が問題か**：
  - 本日（2026-11-21）時点で、11/16に凍結・計算開始しているはずの柱B②のコード（連結実行、朝始まりの1日計画、予報F1/F2、対策T1/T2、短縮1〜4）が未実装であり、日程表がすでに破綻している。
  - さらに見積もり表（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L195)）は日計画Dを「1件0.5時間（短縮後）〜1時間（今のまま）」と仮定しているが、直後の8.5節の実測（[同L216](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L216)）で冬90 kWの日計画は1日 **2.8時間** かかっている。90 kW（336日分）が1日2.8時間、200 kW（336日分）が1日1.5時間かかれば、日計画1,680件だけで約1,800〜2,000時間となり、週計画920時間と合わせて6並列（`global_gurobi_slots=6`）で **約19〜21日（無停止・失敗なし前提）** を要する。
  - 「予報と対策の比較は絞らず、全組み合わせを行う」（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L157)）という方針を今から強行すれば、12/20の全国大会原稿にも年末報告にも間に合わない。
- **具体的な直し方**：
  - フルグリッド（1,920件）を直ちに撤回し、第4節に示す通り **①既存の週計画フレームワーク上で完結する「予報（F0/F1/F2）×対策（T0/T1/T2）×BESS最適化」の固定配車実験（24〜36件、6並列で半日〜1日）** と、**②修論向けの「週計画W vs 日計画D」の少数代表比較（200・400 kW×冬・夏など）** に分割・縮小せよ。

---

#### 指摘3（重大）：Stage 1（便割当）の車両使用費（総費用の97〜98%）と大きな証明ギャップ（44.8〜49.5%）により、エネルギー費用の比較が探索ノイズに埋もれている
- **対象**：モデル・結果・主張（Stage 1のギャップとエネルギー費・受電上限比較の関係）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L12-L17)、[同L26-L28](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L26-L28)、[同L58-L59](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L58-L59)
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L185-L202)（200 kW春：`total_cost` 4,149,057円、`vehicle_usage_cost` 4,040,000円、`used_vehicle_day_count` = **202**、電気代42,634円、燃料代61,078円、超過3,608円）
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L305-L320)（400 kW春：`total_cost` 4,180,747円、`vehicle_usage_cost` 4,080,000円、`used_vehicle_day_count` = **204**、電気代40,848円、燃料代58,195円、超過62円）
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L2067-L2074)（`stage1_certified_mip_gap_ratio`: 0.4632、`stage1_objective_value`: 4,172,680円、`stage1_certified_best_bound`: 2,240,000円）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L185)（Stage 1の探索時間3時間時点で中央値2.1万円・最大6.4万円、1時間時点で中央値6.3万円の差が出る）
- **何が問題か**：
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L185-L202) と [同L305-L320](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L305-L320) を照合すると、春の400 kWは春の200 kWに比べて「電気代＋燃料代＋超過罰金（基本料金除く）」では **8,215円安い**（200 kW：107,320円 vs 400 kW：99,105円）にもかかわらず、Stage 1のLNSが見つけた配車の延べ使用車両日数が **202台日 vs 204台日** と2台日（＝車両使用費 **40,000円**）違ったせいで、`total_cost` が31,691円逆転している。
  - すなわち、車両1台日あたり20,000円の離散的な段差とLNSの探索到達度のばらつき（数万円）が、太陽光・蓄電池・受電上限による純粋なエネルギー費用の差（数千円〜数万円）を覆い隠している。この状態でケースごとにStage 1を別々に解き直すと、予報や対策の優劣ではなく「たまたまStage 1で201台日を引いたか203台日を引いたか」を比較してしまう。
- **具体的な直し方**：
  1. **固定配車（Fixed-Assignment）による純粋エネルギー対照実験の導入**：予報（F0〜F2）、対策（T0〜T2）、BESS方式（規則 vs 最適化）、受電上限（200/400/900 kW）の比較では、まず**季節ごとに共通の基準便割当（例：rc42の400 kWまたは900 kWの検証済み配車）を1つ固定し、Stage 2（前日充電計画）と毎時ローリングだけを比較する実験**を主評価とせよ。これにより車両使用費と走行エネルギー需要が完全に統制され、純粋な充電・BESS・予測の効果を1円・1 kWhの狂いもなく比較でき、かつStage 1の計算時間（1件5.7時間）がゼロになる。
  2. **Stage 1下界の説明改善**：Stage 1のcertified best boundが `2,240,000円`（112台日相当：[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L2071)）にとどまるため見かけのMIPギャップが46%になっているが、実際には時刻表上、各日の同時運行ピーク便数をこなすだけで最低約200台日（約400万円）が必要である。原稿・論文では「ソルバのLP緩和下界に対するギャップ（44.8〜49.5%）」と並べて、「ダイヤ上の最小必要車両日数（約201台日＝402万円）を除いたエネルギー・運用変動費部分（約10万〜55万円）の比率」を明記し、読者に「コストが半減する余地が45%も残っている」という誤解を与えないようにせよ。

---

#### 指摘4（重大）：柱B②の「週計画 W vs 日ごとの計画 D」は、毎朝90%リセット条件の統一によって両者の本質的な差が消える設計になっている
- **対象**：モデル・方針（柱B②の問い1と終端条件設計）
- **根拠**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L8-L17)（問い1「日ごとに計画した場合と比べて、日をまたいで（1週間まとめて）計画すると、何が防げるか」）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L29-L38)（「Wの途中の朝もDと同じ条件にする（11/1本人確定）。以前の『途中の朝は下限20%のみ』は撤回。差は計画の長さと予報だけになる」）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L113)（「1日の問題は1週間より小さいので、Stage 1のギャップが小さくなりうる。Dが良く見えても、原因が『よく解けた』ことかもしれない」）
  - [reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L538)、[prepare_shibu21_24_seasonal_inputs.py](file:///C:/master-course/scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py#L407)（毎時の立て直しはWであっても `rolling_lookahead_hours=24` で24時間先までしか見ない）
- **何が問題か**：
  - 11/1の本人決定により、週計画Wの途中の朝にも日次計画Dと全く同じ「毎朝目標SOC 90%（許容80%、不足ペナルティ50円/kWh）」を課している（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L33-L37)）。
  - 超過罰金（500円/kWh）が発生しない受電上限（400 kW以上）や通常の夜間では、買電単価（17.43円/kWh）＜不足罰則（50円/kWh）であるため、WであってもDであっても**毎朝全電気バスのSOCが90%に強制リセットされる**。毎朝90%に固定され、かつ実行時の毎時ローリング窓がどちらも24時間先（`lookahead_hours=24`）であれば、日をまたいで計画する自由度は「定置用BESSの残量推移」と「90〜200 kWで超過罰金500円を避けるために朝80%へ妥協する10%幅」しか残らない。
  - その一方で、Stage 1（便割当）は7日間のWよりも1日単位のDの方が問題規模が7分の1で解きやすいため（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L113)）、このまま実行すると「エネルギー面の差はほとんど出ず、Stage 1が解きやすいDの方が車両日数が減って安くなる」という、問い1の意図と逆転した結果になる公算が大きい。
- **具体的な直し方**：
  - 「日をまたぐ計画（Multi-day Planning）の優位性」を検証したいなら、WとDで毎朝90%固定を揃えるのではなく、**「①近視眼的日次運用（毎朝一律90%を要求）」対「②複数日見通し運用（翌日・翌々日のダイヤ便数［平日264・土203・日祝181便］と天候予報［晴・曇・雨］を見通し、途中の朝は翌日の運行と昼のPV充電で間に合うならSOC 70〜80%出庫をペナルティなしで許容する）」**という比較に再定義せよ。
  - しかもこの「①毎朝90%厳守 vs ②途中の朝の目標緩和（週末朝のみ90%）」の比較であれば、未実装の「朝始まりの1日計画Dの連結実行」を作らなくても、**既存の7日間週計画Wの設定パラメータ変更だけ**で直ちに実験できる。

---

#### 指摘5（重大）：料金Aにおける基本料金（事後定数加算）と契約超過罰金（500円/kWh）のハイブリッド仮定による現実契約・物理上限との乖離
- **対象**：モデル・結果・主張（料金Aの定式化と受電上限の解釈）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L11-L12)、[同L26-L28](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L26-L28)
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L138-L176)（200 kW冬：`basic_charge_week_jpy`: 99,254円、`peak_grid_kw`: **690.0 kW**、`contract_over_limit_kwh`: **534.4 kWh**、`contract_overage_cost`: 267,203円）
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L258-L296)（400 kW冬：`basic_charge_week_jpy`: 198,508円、`peak_grid_kw`: **400.0 kW**、`contract_over_limit_kwh`: 0.0 kWh）
  - [cost_components.py](file:///C:/master-course/src/optimization/common/cost_components.py#L7)（`DEFAULT_CONTRACT_OVERAGE_PENALTY_YEN_PER_KWH = 500.0`）
- **何が問題か**：
  - 現実の高圧・特別高圧電力契約（実量制・契約電力制）では、契約電力を超えて受電すれば、その30分最大需要電力（kW）が以後1年間の契約電力（基本料金 $2,530\text{ 円/kW・月} \times 0.85$）を更新するか、受電設備定格であれば物理的に遮断（ハード上限）される。「超過した電力量（kWh）に500円/kWhを払えば、基本料金は200 kW分（週9.9万円）のままでピーク690 kWまで受電してよい」という契約は実在しない。
  - もし200 kW冬の実現ピーク $690.0\text{ kW}$ に実量制の基本料金を適用すれば、基本料金は週9.9万円ではなく週34.2万円（年1,780万円）に跳ね上がる。逆に400 kW冬はピークを $400.0\text{ kW}$ にきっちり抑え込んでいる（基本料金 週19.9万円）。
  - また、[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L265-L295) の `total_cost` フィールドには `basic_charge_week_jpy` が含まれておらず、ポスター等で事後加算されているため、JSONの `total_cost`（411.9万〜454.4万円）と [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L26) の総費用（419.9万〜457.4万円）で数値の定義が異なる。
- **具体的な直し方**：
  - 電気学会全国大会の原稿および修論では、「500円/kWhは実在の超過料金ではなく、ハード上限下で解なし（Infeasible）になることを防ぎつつ、指定受電枠（90/200/400/900 kW）からの逸脱電力量（kWh）を最小化・定量化するためのソフト制約ペナルティ係数である」と明記せよ（[RESEARCH_MEANING_AND_TEACHER_RESPONSE.md](file:///C:/master-course/outcome/2026-10-03_research_review/RESEARCH_MEANING_AND_TEACHER_RESPONSE.md#L73) の整理を徹底すること）。
  - 結果の表では、①契約超過がゼロ（または丸め誤差以下）で受電枠内に収まったケース（400 kW・900 kW、および200 kW夏）と、②受電枠を守れず大幅な超過（ピーク227〜690 kW）を起こした事実上の「受電枠不足（契約不成立）ケース」（90 kW全季節、200 kW冬・春）を明確に区別して議論せよ。

---

### 【中（Medium）】

#### 指摘6（中）：柱A・冬90 kWで「燃料バス寄りが採用された」結果は、LNSの初期解依存性による極端な2択（BEV 95.6% vs 22.0%）の産物である
- **対象**：結果・主張（柱Aの冬90 kWの解釈）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L17)、[同L27](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L27)
  - [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L18-L55)（90 kW冬・採用 `ice` start：`bev_trip_share_pct`: **22.01%**, `grid_import_kwh`: **0.0 kWh**, `pv_curtailed_kwh`: **14,931.4 kWh**, `total_co2_kg`: **7,174.5 kg**, `total_cost`: 4,543,796円 vs 不採用 `bev` start：`bev_trip_share_pct`: **95.60%**, `contract_over_limit_kwh`: 1,772.5 kWh, `contract_overage_cost`: 886,255円, `total_co2_kg`: **2,198.0 kg**, `total_cost`: 5,024,939円）
  - [stage1_lns.py](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L37-L41)（既定の `OPERATORS = ("time_window", "random_trips", "route_day")` について、「Trip-sample neighbourhoods almost never free a complete duty, so the seed's BEV/ICE split could not change (rc29: 0.5 % improvement in 1 h)」とコード内に明記されている）
- **何が問題か**：
  - 90 kW冬で採用された `ice` start 解は、系統買電が **0.0 kWh**（90 kWの受電枠を1 kWhも使っていない）であり、PV発電量24,577 kWhのうち **14,931 kWh（60.8%）を捨て**、軽油を2,738 L消費してCO₂を7.17 t排出している。
  - これは「冬90 kWではBEVを22%に減らすのが最適」なのではなく、[stage1_lns.py](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L39-L41) のLNSオペレータが初期解のBEV/ICE分担率（約95%か約22%かの両極端）をほとんど動かせないため、「95%担当で88.6万円の超過罰金を払う解」と「22%担当で買電ゼロの解」の2択しか比較できていないことが原因である。本来であれば、90 kWの受電枠を夜間・日中に使い切って超過罰金を出さない **中間のBEV担当率（たとえば60〜80%）** にずっと安い解が存在するはずである。
- **具体的な直し方**：
  - 全国大会原稿では、冬90 kWについて「BEV優先初期解（担当率95.6%）では1,773 kWhの契約超過（罰金88.6万円）が生じるため、2つの初期解のうちでは燃料バス優先初期解（担当率22.0%、買電0 kWh、燃料費51.7万円）の方がモデル総費用が低くなった。ただし中間のBEV分担率の探索は今後の課題である」と正確に記述せよ。
  - 修論に向けては、[stage1_lns.py](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L41) にすでに実装されている `"vehicle_day"` オペレータ（1日のBEV $k$ 台とICE $k$ 台の全便を同時に解放してパワートレインを入れ替える近傍）を `OPERATORS` に有効化せよ。

---

#### 指摘7（中）：毎時の立て直し（ローリング）が「平年値予報のまま固定再発行（T0）」かつ「前日計画の車載SOC軌跡に終端固定」されており、MPC本来の適応性を発揮できていない
- **対象**：モデル（毎時の立て直し `reoptimizer.py` の情報更新と終端参照）
- **根拠**：
  - [柱Aまとめ.md](file:///C:/master-course/outcome/2026-10-30_pillarA_summary/柱Aまとめ.md#L46)（`unchanged_climatology_reissued_hourly`）
  - [date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L168)（`'update_policy': 'unchanged_climatology_reissued_hourly'`）
  - [reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L530-L607)（`rolling_window_terminal_policy == "day_ahead_boundary_state"` のとき、24時間窓の終端 `boundary` における各バスの目標SOCを前日計画の `plan.vehicle_soc_kwh_by_vehicle_slot[vid][boundary]` に固定）
- **何が問題か**：
  - 現在の毎時ローリングは、1時間ごとに実測SOCを反映して解き直しているものの、①その日の残り時間のPV予測を平年値のまま一切更新せず、②24時間先の車載SOC目標も「平年値で作った前日計画の値」に固定している。そのため、朝から雨が降ってPVが全く出ていなくても、正午のローリング計画は「午後13〜16時には平年通り晴れてPVが出る」と仮定して買電を先送りし、夕方になってから夜間に買電を集中させて契約超過を引き起こす。
- **具体的な直し方**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L90) の対策T1（当日のここまでの実績と標準パターンの比による当日残り時間の予報補正・天候切替）は、この問題を直接解決する極めて有効な方策である。
  - 重要なのは、**T1は「日次計画Dの連結実行」を作らなくても、既存の週計画Wの `reoptimizer.py` にそのまま組み込める**という点である。連結実行の実装を待たず、既存の週計画W上で T0（平年値固定）vs T1（当日オンライン補正）を比較せよ。

---

#### 指摘8（中）：柱B②の対策 T3（蓄電池の予備 `bess_forecast_reserve_policy`）は現在の `minimum_only` 方針および柱B①とコード上で排他（例外終了）になっている
- **対象**：モデル・方針（柱B②の対策T3の実装可能性）
- **根拠**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L92)、[同L153](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L153)（要確認：T3を今の料金と超過の設定で使えるか）
  - [seasonal_design_contract.py](file:///C:/master-course/scripts/benchmarks/seasonal_design_contract.py#L53-L66)（54行目：`if reserve != "physical_floor_only" and (policy != "return_to_initial" or rolling != "scenario"): raise ValueError("BESS forecast reserve requires the retained evaluation return_to_initial target")`、59行目：`pv_self_consumption` でも拒否、65行目：`bess_terminal_energy_value_yen_per_kwh > 0` でも `minimum_only` 必須のため排他）
  - [bess_reserve_policy.py](file:///C:/master-course/src/optimization/common/bess_reserve_policy.py#L44-L55)
- **何が問題か**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L153) で「要確認」とされていたT3（`evaluation_target_zero_pv` 等）をコード上で確認すると、`bess_terminal_soc_policy == "return_to_initial"`（週末に初期残量3,000 kWhへ戻す等式制約）が前提となっており、現在の `minimum_only`（下限1,200 kWhのみ＋残量単価評価）と組み合わせると `ValueError` で即座に拒否される。
  - また9/19〜9/21の記録（[柱B_蓄電池最適化_設計.md](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L18-L19)、[CURRENT_RESEARCH_RELEASE_BLOCKERS.md](file:///C:/master-course/docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md#L143)）の通り、`evaluation_target_zero_pv` は「初期残量3,000 kWhを常に予備として守る」ため、初期3,000 kWhから始まると蓄電池を放電できなくなる欠陥があった。
- **具体的な直し方**：
  - 柱B②から対策T3（`evaluation_target_zero_pv`）を削除せよ。
  - すでに [pv_execution_reserve.py](file:///C:/master-course/src/optimization/milp/pv_execution_reserve.py#L112-L128) によって「各実行1時間の放電はその時間の開始時BESS残量から下限1,200 kWhまでしか出せない（未観測の同時間PVを当てにしない）」という物理保護は常時有効になっている（rc43でもこれを使って完走している）。

---

#### 指摘9（中）：予報 F1（天候つき標準パターン）の定義とコード実装（平均 vs P50、事後実績分類オラクル）の不整合
- **対象**：モデル・方針（柱B②の予報F1・対策T2）
- **根拠**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L74-L78)（F1：翌日の天候が天気予報で分かるとして、その天候の **P50** 曲線を使う。F1の天候は2025年の実績を同じ分類規則で分類したもの）
  - [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L63-L71)、[同L83-L108](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L83-L108)（`fit_climatology_proxy` と `predict_climatology_ghi` はP50ではなくクラス内の **算術平均 `fmean`** から減衰率を計算し、`known_weather_class` 指定時は `'known_class_oracle_reference'` とラベル付けしている）
  - [seasonal_irradiance.py](file:///C:/master-course/src/preprocess/weather/seasonal_irradiance.py#L163-L165)、[同L199](file:///C:/master-course/src/preprocess/weather/seasonal_irradiance.py#L199)（`'Pointwise empirical quantiles are not calibrated forecast intervals.'`）
- **何が問題か**：
  1. [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L74) ではF1を「P50曲線」としているが、既存の予測生成コード [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L64) は算術平均（mean）で組まれている。
  2. F1は2025年の評価日の実績GHIと降水量から事後判定した天候ラベル（晴・曇・雨）を参照するため、実際の天気予報ではなく「天候クラス完全予知オラクル（Oracle Weather-Class Reference）」である。
- **具体的な直し方**：
  - F1に `seasonal_curves.json` の `p50` を使うのか `mean` を使うのかを統一せよ（P10のT2と対比するなら、同じ `seasonal_curves.json` の `p50` と `p10` を `poa_from_ghi` で30度傾斜面変換して使うのが一貫する）。
  - 論文・原稿ではF1を「実際に出された天気予報」と曖昧に呼ばず、「天候クラス（晴・曇・雨の3区分）のみが既知である条件付き参照予測」と明記し、F0（無条件気候値）→ F1（天候クラス既知）→ F2（15分波形完全既知）の**段階的な情報価値（Value of Information）の分解**として位置づけよ。

---

#### 指摘10（中）：毎朝のSOC不足ペナルティ（50円/kWh）がStage 1とStage 2で非対称であり、かつ会計外のため比較にバイアスを生む
- **対象**：モデル（翌朝SOC目標の許容幅とペナルティ設計）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L18)
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L36-L37)（「単価は電気代30円/kWhより高い50円/kWh。費用の集計には入れず、`stage2_objective` からも除いて別に記録する。Stage 1には罰則を入れない（下限80%だけを課す）ので、便の割当は不足分の罰則を見ない」）
- **何が問題か**：
  - Stage 1は「毎朝80%でよい（ペナルティ0円）」としてBEVに便を割り当てる一方、Stage 2とローリングは「90%未満には50円/kWh（料金Aの買電17.43円の約2.9倍）の罰則がかかる」として90%まで充電しようとする。
  - また、50円/kWhのペナルティは会計（`executed_day_accounting.json`）から除外されるため、もしあるケースが朝80%で出庫して夜間の買電や契約超過を回避した場合、朝90%まで充電したケースより「会計上の費用が安く」見えてしまう。
- **具体的な直し方**：
  - 許容幅（80〜90%）を使う実験では、結果表に必ず「朝の90%目標に対する累積未達電力量（kWh）」と「週終端（翌週月曜朝）の車載電池総残量差（kWh）」を併記し、未達のまま終えた電力量を買電単価で補正してもなお優位かどうかを確認せよ。

---

#### 指摘11（中）：季節比較における「電費一定（1.316 kWh/km）」の限界に対し、既存コードの電費感度機能と気温データが未活用である
- **対象**：モデル・主張（季節比較の妥当性と感度分析）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L13)、[同L60](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L60)
  - [NOVELTY_AND_USEFULNESS.md](file:///C:/master-course/outcome/2026-10-05_literature_novelty/NOVELTY_AND_USEFULNESS.md#L22-L23)（近接文献 L04, L07, L09 はいずれも気温による電費変化を考慮）
  - [simulation_builder.py](file:///C:/master-course/bff/services/simulation_builder.py#L543-L548)（`bev_trip_energy_sensitivity_scale` がすでに実装されている）
  - [training_cy2024/manifest.json](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/training_cy2024/manifest.json#L36)（Solcastデータには15分ごとの `air_temp` が含まれている）
- **何が問題か**：
  - 先行研究（Hendriks & Sturmberg 2024, Nath et al. 2025/2026, J. Liu et al. 2026）がすべて気温・空調による季節電費変動を扱っている中、電費を通年 $1.316\text{ kWh/km}$ 固定にしたまま「季節比較」を主張すると、査読者から「実質的に太陽光発電量の大小を比べているだけで、冬季暖房や夏季冷房による需要側の季節変動が抜けている」と批判される。
- **具体的な直し方**：
  - 全国大会原稿では「発電側の季節変動の影響を純粋に分離するため、走行電費は $1.316\text{ kWh/km}$ に統制した」と実験統制として明記せよ。
  - 修論（または全国大会の追加考察）では、既存の `bev_trip_energy_sensitivity_scale` を $1.20$（冬季暖房・猛暑冷房による電費 $+20\%$ 悪化想定）に設定した感度ケースを冬の200 kW・400 kWで2〜4件だけ実行し、「冬季に日射減と電費悪化が重なると必要契約電力や燃料バス併用率がどう変化するか」を示せ。コード改修ゼロで実行できる。

---

### 【軽（Minor）】

#### 指摘12（軽）：柱B②の受電上限（90/200/400/600/800 kW）と柱A・柱B①（90/200/400/900 kW）の不一致
- **対象**：方針（柱B②の受電上限設定）
- **根拠**：
  - [briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L11)（柱A・rc42：90/200/400/900 kW）
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L23)（柱B②：90/200/400/600/800 kW、600 kWは新規作成）
- **何が問題か**：
  - 400 kW以上で契約超過がほぼゼロ（400 kW春で $0.124\text{ kWh}$ のみ、冬・夏は $0\text{ kWh}$：[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L270-L350)）になることが判明しているにもかかわらず、柱B②で600 kWを新設して5水準に増やし、かつ最大値を800 kWに変えると、柱A（rc42）や柱B①（rc43/rc44）と直接比較できなくなる上、計算量が25%増える。
- **具体的な直し方**：
  - 600 kWと800 kWをやめ、柱A・柱B①と同じ水準から **`200 kW`（超過が出る境界）と `400 kW`（超過が消える目安）の2水準（必要に応じて `90 kW` を加えた3水準）** に絞れ。

---

#### 指摘13（軽）：柱B②の冬の慣らし週（2024-12-30開始）は、データリーク防止ガードによりコード上で例外停止する
- **対象**：方針・モデル（柱B②の慣らし週設定）
- **根拠**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L50-L58)（冬の慣らし週：2024-12-30〜2025-01-05）
  - [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L88-L90)（`cutoff = datetime.fromisoformat(model['training_end_exclusive']).replace(tzinfo=JST); if issued_at < cutoff or any(stamp < issued_at for stamp in valid_starts): raise ValueError('Forecast uses training data or valid times unavailable at issuance')`）
  - [output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json](file:///C:/master-course/output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json#L40-L41)（`"training_end_exclusive": "2025-01-01"`）
- **何が問題か**：
  - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L58) では「予報が実績寄りになりうるが評価週は2025年なので影響しない」と軽く書かれているが、実際のコード [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L89-L90) は `2025-01-01` より前の日付（2024-12-30〜12-31）に対する予測発行を `ValueError` でハードに拒否する。また年末年始（12/30〜1/3）は特別休日ダイヤが連続するため、通常週の慣らしとしても不適切である。
- **具体的な直し方**：
  - 毎朝車載電池が90%（許容80%）に戻る設定では、1週間の慣らしが2週目に引き継ぐ情報は実質的に「月曜朝のBESS残量（1変数）」しかない。計算時間を2倍に増やし、かつ訓練・評価分離ガードに抵触する慣らし週（1週目）は全面的にやめ、評価週（1週）の初期BESS残量感度（例：3,000 kWh vs 1,200 kWh）を少数ケースで確認する方式に改めよ。

---

#### 指摘14（軽）：電気学会全国大会2ページ原稿における図表の重複と、車両使用費（98%）による視認性低下
- **対象**：方針・主張（全国大会原稿の構成案）
- **根拠**：
  - [原稿の構成.md](file:///C:/master-course/outcome/2026-12-20_ieej_manuscript/原稿の構成.md#L11-L17)（A4・2ページ、2段組、段幅83.5 mm、白黒印刷）
  - [原稿の構成.md](file:///C:/master-course/outcome/2026-12-20_ieej_manuscript/原稿の構成.md#L32)（「4. 結果 約30%：電気バスの担当便、総費用（表2）、費用の内訳（図2、総費用が400万円台であることを明記）」）
- **何が問題か**：
  - 約3,000字・2ページの原稿で、同じ12ケースの費用を表2と図2の両方に載せるのは紙面の重複である。また図2の棒グラフに約404万円の車両使用費を含めると、白黒83.5 mm幅の中では電気代（3万〜7万円）や燃料代（3万〜6万円）の差が1 mm以下の線になって潰れる。
- **具体的な直し方**：
  - 図2は**「車両使用費を除いたエネルギー・電力関連費用（従量電気代・燃料代・契約基本料金・超過ペナルティ）の積み上げ棒グラフ」**とし、キャプションに「※別途、車両使用費402〜408万円/週（201〜204台日）が加わる」と明記せよ。
  - 表2は費用表ではなく、**「物理・環境指標および情報/BESS対照結果（BEV担当率、買電量、ピーク電力、超過電力量、PV自家消費量・抑制量、BESS終端残量、CO₂排出量）」**の表とすることで、2ページの情報密度を最大化せよ。

---

## 3. 新規性・有用性・創造性を高める具体案（4件）

今ある資源（計算機11台・Gurobi同時6枠、2022〜2024年季節×天候別日射曲線 P10/P50/P90、2025年Solcast実績、毎時ローリング機構、検証済みrc42固定配車）を最大限に活かし、**最小の実装・計算量で「本当に研究らしい研究」に化ける4案**を提案する。

---

### 案1：【12/20全国大会の目玉に推奨】固定配車下での「気象情報の段階的価値（Value of Information）」と「蓄電池最適化」の相乗効果の解明
- **問い（1文）**：太陽光・定置蓄電池を併設した電気バス営業所において、予測情報を「①平年値（F0）→ ②翌日天候3区分（F1）→ ③当日毎時の実績比オンライン補正（T1）→ ④15分波形完全予知（F2）」と高度化したとき、買電量・契約超過・PV抑制はどこまで減り、BESSの最適化はどの情報段階から規則方式（自家消費優先）を上回るか？
- **何が新しいか（近接文献との違い）**：
  - 近接文献 [Zaneti et al., 2022 (L01)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L7) や [Ji et al., 2026 (L08)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L14) は単一の予測モデルや強化学習による動的充電を提案しているが、**「どの粒度の気象情報（天候クラス vs 時間帯波形 vs 当日オンライン観測）が、BESSの先行放電（朝に空きを作って昼のPVを吸う動き）を成立させる必要十分条件か」**を分離・定量化した研究はない。
  - とくに柱B①のrc43で「平年値予報（F0）のままではBESS最適化が規則方式に勝てない」（[柱B_蓄電池最適化_設計.md](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L45)、[同L95-L97](file:///C:/master-course/outcome/2026-11-20_pillarB_bess/柱B_蓄電池最適化_設計.md#L95-L97)）という重要な現象がすでに見えている。これを「情報（F0/F1/F2）×制御（規則/BESS最適化）」の $3 \times 2$ マトリクスとして提示すれば、なぜF0ではダメでF1なら効くのかが一目で分かる。
- **誰に役立つか**：
  - バス事業者および営業所EMS開発者。「高価な15分日射予測サービスを購入しなくても、無料の翌日天気予報（晴/曇/雨）と当日の発電実績フィードバックだけで、完全予知（F2）の何%の経済・ピーク削減効果を達成できるか」の設計指針になる。
- **必要な実装と計算の量**：
  - **実装（約1〜2日）**：日次連結実行は**不要**。既存の週計画（`weekly_campaign.py`）上で、Stage 1の配車をrc42の検証済み解に固定する。F0（`forecast`）とF2（`actual_hindsight`：[prepare_shibu21_24_seasonal_inputs.py](file:///C:/master-course/scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py#L363) に実装済み）はすぐ動く。F1も [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L84) の `known_weather_class` に2025年各日の天候ラベルを渡すだけで動く。BESS最適化の終端単価は損益分岐点を踏まえた $v = 16.0\text{ 円/kWh}$ に修正する。
  - **計算量**：3季節（冬・春・夏）× 2上限（200 kW・400 kW）× 3情報（F0, F1, F2）× 2制御（規則 `rule`, 最適化 `optimized`）＝ **36件**（冬・春の2週に絞れば **24件**）。Stage 1が0秒、Stage 2＋ローリング（10分制限）は1件あたり約1.5〜2.0時間（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L169-L179) 実測根拠）。総計約60ソルバ時間 ÷ 6並列（`global_gurobi_slots=6`）＝ **約10〜12時間（半日）** で完了する。
- **12/20 と修論のどちらに向くか**：
  - **12/20の全国大会原稿に直結**し、さらにT1（毎時オンライン補正）を加えた完全版が修論の主章になる。
- **失敗したときに何が言えるか**：
  - もしF1やF2を与えてもBESS最適化と規則方式の差が小さければ、**「電気バス35台（日中の帰庫便が常時存在する運用）に対してPV 1,000 kW・BESS実効3,600 kWhの設備条件では、予測連動の複雑なBESS充放電計画を組まなくとも、因果的な自家消費優先ルール（Rule-based EMS）だけで完全予知下の95%以上の性能に到達できる」**という、実務導入を強く後押しする「簡易制御の十分性定理」として報告できる。

---

### 案2：【12/20にも修論にも有効】「PV総量パラドックス」の解明と、時刻表構造が決める「営業所の太陽光受入限界（Solar Acceptance Envelope）」の定式化
- **問い（1文）**：週間PV発電総量がほぼ等しい週（例：4月 26,357 kWh vs 5月 26,639 kWh、差1.07%）で買電量と契約超過が大きく乖離するのはなぜか、また「日射の時系列順序（曇→晴 vs 晴→曇）」と「バス時刻表の日中在庫台数・夜間充電窓」は営業所の太陽光吸収限界をどう規定するか？
- **何が新しいか（近接文献との違い）**：
  - [Liu et al., 2024 (L03)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L9) や [Dumoulin et al., 2026 (L10)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L16) はPVと充電需要の時間整合を論じているが、本研究が発見した「4月と5月でPV総量が1%しか違わないのに買電量が1,633→3,513 kWh（2.15倍）、超過費用が2.2万→54.7万円へ急増する」（[RESEARCH_MEANING_AND_TEACHER_RESPONSE.md](file:///C:/master-course/outcome/2026-10-03_research_review/RESEARCH_MEANING_AND_TEACHER_RESPONSE.md#L29-L38)）という現象を、**「時刻表と初期在庫を完全固定したまま、7日間の日射曲線の並び順（Sequence）だけを入れ替える反事実実験（Sequence Counterfactual）」**で因果証明した研究はない。
  - これは [AGENTS.md](file:///C:/master-course/AGENTS.md#L64-L66) の反事実実験契約（ダイヤ・車両・初期SOC・設備・ソルバ制御を完全固定し、ハッシュ化したPV曲線のみを変える）に100%合致する最もクリーンな実験設計である。
- **誰に役立つか**：
  - バス事業者・蓄電池設計者。「週間・月間の平均日射量」でPV・BESS容量を設計すると失敗すること、特に「低日射日の翌朝出庫に必要な買電ピーク」と「高日射日の連続によるBESS飽和（PV抑制）」という**非対称な記憶効果（ヒステリシス）**を見積もるための定量指標を提供する。
- **必要な実装と計算の量**：
  - **実装（半日）**：
    1. 既存結果JSONから15分ごとの「在庫BEV台数・空き車載容量・空き充電器数・BESS空き容量」を重ねてPV抑制の原因（①バス不在、②充電器10口飽和、③BESS上限4,800 kWh飽和）を分類する集計スクリプト（新規ソルバ計算ゼロ）。
    2. 1つの代表週（冬または春・5月）の7日間の実測PV曲線の「日次の並び順」を入れ替えた入力（例：①実際の並び、②晴天日と雨天日を逆順にした並び、③7日間平均波形を毎日繰り返した並び）を作るスクリプト。
  - **計算量**：固定配車（Stage 1は0秒）× 受電上限2水準（200・400 kW）× 並び順3〜4通り ＝ **6〜8件**。1件約1.5〜2時間 × 8件 ＝ 6並列で **約2〜3時間** で完了する。
- **12/20 と修論のどちらに向くか**：
  - **12/20の全国大会原稿および修論の両方に向く**。わずか3時間の計算で「AIっぽくない、物理と数理の筋が通ったグラフ」が1枚手に入る。
- **失敗したときに何が言えるか**：
  - すでに4月と5月の実データで2.15倍の買電量差が確認されているため空振りのリスクは極めて低い。もし「7日間平均波形」と「実波形」の差が大きければ、それ自体が「平均気象シナリオで設備計画を行う先行研究（[Nath et al., 2025/2026 (L07)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L13) 等）は買電とPV抑制を過小評価する」という強力な学術的批判になる。

---

### 案3：【12/20〜年末に有効】「日射分位点（P10悲観曲線）による慎重計画」と「翌朝SOC目標の柔軟化（90%→80%）」による200 kW契約成立化
- **問い（1文）**：前日計画において天候別P10曲線（低日射想定）を用いて夜間買電を先行平準化する方策（T2）と、翌朝の出庫SOC目標を90%から80%まで柔軟化する方策を組み合わせることで、定置蓄電池を増設せずに受電上限200 kWでの契約超過をどこまでゼロに近づけられるか？
- **何が新しいか（近接文献との違い）**：
  - [Hendriks & Sturmberg, 2024 (L04)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L10) 等は終端SOCを90%に固定している。本研究は手元の2022〜2024年データから構築済みの **P10 / P50 / P90 分位点曲線**（[seasonal_irradiance.py](file:///C:/master-course/src/preprocess/weather/seasonal_irradiance.py#L164)）と、実装済みの翌朝SOC許容幅（[weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L142)）を用い、「気象側の安全余裕（P10予測）」と「交通運用側の安全余裕の緩和（朝80%許容）」という**電力×交通の双方向バッファの代替関係**を定量化する点が新しい。
- **誰に役立つか**：
  - バス事業者・配電事業者。受電契約を400 kWから200 kWに下げられれば、基本料金だけで週9.9万円（年約516万円：[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L175)、[同L295](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L295)）を削減でき、系統側の変圧器増強を回避できる。
- **必要な実装と計算の量**：
  - **実装（半日）**：日次連結実行は**不要**。既存の週計画（W）で、前日計画のPV曲線として `seasonal_curves.json` の P10 / P50 を選ぶオプションと、既存の `morning_tolerance_percent=10.0` を有効化するだけ。
  - **計算量**：200 kW（冬・春・夏の3週、固定配車）× 4設定（①P50+朝90%厳守、②P10+朝90%厳守、③P50+朝80%許容、④P10+朝80%許容）＝ **12件**。Stage 1は固定（0秒）、Stage 2＋ローリング（10分制限）で1件約2時間 → 6並列で **約4時間**。
- **12/20 と修論のどちらに向くか**：
  - **12/20の全国大会（または年末報告）と修論の両方に向く**。柱B②でやりたかった「予報が外れたときの対策（T2・朝の許容幅）」の核心を、1,920件ではなく12件（4時間）で検証できる。
- **失敗したときに何が言えるか**：
  - 晴れた日にP10で計画すると夜間買電が増えて昼のPV抑制が増えるため、「超過削減量（kW / kWh）と引き換えに増加するPV抑制量（kWh）のパレートトレードオフ（保険料コスト）」として定量化できる。また冬の200 kWでどうしても超過が消えなければ、「BEV 35台（95%担当）の冬ダイヤでは200 kWは制御によらず物理容量不足である」という設備下界の証明になる。

---

### 案4：【修論の主軸に推奨】混成フリート（電気35台・燃料25台）における「受電制約・冬季電費悪化時の最適電化率とディーゼル・ピークシェービング価値」
- **問い（1文）**：受電上限が厳しい（90〜200 kW）営業所や冬季の低日射・暖房電費悪化（$+20\%$）時において、全便の95%を電気バスに固定するよりも、低日射日やピーク日だけ燃料バス（ICE）の分担率を戦略的に15〜30%へ引き上げることは、受電基本料金・超過リスクとCO₂削減のパレートフロントをどう改善するか？
- **何が新しいか（近接文献との違い）**：
  - 研究題目に「**燃料バスと併用する電気バス**」（[briefing.md](file:///C:/master-course/outcome/2026-11-21_research_audit/briefing.md#L3)）と掲げながら、現状はBEV担当率が約95%でほぼ一定（または冬90 kWで22%に極端化）しており、混成フリート本来の強みが分析されていない。
  - [Bazarnovi et al., 2026 (L11)](file:///C:/master-course/outcome/2026-10-05_literature_novelty/literature_matrix.md#L17) は混成バスの日次計画を扱うが、PV・BESS・受電契約上限のもとで**「燃料バスを電力系統のピークカット資源（ディーゼル・バックアップによる受電設備容量の節約手段）として評価する」**視点は電気工学×交通工学の境界領域ならではの独自性を持つ。
- **誰に役立つか**：
  - バス事業者およびGX補助金制度の設計者。「100%電化のために受電設備を900 kWへ増強する投資」と「受電設備を200 kWに抑え、冬季や雨天の数%〜十数%の便だけ燃料バスを残す段階的GX移行」の費用対効果（1 t-CO₂削減あたりの限界費用）を比較できる。
- **必要な実装と計算の量**：
  - **実装（1〜2日）**：[stage1_lns.py](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L41) にすでに実装済みの `"vehicle_day"` オペレータを有効化し、[simulation_builder.py](file:///C:/master-course/bff/services/simulation_builder.py#L546) の `bev_trip_energy_sensitivity_scale`（1.0倍 vs 1.20倍）および稼働BEV台数上限（20, 25, 30, 35台）を振る。
  - **計算量**：冬・90 kWおよび200 kW × 電費2通り（1.0, 1.2）× BEV台数4通り ＝ **16件**（Stage 1込みで1件約4時間 → 6並列で約11時間）。
- **12/20 と修論のどちらに向くか**：
  - **修論（2028年2月）および次回の部門大会・論文誌投稿の主軸**に向く。
- **失敗したときに何が言えるか**：
  - もし燃料バスを少し混ぜるだけで200 kWや90 kWの契約超過が完全に消えれば「混成フリートのピークカット価値」が実証され、逆にどれだけ混ぜてもコストが高いなら「燃料費150円/Lのもとでは燃料バス温存よりも受電設備を400 kWへ増強する方が経済合理的である」という明確な設備投資結論が得られる。

---

## 4. 今の計画（柱B①・柱B②・原稿）で、やめる・絞る・順序を変えるべきもの

設計書（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L155-L235)）の実測値とコードの実装状況に基づき、計画を以下の通り抜本的に再編する。

### 4.1 やめるべきもの（4点）

1. **柱B①の「BESS終端残量単価 $v = 0\text{ 円/kWh}$（`optimized_pv_cost`）」を正式比較の主軸にすること**
   - **理由**：指摘1の通り、ローリング窓終端の残量価値を0円にすると、初期在庫 $3,000\text{ kWh}$ を無償の電気として週前半に下限 $1,200\text{ kWh}$ まで使い切る挙動になり、規則方式との公平な比較にならない。rc44は挙動確認（診断）にとどめ、本比較は往復・放電効率を考慮した適正単価（$v = 16.0\sim 16.5\text{ 円/kWh}$）で行うこと。
2. **柱B②の「1,920件フルグリッド計算（週240件＋日1,680件）」**
   - **理由**：指摘2の通り、実測値（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L168-L170)、[同L216](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L216) の冬90 kW日計画＝1日2.8時間）を当てはめると、短縮を入れてもGurobi同時6枠で18〜25日以上かかり、年内に集計まで終わらない。
3. **柱B②の「慣らし週（1週目）」と「600 kW・800 kWシナリオ」と「対策T3（旧 `evaluation_target_zero_pv`）」**
   - **理由**：
     - 慣らし週は計算量を2倍にする上、冬の慣らし週（2024-12-30開始）は [seasonal_forecast_proxy.py](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L88-L90) のデータリーク防止ガード（`training_end_exclusive = 2025-01-01`）で `ValueError` となり動かない（指摘13）。
     - 400 kW以上で超過が消えるため600 kW・800 kWは冗長であり、柱A・柱B①の `90/200/400/900 kW` と不整合を起こす（指摘12）。
     - 対策T3（`evaluation_target_zero_pv`）は `return_to_initial` 専用であり、現在の `minimum_only` 設定では [seasonal_design_contract.py](file:///C:/master-course/scripts/benchmarks/seasonal_design_contract.py#L54) で `ValueError` となる（指摘8）。
4. **12/20の前に「朝から始まる1日計画Dの連結実行」を新規開発すること**
   - **理由**：[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L149) にある通り、00:00始まり前提の `simulation_builder.py` を朝（始発時刻、曜日ごとに異なる）始まりに改修し、便の重なりや状態引き継ぎの回帰テストを通すには最低1〜2週間の実装・デバッグ期間を要する。12/20の全国大会原稿の前にこれに手をつけると共倒れになる。

---

### 4.2 絞るべきもの（3点）

1. **Stage 1（便割当）の再計算を絞り、「固定配車（Fixed-Assignment）比較」を標準にする**
   - 設計書8.2節の「Stage 1の引き継ぎ（5.5時間→1時間）」（[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L181-L187)）よりもさらに踏み込み、予報（F0/F1/F2）・対策（T0/T1/T2）・BESS方式（規則/最適化）の比較では **rc42の検証済み便割当をそのまま固定（Stage 1計算時間＝0時間）** してStage 2＋毎時ローリングだけを解く。これにより1件あたりの計算時間が **11.7時間 → 約1.5〜2.0時間（約6分の1）** に激減し、かつ車両使用費（2万円/台日の段差ノイズ）が完全に排除される。
2. **毎時ローリングの制限時間は直ちに「1時間→10分（600秒）」へ絞る**
   - [柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L179) の実測分析（10分を超えた74回中70回で解が同一、12件で53時間短縮）は極めて確かな根拠がある。前日Stage 2（600〜1,800秒）と毎時ローリング（600秒）の設定分離だけ今すぐ入れよ。
3. **受電上限は `200 kW`（制約が効く領域）と `400 kW`（制約が緩和される領域）の2水準を中心に絞る**
   - 90 kWはローリング計算時間が突出して長い（1件19〜24時間：[柱B設計.md](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L170)）ため、主実験は200 kW・400 kW（必要なら900 kW）で回し、90 kWは最後に代表ケースのみ確認する。

---

### 4.3 順序を変えるべきもの：実測値に基づく12/20および修論への新ロードマップ

今の計画は「柱B①（平年値F0のままBESS最適化）→ 全国大会原稿（柱Aのみ）→ 柱B②（日次連結と予報F1/F2を年末に同時実装）」という順序になっているが、**「F1（天候つき予報）がないから柱B①のBESS最適化がうまく動かない」**という因果関係があるため、**柱B②の「予報（F1/F2）と対策（T1/T2）」だけを先に切り出して、既存の週計画Wと柱B①に合流させる順序**に変えるべきである。

#### 【フェーズ1：11/22〜11/28（中間発表まで）】計算時間約12時間（6並列で半日）
- **やること**：
  1. 柱B①のBESS終端残量単価を $v = 16.0\text{ 円/kWh}$（または $16.5\text{ 円/kWh}$）に修正し、冬400 kWの1件で「朝に放電して昼の余剰PVを吸う」挙動と会計整合を確認する（約1.5時間）。
  2. 既存の週計画W（固定配車）に、すでにコードにある F2（`actual_hindsight`）と F1（`known_weather_class` による天候別標準パターン）を入力し、**案1（F0/F1/F2 × 規則/BESS最適化）の24〜36件**を中間発表の裏で計算機6並列で回す（36件 × 約1.8時間 ÷ 6並列 ＝ **約11時間**）。

#### 【フェーズ2：11/29〜12/10（全国大会原稿のデータ確定）】計算時間約7時間（6並列で半日）
- **やること**：
  1. **案2（日射順序の入れ替え反事実実験：6〜8件、6並列で約2.5時間）** と **案3（P10慎重計画＋翌朝SOC 80%許容：12件、6並列で約4時間）** を既存の週計画W（固定配車）で実行する。
  2. この時点で、**一切の「日次連結実行」を作ることなく、わずか合計約18時間（1日未満）のクラスタ計算で、柱A＋柱B①＋柱B②の後半（予報と対策）の最も美味しい結果がすべて揃う。**

#### 【フェーズ3：12/11〜12/20（電気学会全国大会2ページ原稿の完成）】
- **やること**：
  - 占部先生に「①柱A（受電上限4通り×3季節の基礎評価）」に加えて、「②案1・案2（なぜPV総量だけでは費用が決まらないのか、天候予報F1とBESS最適化を組み合わせると買電とPV抑制がどれだけ改善するか）」まで含めた2ページ原稿を提示する。これにより「ただ計算機を回しただけの報告」から「明確な問いと対照実験を持つ電気工学の研究論文」へ劇的に質が上がる。

#### 【フェーズ4：2027年1月〜修論（2028年2月）】
- **やること**：
  1. まず既存の7日間週計画Wの中で「毎朝SOC 90%厳守（近視眼的日次目標）」vs「途中の朝は翌日ダイヤ・天候に応じてSOC目標を緩和する複数日適応運用」を比較する（指摘4）。
  2. その上で、本当に1日単位の再配車が必要かを見極めたうえで日次連結実行（D）および **案4（混成フリートのBEV/ICE最適分担フロンティアと冬季暖房電費 $+20\%$ 感度分析）** を実装・実行し、修論の題目「GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化」を完結させる。
