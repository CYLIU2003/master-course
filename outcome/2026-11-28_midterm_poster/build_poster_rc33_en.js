// English version of the midterm (2026-11-28) A0 portrait poster, 2026-11-09. Same layout, data and numbers as
// build_poster_rc33.js (latest version rc33/rc35 via ../2026-11-12_three_party/deck_data_latest.json, cheaper of the
// two start points per limit x season, diesel valued by the litres burnt; all results DIAGNOSTIC). Keep the K9 table
// and every hard-coded sentence in step with build_poster_rc33.js. The older English poster (rc8/rc9) is build_poster_en.js.
// 30 JPY/kWh is all-inclusive; the annual basic charge is a reference only and is never added.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));
// 2026-11-10 (user request: images, graphs and tables): Figs. 2, 3 and 6 come from poster_figs.js.
const { systemDiagram, flowDiagram, hourlyFlow } = require("./poster_figs.js");

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_latest.json"), "utf8"));
DATA.cases.forEach((r) => { if (r.status === "VERIFIED") {
  r.total_cost_accounting = r.total_cost; r.total_cost = r.total_cost_fuel_consumed; r.fuel_cost = r.ice_fuel_consumed_l * 150; } });
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const diesel = DATA.diesel;
const LIMITS = DATA.limits;
const SE = [["2025-01-06", "Winter"], ["2025-04-07", "Spring"], ["2025-07-07", "Summer"]];
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const avg = (g, k) => { const rs = cases.filter((r) => r.grid_limit_kw === g); return rs.reduce((a, r) => a + r[k], 0) / Math.max(rs.length, 1); };
const val = (g, w, k, f = (v) => v) => (get(g, w) ? f(get(g, w)[k]) : null);
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const FONT = "Arial";
const THEME = { name: "TCU white", headFontFace: FONT, bodyFontFace: FONT,
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: FONT, bodyFontFace: FONT };
pres.title = "Midterm poster 2026-11-28 (English)";
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.9, COL = (W - GAP) / 2, LX = M, RX = M + COL + GAP;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`); return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 40, fontFace: FONT, lineSpacingMultiple: 1.1, ...o }); };
const section = (label, x, y, w) => {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 1.25, fill: { color: BLUE }, line: { color: BLUE } });
  text(label, { x: x + 0.35, y, w: w - 0.5, h: 1.25, valign: "middle", fontSize: 50, bold: true, color: "FFFFFF" });
  return y + 1.6;
};
const chart = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 32, valAxisLabelFontSize: 28, valGridLine: { color: GRID, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 32, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 30, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt" });
const caption = (t, x, y, w, h = 0.9, fs = 28) => text(t, { x, y, w, h, fontSize: fs, color: SUB });

const SEASON_OF = Object.fromEntries(SE);
const lab = (r) => `${r.grid_limit_kw} kW ${SEASON_OF[r.week].toLowerCase()}`;
const list = (a) => a.length <= 1 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => !a.length ? "—" : Math.min(...a).toFixed(d) === Math.max(...a).toFixed(d) ? Math.min(...a).toFixed(d) : `${Math.min(...a).toFixed(d)}–${Math.max(...a).toFixed(d)}`;
// 2026-11-09: 90 kW spring has no running job; its diesel-heavy run (rc35 a090s10) FAILED.
// 400 kW summer: the first electric-heavy run (rc35 a400s10) FAILED; its resubmission a400s10f completed (2026-11-10).
const STOPPED = new Map([]);
const notDone = DATA.cases.filter((r) => r.status !== "VERIFIED");
const pend = notDone.filter((r) => !STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map(lab);
const stopped = notDone.filter((r) => STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${lab(r)} (${STOPPED.get(`${r.grid_limit_kw}/${r.week}`)})`);
const pairOf = (g, w, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
const pb90 = pairOf(90, "2025-01-06", "bev"), pi90 = pairOf(90, "2025-01-06", "ice");
const maxTimeouts = Math.max(...DATA.rolling.map((r) => r.time_limit));
const man = (v) => (v / 1e6).toFixed(2);           // million JPY
const fmt = (v) => Math.round(v).toLocaleString("en-US");
// Same numbers as build_poster_rc33.js (winter rc33 pair, spring rc35, summer rc35).
const K9 = {
  wb: { cost: 4189120, share: 92.6, co2: 2470, pvUse: 19867, pvCut: 4709, over: 0 },
  wi: { cost: 4387150, share: 37.6, co2: 5949, pvUse: 14258, pvCut: 10318, over: 0 },
  sb: { cost: 4157225, share: 93.5, co2: 1945, pvUse: 22127, pvCut: 5692, over: 0 },
  // 2026-11-10: summer BEV-heavy is rerunning as rc36 a900u. The earlier rc35 a900s10f numbers were removed:
  // that launch carried no seed and default time limits, so it was not the same case as the other columns.
  ub: null };
const wCut = Math.round((1 - K9.wb.co2 / K9.wi.co2) * 100);

// ---- Title block (the top-left 20 x 20 cm is kept free for the poster number)
const NUM = 7.87;
text("Trip Assignment and Charging Optimization for Battery-Electric Buses Operated Alongside Diesel Buses toward Green Transformation (GX)",
  { x: M + NUM, y: M + 0.2, w: W - NUM, h: 3.6, fontSize: 64, bold: true, valign: "middle" });
text("(Author name, laboratory and supervisor), Tokyo City University", { x: M + NUM, y: M + 3.95, w: W - NUM, h: 1.0, fontSize: 42, color: SUB });
s.addShape(pres.shapes.LINE, { x: M, y: M + 5.6, w: W, h: 0, line: { color: BLUE, width: 8 } });

// ---- Abstract
text(`Abstract  When battery-electric buses charge at the depot at the same time, the grid demand rises. For a depot that operates electric and diesel buses, we optimize the trip assignment and the charging plan, and evaluate trip shares, cost and CO₂ under different grid limits in representative winter, spring and summer weeks. With a 900 kW limit and 1,000 kW of PV in winter, electric-heavy operation was ${man(K9.wi.cost - K9.wb.cost)} million JPY per week cheaper than diesel-heavy operation and emitted ${wCut}% less CO₂. Lower limits shrink this advantage: ${iceWins.length ? `in ${list(iceWins.map(lab))}, diesel-heavy operation was cheaper (at 90 kW in winter it emitted about ${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)} times the CO₂).` : "electric-heavy operation was cheaper at every limit."}`,
  { x: M, y: 8.0, w: W, h: 3.9, fontSize: 38 });

