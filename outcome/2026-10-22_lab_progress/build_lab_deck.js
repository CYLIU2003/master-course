// Lab progress talk (2026-10-22) for a mixed audience: the supervisor plus juniors
// from other topics.  Plain words, one idea per slide, numbers from verified runs.
// Run: NODE_PATH=<pptxgenjs node_modules> DECK_NODE_MODULES=... PPTX_SKILL=... node build_lab_deck.js
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const rc8 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc8.json"), "utf8"));
const rc9 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc9.json"), "utf8")).filter((r) => r.status === "VERIFIED");
const diesel = fs.readFileSync(path.join(__dirname, "all_diesel_estimate.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dKeys = diesel[0].split(",");
const dRows = diesel.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dKeys[i], v])));
const LIMITS = [90, 200, 400, 800];
const WIN = "2025-01-06";
const get = (rows, g, w) => rows.find((r) => r.grid_limit_kw === g && r.week === w);

const THEME = {
  name: "Lab progress EV bus", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: "1B2A2F", lt1: "FFFFFF", dk2: "0F4C5C", lt2: "EEF4F3", accent1: "1F7A8C", accent2: "E07A2E",
            accent3: "5FA84A", accent4: "C9A227", accent5: "6C5B9E", accent6: "B23A48", hlink: "1F7A8C", folHlink: "6C5B9E" },
};
const HEX = { teal: "1F7A8C", orange: "E07A2E", green: "5FA84A", ink: "1B2A2F", muted: "5B6B70", grid: "D9E2E1", soft: "EEF4F3" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "研究室進捗発表 2026-10-22";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "DARK", background: { color: THEME.colors.dk2 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.8, fontSize: 36, bold: true, color: C.background1, valign: "middle" }, text: "" } },
            { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 2.0, fontSize: 20, color: C.background2 }, text: "" } }] });
pres.defineSlideMaster({ title: "LIGHT", background: { color: THEME.colors.lt1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.95, fontSize: 30, bold: true, color: C.text2, valign: "middle" }, text: "" } }],
  slideNumber: { x: 12.4, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: HEX.muted } });

const card = (s, x, y, w, h) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: HEX.soft }, line: { color: HEX.soft }, rectRadius: 0.12 });
const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: HEX.ink, fontSize: 16, ...o });
const chartBase = (title) => ({ showTitle: true, title, titleFontFace: "+mn-lt", titleFontSize: 14, titleColor: HEX.ink,
  catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 13, valAxisLabelFontSize: 11, valGridLine: { color: HEX.grid, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: HEX.ink, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12, dataLabelColor: HEX.ink });

// 1. Title
let s = pres.addSlide({ masterName: "DARK" });
s.addText("どのバスが・いつ充電すれば\n安くて環境にやさしい？", { placeholder: "title" });
s.addText("研究室 進捗発表（2026年10月22日）\nGXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", { placeholder: "body" });
s.addNotes("今日は、研究の中身を、専門外の人にも分かるように話します。キーワードは、電気バス、充電、電気の基本料金です。");

// 2. Background
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("背景：バス会社が電気バスを入れ始めている", { placeholder: "title" });
[["CO₂を減らしたい", "バスの排気ガスを減らすため、各社が電気バスを導入している（GX：脱炭素への転換）"],
 ["全部は電気にできない", "値段が高く、充電にも時間がかかる。しばらくは燃料（軽油）バスと一緒に使う"],
 ["充電の電気が大問題", "夜や昼にまとめて充電すると、営業所が一度にたくさんの電気を使う"]].forEach(([h, b], i) => {
  const x = 0.6 + i * 4.15; card(s, x, 1.6, 3.85, 3.6);
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.85, w: 0.75, h: 0.75, fill: { color: C.accent1 }, line: { color: C.accent1 } });
  s.addText(String(i + 1), { x: x + 0.3, y: 1.85, w: 0.75, h: 0.75, align: "center", valign: "middle", fontSize: 24, bold: true, color: C.background1, isTextBox: true, margin: 0 });
  text(s, h, { x: x + 0.3, y: 2.85, w: 3.3, h: 0.6, fontSize: 20, bold: true, color: C.text2 });
  text(s, b, { x: x + 0.3, y: 3.55, w: 3.3, h: 1.5, fontSize: 17 });
});
text(s, "対象：東急バス 渋21〜23系統（弦巻営業所）、1週間で1,704本の運行、電気バス35台＋燃料バス25台", { x: 0.6, y: 5.5, w: 12.1, h: 0.5, fontSize: 16, color: HEX.muted });
s.addNotes("電気バスはCO₂を減らせますが、全部を電気にはまだできません。そこで燃料バスと一緒に使います。そのとき問題になるのが、充電に使う電気です。");

