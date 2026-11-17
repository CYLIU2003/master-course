// Consultation deck for Prof. Nishiyama, 2026-11 (purpose first, latest pillar-A results, link to his research,
// pillar-C directions, questions, thanks; technical details in the appendix).
// Revised 2026-11-16 after a Gemini review: polite wording, consultation purpose up front, pillar-C candidates
// re-ordered by their link to his published work (mobility, universal design, electric full-flat bus, co-creation).
// Revised 2026-11-17 after a second Gemini review (naturalness): label bands, check marks and repeated formulaic honorifics removed;
// slide 2 shows the three pillars and schedule; the result slide carries the bridge to pillar C; no separate thanks slide (main deck = 9 slides).
// Data: the verified cases used by the midterm poster (DIAGNOSTIC, earlier versions, 30 JPY/kWh series); totals exclude the CO2 cost.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");


const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "西山先生へのご相談 2026-11";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "2026年11月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 8, ...o });
const chart = (o) => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleColor: SUB, catAxisTitleColor: SUB, valAxisTitleFontSize: 12, catAxisTitleFontSize: 12, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const tableOpts = (o) => ({ fontSize: 14, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center" } });
const B = (t) => ({ text: t, options: { bold: true } });
const heading = (s, t, y, x = 0.6, w = 12.1) => text(s, t, { x, y, w, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
const box = (s, x, y, w, h, fill = BLUE_PALE, line = GRID) => s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 0.75 } });
const arrow = (s, x, y, w) => s.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color: GREY, width: 2, endArrowType: "triangle" } });

// ---------------- data: the same verified cases as the midterm poster (DIAGNOSTIC, 30 JPY/kWh all-inclusive series)
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_latest.json"), "utf8"));
const CO2_YEN_PER_KG = 1; // in the objective only; never in a reported total (user decision 2026-11-16)
[...DATA.cases, ...DATA.pairs].forEach((r) => { if (r.total_cost_fuel_consumed != null) r.total_cost_reported = r.total_cost_fuel_consumed - r.total_co2_kg * CO2_YEN_PER_KG; });
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const LIMITS = DATA.limits;
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const SEASON_OF = Object.fromEntries(SEASONS);
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const pairOf = (g, w, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
const man = (v) => (v / 1e4).toFixed(1);
const fmt = (v) => Math.round(v).toLocaleString("ja-JP");
const lab = (r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const maxTimeouts = Math.max(...DATA.pairs.filter((r) => r.status === "VERIFIED").map((r) => r.rolling_time_limit_steps));
const p9b = pairOf(900, "2025-01-06", "bev"), p9i = pairOf(900, "2025-01-06", "ice");
const p90b = pairOf(90, "2025-01-06", "bev"), p90i = pairOf(90, "2025-01-06", "ice");
const tc = (r) => r.total_cost_reported;
const co2Ratio = (p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1);
const PROVISIONAL = "数値は条件をそろえる前の暫定値で、研究の結論には使っていません（現在、全ケースを同じ条件で計算し直しています）";

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "西山 敏樹 先生　ご相談資料", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.8, w: 11.5, h: 1.8, fontSize: 32, bold: true, valign: "bottom" });
text(s, "研究の進捗のご報告と、3本目の柱についてのご相談", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年11月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- helpers for the picture-first main slides
const ICON = (n) => { const p = path.join(__dirname, "icons", `${n}.png`); return fs.existsSync(p) ? p : path.join(__dirname, "..", "2026-11-28_midterm_poster", "icons", `${n}.png`); };
const icon = (s, n, x, y, w, alt) => s.addImage({ path: ICON(n), x, y, w, h: w, altText: alt || n });
const card = (s, x, y, w, h, fill = BLUE_PALE) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: GRID, width: 0.75 } });
const down = (s, x, y) => s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x, y, w: 0.34, h: 0.2, rotate: 180, fill: { color: GREY }, line: { color: GREY } });
const right = (s, x, y) => s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x, y, w: 0.3, h: 0.22, rotate: 90, fill: { color: BLUE }, line: { color: BLUE } });

// ---- 2. Today's purpose and the whole research (2026-11-17: agenda list replaced by the three pillars and their schedule)
s = page("今日のご相談と、研究の全体");
box(s, 0.6, 1.55, 12.1, 1.1, "DCEBF7");
text(s, "これまで電力と費用の面から研究を進めてきました。3本目の柱（柱C）では、利用者や地域にとっての価値も考えたいと思っています。その方向性について、ご相談させてください。",
  { x: 0.85, y: 1.6, w: 11.6, h: 1.0, fontSize: 16, valign: "middle" });
