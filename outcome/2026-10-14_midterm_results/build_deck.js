// Midterm (2026-11-28) pillar A results deck, built from the verified rc8 table.
// Run: node build_deck.js   (data files are copies from output/midterm_20261128/results_rc8)
const path = require("path");
const fs = require("fs");
const SCRATCH = process.env.DECK_NODE_MODULES;
const pptxgen = require(path.join(SCRATCH, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "midterm_pillarA_cases.json"), "utf8"));
const csv = (f) => {
  const [head, ...lines] = fs.readFileSync(path.join(__dirname, f), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
  const keys = head.split(",");
  return lines.map((l) => Object.fromEntries(l.split(",").map((v, i) => [keys[i], v])));
};
const evals = csv("posthoc_tariff_eval.csv");
const diesel = csv("all_diesel_estimate.csv");
const LIMITS = [90, 200, 400, 800];
const WEEKS = [["2025-01-06", "冬（1月）"], ["2025-04-07", "春（4月）"], ["2025-07-07", "夏（7月）"]];
const cell = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const man = (v) => Math.round(Number(v) / 1e3) / 10; // JPY -> 10^4 JPY, 1 decimal

const THEME = {
  name: "Midterm GX bus",
  headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: "1B2A2F", lt1: "FFFFFF", dk2: "0F4C5C", lt2: "EEF4F3", accent1: "1F7A8C", accent2: "E07A2E",
            accent3: "5FA84A", accent4: "C9A227", accent5: "6C5B9E", accent6: "B23A48", hlink: "1F7A8C", folHlink: "6C5B9E" },
};
const HEX = { teal: "1F7A8C", orange: "E07A2E", green: "5FA84A", gold: "C9A227", ink: "1B2A2F", muted: "5B6B70", grid: "D9E2E1" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "中間発表 柱A 受電上限の影響";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "TITLE_DARK", background: { color: THEME.colors.dk2 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.3, w: 11.7, h: 1.6, fontSize: 36, bold: true, color: C.background1, valign: "middle" }, text: "" } },
            { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 1.4, fontSize: 18, color: C.background2 }, text: "" } }],
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: THEME.colors.lt1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.9, fontSize: 28, bold: true, color: C.text2, valign: "middle" }, text: "" } }],
  slideNumber: { x: 12.4, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: HEX.muted },
});

