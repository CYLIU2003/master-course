// Layout of the midterm poster after the advisor's comments of 2026-11-12 (included by build_poster_rc33.js).
// Order: 1 goal and my work, 2 method (what is optimized, objective, parameters), 3 case study,
// 4 results (bar charts of trip share and cost, the two initial assignments), 5 discussion, outlook, road to the final.
// "2つの出発点" is no longer used (it reads as a bus route's starting point): the two Stage 1 seeds are
// "電気バス優先の初期割当" and "燃料バス優先の初期割当".
module.exports = function layout(c) {
  const { s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    cases, LIMITS, SE, SEASON_OF, lab, val, pairOf, iceWins, bevWins, rngTxt, man, fmt, pb90, pi90, eqSize, maxTimeouts, versions } = c;
  const NUM = 7.87;
  text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M, w: W - NUM, h: 2.5, fontSize: 68, bold: true, valign: "middle" });
  text("東京都市大学　劉 承洋（研究室名・指導教員をここに記入）", { x: M + NUM, y: M + 2.55, w: W - NUM, h: 0.8, fontSize: 36, color: SUB });
  s.addShape(pres.shapes.LINE, { x: M, y: 8.8, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const p9b = pairOf(900, "2025-01-06", "bev"), p9i = pairOf(900, "2025-01-06", "ice");
  const tc = (r) => r.total_cost_reported; // CO2 cost excluded from every reported total (2026-11-16)
  const wCut = Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100);
  text(`概要　路線バスの電動化では、営業所での充電が重なると受電電力が大きくなる。燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を最適化し、受電上限を変えたときの電気バスの担当便・費用・CO₂を冬・春・夏の代表週で評価した。受電上限900 kW・太陽光1,000 kWの冬では、電気バスを多く使う解は燃料バスを多く使う解より1週間で${man(tc(p9i) - tc(p9b))}万円安く、CO₂は${wCut}%少なかった。上限を下げるとこの差は縮み、${iceWins.map(lab).join("・")}では燃料バスを多く使う解の方が安かった。`,
    { x: M + NUM, y: M + 3.45, w: W - NUM, h: 3.5, fontSize: 32 });

  // ---------------- left column
  let y = 9.2;
  y = section("1．背景と目的", LX, y, COL);
  // 2026-11-16 (user): the background opens with the 2050 carbon-neutral declaration and narrows to transport and buses.
  // Figures: MLIT "運輸部門における二酸化炭素排出量" (FY2024: 187.19 Mt, 19.3 % of 971.48 Mt; cars about 86 % of transport).
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: 4.3, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  const story = [
    ["2050年カーボンニュートラル", "日本は2020年10月、2050年に温室効果ガスの排出を実質ゼロにすると宣言した［7］"],
    ["交通分野", "運輸部門は日本のCO₂排出量の19.3%を占め、その約86%が自動車である（2024年度）［8］"],
    ["路線バス", "電気バスへの置き換えが進むが、一度には替えられず、当面は燃料バスと併用する。営業所で同時に充電すると受電電力が大きくなる"]];
  text(story.flatMap(([h, b], i) => [
      { text: (i ? "▶ " : "") + h + "　", options: { bold: true, color: BLUE_DARK } },
      { text: b, options: { breakLine: true } }]).concat([
      { text: "目指すこと　", options: { bold: true, color: BLUE_DARK } },
      { text: "受電設備と電気料金の負担を抑え、今の時刻表どおりに運行しながら、路線バスの電動化でCO₂を減らす（GX）", options: { bold: true } }]),
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: 3.95, fontSize: 25, paraSpaceAfter: 3 });
  y += 4.55;
  text([{ text: "本研究の取り組み", options: { bold: true, color: BLUE_DARK, breakLine: true } },
    ...["燃料バスと併用する営業所で、便割当と充電計画を最適化する", "受電上限を変えて、電気バスに任せられる便・費用・CO₂を比べる", "受電上限の超過が、いつ・なぜ生じるかを調べる"]
      .map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } }))],
    { x: LX, y, w: COL, h: 2.25, fontSize: 28, paraSpaceAfter: 4 });
  y += 2.4;

  y = section("2．手法", LX, y, COL);
  text([{ text: "最適化するもの　", options: { bold: true, color: BLUE_DARK } },
    { text: "(a) 各便をどの車両（電気バス・燃料バス）が担当するか、(b) 各電気バスをいつ・何kWで充電するか。時刻表の便はすべて運行する。" }],
    { x: LX, y, w: COL, h: 1.4, fontSize: 29 });
  y += 1.5;
  text([{ text: "目的関数　", options: { bold: true, color: BLUE_DARK } }, { text: "1週間の総費用を最小にする" }], { x: LX, y, w: COL, h: 0.6, fontSize: 29 });
  y += 0.7;
  const EQW = COL * 0.86, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: "目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化" });
  y += EQH + 0.15;
  caption("左から車両使用費（u：車両kを日dに使うか）、電気代と超過費用（g：時刻tの買電量、s：超過量）、燃料代（f：便jの軽油）、CO₂の費用（Q：排出量）。c・p・πは単価。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限（超過分は費用）", LX, y, COL, 1.65, 22);
  y += 1.75;
  flowDiagram(s, pres, LX, y, COL, [
    ["① 便割当", ["1,704便を60台に割当", "整数計画＋割当の一部を組み直す探索［5］"]],
    ["② 前日の計画", ["割当は固定、15分ごとに充電を計画", "太陽光は平年値で予測［2］"]],
    ["③ 毎時の立て直し", ["実際の日射で1時間ごとに再計画", "週末の翌朝まで174〜175回"]],
    ["④ 集計", ["実行結果で費用・CO₂を集計", "2通りの初期割当の安い方を採用"]]], "Yu Gothic", 3.25, 22);
  caption("図1　計算の流れ（ソルバーはGurobi［4］）。蓄電池は規則で充放電する", LX, y + 3.3, COL, 0.6, 24);
  y += 4.0;
  // 2026-11-16: tariff of the et series (energy charge in the model, basic charge added to the result) and the
  // uniform settings of rc41/rc42 (gap 5 %, re-plan 300 s). The 30 JPY/kWh all-inclusive series (ct) is a comparison.
  const params = [["電気料金", "17.43円/kWh［6］。基本料金（週4.5万〜44.7万円）は結果に加算。比較：30円/kWh（基本料金込み）"],["軽油", "150円/L、CO₂ 2.62 kg/L［1］"], ["電力のCO₂", "0.5 kg/kWh（仮）。CO₂の費用1円/kg（集計しない）"],
    ["車両使用費", "2万円/台・日"], ["受電上限の超過", "500円/kWh（仮）"], ["朝の電池残量", "電気バス：目標90%・下限80%"],
    ["時間の刻み", "15分（立て直しの実行は1時間ごと）"], ["計算の打ち切り", "ギャップ5%（全ケース共通）、便割当3時間、立て直し300秒/回（時間切れ時のみ600秒）"]];
  const tbl = (rowsIn, x, yy, w, k = 3.9, fs = 27, rh = 0.56) => // rh: number or per-row array
   s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
    { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: "Yu Gothic", color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  const prh = params.map(([k]) => (k === "電気料金" || k === "計算の打ち切り" ? 0.9 : 0.5));
  tbl(params, LX, y, COL, 3.9, 27, prh);
  y += prh.reduce((a, b) => a + b, 0) + 0.35; // PowerPoint grows two-line rows beyond rowH
  caption("表1　計算に用いた値（仮の値は今後、感度を調べる）。ギャップ＝解と理論上の下限の差", LX, y, COL, 0.6, 23);
  y += 0.7;

  y = section("3．ケーススタディ", LX, y, COL);
  const MAPW = COL * 0.40, MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, "route_map_ja_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH, altText: "渋21・渋22・渋23の路線図と弦巻営業所の位置" });
  y += MAPH + 0.08;
  caption("図2　対象路線と弦巻営業所（停留所の位置は公共交通オープンデータ（ODPT）［3］、停留所の間は直線。背景は © OpenStreetMap contributors）", LX, y, COL, 1.0, 22);
  y += 1.0;
  const study = [["対象", "東急バス 渋21〜23系統（弦巻営業所）、1週間1,704便"], ["車両・設備", "電気バス35台・燃料バス25台、充電器90 kW×10、太陽光1,000 kW、蓄電池6,000 kWh"],
    ["比べるケース", "受電上限 90・200・400・900 kW × 冬・春・夏の代表週（2025年1/6・4/7・7/7からの1週間、実際の日射）＝12ケース"]];
  tbl(study, LX, y, COL, 3.3, 25, 0.8);
  y += study.length * 0.8 + 0.4;
  caption("表2　ケーススタディの条件", LX, y, COL, 0.5, 24);
  if (y + 0.5 > 45.5 - 1.6) throw new Error(`left column overflows: ${y}`);
  text([{ text: "参考文献　", options: { bold: true } },
    { text: "［1］環境省・経済産業省：算定方法及び排出係数一覧（2025年版）　［2］W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018　［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）　［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0　［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998　［6］東京電力エナジーパートナー：高圧の電気料金（ベーシックプラン、2026年4月1日実施）　［7］首相官邸：第203回国会における菅内閣総理大臣所信表明演説（2020年10月26日）　［8］国土交通省：運輸部門における二酸化炭素排出量" }],
    { x: LX, y: 45.5 - 1.6, w: COL, h: 1.6, fontSize: 16, color: SUB });

  // ---------------- right column
  y = 9.2;
  y = section("4．結果", RX, y, COL);
  const halfR = (COL - 0.5) / 2, cats = LIMITS.map((g) => `${g}`);
  s.addChart(pres.charts.BAR, SE.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
    { ...chart(), x: RX, y, w: halfR, h: 6.0, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: 26, valAxisLabelFontSize: 24, legendFontSize: 26, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: "受電上限 [kW]", catAxisTitleFontSize: 24, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
  // 2026-11-16 (user): Fig. 4 is a table, grid limit (rows) x season (columns), total cost per case without the CO2 cost.
  const T4 = halfR, k4 = 2.0, cw4 = (T4 - k4) / SE.length, rh4 = 0.95;
  const hd4 = (t) => ({ text: t, options: { bold: true, align: "center", fill: { color: "F2F2F2" } } });
  const c4 = (g, w) => { const r = cases.find((x) => x.grid_limit_kw === g && x.week === w);
    return { text: r ? `${man(tc(r))}${r.selected_start === "ice" ? "＊" : ""}` : "—", options: { align: "center", color: r && r.selected_start === "ice" ? BLUE_DARK : INK, bold: !!(r && r.selected_start === "ice") } }; };
  s.addTable([[hd4("受電上限"), ...SE.map(([, n]) => hd4(n))],
    ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => c4(g, w))])],
    { x: RX + halfR + 0.5, y: y + 0.4, w: T4, colW: [k4, ...SE.map(() => cw4)], fontSize: 28, fontFace: "Yu Gothic", color: INK,
      rowH: rh4, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  caption("図3　受電上限と電気バスの担当便（1,704便/週）。各ケースで2通りの初期割当のうち総費用の安い方の解", RX, y + 6.05, halfR, 1.6, 24);
  caption("図4　各ケースの総費用［万円/週］（車両使用費＋電気代＋燃料代＋超過費用。CO₂の費用は集計に含めない）。＊は燃料バス優先の初期割当から得た解", RX + halfR + 0.5, y + 0.4 + rh4 * (LIMITS.length + 1) + 0.15, halfR, 1.9, 24);
  y += 7.85;
  text(`受電上限が400 kW以上なら、電気バスが便の${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%を担当し、総費用も小さい。上限の低い${iceWins.map(lab).join("・")}では燃料バスを多く使う方が安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%に下がった。`,
    { x: RX, y, w: COL, h: 1.9, fontSize: 28 });
  y += 2.05;
  text([{ text: "限られた計算時間で効率よく最適化する工夫　", options: { bold: true, color: BLUE_DARK } },
    { text: "便割当は規模が大きく、制限時間内に最適とは確認できない。探索は最初に与えた割当に近い解に留まりやすいため、性質の違う「電気バスを優先して使う割当」と「燃料バスを優先して使う割当」の2通りを初期割当として最適化を始め、総費用の安い方を採用した（表3）。" }],
    { x: RX, y, w: COL, h: 2.3, fontSize: 28 });
  y += 2.45;
  const p90b = pb90, p90i = pi90;
  const cols = [["900 kW冬", p9b, "電気バス優先"], ["900 kW冬", p9i, "燃料バス優先"], ["90 kW冬", p90b, "電気バス優先"], ["90 kW冬", p90i, "燃料バス優先"]];
  const win = (a, b) => tc(a) <= tc(b);
  const adopted = [win(p9b, p9i), !win(p9b, p9i), win(p90b, p90i), !win(p90b, p90i)];
  const cell = (t, i, extra = {}) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK, ...extra } });
  const head = (t) => ({ text: t, options: { bold: true, fill: { color: "F2F2F2" }, align: "center" } });
  const row = (label, f) => [{ text: label, options: { bold: true } }, ...cols.map(([, r], i) => cell(f(r), i))];
  s.addTable([
    [head("受電上限・季節"), ...cols.map(([n]) => head(n))],
    [{ text: "初期割当", options: { bold: true } }, ...cols.map(([, , n], i) => cell(n, i))],
    row("総費用", (r) => `${man(tc(r))}万円`),
    row("電気バス担当便", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
    row("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`),
    row("上限の超過", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`),
    [{ text: "採用", options: { bold: true } }, ...adopted.map((a, i) => cell(a ? "○" : "—", i))]],
    { x: RX, y, w: COL, colW: [3.7, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4], fontSize: 25, fontFace: "Yu Gothic",
      color: INK, rowH: 0.62, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  y += 7 * 0.62 + 0.1;
  caption("表3　2通りの初期割当から最適化して得た解（1週間）。青字が採用した方", RX, y, COL, 0.6, 24);
  y += 0.8;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g}${SEASON_OF[w]}`, b, i }); }));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: 5.4, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 18, legendFontSize: 22, catAxisLabelFontSize: 20, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 20, valAxisTitleFontSize: 22, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  s.addChart(pres.charts.BAR, [{ name: "電気バス優先 − 燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round((tc(p.b) - tc(p.i)) / 1e3) / 10) }],
    pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0.0;-0.0", valAxisMinVal: -60, valAxisMaxVal: 60, valAxisMajorUnit: 30, catAxisLabelPos: "low", valAxisTitle: "費用の差 [万円/週]" }));
  s.addChart(pres.charts.BAR, [
    { name: "電気バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/週]" }));
  y += 5.45;
  const bevCheap = PAIRS.filter((p) => tc(p.b) < tc(p.i)).length, co2Low = PAIRS.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
  caption(`図5　2通りの初期割当から最適化して得た解の比較：総費用の差（左。負は電気バス優先から得た解が安い）とCO₂（右）。CO₂は${PAIRS.length}ケース中${co2Low}ケースで電気バス優先が少なく、費用は${bevCheap}ケースで電気バス優先が安い`, RX, y, COL, 1.2, 24);
  y += 1.4;

  y = section("5．考察とまとめ", RX, y, COL);
  text([
    { text: `受電上限に余裕があれば、電化は費用もCO₂も下げる。上限が低い${iceWins.map(lab).join("・")}では燃料バスを多く使う解の方が安かった。90 kW冬ではその差は約${Math.round((tc(p90b) - tc(p90i)) / 1e4)}万円/週だが、CO₂は約${(p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1)}倍になる。`, options: { bullet: true, breakLine: true } },
    { text: `上限の超過は、曇りの日の翌未明、蓄電池が空の時間に集中した（90 kW冬・電気バス優先から得た解〔不採用〕の超過${fmt(p90b.contract_over_limit_kwh)} kWh/週の9割）。前日の計画は太陽光を平年値で予測するため、曇りの日の不足を見込めない。`, options: { bullet: true } }],
    { x: RX, y, w: COL, h: 3.0, fontSize: 26, paraSpaceAfter: 4 });
  y += 3.1;
  text([{ text: "今後の展望　", options: { bold: true, color: BLUE_DARK } },
    { text: "本発表の内容を再計算した結果で2027年3月の電気学会全国大会に発表する。その後、曇りの日の不足や未明の蓄電池切れに備える計画の方式と蓄電池の最適化を進め、受電上限と設備の決め方の指針につなげる。" }],
    { x: RX, y, w: COL, h: 1.75, fontSize: 25 });
  y += 1.85;
  // 2026-11-16 (user): road to the M2 midterm (2027-11) and the master's final (2028-02), via the IEEJ national
  // convention (2027-03) and several conferences in FY2027. Contents of each step are the plan, not results.
  const steps = [["2027年3月", "電気学会全国大会", "本発表の内容（受電上限と電気バスの担当便・費用・CO₂）"],
    ["2027年度", "学会発表（数回）", "日をまたぐ計画、蓄電池の充放電の最適化、単価・CO₂係数の感度"],
    ["2027年11月", "中間発表", "日ごとの計画と比べた効果（翌朝の電池不足、燃料バスへの振替、夜の買電）"],
    ["2028年2月", "修士最終発表", "受電上限・蓄電池・充電器の決め方の指針（季節を通した評価）"]];
  const sw = (COL - 0.6) / 4, bh = 2.55;
  steps.forEach(([when, where, what], i) => {
    const x = RX + i * (sw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: bh, fill: { color: i === 3 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } },
      { text: what, options: { fontSize: 17, color: SUB } }], { x: x + 0.12, y: y + 0.08, w: sw - 0.24, h: bh - 0.12, fontSize: 20, align: "center" });
  });
  caption("図6　修士最終発表までの予定と、それぞれで出す成果", RX, y + bh + 0.05, COL, 0.5, 22);
  y += bh + 0.6;
  caption(`注：結果はすべて診断用（DIAGNOSTIC）で、研究の結論にはまだ使わない。便割当は制限時間内に最適と確認できておらず、便割当と充電計画を2段階で解くため全体の最適でもない。蓄電池は規則で充放電し、最適化していない。毎時の立て直しは、示した解のうち最大${maxTimeouts}回が時間切れ（1週間174〜175回中）。図表の数値は旧版（${versions}、30円/kWh（基本料金込み））の結果で、表1の2通りの電気料金で全ケースを再計算中。`,
    RX, y, COL, 45.5 - y, 20);
};