heading(s, "研究の3本の柱と予定", 2.95);
const hiC = { fill: { color: "DCEBF7" } };
s.addTable([
  [H("柱"), H("内容"), H("予定")],
  [{ text: "A", options: { bold: true, align: "center" } }, "受け取れる電力の上限と、電気バスの担当便・費用・CO₂", "11/28 中間発表（再計算中）\n2027年3月 電気学会全国大会"],
  [{ text: "B", options: { bold: true, align: "center" } }, "1日ずつと数日まとめての計画の比較、蓄電池の使い方", "2027年度 学会発表\n2027年11月 修士2年中間発表"],
  [{ text: "C", options: { bold: true, align: "center", ...hiC } }, { text: "利用者・地域にとっての価値（今日ご相談したい点）", options: { bold: true, color: BLUE_DARK, ...hiC } }, { text: "2028年2月 修士最終発表\n（設備の決め方の指針とあわせて）", options: hiC }]],
  tableOpts({ x: 0.6, y: 3.35, w: 12.1, colW: [0.9, 6.6, 4.6], fontSize: 14, rowH: [0.5, 0.72, 0.72, 0.72] }));
caption(s, "今日は、結果を5分ほどでご報告したあと、柱Cについてご相談させてください。計算条件などの詳細は、末尾の補足にまとめています。", 0.6, 6.45, 12.1);

// ---- 3. Background (picture-first; plain sentences, no label bands)
s = page("研究の背景");
card(s, 0.6, 1.5, 3.9, 0.45, "DCEBF7");
text(s, "2050年カーボンニュートラル（2020年10月宣言）", { x: 0.65, y: 1.5, w: 3.8, h: 0.45, fontSize: 11, bold: true, color: BLUE_DARK, valign: "middle", align: "center" });
s.addChart(pres.charts.DOUGHNUT, [{ name: "CO₂排出量", labels: ["運輸部門", "その他"], values: [19.3, 80.7] }],
  { x: 0.75, y: 2.05, w: 3.6, h: 3.3, holeSize: 62, chartColors: [BLUE, "DDDDDD"], showLegend: false, showValue: false, showPercent: false, showTitle: false, dataBorder: { pt: 1, color: "FFFFFF" } });
text(s, "19.3%", { x: 0.75, y: 3.3, w: 3.6, h: 0.55, fontSize: 30, bold: true, color: BLUE_DARK, align: "center", valign: "middle" });
text(s, "運輸部門", { x: 0.75, y: 3.85, w: 3.6, h: 0.35, fontSize: 13, color: SUB, align: "center" });
text(s, "日本のCO₂排出量に占める運輸部門の割合\nそのうち約86%が自動車", { x: 0.6, y: 5.4, w: 3.9, h: 0.6, fontSize: 13, align: "center" });
caption(s, "2024年度、国土交通省", 0.6, 6.0, 3.9, 0.3);
const BG = [
  [["ebus", "dbus"], "電気バスは一度には入れ替えられないので、\nしばらくは燃料バスと一緒に走ります"],
  [["moon", "charger", "ebus"], "電気バスは夜、営業所でまとめて充電します"],
  [["grid"], "そのぶん営業所が受け取る電力が大きくなり、\n設備の増強や電気料金の負担になります"]];
BG.forEach(([ics, t], i) => {
  const y = 1.5 + i * 1.45;
  card(s, 4.9, y, 7.8, 1.15);
  ics.forEach((n, k) => icon(s, n, 5.05 + k * 0.85, y + 0.17, 0.8));
  text(s, t, { x: 7.75, y: y + 0.1, w: 4.8, h: 0.95, fontSize: 16, valign: "middle" });
  if (i < BG.length - 1) down(s, 8.6, y + 1.2);
});
text(s, "そこで、今の時刻表どおりに走らせながら受け取る電力を抑え、\n電気バスでCO₂を減らす計画を考えています。",
  { x: 4.9, y: 5.95, w: 7.8, h: 0.75, fontSize: 15, bold: true, color: BLUE_DARK, valign: "middle" });

// ---- 4. Target (route map = poster Fig. 2)
s = page("東急バスの渋21〜23系統と弦巻営業所を対象にしました");
const MAPW = 6.4, MAPH = MAPW * 1409 / 2700;
s.addImage({ path: path.join(__dirname, "..", "2026-11-28_midterm_poster", "route_map_ja_poster.png"), x: 0.6, y: 1.5, w: MAPW, h: MAPH,
  altText: "渋21・渋22・渋23の路線図と弦巻営業所の位置" });