const note = (slide, text, y = 6.85) => slide.addText(text, { x: 0.6, y, w: 11.6, h: 0.4, fontSize: 10, color: HEX.muted, isTextBox: true, margin: 0 });
const chartBase = (title) => ({
  showTitle: true, title, titleFontFace: "+mn-lt", titleFontSize: 13, titleColor: HEX.ink,
  catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 11, valAxisLabelFontSize: 10, valGridLine: { color: HEX.grid, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 11, legendColor: HEX.ink, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 9, dataLabelColor: HEX.ink,
});

// 1. Title
let s = pres.addSlide({ masterName: "TITLE_DARK" });
s.addText("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { placeholder: "title" });
  s.addNotes('本日は、柱Aとして、営業所の受電上限と電気の基本料金が、電気バスと燃料バスの運用費・CO₂にどう効くかを、便割当と充電計画を同時に最適化して評価した中間結果を報告します。');
s.addText("柱A：受電上限が費用・CO₂に与える影響（中間結果）\n渋21〜23系統・弦巻営業所／冬・春・夏の代表週", { placeholder: "body" });

// 2. Conditions
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("実験条件：60台・3季節・受電上限4通りの12ケース", { placeholder: "title" });
  s.addNotes('対象は渋21〜23系統の1週間1,704便で、電気バス35台・燃料バス25台に固定しました。営業所には太陽光1,000 kWと蓄電池6,000 kWhがあります。受電上限を90・200・400・800 kWの4通り、季節を冬・春・夏の3通りにした12ケースです。12ケースすべてで、毎時の見直しまで実行した最終費用の検査に合格しています。');
const conds = [["対象", "渋21〜23系統、1週間 1,704便"], ["車両", "電気バス35台・燃料バス25台（固定）"], ["エネルギー設備", "PV 1,000 kW（傾斜30°・真南）、蓄電池 6,000 kWh"],
  ["受電上限", "90 / 200 / 400 / 800 kW（超えた分は罰金で受電可）"], ["季節", "冬 2025-01-06・春 04-07・夏 07-07 の各1週間"],
  ["CO₂", "軽油 2.62 kg/L（環境省 算定・報告・公表制度）、電力 0.5 kg/kWh"], ["価格", "電気 30円/kWh、軽油 150円/L、車両 2万円/台日"]];
s.addTable(conds.map(([k, v]) => [{ text: k, options: { bold: true, color: C.text2, fill: { color: THEME.colors.lt2 } } }, { text: v }]),
  { x: 0.6, y: 1.5, w: 7.6, colW: [1.9, 5.7], fontSize: 15, color: HEX.ink, border: { type: "solid", pt: 0.75, color: HEX.grid }, rowH: 0.55, valign: "middle" });
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.7, y: 1.5, w: 4.0, h: 3.9, fill: { color: THEME.colors.lt2 }, rectRadius: 0.15, line: { color: THEME.colors.lt2 } });
s.addText([{ text: "12", options: { fontSize: 66, bold: true, color: C.accent1, breakLine: true } }, { text: "ケースすべて", options: { fontSize: 18, color: HEX.ink, breakLine: true } },
  { text: "毎時の見直しで1週間を実行し、最終費用の検査に合格", options: { fontSize: 14, color: HEX.muted } }],
  { x: 8.9, y: 1.7, w: 3.6, h: 3.5, align: "center", valign: "middle", isTextBox: true });
note(s, "最終費用は毎時の見直し後の確定会計（executed_day_accounting）を唯一の根拠とし、出力値との一致を検査した。");

// 3. Method
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("手法：二段階の最適化と毎時の見直し", { placeholder: "title" });
  s.addNotes('手法は二段階です。Stage 1で便を電気バスと燃料バスに割り当て、Stage 2で15分刻みの充電・太陽光・蓄電池・受電を最適化します。その後、1時間ごとに計画を立て直しながら1週間を実行します。Stage 1は汎用ソルバーだけでは改善しなかったため、ALNS型の部分再最適化で初期解を改善しました。');
const steps = [["Stage 1", "便割当", "電気バス／燃料バスへの便の割当（MILP）。規則に基づく初期解から出発し、LNS（ALNS型の部分再最適化）で改善"],
  ["Stage 2", "充電計画", "割当を固定し、充電・PV・蓄電池・受電を15分刻みで最適化（MILP）"],
  ["実行", "毎時の見直し", "1時間ごとに残りの計画を最適化し直して1週間を実行（175回）"]];
steps.forEach(([tag, name, desc], i) => {
  const x = 0.6 + i * 4.2;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.6, w: 3.8, h: 3.3, fill: { color: THEME.colors.lt2 }, line: { color: THEME.colors.lt2 }, rectRadius: 0.12 });
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.85, w: 0.9, h: 0.9, fill: { color: C.accent1 }, line: { color: C.accent1 } });
  s.addText(String(i + 1), { x: x + 0.3, y: 1.85, w: 0.9, h: 0.9, align: "center", valign: "middle", fontSize: 26, bold: true, color: C.background1, isTextBox: true, margin: 0 });
  s.addText([{ text: tag, options: { fontSize: 13, color: HEX.muted, breakLine: true } }, { text: name, options: { fontSize: 22, bold: true, color: C.text2 } }],
    { x: x + 1.35, y: 1.85, w: 2.3, h: 0.9, valign: "middle", isTextBox: true, margin: 0 });
  s.addText(desc, { x: x + 0.3, y: 2.95, w: 3.3, h: 1.8, fontSize: 14, color: HEX.ink, valign: "top", isTextBox: true, margin: 0 });
  if (i < 2) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 3.85, y: 3.0, w: 0.3, h: 0.45, fill: { color: C.accent2 }, line: { color: C.accent2 } });
});
s.addText("解の質：停止条件のギャップは1%。Stage 2 は12件中11件で最適（ギャップ0〜0.3%）。Stage 1 は6時間の時間制限内の実行可能解（LNSで初期解から最大9.1万円改善）。",
  { x: 0.6, y: 5.25, w: 12.1, h: 0.9, fontSize: 14, color: HEX.ink, isTextBox: true, margin: 0 });
