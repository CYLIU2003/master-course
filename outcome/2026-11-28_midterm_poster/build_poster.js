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
const iceHour = JSON.parse(fs.readFileSync(path.join(__dirname, "ice_by_hour_rc8.json"), "utf8"));
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
text("概要　路線バスの電動化では、営業所での充電が重なると受電電力のピークが大きくなり、契約電力に応じた基本料金や受電設備の負担が増える。本研究では、燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を同時に最適化し、受電上限を変えたときの電気バスの担当便と、基本料金を考慮したときの受電ピーク・費用を評価した。受電上限を下げても電気バスの担当便は92.0〜96.5%でほぼ一定であり、基本料金を目的関数に含めると冬の受電ピークが約2.5〜5割低くなった。",
  { x: M, y: 8.0, w: W, h: 3.9, fontSize: 42 });

// ---- Left column
let y = 12.5;
y = section("1．背景と目的", LX, y, COL);
text([
  { text: "路線バスで電気バスの導入が進んでいるが、車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続く。", options: { breakLine: true } },
  { text: "電気料金は、使用電力量に応じた料金と、契約電力（過去1年の最大需要電力）に応じた基本料金からなる。夜間に充電が集中すると後者が大きくなる。", options: { breakLine: true } },
  { text: "本研究の目的は、(1) 受電上限を変えたとき、電気バスに任せられる便の割合と費用・CO₂がどう変わるか、(2) 基本料金を考慮すると、充電計画と費用がどう変わるかを明らかにすることである。" }],
  { x: LX, y, w: COL, h: 8.9, paraSpaceAfter: 14 });
y += 9.2;
y = section("2．対象と条件", LX, y, COL);
const rows = [["対象", "東急バス 渋21〜23系統（弦巻営業所）"], ["運行", "1週間 1,704便"], ["車両", "保有 電気バス35台・燃料バス25台（固定）"],
  ["設備", "太陽光1,000 kW・蓄電池6,000 kWh・充電器90 kW×10"], ["受電上限", "90/200/400/800 kW（超過分に500円/kWh・仮）"], ["期間", "冬・春・夏の代表週（基本料金ありは秋も）"],
  ["単価", "電気30円/kWh・軽油150円/L・基本料金2,530円/kW月"], ["CO₂", "軽油2.62 kg/L、電力0.5 kg/kWh（仮・実値0.452）"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.2, COL - 3.2], fontSize: 34, fontFace: "Yu Gothic", color: INK, rowH: 0.78, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.78 + 1.2;
y = section("3．手法", LX, y, COL);
text([
  { text: "便割当（Stage 1）：1,704便を60台に割り当てる混合整数計画問題。汎用ソルバーだけでは改善しなかったため、一部の便だけを解き直す大近傍探索（LNS）で初期解を改善した。", options: { breakLine: true } },
  { text: "充電計画（Stage 2）：割当を固定し、15分ごとの充電・太陽光・蓄電池・買電を最適化する。", options: { breakLine: true } },
  { text: "毎時の見直し：1時間ごとに計画を立て直しながら1週間を実行し、その結果で費用を集計した。", options: { breakLine: true } },
  { text: "比較：(1) 受電上限4段階 × 冬・春・夏（基本料金を含めない12ケース）、(2) 基本料金を含めた16ケース。" }],
  { x: LX, y, w: COL, h: 42.8 - y, paraSpaceAfter: 18 });

// ---- Right column
y = 12.5;
y = section("4．結果", RX, y, COL);
const WIN = "2025-01-06";
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.LINE, SE.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, w).bev_trip_share_pct * 10) / 10) })),
  { ...chart(), x: RX, y, w: COL, h: 5.4, lineSize: 5, lineDataSymbol: "circle", lineDataSymbolSize: 14, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図1　受電上限と電気バスの担当便（基本料金を含めない場合）", RX, y + 5.45, COL);
y += 6.4;
const shares = rc8.map((r) => r.bev_trip_share_pct);
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
text(`(1) 受電上限を90〜800 kWで変えても、電気バスの担当便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%でほぼ一定だった。燃料バスが担当したのは主に早朝（${rng("05-06")}）と深夜（${rng("22-")}）の便で（図2）、上限を下げても燃料バスに戻る便は増えず、超過分の費用を払う計画となった。`,
  { x: RX, y, w: COL, h: 3.0, fontSize: 33 });
y += 3.3;
const half = (COL - 0.6) / 2;
const BANDS = [["05-06", "早朝"], ["07-21", "日中"], ["22-", "深夜"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10; };
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g}`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  { ...chart(), x: RX, y, w: half, h: 5.0, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", GREY, "7AB8E8", BLUE_DARK], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "燃料バス担当便 [%]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バス併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  { ...chart(), x: RX + half + 0.6, y, w: half, h: 5.0, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("図2　時間帯別の燃料バス担当便（凡例：受電上限 kW）", RX, y + 5.05, half, 1.2, 28);
caption("図3　1週間のCO₂（全車燃料バスは走行距離からの概算）", RX + half + 0.6, y + 5.05, half, 1.2, 28);
y += 6.45;
const avg = (g, k) => { const rs = rc8.filter((r) => r.grid_limit_kw === g); return rs.reduce((a, r) => a + r[k], 0) / rs.length; };
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "上限の超過費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  { ...chart(), x: RX, y, w: COL, h: 5.2, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図4　受電上限と1週間の運用費の内訳（3週平均、車両使用費は除く）", RX, y + 5.25, COL);
y += 6.15;
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
text(`運用費は上限800 kWの約${Math.round(opex(800))}万円/週から90 kWの約${Math.round(opex(90))}万円/週に増えたが、増分はほぼ超過費用で、燃料使用量は約155 L/週で一定だった（図4）。（参考）基本料金を目的関数に含めると、冬の受電ピークは359〜380 kWに下がった。`,
  { x: RX, y, w: COL, h: 3.0, fontSize: 33 });
y += 3.3;
y = section("5．まとめと今後", RX, y, COL);
text([
  { text: "受電上限は、今回の条件では電気バスの担当便と燃料使用量を変えず、超過費用として効いた。燃料バスが担当するのは早朝・深夜の便に限られた。", options: { breakLine: true } },
  { text: "今後：担当便が変わらない原因の検証（便割当段階の買電の見込みと実際の差）、日本の料金体系に沿った再計算、日をまたぐ計画の評価。" }],
  { x: RX, y, w: COL, h: 45.4 - y, paraSpaceAfter: 8, fontSize: 32 });

// ---- Footnote across the bottom
caption("注：便割当は全件、基本料金を含めた充電計画は16件すべて制限時間内の実行可能解（ギャップ13〜67%）。含めない充電計画は12件中11件が最適。最大受電は15分平均。契約電力は実量制（500 kW未満）の考え方で年間最大受電とした。基本料金は東京電力EP（2026年4月、関東・高圧ベーシックプラン）2,530円/kW、力率100%。最適化には旧単価1,890円を使用。",
  LX, 43.2, COL, 2.2, 28);

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
