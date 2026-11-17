// Consultation material for the advisor (2026-11-18): rc42 (19dc0780) pillar A results under the two electricity
// tariff treatments, to decide which one the 11/28 poster shows. User decision 2026-11-18: keep both result sets,
// decide with the advisor. Every number is read from ../2026-11-12_three_party/deck_data_rc42_{et,ct}.json
// (prepare_deck_data_rc42.py; verified runs only). DIAGNOSTIC: not used for research conclusions.
// Cost basis = the poster's: executed-day accounting with diesel valued by litres burnt, CO2 cost (1 JPY/kg) excluded;
// et adds the weekly basic charge as a constant.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const load = (s) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", `deck_data_rc42_${s}.json`), "utf8"));
const D = { et: load("et"), ct: load("ct") };
const tc = (r) => r.total_cost_fuel_consumed - r.total_co2_kg + r.basic_charge_week_jpy;
const otc = (r) => r.other_start_total_cost_fuel_consumed - r.other_start_total_co2_kg + r.basic_charge_week_jpy;
for (const s of ["et", "ct"]) {
  if (D[s].cases.some((r) => r.status !== "VERIFIED") || D[s].pairs.some((r) => r.status !== "VERIFIED")) throw new Error(`${s}: unverified case`);
}
const LIMITS = D.et.limits, SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (s, g, w) => D[s].cases.find((r) => r.grid_limit_kw === g && r.week === w);
const man = (v) => (v / 1e4).toFixed(1);
const lab = (r) => `${r.grid_limit_kw} kW ${SE.find(([w]) => w === r.week)[1]}`;
const iceWins = (s) => D[s].cases.filter((r) => r.selected_start === "ice");
const range = (a, d = 1) => `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const maxTL = (rows) => Math.max(...rows.map((r) => r.rolling_time_limit_steps));
const veh = [...D.et.cases, ...D.ct.cases].map((r) => r.vehicle_usage_cost / 1e4);

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2", ORANGE = "C0661A";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "電気料金の2通りの扱いによる結果の比較 2026-11";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "2026年11月　劉 承洋　（数値はすべて診断用 DIAGNOSTIC）", options: { x: 0.6, y: 7.05, w: 9, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });
const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 6, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const H = (t, o = {}) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center", valign: "middle", ...o } });
const heading = (s, t, x, y, w) => text(s, t, { x, y, w, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK, valign: "middle" });
const card = (s, x, y, w, h, fill = BLUE_PALE) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: GRID, width: 0.75 } });
const cell = (t, o = {}) => ({ text: t, options: { valign: "middle", ...o } });

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "中間発表ポスターについてのご相談", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "電気料金の2通りの扱いで\n計算し直した結果の比較", { x: 0.9, y: 1.8, w: 11.5, h: 1.6, fontSize: 34, bold: true, valign: "bottom" });
text(s, "どちらをポスターの主な結果にするか", { x: 0.9, y: 3.5, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.2, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年11月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.45, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- 2. The two treatments
s = page("2通りの電気料金の扱いと、共通の条件");
s.addTable([
  [H(""), H("A：電力量料金＋基本料金"), H("B：30円/kWh（基本料金込み）")],
  [cell("最適化で使う電気の単価", { bold: true }), cell("17.43円/kWh（東京電力EP 高圧）"), cell("30円/kWh")],
  [cell("基本料金", { bold: true }), cell(`結果に定数で加える（受電上限で決まる。1週間あたり 90 kW ${man(44664)}万円、200 kW ${man(99254)}万円、400 kW ${man(198508)}万円、900 kW ${man(446642)}万円）`), cell("単価に含まれているとみなし、加えない")],
  [cell("ねらい", { bold: true }), cell("実際の料金のしくみに近い"), cell("これまでの結果（旧版）と同じ扱い")]],
  { x: 0.6, y: 1.6, w: 12.1, colW: [2.9, 4.6, 4.6], fontSize: 15, color: INK, border: { type: "solid", pt: 0.75, color: GRID }, rowH: [0.45, 0.6, 1.0, 0.55] });
heading(s, "共通の条件（AとBで違うのは電気の単価と基本料金だけ）", 0.6, 4.55, 12.1);
bullets(s, [
  "同じ版（rc42）・同じ入力：受電上限 90／200／400／900 kW × 冬・春・夏の代表週 ＝ 12ケース。各ケースを「電気バス優先」「燃料バス優先」の2通りの初期割当から解き、総費用の安い方を採用（1系列24回、計48回）",
  "計算の打ち切りは全ケース共通：ギャップ5%、毎時の立て直し300秒/回",
  "総費用＝車両使用費＋電気代＋燃料代（使った軽油）＋上限超過の費用（＋Aでは基本料金）。CO₂の費用は含めない"],
  { x: 0.6, y: 5.05, w: 12.1, h: 1.9, fontSize: 15 });

// ---- 3. Results table
s = page("結果の一覧（各ケースで採用した解、1週間）");
const c3 = (r) => {
  const ice = r.selected_start === "ice", o = { align: "center", color: ice ? ORANGE : INK, bold: ice };
  return [cell(`${man(tc(r))}${ice ? "＊" : ""}`, o), cell(r.bev_trip_share_pct.toFixed(1), o), cell((r.total_co2_kg / 1e3).toFixed(2), o)];
};
const rows = [];
LIMITS.forEach((g) => SE.forEach(([w, n]) => rows.push([cell(`${g} kW`, { bold: true, align: "center" }), cell(n, { align: "center" }), ...c3(get("et", g, w)), ...c3(get("ct", g, w))])));
const cw = [1.3, 0.9, 1.75, 1.95, 1.3, 1.75, 1.95, 1.3], cws = cw.reduce((a, b) => a + b);
s.addTable([
  [H("受電上限", { rowspan: 2 }), H("季節", { rowspan: 2 }), H("A：電力量料金＋基本料金", { colspan: 3 }), H("B：30円/kWh", { colspan: 3 })],
  [H("総費用［万円］"), H("電気バス便［%］"), H("CO₂［t］"), H("総費用［万円］"), H("電気バス便［%］"), H("CO₂［t］")],
  ...rows],
  { x: 0.6, y: 1.5, w: 12.1, colW: cw.map((v) => v * 12.1 / cws), fontSize: 13, color: INK, border: { type: "solid", pt: 0.75, color: GRID }, rowH: 0.33 });
caption(s, "＊（橙）は燃料バス優先の初期割当から得た解が安かったケース。総費用は車両使用費・電気代・燃料代（使った軽油）・超過費用の合計で、Aは基本料金を含む。CO₂の費用は含めない", 0.6, 6.5, 12.1, 0.45);

// ---- 4. Chart of the BEV share
s = page("電気バスの担当便：違いは上限の低い冬だけ");
const cats = []; LIMITS.forEach((g) => SE.forEach(([, n]) => cats.push(`${g}${n}`)));
const series = (k) => { const v = []; LIMITS.forEach((g) => SE.forEach(([w]) => v.push(Math.round(get(k, g, w).bev_trip_share_pct * 10) / 10))); return v; };
s.addChart(pres.charts.BAR, [{ name: "A：電力量料金＋基本料金", labels: cats, values: series("et") }, { name: "B：30円/kWh", labels: cats, values: series("ct") }],
  { x: 0.6, y: 1.5, w: 7.6, h: 5.0, barDir: "col", barGrouping: "clustered", barGapWidthPct: 50, chartColors: [BLUE_DARK, GREY],
    showLegend: true, legendPos: "t", legendFontSize: 13, legendFontFace: "+mn-lt", catAxisLabelFontSize: 12, valAxisLabelFontSize: 12,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisLabelColor: SUB, valAxisLabelColor: SUB,
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
    showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 12, valAxisTitleColor: SUB, valAxisTitleFontFace: "+mn-lt",
    showCatAxisTitle: true, catAxisTitle: "受電上限 [kW]・季節", catAxisTitleFontSize: 12, catAxisTitleColor: SUB, catAxisTitleFontFace: "+mn-lt" });
const iceA = iceWins("et"), iceB = iceWins("ct");
card(s, 8.5, 1.55, 4.2, 4.95);
text(s, [
  { text: "燃料バス優先の解が安かったケース", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: `A：${iceA.map(lab).join("・")}（電気バス ${iceA.map((r) => r.bev_trip_share_pct.toFixed(1)).join("・")}%）`, options: { breakLine: true } },
  { text: `B：${iceB.map(lab).join("・")}（電気バス ${iceB.map((r) => r.bev_trip_share_pct.toFixed(1)).join("・")}%）`, options: { breakLine: true } },
  { text: " ", options: { breakLine: true, fontSize: 8 } },
  { text: "それ以外のケース", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: `A・Bとも電気バスが ${range([...D.et.cases, ...D.ct.cases].filter((r) => r.selected_start === "bev").map((r) => r.bev_trip_share_pct))}% を担当` }],
  { x: 8.75, y: 1.75, w: 3.75, h: 4.6, fontSize: 15, paraSpaceAfter: 4 });
caption(s, "各ケースで採用した解（2通りの初期割当のうち総費用の安い方）", 0.6, 6.5, 7.6, 0.4);

// ---- 5. How to read the difference
s = page("違いの読み方");
const b200 = get("ct", 200, "2025-01-06"), a200 = get("et", 200, "2025-01-06");
const costsA900 = D.et.cases.filter((r) => r.grid_limit_kw === 900).map((r) => tc(r) / 1e4), costsAlow = D.et.cases.filter((r) => r.grid_limit_kw !== 900).map((r) => tc(r) / 1e4);
const costsBice = iceB.map((r) => tc(r) / 1e4), costsBbev = D.ct.cases.filter((r) => r.selected_start === "bev").map((r) => tc(r) / 1e4);
bullets(s, [
  `差が出たのは200 kW冬だけ：Bでは燃料バス優先の解が ${man(otc(b200) - tc(b200))}万円/週 安く、Aでは電気バス優先の解が ${man(otc(a200) - tc(a200))}万円/週 安かった。どちらの差も、計算を打ち切ったギャップ5%（約${(tc(b200) * 0.05 / 1e4).toFixed(0)}万円/週）より小さく、どちらの割当が本当に安いかは言い切れない`,
  `費用の水準：Aは基本料金を加えるので900 kWが最も高い（${range(costsA900)}万円/週、うち基本料金${man(446642)}万円）。90〜400 kWは${range(costsAlow)}万円/週。Bは燃料バスに寄った冬の2ケース（${range(costsBice)}万円/週）を除くと、上限によらず${range(costsBbev)}万円/週`,
  `総費用の大半は車両使用費（${range(veh)}万円/週）で、電気代・燃料代・超過費用の違いは数万〜数十万円/週`,
  "上限の低い冬に燃料バスへ寄るという傾向は、A・Bどちらでも同じ。どこまでの上限で燃料バスに寄るか（90 kWだけか、200 kWまでか）は、料金の扱いと割当の探索の打ち切りに左右される"],
  { x: 0.6, y: 1.6, w: 12.1, h: 5.2, fontSize: 17, paraSpaceAfter: 12 });

// ---- 6. The question
s = page("ご相談：ポスターにどちらを載せるか");
const opts = [
  ["案1　Aを主、Bを比較", "表1の料金はすでにAの書き方。実際の料金のしくみに近い。Bは「単価の感度」として一言か小さな表で示す"],
  ["案2　Bを主、Aを比較", "これまでの結果と同じ扱いで続けて説明できる。燃料バスへ寄る境目が200 kWまで広がって見える（ただし差はギャップ未満）"],
  ["案3　両方を並べる", "図3・図4をA・Bの2系列にする。紙面が足りないため、表3や図5を小さくする必要がある"]];
opts.forEach(([h, b], i) => {
  const y = 1.6 + i * 1.45;
  card(s, 0.6, y, 12.1, 1.3, i === 0 ? BLUE_PALE : "F7F7F7");
  text(s, [{ text: h, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: b }], { x: 0.85, y: y + 0.12, w: 11.6, h: 1.1, fontSize: 16 });
});
text(s, [{ text: "私の考え　", options: { bold: true, color: BLUE_DARK } },
  { text: "案1。電気料金を実際のしくみに近い形で扱い、30円/kWhでも結論が大きく変わらないことを感度として添えたい。" }],
  { x: 0.6, y: 6.05, w: 12.1, h: 0.8, fontSize: 16 });

// ---- 7. Notes and disclosures
s = page("補足：計算の経過と注意点");
bullets(s, [
  "48回すべてで、前日の計画と毎時の立て直し（174〜175回）が最後まで通り、物理的な検証も通った",
  "夏の3件（A：200 kW 電気バス優先、B：90 kW・900 kW 電気バス優先）は、最初の計算が前日の計画の段階でメモリの上限（14 GiB）を超えて止まった。モデルと入力は変えずに上限を24 GiBにして1回だけ計算し直し、その結果を使っている。Aの夏 90／400／900 kW 電気バス優先は、前の版で同じ止まり方をしたため最初から24 GiB",
  `毎時の立て直しが300秒で打ち切られた回は、1ケースで最大 A ${maxTL(D.et.pairs)}回・B ${maxTL(D.ct.pairs)}回（採用した解では最大 ${Math.max(maxTL(D.et.cases), maxTL(D.ct.cases))}回）。打ち切り時点のいちばん良い解で進めている`,
  "便割当は最適解と確かめられておらず、2段階で解くため全体としての最適解でもない。蓄電池は決めた規則で充放電し、最適化していない",
  "数値はすべて診断用（DIAGNOSTIC）で、研究の結論にはまだ用いない"],
  { x: 0.6, y: 1.6, w: 12.1, h: 5.3, fontSize: 16, paraSpaceAfter: 10 });

(async () => {
  const out = path.join(__dirname, "電気料金2通りの比較_ご相談.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
