// Midterm (2026-11-28) A0 portrait poster (841 x 1189 mm), editable PowerPoint.
// Guidance followed: A0 title >= 72 pt and body >= 48 pt, 35-50 mm outer margin, top ~20 cm
// for title with the top-left 20 x 20 cm left free for the abstract number, Z reading order with
// the key result large in the middle, groups shown by a background tint instead of frames,
// one theme colour plus one accent, flat design (no shadow / gradient), left-aligned text.
// Data: verified rc8 (no basic charge) and rc9 (basic charge) tables copied next to this file.
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
const basicYear = (kw) => kw * (kw >= 500 ? 1989 : 1890) * 0.85 * 12; // JPY/year, contract = annual max demand

const THEME = { name: "Midterm poster", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: "1B2A2F", lt1: "FFFFFF", dk2: "0F4C5C", lt2: "EEF4F3", accent1: "1F7A8C", accent2: "E07A2E",
            accent3: "5FA84A", accent4: "C9A227", accent5: "6C5B9E", accent6: "B23A48", hlink: "1F7A8C", folHlink: "6C5B9E" } };
const HEX = { teal: "1F7A8C", deep: "0F4C5C", orange: "E07A2E", ink: "1B2A2F", muted: "4F5E63", grid: "D9E2E1", tint: "EEF4F3" };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "中間発表ポスター 2026-11-28";
const C = pres.SchemeColor;
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.6, COL = (W - GAP) / 2;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: HEX.ink, fontSize: 48, fontFace: "Yu Gothic", ...o });
const block = (x, y, w, h) => s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: HEX.tint }, line: { color: HEX.tint } });
const heading = (n, t, x, y, w) => {
  s.addShape(pres.shapes.OVAL, { x, y, w: 1.25, h: 1.25, fill: { color: C.accent1 }, line: { color: C.accent1 } });
  text(String(n), { x, y, w: 1.25, h: 1.25, align: "center", valign: "middle", fontSize: 54, bold: true, color: C.background1 });
  text(t, { x: x + 1.55, y: y - 0.05, w: w - 1.55, h: 1.35, valign: "middle", fontSize: 58, bold: true, color: C.text2 });
};
const chart = (title) => ({ showTitle: true, title, titleFontFace: "+mn-lt", titleFontSize: 40, titleColor: HEX.ink,
  catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 34, valAxisLabelFontSize: 30, valGridLine: { color: HEX.grid, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 34, legendColor: HEX.ink, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 32, dataLabelColor: HEX.ink,
  showLegend: true, legendPos: "t" });

// ---- Title band (top ~20 cm); the top-left 20 x 20 cm stays free for the abstract number.
const NUM = 7.87;
s.addShape(pres.shapes.RECTANGLE, { x: M, y: M, w: NUM - 0.4, h: 6.3, fill: { color: "FFFFFF" }, line: { color: HEX.grid, width: 2, dashType: "dash" } });
text("（演題番号）", { x: M, y: M + 2.7, w: NUM - 0.4, h: 0.8, align: "center", fontSize: 36, color: HEX.muted });
text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M + 0.1, w: W - NUM, h: 4.2, fontSize: 92, bold: true, color: C.text2, valign: "middle" });
text("劉 承洋（所属・研究室名をここに記入）", { x: M + NUM, y: M + 4.5, w: W - NUM, h: 1.0, fontSize: 44, color: HEX.muted });

// ---- Key message band
s.addShape(pres.shapes.RECTANGLE, { x: M, y: 8.3, w: W, h: 2.6, fill: { color: C.accent1 }, line: { color: C.accent1 } });
text([{ text: "電気バスの充電を「ならす」と、営業所の受電ピークをほぼ半分にでき、", options: { breakLine: true } },
  { text: "1年の基本料金を約2〜5割減らせる（使う電気の量はほぼ同じ）" }],
  { x: M + 0.6, y: 8.5, w: W - 1.2, h: 2.2, fontSize: 60, bold: true, color: C.background1, valign: "middle" });

// ---- Row A: background / method
let y = 11.4;
block(M, y, COL, 8.6); block(M + COL + GAP, y, COL, 8.6);
heading(1, "背景と目的", M + 0.6, y + 0.6, COL - 1.2);
text([
  { text: "バス会社は脱炭素（GX）のため電気バスを導入中。当面は燃料バスと併用する", options: { bullet: { indent: 40 }, breakLine: true } },
  { text: "電気料金は「使った量」と、1年で最も多く使った瞬間で決まる「基本料金」の2つ", options: { bullet: { indent: 40 }, breakLine: true } },
  { text: "充電が重なると基本料金が大きくなる", options: { bullet: { indent: 40 }, breakLine: true } },
  { text: "目的：受電上限と基本料金が、便の割当・充電計画・費用・CO₂に与える影響を明らかにする", options: { bullet: { indent: 40 }, bold: true, color: C.text2 } }],
  { x: M + 0.6, y: y + 2.2, w: COL - 1.2, h: 6.2, fontSize: 44, paraSpaceAfter: 12 });
