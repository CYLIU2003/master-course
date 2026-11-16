// English twin of poster_layout_v2_ja.js (2026-11-16): same order, data and rules (CO2 cost in the objective only,
// never in a reported total; timeouts counted over every shown run). Built with POSTER_LANG=en.
module.exports = function layout(c) {
  const { FONT, s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    cases, LIMITS, SE, val, pairOf, iceWins, bevWins, fmt, pb90, pi90, eqSize, maxTimeouts } = c;
  const rngTxt = (a, d) => c.rngTxt(a, d).replace("〜", "–"), versions = c.versions.split("・").join(", ");
  const NUM = 7.87;
  const SEASON = { "2025-01-06": "winter", "2025-04-07": "spring", "2025-07-07": "summer" };
  const SHORT = { "2025-01-06": "W", "2025-04-07": "Sp", "2025-07-07": "Su" };
  const SEN = SE.map(([w]) => [w, SEASON[w][0].toUpperCase() + SEASON[w].slice(1)]);
  const lab = (r) => `${r.grid_limit_kw} kW ${SEASON[r.week]}`;
  const list = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`);
  const mJ = (v) => (v / 1e6).toFixed(2); // million JPY
  const kJ = (v) => Math.round(v / 1e3); // thousand JPY
  const tc = (r) => r.total_cost_reported; // CO2 cost excluded from every reported total

  text("Trip Assignment and Charging Optimization for Electric Buses\nOperated Alongside Diesel Buses toward GX", { x: M + NUM, y: M, w: W - NUM, h: 2.5, fontSize: 48, bold: true, valign: "middle" });
  text("(Author name, laboratory and supervisor), Tokyo City University", { x: M + NUM, y: M + 2.55, w: W - NUM, h: 0.8, fontSize: 34, color: SUB });
  s.addShape(pres.shapes.LINE, { x: M, y: 8.8, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const p9b = pairOf(900, "2025-01-06", "bev"), p9i = pairOf(900, "2025-01-06", "ice");
  const wCut = Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100);
  text(`Abstract  When route buses are electrified, charging at the depot overlaps and the grid power drawn by the depot rises. For a depot that runs electric and diesel buses together, we optimize trip assignment and charging, and examine how the electric buses' share of trips, the cost and CO₂ change with the grid limit, using one week each in winter, spring and summer. In winter at 900 kW with 1,000 kW of PV, the solution using more electric buses cost ${kJ(tc(p9i) - tc(p9b))} thousand JPY less per week and emitted ${wCut}% less CO₂. The gap narrows as the limit falls; at ${list(iceWins.map(lab))} the solution using more diesel buses was cheaper.`,
    { x: M + NUM, y: M + 3.45, w: W - NUM, h: 3.5, fontSize: 28 });

  // ---------------- left column
  let y = 9.2;
  y = section("1. Background and aim", LX, y, COL);
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: 4.3, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  const story = [
    ["Carbon neutral by 2050", "In October 2020, Japan declared net-zero greenhouse-gas emissions by 2050 [7]"],
    ["Transport", "Transport emits 19.3% of Japan's CO₂, and road vehicles about 86% of that (FY2024) [8]"],
    ["Route buses", "Electric buses are being introduced, but fleets cannot be replaced at once and will run with diesel buses for years. Charging many buses at the depot at the same time raises its grid power"]];
  text(story.flatMap(([h, b], i) => [
      { text: (i ? "▶ " : "") + h + "  ", options: { bold: true, color: BLUE_DARK } },
      { text: b, options: { breakLine: true } }]).concat([
      { text: "Aim  ", options: { bold: true, color: BLUE_DARK } },
      { text: "Cut CO₂ by electrifying buses (GX) while keeping today's timetable and limiting the cost of grid equipment and electricity", options: { bold: true } }]),
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: 3.95, fontSize: 23, paraSpaceAfter: 3 });
  y += 4.55;
  text([{ text: "This study", options: { bold: true, color: BLUE_DARK, breakLine: true } },
    ...["Optimize trip assignment and charging at a depot with electric and diesel buses", "Compare electric-bus trips, cost and CO₂ across grid limits", "Find when and why the grid limit is exceeded"]
      .map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } }))],
    { x: LX, y, w: COL, h: 2.25, fontSize: 26, paraSpaceAfter: 4 });
  y += 2.4;

  y = section("2. Method", LX, y, COL);
  text([{ text: "Decisions  ", options: { bold: true, color: BLUE_DARK } },
    { text: "(a) which vehicle, electric or diesel, runs each trip; (b) when and at how many kW each electric bus charges. Every timetabled trip is run." }],
    { x: LX, y, w: COL, h: 1.4, fontSize: 27 });
  y += 1.5;
  text([{ text: "Objective  ", options: { bold: true, color: BLUE_DARK } }, { text: "minimize the total cost of one week" }], { x: LX, y, w: COL, h: 0.6, fontSize: 27 });
  y += 0.7;
  const EQW = COL * 0.86, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: "Objective: minimize vehicle use, electricity with the excess over the grid limit, diesel, and the CO2 cost" });
  y += EQH + 0.15;
  caption("From left: vehicle use (u: vehicle k used on day d), electricity and excess (g: grid power at time t, s: excess), diesel (f: fuel of trip j), CO₂ (Q: emissions); c, p, π are unit prices. Main constraints: trip connection (arrival + turnaround + deadhead ≤ next departure), battery level, 10 chargers, grid limit (excess is charged)", LX, y, COL, 1.65, 20);
  y += 1.75;
  flowDiagram(s, pres, LX, y, COL, [
    ["1 Assignment", ["1,704 trips to 60 buses", "integer program and partial re-solving [5]"]],
    ["2 Day-ahead plan", ["assignment fixed; charging every 15 min", "PV forecast from normals [2]"]],
    ["3 Hourly re-plan", ["re-planned each hour with actual sunshine", "174–175 times to the last morning"]],
    ["4 Accounting", ["cost and CO₂ of what was executed", "cheaper of two initial assignments"]]], FONT, 3.25, 20);
  caption("Fig. 1  Calculation flow (solver: Gurobi [4]). The battery follows a fixed rule", LX, y + 3.3, COL, 0.6, 22);
  y += 4.0;
  const params = [["Electricity", "17.43 JPY/kWh [6]; basic charge (45–447 thousand JPY/week) added to results. Comparison: 30 JPY/kWh incl. basic charge"],
    ["Diesel", "150 JPY/L, 2.62 kg-CO₂/L [1]"], ["Grid CO₂", "0.5 kg/kWh (tentative); CO₂ cost 1 JPY/kg, not totalled"],
    ["Vehicle use", "20,000 JPY per bus-day"], ["Excess over limit", "500 JPY/kWh (tentative)"], ["Morning battery", "electric buses: target 90%, floor 80%"],
    ["Time step", "15 min (re-planning every hour)"], ["Stopping rule", "gap 5% (all cases), assignment 3 h, re-plan 300 s each (600 s only for time-out reruns)"]];
  const tbl = (rowsIn, x, yy, w, k = 3.9, fs = 25, rh = 0.56) =>
    s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
      { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: FONT, color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  const prh = params.map(([k]) => (k === "Electricity" || k === "Stopping rule" ? 0.9 : 0.5));
  tbl(params, LX, y, COL, 3.9, 24, prh);
  y += prh.reduce((a, b) => a + b, 0) + 0.35;
  caption("Table 1  Values used (tentative values to be tested for sensitivity). Gap: solution vs proven lower bound", LX, y, COL, 0.6, 21);
  y += 0.7;

  y = section("3. Case study", LX, y, COL);
  const MAPW = COL * 0.40, MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, "route_map_en_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH, altText: "Routes Shibu 21, 22 and 23 and the Tsurumaki depot" });
  y += MAPH + 0.08;
  caption("Fig. 2  Routes and the Tsurumaki depot (stop positions from Japan's public-transport open data, ODPT [3], joined by straight lines; background © OpenStreetMap contributors)", LX, y, COL, 1.0, 20);
  y += 1.0;
  const study = [["Service", "Tokyu Bus routes Shibu 21–23 (Tsurumaki depot), 1,704 trips/week"], ["Fleet, equipment", "35 electric and 25 diesel buses; 10 × 90 kW chargers; 1,000 kW PV; 6,000 kWh battery"],
    ["Cases", "grid limit 90, 200, 400, 900 kW × one week each in winter, spring, summer (from 6 Jan, 7 Apr, 7 Jul 2025, actual sunshine) = 12 cases"]];
  tbl(study, LX, y, COL, 3.3, 23, 0.8);
  y += study.length * 0.8 + 0.4;
  caption("Table 2  Case-study conditions", LX, y, COL, 0.5, 22);
  if (y + 0.5 > 45.5 - 1.6) throw new Error(`left column overflows: ${y}`);
  text([{ text: "References  ", options: { bold: true } },
    { text: "[1] Ministry of the Environment and METI: Calculation methods and emission factors (2025)  [2] W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018  [3] Open Data Challenge for Public Transportation: Tokyu Bus timetable (ODPT)  [4] Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0  [5] P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998  [6] TEPCO Energy Partner: high-voltage electricity rates (Basic plan, from 1 Apr 2026)  [7] Prime Minister's Office of Japan: policy speech to the 203rd Diet session (26 Oct 2020)  [8] MLIT: CO₂ emissions in the transport sector" }],
    { x: LX, y: 45.5 - 1.6, w: COL, h: 1.6, fontSize: 15, color: SUB });

  // ---------------- right column
  y = 9.2;
  y = section("4. Results", RX, y, COL);
  const halfR = (COL - 0.5) / 2, cats = LIMITS.map((g) => `${g}`);
  s.addChart(pres.charts.BAR, SEN.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
    { ...chart(), x: RX, y, w: halfR, h: 6.0, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: 26, valAxisLabelFontSize: 24, legendFontSize: 26, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: "Grid limit [kW]", catAxisTitleFontSize: 24, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: "Electric-bus trips [%]", valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
  const T4 = halfR, k4 = 2.0, cw4 = (T4 - k4) / SE.length, rh4 = 0.95;
  const hd4 = (t) => ({ text: t, options: { bold: true, align: "center", fill: { color: "F2F2F2" } } });
  const c4 = (g, w) => { const r = cases.find((x) => x.grid_limit_kw === g && x.week === w);
    return { text: r ? `${mJ(tc(r))}${r.selected_start === "ice" ? "*" : ""}` : "—", options: { align: "center", color: r && r.selected_start === "ice" ? BLUE_DARK : INK, bold: !!(r && r.selected_start === "ice") } }; };
  s.addTable([[hd4("Limit"), ...SEN.map(([, n]) => hd4(n))],
    ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => c4(g, w))])],
    { x: RX + halfR + 0.5, y: y + 0.4, w: T4, colW: [k4, ...SE.map(() => cw4)], fontSize: 26, fontFace: FONT, color: INK,
      rowH: rh4, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  caption("Fig. 3  Share of the 1,704 weekly trips run by electric buses. Each case shows the cheaper of the two initial assignments", RX, y + 6.05, halfR, 1.6, 22);
  caption("Fig. 4  Total weekly cost [million JPY]: vehicle use, electricity, diesel and excess; CO₂ cost not included. * = solution from the diesel-first initial assignment", RX + halfR + 0.5, y + 0.4 + rh4 * (LIMITS.length + 1) + 0.15, halfR, 1.9, 22);
  y += 7.85;
  text(`At limits of 400 kW and above, electric buses ran ${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}% of all trips at a lower total cost. At ${list(iceWins.map(lab))}, the solution using more diesel buses was cheaper and electric buses ran only ${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}% of trips.`,
    { x: RX, y, w: COL, h: 1.9, fontSize: 26 });
  y += 2.05;
  text([{ text: "Getting good solutions in limited time  ", options: { bold: true, color: BLUE_DARK } },
    { text: "The assignment problem is too large to prove optimality within the time limit, and the search tends to stay near its starting assignment. We therefore start from two different assignments, electric-first and diesel-first, and keep the cheaper result (Table 3)." }],
    { x: RX, y, w: COL, h: 2.3, fontSize: 26 });
  y += 2.45;
  const p90b = pb90, p90i = pi90;
  const cols = [["900 kW winter", p9b, "Electric-first"], ["900 kW winter", p9i, "Diesel-first"], ["90 kW winter", p90b, "Electric-first"], ["90 kW winter", p90i, "Diesel-first"]];
  const win = (a, b) => tc(a) <= tc(b);
  const adopted = [win(p9b, p9i), !win(p9b, p9i), win(p90b, p90i), !win(p90b, p90i)];
  const cell = (t, i) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK } });
  const head = (t) => ({ text: t, options: { bold: true, fill: { color: "F2F2F2" }, align: "center" } });
  const row = (label, f) => [{ text: label, options: { bold: true } }, ...cols.map(([, r], i) => cell(f(r), i))];
  s.addTable([
    [head("Limit, season"), ...cols.map(([n]) => head(n))],
    [{ text: "Initial assignment", options: { bold: true } }, ...cols.map(([, , n], i) => cell(n, i))],
    row("Total cost", (r) => `${mJ(tc(r))} M JPY`),
    row("Electric-bus trips", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
    row("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`),
    row("Excess over limit", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`),
    [{ text: "Adopted", options: { bold: true } }, ...adopted.map((a, i) => cell(a ? "○" : "—", i))]],
    { x: RX, y, w: COL, colW: [3.7, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4], fontSize: 23, fontFace: FONT,
      color: INK, rowH: 0.62, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  y += 7 * 0.62 + 0.1;
  caption("Table 3  Solutions from the two initial assignments (one week). Blue: adopted", RX, y, COL, 0.6, 22);
  y += 0.8;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g} ${SHORT[w]}`, b, i }); }));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: 5.4, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 18, legendFontSize: 22, catAxisLabelFontSize: 20, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 20, valAxisTitleFontSize: 22, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  s.addChart(pres.charts.BAR, [{ name: "Electric-first − diesel-first", labels: pcats, values: PAIRS.map((p) => kJ(tc(p.b) - tc(p.i))) }],
    pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0;-0", valAxisMinVal: -600, valAxisMaxVal: 600, valAxisMajorUnit: 300, catAxisLabelPos: "low", valAxisTitle: "Cost difference [thousand JPY/week]" }));
  s.addChart(pres.charts.BAR, [
    { name: "Electric-first", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "Diesel-first", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/week]" }));
  y += 5.45;
  const bevCheap = PAIRS.filter((p) => tc(p.b) < tc(p.i)).length, co2Low = PAIRS.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
  caption(`Fig. 5  Solutions from the two initial assignments: total-cost difference (left; negative = electric-first cheaper) and CO₂ (right). Electric-first emitted less CO₂ in ${co2Low === PAIRS.length ? "every case" : `${co2Low} of ${PAIRS.length} cases`} and was cheaper in ${bevCheap}. W, Sp, Su: winter, spring, summer`, RX, y, COL, 1.2, 22);
  y += 1.4;

  y = section("5. Discussion and outlook", RX, y, COL);
  text([
    { text: `With enough grid headroom, electrification lowers both cost and CO₂. At ${list(iceWins.map(lab))}, using more diesel buses was cheaper; at 90 kW in winter it saved about ${kJ(tc(p90b) - tc(p90i))} thousand JPY a week but emitted about ${(p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1)} times the CO₂.`, options: { bullet: true, breakLine: true } },
    { text: `The excess came in the early hours after cloudy days, when the battery was empty (90% of the ${fmt(p90b.contract_over_limit_kwh)} kWh/week of the electric-first solution at 90 kW in winter, not adopted). The day-ahead plan forecasts PV from normals and cannot foresee cloudy days.`, options: { bullet: true } }],
    { x: RX, y, w: COL, h: 3.0, fontSize: 24, paraSpaceAfter: 4 });
  y += 3.1;
  text([{ text: "Outlook  ", options: { bold: true, color: BLUE_DARK } },
    { text: "This work, recomputed under uniform settings, will be presented at the IEEJ National Convention in March 2027. Next we will plan for cloudy days and empty batteries and optimize battery operation, toward guidance on choosing grid limits and equipment." }],
    { x: RX, y, w: COL, h: 1.75, fontSize: 23 });
  y += 1.85;
  const steps = [["Mar 2027", "IEEJ National Convention", "this work: grid limit vs electric-bus trips, cost, CO₂"],
    ["FY2027", "Conference papers", "multi-day planning, battery optimization, price and CO₂-factor sensitivity"],
    ["Nov 2027", "Master's midterm", "gains over day-by-day planning (morning battery shortfall, trips moved to diesel, night grid use)"],
    ["Feb 2028", "Master's final", "guidance on grid limit, battery and chargers across seasons"]];
  const sw = (COL - 0.6) / 4, bh = 2.55;
  steps.forEach(([when, where, what], i) => {
    const x = RX + i * (sw + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: bh, fill: { color: i === 3 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } },
      { text: what, options: { fontSize: 15, color: SUB } }], { x: x + 0.12, y: y + 0.08, w: sw - 0.24, h: bh - 0.12, fontSize: 18, align: "center" });
  });
  caption("Fig. 6  Road to the master's final presentation and the planned outcome of each step", RX, y + bh + 0.05, COL, 0.5, 20);
  y += bh + 0.6;
  caption(`Note: all figures are DIAGNOSTIC and not yet used for research conclusions. The assignment is not proven optimal, and solving in two stages does not give a global optimum. The battery follows a rule and is not optimized. Up to ${maxTimeouts} of the 174–175 hourly re-plans timed out. The numbers are from earlier versions (${versions}, 30 JPY/kWh incl. basic charge); every case is being recomputed with both tariffs in Table 1.`,
    RX, y, COL, 45.5 - y, 18);
};
