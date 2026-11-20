// Answers to the six questions from the lab meeting of 2026-11-19, for lab members and the co-examiners (2026-11-20).
// Tariff A only (Prof. Urabe: proceed with variant A). Every number is computed here from
// ../2026-11-12_three_party/deck_data_rc42_et.json with the poster's reporting rule
// (total = total_cost_fuel_consumed - CO2 kg x 1 JPY + weekly basic charge) and guarded, so the slides cannot drift from the data.
// Facts (data, code, records) and outlook (not computed) are labelled on each slide. Text answers: 研究室からの質問への回答_20261120.md.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

// ---------------- data
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_rc42_et.json"), "utf8"));
if (D.tariff_series !== "et" || D.cases.length !== 12 || D.pairs.length !== 24 || [...D.cases, ...D.pairs].some((r) => r.status !== "VERIFIED"))
  throw new Error("rc42 tariff A data is not 12 cases / 24 runs, all VERIFIED");
const tc = (r) => r.total_cost_fuel_consumed - r.total_co2_kg + r.basic_charge_week_jpy;
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]], LIMITS = D.limits;
const get = (g, w) => D.cases.find((r) => r.grid_limit_kw === g && r.week === w);
const man = (v, d = 1) => (v / 1e4).toFixed(d);
const fmt = (v) => Math.round(v).toLocaleString("en-US");
const W = "2025-01-06";
const BASIC = (g) => g * 2530 * 0.85 * 12 / 52;
D.cases.forEach((r) => {
  if (Math.abs(BASIC(r.grid_limit_kw) - r.basic_charge_week_jpy) > 1) throw new Error(`basic charge formula mismatch: ${r.case}`);
  const p = r.vehicle_usage_cost + r.electricity_cost + r.contract_overage_cost + r.ice_fuel_consumed_l * 150 + r.basic_charge_week_jpy;
  if (Math.abs(p - tc(r)) > 1) throw new Error(`cost parts do not add up: ${r.case}`);
  if (Math.abs(r.contract_over_limit_kwh * 500 - r.contract_overage_cost) > 1) throw new Error(`excess price mismatch: ${r.case}`); });
const S4 = SE.map(([w, n]) => ({ n, r: get(400, w) }));
if (!S4.every((x) => Math.abs(x.r.peak_grid_kw - 400) < 0.5)) throw new Error("400 kW peaks are no longer at the limit; rewrite slide 4");
const winter4 = get(400, W), summer4 = get(400, "2025-07-07");
const ratioWS = winter4.grid_import_kwh / summer4.grid_import_kwh;
const pvMax = SE.reduce((b, [w]) => (get(400, w).pv_generated_kwh > get(400, b).pv_generated_kwh ? w : b), W);
if (pvMax !== "2025-07-07" || ratioWS < 1.4) throw new Error("summer is no longer the sunniest or winter purchase lead changed; rewrite slide 4");
const best = SE.map(([w, n]) => ({ n, r: LIMITS.map((g) => get(g, w)).sort((a, b) => tc(a) - tc(b))[0] }));
if (best[0].r.grid_limit_kw !== 400 || best[1].r.grid_limit_kw !== 200 || best[2].r.grid_limit_kw !== 200) throw new Error("cheapest limits changed; rewrite slide 5");
const gap4 = Math.min(...S4.map((x) => 0.05 * tc(x.r))), gap4max = Math.max(...S4.map((x) => 0.05 * tc(x.r)));
const spread4 = Math.max(...S4.map((x) => tc(x.r))) - Math.min(...S4.map((x) => tc(x.r)));
if (!(spread4 < gap4)) throw new Error("seasonal spread at 400 kW exceeds the gap; rewrite slide 5");
const w200 = get(200, W);
const curt = S4.map((x) => x.r.pv_curtailed_kwh);
const fl = (v, s) => Math.floor(v / s) * s, cl = (v, s) => Math.ceil(v / s) * s;