// 3. Key idea: the breaker and the basic charge
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("電気代は「使った量」と「一番多く使った瞬間」で決まる", { placeholder: "title" });
card(s, 0.6, 1.6, 5.9, 3.8); card(s, 6.8, 1.6, 5.9, 3.8);
text(s, "① 使った量で払う（電力量料金）", { x: 0.9, y: 1.85, w: 5.4, h: 0.5, fontSize: 20, bold: true, color: C.accent1 });
text(s, "家の電気代と同じ。たくさん使えば高くなる。\n\n例：1 kWhあたり30円", { x: 0.9, y: 2.55, w: 5.4, h: 2.6, fontSize: 19 });
text(s, "② 一番多い瞬間で決まる（基本料金）", { x: 7.1, y: 1.85, w: 5.4, h: 0.5, fontSize: 20, bold: true, color: C.accent2 });
text(s, "1年のうち、一番たくさん電気を使った瞬間の大きさ（kW）で、1年分の基本料金が決まる。\n\n家でいえば「ブレーカーの大きさ」。一度だけ大きく使っても、1年間高いまま。",
  { x: 7.1, y: 2.55, w: 5.4, h: 2.6, fontSize: 19 });
text(s, "→ 電気バスの充電を一度に重ねると、②が大きくなってしまう", { x: 0.6, y: 5.75, w: 12.1, h: 0.6, fontSize: 20, bold: true, color: C.text2 });
s.addNotes("ここが今日一番大事なポイントです。会社の電気代は、使った量だけでなく、一番たくさん使った瞬間の大きさでも決まります。これを基本料金と呼びます。一度でもたくさん使うと、1年間その分の料金がかかります。");

// 4. What is decided
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("研究でやっていること：巨大なパズルをコンピュータで解く", { placeholder: "title" });
[["どのバスが", "どの運行を走るか", "1,704本の運行を、60台のバスに割り振る"],
 ["いつ", "どれだけ充電するか", "15分ごとに、充電・太陽光・蓄電池・買う電気を決める"],
 ["何を一番小さく", "するか", "電気代・燃料代・基本料金・CO₂などの合計費用"]].forEach(([a, b, c], i) => {
  const x = 0.6 + i * 4.15; card(s, x, 1.6, 3.85, 3.2);
  text(s, a, { x: x + 0.3, y: 1.85, w: 3.3, h: 0.5, fontSize: 18, color: HEX.muted });
  text(s, b, { x: x + 0.3, y: 2.35, w: 3.3, h: 0.6, fontSize: 22, bold: true, color: C.text2 });
  text(s, c, { x: x + 0.3, y: 3.15, w: 3.3, h: 1.5, fontSize: 17 });
});
text(s, "組み合わせが多すぎて人の手では無理。数理最適化（数式で書いて、計算機で一番よい答えを探す方法）で解く。普通の解き方では答えが良くならなかったので、「一部だけを少しずつ解き直す」工夫（LNS）を入れて改善した。",
  { x: 0.6, y: 5.1, w: 12.1, h: 1.3, fontSize: 17 });
s.addNotes("決めることは、どのバスがどの運行を走るか、いつ充電するかの2つです。目的は、費用の合計を一番小さくすること。組み合わせが膨大なので、計算機で解きます。");

// 5. Result 1: without basic charge, peaks stay high
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("結果①：基本料金を考えないと、一度にたくさん電気を使う", { placeholder: "title" });
const winterLabels = LIMITS.map((g) => `上限 ${g} kW`);
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考えない計画", labels: winterLabels, values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金も考えた計画", labels: winterLabels, values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  { ...chartBase("冬の1週間で、一番多く電気を使った瞬間（kW）"), x: 0.6, y: 1.45, w: 8.4, h: 5.2, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", showLegend: true, legendPos: "t", valAxisMinVal: 0 });
card(s, 9.3, 1.6, 3.5, 4.8);
const w8 = LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw), w9 = LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw);
text(s, [{ text: "約半分に", options: { fontSize: 30, bold: true, color: C.accent1, breakLine: true } },
  { text: `考えない：${Math.round(Math.min(...w8))}〜${Math.round(Math.max(...w8))} kW`, options: { fontSize: 15, breakLine: true } },
  { text: `考える：${Math.round(Math.min(...w9))}〜${Math.round(Math.max(...w9))} kW`, options: { fontSize: 15, breakLine: true } },
  { text: " ", options: { fontSize: 10, breakLine: true } },
  { text: "使う電気の量や、電気バスが担当する運行の割合はほとんど同じ。充電の時間や蓄電池の使い方をずらして、重なりを減らしたと考えられる。", options: { fontSize: 14, color: HEX.muted } }],
  { x: 9.5, y: 1.8, w: 3.1, h: 4.4 });
s.addNotes("受電上限を変えて冬の1週間を計算しました。オレンジは基本料金を考えない計画、青は考えた計画です。考えないと600〜750 kWまで上がりますが、考えると約370 kWで済みます。");

