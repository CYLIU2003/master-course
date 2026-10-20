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
// Annual basic charge at the current TEPCO EP tariff (Kanto, high voltage, Basic plan, 2026-04-01, tax incl.).
const BASIC_YEN_PER_KW = 2530;
const basicYear = (kw) => kw * BASIC_YEN_PER_KW * 0.85 * 12;

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

// 2. Background and objective
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("研究の背景と目的", { placeholder: "title" });
text(s, "背景", { x: 0.6, y: 1.55, w: 12.1, h: 0.45, fontSize: 19, bold: true, color: BLUE_DARK });
bullets(s, [
  "脱炭素（GX）に向けて、路線バスへの電気バスの導入が進んでいる",
  "車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続くと考えられる",
  "電気バスは営業所で夜間にまとめて充電するため、受電電力のピークが大きくなりやすい。ピークは電気の基本料金に直結する"],
  { x: 0.6, y: 2.05, w: 12.1, h: 2.3, fontSize: 18, paraSpaceAfter: 6 });
text(s, "目的", { x: 0.6, y: 4.4, w: 12.1, h: 0.45, fontSize: 19, bold: true, color: BLUE_DARK });
bullets(s, [
  "燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を合わせて最適化する",
  "受電上限と基本料金の考慮の有無が、受電ピーク・費用・CO₂に与える影響を明らかにする"],
  { x: 0.6, y: 4.9, w: 12.1, h: 1.3, fontSize: 18, paraSpaceAfter: 6 });
text(s, "今回の報告：基本料金を考慮しない場合（12ケース）と考慮する場合（16ケース）の計算が完了したため、その比較結果を報告する。",
  { x: 0.6, y: 6.35, w: 12.1, h: 0.6, fontSize: 17, color: SUB });
s.addNotes("研究の背景と目的です。電気バスの導入は進んでいますが、当面は燃料バスとの併用が続きます。そのとき問題になるのが充電の電気で、夜にまとめて充電すると受電のピークが大きくなり、電気の基本料金が上がります。本研究では、便の割当と充電計画を合わせて最適化し、受電上限と基本料金の影響を調べています。今回は、基本料金を考えない場合と考える場合の計算がそろったので、その比較を報告します。");

// 3. Terms (for listeners from other fields)
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("本発表で用いる用語", { placeholder: "title" });
s.addTable([
  ["便", "バスが始発から終点まで1回運行すること。対象路線では1週間に1,704便"],
  ["燃料バス", "軽油で走行する従来のバス（ディーゼルバス）"],
  ["営業所", "バスの車庫。運行を終えたバスが戻り、電気バスはここで充電する"],
  ["受電（買電）", "営業所が電力会社から電気を購入すること"],
  ["kW（キロワット）", "ある時点で使用している電力の大きさ"],
  ["kWh（キロワット時）", "使用した電力量。kW × 時間"],
  ["太陽光・蓄電池", "営業所に設置した太陽光発電と、電力をためておく大型の蓄電池（本研究では設置を仮定）"]].map(([k, v]) => [{ text: k, options: { bold: true } }, v]),
  { x: 0.6, y: 1.6, w: 12.1, colW: [2.9, 9.2], fontSize: 18, color: INK, rowH: 0.66, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID } });
s.addNotes("研究テーマが違う方も多いので、先に用語をそろえておきます。特にkWとkWhの違いが今日の話の中心になるので、次のページで説明します。");

// 4. kW vs kWh
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("kWとkWhの違い：本研究で注目する「ピーク」", { placeholder: "title" });
const AX = (x0, label) => {
  s.addShape(pres.shapes.LINE, { x: x0, y: 5.3, w: 4.6, h: 0, line: { color: SUB, width: 1.25 } });
  s.addShape(pres.shapes.LINE, { x: x0, y: 2.0, w: 0, h: 3.3, line: { color: SUB, width: 1.25 } });
  text(s, "時間 →", { x: x0 + 3.6, y: 5.35, w: 1.0, h: 0.35, fontSize: 13, color: SUB, align: "right" });
  text(s, "kW", { x: x0 - 0.55, y: 1.95, w: 0.5, h: 0.35, fontSize: 13, color: SUB, align: "right" });
  text(s, label, { x: x0, y: 1.55, w: 4.6, h: 0.4, fontSize: 18, bold: true });
};
AX(0.9, "短時間に集中して充電");
s.addShape(pres.shapes.RECTANGLE, { x: 2.0, y: 2.3, w: 1.2, h: 3.0, fill: { color: GREY }, line: { color: GREY } });
AX(6.3, "時間を分散して充電");
s.addShape(pres.shapes.RECTANGLE, { x: 7.4, y: 3.8, w: 2.4, h: 1.5, fill: { color: BLUE }, line: { color: BLUE } });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 2.3, w: 10.0, h: 0, line: { color: GREY, width: 1, dashType: "dash" } });
s.addShape(pres.shapes.LINE, { x: 6.3, y: 3.8, w: 4.6, h: 0, line: { color: BLUE, width: 1, dashType: "dash" } });
text(s, "ピーク大", { x: 3.3, y: 2.35, w: 1.4, h: 0.35, fontSize: 14, color: SUB });
text(s, "ピーク小", { x: 10.5, y: 3.45, w: 1.4, h: 0.35, fontSize: 14, color: BLUE_DARK });
bullets(s, [
  "高さ＝電力（kW）→ そのピークが基本料金を決める",
  "面積＝電力量（kWh）→ 電力量料金を決める",
  "同じ電力量でも、充電を時間的に分散させればピークを抑えられる"], { x: 0.6, y: 5.9, w: 12.1, h: 1.3, fontSize: 18, paraSpaceAfter: 4 });