note(s, "Stage 1 の報告ギャップ（約45%）は、下界に車両費しか含まれず電気・燃料費が入らないためで、最適解からの距離を表すものではない（質疑用）。");

// 4. Weekly variable cost
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("受電上限が低いほど契約超過の罰金で費用が増える", { placeholder: "title" });
  s.addNotes('1週間の電気代・燃料代・超過の罰金です。上限を下げると罰金が大きく増え、冬の90 kWでは週135万円になります。電気代と燃料代そのものは上限によってあまり変わりません。');
WEEKS.forEach(([w, name], i) => {
  const labels = LIMITS.map((g) => `${g} kW`);
  const series = [["電気代", "electricity_cost"], ["燃料代", "fuel_cost"], ["契約超過の罰金", "contract_overage_cost"]]
    .map(([n, k]) => ({ name: n, labels, values: LIMITS.map((g) => man(cell(g, w)[k] || 0)) }));
  s.addChart(pres.charts.BAR, series, { ...chartBase(name), x: 0.5 + i * 4.15, y: 1.35, w: 4.05, h: 4.9, barDir: "col", barGrouping: "stacked",
    chartColors: [HEX.teal, HEX.orange, HEX.gold], showLegend: i === 0, legendPos: "t", legendFontSize: 12, catAxisLabelFontSize: 12, valAxisMaxVal: 140, valAxisMinVal: 0,
    valAxisTitle: i === 0 ? "万円/週" : undefined, showValAxisTitle: i === 0, valAxisTitleFontSize: 10, valAxisTitleColor: HEX.muted });
});
note(s, "冬の90 kWは週135万円、800 kWは13万円。車両費（約410万円/週）は全ケースでほぼ同じなので除いた。罰金は計算上の仮の単価（500円/kWh）。");

// 5. Peak vs limit
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("上限を下げても、実際の受電ピークは約600 kWまで上がる", { placeholder: "title" });
  s.addNotes('ここが一つ目のポイントです。上限を90 kWにしても、実際の最大受電は冬に約600 kWまで上がっています。罰金がkWhあたりなので、短時間の大きなピークを抑える動機がないためです。実際の料金では、ピークのkWが1年間の基本料金を決めます。');
s.addChart(pres.charts.BAR, WEEKS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `上限 ${g} kW`), values: LIMITS.map((g) => Math.round(cell(g, w).peak_grid_kw)) })),
  { ...chartBase("実行した1週間の最大受電電力（kW）"), x: 0.6, y: 1.35, w: 8.2, h: 5.2, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.teal, HEX.orange, HEX.green], showValue: true, dataLabelPosition: "outEnd", showLegend: true, legendPos: "t", valAxisMaxVal: 800, valAxisMinVal: 0 });
s.addText([{ text: "なぜ？", options: { bold: true, fontSize: 18, color: C.text2, breakLine: true } },
  { text: "今の計算は、上限を超えた分を「1 kWhあたり500円」で罰している。短く大きなピークはkWhが小さいので罰金も小さく、ピークを抑える動機がない。", options: { fontSize: 14, color: HEX.ink, breakLine: true } },
  { text: " ", options: { fontSize: 8, breakLine: true } },
  { text: "実際の料金では、ピーク（kW）が1年間の基本料金を決める。", options: { fontSize: 14, bold: true, color: C.accent2 } }],
  { x: 9.1, y: 1.6, w: 3.7, h: 4.6, valign: "top", isTextBox: true, margin: 0 });

