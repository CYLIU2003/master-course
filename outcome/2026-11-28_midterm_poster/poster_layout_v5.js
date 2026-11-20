// Poster layout for the rc42 results (built by build_poster_rc42.js; 2026-11-18).
// Same frame and type sizes as v4 (Prof. Urabe's comments of 11/18), one file for both languages (L(ja, en)).
// Changes from v4:
//  - data: rc42 (19dc0780) for tariff A (et: 17.43 JPY/kWh + basic charge) and B (ct: 30 JPY/kWh incl. basic charge);
//    reported totals include the weekly basic charge for A and exclude the CO2 cost (see build_poster_rc42.js);
//  - variant a/b: one tariff in figs. 3-5, the other in a comparison bullet; variant c: both tariffs in figs. 3-5;
//  - results bullets are computed from the data (the v4 wording "400 kW and above" no longer matches rc42);
//  - the v4 discussion claim "90% of the excess in the early hours after cloudy days" came from an earlier version and
//    was not rechecked for rc42, so it is replaced by tariff comparisons computed from the rc42 data;
//  - the footer note lists the rc42 retries (14 GiB memory_limit -> one rerun at 24 GiB) and time-limit counts.
module.exports = function layout(c) {
  const { LANG, VARIANT, s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    LIMITS, SE, MAIN, OTHER, ET, CT, eqSize, FONT } = c;
  const EN = LANG === "en", L = (ja, en) => (EN ? en : ja);
  const NUM = 7.87, BODY = 34, CAP = 28;
  const FOOT = 43.0;
  const BOTH = VARIANT === "c";
  // 2026-11-19 (user, variant a): a higher grid limit is not always cheaper under tariff A — explain it in the results,
  // discussion and operating guidance, and show the electricity-cost formula in detail. Variants b and c are unchanged.
  const COSTA = VARIANT === "a";
  const TAR = { et: { k: "A", d: L("17.43円/kWh＋基本料金", "17.43 JPY/kWh + basic charge") },
                ct: { k: "B", d: L("30円/kWh・基本料金込み", "30 JPY/kWh incl. basic charge") } };
  const SEASON = { "2025-01-06": L("冬", "winter"), "2025-04-07": L("春", "spring"), "2025-07-07": L("夏", "summer") };
  const SHORT = { "2025-01-06": L("冬", "W"), "2025-04-07": L("春", "Sp"), "2025-07-07": L("夏", "Su") };
  const SEN = SE.map(([w]) => [w, EN ? SEASON[w][0].toUpperCase() + SEASON[w].slice(1) : SEASON[w]]);
  const lab = (r) => (EN ? `${r.grid_limit_kw} kW ${SEASON[r.week]}` : `${r.grid_limit_kw} kW${SEASON[r.week]}`);
  const list = (a) => (EN ? (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`) : a.join("・"));
  const tc = (r) => r.total_cost_reported;
  // money: 万円 (ja) / thousand JPY (en)
  const money = (v) => (EN ? `${Math.round(v / 1e3)}` : (v / 1e4).toFixed(1));
  const moneyU = L("万円/週", " thousand JPY/week");
  const tbl4 = (v) => (EN ? (v / 1e6).toFixed(2) : (v / 1e4).toFixed(1)); // fig. 4 cells: 万円 / million JPY
  const rngTxt = (a, d = 0) => (!a.length ? "—" : Math.min(...a).toFixed(d) === Math.max(...a).toFixed(d) ? Math.min(...a).toFixed(d)
    : `${Math.min(...a).toFixed(d)}${L("〜", "–")}${Math.max(...a).toFixed(d)}`);
  const sel = (st) => (st === "ice" ? L("燃料バス優先", "diesel-first") : L("電気バス優先", "electric-first"));
  const bullets = (items, o) => text(items.map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } })), o);
  const iceW = (X) => X.cases.filter((r) => r.selected_start === "ice"), bevW = (X) => X.cases.filter((r) => r.selected_start === "bev");
  const avgAt = (X, g) => X.cases.filter((r) => r.grid_limit_kw === g).reduce((a, r) => a + tc(r), 0) / SE.length;
  const gapOf = (X, r) => 0.05 * tc(r);
  const pdiff = (X, g, w) => Math.abs(tc(X.pair(g, w, "bev")) - tc(X.pair(g, w, "ice")));
  const W90 = "2025-01-06", fmtN = (v) => Math.round(v).toLocaleString("en-US");

  // ---------------- header
  if (EN) {
    text("Trip Assignment and Charging Optimization\nfor Electric Buses Operated Alongside\nDiesel Buses toward GX", { x: M + NUM, y: M - 0.1, w: W - NUM, h: 3.3, fontSize: 60, bold: true, valign: "middle", lineSpacingMultiple: 1.0 });
    text([{ text: "LIU Chengyang", options: { bold: true, color: INK } }, { text: " (M1), Electric Power System Laboratory, Tokyo City University", options: { breakLine: true } },
      { text: "Electrical Engineering and Chemistry, Graduate School of Integrative Science and Engineering", options: { breakLine: true } },
      { text: "Supervisor: Assoc. Prof. C. Urabe    Co-examiners: Prof. T. Nakajima, Assoc. Prof. T. Hirano" }],
      { x: M + NUM, y: M + 3.25, w: W - NUM, h: 1.6, fontSize: 28, color: SUB, lineSpacingMultiple: 1.05 });
  } else {
    text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M, w: W - NUM, h: 3.2, fontSize: 78, bold: true, valign: "middle", lineSpacingMultiple: 1.05 });
    text([{ text: "東京都市大学大学院 総合理工学研究科 電気・化学専攻　電力システム研究室（修士1年）", options: { breakLine: true } },
      { text: "劉 承洋", options: { bold: true, color: INK } }, { text: "　指導教員：占部千由 准教授　副査：中島達人 教授、平野拓一 准教授" }],
      { x: M + NUM, y: M + 3.3, w: W - NUM, h: 1.45, fontSize: 34, color: SUB });
  }
  const RULE = M + 4.95;
  s.addShape(pres.shapes.LINE, { x: M, y: RULE, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const TOP = RULE + 0.35;

  // ---------------- left column (as v4; table 1 names the tariffs A and B)
  let y = TOP;
  y = section(L("1．背景と目的", "1. Background and aim"), LX, y, COL);
  const BOXH = COSTA ? 4.3 : 5.0;
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: BOXH, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text([
    ...(EN ? ["Transport emits 19.3% of Japan's CO₂ (FY2024) [8]", "Toward carbon neutrality by 2050 [7], route buses are being electrified",
      "Fleets cannot be replaced at once; electric and diesel buses run together", "Charging many buses at the depot at once raises its grid power"]
      : ["運輸部門は日本のCO₂排出の19.3%を占める（2024年度）［8］", "2050年カーボンニュートラル［7］に向け、電動化が進む",
        "電気バスは一度に置き換えられず、当面は燃料バスと併用する", "営業所で同時に充電すると、受電電力が大きくなる"])
      .map((t) => ({ text: t, options: { bullet: { code: "25B6" }, breakLine: true } })),
    ...(EN ? [{ text: "Aim  ", options: { bold: true, color: BLUE_DARK } },
      { text: "Cut CO₂ by electrification (GX) while keeping today's timetable and limiting grid power", options: { bold: true } }]
      : [{ text: "目的　", options: { bold: true, color: BLUE_DARK } },
        { text: "受電電力を抑えつつ、今の時刻表のまま、", options: { bold: true, breakLine: true } }, { text: "電動化でCO₂を減らす（GX）", options: { bold: true } }])],
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: BOXH - 0.3, fontSize: EN ? 29 : BODY - 2, paraSpaceAfter: EN ? 2 : 4 });
  y += BOXH + 0.35;

  y = section(L("2．手法", "2. Method"), LX, y, COL);
  text([{ text: L("決めること　", "Decisions  "), options: { bold: true, color: BLUE_DARK } },
    { text: L("各便を担当する車両（電気バス・燃料バス）と、電気バスの充電の時刻・電力。時刻表の便はすべて運行する",
      "which bus, electric or diesel, runs each trip, and when and at how many kW each electric bus charges. Every timetabled trip is run.") }],
    { x: LX, y, w: COL, h: 1.5, fontSize: EN ? 29 : BODY });
  y += 1.6;
  text([{ text: L("目的関数　", "Objective  "), options: { bold: true, color: BLUE_DARK } }, { text: L("1週間の総費用を最小にする", "minimize the total cost of one week") }], { x: LX, y, w: COL, h: 0.75, fontSize: BODY });
  y += 0.85;
  const EQW = COL * 0.84, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: L("目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化", "Objective: minimize vehicle use, electricity with the excess over the grid limit, diesel, and the CO2 cost") });
  y += EQH + 0.15;
  const capEq = L("左から車両使用費、電気代と上限の超過費用、燃料代、CO₂の費用。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限",
    "From left: vehicle use, electricity and excess over the grid limit, diesel, CO₂. Main constraints: trip connection (arrival + turnaround + deadhead ≤ next departure), battery level, 10 chargers, grid limit");
  caption(capEq, LX, y, COL, EN ? 1.7 : 1.4, CAP);
  y += EN ? 1.8 : 1.55;
  if (COSTA) {
    // Electricity cost in detail (tariff A). Basic charge: 2,530 JPY/kW-month [6] x 0.85 x P, monthly -> weekly x 12/52
    // (prepare_deck_data_rc42.py: 90 kW 44,664 ... 900 kW 446,642 JPY/week). It depends on P only, so it is a constant
    // added to the result, not part of the objective; the energy and excess terms are in the objective.
    const FH = 1.55;
    s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: FH, fill: { color: "F4F7FA" }, line: { color: GRID, width: 1 } });
    const sb = (t) => ({ text: t, options: { subscript: true } });
    text([{ text: L("電気代（料金A）", "Electricity cost (tariff A)"), options: { bold: true, color: BLUE_DARK, fontSize: CAP, breakLine: true } },
      { text: L("電気代 ＝ Σ", "Cost = Σ") }, sb("t"), { text: " 17.43 g" }, sb("t"), { text: " Δt ＋ 2,530 × 0.85 × P × 12/52 ＋ 500 Σ" }, sb("t"), { text: " s" }, sb("t"), { text: " Δt" }],
      { x: LX + 0.3, y: y + 0.1, w: COL - 0.6, h: FH - 0.15, fontSize: EN ? 27 : 29, align: "center" });
    y += FH + 0.1;
    caption(L("第1項：電力量料金（gₜ：買電電力［kW］、Δt＝0.25 h）。第2項：基本料金（P：受電上限＝契約電力［kW］、2,530円/kW・月［6］、力率割引0.85、月額を週に換算）。第3項：上限超過（sₜ：上限を超えた電力、500円/kWh（仮））。第2項はPだけで決まる定数のため目的関数には入れず、結果に加える",
      "Term 1: energy (gₜ: grid power [kW], Δt = 0.25 h). Term 2: basic charge (P: grid limit = contract power [kW], 2,530 JPY/kW-month [6], power-factor discount 0.85, monthly to weekly). Term 3: excess (sₜ: power above the limit, 500 JPY/kWh, tentative). Term 2 depends on P only, so it is added to the result, not optimized"),
      LX, y, COL, 2.1, CAP - 2);
    y += 2.2;
  }
  flowDiagram(s, pres, LX, y, COL, EN ? [
    ["1 Assignment", ["1,704 trips to 60 buses", "partial re-solving [5]"]],
    ["2 Day-ahead", ["charging every 15 min", "PV from normals [2]"]],
    ["3 Hourly re-plan", ["re-planned each hour with actual sunshine"]],
    ["4 Accounting", ["cost and CO₂ of what was executed"]]] : [
    ["① 便割当", ["1,704便を60台に割り当てる", "部分的な組み直し［5］"]],
    ["② 前日の計画", ["15分ごとの充電を決める", "太陽光は平年値［2］"]],
    ["③ 毎時の再計画", ["実際の日射で1時間ごとに計画し直す"]],
    ["④ 集計", ["実行した結果で費用とCO₂を数える"]]], FONT, COSTA ? 3.1 : 3.4, EN ? 24 : 26);
  const FLH = COSTA ? 3.1 : 3.4;
  caption(L("図1　計算の流れ（ソルバーはGurobi［4］）。蓄電池は決めた規則で充放電する", "Fig. 1  Calculation flow (solver: Gurobi [4]). The battery follows a fixed rule"), LX, y + FLH + 0.1, COL, 0.65, CAP);
  y += FLH + 0.9;
  // Table 1: both tariffs named A and B in every variant; the one the results use is marked.
  const mark = (k) => (BOTH ? "" : (MAIN.series === k ? L("（図3〜5）", " (Figs. 3–5)") : L("（比較）", " (comparison)")));
  const elec = EN ? `A: 17.43 JPY/kWh + basic charge [6]${mark("et")}\nB: 30 JPY/kWh incl. basic charge${mark("ct")}`
    : `A：17.43円/kWh＋基本料金［6］${mark("et")}\nB：30円/kWh（基本料金込み）${mark("ct")}`;
  const params = [...(COSTA ? [] : [[L("電気料金", "Electricity"), elec]]), [L("軽油", "Diesel"), L("150円/L、CO₂ 2.62 kg/L［1］", "150 JPY/L, 2.62 kg-CO₂/L [1]")],
    [L("電力のCO₂", "Grid CO₂"), L("0.5 kg/kWh（仮）。CO₂の費用1円/kg", "0.5 kg/kWh (tentative); CO₂ cost 1 JPY/kg")],
    [L("車両使用費", "Vehicle use"), L("2万円/台・日", "20,000 JPY per bus-day")], [L("受電上限の超過", "Excess over limit"), L("500円/kWh（仮）", "500 JPY/kWh (tentative)")]];
  const tbl = (rowsIn, x, yy, w, k, fs, rh) =>
    s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
      { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: FONT, color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  const prh = params.map((_, i) => (i === 0 && !COSTA ? 1.15 : 0.66));
  tbl(params, LX, y, COL, 4.3, CAP, prh);
  y += prh.reduce((a, b) => a + b, 0) + 0.15;
  if (COSTA) {
    caption(L("表1　計算に用いた値（電気料金は上の式、仮の値は今後感度を調べる）。CO₂の費用は集計に含めない。15分刻み、ギャップ5%で打ち切り",
      "Table 1  Values used (electricity: formula above; tentative values to be tested). CO₂ cost: objective only, not in totals. 15-min steps; 5% gap"), LX, y, COL, 1.4, CAP);
    y += 1.5;
  } else {
  caption(L("表1　計算に用いた値（仮の値は今後、感度を調べる）。Aの基本料金は受電上限×2,530円/kW・月×0.85を週割りして総費用に加える。CO₂の費用は目的関数だけに入れ、集計には含めない。時間の刻みは15分、ギャップ5%で打ち切り",
    "Table 1  Values used (tentative ones to be tested). A adds a weekly basic charge (limit × 2,530 JPY/kW-month × 0.85). CO₂ cost: objective only, not in totals. 15-min steps; 5% gap"), LX, y, COL, 1.9, CAP);
  y += 2.0;
  }

  y = section(L("3．ケーススタディ", "3. Case study"), LX, y, COL);
  const MAPW = COL * (COSTA ? (EN ? 0.32 : 0.36) : EN ? 0.5 : 0.54), MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, EN ? "route_map_en_poster.png" : "route_map_ja_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH,
    altText: L("渋21・渋22・渋23の路線図と弦巻営業所の位置", "Routes Shibu 21, 22 and 23 and the Tsurumaki depot") });
  y += MAPH + 0.1;
  caption(L("図2　対象路線と弦巻営業所（停留所の位置はODPT［3］、停留所の間は直線。背景は © OpenStreetMap contributors）",
    "Fig. 2  Routes and the Tsurumaki depot (stop positions from ODPT [3], joined by straight lines; background © OpenStreetMap contributors)"), LX, y, COL, 1.4, CAP);
  y += 1.5;
  const study = EN ? [["Service", "Tokyu Bus routes Shibu 21–23 (Tsurumaki depot), 1,704 trips/week"], ["Fleet, equipment", "35 electric and 25 diesel buses; 10 × 90 kW chargers; 1,000 kW PV; 6,000 kWh battery"],
    ["Cases", "grid limit 90/200/400/900 kW × a winter, spring and summer week (from 6 Jan, 7 Apr, 7 Jul 2025; actual sunshine) = 12"]]
    : [["対象", "東急バス 渋21〜23系統（弦巻営業所）、1週間1,704便"], ["車両・設備", "電気バス35台・燃料バス25台、充電器90 kW×10、太陽光1,000 kW、蓄電池6,000 kWh"],
      ["比べるケース", "受電上限 90・200・400・900 kW × 冬・春・夏の代表週（2025年1/6・4/7・7/7から、実際の日射）＝12ケース"]];
  tbl(study, LX, y, COL, 3.4, EN ? 26 : CAP, [1.15, 1.15, 1.15]);
  y += 3 * 1.15 + 0.15;
  caption(COSTA ? L("表2　ケーススタディの条件。季節は代表1週ずつ（秋は春で代表）", "Table 2  Case-study conditions (one week per season; spring covers autumn)") : L("表2　ケーススタディの条件", "Table 2  Case-study conditions"), LX, y, COL, 0.65, CAP);
  y += 0.7;
  if (y > FOOT) throw new Error(`left column overflows: ${y}`);

  // ---------------- right column
  y = TOP;
  y = section(L("4．結果", "4. Results"), RX, y, COL);
  if (!COSTA) text(BOTH ? [{ text: L("電気料金A・Bの両方で計算（表1）", "Computed with both tariffs A and B (Table 1)"), options: { bold: true, color: BLUE_DARK } }]
    : [{ text: L(`電気料金${TAR[MAIN.series].k}（${TAR[MAIN.series].d}）の結果。`, `Tariff ${TAR[MAIN.series].k} (${TAR[MAIN.series].d}); `), options: { bold: true, color: BLUE_DARK } },
      { text: L(`${TAR[OTHER.series].k}との比較は5．`, `${TAR[OTHER.series].k} in Section 5`) }],
    { x: RX, y, w: COL, h: 0.7, fontSize: CAP + 2 });
  if (!COSTA) y += 0.8;
  const halfR = (COL - 0.5) / 2, CH3 = BOTH ? 7.0 : COSTA ? 6.0 : 6.6;
  const seriesSets = BOTH ? [ET, CT] : [MAIN];
  const cats = BOTH ? LIMITS.flatMap((g) => seriesSets.map((X) => `${g}
${TAR[X.series].k}`)) : LIMITS.map((g) => `${g}`);
  const share = (X, g, w) => Math.round(X.get(g, w).bev_trip_share_pct * 10) / 10;
  s.addChart(pres.charts.BAR, SEN.map(([w, n]) => ({ name: n, labels: cats,
    values: BOTH ? LIMITS.flatMap((g) => seriesSets.map((X) => share(X, g, w))) : LIMITS.map((g) => share(MAIN, g, w)) })),
    { ...chart(), x: RX, y, w: halfR, h: CH3, barDir: "col", barGrouping: "clustered", barGapWidthPct: BOTH ? 40 : 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: BOTH ? 22 : 28, valAxisLabelFontSize: 26, legendFontSize: 28, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: BOTH ? L("受電上限 [kW]・電気料金", "Grid limit [kW], tariff") : L("受電上限 [kW]", "Grid limit [kW]"), catAxisTitleFontSize: 26, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: L("電気バス担当便 [%]", "Electric-bus trips [%]"), valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
  // Fig. 4: weekly total cost table (adopted solution; * = diesel-first adopted)
  const hd4 = (t, o = {}) => ({ text: t, options: { bold: true, align: "center", fill: { color: "F2F2F2" }, ...(EN ? { fontSize: BOTH ? 22 : 25 } : {}), ...o } });
  const c4 = (X, g, w) => { const r = X.get(g, w), ice = r.selected_start === "ice";
    return { text: `${tbl4(tc(r))}${ice ? "*" : ""}`, options: { align: "center", color: ice ? BLUE_DARK : INK, bold: ice } }; };
  let rows4, colW4, rh4;
  if (BOTH) {
    const kA = 1.55, kB = 0.75, cw = (halfR - kA - kB) / SE.length; rh4 = 0.66; colW4 = [kA, kB, ...SE.map(() => cw)];
    rows4 = [[hd4(L("受電上限", "Limit"), { colspan: 2 }), ...SEN.map(([, n]) => hd4(n))],
      ...LIMITS.flatMap((g) => seriesSets.map((X, i) => [
        ...(i === 0 ? [{ text: `${g} kW`, options: { bold: true, align: "center", rowspan: 2 } }] : []),
        { text: TAR[X.series].k, options: { bold: true, align: "center", color: SUB } }, ...SE.map(([w]) => c4(X, g, w))]))];
  } else {
    const k4 = EN ? 1.75 : 2.1, cw = (halfR - k4) / SE.length; rh4 = COSTA ? 0.88 : 1.0; colW4 = [k4, ...SE.map(() => cw)];
    rows4 = [[hd4(L("受電上限", "Limit")), ...SEN.map(([, n]) => hd4(n))],
      ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => c4(MAIN, g, w))])];
  }
  s.addTable(rows4, { x: RX + halfR + 0.5, y: y + 0.3, w: halfR, colW: colW4, fontSize: BOTH ? 26 : (EN ? 28 : 30), fontFace: FONT, color: INK,
    rowH: rh4, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  caption(BOTH ? L("図3　電気バスの担当便の割合（全1,704便/週）。A・Bは電気料金（表1）", "Fig. 3  Electric-bus share of the 1,704 weekly trips (A, B: tariff)")
    : COSTA ? L(`図3　電気バスの担当便の割合（1,704便/週）。${list(iceW(MAIN).map(lab))}以外は9割超`, `Fig. 3  Electric-bus share of 1,704 weekly trips; over 90% except ${list(iceW(MAIN).map(lab))}`) : L("図3　受電上限と電気バスの担当便の割合（全1,704便/週）", "Fig. 3  Share of the 1,704 weekly trips run by electric buses"), RX, y + CH3 + 0.05, halfR, 1.3, COSTA ? CAP - 2 : CAP);
  const y4 = y + 0.3 + rh4 * (rows4.length) + 0.15;
  caption(COSTA ? L("表3　1週間の総費用［万円］（CO₂の費用は含めない）。*は燃料バス優先の解", "Table 3  Total weekly cost [million JPY] (no CO₂ cost). * = diesel-first solution") : L("図4　1週間の総費用［万円］（CO₂の費用は含めない）。*は燃料バス優先の解", "Fig. 4  Total weekly cost [million JPY] (no CO₂ cost). * = diesel-first solution"),
    RX + halfR + 0.5, y4, halfR, y + CH3 + 1.4 - y4, CAP);
  if (y + CH3 + 1.4 - y4 < 1.2) throw new Error(`fig. 4 caption too short: ${y + CH3 + 1.4 - y4}`);
  y += CH3 + 1.5;
  if (COSTA) {
    // ---- variant a: why a higher grid limit is not cheaper under tariff A (all numbers computed from deck_data_rc42_et.json)
    const X = MAIN;
    const fuelOf = (r) => r.ice_fuel_consumed_l * 150;
    X.cases.forEach((r) => { const parts = r.vehicle_usage_cost + r.electricity_cost + r.contract_overage_cost + fuelOf(r) + r.basic_charge_week_jpy;
      if (Math.abs(parts - tc(r)) > 1) throw new Error(`cost parts do not add up: ${r.case}`); });
    const opx = (r) => tc(r) - r.basic_charge_week_jpy;
    const best = SE.map(([w]) => { const rs = LIMITS.map((g) => X.get(g, w)).sort((a, b) => tc(a) - tc(b)); return { w, r: rs[0], second: rs[1], worst: rs[rs.length - 1] }; });
    const gTop = LIMITS[LIMITS.length - 1];
    if (!best.every((b) => b.worst.grid_limit_kw === gTop)) throw new Error("the highest limit is not the most expensive in every season; rewrite the text");
    const bestTxt = (() => { const by = {}; best.forEach((b) => { (by[b.r.grid_limit_kw] = by[b.r.grid_limit_kw] || []).push(SEASON[b.w]); });
      return Object.entries(by).map(([g, ss]) => (EN ? `${g} kW in ${list(ss)}` : `${ss.join("・")}は${g} kW`)).join(L("、", ", ")); })();
    const flat = X.cases.filter((r) => r.grid_limit_kw >= best.find((b) => b.w === r.week).r.grid_limit_kw);
    const flatR = rngTxt(flat.map((r) => opx(r) / (EN ? 1e6 : 1e4)), EN ? 2 : 1);
    const bmin = X.get(LIMITS[0], W90).basic_charge_week_jpy, bmax = X.get(gTop, W90).basic_charge_week_jpy;
    const iw = iceW(X), bw = bevW(X);
    const PAIRS2 = LIMITS.flatMap((g) => SE.map(([w]) => ({ b: X.pair(g, w, "bev"), i: X.pair(g, w, "ice") })));
    const cheapN = PAIRS2.filter((p) => tc(p.b) < tc(p.i)).length, co2N = PAIRS2.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
    const allTxt = (n) => (n === PAIRS2.length ? L("すべてのケース", "every case") : L(`${n}ケース`, `${n} cases`));
    bullets([
      L(`電気バスの担当は、燃料バス優先が採用された${list(iw.map(lab))}（${rngTxt(iw.map((r) => r.bev_trip_share_pct))}%）を除く${bw.length}ケースで${rngTxt(bw.map((r) => r.bev_trip_share_pct), 1)}%（図3）`,
        `Electric buses ran ${rngTxt(bw.map((r) => r.bev_trip_share_pct), 1)}% of trips in ${bw.length} cases; at ${list(iw.map(lab))} (diesel-first adopted) ${rngTxt(iw.map((r) => r.bev_trip_share_pct))}% (Fig. 3)`),
      L(`受電上限が高いほど安いわけではない。総費用が最も小さいのは${bestTxt}で、${gTop} kWは全季節で最も大きい（表3）`,
        `A higher grid limit is not cheaper: the lowest total cost was at ${bestTxt}, and ${gTop} kW was the most expensive in every season (Table 3)`)],
      { x: RX, y, w: COL, h: 2.9, fontSize: EN ? 27 : 30, paraSpaceAfter: 4 });
    y += 3.0;
    void cheapN; void co2N; void allTxt;
    // Fig. 5: cost breakdown without the (nearly constant) vehicle-use cost
    const vehR = rngTxt(X.cases.map((r) => r.vehicle_usage_cost / (EN ? 1e6 : 1e4)), EN ? 2 : 0);
    const u = (v) => (EN ? Math.round(v / 1e3) : Math.round(v / 1e3) / 10);
    const cats5 = SE.flatMap(([w]) => LIMITS.map((g) => (EN ? `${g} ${SHORT[w]}` : `${g}${SHORT[w]}`)));
    const rows5 = SE.flatMap(([w]) => LIMITS.map((g) => X.get(g, w)));
    // banner above fig. 4 (2026-11-20, author): the bars leave out vehicle use, so state the full weekly total (4 million JPY range) right above them
    const totR = rngTxt(X.cases.map((r) => tc(r) / (EN ? 1e6 : 1e4)), EN ? 2 : 1);
    if (!X.cases.every((r) => tc(r) >= 4e6 && tc(r) < 5e6)) throw new Error("total cost left the 4-million-JPY range; rewrite the fig. 4 banner");
    s.addShape(pres.shapes.RECTANGLE, { x: RX, y: y - 0.1, w: COL, h: 1.05, fill: { color: "FFF4E0" }, line: { color: "E08A00", width: 2 } });
    text([{ text: L("総費用は全ケース", "Total cost in every case: "), options: {} },
      { text: L(`${totR}万円/週`, `${totR} million JPY/week`), options: { bold: true, color: "B35C00" } },
      { text: L(`（表3）。下の図は、そのうち車両使用費（${vehR}万円/週、ほぼ一定）を除いた残り`, ` (Table 3). The chart shows what remains after vehicle use (${vehR} million JPY/week, nearly constant)`), options: {} }],
      { x: RX + 0.15, y: y - 0.1, w: COL - 0.3, h: 1.05, fontSize: EN ? 24 : 25, valign: "middle", margin: 0 });
    y += 1.0;
    const CH5 = 3.8;
    s.addChart(pres.charts.BAR, [
      { name: L("電力量料金", "Energy"), labels: cats5, values: rows5.map((r) => u(r.electricity_cost)) },
      { name: L("基本料金", "Basic charge"), labels: cats5, values: rows5.map((r) => u(r.basic_charge_week_jpy)) },
      { name: L("燃料代", "Diesel"), labels: cats5, values: rows5.map((r) => u(fuelOf(r))) },
      { name: L("上限超過", "Excess"), labels: cats5, values: rows5.map((r) => u(r.contract_overage_cost)) }],
      { ...chart(), x: RX, y, w: COL, h: CH5, barDir: "col", barGrouping: "stacked", barGapWidthPct: 45, chartColors: ["7AB8E8", BLUE_DARK, GREY, "E08A00"],
        catAxisLabelFontSize: 22, valAxisLabelFontSize: 24, legendFontSize: 26, valAxisMinVal: 0, valAxisMaxVal: EN ? 600 : 60, valAxisMajorUnit: EN ? 100 : 10,
        showValAxisTitle: true, valAxisTitle: L("万円/週", "thousand JPY/week"), valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
    if (Math.max(...rows5.map((r) => u(r.electricity_cost) + u(r.basic_charge_week_jpy) + u(fuelOf(r)) + u(r.contract_overage_cost))) > (EN ? 600 : 60)) throw new Error("fig. 5 axis too short");
    y += CH5 + 0.05;
    const winterMost = LIMITS.filter((g) => g >= 200).every((g) => SE.every(([w]) => X.get(g, W90).electricity_cost >= X.get(g, w).electricity_cost));
    if (!winterMost) throw new Error("winter no longer has the largest energy charge; rewrite the fig. 4 caption");
    caption(L(`図4　車両使用費を除いた費用の内訳（料金A、採用した解）。基本料金は上限に比例し、電力量料金は日射の少ない冬が大きい`,
      `Fig. 4  Costs other than vehicle use (tariff A, adopted). Basic charge grows with the limit; energy is highest in winter`),
      RX, y, COL, 1.4, CAP);
    y += 1.5;
    // Fig. 5 (2026-11-19, Prof. Urabe): how the objective decreased before the time limit, adopted tariff-A solutions.
    // Left: Stage 1 LNS best weekly objective vs time (step function on a 5-min grid), excess over its final value,
    // median and maximum over the 12 adopted runs. Right: hourly re-plans that hit the 300 s limit - share that already
    // had a solution / their final solution at each time. Source: outcome/2026-11-12_three_party/cutoff_trajectory_rc42_et.json.
    const CUT = JSON.parse(require("fs").readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "cutoff_trajectory_rc42_et.json"), "utf8"));
    const adoptedRuns = CUT.runs.filter((r) => X.get(r.grid_limit_kw, r.week).selected_start === r.start);
    if (adoptedRuns.length !== 12) throw new Error("expected 12 adopted runs in the cutoff data");
    const MINS = Array.from({ length: 31 }, (_, i) => i * 5);
    const exc = (r, m) => { const tr = r.stage1.trajectory_sec_objective, fin = r.stage1.best_objective;
      const cur = tr.filter(([t]) => t <= m * 60); return ((cur.length ? cur[cur.length - 1][1] : tr[0][1]) - fin) / fin * 100; };
    const med = (a) => { const b = [...a].sort((x, y2) => x - y2), n = b.length; return n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2; };
    const r2 = (v) => Math.round(v * 100) / 100;
    const s1Med = MINS.map((m) => r2(med(adoptedRuns.map((r) => exc(r, m))))), s1Max = MINS.map((m) => r2(Math.max(...adoptedRuns.map((r) => exc(r, m)))));
    const late30 = Math.max(...adoptedRuns.map((r) => exc(r, r.stage1.elapsed_sec / 60 - 30)));
    const HL = adoptedRuns.flatMap((r) => r.hourly.time_limited_steps);
    const SECS = Array.from({ length: 31 }, (_, i) => i * 10);
    const pct = (f) => SECS.map((t) => Math.round(HL.filter((h) => f(h) !== null && f(h) <= t).length / HL.length * 1000) / 10);
    const by240 = HL.filter((h) => h.t_final_incumbent_s <= 240).length, gapMed = med(HL.map((h) => h.final_gap_pct));
    const half6 = (COL - 0.6) / 2, CH6 = 4.0;
    const lineOpt = (o) => ({ ...chart(), y, w: half6, h: CH6, lineDataSymbol: "none", lineSize: 3, catAxisLabelFontSize: 24, valAxisLabelFontSize: 24,
      legendFontSize: 24, showValAxisTitle: true, valAxisTitleFontSize: 22, valAxisTitleColor: SUB, showCatAxisTitle: true, catAxisTitleFontSize: 22, catAxisTitleColor: SUB, ...o });
    s.addChart(pres.charts.LINE, [{ name: L("中央値", "median"), labels: MINS.map(String), values: s1Med }, { name: L("最大", "max"), labels: MINS.map(String), values: s1Max }],
      lineOpt({ x: RX, chartColors: [BLUE_DARK, GREY], catAxisLabelFrequency: 6, valAxisMinVal: 0, valAxisTitle: L("最終値との差 [%]", "above final [%]"), catAxisTitle: L("便割当の探索時間 [分]", "assignment search [min]") }));
    s.addChart(pres.charts.LINE, [{ name: L("解あり", "any solution"), labels: SECS.map(String), values: pct((h) => h.t_first_incumbent_s) },
      { name: L("最終の解", "final solution"), labels: SECS.map(String), values: pct((h) => h.t_final_incumbent_s) }],
      lineOpt({ x: RX + half6 + 0.6, chartColors: ["7AB8E8", BLUE_DARK], catAxisLabelFrequency: 6, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 25, valAxisTitle: L("割合 [%]", "share [%]"), catAxisTitle: L("毎時の再計画の計算時間 [秒]", "hourly re-plan [s]") }));
    y += CH6 + 0.05;
    caption(L(`図5　時間で打ち切った計算の目的関数（料金A、採用した解）。左：便割当（${Math.round(adoptedRuns[0].stage1.time_budget_sec).toLocaleString("en-US")}秒で打ち切り）の1週間の目的関数の、最終値との差（12ケース）。右：毎時の再計画で時間切れになった${HL.length}回のうち、解と最終の解が見つかっていた割合`,
      `Fig. 5  Objective before the time limit (tariff A, adopted). Left: weekly assignment objective above its final value (12 cases, ${Math.round(adoptedRuns[0].stage1.time_budget_sec).toLocaleString("en-US")} s budget). Right: of the ${HL.length} hourly re-plans that hit the time limit, share with a solution and with their final solution`),
      RX, y, COL, 1.6, CAP - 2);
    y += 1.8;

    y = section(L("5．考察とまとめ", "5. Discussion and outlook"), RX, y, COL);
    const w200 = X.get(200, W90), b90 = X.pair(90, W90, "bev"), i90 = X.pair(90, W90, "ice");
    if (!(w200.contract_over_limit_kwh > 0) || !(tc(i90) < tc(b90))) throw new Error("winter shortfall text no longer matches the data");
    const bestW = best.find((b) => b.w === W90).r.grid_limit_kw;
    if (X.get(bestW, W90).contract_over_limit_kwh > 1e-6) throw new Error(`winter excess at ${bestW} kW; rewrite d3`);
    const sh = rngTxt(LIMITS.includes(bestW) ? SE.map(([w]) => X.get(bestW, w).bev_trip_share_pct) : [], 1);
    const save = avgAt(X, gTop) - avgAt(X, bestW);
    const near = best.map((b) => tc(b.second) - tc(b.r)), gapMin = Math.min(...best.map((b) => gapOf(X, b.r)));
    const nearIn = near.every((d) => d < gapMin);
    const DH = 6.7;
    bullets([
      L(`基本料金は受電上限に比例し（${LIMITS[0]} kW ${money(bmin)}万〜${gTop} kW ${money(bmax)}万円/週）、車両使用費などそれ以外の費用は上限が足りれば${flatR}万円/週でほぼ同じ。足りないと、冬200 kWは超過${fmtN(w200.contract_over_limit_kwh)} kWh（${money(w200.contract_overage_cost)}万円/週）、冬90 kWは燃料バスが増え、CO₂は電気バス優先の解の約${(i90.total_co2_kg / b90.total_co2_kg).toFixed(1)}倍`,
        `The basic charge grows with the limit (${money(bmin)} at ${LIMITS[0]} kW to ${money(bmax)} thousand JPY/week at ${gTop} kW); other costs, including vehicle use, stay at ${flatR} million JPY/week once the limit suffices. Too low a limit adds ${fmtN(w200.contract_over_limit_kwh)} kWh of excess at 200 kW in winter (${money(w200.contract_overage_cost)} thousand JPY/week), or, at 90 kW in winter, more diesel and about ${(i90.total_co2_kg / b90.total_co2_kg).toFixed(1)} times the CO₂ of the electric-first solution`),
      L(`運用の目安（今回の条件）：受電上限は大きく取らず、充電の時間をずらして、冬に超過が出ない${bestW} kWに抑える。電気バスは全季節で${sh}%の便を担当でき、${gTop} kWより約${money(save)}万円/週安い（3季節平均）${nearIn ? `。200 kWとの差はギャップ5%（約${money(gapMin)}万円/週）より小さい` : ""}`,
        `Operating guidance (these conditions): keep the limit small and spread charging, at ${bestW} kW where winter has no excess; electric buses still ran ${sh}% of trips, about ${money(save)} thousand JPY/week cheaper than ${gTop} kW${nearIn ? `. The difference from 200 kW is below the 5% gap (about ${money(gapMin)} thousand JPY/week)` : ""}`),
      L(`時間で打ち切った計算も、目的関数は打ち切り前にほぼ下げ止まった（図5）。便割当は最後の30分の改善が${late30.toFixed(2)}%以下、毎時の再計画は${HL.length}回中${by240}回が240秒までに最終の解に達した。ただし下限との差（ギャップ、中央値${Math.round(gapMed)}%）は残り、最適とは言えない。基本料金と受電上限も一緒に最適化するのが今後の課題`,
        `Runs cut by the time limit had nearly stopped improving (Fig. 5): the assignment improved by at most ${late30.toFixed(2)}% in its last 30 min, and ${by240} of ${HL.length} timed-out re-plans had their final solution by 240 s. The gap to the bound remains (median ${Math.round(gapMed)}%), so this is not optimality. Optimizing the basic charge and the limit together is next`)],
      { x: RX, y, w: COL, h: DH, fontSize: EN ? 25 : 28, paraSpaceAfter: 4 });
    y += DH + 0.1;
  } else {
  let resB;
  if (BOTH) {
    const shareAll = [...bevW(ET), ...bevW(CT)].map((r) => r.bev_trip_share_pct), iceAll = [...iceW(ET), ...iceW(CT)].map((r) => r.bev_trip_share_pct);
    resB = [L(`A・Bとも、燃料バス優先が採用されたケース（A：${list(iceW(ET).map(lab))}、B：${list(iceW(CT).map(lab))}）を除き、電気バスが全便の${rngTxt(shareAll, 1)}%を担当`,
      `With both tariffs, electric buses ran ${rngTxt(shareAll, 1)}% of trips, except where the diesel-first solution was adopted (A: ${list(iceW(ET).map(lab))}; B: ${list(iceW(CT).map(lab))})`),
      L(`燃料バス優先が採用されたケースでは、電気バスの担当は${rngTxt(iceAll)}%`, `Where diesel-first was adopted, electric buses ran ${rngTxt(iceAll)}% of trips`)];
  } else {
    const iw = iceW(MAIN), bw = bevW(MAIN);
    resB = [L(`燃料バス優先が採用された${list(iw.map(lab))}を除く${bw.length}ケースでは、電気バスが全便の${rngTxt(bw.map((r) => r.bev_trip_share_pct), 1)}%を担当`,
      `In the ${bw.length} cases other than ${list(iw.map(lab))}, electric buses ran ${rngTxt(bw.map((r) => r.bev_trip_share_pct), 1)}% of trips`),
      L(`${list(iw.map(lab))}では、燃料バスを多く使う解の方が安く、電気バスの担当は${rngTxt(iw.map((r) => r.bev_trip_share_pct))}%`,
        `At ${list(iw.map(lab))}, using more diesel buses was cheaper; electric buses ran ${rngTxt(iw.map((r) => r.bev_trip_share_pct))}% of trips`)];
  }
  bullets(resB, { x: RX, y, w: COL, h: 3.0, fontSize: BOTH || EN ? 31 : BODY, paraSpaceAfter: 4 });
  y += 3.1;
  text([{ text: L("2通りの初期割当　", "Two initial assignments  "), options: { bold: true, color: BLUE_DARK } },
    { text: L("便割当は最適解と確かめられないため、「電気バス優先」と「燃料バス優先」の2通りから解き、総費用の安い方を採用した（図5）",
      "The assignment cannot be proven optimal, so we solve from an electric-first and a diesel-first start and keep the cheaper result (Fig. 5).") }],
    { x: RX, y, w: COL, h: 2.2, fontSize: BODY });
  y += 2.3;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => PAIRS.push({ label: EN ? `${g} ${SHORT[w]}` : `${g}${SHORT[w]}`, g, w })));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2, CH5 = 6.0;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: CH5, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: BOTH ? 16 : 20, legendFontSize: 24, catAxisLabelFontSize: 22, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 22, valAxisTitleFontSize: 24, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  const dval = (X, p) => { const d = tc(X.pair(p.g, p.w, "bev")) - tc(X.pair(p.g, p.w, "ice")); return EN ? Math.round(d / 1e3) : Math.round(d / 1e3) / 10; };
  const LIM = EN ? 800 : 80;
  seriesSets.forEach((X) => PAIRS.forEach((p) => { if (Math.abs(dval(X, p)) > LIM) throw new Error(`fig. 5 axis too short: ${dval(X, p)}`); }));
  s.addChart(pres.charts.BAR, seriesSets.map((X) => ({ name: BOTH ? L(`電気料金${TAR[X.series].k}`, `Tariff ${TAR[X.series].k}`) : L("電気バス優先 − 燃料バス優先", "Electric-first − diesel-first"),
    labels: pcats, values: PAIRS.map((p) => dval(X, p)) })),
    pairChart({ x: RX, chartColors: BOTH ? [BLUE_DARK, "7AB8E8"] : [BLUE_DARK], dataLabelFormatCode: EN ? "+0;-0" : "+0.0;-0.0", valAxisMinVal: -LIM, valAxisMaxVal: LIM,
      valAxisMajorUnit: LIM / 2, catAxisLabelPos: "low", valAxisTitle: L("費用の差 [万円/週]", "Cost difference [thousand JPY/week]") }));
  const C5 = BOTH ? ET : MAIN;
  s.addChart(pres.charts.BAR, [
    { name: L("電気バス優先", "Electric-first"), labels: pcats, values: PAIRS.map((p) => Math.round(C5.pair(p.g, p.w, "bev").total_co2_kg / 100) / 10) },
    { name: L("燃料バス優先", "Diesel-first"), labels: pcats, values: PAIRS.map((p) => Math.round(C5.pair(p.g, p.w, "ice").total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: L("CO₂ [t/週]", "CO₂ [t/week]") }));
  y += CH5 + 0.05;
  const cnt = (X) => ({ cheap: PAIRS.filter((p) => tc(X.pair(p.g, p.w, "bev")) < tc(X.pair(p.g, p.w, "ice"))).length,
    co2: PAIRS.filter((p) => X.pair(p.g, p.w, "bev").total_co2_kg < X.pair(p.g, p.w, "ice").total_co2_kg).length });
  const every = (n) => (n === PAIRS.length ? L("すべてのケース", "every case") : L(`${PAIRS.length}ケース中${n}ケース`, `${n} of ${PAIRS.length} cases`));
  let cap5;
  if (BOTH) {
    const a = cnt(ET), b = cnt(CT);
    cap5 = L(`図5　2通りの初期割当から得た解の比較。左は総費用の差（負なら電気バス優先の方が安い）、右はAのCO₂。CO₂はA・Bとも${a.co2 === b.co2 ? every(a.co2) : `${every(a.co2)}（A）・${every(b.co2)}（B）`}で電気バス優先の方が少なく、費用は${a.cheap}ケース（A）・${b.cheap}ケース（B）で電気バス優先の方が安い`,
      `Fig. 5  Solutions from the two initial assignments: total-cost difference (left; negative = electric-first cheaper) and CO₂ under A (right). Electric-first emitted less CO₂ in ${a.co2 === b.co2 ? every(a.co2) : `${every(a.co2)} (A), ${every(b.co2)} (B)`} with both tariffs and was cheaper in ${a.cheap} (A) and ${b.cheap} (B) cases. W, Sp, Su: winter, spring, summer`);
  } else {
    const a = cnt(MAIN);
    cap5 = L(`図5　2通りの初期割当から得た解の比較。左は総費用の差（負なら電気バス優先の方が安い）、右はCO₂。CO₂は${every(a.co2)}で電気バス優先の方が少なく、費用は${a.cheap}ケースで電気バス優先の方が安い`,
      `Fig. 5  Solutions from the two initial assignments: total-cost difference (left; negative = electric-first cheaper) and CO₂ (right). Electric-first emitted less CO₂ in ${every(a.co2)} and was cheaper in ${a.cheap}. W, Sp, Su: winter, spring, summer`);
  }
  caption(cap5, RX, y, COL, 2.0, CAP);
  y += 2.1;

  // ---------------- discussion (computed from the rc42 data)
  y = section(L("5．考察とまとめ", "5. Discussion and outlook"), RX, y, COL);
  // W90 is defined at the top (2026-11-19)
  const p90 = (X) => { const b = X.pair(90, W90, "bev"), i = X.pair(90, W90, "ice");
    if (!(tc(i) < tc(b))) throw new Error(`${X.series}: 90 kW winter diesel-first is not cheaper; rewrite the discussion`);
    return { save: tc(b) - tc(i), ratio: i.total_co2_kg / b.total_co2_kg }; };
  const flips = LIMITS.flatMap((g) => SE.map(([w]) => ET.get(g, w)).filter((r) => r.selected_start !== CT.get(r.grid_limit_kw, r.week).selected_start));
  if (flips.length > 2) throw new Error(`more tariff flips than the text handles: ${flips.length}`);
  const gapMax = Math.max(...flips.map((r) => Math.max(gapOf(ET, ET.get(r.grid_limit_kw, r.week)), gapOf(CT, CT.get(r.grid_limit_kw, r.week)))));
  const flipsInsideGap = flips.every((r) => pdiff(ET, r.grid_limit_kw, r.week) < gapOf(ET, r) && pdiff(CT, r.grid_limit_kw, r.week) < gapOf(CT, CT.get(r.grid_limit_kw, r.week)));
  const d1 = (() => {
    if (BOTH) { const a = p90(ET), b = p90(CT);
      return L(`受電上限に余裕があれば、電動化で費用もCO₂も下がる。90 kW冬では燃料バス中心の方が約${money(a.save)}万円（A）・${money(b.save)}万円（B）/週安いが、CO₂は約${a.ratio.toFixed(1)}倍・${b.ratio.toFixed(1)}倍になる`,
        `With enough grid headroom, electrification lowers both cost and CO₂. At 90 kW in winter, the diesel-heavy solution saved about ${money(a.save)} (A) and ${money(b.save)} (B) thousand JPY a week but emitted about ${a.ratio.toFixed(1)} and ${b.ratio.toFixed(1)} times the CO₂`); }
    const a = p90(MAIN);
    return L(`受電上限に余裕があれば、電動化で費用もCO₂も下がる。90 kW冬では燃料バス中心の方が約${money(a.save)}万円/週安いが、CO₂は約${a.ratio.toFixed(1)}倍になる`,
      `With enough grid headroom, electrification lowers both cost and CO₂. At 90 kW in winter, the diesel-heavy solution saved about ${money(a.save)} thousand JPY a week but emitted about ${a.ratio.toFixed(1)} times the CO₂`);
  })();
  const gapTxt = flipsInsideGap ? L(`。差はいずれもギャップ5%（約${money(gapMax)}万円/週）より小さく、どちらが安いとは言い切れない`,
    `, both below the 5% gap (about ${money(gapMax)}), so neither is clearly cheaper`) : "";
  const fdiff = (r) => L(`A ${money(pdiff(ET, r.grid_limit_kw, r.week))}万円・B ${money(pdiff(CT, r.grid_limit_kw, r.week))}万円/週`,
    `A ${money(pdiff(ET, r.grid_limit_kw, r.week))}, B ${money(pdiff(CT, r.grid_limit_kw, r.week))} thousand JPY/week`);
  const d2 = (() => {
    if (!flips.length) return L("電気料金をA・Bのどちらにしても、採用される解はすべてのケースで同じ", "Every case adopted the same solution under tariffs A and B");
    const fl = list(flips.map(lab)), r = flips[0];
    const m = MAIN.get(r.grid_limit_kw, r.week).selected_start, o = OTHER.get(r.grid_limit_kw, r.week).selected_start;
    if (BOTH) return L(`A・Bで採用が分かれたのは${fl}だけ（A：${sel(ET.get(r.grid_limit_kw, r.week).selected_start)}、B：${sel(CT.get(r.grid_limit_kw, r.week).selected_start)}）。2つの解の差は${flips.map(fdiff).join("、")}${gapTxt}`,
      `The tariffs adopted different solutions only at ${fl} (A: ${sel(ET.get(r.grid_limit_kw, r.week).selected_start)}, B: ${sel(CT.get(r.grid_limit_kw, r.week).selected_start)}). The two solutions differ by ${flips.map(fdiff).join("; ")}${gapTxt}`);
    return L(`比較：電気料金を${TAR[OTHER.series].k}（${TAR[OTHER.series].d}）にすると、${fl}で採用される解が${sel(m)}から${sel(o)}に変わる（他の${12 - flips.length}ケースは同じ）。2つの解の差は${flips.map(fdiff).join("、")}${gapTxt}`,
      `Comparison: with tariff ${TAR[OTHER.series].k}, the adopted solution at ${fl} changes from ${sel(m)} to ${sel(o)}; the other ${12 - flips.length} cases are unchanged. The two differ by ${flips.map(fdiff).join("; ")}${gapTxt}`);
  })();
  const gHi = LIMITS[LIMITS.length - 1], gMid = LIMITS[LIMITS.length - 2];
  const hiMid = (X) => avgAt(X, gHi) - avgAt(X, gMid);
  const basicDiff = ET.get(gHi, W90).basic_charge_week_jpy - ET.get(gMid, W90).basic_charge_week_jpy;
  const d3 = (() => {
    const aTxt = L(`Aでは約${money(hiMid(ET))}万円/週（基本料金の差${money(basicDiff)}万円/週とほぼ同じ）`, `about ${money(hiMid(ET))} thousand JPY/week under A (close to the ${money(basicDiff)} thousand JPY/week difference in basic charge)`);
    const bTxt = L(`Bでは約${money(hiMid(CT))}万円/週`, `about ${money(hiMid(CT))} under B`);
    const head = L(`${gHi} kWと${gMid} kWの総費用の差（3季節の平均）は、`, `The total cost at ${gHi} kW exceeds that at ${gMid} kW (mean of three seasons) by `);
    if (BOTH) return head + aTxt + L("、", " and ") + bTxt + L("。基本料金の扱いで、受電上限を上げる費用の見え方が変わる", ". How the basic charge is counted changes the cost of a higher grid limit");
    return MAIN.series === "et" ? head + aTxt + L(`。${TAR.ct.k}では${money(hiMid(CT))}万円/週`, `; under ${TAR.ct.k}, ${money(hiMid(CT))}`)
      : head + bTxt + L(`。基本料金を上限から別に数える${TAR.et.k}では${money(hiMid(ET))}万円/週`, `; under ${TAR.et.k}, which counts the basic charge from the limit, ${money(hiMid(ET))}`);
  })();
  const DH = 6.4;
  bullets([d1, d2, d3], { x: RX, y, w: COL, h: DH, fontSize: EN ? 28 : BODY - 2, paraSpaceAfter: EN ? 4 : 6 });
  y += DH + 0.1;
  if (process.env.POSTER_DUMP) console.log(JSON.stringify({ VARIANT, LANG, resB, d1, d2, d3, cap5 }, null, 1));
  }
  const steps = EN ? [["Mar 2027", "IEEJ National Convention", "this work: grid limit vs electric-bus trips, cost, CO₂"],
    ["FY2027", "Conference papers", "multi-day planning, battery optimization, price and CO₂-factor sensitivity"],
    ["Nov 2027", "Master's midterm", "gains over day-by-day planning (morning shortfall, trips moved to diesel, night grid use)"],
    ["Feb 2028", "Master's final", "guidance on grid limit, battery and chargers across seasons"]]
    : [["2027年3月", "電気学会全国大会", "本発表の内容（受電上限と電気バスの担当便・費用・CO₂）"],
      ["2027年度", "学会発表（数回）", "日をまたぐ計画、蓄電池の充放電の最適化、単価・CO₂係数の感度"],
      ["2027年11月", "中間発表", "日ごとの計画と比べた効果（翌朝の電池不足、燃料バスへの振替、夜の買電）"],
      ["2028年2月", "修士最終発表", "受電上限・蓄電池・充電器の決め方の指針（季節を通した評価）"]];
  const sw = (COL - 0.6) / 4, bh = FOOT - 0.8 - y;
  if (bh < 2.6) throw new Error(`road-map boxes too short: ${bh}`);
  steps.forEach(([when, where, what], i) => {
    const x = RX + i * (sw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: bh, fill: { color: i === 3 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } },
      { text: what, options: { fontSize: EN ? 22 : 24, color: SUB } }], { x: x + 0.12, y: y + 0.08, w: sw - 0.24, h: bh - 0.12, fontSize: EN ? 24 : 26, align: "center", lineSpacingMultiple: 1.0 });
  });
  caption(COSTA ? L("図6　修士最終発表までの予定と、それぞれで目指す成果", "Fig. 6  Road to the master's final and the planned outcome of each step")
    : L("図6　修士最終発表までの予定と、それぞれで目指す成果", "Fig. 6  Road to the master's final and the planned outcome of each step"), RX, y + bh + 0.05, COL, 0.65, CAP);

  // ---------------- footer (full width)
  const retries = [...ET.D.first_attempt_failures.map((f) => ["A", f]), ...(COSTA ? [] : CT.D.first_attempt_failures.map((f) => ["B", f]))].map(([k, f]) => {
    const m = /^rc42\/(et|ct)([bi])(\d{3})\/(\d{4}-\d{2}-\d{2})$/.exec(f.case);
    if (!m || !/memory_limit at 14 GiB; rerun once at 24 GiB/.test(f.reason)) throw new Error(`unexpected first-attempt failure: ${JSON.stringify(f)}`);
    return { k, g: Number(m[3]), w: m[4], st: m[2] === "b" ? "bev" : "ice" }; });
  const sts = [...new Set(retries.map((r) => r.st))];
  const retryTxt = (EN ? retries.map((r) => `${r.k} ${r.g} kW ${SEASON[r.w]}`).join(", ") : retries.map((r) => `${r.k} ${r.g} kW${SEASON[r.w]}`).join("、"))
    + (sts.length === 1 ? L(`（いずれも${sel(sts[0])}）`, ` (all ${sel(sts[0])})`) : "");
  const steps0 = Math.min(ET.steps[0], CT.steps[0]), steps1 = Math.max(ET.steps[1], CT.steps[1]);
  if (COSTA) caption(L(`注：数値はいずれも診断用（DIAGNOSTIC）で、研究の結論にはまだ用いない。便割当は最適解と確かめられておらず、2段階で解くため全体としての最適解でもない。蓄電池は規則で充放電し、最適化していない。数値は rc42（19dc0780）の料金Aの24計算（12ケース×初期割当2通り）で、すべて検証を通過。${retries.map((r) => `${r.g} kW${SEASON[r.w]}・${sel(r.st)}`).join("、")}は1回目が前日計画のメモリ上限（14 GiB）で止まり、24 GiBで1回だけ計算し直した。毎時の再計画は最大${ET.maxTimeouts}回（${ET.steps[0]}〜${ET.steps[1]}回中）が時間切れ。季節は代表1週ずつ・各1回の計算で、季節差の統計的な有意性は確かめていない（秋は春で代表）。電費は距離×平均の値で、冷暖房の季節変化は入れていない。`,
    `Note: all figures are DIAGNOSTIC and not yet used for research conclusions. The assignment is not proven optimal, and solving in two stages does not give a global optimum. The battery follows a rule and is not optimized. Numbers are from rc42 (19dc0780): the 24 tariff-A runs (12 cases × 2 initial assignments), all passing verification. ${retries.map((r) => `${r.g} kW ${SEASON[r.w]} ${sel(r.st)}`).join(", ")} stopped at the day-ahead memory limit (14 GiB) on the first attempt and was rerun once at 24 GiB. Up to ${ET.maxTimeouts} of the ${ET.steps[0]}–${ET.steps[1]} hourly re-plans timed out. One week per season, solved once (no significance test; spring stands for autumn); energy use is distance × an average rate, without seasonal heating or cooling.`),
    M, FOOT + 0.2, W, 1.5, 20);
  else caption(L(`注：数値はいずれも診断用（DIAGNOSTIC）で、研究の結論にはまだ用いない。便割当は最適解と確かめられておらず、2段階で解くため全体としての最適解でもない。蓄電池は規則で充放電し、最適化していない。数値は rc42（19dc0780）の48計算（電気料金2通り×12ケース×初期割当2通り）で、すべて検証を通過。${retryTxt}の${retries.length}計算は1回目が前日計画のメモリ上限（14 GiB）で止まり、24 GiBで1回だけ計算し直した。毎時の再計画は最大${ET.maxTimeouts}回（A）・${CT.maxTimeouts}回（B）（${steps0}〜${steps1}回中）が時間切れ。`,
    `Note: all figures are DIAGNOSTIC and not yet used for research conclusions. The assignment is not proven optimal, and solving in two stages does not give a global optimum. The battery follows a rule and is not optimized. Numbers are from rc42 (19dc0780): 48 runs (2 tariffs × 12 cases × 2 initial assignments), all passing verification. ${retryTxt} stopped at the day-ahead memory limit (14 GiB) on the first attempt and were rerun once at 24 GiB. Up to ${ET.maxTimeouts} (A) and ${CT.maxTimeouts} (B) of the ${steps0}–${steps1} hourly re-plans timed out.`),
    M, FOOT + 0.2, W, 1.15, 20);
  text([{ text: L("参考文献　", "References  "), options: { bold: true } },
    { text: L("［1］環境省・経済産業省：算定方法及び排出係数一覧（2025年版）　［2］W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018　［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）　［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0　［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998　［6］東京電力エナジーパートナー：高圧の電気料金（ベーシックプラン、2026年4月1日実施）　［7］首相官邸：第203回国会における菅内閣総理大臣所信表明演説（2020年10月26日）　［8］国土交通省：運輸部門における二酸化炭素排出量",
      "[1] Ministry of the Environment and METI: Calculation methods and emission factors (2025)  [2] W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018  [3] Open Data Challenge for Public Transportation: Tokyu Bus timetable (ODPT)  [4] Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0  [5] P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998  [6] TEPCO Energy Partner: high-voltage electricity rates (Basic plan, from 1 Apr 2026)  [7] Prime Minister's Office of Japan: policy speech to the 203rd Diet session (26 Oct 2020)  [8] MLIT: CO₂ emissions in the transport sector") }],
    { x: M, y: FOOT + (COSTA ? 1.75 : 1.45), w: W, h: 45.55 - FOOT - (COSTA ? 1.75 : 1.45), fontSize: 18, color: SUB });

  // Numbers for the talk scripts (printed by the build so the scripts can be checked against the poster).
};