const mx = M + COL + GAP;
heading(2, "方法", mx + 0.6, y + 0.6, COL - 1.2);
[["便割当", "1,704便を60台（電気35・燃料25）に割り当てる（MILP＋LNSで改善）"],
 ["充電計画", "15分ごとに充電・太陽光・蓄電池・受電を決める（MILP）"],
 ["毎時の見直し", "1時間ごとに計画を立て直して1週間を実行（175回）"]].forEach(([h, b], i) => {
  const yy = y + 2.2 + i * 1.85;
  s.addShape(pres.shapes.RECTANGLE, { x: mx + 0.6, y: yy, w: 3.6, h: 1.55, fill: { color: C.accent1 }, line: { color: C.accent1 } });
  text(h, { x: mx + 0.6, y: yy, w: 3.6, h: 1.55, align: "center", valign: "middle", fontSize: 40, bold: true, color: C.background1 });
  text(b, { x: mx + 4.5, y: yy, w: COL - 5.4, h: 1.55, valign: "middle", fontSize: 36 });
});
text("対象：東急バス渋21〜23系統（弦巻営業所）、PV 1,000 kW・蓄電池 6,000 kWh、冬・春・夏・秋の代表週 × 受電上限 90/200/400/800 kW",
  { x: mx + 0.6, y: y + 7.75, w: COL - 1.2, h: 0.75, fontSize: 28, color: HEX.muted });

// ---- Row B: key result, large and central
y = 20.6;
block(M, y, W, 12.2);
heading(3, "結果①　基本料金を考えると、受電ピークがほぼ半分になる", M + 0.6, y + 0.6, W - 1.2);
const WIN = "2025-01-06";
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考えない", labels: LIMITS.map((g) => `上限${g}kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金を考える", labels: LIMITS.map((g) => `上限${g}kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  { ...chart("冬の1週間の最大受電電力（kW）"), x: M + 0.6, y: y + 2.2, w: COL - 0.9, h: 9.7, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0 });
s.addChart(pres.charts.LINE, [
  { name: "基本料金を考えない", labels: night.labels, values: night.rc8_grid_kw },
  { name: "基本料金を考える", labels: night.labels, values: night.rc9_grid_kw }],
  { ...chart("ある冬の夜の受電（kW、上限90kW）"), x: M + COL + GAP + 0.3, y: y + 2.2, w: COL - 0.9, h: 7.3, lineSize: 6, lineDataSymbol: "none",
    chartColors: [HEX.orange, HEX.teal], valAxisMinVal: 0, catAxisLabelFrequency: 8 });
text([{ text: `1週間に買った電気はほぼ同じ：${night.week_grid_kwh[0].toLocaleString()}→${night.week_grid_kwh[1].toLocaleString()} kWh`, options: { breakLine: true } },
  { text: "夜の長い時間に充電を分けて、山を低くした。", options: { bold: true, color: C.text2 } }],
  { x: M + COL + GAP + 0.6, y: y + 9.6, w: COL - 1.2, h: 2.4, fontSize: 38 });

// ---- Row C: annual basic charge and CO2
y = 33.4;
block(M, y, COL, 9.4); block(M + COL + GAP, y, COL, 9.4);
heading(4, "結果②　1年の基本料金", M + 0.6, y + 0.6, COL - 1.2);
s.addChart(pres.charts.BAR, [
  { name: "考えない", labels: LIMITS.map((g) => `上限${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e4)) },
  { name: "考える", labels: LIMITS.map((g) => `上限${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e4)) }],
  { ...chart("1年の基本料金（万円）"), x: M + 0.4, y: y + 2.1, w: COL - 0.8, h: 6.3, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0 });
text("契約電力＝1年の最大受電、単価 1,890円/kW（500 kW以上 1,989円）×0.85×12か月", { x: M + 0.6, y: y + 8.45, w: COL - 1.2, h: 0.8, fontSize: 28, color: HEX.muted });
const cx = M + COL + GAP;
heading(5, "結果③　CO₂は約8割減", cx + 0.6, y + 0.6, COL - 1.2);
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全部燃料バス（目安）", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  { ...chart("1週間のCO₂（t）"), x: cx + 0.4, y: y + 2.1, w: COL - 0.8, h: 6.3, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0 });
text("全部燃料バスは走行距離からの単純計算（最適化の結果ではない）。電気バス併用は受電上限800 kW", { x: cx + 0.6, y: y + 8.45, w: COL - 1.2, h: 0.8, fontSize: 28, color: HEX.muted });

// ---- Row D: conclusion and next steps
y = 43.3;
text([{ text: "まとめ　", options: { bold: true, color: C.accent2 } },
  { text: "基本料金まで考えて充電をならすと、受電設備と基本料金を小さくできる。今後：燃料バスに切り替えた方が得になる条件の感度分析、下界の強化。" }],
  { x: M, y, w: W, h: 1.3, fontSize: 40 });
text("解の質：停止条件のギャップ1%、制限時間内の実行可能解を含む。全ケースで毎時の見直し後の確定会計を検査済み。電気料金単価は東京電力EP業務用・高圧の値。",
  { x: M, y: y + 1.35, w: W, h: 0.55, fontSize: 26, color: HEX.muted });

(async () => {
  const out = path.join(__dirname, "midterm_poster_A0.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
