// Layout after Prof. Urabe's comments of 2026-11-18 on the v3 preview (built with POSTER_LAYOUT=v4):
//  - type too small: body 34 pt, captions/tables/boxes 26-30 pt, references 18 pt, note 20 pt (was 16-29 pt);
//  - abstract removed ("これは必要でしょうか"); the space goes to the larger type;
//  - author line filled in with the user's affiliation, supervisor and sub-examiners.
// Content cut to fit the larger type (same data and numbers as v3; no new figures):
//  background condensed, "本研究の取り組み" folded into the aim, variable glossary under the objective shortened,
//  table 1 reduced to prices (time step and gap moved to its caption), table 3 dropped (fig. 5 shows all 12 pairs),
//  "今後の展望" paragraph dropped (fig. 6 carries it), references and note moved to a full-width footer.
module.exports = function layout(c) {
  const { s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    cases, LIMITS, SE, SEASON_OF, lab, val, pairOf, iceWins, bevWins, rngTxt, man, fmt, pb90, pi90, eqSize, maxTimeouts, versions } = c;
  const NUM = 7.87, BODY = 34, CAP = 28;
  const FOOT = 43.0; // top of the full-width footer (references, note)
  const tc = (r) => r.total_cost_reported; // CO2 cost excluded from every reported total (2026-11-16)
  const bullets = (items, o) => text(items.map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } })), o);

  // ---------------- header
  text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M, w: W - NUM, h: 3.2, fontSize: 78, bold: true, valign: "middle", lineSpacingMultiple: 1.05 });
  // 2026-11-18 (user): affiliation, supervisor and sub-examiners as given by the user.
  text([{ text: "東京都市大学大学院 総合理工学研究科 電気・化学専攻　電力システム研究室（修士1年）", options: { breakLine: true } },
    { text: "劉 承洋", options: { bold: true, color: INK } }, { text: "　指導教員：占部千由 准教授　副査：中島達人 教授、平野拓一 准教授" }],
    { x: M + NUM, y: M + 3.3, w: W - NUM, h: 1.45, fontSize: 34, color: SUB });
  const RULE = M + 4.95;
  s.addShape(pres.shapes.LINE, { x: M, y: RULE, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const TOP = RULE + 0.35;

  // ---------------- left column
  let y = TOP;
  y = section("1．背景と目的", LX, y, COL);
  const BOXH = 5.0;
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: BOXH, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text([
    ...["運輸部門は日本のCO₂排出の19.3%を占める（2024年度）［8］", "2050年カーボンニュートラル［7］に向け、電動化が進む",
      "電気バスは一度に置き換えられず、当面は燃料バスと併用する", "営業所で同時に充電すると、受電電力が大きくなる"]
      .map((t) => ({ text: t, options: { bullet: { code: "25B6" }, breakLine: true } })),
    { text: "目的　", options: { bold: true, color: BLUE_DARK } },
    { text: "受電電力を抑えつつ、今の時刻表のまま、", options: { bold: true, breakLine: true } }, { text: "電動化でCO₂を減らす（GX）", options: { bold: true } }],
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: BOXH - 0.3, fontSize: BODY - 2, paraSpaceAfter: 4 });
  y += BOXH + 0.35;

  y = section("2．手法", LX, y, COL);
  text([{ text: "決めること　", options: { bold: true, color: BLUE_DARK } },
    { text: "各便を担当する車両（電気バス・燃料バス）と、電気バスの充電の時刻・電力。時刻表の便はすべて運行する" }],
    { x: LX, y, w: COL, h: 1.5, fontSize: BODY });
  y += 1.6;
  text([{ text: "目的関数　", options: { bold: true, color: BLUE_DARK } }, { text: "1週間の総費用を最小にする" }], { x: LX, y, w: COL, h: 0.75, fontSize: BODY });
  y += 0.85;
  const EQW = COL * 0.84, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: "目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化" });
  y += EQH + 0.15;
  caption("左から車両使用費、電気代と上限の超過費用、燃料代、CO₂の費用。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限", LX, y, COL, 1.4, CAP);
  y += 1.55;
  flowDiagram(s, pres, LX, y, COL, [
    ["① 便割当", ["1,704便を60台に割り当てる", "部分的な組み直し［5］"]],
    ["② 前日の計画", ["15分ごとの充電を決める", "太陽光は平年値［2］"]],
    ["③ 毎時の再計画", ["実際の日射で1時間ごとに計画し直す"]],
    ["④ 集計", ["実行した結果で費用とCO₂を数える"]]], "Yu Gothic", 3.4, 26);
  caption("図1　計算の流れ（ソルバーはGurobi［4］）。蓄電池は決めた規則で充放電する", LX, y + 3.5, COL, 0.65, CAP);
  y += 4.3;
  // Table 1 keeps both tariffs (the note refers to them); time step, gap and the battery rule move to captions.
  const params = [["電気料金", "17.43円/kWh＋基本料金［6］。比較用：30円/kWh（基本料金込み）"], ["軽油", "150円/L、CO₂ 2.62 kg/L［1］"],
    ["電力のCO₂", "0.5 kg/kWh（仮）。CO₂の費用1円/kg"], ["車両使用費", "2万円/台・日"], ["受電上限の超過", "500円/kWh（仮）"]];
  const tbl = (rowsIn, x, yy, w, k, fs, rh) =>
    s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
      { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: "Yu Gothic", color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  const prh = params.map(([k]) => (k === "電気料金" ? 1.15 : 0.66));
  tbl(params, LX, y, COL, 4.3, CAP, prh);
  y += prh.reduce((a, b) => a + b, 0) + 0.15;
  caption("表1　計算に用いた値（仮の値は今後、感度を調べる）。CO₂の費用は目的関数だけに入れ、集計には含めない。時間の刻みは15分、ギャップ5%で打ち切り", LX, y, COL, 1.4, CAP);
  y += 1.55;

  y = section("3．ケーススタディ", LX, y, COL);
  const MAPW = COL * 0.56, MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, "route_map_ja_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH, altText: "渋21・渋22・渋23の路線図と弦巻営業所の位置" });
  y += MAPH + 0.1;
  caption("図2　対象路線と弦巻営業所（停留所の位置はODPT［3］、停留所の間は直線。背景は © OpenStreetMap contributors）", LX, y, COL, 1.4, CAP);
  y += 1.5;
  const study = [["対象", "東急バス 渋21〜23系統（弦巻営業所）、1週間1,704便"], ["車両・設備", "電気バス35台・燃料バス25台、充電器90 kW×10、太陽光1,000 kW、蓄電池6,000 kWh"],
    ["比べるケース", "受電上限 90・200・400・900 kW × 冬・春・夏の代表週（2025年1/6・4/7・7/7から、実際の日射）＝12ケース"]];
  tbl(study, LX, y, COL, 3.4, CAP, [1.15, 1.15, 1.15]);
  y += 3 * 1.15 + 0.15;
  caption("表2　ケーススタディの条件", LX, y, COL, 0.65, CAP);
  y += 0.7;
  if (y > FOOT) throw new Error(`left column overflows: ${y}`);

  // ---------------- right column
  y = TOP;
  y = section("4．結果", RX, y, COL);
  const halfR = (COL - 0.5) / 2, cats = LIMITS.map((g) => `${g}`), CH3 = 6.6;
  s.addChart(pres.charts.BAR, SE.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
    { ...chart(), x: RX, y, w: halfR, h: CH3, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: 28, valAxisLabelFontSize: 26, legendFontSize: 28, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: "受電上限 [kW]", catAxisTitleFontSize: 26, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
  const T4 = halfR, k4 = 2.1, cw4 = (T4 - k4) / SE.length, rh4 = 1.0;
  const hd4 = (t) => ({ text: t, options: { bold: true, align: "center", fill: { color: "F2F2F2" } } });
  const c4 = (g, w) => { const r = cases.find((x) => x.grid_limit_kw === g && x.week === w);
    return { text: r ? `${man(tc(r))}${r.selected_start === "ice" ? "*" : ""}` : "—", options: { align: "center", color: r && r.selected_start === "ice" ? BLUE_DARK : INK, bold: !!(r && r.selected_start === "ice") } }; };
  s.addTable([[hd4("受電上限"), ...SE.map(([, n]) => hd4(n))],
    ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => c4(g, w))])],
    { x: RX + halfR + 0.5, y: y + 0.3, w: T4, colW: [k4, ...SE.map(() => cw4)], fontSize: 30, fontFace: "Yu Gothic", color: INK,
      rowH: rh4, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  caption("図3　受電上限と電気バスの担当便の割合（全1,704便/週）", RX, y + CH3 + 0.05, halfR, 1.3, CAP);
  const y4 = y + 0.3 + rh4 * (LIMITS.length + 1) + 0.15;
  caption("図4　1週間の総費用［万円］（車両使用費・電気代・燃料代・超過費用。CO₂の費用は含めない）。*は燃料バス優先の解", RX + halfR + 0.5, y4, halfR, y + CH3 + 1.4 - y4, CAP);
  y += CH3 + 1.5;
  bullets([`受電上限400 kW以上：電気バスが全便の${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%を担当し、総費用も小さい`,
    `${iceWins.map(lab).join("・")}：燃料バスを多く使う解の方が安く、電気バスの担当は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%`],
    { x: RX, y, w: COL, h: 3.0, fontSize: BODY, paraSpaceAfter: 6 });
  y += 3.1;
  text([{ text: "2通りの初期割当　", options: { bold: true, color: BLUE_DARK } },
    { text: "便割当は最適解と確かめられないため、「電気バス優先」と「燃料バス優先」の2通りから解き、総費用の安い方を採用した（図5）" }],
    { x: RX, y, w: COL, h: 2.2, fontSize: BODY });
  y += 2.3;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g}${SEASON_OF[w]}`, b, i }); }));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2, CH5 = 7.0;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: CH5, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 20, legendFontSize: 24, catAxisLabelFontSize: 22, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 22, valAxisTitleFontSize: 24, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  s.addChart(pres.charts.BAR, [{ name: "電気バス優先 − 燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round((tc(p.b) - tc(p.i)) / 1e3) / 10) }],
    pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0.0;-0.0", valAxisMinVal: -60, valAxisMaxVal: 60, valAxisMajorUnit: 30, catAxisLabelPos: "low", valAxisTitle: "費用の差 [万円/週]" }));
  s.addChart(pres.charts.BAR, [
    { name: "電気バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/週]" }));
  y += CH5 + 0.05;
  const bevCheap = PAIRS.filter((p) => tc(p.b) < tc(p.i)).length, co2Low = PAIRS.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
  caption(`図5　2通りの初期割当から得た解の比較。左は総費用の差（負なら電気バス優先の方が安い）、右はCO₂。CO₂は${co2Low === PAIRS.length ? "すべてのケース" : `${PAIRS.length}ケース中${co2Low}ケース`}で電気バス優先の方が少なく、費用は${bevCheap}ケースで電気バス優先の方が安い`, RX, y, COL, 2.0, CAP);
  y += 2.1;

  y = section("5．考察とまとめ", RX, y, COL);
  bullets([`受電上限に余裕があれば、電動化で費用もCO₂も下がる。90 kW冬では燃料バス中心の方が約${Math.round((tc(pb90) - tc(pi90)) / 1e4)}万円/週安いが、CO₂は約${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)}倍になる`,
    `上限の超過は、曇りの日の翌日未明、蓄電池が空の時間帯に集中した（90 kW冬・電気バス優先の解〔不採用〕で超過${fmt(pb90.contract_over_limit_kwh)} kWh/週の9割）。前日の計画は太陽光を平年値で予測するため、曇りを見込めない`],
    { x: RX, y, w: COL, h: 5.0, fontSize: BODY, paraSpaceAfter: 6 });
  y += 5.1;
  // 2026-11-16 (user): road to the M2 midterm (2027-11) and the master's final (2028-02). Contents are the plan, not results.
  const steps = [["2027年3月", "電気学会全国大会", "本発表の内容（受電上限と電気バスの担当便・費用・CO₂）"],
    ["2027年度", "学会発表（数回）", "日をまたぐ計画、蓄電池の充放電の最適化、単価・CO₂係数の感度"],
    ["2027年11月", "中間発表", "日ごとの計画と比べた効果（翌朝の電池不足、燃料バスへの振替、夜の買電）"],
    ["2028年2月", "修士最終発表", "受電上限・蓄電池・充電器の決め方の指針（季節を通した評価）"]];
  const sw = (COL - 0.6) / 4, bh = FOOT - 0.8 - y;
  steps.forEach(([when, where, what], i) => {
    const x = RX + i * (sw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: bh, fill: { color: i === 3 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } },
      { text: what, options: { fontSize: 26, color: SUB } }], { x: x + 0.12, y: y + 0.1, w: sw - 0.24, h: bh - 0.15, fontSize: 28, align: "center", lineSpacingMultiple: 1.05 });
  });
  caption("図6　修士最終発表までの予定と、それぞれで目指す成果", RX, y + bh + 0.05, COL, 0.65, CAP);
  if (bh < 3.0) throw new Error(`road-map boxes too short: ${bh}`);

  // ---------------- footer (full width)
  s.addShape(pres.shapes.LINE, { x: M, y: FOOT + 0.1, w: W, h: 0, line: { color: GRID, width: 2 } });
  caption(`注：数値はいずれも診断用（DIAGNOSTIC）で、研究の結論にはまだ用いない。便割当は最適解と確かめられておらず、2段階で解くため全体としての最適解でもない。蓄電池は規則で充放電し、最適化していない。毎時の再計画は最大${maxTimeouts}回（174〜175回中）が時間切れ。数値は旧版（${versions}、30円/kWh・基本料金込み）の結果で、表1の2通りの電気料金で全ケースを計算し直している。`,
    M, FOOT + 0.25, W, 1.05, 20);
  text([{ text: "参考文献　", options: { bold: true } },
    { text: "［1］環境省・経済産業省：算定方法及び排出係数一覧（2025年版）　［2］W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018　［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）　［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0　［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998　［6］東京電力エナジーパートナー：高圧の電気料金（ベーシックプラン、2026年4月1日実施）　［7］首相官邸：第203回国会における菅内閣総理大臣所信表明演説（2020年10月26日）　［8］国土交通省：運輸部門における二酸化炭素排出量" }],
    { x: M, y: FOOT + 1.4, w: W, h: 45.55 - FOOT - 1.4, fontSize: 18, color: SUB });
};