// ---------------- frame (same look as the November lab report, outcome/2026-11-19_lab_progress)
const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2", ORANGE = "E08A00", AMBER_PALE = "FFF4E0";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "研究室からのご質問への回答 2026-11-20";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "11/19 研究室でのご質問への回答　2026年11月20日　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });
const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 6, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const tableOpts = (o) => ({ fontSize: 14, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center" } });
const ICON = (n) => {
  for (const d of ["../2026-11-28_midterm_poster/icons", "../2026-11-16_nishiyama_consult/icons", "../2026-11-17_nishiyama_feedback_report/icons"]) {
    const p = path.join(__dirname, d, `${n}.png`); if (fs.existsSync(p)) return p; }
  throw new Error("icon " + n); };
const icon = (s, n, x, y, w, alt) => s.addImage({ path: ICON(n), x, y, w, h: w, altText: alt || n });
const card = (s, x, y, w, h, fill = BLUE_PALE) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: GRID, width: 0.75 } });
// evidence tag: 事実 (data / code / records) or 見通し (not computed)
const tag = (s, kind, x, y) => { const f = kind === "事実" ? BLUE_DARK : ORANGE;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 0.9, h: 0.34, rectRadius: 0.06, fill: { color: f }, line: { color: f } });
  text(s, kind, { x, y, w: 0.9, h: 0.34, fontSize: 12, bold: true, color: "FFFFFF", align: "center", valign: "middle" }); };
const question = (s, q) => { card(s, 0.6, 1.45, 12.1, 0.7, "F4F7FA");
  text(s, [{ text: "ご質問　", options: { bold: true, color: BLUE_DARK } }, { text: q }], { x: 0.8, y: 1.45, w: 11.8, h: 0.7, fontSize: q.length > 55 ? 13 : 15, valign: "middle" }); };
const chartBase = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: INK, showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt",
  dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12, dataLabelColor: INK });