// 6. Annual with basic charge (post-hoc)
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("基本料金まで含めると、年間では400 kWが最も安い", { placeholder: "title" });
  s.addNotes('そこで、罰金を外し、実際の料金体系、つまり契約電力に応じた基本料金と受変電設備の費用で年間費用を評価し直しました。この事後評価では400 kWが最も安く、800 kWより年に約670万円安くなりました。');
const veh = evals.map((r) => Number(r.annual_vehicle_cost_yen));
s.addChart(pres.charts.BAR, [
  { name: "電気代・燃料代など", labels: evals.map((r) => `上限 ${r.grid_limit_kw} kW`), values: evals.map((r, i) => Math.round((Number(r.annual_operating_cost_yen) - veh[i]) / 1e4)) },
  { name: "基本料金", labels: [], values: evals.map((r) => Math.round(Number(r.annual_basic_charge_yen) / 1e4)) },
  { name: "受変電設備（参考）", labels: [], values: evals.map((r) => Math.round(Number(r.annual_substation_mid_yen) / 1e4)) }],
  { ...chartBase("年間費用（万円、車両費を除く）"), x: 0.6, y: 1.35, w: 8.2, h: 5.2, barDir: "col", barGrouping: "stacked",
    chartColors: [HEX.teal, HEX.orange, HEX.gold], showValue: true, dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", showLegend: true, legendPos: "t" });
const best = evals.reduce((a, b) => (Number(a.annual_total_real_tariff_mid_yen) < Number(b.annual_total_real_tariff_mid_yen) ? a : b));
const worst = evals.reduce((a, b) => (Number(a.annual_total_real_tariff_mid_yen) > Number(b.annual_total_real_tariff_mid_yen) ? a : b));
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.1, y: 1.6, w: 3.7, h: 2.2, fill: { color: THEME.colors.lt2 }, line: { color: THEME.colors.lt2 }, rectRadius: 0.12 });
s.addText([{ text: `年 −${Math.round((Number(worst.annual_total_real_tariff_mid_yen) - Number(best.annual_total_real_tariff_mid_yen)) / 1e4)}万円`, options: { fontSize: 30, bold: true, color: C.accent1, breakLine: true } },
  { text: `${best.grid_limit_kw} kW（契約${best.contract_kw} kW）と ${worst.grid_limit_kw} kW の差`, options: { fontSize: 13, color: HEX.ink } }],
  { x: 9.2, y: 1.7, w: 3.5, h: 2.0, align: "center", valign: "middle", isTextBox: true });
s.addText("契約電力＝max（受電上限、年間最大の受電ピーク）。基本料金1,890円/kW×0.85×12か月。受変電設備は相場の中位を20年で割った参考値（安い〜高いで年±60万円、順位は変わらない）。",
  { x: 9.1, y: 4.0, w: 3.7, h: 2.4, fontSize: 12, color: HEX.muted, valign: "top", isTextBox: true, margin: 0 });
note(s, "事後評価（再計算なし）。代表3週を冬13・春秋26・夏13週で年換算。基本料金を目的関数に入れた再計算を実施中。");