text(s, "停留所の位置は公共交通オープンデータ（ODPT）、停留所の間は直線。背景は © OpenStreetMap contributors", { x: 0.6, y: 1.5 + MAPH + 0.05, w: MAPW, h: 0.4, fontSize: 10, color: SUB });
const TILES = [["ebus", "電気バス", "35台"], ["dbus", "燃料バス", "25台"], ["calendar", "1週間の便", "1,704便"], ["charger", "充電器", "10基"]];
TILES.forEach(([n, l, v], i) => {
  const x = 7.3 + (i % 2) * 2.75, y = 1.5 + Math.floor(i / 2) * 0.98;
  card(s, x, y, 2.6, 0.86);
  icon(s, n, x + 0.1, y + 0.1, 0.66);
  text(s, [{ text: l, options: { fontSize: 11, color: SUB, breakLine: true } }, { text: v, options: { fontSize: 17, bold: true, color: INK } }], { x: x + 0.85, y: y + 0.06, w: 1.7, h: 0.76, valign: "middle", lineSpacingMultiple: 1.0 });
});
card(s, 7.3, 3.46, 5.35, 0.86);
icon(s, "pv", 7.4, 3.56, 0.66); icon(s, "battery", 8.1, 3.56, 0.66);
text(s, "太陽光パネルと蓄電池は、\n営業所に設置すると想定しています", { x: 8.9, y: 3.46, w: 3.65, h: 0.86, fontSize: 12.5, valign: "middle" });
text(s, "比べた条件", { x: 7.3, y: 4.5, w: 5.4, h: 0.35, fontSize: 14, bold: true, color: BLUE_DARK });
[[7.3, 2.1, "営業所が受け取れる\n電力の上限（4段階）\n90・200・400・900 kW"], [9.7, 1.7, "季節\n冬・春・夏\n各1週間"], [11.7, 1.0, "12\n通り"]].forEach(([x, w, t], i) => {
  card(s, x, 4.9, w, 1.05, i === 2 ? "DCEBF7" : "FFFFFF");
  text(s, t, { x: x + 0.05, y: 4.9, w: w - 0.1, h: 1.05, fontSize: i === 2 ? 15 : 11.5, bold: i === 2, color: i === 2 ? BLUE_DARK : INK, align: "center", valign: "middle", lineSpacingMultiple: 1.05 });
});
text(s, "×", { x: 9.4, y: 4.9, w: 0.3, h: 1.05, fontSize: 18, color: SUB, align: "center", valign: "middle" });
text(s, "＝", { x: 11.4, y: 4.9, w: 0.3, h: 1.05, fontSize: 18, color: SUB, align: "center", valign: "middle" });
text(s, "この12通りで、電気バスが担当できる便・費用・CO₂がどう変わるかを比べました。", { x: 0.6, y: 6.2, w: 12.1, h: 0.5, fontSize: 15, bold: true, color: BLUE_DARK, valign: "middle" });

// ---- 5. What is decided (plain-language picture; the formula and the flow are in appendix A2)
s = page("どのバスがどの便を走り、いつ充電するかを計算で決めます");
text(s, "イメージ図（1日の計画の例。実際の計算結果ではありません）", { x: 0.6, y: 1.45, w: 7.9, h: 0.3, fontSize: 11, color: SUB });
const XA = 2.15, XB = 8.35, hx = (h) => XA + (h - 5) / 24 * (XB - XA);
const LANES = [
  ["ebus", "電気バス①", [[6, 9.2, "T"], [10.3, 13, "T"], [13.3, 15.6, "C"], [16, 19.6, "T"], [21.5, 27, "C"]]],
  ["ebus", "電気バス②", [[7, 10.2, "T"], [10.6, 13.5, "C"], [17, 21, "T"], [22.5, 28.5, "C"]]],
  ["dbus", "燃料バス", [[6.4, 12, "T2"], [13, 20.5, "T2"]]]];