const DIAG = "数値は rc42（19dc0780）・料金Aの診断用（DIAGNOSTIC）の結果。研究の結論にはまだ使っていません。";

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "11/19 研究室 月次報告へのご質問", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "いただいた6つのご質問への回答", { x: 0.9, y: 1.8, w: 11.5, h: 1.2, fontSize: 34, bold: true, valign: "bottom" });
text(s, "研究題目：GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", { x: 0.9, y: 3.2, w: 11.5, h: 0.5, fontSize: 16, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 3.85, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "電力システム研究室　修士1年　劉 承洋　2026年11月20日", { x: 0.9, y: 4.1, w: 11.5, h: 0.5, fontSize: 17, color: SUB });
text(s, "電気料金は料金A（17.43円/kWh＋基本料金）で答えます（占部先生のご指示で、今後は料金Aで進めます）。各ページで、データで確かめた「事実」と、まだ計算していない「見通し」を分けて示します。",
  { x: 0.9, y: 4.9, w: 11.5, h: 0.9, fontSize: 15 });
tag(s, "事実", 0.9, 5.95); text(s, "計算結果・コード・記録で確かめたこと", { x: 1.9, y: 5.95, w: 4.5, h: 0.34, fontSize: 13, valign: "middle", color: SUB });
tag(s, "見通し", 6.5, 5.95); text(s, "考えや今後の計画（まだ計算していない）", { x: 7.5, y: 5.95, w: 4.9, h: 0.34, fontSize: 13, valign: "middle", color: SUB });
s.addNotes("昨日の研究室でいただいた6つのご質問に、まとめてお答えします。電気料金は、占部先生のご指示どおり料金Aで答えます。計算やデータで確かめたことは「事実」、まだ計算していない考えは「見通し」と、色で分けて示します。");

// ---- 2. Summary
s = page("ご質問と答えの要点");
const SUM = [
  ["1", "秋がないのはなぜ", "秋は春と似ているので、春の週で秋も代表させた", "事実"],
  ["2", "冬の方が太陽光で賄えるのか。季節差は意味があるか", `逆。太陽光は夏が多く、冬は夏の約${ratioWS.toFixed(1)}倍の電力を買う。費用の季節差はギャップより小さく、統計的に有意とは言えない`, "事実"],
  ["3", "社会の課題は無人バスで改善できるか", "運転士の制約は軽くなる。今のモデルは運転士を入れていないので、「制約あり／なし」を比べられる", "見通し"],
  ["4", "人の気持ちを考えるとは", "効率を捨てるのではなく、何を「効率」とするかに利用者・事業者の視点を入れる", "見通し"],
  ["5", "電気料金の計算の一例", `400 kW冬で約${man(winter4.electricity_cost + winter4.basic_charge_week_jpy)}万円/週（うち基本料金${man(winter4.basic_charge_week_jpy)}万円）`, "事実"],
  ["6", "冷暖房を強くすると消費が増えるが大丈夫か", "今の計算は冷暖房の季節変化を入れていない。上限に余裕がないので、感度計算で確かめる", "事実"]];
s.addTable([[H("#"), H("ご質問"), H("答えの要点"), H("根拠")],
  ...SUM.map(([n, q, a, k]) => [{ text: n, options: { align: "center", bold: true } }, { text: q, options: { bold: true } }, a,
    { text: k, options: { align: "center", bold: true, color: k === "事実" ? BLUE_DARK : ORANGE } }])],
  tableOpts({ x: 0.6, y: 1.5, w: 12.1, colW: [0.5, 3.6, 7.0, 1.0], fontSize: 13, rowH: [0.42, 0.72, 0.72, 0.72, 0.72, 0.72, 0.72] }));
caption(s, "Q2・Q5・Q6 は計算結果とコードで確かめた。Q3・Q4 は計算していない考え。", 0.6, 6.35, 12.1, 0.55);
s.addNotes("6つのご質問と、答えの要点です。1番は計算の条件、2番・5番・6番は、計算結果やプログラムで確かめた事実でお答えします。3番と4番は、まだ計算していない考え方の話になります。");

// ---- 3. Q1 autumn
s = page("Q1. 季節に秋がないのは、何か意味があるのですか？");
question(s, "季節の中に秋がないのは何か意味があるのですか？");
card(s, 0.6, 2.35, 5.9, 4.1); tag(s, "事実", 0.85, 2.55);
text(s, "今回の計算", { x: 1.9, y: 2.5, w: 4.4, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, ["冬（1/6〜）・春（4/7〜）・夏（7/7〜）の代表3週。受電上限4通りと合わせて12ケース",
  "以前の年間の見積もり（10/14）では、春の週で秋も代表させた（冬13週・春26週・夏13週）",
  "秋の週も、以前の版（rc9、10/19）では計算したことがある"], { x: 0.85, y: 3.1, w: 5.4, h: 3.2, fontSize: 15 });
card(s, 6.8, 2.35, 5.9, 4.1); tag(s, "事実", 7.05, 2.55);
text(s, "理由", { x: 8.1, y: 2.5, w: 4.4, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, ["秋は春と似ているので、春の週で秋も代表させた"], { x: 7.05, y: 3.1, w: 5.4, h: 3.2, fontSize: 18 });
s.addNotes("今回は冬・春・夏の3週で、秋はありません。以前の年間の見積もりでは、春の週で秋も代表させていました。秋は春と似ているので、春の週で秋も代表させています。ポスターの表2にもそう書きました。");

// ---- 4. Q2 (1) seasons and PV
s = page("Q2①. 太陽光で賄えるのは夏、電気を多く買うのは冬");
question(s, "夏よりも冬の方が太陽光で賄える電力量が増えて、受電コストは低くなるのでしょうか？");
tag(s, "事実", 0.6, 2.3);
s.addChart(pres.charts.BAR, [
  { name: "太陽光の発電量", labels: S4.map((x) => x.n), values: S4.map((x) => Math.round(x.r.pv_generated_kwh / 100) / 10) },
  { name: "太陽光のうち使えた量", labels: S4.map((x) => x.n), values: S4.map((x) => Math.round(x.r.pv_used_total_kwh / 100) / 10) },
  { name: "電力会社から買った量", labels: S4.map((x) => x.n), values: S4.map((x) => Math.round(x.r.grid_import_kwh / 100) / 10) }],
  { ...chartBase(), x: 0.6, y: 2.7, w: 6.6, h: 3.75, barDir: "col", barGrouping: "clustered", barGapWidthPct: 50, chartColors: ["7AB8E8", BLUE_DARK, ORANGE],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0, valAxisMaxVal: 35, valAxisMajorUnit: 5,
    showValAxisTitle: true, valAxisTitle: "MWh/週（1,000 kWh）", valAxisTitleFontSize: 12, valAxisTitleColor: SUB });
caption(s, "受電上限400 kW、各季節で採用した解（料金A）。電力量は1週間の合計。", 0.6, 6.5, 6.6);
card(s, 7.5, 2.3, 5.2, 4.55);
bullets(s, [`逆です。太陽光の発電は夏が最も多く（${fmt(summer4.pv_generated_kwh)} kWh/週）、冬が最も少ない（${fmt(winter4.pv_generated_kwh)} kWh/週）`,
  `そのため冬は電気を多く買う：${fmt(winter4.grid_import_kwh)} kWh/週で、夏（${fmt(summer4.grid_import_kwh)} kWh）の約${ratioWS.toFixed(1)}倍。電力量料金も冬が最も大きい（${man(winter4.electricity_cost)}万円/週）`,
  `400 kW では、どの季節も受電の最大値が上限ちょうど（400 kW）。「どれも400 kW強」に見えたのは、上限に張り付いているためと思われる`,
  `太陽光は、どの季節も週に${fmt(fl(Math.min(...curt), 100))}〜${fmt(cl(Math.max(...curt), 100))} kWh が使われずに捨てられている（蓄電池は規則で動かしており、最適化していない）`],
  { x: 7.7, y: 2.45, w: 4.85, h: 4.3, fontSize: 14 });
s.addNotes(`ご質問とは逆で、太陽光の発電が多いのは夏、少ないのは冬です。そのため冬は電気を多く買っていて、受電上限400 kWでは、冬は夏の約${ratioWS.toFixed(1)}倍を買っています。400 kWのケースでは、どの季節も受電の最大値がちょうど400 kWで、上限に張り付いています。「どれも400 kW強」に見えたのは、このためだと思います。また、太陽光はどの季節も週に4,000〜5,000 kWh台が捨てられていて、蓄電池の使い方を最適化すれば減らせる可能性があります。`);

// ---- 5. Q2 (2) is the seasonal difference meaningful
s = page("Q2②. 季節の差は「意味のある差」と言えるか");
question(s, "各季節の受電上限を見るとどれも400 kW強ですが、それは季節によって優位な差だと言えるのでしょうか？");
tag(s, "事実", 0.6, 2.3);
s.addTable([[H(""), ...SE.map(([, n]) => H(n))],
  [{ text: "いちばん安い受電上限", options: { bold: true } }, ...best.map((b) => ({ text: `${b.r.grid_limit_kw} kW`, options: { align: "center", bold: true, color: BLUE_DARK } }))],
  [{ text: "そのときの総費用［万円/週］", options: { bold: true } }, ...best.map((b) => ({ text: man(tc(b.r)), options: { align: "center" } }))],
  [{ text: "400 kW の総費用［万円/週］", options: { bold: true } }, ...S4.map((x) => ({ text: man(tc(x.r)), options: { align: "center" } }))],
  [{ text: "400 kW の買った電力量［kWh/週］", options: { bold: true } }, ...S4.map((x) => ({ text: fmt(x.r.grid_import_kwh), options: { align: "center" } }))]],
  tableOpts({ x: 0.6, y: 2.75, w: 6.6, colW: [3.6, 1.0, 1.0, 1.0], fontSize: 14, rowH: [0.45, 0.6, 0.6, 0.6, 0.6] }));
caption(s, `総費用は車両使用費を含み、CO₂の費用は含めない。ギャップ5%は各ケースの総費用の5%（400 kW では${man(gap4)}〜${man(gap4max)}万円/週）。`, 0.6, 5.7, 6.6, 0.5);
card(s, 7.5, 2.3, 5.2, 4.55);
text(s, "答え：統計的に有意とは言えない", { x: 7.7, y: 2.4, w: 4.85, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, ["各季節1週間ずつ・各1回の計算で、ばらつきを測れないため",
  `費用：400 kW の季節差は最大${man(spread4)}万円/週。計算を止めてよいとした幅（ギャップ5%、約${man(gap4)}万円/週）より小さく、差があるとは言えない`,
  `買った電力量：冬は夏の約${ratioWS.toFixed(1)}倍。日射の違いという物理的な理由があり、方向ははっきりしている。ただしこれも1週ずつの比較`,
  "いちばん安い上限は季節で違う（冬400 kW、春・夏200 kW）。冬の200 kWは上限を超えるため"],
  { x: 7.7, y: 2.95, w: 4.85, h: 3.85, fontSize: 14 });
text(s, "確かめるには：季節ごとに複数の週・複数の乱数で計算し、ばらつきと比べる（今後の課題）。", { x: 0.6, y: 6.2, w: 6.6, h: 0.6, fontSize: 14, bold: true, color: BLUE_DARK });
s.addNotes(`統計的に有意な差とは言えません。各季節1週間ずつ、1回ずつの計算なので、ばらつきが分からないからです。費用で見ると、400 kWの季節差は最大${man(spread4)}万円で、計算を止めてよいとした幅の約${man(gap4)}万円より小さいです。一方、買った電力量は冬が夏の約${ratioWS.toFixed(1)}倍で、日射という物理的な理由があるので方向ははっきりしています。いちばん安い上限は、冬が400 kW、春と夏が200 kWで、季節で違います。きちんと確かめるには、季節ごとに複数の週と乱数で計算する必要があり、今後の課題です。`);

// ---- 6. Q5 worked bill
s = page("Q5. 電気料金の計算の一例（料金A、1週間）");
question(s, "電気料金算出の一例を教えてください。");
tag(s, "事実", 0.6, 2.3);
text(s, "電気代 ＝ 買った電力量 × 17.43円/kWh ＋ 受電上限 × 2,530円/kW・月 × 0.85 × 12/52 ＋ 上限を超えた電力量 × 500円/kWh",
  { x: 1.6, y: 2.25, w: 11.1, h: 0.45, fontSize: 13, bold: true, valign: "middle" });
const bill = (x, title, r, note) => {
  card(s, x, 2.9, 5.9, 3.55, "FFFFFF");
  text(s, title, { x: x + 0.2, y: 3.0, w: 5.5, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
  const rows = [["電力量料金", `${fmt(r.grid_import_kwh)} kWh × 17.43円`, r.electricity_cost],
    ["基本料金", `${r.grid_limit_kw} kW × 2,530円 × 0.85 × 12/52`, r.basic_charge_week_jpy],
    ["上限超過", `${fmt(r.contract_over_limit_kwh)} kWh × 500円`, r.contract_overage_cost]];
  s.addTable([...rows.map(([a, b, v]) => [{ text: a, options: { bold: true } }, b, { text: `${fmt(v)} 円`, options: { align: "right" } }]),
    [{ text: "合計", options: { bold: true, fill: { color: "DCEBF7" } } }, { text: "", options: { fill: { color: "DCEBF7" } } },
      { text: `${fmt(r.electricity_cost + r.basic_charge_week_jpy + r.contract_overage_cost)} 円`, options: { align: "right", bold: true, fill: { color: "DCEBF7" } } }]],
    tableOpts({ x: x + 0.2, y: 3.5, w: 5.5, colW: [1.25, 2.75, 1.5], fontSize: 13, rowH: 0.48 }));
  text(s, note, { x: x + 0.2, y: 5.5, w: 5.5, h: 0.85, fontSize: 13, color: SUB });
};
bill(0.6, "例1：受電上限400 kW・冬（超過なし）", winter4, `基本料金が電力量料金の約${(winter4.basic_charge_week_jpy / winter4.electricity_cost).toFixed(1)}倍。使わなくても毎月かかる`);
bill(6.8, "例2：受電上限200 kW・冬（上限を超えた）", w200, `超過の費用が最も大きい。500円/kWh は計算上の仮の罰金で、実際の契約では契約電力そのものが上がる`);
caption(s, "電力量料金は計算結果の値（買った電力量×17.43円）。基本料金・超過はデータの値と式が一致することを確かめた。燃料代・車両使用費は含めない（電気代だけ）。", 0.6, 6.55, 12.1);
s.addNotes(`料金Aの電気代は3つの部分の足し算です。例1の400 kW・冬では、電力量料金が約${man(winter4.electricity_cost)}万円、基本料金が約${man(winter4.basic_charge_week_jpy)}万円で、超過はありません。基本料金の方が大きいのがポイントです。例2の200 kW・冬では、上限を${fmt(w200.contract_over_limit_kwh)} kWh超えたので、その費用が約${man(w200.contract_overage_cost)}万円かかっています。500円/kWhは計算上の仮の罰金で、実際の契約では契約電力そのものが上がります。`);

// ---- 7. Q6 HVAC
s = page("Q6. 冷暖房などで消費電力が増えたら、運用は大丈夫か");
question(s, "利用者目線での改善案などを採用する場合、消費電力が増えてしまうと思うのですが、運用に問題はないのでしょうか？");
card(s, 0.6, 2.35, 5.9, 4.5); tag(s, "事実", 0.85, 2.55);
text(s, "今の計算でわかること", { x: 1.9, y: 2.5, w: 4.4, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, ["電気バスの消費は「走行距離×平均の電費」。気温や冷暖房の季節変化は入れていない（計算設定 distance_average_v0、記録で確認）",
  "そのため、冷暖房を強くした場合の結果は、まだ計算していない",
  "400 kW では、どの季節も受電の最大値が上限ちょうど。上限に余裕はない",
  `一方、太陽光は週に${fmt(fl(Math.min(...curt), 100))}〜${fmt(cl(Math.max(...curt), 100))} kWh が捨てられている（400 kW）`],
  { x: 0.85, y: 3.1, w: 5.4, h: 3.65, fontSize: 14 });
card(s, 6.8, 2.35, 5.9, 4.5, AMBER_PALE); tag(s, "見通し", 7.05, 2.55);
text(s, "消費が増えたときの4つの道と確かめ方", { x: 8.1, y: 2.5, w: 4.5, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, ["① 充電の時間を広げる（夜、昼の太陽光の時間）", "② 受電上限を上げる → 基本料金が増える", "③ 一部の便を燃料バスに回す → CO₂が増える", "④ 上限を超える → 超過の費用",
  "捨てている太陽光を昼に使えれば、受電を増やさずに済む可能性がある（蓄電池の最適化＝柱B）",
  "確かめ方：電費を＋10%・＋20%にした計算（感度分析）で、上限・燃料バス・CO₂の変化を示す"],
  { x: 7.05, y: 3.1, w: 5.4, h: 3.65, fontSize: 14 });
s.addNotes("今の計算では、電気バスの消費は走行距離に平均の電費をかけたもので、季節の冷暖房の増減は入れていません。プログラムの設定と記録で確かめました。ですので、冷暖房を強くした場合の結果は、まだ出ていません。400 kWではどの季節も受電の最大値が上限ちょうどなので、消費が増えると、充電の時間を広げる、上限を上げる、燃料バスに回す、上限を超える、のどれかになると考えています。一方、太陽光は毎週4,000〜5,000 kWh台が捨てられているので、昼に充電できれば受電を増やさずに済むかもしれません。電費を10%、20%増やした計算で確かめる予定です。");

// ---- 8. Q3 / Q4 society and people
s = page("Q3・Q4. 社会の課題と、人の視点を入れた最適化");
card(s, 0.6, 1.5, 5.9, 5.35, AMBER_PALE); tag(s, "見通し", 0.85, 1.7);
text(s, "Q3. 無人バスなどの技術で改善できるか", { x: 1.9, y: 1.62, w: 4.5, h: 0.5, fontSize: 16, bold: true, color: BLUE_DARK, valign: "middle" });
text(s, "（11枚目、西山先生のご意見のうち運転士不足について）", { x: 0.85, y: 2.2, w: 5.4, h: 0.35, fontSize: 12, color: SUB });
bullets(s, ["自動運転が広がれば、「運転士が何人・何時間まで乗れるか」という制約は軽くなる。遠隔で見守る人や車内の案内の役割は残る",
  "今のモデルが決めるのは「どの車両がどの便を走るか」で、運転士の勤務は入れていない。運転士の制約を入れた場合と、入れない場合（無人を想定）を比べられる（柱Cの候補）",
  "無人バスの多くは電動なので、充電の計画（柱A・B）はそのまま関係する",
  "冷暖房の増加や、バスを移動以外にも使う話は、技術だけでは解けない。東急バスへの聞き取りで確かめたい"],
  { x: 0.85, y: 2.6, w: 5.4, h: 4.15, fontSize: 13 });
card(s, 6.8, 1.5, 5.9, 5.35, AMBER_PALE); tag(s, "見通し", 7.05, 1.7);
text(s, "Q4. 人の気持ちを考えるとは", { x: 8.1, y: 1.62, w: 4.5, h: 0.5, fontSize: 16, bold: true, color: BLUE_DARK, valign: "middle" });
text(s, "効率を捨てるのではなく、何を「効率」とするかに、利用者・事業者の視点を入れる", { x: 7.05, y: 2.2, w: 5.4, h: 0.75, fontSize: 14, bold: true });
bullets(s, ["今の目的は「1週間の費用を最小」。運転士の勤務のしやすさ、待ち時間、車内の快適さ、遅れへの強さは入っていない",
  "入れ方は2つ。① 制約にする（例：運転士の拘束時間は○時間以内）。② 費用とは別の評価軸にして、「費用が○万円増える代わりに待ち時間が○分減る」と並べる",
  "どの案を選ぶかは、バス会社や利用者が決めること。計算の役割は、選べる案とその代償をはっきり示すこと"],
  { x: 7.05, y: 3.0, w: 5.4, h: 3.75, fontSize: 13 });
s.addNotes("3番目と4番目は、まだ計算していない考え方の話です。無人バスが広がれば運転士の制約は軽くなりますが、今のモデルはそもそも運転士の勤務を入れていません。入れた場合と入れない場合を比べるのは、柱Cの候補になります。4番目は、効率を捨てるという意味ではありません。何を効率とみなすかに、利用者や事業者の視点を入れるという意味です。制約として入れるか、費用とは別の軸にして、費用とのトレードオフとして並べるか、の2つのやり方があります。最終的に選ぶのはバス会社や利用者で、計算はその材料を示す役割だと考えています。");

// ---- 9. What changed in the poster and what remains
s = page("ポスターに反映したことと、これからの課題");
card(s, 0.6, 1.5, 5.9, 4.95);
text(s, "中間発表ポスターに反映したこと", { x: 0.85, y: 1.6, w: 5.4, h: 0.5, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, ["表2：「季節は代表1週ずつ（秋は春で代表）」（Q1）",
  "図4：「電力量料金は日射の少ない冬が大きい」（Q2）",
  "注：「季節は代表1週ずつ・各1回の計算で、季節差の統計的な有意性は確かめていない」（Q2）",
  "注：「電費は距離×平均の値で、冷暖房の季節変化は入れていない」（Q6）",
  "電気料金の式はポスターに載せてある。計算例（Q5）は当日の質問への答えとして準備した"],
  { x: 0.85, y: 2.2, w: 5.4, h: 4.15, fontSize: 14 });
card(s, 6.8, 1.5, 5.9, 4.95, AMBER_PALE);
text(s, "これからの課題（いただいたご質問から）", { x: 7.05, y: 1.6, w: 5.4, h: 0.5, fontSize: 18, bold: true, color: BLUE_DARK });
s.addTable([[H("課題"), H("関係するご質問"), H("柱")],
  ["季節ごとに複数の週・乱数で計算し、季節差を確かめる", "Q2", "A"],
  ["電費を＋10%・＋20%にした感度計算（冷暖房）", "Q6", "A・B"],
  ["蓄電池の最適化で、捨てている太陽光を使う", "Q2・Q6", "B"],
  ["運転士の制約と、費用以外の評価軸", "Q3・Q4", "C"]],
  tableOpts({ x: 7.05, y: 2.25, w: 5.4, colW: [3.3, 1.3, 0.8], fontSize: 12, rowH: [0.4, 0.68, 0.68, 0.68, 0.55] }));
caption(s, "いつ行うかは、先生とご相談して決めます。", 7.05, 5.9, 5.4, 0.35);
caption(s, DIAG, 0.6, 6.55, 12.1);
s.addNotes("いただいたご質問を受けて、中間発表のポスターも直しました。秋は春で代表させていること、季節の差を統計的には確かめていないこと、冷暖房を入れていないことを、表や注に書きました。これからの課題としては、季節ごとに複数の週で確かめること、電費を増やした感度計算、蓄電池の最適化、運転士の制約などがあります。ご質問ありがとうございました。");

(async () => {
  const out = path.join(__dirname, "研究室からのご質問への回答_20261120.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