// 6b. rc9: basic charge inside the optimization (only when the rc9 table is present)
const rc9Path = path.join(__dirname, "midterm_pillarA_cases_rc9.json");
if (fs.existsSync(rc9Path)) {
  const rc9 = JSON.parse(fs.readFileSync(rc9Path, "utf8")).filter((r) => r.status === "VERIFIED");
  const c9 = (g, w) => rc9.find((r) => r.grid_limit_kw === g && r.week === w);
  const done = LIMITS.flatMap((g) => WEEKS.map(([w]) => [g, w])).filter(([g, w]) => c9(g, w));
  s = pres.addSlide({ masterName: "CONTENT" });
  s.addText("基本料金を最適化に入れると、受電ピークが大きく下がる", { placeholder: "title" });
  s.addNotes('次に、基本料金を最適化の目的関数に入れて計算し直しました。同じケースで比べると、受電ピークが25〜63%下がりました。1週間に買う電気の量と電気バスの担当便の割合はほぼ同じで、夜の充電を時間的にならしてピークを下げていました。');
  const labels = done.map(([g, w]) => `${g} kW・${WEEKS.find((x) => x[0] === w)[1].slice(0, 1)}`);
  s.addChart(pres.charts.BAR, [
    { name: "基本料金なしで最適化", labels, values: done.map(([g, w]) => Math.round(cell(g, w).peak_grid_kw)) },
    { name: "基本料金ありで最適化", labels, values: done.map(([g, w]) => Math.round(c9(g, w).peak_grid_kw)) }],
    { ...chartBase("1週間の最大受電電力（kW）"), x: 0.6, y: 1.35, w: 8.6, h: 5.2, barDir: "col", barGrouping: "clustered",
      chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", showLegend: true, legendPos: "t" });
  const drops = done.map(([g, w]) => 1 - c9(g, w).peak_grid_kw / cell(g, w).peak_grid_kw);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.5, y: 1.6, w: 3.3, h: 2.2, fill: { color: THEME.colors.lt2 }, line: { color: THEME.colors.lt2 }, rectRadius: 0.12 });
  s.addText([{ text: `ピーク −${Math.round(Math.min(...drops) * 100)}〜${Math.round(Math.max(...drops) * 100)}%`, options: { fontSize: 22, bold: true, color: C.accent1, breakLine: true } },
    { text: "同じケースで、基本料金の有無を比べた", options: { fontSize: 13, color: HEX.ink } }],
    { x: 9.6, y: 1.7, w: 3.1, h: 2.0, align: "center", valign: "middle", isTextBox: true });
  s.addText("基本料金は1,606.5円/kW月（1,890円×0.85）を計画期間に按分して目的関数に入れた。ほかの条件は同じ。1週間の買電量と電気バスの担当便の割合はほぼ同じで、夜の充電を時間的にならしてピークを下げた（90 kW・冬の買電量 3,896→3,931 kWh で確認）。",
    { x: 9.5, y: 4.0, w: 3.3, h: 2.4, fontSize: 12, color: HEX.muted, valign: "top", isTextBox: true, margin: 0 });
  if (done.length < 12) note(s, `計算中のケースを除く（${done.length}/12ケース）。`);
}

// 7. CO2 vs all-diesel
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("電気バスとの併用で、CO₂は全車エンジンバスより75〜85%少ない", { placeholder: "title" });
  s.addNotes('全車エンジンバスと比べると、電気バスとの併用でCO₂は75〜85%少なく、費用も週38〜44万円安くなります。なお、全車エンジンバスは距離からの単純計算です。');