LANES.forEach(([n, lab, bars], i) => {
  const y = 2.0 + i * 0.95;
  icon(s, n, 0.6, y, 0.55);
  text(s, lab, { x: 1.15, y, w: 1.0, h: 0.55, fontSize: 11.5, valign: "middle" });
  s.addShape(pres.shapes.LINE, { x: XA, y: y + 0.27, w: XB - XA, h: 0, line: { color: GRID, width: 0.75 } });
  bars.forEach(([a, b, k]) => {
    const fill = k === "C" ? "F2A900" : k === "T2" ? GREY : BLUE;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: hx(a), y: y + 0.02, w: hx(b) - hx(a), h: 0.5, rectRadius: 0.06, fill: { color: fill }, line: { color: fill } });
    text(s, k === "C" ? "充電" : "便", { x: hx(a), y: y + 0.02, w: hx(b) - hx(a), h: 0.5, fontSize: 11, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  });
});
s.addShape(pres.shapes.LINE, { x: XA, y: 4.75, w: XB - XA, h: 0, line: { color: SUB, width: 1 } });
[[6, "6時"], [12, "12時"], [18, "18時"], [24, "0時"], [28, "4時"]].forEach(([h, l]) => text(s, l, { x: hx(h) - 0.4, y: 4.8, w: 0.8, h: 0.3, fontSize: 10.5, color: SUB, align: "center" }));
[[BLUE, "電気バスが走る便"], [GREY, "燃料バスが走る便"], ["F2A900", "充電"]].forEach(([c, l], i) => {
  s.addShape(pres.shapes.RECTANGLE, { x: 2.2 + i * 2.1, y: 5.25, w: 0.25, h: 0.2, fill: { color: c }, line: { color: c } });
  text(s, l, { x: 2.5 + i * 2.1, y: 5.2, w: 1.8, h: 0.3, fontSize: 11 });
});
card(s, 8.8, 1.5, 3.9, 2.6);
text(s, [{ text: "計算の条件", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  ...["時刻表の便はすべて走らせる", "途中で電池切れにならない", "充電器は10基まで", "受け取る電力の上限を守る（超えた分は費用として数える）"].map((t, i, a) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: i < a.length - 1 } }))],
  { x: 9.0, y: 1.6, w: 3.6, h: 2.45, fontSize: 13, paraSpaceAfter: 4 });
card(s, 8.8, 4.25, 3.9, 1.25, "DCEBF7");
text(s, [{ text: "選ぶ基準", options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: "条件の中で、1週間の費用\n（車両・電気・燃料）が\nいちばん安い組み合わせを選ぶ" }],
  { x: 9.0, y: 4.3, w: 3.6, h: 1.15, fontSize: 12.5, valign: "middle" });
text(s, "実際には、まず1週間分を決めてから、実際の天気に合わせて1時間ごとに充電を見直し、\nかかった費用とCO₂を数えています（式と流れは補足A2）。",
  { x: 0.6, y: 5.75, w: 12.1, h: 0.8, fontSize: 14, valign: "middle" });

