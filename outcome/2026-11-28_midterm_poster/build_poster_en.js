// English version of the midterm A0 portrait poster (841 x 1189 mm), same layout and data as
// build_poster.js: white background, black text, Tokyo City University blue (#0485D7) only for the
// title rule, section headings and the proposed-case series (comparison case in grey).
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const rc8 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc8.json"), "utf8"));
const rc9 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc9.json"), "utf8")).filter((r) => r.status === "VERIFIED");
const night = JSON.parse(fs.readFileSync(path.join(__dirname, "night_profile_90kW_winter.json"), "utf8"));
const dl = fs.readFileSync(path.join(__dirname, "all_diesel_estimate.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dk = dl[0].split(","), diesel = dl.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dk[i], v])));
const LIMITS = [90, 200, 400, 800];
const get = (rows, g, w) => rows.find((r) => r.grid_limit_kw === g && r.week === w);
const peakYear = (rows, g) => Math.max(...rows.filter((r) => r.grid_limit_kw === g).map((r) => r.peak_grid_kw));
const basicYear = (kw) => kw * (kw >= 500 ? 1989 : 1890) * 0.85 * 12;
const fmt = (n) => n.toLocaleString("en-US");

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
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`);
  return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 40, fontFace: FONT, lineSpacingMultiple: 1.1, ...o }); };
const section = (label, x, y, w) => {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 1.25, fill: { color: BLUE }, line: { color: BLUE } });
  text(label, { x: x + 0.35, y, w: w - 0.5, h: 1.25, valign: "middle", fontSize: 50, bold: true, color: "FFFFFF" });
  return y + 1.6;
};
const chart = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
  catAxisLabelFontSize: 32, valAxisLabelFontSize: 28, valGridLine: { color: GRID, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: FONT, legendFontSize: 32, legendColor: INK, dataLabelFontFace: FONT, dataLabelFontSize: 30, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleFontFace: FONT, catAxisTitleFontFace: FONT });
const caption = (t, x, y, w, h = 0.9, fs = 30) => text(t, { x, y, w, h, fontSize: fs, color: SUB });

// ---- Title block; the top-left 20 x 20 cm is kept free for the abstract number.
const NUM = 7.87;
text("Trip Assignment and Charging Optimization for Battery-Electric Buses Operated Alongside Diesel Buses toward Green Transformation (GX)",
  { x: M + NUM, y: M + 0.2, w: W - NUM, h: 3.6, fontSize: 64, bold: true, valign: "middle" });
text("(Author name, laboratory and supervisor), Tokyo City University", { x: M + NUM, y: M + 3.95, w: W - NUM, h: 1.0, fontSize: 42, color: SUB });
s.addShape(pres.shapes.LINE, { x: M, y: M + 5.6, w: W, h: 0, line: { color: BLUE, width: 8 } });

// ---- Abstract
text("Abstract  When battery-electric buses charge at the depot at the same time, the peak grid demand rises, and so do the demand-based basic electricity charge and the required receiving equipment. For a depot that operates electric and diesel buses together, we jointly optimize trip assignment and charging and evaluate how the grid import limit and the basic charge affect cost and CO₂ emissions. Including the basic charge in the objective lowered the winter peak demand by about 25–50% without a large change in the energy purchased.",
  { x: M, y: 8.0, w: W, h: 4.0, fontSize: 38 });

// ---- Left column
let y = 12.5;
y = section("1. Background and objective", LX, y, COL);
text([
  { text: "Electric buses are being introduced on city bus routes, but because of vehicle cost and charging time they will be operated together with diesel buses for some time.", options: { breakLine: true } },
  { text: "A business electricity bill consists of an energy charge (per kWh) and a basic charge set by the contract demand, i.e. the highest demand of the past 12 months. Charging concentrated at night raises the latter.", options: { breakLine: true } },
  { text: "Objective: clarify how the grid import limit and the basic charge affect trip assignment, charging, cost and CO₂." }],
  { x: LX, y, w: COL, h: 7.6, paraSpaceAfter: 18 });
y += 8.0;
y = section("2. Case study", LX, y, COL);
const rows = [["Routes", "Tokyu Bus Shibu 21–23 (Tsurumaki depot)"], ["Trips", "1,704 trips per week"], ["Fleet", "35 electric + 25 diesel buses available (fixed)"],
  ["Assets", "PV 1,000 kW, battery 6,000 kWh, chargers 10 × 90 kW"], ["Grid limit", "90/200/400/800 kW (500 JPY/kWh on excess)"], ["Weeks", "Winter, spring, summer (+autumn, basic charge)"],
  ["Prices", "Grid 30 JPY/kWh; diesel 150 JPY/L; basic 1,890 JPY/kW-mo"], ["CO₂", "Diesel 2.62 kg/L; grid 0.5 kg/kWh (provisional)"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.0, COL - 3.0], fontSize: 30, fontFace: FONT, color: INK, rowH: 0.78, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.78 + 1.5;
y = section("3. Method", LX, y, COL);
text([
  { text: "Trip assignment (Stage 1): a mixed-integer program assigning 1,704 trips to 60 buses. A general-purpose solver did not improve the initial plan, so we improved it with large neighborhood search (LNS), re-solving only part of the trips at a time.", options: { breakLine: true } },
  { text: "Charging (Stage 2): with the assignment fixed, optimize charging, PV, battery and grid purchase every 15 minutes.", options: { breakLine: true } },
  { text: "Hourly rolling: re-plan every hour while executing the week; costs are taken from the executed result.", options: { breakLine: true } },
  { text: "Comparison: objective without and with the basic charge." }],
  { x: LX, y, w: COL, h: 42.8 - y, paraSpaceAfter: 18 });
caption("Note: All trip assignments and all 16 charging plans with the basic charge are time-limited feasible solutions (MIP gap 13–67%); without it, 11 of 12 charging plans are optimal. Peak = 15-min average. Basic charge rates of TEPCO Energy Partner (business, <500 kW; 1,989 JPY/kW at ≥500 kW); power factor 100% assumed.",
  LX, 43.2, COL, 2.2, 26);

// ---- Right column
y = 12.5;
y = section("4. Results", RX, y, COL);
const WIN = "2025-01-06";
s.addChart(pres.charts.BAR, [
  { name: "Without basic charge", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "With basic charge", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  { ...chart(), x: RX, y, w: COL, h: 6.4, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE],
    showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0, showCatAxisTitle: true, catAxisTitle: "Grid import limit", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "Peak demand [kW]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("Fig. 1  Peak grid demand in the winter week", RX, y + 6.45, COL);
y += 7.4;
s.addChart(pres.charts.LINE, [
  { name: "Without basic charge", labels: night.labels, values: night.rc8_grid_kw },
  { name: "With basic charge", labels: night.labels, values: night.rc9_grid_kw }],
  { ...chart(), x: RX, y, w: COL, h: 5.4, lineSize: 5, lineDataSymbol: "none", chartColors: [GREY, BLUE], valAxisMinVal: 0, catAxisLabelFrequency: 8,
    showValAxisTitle: true, valAxisTitle: "Grid purchase [kW]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("Fig. 2  Grid purchase over one winter night (22:00–08:00), 90 kW limit", RX, y + 5.45, COL);
y += 6.4;
text(`With the basic charge, the winter peak demand was 359–380 kW regardless of the grid limit (478–750 kW without it). At the 90 kW limit the weekly energy purchased was almost unchanged (${fmt(night.week_grid_kwh[0])} → ${fmt(night.week_grid_kwh[1])} kWh); night charging was spread over time (Fig. 2). The limit is a soft limit with a cost on the excess, so the peak can exceed it. Electric buses served 92–96% of trips in both cases.`,
  { x: RX, y, w: COL, h: 3.9, fontSize: 32 });
y += 4.2;
const half = (COL - 0.6) / 2;
s.addChart(pres.charts.BAR, [
  { name: "Without", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e5) / 10) },
  { name: "With", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e5) / 10) }],
  { ...chart(), x: RX, y, w: half, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 28, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "Basic charge [M JPY/yr]", valAxisTitleFontSize: 28, valAxisTitleColor: SUB,
    showCatAxisTitle: true, catAxisTitle: "Grid limit [kW]", catAxisTitleFontSize: 28, catAxisTitleColor: SUB });
const SE = [["2025-01-06", "Winter"], ["2025-04-07", "Spring"], ["2025-07-07", "Summer"]];
s.addChart(pres.charts.BAR, [
  { name: "All diesel", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "Mixed fleet", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  { ...chart(), x: RX + half + 0.6, y, w: half, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 28, catAxisLabelFontSize: 26, showValAxisTitle: true, valAxisTitle: "CO₂ [t/week]", valAxisTitleFontSize: 28, valAxisTitleColor: SUB });
caption("Fig. 3  Annual basic charge (contract demand = annual peak)", RX, y + 5.25, half, 1.2);
caption("Fig. 4  Weekly CO₂ (all-diesel: estimate from distance)", RX + half + 0.6, y + 5.25, half, 1.2);
y += 6.6;
y = section("5. Conclusions", RX, y, COL);
const b8 = basicYear(peakYear(rc8, 90)) / 1e6, b9 = basicYear(peakYear(rc9, 90)) / 1e6;
text([
  { text: `Spreading charging with the basic charge in the objective lowers the peak demand and the basic charge without a large change in the energy purchased (90 kW limit: ${b8.toFixed(1)} → ${b9.toFixed(1)} million JPY per year).`, options: { breakLine: true } },
  { text: "The mixed fleet emits about 75–85% less CO₂ than an all-diesel fleet.", options: { breakLine: true } },
  { text: "Next: sensitivity of the conditions that favor diesel buses, and the solution quality of trip assignment." }],
  { x: RX, y, w: COL, h: 45.4 - y, paraSpaceAfter: 10, fontSize: 34 });

(async () => {
  const out = path.join(__dirname, "midterm_poster_A0_en.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
