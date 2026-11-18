// English twin of poster_layout_v4_ja.js (2026-11-18, Prof. Urabe's comments on the v3 English preview):
// larger type, no abstract, author block filled in, same cuts as the Japanese v4 (same data and numbers as v3).
// Romanizations and English names of the graduate school, major and laboratory are drafts for the user to confirm.
module.exports = function layout(c) {
  const { FONT, s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    cases, LIMITS, SE, val, pairOf, iceWins, bevWins, fmt, pb90, pi90, eqSize, maxTimeouts } = c;
  const rngTxt = (a, d) => c.rngTxt(a, d).replace("〜", "–"), versions = c.versions.split("・").join(", ");
  const NUM = 7.87, BODY = 32, CAP = 26;
  const FOOT = 43.0;
  const SEASON = { "2025-01-06": "winter", "2025-04-07": "spring", "2025-07-07": "summer" };
  const SHORT = { "2025-01-06": "W", "2025-04-07": "Sp", "2025-07-07": "Su" };
  const SEN = SE.map(([w]) => [w, SEASON[w][0].toUpperCase() + SEASON[w].slice(1)]);
  const lab = (r) => `${r.grid_limit_kw} kW ${SEASON[r.week]}`;
  const list = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`);
  const mJ = (v) => (v / 1e6).toFixed(2); // million JPY
  const kJ = (v) => Math.round(v / 1e3); // thousand JPY
  const tc = (r) => r.total_cost_reported; // CO2 cost excluded from every reported total
  const bullets = (items, o) => text(items.map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } })), o);

  // ---------------- header
  text("Trip Assignment and Charging Optimization\nfor Electric Buses Operated Alongside\nDiesel Buses toward GX", { x: M + NUM, y: M - 0.1, w: W - NUM, h: 3.3, fontSize: 60, bold: true, valign: "middle", lineSpacingMultiple: 1.0 });
  text([{ text: "LIU Chengyang", options: { bold: true, color: INK } }, { text: " (M1), Electric Power System Laboratory, Tokyo City University", options: { breakLine: true } },
    { text: "Electrical Engineering and Chemistry, Graduate School of Integrative Science and Engineering", options: { breakLine: true } },
    { text: "Supervisor: Assoc. Prof. C. Urabe    Co-examiners: Prof. T. Nakajima, Assoc. Prof. T. Hirano" }],
    { x: M + NUM, y: M + 3.25, w: W - NUM, h: 1.6, fontSize: 28, color: SUB, lineSpacingMultiple: 1.05 });
  const RULE = M + 4.95;
  s.addShape(pres.shapes.LINE, { x: M, y: RULE, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const TOP = RULE + 0.35;

  // ---------------- left column
  let y = TOP;
  y = section("1. Background and aim", LX, y, COL);
  const BOXH = 5.0;
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: BOXH, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text([
    ...["Transport emits 19.3% of Japan's CO₂ (FY2024) [8]", "Toward carbon neutrality by 2050 [7], route buses are being electrified",
      "Fleets cannot be replaced at once; electric and diesel buses run together", "Charging many buses at the depot at once raises its grid power"]
      .map((t) => ({ text: t, options: { bullet: { code: "25B6" }, breakLine: true } })),
    { text: "Aim  ", options: { bold: true, color: BLUE_DARK } },
    { text: "Cut CO₂ by electrification (GX) while keeping today's timetable and limiting grid power", options: { bold: true } }],
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: BOXH - 0.3, fontSize: BODY - 2, paraSpaceAfter: 4 });
  y += BOXH + 0.35;

  y = section("2. Method", LX, y, COL);
  text([{ text: "Decisions  ", options: { bold: true, color: BLUE_DARK } },
    { text: "which bus, electric or diesel, runs each trip, and when and at how many kW each electric bus charges. Every timetabled trip is run." }],
    { x: LX, y, w: COL, h: 1.5, fontSize: BODY });
  y += 1.6;
  text([{ text: "Objective  ", options: { bold: true, color: BLUE_DARK } }, { text: "minimize the total cost of one week" }], { x: LX, y, w: COL, h: 0.75, fontSize: BODY });
  y += 0.85;
  const EQW = COL * 0.84, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: "Objective: minimize vehicle use, electricity with the excess over the grid limit, diesel, and the CO2 cost" });
  y += EQH + 0.15;
  caption("From left: vehicle use, electricity and excess over the grid limit, diesel, CO₂. Main constraints: trip connection (arrival + turnaround + deadhead ≤ next departure), battery level, 10 chargers, grid limit", LX, y, COL, 1.7, CAP);
  y += 1.8;
  flowDiagram(s, pres, LX, y, COL, [
    ["1 Assignment", ["1,704 trips to 60 buses", "partial re-solving [5]"]],
    ["2 Day-ahead", ["charging every 15 min", "PV from normals [2]"]],
    ["3 Hourly re-plan", ["re-planned each hour with actual sunshine"]],
    ["4 Accounting", ["cost and CO₂ of what was executed"]]], FONT, 3.4, 24);
  caption("Fig. 1  Calculation flow (solver: Gurobi [4]). The battery follows a fixed rule", LX, y + 3.5, COL, 0.65, CAP);
  y += 4.3;
  const params = [["Electricity", "17.43 JPY/kWh + basic charge [6]; comparison: 30 JPY/kWh incl. basic charge"], ["Diesel", "150 JPY/L, 2.62 kg-CO₂/L [1]"],
    ["Grid CO₂", "0.5 kg/kWh (tentative); CO₂ cost 1 JPY/kg"], ["Vehicle use", "20,000 JPY per bus-day"], ["Excess over limit", "500 JPY/kWh (tentative)"]];
  const tbl = (rowsIn, x, yy, w, k, fs, rh) =>
    s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
      { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: FONT, color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  const prh = params.map(([k]) => (k === "Electricity" ? 1.15 : 0.66));
  tbl(params, LX, y, COL, 4.3, CAP, prh);
  y += prh.reduce((a, b) => a + b, 0) + 0.15;
  caption("Table 1  Values used (tentative values to be tested for sensitivity). The CO₂ cost is in the objective only, not in reported totals. Time step 15 min; stopped at a 5% gap", LX, y, COL, 1.4, CAP);
  y += 1.55;

  y = section("3. Case study", LX, y, COL);
  const MAPW = COL * 0.52, MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, "route_map_en_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH, altText: "Routes Shibu 21, 22 and 23 and the Tsurumaki depot" });
  y += MAPH + 0.1;
  caption("Fig. 2  Routes and the Tsurumaki depot (stop positions from ODPT [3], joined by straight lines; background © OpenStreetMap contributors)", LX, y, COL, 1.4, CAP);
  y += 1.5;
  const study = [["Service", "Tokyu Bus routes Shibu 21–23 (Tsurumaki depot), 1,704 trips/week"], ["Fleet, equipment", "35 electric and 25 diesel buses; 10 × 90 kW chargers; 1,000 kW PV; 6,000 kWh battery"],
    ["Cases", "grid limit 90, 200, 400, 900 kW × one week in winter, spring, summer (from 6 Jan, 7 Apr, 7 Jul 2025, actual sunshine) = 12 cases"]];
  tbl(study, LX, y, COL, 3.4, CAP, [1.15, 1.15, 1.15]);
  y += 3 * 1.15 + 0.15;
  caption("Table 2  Case-study conditions", LX, y, COL, 0.65, CAP);
  y += 0.7;
  if (y > FOOT) throw new Error(`left column overflows: ${y}`);

  // ---------------- right column
  y = TOP;
  y = section("4. Results", RX, y, COL);
  const halfR = (COL - 0.5) / 2, cats = LIMITS.map((g) => `${g}`), CH3 = 6.6;
  s.addChart(pres.charts.BAR, SEN.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
    { ...chart(), x: RX, y, w: halfR, h: CH3, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: 28, valAxisLabelFontSize: 26, legendFontSize: 28, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: "Grid limit [kW]", catAxisTitleFontSize: 26, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: "Electric-bus trips [%]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
  const T4 = halfR, k4 = 1.75, cw4 = (T4 - k4) / SE.length, rh4 = 1.0;
  const hd4 = (t) => ({ text: t, options: { bold: true, align: "center", fontSize: 25, fill: { color: "F2F2F2" } } });
  const c4 = (g, w) => { const r = cases.find((x) => x.grid_limit_kw === g && x.week === w);
    return { text: r ? `${mJ(tc(r))}${r.selected_start === "ice" ? "*" : ""}` : "—", options: { align: "center", color: r && r.selected_start === "ice" ? BLUE_DARK : INK, bold: !!(r && r.selected_start === "ice") } }; };
  s.addTable([[hd4("Limit"), ...SEN.map(([, n]) => hd4(n))],
    ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => c4(g, w))])],
    { x: RX + halfR + 0.5, y: y + 0.3, w: T4, colW: [k4, ...SE.map(() => cw4)], fontSize: 28, fontFace: FONT, color: INK,
      rowH: rh4, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  caption("Fig. 3  Share of the 1,704 weekly trips run by electric buses", RX, y + CH3 + 0.05, halfR, 1.3, CAP);
  const y4 = y + 0.3 + rh4 * (LIMITS.length + 1) + 0.15;
  caption("Fig. 4  Total weekly cost [million JPY] (vehicle use, electricity, diesel, excess; no CO₂ cost). * = diesel-first solution", RX + halfR + 0.5, y4, halfR, y + CH3 + 1.4 - y4, CAP);
  y += CH3 + 1.5;
  bullets([`At 400 kW and above: electric buses ran ${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}% of trips at a lower total cost`,
    `At ${list(iceWins.map(lab))}: using more diesel buses was cheaper; electric buses ran ${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}% of trips`],
    { x: RX, y, w: COL, h: 3.0, fontSize: BODY, paraSpaceAfter: 6 });
  y += 3.1;
  text([{ text: "Two initial assignments  ", options: { bold: true, color: BLUE_DARK } },
    { text: "The assignment cannot be proven optimal, so we solve from an electric-first and a diesel-first start and keep the cheaper result (Fig. 5)." }],
    { x: RX, y, w: COL, h: 2.2, fontSize: BODY });
  y += 2.3;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g} ${SHORT[w]}`, b, i }); }));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2, CH5 = 7.0;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: CH5, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 20, legendFontSize: 24, catAxisLabelFontSize: 22, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 22, valAxisTitleFontSize: 24, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  s.addChart(pres.charts.BAR, [{ name: "Electric-first − diesel-first", labels: pcats, values: PAIRS.map((p) => kJ(tc(p.b) - tc(p.i))) }],
    pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0;-0", valAxisMinVal: -600, valAxisMaxVal: 600, valAxisMajorUnit: 300, catAxisLabelPos: "low", valAxisTitle: "Cost difference [thousand JPY/week]" }));
  s.addChart(pres.charts.BAR, [
    { name: "Electric-first", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "Diesel-first", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/week]" }));
  y += CH5 + 0.05;
  const bevCheap = PAIRS.filter((p) => tc(p.b) < tc(p.i)).length, co2Low = PAIRS.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
  caption(`Fig. 5  Solutions from the two initial assignments: total-cost difference (left; negative = electric-first cheaper) and CO₂ (right). Electric-first emitted less CO₂ in ${co2Low === PAIRS.length ? "every case" : `${co2Low} of ${PAIRS.length} cases`} and was cheaper in ${bevCheap}. W, Sp, Su: winter, spring, summer`, RX, y, COL, 2.0, CAP);
  y += 2.1;

  y = section("5. Discussion and outlook", RX, y, COL);
  bullets([`With enough grid headroom, electrification lowers both cost and CO₂. At 90 kW in winter, the diesel-heavy solution saved about ${kJ(tc(pb90) - tc(pi90))} thousand JPY a week but emitted about ${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)} times the CO₂`,
    `The excess came in the early hours after cloudy days, when the battery was empty (90% of the ${fmt(pb90.contract_over_limit_kwh)} kWh/week of the electric-first solution at 90 kW in winter, not adopted). The day-ahead plan uses PV normals and cannot foresee cloudy days`],
    { x: RX, y, w: COL, h: 5.0, fontSize: BODY, paraSpaceAfter: 6 });
  y += 5.1;
  const steps = [["Mar 2027", "IEEJ National Convention", "this work: grid limit vs electric-bus trips, cost, CO₂"],
    ["FY2027", "Conference papers", "multi-day planning, battery optimization, price and CO₂-factor sensitivity"],
    ["Nov 2027", "Master's midterm", "gains over day-by-day planning (morning shortfall, trips moved to diesel, night grid use)"],
    ["Feb 2028", "Master's final", "guidance on grid limit, battery and chargers across seasons"]];
  const sw = (COL - 0.6) / 4, bh = FOOT - 0.8 - y;
  steps.forEach(([when, where, what], i) => {
    const x = RX + i * (sw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: bh, fill: { color: i === 3 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } },
      { text: what, options: { fontSize: 24, color: SUB } }], { x: x + 0.12, y: y + 0.1, w: sw - 0.24, h: bh - 0.15, fontSize: 26, align: "center", lineSpacingMultiple: 1.05 });
  });
  caption("Fig. 6  Road to the master's final presentation and the planned outcome of each step", RX, y + bh + 0.05, COL, 0.65, CAP);
  if (bh < 3.0) throw new Error(`road-map boxes too short: ${bh}`);

  // ---------------- footer (full width)
  s.addShape(pres.shapes.LINE, { x: M, y: FOOT + 0.1, w: W, h: 0, line: { color: GRID, width: 2 } });
  caption(`Note: all figures are DIAGNOSTIC and not yet used for research conclusions. The assignment is not proven optimal, and solving in two stages does not give a global optimum. The battery follows a rule and is not optimized. Up to ${maxTimeouts} of the 174–175 hourly re-plans timed out. The numbers are from earlier versions (${versions}, 30 JPY/kWh incl. basic charge); every case is being recomputed with both tariffs in Table 1.`,
    M, FOOT + 0.25, W, 1.05, 20);
  text([{ text: "References  ", options: { bold: true } },
    { text: "[1] Ministry of the Environment and METI: Calculation methods and emission factors (2025)  [2] W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018  [3] Open Data Challenge for Public Transportation: Tokyu Bus timetable (ODPT)  [4] Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0  [5] P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998  [6] TEPCO Energy Partner: high-voltage electricity rates (Basic plan, from 1 Apr 2026)  [7] Prime Minister's Office of Japan: policy speech to the 203rd Diet session (26 Oct 2020)  [8] MLIT: CO₂ emissions in the transport sector" }],
    { x: M, y: FOOT + 1.4, w: W, h: 45.55 - FOOT - 1.4, fontSize: 18, color: SUB });
};