// ---- 6. Results and what they suggest (bridge to pillar C; the cost table is in appendix A4)
const shareLo = iceWins.map((r) => r.bev_trip_share_pct), shareHi = bevWins.map((r) => r.bev_trip_share_pct);
if (Math.min(...shareHi) < 90) throw new Error("the '9割以上' wording no longer holds");
const wari = `${Math.floor(Math.min(...shareLo) / 10)}〜${Math.ceil(Math.max(...shareLo) / 10)}割`;
s = page("電力の上限に余裕があれば、電気バスが9割以上の便を担当");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => (get(g, w) ? Math.round(get(g, w).bev_trip_share_pct * 10) / 10 : null)) })),
  chart({ x: 0.6, y: 1.4, w: 6.6, h: 3.95, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, legendFontSize: 13,
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便の割合 [%]", showCatAxisTitle: true, catAxisTitle: "営業所が受け取れる電力の上限", valAxisTitleFontSize: 12, catAxisTitleFontSize: 12 }));
caption(s, "1週間 1,704便のうち、電気バスが担当した便の割合", 0.6, 5.35, 6.6, 0.3);
card(s, 7.5, 1.5, 5.2, 1.75);
icon(s, "ebus", 7.65, 1.85, 1.0);
text(s, [{ text: "400 kW以上", options: { bold: true, color: BLUE_DARK, fontSize: 16, breakLine: true } },
  { text: "電気バスが9割以上の便を担当し、費用もいちばん安くなりました", options: { fontSize: 14 } }], { x: 8.8, y: 1.55, w: 3.8, h: 1.65, valign: "middle" });
card(s, 7.5, 3.4, 5.2, 1.95);
icon(s, "dbus", 7.65, 3.85, 1.0);
text(s, [{ text: "上限が低いとき", options: { bold: true, color: BLUE_DARK, fontSize: 16, breakLine: true } }, { text: `（${iceWins.map(lab).join("・")}）`, options: { color: SUB, fontSize: 12, breakLine: true } },
  { text: `燃料バスを多く使う方が安くなり、電気バスは${wari}の便だけでした。ただし90 kWの冬では、CO₂が約${co2Ratio}倍になります`, options: { fontSize: 13.5 } }], { x: 8.8, y: 3.45, w: 3.8, h: 1.85, valign: "middle" });
box(s, 0.6, 5.75, 12.1, 0.8, "DCEBF7");
text(s, "電力の上限が低いと、電気バスに任せられる便は限られます。そのとき、限られた電気バスをどの便に使うのが利用者や地域にとって望ましいかは、電力と費用の計算だけでは決められないと感じ、3本目の柱としてご相談したいと考えました。",
  { x: 0.8, y: 5.75, w: 11.7, h: 0.8, fontSize: 13.5, valign: "middle" });
caption(s, "数値は条件をそろえる前の暫定値で、研究の結論には使っていません（全ケースを計算し直し中。各ケースの費用は補足A4）", 0.6, 6.62, 12.1, 0.3);

// ---- 7. What I hope to learn from Prof. Nishiyama's work
s = page("先生のご研究から学びたいこと");
text(s, "公開されている論文と講義紹介を拝見して、まとめました。読み違いがありましたら、ご指摘ください。",
  { x: 0.6, y: 1.5, w: 12.1, h: 0.45, fontSize: 14, color: SUB });
const WORKS = [
  ["ebus", "乗り物の開発と普及", "段差のない電動フルフラットバスを試作し、バス事業者への調査と利用者へのアンケートから普及の形を整理された研究 [1]"],
  ["people", "地域との共創", "地域の方々と対話しながら、新しい移動のサービスを一緒につくる実践 [2]"],
  ["shop", "乗り物や営業所を\n地域に活かす", "使われなくなった乗り物や営業所の空きスペースを、地域の居場所や移動販売に活かすお考え [2]"]];
WORKS.forEach(([n, h, b], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 2.1, 3.9, 2.55);
  icon(s, n, x + 0.2, 2.25, 0.75);
  text(s, h, { x: x + 1.1, y: 2.25, w: 2.7, h: 0.75, fontSize: 14.5, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, b, { x: x + 0.2, y: 3.1, w: 3.5, h: 1.5, fontSize: 14 });
});
text(s, "私の研究は電力と費用の計算が中心で、利用者や地域にとっての価値をどう評価するかがまだ弱いと感じています。\nこの点について、ご指導いただきたいと考えています。",
  { x: 0.6, y: 4.95, w: 12.1, h: 1.0, fontSize: 16, bold: true, color: BLUE_DARK, valign: "middle" });
caption(s, "[1] T. Nishiyama, Int. J. Critical Infrastructures, Vol. 11, No. 2, pp. 136–147, 2015（電動フルフラットバスの試作と普及戦略）\n[2] 夢ナビ講義「走るスーパー・動く居場所　乗り物が変える地域の未来」（東京都市大学 都市生活学部）",
  0.6, 6.25, 12.1, 0.6);

// ---- 8. Pillar-C ideas, one picture and one short paragraph each
s = page("3本目の柱（柱C）の案");
const DIRS = [
  ["① 運行のない時間の電気バスと\n営業所を、地域に活かす",
    "運行していない時間の電気バスや、営業所の空きスペース・太陽光の電気を、地域の居場所や移動販売に使う案です。次の運行に必要な電池を残したまま、何台・何時間・どれだけの電力まで使えるかを計算で確かめます。災害時の電源としての活用は、その応用と考えています。"],
  ["② ユニバーサルデザインの\n視点で、バスを割り当てる",
    `電気バスが走れる便は、電力の上限が低いと\n${rngTxt(shareLo)}%に限られます。乗り降りしやすい電気バス（例：フルフラット車）を一部に入れると仮定し、高齢の方や車いすの方が多い便を優先したとき、費用やCO₂がどう変わるかを調べます。燃料バスとの違い（段差・静かさ・揺れなど）の置き方もご相談したい点です。`],
  ["③ 現場や利用者の声から、\n計画の条件を決める",
    "事業者へのヒアリングや利用者調査で、受け入れられる運用（車両を入れ替える回数、運転士の休憩と充電の両立など）を先に調べます。それを条件に入れた計画と入れない計画で、費用や電気バスの担当便を比べます。"]];
DIRS.forEach(([h, q], i) => {
  const x = 0.6 + i * 4.1, w = 3.9;
  card(s, x, 1.5, w, 4.8, "FFFFFF");
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w, h: 0.75, fill: { color: BLUE }, line: { color: BLUE } });
  text(s, h, { x: x + 0.12, y: 1.5, w: w - 0.24, h: 0.75, fontSize: 13.5, bold: true, color: "FFFFFF", valign: "middle" });
  const py = 2.4; // picture area 2.4-3.85
  if (i === 0) {
    const segs = [[0, 0.22, BLUE, "運行"], [0.22, 0.48, "3E9B5F", "地域で活用"], [0.48, 0.74, BLUE, "運行"], [0.74, 1, "F2A900", "夜に充電"]];
    const bx = x + 0.15, bw = w - 0.3;
    segs.forEach(([a, b, c, l]) => { s.addShape(pres.shapes.RECTANGLE, { x: bx + a * bw, y: py + 0.05, w: (b - a) * bw, h: 0.42, fill: { color: c }, line: { color: "FFFFFF", width: 1 } });
      text(s, l, { x: bx + a * bw, y: py + 0.05, w: (b - a) * bw, h: 0.42, fontSize: 10, bold: true, color: "FFFFFF", align: "center", valign: "middle" }); });
    [["home", "居場所"], ["shop", "移動販売"], ["power", "災害時の電源"]].forEach(([n, l], k) => {
      const cx = x + 0.35 + k * 1.2; icon(s, n, cx + 0.2, py + 0.62, 0.55); text(s, l, { x: cx - 0.1, y: py + 1.18, w: 1.15, h: 0.28, fontSize: 10, align: "center", color: SUB }); });
  } else if (i === 1) {
    icon(s, "elder", x + 0.2, py, 0.6); icon(s, "wheelchair", x + 0.8, py, 0.6);
    text(s, "の多い便", { x: x + 1.4, y: py, w: 0.9, h: 0.6, fontSize: 11, valign: "middle" });
    right(s, x + 2.3, py + 0.2); icon(s, "ebus", x + 2.8, py - 0.05, 0.7);
    text(s, "その他の便", { x: x + 0.3, y: py + 0.85, w: 1.9, h: 0.5, fontSize: 11, valign: "middle", align: "center" });
    right(s, x + 2.3, py + 0.99); icon(s, "dbus", x + 2.8, py + 0.75, 0.7);
  } else {
    [["clipboard", "ヒアリング・調査"], ["people", "受け入れられる運用"], ["plan", "計画の条件に"]].forEach(([n, l], k) => {
      const cx = x + 0.15 + k * 1.3; icon(s, n, cx + 0.25, py + 0.05, 0.65); text(s, l, { x: cx - 0.05, y: py + 0.75, w: 1.25, h: 0.5, fontSize: 10, align: "center", color: SUB });
      if (k < 2) right(s, cx + 1.1, py + 0.27); });
  }
  text(s, q, { x: x + 0.15, y: 3.95, w: w - 0.3, h: 2.3, fontSize: 12, lineSpacingMultiple: 1.12 });
});
caption(s, "ダイヤや車両の大きさの見直しは、時刻表を固定するという今の前提を外すため、今後の課題としています。", 0.6, 6.4, 12.1, 0.4);

