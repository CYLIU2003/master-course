// Lab progress talk (2026-10-22): supervisor plus juniors from other topics.
// Plain academic slides: white background, black text, Tokyo City University blue (#0485D7) only for
// the title rule and the proposed-case series; the comparison case is grey. Plain words, one point per slide.
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
const WIN = "2025-01-06";
const get = (rows, g, w) => rows.find((r) => r.grid_limit_kw === g && r.week === w);
const peakYear = (rows, g) => Math.max(...rows.filter((r) => r.grid_limit_kw === g && r.week !== "2025-10-06").map((r) => r.peak_grid_kw));
const basicYear = (kw) => kw * (kw >= 500 ? 1989 : 1890) * 0.85 * 12;

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "研究室進捗発表 2026-10-22";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 28, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } }],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 11, color: SUB } });

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 10, ...o });
const chart = (o) => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 14, valAxisLabelFontSize: 12, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 14, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 13, dataLabelColor: INK,
  showLegend: true, legendPos: "t", chartColors: [GREY, BLUE], valAxisTitleColor: SUB, catAxisTitleColor: SUB, valAxisTitleFontSize: 13, catAxisTitleFontSize: 13, ...o });
const caption = (s, t, x, y, w) => text(s, t, { x, y, w, h: 0.4, fontSize: 13, color: SUB });

// 1. Title (white, blue rule)
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 2.0, w: 11.5, h: 1.9, fontSize: 36, bold: true, valign: "bottom" });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.1, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "研究室進捗発表　2026年10月22日\n劉 承洋", { x: 0.9, y: 4.35, w: 11.5, h: 1.2, fontSize: 20, color: SUB });
s.addNotes("今日は、研究の中身を、ほかのテーマの人にも分かるように話します。キーワードは電気バス、充電、電気の基本料金です。");

// 2. Background
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("背景", { placeholder: "title" });
bullets(s, [
  "脱炭素（GX）のため、路線バスに電気バスの導入が進んでいる",
  "ただし車両が高く充電にも時間がかかるので、当面は燃料（軽油）バスと一緒に使う",
  "電気バスは営業所で充電する。夜にまとめて充電すると、営業所が一度に多くの電気を使う",
  "対象：東急バス 渋21〜23系統（弦巻営業所）。1週間に1,704便。保有は電気バス35台・燃料バス25台、充電器は90 kW×10基",
  "営業所には太陽光（1,000 kW）と蓄電池（6,000 kWh）も置いた設定"], { x: 0.6, y: 1.7, w: 12.1, h: 4.8, fontSize: 20 });
s.addNotes("電気バスはCO₂を減らせますが、全部を電気にはまだできません。燃料バスと一緒に使うときに問題になるのが、充電の電気です。");

// 3. Electricity bill
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("電気料金の仕組み", { placeholder: "title" });
s.addTable([
  [{ text: "", options: { fill: { color: "F2F2F2" } } }, { text: "電力量料金", options: { bold: true, fill: { color: "F2F2F2" } } }, { text: "基本料金", options: { bold: true, fill: { color: "F2F2F2" } } }],
  [{ text: "何で決まるか", options: { bold: true } }, "使った電気の量（kWh）", "1年で最も多く使った30分間の電力（kW）"],
  [{ text: "家庭でいうと", options: { bold: true } }, "毎月の使用量に応じた料金", "ブレーカー（契約アンペア）の大きさ"],
  [{ text: "この研究の値", options: { bold: true } }, "30円/kWh", "1,890円/kW・月（500 kW以上は1,989円）"]],
  { x: 0.6, y: 1.7, w: 12.1, colW: [2.4, 4.2, 5.5], fontSize: 18, color: INK, rowH: 0.75, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID } });
text(s, "基本料金は、一度でも大きく使うとその後1年間高くなる。電気バスの充電が一度に重なると、基本料金が大きくなる。", { x: 0.6, y: 5.1, w: 12.1, h: 1.0, fontSize: 20 });
s.addNotes("会社の電気料金は、使った量だけでなく、一番たくさん使った30分間の電力の大きさでも決まります。計算は15分ごとなので、15分間の最大で評価しています（30分平均より厳しめ）。これが基本料金です。一度でもたくさん使うと、1年間その分の料金がかかります。");

// 4. What is optimized
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("この研究で決めていること", { placeholder: "title" });
bullets(s, [
  "便の割当：1,704便を、どのバス（電気・燃料）が走るか",
  "充電計画：15分ごとに、充電・太陽光・蓄電池・買う電気をどうするか",
  "目的：車両の使用費・電気代・燃料代などを合わせた費用を最も小さくする",
  "受電上限：営業所が買う電力の目安。超えた分には1 kWhあたり500円の追加費用（仮の値）をかける。超えること自体は認めている",
  "方法：数式で問題を書いて計算機で解く（数理最適化）。そのままでは解が改善しなかったので、一部の便だけを解き直す方法（LNS）を加えた",
  "比較：基本料金を考えずに計画した場合と、考えて計画した場合"], { x: 0.6, y: 1.7, w: 12.1, h: 5.2, fontSize: 19 });
s.addNotes("決めることは、どのバスがどの便を走るかと、いつ充電するかの2つです。組み合わせが非常に多いので、計算機で解いています。費用の中心は車両の使用費（1台1日2万円）で、CO₂も1 kgあたり1円として含めていますが、影響は小さく、主に結果として評価しています。受電上限は絶対に超えられない線ではなく、超えた分に追加費用がかかる目安として扱っています。基本料金を考える場合と考えない場合を比べました。");

// 5. Result: peak
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果1：基本料金を考えると、受電のピークが下がる", { placeholder: "title" });
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考えない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金を考える", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "最大受電電力 [kW]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "冬の代表週（2025年1月6日〜）の最大受電電力", 0.6, 6.5, 7.6);
bullets(s, [
  `考えない場合：${Math.round(Math.min(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))}〜${Math.round(Math.max(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))} kW`,
  `考える場合：${Math.round(Math.min(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))}〜${Math.round(Math.max(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))} kW`,
  "受電上限は目安なので、ピークは上限を超えることがある（超えた分は追加費用）",
  "電気バスが担当する便の割合は92〜96%で、ほとんど変わらない"], { x: 8.6, y: 1.9, w: 4.2, h: 4.4, fontSize: 17 });
s.addNotes("冬の1週間で一番多く電気を使った15分間を比べました。灰色が基本料金を考えない場合、青が考えた場合です。考えると、受電上限によらず約370 kW前後に下がりました。90 kWや200 kWの上限では、ピークが上限を超えています。上限は超えた分に追加費用がかかる目安なので、計算上は超えることがあります。全便を運行し、実際に使ったのは電気バス26〜34台・燃料バス5〜7台です。");

// 6. Why
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("ピークが下がった理由：夜の充電を分散させた", { placeholder: "title" });
s.addChart(pres.charts.LINE, [
  { name: "基本料金を考えない", labels: night.labels, values: night.rc8_grid_kw },
  { name: "基本料金を考える", labels: night.labels, values: night.rc9_grid_kw }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, lineSize: 2.5, lineDataSymbol: "none", valAxisMinVal: 0, catAxisLabelFrequency: 4, catAxisLabelFontSize: 12,
    showValAxisTitle: true, valAxisTitle: "買電電力 [kW]" }));
caption(s, "受電上限90 kW・冬の一晩（22時〜8時）の買電電力（15分ごと）", 0.6, 6.5, 7.6);
bullets(s, [
  `この例では、1週間に買った電気はほぼ同じ（${night.week_grid_kwh[0].toLocaleString()} → ${night.week_grid_kwh[1].toLocaleString()} kWh）`,
  `一番高いときは ${Math.round(Math.max(...night.rc8_grid_kw))} kW → ${Math.round(Math.max(...night.rc9_grid_kw))} kW`,
  "バスが車庫にいる夜の時間を広く使い、充電を少しずつ分けている",
  "買った電気の96%は夜（22〜6時）。昼の充電は主に太陽光と蓄電池"], { x: 8.6, y: 1.9, w: 4.2, h: 4.6, fontSize: 17 });
