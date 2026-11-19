// Lab monthly progress report for junior lab members (2026-11-19), written in plain words.
// Content = this month's work as recorded in this repository:
//  - rc42 (19dc0780): 48 runs (2 tariffs x 12 cases x 2 initial assignments), all VERIFIED; figures use tariff A
//    (17.43 JPY/kWh + basic charge), the user's choice for the poster (variant a, 2026-11-19); numbers are DIAGNOSTIC;
//  - midterm poster and Prof. Urabe's comments of 11/18 (type too small, abstract not needed, author line);
//  - consultation with Prof. Nishiyama (11/17 notes) and the plan for a Tokyu Bus hearing;
//  - next steps.
// All result numbers are computed here from ../2026-11-12_three_party/deck_data_rc42_et.json with the same reporting rule
// as the poster (build_poster_rc42.js): total = total_cost_fuel_consumed - CO2 kg x 1 JPY + weekly basic charge.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

// ---------------- data (tariff A, adopted solution per case)
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_rc42_et.json"), "utf8"));
if (D.tariff_series !== "et" || D.cases.length !== 12 || D.pairs.length !== 24 || [...D.cases, ...D.pairs].some((r) => r.status !== "VERIFIED"))
  throw new Error("rc42 tariff A data is not 12 cases / 24 runs, all VERIFIED");
const tc = (r) => r.total_cost_fuel_consumed - r.total_co2_kg + r.basic_charge_week_jpy;
const fuelOf = (r) => r.ice_fuel_consumed_l * 150;
D.cases.forEach((r) => { const p = r.vehicle_usage_cost + r.electricity_cost + r.contract_overage_cost + fuelOf(r) + r.basic_charge_week_jpy;
  if (Math.abs(p - tc(r)) > 1) throw new Error(`cost parts do not add up: ${r.case}`); });
const LIMITS = D.limits, SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (g, w) => D.cases.find((r) => r.grid_limit_kw === g && r.week === w);
const man = (v) => (v / 1e4).toFixed(1);
const best = SE.map(([w, n]) => { const rs = LIMITS.map((g) => get(g, w)).sort((a, b) => tc(a) - tc(b)); return { w, n, r: rs[0], worst: rs[rs.length - 1] }; });
if (!best.every((b) => b.worst.grid_limit_kw === 900)) throw new Error("900 kW is not the most expensive in every season");
if (best.find((b) => b.w === "2025-01-06").r.grid_limit_kw !== 400 || best.filter((b) => b.w !== "2025-01-06").some((b) => b.r.grid_limit_kw !== 200))
  throw new Error("cheapest limits changed; rewrite slides 7-8");