// ---- 9. Questions (the deck ends here; thanks are said in person while this slide stays on screen)
s = page("伺いたいこと");
const QS = [
  ["people", "3つの案のうち、利用者や地域にとって意義が大きいのはどれでしょうか。見落としている視点があれば、あわせて教えていただきたいです。"],
  ["clipboard", "移動のしやすさや、事業者・地域の受け止めを研究に入れるとき、数値の指標と、アンケートや対話などの調査を、どう組み合わせるのがよいでしょうか。"],
  ["calendar", "修士の残りの期間で、どのくらいの範囲の調査なら現実的でしょうか。先生のこれまでの調査から、参考になる点を伺えればと思います。"]];
QS.forEach(([n, q], i) => {
  const y = 1.55 + i * 1.5;
  card(s, 0.6, y, 12.1, 1.3);
  s.addShape(pres.shapes.OVAL, { x: 0.8, y: y + 0.4, w: 0.5, h: 0.5, fill: { color: BLUE }, line: { color: BLUE } });
  text(s, String(i + 1), { x: 0.8, y: y + 0.4, w: 0.5, h: 0.5, fontSize: 17, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  icon(s, n, 1.5, y + 0.3, 0.7);
  text(s, q, { x: 2.4, y: y + 0.08, w: 10.1, h: 1.14, fontSize: 17, valign: "middle" });
});
caption(s, "時間があれば：交通やまちづくりの分野でも意義を認めてもらえる研究にするには、何が必要でしょうか", 0.6, 6.15, 12.1, 0.6);

// ---- A1. Conditions (appendix)
s = page("補足A1　計算条件");
s.addTable([
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間 1,704便"],
  [B("車両・設備"), "電気バス35台・燃料バス25台、充電器 90 kW × 10基、太陽光 1,000 kW、蓄電池 6,000 kWh（設備は設置を仮定）"],
  [B("対象期間"), "2025年の冬（1/6〜）・春（4/7〜）・夏（7/7〜）の各1週間、実際の日射"],
  [B("受電上限"), "90／200／400／900 kWの4段階（× 3季節 ＝ 12ケース）。超過した電力量には500円/kWhの費用（仮の値）"],
  [B("単価"), "電気 17.43円/kWh＋基本料金（比較として30円/kWh込みでも計算）、軽油 150円/L、車両使用費 2万円/台・日"],
  [B("CO₂"), "計画を立てるときにはCO₂の排出も抑えるよう考慮しているが、総費用（実際にかかるお金）には含めず、CO₂は kg で別に示す"],
  [B("計算の打ち切り"), "最適性ギャップ5%（全ケース共通）、便割当3時間、毎時の立て直し300秒/回"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 14, rowH: 0.65 }));
caption(s, "今回お示しした数値は旧版の計算（30円/kWh込み）の結果で、この表の条件で全ケースを計算し直しています", 0.6, 6.3, 12.1);

// ---- A2. Formula and calculation flow = poster Fig. 1 (appendix; the main deck shows a plain-language picture)
s = page("補足A2　計算の仕組み（式と流れ）");
text(s, [{ text: "最適化するもの　", options: { bold: true, color: BLUE_DARK } },
  { text: "(a) 各便を電気バス・燃料バスのどの車両が担当するか、(b) 各電気バスをいつ・何kWで充電するか。時刻表の便はすべて運行する。" }],
  { x: 0.6, y: 1.5, w: 12.1, h: 0.65, fontSize: 15 });
text(s, [{ text: "目的関数　", options: { bold: true, color: BLUE_DARK } }, { text: "1週間の総費用を最小にする" }], { x: 0.6, y: 2.15, w: 12.1, h: 0.4, fontSize: 15 });
const EQW = 7.6, EQH = EQW * 0.763 / 7.273;
s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: 0.9, y: 2.55, w: EQW, h: EQH,
  altText: "目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化" });
