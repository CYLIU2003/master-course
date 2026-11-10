// Shared figure blocks for the A0 poster (JP: build_poster_rc33.js, EN: build_poster_rc33_en.js), 2026-11-10.
// systemDiagram: Fig. 2, the depot's energy system as a one-line diagram with icons (icons/*.png, make_icons.js).
// flowDiagram:   Fig. 3, the calculation flow (Stage 1 -> Stage 2 day-ahead -> hourly re-plan -> accounting).
// hourlyFlow:    Fig. 6, executed energy flows by hour of day (hourly_flow_900_winter.json, hourly_flow_base.py).
const path = require("path");
const fs = require("fs");
const ICON = (n) => path.join(__dirname, "icons", `${n}.png`);
const BLUE = "0485D7", BLUE_DARK = "0268B0", INK = "222222", SUB = "555555", GREY = "9A9A9A";

function systemDiagram(s, pres, x, y, w, L, font, fs = 26) {
  const ic = 1.25, lx = x + ic + 0.2, barX = x + 6.3;
  const rows = [["pv", L.pv, "→"], ["battery", L.battery, "↔"], ["grid", L.grid, "→"]];
  rows.forEach(([n, lab, dir], i) => {
    const yy = y + 0.05 + i * 1.45, cy = yy + ic / 2;
    s.addImage({ path: ICON(n), x, y: yy, w: ic, h: ic, altText: lab.replace(/\n/g, " ") });
    s.addText(lab, { isTextBox: true, x: lx, y: yy, w: barX - lx - 0.75, h: ic, fontSize: fs, fontFace: font, color: INK, valign: "middle", margin: 0 });
    s.addShape(pres.shapes.LINE, { x: barX - 0.7, y: cy, w: 0.65, h: 0, line: { color: n === "pv" ? "F2A900" : n === "grid" ? "555555" : BLUE, width: 5,
      endArrowType: "triangle", beginArrowType: dir === "↔" ? "triangle" : undefined } });
  });
  // the depot's switchboard as a vertical bar
  s.addShape(pres.shapes.RECTANGLE, { x: barX, y: y + 0.45, w: 0.16, h: 3.45, fill: { color: INK }, line: { color: INK } });
  const cy = y + 0.05 + 1.45 + ic / 2;
  s.addShape(pres.shapes.LINE, { x: barX + 0.2, y: cy, w: 0.6, h: 0, line: { color: BLUE, width: 5, endArrowType: "triangle" } });
  const chX = barX + 0.85, ch = 1.45;
  s.addImage({ path: ICON("charger"), x: chX, y: cy - ch / 2, w: ch, h: ch, altText: L.charger.replace(/\n/g, " ") });
  s.addText(L.charger, { isTextBox: true, x: chX - 0.5, y: cy + ch / 2 + 0.05, w: ch + 1.0, h: 0.9, fontSize: fs - 2, fontFace: font, color: INK, align: "center", margin: 0 });
  s.addShape(pres.shapes.LINE, { x: chX + ch + 0.05, y: cy, w: 0.6, h: 0, line: { color: BLUE, width: 5, endArrowType: "triangle" } });
  const bw = 1.75, ebX = chX + ch + 0.7, dbX = x + w - bw - 0.15;
  [["ebus", L.ebus, ebX], ["dbus", L.dbus, dbX]].forEach(([n, lab, bx]) => {
    s.addImage({ path: ICON(n), x: bx, y: cy - bw / 2, w: bw, h: bw, altText: lab.replace(/\n/g, " ") });
    s.addText(lab, { isTextBox: true, x: bx - 0.55, y: cy + bw / 2 - 0.05, w: bw + 1.1, h: 0.9, fontSize: fs - 2, fontFace: font, color: INK, align: "center", margin: 0 });
  });
  // the two fleets share the timetable
  const top = cy - bw / 2 - 0.15;
  s.addShape(pres.shapes.LINE, { x: ebX + bw / 2, y: top, w: dbX - ebX, h: 0, line: { color: SUB, width: 2.5, beginArrowType: "triangle", endArrowType: "triangle" } });
  s.addText(L.share, { isTextBox: true, x: ebX - 0.3, y: top - 0.95, w: dbX + bw - ebX + 0.45, h: 0.85, fontSize: fs - 2, fontFace: font, color: SUB, align: "center", valign: "bottom", margin: 0 });
  return 4.45;
}

function flowDiagram(s, pres, x, y, w, steps, font, h = 3.7, fs = 22) {
  const gap = 0.42, bw = (w - gap * (steps.length - 1)) / steps.length;
  steps.forEach(([head, body], i) => {
    const bx = x + i * (bw + gap);
    s.addShape(pres.shapes.RECTANGLE, { x: bx, y, w: bw, h, fill: { color: "F4F7FA" }, line: { color: BLUE, width: 2 } });
    s.addShape(pres.shapes.RECTANGLE, { x: bx, y, w: bw, h: 1.05, fill: { color: i === steps.length - 1 ? BLUE_DARK : BLUE }, line: { color: BLUE, width: 2 } });
    s.addText(head, { isTextBox: true, x: bx + 0.1, y, w: bw - 0.2, h: 1.05, fontSize: fs + 2, bold: true, color: "FFFFFF", fontFace: font, align: "center", valign: "middle", margin: 0 });
    s.addText(body.map((t, k, a) => ({ text: t, options: { bullet: true, breakLine: k < a.length - 1 } })),
      { isTextBox: true, x: bx + 0.12, y: y + 1.15, w: bw - 0.2, h: h - 1.25, fontSize: fs, color: INK, fontFace: font, valign: "top", margin: 0, paraSpaceAfter: 4, lineSpacingMultiple: 1.05 });
    if (i < steps.length - 1) s.addShape(pres.shapes.ISOSCELES_TRIANGLE,
      { x: bx + bw + 0.07, y: y + h / 2 - 0.22, w: 0.28, h: 0.44, rotate: 90, fill: { color: BLUE }, line: { color: BLUE } });
  });
}

const FLOW = JSON.parse(fs.readFileSync(path.join(__dirname, "hourly_flow_900_winter.json"), "utf8"));
function hourlyFlow(s, pres, base, x, y, w, h, names, axes, key = "bev") {
  const hrs = FLOW[key].hours, cats = hrs.map((_, i) => String(i));
  const series = [["pv_to_bess", names[0]], ["pv_to_bus", names[1]], ["bess_to_bus", names[2]], ["grid_to_bus", names[3]], ["pv_curtail", names[4]]];
  s.addChart(pres.charts.BAR, series.map(([k, n]) => ({ name: n, labels: cats, values: hrs.map((r) => Math.round(r[k] / 100) / 10) })),
    { ...base, x, y, w, h, barDir: "col", barGrouping: "stacked", barGapWidthPct: 25, chartColors: ["F6C443", "E08A00", BLUE, "264478", "D0D0D0"],
      valAxisMinVal: 0, catAxisLabelFrequency: 3, catAxisLabelFontSize: 24, valAxisLabelFontSize: 24, legendFontSize: 22, legendPos: "t",
      showCatAxisTitle: true, catAxisTitle: axes[0], catAxisTitleFontSize: 24, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: axes[1], valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
  return FLOW[key];
}
module.exports = { systemDiagram, flowDiagram, hourlyFlow, FLOW };