s.addChart(pres.charts.BAR, [
  { name: "全車エンジンバス（単純計算）", labels: WEEKS.map(([, n]) => n), values: WEEKS.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バス併用（最適化、800 kW）", labels: [], values: WEEKS.map(([w]) => Math.round(cell(800, w).total_co2_kg / 100) / 10) }],
  { ...chartBase("1週間のCO₂排出量（t）"), x: 0.6, y: 1.35, w: 7.4, h: 5.2, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.orange, HEX.teal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", dataLabelFontSize: 11, showLegend: true, legendPos: "t" });
const costDiff = WEEKS.map(([w]) => Number(diesel.find((d) => d.week === w).total_cost) - cell(800, w).total_cost);
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.4, y: 1.6, w: 4.4, h: 2.2, fill: { color: THEME.colors.lt2 }, line: { color: THEME.colors.lt2 }, rectRadius: 0.12 });
s.addText([{ text: `費用も週 −${Math.round(Math.min(...costDiff) / 1e4)}〜${Math.round(Math.max(...costDiff) / 1e4)}万円`, options: { fontSize: 24, bold: true, color: C.accent1, breakLine: true } },
  { text: "全車エンジンバスと比べた併用（800 kW）の差", options: { fontSize: 13, color: HEX.ink } }],
  { x: 8.5, y: 1.7, w: 4.2, h: 2.0, align: "center", valign: "middle", isTextBox: true });
s.addText("全車エンジンバスは、800 kWの実行計画の走行距離を4.52 km/Lで軽油に換算した単純計算（最適化の結果ではない）。車両日数と単価は同じとした。",
  { x: 8.4, y: 4.0, w: 4.4, h: 2.4, fontSize: 12, color: HEX.muted, valign: "top", isTextBox: true, margin: 0 });

// 8. LNS effect
s = pres.addSlide({ masterName: "CONTENT" });
s.addText("便割当はLNS（ALNS型）で初期解から改善した", { placeholder: "title" });
  s.addNotes('最後に手法の効果です。汎用ソルバーでは6時間かけても初期解から改善しませんでしたが、LNSにより1週あたり最大9.1万円改善しました。最適性の証明ではなく、改善された実行可能解として扱っています。');
s.addChart(pres.charts.BAR, WEEKS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `上限 ${g} kW`), values: LIMITS.map((g) => Math.round((cell(g, w).lns_improvement_yen || 0) / 1e3) / 10) })),
  { ...chartBase("初期解からの削減額（万円/週）"), x: 0.6, y: 1.35, w: 8.2, h: 5.2, barDir: "col", barGrouping: "clustered",
    chartColors: [HEX.teal, HEX.orange, HEX.green], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", showLegend: true, legendPos: "t" });
s.addText([{ text: "LNSのしくみ", options: { bold: true, fontSize: 18, color: C.text2, breakLine: true } },
  { text: "現在の割当の大部分を固定し、一部の便（ランダム・時間帯・路線）だけを小さなMIPで解き直す。安くなれば採用し、効いた選び方を多く使う。", options: { fontSize: 14, color: HEX.ink, breakLine: true } },
  { text: " ", options: { fontSize: 8, breakLine: true } },
  { text: "汎用のMILPソルバーだけでは6時間かけても初期解から改善しなかった。", options: { fontSize: 14, color: C.accent2 } }],
  { x: 9.1, y: 1.6, w: 3.7, h: 4.6, valign: "top", isTextBox: true, margin: 0 });

// 9. Summary
s = pres.addSlide({ masterName: "TITLE_DARK" });
s.addText("まとめと今後", { placeholder: "title" });
  s.addNotes('まとめです。受電上限を下げると費用が増えますが、基本料金を最適化に入れると受電ピークを大きく抑えられます。今後は秋の週を加えた年間評価、燃料バスへの振り替えが起きる条件の感度分析、下界の強化に取り組みます。');
s.addText([
  { text: "受電上限を下げると、超過分の受電で費用が増える。90 kWでは800 kWより週 約53〜121万円高い", options: { bullet: true, breakLine: true } },
  { text: "電気バスの担当便は上限によらず92〜97%。CO₂は全車エンジンバスより75〜85%少ない", options: { bullet: true, breakLine: true } },
  { text: "基本料金まで含めた年間評価では、400 kWが最も安い（事後評価）", options: { bullet: true, breakLine: true } },
  { text: "今後：基本料金を目的関数に入れた再計算、秋と年間への拡張、設備費の精緻化", options: { bullet: true } }],
  { placeholder: "body", fontSize: 18, paraSpaceAfter: 8 });

(async () => {
  const out = path.join(__dirname, "midterm_pillarA_results.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