caption(s, "模式図（左右の面積は同じ）", 6.3, 5.35, 3.2);
s.addNotes("kWとkWhの違いです。水道に例えると、kWは蛇口から出る水の勢い、kWhはたまった水の量にあたります。左右の図は面積が同じなので、電力量料金は同じです。しかし左の方がピークが高いので、基本料金は左の方が高くなります。本研究では、このピークに注目しています。");

// 5. Electricity bill
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("電気料金の仕組みと本研究での扱い", { placeholder: "title" });
s.addTable([
  [{ text: "", options: { fill: { color: "F2F2F2" } } }, { text: "電力量料金", options: { bold: true, fill: { color: "F2F2F2" } } }, { text: "基本料金", options: { bold: true, fill: { color: "F2F2F2" } } }],
  [{ text: "決まり方", options: { bold: true } }, "使用した電力量（kWh）", "過去1年間で最大の30分平均電力（kW）"],
  [{ text: "家庭での例え", options: { bold: true } }, "毎月の使用量に応じた料金", "契約アンペア（ブレーカー）の大きさ"],
  [{ text: "本研究での値", options: { bold: true } }, "30円/kWh（設定値）", "2,530円/kW・月（東京電力EP）"]],
  { x: 0.6, y: 1.7, w: 12.1, colW: [2.4, 4.2, 5.5], fontSize: 18, color: INK, rowH: 0.75, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID } });
bullets(s, [
  "基本料金は過去1年間の最大値で決まるため、一度のピークがその後1年間の料金に影響する",
  "電気バスの充電が同じ時間帯に集中すると、このピークが大きくなる"], { x: 0.6, y: 5.0, w: 12.1, h: 1.6, fontSize: 18, paraSpaceAfter: 6 });
s.addNotes("事業者向けの電気料金は、使った量に応じた電力量料金と、ピークに応じた基本料金の2つからなります。基本料金は、過去1年間で最も大きかった30分平均の電力で決まります（500 kW未満の場合。東京電力EPの公式ページで確認）。本研究の計算は15分ごとなので、15分間の最大で評価しており、やや厳しめの評価です。単価は東京電力EPの2026年4月からの料金表（関東・高圧・ベーシックプラン、税込）の値で、最適化の計算自体は旧単価1,890円で行っています。");

// 6. Method
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("研究手法：数理最適化による運行・充電計画", { placeholder: "title" });
const COLS = [
  ["決定変数（決めること）", ["各便の担当車両（電気・燃料）", "各車両の充電の時刻と量", "太陽光・蓄電池・買電の配分"]],
  ["制約条件（守るルール）", ["次の便の出発に間に合う", "電池残量が下限を下回らない", "充電器は同時に10基まで", "受電上限の超過分には追加費用"]],
  ["目的関数（最小化する費用）", ["1週間の総費用", "車両使用費・電気代・燃料代・超過分の費用", "基本料金を含む場合と含まない場合を比較"]]];
COLS.forEach(([head, items], i) => {
  const x = 0.6 + i * 4.1;
  text(s, head, { x, y: 1.6, w: 3.8, h: 0.5, fontSize: 18, bold: true, color: BLUE_DARK });
  s.addShape(pres.shapes.LINE, { x, y: 2.15, w: 3.8, h: 0, line: { color: GRID, width: 1 } });
  bullets(s, items, { x, y: 2.3, w: 3.8, h: 3.0, fontSize: 16, paraSpaceAfter: 8 });
});
bullets(s, [
  "便割当（Stage 1）と充電計画（Stage 2、15分刻み）の2段階に分け、混合整数計画問題として解いた（Gurobi）",
  "便割当は一括では解が改善しなかったため、一部の便のみを解き直す大近傍探索（LNS）を併用した",
  "1時間ごとに計画を更新しながら1週間を運用し、その実行結果から費用を集計した"],
  { x: 0.6, y: 5.35, w: 12.1, h: 1.6, fontSize: 16, paraSpaceAfter: 4 });