// ---- Left column
let y = 12.5;
y = section("1. Background and objective", LX, y, COL);
text([
  { text: "Electric buses are entering Japanese route-bus networks, but vehicle price and charging time mean they will run alongside diesel buses for some time. They charge together at the depot at night, which raises the grid demand.", options: { breakLine: true } },
  { text: "This study asks how, as the grid limit changes, (1) the share of trips electric buses can serve and the cost, fuel and CO₂ change, and (2) where and why the limit is exceeded." }],
  { x: LX, y, w: COL, h: 3.6, paraSpaceAfter: 6, fontSize: 30 });
y += 3.75;
y = section("2. Case study", LX, y, COL);
y += systemDiagram(s, pres, LX, y, COL, { pv: "PV\n1,000 kW", battery: "Battery 6,000 kWh\n(not charged from grid)", grid: "Grid (limit)\n90–900 kW",
  charger: "Chargers\n90 kW × 10", ebus: "35 electric buses", dbus: "25 diesel buses", share: "share 1,704 trips/week" }, FONT, 24);
caption("Fig. 2  Depot equipment and power flows (planned in 15-min steps)", LX, y, COL, 0.7, 26);
y += 0.85;
const rows = [["Routes", "Tokyu Bus Shibu 21–23 (Tsurumaki depot); ODPT timetable [3]"], ["Service", "1,704 trips/week (264 weekday, 203 Sat, 181 Sun/holiday per day)"],
  ["Grid limit", "90, 200, 400, 900 kW (excess 500 JPY/kWh, provisional)"], ["Period", "Representative winter, spring, summer weeks (2025)"],
  ["Morning SOC", "Target 90%, minimum 80%"], ["Prices", "Electricity 30 JPY/kWh (incl. basic charge); diesel 150 JPY/L"], ["CO₂", "Diesel 2.62 kg/L [1]; grid 0.5 kg/kWh (provisional)"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.6, COL - 3.6], fontSize: 27, fontFace: FONT, color: INK, rowH: 0.6, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.6 + 0.5;
y = section("3. Method", LX, y, COL);
flowDiagram(s, pres, LX, y, COL, [
  ["1 Assign trips", ["1,704 trips to 60 buses", "MIP + large neighbourhood search [5]"]],
  ["2 Day-ahead plan", ["Assignment fixed; charging, battery and grid in 15-min steps", "PV forecast = climatological normal [2]"]],
  ["3 Hourly re-plan", ["Re-plan every hour on actual weather", "174–175 times/week × 120 s"]],
  ["4 Account", ["Cost and CO₂ from the executed week", "Cheaper start point kept"]]], FONT, 3.6, 21);
caption("Fig. 3  Calculation flow (1 = Stage 1; 2–3 = Stage 2; solver Gurobi [4])", LX, y + 3.65, COL, 0.7, 26);
y += 4.45;
const FC = [3391, 3401, 3412, 3423, 3436, 3448, 3462], AC = [1399, 2640, 3836, 4871, 5059, 5079, 1693];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
s.addChart(pres.charts.BAR, [{ name: "Day-ahead forecast (normal)", labels: DAYS, values: FC }, { name: "Actual", labels: DAYS, values: AC }],
  { ...chart(), x: LX, y, w: COL, h: 3.6, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", BLUE], valAxisMinVal: 0,
    legendFontSize: 28, showValAxisTitle: true, valAxisTitle: "kWh/day", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("Fig. 5  PV in the winter week (from 6 Jan 2025): day-ahead forecast vs actual (input data)", LX, y + 3.65, COL, 0.7, 26);
y += 4.45;
caption(`Note: All results are DIAGNOSTIC, from the latest versions (rc33, rc35, rc36; both 90 kW spring starts and the 400 kW summer electric-heavy start on rc36, the latter having stopped in the hourly re-plan on rc35). Each case is solved from two start points (electric-heavy and diesel-heavy); the one with the lower total cost (diesel valued by litres burnt) is shown. The trip assignment stops at the memory limit and the two-stage method is not a global optimum. Up to ${maxTimeouts} of the 174–175 hourly re-plans per week hit the time limit; slower machines were given longer limits. The basic charge is included in 30 JPY/kWh and not added. ${pend.length ? `Still running: ${list(pend)}. ` : ""}${(DATA.first_attempt_failures || []).length ? `The electric-heavy run of ${list(DATA.first_attempt_failures.map((k) => `${k.split("/")[0]} kW ${SEASON_OF[k.split("/")[1]].toLowerCase()}`))} stopped in the hourly re-plan on its first attempt and is being rerun on the same version. ` : ""}${stopped.length ? `Not completed, one start failed: ${list(stopped)}. ` : ""}Peak = 15-min average.`,
  LX, y, COL, 45.5 - y - 2.5, 22);
text([{ text: "References", options: { bold: true, breakLine: true } },
  ...["[1] Ministry of the Environment, METI: List of calculation methods and emission factors (2025)", "[2] W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018",
    "[3] Public Transportation Open Data Center: Tokyu Bus timetable data (ODPT)", "[4] Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0",
    "[5] P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998"]
    .map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } }))],
  { x: LX, y: 45.5 - 2.4, w: COL, h: 2.4, fontSize: 19, color: SUB });