s.addNotes("なぜ下がったのかを一晩の電気の買い方で見ます。灰色は一度にたくさん買っていますが、青は同じくらいの量を夜の長い時間に分けて買っています。この例では買う量がほぼ同じなので、電気代はあまり変わらず、基本料金だけが下がります。");

// 7. Basic charge per year
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果2：1年の基本料金", { placeholder: "title" });
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考えない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e4)) },
  { name: "基本料金を考える", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e4)) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "基本料金 [万円/年]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "契約電力＝1年の最大受電電力（冬・春・夏）として計算", 0.6, 6.5, 7.6);
const b8 = Math.round(basicYear(peakYear(rc8, 90)) / 1e4), b9 = Math.round(basicYear(peakYear(rc9, 90)) / 1e4);
bullets(s, [`受電上限90 kWの例：年 ${b8.toLocaleString()}万円 → ${b9.toLocaleString()}万円`, "どの受電上限でも、基本料金は約2.5〜5割下がる",
  "一方、電気代（電力量料金）の増減は1週間で最大約2万円で、基本料金の差に比べて小さい",
  "計算：最大受電電力 × 単価 × 0.85（力率100%）× 12か月"], { x: 8.6, y: 1.9, w: 4.2, h: 4.6, fontSize: 17 });
s.addNotes("ピークが下がると、1年分の基本料金が下がります。90 kWの例では年に約540万円の差です。電気を買う量は条件によって−11%〜+19%変わりましたが、電気代の差は1週間で最大約2万円です。単価は東京電力の業務用の値で、正式な料金表で確認する予定です。");

// 8. CO2
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果3：CO₂排出量", { placeholder: "title" });
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "全車燃料バスは走行距離から軽油の量を計算した概算（最適化の結果ではない）。電力は0.5 kg/kWh（仮の値）", 0.6, 6.5, 7.6);
bullets(s, ["電気バスと併用すると、CO₂は全車燃料バスより約75〜85%少ない", "電気バスは走行中にCO₂を出さず、太陽光の電気も使える"], { x: 8.6, y: 1.9, w: 4.2, h: 4.2, fontSize: 18 });
s.addNotes("CO₂の比較です。電気バスと一緒に使うと、全部を燃料バスで走る場合より約8割少なくなります。全部燃料バスの方は距離からの概算です。");

// 9. Summary
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("まとめと今後", { placeholder: "title" });
bullets(s, [
  "基本料金を考えて計画すると、買う電気の量を大きく変えずに、受電のピークと1年の基本料金を下げられる",
  "電気バスと燃料バスを併用すると、全車燃料バスに比べてCO₂を約8割減らせる",
  "注意：結果は制限時間内に得られた計画で、最適であることの確認までは至っていない（さらに良い計画がありうる）",
  "今後：燃料バスに切り替えた方が得になる条件を調べる／計算結果の質（最適性）をさらに確かめる",
  "中間発表（11月28日）はA0ポスターで発表予定"], { x: 0.6, y: 1.7, w: 12.1, h: 5.2, fontSize: 20 });
s.addNotes("まとめです。充電の重なりを減らすことで、基本料金を大きく減らせることが分かりました。ただし、計算は制限時間で打ち切っています。便の割当は全件、基本料金を考えた充電計画も16件すべてが、時間内に得られた計画で、最適との差の上限（ギャップ）は13〜67%です。示した削減は実際に得られた計画での値で、さらに良い計画がありうるという意味です。今後は、燃料バスに切り替えた方が得になる条件を調べます。");

(async () => {
  const out = path.join(__dirname, "lab_progress_20261022.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