const w200 = get(200, "2025-01-06"), w90 = get(90, "2025-01-06");
const gapMin = Math.min(...best.map((b) => 0.05 * tc(b.r)));
const bevCases = D.cases.filter((r) => r.selected_start === "bev"), iceCases = D.cases.filter((r) => r.selected_start === "ice");
if (iceCases.length !== 1 || iceCases[0] !== get(90, "2025-01-06")) throw new Error("diesel-first cases changed; rewrite slide 6");
const rng = (a, d = 1) => `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const basic = Object.fromEntries(LIMITS.map((g) => [g, get(g, "2025-01-06").basic_charge_week_jpy]));
const avgAt = (g) => SE.reduce((a, [w]) => a + tc(get(g, w)), 0) / SE.length;
const p90b = D.pairs.find((x) => x.grid_limit_kw === 90 && x.week === "2025-01-06" && x.start === "bev");
const p90i = D.pairs.find((x) => x.grid_limit_kw === 90 && x.week === "2025-01-06" && x.start === "ice");

// ---------------- deck frame (same look as the November report decks)
const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2", ORANGE = "E08A00";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "研究室 月次進捗報告 2026年11月";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "研究室 月次進捗報告　2026年11月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });
const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 6, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const tableOpts = (o) => ({ fontSize: 14, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center" } });
const heading = (s, t, x, y, w) => text(s, t, { x, y, w, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK, valign: "middle" });
const ICON = (n) => {
  for (const d of ["../2026-11-28_midterm_poster/icons", "../2026-11-16_nishiyama_consult/icons", "../2026-11-17_nishiyama_feedback_report/icons"]) {
    const p = path.join(__dirname, d, `${n}.png`);
    if (fs.existsSync(p)) return p;
  }
  throw new Error("icon " + n);
};
const icon = (s, n, x, y, w, alt) => s.addImage({ path: ICON(n), x, y, w, h: w, altText: alt || n });
const card = (s, x, y, w, h, fill = BLUE_PALE) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: GRID, width: 0.75 } });
const chartBase = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 12, legendColor: INK, showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt" });
const DIAG = "数値は計算プログラムの版 rc42 による診断用（DIAGNOSTIC）の結果で、研究の結論にはまだ使っていません。";

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "研究室 月次進捗報告（2026年11月）", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "電気バスと燃料バスを一緒に使うとき、\nどう走らせて、いつ充電するか", { x: 0.9, y: 1.8, w: 11.5, h: 1.6, fontSize: 32, bold: true, valign: "bottom" });
text(s, "研究題目：GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", { x: 0.9, y: 3.5, w: 11.5, h: 0.5, fontSize: 16, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.15, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "電力システム研究室　修士1年　劉 承洋", { x: 0.9, y: 4.4, w: 11.5, h: 0.5, fontSize: 17, color: SUB });
["ebus", "dbus", "charger", "pv"].forEach((n, i) => icon(s, n, 8.6 + i * 1.0, 5.4, 0.85));
s.addNotes("研究室の月次報告です。今月は、計算のやり直しが全部終わったこと、中間発表のポスター、西山先生へのご相談の3つを中心に話します。専門的なところはなるべくかみくだいて説明します。");

// ---- 2. The research in one picture
s = page("研究をひとことで言うと");
const flow = [["ebus", "電気バス 35台"], ["dbus", "燃料バス 25台"], ["charger", "充電器 90 kW×10"], ["pv", "太陽光 1,000 kW"], ["grid", "電力会社から買う電気"]];
flow.forEach(([n, l], i) => { const x = 0.75 + i * 2.45; card(s, x, 1.6, 2.2, 2.0, "FFFFFF"); icon(s, n, x + 0.6, 1.75, 1.0); text(s, l, { x: x + 0.1, y: 2.85, w: 2.0, h: 0.6, fontSize: 14, align: "center", bold: true }); });
card(s, 0.6, 3.9, 12.1, 1.55, "DCEBF7");
text(s, [{ text: "計算で決めること　", options: { bold: true, color: BLUE_DARK } },
  { text: "1週間の時刻表（1,704便）を、どのバスが走るか。電気バスを、いつ・どれだけ充電するか。", options: { breakLine: true } },
  { text: "目標　", options: { bold: true, color: BLUE_DARK } }, { text: "時刻表どおりに全部の便を走らせたうえで、1週間の費用をいちばん安くする。" }],
  { x: 0.85, y: 4.0, w: 11.6, h: 1.35, fontSize: 17, valign: "middle" });
bullets(s, ["対象：東急バス 渋21〜23系統（弦巻営業所）。時刻表は公共交通オープンデータ（ODPT）",
  "営業所が電力会社から一度に受け取れる電力には上限（受電上限）がある。家のアンペア契約のようなもので、たくさんのバスを同時に充電すると超えてしまう。上限を90・200・400・900 kWの4通り、季節を冬・春・夏の3通りにして、12ケースを比べた"],
  { x: 0.6, y: 5.6, w: 12.1, h: 1.35, fontSize: 14 });
s.addNotes("一言で言うと、電気バスと燃料バスが混ざった営業所で、どのバスがどの便を走るか、電気バスをいつ充電するかを最適化で決める研究です。条件として、営業所が受け取れる電力の上限を4通り、季節を3通り変えて比べています。");

// ---- 3. Three pillars and where I am
s = page("研究の3本の柱と、いまの位置");
const hiA = { fill: { color: "DCEBF7" } };
s.addTable([
  [H("柱"), H("内容"), H("予定")],
  [{ text: "A", options: { bold: true, align: "center", ...hiA } }, { text: "受電上限と、電気バスの担当便・費用・CO₂（今月はここ）", options: { bold: true, color: BLUE_DARK, ...hiA } }, { text: "11/28 中間発表\n2027年3月 電気学会全国大会", options: hiA }],
  [{ text: "B", options: { bold: true, align: "center" } }, "1日ずつと数日まとめての計画の比較、蓄電池の使い方", "2027年度 学会発表\n2027年11月 修士2年中間発表"],
  [{ text: "C", options: { bold: true, align: "center" } }, "利用者・地域・事業者にとっての価値（都市生活学部の西山先生にご相談）", "2028年2月 修士最終発表"]],
  tableOpts({ x: 0.6, y: 1.6, w: 12.1, colW: [0.9, 7.0, 4.2], fontSize: 17, rowH: [0.55, 1.15, 1.15, 1.15] }));
caption(s, "柱Aは中間発表と電気学会全国大会、柱Bと柱Cは修士2年に向けて進めます。", 0.6, 6.0, 12.1);
s.addNotes("研究は3本の柱で進めています。今月は柱Aの計算と発表準備が中心でした。柱Cについては西山先生にご相談しました。");

// ---- 4. What I did this month
s = page("今月やったこと");
const DID = [
  ["plan", "計算をすべてやり直した", "条件をそろえて全48通りを計算し直し、すべてチェックを通った。電気料金2通り×12ケース×計算の出発点2通り（電気バス優先・燃料バス優先）"],
  ["power", "電気料金を2通りで比べた", "A：基本料金を別に払う料金、B：基本料金を使った分の単価に含めた料金。紙面が限られるので、ポスターにはAだけを載せる（占部先生のご助言）"],
  ["clipboard", "中間発表のポスターを作った", "占部先生の添削で、文字サイズを大きくし、概要を削って中身を絞った"],
  ["talk", "西山先生にご相談した", "都市生活学部の先生に、柱Cの方向性と、バス会社への聞き取りについて伺った"]];
DID.forEach(([n, h, t], i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.6;
  card(s, x, y, 5.95, 2.4);
  icon(s, n, x + 0.2, y + 0.2, 0.8);
  text(s, h, { x: x + 1.15, y: y + 0.2, w: 4.6, h: 0.8, fontSize: 19, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, t, { x: x + 0.25, y: y + 1.1, w: 5.45, h: 1.2, fontSize: 15 });
});
s.addNotes("今月やったことは4つです。1つ目は計算のやり直しで、48通りの計算が全部、検証を通りました。計算の出発点として、電気バスを優先する割り当てと燃料バスを優先する割り当ての2通りから始め、安かった方を使っています。2つ目は電気料金の扱いを2通りで比べたことで、くわしくは次のページで説明します。3つ目は中間発表のポスター、4つ目は西山先生へのご相談です。");

// ---- 5. How the electricity bill works (plain words)
s = page("電気代のしくみ（料金A）");
text(s, "電気代は、3つの部分の足し算です。スマホの料金で言うと「使った分」と「基本料金」に近いです。", { x: 0.6, y: 1.5, w: 12.1, h: 0.5, fontSize: 17 });
const PARTS = [
  ["grid", "使った分", "電力量料金", "買った電力量 × 17.43円/kWh", "7AB8E8"],
  ["calendar", "契約で決まる分", "基本料金", "受電上限 × 2,530円/kW・月 × 0.85\n（0.85は力率割引。使わなくても毎月かかる）", BLUE_DARK],
  ["power", "上限を超えた分", "上限超過の費用", "超えた電力量 × 500円/kWh\n（計算上の仮のペナルティ）", ORANGE]];
PARTS.forEach(([n, h, k, f, col], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 2.2, 3.9, 3.3, "FFFFFF");
  s.addShape(pres.shapes.RECTANGLE, { x, y: 2.2, w: 3.9, h: 0.12, fill: { color: col }, line: { color: col } });
  icon(s, n, x + 0.2, 2.5, 0.75);
  text(s, h, { x: x + 1.1, y: 2.5, w: 2.7, h: 0.75, fontSize: 18, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, k, { x: x + 0.25, y: 3.4, w: 3.4, h: 0.4, fontSize: 15, bold: true });
  text(s, f, { x: x + 0.25, y: 3.85, w: 3.4, h: 1.5, fontSize: 15 });
  if (i < 2) text(s, "＋", { x: x + 3.9, y: 3.4, w: 0.2, h: 0.6, fontSize: 24, bold: true, color: GREY, align: "center" });
});
card(s, 0.6, 5.7, 12.1, 1.1, "F4F7FA");
text(s, [{ text: "ポイント　", options: { bold: true, color: BLUE_DARK } },
  { text: `基本料金は受電上限に比例します。1週間あたり、90 kWで約${man(basic[90])}万円、900 kWで約${man(basic[900])}万円。受電上限を大きくすると、使わなくても基本料金が増えます。` }],
  { x: 0.85, y: 5.75, w: 11.6, h: 1.0, fontSize: 15, valign: "middle" });
s.addNotes("電気代の説明です。料金Aでは、使った電力量に応じた料金と、契約の大きさで決まる基本料金、上限を超えたときの費用の3つを足しています。基本料金は月額を週に換算していて、0.85は力率割引です。ここが今月の結果を理解するうえでいちばん大事なポイントです。料金Bは30円/kWhに基本料金が含まれている扱いなので、基本料金の項はありません。");

// ---- 6. Result 1: electric buses can run most trips
s = page("結果①：電気バスは、ほとんどの便を担当できた");
const cats = LIMITS.map((g) => `${g} kW`);
s.addChart(pres.charts.BAR, SE.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  { ...chartBase(), x: 0.6, y: 1.5, w: 6.6, h: 4.7, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便の割合 [%]", valAxisTitleFontSize: 12, valAxisTitleColor: SUB,
    showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 12, catAxisTitleColor: SUB });
caption(s, "全1,704便/週のうち電気バスが担当した割合（料金A。電気バス優先・燃料バス優先の2通りの出発点から計算し、安かった方の結果）", 0.6, 6.25, 6.6, 0.6);
// call-out on the 90 kW winter bar (left-most group)
text(s, `${Math.round(iceCases[0].bev_trip_share_pct)}%`, { x: 1.62, y: 4.22, w: 0.45, h: 0.35, fontSize: 14, bold: true, color: ORANGE, align: "center" });
card(s, 7.5, 1.6, 5.2, 4.6);
bullets(s, [`12ケース中${bevCases.length}ケースで、電気バスが${rng(bevCases.map((r) => r.bev_trip_share_pct))}%の便を担当した`,
  `例外は冬の90 kWだけ。電力が足りず、燃料バスを多く使う方が安くなった（電気バスは${Math.round(iceCases[0].bev_trip_share_pct)}%）`,
  `ただし冬の90 kWで燃料バスを多く使うと、CO₂は電気バス中心の約${(p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1)}倍になる`],
  { x: 7.75, y: 1.85, w: 4.75, h: 4.2, fontSize: 16, paraSpaceAfter: 10 });
caption(s, DIAG, 7.5, 6.3, 5.2, 0.6);
s.addNotes("1つ目の結果です。受電上限が200 kW以上なら、季節にかかわらず電気バスが9割以上の便を担当できました。冬の90 kWだけは電力が足りず、燃料バス中心の方が安くなりましたが、CO₂は3倍以上になります。");

// ---- 7. Result 2: a higher limit is not cheaper
s = page("結果②：受電上限が大きいほど安い、とは限らない");
const rows5 = SE.flatMap(([w, n]) => LIMITS.map((g) => ({ r: get(g, w), l: `${g}${n}` })));
const u = (v) => Math.round(v / 1e3) / 10;
s.addChart(pres.charts.BAR, [
  { name: "電力量料金", labels: rows5.map((x) => x.l), values: rows5.map((x) => u(x.r.electricity_cost)) },
  { name: "基本料金", labels: rows5.map((x) => x.l), values: rows5.map((x) => u(x.r.basic_charge_week_jpy)) },
  { name: "燃料代", labels: rows5.map((x) => x.l), values: rows5.map((x) => u(fuelOf(x.r))) },
  { name: "上限超過", labels: rows5.map((x) => x.l), values: rows5.map((x) => u(x.r.contract_overage_cost)) }],
  { ...chartBase(), x: 0.6, y: 1.5, w: 7.3, h: 4.75, barDir: "col", barGrouping: "stacked", barGapWidthPct: 45, chartColors: ["7AB8E8", BLUE_DARK, GREY, ORANGE],
    catAxisLabelFontSize: 10, valAxisMinVal: 0, valAxisMaxVal: 60, valAxisMajorUnit: 10, showValAxisTitle: true, valAxisTitle: "万円/週", valAxisTitleFontSize: 12, valAxisTitleColor: SUB });
const vR = D.cases.map((r) => r.vehicle_usage_cost / 1e4);
caption(s, `費用の内訳（料金A、1週間）。どのケースでもほぼ同じ車両使用費（${Math.min(...vR).toFixed(0)}〜${Math.max(...vR).toFixed(0)}万円/週）を除き、差が出る部分だけを拡大しています。右の表は車両使用費を含む総額です`, 0.6, 6.25, 7.3, 0.7);
s.addTable([[H("受電上限"), ...SE.map(([, n]) => H(n))],
  ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SE.map(([w]) => {
    const r = get(g, w), b = best.find((x) => x.w === w).r === r;
    return { text: man(tc(r)), options: { align: "center", bold: b, color: b ? BLUE_DARK : INK, fill: b ? { color: "DCEBF7" } : undefined } }; })])],
  tableOpts({ x: 8.2, y: 1.6, w: 4.5, colW: [1.35, 1.05, 1.05, 1.05], fontSize: 14, rowH: 0.48 }));
caption(s, "1週間の総費用［万円］（車両使用費を含む。CO₂の費用は含めない）。青が各季節でいちばん安い", 8.2, 4.1, 4.5, 0.6);
card(s, 8.2, 4.72, 4.5, 1.3, "F4F7FA");
text(s, [{ text: "グラフの見るところ", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: `濃い青（基本料金）：900 kWで約${man(basic[900])}万円/週と大きい`, options: { bullet: { indent: 14 }, breakLine: true } },
  { text: "オレンジ（上限超過）：上限が小さいときだけ出る", options: { bullet: { indent: 14 } } }], { x: 8.35, y: 4.75, w: 4.2, h: 1.24, fontSize: 13, valign: "middle" });
caption(s, "数値は rc42 の診断用（DIAGNOSTIC）で、研究の結論にはまだ使っていません。", 8.2, 6.1, 4.5, 0.75);
s.addNotes("2つ目の結果で、今月いちばん面白かったところです。受電上限を大きくすれば電気が自由に使えるので安くなりそうですが、実際には900 kWがどの季節でもいちばん高くなりました。右の表は総額で400万円台ですが、左のグラフはどのケースでもほぼ同じ車両使用費を除いて、差が出る部分だけを拡大しています。まず冬の4本を見てください。濃い青が基本料金で、上限に比例して増えています。オレンジは上限を超えた費用で、上限が小さいときだけ出ます。電力量料金や燃料代は、上限が足りていればほとんど変わりません。");

// ---- 8. Discussion: the right-sized limit
s = page("考察：ちょうどよい受電上限がある");
const ZONES = [
  ["小さすぎる", `冬の200 kWでは上限を${Math.round(w200.contract_over_limit_kwh)} kWh超え、超過の費用が約${man(w200.contract_overage_cost)}万円/週。冬の90 kWでは燃料バスが増える`, "F4F7FA", INK],
  ["ちょうどよい", "冬は400 kW、春と夏は200 kWで総費用がいちばん安い。電気バスも9割以上の便を担当できる", "DCEBF7", BLUE_DARK],
  ["大きすぎる", `電力量料金や燃料代はほとんど下がらないのに、基本料金だけが増える（900 kWで約${man(basic[900])}万円/週）`, "F4F7FA", INK]];
ZONES.forEach(([h, t, fill, col], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 1.6, 3.9, 2.9, fill);
  text(s, h, { x: x + 0.25, y: 1.75, w: 3.4, h: 0.6, fontSize: 20, bold: true, color: col });
  text(s, t, { x: x + 0.25, y: 2.45, w: 3.4, h: 1.95, fontSize: 15 });
  if (i < 2) text(s, "→", { x: x + 3.9, y: 2.75, w: 0.2, h: 0.5, fontSize: 18, color: GREY, align: "center" });
});
heading(s, "運用の目安（今回の条件で）", 0.6, 4.7, 12.1);
bullets(s, [`受電上限は大きく取りすぎない：充電の時間をずらせば冬も400 kWで足り、900 kWより約${man(avgAt(900) - avgAt(400))}万円/週安い（3季節平均）`,
  `200 kWと400 kWの差は言い切れない：今の答えと「理論上これ以上安くならない値」との差を5%まで許して計算を止めている（ギャップ、約${man(gapMin)}万円/週）。差がそれより小さい`,
  "次の課題：いまは基本料金を後から足しているだけ。受電上限そのものも計算で決められるようにする"],
  { x: 0.6, y: 5.15, w: 12.1, h: 1.8, fontSize: 14, paraSpaceAfter: 4 });
s.addNotes("考察です。受電上限は、小さすぎると超過や燃料バスが増え、大きすぎると基本料金だけが増えます。今回の条件では、冬は400 kW、春と夏は200 kWがちょうどよいという結果でした。ただ、200 kWと400 kWの差は言い切れません。計算は、今の答えと理論上これ以上安くならない値との差が5%以内になったら止めているので、それより小さい差は、もっと計算すれば入れ替わるかもしれないからです。基本料金を最初から計算に入れて、上限も一緒に決めるのが次の課題です。");

// ---- 8b. Objective before the time limit (Prof. Urabe's Slack reply, 2026-11-19; tariff A, adopted solutions)
// Data: ../2026-11-12_three_party/cutoff_trajectory_rc42_et.json (prepare_cutoff_trajectory_rc42.py, from the Gurobi logs
// and the Stage 1 LNS record of each rc42 run). Same derivation as the poster's fig. 6.
{
  const CUT = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "cutoff_trajectory_rc42_et.json"), "utf8"));
  const runs = CUT.runs.filter((r) => get(r.grid_limit_kw, r.week).selected_start === r.start);
  if (runs.length !== 12) throw new Error("expected 12 adopted runs");
  const med = (a) => { const b = [...a].sort((x, y) => x - y), n = b.length; return n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2; };
  const exc = (r, m) => { const tr = r.stage1.trajectory_sec_objective, fin = r.stage1.best_objective;
    const cur = tr.filter(([t]) => t <= m * 60); return ((cur.length ? cur[cur.length - 1][1] : tr[0][1]) - fin) / fin * 100; };
  const MINS = Array.from({ length: 31 }, (_, i) => i * 5), r2 = (v) => Math.round(v * 100) / 100;
  const HL = runs.flatMap((r) => r.hourly.time_limited_steps);
  const SECS = Array.from({ length: 31 }, (_, i) => i * 10);
  const pct = (f) => SECS.map((t) => Math.round(HL.filter((h) => f(h) !== null && f(h) <= t).length / HL.length * 1000) / 10);
  const late30 = Math.max(...runs.map((r) => exc(r, r.stage1.elapsed_sec / 60 - 30)));
  const by240 = HL.filter((h) => h.t_final_incumbent_s <= 240).length, gapMed = med(HL.map((h) => h.final_gap_pct));
  const tlRuns = runs.filter((r) => r.hourly.time_limit_steps > 0).map((r) => `${r.grid_limit_kw} kW${SE.find(([w]) => w === r.week)[1]} ${r.hourly.time_limit_steps}回`);
  s = page("計算を時間で打ち切ったとき、目的関数はどう減っていたか");
  text(s, "占部先生から「打ち切り前に目的関数（費用）がどう減っていたか分かるか」と質問をいただき、計算ソフトの記録から取り出しました（料金A、採用した解）。",
    { x: 0.6, y: 1.45, w: 12.1, h: 0.6, fontSize: 15 });
  const lo = { ...chartBase(), y: 2.15, w: 5.9, h: 3.2, lineDataSymbol: "none", lineSize: 2, showCatAxisTitle: true, catAxisTitleFontSize: 11, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitleFontSize: 11, valAxisTitleColor: SUB, catAxisLabelFrequency: 6 };
  s.addChart(pres.charts.LINE, [{ name: "中央値", labels: MINS.map(String), values: MINS.map((m) => r2(med(runs.map((r) => exc(r, m))))) },
    { name: "最大", labels: MINS.map(String), values: MINS.map((m) => r2(Math.max(...runs.map((r) => exc(r, m))))) }],
    { ...lo, x: 0.6, chartColors: [BLUE_DARK, GREY], valAxisMinVal: 0, valAxisTitle: "最終の値との差 [%]", catAxisTitle: "便割当の探索時間 [分]" });
  s.addChart(pres.charts.LINE, [{ name: "解が見つかっていた", labels: SECS.map(String), values: pct((h) => h.t_first_incumbent_s) },
    { name: "最終の解が見つかっていた", labels: SECS.map(String), values: pct((h) => h.t_final_incumbent_s) }],
    { ...lo, x: 6.8, chartColors: ["7AB8E8", BLUE_DARK], valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 25, valAxisTitle: "割合 [%]", catAxisTitle: "毎時の再計画の計算時間 [秒]" });
  caption(s, `左：1週間の便割当（${Math.round(runs[0].stage1.time_budget_sec).toLocaleString("en-US")}秒で打ち切り）。12ケースの目的関数が最後の値よりどれだけ高かったか`, 0.6, 5.4, 5.9, 0.6);
  caption(s, `右：毎時の再計画（300秒で打ち切り）で時間切れの${HL.length}回。${tlRuns.join("・")}`, 6.8, 5.4, 5.9, 0.6);
  card(s, 0.6, 6.05, 12.1, 0.85, "DCEBF7");
  text(s, `打ち切る前に、ほぼ下げ止まっていた：便割当は最後の30分で${late30.toFixed(2)}%以下しか下がらず、再計画は${HL.length}回中${by240}回が240秒までに最終の解に着いた。ただし下限との差（ギャップ、中央値${Math.round(gapMed)}%）は残るので、最適とは言えない。`,
    { x: 0.8, y: 6.08, w: 11.7, h: 0.8, fontSize: 13.5, valign: "middle" });
  s.addNotes("占部先生からの質問への答えです。左は1週間の便割当で、9,000秒の上限で止まっていますが、目的関数は始めの30分ほどで大きく下がり、最後の30分はほとんど変わっていません。右は1時間ごとの再計画で、300秒で打ち切られた回のうち、どの時点で最終の解が見つかっていたかの割合です。多くは早い段階で最終の解が見つかっていました。ただ、下限との差であるギャップは大きいままなので、これで最適だとは言えません。");
}

// ---- 9. What I learned (tips for juniors)
s = page("今月学んだこと（後輩のみなさんへ）");
const TIPS = [
  ["clipboard", "ポスターは文字を大きく", "A0のポスターでは、本文は30pt以上が目安。占部先生から、まず文字サイズを適切にしてから、書ける分量を考えるようにとご指導いただいた"],
  ["check", "概要は要らないこともある", "ポスター自体が要約なので、タイトルの下の長い概要は削った。文章より図で見せる"],
  ["talk", "計算結果だけでは伝わらない", "西山先生から「計算の結果だけでは、バス会社としても受け入れにくい」とのご意見。利用者や運用者の視点も入れる"],
  ["plan", "数値の状態を正直に書く", "まだ研究の結論に使えない数値は「診断用」と書き、打ち切りの幅（ギャップ）より小さい差は言い切らない"]];
TIPS.forEach(([n, h, t], i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.6;
  card(s, x, y, 5.95, 2.4);
  icon(s, n, x + 0.2, y + 0.2, 0.8);
  text(s, h, { x: x + 1.15, y: y + 0.2, w: 4.6, h: 0.8, fontSize: 19, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, t, { x: x + 0.25, y: y + 1.1, w: 5.45, h: 1.2, fontSize: 15 });
});
s.addNotes("今月、資料づくりや相談で学んだことを4つ共有します。ポスターの文字サイズ、概要の要否、計算結果だけでは現場に伝わらないこと、数値の状態を正直に書くこと、です。みなさんの発表準備にも役立てばうれしいです。");

// ---- 10. Next steps
s = page("これからの予定");
const STEPS = [["2026年11月", "中間発表", "11/28に、料金Aの結果でポスター発表"], ["2027年3月", "電気学会全国大会", "柱Aの内容で講演。講演論文集（冊子）ができたら、それを持って東急バスに聞き取りに伺いたい"],
  ["2027年度（修士2年）", "柱Bの研究", "基本料金を含めて受電上限を決める、蓄電池の使い方の最適化、数日まとめての計画"], ["2028年2月まで", "柱Cと修士論文", "利用者・地域・事業者の視点を、計算の条件や評価に入れる。2028年2月に修士最終発表"]];
STEPS.forEach(([when, h, t], i) => {
  const x = 0.6 + i * 3.08;
  s.addShape(pres.shapes.OVAL, { x: x + 1.15, y: 1.65, w: 0.5, h: 0.5, fill: { color: i === 0 ? BLUE : "FFFFFF" }, line: { color: BLUE, width: 2 } });
  if (i < 3) s.addShape(pres.shapes.LINE, { x: x + 1.7, y: 1.9, w: 2.53, h: 0, line: { color: BLUE, width: 2 } });
  text(s, when, { x, y: 2.3, w: 2.8, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK, align: "center" });
  card(s, x, 2.85, 2.8, 3.1, i === 0 ? "DCEBF7" : BLUE_PALE);
  text(s, h, { x: x + 0.15, y: 3.0, w: 2.5, h: 0.5, fontSize: 17, bold: true, align: "center" });
  text(s, t, { x: x + 0.2, y: 3.6, w: 2.4, h: 2.25, fontSize: 14 });
});
text(s, "ご質問やアドバイスがあれば、気軽に声をかけてください。", { x: 0.6, y: 6.25, w: 12.1, h: 0.5, fontSize: 17, bold: true, color: BLUE_DARK });
s.addNotes("最後に今後の予定です。まず11月28日の中間発表、次に3月の電気学会全国大会です。全国大会の講演論文集ができたら、それを持って東急バスへ聞き取りに伺いたいと考えています。そのあと柱Bと柱Cに進みます。以上です。");

(async () => {
  const out = path.join(__dirname, "研究室月次進捗報告_202611_劉.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