s.addNotes("手法です。数理最適化は、決めること・守るルール・最小化したいものの3つを数式で書き、計算機で最もよい計画を探す方法です。時間割やシフト表を作るのに近いと考えてください。費用の中心は車両の使用費（1台1日2万円）で、CO₂も1 kgあたり1円として含めていますが、影響は小さく、主に結果として評価しています。受電上限は絶対に超えられない線ではなく、超えた分に追加費用がかかる目安として扱っています。問題が大きいため、便割当と充電計画の2段階に分けて解いています。");

// 6b. Conditions
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("計算条件", { placeholder: "title" });
s.addTable([
  ["対象", "東急バス 渋21〜23系統（弦巻営業所）"],
  ["運行", "1週間 1,704便"],
  ["車両", "電気バス35台・燃料バス25台（保有台数、固定）"],
  ["設備", "太陽光 1,000 kW、蓄電池 6,000 kWh、充電器 90 kW × 10基"],
  ["受電上限", "90 / 200 / 400 / 800 kW（超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（基本料金を考慮する場合は秋も計算）"],
  ["単価", "電力量 30円/kWh（設定値）、軽油 150円/L"],
  ["計算ケース", "基本料金を考慮しない 12ケース、考慮する 16ケース（計28ケース）"]].map(([k, v]) => [{ text: k, options: { bold: true } }, v]),
  { x: 0.6, y: 1.6, w: 12.1, colW: [2.4, 9.7], fontSize: 18, color: INK, rowH: 0.6, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID } });
s.addNotes("計算条件です。対象は東急バスの渋21から23系統で、弦巻営業所の1週間1,704便です。太陽光と蓄電池は、営業所に設置したと仮定した設定です。受電上限を4通り、季節を3〜4週、基本料金の有無の2通りで、計28ケースを計算しました。");


// 5. Result: peak
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果1：基本料金の考慮による受電ピークの低減", { placeholder: "title" });
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考慮しない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金を考慮する", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "最大受電電力 [kW]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "冬の代表週（2025年1月6日〜）の最大受電電力", 0.6, 6.5, 7.6);
bullets(s, [
  `考慮しない場合：${Math.round(Math.min(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))}〜${Math.round(Math.max(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))} kW`,
  `考慮する場合：${Math.round(Math.min(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))}〜${Math.round(Math.max(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))} kW`,
  "受電上限は超過分に追加費用を課す目安のため、ピークが上限を上回る場合がある",
  "電気バスが担当する便の割合は92〜96%で、ほぼ変化しなかった"], { x: 8.6, y: 1.9, w: 4.2, h: 4.4, fontSize: 17 });
s.addNotes("冬の1週間で一番多く電気を使った15分間を比べました。灰色が基本料金を考えない場合、青が考えた場合です。考えると、受電上限によらず約370 kW前後に下がりました。90 kWや200 kWの上限では、ピークが上限を超えています。上限は超えた分に追加費用がかかる目安なので、計算上は超えることがあります。全便を運行し、実際に使ったのは電気バス26〜34台・燃料バス5〜7台です。");

// 6. Why
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("ピーク低減の要因：夜間充電の分散", { placeholder: "title" });
s.addChart(pres.charts.LINE, [
  { name: "基本料金を考慮しない", labels: night.labels, values: night.rc8_grid_kw },
  { name: "基本料金を考慮する", labels: night.labels, values: night.rc9_grid_kw }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, lineSize: 2.5, lineDataSymbol: "none", valAxisMinVal: 0, catAxisLabelFrequency: 4, catAxisLabelFontSize: 12,
    showValAxisTitle: true, valAxisTitle: "買電電力 [kW]" }));
caption(s, "受電上限90 kW・冬の一晩（22時〜8時）の買電電力（15分ごと）", 0.6, 6.5, 7.6);
bullets(s, [
  `この例では、1週間の買電量はほぼ同じ（${night.week_grid_kwh[0].toLocaleString()} → ${night.week_grid_kwh[1].toLocaleString()} kWh）`,
  `最大値は ${Math.round(Math.max(...night.rc8_grid_kw))} kW → ${Math.round(Math.max(...night.rc9_grid_kw))} kW`,
  "バスが車庫に停車している夜間全体に、充電を分散させていた",
  "買電の96%は夜間（22〜6時）。日中の充電は主に太陽光と蓄電池でまかなわれていた"], { x: 8.6, y: 1.9, w: 4.2, h: 4.6, fontSize: 17 });