// ---- Right column
y = 12.5;
y = section("4. Results", RX, y, COL);
const halfR = (COL - 0.5) / 2;
s.addChart(pres.charts.LINE, SE.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
  { ...chart(), x: RX, y, w: halfR, h: 5.6, lineSize: 5, lineDataSymbol: "circle", lineDataSymbolSize: 14, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    catAxisLabelFontSize: 26, valAxisLabelFontSize: 24, legendFontSize: 26,
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showCatAxisTitle: true, catAxisTitle: "Grid limit [kW]", catAxisTitleFontSize: 24, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "Electric-bus trips [%]", valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
hourlyFlow(s, pres, chart(), RX + halfR + 0.5, y, halfR, 5.6, ["PV→battery", "PV→bus", "Battery→bus", "Grid→bus", "PV curtailed"], ["Hour of day", "Energy [MWh/week]"]);
caption("Fig. 1  Grid limit vs electric-bus trip share (1,704 trips/week, cheaper start point)", RX, y + 5.65, halfR, 1.3, 22);
caption("Fig. 6  Power flows by hour of day (900 kW winter, electric-heavy, week total). Daytime PV is stored in the battery and charges the buses at night", RX + halfR + 0.5, y + 5.65, halfR, 1.3, 22);
y += 7.1;
text(`(1) Taking the cheaper of the two start points, ${iceWins.length ? `the diesel-heavy start was cheaper at the low limits (${list(iceWins.map(lab))}), with electric buses serving ${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}% of trips. ` : ""}Elsewhere the electric-heavy start was cheaper, with ${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}% of trips. The same case gave very different trip shares from the two start points.`,
  { x: RX, y, w: COL, h: 2.5, fontSize: 27 });
y += 2.6;
const half = (COL - 0.6) / 2;
const K9COLS = [["wb", "Winter, electric-heavy"], ["wi", "Winter, diesel-heavy"], ["sb", "Spring, electric-heavy"], ["ub", "Summer, electric-heavy"]];
const k9Row = (label, f) => [{ text: label, options: { bold: true } }, ...K9COLS.map(([k]) => ({ text: (K9[k] ? f(K9[k]) : "running"), options: { align: "center" } }))];
s.addTable([
  [{ text: "Base case", options: { bold: true, fill: { color: "F2F2F2" } } },
   ...K9COLS.map(([, n]) => ({ text: n, options: { bold: true, fill: { color: "F2F2F2" }, align: "center" } }))],
  k9Row("Total cost", (r) => `${man(r.cost)} M JPY`),
  k9Row("Electric-bus trips", (r) => `${r.share.toFixed(1)}%`),
  k9Row("CO₂", (r) => `${fmt(r.co2)} kg`),
  k9Row("PV used / curtailed [MWh]", (r) => `${(r.pvUse / 1e3).toFixed(1)} / ${(r.pvCut / 1e3).toFixed(1)}`),
  k9Row("Excess over limit", (r) => `${fmt(r.over)} kWh`)],
  { x: RX, y, w: COL, colW: [4.0, (COL - 4.0) / 4, (COL - 4.0) / 4, (COL - 4.0) / 4, (COL - 4.0) / 4], fontSize: 25, fontFace: FONT,
    color: INK, rowH: 0.74, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
caption(`Table 1  One week at a 900 kW limit and 1,000 kW of PV. The two winter columns use the same version and differ only in the start point (rc33); spring is electric-heavy (rc35); summer is being rerun on the new version (rc36). In winter, electric-heavy is ${man(K9.wi.cost - K9.wb.cost)} M JPY cheaper with ${wCut}% less CO₂; diesel-heavy curtails about 40% of PV. DIAGNOSTIC`, RX, y + 5.0, COL, 1.6, 24);
y += 6.7;
// 11/9 (user request): cost and CO2 of both start points by grid limit, cases where both are verified.
const PAIRS = [];
LIMITS.forEach((g) => SE.forEach(([w, n]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g} ${n.slice(0, 3)}`, b, i }); }));
const pcats = PAIRS.map((p) => p.label);
const pairChart = (o) => ({ ...chart(), y, w: half, h: 6.3, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin", barGapWidthPct: 60,
  showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 14, legendFontSize: 26, catAxisLabelFontSize: 20, catAxisLabelFrequency: 1, barGapWidthPct: 15, valAxisLabelFontSize: 22, valAxisTitleFontSize: 26, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
s.addChart(pres.charts.BAR, [
  { name: "Electric-heavy − diesel-heavy", labels: pcats, values: PAIRS.map((p) => Math.round((p.b.total_cost_fuel_consumed - p.i.total_cost_fuel_consumed) / 1e4) / 100) }],
  pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0.00;-0.00", valAxisMinVal: -0.6, valAxisMaxVal: 0.6, valAxisMajorUnit: 0.3, catAxisLabelPos: "low", showLegend: true, valAxisTitle: "Cost difference [M JPY/week]" }));
s.addChart(pres.charts.BAR, [
  { name: "Electric-heavy", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
  { name: "Diesel-heavy", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
  pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/week]" }));
caption("Fig. 4  Cost difference (left; negative = electric-heavy is cheaper) and CO₂ (right)", RX, y + 6.35, COL, 0.9, 26);
y += 7.25;
const overCases = cases.filter((r) => r.contract_over_limit_kwh > 1);
text(`(2) With the cheaper start point, excess remained in ${overCases.length ? list(overCases.map((r) => `${lab(r)} (${fmt(r.contract_over_limit_kwh)} kWh/week)`)) : "no case"}. From the electric-heavy start, 90 kW winter exceeded the limit by ${fmt(pb90.contract_over_limit_kwh)} kWh/week. In Fig. 4, the electric-heavy start emitted less CO₂ in all ${PAIRS.length} cases (1/${(Math.min(...PAIRS.map((p) => p.i.total_co2_kg / p.b.total_co2_kg))).toFixed(1)} to 1/${(Math.max(...PAIRS.map((p) => p.i.total_co2_kg / p.b.total_co2_kg))).toFixed(1)} of diesel-heavy) and was cheaper in ${PAIRS.filter((p) => p.b.total_cost_fuel_consumed < p.i.total_cost_fuel_consumed).length} of them.`,
  { x: RX, y, w: COL, h: 3.1, fontSize: 28 });
y += 3.25;

y = section("5. Discussion and conclusions", RX, y, COL);
text([
  { text: "At 90 kW in winter from the electric-heavy start, the day-ahead plan had no excess. 90% of the executed excess came in the early hours after a cloudy Monday (PV 41% of forecast, Fig. 5), when the battery was empty. Because the battery is not charged from the grid, Monday's unused grid headroom could not be shifted to the night. Halving the forecast in the plan cut the excess by only 10%.", options: { breakLine: true } },
  { text: `With enough grid headroom, electrification lowers both cost and CO₂ (Table 1). It loses at low limits in winter (at 90 kW the diesel-heavy start was about 0.4 M JPY cheaper, with about 3 times the CO₂: about ${Math.round((pb90.total_cost_fuel_consumed - pi90.total_cost_fuel_consumed) / (pi90.total_co2_kg - pb90.total_co2_kg))} JPY per kg of CO₂ avoided) and without PV. Next: compare with grid-to-battery charging, and multi-day planning.` }],
  { x: RX, y, w: COL, h: 45.5 - y, paraSpaceAfter: 6, fontSize: 24 });

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0_rc33_en.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
