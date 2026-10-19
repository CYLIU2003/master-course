// Midterm (2026-11-28) A0 portrait poster (841 x 1189 mm), editable PowerPoint.
// Plain academic layout: white background, black text, Tokyo City University blue only for the
// title rule, section headings and the proposed-case series (comparison case in grey).
// Two columns read top to bottom (left, then right); 40 mm outer margin; title >= 72 pt.
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
// Annual basic charge at the current TEPCO EP tariff (Kanto, high voltage, Basic plan, 2026-04-01, tax incl.).
const BASIC_YEN_PER_KW = 2530;
const basicYear = (kw) => kw * BASIC_YEN_PER_KW * 0.85 * 12;

// Tokyo City University blue as used on tcu.ac.jp (#0485D7).
const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "中間発表ポスター 2026-11-28";
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.9, COL = (W - GAP) / 2, LX = M, RX = M + COL + GAP;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`); return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 42, fontFace: "Yu Gothic", lineSpacingMultiple: 1.15, ...o }); };
const section = (label, x, y, w) => {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 1.25, fill: { color: BLUE }, line: { color: BLUE } });
  text(label, { x: x + 0.35, y, w: w - 0.5, h: 1.25, valign: "middle", fontSize: 50, bold: true, color: "FFFFFF" });
  return y + 1.6;
};
const chart = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 32, valAxisLabelFontSize: 28, valGridLine: { color: GRID, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 32, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 30, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt" });
const caption = (t, x, y, w, h = 0.9, fs = 30) => text(t, { x, y, w, h, fontSize: fs, color: SUB });

// ---- Title block: one blue rule under the title; the top-left 20 x 20 cm is kept free for the number.
const NUM = 7.87;
text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M + 0.3, w: W - NUM, h: 3.4, fontSize: 80, bold: true, valign: "middle" });
text("東京都市大学　劉 承洋（研究室名・指導教員をここに記入）", { x: M + NUM, y: M + 3.9, w: W - NUM, h: 1.0, fontSize: 44, color: SUB });
s.addShape(pres.shapes.LINE, { x: M, y: M + 5.6, w: W, h: 0, line: { color: BLUE, width: 8 } });

// ---- Abstract (full width)
text("概要　路線バスの電動化では、営業所での充電が重なると受電電力のピークが大きくなり、契約電力に応じた基本料金や受電設備の負担が増える。本研究では、燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を同時に最適化し、受電上限と基本料金が費用とCO₂に与える影響を評価した。基本料金を目的関数に含めた場合、買電量を大きく変えずに、冬の受電ピークが約2.5〜5割低くなった。",
  { x: M, y: 8.0, w: W, h: 3.9, fontSize: 42 });

// ---- Left column
let y = 12.5;
y = section("1．背景と目的", LX, y, COL);
text([
  { text: "路線バスで電気バスの導入が進んでいるが、車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続く。", options: { breakLine: true } },
  { text: "電気料金は、使用電力量に応じた料金と、契約電力（過去1年の最大需要電力）に応じた基本料金からなる。夜間に充電が集中すると後者が大きくなる。", options: { breakLine: true } },
  { text: "本研究の目的は、受電上限と基本料金の有無が、便割当・充電計画・費用・CO₂に与える影響を明らかにすることである。" }],
  { x: LX, y, w: COL, h: 7.6, paraSpaceAfter: 18 });
y += 8.0;
y = section("2．対象と条件", LX, y, COL);
const rows = [["対象", "東急バス 渋21〜23系統（弦巻営業所）"], ["運行", "1週間 1,704便"], ["車両", "保有 電気バス35台・燃料バス25台（固定）"],
  ["設備", "太陽光1,000 kW・蓄電池6,000 kWh・充電器90 kW×10"], ["受電上限", "90/200/400/800 kW（超過分に500円/kWh・仮）"], ["期間", "冬・春・夏の代表週（基本料金ありは秋も）"],
  ["単価", "電気30円/kWh・軽油150円/L・基本料金2,530円/kW月"], ["CO₂", "軽油2.62 kg/L、電力0.5 kg/kWh（仮・実値0.452）"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.2, COL - 3.2], fontSize: 34, fontFace: "Yu Gothic", color: INK, rowH: 0.78, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.78 + 1.5;
y = section("3．手法", LX, y, COL);
text([
  { text: "便割当（Stage 1）：1,704便を60台に割り当てる混合整数計画問題。汎用ソルバーだけでは改善しなかったため、一部の便だけを解き直す大近傍探索（LNS）で初期解を改善した。", options: { breakLine: true } },
  { text: "充電計画（Stage 2）：割当を固定し、15分ごとの充電・太陽光・蓄電池・買電を最適化する。", options: { breakLine: true } },
  { text: "毎時の見直し：1時間ごとに計画を立て直しながら1週間を実行し、その結果で費用を集計した。", options: { breakLine: true } },
  { text: "比較：目的関数に基本料金を含めない場合と含める場合の2通りで計算した。" }],
  { x: LX, y, w: COL, h: 42.8 - y, paraSpaceAfter: 18 });

// ---- Right column
y = 12.5;
y = section("4．結果", RX, y, COL);
const WIN = "2025-01-06";
s.addChart(pres.charts.BAR, [
  { name: "基本料金を含めない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金を含める", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  { ...chart(), x: RX, y, w: COL, h: 6.4, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE],
    showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0, showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "最大受電電力 [kW]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図1　冬の代表週における最大受電電力", RX, y + 6.45, COL);
y += 7.4;
s.addChart(pres.charts.LINE, [
  { name: "基本料金を含めない", labels: night.labels, values: night.rc8_grid_kw },
  { name: "基本料金を含める", labels: night.labels, values: night.rc9_grid_kw }],
  { ...chart(), x: RX, y, w: COL, h: 5.4, lineSize: 5, lineDataSymbol: "none", chartColors: [GREY, BLUE], valAxisMinVal: 0, catAxisLabelFrequency: 8,
    showValAxisTitle: true, valAxisTitle: "買電電力 [kW]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図2　受電上限90 kW・冬の一晩（22時〜8時）の買電電力", RX, y + 5.45, COL);
y += 6.4;
text(`基本料金を含めると、冬の最大受電電力は受電上限によらず359〜380 kWとなった（含めない場合は478〜750 kW）。上限90 kWの例では1週間の買電量はほぼ同じで（${night.week_grid_kwh[0].toLocaleString()} → ${night.week_grid_kwh[1].toLocaleString()} kWh）、夜間の充電を分散させてピークを下げていた（図2）。受電上限は超過分に追加費用を課す目安のため、ピークが上限を超える場合がある。電気バスが担当する便の割合は92〜96%で、ほぼ変わらなかった。`,
  { x: RX, y, w: COL, h: 3.9, fontSize: 34 });
y += 4.2;
const half = (COL - 0.6) / 2;
s.addChart(pres.charts.BAR, [
  { name: "含めない", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e4)) },
  { name: "含める", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e4)) }],
  { ...chart(), x: RX, y, w: half, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 28, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "基本料金 [万円/年]", valAxisTitleFontSize: 28, valAxisTitleColor: SUB,
    showCatAxisTitle: true, catAxisTitle: "受電上限 [kW]", catAxisTitleFontSize: 28, catAxisTitleColor: SUB });
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バス併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  { ...chart(), x: RX + half + 0.6, y, w: half, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 28, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]", valAxisTitleFontSize: 28, valAxisTitleColor: SUB });
caption("図3　年間の基本料金（契約電力＝年間最大受電）", RX, y + 5.25, half, 1.2);
caption("図4　1週間のCO₂（全車燃料バスは走行距離からの概算）", RX + half + 0.6, y + 5.25, half, 1.2);
y += 6.6;
y = section("5．まとめと今後", RX, y, COL);
text([
  { text: `基本料金を考慮して充電を分散させると、買電量を大きく変えずに受電ピークと基本料金を下げられる（上限90 kWで年約${Math.round(basicYear(peakYear(rc8, 90)) / 1e4).toLocaleString()}万円→${Math.round(basicYear(peakYear(rc9, 90)) / 1e4).toLocaleString()}万円）。`, options: { breakLine: true } },
  { text: "電気バスとの併用で、CO₂は全車燃料バスより約75〜85%少なかった。", options: { breakLine: true } },
  { text: "今後：便割当段階の充電の見込みと実際の買電の差の検証、燃料バスへの振り替え条件の感度分析。" }],
  { x: RX, y, w: COL, h: 45.4 - y, paraSpaceAfter: 10, fontSize: 36 });

// ---- Footnote across the bottom
caption("注：便割当は全件、基本料金を含めた充電計画は16件すべて制限時間内の実行可能解（ギャップ13〜67%）。含めない充電計画は12件中11件が最適。最大受電は15分平均。契約電力は実量制（500 kW未満）の考え方で年間最大受電とした。基本料金は東京電力EP（2026年4月、関東・高圧ベーシックプラン）2,530円/kW、力率100%。最適化には旧単価1,890円を使用。",
  LX, 43.2, COL, 2.2, 28);

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