caption(s, "左から車両使用費（u：車両kを日dに使うか）、電気代と超過費用（g：時刻tの買電量、s：超過量）、燃料代（f：便jの軽油）、CO₂の費用（Q：排出量）。c・p・πは単価。CO₂の費用は計算の中だけで用い、示す総費用には含めない。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限（超過分は費用）",
  0.6, 2.55 + EQH + 0.05, 12.1, 0.7);
const STEPS = [
  ["① 便割当", ["1,704便を60台に割り当てる", "整数計画と、割当を部分的に組み直す探索"]],
  ["② 前日の計画", ["割当を固定し、15分ごとの充電を決める", "太陽光は平年値で予測"]],
  ["③ 毎時の立て直し", ["実際の日射で1時間ごとに計画し直す", "最終日の翌朝まで174〜175回"]],
  ["④ 集計", ["実行した結果で費用とCO₂を数える", "2通りの初期割当の安い方を採用"]]];
const FY = 4.3, FH = 1.95, FGAP = 0.3, FBW = (12.1 - FGAP * 3) / 4;
STEPS.forEach(([hd, body], i) => {
  const bx = 0.6 + i * (FBW + FGAP);
  s.addShape(pres.shapes.RECTANGLE, { x: bx, y: FY, w: FBW, h: FH, fill: { color: "F4F7FA" }, line: { color: BLUE, width: 1.25 } });
  s.addShape(pres.shapes.RECTANGLE, { x: bx, y: FY, w: FBW, h: 0.5, fill: { color: i === 3 ? BLUE_DARK : BLUE }, line: { color: BLUE, width: 1.25 } });
  text(s, hd, { x: bx + 0.05, y: FY, w: FBW - 0.1, h: 0.5, fontSize: 15, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  bullets(s, body, { x: bx + 0.12, y: FY + 0.6, w: FBW - 0.22, h: FH - 0.7, fontSize: 13, paraSpaceAfter: 4, lineSpacingMultiple: 1.1 });
  if (i < 3) s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x: bx + FBW + 0.06, y: FY + FH / 2 - 0.12, w: 0.18, h: 0.24, rotate: 90, fill: { color: BLUE }, line: { color: BLUE } });
});
caption(s, "計算の流れ（ソルバーはGurobi）。蓄電池は決めた規則で充放電し、最適化していない。2通りの初期割当の理由と比較は補足A3", 0.6, FY + FH + 0.1, 12.1);