s.addNotes("なぜ下がったのかを一晩の電気の買い方で見ます。灰色は一度にたくさん買っていますが、青は同じくらいの量を夜の長い時間に分けて買っています。この例では買う量がほぼ同じなので、電気代はあまり変わらず、基本料金だけが下がります。");

// 7. Basic charge per year
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果2：年間の基本料金", { placeholder: "title" });
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考慮しない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e4)) },
  { name: "基本料金を考慮する", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e4)) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "基本料金 [万円/年]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "契約電力＝代表週（冬・春・夏）の最大受電電力。500 kW未満の実量制の考え方", 0.6, 6.5, 7.6);
const b8 = Math.round(basicYear(peakYear(rc8, 90)) / 1e4), b9 = Math.round(basicYear(peakYear(rc9, 90)) / 1e4);
bullets(s, [`受電上限90 kWの例：年 ${b8.toLocaleString()}万円 → ${b9.toLocaleString()}万円`, "いずれの受電上限でも、基本料金は約2.5〜5割減少した",
  "一方、電力量料金の増減は1週間で最大約2万円であり、基本料金の差と比べて小さい",
  "計算：最大受電電力 × 2,530円 × 0.85（力率100%）× 12か月"], { x: 8.6, y: 1.9, w: 4.2, h: 4.6, fontSize: 17 });
s.addNotes("ピークが下がると、1年分の基本料金が下がります。90 kWの例では年に約645万円の差です。電気を買う量は条件によって−11%〜+19%変わりましたが、電気代の差は1週間で最大約2万円です。契約電力は、500 kW未満なら過去1年の最大需要電力で決まります（実量制、東京電力EPの公式ページで確認）。単価2,530円は、東京電力EPの2026年4月からの料金表（関東・高圧・ベーシックプラン、税込）の値です。なお、最適化の計算そのものは旧単価1,890円で行っています。単価が変わっても、削減の割合は変わりません。");

// 8. CO2
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("結果3：CO₂排出量", { placeholder: "title" });
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  chart({ x: 0.6, y: 1.55, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "全車燃料バスは走行距離から軽油の量を計算した概算（最適化の結果ではない）。電力は0.5 kg/kWh（仮。東京電力EPの実値0.452より大きめ）", 0.6, 6.5, 7.6);
bullets(s, ["電気バスとの併用により、CO₂は全車燃料バスと比べて約75〜85%少なかった", "電気バスは走行時にCO₂を排出せず、太陽光発電の電力も利用できる"], { x: 8.6, y: 1.9, w: 4.2, h: 4.2, fontSize: 18 });
s.addNotes("CO₂の比較です。電気バスと一緒に使うと、全部を燃料バスで走る場合より約8割少なくなります。全部燃料バスの方は距離からの概算です。電力の係数0.5は、東京電力EPの実値（令和6年度実績0.452）より大きめで、電気バスに不利な側の仮定です。実値で計算すると削減は約77〜86%になります。");

// 9. Summary
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("まとめと今後の予定", { placeholder: "title" });
bullets(s, [
  "基本料金を考慮して計画すると、買電量を大きく変えずに、受電ピークと年間の基本料金を下げられることを確認した",
  "電気バスとの併用により、CO₂は全車燃料バスと比べて約8割少なかった",
  "留意点：結果は制限時間内に得られた計画であり、最適性の確認には至っていない",
  "明らかになった課題：便割当の段階では充電を太陽光と蓄電池でまかなえる見込みだったが、実際の充電計画では夜間の買電が必要となった",
  "今後の予定：上記の見込みと実際の差の検証、燃料バスへの振り替えが有利になる条件の感度分析、解の質の確認",
  "11月28日の中間発表（A0ポスター）に向けて、本結果を取りまとめる"], { x: 0.6, y: 1.7, w: 12.1, h: 5.4, fontSize: 18 });
s.addNotes("まとめです。充電の重なりを減らすことで、基本料金を大きく減らせることが分かりました。ただし、計算は制限時間で打ち切っています。便の割当は全件、基本料金を考えた充電計画も16件すべてが、時間内に得られた計画で、最適との差の上限（ギャップ）は13〜67%です。示した削減は実際に得られた計画での値で、さらに良い計画がありうるという意味です。また、便割当の段階では充電をほぼ太陽光と蓄電池でまかなえる見込みでしたが、実際の充電計画では夜に電気を買う必要が出ました。2段階に分けて解いていることによる見込みのずれと考えていて、確かめるのが次の課題です。今後は、燃料バスに切り替えた方が得になる条件を調べます。");

(async () => {
  const out = path.join(__dirname, "lab_progress_20261022.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