// 6. Result 2: what it means in money
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("結果②：基本料金は1年で数百万円変わる", { placeholder: "title" });
const unit = (kw) => (kw >= 500 ? 1989 : 1890) * 0.85 * 12; // JPY per kW-year (TEPCO business <500 kW, high voltage >=500 kW)
const peakYear = (rows, g) => Math.max(...rows.filter((r) => r.grid_limit_kw === g && ["2025-01-06", "2025-04-07", "2025-07-07"].includes(r.week)).map((r) => r.peak_grid_kw));
const p8 = peakYear(rc8, 90), p9 = peakYear(rc9, 90);
const basic8 = Math.round(p8 * unit(p8) / 1e4), basic9 = Math.round(p9 * unit(p9) / 1e4);
card(s, 0.6, 1.6, 5.9, 3.6); card(s, 6.8, 1.6, 5.9, 3.6);
text(s, [{ text: "基本料金を考えない計画", options: { fontSize: 18, color: HEX.muted, breakLine: true } },
  { text: `年 ${basic8.toLocaleString()} 万円`, options: { fontSize: 40, bold: true, color: C.accent2 } }], { x: 0.9, y: 2.0, w: 5.4, h: 2.8, align: "center", valign: "middle" });
text(s, [{ text: "基本料金も考えた計画", options: { fontSize: 18, color: HEX.muted, breakLine: true } },
  { text: `年 ${basic9.toLocaleString()} 万円`, options: { fontSize: 40, bold: true, color: C.accent1 } }], { x: 7.1, y: 2.0, w: 5.4, h: 2.8, align: "center", valign: "middle" });
text(s, `受電上限90 kWの例。1年で一番大きかった瞬間（kW）×基本料金単価（500 kW未満1,890円・以上1,989円/kW・月、力率100%で0.85倍）×12か月で計算（冬・春・夏の最大）。差は年 約${(basic8 - basic9).toLocaleString()}万円。`,
  { x: 0.6, y: 5.5, w: 12.1, h: 0.9, fontSize: 15, color: HEX.muted });
s.addNotes("一番大きく使った瞬間が下がると、1年分の基本料金が下がります。90 kWの例では、年に約540万円の差になります。単価は東京電力の業務用の値で、正式な料金表でもう一度確認する予定です。");

// 7. Result 3: CO2
s = pres.addSlide({ masterName: "LIGHT" });
s.addText("結果③：電気バスと一緒に使うと、CO₂は約8割減る", { placeholder: "title" });
const W = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全部を燃料バスで走る（計算上の目安）", labels: W.map((x) => x[1]), values: W.map(([w]) => Math.round(Number(dRows.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと一緒に使う（最適化）", labels: W.map((x) => x[1]), values: W.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  { ...chartBase("1週間のCO₂（トン）"), x: 0.6, y: 1.45, w: 8.4, h: 5.2, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", showLegend: true, legendPos: "t" });
card(s, 9.3, 1.6, 3.5, 4.8);
text(s, [{ text: "CO₂ 約75〜85%減", options: { fontSize: 24, bold: true, color: C.accent1, breakLine: true } },
  { text: " ", options: { fontSize: 10, breakLine: true } },
  { text: "電気バスは走行中にCO₂を出さず、太陽光の電気も使える。\n\n「全部燃料バス」は走る距離から軽油の量を計算した目安で、最適化した結果ではない。", options: { fontSize: 14, color: HEX.ink } }],
  { x: 9.5, y: 1.8, w: 3.1, h: 4.4 });
s.addNotes("CO₂の比較です。電気バスと一緒に使うと、全部を燃料バスで走る場合より、CO₂が約8割減ります。全部燃料バスの方は、距離から計算した目安です。");

// 8. Lessons and next
s = pres.addSlide({ masterName: "DARK" });
s.addText("わかったことと、これから", { placeholder: "title" });
s.addText([
  { text: "電気バスの充電は、「使う量」より「一度に使う大きさ」に気をつけると、基本料金を大きく減らせる", options: { bullet: true, breakLine: true } },
  { text: "電気バスと燃料バスを一緒に使うと、CO₂を約8割減らせる", options: { bullet: true, breakLine: true } },
  { text: "これから：秋の週を加えて1年で評価する／燃料バスに切り替えた方が得になる条件を調べる", options: { bullet: true } }],
  { placeholder: "body", fontSize: 20, paraSpaceAfter: 10 });
s.addNotes("まとめです。充電の重なりを減らすことで、基本料金を大きく減らせることが分かりました。これからは、秋を加えた1年間の評価と、燃料バスに切り替えた方が得になる条件を調べます。");

(async () => {
  const out = path.join(__dirname, "lab_progress_20261022.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