// ---- A3. Why two initial assignments, the two solutions compared, and caveats (appendix)
s = page("補足A3　2通りの初期割当と、結果の扱い");
text(s, "便割当は問題が大きく、制限時間内に最適と確かめられない。探索は最初の割当に近い解にとどまりやすいため、性質の異なる「電気バス優先」と「燃料バス優先」の2通りの初期割当から始め、総費用の安い方を採用した。", { x: 0.6, y: 1.5, w: 12.1, h: 0.65, fontSize: 13 });
const COLS = [["900 kW冬", p9b, "電気バス優先"], ["900 kW冬", p9i, "燃料バス優先"], ["90 kW冬", p90b, "電気バス優先"], ["90 kW冬", p90i, "燃料バス優先"]];
const adopted = [tc(p9b) <= tc(p9i), tc(p9i) < tc(p9b), tc(p90b) <= tc(p90i), tc(p90i) < tc(p90b)];
const c3 = (t, i) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK } });
const row3 = (label, f) => [B(label), ...COLS.map(([, r], i) => c3(f(r), i))];
s.addTable([[H("受電上限・季節"), ...COLS.map(([n]) => H(n))], [B("初期割当"), ...COLS.map(([, , n], i) => c3(n, i))],
  row3("総費用", (r) => `${man(tc(r))}万円`), row3("電気バス担当便", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
  row3("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`), row3("上限の超過", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`)],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.5, 2.4, 2.4, 2.4, 2.4], fontSize: 13, rowH: 0.4 }));
caption(s, "表A3　2通りの初期割当から得た解（1週間）。青字が採用した方", 0.6, 4.65, 12.1, 0.35);
bullets(s, [
  `900 kW冬では、電気バスを多く使う解が${man(tc(p9i) - tc(p9b))}万円安く、CO₂は${Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100)}%少ない。90 kW冬では燃料バスを多く使う解が約${Math.round((tc(p90b) - tc(p90i)) / 1e4)}万円安いが、CO₂は約${co2Ratio}倍`,
  `上限の超過は、曇りの日の翌未明、蓄電池が空の時間に集中した（90 kW冬・電気バスを多く使う解で${fmt(p90b.contract_over_limit_kwh)} kWh/週）`,
  `数値は暫定値（診断用）で、研究の結論には使っていない。便割当は最適と確認できておらず、2段階で解くため全体の最適でもない。毎時の立て直しは最大${maxTimeouts}回（1週間174〜175回中）が時間切れ`,
  "超過の費用（500円/kWh）と電力のCO₂排出係数（0.5 kg/kWh）は仮の値で、今後感度を調べる"],
  { x: 0.6, y: 5.0, w: 12.1, h: 1.95, fontSize: 12, paraSpaceAfter: 3 });

// ---- A4. Total cost per case (appendix; moved from the results slide 2026-11-17)
s = page("補足A4　各ケースの1週間の総費用");
const cell = (g, w) => { const r = get(g, w); const ice = r && r.selected_start === "ice";
  return { text: r ? `${man(tc(r))}${ice ? "＊" : ""}` : "—", options: { align: "center", bold: ice, color: ice ? BLUE_DARK : INK } }; };
s.addTable([[H("受け取れる電力の上限"), ...SEASONS.map(([, n]) => H(n))], ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SEASONS.map(([w]) => cell(g, w))])],
  tableOpts({ x: 2.2, y: 1.7, w: 8.9, colW: [3.2, 1.9, 1.9, 1.9], fontSize: 17, rowH: 0.7 }));
caption(s, "1週間の総費用［万円］（車両・電気代・燃料代・上限を超えた分の費用の合計。CO₂の費用は含めない）。＊は燃料バスを多く使う解の方が安かったケース", 2.2, 5.4, 8.9, 0.6);
caption(s, PROVISIONAL, 2.2, 6.1, 8.9, 0.5);

// ---- A5. Glossary (appendix): power and optimization terms only
s = page("補足A5　用語（電力・最適化）");
s.addTable([
  [B("受電電力・受電上限"), "営業所が電力会社から受け取る電力（kW）と、その目安。本研究では、上限を超えた電力量に費用を課している"],
  [B("kW と kWh"), "kWはある時点の電力の大きさ、kWhは使用した電力量（kW × 時間）"],
  [B("基本料金"), "契約した電力の大きさに応じて毎月かかる電気料金。使った電力量に応じた料金とは別"],
  [B("数理最適化"), "条件と費用を数式で表し、費用が最小となる計画を計算機で求める方法"],
  [B("初期割当"), "最適化を始めるときに与える仮の便割当。ここから少しずつ良い割当を探す"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.8, 9.3], fontSize: 15, rowH: 0.75 }));

(async () => {
  const out = path.join(__dirname, process.env.DECK_OUT || "西山先生へのご相談_最新結果と3本目の柱.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  const JSZip = require(path.join(process.env.DECK_NODE_MODULES, "jszip"));
  const zip = await JSZip.loadAsync(fs.readFileSync(out));
  const themePath = Object.keys(zip.files).find((f) => /^ppt\/theme\/theme\d+\.xml$/.test(f));
  const xml = (await zip.file(themePath).async("string")).replace(/<a:ea typeface="[^"]*"\/>/g, `<a:ea typeface="${THEME.bodyFontFace}"/>`);
  zip.file(themePath, xml);
  fs.writeFileSync(out, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log("wrote", out);
})();
